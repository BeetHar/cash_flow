import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

MONEY = {"max_digits": 14, "decimal_places": 2}


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField("รหัสลูกค้า", max_length=30, blank=True)
    name = models.CharField("ชื่อลูกค้า", max_length=255)
    # None = ไม่ระบุ นับเป็น 0 วันจนกว่าจะกรอก เหมือนเครดิตของผู้ขาย
    credit_days = models.PositiveIntegerField("เครดิต (วัน)", null=True, blank=True)
    is_active = models.BooleanField("ใช้งานอยู่", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ลูกค้า"
        verbose_name_plural = "ลูกค้า"
        ordering = ("code", "name")
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=("code",), condition=~models.Q(code=""), name="customer_code_unique_when_set"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}".strip()


class InvoiceStatus(models.TextChoices):
    OPEN = "open", "รอรับเงิน"
    RECEIVED = "received", "รับเงินแล้ว"
    CANCELLED = "cancelled", "ยกเลิก"


class ReceiptPlan(models.Model):
    """ประมาณการรับเงินจากลูกค้า ก่อนมีบิลจริง แล้วผูกบิลจริงเข้ามาเทียบ"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, verbose_name="ลูกค้า", on_delete=models.PROTECT, related_name="plans")
    plan_date = models.DateField("วันที่คาดว่าจะได้รับ")
    amount = models.DecimalField("ยอดประมาณการ", **MONEY)
    note = models.TextField("หมายเหตุ", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "แผนรับเงิน"
        verbose_name_plural = "แผนรับเงิน"
        ordering = ("-plan_date",)
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="receipt_plan_amount_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.customer} {self.plan_date}"


class SalesInvoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField("เลขที่ใบขาย", max_length=40, unique=True)
    customer = models.ForeignKey(Customer, verbose_name="ลูกค้า", on_delete=models.PROTECT, related_name="invoices")
    reference = models.CharField("เลขที่ PO ลูกค้า", max_length=60, blank=True)
    branch = models.CharField("สาขา", max_length=120, blank=True)
    amount = models.DecimalField("ยอดสุทธิ", **MONEY)
    document_date = models.DateField("วันที่ใบขาย")
    due_date = models.DateField("วันที่คาดว่าจะได้รับเงิน")
    due_date_manual = models.BooleanField(default=False)
    status = models.CharField("สถานะ", max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.OPEN)
    received_date = models.DateField("วันที่รับเงินจริง", null=True, blank=True)
    received_amount = models.DecimalField("ยอดรับจริง", null=True, blank=True, **MONEY)
    plan = models.ForeignKey(
        ReceiptPlan, verbose_name="แผนรับเงิน", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    note = models.TextField("หมายเหตุ", blank=True)
    cancel_reason = models.TextField("เหตุผลที่ยกเลิก", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ใบขาย"
        verbose_name_plural = "ใบขาย"
        ordering = ("-document_date", "-number")
        default_permissions = ()
        permissions = (
            ("view_receivables", "ดูใบขาย ลูกค้า และแผนรับเงิน"),
            ("manage_receivables", "บันทึกใบขาย รับเงิน และแผนรับเงิน"),
        )
        indexes = [models.Index(fields=("status", "due_date"))]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="sales_invoice_amount_positive"),
            models.CheckConstraint(
                condition=models.Q(due_date__gte=models.F("document_date")), name="sales_invoice_due_after_document"
            ),
            models.CheckConstraint(
                condition=~models.Q(status="received")
                | (models.Q(received_date__isnull=False) & models.Q(received_amount__isnull=False)),
                name="sales_invoice_received_has_date_and_amount",
            ),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def difference(self) -> Decimal | None:
        if self.received_amount is None:
            return None
        return self.received_amount - self.amount
