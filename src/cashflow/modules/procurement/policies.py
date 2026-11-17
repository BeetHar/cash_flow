from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from .constants import (
    MANAGE_PURCHASE_ORDERS_PERMISSION,
    MANAGE_SUPPLIERS_PERMISSION,
    VIEW_PURCHASE_ORDERS_PERMISSION,
)

Principal = AbstractBaseUser | AnonymousUser


def _has(principal: Principal, *permissions: str) -> bool:
    if not principal.is_authenticated:
        return False
    if principal.is_superuser:
        return True
    return any(principal.has_perm(permission) for permission in permissions)


def can_manage_purchase_orders(principal: Principal) -> bool:
    return _has(principal, MANAGE_PURCHASE_ORDERS_PERMISSION)


def can_manage_suppliers(principal: Principal) -> bool:
    return _has(principal, MANAGE_SUPPLIERS_PERMISSION)


def can_view_purchase_orders(principal: Principal) -> bool:
    """สิทธิ์จัดการใด ๆ ในโมดูลนี้รวมสิทธิ์ดูไว้ด้วย"""

    return _has(
        principal,
        VIEW_PURCHASE_ORDERS_PERMISSION,
        MANAGE_PURCHASE_ORDERS_PERMISSION,
        MANAGE_SUPPLIERS_PERMISSION,
    )
