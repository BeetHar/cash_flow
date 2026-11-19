from django.apps import AppConfig


class ReceivablesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cashflow.modules.receivables"
    label = "receivables"
    verbose_name = "รับเงิน"
