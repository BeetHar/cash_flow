from django import forms
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from cashflow.modules.identity.models import User


class LoginForm(forms.Form):
    username = forms.CharField(
        label="ชื่อผู้ใช้",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
                "placeholder": "กรอกชื่อผู้ใช้",
            }
        ),
    )
    password = forms.CharField(
        label="รหัสผ่าน",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": "กรอกรหัสผ่าน",
            }
        ),
    )


class PermissionChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, permission: Permission) -> str:
        return permission.name


class UserCreateForm(forms.Form):
    username = forms.CharField(label="ชื่อผู้ใช้", max_length=150)
    display_name = forms.CharField(label="ชื่อที่แสดง", max_length=150, required=False)
    email = forms.EmailField(label="อีเมล", required=False)
    password = forms.CharField(
        label="รหัสผ่านเริ่มต้น",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password_confirmation = forms.CharField(
        label="ยืนยันรหัสผ่าน",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    roles = forms.ModelMultipleChoiceField(
        label="บทบาท",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    is_active = forms.BooleanField(label="เปิดใช้งานบัญชี", required=False, initial=True)

    def __init__(self, *args, roles_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if roles_queryset is not None:
            self.fields["roles"].queryset = roles_queryset

    def clean_username(self) -> str:
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError("ชื่อผู้ใช้นี้ถูกใช้งานแล้ว")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirmation = cleaned_data.get("password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error("password_confirmation", "รหัสผ่านทั้งสองช่องไม่ตรงกัน")
            return cleaned_data
        if password:
            candidate = User(username=cleaned_data.get("username", ""))
            try:
                validate_password(password, candidate)
            except ValidationError as exc:
                self.add_error("password", exc)
        return cleaned_data


class UserUpdateForm(forms.Form):
    display_name = forms.CharField(label="ชื่อที่แสดง", max_length=150, required=False)
    email = forms.EmailField(label="อีเมล", required=False)
    roles = forms.ModelMultipleChoiceField(
        label="บทบาท",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    is_active = forms.BooleanField(label="เปิดใช้งานบัญชี", required=False)

    def __init__(
        self,
        *args,
        user: User,
        roles_queryset=None,
        allow_role_changes: bool = True,
        **kwargs,
    ):
        initial = kwargs.setdefault("initial", {})
        initial.update(
            {
                "display_name": user.display_name,
                "email": user.email,
                "roles": user.groups.all(),
                "is_active": user.is_active,
            }
        )
        super().__init__(*args, **kwargs)
        if roles_queryset is not None:
            self.fields["roles"].queryset = roles_queryset
        if not allow_role_changes:
            self.fields["roles"].disabled = True
            self.fields["roles"].help_text = (
                "เพื่อป้องกันการล็อกตัวเองออกจากระบบ บัญชีที่กำลังใช้งาน "
                "ไม่สามารถเปลี่ยนบทบาทตัวเองได้"
            )


class PasswordResetForm(forms.Form):
    password = forms.CharField(
        label="รหัสผ่านใหม่",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password_confirmation = forms.CharField(
        label="ยืนยันรหัสผ่านใหม่",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, user: User, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirmation = cleaned_data.get("password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error("password_confirmation", "รหัสผ่านทั้งสองช่องไม่ตรงกัน")
            return cleaned_data
        if password:
            try:
                validate_password(password, self.user)
            except ValidationError as exc:
                self.add_error("password", exc)
        return cleaned_data


class RoleForm(forms.Form):
    name = forms.CharField(label="ชื่อบทบาท", max_length=150)
    permissions = PermissionChoiceField(
        label="สิทธิ์ของบทบาท",
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, permissions_queryset=None, role: Group | None = None, **kwargs):
        self.role = role
        if role is not None:
            initial = kwargs.setdefault("initial", {})
            initial.update({"name": role.name, "permissions": role.permissions.all()})
        super().__init__(*args, **kwargs)
        if permissions_queryset is not None:
            self.fields["permissions"].queryset = permissions_queryset

    def clean_name(self) -> str:
        name = self.cleaned_data["name"].strip()
        roles = Group.objects.filter(name=name)
        if self.role is not None:
            roles = roles.exclude(pk=self.role.pk)
        if roles.exists():
            raise ValidationError("ชื่อบทบาทนี้ถูกใช้งานแล้ว")
        return name


