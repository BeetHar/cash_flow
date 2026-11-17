from collections.abc import Mapping
from typing import Any

from django.db.models import QuerySet

from cashflow.modules.identity.models import User

from .models import AuditEvent


def record_event(
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: str,
    entity_label: str = "",
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        actor_identifier=actor.username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        before=dict(before or {}),
        after=dict(after or {}),
    )


def events_for_entity(*, entity_type: str, entity_id: str) -> QuerySet[AuditEvent]:
    """อ่านประวัติของข้อมูลหนึ่งรายการ เรียงจากเก่าไปใหม่ (อ่านอย่างเดียว)

    โมดูลที่เรียกต้องตรวจสิทธิ์ของผู้ใช้เองก่อนส่งผลลัพธ์ออกไป
    """

    return (
        AuditEvent.objects.filter(entity_type=entity_type, entity_id=entity_id)
        .select_related("actor")
        .order_by("occurred_at")
    )
