"""นำเข้าใบขายจากไฟล์ "รายการคำสั่งซื้อแม็คโคร ที่เสร็จสิ้นแล้ว" (หนึ่งไฟล์ = ลูกค้าหนึ่งราย)

คอลัมน์ที่ต้องมี: หมายเลข Invoice, ยอดสุทธิ, วันที่ Invoice
คอลัมน์ที่ใช้ถ้ามี: หมายเลข PO, สาขา, วันที่ต้องส่ง
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction

from cashflow.modules.audit.services import record_event
from cashflow.modules.identity.models import User
from cashflow.modules.procurement.xlsx_reader import WorkbookError, read_workbook

from .models import Customer, InvoiceStatus, SalesInvoice
from .services import _require_manage, create_invoice, default_due_date, update_invoice

IMPORT_REASON = "นำเข้าจาก Excel"
COLUMNS = {
    "number": ("หมายเลขinvoice", "เลขที่invoice", "เลขที่ใบกำกับ"),
    "amount": ("ยอดสุทธิ", "จำนวนเงิน", "ยอดเงิน"),
    "document_date": ("วันที่invoice", "วันที่ใบกำกับ"),
    "reference": ("หมายเลขpo", "เลขที่po"),
    "branch": ("สาขา",),
}
REQUIRED = ("number", "amount", "document_date")
EXCEL_EPOCH = date(1899, 12, 30)


def _key(header: str) -> str:
    return re.sub(r"\s+", "", header).lower()


def parse_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    if re.fullmatch(r"\d{4,5}(\.0+)?", value):  # วันที่ที่ Excel เก็บเป็นตัวเลข
        return EXCEL_EPOCH + timedelta(days=int(float(value)))
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", value.split(" ")[0])
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year > 2400:  # ปี พ.ศ.
        year -= 543
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_amount(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


@dataclass(frozen=True)
class ImportRow:
    number: str
    amount: str
    document_date: str
    reference: str
    branch: str


@dataclass
class PlannedRow:
    row: ImportRow
    action: str  # create | update | unchanged | skip
    note: str = ""
    changes: list[str] = field(default_factory=list)


def parse_invoice_file(file) -> tuple[list[ImportRow], list[str]]:
    workbook = read_workbook(file)
    for sheet_name, rows in workbook.items():
        for index, row in enumerate(rows[:30]):
            keys = [_key(cell) for cell in row]
            columns = {}
            for name, aliases in COLUMNS.items():
                for position, key in enumerate(keys):
                    if key in aliases:
                        columns.setdefault(name, position)
            if all(name in columns for name in REQUIRED):
                return _parse_rows(rows[index + 1 :], columns, start_line=index + 2)
    raise WorkbookError("ไม่พบหัวตาราง หมายเลข Invoice, ยอดสุทธิ และวันที่ Invoice ในไฟล์นี้")


def _parse_rows(rows, columns, start_line) -> tuple[list[ImportRow], list[str]]:
    width = max(columns.values()) + 1
    parsed, warnings, seen = [], [], set()
    for line, row in enumerate(rows, start=start_line):
        cells = row + [""] * (width - len(row))
        number = re.sub(r"\s+", "", cells[columns["number"]]).upper()
        if not number:
            continue
        amount = parse_amount(cells[columns["amount"]])
        document_date = parse_date(cells[columns["document_date"]])
        if amount is None or amount <= 0 or document_date is None:
            warnings.append(f"แถว {line} ({number}): ยอดเงินหรือวันที่ไม่ถูกต้อง ข้ามแถวนี้")
            continue
        if number in seen:
            warnings.append(f"แถว {line}: {number} ซ้ำในไฟล์ ใช้แถวแรก")
            continue
        seen.add(number)
        parsed.append(ImportRow(
            number=number[:40], amount=str(amount), document_date=document_date.isoformat(),
            reference=cells[columns["reference"]].strip()[:60] if "reference" in columns else "",
            branch=cells[columns["branch"]].strip()[:120] if "branch" in columns else "",
        ))
    if not parsed:
        raise WorkbookError("ไม่พบรายการใบขายในไฟล์นี้")
    return parsed, warnings


def rows_to_session(rows):
    return [asdict(row) for row in rows]


def rows_from_session(data):
    return [ImportRow(**item) for item in data]


def build_plan(*, actor: User, customer: Customer, rows: list[ImportRow]) -> list[PlannedRow]:
    _require_manage(actor)
    existing = {i.number: i for i in SalesInvoice.objects.filter(number__in=[r.number for r in rows]).select_related("customer")}
    planned = []
    for row in rows:
        invoice = existing.get(row.number)
        if invoice is None:
            planned.append(PlannedRow(row, "create"))
        elif invoice.customer_id != customer.pk:
            planned.append(PlannedRow(row, "skip", f"เป็นใบขายของลูกค้า {invoice.customer}"))
        elif invoice.status != InvoiceStatus.OPEN:
            planned.append(PlannedRow(row, "skip", f"สถานะ{invoice.get_status_display()} ไม่แก้ทับ"))
        else:
            changes = []
            if invoice.amount != Decimal(row.amount):
                changes.append(f"ยอด {invoice.amount:,.2f} → {Decimal(row.amount):,.2f}")
            if invoice.document_date.isoformat() != row.document_date:
                changes.append(f"วันที่ {invoice.document_date} → {row.document_date}")
            if invoice.reference != row.reference or invoice.branch != row.branch:
                changes.append("เลข PO หรือสาขา")
            planned.append(PlannedRow(row, "update" if changes else "unchanged", changes=changes))
    return planned


@transaction.atomic
def apply_import(*, actor: User, customer: Customer, rows: list[ImportRow], file_name: str) -> dict[str, int]:
    counts = {"create": 0, "update": 0, "unchanged": 0, "skip": 0}
    for item in build_plan(actor=actor, customer=customer, rows=rows):
        row, action = item.row, item.action
        counts[action] += 1
        if action == "create":
            create_invoice(actor=actor, number=row.number, customer=customer, amount=Decimal(row.amount),
                           document_date=date.fromisoformat(row.document_date), reference=row.reference,
                           branch=row.branch, reason=IMPORT_REASON)
        elif action == "update":
            invoice = SalesInvoice.objects.get(number=row.number)
            update_invoice(actor=actor, invoice=invoice, number=row.number, customer=customer,
                           amount=Decimal(row.amount), document_date=date.fromisoformat(row.document_date),
                           due_date=invoice.due_date if invoice.due_date_manual else None,
                           reference=row.reference, branch=row.branch, note=invoice.note, reason=IMPORT_REASON)
    record_event(actor=actor, action="import", entity_type="receivables.invoice_import",
                 entity_id=datetime.now().strftime("%Y%m%d%H%M%S%f"), entity_label=file_name[:255],
                 after={"customer": str(customer), **counts})
    return counts


__all__ = ["parse_invoice_file", "build_plan", "apply_import", "default_due_date"]
