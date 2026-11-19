# Work Log

## 2026-10-05

- เริ่มต้น repository สำหรับระบบ Cash Flow
- บันทึก requirement ที่ยืนยันแล้ว: Docker, Login และประวัติการเปลี่ยนแปลงโดยผู้ใช้
- เพิ่ม `AGENTS.md` เพื่อกำหนดวิธีอ่านและดูแลความจำของโครงการ
- เพิ่มเอกสารบริบท การตัดสินใจ และ roadmap แยกตามหน้าที่
- บันทึกว่าแหล่งข้อมูลเดิมเป็น Excel แต่จะไม่ใช้ไฟล์จริงหรือข้อมูลลับในการพัฒนา
- ยืนยันขอบเขตว่ามีทั้ง Actual และ Forecast และจะเก็บรายละเอียดด้านเครดิตเพิ่มทีละส่วน
- เลือก stack เบื้องต้นเป็น Python 3.14, Django 5.2 LTS, PostgreSQL 18 และ Django Templates/HTMX
- กำหนด development loop ให้รันผ่าน Docker Compose พร้อม auto reload เพื่อทดลองการแก้ไขได้เร็ว
- เปลี่ยนแนวทางเก็บ requirement เป็นการสร้างตัวต้นแบบก่อน แล้วปรับ workflow, Budget, เครดิต และรายงานจาก feedback ทีละรอบ
- ยืนยันว่า Admin มีสิทธิ์เต็มและจัดการบัญชีผู้ใช้ บทบาท และสิทธิ์ได้ โดยระบบไม่เปิดเผยรหัสผ่านเดิม
- สร้าง Dockerfile และ Docker Compose สำหรับ Django 5.2.17, Python 3.14 และ PostgreSQL 18 พร้อม named volume และ health check
- สร้าง Custom User, authentication service, development Admin bootstrap และ migration แรก
- แยก Web UI ออกจาก identity module พร้อมหน้า Login, Dashboard และ System Admin
- เพิ่ม PowerShell scripts สำหรับ start, stop และ test พร้อม hot reload สำหรับ source code
- เพิ่มชุดทดสอบ Login, Logout, protected page และ database health check รวม 8 รายการ

## 2026-10-06

- คืนลิงก์ Developer console ในเมนูหลักหลังยืนยันขอบเขต โดยแสดงเฉพาะ Developer/Superuser และไม่แสดงแก่ Business Admin
- ซ่อนลิงก์ Developer console จากเมนูหลักโดยยังคงเข้าผ่าน URL โดยตรงได้ และตัดคำอธิบายใต้หัวข้อกระแสเงินสดออกตาม feedback
- เปลี่ยนหน้า Dashboard เป็นตาราง Cash Flow ที่มีวันที่ รายการ เงินเข้า เงินออก เงินคงเหลือ ยอดรวม และยอดคงเหลือล่าสุด โดยใช้ข้อมูลจำลองก่อนเชื่อมโมดูลฐานข้อมูล
- ปรับหน้า Login โดยนำข้อความประชาสัมพันธ์ฝั่งภาพออก และแทนด้วยภาพประกอบ SVG แบบเรียบที่แยกเป็น UI asset เพื่อให้เปลี่ยนภาพภายหลังได้โดยไม่กระทบระบบ Login
- แยกบัญชี Business Admin (`admin`) ออกจาก Developer/Superuser (`developer`)
- จำกัด Django System Admin ให้ Developer ใช้ดูแลโครงระบบ ส่วน Business Admin ใช้ UI หลัก
- เพิ่มหน้ารายการ/สร้าง/แก้ผู้ใช้ กำหนดบทบาท เปิดปิดบัญชี และ reset รหัสผ่าน
- เพิ่มหน้ารายการ/สร้าง/แก้บทบาทและกำหนดสิทธิ์ระดับแอป
- เพิ่ม Audit module แบบ append-only และเชื่อมเหตุการณ์จัดการผู้ใช้/บทบาทโดยไม่บันทึกรหัสผ่าน
- ขยายชุดทดสอบเป็น 16 รายการ และทดสอบสิทธิ์ทั้งสองระดับผ่าน HTTP จริง

## 2026-11-02

- ยืนยัน requirement PO: ไม่มีขั้นอนุมัติแต่ต้องบันทึกผู้ดำเนินการและเวลา, VAT 7% + หัก ณ ที่จ่าย, แสดงเป็นเงินออกที่คาดว่าจะจ่ายในหน้า Cash Flow
- เพิ่มโมดูล `modules/procurement`: models, migration `0001_initial`, `calculations.py`, `policies.py`, `services.py` และ admin แบบอ่านอย่างเดียว
- เพิ่ม `events_for_entity` ใน `modules/audit/services.py` สำหรับอ่านประวัติของข้อมูลหนึ่งรายการ
- แก้ `bootstrap_admin` ให้บทบาทผู้ดูแลระบบได้สิทธิ์ทุกโมดูลธุรกิจ
- เพิ่มหน้าเว็บ `procurement_views.py`, `procurement_forms.py`, templates ใต้ `templates/web/procurement/`, template filters `web_format` (เงิน วันที่ไทย พ.ศ.) และสไตล์ใน `app.css`
- เพิ่มเมนูใบสั่งซื้อและผู้ขายใน `base.html` และตารางเงินออกตาม PO ใน `dashboard.html`
- ขยายชุดทดสอบจาก 18 เป็น 59 รายการ (calculations, services, views) ผ่านทั้งหมดบน PostgreSQL

## 2026-11-08

- ได้รายงาน "รายการใบสั่งซื้อ PO" ตัวอย่างจากระบบเดิม พบว่ามีขั้นอนุมัติ ใบขอซื้อ PR และสถานะ Bplus และยอดรวมเท่ากับก่อน VAT × 1.07 ทุกใบ
- ยืนยันปัญหาหลัก: แก้ไขข้อมูลแล้วระบุคนและเวลาไม่ได้
- เปลี่ยน PO เป็นทะเบียนตามคอลัมน์รายงานระบบเดิม (DEC-015): `models.py`, `services.py`, migration `0002`–`0004`, นำ `calculations.py` และตารางรายการสินค้าออก
- เพิ่มรหัสผู้ขาย, สถานะอนุมัติ, วันที่จัดส่ง และวันครบกำหนดจ่ายจากวันที่จัดส่ง + เครดิตเทอม
- ไทม์ไลน์ในหน้า PO แสดงค่าเดิม → ค่าใหม่ของทุกช่องที่แก้ และเหตุผลการแก้ไข
- ปรับ `procurement_forms.py`, `procurement_views.py`, templates ใต้ `templates/web/procurement/` และ `app.css`
- ทดสอบ migration กับฐานข้อมูลที่มีข้อมูลรุ่นก่อน ชุดทดสอบรวม 53 รายการผ่านทั้งหมดบน PostgreSQL

## 2026-11-09

- ได้ไฟล์ข้อมูลเครดิตของผู้ขายจากระบบเดิม ผู้ขาย 319 ราย เลิกใช้งาน 49 ราย และไม่ระบุเครดิต 47 ราย (นับเฉพาะรายที่ยังใช้งาน)
- เพิ่ม `xlsx_reader.py` (อ่าน .xlsx ด้วย standard library) และ `supplier_import.py` (แปลงไฟล์ วางแผน และนำเข้า)
- เพิ่มรายละเอียด ประเภท และกลุ่มเจ้าหนี้ให้ผู้ขาย และเครดิตแบบไม่ระบุ, `PurchaseOrder.due_date_manual` และการคำนวณวันครบกำหนดใหม่เมื่อเครดิตเปลี่ยน (migration `0005`, `0006`)
- เพิ่มหน้า `suppliers/import/` และตัวกรอง "เครดิตไม่ระบุ" ในหน้าผู้ขาย และป้ายเครดิตไม่ระบุในหน้า PO กับหน้ากระแสเงินสด
- ทดลองนำเข้าไฟล์จริงผ่านหน้าเว็บในเครื่องทดสอบ ชุดทดสอบรวม 69 รายการผ่านทั้งหมดบน PostgreSQL

## 2026-11-16

- เตรียมขึ้น GitHub สำหรับทีม 2 คน (beet, double): เพิ่ม `CONTRIBUTING.md`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/workflows/tests.yml`
- `.gitignore` เพิ่มการกันไฟล์ข้อมูล `.xlsx` `.xls` `.xlsm` `.csv` และไฟล์ระบบปฏิบัติการ
- ตรวจแล้วว่าไม่มีชื่อบริษัทหรือชื่อผู้ขายจริงในโค้ด เทสต์ 69 รายการผ่านด้วยค่าแบบ CI (`DJANGO_DEBUG=false`)
- เลือกแบ่งงานตามโมดูลและ branch แทนโฟลเดอร์ของแต่ละคน (DEC-017)

## 2026-11-19

- ถอดเสียงไฟล์ประชุมและวิดีโอ 16 พ.ย. 2569 แล้วสรุป requirement ลง `project-context.md`
- เพิ่มโมดูล `modules/receivables` (ลูกค้า ใบขาย แผนรับเงิน, `invoice_import.py`) และ migration `0001_initial`
- เพิ่มหน้าเว็บ `receivables_views.py`, `receivables_forms.py`, templates ใต้ `receivables/` และ `cashflow/daily.html` พร้อมเมนู รายวัน / ใบขาย / แผนรับเงิน
- เพิ่ม `outflow_entries` ใน procurement services ให้หน้ารายวันใช้
- ชุดทดสอบรวม 87 รายการผ่านทั้งหมด
