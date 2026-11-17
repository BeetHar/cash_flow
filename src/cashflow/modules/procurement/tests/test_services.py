from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from cashflow.modules.audit.models import AuditEvent
from cashflow.modules.identity.models import User
from cashflow.modules.procurement.models import ApprovalStatus, PurchaseOrderStatus
from cashflow.modules.procurement.services import (
    PURCHASE_ORDER_ENTITY,
    cancel_purchase_order,
    create_purchase_order,
    create_supplier,
    expected_outflows,
    update_purchase_order,
    update_supplier,
)

D = Decimal


def grant(user: User, *codenames: str) -> User:
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="procurement", codename__in=codenames)
    )
    return User.objects.get(pk=user.pk)  # ล้าง permission cache


class ProcurementServiceTestCase(TestCase):
    def setUp(self) -> None:
        self.buyer = grant(
            User.objects.create_user(username="buyer", password="A-safe-password-2026!"),
            "manage_purchase_orders",
            "manage_suppliers",
        )
        self.viewer = grant(
            User.objects.create_user(username="viewer", password="A-safe-password-2026!"),
            "view_purchase_orders",
        )
        self.outsider = User.objects.create_user(
            username="outsider", password="A-safe-password-2026!"
        )
        self.supplier = create_supplier(
            actor=self.buyer, code="ก-001", name="ผู้ขายทดสอบ", credit_days=30
        )
        self.ordered_at = timezone.make_aware(datetime(2026, 11, 4, 10, 30))
        self.counter = 0

    def make_po(self, **overrides):
        self.counter += 1
        arguments = {
            "actor": self.buyer,
            "number": f"PO6911/{self.counter:03d}",
            "supplier": self.supplier,
            "total_amount": D("2140.00"),
            "ordered_at": self.ordered_at,
            "delivery_date": date(2026, 11, 10),
        }
        arguments.update(overrides)
        return create_purchase_order(**arguments)

    def edit(self, po, **changes):
        arguments = {
            "actor": self.buyer,
            "purchase_order": po,
            "number": po.number,
            "supplier": po.supplier,
            "total_amount": po.total_amount,
            "ordered_at": po.ordered_at,
            "delivery_date": po.delivery_date,
            "due_date": po.due_date,
            "status": po.status,
            "approval_status": po.approval_status,
            "note": po.note,
        }
        arguments.update(changes)
        return update_purchase_order(**arguments)


class SupplierServiceTests(ProcurementServiceTestCase):
    def test_supplier_code_must_be_unique(self) -> None:
        with self.assertRaises(ValidationError):
            create_supplier(actor=self.buyer, code="ก-001", name="ซ้ำ")

    def test_blank_codes_do_not_clash(self) -> None:
        create_supplier(actor=self.buyer, name="ไม่มีรหัส 1")
        create_supplier(actor=self.buyer, name="ไม่มีรหัส 2")

    def test_tax_id_is_normalized_and_validated(self) -> None:
        supplier = create_supplier(actor=self.buyer, name="x", tax_id="0-1055-12345-67-8")
        self.assertEqual(supplier.tax_id, "0105512345678")
        with self.assertRaises(ValidationError):
            create_supplier(actor=self.buyer, name="y", tax_id="12345")

    def test_viewer_cannot_create_supplier(self) -> None:
        with self.assertRaises(PermissionDenied):
            create_supplier(actor=self.viewer, name="ไม่มีสิทธิ์")

    def test_update_records_before_and_after(self) -> None:
        update_supplier(
            actor=self.buyer,
            supplier=self.supplier,
            code="ก-001",
            name=self.supplier.name,
            tax_id="",
            branch="",
            address="",
            contact_name="",
            phone="",
            email="",
            credit_days=45,
            is_active=True,
        )

        event = AuditEvent.objects.get(entity_id=str(self.supplier.pk), action="update")
        self.assertEqual((event.before["credit_days"], event.after["credit_days"]), (30, 45))


class PurchaseOrderCreationTests(ProcurementServiceTestCase):
    def test_due_date_is_delivery_date_plus_credit_days(self) -> None:
        po = self.make_po()

        self.assertEqual(po.due_date, date(2026, 11, 10) + timedelta(days=30))

    def test_explicit_due_date_is_kept(self) -> None:
        po = self.make_po(due_date=date(2026, 11, 20))

        self.assertEqual(po.due_date, date(2026, 11, 20))

    def test_due_date_before_delivery_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.make_po(due_date=date(2026, 11, 9))

    def test_three_decimal_total_is_rounded_half_up(self) -> None:
        # ระบบเดิมเก็บทศนิยม 3 ตำแหน่ง
        self.assertEqual(self.make_po(total_amount=D("1234.565")).total_amount, D("1234.57"))
        self.assertEqual(self.make_po(total_amount=D("1234.564")).total_amount, D("1234.56"))

    def test_number_is_normalized_and_unique(self) -> None:
        po = self.make_po(number=" po6911/028 ")
        self.assertEqual(po.number, "PO6911/028")

        with self.assertRaises(ValidationError):
            self.make_po(number="PO6911/028")

    def test_rejects_zero_total(self) -> None:
        with self.assertRaises(ValidationError):
            self.make_po(total_amount=D("0"))

    def test_inactive_supplier_cannot_be_used_for_new_po(self) -> None:
        self.supplier.is_active = False
        self.supplier.save()

        with self.assertRaises(ValidationError):
            self.make_po()

    def test_viewer_and_outsider_cannot_create(self) -> None:
        for actor in (self.viewer, self.outsider):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                self.make_po(actor=actor)

    def test_create_is_audited_with_actor(self) -> None:
        po = self.make_po()

        event = AuditEvent.objects.get(entity_type=PURCHASE_ORDER_ENTITY, entity_id=str(po.pk))
        self.assertEqual((event.action, event.actor), ("create", self.buyer))
        self.assertEqual(event.after["total_amount"], "2140.00")
        self.assertEqual(event.after["supplier"], "ก-001 ผู้ขายทดสอบ")


class PurchaseOrderEditTests(ProcurementServiceTestCase):
    def test_edit_records_only_changed_fields_with_reason(self) -> None:
        po = self.make_po()

        self.edit(po, total_amount=D("2675.00"), reason="ผู้ขายปรับราคา")

        event = AuditEvent.objects.get(entity_id=str(po.pk), action="update")
        self.assertEqual(event.actor, self.buyer)
        self.assertEqual(event.before, {"total_amount": "2140.00"})
        self.assertEqual(event.after, {"total_amount": "2675.00", "reason": "ผู้ขายปรับราคา"})

    def test_saving_without_changes_adds_no_history(self) -> None:
        po = self.make_po()

        self.edit(po, reason="ไม่ได้แก้อะไร")

        self.assertFalse(AuditEvent.objects.filter(entity_id=str(po.pk), action="update").exists())

    def test_blank_due_date_is_recalculated_from_new_delivery_date(self) -> None:
        po = self.make_po()

        po = self.edit(po, delivery_date=date(2026, 11, 15), due_date=None)

        self.assertEqual(po.due_date, date(2026, 12, 15))

    def test_status_and_approval_can_change_with_history(self) -> None:
        po = self.make_po(approval_status=ApprovalStatus.PENDING, number="PR6911/038")

        po = self.edit(
            po,
            number="PO6911/031",
            approval_status=ApprovalStatus.APPROVED,
            status=PurchaseOrderStatus.RECEIVED,
        )

        event = AuditEvent.objects.get(entity_id=str(po.pk), action="update")
        self.assertEqual(event.before["number"], "PR6911/038")
        self.assertEqual(event.after["number"], "PO6911/031")
        self.assertEqual(event.after["approval_status"], "approved")

    def test_cancelled_po_cannot_be_edited_or_cancelled_again(self) -> None:
        po = self.make_po()
        cancel_purchase_order(actor=self.buyer, purchase_order=po, reason="สั่งซ้ำ")

        with self.assertRaises(ValidationError):
            self.edit(po, total_amount=D("1.00"))
        with self.assertRaises(ValidationError):
            cancel_purchase_order(actor=self.buyer, purchase_order=po, reason="อีกครั้ง")

    def test_cancel_requires_reason(self) -> None:
        po = self.make_po()

        with self.assertRaises(ValidationError):
            cancel_purchase_order(actor=self.buyer, purchase_order=po, reason="  ")

    def test_viewer_cannot_edit_or_cancel(self) -> None:
        po = self.make_po()

        with self.assertRaises(PermissionDenied):
            self.edit(po, actor=self.viewer, total_amount=D("1.00"))
        with self.assertRaises(PermissionDenied):
            cancel_purchase_order(actor=self.viewer, purchase_order=po, reason="x")


class ExpectedOutflowTests(ProcurementServiceTestCase):
    def test_counts_only_approved_open_orders(self) -> None:
        new = self.make_po(delivery_date=date(2026, 11, 20))
        received = self.make_po(status=PurchaseOrderStatus.RECEIVED)
        self.make_po(approval_status=ApprovalStatus.PENDING)
        self.make_po(status=PurchaseOrderStatus.CLOSED)
        cancelled = self.make_po()
        cancel_purchase_order(actor=self.buyer, purchase_order=cancelled, reason="ซ้ำ")

        rows = expected_outflows(actor=self.viewer, today=date(2026, 12, 15))

        self.assertEqual([row.number for row in rows], [received.number, new.number])
        self.assertTrue(rows[0].is_overdue)  # ครบกำหนด 10 ธ.ค.
        self.assertFalse(rows[1].is_overdue)  # ครบกำหนด 20 ธ.ค.
        self.assertEqual(rows[0].amount, D("2140.00"))

    def test_outsider_cannot_read_expected_outflows(self) -> None:
        with self.assertRaises(PermissionDenied):
            expected_outflows(actor=self.outsider)
