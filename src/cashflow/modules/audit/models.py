import uuid

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurred_at = models.DateTimeField("เวลาที่เกิดเหตุการณ์", auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้กระทำ",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    actor_identifier = models.CharField("ชื่อผู้กระทำขณะนั้น", max_length=150)
    action = models.CharField("การกระทำ", max_length=50)
    entity_type = models.CharField("ชนิดข้อมูล", max_length=100)
    entity_id = models.CharField("รหัสข้อมูล", max_length=100)
    entity_label = models.CharField("ชื่อข้อมูล", max_length=255, blank=True)
    before = models.JSONField("ค่าก่อนหน้า", default=dict, blank=True)
    after = models.JSONField("ค่าหลังเปลี่ยน", default=dict, blank=True)

    class Meta:
        verbose_name = "ประวัติการเปลี่ยนแปลง"
        verbose_name_plural = "ประวัติการเปลี่ยนแปลง"
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=("entity_type", "entity_id", "-occurred_at")),
            models.Index(fields=("actor", "-occurred_at")),
        ]

    def __str__(self) -> str:
        return f"{self.actor_identifier}: {self.action} {self.entity_type}"

