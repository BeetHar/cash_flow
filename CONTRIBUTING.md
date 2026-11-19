# ทำงานร่วมกันบน GitHub

โปรเจกต์นี้มีคนดูแล 2 คน คือ **beet** และ **double** แบ่งงานกันตามโมดูลของระบบ
และใช้ branch เป็นพื้นที่ทำงานของแต่ละคน

## ใครดูแลอะไร

| ส่วน | คนดูแล | อยู่ในโค้ดที่ |
|---|---|---|
| โครงระบบ, Docker, การตั้งค่า | double | `compose.yaml`, `Dockerfile`, `docker/`, `requirements/`, `src/cashflow/config/` |
| ล็อกอิน ผู้ใช้ และบทบาท | double | `src/cashflow/modules/identity/`, หน้า `auth/` และ `identity/` |
| Audit trail | double | `src/cashflow/modules/audit/` |
| ใบสั่งซื้อ (PO), ผู้ขาย, นำเข้า Excel | beet | `src/cashflow/modules/procurement/`, `procurement_*.py`, หน้า `procurement/` |
| ใบขาย ลูกค้า แผนรับเงิน และหน้ารายวัน | beet | `src/cashflow/modules/receivables/`, `receivables_*.py`, หน้า `receivables/` และ `cashflow/` |
| ไฟล์กลาง | ทั้งสองคน | `settings.py`, `urls.py`, `base.html`, `dashboard.html`, `static/`, `docs/` |

รายละเอียดเต็มอยู่ที่ `.github/CODEOWNERS` เมื่อเปิด Pull Request ที่แก้ส่วนของอีกคน
GitHub จะขอให้คนนั้นรีวิวให้อัตโนมัติ

โมดูลใหม่ (เช่น บันทึกรายรับรายจ่าย) ให้ตกลงกันก่อนเริ่มว่าใครดูแล แล้วเพิ่มบรรทัดใน `CODEOWNERS`

## พื้นที่ทำงานของแต่ละคนคือ branch

- `main` คือโค้ดที่ใช้งานได้จริง **ห้าม push เข้า main ตรง ๆ** ทุกอย่างเข้าทาง Pull Request
- งานของ beet ใช้ branch ที่ขึ้นต้นด้วย `beet/` เช่น `beet/po-export-pdf`
- งานของ double ใช้ branch ที่ขึ้นต้นด้วย `double/` เช่น `double/cashflow-ledger`
- หนึ่ง branch ต่อหนึ่งเรื่อง เสร็จแล้ว merge แล้วลบ branch ทิ้ง

## ขั้นตอนทุกครั้งที่เริ่มงานใหม่

```powershell
git switch main
git pull                              # ดึงงานล่าสุดของอีกคนมาก่อน
git switch -c beet/ชื่อเรื่อง          # double ใช้ double/ชื่อเรื่อง

# ... แก้โค้ด ลองรัน .\test.ps1 ...

git add -A
git commit -m "อธิบายสั้น ๆ ว่าทำอะไร"
git push -u origin beet/ชื่อเรื่อง
```

จากนั้นเปิด Pull Request บนหน้า GitHub แล้วรอสองอย่าง

1. **GitHub Actions** รันเทสต์ให้อัตโนมัติ ต้องขึ้นเครื่องหมายถูกสีเขียว
2. **อีกคนรีวิว** และกด Approve

เสร็จแล้วกด **Squash and merge** และ **Delete branch**

ใน VS Code ทำแบบเดียวกันได้จากแถบ Source Control (ไอคอนกิ่งไม้ด้านซ้าย)
และเปลี่ยน branch ได้ที่มุมซ้ายล่าง

## ไม่มี main.py: ส่วนไหนรวมงานของทุกคน

โปรเจกต์นี้เป็น Django ไม่ได้รวมงานด้วยไฟล์ main ไฟล์เดียว แต่ใช้ 3 จุดนี้

| ไฟล์ | หน้าที่ |
|---|---|
| `src/manage.py` | จุดเริ่มรันโปรแกรม (Docker เรียก `python manage.py runserver`) |
| `src/cashflow/config/settings.py` | `INSTALLED_APPS` บอกว่าระบบมีโมดูลอะไรบ้าง |
| `src/cashflow/presentation/web/urls.py` | บอกว่าแต่ละหน้าเว็บ (URL) ไปที่โค้ดส่วนไหน |

การเพิ่มโมดูลใหม่

1. สร้างโฟลเดอร์ใต้ `src/cashflow/modules/<ชื่อโมดูล>/` พร้อม `apps.py`, `models.py`, `services.py`, `policies.py`
2. เพิ่มโมดูลใน `INSTALLED_APPS`
3. เขียนหน้าเว็บใน `presentation/web/` แล้วเพิ่ม URL ใน `urls.py`
4. หน้าเว็บเรียกโมดูลผ่าน `services.py` เท่านั้น (ดู `docs/architecture.md`)
5. เพิ่มเจ้าของใน `.github/CODEOWNERS`

## กฎเรื่อง migration (สำคัญ)

ไฟล์ migration ของ Django เรียงเลขต่อกัน ถ้าสองคนสร้างเลขเดียวกันในโมดูลเดียวกัน ระบบจะชนกัน

- สร้าง migration เฉพาะในโมดูลที่ตัวเองดูแล
- `git pull` จาก `main` ก่อนรัน `makemigrations` ทุกครั้ง
- ถ้าชนกัน ให้คนที่ merge ทีหลังลบ migration ของตัวเอง ดึง `main` ใหม่ แล้วสร้างใหม่
- ห้ามแก้ไฟล์ migration ที่ merge เข้า `main` ไปแล้ว ถ้าต้องเปลี่ยน ให้สร้าง migration ใหม่ต่อท้าย

## ห้ามขึ้น GitHub

- ไฟล์ `.env` และรหัสผ่านจริง (`.gitignore` กันไว้แล้ว)
- ไฟล์ข้อมูลจริงของบริษัท เช่น Excel หรือ CSV ที่มีชื่อผู้ขายและยอดเงินจริง (`.gitignore` กันไฟล์ `.xlsx` `.xls` `.csv` ไว้แล้ว)
- ภาพหน้าจอที่เห็นข้อมูลจริงใน Pull Request หรือ Issue
- repository ต้องตั้งเป็น **Private**

## เทสต์

- รันในเครื่อง: `.\test.ps1`
- GitHub รันให้อัตโนมัติทุก Pull Request (ดูไฟล์ `.github/workflows/tests.yml`)
- งานที่แตะเงิน สิทธิ์ หรือ audit trail ต้องมีเทสต์ (ตาม `AGENTS.md`)

## เอกสาร

เมื่อทำอะไรที่มีสาระสำคัญ ให้อัปเดตเอกสารใน `docs/` ตามกติกาใน `AGENTS.md`
ใส่ไว้ใน Pull Request เดียวกับโค้ด
