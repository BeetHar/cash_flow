from django.contrib import admin

from .models import PurchaseOrder, Supplier


class ReadOnlyAdmin(admin.ModelAdmin):
    """Developer ดูข้อมูลได้ แต่การแก้ไขต้องผ่าน service เพื่อให้มี audit trail"""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Supplier)
class SupplierAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "tax_id", "credit_days", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "tax_id")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(ReadOnlyAdmin):
    list_display = (
        "number",
        "supplier",
        "total_amount",
        "ordered_at",
        "delivery_date",
        "due_date",
        "status",
        "approval_status",
    )
    list_filter = ("status", "approval_status")
    search_fields = ("number", "supplier__name", "supplier__code")
