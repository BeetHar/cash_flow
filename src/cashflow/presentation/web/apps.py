from django.apps import AppConfig


class WebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cashflow.presentation.web"
    label = "cashflow_web"
    verbose_name = "หน้าเว็บ"

