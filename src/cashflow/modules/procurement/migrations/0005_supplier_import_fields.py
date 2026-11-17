from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0004_purchase_order_register_constraints"),
    ]

    operations = [
        migrations.AlterField(
            model_name="supplier",
            name="credit_days",
            field=models.PositiveIntegerField(
                blank=True, default=None, null=True, verbose_name="เครดิตเทอม (วัน)"
            ),
        ),
        migrations.AddField(
            model_name="supplier",
            name="description",
            field=models.CharField(blank=True, max_length=255, verbose_name="รายละเอียด"),
        ),
        migrations.AddField(
            model_name="supplier",
            name="supplier_type",
            field=models.CharField(blank=True, max_length=100, verbose_name="ประเภทผู้ขาย"),
        ),
        migrations.AddField(
            model_name="supplier",
            name="credit_group",
            field=models.CharField(blank=True, max_length=150, verbose_name="กลุ่มเจ้าหนี้"),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="due_date_manual",
            field=models.BooleanField(default=False, verbose_name="กำหนดวันครบกำหนดจ่ายเอง"),
        ),
    ]
