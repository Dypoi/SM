"""Parser berkas Dapodik + validasi data peserta didik.

Berkas ekspor Dapodik punya bentuk yang khas:

* baris 1-4  : judul, nama sekolah, wilayah, tanggal unduh & pengunduh
* baris 5    : header kolom (66 kolom)
* baris 6    : sub-header untuk kolom bergrup ("Data Ayah/Ibu/Wali")
* baris 7+   : data siswa

Modul ini mendeteksi struktur tersebut secara otomatis sehingga berkas dari
daerah/tahun berbeda tetap terbaca, lalu memetakan setiap kolom ke field
database dan menjalankan pemeriksaan kualitas data (mirip validasi Dapodik).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .readers import (
    SheetData,
    clean_text,
    parse_float,
    parse_int,
    to_iso_date,
)

# --------------------------------------------------------------------------- #
# Definisi field peserta didik
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    group: str = "lainnya"
    kind: str = "text"  # text | int | float | date | ya_tidak
    #: Daftar pilihan tetap. Bila diisi, kolom ditampilkan sebagai dropdown
    #: (nilai di luar daftar tetap boleh tersimpan — mis. hasil impor lama).
    choices: tuple[str, ...] = ()
    required: bool = False
    help_text: str = ""


#: Pilihan pekerjaan ayah/ibu/wali (mengikuti daftar Dapodik).
PEKERJAAN_OPTIONS: tuple[str, ...] = (
    "Tidak Bekerja",
    "Nelayan",
    "Petani",
    "Peternak",
    "PNS/TNI/Polri",
    "Karyawan Swasta",
    "Pedagang Kecil",
    "Pedagang Besar",
    "Wiraswasta",
    "Wirausaha",
    "Buruh",
    "Pensiunan",
    "Tenaga Kerja Indonesia",
    "Karyawan BUMN",
    "Tidak Dapat Diterapkan",
    "Sudah Meninggal",
    "Lainnya",
)

#: Pilihan penghasilan per bulan ayah/ibu/wali (daftar Dapodik).
PENGHASILAN_OPTIONS: tuple[str, ...] = (
    "Kurang dari Rp. 500,000",
    "Rp. 500,000 - Rp. 999,999",
    "Rp. 1,000,000 - Rp. 1,999,999",
    "Rp. 2,000,000 - Rp. 4,999,999",
    "Rp. 5,000,000 - Rp. 20,000,000",
    "Lebih dari Rp. 20,000,000",
    "Tidak Berpenghasilan",
)

#: Kolom yang memakai daftar pilihan pekerjaan / penghasilan.
FIELD_PEKERJAAN: tuple[str, ...] = ("ayah_pekerjaan", "ibu_pekerjaan", "wali_pekerjaan")
FIELD_PENGHASILAN: tuple[str, ...] = ("ayah_penghasilan", "ibu_penghasilan", "wali_penghasilan")


STUDENT_FIELDS: tuple[FieldSpec, ...] = (
    # ---- Identitas ----
    FieldSpec("nama", "Nama Lengkap", ("nama", "nama lengkap", "nama siswa", "nama peserta didik"), "identitas", required=True),
    FieldSpec("nisn", "NISN", ("nisn", "nomor induk siswa nasional"), "identitas", required=True,
              help_text="10 digit angka, dipakai siswa untuk login."),
    FieldSpec("nipd", "NIPD / NIS Lokal", ("nipd", "nis", "nis lokal", "nisn lokal", "no induk", "nomor induk"), "identitas"),
    FieldSpec("jk", "Jenis Kelamin", ("jk", "jenis kelamin", "lp", "l p", "jenis kelamin lp", "jenkel"), "identitas"),
    FieldSpec("tempat_lahir", "Tempat Lahir", ("tempat lahir", "tempatl aahir", "tmp lahir"), "identitas"),
    FieldSpec("tanggal_lahir", "Tanggal Lahir", ("tanggal lahir", "tgl lahir", "tanggal lahir siswa"), "identitas", kind="date"),
    FieldSpec("nik", "NIK Siswa", ("nik", "nik siswa", "no ktp"), "identitas"),
    FieldSpec("no_kk", "No. Kartu Keluarga", ("no kk", "nomor kk", "no kartu keluarga", "nomor kartu keluarga"), "identitas"),
    FieldSpec("agama", "Agama", ("agama",), "identitas"),
    FieldSpec("kebutuhan_khusus", "Kebutuhan Khusus", ("kebutuhan khusus",), "identitas"),
    FieldSpec("sekolah_asal", "Sekolah Asal", ("sekolah asal", "asal sekolah"), "identitas"),

    # ---- Alamat & kontak ----
    FieldSpec("alamat", "Alamat (Jalan)", ("alamat", "alamat jalan", "jalan"), "alamat"),
    FieldSpec("rt", "RT", ("rt",), "alamat"),
    FieldSpec("rw", "RW", ("rw",), "alamat"),
    FieldSpec("kelurahan", "Desa/Kelurahan", ("kelurahan", "desa kelurahan", "desa", "kelurahan desa"), "alamat"),
    FieldSpec("kecamatan", "Kecamatan", ("kecamatan", "kec"), "alamat"),
    FieldSpec("kode_pos", "Kode Pos", ("kode pos", "kodepos"), "alamat"),
    FieldSpec("hp", "HP", ("hp", "no hp", "handphone", "ponsel", "no wa", "whatsapp"), "alamat"),
    FieldSpec("jarak_rumah", "Jarak Rumah ke Sekolah (KM)", ("jarak rumah ke sekolah km", "jarak rumah", "jarak ke sekolah"), "alamat", kind="float"),

    # ---- Data Ayah ----
    FieldSpec("ayah_nama", "Ayah - Nama", ("nama", "nama ayah", "ayah", "nama bapak", "bapak", "nama papa"), "ayah"),
    FieldSpec("ayah_tahun_lahir", "Ayah - Tahun Lahir", ("tahun lahir",), "ayah", kind="int"),
    FieldSpec("ayah_pendidikan", "Ayah - Jenjang Pendidikan", ("jenjang pendidikan",), "ayah"),
    FieldSpec("ayah_pekerjaan", "Ayah - Pekerjaan", ("pekerjaan",), "ayah", choices=PEKERJAAN_OPTIONS),
    FieldSpec("ayah_penghasilan", "Ayah - Penghasilan", ("penghasilan",), "ayah", choices=PENGHASILAN_OPTIONS),
    FieldSpec("ayah_nik", "Ayah - NIK", ("nik",), "ayah"),

    # ---- Data Ibu ----
    FieldSpec("ibu_nama", "Ibu - Nama", ("nama", "nama ibu", "ibu", "nama mama", "nama emak", "nama bunda"), "ibu"),
    FieldSpec("ibu_tahun_lahir", "Ibu - Tahun Lahir", ("tahun lahir",), "ibu", kind="int"),
    FieldSpec("ibu_pendidikan", "Ibu - Jenjang Pendidikan", ("jenjang pendidikan",), "ibu"),
    FieldSpec("ibu_pekerjaan", "Ibu - Pekerjaan", ("pekerjaan",), "ibu", choices=PEKERJAAN_OPTIONS),
    FieldSpec("ibu_penghasilan", "Ibu - Penghasilan", ("penghasilan",), "ibu", choices=PENGHASILAN_OPTIONS),
    FieldSpec("ibu_nik", "Ibu - NIK", ("nik",), "ibu"),

    # ---- Data Wali ----
    FieldSpec("wali_nama", "Wali - Nama", ("nama", "nama wali", "wali"), "wali"),
    FieldSpec("wali_tahun_lahir", "Wali - Tahun Lahir", ("tahun lahir",), "wali", kind="int"),
    FieldSpec("wali_pendidikan", "Wali - Jenjang Pendidikan", ("jenjang pendidikan",), "wali"),
    FieldSpec("wali_pekerjaan", "Wali - Pekerjaan", ("pekerjaan",), "wali", choices=PEKERJAAN_OPTIONS),
    FieldSpec("wali_penghasilan", "Wali - Penghasilan", ("penghasilan",), "wali", choices=PENGHASILAN_OPTIONS),
    FieldSpec("wali_nik", "Wali - NIK", ("nik",), "wali"),

    # ---- Rombel & akademik ----
    FieldSpec("rombel", "Rombel Saat Ini", ("rombel saat ini", "rombel", "kelas", "nama rombel", "ruang kelas", "kelas saat ini"), "akademik"),
    FieldSpec("tingkat", "Tingkat", ("tingkat", "jenjang"), "akademik"),
    FieldSpec("no_seri_ijazah", "No. Seri Ijazah", ("no seri ijazah", "nomor seri ijazah"), "akademik"),

    # ---- Bantuan & kesejahteraan ----
    FieldSpec("penerima_kps", "Penerima KPS", ("penerima kps", "kps"), "bantuan", kind="ya_tidak"),
    FieldSpec("no_kps", "No. KPS", ("no kps", "nomor kps"), "bantuan"),
    FieldSpec("penerima_kip", "Penerima KIP", ("penerima kip", "kip"), "bantuan", kind="ya_tidak"),
    FieldSpec("nomor_kip", "Nomor KIP", ("nomor kip", "no kip"), "bantuan"),
    FieldSpec("nama_kip", "Nama di KIP", ("nama di kip", "nama kip"), "bantuan"),
    FieldSpec("no_registrasi_akta", "No. Registrasi Akta Lahir", ("no registrasi akta lahir", "akta lahir", "no akta"), "bantuan"),
    FieldSpec("layak_pip", "Layak PIP (usulan sekolah)", ("layak pip", "layak pip usulan dari sekolah"), "bantuan", kind="ya_tidak"),
    FieldSpec("alasan_layak_pip", "Alasan Layak PIP", ("alasan layak pip",), "bantuan"),

    # ---- Kesehatan & keluarga ----
    FieldSpec("anak_ke", "Anak ke-berapa", ("anak ke berapa", "anak ke"), "kesehatan", kind="int"),
    FieldSpec("jml_saudara", "Jumlah Saudara Kandung", ("jml saudara kandung", "jumlah saudara kandung", "jml saudara"), "kesehatan", kind="int"),
    FieldSpec("berat_badan", "Berat Badan (kg)", ("berat badan",), "kesehatan", kind="float"),
    FieldSpec("tinggi_badan", "Tinggi Badan (cm)", ("tinggi badan",), "kesehatan", kind="float"),
    FieldSpec("lingkar_kepala", "Lingkar Kepala (cm)", ("lingkar kepala",), "kesehatan", kind="float"),
)

FIELD_BY_KEY: dict[str, FieldSpec] = {spec.key: spec for spec in STUDENT_FIELDS}

#: Field Dapodik yang tidak dipakai lagi di SM (dihapus atas permintaan sekolah).
#: Kolomnya tetap ada pada berkas Excel Dapodik, jadi saat impor hanya diabaikan.
FIELD_DIHAPUS: tuple[str, ...] = (
    "dusun", "jenis_tinggal", "transportasi", "telepon", "email", "skhun",
    "no_peserta_un", "nomor_kks", "bank", "no_rekening", "rekening_atas_nama",
    "lintang", "bujur",
)
LABEL_DIHAPUS: tuple[str, ...] = (
    "Dusun", "Jenis Tinggal", "Alat Transportasi", "Telepon", "E-Mail", "SKHUN",
    "No. Peserta Ujian Nasional", "Nomor KKS", "Bank", "Nomor Rekening Bank",
    "Rekening Atas Nama", "Lintang", "Bujur",
)

GROUP_LABELS = {
    "identitas": "Identitas",
    "alamat": "Alamat & Kontak",
    "ayah": "Data Ayah",
    "ibu": "Data Ibu",
    "wali": "Data Wali",
    "akademik": "Rombel & Akademik",
    "bantuan": "Bantuan & Kesejahteraan",
    "kesehatan": "Kesehatan & Keluarga",
    "lainnya": "Lainnya",
}

GROUP_ORDER = ["identitas", "alamat", "ayah", "ibu", "wali", "akademik", "bantuan", "kesehatan"]


def fields_by_group() -> dict[str, list[FieldSpec]]:
    grouped: dict[str, list[FieldSpec]] = {key: [] for key in GROUP_ORDER}
    for spec in STUDENT_FIELDS:
        grouped.setdefault(spec.group, []).append(spec)
    return {key: value for key, value in grouped.items() if value}


# --------------------------------------------------------------------------- #
# Normalisasi teks header
# --------------------------------------------------------------------------- #
def normalize_header(text: Any) -> str:
    """'Jml. Saudara\\nKandung' -> 'jml saudara kandung'; '(KM)' dibuang."""
    if text is None:
        return ""
    value = str(text).lower()
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\(.*?\)", " ", value)          # buang keterangan dalam kurung
    value = re.sub(r"[^a-z0-9]+", " ", value)        # sisakan alfanumerik
    return re.sub(r"\s+", " ", value).strip()


# Indeks alias -> field, dibangun sekali.
def _build_alias_index() -> dict[str, list[FieldSpec]]:
    index: dict[str, list[FieldSpec]] = {}
    for spec in STUDENT_FIELDS:
        for alias in (spec.label, *spec.aliases):
            index.setdefault(normalize_header(alias), []).append(spec)
    return index


_ALIAS_INDEX = _build_alias_index()

KNOWN_GROUP_HEADERS = {
    "data ayah": "ayah",
    "data ibu": "ibu",
    "data wali": "wali",
    "data orang tua": "ayah",
}


# --------------------------------------------------------------------------- #
# Hasil parsing
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    row_number: int | None
    level: str          # 'error' | 'warning' | 'info'
    field: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "level": self.level,
            "field": self.field,
            "message": self.message,
        }


@dataclass
class StudentRecord:
    row_number: int
    values: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def has_error(self) -> bool:
        return any(issue.level == "error" for issue in self.issues)


@dataclass
class ParsedSpreadsheet:
    sheet_name: str
    kind: str                       # 'daftar_peserta_didik' | 'generik'
    header_row: int
    sub_header_row: int | None
    data_start_row: int
    columns: list[str]              # label kolom yang terdeteksi
    mapping: dict[str, str]         # field_key -> label kolom asli
    column_map: dict[int, str]      # index kolom -> field_key
    records: list[StudentRecord]
    issues: list[Issue]
    metadata: dict[str, str]
    total_columns: int = 0

    @property
    def mapped_field_count(self) -> int:
        return len(self.column_map)

    @property
    def ignored_columns(self) -> list[str]:
        """Kolom berkas yang cocok dengan field yang sudah dihapus dari aplikasi."""
        diabaikan: list[str] = []
        for label in self.columns:
            normal = normalize_header(label)
            if normal and normal in {normalize_header(item) for item in LABEL_DIHAPUS}:
                diabaikan.append(label)
        return diabaikan

    @property
    def detected_fields(self) -> list[str]:
        return list(self.mapping.keys())

    def issues_for(self, level: str) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == level]


# --------------------------------------------------------------------------- #
# Deteksi struktur berkas
# --------------------------------------------------------------------------- #
def _row_fill(row: Sequence[Any]) -> int:
    return sum(1 for cell in row if cell is not None and str(cell).strip() != "")


def _looks_like_header(row: Sequence[Any]) -> int:
    """Hitung berapa sel di baris ini yang cocok dengan field peserta didik."""
    score = 0
    for cell in row:
        normalized = normalize_header(cell)
        if not normalized:
            continue
        if normalized in _ALIAS_INDEX or normalized in KNOWN_GROUP_HEADERS:
            score += 1
    return score


def _has_group_header(row: Sequence[Any]) -> bool:
    """Apakah baris memuat judul bergabung seperti 'Data Ayah'?"""
    return any(normalize_header(cell) in KNOWN_GROUP_HEADERS for cell in row)


def _has_long_number(row: Sequence[Any]) -> bool:
    """Deteksi angka panjang (NISN/NIK/NIPD) yang menandakan baris data."""
    for cell in row:
        if isinstance(cell, (int, float)) and not isinstance(cell, bool):
            if abs(float(cell)) >= 100000:
                return True
        elif isinstance(cell, str) and re.search(r"\d{6,}", cell):
            return True
    return False


def find_header_row(sheet: SheetData, scan_limit: int = 40) -> tuple[int, int | None]:
    """Cari baris header (1-based) dan sub-header-nya bila ada.

    Sub-header hanya dicari bila baris header memakai judul bergabung
    ("Data Ayah", "Data Ibu", "Data Wali") — ciri khas ekspor Dapodik.
    Tanpa syarat ini, baris data pertama pada berkas sederhana bisa keliru
    dianggap sebagai sub-header.
    """
    best_index, best_score = 0, 0
    limit = min(sheet.row_count, scan_limit)
    for index in range(limit):
        score = _looks_like_header(sheet.rows[index])
        if score > best_score:
            best_index, best_score = index, score

    if best_score < 3:
        # Tidak ada header Dapodik: pakai baris pertama yang cukup terisi.
        for index in range(limit):
            if _row_fill(sheet.rows[index]) >= 2:
                return index + 1, None
        return 1, None

    sub_row: int | None = None
    top = sheet.rows[best_index]
    if best_index + 1 < sheet.row_count and _has_group_header(top):
        below = sheet.rows[best_index + 1]
        filled_below = _row_fill(below)
        filled_top = _row_fill(top)
        # Sub-header: lebih sedikit sel terisi daripada baris header,
        # tidak mengandung angka panjang, dan bukan baris kosong.
        if 0 < filled_below < filled_top and not _has_long_number(below):
            sub_row = best_index + 2
    return best_index + 1, sub_row


def build_columns(sheet: SheetData, header_row: int, sub_header_row: int | None) -> list[str]:
    """Gabungkan header + sub-header menjadi label kolom yang bermakna."""
    top = sheet.rows[header_row - 1] if header_row - 1 < sheet.row_count else []
    sub = (
        sheet.rows[sub_header_row - 1]
        if sub_header_row and sub_header_row - 1 < sheet.row_count
        else []
    )
    columns: list[str] = []
    current_group: str | None = None
    width = max(len(top), len(sub))
    for index in range(width):
        top_value = clean_text(top[index]) if index < len(top) else None
        sub_value = clean_text(sub[index]) if index < len(sub) else None

        if top_value:
            group_key = KNOWN_GROUP_HEADERS.get(normalize_header(top_value))
            if group_key and sub_value:
                current_group = top_value
                columns.append(f"{top_value} - {sub_value}")
                continue
            current_group = None
            columns.append(top_value)
            continue

        # Sel kosong: lanjutkan grup terakhir (kolom gabungan/merge).
        if current_group and sub_value:
            columns.append(f"{current_group} - {sub_value}")
        elif sub_value:
            columns.append(sub_value)
        else:
            columns.append(f"Kolom {index + 1}")
    return columns


def build_mapping(columns: Sequence[str]) -> dict[int, str]:
    """Petakan indeks kolom -> field_key (tanpa duplikasi field)."""
    column_map: dict[int, str] = {}
    used: set[str] = set()
    for index, label in enumerate(columns):
        candidates = _candidates_for(label)
        for spec in candidates:
            if spec.key in used:
                continue
            column_map[index] = spec.key
            used.add(spec.key)
            break
    return column_map


def _candidates_for(label: str) -> list[FieldSpec]:
    """Kandidat field untuk sebuah label kolom, dengan mempertimbangkan grup."""
    normalized = normalize_header(label)
    if not normalized:
        return []

    # Label bergrup: "Data Ayah - Pekerjaan" -> group=ayah, sub=pekerjaan
    group_key = None
    sub_part = normalized
    for group_name, key in KNOWN_GROUP_HEADERS.items():
        if normalized.startswith(group_name):
            group_key = key
            sub_part = normalized[len(group_name):].strip(" -") or normalized
            break

    if group_key:
        matches = [spec for spec in _ALIAS_INDEX.get(sub_part, []) if spec.group == group_key]
        if matches:
            return matches

    exact = list(_ALIAS_INDEX.get(normalized, []))
    if exact:
        # Prioritaskan field non-grup untuk header tanpa awalan grup.
        exact.sort(key=lambda spec: (spec.group in {"ayah", "ibu", "wali"}, STUDENT_FIELDS.index(spec)))
        return exact

    # Pencocokan longgar: label yang memuat alias (mis. "nama lengkap siswa").
    loose: list[FieldSpec] = []
    for alias, specs in _ALIAS_INDEX.items():
        if len(alias) >= 5 and alias in normalized:
            loose.extend(specs)
    loose.sort(key=lambda spec: (spec.group in {"ayah", "ibu", "wali"}, STUDENT_FIELDS.index(spec)))
    return loose


# --------------------------------------------------------------------------- #
# Metadata kepala berkas
# --------------------------------------------------------------------------- #
def extract_metadata(sheet: SheetData, header_row: int) -> dict[str, str]:
    meta: dict[str, str] = {}
    for index in range(header_row - 1):
        row = sheet.rows[index]
        values = [clean_text(cell) for cell in row if clean_text(cell)]
        if not values:
            continue
        joined = " | ".join(values)
        if index == 0:
            meta.setdefault("judul", values[0])
        for value in values:
            low = value.lower()
            if low.startswith("tanggal unduh"):
                meta["tanggal_unduh"] = value.split(":", 1)[-1].strip()
            elif low.startswith("tanggal"):
                meta.setdefault("tanggal_unduh", value.split(":", 1)[-1].strip())
            elif low.startswith("pengunduh"):
                pengunduh = value.split(":", 1)[-1].strip()
                meta["pengunduh"] = pengunduh
                email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", pengunduh)
                if email_match:
                    meta["pengunduh_email"] = email_match.group(0)
            elif "kecamatan" in low and ("provinsi" in low or "kabupaten" in low):
                kec = re.search(r"Kecamatan\s+(.*?),\s*Kabupaten", value)
                kab = re.search(r"Kabupaten\s*(?:Kota)?\s*(.*?),\s*Provinsi", value)
                prov = re.search(r"Provinsi\s+(.*)$", value)
                if kec:
                    meta["kecamatan"] = kec.group(1).strip()
                if kab:
                    meta["kabupaten"] = kab.group(1).strip()
                if prov:
                    meta["provinsi"] = prov.group(1).strip()
        if index == 1 and "sekolah" not in meta and values[0]:
            meta["sekolah"] = values[0]
        meta.setdefault("baris_judul", "")
        if index == 0:
            meta["baris_judul"] = joined
    return meta


def detect_kind(mapping: dict[int, str]) -> str:
    keys = set(mapping.values())
    # Struktur wajib daftar peserta didik: identitas inti.
    if {"nama", "nisn"} <= keys or len(keys & {"nama", "nisn", "nipd", "rombel"}) >= 3:
        return "daftar_peserta_didik"
    return "generik"


# --------------------------------------------------------------------------- #
# Konversi nilai sesuai tipe field
# --------------------------------------------------------------------------- #
def convert_value(spec: FieldSpec, value: Any) -> tuple[Any, str | None]:
    """Ubah nilai mentah ke tipe database. Mengembalikan (nilai, peringatan)."""
    if spec.kind == "date":
        return to_iso_date(value)
    if spec.kind == "int":
        return parse_int(value), None
    if spec.kind == "float":
        return parse_float(value), None
    if spec.kind == "ya_tidak":
        text = clean_text(value)
        if text is None:
            return None, None
        low = text.lower()
        if low.startswith("ya") or low in {"y", "yes", "1", "true"}:
            return "Ya", None
        if low.startswith("tidak") or low in {"t", "no", "0", "false"}:
            return "Tidak", None
        return text, f"Nilai '{text}' tidak dikenali untuk kolom Ya/Tidak (dianggap Tidak)."
    return clean_text(value, upper=False), None


def derive_tingkat(rombel: str | None) -> str | None:
    """'9D' -> '9'; 'VII A' -> '7'."""
    if not rombel:
        return None
    text = str(rombel).strip().upper()
    match = re.match(r"^(\d{1,2})", text)
    if match:
        return match.group(1)
    roman = re.match(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\b", text)
    if roman:
        table = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6",
                 "VII": "7", "VIII": "8", "IX": "9", "X": "10", "XI": "11", "XII": "12"}
        return table.get(roman.group(1))
    return None


YA_TIDAK_FLAGS = {
    "penerima_kps": "is_kps",
    "penerima_kip": "is_kip",
    "layak_pip": "is_layak_pip",
}


# --------------------------------------------------------------------------- #
# Validasi
# --------------------------------------------------------------------------- #
def validate_record(record: StudentRecord, seen_nisn: dict[str, int]) -> None:
    """Tambah temuan pada record (mutasi langsung)."""
    values = record.values
    nama = values.get("nama")
    if not nama or len(str(nama)) < 3:
        record.issues.append(Issue(record.row_number, "error", "nama", "Nama siswa kosong atau terlalu pendek."))

    nisn = values.get("nisn")
    if not nisn:
        record.issues.append(Issue(record.row_number, "error", "nisn", "NISN kosong — siswa tidak bisa login."))
    else:
        text = str(nisn).strip()
        if not text.isdigit():
            record.issues.append(Issue(record.row_number, "error", "nisn", f"NISN '{text}' bukan angka."))
        elif len(text) != 10:
            record.issues.append(
                Issue(record.row_number, "warning", "nisn", f"Panjang NISN {len(text)} digit (Dapodik mensyaratkan 10 digit).")
            )
        if text in seen_nisn and seen_nisn[text] != record.row_number:
            record.issues.append(
                Issue(record.row_number, "warning", "nisn", f"NISN {text} ganda dengan baris {seen_nisn[text]}.")
            )

    nik = values.get("nik")
    if not nik:
        record.issues.append(Issue(record.row_number, "info", "nik", "NIK belum diisi."))
    elif str(nik).strip().isdigit() and len(str(nik).strip()) != 16:
        record.issues.append(Issue(record.row_number, "warning", "nik", f"NIK {nik} berjumlah {len(str(nik).strip())} digit (seharusnya 16)."))

    jk = values.get("jk")
    if jk and str(jk).strip().upper() not in {"L", "P"}:
        record.issues.append(Issue(record.row_number, "warning", "jk", f"Jenis kelamin '{jk}' di luar L/P."))

    if not values.get("tanggal_lahir"):
        record.issues.append(Issue(record.row_number, "warning", "tanggal_lahir", "Tanggal lahir belum ada/format tidak dikenali."))
    if not values.get("rombel"):
        record.issues.append(Issue(record.row_number, "warning", "rombel", "Rombel/kelas belum diisi."))
    if not values.get("no_kk"):
        record.issues.append(Issue(record.row_number, "info", "no_kk", "Nomor Kartu Keluarga kosong."))
    if not values.get("ayah_nama"):
        record.issues.append(Issue(record.row_number, "info", "ayah_nama", "Nama ayah kosong."))
    if not values.get("ibu_nama"):
        record.issues.append(Issue(record.row_number, "info", "ibu_nama", "Nama ibu kosong."))


# --------------------------------------------------------------------------- #
# API utama parser
# --------------------------------------------------------------------------- #
def parse_sheet(
    sheet: SheetData,
    *,
    header_row: int | None = None,
    sub_header_row: int | None = None,
    column_map: dict[int, str] | None = None,
) -> ParsedSpreadsheet:
    """Urai satu worksheet menjadi catatan peserta didik + temuan validasi.

    Parameter opsional dipakai saat pengguna memperbaiki pemetaan kolom di UI.
    """
    detected_header, detected_sub = find_header_row(sheet)
    header = header_row or detected_header
    sub = detected_sub if sub_header_row is None else sub_header_row
    columns = build_columns(sheet, header, sub)
    mapping = column_map if column_map is not None else build_mapping(columns)
    mapping = dict(mapping)

    data_start = (sub or header) + 1
    records: list[StudentRecord] = []
    issues: list[Issue] = []
    seen_nisn: dict[str, int] = {}

    for index in range(data_start - 1, sheet.row_count):
        row = sheet.rows[index]
        row_number = index + 1
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        values: dict[str, Any] = {}
        raw: dict[str, Any] = {}
        row_issues: list[Issue] = []

        for col_index, cell in enumerate(row):
            label = columns[col_index] if col_index < len(columns) else f"Kolom {col_index + 1}"
            if cell is None or str(cell).strip() == "":
                continue
            raw[label] = cell
            field_key = mapping.get(col_index)
            if not field_key:
                continue
            spec = FIELD_BY_KEY.get(field_key)
            if spec is None:
                continue
            converted, warning = convert_value(spec, cell)
            if converted is not None:
                values[field_key] = converted
            if warning:
                row_issues.append(Issue(row_number, "warning", field_key, warning))

        # Baris yang sama sekali tidak menghasilkan field -> kemungkinan baris catatan.
        if not values:
            if raw:
                row_issues.append(Issue(row_number, "info", None, "Baris tidak menghasilkan data yang dikenal (dilewati)."))
                issues.extend(row_issues)
            continue

        # Turunan otomatis
        for source_key, flag_key in YA_TIDAK_FLAGS.items():
            values[flag_key] = 1 if values.get(source_key) == "Ya" else 0
        tingkat = derive_tingkat(values.get("rombel"))
        if tingkat and not values.get("tingkat"):
            values["tingkat"] = tingkat

        if values.get("nama"):
            values["nama"] = clean_text(values["nama"], upper=True)
        if values.get("nisn"):
            values["nisn"] = str(values["nisn"]).strip()

        nisn_text = str(values.get("nisn") or "")
        if nisn_text:
            seen_nisn.setdefault(nisn_text, row_number)

        record = StudentRecord(row_number=row_number, values=values, raw=raw, issues=row_issues)
        validate_record(record, seen_nisn)
        records.append(record)

    for record in records:
        issues.extend(record.issues)

    kind = detect_kind(mapping)
    # mapping publik: {field_key: label kolom asli pada berkas}
    detail_mapping = {
        key: columns[col] for col, key in sorted(mapping.items()) if col < len(columns)
    }
    return ParsedSpreadsheet(
        sheet_name=sheet.name,
        kind=kind,
        header_row=header,
        sub_header_row=sub,
        data_start_row=data_start,
        columns=columns,
        mapping=detail_mapping,
        column_map=mapping,
        records=records,
        issues=issues,
        metadata=extract_metadata(sheet, header),
        total_columns=len(columns),
    )


def summarize_issues(issues: Iterable[Issue]) -> dict[str, int]:
    summary = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        summary[issue.level] = summary.get(issue.level, 0) + 1
    return summary
