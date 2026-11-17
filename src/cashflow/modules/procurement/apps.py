from django.apps import AppConfig


class ProcurementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cashflow.modules.procurement"
    label = "procurement"
    verbose_name = "จัดซื้อ"
