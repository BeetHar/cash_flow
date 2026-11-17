from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest

from cashflow.modules.identity.models import User


def authenticate_credentials(
    *, request: HttpRequest, username: str, password: str
) -> User | None:
    """Validate credentials without depending on any presentation implementation."""

    principal = authenticate(request=request, username=username, password=password)
    return principal if isinstance(principal, User) else None


def start_session(*, request: HttpRequest, user: User) -> None:
    login(request, user)


def end_session(*, request: HttpRequest) -> None:
    logout(request)

