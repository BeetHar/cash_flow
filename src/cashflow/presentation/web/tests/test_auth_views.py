from django.test import TestCase
from django.urls import reverse

from cashflow.modules.identity.models import User


class AuthenticationViewTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="admin-test",
            password="A-safe-test-password-2026!",
            display_name="ผู้ดูแลทดสอบ",
        )

    def test_dashboard_requires_authentication(self) -> None:
        response = self.client.get(reverse("web:dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('web:login')}?next={reverse('web:dashboard')}",
        )

    def test_authenticated_dashboard_shows_cashflow_prototype(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("web:dashboard"))

        self.assertContains(response, "รายการเคลื่อนไหว")
        self.assertContains(response, "เงินเข้า")
        self.assertContains(response, "เงินออก")
        self.assertContains(response, "เงินคงเหลือ")
        self.assertContains(response, "ข้อมูลตัวอย่าง")

    def test_developer_console_link_is_only_shown_to_developer(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("web:dashboard"))

        self.assertNotContains(response, "Developer console")

        developer = User.objects.create_superuser(
            username="developer-test",
            password="A-safe-developer-password-2026!",
        )
        self.client.force_login(developer)

        response = self.client.get(reverse("web:dashboard"))

        self.assertContains(response, "Developer console")

    def test_user_can_log_in(self) -> None:
        response = self.client.post(
            reverse("web:login"),
            {"username": "admin-test", "password": "A-safe-test-password-2026!"},
        )

        self.assertRedirects(response, reverse("web:dashboard"))
        self.assertEqual(str(self.client.session.get("_auth_user_id")), str(self.user.pk))

    def test_invalid_login_uses_generic_error(self) -> None:
        response = self.client.post(
            reverse("web:login"),
            {"username": "admin-test", "password": "incorrect"},
        )

        self.assertContains(response, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("web:logout"))

        self.assertEqual(response.status_code, 405)

    def test_user_can_log_out(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(reverse("web:logout"))

        self.assertRedirects(response, reverse("web:login"))
        self.assertNotIn("_auth_user_id", self.client.session)


class HealthViewTests(TestCase):
    def test_health_reports_database_connection(self) -> None:
        response = self.client.get(reverse("web:health"))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok", "database": "connected"})

