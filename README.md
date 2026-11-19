# Cash Flow
ระบบตามเงิน
ระบบ Cash Flow ภายในบริษัท พัฒนาด้วย Django และ PostgreSQL โดยแยก business modules ออกจาก Web UI

## เริ่มระบบสำหรับทดลอง

ต้องมี Docker Desktop จากนั้นเปิด PowerShell ที่โฟลเดอร์โครงการแล้วรัน:

```powershell
.\dev.ps1
```

ครั้งแรกระบบจะสร้าง `.env` จาก `.env.example`, build image, สร้างฐานข้อมูล และเปิดที่:

- Application: http://localhost:8000
- Health check: http://localhost:8000/health/
- Business Admin: http://localhost:8000/settings/users/
- Developer console: http://localhost:8000/system-admin/

บัญชีสำหรับทดลองหน้าแอป:

- Username: `admin`
- Password: `CashFlow-dev-2026!`

บัญชีสำหรับ Developer console:

- Username: `developer`
- Password: `CashFlow-system-2026!`

Business Admin จัดการบัญชีและบทบาทผ่านหน้าแอป แต่เข้า Developer console ไม่ได้ ส่วน Developer เป็น Django superuser สำหรับดูแลโครงระบบและ Audit Event ทั้งหมด บัญชีทั้งสองสร้างเฉพาะเมื่อ `DJANGO_DEBUG=true` และต้องเปลี่ยนก่อนนำระบบออกนอกเครื่องพัฒนา

หยุดระบบ:

```powershell
.\stop.ps1
```

รัน test:

```powershell
.\test.ps1
```

## การแก้โค้ด

โฟลเดอร์ `src` ถูก mount เข้า container และ Django reload โค้ดอัตโนมัติ บันทึกไฟล์แล้ว Refresh หน้าเว็บได้ทันที หากแก้ dependency หรือ Dockerfile Compose Watch จะ rebuild application image

อ่านขอบเขตและกฎของแต่ละชิ้นส่วนที่ [docs/architecture.md](docs/architecture.md)

## ทำงานร่วมกัน

ทีมแบ่งงานตามโมดูล: **double** ดูแลโครงระบบ ล็อกอิน และ audit trail ส่วน **beet** ดูแลใบสั่งซื้อ ผู้ขาย และการนำเข้า Excel
แต่ละคนทำงานใน branch ของตัวเอง (`beet/...`, `double/...`) แล้วรวมเข้า `main` ผ่าน Pull Request
ที่ GitHub รันเทสต์ให้อัตโนมัติ

อ่านขั้นตอนและกติกาที่ [CONTRIBUTING.md](CONTRIBUTING.md)

