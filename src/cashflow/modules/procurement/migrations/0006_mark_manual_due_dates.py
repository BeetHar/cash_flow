"""PO เดิมที่วันครบกำหนดจ่ายไม่เท่ากับวันที่จัดส่ง + เครดิต ถือว่ากำหนดเอง"""

from datetime import timedelta

from django.db import migrations


def mark_manual(apps, schema_editor):
    PurchaseOrder = apps.get_model("procurement", "PurchaseOrder")
    for order in PurchaseOrder.objects.order_by().select_related("supplier"):
        computed = order.delivery_date + timedelta(days=order.supplier.credit_days or 0)
        if order.due_date != computed:
            order.due_date_manual = True
            order.save(update_fields=["due_date_manual"])


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0005_supplier_import_fields"),
    ]

    operations = [
        migrations.RunPython(mark_manual, migrations.RunPython.noop),
    ]
