"""ขั้นที่ 1/3: เปลี่ยนโครงสร้าง PO แบบมีรายการสินค้า เป็นทะเบียน PO ตามคอลัมน์รายงานของระบบเดิม

ข้อมูลเดิมยังอยู่: ยอดรวม VAT เดิมคงไว้, วันที่สั่งซื้อกลายเป็นวันเวลาทำรายการ
และใช้เป็นวันที่จัดส่งตั้งต้น, สถานะร่าง/ส่งแล้วกลายเป็น "ใบสั่งซื้อใหม่"
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="purchaseorder",
            name="po_due_date_not_before_order_date",
        ),
        migrations.DeleteModel(name="PurchaseOrderLine"),
        migrations.DeleteModel(name="PurchaseOrderSequence"),
        migrations.RemoveField(model_name="purchaseorder", name="subtotal"),
        migrations.RemoveField(model_name="purchaseorder", name="vat_amount"),
        migrations.RemoveField(model_name="purchaseorder", name="wht_amount"),
        migrations.RemoveField(model_name="purchaseorder", name="net_payable"),
        migrations.RemoveField(model_name="purchaseorder", name="vat_rate"),
        migrations.RemoveField(model_name="purchaseorder", name="reference"),
        migrations.RenameField(
            model_name="purchaseorder", old_name="order_date", new_name="ordered_at"
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="ordered_at",
            field=models.DateTimeField(verbose_name="วันเวลาทำรายการ"),
        ),
        migrations.AlterModelOptions(
            name="purchaseorder",
            options={
                "default_permissions": (),
                "ordering": ("-ordered_at", "-number"),
                "permissions": (
                    ("view_purchase_orders", "ดูใบสั่งซื้อและผู้ขาย"),
                    ("manage_purchase_orders", "บันทึก แก้ไข และยกเลิกใบสั่งซื้อ"),
                    ("manage_suppliers", "เพิ่มและแก้ไขข้อมูลผู้ขาย"),
                ),
                "verbose_name": "ใบสั่งซื้อ",
                "verbose_name_plural": "ใบสั่งซื้อ",
            },
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="delivery_date",
            field=models.DateField(null=True, verbose_name="วันที่จัดส่ง"),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="approval_status",
            field=models.CharField(
                choices=[("pending", "รออนุมัติ"), ("approved", "อนุมัติ")],
                default="approved",
                max_length=20,
                verbose_name="สถานะอนุมัติ",
            ),
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "ใบสั่งซื้อใหม่"),
                    ("received", "รับของแล้ว"),
                    ("closed", "ปิดแล้ว"),
                    ("cancelled", "ยกเลิก"),
                ],
                default="new",
                max_length=20,
                verbose_name="สถานะ",
            ),
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="number",
            field=models.CharField(max_length=30, unique=True, verbose_name="หมายเลข PO"),
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="total_amount",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=14, verbose_name="ยอดรวม (รวม VAT)"
            ),
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="created_by",
            field=models.ForeignKey(
                on_delete=models.deletion.PROTECT,
                related_name="+",
                to="identity.user",
                verbose_name="ผู้บันทึก",
            ),
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, verbose_name="บันทึกเมื่อ"),
        ),
        migrations.AddField(
            model_name="supplier",
            name="code",
            field=models.CharField(blank=True, max_length=20, verbose_name="รหัสผู้ขาย"),
        ),
        migrations.AddConstraint(
            model_name="supplier",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("code",),
                name="supplier_code_unique_when_set",
            ),
        ),
    ]
