"""อ่านค่าในไฟล์ .xlsx ด้วย standard library เท่านั้น

ไฟล์ .xlsx คือ zip ที่มี XML อยู่ข้างใน การไม่เพิ่ม dependency ทำให้ไม่ต้อง build
Docker image ใหม่ อ่านได้เฉพาะค่าที่บันทึกไว้ในไฟล์ (ค่าที่ Excel คำนวณล่าสุดของสูตร)
"""

import posixpath
import re
import zipfile
from xml.etree import ElementTree

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024
CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")


class WorkbookError(ValueError):
    """ไฟล์อ่านไม่ได้ ข้อความใช้แสดงให้ผู้ใช้เห็นได้ตรง ๆ"""


def _column_index(letters: str) -> int:
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - 64)
    return index - 1


def _text(element) -> str:
    # รวมข้อความทุกช่วง (rich text) แต่ข้ามคำอ่านภาษาญี่ปุ่น <rPh>
    phonetic = {id(t) for ph in element.iter(f"{MAIN}rPh") for t in ph.iter(f"{MAIN}t")}
    return "".join(
        node.text or "" for node in element.iter(f"{MAIN}t") if id(node) not in phonetic
    )


def _number(raw: str) -> str:
    try:
        value = float(raw)
    except ValueError:
        return raw
    return str(int(value)) if value.is_integer() else raw


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_text(item) for item in root.iter(f"{MAIN}si")]


def _sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target", "") for rel in rels.iter(f"{PACKAGE_REL}Relationship")}
    paths = {}
    for sheet in workbook.iter(f"{MAIN}sheet"):
        target = targets.get(sheet.get(f"{REL}id"), "")
        path = target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
        paths[sheet.get("name", "")] = posixpath.normpath(path)
    return paths


def _read_sheet(archive: zipfile.ZipFile, path: str, shared: list[str]) -> list[list[str]]:
    root = ElementTree.fromstring(archive.read(path))
    rows: list[list[str]] = []
    for row in root.iter(f"{MAIN}row"):
        values: dict[int, str] = {}
        for position, cell in enumerate(row.iter(f"{MAIN}c")):
            match = CELL_REF.match(cell.get("r", ""))
            column = _column_index(match.group(1)) if match else position
            kind = cell.get("t", "n")
            raw = cell.find(f"{MAIN}v")
            raw_text = raw.text if raw is not None and raw.text is not None else ""
            if kind == "s":
                value = shared[int(raw_text)] if raw_text.isdigit() and int(raw_text) < len(shared) else ""
            elif kind == "inlineStr":
                inline = cell.find(f"{MAIN}is")
                value = _text(inline) if inline is not None else ""
            elif kind in ("str", "e"):
                value = raw_text if kind == "str" else ""
            elif kind == "b":
                value = "TRUE" if raw_text == "1" else "FALSE"
            else:
                value = _number(raw_text) if raw_text else ""
            values[column] = value.strip()
        width = max(values) + 1 if values else 0
        rows.append([values.get(index, "") for index in range(width)])
    return rows


def read_workbook(file, *, sheets: set[str] | None = None) -> dict[str, list[list[str]]]:
    """คืนค่า {ชื่อชีต: แถว} ทุกค่าเป็นข้อความ ระบุ sheets เพื่ออ่านเฉพาะชีตที่ต้องใช้"""

    try:
        archive = zipfile.ZipFile(file)
    except zipfile.BadZipFile as exc:
        raise WorkbookError("ไฟล์นี้ไม่ใช่ไฟล์ Excel แบบ .xlsx") from exc
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
            raise WorkbookError("ไฟล์ใหญ่เกินกว่าที่ระบบรับได้")
        try:
            shared = _shared_strings(archive)
            paths = _sheet_paths(archive)
            return {
                name: _read_sheet(archive, path, shared)
                for name, path in paths.items()
                if sheets is None or name in sheets
            }
        except (KeyError, ElementTree.ParseError) as exc:
            raise WorkbookError("อ่านโครงสร้างไฟล์ Excel ไม่ได้ ลองเปิดแล้วบันทึกเป็น .xlsx ใหม่") from exc
