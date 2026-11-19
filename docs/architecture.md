# Architecture

อัปเดตล่าสุด: 2026-11-19

## เป้าหมาย

ระบบประกอบจากชิ้นส่วนที่มีขอบเขตชัดเจน เพื่อให้เปลี่ยน UI หรือเพิ่มโมดูลธุรกิจได้โดยไม่ย้ายกติกาเดิมตามไปด้วย

## โครงสร้างปัจจุบัน

```text
Docker / Compose
    ├── PostgreSQL
    └── Django application
            ├── config                     ประกอบระบบและตั้งค่า
            ├── modules/identity           ผู้ใช้ รหัสผ่าน session และสิทธิ์
            │       └── services           จุดเรียกใช้ logic จากภายนอกโมดูล
            ├── modules/audit              Audit Event แบบ append-only
            ├── modules/receivables        ลูกค้า ใบขาย แผนรับเงิน และนำเข้าใบขาย
            ├── modules/procurement        ผู้ขายและทะเบียนใบสั่งซื้อ
            │       ├── xlsx_reader        อ่าน .xlsx ด้วย standard library
            │       ├── supplier_import    นำเข้าผู้ขายจาก Excel ของระบบเดิม
            │       ├── policies           ตรวจสิทธิ์
            │       └── services           จุดเรียกใช้จากภายนอกโมดูล
            └── presentation/web           views, forms, templates และ CSS
```

## กฎการพึ่งพา

- `presentation/web` เรียกใช้ public service ของ `modules/identity`
- `modules/identity` ห้าม import template, form, view หรือ CSS จาก presentation
- โมดูลธุรกิจใหม่ต้องเก็บ model และ logic ของตัวเองใต้ `modules/<module-name>`
- UI ใหม่ เช่น REST API หรือ mobile API สามารถเพิ่มใต้ `presentation/` และใช้ service เดิม
- `config` เชื่อม URL, settings และ application startup แต่ไม่เก็บ business logic
- PostgreSQL เป็น persistence หลัก ทุก schema change ผ่าน Django migration

## ชิ้นส่วนแรก

### Infrastructure

- `Dockerfile` สร้าง application image
- `compose.yaml` เชื่อม Django กับ PostgreSQL และเก็บข้อมูลใน named volume
- `docker/entrypoint.dev.sh` รัน migration และสร้าง Admin สำหรับ development ก่อนเปิด server

### Identity

- Custom User model ถูกสร้างตั้งแต่ migration แรก เพื่อให้ขยายในอนาคตได้
- Django Groups ทำหน้าที่เป็นบทบาท และ Django Permissions เป็นสิทธิ์ย่อย
- Authentication service แยกการตรวจรหัสผ่านและ session ออกจากหน้าเว็บ
- รหัสผ่านเก็บเป็น password hash ผ่าน Django เท่านั้น
- Business Admin ใช้ custom permissions `manage_application_users` และ `manage_application_roles` โดยไม่ต้องเป็น Django staff
- Developer เป็น superuser แยกต่างหากและเข้าถึง `/system-admin/`

### Audit

- Identity service ส่งเหตุการณ์สร้าง/แก้ผู้ใช้ สร้าง/แก้บทบาท และ reset รหัสผ่านไปที่ Audit service
- Audit Event เก็บ actor, เวลา, entity, ค่าเดิมและค่าใหม่ โดยไม่เก็บรหัสผ่านหรือ hash
- Django Admin เปิดให้อ่าน Audit Event ได้เฉพาะ Developer และปิด add/change/delete

### Web UI

- หน้า Login และ Dashboard อยู่ใน presentation layer โดย Dashboard รุ่นแรกใช้ข้อมูล Cash Flow จำลองเพื่อทดลอง UI ก่อนเชื่อม business module
- หน้า `/settings/users/` และ `/settings/roles/` เป็น Business Admin UI
- HTML/CSS เปลี่ยนใหม่ได้โดยไม่แก้ identity model หรือ authentication service
- Logout รับเฉพาะ `POST` และทุก form ที่เปลี่ยน state ใช้ CSRF protection

### Procurement

- `services.py` เป็นทางเดียวที่เปลี่ยนข้อมูลผู้ขายและ PO ทุกฟังก์ชันรับ `actor` ตรวจสิทธิ์ และบันทึก audit เอง
- การแก้ไข PO บันทึกเฉพาะช่องที่เปลี่ยนลง Audit Event หน้าเว็บแปลงค่าเหล่านั้นเป็นไทม์ไลน์ "ค่าเดิม → ค่าใหม่" ใน `procurement_views.py`
- พึ่งพา `modules/audit/services` (`record_event`, `events_for_entity`) และ `identity.User` เท่านั้น
- `supplier_import.py` ใช้ helper ภายในของ `services.py` (`_create_supplier_record`, `_update_supplier_record`) เพื่อให้การนำเข้าบันทึก audit และคำนวณวันครบกำหนดใหม่ด้วยกติกาเดียวกับการแก้ไขผ่านฟอร์ม
- `expected_outflows()` คืนรายการเงินออกที่คาดว่าจะจ่ายเป็น dataclass ให้หน้า Cash Flow และโมดูล cashflow ในอนาคตนำไปใช้ โดยไม่ต้องรู้โครงสร้างตาราง PO
- หน้าเว็บอยู่ที่ `presentation/web/procurement_views.py`, `procurement_forms.py` และ `templates/web/procurement/`

## โมดูลถัดไป

เมื่อเริ่ม Cash Flow ให้สร้าง `modules/cashflow` แยกจาก identity และให้ UI เรียกผ่าน service/use case ของโมดูลนั้น ไม่วางกติกาคำนวณเงินไว้ใน view หรือ template

