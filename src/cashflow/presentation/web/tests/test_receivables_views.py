from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cashflow.modules.identity.models import User
from cashflow.modules.procurement.tests.xlsx_factory import make_xlsx
from cashflow.modules.receivables.models import InvoiceStatus, SalesInvoice
from cashflow.modules.receivables.services import create_customer, create_invoice


def make_user(username, *codenames):
    user = User.objects.create_user(username=username, password="A-safe-password-2026!")
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return User.objects.get(pk=user.pk)


class ReceivablesViewTests(TestCase):
    def setUp(self):
        self.acc = make_user("acc", "manage_receivables")
        self.viewer = make_user("viewer", "view_receivables")
        self.outsider = make_user("outsider")
        self.customer = create_customer(actor=self.acc, code="MK", name="ลูกค้าทดสอบ", credit_days=0)
        self.today = timezone.localdate()
        self.invoice = create_invoice(actor=self.acc, number="IV6911/00001", customer=self.customer,
                                      amount=Decimal("1500"), document_date=self.today)

    def test_outsider_is_blocked(self):
        self.client.force_login(self.outsider)
        for name in ("web:sales-invoice-list", "web:receipt-plan-list", "web:customer-list", "web:daily"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_receive_through_detail_page_and_history(self):
        self.client.force_login(self.acc)
        url = reverse("web:sales-invoice-action", args=[self.invoice.pk, "receive"])
        self.client.post(url, {"received_date": self.today.isoformat(), "received_amount": "1400", "reason": "หักค่าธรรมเนียม"})
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceStatus.RECEIVED)
        page = self.client.get(reverse("web:sales-invoice-detail", args=[self.invoice.pk]))
        self.assertContains(page, "บันทึกรับเงิน")
        self.assertContains(page, "-100.00")

    def test_unknown_action_is_404_and_viewer_cannot_post(self):
        self.client.force_login(self.acc)
        self.assertEqual(self.client.post(reverse("web:sales-invoice-action", args=[self.invoice.pk, "delete"]), {"reason": "x"}).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse("web:sales-invoice-action", args=[self.invoice.pk, "cancel"]), {"reason": "x"}).status_code, 403)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceStatus.OPEN)

    def test_daily_page_combines_and_switches_views(self):
        self.client.force_login(self.viewer)
        summary = self.client.get(reverse("web:daily"), {"opening": "1000"})
        self.assertContains(summary, "+1,500.00")
        self.assertContains(summary, "2,500.00")  # ยกมา 1,000 + เข้า 1,500
        listing = self.client.get(reverse("web:daily"), {"mode": "list"})
        self.assertContains(listing, "IV6911/00001")
        self.assertContains(listing, "คาดว่าจะได้รับ")

    def test_import_preview_then_confirm(self):
        self.client.force_login(self.acc)
        file = make_xlsx({"S": [["หมายเลข Invoice", "ยอดสุทธิ", "วันที่ Invoice", "สาขา"],
                                ["IV6911/00002", "2,000.00", "13/11/2569", "บางบอน"]]})
        preview = self.client.post(reverse("web:sales-invoice-import"), {"customer": str(self.customer.pk), "file": file})
        self.assertContains(preview, "ยืนยันนำเข้า")
        self.assertFalse(SalesInvoice.objects.filter(number="IV6911/00002").exists())
        self.client.post(reverse("web:sales-invoice-import-confirm"))
        created = SalesInvoice.objects.get(number="IV6911/00002")
        self.assertEqual((created.amount, created.branch, created.document_date), (Decimal("2000.00"), "บางบอน", date(2026, 11, 13)))

    def test_daily_page_warns_about_overdue_open_invoices(self):
        create_invoice(actor=self.acc, number="IV6910/00099", customer=self.customer,
                       amount=Decimal("700"), document_date=self.today - timedelta(days=40))
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("web:daily"))
        self.assertContains(response, "ใบขายยังไม่ได้รับเงิน 1 ใบ")
        self.assertContains(response, "700.00")
