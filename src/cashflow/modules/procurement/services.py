"""จุดเรียกใช้ของโมดูลจัดซื้อ ทุกฟังก์ชันตรวจสิทธิ์ฝั่ง server และบันทึก audit เอง"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from cashflow.modules.audit.models import AuditEvent
from cashflow.modules.audit.services import events_for_entity, record_event
from cashflow.modules.identity.models import User

from .constants import MAX_CREDIT_DAYS
from .models import ApprovalStatus, PurchaseOrder, PurchaseOrderStatus, Supplier
from .policies import (
    can_manage_purchase_orders,
    can_manage_suppliers,
    can_view_purchase_orders,
)

SUPPLIER_ENTITY = "procurement.supplier"
PURCHASE_ORDER_ENTITY = "procurement.purchase_order"
CENT = Decimal("0.01")

# PO ที่ยังต้องจ่ายเงิน นับเป็นเงินออกที่คาดว่าจะจ่ายเมื่ออนุมัติแล้ว
OUTSTANDING_STATUSES = (PurchaseOrderStatus.NEW, PurchaseOrderStatus.RECEIVED)
# สถานะที่เลือกได้ในฟอร์ม การยกเลิกทำผ่านปุ่มยกเลิกเพื่อบังคับใส่เหตุผล
EDITABLE_STATUSES = (
    PurchaseOrderStatus.NEW,
    PurchaseOrderStatus.RECEIVED,
    PurchaseOrderStatus.CLOSED,
)


@dataclass(frozen=True)
class ExpectedOutflow:
    purchase_order_id: object
    number: str
    supplier_code: str
    supplier_name: str
    due_date: date
    amount: Decimal
    status: str
    status_label: str
    is_overdue: bool
    credit_unknown: bool = False


# ---------------------------------------------------------------- สิทธิ์

def _require_view(actor: User) -> None:
    if not can_view_purchase_orders(actor):
        raise PermissionDenied("ไม่มีสิทธิ์ดูใบสั่งซื้อ")


def _require_po_management(actor: User) -> None:
    if not can_manage_purchase_orders(actor):
        raise PermissionDenied("ไม่มีสิทธิ์จัดการใบสั่งซื้อ")


def _require_supplier_management(actor: User) -> None:
    if not can_manage_suppliers(actor):
        raise PermissionDenied("ไม่มีสิทธิ์จัดการผู้ขาย")


# ---------------------------------------------------------------- snapshot สำหรับ audit

def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _supplier_snapshot(supplier: Supplier) -> dict[str, object]:
    return {
        "code": supplier.code,
        "name": supplier.name,
        "tax_id": supplier.tax_id,
        "branch": supplier.branch,
        "address": supplier.address,
        "contact_name": supplier.contact_name,
        "phone": supplier.phone,
        "email": supplier.email,
        "credit_days": supplier.credit_days,
        "credit_group": supplier.credit_group,
        "description": supplier.description,
        "supplier_type": supplier.supplier_type,
        "is_active": supplier.is_active,
    }


def _purchase_order_snapshot(purchase_order: PurchaseOrder) -> dict[str, object]:
    supplier = purchase_order.supplier
    return {
        "number": purchase_order.number,
        "supplier": f"{supplier.code} {supplier.name}".strip(),
        "total_amount": _money(purchase_order.total_amount),
        "ordered_at": timezone.localtime(purchase_order.ordered_at).isoformat(timespec="minutes"),
        "delivery_date": purchase_order.delivery_date.isoformat(),
        "due_date": purchase_order.due_date.isoformat(),
        "status": purchase_order.status,
        "approval_status": purchase_order.approval_status,
        "note": purchase_order.note,
    }


# ---------------------------------------------------------------- ผู้ขาย

TAX_ID_PATTERN = re.compile(r"^\d{13}$")


def _clean_supplier_fields(
    *, code: str, name: str, tax_id: str, credit_days: int | None, current_id=None
) -> tuple[str, str, str]:
    code = code.strip().upper()
    name = name.strip()
    tax_id = re.sub(r"[\s-]", "", tax_id)
    errors: dict[str, str] = {}
    if code and Supplier.objects.filter(code__iexact=code).exclude(pk=current_id).exists():
        errors["code"] = "รหัสผู้ขายนี้มีอยู่แล้ว"
    if not name:
        errors["name"] = "กรุณากรอกชื่อผู้ขาย"
    if tax_id and not TAX_ID_PATTERN.match(tax_id):
        errors["tax_id"] = "เลขประจำตัวผู้เสียภาษีต้องเป็นตัวเลข 13 หลัก"
    if credit_days is not None and not 0 <= credit_days <= MAX_CREDIT_DAYS:
        errors["credit_days"] = f"เครดิตเทอมต้องอยู่ระหว่าง 0–{MAX_CREDIT_DAYS} วัน"
    if errors:
        raise ValidationError(errors)
    return code, name, tax_id


def list_suppliers(
    *, actor: User, search: str = "", credit_unknown: bool = False
) -> QuerySet[Supplier]:
    _require_view(actor)
    suppliers = Supplier.objects.order_by("-is_active", "code", "name")
    search = search.strip()
    if search:
        suppliers = suppliers.filter(
            Q(code__icontains=search)
            | Q(name__icontains=search)
            | Q(tax_id__icontains=search)
        )
    if credit_unknown:
        suppliers = suppliers.filter(credit_days__isnull=True, is_active=True)
    return suppliers


def selectable_suppliers(*, actor: User, include_id=None) -> QuerySet[Supplier]:
    """ผู้ขายที่เลือกใส่ PO ได้ ตอนแก้ไขให้รวมผู้ขายเดิมไว้ด้วยแม้ถูกปิดไปแล้ว"""

    _require_po_management(actor)
    condition = Q(is_active=True)
    if include_id is not None:
        condition |= Q(pk=include_id)
    return Supplier.objects.filter(condition).order_by("code", "name")


def _credit_reason(credit_days: int | None) -> str:
    if credit_days is None:
        return "เครดิตของผู้ขายเปลี่ยนเป็นไม่ระบุ"
    return f"เครดิตของผู้ขายเปลี่ยนเป็น {credit_days} วัน"


def _refresh_due_dates(*, actor: User, supplier: Supplier) -> int:
    """คำนวณวันครบกำหนดจ่ายใหม่ให้ PO ที่ยังเปิดอยู่และไม่ได้กำหนดวันเอง"""

    reason = _credit_reason(supplier.credit_days)
    changed = 0
    orders = PurchaseOrder.objects.select_for_update().filter(
        supplier=supplier, status__in=OUTSTANDING_STATUSES, due_date_manual=False
    )
    for order in orders:
        new_due_date = default_due_date(supplier, order.delivery_date)
        if new_due_date == order.due_date:
            continue
        before = order.due_date.isoformat()
        order.due_date = new_due_date
        order.save(update_fields=["due_date", "updated_at"])
        record_event(
            actor=actor,
            action="update",
            entity_type=PURCHASE_ORDER_ENTITY,
            entity_id=str(order.pk),
            entity_label=order.number,
            before={"due_date": before},
            after={"due_date": new_due_date.isoformat(), "reason": reason},
        )
        changed += 1
    return changed


def _create_supplier_record(
    *, actor: User, fields: dict[str, object], reason: str = ""
) -> Supplier:
    supplier = Supplier.objects.create(**fields)
    after = _supplier_snapshot(supplier)
    if reason:
        after["reason"] = reason
    record_event(
        actor=actor,
        action="create",
        entity_type=SUPPLIER_ENTITY,
        entity_id=str(supplier.pk),
        entity_label=supplier.name,
        after=after,
    )
    return supplier


def _update_supplier_record(
    *, actor: User, supplier: Supplier, fields: dict[str, object], reason: str = ""
) -> tuple[Supplier, bool]:
    """บันทึกเฉพาะช่องที่เปลี่ยนลง audit คืนค่า (ผู้ขาย, มีการเปลี่ยนหรือไม่)"""

    supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
    before = _supplier_snapshot(supplier)
    for field, value in fields.items():
        setattr(supplier, field, value)
    after = _supplier_snapshot(supplier)
    changed = {key for key in after if after[key] != before[key]}
    if not changed:
        return supplier, False
    supplier.save()
    audit_after: dict[str, object] = {key: after[key] for key in changed}
    if reason:
        audit_after["reason"] = reason
    record_event(
        actor=actor,
        action="update",
        entity_type=SUPPLIER_ENTITY,
        entity_id=str(supplier.pk),
        entity_label=supplier.name,
        before={key: before[key] for key in changed},
        after=audit_after,
    )
    if "credit_days" in changed:
        _refresh_due_dates(actor=actor, supplier=supplier)
    return supplier, True


@transaction.atomic
def create_supplier(
    *,
    actor: User,
    name: str,
    code: str = "",
    tax_id: str = "",
    branch: str = "",
    address: str = "",
    contact_name: str = "",
    phone: str = "",
    email: str = "",
    credit_days: int | None = None,
    description: str = "",
    supplier_type: str = "",
) -> Supplier:
    _require_supplier_management(actor)
    code, name, tax_id = _clean_supplier_fields(
        code=code, name=name, tax_id=tax_id, credit_days=credit_days
    )
    return _create_supplier_record(
        actor=actor,
        fields={
            "code": code,
            "name": name,
            "tax_id": tax_id,
            "branch": branch.strip(),
            "address": address.strip(),
            "contact_name": contact_name.strip(),
            "phone": phone.strip(),
            "email": email.strip(),
            "credit_days": credit_days,
            "description": description.strip(),
            "supplier_type": supplier_type.strip(),
        },
    )


@transaction.atomic
def update_supplier(
    *,
    actor: User,
    supplier: Supplier,
    code: str,
    name: str,
    tax_id: str,
    branch: str,
    address: str,
    contact_name: str,
    phone: str,
    email: str,
    credit_days: int | None,
    is_active: bool,
    description: str = "",
    supplier_type: str = "",
) -> Supplier:
    _require_supplier_management(actor)
    code, name, tax_id = _clean_supplier_fields(
        code=code,
        name=name,
        tax_id=tax_id,
        credit_days=credit_days,
        current_id=supplier.pk,
    )
    supplier, _ = _update_supplier_record(
        actor=actor,
        supplier=supplier,
        fields={
            "code": code,
            "name": name,
            "tax_id": tax_id,
            "branch": branch.strip(),
            "address": address.strip(),
            "contact_name": contact_name.strip(),
            "phone": phone.strip(),
            "email": email.strip(),
            "credit_days": credit_days,
            "description": description.strip(),
            "supplier_type": supplier_type.strip(),
            "is_active": is_active,
        },
    )
    return supplier


# ---------------------------------------------------------------- ใบสั่งซื้อ

def list_purchase_orders(
    *, actor: User, status: str = "", approval: str = "", search: str = ""
) -> QuerySet[PurchaseOrder]:
    _require_view(actor)
    orders = PurchaseOrder.objects.select_related("supplier")
    if status in PurchaseOrderStatus.values:
        orders = orders.filter(status=status)
    if approval in ApprovalStatus.values:
        orders = orders.filter(approval_status=approval)
    search = search.strip()
    if search:
        orders = orders.filter(
            Q(number__icontains=search)
            | Q(supplier__code__icontains=search)
            | Q(supplier__name__icontains=search)
        )
    return orders.order_by("-ordered_at", "-number")


def default_due_date(supplier: Supplier, delivery_date: date) -> date:
    """วันครบกำหนดจ่ายตั้งต้น = วันที่จัดส่ง + เครดิตเทอม (ไม่ระบุเครดิตนับเป็น 0 วัน)"""

    return delivery_date + timedelta(days=supplier.credit_days or 0)


def _clean_order(
    *,
    number: str,
    supplier: Supplier,
    total_amount: Decimal,
    delivery_date: date,
    due_date: date | None,
    status: str,
    approval_status: str,
    current: PurchaseOrder | None = None,
) -> tuple[str, Decimal, date, bool]:
    number = re.sub(r"\s+", "", number).upper()
    errors: dict[str, str] = {}
    if not number:
        errors["number"] = "กรุณากรอกหมายเลข PO"
    elif (
        PurchaseOrder.objects.filter(number__iexact=number)
        .exclude(pk=current.pk if current else None)
        .exists()
    ):
        errors["number"] = f"หมายเลข {number} มีอยู่ในระบบแล้ว"
    if not supplier.is_active and (current is None or supplier.pk != current.supplier_id):
        errors["supplier"] = "ผู้ขายรายนี้ถูกปิดการใช้งานแล้ว"
    # ระบบเดิมเก็บทศนิยม 3 ตำแหน่ง ปัดเป็นสตางค์แบบครึ่งขึ้น
    total_amount = total_amount.quantize(CENT, rounding=ROUND_HALF_UP)
    if total_amount <= 0:
        errors["total_amount"] = "ยอดรวมต้องมากกว่า 0"
    if status not in EDITABLE_STATUSES:
        errors["status"] = "สถานะไม่ถูกต้อง"
    if approval_status not in ApprovalStatus.values:
        errors["approval_status"] = "สถานะอนุมัติไม่ถูกต้อง"
    computed_due_date = default_due_date(supplier, delivery_date)
    resolved_due_date = due_date or computed_due_date
    if resolved_due_date < delivery_date:
        errors["due_date"] = "วันครบกำหนดจ่ายต้องไม่ก่อนวันที่จัดส่ง"
    if errors:
        raise ValidationError(errors)
    return number, total_amount, resolved_due_date, resolved_due_date != computed_due_date


@transaction.atomic
def create_purchase_order(
    *,
    actor: User,
    number: str,
    supplier: Supplier,
    total_amount: Decimal,
    delivery_date: date,
    ordered_at: datetime | None = None,
    due_date: date | None = None,
    status: str = PurchaseOrderStatus.NEW,
    approval_status: str = ApprovalStatus.APPROVED,
    note: str = "",
) -> PurchaseOrder:
    _require_po_management(actor)
    number, total_amount, resolved_due_date, due_date_manual = _clean_order(
        number=number,
        supplier=supplier,
        total_amount=total_amount,
        delivery_date=delivery_date,
        due_date=due_date,
        status=status,
        approval_status=approval_status,
    )
    purchase_order = PurchaseOrder.objects.create(
        number=number,
        supplier=supplier,
        total_amount=total_amount,
        ordered_at=ordered_at or timezone.now(),
        delivery_date=delivery_date,
        due_date=resolved_due_date,
        due_date_manual=due_date_manual,
        status=status,
        approval_status=approval_status,
        note=note.strip(),
        created_by=actor,
    )
    record_event(
        actor=actor,
        action="create",
        entity_type=PURCHASE_ORDER_ENTITY,
        entity_id=str(purchase_order.pk),
        entity_label=purchase_order.number,
        after=_purchase_order_snapshot(purchase_order),
    )
    return purchase_order


@transaction.atomic
def update_purchase_order(
    *,
    actor: User,
    purchase_order: PurchaseOrder,
    number: str,
    supplier: Supplier,
    total_amount: Decimal,
    delivery_date: date,
    ordered_at: datetime,
    due_date: date | None = None,
    status: str = PurchaseOrderStatus.NEW,
    approval_status: str = ApprovalStatus.APPROVED,
    note: str = "",
    reason: str = "",
) -> PurchaseOrder:
    """แก้ไขได้ทุกช่องจนกว่าจะยกเลิก ทุกครั้งที่ค่าเปลี่ยนจะบันทึกค่าก่อน/หลังและเหตุผล"""

    _require_po_management(actor)
    purchase_order = (
        PurchaseOrder.objects.select_for_update()
        .select_related("supplier")
        .get(pk=purchase_order.pk)
    )
    if not purchase_order.is_editable:
        raise ValidationError("ใบสั่งซื้อที่ยกเลิกแล้วแก้ไขไม่ได้")
    number, total_amount, resolved_due_date, due_date_manual = _clean_order(
        number=number,
        supplier=supplier,
        total_amount=total_amount,
        delivery_date=delivery_date,
        due_date=due_date,
        status=status,
        approval_status=approval_status,
        current=purchase_order,
    )
    before = _purchase_order_snapshot(purchase_order)
    purchase_order.number = number
    purchase_order.supplier = supplier
    purchase_order.total_amount = total_amount
    purchase_order.ordered_at = ordered_at
    purchase_order.delivery_date = delivery_date
    purchase_order.due_date = resolved_due_date
    purchase_order.due_date_manual = due_date_manual
    purchase_order.status = status
    purchase_order.approval_status = approval_status
    purchase_order.note = note.strip()
    after = _purchase_order_snapshot(purchase_order)
    if after == before:
        # วันไม่เปลี่ยนแต่อาจเปลี่ยนจากกำหนดเองเป็นคำนวณอัตโนมัติ ไม่ต้องลงประวัติ
        purchase_order.save(update_fields=["due_date_manual"])
        return purchase_order

    purchase_order.save()
    changed = {key for key in after if after[key] != before[key]}
    audit_after: dict[str, object] = {key: after[key] for key in changed}
    reason = reason.strip()
    if reason:
        audit_after["reason"] = reason
    record_event(
        actor=actor,
        action="update",
        entity_type=PURCHASE_ORDER_ENTITY,
        entity_id=str(purchase_order.pk),
        entity_label=purchase_order.number,
        before={key: before[key] for key in changed},
        after=audit_after,
    )
    return purchase_order


@transaction.atomic
def cancel_purchase_order(
    *, actor: User, purchase_order: PurchaseOrder, reason: str
) -> PurchaseOrder:
    _require_po_management(actor)
    purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    if purchase_order.status == PurchaseOrderStatus.CANCELLED:
        raise ValidationError("ใบสั่งซื้อนี้ถูกยกเลิกไปแล้ว")
    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": "กรุณาระบุเหตุผลที่ยกเลิก"})
    previous_status = purchase_order.status
    purchase_order.status = PurchaseOrderStatus.CANCELLED
    purchase_order.cancel_reason = reason
    purchase_order.save(update_fields=["status", "cancel_reason", "updated_at"])
    record_event(
        actor=actor,
        action="cancel",
        entity_type=PURCHASE_ORDER_ENTITY,
        entity_id=str(purchase_order.pk),
        entity_label=purchase_order.number,
        before={"status": previous_status},
        after={"status": purchase_order.status, "reason": reason},
    )
    return purchase_order


def purchase_order_history(
    *, actor: User, purchase_order: PurchaseOrder
) -> QuerySet[AuditEvent]:
    _require_view(actor)
    return events_for_entity(
        entity_type=PURCHASE_ORDER_ENTITY, entity_id=str(purchase_order.pk)
    )


# ---------------------------------------------------------------- เชื่อมกับกระแสเงินสด

def expected_outflows(*, actor: User, today: date | None = None) -> list[ExpectedOutflow]:
    """เงินออกที่คาดว่าจะจ่ายจาก PO ที่อนุมัติแล้วและยังไม่ปิด เรียงตามวันครบกำหนด

    ใช้ยอดรวม VAT ตามรายงานระบบเดิม ยังไม่หัก ณ ที่จ่าย จึงอาจสูงกว่ายอดจ่ายจริงเล็กน้อย
    """

    _require_view(actor)
    today = today or timezone.localdate()
    orders = (
        PurchaseOrder.objects.filter(
            status__in=OUTSTANDING_STATUSES,
            approval_status=ApprovalStatus.APPROVED,
        )
        .select_related("supplier")
        .order_by("due_date", "number")
    )
    return [
        ExpectedOutflow(
            purchase_order_id=order.pk,
            number=order.number,
            supplier_code=order.supplier.code,
            supplier_name=order.supplier.name,
            due_date=order.due_date,
            amount=order.total_amount,
            status=order.status,
            status_label=order.get_status_display(),
            is_overdue=order.due_date < today,
            credit_unknown=order.supplier.credit_days is None and not order.due_date_manual,
        )
        for order in orders
    ]
