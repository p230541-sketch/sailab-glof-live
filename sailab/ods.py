"""Read the cells of an OpenDocument spreadsheet (.ods) with the Python standard library only.

The global flood database (Lützow, Veh and Korup 2023) is published as .ods. An .ods file is a zip
archive; the cells are in content.xml. Only plain values are read (text and numbers as text), which is
all the flood counts need. Formulas, formatting and merged-cell layout are ignored.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
}
_REPEAT_COLS = f"{{{NS['table']}}}number-columns-repeated"
_REPEAT_ROWS = f"{{{NS['table']}}}number-rows-repeated"
_NAME = f"{{{NS['table']}}}name"
# Spreadsheets often end with a run of empty rows or columns "repeated" a million times. Expanding such
# a run would use gigabytes for nothing, so a run of EMPTY cells or rows longer than this is cut to this
# length. A run this long only ever happens at the end of a row or sheet, where it is dropped anyway;
# shorter empty runs in the middle are kept in full, or every later column would shift left.
_EMPTY_REPEAT_CAP = 1000


def _cell_text(cell) -> str:
    parts = []
    for paragraph in cell.findall("text:p", NS):
        parts.append("".join(paragraph.itertext()))
    return "\n".join(parts).strip()


def read_sheets(path: str | Path) -> dict[str, list[list[str]]]:
    """{sheet name: rows}, each row a list of cell strings ('' for an empty cell). Trailing empty cells
    of each row and trailing empty rows of each sheet are dropped."""
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("content.xml"))
    sheets: dict[str, list[list[str]]] = {}
    for table in root.iter(f"{{{NS['table']}}}table"):
        rows: list[list[str]] = []
        for row in table.iter(f"{{{NS['table']}}}table-row"):
            values: list[str] = []
            for cell in row:
                if not cell.tag.endswith("table-cell") and not cell.tag.endswith("covered-table-cell"):
                    continue
                text = _cell_text(cell)
                repeat = int(cell.get(_REPEAT_COLS, "1"))
                values.extend([text] * (repeat if text or repeat <= _EMPTY_REPEAT_CAP else _EMPTY_REPEAT_CAP))
            while values and values[-1] == "":
                values.pop()
            repeat_rows = int(row.get(_REPEAT_ROWS, "1"))
            rows.extend([values] * (repeat_rows if values or repeat_rows <= _EMPTY_REPEAT_CAP else _EMPTY_REPEAT_CAP))
        while rows and not rows[-1]:
            rows.pop()
        sheets[table.get(_NAME)] = rows
    return sheets
