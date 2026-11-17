import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

MONEY = {"max_digits": 14, "decimal_places": 2}
ZERO = Decimal("0.00")


class Supplier(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField("รหัสผู้ขาย", max_length=20, blank=True)
    name = models.CharField("ชื่อผู้ขาย", max_length=255)
    tax_id = models.CharField("เลขประจำตัวผู้เสียภาษี", max_length=13, blank=True)
    branch = models.CharField("สำนักงานใหญ่/สาขา", max_length=100, blank=True)
    address = models.TextField("ที่อยู่", blank=True)
    contact_name = models.CharField("ผู้ติดต่อ", max_length=150, blank=True)
    phone = models.CharField("โทรศัพท์", max_length=50, blank=True)
    email = models.EmailField("อีเมล", blank=True)
    description = models.CharField("รายละเอียด", max_length=255, blank=True)
    supplier_type = models.CharField("ประเภทผู้ขาย", max_length=100, blank=True)
    credit_group = models.CharField("กลุ่มเจ้าหนี้", max_length=150, blank=True)
    # None = ไม่ระบุ ระบบนับเป็น 0 วันและติดป้ายให้ฝ่ายบัญชีมากรอก
    credit_days = models.PositiveIntegerField(
        "เครดิตเทอม (วัน)", null=True, blank=True, default=None
    )
    is_active = models.BooleanField("ใช้งานอยู่", default=True)
    created_at = models.DateTimeField("สร้างเมื่อ", auto_now_add=True)
    updated_at = models.DateTimeField("แก้ไขล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "ผู้ขาย"
        verbose_name_plural = "ผู้ขาย"
        ordering = ("name",)
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=("code",),
                condition=~models.Q(code=""),
                name="supplier_code_unique_when_set",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}".strip()

    @property
    def credit_unknown(self) -> bool:
        return self.credit_days is None


class PurchaseOrderStatus(models.TextChoices):
    """ชื่อสถานะตามรายงานของระบบ PO เดิม แก้หรือเพิ่มได้ที่นี่ที่เดียว"""

    NEW = "new", "ใบสั่งซื้อใหม่"
    RECEIVED = "received", "รับของแล้ว"
    CLOSED = "closed", "ปิดแล้ว"
    CANCELLED = "cancelled", "ยกเลิก"


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "รออนุมัติ"
    APPROVED = "approved", "อนุมัติ"


class PurchaseOrder(models.Model):
    """ทะเบียน PO: เก็บช่องเดียวกับรายงาน PO ของระบบเดิม และบันทึกทุกการแก้ไขลง audit"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField("หมายเลข PO", max_length=30, unique=True)
    supplier = models.ForeignKey(
        Supplier,
        verbose_name="ผู้ขาย",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    total_amount = models.DecimalField("ยอดรวม (รวม VAT)", default=ZERO, **MONEY)
    ordered_at = models.DateTimeField("วันเวลาทำรายการ")
    delivery_date = models.DateField("วันที่จัดส่ง")
    due_date = models.DateField("วันครบกำหนดจ่าย")
    # False = คำนวณจากวันที่จัดส่ง + เครดิต และคำนวณใหม่เมื่อเครดิตของผู้ขายเปลี่ยน
    due_date_manual = models.BooleanField("กำหนดวันครบกำหนดจ่ายเอง", default=False)
    status = models.CharField(
        "สถานะ",
        max_length=20,
        choices=PurchaseOrderStatus.choices,
        default=PurchaseOrderStatus.NEW,
    )
    approval_status = models.CharField(
        "สถานะอนุมัติ",
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.APPROVED,
    )
    note = models.TextField("หมายเหตุ", blank=True)
    cancel_reason = models.TextField("เหตุผลที่ยกเลิก", blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ผู้บันทึก",
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField("บันทึกเมื่อ", auto_now_add=True)
    updated_at = models.DateTimeField("แก้ไขล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "ใบสั่งซื้อ"
        verbose_name_plural = "ใบสั่งซื้อ"
        ordering = ("-ordered_at", "-number")
        default_permissions = ()
        permissions = (
            ("view_purchase_orders", "ดูใบสั่งซื้อและผู้ขาย"),
            ("manage_purchase_orders", "บันทึก แก้ไข และยกเลิกใบสั่งซื้อ"),
            ("manage_suppliers", "เพิ่มและแก้ไขข้อมูลผู้ขาย"),
        )
        indexes = [
            models.Index(fields=("status", "due_date")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(due_date__gte=models.F("delivery_date")),
                name="po_due_date_not_before_delivery_date",
            ),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def is_editable(self) -> bool:
        return self.status != PurchaseOrderStatus.CANCELLED
