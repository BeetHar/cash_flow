from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from cashflow.modules.identity.services import (
    authenticate_credentials,
    end_session,
    start_session,
)
from cashflow.modules.procurement.policies import can_view_purchase_orders
from cashflow.modules.procurement.services import expected_outflows

from .forms import LoginForm


def _safe_redirect_target(request: HttpRequest) -> str:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(
        url=target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse("web:dashboard")


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("web:dashboard")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate_credentials(
            request=request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if user is not None:
            start_session(request=request, user=user)
            return redirect(_safe_redirect_target(request))
        form.add_error(None, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    return render(
        request,
        "web/auth/login.html",
        {"form": form, "next": request.POST.get("next") or request.GET.get("next", "")},
    )


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    end_session(request=request)
    return redirect("web:login")


@login_required
def dashboard_view(request: HttpRequest) -> HttpResponse:
    cashflow_rows = [
        {
            "date": "1 ต.ค. 2569",
            "description": "ยอดเงินคงเหลือยกมา",
            "inflow": None,
            "outflow": None,
            "balance": "1,250,000.00",
        },
        {
            "date": "2 ต.ค. 2569",
            "description": "รับชำระจากลูกค้า A",
            "inflow": "485,000.00",
            "outflow": None,
            "balance": "1,735,000.00",
        },
        {
            "date": "3 ต.ค. 2569",
            "description": "ค่าเช่าสำนักงาน",
            "inflow": None,
            "outflow": "85,000.00",
            "balance": "1,650,000.00",
        },
        {
            "date": "4 ต.ค. 2569",
            "description": "ชำระค่าสินค้า Supplier A",
            "inflow": None,
            "outflow": "240,000.00",
            "balance": "1,410,000.00",
        },
        {
            "date": "5 ต.ค. 2569",
            "description": "รับชำระจากลูกค้า B",
            "inflow": "320,000.00",
            "outflow": None,
            "balance": "1,730,000.00",
        },
        {
            "date": "6 ต.ค. 2569",
            "description": "เงินเดือนพนักงาน",
            "inflow": None,
            "outflow": "410,000.00",
            "balance": "1,320,000.00",
        },
    ]
    po_outflows = (
        expected_outflows(actor=request.user)
        if can_view_purchase_orders(request.user)
        else None
    )
    return render(
        request,
        "web/dashboard.html",
        {
            "po_outflows": po_outflows,
            "po_outflow_total": sum(
                (row.amount for row in po_outflows or []), Decimal("0.00")
            ),
            "cashflow_rows": cashflow_rows,
            "total_inflow": "805,000.00",
            "total_outflow": "735,000.00",
            "closing_balance": "1,320,000.00",
        },
    )


def health_view(request: HttpRequest) -> JsonResponse:
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse({"status": "unhealthy", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "connected"})

