from django.test import RequestFactory, TestCase

from cashflow.modules.identity.models import User
from cashflow.modules.identity.services import authenticate_credentials


class AuthenticationServiceTests(TestCase):
    def setUp(self) -> None:
        self.request = RequestFactory().post("/login/")
        self.user = User.objects.create_user(
            username="finance-user",
            password="A-safe-test-password-2026!",
        )

    def test_authenticates_valid_credentials(self) -> None:
        result = authenticate_credentials(
            request=self.request,
            username="finance-user",
            password="A-safe-test-password-2026!",
        )

        self.assertEqual(result, self.user)

    def test_rejects_invalid_credentials(self) -> None:
        result = authenticate_credentials(
            request=self.request,
            username="finance-user",
            password="wrong-password",
        )

        self.assertIsNone(result)

