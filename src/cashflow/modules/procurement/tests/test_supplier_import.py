from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from cashflow.modules.audit.models import AuditEvent
from cashflow.modules.identity.models import User
from cashflow.modules.procurement.models import PurchaseOrderStatus, Supplier
from cashflow.modules.procurement.services import (
    create_purchase_order,
    create_supplier,
    update_supplier,
)
from cashflow.modules.procurement.supplier_import import (
    apply_supplier_import,
    build_import_plan,
    parse_credit_days,
    parse_supplier_file,
)
from cashflow.modules.procurement.xlsx_reader import WorkbookError, read_workbook

from .xlsx_factory import make_xlsx, supplier_workbook

SUPPLIERS = [
    ["ก-001", "ผู้ขายเครดิต 30", "กระดาษ", "ซื้อมาขายไป"],
    ["ก-002", "ผู้ขายภายใน 7", "-", "อื่นๆ"],
    ["ก-003", "ผู้ขายไม่ระบุ", "-", "-"],
    ["ก-004", "ผู้ขายเลิกแล้ว", "**ยกเลิกซื้อขาย**", "จ้างผลิต"],
    ["ก-005", "ไม่อยู่ในชีตเครดิต", "-", "-"],
]
CREDITS = [
    ["ก-001", "ผู้ขายเครดิต 30", "เจ้าหนี้การค้า-ในประเทศ เครดิต 30 วัน", "-"],
    ["ก-002", "ผู้ขายภายใน 7", "เจ้าหนี้อื่นภายใน 7 วัน", "-"],
    ["ก-003", "ผู้ขายไม่ระบุ", "เจ้าหนี้อื่น", "-"],
    ["ก-004", "ผู้ขายเลิกแล้ว", "เจ้าหนี้การค้า-ในประเทศ เครดิต 60 วัน", "-"],
    [0, "เจ้าหนี้เงินสด", "เจ้าหนี้เงินสด", "-"],
]


class CreditParsingTests(SimpleTestCase):
    def test_reads_days_from_group_name(self) -> None:
        cases = {
            "เจ้าหนี้การค้า-ในประเทศ เครดิต 30 วัน": 30,
            "เจ้าหนี้อื่นภายใน 7 วัน": 7,
            "เจ้าหนี้การค้า-ในประเทศ ภายใน 7 วัน": 7,
            "เจ้าหนี้อื่น เครดิต 180 วัน": 180,
            "เจ้าหนี้เงินสด": 0,
            "เจ้าหนี้อื่น": None,
            "เจ้าหนี้การค้า-ต่างประเทศ": None,
            "": None,
        }
        for group, expected in cases.items():
            with self.subTest(group=group):
                self.assertEqual(parse_credit_days(group), expected)


class FileParsingTests(SimpleTestCase):
    def test_reader_converts_whole_numbers_to_text(self) -> None:
        workbook = read_workbook(make_xlsx({"S": [["รหัส", 77777, 1.5]]}))

        self.assertEqual(workbook["S"], [["รหัส", "77777", "1.5"]])

    def test_parses_supplier_rows_with_credit(self) -> None:
        rows, warnings = parse_supplier_file(supplier_workbook(SUPPLIERS, CREDITS))
        by_code = {row.code: row for row in rows}

        self.assertEqual(len(rows), 5)
        self.assertEqual(by_code["ก-001"].credit_days, 30)
        self.assertEqual(by_code["ก-001"].description, "กระดาษ")
        self.assertEqual(by_code["ก-002"].credit_days, 7)
        self.assertEqual(by_code["ก-002"].description, "")  # "-" แปลว่าว่าง
        self.assertIsNone(by_code["ก-003"].credit_days)
        self.assertFalse(by_code["ก-004"].is_active)
        self.assertIsNone(by_code["ก-005"].credit_days)
        self.assertIn("ก-005", warnings[0])

    def test_missing_sheet_is_a_clear_error(self) -> None:
        with self.assertRaisesMessage(WorkbookError, "เครดิต"):
            parse_supplier_file(make_xlsx({"รายการ ผู้ผลิต": [["รหัสผู้ผลิต", "ชื่อผู้ผลิต"]]}))

    def test_non_excel_file_is_rejected(self) -> None:
        import io

        with self.assertRaises(WorkbookError):
            parse_supplier_file(io.BytesIO(b"not a zip"))


class ImportTests(TestCase):
    def setUp(self) -> None:
        self.manager = User.objects.create_user(username="acc", password="A-safe-password-2026!")
        self.manager.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="procurement")
        )
        self.manager = User.objects.get(pk=self.manager.pk)
        self.viewer = User.objects.create_user(username="viewer", password="A-safe-password-2026!")
        self.rows, self.warnings = parse_supplier_file(supplier_workbook(SUPPLIERS, CREDITS))

    def test_first_import_creates_everyone_with_history(self) -> None:
        plan = build_import_plan(actor=self.manager, rows=self.rows, warnings=self.warnings)
        self.assertEqual(plan.counts["create"], 5)
        self.assertEqual(plan.counts["credit_unknown"], 2)
        self.assertEqual(plan.counts["inactive"], 1)

        result = apply_supplier_import(actor=self.manager, rows=self.rows, file_name="s.xlsx")

        self.assertEqual(result["created"], 5)
        self.assertFalse(Supplier.objects.get(code="ก-004").is_active)
        self.assertIsNone(Supplier.objects.get(code="ก-003").credit_days)
        event = AuditEvent.objects.get(entity_type="procurement.supplier_import")
        self.assertEqual((event.actor, event.entity_label), (self.manager, "s.xlsx"))
        created = AuditEvent.objects.filter(entity_type="procurement.supplier", action="create")
        self.assertEqual(created.count(), 5)
        self.assertEqual(created.first().after["reason"], "นำเข้าจาก Excel")

    def test_reimport_updates_only_changes(self) -> None:
        apply_supplier_import(actor=self.manager, rows=self.rows, file_name="s.xlsx")
        credits = [list(row) for row in CREDITS]
        credits[0][2] = "เจ้าหนี้การค้า-ในประเทศ เครดิต 45 วัน"
        rows, warnings = parse_supplier_file(supplier_workbook(SUPPLIERS, credits))

        plan = build_import_plan(actor=self.manager, rows=rows, warnings=warnings)

        self.assertEqual((plan.counts["update"], plan.counts["unchanged"]), (1, 4))
        change = plan.of("update")[0].changes
        self.assertIn({"label": "เครดิต", "before": "30 วัน", "after": "45 วัน"}, change)

    def test_unknown_credit_in_file_keeps_value_entered_by_accounting(self) -> None:
        apply_supplier_import(actor=self.manager, rows=self.rows, file_name="s.xlsx")
        supplier = Supplier.objects.get(code="ก-003")
        update_supplier(
            actor=self.manager, supplier=supplier, code=supplier.code, name=supplier.name,
            tax_id="", branch="", address="", contact_name="", phone="", email="",
            credit_days=15, is_active=True,
        )

        result = apply_supplier_import(actor=self.manager, rows=self.rows, file_name="s.xlsx")

        self.assertEqual(Supplier.objects.get(code="ก-003").credit_days, 15)
        self.assertEqual(result["updated"], 0)

    def test_matches_existing_supplier_by_code(self) -> None:
        create_supplier(actor=self.manager, code="ก-001", name="ชื่อที่กรอกเอง", credit_days=10)

        plan = build_import_plan(actor=self.manager, rows=self.rows, warnings=[])

        self.assertEqual(plan.counts["create"], 4)
        self.assertEqual(plan.counts["update"], 1)

    def test_viewer_cannot_import(self) -> None:
        with self.assertRaises(PermissionDenied):
            build_import_plan(actor=self.viewer, rows=self.rows, warnings=[])
        with self.assertRaises(PermissionDenied):
            apply_supplier_import(actor=self.viewer, rows=self.rows, file_name="x")


class DueDateRefreshTests(TestCase):
    """เครดิตของผู้ขายเปลี่ยน → PO ที่ยังเปิดและไม่ได้กำหนดวันเองต้องเลื่อนตาม"""

    def setUp(self) -> None:
        self.manager = User.objects.create_user(username="acc", password="A-safe-password-2026!")
        self.manager.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="procurement")
        )
        self.manager = User.objects.get(pk=self.manager.pk)
        self.supplier = create_supplier(actor=self.manager, code="ก-003", name="ไม่ระบุเครดิต")
        self.count = 0

    def make_po(self, **overrides):
        self.count += 1
        arguments = {
            "actor": self.manager,
            "number": f"PO6911/{self.count:03d}",
            "supplier": self.supplier,
            "total_amount": Decimal("1000"),
            "ordered_at": timezone.make_aware(datetime(2026, 11, 4, 9, 0)),
            "delivery_date": date(2026, 11, 10),
        }
        arguments.update(overrides)
        return create_purchase_order(**arguments)

    def set_credit(self, days):
        update_supplier(
            actor=self.manager, supplier=self.supplier, code="ก-003", name=self.supplier.name,
            tax_id="", branch="", address="", contact_name="", phone="", email="",
            credit_days=days, is_active=True,
        )

    def test_unknown_credit_counts_as_delivery_date(self) -> None:
        self.assertEqual(self.make_po().due_date, date(2026, 11, 10))

    def test_filling_credit_moves_open_calculated_due_dates(self) -> None:
        auto = self.make_po()
        manual = self.make_po(due_date=date(2026, 11, 20))
        closed = self.make_po(status=PurchaseOrderStatus.CLOSED)

        self.set_credit(30)

        auto.refresh_from_db(); manual.refresh_from_db(); closed.refresh_from_db()
        self.assertEqual(auto.due_date, date(2026, 12, 10))
        self.assertEqual(manual.due_date, date(2026, 11, 20))
        self.assertEqual(closed.due_date, date(2026, 11, 10))
        event = AuditEvent.objects.filter(entity_id=str(auto.pk), action="update").get()
        self.assertEqual(event.before, {"due_date": "2026-11-10"})
        self.assertEqual(event.after["reason"], "เครดิตของผู้ขายเปลี่ยนเป็น 30 วัน")
