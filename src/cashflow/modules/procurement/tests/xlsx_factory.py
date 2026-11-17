"""สร้างไฟล์ .xlsx ขนาดเล็กสำหรับทดสอบ โดยไม่ต้องพึ่ง openpyxl"""

import io
import zipfile
from xml.sax.saxutils import escape

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"


def _column(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def make_xlsx(sheets: dict[str, list[list[object]]]) -> io.BytesIO:
    strings: list[str] = []
    lookup: dict[str, int] = {}

    def string_id(value: str) -> int:
        if value not in lookup:
            lookup[value] = len(strings)
            strings.append(value)
        return lookup[value]

    sheet_xml = []
    for rows in sheets.values():
        body = []
        for row_number, row in enumerate(rows, start=1):
            cells = []
            for column, value in enumerate(row):
                ref = f"{_column(column)}{row_number}"
                if value is None or value == "":
                    continue
                if isinstance(value, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="s"><v>{string_id(str(value))}</v></c>')
            body.append(f'<row r="{row_number}">{"".join(cells)}</row>')
        sheet_xml.append(f'<worksheet xmlns="{MAIN}"><sheetData>{"".join(body)}</sheetData></worksheet>')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        entries = "".join(
            f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(sheets, start=1)
        )
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{entries}</sheets></workbook>',
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="worksheet"/>'
            for i in range(1, len(sheets) + 1)
        )
        archive.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{PACKAGE}">{rels}</Relationships>')
        for i, xml in enumerate(sheet_xml, start=1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", xml)
        shared = "".join(f"<si><t>{escape(value)}</t></si>" for value in strings)
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{MAIN}">{shared}</sst>')
    buffer.seek(0)
    buffer.name = "suppliers.xlsx"
    return buffer


def supplier_workbook(suppliers: list[list[object]], credits: list[list[object]]) -> io.BytesIO:
    """โครงเดียวกับไฟล์ข้อมูลผู้ผลิตของระบบเดิม: หัวกระดาษ 3 แถว เว้น 1 แถว แล้วหัวตาราง"""

    return make_xlsx(
        {
            "รายการ ผู้ผลิต": [
                ["บริษัททดสอบ"],
                ["รายการ ผู้ผลิต"],
                ["วันที่พิมพ์"],
                [],
                ["ลำดับ", "รหัสผู้ผลิต", "ชื่อผู้ผลิต", "รายละเอียด", "ประเภท"],
                *[[index, *row] for index, row in enumerate(suppliers, start=1)],
            ],
            "เครดิต": [
                ["ลำดับที่", "รหัสผู้ผลิต", "ชื่อผู้ผลิต", "กลุ่มผู้ผลิต", "ประเภทผู้ผลิต"],
                *[[index, *row] for index, row in enumerate(credits, start=1)],
            ],
        }
    )
