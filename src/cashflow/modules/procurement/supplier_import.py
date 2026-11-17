"""นำเข้าผู้ขายจากไฟล์ Excel ที่ export จากระบบเดิม (ชีต "รายการ ผู้ผลิต" และ "เครดิต")

ขั้นตอน: parse_supplier_file → build_import_plan (แสดงตัวอย่าง) → apply_supplier_import
ไฟล์เป็นแหล่งข้อมูลหลักของช่องที่มีในไฟล์ ยกเว้นเครดิต: ถ้าไฟล์ไม่ระบุเครดิต
จะไม่ลบค่าที่ฝ่ายบัญชีกรอกไว้แล้วในระบบ
"""

import re
import uuid
from dataclasses import asdict, dataclass, field

from django.core.exceptions import PermissionDenied
from django.db import transaction

from cashflow.modules.audit.services import record_event
from cashflow.modules.identity.models import User

from .models import Supplier
from .policies import can_manage_suppliers
from .services import _create_supplier_record, _update_supplier_record
from .xlsx_reader import WorkbookError, read_workbook

SUPPLIER_SHEET = "รายการ ผู้ผลิต"
CREDIT_SHEET = "เครดิต"
CODE_HEADER = "รหัสผู้ผลิต"
NAME_HEADER = "ชื่อผู้ผลิต"
DESCRIPTION_HEADER = "รายละเอียด"
TYPE_HEADER = "ประเภท"
CREDIT_GROUP_HEADER = "กลุ่มผู้ผลิต"
INACTIVE_MARKER = "ยกเลิกซื้อขาย"
EMPTY_MARKERS = {"-", "—"}
CREDIT_PATTERN = re.compile(r"(?:เครดิต|ภายใน)\s*(\d+)\s*วัน")
IMPORT_ENTITY = "procurement.supplier_import"
IMPORT_REASON = "นำเข้าจาก Excel"

FIELD_LABELS = {
    "name": "ชื่อ",
    "description": "รายละเอียด",
    "supplier_type": "ประเภท",
    "credit_group": "กลุ่มเจ้าหนี้",
    "credit_days": "เครดิต",
    "is_active": "สถานะ",
}


def parse_credit_days(group: str) -> int | None:
    """"เครดิต 30 วัน" / "ภายใน 7 วัน" → จำนวนวัน, เจ้าหนี้เงินสด → 0, อื่น ๆ → ไม่ระบุ"""

    match = CREDIT_PATTERN.search(group or "")
    if match:
        return int(match.group(1))
    if "เงินสด" in (group or ""):
        return 0
    return None


@dataclass(frozen=True)
class ImportRow:
    code: str
    name: str
    description: str
    supplier_type: str
    credit_group: str
    credit_days: int | None
    is_active: bool
    in_credit_sheet: bool


@dataclass
class PlannedChange:
    row: ImportRow
    action: str  # create | update | unchanged
    changes: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ImportPlan:
    items: list[PlannedChange]
    warnings: list[str]

    def of(self, action: str) -> list[PlannedChange]:
        return [item for item in self.items if item.action == action]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "total": len(self.items),
            "create": len(self.of("create")),
            "update": len(self.of("update")),
            "unchanged": len(self.of("unchanged")),
            "inactive": sum(1 for item in self.items if not item.row.is_active),
            "credit_unknown": sum(
                1 for item in self.items if item.row.is_active and item.row.credit_days is None
            ),
        }


def _clean(value: str) -> str:
    value = (value or "").strip()
    return "" if value in EMPTY_MARKERS else value


def _find_header(rows: list[list[str]], required: tuple[str, ...], sheet: str) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(rows[:20]):
        columns = {value.strip(): position for position, value in enumerate(row) if value.strip()}
        if all(name in columns for name in required):
            return index, columns
    raise WorkbookError(f"ไม่พบหัวตาราง {', '.join(required)} ในชีต “{sheet}”")


def parse_supplier_file(file) -> tuple[list[ImportRow], list[str]]:
    workbook = read_workbook(file, sheets={SUPPLIER_SHEET, CREDIT_SHEET})
    for sheet in (SUPPLIER_SHEET, CREDIT_SHEET):
        if sheet not in workbook:
            raise WorkbookError(f"ไม่พบชีต “{sheet}” ในไฟล์นี้")

    credit_rows = workbook[CREDIT_SHEET]
    header_index, columns = _find_header(credit_rows, (CODE_HEADER, CREDIT_GROUP_HEADER), CREDIT_SHEET)
    credit_groups: dict[str, str] = {}
    for row in credit_rows[header_index + 1 :]:
        cells = row + [""] * (max(columns.values()) + 1 - len(row))
        code = cells[columns[CODE_HEADER]].strip().upper()
        if code:
            credit_groups.setdefault(code, cells[columns[CREDIT_GROUP_HEADER]].strip())

    supplier_rows = workbook[SUPPLIER_SHEET]
    header_index, columns = _find_header(supplier_rows, (CODE_HEADER, NAME_HEADER), SUPPLIER_SHEET)
    width = max(columns.values()) + 1
    rows: list[ImportRow] = []
    seen: set[str] = set()
    warnings: list[str] = []
    for line, row in enumerate(supplier_rows[header_index + 1 :], start=header_index + 2):
        cells = row + [""] * (width - len(row))
        code = cells[columns[CODE_HEADER]].strip().upper()
        name = cells[columns[NAME_HEADER]].strip()
        if not code and not name:
            continue
        if not code or not name:
            warnings.append(f"แถว {line}: ไม่มี{'รหัส' if not code else 'ชื่อ'}ผู้ขาย ข้ามแถวนี้")
            continue
        if len(code) > 20 or len(name) > 255:
            warnings.append(f"แถว {line}: รหัสหรือชื่อยาวเกินไป ข้ามแถวนี้")
            continue
        if code in seen:
            warnings.append(f"แถว {line}: รหัส {code} ซ้ำในไฟล์ ใช้แถวแรก")
            continue
        seen.add(code)
        description = cells[columns[DESCRIPTION_HEADER]] if DESCRIPTION_HEADER in columns else ""
        is_active = INACTIVE_MARKER not in description
        group = credit_groups.get(code, "")
        rows.append(
            ImportRow(
                code=code,
                name=name,
                description="" if not is_active else _clean(description)[:255],
                supplier_type=_clean(cells[columns[TYPE_HEADER]] if TYPE_HEADER in columns else "")[:100],
                credit_group=group[:150],
                credit_days=parse_credit_days(group),
                is_active=is_active,
                in_credit_sheet=code in credit_groups,
            )
        )
    if not rows:
        raise WorkbookError(f"ไม่พบรายชื่อผู้ขายในชีต “{SUPPLIER_SHEET}”")
    missing = [row.code for row in rows if not row.in_credit_sheet]
    if missing:
        warnings.append(
            f"ไม่พบในชีตเครดิต {len(missing)} ราย ({', '.join(missing[:10])}) จะติดป้ายเครดิตไม่ระบุ"
        )
    return rows, warnings


def rows_to_session(rows: list[ImportRow]) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]


def rows_from_session(data: list[dict[str, object]]) -> list[ImportRow]:
    return [ImportRow(**item) for item in data]


def _format(field_name: str, value) -> str:
    if field_name == "credit_days":
        return "ไม่ระบุ" if value is None else f"{value} วัน"
    if field_name == "is_active":
        return "ใช้งาน" if value else "ปิดใช้งาน"
    return str(value) if value not in (None, "") else "—"


def _target_fields(row: ImportRow, existing: Supplier | None) -> dict[str, object]:
    credit_days = row.credit_days
    if credit_days is None and existing is not None:
        credit_days = existing.credit_days  # ไม่ลบเครดิตที่ฝ่ายบัญชีกรอกไว้
    return {
        "name": row.name,
        "description": row.description,
        "supplier_type": row.supplier_type,
        "credit_group": row.credit_group or (existing.credit_group if existing else ""),
        "credit_days": credit_days,
        "is_active": row.is_active,
    }


def _require_import(actor: User) -> None:
    if not can_manage_suppliers(actor):
        raise PermissionDenied("ไม่มีสิทธิ์นำเข้าผู้ขาย")


def build_import_plan(*, actor: User, rows: list[ImportRow], warnings: list[str]) -> ImportPlan:
    _require_import(actor)
    existing = {supplier.code.upper(): supplier for supplier in Supplier.objects.exclude(code="")}
    items: list[PlannedChange] = []
    for row in rows:
        supplier = existing.get(row.code)
        target = _target_fields(row, supplier)
        if supplier is None:
            items.append(PlannedChange(row=row, action="create"))
            continue
        changes = [
            {
                "label": FIELD_LABELS[name],
                "before": _format(name, getattr(supplier, name)),
                "after": _format(name, value),
            }
            for name, value in target.items()
            if getattr(supplier, name) != value
        ]
        items.append(PlannedChange(row=row, action="update" if changes else "unchanged", changes=changes))
    return ImportPlan(items=items, warnings=warnings)


@transaction.atomic
def apply_supplier_import(
    *, actor: User, rows: list[ImportRow], file_name: str
) -> dict[str, int]:
    _require_import(actor)
    existing = {
        supplier.code.upper(): supplier
        for supplier in Supplier.objects.select_for_update().exclude(code="")
    }
    created = updated = 0
    for row in rows:
        supplier = existing.get(row.code)
        target = _target_fields(row, supplier)
        if supplier is None:
            _create_supplier_record(
                actor=actor, fields={"code": row.code, **target}, reason=IMPORT_REASON
            )
            created += 1
        else:
            _, changed = _update_supplier_record(
                actor=actor, supplier=supplier, fields=target, reason=IMPORT_REASON
            )
            updated += changed
    result = {
        "total": len(rows),
        "created": created,
        "updated": updated,
        "unchanged": len(rows) - created - updated,
    }
    record_event(
        actor=actor,
        action="import",
        entity_type=IMPORT_ENTITY,
        entity_id=uuid.uuid4().hex,
        entity_label=file_name[:255],
        after=result,
    )
    return result
