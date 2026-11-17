"""ขั้นที่ 3/3: บังคับให้ทุก PO มีวันที่จัดส่ง และวันครบกำหนดจ่ายไม่ก่อนวันจัดส่ง"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0003_purchase_order_register_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorder",
            name="delivery_date",
            field=models.DateField(verbose_name="วันที่จัดส่ง"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.CheckConstraint(
                condition=models.Q(due_date__gte=models.F("delivery_date")),
                name="po_due_date_not_before_delivery_date",
            ),
        ),
    ]
