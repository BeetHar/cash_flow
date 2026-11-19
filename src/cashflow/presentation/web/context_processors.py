from django.http import HttpRequest

from cashflow.modules.identity.policies import can_manage_roles, can_manage_users
from cashflow.modules.procurement.policies import (
    can_manage_purchase_orders,
    can_manage_suppliers,
    can_view_purchase_orders,
)
from cashflow.modules.receivables.policies import can_manage_receivables, can_view_receivables


def identity_capabilities(request: HttpRequest) -> dict[str, bool]:
    principal = request.user
    return {
        "can_manage_users": can_manage_users(principal),
        "can_manage_roles": can_manage_roles(principal),
        "is_system_developer": bool(
            principal.is_authenticated and principal.is_superuser
        ),
    }


def procurement_capabilities(request: HttpRequest) -> dict[str, bool]:
    principal = request.user
    return {
        "can_view_purchase_orders": can_view_purchase_orders(principal),
        "can_manage_purchase_orders": can_manage_purchase_orders(principal),
        "can_manage_suppliers": can_manage_suppliers(principal),
    }


def receivables_capabilities(request: HttpRequest) -> dict[str, bool]:
    return {
        "can_view_receivables": can_view_receivables(request.user),
        "can_manage_receivables": can_manage_receivables(request.user),
    }


def application_version(request: HttpRequest) -> dict[str, str | int]:
    from django.conf import settings

    return {
        "app_version": settings.APP_VERSION,
        "app_update_count": settings.APP_UPDATE_COUNT,
    }
