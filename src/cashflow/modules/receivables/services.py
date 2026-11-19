"""จุดเรียกใช้ของโมดูลรับเงิน ตรวจสิทธิ์ฝั่ง server และบันทึก audit ทุกการเปลี่ยนแปลง"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from cashflow.modules.audit.models import AuditEvent
from cashflow.modules.audit.services import events_for_entity, record_event
from cashflow.modules.identity.models import User

from .models import Customer, InvoiceStatus, ReceiptPlan, SalesInvoice
from .policies import can_manage_receivables, can_view_receivables

CUSTOMER_ENTITY = "receivables.customer"
INVOICE_ENTITY = "receivables.sales_invoice"
PLAN_ENTITY = "receivables.receipt_plan"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_CREDIT_DAYS = 365


def _require_view(actor: User) -> None:
    if not can_view_receivables(actor):
        raise PermissionDenied("ไม่มีสิทธิ์ดูข้อมูลรับเงิน")


def _require_manage(actor: User) -> None:
    if not can_manage_receivables(actor):
        raise PermissionDenied("ไม่มีสิทธิ์จัดการข้อมูลรับเงิน")


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _audit_changes(*, actor, entity_type, entity, label, before, after, action="update", reason="") -> bool:
    changed = {key for key in after if after.get(key) != before.get(key)}
    if not changed:
        return False
    audit_after = {key: after[key] for key in changed}
    if reason:
        audit_after["reason"] = reason
    record_event(
        actor=actor, action=action, entity_type=entity_type, entity_id=str(entity.pk),
        entity_label=label, before={key: before.get(key) for key in changed}, after=audit_after,
    )
    return True


# ---------------------------------------------------------------- ลูกค้า

def _customer_snapshot(customer: Customer) -> dict[str, object]:
    return {"code": customer.code, "name": customer.name, "credit_days": customer.credit_days, "is_active": customer.is_active}


def _clean_customer(*, code: str, name: str, credit_days: int | None, current_id=None) -> tuple[str, str]:
    code, name = code.strip().upper(), name.strip()
    errors = {}
    if code and Customer.objects.filter(code__iexact=code).exclude(pk=current_id).exists():
        errors["code"] = "รหัสลูกค้านี้มีอยู่แล้ว"
    if not name:
        errors["name"] = "กรุณากรอกชื่อลูกค้า"
    if credit_days is not None and not 0 <= credit_days <= MAX_CREDIT_DAYS:
        errors["credit_days"] = f"เครดิตต้องอยู่ระหว่าง 0–{MAX_CREDIT_DAYS} วัน"
    if errors:
        raise ValidationError(errors)
    return code, name


def list_customers(*, actor: User, search: str = "") -> QuerySet[Customer]:
    _require_view(actor)
    customers = Customer.objects.order_by("-is_active", "code", "name")
    if search.strip():
        customers = customers.filter(Q(code__icontains=search.strip()) | Q(name__icontains=search.strip()))
    return customers


def selectable_customers(*, actor: User, include_id=None) -> QuerySet[Customer]:
    _require_manage(actor)
    condition = Q(is_active=True)
    if include_id is not None:
        condition |= Q(pk=include_id)
    return Customer.objects.filter(condition).order_by("code", "name")


@transaction.atomic
def create_customer(*, actor: User, name: str, code: str = "", credit_days: int | None = None) -> Customer:
    _require_manage(actor)
    code, name = _clean_customer(code=code, name=name, credit_days=credit_days)
    customer = Customer.objects.create(code=code, name=name, credit_days=credit_days)
    record_event(actor=actor, action="create", entity_type=CUSTOMER_ENTITY, entity_id=str(customer.pk),
                 entity_label=customer.name, after=_customer_snapshot(customer))
    return customer


@transaction.atomic
def update_customer(*, actor: User, customer: Customer, name: str, code: str, credit_days: int | None, is_active: bool) -> Customer:
    _require_manage(actor)
    code, name = _clean_customer(code=code, name=name, credit_days=credit_days, current_id=customer.pk)
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    before = _customer_snapshot(customer)
    customer.code, customer.name, customer.credit_days, customer.is_active = code, name, credit_days, is_active
    after = _customer_snapshot(customer)
    if after != before:
        customer.save()
        _audit_changes(actor=actor, entity_type=CUSTOMER_ENTITY, entity=customer, label=customer.name, before=before, after=after)
        if before["credit_days"] != after["credit_days"]:
            _refresh_due_dates(actor=actor, customer=customer)
    return customer


# ---------------------------------------------------------------- ใบขาย

def default_due_date(customer: Customer, document_date: date) -> date:
    """วันที่คาดว่าจะได้รับเงิน = วันที่ใบขาย + เครดิตลูกค้า (ไม่ระบุนับเป็น 0 วัน)"""

    return document_date + timedelta(days=customer.credit_days or 0)


def _invoice_snapshot(invoice: SalesInvoice) -> dict[str, object]:
    return {
        "number": invoice.number,
        "customer": str(invoice.customer),
        "reference": invoice.reference,
        "branch": invoice.branch,
        "amount": _money(invoice.amount),
        "document_date": invoice.document_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "status": invoice.status,
        "received_date": invoice.received_date.isoformat() if invoice.received_date else None,
        "received_amount": _money(invoice.received_amount),
        "plan": str(invoice.plan_id) if invoice.plan_id else None,
        "note": invoice.note,
    }


def _refresh_due_dates(*, actor: User, customer: Customer) -> None:
    reason = "เครดิตลูกค้าเปลี่ยนเป็น " + ("ไม่ระบุ" if customer.credit_days is None else f"{customer.credit_days} วัน")
    for invoice in SalesInvoice.objects.select_for_update().filter(
        customer=customer, status=InvoiceStatus.OPEN, due_date_manual=False
    ):
        new_due = default_due_date(customer, invoice.document_date)
        if new_due != invoice.due_date:
            before = {"due_date": invoice.due_date.isoformat()}
            invoice.due_date = new_due
            invoice.save(update_fields=["due_date", "updated_at"])
            _audit_changes(actor=actor, entity_type=INVOICE_ENTITY, entity=invoice, label=invoice.number,
                           before=before, after={"due_date": new_due.isoformat()}, reason=reason)


def list_invoices(*, actor: User, status: str = "", customer_id=None, search: str = "") -> QuerySet[SalesInvoice]:
    _require_view(actor)
    invoices = SalesInvoice.objects.select_related("customer", "plan")
    if status in InvoiceStatus.values:
        invoices = invoices.filter(status=status)
    if customer_id:
        invoices = invoices.filter(customer_id=customer_id)
    if search.strip():
        term = search.strip()
        invoices = invoices.filter(
            Q(number__icontains=term) | Q(reference__icontains=term) | Q(customer__name__icontains=term)
            | Q(customer__code__icontains=term) | Q(branch__icontains=term)
        )
    return invoices.order_by("-document_date", "-number")


def _clean_invoice(*, number, customer, amount, document_date, due_date, current=None):
    number = re.sub(r"\s+", "", number).upper()
    errors = {}
    if not number:
        errors["number"] = "กรุณากรอกเลขที่ใบขาย"
    elif SalesInvoice.objects.filter(number__iexact=number).exclude(pk=current.pk if current else None).exists():
        errors["number"] = f"เลขที่ {number} มีอยู่ในระบบแล้ว"
    if not customer.is_active and (current is None or customer.pk != current.customer_id):
        errors["customer"] = "ลูกค้ารายนี้ถูกปิดการใช้งานแล้ว"
    amount = _round(amount)
    if amount <= 0:
        errors["amount"] = "ยอดเงินต้องมากกว่า 0"
    computed = default_due_date(customer, document_date)
    resolved = due_date or computed
    if resolved < document_date:
        errors["due_date"] = "วันที่คาดว่าจะได้รับเงินต้องไม่ก่อนวันที่ใบขาย"
    if errors:
        raise ValidationError(errors)
    return number, amount, resolved, resolved != computed


@transaction.atomic
def create_invoice(*, actor: User, number: str, customer: Customer, amount: Decimal, document_date: date,
                   due_date: date | None = None, reference: str = "", branch: str = "", note: str = "",
                   reason: str = "") -> SalesInvoice:
    _require_manage(actor)
    number, amount, due, manual = _clean_invoice(number=number, customer=customer, amount=amount,
                                                 document_date=document_date, due_date=due_date)
    invoice = SalesInvoice.objects.create(
        number=number, customer=customer, amount=amount, document_date=document_date, due_date=due,
        due_date_manual=manual, reference=reference.strip(), branch=branch.strip(), note=note.strip(), created_by=actor,
    )
    after = _invoice_snapshot(invoice)
    if reason:
        after["reason"] = reason
    record_event(actor=actor, action="create", entity_type=INVOICE_ENTITY, entity_id=str(invoice.pk),
                 entity_label=invoice.number, after=after)
    return invoice


@transaction.atomic
def update_invoice(*, actor: User, invoice: SalesInvoice, number: str, customer: Customer, amount: Decimal,
                   document_date: date, due_date: date | None = None, reference: str = "", branch: str = "",
                   note: str = "", reason: str = "") -> SalesInvoice:
    _require_manage(actor)
    invoice = SalesInvoice.objects.select_for_update().select_related("customer").get(pk=invoice.pk)
    if invoice.status == InvoiceStatus.CANCELLED:
        raise ValidationError("ใบขายที่ยกเลิกแล้วแก้ไขไม่ได้")
    number, amount, due, manual = _clean_invoice(number=number, customer=customer, amount=amount,
                                                 document_date=document_date, due_date=due_date, current=invoice)
    before = _invoice_snapshot(invoice)
    if invoice.plan_id and invoice.plan.customer_id != customer.pk:
        invoice.plan = None  # แผนเป็นของลูกค้าเดิม เปลี่ยนลูกค้าแล้วต้องผูกใหม่
    invoice.number, invoice.customer, invoice.amount = number, customer, amount
    invoice.document_date, invoice.due_date, invoice.due_date_manual = document_date, due, manual
    invoice.reference, invoice.branch, invoice.note = reference.strip(), branch.strip(), note.strip()
    invoice.save()
    _audit_changes(actor=actor, entity_type=INVOICE_ENTITY, entity=invoice, label=invoice.number,
                   before=before, after=_invoice_snapshot(invoice), reason=reason.strip())
    return invoice


@transaction.atomic
def receive_invoice(*, actor: User, invoice: SalesInvoice, received_date: date, received_amount: Decimal,
                    reason: str = "") -> SalesInvoice:
    """บันทึกรับเงินจริง ยอดจริงต่างจากยอดบิลได้ ระบบเก็บส่วนต่างไว้ให้ตามต่อ"""

    _require_manage(actor)
    invoice = SalesInvoice.objects.select_for_update().select_related("customer").get(pk=invoice.pk)
    if invoice.status == InvoiceStatus.CANCELLED:
        raise ValidationError("ใบขายที่ยกเลิกแล้วรับเงินไม่ได้")
    received_amount = _round(received_amount)
    if received_amount < 0:
        raise ValidationError({"received_amount": "ยอดรับจริงต้องไม่ติดลบ"})
    before = _invoice_snapshot(invoice)
    invoice.status = InvoiceStatus.RECEIVED
    invoice.received_date, invoice.received_amount = received_date, received_amount
    invoice.save()
    _audit_changes(actor=actor, action="receive", entity_type=INVOICE_ENTITY, entity=invoice, label=invoice.number,
                   before=before, after=_invoice_snapshot(invoice), reason=reason.strip())
    return invoice


@transaction.atomic
def reopen_invoice(*, actor: User, invoice: SalesInvoice, reason: str) -> SalesInvoice:
    """ยกเลิกการบันทึกรับเงินที่ลงผิด กลับเป็นรอรับเงิน ต้องมีเหตุผล"""

    _require_manage(actor)
    invoice = SalesInvoice.objects.select_for_update().select_related("customer").get(pk=invoice.pk)
    if invoice.status != InvoiceStatus.RECEIVED:
        raise ValidationError("ใบขายนี้ยังไม่ได้บันทึกรับเงิน")
    if not reason.strip():
        raise ValidationError({"reason": "กรุณาระบุเหตุผล"})
    before = _invoice_snapshot(invoice)
    invoice.status, invoice.received_date, invoice.received_amount = InvoiceStatus.OPEN, None, None
    invoice.save()
    _audit_changes(actor=actor, action="reopen", entity_type=INVOICE_ENTITY, entity=invoice, label=invoice.number,
                   before=before, after=_invoice_snapshot(invoice), reason=reason.strip())
    return invoice


@transaction.atomic
def cancel_invoice(*, actor: User, invoice: SalesInvoice, reason: str) -> SalesInvoice:
    _require_manage(actor)
    invoice = SalesInvoice.objects.select_for_update().select_related("customer").get(pk=invoice.pk)
    if invoice.status == InvoiceStatus.CANCELLED:
        raise ValidationError("ใบขายนี้ถูกยกเลิกไปแล้ว")
    if not reason.strip():
        raise ValidationError({"reason": "กรุณาระบุเหตุผลที่ยกเลิก"})
    before = _invoice_snapshot(invoice)
    invoice.status, invoice.cancel_reason, invoice.plan = InvoiceStatus.CANCELLED, reason.strip(), None
    invoice.save()
    _audit_changes(actor=actor, action="cancel", entity_type=INVOICE_ENTITY, entity=invoice, label=invoice.number,
                   before=before, after=_invoice_snapshot(invoice), reason=reason.strip())
    return invoice


def history(*, actor: User, entity_type: str, entity_id) -> QuerySet[AuditEvent]:
    _require_view(actor)
    return events_for_entity(entity_type=entity_type, entity_id=str(entity_id))


# ---------------------------------------------------------------- แผนรับเงิน

@dataclass(frozen=True)
class PlanSummary:
    plan: ReceiptPlan
    invoiced: Decimal  # ยอดบิลที่ผูกแล้ว
    received: Decimal  # ยอดรับจริงของบิลที่ผูก
    outstanding: Decimal  # ส่วนของแผนที่ยังไม่มีบิล
    difference: Decimal  # รับจริง − แผน (ติดลบ = เงินขาด)


def summarize_plan(plan: ReceiptPlan) -> PlanSummary:
    invoices = [i for i in plan.invoices.all() if i.status != InvoiceStatus.CANCELLED]
    invoiced = sum((i.amount for i in invoices), ZERO)
    received = sum((i.received_amount or ZERO for i in invoices if i.status == InvoiceStatus.RECEIVED), ZERO)
    return PlanSummary(plan=plan, invoiced=invoiced, received=received,
                       outstanding=max(plan.amount - invoiced, ZERO), difference=received - plan.amount)


def list_plans(*, actor: User, customer_id=None) -> list[PlanSummary]:
    _require_view(actor)
    plans = ReceiptPlan.objects.select_related("customer").prefetch_related("invoices")
    if customer_id:
        plans = plans.filter(customer_id=customer_id)
    return [summarize_plan(plan) for plan in plans.order_by("-plan_date", "customer__code")]


def get_plan(*, actor: User, plan_id) -> ReceiptPlan:
    _require_view(actor)
    return ReceiptPlan.objects.select_related("customer", "created_by").prefetch_related("invoices").get(pk=plan_id)


def _plan_snapshot(plan: ReceiptPlan) -> dict[str, object]:
    return {"customer": str(plan.customer), "plan_date": plan.plan_date.isoformat(),
            "amount": _money(plan.amount), "note": plan.note}


@transaction.atomic
def create_plan(*, actor: User, customer: Customer, plan_date: date, amount: Decimal, note: str = "") -> ReceiptPlan:
    _require_manage(actor)
    amount = _round(amount)
    if amount <= 0:
        raise ValidationError({"amount": "ยอดประมาณการต้องมากกว่า 0"})
    plan = ReceiptPlan.objects.create(customer=customer, plan_date=plan_date, amount=amount, note=note.strip(), created_by=actor)
    record_event(actor=actor, action="create", entity_type=PLAN_ENTITY, entity_id=str(plan.pk),
                 entity_label=str(plan), after=_plan_snapshot(plan))
    return plan


@transaction.atomic
def update_plan(*, actor: User, plan: ReceiptPlan, plan_date: date, amount: Decimal, note: str = "", reason: str = "") -> ReceiptPlan:
    _require_manage(actor)
    amount = _round(amount)
    if amount <= 0:
        raise ValidationError({"amount": "ยอดประมาณการต้องมากกว่า 0"})
    plan = ReceiptPlan.objects.select_for_update().select_related("customer").get(pk=plan.pk)
    before = _plan_snapshot(plan)
    plan.plan_date, plan.amount, plan.note = plan_date, amount, note.strip()
    plan.save()
    _audit_changes(actor=actor, entity_type=PLAN_ENTITY, entity=plan, label=str(plan), before=before,
                   after=_plan_snapshot(plan), reason=reason.strip())
    return plan


def linkable_invoices(*, actor: User, plan: ReceiptPlan) -> QuerySet[SalesInvoice]:
    """ใบขายของลูกค้าเดียวกันที่ยังไม่ยกเลิก และยังไม่ได้ผูกกับแผนอื่น"""

    _require_view(actor)
    return (
        SalesInvoice.objects.filter(customer=plan.customer)
        .exclude(status=InvoiceStatus.CANCELLED)
        .filter(Q(plan__isnull=True) | Q(plan=plan))
        .order_by("due_date", "number")
    )


@transaction.atomic
def set_plan_invoices(*, actor: User, plan: ReceiptPlan, invoice_ids: Iterable) -> PlanSummary:
    _require_manage(actor)
    plan = ReceiptPlan.objects.select_for_update().select_related("customer").get(pk=plan.pk)
    allowed = {str(i.pk): i for i in linkable_invoices(actor=actor, plan=plan).select_for_update()}
    wanted = {str(i) for i in invoice_ids}
    unknown = wanted - set(allowed)
    if unknown:
        raise ValidationError("มีใบขายที่ผูกกับแผนนี้ไม่ได้ (ลูกค้าไม่ตรง ยกเลิกแล้ว หรืออยู่ในแผนอื่น)")
    before = sorted(i.number for i in allowed.values() if i.plan_id == plan.pk)
    for key, invoice in allowed.items():
        target = plan if key in wanted else None
        if invoice.plan_id != (target.pk if target else None):
            invoice.plan = target
            invoice.save(update_fields=["plan", "updated_at"])
    after = sorted(allowed[key].number for key in wanted)
    _audit_changes(actor=actor, action="link", entity_type=PLAN_ENTITY, entity=plan, label=str(plan),
                   before={"invoices": before}, after={"invoices": after})
    return summarize_plan(ReceiptPlan.objects.prefetch_related("invoices").get(pk=plan.pk))


# ---------------------------------------------------------------- ให้หน้ากระแสเงินสดใช้

@dataclass(frozen=True)
class CashEntry:
    day: date
    direction: str  # in | out
    kind: str  # actual | expected | plan
    amount: Decimal
    title: str
    detail: str
    url_name: str
    object_id: object


def cash_entries(*, actor: User, start: date, end: date) -> list[CashEntry]:
    _require_view(actor)
    entries: list[CashEntry] = []
    for invoice in SalesInvoice.objects.select_related("customer").filter(
        status=InvoiceStatus.OPEN, due_date__range=(start, end)
    ):
        entries.append(CashEntry(invoice.due_date, "in", "expected", invoice.amount, invoice.number,
                                 str(invoice.customer), "web:sales-invoice-detail", invoice.pk))
    for invoice in SalesInvoice.objects.select_related("customer").filter(
        status=InvoiceStatus.RECEIVED, received_date__range=(start, end)
    ):
        entries.append(CashEntry(invoice.received_date, "in", "actual", invoice.received_amount, invoice.number,
                                 str(invoice.customer), "web:sales-invoice-detail", invoice.pk))
    for plan in ReceiptPlan.objects.select_related("customer").prefetch_related("invoices").filter(
        plan_date__range=(start, end)
    ):
        summary = summarize_plan(plan)
        if summary.outstanding > 0:
            entries.append(CashEntry(plan.plan_date, "in", "plan", summary.outstanding, "แผนรับเงิน",
                                     str(plan.customer), "web:receipt-plan-detail", plan.pk))
    return entries


def overdue_invoices(*, actor: User, before: date) -> QuerySet[SalesInvoice]:
    """ใบขายที่เลยวันที่คาดว่าจะได้รับแล้ว แต่ยังไม่ได้บันทึกรับเงิน"""

    _require_view(actor)
    return SalesInvoice.objects.select_related("customer").filter(status=InvoiceStatus.OPEN, due_date__lt=before)
