from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cashflow.modules.identity.models import User
from cashflow.modules.procurement.models import PurchaseOrder, PurchaseOrderStatus
from cashflow.modules.procurement.services import create_purchase_order, create_supplier


def grant(user: User, *codenames: str) -> User:
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="procurement", codename__in=codenames)
    )
    return User.objects.get(pk=user.pk)


class PurchaseOrderViewTests(TestCase):
    def setUp(self) -> None:
        self.buyer = grant(
            User.objects.create_user(
                username="buyer", password="A-safe-password-2026!", display_name="ฝ่ายจัดซื้อ"
            ),
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

    def post_data(self, **overrides) -> dict[str, str]:
        data = {
            "number": "PO6911/028",
            "supplier": str(self.supplier.pk),
            "total_amount": "749",
            "ordered_at": "2026-11-04T15:13",
            "delivery_date": "2026-11-09",
            "due_date": "",
            "status": "new",
            "approval_status": "approved",
            "note": "",
        }
        data.update(overrides)
        return data

    def make_po(self) -> PurchaseOrder:
        return create_purchase_order(
            actor=self.buyer,
            number="PO6911/030",
            supplier=self.supplier,
            total_amount=Decimal("39292.326"),
            ordered_at=timezone.make_aware(datetime(2026, 11, 4, 8, 54)),
            delivery_date=date(2026, 11, 26),
        )

    def test_outsider_cannot_open_purchase_orders(self) -> None:
        self.client.force_login(self.outsider)

        for name in ("web:purchase-order-list", "web:supplier-list"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_viewer_sees_list_but_cannot_create(self) -> None:
        self.make_po()
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("web:purchase-order-list"))
        self.assertContains(response, "PO6911/030")
        self.assertContains(response, "39,292.33")
        self.assertNotContains(response, reverse("web:purchase-order-create"))
        self.assertEqual(self.client.get(reverse("web:purchase-order-create")).status_code, 403)

    def test_buyer_records_po_through_form(self) -> None:
        self.client.force_login(self.buyer)

        response = self.client.post(reverse("web:purchase-order-create"), self.post_data())

        po = PurchaseOrder.objects.get()
        self.assertRedirects(response, reverse("web:purchase-order-detail", args=[po.pk]))
        self.assertEqual(po.total_amount, Decimal("749.00"))
        self.assertEqual(po.due_date, date(2026, 12, 9))
        self.assertEqual(timezone.localtime(po.ordered_at).hour, 15)
        self.assertEqual(po.created_by, self.buyer)

    def test_save_and_new_returns_to_empty_form(self) -> None:
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("web:purchase-order-create"), self.post_data(save_and_new="1")
        )

        self.assertRedirects(response, reverse("web:purchase-order-create"))

    def test_buddhist_year_is_rejected_with_hint(self) -> None:
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("web:purchase-order-create"), self.post_data(delivery_date="2569-11-09")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "กรอกปีเป็น ค.ศ.")
        self.assertFalse(PurchaseOrder.objects.exists())

    def test_duplicate_number_shows_field_error(self) -> None:
        self.make_po()
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("web:purchase-order-create"), self.post_data(number="po6911/030")
        )

        self.assertContains(response, "มีอยู่ในระบบแล้ว")

    def test_edit_shows_old_and_new_values_in_history(self) -> None:
        po = self.make_po()
        self.client.force_login(self.buyer)

        self.client.post(
            reverse("web:purchase-order-edit", args=[po.pk]),
            self.post_data(
                number="PO6911/030",
                total_amount="41000",
                ordered_at="2026-11-04T08:54",
                delivery_date="2026-11-26",
                reason="ผู้ขายปรับราคา",
            ),
        )
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("web:purchase-order-detail", args=[po.pk]))

        self.assertContains(response, "แก้ไขข้อมูล")
        self.assertContains(response, "ฝ่ายจัดซื้อ")
        self.assertContains(response, "<del>39,292.33</del>", html=False)
        self.assertContains(response, "<ins>41,000.00</ins>", html=False)
        self.assertContains(response, "เหตุผล: ผู้ขายปรับราคา")

    def test_cancel_without_reason_is_rejected(self) -> None:
        po = self.make_po()
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("web:purchase-order-cancel", args=[po.pk]), {"reason": ""}
        )

        self.assertEqual(response.status_code, 400)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrderStatus.NEW)

    def test_cancelled_po_cannot_be_opened_for_edit(self) -> None:
        po = self.make_po()
        self.client.force_login(self.buyer)
        self.client.post(reverse("web:purchase-order-cancel", args=[po.pk]), {"reason": "สั่งซ้ำ"})

        response = self.client.get(reverse("web:purchase-order-edit", args=[po.pk]))

        self.assertRedirects(response, reverse("web:purchase-order-detail", args=[po.pk]))

    def test_viewer_cannot_post_edit_or_cancel(self) -> None:
        po = self.make_po()
        self.client.force_login(self.viewer)

        for name in ("web:purchase-order-edit", "web:purchase-order-cancel"):
            with self.subTest(name=name):
                response = self.client.post(reverse(name, args=[po.pk]), {"reason": "x"})
                self.assertEqual(response.status_code, 403)

    def test_dashboard_lists_approved_po_as_expected_outflow(self) -> None:
        po = self.make_po()
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("web:dashboard"))

        self.assertContains(response, "เงินออกที่คาดว่าจะจ่ายตามใบสั่งซื้อ")
        self.assertContains(response, po.number)
        self.assertContains(response, "-฿39,292.33")

    def test_nav_shows_purchase_orders_only_with_permission(self) -> None:
        self.client.force_login(self.outsider)
        self.assertNotContains(
            self.client.get(reverse("web:dashboard")), reverse("web:purchase-order-list")
        )
        self.client.force_login(self.viewer)
        self.assertContains(
            self.client.get(reverse("web:dashboard")), reverse("web:purchase-order-list")
        )
