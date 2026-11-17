from datetime import date
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from cashflow.modules.procurement.constants import MAX_CREDIT_DAYS
from cashflow.modules.procurement.models import (
    ApprovalStatus,
    PurchaseOrder,
    PurchaseOrderStatus,
    Supplier,
)
from cashflow.modules.procurement.services import EDITABLE_STATUSES

BUDDHIST_YEAR_THRESHOLD = 2400
MAX_IMPORT_BYTES = 15 * 1024 * 1024


def _reject_buddhist_year(value: date | None) -> date | None:
    """ช่องวันที่ของเบราว์เซอร์ใช้ปี ค.ศ. ถ้ากรอก 2569 จะกลายเป็นปี ค.ศ. 2569"""

    if value is not None and value.year >= BUDDHIST_YEAR_THRESHOLD:
        raise ValidationError(
            f"กรอกปีเป็น ค.ศ. เช่น {value.year - 543} (ไม่ใช่ พ.ศ. {value.year})"
        )
    return value


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(**kwargs)


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%dT%H:%M")
        super().__init__(**kwargs)


class SupplierForm(forms.Form):
    code = forms.CharField(
        label="รหัสผู้ขาย",
        max_length=20,
        required=False,
        help_text="รหัสเดียวกับในระบบ PO เดิม เช่น ก-001",
    )
    name = forms.CharField(label="ชื่อผู้ขาย", max_length=255)
    tax_id = forms.CharField(
        label="เลขประจำตัวผู้เสียภาษี",
        max_length=17,
        required=False,
        help_text="ตัวเลข 13 หลัก มีขีดหรือเว้นวรรคได้",
        widget=forms.TextInput(attrs={"inputmode": "numeric"}),
    )
    branch = forms.CharField(
        label="สำนักงานใหญ่/สาขา",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "เช่น สำนักงานใหญ่ หรือ สาขา 00001"}),
    )
    credit_days = forms.IntegerField(
        label="เครดิตเทอม (วัน)",
        min_value=0,
        max_value=MAX_CREDIT_DAYS,
        required=False,
        help_text="เว้นว่าง = ไม่ระบุ (นับเป็น 0 วันจนกว่าจะกรอก) เมื่อแก้ PO ที่ยังเปิดอยู่จะเลื่อนวันครบกำหนดตาม",
    )
    supplier_type = forms.CharField(label="ประเภท", max_length=100, required=False)
    description = forms.CharField(label="รายละเอียด", max_length=255, required=False)
    contact_name = forms.CharField(label="ผู้ติดต่อ", max_length=150, required=False)
    phone = forms.CharField(label="โทรศัพท์", max_length=50, required=False)
    email = forms.EmailField(label="อีเมล", required=False)
    address = forms.CharField(
        label="ที่อยู่", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    is_active = forms.BooleanField(label="ใช้งานอยู่", required=False, initial=True)

    def __init__(self, *args, supplier: Supplier | None = None, **kwargs):
        if supplier is not None:
            initial = kwargs.setdefault("initial", {})
            initial.update(
                {
                    field: getattr(supplier, field)
                    for field in (
                        "code",
                        "name",
                        "tax_id",
                        "branch",
                        "credit_days",
                        "supplier_type",
                        "description",
                        "contact_name",
                        "phone",
                        "email",
                        "address",
                        "is_active",
                    )
                }
            )
        super().__init__(*args, **kwargs)


class SupplierImportForm(forms.Form):
    file = forms.FileField(
        label="ไฟล์ Excel (.xlsx)",
        help_text="ไฟล์ที่มีชีต “รายการ ผู้ผลิต” และ “เครดิต”",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith(".xlsx"):
            raise ValidationError("รองรับเฉพาะไฟล์ .xlsx")
        if upload.size > MAX_IMPORT_BYTES:
            raise ValidationError("ไฟล์ใหญ่เกิน 15 MB")
        return upload


class SupplierChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, supplier: Supplier) -> str:
        label = f"{supplier.code} {supplier.name}".strip()
        credit = "ไม่ระบุ" if supplier.credit_days is None else f"{supplier.credit_days} วัน"
        label = f"{label} (เครดิต {credit})"
        return label if supplier.is_active else f"{label} — ปิดใช้งานแล้ว"


class PurchaseOrderForm(forms.Form):
    number = forms.CharField(
        label="หมายเลข PO",
        max_length=30,
        help_text="เลขเดียวกับในระบบเดิม เช่น PO6911/028 หรือ PR6911/038",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    supplier = SupplierChoiceField(
        label="ผู้ขาย", queryset=Supplier.objects.none(), empty_label="เลือกผู้ขาย"
    )
    total_amount = forms.DecimalField(
        label="ยอดรวม (รวม VAT)",
        max_digits=15,
        decimal_places=3,
        min_value=Decimal("0.001"),
        help_text="ถ้ามีทศนิยม 3 ตำแหน่ง ระบบจะปัดเป็นสตางค์",
        widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
    )
    ordered_at = forms.DateTimeField(
        label="วันเวลาทำรายการ",
        widget=DateTimeInput(),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )
    delivery_date = forms.DateField(label="วันที่จัดส่ง", widget=DateInput())
    due_date = forms.DateField(
        label="วันครบกำหนดจ่าย",
        required=False,
        widget=DateInput(),
        help_text="เว้นว่างไว้ ระบบจะใช้วันที่จัดส่ง + เครดิตเทอมของผู้ขาย",
    )
    status = forms.ChoiceField(
        label="สถานะ",
        choices=[(value, PurchaseOrderStatus(value).label) for value in EDITABLE_STATUSES],
        initial=PurchaseOrderStatus.NEW,
    )
    approval_status = forms.ChoiceField(
        label="สถานะอนุมัติ",
        choices=ApprovalStatus.choices,
        initial=ApprovalStatus.APPROVED,
    )
    note = forms.CharField(
        label="หมายเหตุ", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    reason = forms.CharField(
        label="เหตุผลที่แก้ไข",
        required=False,
        max_length=500,
        help_text="ไม่บังคับ แต่ช่วยให้คนที่ดูประวัติเข้าใจว่าแก้เพราะอะไร",
        widget=forms.TextInput(attrs={"placeholder": "เช่น ผู้ขายแจ้งเลื่อนวันส่ง"}),
    )

    def __init__(
        self,
        *args,
        supplier_queryset,
        purchase_order: PurchaseOrder | None = None,
        **kwargs,
    ):
        initial = kwargs.setdefault("initial", {})
        if purchase_order is not None:
            initial.update(
                {
                    "number": purchase_order.number,
                    "supplier": purchase_order.supplier_id,
                    "total_amount": purchase_order.total_amount,
                    "ordered_at": timezone.localtime(purchase_order.ordered_at),
                    "delivery_date": purchase_order.delivery_date,
                    # ว่างไว้ถ้าระบบคำนวณให้ เพื่อให้คำนวณใหม่เมื่อเปลี่ยนวันจัดส่งหรือผู้ขาย
                    "due_date": purchase_order.due_date
                    if purchase_order.due_date_manual
                    else None,
                    "status": purchase_order.status,
                    "approval_status": purchase_order.approval_status,
                    "note": purchase_order.note,
                }
            )
        else:
            initial.setdefault("ordered_at", timezone.localtime().replace(second=0, microsecond=0))
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = supplier_queryset
        if purchase_order is None:
            del self.fields["reason"]

    def clean_ordered_at(self):
        value = self.cleaned_data["ordered_at"]
        _reject_buddhist_year(value.date() if value else None)
        return value

    def clean_delivery_date(self):
        return _reject_buddhist_year(self.cleaned_data["delivery_date"])

    def clean_due_date(self):
        return _reject_buddhist_year(self.cleaned_data["due_date"])


class CancelPurchaseOrderForm(forms.Form):
    reason = forms.CharField(
        label="เหตุผลที่ยกเลิก",
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=1000,
    )
