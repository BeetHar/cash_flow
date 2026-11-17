import os

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from cashflow.modules.identity.constants import (
    BUSINESS_ADMIN_ROLE_NAME,
    MANAGEMENT_PERMISSION_CODENAMES,
)
from cashflow.modules.identity.models import User


class Command(BaseCommand):
    help = "Create separate developer and business admin accounts for local development."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        if not settings.DEBUG:
            self.stdout.write("Skipping local account bootstrap outside DEBUG mode.")
            return

        developer_username = os.getenv("DEV_SUPERUSER_USERNAME", "").strip()
        developer_password = os.getenv("DEV_SUPERUSER_PASSWORD", "")
        developer_email = os.getenv("DEV_SUPERUSER_EMAIL", "").strip()
        admin_username = os.getenv("APP_ADMIN_USERNAME", "").strip()
        admin_password = os.getenv("APP_ADMIN_PASSWORD", "")
        admin_email = os.getenv("APP_ADMIN_EMAIL", "").strip()

        if not all(
            [
                developer_username,
                developer_password,
                admin_username,
                admin_password,
            ]
        ):
            self.stdout.write(
                self.style.WARNING(
                    "Local developer or business admin credentials are missing; "
                    "no accounts were changed."
                )
            )
            return
        if developer_username == admin_username:
            self.stdout.write(
                self.style.ERROR(
                    "DEV_SUPERUSER_USERNAME and APP_ADMIN_USERNAME must be different."
                )
            )
            return

        developer, developer_created = User.objects.get_or_create(
            username=developer_username,
            defaults={
                "email": developer_email,
                "display_name": "นักพัฒนาระบบ",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        developer_fields: list[str] = []
        if developer_created:
            developer.set_password(developer_password)
            developer_fields.append("password")
        if not developer.is_staff:
            developer.is_staff = True
            developer_fields.append("is_staff")
        if not developer.is_superuser:
            developer.is_superuser = True
            developer_fields.append("is_superuser")
        if developer_fields:
            developer.save(update_fields=developer_fields)

        admin_role, _ = Group.objects.get_or_create(name=BUSINESS_ADMIN_ROLE_NAME)
        management_permissions = Permission.objects.filter(
            content_type__app_label="identity",
            codename__in=MANAGEMENT_PERMISSION_CODENAMES,
        )
        # Admin ทำได้ทุกอย่าง จึงได้รับสิทธิ์ของทุกโมดูลธุรกิจด้วย รวมถึงโมดูลที่เพิ่มภายหลัง
        business_module_labels = {
            config.label
            for config in apps.get_app_configs()
            if config.name.startswith("cashflow.modules.")
            and config.label not in {"identity", "audit"}
        }
        module_permissions = Permission.objects.filter(
            content_type__app_label__in=business_module_labels
        )
        admin_role.permissions.add(*management_permissions, *module_permissions)

        business_admin, admin_created = User.objects.get_or_create(
            username=admin_username,
            defaults={
                "email": admin_email,
                "display_name": "ผู้ดูแลระบบ",
                "is_staff": False,
                "is_superuser": False,
            },
        )
        admin_fields: list[str] = []
        if admin_created:
            business_admin.set_password(admin_password)
            admin_fields.append("password")
        if business_admin.is_staff:
            business_admin.is_staff = False
            admin_fields.append("is_staff")
        if business_admin.is_superuser:
            business_admin.is_superuser = False
            admin_fields.append("is_superuser")
        if admin_fields:
            business_admin.save(update_fields=admin_fields)
        business_admin.groups.add(admin_role)

        developer_state = "created" if developer_created else "ready"
        admin_state = "created" if admin_created else "ready"
        self.stdout.write(
            self.style.SUCCESS(
                f"Developer '{developer_username}' {developer_state}; "
                f"business admin '{admin_username}' {admin_state}."
            )
        )

