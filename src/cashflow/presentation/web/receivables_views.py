from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from cashflow.modules.procurement.policies import can_view_purchase_orders
from cashflow.modules.procurement.services import expected_outflows, outflow_entries
from cashflow.modules.procurement.xlsx_reader import WorkbookError
from cashflow.modules.receivables import invoice_import
from cashflow.modules.receivables.models import InvoiceStatus, ReceiptPlan
from cashflow.modules.receivables.policies import can_manage_receivables, can_view_receivables
from cashflow.modules.receivables.services import (
    INVOICE_ENTITY,
    PLAN_ENTITY,
    cancel_invoice,
    cash_entries,
    create_customer,
    create_invoice,
    create_plan,
    get_plan,
    history,
    linkable_invoices,
    list_customers,
    list_invoices,
    list_plans,
    overdue_invoices,
    receive_invoice,
    reopen_invoice,
    selectable_customers,
    set_plan_invoices,
    summarize_plan,
    update_customer,
    update_invoice,
    update_plan,
)

from .access import capability_required
from .procurement_views import _add_service_error
from .receivables_forms import (
    CustomerForm,
    InvoiceForm,
    InvoiceImportForm,
    PlanForm,
    ReasonForm,
    ReceiveForm,
)
from .templatetags.web_format import money, thai_date

ACTION_LABELS = {
    "create": "บันทึก", "update": "แก้ไข", "receive": "บันทึกรับเงิน", "reopen": "ยกเลิกการรับเงิน",
    "cancel": "ยกเลิก", "link": "ผูกใบขายกับแผน",
}
FIELD_LABELS = {
    "number": "เลขที่", "customer": "ลูกค้า", "amount": "ยอด", "document_date": "วันที่ใบขาย",
    "due_date": "คาดว่าจะได้รับ", "plan_date": "วันที่แผน", "status": "สถานะ", "received_date": "วันที่รับจริง",
    "received_amount": "ยอดรับจริง", "reference": "เลข PO ลูกค้า", "branch": "สาขา", "note": "หมายเหตุ",
    "invoices": "ใบขายที่ผูก",
}
IMPORT_SESSION_KEY = "receivables_invoice_import"
INVOICE_ACTIONS = {"receive", "reopen", "cancel"}


def _fmt(field: str, value) -> str:
    if value in (None, "", []):
        return "—"
    if isinstance(value, list):
        return ", ".join(value)
    try:
        if field in ("amount", "received_amount"):
            return money(Decimal(str(value)))
        if field in ("document_date", "due_date", "plan_date", "received_date"):
            return thai_date(date.fromisoformat(str(value)))
    except (InvalidOperation, ValueError):
        pass
    if field == "status":
        return dict(InvoiceStatus.choices).get(value, value)
    return str(value)


def _history_rows(events):
    rows = []
    for event in events:
        changes = []
        if event.action != "create":
            changes = [
                {"label": label, "before": _fmt(key, event.before.get(key)), "after": _fmt(key, event.after.get(key))}
                for key, label in FIELD_LABELS.items()
                if key in event.after and event.before.get(key) != event.after.get(key)
            ]
        rows.append({
            "label": ACTION_LABELS.get(event.action, event.action), "action": event.action,
            "actor": event.actor.get_display_name() if event.actor else event.actor_identifier,
            "occurred_at": event.occurred_at, "reason": event.after.get("reason", ""), "changes": changes,
        })
    return rows


# ---------------------------------------------------------------- ลูกค้า

@capability_required(can_view_receivables)
def customer_list_view(request: HttpRequest) -> HttpResponse:
    search = request.GET.get("q", "")
    return render(request, "web/receivables/customer_list.html",
                  {"customers": list_customers(actor=request.user, search=search), "search": search})


@capability_required(can_manage_receivables)
@require_http_methods(["GET", "POST"])
def customer_form_view(request: HttpRequest, customer_id=None) -> HttpResponse:
    customer = get_object_or_404(list_customers(actor=request.user), pk=customer_id) if customer_id else None
    form = CustomerForm(request.POST or None, customer=customer)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            if customer is None:
                create_customer(actor=request.user, code=data["code"], name=data["name"], credit_days=data["credit_days"])
            else:
                update_customer(actor=request.user, customer=customer, code=data["code"], name=data["name"],
                                credit_days=data["credit_days"], is_active=data["is_active"])
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"บันทึกลูกค้า {data['name']} แล้ว")
            return redirect("web:customer-list")
    return render(request, "web/receivables/customer_form.html", {"form": form, "customer": customer})


# ---------------------------------------------------------------- ใบขาย

@capability_required(can_view_receivables)
def invoice_list_view(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "")
    status = status if status in InvoiceStatus.values else ""
    customer_id = request.GET.get("customer") or None
    search = request.GET.get("q", "")
    try:
        invoices = list_invoices(actor=request.user, status=status, customer_id=customer_id, search=search)
        invoices = list(invoices[:500])
    except ValidationError:
        invoices, customer_id = [], None
    return render(request, "web/receivables/invoice_list.html", {
        "invoices": invoices, "status_choices": InvoiceStatus.choices, "current_status": status,
        "customers": list_customers(actor=request.user), "current_customer": customer_id or "", "search": search,
    })


def _invoice_args(form):
    data = form.cleaned_data
    return {key: data[key] for key in ("number", "customer", "amount", "document_date", "due_date", "reference", "branch", "note")}


@capability_required(can_manage_receivables)
@require_http_methods(["GET", "POST"])
def invoice_form_view(request: HttpRequest, invoice_id=None) -> HttpResponse:
    invoice = get_object_or_404(list_invoices(actor=request.user), pk=invoice_id) if invoice_id else None
    if invoice is not None and invoice.status == InvoiceStatus.CANCELLED:
        messages.error(request, "ใบขายที่ยกเลิกแล้วแก้ไขไม่ได้")
        return redirect("web:sales-invoice-detail", invoice_id=invoice.pk)
    customers = selectable_customers(actor=request.user, include_id=invoice.customer_id if invoice else None)
    form = InvoiceForm(request.POST or None, customer_queryset=customers, invoice=invoice)
    if request.method == "POST" and form.is_valid():
        try:
            if invoice is None:
                saved = create_invoice(actor=request.user, **_invoice_args(form))
            else:
                saved = update_invoice(actor=request.user, invoice=invoice, reason=form.cleaned_data["reason"], **_invoice_args(form))
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"บันทึก {saved.number} แล้ว")
            if "save_and_new" in request.POST:
                return redirect("web:sales-invoice-create")
            return redirect("web:sales-invoice-detail", invoice_id=saved.pk)
    return render(request, "web/receivables/invoice_form.html",
                  {"form": form, "invoice": invoice, "has_customers": customers.exists()})


def _render_invoice(request, invoice, *, receive_form=None, reason_form=None, open_box="", status=200):
    return render(request, "web/receivables/invoice_detail.html", {
        "invoice": invoice,
        "history": _history_rows(history(actor=request.user, entity_type=INVOICE_ENTITY, entity_id=invoice.pk)),
        "can_manage": can_manage_receivables(request.user),
        "receive_form": receive_form or ReceiveForm(initial={"received_amount": invoice.amount}),
        "reason_form": reason_form or ReasonForm(),
        "open_box": open_box,
    }, status=status)


@capability_required(can_view_receivables)
def invoice_detail_view(request: HttpRequest, invoice_id) -> HttpResponse:
    return _render_invoice(request, get_object_or_404(list_invoices(actor=request.user), pk=invoice_id))


@capability_required(can_manage_receivables)
@require_POST
def invoice_action_view(request: HttpRequest, invoice_id, action: str) -> HttpResponse:
    if action not in INVOICE_ACTIONS:
        raise Http404("ไม่รู้จักคำสั่งนี้")
    invoice = get_object_or_404(list_invoices(actor=request.user), pk=invoice_id)
    form = ReceiveForm(request.POST) if action == "receive" else ReasonForm(request.POST)
    if not form.is_valid():
        kwargs = {"receive_form": form} if action == "receive" else {"reason_form": form}
        return _render_invoice(request, invoice, open_box=action, status=400, **kwargs)
    data = form.cleaned_data
    try:
        if action == "receive":
            receive_invoice(actor=request.user, invoice=invoice, received_date=data["received_date"],
                            received_amount=data["received_amount"], reason=data["reason"])
        elif action == "reopen":
            reopen_invoice(actor=request.user, invoice=invoice, reason=data["reason"])
        elif action == "cancel":
            cancel_invoice(actor=request.user, invoice=invoice, reason=data["reason"])
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"{ACTION_LABELS.get(action, action)} {invoice.number} แล้ว")
    return redirect("web:sales-invoice-detail", invoice_id=invoice.pk)


@capability_required(can_manage_receivables)
@require_http_methods(["GET", "POST"])
def invoice_import_view(request: HttpRequest) -> HttpResponse:
    customers = selectable_customers(actor=request.user)
    form = InvoiceImportForm(request.POST or None, request.FILES or None, customer_queryset=customers)
    plan, warnings = None, []
    if request.method == "POST" and form.is_valid():
        try:
            rows, warnings = invoice_import.parse_invoice_file(form.cleaned_data["file"])
        except WorkbookError as exc:
            form.add_error("file", str(exc))
        else:
            customer = form.cleaned_data["customer"]
            plan = invoice_import.build_plan(actor=request.user, customer=customer, rows=rows)
            request.session[IMPORT_SESSION_KEY] = {
                "customer": str(customer.pk), "file_name": form.cleaned_data["file"].name,
                "rows": invoice_import.rows_to_session(rows),
            }
    counts = {key: sum(1 for item in plan or [] if item.action == key) for key in ("create", "update", "unchanged", "skip")}
    return render(request, "web/receivables/invoice_import.html",
                  {"form": form, "plan": plan, "warnings": warnings, "counts": counts})


@capability_required(can_manage_receivables)
@require_POST
def invoice_import_confirm_view(request: HttpRequest) -> HttpResponse:
    pending = request.session.pop(IMPORT_SESSION_KEY, None)
    if not pending:
        messages.error(request, "ไม่พบไฟล์ที่รอนำเข้า กรุณาอัปโหลดใหม่")
        return redirect("web:sales-invoice-import")
    customer = get_object_or_404(list_customers(actor=request.user), pk=pending["customer"])
    counts = invoice_import.apply_import(actor=request.user, customer=customer, file_name=pending["file_name"],
                                         rows=invoice_import.rows_from_session(pending["rows"]))
    messages.success(request, f"นำเข้าแล้ว: เพิ่ม {counts['create']} อัปเดต {counts['update']} "
                              f"ไม่เปลี่ยน {counts['unchanged']} ข้าม {counts['skip']}")
    return redirect(f"{reverse('web:sales-invoice-list')}?customer={customer.pk}")


# ---------------------------------------------------------------- แผนรับเงิน

@capability_required(can_view_receivables)
def plan_list_view(request: HttpRequest) -> HttpResponse:
    summaries = list_plans(actor=request.user)
    return render(request, "web/receivables/plan_list.html", {"summaries": summaries})


@capability_required(can_manage_receivables)
@require_http_methods(["GET", "POST"])
def plan_form_view(request: HttpRequest, plan_id=None) -> HttpResponse:
    plan = get_plan(actor=request.user, plan_id=plan_id) if plan_id else None
    form = PlanForm(request.POST or None, plan=plan,
                    customer_queryset=None if plan else selectable_customers(actor=request.user))
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            if plan is None:
                plan = create_plan(actor=request.user, customer=data["customer"], plan_date=data["plan_date"],
                                   amount=data["amount"], note=data["note"])
            else:
                plan = update_plan(actor=request.user, plan=plan, plan_date=data["plan_date"], amount=data["amount"],
                                   note=data["note"], reason=data["reason"])
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, "บันทึกแผนรับเงินแล้ว")
            return redirect("web:receipt-plan-detail", plan_id=plan.pk)
    return render(request, "web/receivables/plan_form.html", {"form": form, "plan": plan})


@capability_required(can_view_receivables)
def plan_detail_view(request: HttpRequest, plan_id) -> HttpResponse:
    try:
        plan = get_plan(actor=request.user, plan_id=plan_id)
    except ReceiptPlan.DoesNotExist:
        return redirect("web:receipt-plan-list")
    if request.method == "POST":
        if not can_manage_receivables(request.user):
            return HttpResponse(status=403)
        try:
            set_plan_invoices(actor=request.user, plan=plan, invoice_ids=request.POST.getlist("invoices"))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "บันทึกใบขายที่ผูกกับแผนแล้ว")
        return redirect("web:receipt-plan-detail", plan_id=plan.pk)
    return render(request, "web/receivables/plan_detail.html", {
        "summary": summarize_plan(plan),
        "candidates": linkable_invoices(actor=request.user, plan=plan),
        "history": _history_rows(history(actor=request.user, entity_type=PLAN_ENTITY, entity_id=plan.pk)),
        "can_manage": can_manage_receivables(request.user),
    })


# ---------------------------------------------------------------- รายการรายวัน

def _can_view_daily(user) -> bool:
    return can_view_receivables(user) or can_view_purchase_orders(user)


def _parse_day(value: str, default: date) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@capability_required(_can_view_daily)
def daily_view(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    start = _parse_day(request.GET.get("start"), today - timedelta(days=3))
    end = _parse_day(request.GET.get("end"), today + timedelta(days=30))
    if end < start:
        start, end = end, start
    end = min(end, start + timedelta(days=366))
    mode = "list" if request.GET.get("mode") == "list" else "summary"
    try:
        opening = Decimal(request.GET.get("opening", "0").replace(",", "") or "0")
    except InvalidOperation:
        opening = Decimal("0")

    rows = []
    if can_view_receivables(request.user):
        for entry in cash_entries(actor=request.user, start=start, end=end):
            rows.append({"day": entry.day, "direction": entry.direction, "kind": entry.kind, "amount": entry.amount,
                         "title": entry.title, "detail": entry.detail, "url_name": entry.url_name, "object_id": entry.object_id})
    if can_view_purchase_orders(request.user):
        for row in outflow_entries(actor=request.user, start=start, end=end):
            rows.append({"day": row.due_date, "direction": "out", "kind": "expected", "amount": row.amount,
                         "title": row.number, "detail": row.supplier_name, "url_name": "web:purchase-order-detail",
                         "object_id": row.purchase_order_id})
    rows.sort(key=lambda r: (r["day"], r["direction"] == "out", r["title"]))

    days, balance = [], opening
    for row in rows:
        if not days or days[-1]["day"] != row["day"]:
            days.append({"day": row["day"], "rows": [], "in": Decimal("0"), "out": Decimal("0"), "opening": balance})
        bucket = days[-1]
        bucket["rows"].append(row)
        if row["direction"] == "in":
            bucket["in"] += row["amount"]
            balance += row["amount"]
        else:
            bucket["out"] += row["amount"]
            balance -= row["amount"]
        row["balance"] = balance
        bucket["closing"] = balance
        bucket["net"] = bucket["in"] - bucket["out"]
    overdue_in = list(overdue_invoices(actor=request.user, before=start)) if can_view_receivables(request.user) else []
    overdue_out = (
        [row for row in expected_outflows(actor=request.user) if row.due_date < start]
        if can_view_purchase_orders(request.user) else []
    )
    return render(request, "web/cashflow/daily.html", {
        "overdue_in_count": len(overdue_in), "overdue_in_total": sum((i.amount for i in overdue_in), Decimal("0")),
        "overdue_out_count": len(overdue_out), "overdue_out_total": sum((r.amount for r in overdue_out), Decimal("0")),
        "days": days, "start": start, "end": end, "mode": mode, "opening": opening, "today": today,
        "total_in": sum((d["in"] for d in days), Decimal("0")),
        "total_out": sum((d["out"] for d in days), Decimal("0")), "closing": balance,
    })
