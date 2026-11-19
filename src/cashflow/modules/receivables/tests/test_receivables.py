from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase

from cashflow.modules.audit.models import AuditEvent
from cashflow.modules.identity.models import User
from cashflow.modules.procurement.tests.xlsx_factory import make_xlsx
from cashflow.modules.receivables import invoice_import
from cashflow.modules.receivables.models import InvoiceStatus
from cashflow.modules.receivables.services import (
    cancel_invoice, cash_entries, create_customer, create_invoice, create_plan, receive_invoice,
    reopen_invoice, set_plan_invoices, summarize_plan, update_customer,
)

D = Decimal
DAY = date(2026, 11, 10)


def make_user(username, *codenames):
    user = User.objects.create_user(username=username, password="A-safe-password-2026!")
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="receivables", codename__in=codenames))
    return User.objects.get(pk=user.pk)


class ReceivablesTestCase(TestCase):
    def setUp(self):
        self.acc = make_user("acc", "manage_receivables")
        self.viewer = make_user("viewer", "view_receivables")
        self.makro = create_customer(actor=self.acc, code="MK", name="ลูกค้าทดสอบ MK", credit_days=30)
        self.bj = create_customer(actor=self.acc, code="BJ", name="ลูกค้าทดสอบ BJ")
        self.n = 0

    def invoice(self, customer=None, amount="1000", **kw):
        self.n += 1
        return create_invoice(actor=self.acc, number=f"IV6911/{self.n:05d}", customer=customer or self.makro,
                              amount=D(amount), document_date=kw.pop("document_date", DAY), **kw)


class InvoiceTests(ReceivablesTestCase):
    def test_due_date_is_document_date_plus_customer_credit(self):
        self.assertEqual(self.invoice().due_date, DAY + timedelta(days=30))
        self.assertEqual(self.invoice(customer=self.bj).due_date, DAY)  # ไม่ระบุเครดิต = 0 วัน

    def test_credit_change_moves_open_calculated_invoices_only(self):
        auto = self.invoice(customer=self.bj)
        manual = self.invoice(customer=self.bj, due_date=date(2026, 11, 20))
        update_customer(actor=self.acc, customer=self.bj, code="BJ", name=self.bj.name, credit_days=15, is_active=True)
        auto.refresh_from_db(); manual.refresh_from_db()
        self.assertEqual(auto.due_date, date(2026, 11, 25))
        self.assertEqual(manual.due_date, date(2026, 11, 20))

    def test_receive_keeps_difference_and_history(self):
        invoice = receive_invoice(actor=self.acc, invoice=self.invoice(amount="5000000"),
                                  received_date=date(2026, 11, 12), received_amount=D("4600000"), reason="ลูกค้าหักบางส่วน")
        self.assertEqual(invoice.status, InvoiceStatus.RECEIVED)
        self.assertEqual(invoice.difference, D("-400000.00"))
        event = AuditEvent.objects.get(entity_id=str(invoice.pk), action="receive")
        self.assertEqual(event.after["received_amount"], "4600000.00")
        self.assertEqual(event.after["reason"], "ลูกค้าหักบางส่วน")

    def test_reopen_and_cancel_require_reason(self):
        invoice = receive_invoice(actor=self.acc, invoice=self.invoice(), received_date=DAY, received_amount=D("1000"))
        with self.assertRaises(ValidationError):
            reopen_invoice(actor=self.acc, invoice=invoice, reason=" ")
        invoice = reopen_invoice(actor=self.acc, invoice=invoice, reason="ลงผิดใบ")
        self.assertIsNone(invoice.received_amount)
        with self.assertRaises(ValidationError):
            cancel_invoice(actor=self.acc, invoice=invoice, reason="")
        self.assertEqual(cancel_invoice(actor=self.acc, invoice=invoice, reason="ซ้ำ").status, InvoiceStatus.CANCELLED)

    def test_duplicate_number_and_permissions(self):
        self.invoice()
        with self.assertRaises(ValidationError):
            create_invoice(actor=self.acc, number="iv6911/00001", customer=self.makro, amount=D("1"), document_date=DAY)
        with self.assertRaises(PermissionDenied):
            create_invoice(actor=self.viewer, number="X1", customer=self.makro, amount=D("1"), document_date=DAY)


class PlanTests(ReceivablesTestCase):
    def test_plan_versus_actual_shows_shortfall(self):
        """ตัวอย่างจากที่ประชุม: แผน 5 ล้าน แต่เข้าจริง 4.6 ล้าน ขาด 4 แสน"""

        plan = create_plan(actor=self.acc, customer=self.makro, plan_date=DAY, amount=D("5000000"))
        a, b = self.invoice(amount="3000000"), self.invoice(amount="2000000")
        receive_invoice(actor=self.acc, invoice=a, received_date=DAY, received_amount=D("3000000"))
        receive_invoice(actor=self.acc, invoice=b, received_date=DAY, received_amount=D("1600000"))
        summary = set_plan_invoices(actor=self.acc, plan=plan, invoice_ids=[a.pk, b.pk])
        self.assertEqual((summary.invoiced, summary.received), (D("5000000.00"), D("4600000.00")))
        self.assertEqual(summary.difference, D("-400000.00"))
        self.assertEqual(summary.outstanding, D("0.00"))

    def test_cannot_link_other_customers_invoice(self):
        plan = create_plan(actor=self.acc, customer=self.makro, plan_date=DAY, amount=D("100"))
        with self.assertRaises(ValidationError):
            set_plan_invoices(actor=self.acc, plan=plan, invoice_ids=[self.invoice(customer=self.bj).pk])

    def test_cash_entries_do_not_double_count_plan_and_invoices(self):
        plan = create_plan(actor=self.acc, customer=self.bj, plan_date=DAY, amount=D("25000000"))
        linked = self.invoice(customer=self.bj, amount="2000000")
        set_plan_invoices(actor=self.acc, plan=plan, invoice_ids=[linked.pk])
        received = self.invoice(customer=self.bj, amount="500000")
        receive_invoice(actor=self.acc, invoice=received, received_date=DAY, received_amount=D("500000"))

        entries = cash_entries(actor=self.viewer, start=DAY, end=DAY)
        by_kind = {(e.kind, e.title): e.amount for e in entries}
        self.assertEqual(by_kind[("plan", "แผนรับเงิน")], D("23000000.00"))  # ส่วนที่ยังไม่มีบิล
        self.assertEqual(by_kind[("expected", linked.number)], D("2000000.00"))
        self.assertEqual(by_kind[("actual", received.number)], D("500000.00"))
        self.assertEqual(sum(e.amount for e in entries), D("25500000.00"))


class ImportParsingTests(SimpleTestCase):
    def test_parses_makro_layout_with_buddhist_dates(self):
        file = make_xlsx({"รายการคำสั่งซื้อแม็คโคร": [
            ["บริษัททดสอบ จำกัด"], ["รายการคำสั่งซื้อแม็คโคร ที่เสร็จสิ้นแล้ว"], ["วันที่ PO", "09/11/2569 - 21/11/2569"], [],
            ["หมายเลข Invoice", "หมายเลข PO", "สาขา", "ยอดสุทธิ", "วันที่ PO", "วันที่ต้องส่ง", "วันที่ Invoice", "Buyer Code"],
            ["IV6911/00480", "4.2174576", "บางบอน", "3,370.50", "09/11/2569", "18/11/2569", "13/11/2569", "BFS6"],
            ["IV6911/00481", "83.2174592", "นครอินทร์", 2140, "09/11/2569", "18/11/2569", 46339, "BFS6"],
            ["IV6911/00482", "", "", "abc", "", "", "13/11/2569", ""],
        ]})
        rows, warnings = invoice_import.parse_invoice_file(file)
        self.assertEqual([r.number for r in rows], ["IV6911/00480", "IV6911/00481"])
        self.assertEqual(rows[0].amount, "3370.50")
        self.assertEqual(rows[0].document_date, "2026-11-13")
        self.assertEqual(rows[1].document_date, (date(1899, 12, 30) + timedelta(days=46339)).isoformat())
        self.assertEqual(rows[0].branch, "บางบอน")
        self.assertIn("IV6911/00482", warnings[0])

    def test_rejects_file_without_required_columns(self):
        from cashflow.modules.procurement.xlsx_reader import WorkbookError
        with self.assertRaises(WorkbookError):
            invoice_import.parse_invoice_file(make_xlsx({"S": [["ชื่อ", "ยอด"]]}))


class ImportApplyTests(ReceivablesTestCase):
    def test_import_creates_updates_and_skips(self):
        existing = self.invoice(amount="100")  # IV6911/00001
        done = self.invoice(amount="200")
        receive_invoice(actor=self.acc, invoice=done, received_date=DAY, received_amount=D("200"))
        rows = [
            invoice_import.ImportRow(existing.number, "150.00", DAY.isoformat(), "", ""),
            invoice_import.ImportRow(done.number, "999.00", DAY.isoformat(), "", ""),
            invoice_import.ImportRow("IV6911/09999", "500.00", DAY.isoformat(), "PO1", "สาขา 1"),
        ]
        counts = invoice_import.apply_import(actor=self.acc, customer=self.makro, rows=rows, file_name="mk.xlsx")
        self.assertEqual(counts, {"create": 1, "update": 1, "unchanged": 0, "skip": 1})
        existing.refresh_from_db(); done.refresh_from_db()
        self.assertEqual(existing.amount, D("150.00"))
        self.assertEqual(done.amount, D("200.00"))
        self.assertTrue(AuditEvent.objects.filter(entity_type="receivables.invoice_import", entity_label="mk.xlsx").exists())


class OverdueTests(ReceivablesTestCase):
    def test_open_invoices_before_range_are_reported_as_overdue(self):
        from cashflow.modules.receivables.services import overdue_invoices

        old = self.invoice(customer=self.bj, document_date=date(2026, 10, 1))
        done = self.invoice(customer=self.bj, document_date=date(2026, 10, 2))
        receive_invoice(actor=self.acc, invoice=done, received_date=date(2026, 10, 3), received_amount=D("1000"))
        self.assertEqual(list(overdue_invoices(actor=self.viewer, before=DAY)), [old])
