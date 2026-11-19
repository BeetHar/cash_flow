from decimal import Decimal

from django import forms
from django.utils import timezone

from cashflow.modules.receivables.models import Customer

from .procurement_forms import DateInput, _reject_buddhist_year

MONEY_WIDGET = forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"})


class CustomerForm(forms.Form):
    code = forms.CharField(label="รหัสลูกค้า", max_length=30, required=False)
    name = forms.CharField(label="ชื่อลูกค้า", max_length=255)
    credit_days = forms.IntegerField(
        label="เครดิต (วัน)", min_value=0, max_value=365, required=False,
        help_text="วันที่คาดว่าจะได้รับเงิน = วันที่ใบขาย + เครดิต เว้นว่าง = ไม่ระบุ",
    )
    is_active = forms.BooleanField(label="ใช้งานอยู่", required=False, initial=True)

    def __init__(self, *args, customer: Customer | None = None, **kwargs):
        if customer is not None:
            kwargs.setdefault("initial", {}).update(
                code=customer.code, name=customer.name, credit_days=customer.credit_days, is_active=customer.is_active
            )
        super().__init__(*args, **kwargs)


class CustomerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, customer: Customer) -> str:
        credit = "ไม่ระบุ" if customer.credit_days is None else f"{customer.credit_days} วัน"
        return f"{customer} (เครดิต {credit})"


class InvoiceForm(forms.Form):
    number = forms.CharField(label="เลขที่ใบขาย", max_length=40, help_text="เช่น IV6911/00480")
    customer = CustomerChoiceField(label="ลูกค้า", queryset=Customer.objects.none(), empty_label="เลือกลูกค้า")
    amount = forms.DecimalField(label="ยอดสุทธิ", max_digits=15, decimal_places=3, min_value=Decimal("0.001"), widget=MONEY_WIDGET)
    document_date = forms.DateField(label="วันที่ใบขาย", widget=DateInput())
    due_date = forms.DateField(
        label="วันที่คาดว่าจะได้รับเงิน", required=False, widget=DateInput(),
        help_text="เว้นว่างไว้ ระบบจะใช้วันที่ใบขาย + เครดิตลูกค้า",
    )
    reference = forms.CharField(label="เลขที่ PO ลูกค้า", max_length=60, required=False)
    branch = forms.CharField(label="สาขา", max_length=120, required=False)
    note = forms.CharField(label="หมายเหตุ", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    reason = forms.CharField(label="เหตุผลที่แก้ไข", max_length=500, required=False)

    def __init__(self, *args, customer_queryset, invoice=None, **kwargs):
        if invoice is not None:
            kwargs.setdefault("initial", {}).update(
                number=invoice.number, customer=invoice.customer_id, amount=invoice.amount,
                document_date=invoice.document_date, due_date=invoice.due_date if invoice.due_date_manual else None,
                reference=invoice.reference, branch=invoice.branch, note=invoice.note,
            )
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = customer_queryset
        if invoice is None:
            del self.fields["reason"]

    def clean_document_date(self):
        return _reject_buddhist_year(self.cleaned_data["document_date"])

    def clean_due_date(self):
        return _reject_buddhist_year(self.cleaned_data["due_date"])


class ReceiveForm(forms.Form):
    received_date = forms.DateField(label="วันที่รับเงินจริง", widget=DateInput(), initial=timezone.localdate)
    received_amount = forms.DecimalField(label="ยอดรับจริง", max_digits=15, decimal_places=3, min_value=Decimal("0"), widget=MONEY_WIDGET)
    reason = forms.CharField(label="หมายเหตุ", max_length=500, required=False, help_text="เช่น ลูกค้าหักค่าธรรมเนียม หรือโอนมาสองก้อน")

    def clean_received_date(self):
        return _reject_buddhist_year(self.cleaned_data["received_date"])


class ReasonForm(forms.Form):
    reason = forms.CharField(label="เหตุผล", max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))


class PlanForm(forms.Form):
    customer = CustomerChoiceField(label="ลูกค้า", queryset=Customer.objects.none(), empty_label="เลือกลูกค้า")
    plan_date = forms.DateField(label="วันที่คาดว่าจะได้รับ", widget=DateInput())
    amount = forms.DecimalField(label="ยอดประมาณการ", max_digits=15, decimal_places=2, min_value=Decimal("0.01"), widget=MONEY_WIDGET)
    note = forms.CharField(label="หมายเหตุ", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    reason = forms.CharField(label="เหตุผลที่แก้ไข", max_length=500, required=False)

    def __init__(self, *args, customer_queryset=None, plan=None, **kwargs):
        if plan is not None:
            kwargs.setdefault("initial", {}).update(plan_date=plan.plan_date, amount=plan.amount, note=plan.note)
        super().__init__(*args, **kwargs)
        if plan is None:
            self.fields["customer"].queryset = customer_queryset
            del self.fields["reason"]
        else:
            del self.fields["customer"]

    def clean_plan_date(self):
        return _reject_buddhist_year(self.cleaned_data["plan_date"])


class InvoiceImportForm(forms.Form):
    customer = CustomerChoiceField(label="ไฟล์นี้เป็นของลูกค้า", queryset=Customer.objects.none(), empty_label="เลือกลูกค้า")
    file = forms.FileField(label="ไฟล์ Excel (.xlsx)", help_text="เช่น รายการคำสั่งซื้อแม็คโคร ที่เสร็จสิ้นแล้ว")

    def __init__(self, *args, customer_queryset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = customer_queryset

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("รองรับเฉพาะไฟล์ .xlsx")
        if upload.size > 15 * 1024 * 1024:
            raise forms.ValidationError("ไฟล์ใหญ่เกิน 15 MB")
        return upload
