from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cashflow.modules.identity"
    label = "identity"
    verbose_name = "ผู้ใช้และสิทธิ์"

