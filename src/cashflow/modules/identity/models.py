import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """System identity. Business modules reference this model, never UI classes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField("ชื่อที่แสดง", max_length=150, blank=True)

    class Meta:
        verbose_name = "ผู้ใช้"
        verbose_name_plural = "ผู้ใช้"
        ordering = ("username",)
        permissions = (
            ("manage_application_users", "จัดการผู้ใช้ในระบบ"),
            ("manage_application_roles", "จัดการบทบาทและสิทธิ์ในระบบ"),
        )

    def get_display_name(self) -> str:
        return self.display_name or self.get_full_name() or self.username

