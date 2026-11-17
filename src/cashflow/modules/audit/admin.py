from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "actor_identifier",
        "action",
        "entity_type",
        "entity_label",
    )
    list_filter = ("action", "entity_type", "occurred_at")
    search_fields = ("actor_identifier", "entity_id", "entity_label")
    readonly_fields = (
        "id",
        "occurred_at",
        "actor",
        "actor_identifier",
        "action",
        "entity_type",
        "entity_id",
        "entity_label",
        "before",
        "after",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

