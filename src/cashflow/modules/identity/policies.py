from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from .constants import MANAGE_ROLES_PERMISSION, MANAGE_USERS_PERMISSION


Principal = AbstractBaseUser | AnonymousUser


def can_manage_users(principal: Principal) -> bool:
    return bool(
        principal.is_authenticated
        and (principal.is_superuser or principal.has_perm(MANAGE_USERS_PERMISSION))
    )


def can_manage_roles(principal: Principal) -> bool:
    return bool(
        principal.is_authenticated
        and (principal.is_superuser or principal.has_perm(MANAGE_ROLES_PERMISSION))
    )

