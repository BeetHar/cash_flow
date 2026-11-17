from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from cashflow.modules.procurement.models import ApprovalStatus, PurchaseOrderStatus
from cashflow.modules.procurement.policies import (
    can_manage_purchase_orders,
    can_manage_suppliers,
    can_view_purchase_orders,
)
from cashflow.modules.procurement.services import (
    OUTSTANDING_STATUSES,
    cancel_purchase_order,
    create_purchase_order,
    create_supplier,
    list_purchase_orders,
    list_suppliers,
    purchase_order_history,
    selectable_suppliers,
    update_purchase_order,
    update_supplier,
)

from cashflow.modules.procurement.supplier_import import (
    apply_supplier_import,
    build_import_plan,
    parse_supplier_file,
    rows_from_session,
    rows_to_session,
)
from cashflow.modules.procurement.xlsx_reader import WorkbookError

from .access import capability_required
from .procurement_forms import (
    CancelPurchaseOrderForm,
    PurchaseOrderForm,
    SupplierForm,
    SupplierImportForm,
)
from .templatetags.web_format import money, thai_date, thai_datetime

PROGRESS_STEPS = (
    PurchaseOrderStatus.NEW,
    PurchaseOrderStatus.RECEIVED,
    PurchaseOrderStatus.CLOSED,
)

HISTORY_LABELS = {
    "create": "บันทึกใบสั่งซื้อ",
    "update": "แก้ไขข้อมูล",
    "cancel": "ยกเลิกใบสั่งซื้อ",
    # เหตุการณ์จากรุ่นก่อนหน้าที่อาจยังอยู่ในฐานข้อมูล
    "send": "ส่งให้ผู้ขาย",
    "receive": "บันทึกรับของ",
    "close": "ปิดใบสั่งซื้อ",
}

FIELD_LABELS = {
    "number": "หมายเลข PO",
    "supplier": "ผู้ขาย",
    "total_amount": "ยอดรวม",
    "ordered_at": "วันเวลาทำรายการ",
    "delivery_date": "วันที่จัดส่ง",
    "due_date": "ครบกำหนดจ่าย",
    "status": "สถานะ",
    "approval_status": "สถานะอนุมัติ",
    "note": "หมายเหตุ",
}

STATUS_LABELS = {
    **dict(PurchaseOrderStatus.choices),
    **dict(ApprovalStatus.choices),
    "draft": "ร่าง",
    "sent": "ส่งแล้ว",
}


def _add_service_error(form, error: ValidationError) -> None:
    if hasattr(error, "error_dict"):
        for field, field_errors in error.error_dict.items():
            target = field if field in form.fields else None
            for field_error in field_errors:
                form.add_error(target, field_error)
    else:
        form.add_error(None, error)


def _format_value(field: str, value) -> str:
    """แปลงค่าที่เก็บใน audit เป็นข้อความอ่านง่าย ค่าที่แปลงไม่ได้แสดงตามเดิม"""

    if value in (None, ""):
        return "—"
    try:
        if field == "total_amount":
            return money(Decimal(str(value)))
        if field in ("delivery_date", "due_date"):
            return thai_date(date.fromisoformat(str(value)))
        if field == "ordered_at":
            return thai_datetime(datetime.fromisoformat(str(value)))
    except (InvalidOperation, ValueError):
        return str(value)
    if field in ("status", "approval_status"):
        return STATUS_LABELS.get(str(value), str(value))
    return str(value)


# ---------------------------------------------------------------- ผู้ขาย

@capability_required(can_view_purchase_orders)
def supplier_list_view(request: HttpRequest) -> HttpResponse:
    search = request.GET.get("q", "")
    credit_unknown = request.GET.get("credit") == "unknown"
    return render(
        request,
        "web/procurement/supplier_list.html",
        {
            "suppliers": list_suppliers(
                actor=request.user, search=search, credit_unknown=credit_unknown
            ),
            "search": search,
            "credit_unknown": credit_unknown,
            "credit_unknown_count": list_suppliers(
                actor=request.user, credit_unknown=True
            ).count(),
        },
    )


@capability_required(can_manage_suppliers)
@require_http_methods(["GET", "POST"])
def supplier_create_view(request: HttpRequest) -> HttpResponse:
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            supplier = create_supplier(
                actor=request.user,
                code=data["code"],
                name=data["name"],
                tax_id=data["tax_id"],
                branch=data["branch"],
                address=data["address"],
                contact_name=data["contact_name"],
                phone=data["phone"],
                email=data["email"],
                credit_days=data["credit_days"],
                supplier_type=data["supplier_type"],
                description=data["description"],
            )
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"เพิ่มผู้ขาย {supplier.name} แล้ว")
            next_url = request.GET.get("next")
            if next_url == "po-create":
                return redirect("web:purchase-order-create")
            return redirect("web:supplier-list")
    return render(
        request,
        "web/procurement/supplier_form.html",
        {"form": form, "mode": "create", "supplier": None},
    )


@capability_required(can_manage_suppliers)
@require_http_methods(["GET", "POST"])
def supplier_edit_view(request: HttpRequest, supplier_id) -> HttpResponse:
    supplier = get_object_or_404(list_suppliers(actor=request.user), pk=supplier_id)
    form = SupplierForm(request.POST or None, supplier=supplier)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            update_supplier(
                actor=request.user,
                supplier=supplier,
                code=data["code"],
                name=data["name"],
                tax_id=data["tax_id"],
                branch=data["branch"],
                address=data["address"],
                contact_name=data["contact_name"],
                phone=data["phone"],
                email=data["email"],
                credit_days=data["credit_days"],
                supplier_type=data["supplier_type"],
                description=data["description"],
                is_active=data["is_active"],
            )
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"บันทึกข้อมูลผู้ขาย {data['name']} แล้ว")
            return redirect("web:supplier-list")
    return render(
        request,
        "web/procurement/supplier_form.html",
        {"form": form, "mode": "edit", "supplier": supplier},
    )


# ---------------------------------------------------------------- ใบสั่งซื้อ

@capability_required(can_view_purchase_orders)
def purchase_order_list_view(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "")
    if status not in PurchaseOrderStatus.values:
        status = ""
    approval = request.GET.get("approval", "")
    if approval not in ApprovalStatus.values:
        approval = ""
    search = request.GET.get("q", "")
    orders = list_purchase_orders(
        actor=request.user, status=status, approval=approval, search=search
    )
    return render(
        request,
        "web/procurement/purchase_order_list.html",
        {
            "orders": orders,
            "status_choices": PurchaseOrderStatus.choices,
            "approval_choices": ApprovalStatus.choices,
            "current_status": status,
            "current_approval": approval,
            "search": search,
        },
    )


def _service_arguments(form) -> dict[str, object]:
    data = form.cleaned_data
    return {
        "number": data["number"],
        "supplier": data["supplier"],
        "total_amount": data["total_amount"],
        "ordered_at": data["ordered_at"],
        "delivery_date": data["delivery_date"],
        "due_date": data["due_date"],
        "status": data["status"],
        "approval_status": data["approval_status"],
        "note": data["note"],
    }


@capability_required(can_manage_purchase_orders)
@require_http_methods(["GET", "POST"])
def purchase_order_create_view(request: HttpRequest) -> HttpResponse:
    suppliers = selectable_suppliers(actor=request.user)
    form = PurchaseOrderForm(request.POST or None, supplier_queryset=suppliers)
    if request.method == "POST" and form.is_valid():
        try:
            purchase_order = create_purchase_order(
                actor=request.user, **_service_arguments(form)
            )
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"บันทึก {purchase_order.number} แล้ว")
            if "save_and_new" in request.POST:
                return redirect("web:purchase-order-create")
            return redirect("web:purchase-order-detail", purchase_order_id=purchase_order.pk)
    return render(
        request,
        "web/procurement/purchase_order_form.html",
        {
            "form": form,
            "mode": "create",
            "purchase_order": None,
            "has_suppliers": suppliers.exists(),
        },
    )


@capability_required(can_manage_purchase_orders)
@require_http_methods(["GET", "POST"])
def purchase_order_edit_view(request: HttpRequest, purchase_order_id) -> HttpResponse:
    purchase_order = get_object_or_404(
        list_purchase_orders(actor=request.user), pk=purchase_order_id
    )
    if not purchase_order.is_editable:
        messages.error(request, "ใบสั่งซื้อที่ยกเลิกแล้วแก้ไขไม่ได้")
        return redirect("web:purchase-order-detail", purchase_order_id=purchase_order.pk)

    suppliers = selectable_suppliers(actor=request.user, include_id=purchase_order.supplier_id)
    form = PurchaseOrderForm(
        request.POST or None, supplier_queryset=suppliers, purchase_order=purchase_order
    )
    if request.method == "POST" and form.is_valid():
        try:
            saved = update_purchase_order(
                actor=request.user,
                purchase_order=purchase_order,
                reason=form.cleaned_data["reason"],
                **_service_arguments(form),
            )
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"บันทึกการแก้ไข {saved.number} แล้ว")
            return redirect("web:purchase-order-detail", purchase_order_id=saved.pk)
    return render(
        request,
        "web/procurement/purchase_order_form.html",
        {
            "form": form,
            "mode": "edit",
            "purchase_order": purchase_order,
            "has_suppliers": True,
        },
    )


def _history_rows(events) -> list[dict[str, object]]:
    rows = []
    for event in events:
        changes = []
        if event.action == "update":
            changes = [
                {
                    "label": label,
                    "before": _format_value(field, event.before.get(field)),
                    "after": _format_value(field, event.after.get(field)),
                }
                for field, label in FIELD_LABELS.items()
                if field in event.after and event.before.get(field) != event.after.get(field)
            ]
        rows.append(
            {
                "label": HISTORY_LABELS.get(event.action, event.action),
                "action": event.action,
                "actor": event.actor.get_display_name() if event.actor else event.actor_identifier,
                "occurred_at": event.occurred_at,
                "reason": event.after.get("reason", ""),
                "changes": changes,
            }
        )
    return rows


def _progress(status: str) -> list[dict[str, object]]:
    if status not in PROGRESS_STEPS:
        return []
    current = PROGRESS_STEPS.index(status)
    return [
        {
            "label": PurchaseOrderStatus(step).label,
            "state": "done" if index < current else "current" if index == current else "todo",
        }
        for index, step in enumerate(PROGRESS_STEPS)
    ]


SUPPLIER_IMPORT_SESSION_KEY = "procurement_supplier_import"


@capability_required(can_manage_suppliers)
@require_http_methods(["GET", "POST"])
def supplier_import_view(request: HttpRequest) -> HttpResponse:
    form = SupplierImportForm(request.POST or None, request.FILES or None)
    plan = None
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            rows, warnings = parse_supplier_file(upload)
        except WorkbookError as exc:
            form.add_error("file", str(exc))
        else:
            plan = build_import_plan(actor=request.user, rows=rows, warnings=warnings)
            request.session[SUPPLIER_IMPORT_SESSION_KEY] = {
                "file_name": upload.name,
                "rows": rows_to_session(rows),
            }
    return render(
        request,
        "web/procurement/supplier_import.html",
        {
            "form": form,
            "plan": plan,
            "file_name": request.FILES["file"].name if plan else "",
        },
    )


@capability_required(can_manage_suppliers)
@require_POST
def supplier_import_confirm_view(request: HttpRequest) -> HttpResponse:
    pending = request.session.pop(SUPPLIER_IMPORT_SESSION_KEY, None)
    if not pending:
        messages.error(request, "ไม่พบไฟล์ที่รอนำเข้า กรุณาอัปโหลดใหม่อีกครั้ง")
        return redirect("web:supplier-import")
    result = apply_supplier_import(
        actor=request.user,
        rows=rows_from_session(pending["rows"]),
        file_name=pending["file_name"],
    )
    messages.success(
        request,
        f"นำเข้าเสร็จแล้ว: เพิ่มใหม่ {result['created']} ราย "
        f"อัปเดต {result['updated']} ราย ไม่เปลี่ยน {result['unchanged']} ราย",
    )
    return redirect("web:supplier-list")


def _outflow_state(purchase_order) -> tuple[str, str]:
    if purchase_order.status not in OUTSTANDING_STATUSES:
        return "ไม่นับ", "ปิดหรือยกเลิกแล้ว"
    if purchase_order.approval_status != ApprovalStatus.APPROVED:
        return "ยังไม่นับ", "รออนุมัติ"
    return "นับ", "แสดงในหน้ากระแสเงินสด"


def _render_detail(
    request: HttpRequest, purchase_order, *, cancel_form=None, status: int = 200
) -> HttpResponse:
    can_manage = can_manage_purchase_orders(request.user)
    outflow_state, outflow_note = _outflow_state(purchase_order)
    return render(
        request,
        "web/procurement/purchase_order_detail.html",
        {
            "purchase_order": purchase_order,
            "due_is_default": not purchase_order.due_date_manual,
            "progress": _progress(purchase_order.status),
            "history": _history_rows(
                purchase_order_history(actor=request.user, purchase_order=purchase_order)
            ),
            "can_edit": can_manage and purchase_order.is_editable,
            "outflow_state": outflow_state,
            "outflow_note": outflow_note,
            "cancel_form": cancel_form or CancelPurchaseOrderForm(),
            "cancel_open": cancel_form is not None,
        },
        status=status,
    )


@capability_required(can_view_purchase_orders)
def purchase_order_detail_view(request: HttpRequest, purchase_order_id) -> HttpResponse:
    purchase_order = get_object_or_404(
        list_purchase_orders(actor=request.user).select_related("created_by"),
        pk=purchase_order_id,
    )
    return _render_detail(request, purchase_order)


@capability_required(can_manage_purchase_orders)
@require_POST
def purchase_order_cancel_view(request: HttpRequest, purchase_order_id) -> HttpResponse:
    purchase_order = get_object_or_404(
        list_purchase_orders(actor=request.user).select_related("created_by"),
        pk=purchase_order_id,
    )
    cancel_form = CancelPurchaseOrderForm(request.POST)
    if not cancel_form.is_valid():
        return _render_detail(request, purchase_order, cancel_form=cancel_form, status=400)
    try:
        cancel_purchase_order(
            actor=request.user,
            purchase_order=purchase_order,
            reason=cancel_form.cleaned_data["reason"],
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"ยกเลิก {purchase_order.number} แล้ว")
    return redirect("web:purchase-order-detail", purchase_order_id=purchase_order.pk)
