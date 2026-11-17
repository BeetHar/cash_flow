from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from cashflow.modules.identity.constants import BUSINESS_ADMIN_ROLE_NAME
from cashflow.modules.identity.policies import can_manage_roles, can_manage_users
from cashflow.modules.identity.services import (
    assignable_roles,
    available_role_permissions,
    create_application_role,
    create_application_user,
    manageable_roles,
    manageable_users,
    reset_application_password,
    update_application_role,
    update_application_user,
)

from .access import capability_required
from .forms import PasswordResetForm, RoleForm, UserCreateForm, UserUpdateForm


def _add_service_error(form, error: ValidationError) -> None:
    form.add_error(None, error)


@capability_required(can_manage_users)
def user_list_view(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "web/identity/user_list.html",
        {"users": manageable_users(actor=request.user)},
    )


@capability_required(can_manage_users)
@require_http_methods(["GET", "POST"])
def user_create_view(request: HttpRequest) -> HttpResponse:
    roles = assignable_roles(actor=request.user)
    form = UserCreateForm(request.POST or None, roles_queryset=roles)
    if request.method == "POST" and form.is_valid():
        try:
            user = create_application_user(
                actor=request.user,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
                display_name=form.cleaned_data["display_name"],
                email=form.cleaned_data["email"],
                is_active=form.cleaned_data["is_active"],
                roles=form.cleaned_data["roles"],
            )
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"สร้างบัญชี {user.username} แล้ว")
            return redirect("web:user-list")
    return render(
        request,
        "web/identity/user_form.html",
        {"form": form, "mode": "create", "managed_user": None},
    )


@capability_required(can_manage_users)
@require_http_methods(["GET", "POST"])
def user_edit_view(request: HttpRequest, user_id) -> HttpResponse:
    user = get_object_or_404(manageable_users(actor=request.user), pk=user_id)
    roles = assignable_roles(actor=request.user)
    form = UserUpdateForm(
        request.POST or None,
        user=user,
        roles_queryset=roles,
        allow_role_changes=request.user.is_superuser or request.user.pk != user.pk,
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_application_user(
                actor=request.user,
                user=user,
                display_name=form.cleaned_data["display_name"],
                email=form.cleaned_data["email"],
                is_active=form.cleaned_data["is_active"],
                roles=form.cleaned_data["roles"],
            )
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"บันทึกบัญชี {user.username} แล้ว")
            return redirect("web:user-list")
    return render(
        request,
        "web/identity/user_form.html",
        {"form": form, "mode": "edit", "managed_user": user},
    )


@capability_required(can_manage_users)
@require_http_methods(["GET", "POST"])
def user_password_view(request: HttpRequest, user_id) -> HttpResponse:
    user = get_object_or_404(manageable_users(actor=request.user), pk=user_id)
    form = PasswordResetForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        reset_application_password(
            actor=request.user,
            user=user,
            password=form.cleaned_data["password"],
        )
        messages.success(request, f"ตั้งรหัสผ่านใหม่ให้ {user.username} แล้ว")
        return redirect("web:user-list")
    return render(
        request,
        "web/identity/password_form.html",
        {"form": form, "managed_user": user},
    )


@capability_required(can_manage_roles)
def role_list_view(request: HttpRequest) -> HttpResponse:
    roles = manageable_roles(actor=request.user)
    role_rows = [
        {
            "role": role,
            "is_protected": role.name == BUSINESS_ADMIN_ROLE_NAME,
            "user_count": role.user_set.count(),
        }
        for role in roles
    ]
    return render(
        request,
        "web/identity/role_list.html",
        {"role_rows": role_rows},
    )


@capability_required(can_manage_roles)
@require_http_methods(["GET", "POST"])
def role_create_view(request: HttpRequest) -> HttpResponse:
    permissions = available_role_permissions(actor=request.user)
    form = RoleForm(request.POST or None, permissions_queryset=permissions)
    if request.method == "POST" and form.is_valid():
        try:
            role = create_application_role(
                actor=request.user,
                name=form.cleaned_data["name"],
                permissions=form.cleaned_data["permissions"],
            )
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"สร้างบทบาท {role.name} แล้ว")
            return redirect("web:role-list")
    return render(
        request,
        "web/identity/role_form.html",
        {"form": form, "mode": "create", "role": None},
    )


@capability_required(can_manage_roles)
@require_http_methods(["GET", "POST"])
def role_edit_view(request: HttpRequest, role_id: int) -> HttpResponse:
    role = get_object_or_404(manageable_roles(actor=request.user), pk=role_id)
    if role.name == BUSINESS_ADMIN_ROLE_NAME and not request.user.is_superuser:
        raise Http404
    permissions = available_role_permissions(actor=request.user)
    form = RoleForm(
        request.POST or None,
        permissions_queryset=permissions,
        role=role,
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_application_role(
                actor=request.user,
                role=role,
                name=form.cleaned_data["name"],
                permissions=form.cleaned_data["permissions"],
            )
        except ValidationError as exc:
            _add_service_error(form, exc)
        else:
            messages.success(request, f"บันทึกบทบาท {role.name} แล้ว")
            return redirect("web:role-list")
    return render(
        request,
        "web/identity/role_form.html",
        {"form": form, "mode": "edit", "role": role},
    )

