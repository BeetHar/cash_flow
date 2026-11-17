from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from cashflow.modules.identity.models import User
from cashflow.modules.procurement.models import Supplier
from cashflow.modules.procurement.tests.test_supplier_import import CREDITS, SUPPLIERS
from cashflow.modules.procurement.tests.xlsx_factory import supplier_workbook


class SupplierImportViewTests(TestCase):
    def setUp(self) -> None:
        self.manager = User.objects.create_user(username="acc", password="A-safe-password-2026!")
        self.manager.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="procurement")
        )
        self.viewer = User.objects.create_user(username="viewer", password="A-safe-password-2026!")
        self.viewer.user_permissions.add(
            Permission.objects.get(codename="view_purchase_orders")
        )

    def upload(self):
        return self.client.post(
            reverse("web:supplier-import"), {"file": supplier_workbook(SUPPLIERS, CREDITS)}
        )

    def test_preview_then_confirm(self) -> None:
        self.client.force_login(self.manager)

        preview = self.upload()
        self.assertContains(preview, "จะเพิ่มใหม่ 5 ราย")
        self.assertContains(preview, "ยืนยันนำเข้า")
        self.assertFalse(Supplier.objects.exists())

        response = self.client.post(reverse("web:supplier-import-confirm"))

        self.assertRedirects(response, reverse("web:supplier-list"))
        self.assertEqual(Supplier.objects.count(), 5)
        listing = self.client.get(reverse("web:supplier-list") + "?credit=unknown")
        self.assertContains(listing, "เครดิตไม่ระบุ (2)")
        self.assertContains(listing, "ผู้ขายไม่ระบุ")
        self.assertNotContains(listing, "ผู้ขายเครดิต 30")

    def test_confirm_without_preview_is_rejected(self) -> None:
        self.client.force_login(self.manager)

        response = self.client.post(reverse("web:supplier-import-confirm"))

        self.assertRedirects(response, reverse("web:supplier-import"))
        self.assertFalse(Supplier.objects.exists())

    def test_wrong_file_shows_error(self) -> None:
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("web:supplier-import"),
            {"file": SimpleUploadedFile("data.xlsx", b"not excel")},
        )

        self.assertContains(response, "ไม่ใช่ไฟล์ Excel")

    def test_viewer_cannot_open_import(self) -> None:
        self.client.force_login(self.viewer)

        self.assertEqual(self.client.get(reverse("web:supplier-import")).status_code, 403)
        self.assertEqual(self.client.post(reverse("web:supplier-import-confirm")).status_code, 403)
