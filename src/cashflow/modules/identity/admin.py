from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CashFlowUserAdmin(UserAdmin):
    list_display = ("username", "display_name", "email", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("username", "display_name", "first_name", "last_name", "email")
    ordering = ("username",)
    fieldsets = UserAdmin.fieldsets + (
        ("ข้อมูลสำหรับระบบ Cash Flow", {"fields": ("display_name",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("ข้อมูลสำหรับระบบ Cash Flow", {"fields": ("display_name", "email")}),
    )


admin.site.site_header = "Cash Flow — จัดการระบบ"
admin.site.site_title = "Cash Flow Admin"
admin.site.index_title = "ผู้ใช้ บทบาท และข้อมูลระบบ"

