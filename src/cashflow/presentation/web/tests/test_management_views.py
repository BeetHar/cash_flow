from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from cashflow.modules.audit.models import AuditEvent
from cashflow.modules.identity.constants import BUSINESS_ADMIN_ROLE_NAME
from cashflow.modules.identity.models import User


class BusinessAdminViewTests(TestCase):
    def setUp(self) -> None:
        self.admin_role = Group.objects.create(name=BUSINESS_ADMIN_ROLE_NAME)
        self.manage_users = Permission.objects.get(
            content_type__app_label="identity",
            codename="manage_application_users",
        )
        self.manage_roles = Permission.objects.get(
            content_type__app_label="identity",
            codename="manage_application_roles",
        )
        self.admin_role.permissions.add(self.manage_users, self.manage_roles)

        self.manager = User.objects.create_user(
            username="business-admin",
            password="A-safe-admin-password-2026!",
            display_name="Business Admin",
            is_staff=False,
            is_superuser=False,
        )
        self.manager.groups.add(self.admin_role)
        self.basic_user = User.objects.create_user(
            username="basic-user",
            password="A-safe-user-password-2026!",
        )
        self.developer = User.objects.create_superuser(
            username="developer-test",
            password="A-safe-developer-password-2026!",
        )

    def test_business_admin_sees_application_users_but_not_developer(self) -> None:
        self.client.force_login(self.manager)

        response = self.client.get(reverse("web:user-list"))

        self.assertContains(response, "business-admin")
        self.assertContains(response, "basic-user")
        self.assertNotContains(response, "developer-test")

    def test_basic_user_cannot_open_user_management(self) -> None:
        self.client.force_login(self.basic_user)

        response = self.client.get(reverse("web:user-list"))

        self.assertEqual(response.status_code, 403)

    def test_business_admin_creates_non_staff_user_and_audit_event(self) -> None:
        role = Group.objects.create(name="ผู้ตรวจสอบ")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("web:user-create"),
            {
                "username": "new-user",
                "display_name": "ผู้ใช้ใหม่",
                "email": "new@example.test",
                "password": "A-safe-new-user-password-2026!",
                "password_confirmation": "A-safe-new-user-password-2026!",
                "roles": [role.pk],
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("web:user-list"))
        user = User.objects.get(username="new-user")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.groups.filter(pk=role.pk).exists())
        event = AuditEvent.objects.get(entity_type="identity.user", entity_id=str(user.pk))
        self.assertEqual(event.actor, self.manager)
        self.assertNotIn("password", str(event.after).lower())

    def test_business_admin_creates_role_with_application_permission(self) -> None:
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("web:role-create"),
            {"name": "ผู้จัดการผู้ใช้", "permissions": [self.manage_users.pk]},
        )

        self.assertRedirects(response, reverse("web:role-list"))
        role = Group.objects.get(name="ผู้จัดการผู้ใช้")
        self.assertTrue(role.permissions.filter(pk=self.manage_users.pk).exists())
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.manager,
                action="create",
                entity_type="identity.role",
                entity_id=str(role.pk),
            ).exists()
        )

    def test_business_admin_cannot_edit_protected_admin_role(self) -> None:
        self.client.force_login(self.manager)

        response = self.client.get(reverse("web:role-edit", args=[self.admin_role.pk]))

        self.assertEqual(response.status_code, 404)

    def test_business_admin_resets_password_without_auditing_secret(self) -> None:
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("web:user-password", args=[self.basic_user.pk]),
            {
                "password": "A-brand-new-safe-password-2026!",
                "password_confirmation": "A-brand-new-safe-password-2026!",
            },
        )

        self.assertRedirects(response, reverse("web:user-list"))
        self.basic_user.refresh_from_db()
        self.assertTrue(self.basic_user.check_password("A-brand-new-safe-password-2026!"))
        event = AuditEvent.objects.get(
            action="password_reset",
            entity_id=str(self.basic_user.pk),
        )
        self.assertEqual(event.before, {})
        self.assertEqual(event.after, {"password_changed": True})

    def test_business_admin_is_not_django_staff(self) -> None:
        self.assertFalse(self.manager.is_staff)
        self.assertFalse(self.manager.is_superuser)

    def test_developer_remains_django_superuser(self) -> None:
        self.assertTrue(self.developer.is_staff)
        self.assertTrue(self.developer.is_superuser)

