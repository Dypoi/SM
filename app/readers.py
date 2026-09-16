"""Pembaca berkas spreadsheet multi-format -> matriks baris Python.

Format yang didukung
--------------------
======================  ==========================================
Ekstensi                Mesin pembaca
======================  ==========================================
``.xlsx .xlsm .xltx``   openpyxl   (Excel 2007 ke atas)
``.xls``                xlrd       (Excel 97-2003)
``.xlsb``               pyxlsb     (Excel Binary Workbook)
``.ods``                odfpy      (LibreOffice/OpenOffice)
``.csv .txt .tsv``      modul ``csv`` bawaan Python
======================  ==========================================

Seluruh pembaca mengembalikan tipe data Python asli (str/float/int/datetime),
sehingga lapisan berikutnya (parser Dapodik & pemetaan kolom) bisa bekerja
tanpa peduli format berkasnya.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

log = logging.getLogger("simsek.readers")

CellValue = Any
Row = list[CellValue]

# Batas keamanan agar berkas "nakal" tidak menghabiskan memori.
MAX_ROWS = 200_000
MAX_COLS = 512


class UnsupportedFormatError(ValueError):
    """Ekstensi berkas tidak dikenal / tidak didukung."""


class SpreadsheetError(RuntimeError):
    """Berkas rusak, terproteksi kata sandi, atau tidak bisa dibaca."""


# --------------------------------------------------------------------------- #
# Struktur hasil baca
# --------------------------------------------------------------------------- #
@dataclass
class SheetData:
    """Hasil pembacaan satu worksheet."""

    name: str
    rows: list[Row] = field(default_factory=list)
    index: int = 0

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def col_count(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def head(self, n: int = 10) -> list[Row]:
        return self.rows[:n]

    def truncate(self, max_cols: int = MAX_COLS) -> None:
        self.rows = [row[:max_cols] for row in self.rows]


# --------------------------------------------------------------------------- #
# Utilitas
# --------------------------------------------------------------------------- #
def normalize_cell(value: Any) -> CellValue:
    """Rapikan nilai sel: string dipangkas, NaN/None -> None, tipe asli dipertahankan."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.replace("\u00a0", " ").strip()
        return cleaned or None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        if value.is_integer():
            return int(value)
        return value
    return value


def detect_format(filename: str, content: bytes | None = None) -> str:
    """Kembalikan ekstensi kanonik ('.xlsx', '.csv', ...) dari nama atau isi berkas."""
    suffix = Path(filename or "").suffix.lower()
    if suffix:
        return suffix
    if content:
        try:
            head = content[:8]
        except Exception:  # pragma: no cover
            head = b""
        if head.startswith(b"PK\x03\x04"):
            return ".xlsx"
        if head.startswith(b"\xd0\xcf\x11\xe0"):
            return ".xls"
    raise UnsupportedFormatError("Berkas tidak punya ekstensi yang dikenali.")


def sniff_text_dialect(sample: str) -> csv.Dialect:
    """Tebak pemisah CSV (koma / titik-koma / tab / pipe) ala Excel."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        class _Default(csv.excel):
            delimiter = ";" if sample.count(";") > sample.count(",") else ","

        return _Default  # type: ignore[return-value]


def read_text_table(path: Path) -> SheetData:
    """Baca CSV/TXT/TSV dengan deteksi pemisah & encoding otomatis."""
    raw = path.read_bytes()
    text = None
    used_encoding = "utf-8-sig"
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            used_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    if text is None:  # pragma: no cover - latin-1 selalu berhasil
        raise SpreadsheetError("Encoding berkas teks tidak dikenali.")

    # Buang BOM & karakter kontrol yang sering muncul dari ekspor web.
    text = text.replace("\ufeff", "")
    sample = text[:8192]
    dialect = sniff_text_dialect(sample)
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    rows: list[Row] = []
    for index, row in enumerate(reader):
        if index >= MAX_ROWS:
            break
        rows.append([normalize_cell(cell) for cell in row])
    log.debug("CSV dibaca dengan encoding=%s delimiter=%r", used_encoding, getattr(dialect, "delimiter", "?"))
    return SheetData(name=path.stem, rows=rows)


# --------------------------------------------------------------------------- #
# Pembaca per format
# --------------------------------------------------------------------------- #
def _read_xlsx(path: Path) -> list[SheetData]:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(filename=str(path), data_only=True, read_only=False)
    except Exception as exc:  # noqa: BLE001 - pesan asli diteruskan ke UI
        raise SpreadsheetError(f"Gagal membuka berkas Excel: {exc}") from exc

    sheets: list[SheetData] = []
    for index, name in enumerate(workbook.sheetnames):
        worksheet = workbook[name]
        rows: list[Row] = []
        for r_index, row in enumerate(worksheet.iter_rows(values_only=True)):
            if r_index >= MAX_ROWS:
                break
            rows.append([normalize_cell(cell) for cell in row])
        sheets.append(SheetData(name=name, rows=rows, index=index))

    # Buang kolom/baris kosong di ekor supaya tidak terhitung sebagai data.
    for sheet in sheets:
        sheet.truncate()
        while sheet.rows and all(cell is None for cell in sheet.rows[-1]):
            sheet.rows.pop()
    workbook.close()
    return sheets


def _read_xls(path: Path) -> list[SheetData]:
    import xlrd

    try:
        book = xlrd.open_workbook(filename=str(path), ragged_rows=False)
    except Exception as exc:  # noqa: BLE001
        raise SpreadsheetError(f"Gagal membuka berkas .xls: {exc}") from exc

    sheets: list[SheetData] = []
    for index in range(book.nsheets):
        sheet = book.sheet_by_index(index)
        rows: list[Row] = []
        for r_index in range(min(sheet.nrows, MAX_ROWS)):
            converted: Row = []
            for c_index in range(min(sheet.ncols, MAX_COLS)):
                cell = sheet.cell(r_index, c_index)
                value: CellValue = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        value = xlrd.xldate.xldate_as_datetime(value, book.datemode).date().isoformat()
                    except Exception:  # noqa: BLE001
                        pass
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    value = bool(value)
                converted.append(normalize_cell(value))
            rows.append(converted)
        sheets.append(SheetData(name=sheet.name, rows=rows, index=index))
    return sheets


def _read_xlsb(path: Path) -> list[SheetData]:
    from pyxlsb import open_workbook

    sheets: list[SheetData] = []
    try:
        with open_workbook(str(path)) as book:
            for index, name in enumerate(book.sheets):
                rows: list[Row] = []
                with book.get_sheet(name) as sheet:
                    for r_index, row in enumerate(sheet.rows()):
                        if r_index >= MAX_ROWS:
                            break
                        rows.append(
                            [normalize_cell(cell.v) for cell in row[:MAX_COLS]]
                        )
                sheets.append(SheetData(name=name, rows=rows, index=index))
    except Exception as exc:  # noqa: BLE001
        raise SpreadsheetError(f"Gagal membuka berkas .xlsb: {exc}") from exc
    return sheets


def _read_ods(path: Path) -> list[SheetData]:
    from odf import teletype
    from odf.opendocument import load as load_ods
    from odf.table import Table, TableCell, TableRow

    try:
        document = load_ods(str(path))
    except Exception as exc:  # noqa: BLE001
        raise SpreadsheetError(f"Gagal membuka berkas .ods: {exc}") from exc

    sheets: list[SheetData] = []
    for index, table in enumerate(document.getElementsByType(Table)):
        name = table.getAttribute("name") or f"Sheet{index + 1}"
        rows: list[Row] = []
        for row in table.getElementsByType(TableRow):
            if len(rows) >= MAX_ROWS:
                break
            values: Row = []
            for cell in row.getElementsByType(TableCell):
                repeated = int(cell.getAttribute("numbercolumnsrepeated") or 1)
                text = teletype.extractText(cell)
                value = _coerce_ods_value(cell, text)
                values.extend([value] * min(repeated, MAX_COLS - len(values)))
                if len(values) >= MAX_COLS:
                    break
            rows.append(values)
        sheets.append(SheetData(name=name, rows=rows, index=index))
    return sheets


def _coerce_ods_value(cell: Any, text: str) -> CellValue:
    """Ubah teks sel ODS menjadi angka/tanggal bila memungkinkan."""
    value_type = cell.getAttribute("valuetype")
    raw = cell.getAttribute("value")
    if value_type == "float" and raw is not None:
        return normalize_cell(float(raw))
    if value_type == "date" and raw:
        return raw[:10]
    if value_type == "boolean":
        return raw == "true"
    if value_type == "percentage" and raw is not None:
        return normalize_cell(float(raw))
    if value_type == "currency" and raw is not None:
        return normalize_cell(float(raw))
    return normalize_cell(text)


# --------------------------------------------------------------------------- #
# API utama
# --------------------------------------------------------------------------- #
_READERS = {
    ".xlsx": _read_xlsx,
    ".xlsm": _read_xlsx,
    ".xltx": _read_xlsx,
    ".xltm": _read_xlsx,
    ".xls": _read_xls,
    ".xlsb": _read_xlsb,
    ".ods": _read_ods,
    ".csv": read_text_table,
    ".txt": read_text_table,
    ".tsv": read_text_table,
}

FORMAT_LABELS = {
    ".xlsx": "Excel 2007+ (.xlsx)",
    ".xlsm": "Excel macro (.xlsm)",
    ".xltx": "Excel template (.xltx)",
    ".xltm": "Excel template macro (.xltm)",
    ".xls": "Excel 97-2003 (.xls)",
    ".xlsb": "Excel Binary (.xlsb)",
    ".ods": "OpenDocument (.ods)",
    ".csv": "CSV",
    ".txt": "Teks berpemisah",
    ".tsv": "Tab-separated (.tsv)",
}


def supported_extensions() -> list[str]:
    return sorted(_READERS)


def format_label(ext: str) -> str:
    return FORMAT_LABELS.get(ext.lower(), ext.upper().lstrip("."))


def read_spreadsheet(path: str | Path, ext: str | None = None) -> list[SheetData]:
    """Baca berkas spreadsheet apa pun yang didukung -> daftar worksheet.

    Raises
    ------
    UnsupportedFormatError
        Ekstensi tidak didukung.
    SpreadsheetError
        Berkas gagal dibaca (rusak/terproteksi).
    """
    path = Path(path)
    if not path.exists():
        raise SpreadsheetError(f"Berkas tidak ditemukan: {path}")

    extension = (ext or detect_format(path.name)).lower()
    reader = _READERS.get(extension)
    if reader is None:
        raise UnsupportedFormatError(
            f"Format '{extension}' belum didukung. Format yang bisa dibaca: "
            + ", ".join(supported_extensions())
        )

    if extension in {".csv", ".txt", ".tsv"}:
        sheet = reader(path)
        if not sheet.rows:
            raise SpreadsheetError("Berkas teks kosong.")
        return [sheet]

    sheets = reader(path)
    sheets = [sheet for sheet in sheets if any(cell is not None for row in sheet.rows for cell in row)]
    if not sheets:
        raise SpreadsheetError("Semua worksheet kosong.")
    return sheets


def read_first_sheet(path: str | Path, ext: str | None = None) -> SheetData:
    return read_spreadsheet(path, ext)[0]


def iter_non_empty_rows(rows: Iterable[Row]) -> Iterator[tuple[int, Row]]:
    """Iterasi (nomor_baris_1_based, baris) yang benar-benar berisi data."""
    for index, row in enumerate(rows, start=1):
        if any(cell is not None and str(cell).strip() != "" for cell in row):
            yield index, row


MONTHS_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "agu": 8, "ags": 8,
    "sep": 9, "okt": 10, "nov": 11, "des": 12,
}


def to_iso_date(value: Any) -> tuple[str | None, str | None]:
    """Normalisasi banyak format tanggal Indonesia -> ISO (YYYY-MM-DD).

    Returns
    -------
    (iso_date, peringatan) -- peringatan berisi teks jika nilai tidak dikenali.
    """
    if value is None or value == "":
        return None, None
    if isinstance(value, dt.datetime):
        return value.date().isoformat(), None
    if isinstance(value, dt.date):
        return value.isoformat(), None
    if isinstance(value, (int, float)):
        # Serial date Excel (1900 system) -> tanggal.
        number = float(value)
        if 1 <= number <= 60000:
            base = dt.date(1899, 12, 30)
            return (base + dt.timedelta(days=number)).isoformat(), None
        text = str(int(number))
    else:
        text = str(value).strip()

    if not text:
        return None, None

    # 2011-08-22 / 2011/08/22
    match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return _safe_iso(year, month, day)

    # 22-08-2011 / 22/08/2011
    match = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        return _safe_iso(year, month, day)

    # 22 Agustus 2011 / 22 Agu 2011
    match = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", text)
    if match:
        day = int(match.group(1))
        month_name = match.group(2).lower()
        year = int(match.group(3))
        month = MONTHS_ID.get(month_name)
        if month:
            return _safe_iso(year, month, day)

    # 20110822 (format Dapodik lama)
    if re.match(r"^\d{8}$", text):
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:])
        return _safe_iso(year, month, day)

    return None, f"Format tanggal tidak dikenali: '{text}'"


def _safe_iso(year: int, month: int, day: int) -> tuple[str | None, str | None]:
    try:
        return dt.date(year, month, day).isoformat(), None
    except ValueError:
        return None, f"Tanggal tidak valid: {day:02d}-{month:02d}-{year}"


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(".", "").replace(",", ".") if "," in str(value) else str(value).strip()
    try:
        return float(text)
    except ValueError:
        found = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
        if not found:
            return None
        try:
            return float(found.group(0).replace(",", "."))
        except ValueError:
            return None


def parse_int(value: Any) -> int | None:
    number = parse_float(value)
    return None if number is None else int(round(number))


def clean_text(value: Any, *, upper: bool = False, title: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    if upper:
        return text.upper()
    if title:
        return text.title()
    return text
