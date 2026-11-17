from collections.abc import Iterable

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet

from cashflow.modules.audit.services import record_event

from ..constants import (
    BUSINESS_ADMIN_ROLE_NAME,
    MANAGEMENT_PERMISSION_CODENAMES,
)
from ..models import User
from ..policies import can_manage_roles, can_manage_users


def _require_user_management(actor: User) -> None:
    if not can_manage_users(actor):
        raise PermissionDenied("ไม่มีสิทธิ์จัดการผู้ใช้")


def _require_role_management(actor: User) -> None:
    if not can_manage_roles(actor):
        raise PermissionDenied("ไม่มีสิทธิ์จัดการบทบาท")


def _user_snapshot(user: User) -> dict[str, object]:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "is_active": user.is_active,
        "roles": sorted(user.groups.values_list("name", flat=True)),
    }


def _role_snapshot(role: Group) -> dict[str, object]:
    return {
        "name": role.name,
        "permissions": sorted(
            role.permissions.values_list("codename", flat=True)
        ),
    }


def manageable_users(*, actor: User) -> QuerySet[User]:
    _require_user_management(actor)
    users = User.objects.prefetch_related("groups").order_by("username")
    if not actor.is_superuser:
        users = users.filter(is_superuser=False)
    return users


def manageable_roles(*, actor: User) -> QuerySet[Group]:
    _require_role_management(actor)
    return Group.objects.prefetch_related("permissions").order_by("name")


def assignable_roles(*, actor: User) -> QuerySet[Group]:
    _require_user_management(actor)
    return Group.objects.order_by("name")


def available_role_permissions(*, actor: User) -> QuerySet[Permission]:
    _require_role_management(actor)
    module_labels = {
        config.label
        for config in apps.get_app_configs()
        if config.name.startswith("cashflow.modules.")
        and config.label not in {"identity", "audit"}
    }
    query = Q(
        content_type__app_label="identity",
        codename__in=MANAGEMENT_PERMISSION_CODENAMES,
    )
    if module_labels:
        query |= Q(content_type__app_label__in=module_labels)
    return Permission.objects.filter(query).select_related("content_type").order_by(
        "content_type__app_label", "name"
    )


def _validated_roles(*, actor: User, roles: Iterable[Group]) -> list[Group]:
    allowed_ids = set(assignable_roles(actor=actor).values_list("id", flat=True))
    role_list = list(roles)
    if any(role.pk not in allowed_ids for role in role_list):
        raise ValidationError("พบบทบาทที่ไม่สามารถกำหนดได้")
    return role_list


def _validated_permissions(
    *, actor: User, permissions: Iterable[Permission]
) -> list[Permission]:
    allowed_ids = set(
        available_role_permissions(actor=actor).values_list("id", flat=True)
    )
    permission_list = list(permissions)
    if any(permission.pk not in allowed_ids for permission in permission_list):
        raise ValidationError("พบสิทธิ์ที่ไม่สามารถกำหนดผ่านหน้าแอปได้")
    return permission_list


@transaction.atomic
def create_application_user(
    *,
    actor: User,
    username: str,
    password: str,
    display_name: str = "",
    email: str = "",
    is_active: bool = True,
    roles: Iterable[Group] = (),
) -> User:
    _require_user_management(actor)
    role_list = _validated_roles(actor=actor, roles=roles)
    try:
        user = User(
            username=username.strip(),
            display_name=display_name.strip(),
            email=email.strip(),
            is_active=is_active,
            is_staff=False,
            is_superuser=False,
        )
        validate_password(password, user)
        user.set_password(password)
        user.full_clean()
        user.save()
    except IntegrityError as exc:
        raise ValidationError("ชื่อผู้ใช้นี้ถูกใช้งานแล้ว") from exc
    user.groups.set(role_list)
    record_event(
        actor=actor,
        action="create",
        entity_type="identity.user",
        entity_id=str(user.pk),
        entity_label=user.username,
        after=_user_snapshot(user),
    )
    return user


@transaction.atomic
def update_application_user(
    *,
    actor: User,
    user: User,
    display_name: str,
    email: str,
    is_active: bool,
    roles: Iterable[Group],
) -> User:
    _require_user_management(actor)
    if user.is_superuser and not actor.is_superuser:
        raise PermissionDenied("บัญชีนักพัฒนาจัดการได้จาก System Admin เท่านั้น")

    role_list = _validated_roles(actor=actor, roles=roles)
    current_role_ids = set(user.groups.values_list("id", flat=True))
    requested_role_ids = {role.pk for role in role_list}
    if user.pk == actor.pk:
        if not is_active:
            raise ValidationError("ไม่สามารถปิดบัญชีที่กำลังใช้งานอยู่ได้")
        if requested_role_ids != current_role_ids:
            raise ValidationError("ไม่สามารถเปลี่ยนบทบาทของบัญชีที่กำลังใช้งานอยู่ได้")

    before = _user_snapshot(user)
    user.display_name = display_name.strip()
    user.email = email.strip()
    user.is_active = is_active
    user.save(update_fields=["display_name", "email", "is_active"])
    user.groups.set(role_list)
    record_event(
        actor=actor,
        action="update",
        entity_type="identity.user",
        entity_id=str(user.pk),
        entity_label=user.username,
        before=before,
        after=_user_snapshot(user),
    )
    return user


@transaction.atomic
def reset_application_password(*, actor: User, user: User, password: str) -> None:
    _require_user_management(actor)
    if user.is_superuser and not actor.is_superuser:
        raise PermissionDenied("บัญชีนักพัฒนาจัดการได้จาก System Admin เท่านั้น")
    validate_password(password, user)
    user.set_password(password)
    user.save(update_fields=["password"])
    record_event(
        actor=actor,
        action="password_reset",
        entity_type="identity.user",
        entity_id=str(user.pk),
        entity_label=user.username,
        after={"password_changed": True},
    )


@transaction.atomic
def create_application_role(
    *, actor: User, name: str, permissions: Iterable[Permission]
) -> Group:
    _require_role_management(actor)
    permission_list = _validated_permissions(actor=actor, permissions=permissions)
    try:
        role = Group.objects.create(name=name.strip())
    except IntegrityError as exc:
        raise ValidationError("ชื่อบทบาทนี้ถูกใช้งานแล้ว") from exc
    role.permissions.set(permission_list)
    record_event(
        actor=actor,
        action="create",
        entity_type="identity.role",
        entity_id=str(role.pk),
        entity_label=role.name,
        after=_role_snapshot(role),
    )
    return role


@transaction.atomic
def update_application_role(
    *, actor: User, role: Group, name: str, permissions: Iterable[Permission]
) -> Group:
    _require_role_management(actor)
    if role.name == BUSINESS_ADMIN_ROLE_NAME and not actor.is_superuser:
        raise PermissionDenied("บทบาทผู้ดูแลระบบแก้ไขได้จาก Developer console เท่านั้น")
    permission_list = _validated_permissions(actor=actor, permissions=permissions)
    before = _role_snapshot(role)
    role.name = name.strip()
    try:
        role.save(update_fields=["name"])
    except IntegrityError as exc:
        raise ValidationError("ชื่อบทบาทนี้ถูกใช้งานแล้ว") from exc
    role.permissions.set(permission_list)
    record_event(
        actor=actor,
        action="update",
        entity_type="identity.role",
        entity_id=str(role.pk),
        entity_label=role.name,
        before=before,
        after=_role_snapshot(role),
    )
    return role

