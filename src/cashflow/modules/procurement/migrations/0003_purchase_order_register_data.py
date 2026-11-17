"""ขั้นที่ 2/3: แปลงข้อมูลเดิม แยกไฟล์เพราะ PostgreSQL ไม่ยอมให้แก้ข้อมูลกับแก้ตารางใน transaction เดียวกัน"""

from django.db import migrations
from django.utils import timezone


def forward_fill(apps, schema_editor):
    PurchaseOrder = apps.get_model("procurement", "PurchaseOrder")
    # order_by() ล้างการเรียงลำดับตั้งต้นของ model ช่วงกลาง migration
    for order in PurchaseOrder.objects.order_by():
        order.delivery_date = timezone.localtime(order.ordered_at).date()
        if order.status in ("draft", "sent"):
            order.status = "new"
        order.save(update_fields=["delivery_date", "status"])


def rename_permission(apps, schema_editor):
    # Django ไม่เปลี่ยนชื่อสิทธิ์ที่มีอยู่แล้วให้เอง ฐานข้อมูลใหม่จะได้ชื่อใหม่จาก post_migrate
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        content_type__app_label="procurement", codename="manage_purchase_orders"
    ).update(name="บันทึก แก้ไข และยกเลิกใบสั่งซื้อ")


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0002_purchase_order_register"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(forward_fill, migrations.RunPython.noop),
        migrations.RunPython(rename_permission, migrations.RunPython.noop),
    ]
