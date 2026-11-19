from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

VIEW_RECEIVABLES_PERMISSION = "receivables.view_receivables"
MANAGE_RECEIVABLES_PERMISSION = "receivables.manage_receivables"


def _has(principal: AbstractBaseUser | AnonymousUser, *permissions: str) -> bool:
    if not principal.is_authenticated:
        return False
    return principal.is_superuser or any(principal.has_perm(p) for p in permissions)


def can_manage_receivables(principal) -> bool:
    return _has(principal, MANAGE_RECEIVABLES_PERMISSION)


def can_view_receivables(principal) -> bool:
    return _has(principal, VIEW_RECEIVABLES_PERMISSION, MANAGE_RECEIVABLES_PERMISSION)
