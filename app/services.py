"""Lapisan layanan (business logic) SM.

Semua akses data terpusat di sini supaya router HTTP tetap tipis dan logika
mudah diuji maupun dipanggil ulang oleh bot Dapodik di tahap berikutnya.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, db
from .dapodik import (
    FIELD_BY_KEY,
    FIELD_WALI,
    PEKERJAAN_OPTIONS,
    PENGHASILAN_OPTIONS,
    PENDIDIKAN_OPTIONS,
    STUDENT_FIELDS,
    ParsedSpreadsheet,
    parse_sheet,
    summarize_issues,
)
from .readers import SheetData, format_label, read_spreadsheet

log = logging.getLogger("sm.services")

# --------------------------------------------------------------------------- #
# Kolom yang boleh ditulis ke tabel students
# --------------------------------------------------------------------------- #
STUDENT_COLUMNS: tuple[str, ...] = tuple(spec.key for spec in STUDENT_FIELDS) + (
    "is_kps", "is_kip", "is_layak_pip", "status", "catatan",
)
STUDENT_WRITABLE = set(STUDENT_COLUMNS)

STATUS_OPTIONS = ("Aktif", "Lulus", "Mutasi", "Keluar", "Non-aktif")
AGAMA_OPTIONS = ("Islam", "Kristen", "Katholik", "Hindu", "Budha", "Konghucu", "Kepercayaan")

# Field yang dianggap penting untuk kelengkapan data (dipakai halaman Kualitas Data).
FIELD_WAJIB = ("nama", "nisn", "jk", "tempat_lahir", "tanggal_lahir", "nik",
               "alamat", "kelurahan", "kecamatan", "agama", "rombel")
FIELD_PENTING = ("nipd", "no_kk", "hp", "ayah_nama", "ayah_pekerjaan", "ibu_nama",
                 "ibu_pekerjaan", "no_registrasi_akta")


# =========================================================================== #
# PENGATURAN
# =========================================================================== #
def get_settings() -> dict[str, str]:
    return {row["key"]: row["value"] for row in db.query_all("SELECT key, value FROM settings")}


def get_setting(key: str, default: str | None = None) -> str | None:
    row = db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
    if row is None or row["value"] is None:
        return default
    return row["value"]


def set_setting(key: str, value: Any) -> None:
    db.execute(
        """
        INSERT INTO settings(key, value, updated_at) VALUES(?, ?, datetime('now','localtime'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, None if value is None else str(value)),
    )


def update_settings(values: dict[str, Any]) -> None:
    with db.transaction() as conn:
        for key, value in values.items():
            conn.execute(
                """
                INSERT INTO settings(key, value, updated_at) VALUES(?, ?, datetime('now','localtime'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, None if value is None else str(value)),
            )


def school_profile() -> dict[str, str]:
    data = get_settings()
    return {
        "nama": data.get("school_nama") or "Sekolah",
        "npsn": data.get("school_npsn") or "",
        "alamat": data.get("school_alamat") or "",
        "kecamatan": data.get("school_kecamatan") or "",
        "kabupaten": data.get("school_kabupaten") or "",
        "provinsi": data.get("school_provinsi") or "",
        "kepala": data.get("school_kepala") or "",
        "email": data.get("school_email") or "",
        "telepon": data.get("school_telepon") or "",
        "tahun_ajaran": data.get("tahun_ajaran") or config.TAHUN_AJARAN_DEFAULT,
        "semester": data.get("semester") or config.SEMESTER_DEFAULT,
    }


# =========================================================================== #
# AUDIT
# =========================================================================== #
def log_audit(actor: str | None, role: str | None, aksi: str,
              entitas: str | None = None, entitas_id: Any = None,
              detail: str | None = None, ip: str | None = None) -> None:
    db.execute(
        """
        INSERT INTO audit_log(actor, role, aksi, entitas, entitas_id, detail, ip)
        VALUES(?,?,?,?,?,?,?)
        """,
        (actor, role, aksi, entitas, None if entitas_id is None else str(entitas_id), detail, ip),
    )


def recent_audit(limit: int = 20) -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    )


# =========================================================================== #
# IMPOR BERKAS
# =========================================================================== #
@dataclass
class StoredFile:
    path: Path
    filename: str
    size: int
    extension: str


def save_upload(filename: str, content: bytes) -> StoredFile:
    """Simpan berkas unggahan ke folder data (nama unik, aman dari path traversal)."""
    config.ensure_dirs()
    safe_name = re.sub(r"[^\w.\- ]+", "_", Path(filename).name).strip() or "unggahan"
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = config.UPLOAD_DIR / f"{stamp}__{safe_name}"
    counter = 1
    while target.exists():
        target = config.UPLOAD_DIR / f"{stamp}-{counter}__{safe_name}"
        counter += 1
    target.write_bytes(content)
    return StoredFile(
        path=target,
        filename=filename,
        size=len(content),
        extension=target.suffix.lower(),
    )


def create_import(
    stored: StoredFile,
    *,
    sheet: SheetData,
    parsed: ParsedSpreadsheet,
    fmt: str,
    actor: str | None,
    mode: str = "upsert",
) -> int:
    summary = summarize_issues(parsed.issues)
    status = "draft"
    import_id = db.insert_returning_id(
        """
        INSERT INTO imports(
            filename, stored_path, file_ext, file_size, file_format, sheet_name,
            header_row, mapping_json, meta_json, mode, status, rows_total,
            detected_kind, message, created_by
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            stored.filename,
            str(stored.path),
            stored.extension,
            stored.size,
            fmt,
            sheet.name,
            parsed.header_row,
            json.dumps(parsed.mapping, ensure_ascii=False),
            json.dumps({"metadata": parsed.metadata, **summary}, ensure_ascii=False),
            mode,
            status,
            len(parsed.records),
            parsed.kind,
            f"{len(parsed.records)} baris data terdeteksi, {summary['error']} error, {summary['warning']} peringatan.",
            actor,
        ),
    )
    for issue in parsed.issues[:2000]:
        db.execute(
            "INSERT INTO import_issues(import_id, row_number, level, field, message) VALUES(?,?,?,?,?)",
            (import_id, issue.row_number, issue.level, issue.field, issue.message),
        )
    return import_id


def list_imports(limit: int = 50) -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all("SELECT * FROM imports ORDER BY id DESC LIMIT ?", (limit,))
    )


def get_import(import_id: int) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM imports WHERE id = ?", (import_id,))
    return db.row_to_dict(row)


def import_issues(import_id: int, level: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    if level:
        rows = db.query_all(
            "SELECT * FROM import_issues WHERE import_id = ? AND level = ? ORDER BY row_number LIMIT ?",
            (import_id, level, limit),
        )
    else:
        rows = db.query_all(
            "SELECT * FROM import_issues WHERE import_id = ? ORDER BY row_number LIMIT ?",
            (import_id, limit),
        )
    return db.rows_to_dicts(rows)


def count_import_issues(import_id: int) -> dict[str, int]:
    rows = db.query_all(
        "SELECT level, COUNT(*) AS jumlah FROM import_issues WHERE import_id = ? GROUP BY level",
        (import_id,),
    )
    result = {"error": 0, "warning": 0, "info": 0}
    for row in rows:
        result[row["level"]] = row["jumlah"]
    return result


def delete_import(import_id: int) -> None:
    record = get_import(import_id)
    if record and record.get("stored_path"):
        try:
            Path(record["stored_path"]).unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass
    db.execute("DELETE FROM imports WHERE id = ?", (import_id,))


@dataclass
class ImportResult:
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    issues: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.issues is None:
            self.issues = []


def import_students(
    parsed: ParsedSpreadsheet,
    *,
    import_id: int | None = None,
    mode: str = "upsert",
    actor: str | None = None,
    source_file: str | None = None,
    only_valid: bool = True,
    column_map: dict[int, str] | None = None,
) -> ImportResult:
    """Simpan hasil parsing ke tabel ``students``.

    mode:
        ``insert``  - hanya tambah siswa baru, NISN yang sudah ada dilewati
        ``upsert``  - tambah baru / perbarui data yang sudah ada (default)
        ``replace`` - perbarui seluruh field yang tersedia, termasuk menimpa manual
        ``dry``     - hanya validasi, tidak menulis apa pun
    """
    result = ImportResult(total=len(parsed.records))
    if mode == "dry":
        return result

    with db.transaction() as conn:
        for record in parsed.records:
            if only_valid and record.has_error:
                result.failed += 1
                result.issues.append(
                    f"Baris {record.row_number}: dilewati karena {record.issues[0].message}"
                    if record.issues else f"Baris {record.row_number}: dilewati (data tidak valid)"
                )
                continue

            values = {key: value for key, value in record.values.items() if key in STUDENT_WRITABLE}
            if not values.get("nama"):
                result.failed += 1
                continue

            nisn = values.get("nisn")
            existing = None
            if nisn:
                existing = conn.execute("SELECT id FROM students WHERE nisn = ?", (nisn,)).fetchone()
            if existing is None and values.get("nipd"):
                existing = conn.execute(
                    "SELECT id FROM students WHERE nipd = ? AND (nisn IS NULL OR nisn = '')",
                    (values["nipd"],),
                ).fetchone()

            if existing is None:
                if mode == "insert" or mode in {"upsert", "replace"}:
                    columns = list(values.keys()) + ["source_file", "import_id"]
                    placeholders = ", ".join("?" for _ in columns)
                    conn.execute(
                        f"INSERT INTO students({', '.join(columns)}) VALUES({placeholders})",
                        [*values.values(), source_file, import_id],
                    )
                    result.imported += 1
                else:
                    result.skipped += 1
                continue

            student_id = existing["id"]
            if mode == "insert":
                result.skipped += 1
                continue

            current = dict(conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone())
            changes = []
            updates: dict[str, Any] = {}
            for key, new_value in values.items():
                old_value = current.get(key)
                if _same_value(old_value, new_value):
                    continue
                if mode == "upsert" and old_value not in (None, "") and key in {"nik", "no_kk", "nama"}:
                    # pada mode upsert, identitas kunci yang sudah terisi tidak ditimpa
                    continue
                updates[key] = new_value
                changes.append((key, old_value, new_value))

            if not updates:
                result.skipped += 1
                continue

            updates["source_file"] = source_file
            updates["import_id"] = import_id
            set_clause = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE students SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ?",
                [*updates.values(), student_id],
            )
            for field, old_value, new_value in changes:
                conn.execute(
                    """
                    INSERT INTO data_changes(student_id, nisn, field, old_value, new_value, source, actor)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (student_id, nisn, field, _text(old_value), _text(new_value), "impor", actor),
                )
            result.updated += 1

    if import_id is not None:
        status = "sukses"
        if result.failed and result.imported + result.updated == 0:
            status = "gagal"
        elif result.failed:
            status = "sebagian"
        db.execute(
            """
            UPDATE imports SET status = ?, rows_imported = ?, rows_updated = ?,
                   rows_skipped = ?, rows_failed = ?, finished_at = datetime('now','localtime')
             WHERE id = ?
            """,
            (status, result.imported, result.updated, result.skipped, result.failed, import_id),
        )
    return result


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _same_value(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    if a is None or b is None:
        return False
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def read_and_parse(path: str | Path, ext: str | None = None, sheet_index: int = 0,
                   column_map: dict[int, str] | None = None) -> tuple[SheetData, ParsedSpreadsheet, str]:
    """Helper: baca berkas lalu urai isinya (dipakai halaman impor)."""
    sheets = read_spreadsheet(path, ext)
    sheet = sheets[min(sheet_index, len(sheets) - 1)]
    parsed = parse_sheet(sheet, column_map=column_map) if column_map else parse_sheet(sheet)
    extension = Path(path).suffix.lower()
    return sheet, parsed, format_label(extension)


# =========================================================================== #
# PESERTA DIDIK
# =========================================================================== #
SORTABLE_COLUMNS = {
    "nama": "nama",
    "nisn": "nisn",
    "nipd": "nipd",
    "rombel": "rombel",
    "tingkat": "tingkat",
    "tanggal_lahir": "tanggal_lahir",
    "kelurahan": "kelurahan",
    "updated_at": "updated_at",
}


@dataclass
class StudentFilter:
    q: str = ""
    rombel: str = ""
    tingkat: str = ""
    jk: str = ""
    agama: str = ""
    status: str = ""
    kelurahan: str = ""
    sort: str = "nama"
    direction: str = "asc"
    incomplete_only: bool = False

    def where_clause(self) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if self.q:
            like = f"%{self.q.strip()}%"
            clauses.append(
                "(s.nama LIKE ? OR s.nisn LIKE ? OR s.nipd LIKE ? OR s.nik LIKE ? "
                "OR s.no_kk LIKE ? OR s.rombel LIKE ? OR s.ayah_nama LIKE ? OR s.ibu_nama LIKE ?)"
            )
            params.extend([like] * 8)
        if self.rombel:
            clauses.append("s.rombel = ?")
            params.append(self.rombel)
        if self.tingkat:
            clauses.append("s.tingkat = ?")
            params.append(self.tingkat)
        if self.jk:
            clauses.append("s.jk = ?")
            params.append(self.jk)
        if self.agama:
            clauses.append("s.agama = ?")
            params.append(self.agama)
        if self.status:
            clauses.append("s.status = ?")
            params.append(self.status)
        if self.kelurahan:
            clauses.append("s.kelurahan = ?")
            params.append(self.kelurahan)
        if self.incomplete_only:
            checks = " OR ".join(f"s.{field} IS NULL OR TRIM(s.{field}) = ''" for field in FIELD_WAJIB)
            clauses.append(f"({checks})")

        return (" AND ".join(clauses) if clauses else "1=1"), params

    def order_clause(self) -> str:
        column = SORTABLE_COLUMNS.get(self.sort, "nama")
        direction = "DESC" if str(self.direction).lower() == "desc" else "ASC"
        return f"{column} COLLATE NOCASE {direction}, s.id {direction}"


def _pick_columns(include_detail: bool = False) -> str:
    base = (
        "s.id, s.nama, s.nisn, s.nipd, s.jk, s.rombel, s.tingkat, s.tempat_lahir, "
        "s.tanggal_lahir, s.nik, s.agama, s.kelurahan, s.kecamatan, s.hp, s.status, "
        "s.is_kip, s.is_kps, s.is_layak_pip, s.updated_at, s.alamat"
    )
    return base + (", s.*" if include_detail else "")


def list_students(
    filters: StudentFilter,
    page: int = 1,
    per_page: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    per_page = per_page or config.ROWS_PER_PAGE
    where, params = filters.where_clause()
    total = int(db.query_value(f"SELECT COUNT(*) FROM students s WHERE {where}", params, 0) or 0)
    offset = max(0, (page - 1) * per_page)
    rows = db.query_all(
        f"""
        SELECT {_pick_columns()} FROM students s
        WHERE {where}
        ORDER BY {filters.order_clause()}
        LIMIT ? OFFSET ?
        """,
        [*params, per_page, offset],
    )
    return db.rows_to_dicts(rows), total


def get_student(student_id: int) -> dict[str, Any] | None:
    return db.row_to_dict(db.query_one("SELECT * FROM students WHERE id = ?", (student_id,)))


def get_student_by_nisn(nisn: str) -> dict[str, Any] | None:
    return db.row_to_dict(db.query_one("SELECT * FROM students WHERE nisn = ?", (str(nisn).strip(),)))


def student_exists(nisn: str | None, nipd: str | None = None,
                   exclude_id: int | None = None) -> dict[str, Any] | None:
    """Cek duplikat NISN/NIPD sebelum simpan manual."""
    params: list[Any] = []
    clauses: list[str] = []
    if nisn:
        clauses.append("nisn = ?")
        params.append(nisn)
    if nipd:
        clauses.append("nipd = ?")
        params.append(nipd)
    if not clauses:
        return None
    sql = f"SELECT id, nama, nisn, nipd FROM students WHERE ({' OR '.join(clauses)})"
    if exclude_id:
        sql += " AND id <> ?"
        params.append(exclude_id)
    return db.row_to_dict(db.query_one(sql, params))


def create_student(data: dict[str, Any], actor: str | None = None) -> int:
    values = {key: value for key, value in data.items() if key in STUDENT_WRITABLE}
    if not values.get("nama"):
        raise ValueError("Nama siswa wajib diisi.")
    # Data wali yang tidak sesuai aturan tidak disimpan (sistem yang menghapus).
    kosong = normalisasi_wali(values)
    if kosong:
        alasan = kosong.pop("__alasan__")
        values.update({key: None for key in kosong})
        log.info("Data wali tidak disimpan untuk %s: %s", values.get("nama"), alasan)
        data_wali_kosong = True
    else:
        data_wali_kosong = False
    if not values.get("tingkat") and values.get("rombel"):
        from .dapodik import derive_tingkat

        values["tingkat"] = derive_tingkat(values["rombel"])
    columns = list(values.keys())
    placeholders = ", ".join("?" for _ in columns)
    student_id = db.insert_returning_id(
        f"INSERT INTO students({', '.join(columns)}) VALUES({placeholders})",
        [values[key] for key in columns],
    )
    for key, value in values.items():
        db.execute(
            "INSERT INTO data_changes(student_id, nisn, field, new_value, source, actor) VALUES(?,?,?,?,?,?)",
            (student_id, values.get("nisn"), key, _text(value), "manual", actor),
        )
    log_audit(actor, None, "tambah_siswa", "students", student_id, values.get("nama"))
    if data_wali_kosong:
        log_audit(actor, None, "hapus_wali_otomatis", "students", student_id,
                  f"{values.get('nama')} — data wali tidak disimpan sesuai aturan")
    return student_id


def update_student(student_id: int, data: dict[str, Any],
                   actor: str | None = None, source: str = "manual") -> list[tuple[str, Any, Any]]:
    """Perbarui siswa dan catat setiap perubahan field (untuk audit & bot Dapodik).

    Data wali yang tidak sesuai aturan (nama ayah terisi, nama wali sama dengan
    ayah/ibu, atau kolom wali tanpa nama) dihapus otomatis oleh sistem.
    """
    current = get_student(student_id)
    if current is None:
        raise ValueError("Siswa tidak ditemukan.")

    kosong = normalisasi_wali(data, current)
    if kosong:
        alasan_wali = kosong.pop("__alasan__")
        data = {**data, **kosong}
        log_audit(actor, None, "hapus_wali_otomatis", "students", student_id,
                  f"{current.get('nama')} — {alasan_wali}")

    updates: dict[str, Any] = {}
    changes: list[tuple[str, Any, Any]] = []
    for key, new_value in data.items():
        if key not in STUDENT_WRITABLE or key in {"status"} and new_value == "":
            continue
        old_value = current.get(key)
        if _same_value(old_value, new_value):
            continue
        updates[key] = new_value
        changes.append((key, old_value, new_value))

    if not updates:
        return []
    if "rombel" in updates and "tingkat" not in updates:
        from .dapodik import derive_tingkat

        updates["tingkat"] = derive_tingkat(updates["rombel"])

    set_clause = ", ".join(f"{key} = ?" for key in updates)
    with db.transaction() as conn:
        conn.execute(
            f"UPDATE students SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ?",
            [*updates.values(), student_id],
        )
        for field, old_value, new_value in changes:
            conn.execute(
                """
                INSERT INTO data_changes(student_id, nisn, field, old_value, new_value, source, actor)
                VALUES(?,?,?,?,?,?,?)
                """,
                (student_id, current.get("nisn"), field, _text(old_value), _text(new_value), source, actor),
            )
    log_audit(actor, None, "ubah_siswa", "students", student_id, ", ".join(f"{f}" for f, _, _ in changes))
    return changes


def delete_student(student_id: int, actor: str | None = None) -> None:
    student = get_student(student_id)
    db.execute("DELETE FROM students WHERE id = ?", (student_id,))
    if student:
        log_audit(actor, None, "hapus_siswa", "students", student_id, student.get("nama"))


def student_changes(student_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all(
            "SELECT * FROM data_changes WHERE student_id = ? ORDER BY id DESC LIMIT ?",
            (student_id, limit),
        )
    )


def distinct_values(column: str, limit: int = 500) -> list[str]:
    if column not in {"rombel", "tingkat", "jk", "agama", "kelurahan", "kecamatan", "status"}:
        raise ValueError(f"Kolom '{column}' tidak boleh dipakai untuk filter.")
    rows = db.query_all(
        f"SELECT DISTINCT {column} AS v FROM students WHERE {column} IS NOT NULL AND TRIM({column}) <> '' "
        f"ORDER BY {column} COLLATE NOCASE LIMIT ?",
        (limit,),
    )
    return [row["v"] for row in rows]


def student_stats() -> dict[str, Any]:
    total = int(db.query_value("SELECT COUNT(*) FROM students") or 0)
    laki = int(db.query_value("SELECT COUNT(*) FROM students WHERE jk = 'L'") or 0)
    perempuan = int(db.query_value("SELECT COUNT(*) FROM students WHERE jk = 'P'") or 0)
    rombel_count = int(db.query_value("SELECT COUNT(DISTINCT rombel) FROM students WHERE rombel IS NOT NULL AND rombel <> ''") or 0)
    kip = int(db.query_value("SELECT COUNT(*) FROM students WHERE is_kip = 1") or 0)
    kps = int(db.query_value("SELECT COUNT(*) FROM students WHERE is_kps = 1") or 0)
    pip = int(db.query_value("SELECT COUNT(*) FROM students WHERE is_layak_pip = 1") or 0)
    return {
        "total": total,
        "laki_laki": laki,
        "perempuan": perempuan,
        "rombel": rombel_count,
        "penerima_kip": kip,
        "penerima_kps": kps,
        "layak_pip": pip,
    }


def stats_by_rombel() -> list[dict[str, Any]]:
    rows = db.query_all(
        """
        SELECT rombel,
               COUNT(*) AS jumlah,
               SUM(CASE WHEN jk = 'L' THEN 1 ELSE 0 END) AS laki_laki,
               SUM(CASE WHEN jk = 'P' THEN 1 ELSE 0 END) AS perempuan,
               MAX(tingkat) AS tingkat
          FROM students
         WHERE rombel IS NOT NULL AND TRIM(rombel) <> ''
         GROUP BY rombel
         ORDER BY MIN(tingkat), rombel COLLATE NOCASE
        """
    )
    return db.rows_to_dicts(rows)


def stats_by_tingkat() -> list[dict[str, Any]]:
    rows = db.query_all(
        """
        SELECT COALESCE(NULLIF(tingkat,''),'-') AS tingkat,
               COUNT(*) AS jumlah,
               COUNT(DISTINCT rombel) AS rombel,
               SUM(CASE WHEN jk = 'L' THEN 1 ELSE 0 END) AS laki_laki,
               SUM(CASE WHEN jk = 'P' THEN 1 ELSE 0 END) AS perempuan
          FROM students
         GROUP BY COALESCE(NULLIF(tingkat,''),'-')
         ORDER BY tingkat
        """
    )
    return db.rows_to_dicts(rows)


def stats_by(column: str, limit: int = 12) -> list[dict[str, Any]]:
    if column not in {"agama", "kelurahan", "kecamatan", "sekolah_asal"}:
        raise ValueError("Kolom statistik tidak diizinkan.")
    rows = db.query_all(
        f"""
        SELECT COALESCE(NULLIF({column},''),'(belum diisi)') AS label, COUNT(*) AS jumlah
          FROM students
         GROUP BY COALESCE(NULLIF({column},''),'(belum diisi)')
         ORDER BY jumlah DESC
         LIMIT ?
        """,
        (limit,),
    )
    return db.rows_to_dicts(rows)


def data_quality() -> dict[str, Any]:
    """Ringkas kelengkapan data siswa per field — bahan perbaikan sebelum sinkron Dapodik."""
    total = int(db.query_value("SELECT COUNT(*) FROM students") or 0)
    items: list[dict[str, Any]] = []
    for spec in STUDENT_FIELDS:
        filled = int(
            db.query_value(
                f"SELECT COUNT(*) FROM students WHERE {spec.key} IS NOT NULL AND TRIM(CAST({spec.key} AS TEXT)) <> ''"
            )
            or 0
        )
        items.append(
            {
                "key": spec.key,
                "label": spec.label,
                "group": spec.group,
                "wajib": spec.key in FIELD_WAJIB,
                "terisi": filled,
                "kosong": total - filled,
                "persen": round(filled / total * 100, 1) if total else 0.0,
            }
        )

    # Siswa dengan data wajib belum lengkap
    checks = " OR ".join(f"s.{field} IS NULL OR TRIM(CAST(s.{field} AS TEXT)) = ''" for field in FIELD_WAJIB)
    belum_lengkap = int(db.query_value(f"SELECT COUNT(*) FROM students s WHERE {checks}") or 0)

    # Temuan spesifik ala Dapodik
    tanda_pendidikan = ", ".join("?" for _ in PENDIDIKAN_OPTIONS)
    tanda_pekerjaan = ", ".join("?" for _ in PEKERJAAN_OPTIONS)
    tanda_penghasilan = ", ".join("?" for _ in PENGHASILAN_OPTIONS)
    baku_pendidikan = [opsi.lower() for opsi in PENDIDIKAN_OPTIONS]
    baku_pekerjaan = [opsi.lower() for opsi in PEKERJAAN_OPTIONS]
    baku_penghasilan = [opsi.lower() for opsi in PENGHASILAN_OPTIONS]
    temuan = [
        {
            "kode": "NISN_TIDAK_VALID",
            "label": "NISN bukan 10 digit angka",
            "jumlah": int(db.query_value(
                "SELECT COUNT(*) FROM students WHERE nisn IS NULL OR LENGTH(TRIM(nisn)) <> 10 OR TRIM(nisn) GLOB '*[^0-9]*'"
            ) or 0),
            "field": "nisn",
        },
        {
            "kode": "NIK_TIDAK_VALID",
            "label": "NIK bukan 16 digit angka",
            "jumlah": int(db.query_value(
                "SELECT COUNT(*) FROM students WHERE nik IS NULL OR TRIM(nik) = '' OR LENGTH(TRIM(nik)) <> 16 OR TRIM(nik) GLOB '*[^0-9]*'"
            ) or 0),
            "field": "nik",
        },
        {
            "kode": "TANGGAL_LAHIR_KOSONG",
            "label": "Tanggal lahir belum diisi",
            "jumlah": int(db.query_value("SELECT COUNT(*) FROM students WHERE tanggal_lahir IS NULL OR TRIM(tanggal_lahir) = ''") or 0),
            "field": "tanggal_lahir",
        },
        {
            "kode": "ROMBEL_KOSONG",
            "label": "Rombel belum diisi",
            "jumlah": int(db.query_value("SELECT COUNT(*) FROM students WHERE rombel IS NULL OR TRIM(rombel) = ''") or 0),
            "field": "rombel",
        },
        {
            "kode": "NO_KK_KOSONG",
            "label": "Nomor Kartu Keluarga belum diisi",
            "jumlah": int(db.query_value("SELECT COUNT(*) FROM students WHERE no_kk IS NULL OR TRIM(no_kk) = ''") or 0),
            "field": "no_kk",
        },
        {
            "kode": "NISN_GANDA",
            "label": "NISN ganda",
            "jumlah": int(db.query_value(
                "SELECT COUNT(*) FROM (SELECT nisn FROM students WHERE nisn IS NOT NULL AND TRIM(nisn) <> '' GROUP BY nisn HAVING COUNT(*) > 1)"
            ) or 0),
            "field": "nisn",
        },
        {
            "kode": "ALAMAT_KOSONG",
            "label": "Alamat belum diisi",
            "jumlah": int(db.query_value("SELECT COUNT(*) FROM students WHERE alamat IS NULL OR TRIM(alamat) = ''") or 0),
            "field": "alamat",
        },
        {
            "kode": "AYAH_IBU_SAMA",
            "label": "Nama ayah sama dengan nama ibu",
            "jumlah": int(db.query_value(
                """
                SELECT COUNT(*) FROM students
                 WHERE ayah_nama IS NOT NULL AND TRIM(ayah_nama) <> ''
                   AND ibu_nama IS NOT NULL AND TRIM(ibu_nama) <> ''
                   AND REPLACE(LOWER(TRIM(ayah_nama)), ' ', '')
                     = REPLACE(LOWER(TRIM(ibu_nama)), ' ', '')
                """
            ) or 0),
            "field": "ayah_nama",
        },
        {
            "kode": "WALI_SAMA_AYAH_IBU",
            "label": "Nama wali sama dengan nama ayah/ibu",
            "jumlah": int(db.query_value(
                """
                SELECT COUNT(*) FROM students
                 WHERE wali_nama IS NOT NULL AND TRIM(wali_nama) <> ''
                   AND REPLACE(LOWER(TRIM(wali_nama)), ' ', '')
                       IN (REPLACE(LOWER(TRIM(COALESCE(ayah_nama, ''))), ' ', ''),
                           REPLACE(LOWER(TRIM(COALESCE(ibu_nama, ''))), ' ', ''))
                """
            ) or 0),
            "field": "wali_nama",
        },
        {
            "kode": "WALI_PERLU_DIBERSIHKAN",
            "label": "Data wali akan dihapus otomatis oleh sistem",
            "jumlah": len(siswa_perlu_bersih_wali()),
            "field": "wali_nama",
        },
        {
            "kode": "PENDIDIKAN_LUAR_DAFTAR",
            "label": "Pendidikan ayah/ibu/wali di luar daftar pilihan",
            "jumlah": int(db.query_value(
                f"""
                SELECT COUNT(*) FROM students
                 WHERE (COALESCE(ayah_pendidikan, '') <> '' AND LOWER(TRIM(ayah_pendidikan)) NOT IN ({tanda_pendidikan}))
                    OR (COALESCE(ibu_pendidikan, '') <> '' AND LOWER(TRIM(ibu_pendidikan)) NOT IN ({tanda_pendidikan}))
                    OR (COALESCE(wali_pendidikan, '') <> '' AND LOWER(TRIM(wali_pendidikan)) NOT IN ({tanda_pendidikan}))
                """,
                (*baku_pendidikan, *baku_pendidikan, *baku_pendidikan),
            ) or 0),
            "field": "ayah_pendidikan",
        },
        {
            "kode": "PEKERJAAN_LUAR_DAFTAR",
            "label": "Pekerjaan ayah/ibu/wali di luar daftar pilihan",
            "jumlah": int(db.query_value(
                f"""
                SELECT COUNT(*) FROM students
                 WHERE (COALESCE(ayah_pekerjaan, '') <> '' AND LOWER(TRIM(ayah_pekerjaan)) NOT IN ({tanda_pekerjaan}))
                    OR (COALESCE(ibu_pekerjaan, '') <> '' AND LOWER(TRIM(ibu_pekerjaan)) NOT IN ({tanda_pekerjaan}))
                    OR (COALESCE(wali_pekerjaan, '') <> '' AND LOWER(TRIM(wali_pekerjaan)) NOT IN ({tanda_pekerjaan}))
                """,
                (*baku_pekerjaan, *baku_pekerjaan, *baku_pekerjaan),
            ) or 0),
            "field": "ayah_pekerjaan",
        },
        {
            "kode": "PENGHASILAN_LUAR_DAFTAR",
            "label": "Penghasilan ayah/ibu/wali di luar daftar pilihan",
            "jumlah": int(db.query_value(
                f"""
                SELECT COUNT(*) FROM students
                 WHERE (COALESCE(ayah_penghasilan, '') <> '' AND LOWER(TRIM(ayah_penghasilan)) NOT IN ({tanda_penghasilan}))
                    OR (COALESCE(ibu_penghasilan, '') <> '' AND LOWER(TRIM(ibu_penghasilan)) NOT IN ({tanda_penghasilan}))
                    OR (COALESCE(wali_penghasilan, '') <> '' AND LOWER(TRIM(wali_penghasilan)) NOT IN ({tanda_penghasilan}))
                """,
                (*baku_penghasilan, *baku_penghasilan, *baku_penghasilan),
            ) or 0),
            "field": "ayah_penghasilan",
        },
        {
            "kode": "IBU_KOSONG",
            "label": "Data ibu belum diisi",
            "jumlah": int(db.query_value("SELECT COUNT(*) FROM students WHERE ibu_nama IS NULL OR TRIM(ibu_nama) = ''") or 0),
            "field": "ibu_nama",
        },
    ]
    return {
        "total": total,
        "fields": items,
        "wali_dibersihkan": siswa_perlu_bersih_wali(),
        "belum_lengkap": belum_lengkap,
        "siap_sinkron": max(0, total - belum_lengkap),
        "temuan": temuan,
    }


def students_with_duplicate_nisn() -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all(
            """
            SELECT nisn, COUNT(*) AS jumlah, GROUP_CONCAT(nama, ' | ') AS nama
              FROM students
             WHERE nisn IS NOT NULL AND TRIM(nisn) <> ''
             GROUP BY nisn HAVING COUNT(*) > 1
             ORDER BY jumlah DESC
            """
        )
    )


# --------------------------------------------------------------------------- #
# Ekspor
# --------------------------------------------------------------------------- #
def _export_field_keys() -> list[str]:
    return [spec.key for spec in STUDENT_FIELDS]


def export_students_csv(filters: StudentFilter) -> bytes:
    where, params = filters.where_clause()
    rows = db.query_all(f"SELECT * FROM students s WHERE {where} ORDER BY {filters.order_clause()}", params)
    columns = _export_field_keys()
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(["No", *[FIELD_BY_KEY[key].label for key in columns], "Status"])
    for index, row in enumerate(rows, start=1):
        writer.writerow([index, *[row[key] if key in row.keys() else "" for key in columns], row["status"]])
    return buffer.getvalue().encode("utf-8-sig")


def export_students_xlsx(filters: StudentFilter) -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    where, params = filters.where_clause()
    rows = db.query_all(f"SELECT * FROM students s WHERE {where} ORDER BY {filters.order_clause()}", params)
    columns = _export_field_keys()

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Daftar Peserta Didik"
    profile = school_profile()

    sheet["A1"] = "Daftar Peserta Didik"
    sheet["A1"].font = Font(size=14, bold=True)
    sheet["A2"] = profile["nama"]
    sheet["A3"] = f"Kecamatan {profile['kecamatan']}, {profile['kabupaten']}, {profile['provinsi']}".strip(", ")
    sheet["A4"] = f"Tahun Ajaran {profile['tahun_ajaran']} | Diekspor dari SM pada {dt.datetime.now():%Y-%m-%d %H:%M}"

    header = ["No", *[FIELD_BY_KEY[key].label for key in columns], "Status"]
    for col_index, label in enumerate(header, start=1):
        cell = sheet.cell(row=5, column=col_index, value=label)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1D4ED8")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_index, row in enumerate(rows, start=6):
        sheet.cell(row=row_index, column=1, value=row_index - 5)
        for col_index, key in enumerate(columns, start=2):
            value = row[key] if key in row.keys() else None
            sheet.cell(row=row_index, column=col_index, value=value)

    sheet.freeze_panes = "C6"
    sheet.auto_filter.ref = f"A5:{get_column_letter(len(header))}{max(5, 5 + len(rows))}"
    sheet.column_dimensions["A"].width = 5
    sheet.column_dimensions["B"].width = 30

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


# =========================================================================== #
# EKSTRAKURIKULER
# =========================================================================== #
EKSKUL_KATEGORI = ("Olahraga", "Seni", "Akademik", "Keagamaan", "Kepemimpinan", "Teknologi", "Lainnya")

#: Peran akun ekstrakurikuler. Satu ekskul hanya punya satu pembina & satu pelatih.
EKSKUL_PERAN = ("pembina", "pelatih")
PERAN_LABEL = {"pembina": "Pembina", "pelatih": "Pelatih"}
HARI_OPTIONS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")


# --------------------------------------------------------------------------- #
# Akun ekstrakurikuler (pembina & pelatih, masuk memakai NIK 16 digit)
# --------------------------------------------------------------------------- #
def _akun_ekskul_sql() -> str:
    return """
        SELECT a.*, e.nama AS ekskul_nama, e.pembina AS ekskul_pembina, e.pelatih AS ekskul_pelatih
          FROM ekskul_akun a JOIN extracurriculars e ON e.id = a.ekskul_id
    """


def akun_ekskul(nik: str) -> list[dict[str, Any]]:
    """Semua pendaftaran milik satu NIK (satu orang bisa mendampingi >1 ekskul)."""
    return db.rows_to_dicts(
        db.query_all(_akun_ekskul_sql() + " WHERE a.nik = ? ORDER BY e.nama COLLATE NOCASE", (nik,))
    )


def akun_ekskul_ekskul(ekskul_id: int) -> dict[str, dict[str, Any] | None]:
    """Isi posisi pembina & pelatih sebuah ekskul."""
    hasil: dict[str, dict[str, Any] | None] = {"pembina": None, "pelatih": None}
    for baris in db.rows_to_dicts(
        db.query_all(_akun_ekskul_sql() + " WHERE a.ekskul_id = ?", (ekskul_id,))
    ):
        if baris["peran"] in hasil:
            hasil[baris["peran"]] = baris
    return hasil


def akun_ekskul_posisi(ekskul_id: int, peran: str) -> dict[str, Any] | None:
    baris = db.query_one(_akun_ekskul_sql() + " WHERE a.ekskul_id = ? AND a.peran = ?", (ekskul_id, peran))
    return dict(baris) if baris is not None else None


def semua_akun_ekskul() -> list[dict[str, Any]]:
    """Daftar seluruh akun ekskul (untuk halaman Pengaturan)."""
    return db.rows_to_dicts(
        db.query_all(_akun_ekskul_sql() + " ORDER BY e.nama COLLATE NOCASE, a.peran")
    )


def klaim_akun_ekskul(ekskul_id: int, peran: str, nik: str, nama: str | None = None,
                      actor: str | None = None) -> int:
    """Daftarkan NIK pada posisi (ekskul, peran) yang masih kosong."""
    if peran not in EKSKUL_PERAN:
        raise ValueError("Peran harus Pembina atau Pelatih.")
    ekskul = get_ekskul(ekskul_id)
    if ekskul is None:
        raise ValueError("Ekstrakurikuler tidak ditemukan.")
    terisi = akun_ekskul_posisi(ekskul_id, peran)
    if terisi is not None:
        if terisi["nik"] == nik:
            return int(terisi["id"])
        raise ValueError(
            f"{PERAN_LABEL[peran]} {ekskul['nama']} sudah terdaftar. "
            "Hubungi admin sekolah bila memang perlu diganti."
        )
    akun_id = db.insert_returning_id(
        "INSERT INTO ekskul_akun(ekskul_id, peran, nik, nama) VALUES(?,?,?,?)",
        (ekskul_id, peran, nik, (nama or "").strip() or None),
    )
    _sinkron_pendamping(ekskul_id, peran, nama)
    log_audit(actor or nik, "ekskul", "klaim_akun_ekskul", "ekskul_akun", akun_id,
              f"{PERAN_LABEL[peran]} {ekskul['nama']} (NIK {nik})")
    return akun_id


def _sinkron_pendamping(ekskul_id: int, peran: str, nama: str | None) -> None:
    """Salin nama pembina/pelatih yang masuk lewat NIK ke kolom ekskulnya.

    Kolom ``pembina``/``pelatih`` tetap bisa diisi manual oleh admin, tetapi
    begitu pendamping masuk memakai NIK, namanya otomatis mengisi kolom itu.
    """
    kolom = peran if peran in EKSKUL_PERAN else None
    if not kolom:
        return
    nama = (nama or "").strip()
    if not nama:
        return
    db.execute(
        f"UPDATE extracurriculars SET {kolom} = ?, updated_at = datetime('now','localtime') WHERE id = ?",
        (nama, ekskul_id),
    )


def lepas_pendamping(ekskul_id: int, peran: str) -> None:
    """Kosongkan nama pembina/pelatih pada ekskul (dipakai saat akun dilepas)."""
    if peran not in EKSKUL_PERAN:
        return
    db.execute(
        f"UPDATE extracurriculars SET {peran} = NULL, updated_at = datetime('now','localtime') WHERE id = ?",
        (ekskul_id,),
    )


def perbarui_nama_akun_ekskul(akun_id: int, nama: str | None) -> None:
    nama = (nama or "").strip()
    if not nama:
        return
    db.execute("UPDATE ekskul_akun SET nama = ? WHERE id = ?", (nama, akun_id))
    baris = db.query_one("SELECT ekskul_id, peran FROM ekskul_akun WHERE id = ?", (akun_id,))
    if baris is not None:
        _sinkron_pendamping(int(baris["ekskul_id"]), baris["peran"], nama)


def catat_login_akun_ekskul(akun_id: int) -> None:
    db.execute(
        "UPDATE ekskul_akun SET login_terakhir = datetime('now','localtime') WHERE id = ?",
        (akun_id,),
    )


def lepas_akun_ekskul(akun_id: int, actor: str | None = None) -> dict[str, Any] | None:
    """Lepaskan NIK dari posisi ekskul (dipakai admin bila salah orang)."""
    baris = db.query_one(_akun_ekskul_sql() + " WHERE a.id = ?", (akun_id,))
    if baris is None:
        return None
    data = dict(baris)
    db.execute("DELETE FROM ekskul_akun WHERE id = ?", (akun_id,))
    lepas_pendamping(int(data["ekskul_id"]), data["peran"])
    log_audit(actor, "admin", "lepas_akun_ekskul", "ekskul_akun", akun_id,
              f"{PERAN_LABEL.get(data['peran'], data['peran'])} {data['ekskul_nama']} (NIK {data['nik']})")
    return data


def hitung_akun_ekskul() -> int:
    return int(db.query_value("SELECT COUNT(*) FROM ekskul_akun") or 0)


def list_ekskul(aktif_only: bool = False) -> list[dict[str, Any]]:
    sql = """
        SELECT e.*, (SELECT COUNT(*) FROM ekskul_members m WHERE m.ekskul_id = e.id AND m.status='aktif') AS jumlah_anggota
          FROM extracurriculars e
    """
    if aktif_only:
        sql += " WHERE e.aktif = 1"
    sql += " ORDER BY e.aktif DESC, e.nama COLLATE NOCASE"
    return db.rows_to_dicts(db.query_all(sql))


def get_ekskul(ekskul_id: int) -> dict[str, Any] | None:
    return db.row_to_dict(db.query_one("SELECT * FROM extracurriculars WHERE id = ?", (ekskul_id,)))


def save_ekskul(data: dict[str, Any], ekskul_id: int | None = None, actor: str | None = None) -> int:
    fields = ("nama", "pembina", "pelatih", "hari", "jam_mulai", "jam_selesai", "deskripsi", "aktif")
    values = {key: data.get(key) for key in fields if key in data}
    if not values.get("nama"):
        raise ValueError("Nama ekstrakurikuler wajib diisi.")

    if ekskul_id:
        set_clause = ", ".join(f"{key} = ?" for key in values)
        db.execute(
            f"UPDATE extracurriculars SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ?",
            [*values.values(), ekskul_id],
        )
        log_audit(actor, None, "ubah_ekskul", "extracurriculars", ekskul_id, values.get("nama"))
        return ekskul_id

    columns = list(values.keys())
    placeholders = ", ".join("?" for _ in columns)
    new_id = db.insert_returning_id(
        f"INSERT INTO extracurriculars({', '.join(columns)}) VALUES({placeholders})",
        [values[key] for key in columns],
    )
    log_audit(actor, None, "tambah_ekskul", "extracurriculars", new_id, values.get("nama"))
    return new_id


def delete_ekskul(ekskul_id: int, actor: str | None = None) -> None:
    ekskul = get_ekskul(ekskul_id)
    db.execute("DELETE FROM extracurriculars WHERE id = ?", (ekskul_id,))
    if ekskul:
        log_audit(actor, None, "hapus_ekskul", "extracurriculars", ekskul_id, ekskul.get("nama"))


#: Pilihan nilai ekstrakurikuler (huruf) sesuai permintaan sekolah.
EKSKUL_NILAI = ("A", "B", "C", "D")


def cari_siswa_ekskul(teks: str) -> tuple[dict[str, Any] | None, str]:
    """Cari siswa untuk dimasukkan ke ekskul.

    Menerima **NISN** (angka) atau **nama** siswa. Bila nama yang diketik cocok
    dengan lebih dari satu siswa, kembalikan pesan agar NISN yang dipakai.
    """
    teks = (teks or "").strip()
    if not teks:
        return None, "Masukkan NISN atau nama siswa."
    angka = "".join(karakter for karakter in teks if karakter.isdigit())
    if len(angka) >= 8:
        siswa = get_student_by_nisn(angka)
        if siswa is None:
            return None, f"NISN {angka} tidak terdaftar di sekolah ini."
        return siswa, ""
    baris = db.rows_to_dicts(
        db.query_all(
            "SELECT * FROM students WHERE LOWER(nama) LIKE ? ORDER BY nama COLLATE NOCASE LIMIT 6",
            (f"%{teks.lower()}%",),
        )
    )
    if not baris:
        return None, f"Siswa dengan nama \"{teks}\" tidak ditemukan. Gunakan NISN bila ada nama kembar."
    if len(baris) > 1:
        daftar = ", ".join(f"{item['nama']} ({item['nisn']})" for item in baris[:3])
        return None, f"Ada {len(baris)} siswa bernama serupa: {daftar}. Tuliskan NISN-nya."
    return baris[0], ""


def pilihan_siswa_ekskul(limit: int = 1200) -> list[dict[str, Any]]:
    """Daftar siswa untuk saran isian (datalist) di halaman ekskul."""
    return db.rows_to_dicts(
        db.query_all(
            "SELECT nisn, nama, rombel FROM students WHERE nisn IS NOT NULL AND nisn <> '' "
            "ORDER BY nama COLLATE NOCASE LIMIT ?",
            (limit,),
        )
    )


def cari_siswa_cepat(ekskul_id: int, rombel: str = "", cari: str = "",
                     batas: int = 25) -> list[dict[str, Any]]:
    """Cari siswa untuk dijadikan anggota ekskul: per kelas dan/atau nama/NISN.

    Dipakai halaman ekskul pada bagian "Cari cepat siswa" — pembina/pelatih
    sering hanya tahu kelasnya, bukan NISN-nya. Siswa yang sudah menjadi
    anggota ditandai ``sudah_anggota`` supaya tidak ditambahkan dua kali.
    """
    rombel = (rombel or "").strip()[:20]
    cari = (cari or "").strip()[:60]
    if not rombel and not cari:
        return []
    syarat: list[str] = []
    nilai: list[Any] = [ekskul_id]  # untuk EXISTS pada SELECT
    if rombel:
        syarat.append("s.rombel = ?")
        nilai.append(rombel)
    if cari:
        if cari.isdigit():
            syarat.append("s.nisn LIKE ?")
            nilai.append(f"{cari}%")
        else:
            syarat.append("LOWER(s.nama) LIKE ?")
            nilai.append(f"%{cari.lower()}%")
    nilai.append(batas)
    sql = (
        "SELECT s.id, s.nisn, s.nama, s.rombel, s.jk, "
        "(SELECT COUNT(*) FROM ekskul_members m WHERE m.student_id = s.id AND m.ekskul_id = ?) "
        "  AS sudah_anggota "
        "FROM students s WHERE " + " AND ".join(syarat) +
        " ORDER BY s.rombel COLLATE NOCASE, s.nama COLLATE NOCASE LIMIT ?"
    )
    return db.rows_to_dicts(db.query_all(sql, tuple(nilai)))


def ekskul_members(ekskul_id: int) -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all(
            """
            SELECT m.*, COALESCE(m.catatan, '') AS catatan, s.nama, s.nisn, s.rombel, s.tingkat, s.jk
              FROM ekskul_members m
              JOIN students s ON s.id = m.student_id
             WHERE m.ekskul_id = ?
             ORDER BY m.status, s.rombel, s.nama COLLATE NOCASE
            """,
            (ekskul_id,),
        )
    )


def add_ekskul_member(ekskul_id: int, student_id: int, *, jabatan: str = "Anggota",
                      tahun_ajaran: str | None = None, semester: str | None = None,
                      actor: str | None = None) -> int | None:
    profile = school_profile()
    tahun_ajaran = tahun_ajaran or profile["tahun_ajaran"]
    semester = semester or profile["semester"]
    existing = db.query_one(
        "SELECT id FROM ekskul_members WHERE ekskul_id = ? AND student_id = ? AND tahun_ajaran = ?",
        (ekskul_id, student_id, tahun_ajaran),
    )
    if existing:
        return None
    member_id = db.insert_returning_id(
        """
        INSERT INTO ekskul_members(ekskul_id, student_id, jabatan, tahun_ajaran, semester)
        VALUES(?,?,?,?,?)
        """,
        (ekskul_id, student_id, jabatan, tahun_ajaran, semester),
    )
    log_audit(actor, None, "tambah_anggota_ekskul", "ekskul_members", member_id, f"ekskul={ekskul_id}")
    return member_id


def remove_ekskul_member(member_id: int, actor: str | None = None) -> None:
    db.execute("DELETE FROM ekskul_members WHERE id = ?", (member_id,))
    log_audit(actor, None, "hapus_anggota_ekskul", "ekskul_members", member_id)


def update_ekskul_member(member_id: int, data: dict[str, Any], actor: str | None = None) -> None:
    allowed = {
        key: value for key, value in data.items()
        if key in {"jabatan", "nilai", "predikat", "status", "catatan"}
    }
    if not allowed:
        return
    set_clause = ", ".join(f"{key} = ?" for key in allowed)
    db.execute(f"UPDATE ekskul_members SET {set_clause} WHERE id = ?", [*allowed.values(), member_id])
    log_audit(actor, None, "ubah_anggota_ekskul", "ekskul_members", member_id)


def student_ekskul(student_id: int) -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all(
            """
            SELECT e.nama, e.hari, e.jam_mulai, e.jam_selesai, e.pembina, e.pelatih,
                   m.jabatan, m.status, m.predikat, m.nilai, m.catatan, m.tahun_ajaran
              FROM ekskul_members m
              JOIN extracurriculars e ON e.id = m.ekskul_id
             WHERE m.student_id = ?
             ORDER BY e.nama COLLATE NOCASE
            """,
            (student_id,),
        )
    )


def ekskul_stats() -> dict[str, Any]:
    total = int(db.query_value("SELECT COUNT(*) FROM extracurriculars") or 0)
    aktif = int(db.query_value("SELECT COUNT(*) FROM extracurriculars WHERE aktif = 1") or 0)
    anggota = int(db.query_value("SELECT COUNT(*) FROM ekskul_members WHERE status = 'aktif'") or 0)
    siswa_ikut = int(db.query_value("SELECT COUNT(DISTINCT student_id) FROM ekskul_members") or 0)
    tanpa_pendamping = int(db.query_value(
        "SELECT COUNT(*) FROM extracurriculars WHERE COALESCE(pembina,'') = '' "
        "AND COALESCE(pelatih,'') = ''"
    ) or 0)
    return {"total": total, "aktif": aktif, "anggota": anggota, "siswa_ikut": siswa_ikut,
            "tanpa_pendamping": tanpa_pendamping}


def ekskul_ringkas(limit: int = 6) -> list[dict[str, Any]]:
    """Ekskul dengan anggota terbanyak (dipakai dasbor & laporan)."""
    return db.rows_to_dicts(
        db.query_all(
            """
            SELECT e.id, e.nama, e.pembina, e.pelatih, e.hari,
                   (SELECT COUNT(*) FROM ekskul_members m
                     WHERE m.ekskul_id = e.id AND m.status = 'aktif') AS jumlah_anggota
              FROM extracurriculars e
             WHERE e.aktif = 1
             ORDER BY jumlah_anggota DESC, e.nama COLLATE NOCASE
             LIMIT ?
            """,
            (limit,),
        )
    )


# =========================================================================== #
# BOT DAPODIK (kerangka kerja)
# =========================================================================== #
def list_dapodik_jobs(limit: int = 20) -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all("SELECT * FROM dapodik_jobs ORDER BY id DESC LIMIT ?", (limit,))
    )


def create_dapodik_job(jenis: str, mode: str, payload: dict[str, Any] | None = None,
                       actor: str | None = None) -> int:
    job_id = db.insert_returning_id(
        "INSERT INTO dapodik_jobs(jenis, mode, payload_json, created_by) VALUES(?,?,?,?)",
        (jenis, mode, json.dumps(payload or {}, ensure_ascii=False), actor),
    )
    log_audit(actor, None, "buat_job_dapodik", "dapodik_jobs", job_id, f"{jenis}/{mode}")
    return job_id


def dapodik_readiness() -> dict[str, Any]:
    """Ringkasan kesiapan data untuk sinkronisasi ke Dapodik."""
    quality = data_quality()
    return {
        "total": quality["total"],
        "siap": quality["siap_sinkron"],
        "perlu_perbaikan": quality["belum_lengkap"],
        "temuan": quality["temuan"],
        "api_key": get_setting("api_key"),
        "sync_aktif": get_setting("dapodik_sync_aktif", "0") == "1",
    }


# =========================================================================== #
# SEED DATA CONTOH
# =========================================================================== #
#: Contoh kegiatan untuk pemasangan baru yang belum punya data ekskul sama sekali.
#: Nama pembina/pelatih di bawah ini contoh — dapat diganti di menu Ekstrakurikuler.
EKSKUL_SEED = [
    ("OSIS", "Budi Hartono, S.Pd", "Rina Puspita, S.Pd", "Sabtu", "08:00", "10:00"),
    ("PRAMUKA", "Hendra Gunawan, S.Pd", "Agus Setiawan", "Jumat", "14:00", "16:30"),
    ("PMR", "Siti Rohmah, S.Pd", "Dewi Lestari, A.Md.Kep", "Jumat", "14:00", "16:00"),
    ("FUTSAL", "Agus Setiawan, S.Pd", "Bayu Nugroho", "Selasa", "15:00", "17:00"),
    ("BASKET", "Rina Marlina, S.Pd", "Rizky Pratama", "Rabu", "15:00", "17:00"),
    ("ROHIS", "Ahmad Fauzi, S.Ag", "Umar Hakim", "Kamis", "14:00", "15:30"),
]


def seed_ekskul_if_empty() -> int:
    existing = int(db.query_value("SELECT COUNT(*) FROM extracurriculars") or 0)
    if existing:
        return 0
    count = 0
    for nama, pembina, pelatih, hari, mulai, selesai in EKSKUL_SEED:
        db.execute(
            """
            INSERT INTO extracurriculars(nama, pembina, pelatih, hari, jam_mulai, jam_selesai, deskripsi)
            VALUES(?,?,?,?,?,?,?)
            """,
            (nama, pembina, pelatih, hari, mulai, selesai, f"Ekstrakurikuler {nama}"),
        )
        count += 1
    return count


def find_sample_files() -> list[Path]:
    """Cari berkas contoh Dapodik di repo (untuk pengisian data awal)."""
    if not config.SAMPLE_DIR.exists():
        return []
    files: list[Path] = []
    for pattern in ("*.xlsx", "*.xls", "*.csv"):
        files.extend(sorted(config.SAMPLE_DIR.glob(pattern)))
    return files


def auto_seed_sample(nisn_example: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Impor otomatis berkas contoh bila database masih kosong."""
    if not config.AUTO_SEED:
        return None
    total = int(db.query_value("SELECT COUNT(*) FROM students") or 0)
    if total:
        return None
    samples = find_sample_files()
    if not samples:
        return None
    path = samples[0]
    try:
        sheets = read_spreadsheet(path, path.suffix.lower())
        sheet = sheets[0]
        from .dapodik import parse_sheet

        parsed = parse_sheet(sheet)
        if parsed.kind != "daftar_peserta_didik":
            return None
        stored = StoredFile(path=path, filename=path.name, size=path.stat().st_size, extension=path.suffix.lower())
        import_id = create_import(
            stored,
            sheet=sheet,
            parsed=parsed,
            fmt=format_label(path.suffix.lower()),
            actor="sistem",
            mode="upsert",
        )
        result = import_students(parsed, import_id=import_id, mode="upsert",
                                 actor="sistem", source_file=path.name)
        seed_ekskul_if_empty()
        log_audit("sistem", "admin", "impor_otomatis", "imports", import_id,
                  f"{result.imported} siswa dari {path.name}")
        return {"file": path.name, "imported": result.imported, "updated": result.updated,
                "import_id": import_id, "rows": len(parsed.records)}
    except Exception as exc:  # noqa: BLE001
        log.warning("Gagal impor otomatis berkas contoh: %s", exc)
        return None


# =========================================================================== #
# ATURAN DATA KELUARGA (ayah, ibu, wali)
# =========================================================================== #
# ATURAN DATA KELUARGA (ayah, ibu, wali)
# =========================================================================== #
def _nama_normal(nilai: Any) -> str:
    """Rapikan nama untuk pembandingan: huruf kecil, spasi ganda disatukan."""
    return " ".join(str(nilai or "").split()).casefold()


def alasan_wali_dihapus(data: dict[str, Any]) -> str:
    """Kembalikan alasan data wali harus dihapus otomatis ('' bila tidak perlu).

    Aturan sistem (tanpa perlu persetujuan siapa pun):

    * nama ayah sudah diisi -> siswa dianggap tidak memiliki wali;
    * nama wali sama dengan nama ayah/ibu -> itu sebenarnya data ayah/ibu;
    * kolom wali terisi tetapi nama wali kosong.
    """
    ayah = _nama_normal(data.get("ayah_nama"))
    ibu = _nama_normal(data.get("ibu_nama"))
    wali = _nama_normal(data.get("wali_nama"))
    ada_isi_lain = any(
        str(data.get(key) or "").strip() for key in FIELD_WALI if key != "wali_nama"
    )

    if not wali and not ada_isi_lain:
        return ""
    if wali and wali in {ayah, ibu} - {""}:
        return "nama wali sama dengan nama ayah/ibu"
    if ayah:
        return "nama ayah sudah diisi sehingga siswa dianggap tidak memiliki wali"
    if not wali and ada_isi_lain:
        return "kolom wali terisi tetapi nama wali kosong"
    return ""


def normalisasi_wali(data: dict[str, Any], siswa: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hapus otomatis data wali pada ``data`` bila tidak sesuai aturan.

    Mengembalikan dict berisi kolom wali yang dikosongkan (siap dipakai sebagai
    nilai baru) beserta alasannya pada kunci ``__alasan__``.
    """
    gabungan = {**(siswa or {}), **{k: v for k, v in data.items() if k in FIELD_BY_KEY}}
    alasan = alasan_wali_dihapus(gabungan)
    if not alasan:
        return {}
    kosong = {key: None for key in FIELD_WALI}
    kosong["__alasan__"] = alasan
    return kosong


def validasi_keluarga(nilai: dict[str, Any], siswa: dict[str, Any] | None = None) -> None:
    """Aturan yang tidak boleh dilanggar saat menyimpan data siswa.

    Hanya satu yang dihentikan: **nama ayah tidak boleh sama dengan nama ibu**.
    Untuk data wali, sistem membersihkannya otomatis (lihat ``normalisasi_wali``),
    jadi tidak perlu persetujuan atau penolakan.
    """
    lama = siswa or {}
    ayah = _nama_normal(nilai.get("ayah_nama", lama.get("ayah_nama")))
    ibu = _nama_normal(nilai.get("ibu_nama", lama.get("ibu_nama")))
    menyentuh_nama = {"ayah_nama", "ibu_nama"} & set(nilai)
    if menyentuh_nama and ayah and ibu and ayah == ibu:
        raise ValueError(
            "Nama ayah dan nama ibu tidak boleh sama. Mohon periksa kembali penulisan "
            "kedua nama tersebut."
        )


def bersihkan_wali_siswa(student_id: int, aktor: str, sumber: str = "sistem") -> list[tuple[str, Any, Any]]:
    """Hapus data wali seorang siswa bila tidak sesuai aturan (dipakai pembersihan)."""
    siswa = get_student(student_id)
    if siswa is None:
        return []
    kosong = normalisasi_wali({}, siswa)
    if not kosong:
        return []
    alasan = kosong.pop("__alasan__")
    perubahan = update_student(student_id, kosong, actor=aktor, source=sumber)
    if perubahan:
        log_audit(aktor, "admin", "hapus_wali_otomatis", "students", student_id,
                  f"{siswa.get('nama')} — {alasan}")
    return perubahan


def siswa_perlu_bersih_wali() -> list[dict[str, Any]]:
    """Daftar siswa yang data walinya akan dihapus otomatis oleh sistem."""
    hasil: list[dict[str, Any]] = []
    for row in db.rows_to_dicts(db.query_all("SELECT * FROM students ORDER BY id")):
        alasan = alasan_wali_dihapus(row)
        if alasan:
            hasil.append({"id": int(row["id"]), "nama": row.get("nama"),
                          "nisn": row.get("nisn"), "rombel": row.get("rombel"),
                          "wali_nama": row.get("wali_nama"), "alasan": alasan})
    return hasil


def rapikan_wali_otomatis(aktor: str) -> dict[str, Any]:
    """Bersihkan data wali semua siswa yang tidak sesuai aturan (satu klik petugas)."""
    daftar = siswa_perlu_bersih_wali()
    berubah = 0
    for item in daftar:
        if bersihkan_wali_siswa(item["id"], aktor):
            berubah += 1
    return {"diperiksa": len(daftar), "dibersihkan": berubah}


# =========================================================================== #
# DOKUMEN SISWA (akta kelahiran, kartu keluarga, ijazah)
# =========================================================================== #
DOKUMEN_JENIS: tuple[tuple[str, str, str], ...] = (
    ("akta_lahir", "Akta Kelahiran", "Foto/scan akta kelahiran yang terbaca jelas."),
    ("kk", "Kartu Keluarga", "Foto/scan kartu keluarga (KK) terbaru."),
    ("ijazah", "Ijazah / SKL", "Foto/scan ijazah SD/MI atau surat keterangan lulus."),
)
DOKUMEN_LABEL: dict[str, str] = {key: label for key, label, _ in DOKUMEN_JENIS}
DOKUMEN_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf"}


def dokumen_jenis_valid(jenis: str) -> bool:
    return jenis in DOKUMEN_LABEL


def validasi_dokumen(jenis: str, nama_asli: str, content: bytes) -> str:
    """Periksa berkas pendukung sebelum disimpan. Mengembalikan ekstensi yang sah."""
    if not dokumen_jenis_valid(jenis):
        raise ValueError("Jenis berkas tidak dikenal.")
    if not content:
        raise ValueError("Berkas kosong.")
    if len(content) > config.DOKUMEN_MAX_BYTES:
        raise ValueError(f"Ukuran berkas melebihi {config.DOKUMEN_MAX_MB} MB.")
    asli = Path(nama_asli or "berkas").name
    ext = Path(asli).suffix.lower()
    if ext not in DOKUMEN_EXT:
        raise ValueError(
            "Format berkas harus gambar (JPG/PNG/WebP) atau PDF: " + (asli or "tanpa nama")
        )
    return ext


def simpan_dokumen(student_id: int, jenis: str, nama_asli: str, content: bytes, *,
                   aktor: str | None = None, request_id: int | None = None) -> int:
    """Simpan berkas pendukung siswa dan catat di tabel student_documents."""
    ext = validasi_dokumen(jenis, nama_asli, content)
    asli = Path(nama_asli or "berkas").name

    folder = config.DOKUMEN_DIR / str(student_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    aman = re.sub(r"[^\w.\- ]+", "_", Path(asli).stem).strip() or "berkas"
    nama_simpan = f"{jenis}__{stamp}__{aman[:60]}{ext}"
    (folder / nama_simpan).write_bytes(content)

    doc_id = db.insert_returning_id(
        """
        INSERT INTO student_documents(student_id, jenis, nama_asli, nama_simpan,
                                      ukuran, tipe, request_id, status)
        VALUES(?,?,?,?,?,?,?,'menunggu')
        """,
        (student_id, jenis, asli, f"{student_id}/{nama_simpan}", len(content),
         content[:4].hex(), request_id),
    )
    log_audit(aktor, None, "unggah_dokumen", "student_documents", doc_id,
              f"{DOKUMEN_LABEL[jenis]} untuk siswa {student_id}")
    return doc_id


def path_dokumen(row: dict[str, Any]) -> Path:
    return config.DOKUMEN_DIR / str(row.get("nama_simpan") or "")


def daftar_dokumen(student_id: int) -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all(
            "SELECT * FROM student_documents WHERE student_id = ? ORDER BY id DESC",
            (student_id,),
        )
    )


def dokumen_terbaru(student_id: int) -> dict[str, dict[str, Any]]:
    """Berkas terbaru per jenis (mengabaikan yang sudah ditolak admin)."""
    hasil: dict[str, dict[str, Any]] = {}
    for row in daftar_dokumen(student_id):
        if row["status"] == "ditolak":
            continue
        hasil.setdefault(row["jenis"], row)
    return hasil


def dokumen_lengkap(student_id: int) -> tuple[bool, list[str]]:
    """Cek kelengkapan tiga berkas wajib. Mengembalikan (lengkap, jenis yang kurang)."""
    ada = dokumen_terbaru(student_id)
    kurang = [label for key, label, _ in DOKUMEN_JENIS if key not in ada]
    return (not kurang), kurang


def ambil_dokumen(doc_id: int) -> dict[str, Any] | None:
    return db.row_to_dict(db.query_one("SELECT * FROM student_documents WHERE id = ?", (doc_id,)))


def periksa_dokumen(doc_id: int, status: str, aktor: str, catatan: str | None = None) -> None:
    if status not in {"menunggu", "diterima", "ditolak"}:
        raise ValueError("Status berkas tidak dikenal.")
    db.execute(
        """
        UPDATE student_documents
           SET status = ?, catatan = ?, diperiksa_at = datetime('now','localtime'), diperiksa_oleh = ?
         WHERE id = ?
        """,
        (status, catatan, aktor, doc_id),
    )
    log_audit(aktor, "admin", f"dokumen_{status}", "student_documents", doc_id, catatan)


def hapus_dokumen(doc_id: int, aktor: str | None = None) -> None:
    row = ambil_dokumen(doc_id)
    if row is None:
        return
    try:
        path_dokumen(row).unlink(missing_ok=True)
    except OSError:  # pragma: no cover - berkas mungkin sudah hilang
        pass
    db.execute("DELETE FROM student_documents WHERE id = ?", (doc_id,))
    log_audit(aktor, "admin", "hapus_dokumen", "student_documents", doc_id, row.get("nama_asli"))


# =========================================================================== #
# PENGAJUAN PERUBAHAN DATA (siswa mengusulkan, admin memutuskan)
# =========================================================================== #
#: Semua kolom Dapodik boleh diusulkan diubah siswa, kecuali NISN.
FIELD_DAPAT_DIAJUKAN: tuple[str, ...] = tuple(
    spec.key for spec in STUDENT_FIELDS if spec.key != "nisn"
)
#: Field yang hanya boleh diubah petugas (bukan lewat pengajuan siswa).
FIELD_HANYA_PETUGAS: tuple[str, ...] = ("nisn", "status")


def field_dapat_diajukan(key: str) -> bool:
    return key in FIELD_DAPAT_DIAJUKAN


def _pengajuan_dari_row(row: Any) -> dict[str, Any] | None:
    data = db.row_to_dict(row)
    if data is None:
        return None
    data["items"] = db.rows_to_dicts(
        db.query_all(
            "SELECT * FROM change_request_items WHERE request_id = ? ORDER BY id",
            (data["id"],),
        )
    )
    data["dokumen"] = db.rows_to_dicts(
        db.query_all(
            "SELECT * FROM student_documents WHERE request_id = ? ORDER BY id",
            (data["id"],),
        )
    )
    return data


def pengajuan_dokumen_wajib() -> bool:
    return (get_setting("pengajuan_wajib_dokumen") or "1") == "1"


def pengajuan_aktif() -> bool:
    return (get_setting("pengajuan_aktif") or "1") == "1"


def ajukan_perubahan(student_id: int, nilai: dict[str, Any], *, catatan: str = "",
                     aktor: str | None = None, ip: str | None = None,
                     dokumen: dict[str, tuple[str, bytes]] | None = None) -> dict[str, Any]:
    """Buat pengajuan perubahan data. Mengembalikan ringkasan pengajuan.

    ``nilai`` hanya berisi kolom yang benar-benar berubah; ``dokumen`` opsional
    berisi berkas baru {jenis: (nama_asli, isi)} yang ikut diunggah.
    """
    if not pengajuan_aktif():
        raise ValueError("Pengajuan perubahan data sedang dinonaktifkan sekolah.")

    siswa = get_student(student_id)
    if siswa is None:
        raise ValueError("Data siswa tidak ditemukan.")

    perubahan: dict[str, Any] = {}
    for key, baru in nilai.items():
        if key in FIELD_HANYA_PETUGAS or not field_dapat_diajukan(key):
            continue
        teks_baru = "" if baru is None else str(baru).strip()
        teks_lama = "" if siswa.get(key) is None else str(siswa.get(key)).strip()
        if teks_baru != teks_lama:
            perubahan[key] = baru

    # Aturan pengisian data ayah/ibu/wali diperiksa sebelum pengajuan dibuat.
    validasi_keluarga(perubahan, siswa)

    # Pengisian data wali yang melanggar aturan tidak ikut diajukan — sistem
    # yang membersihkan, bukan admin yang menolak.
    catatan_sistem = ""
    if set(FIELD_WALI) & set(perubahan):
        alasan = alasan_wali_dihapus({**siswa, **perubahan})
        ada_pengisian = any(str(perubahan.get(key) or "").strip() for key in FIELD_WALI)
        if alasan and ada_pengisian:
            perubahan = {key: nilai for key, nilai in perubahan.items() if key not in FIELD_WALI}
            catatan_sistem = f"Data wali tidak ikut disimpan karena {alasan}."
            if not perubahan and not dokumen:
                raise ValueError(
                    f"Data wali tidak dapat disimpan karena {alasan}. "
                    "Isi/ubah kolom ayah atau ibu, atau biarkan kolom wali kosong."
                )

    if not perubahan and not dokumen:
        raise ValueError("Tidak ada data yang berubah, jadi belum ada yang diajukan.")

    # Berkas yang ikut diunggah harus lolos pemeriksaan sebelum pengajuan dibuat.
    diunggah = dict(dokumen or {})
    for jenis, (nama_asli, isi) in diunggah.items():
        validasi_dokumen(jenis, nama_asli, isi)

    # Penghapusan data wali diproses sistem saat itu juga: tidak perlu
    # persetujuan admin dan tidak perlu melampirkan berkas.
    hanya_hapus_wali = bool(perubahan) and all(
        key in FIELD_WALI and not str(nilai_baru or "").strip()
        for key, nilai_baru in perubahan.items()
    )

    # Tiga berkas wajib (akta kelahiran, KK, ijazah) harus ada — baru diunggah
    # sekarang atau sudah tersimpan dari pengajuan sebelumnya.
    if pengajuan_dokumen_wajib() and not hanya_hapus_wali:
        tersedia = set(dokumen_terbaru(student_id)) | set(diunggah)
        kurang = [label for key, label, _ in DOKUMEN_JENIS if key not in tersedia]
        if kurang:
            raise ValueError(
                "Berkas wajib belum lengkap: " + ", ".join(kurang) +
                ". Unggah foto akta kelahiran, kartu keluarga, dan ijazah lebih dahulu."
            )

    sudah_lengkap, _kurang_awal = dokumen_lengkap(student_id)
    request_id = db.insert_returning_id(
        """
        INSERT INTO change_requests(student_id, nisn, nama, rombel, status, catatan_siswa,
                                    jumlah_field, dokumen_lengkap, ip)
        VALUES(?,?,?,?,'menunggu',?,?,?,?)
        """,
        (student_id, siswa.get("nisn"), siswa.get("nama"), siswa.get("rombel"), catatan or None,
         len(perubahan), 1 if (sudah_lengkap or diunggah) else 0, ip),
    )

    with db.transaction() as conn:
        for key, baru in perubahan.items():
            spec = FIELD_BY_KEY.get(key)
            conn.execute(
                """
                INSERT INTO change_request_items(request_id, field, label, nilai_lama, nilai_baru)
                VALUES(?,?,?,?,?)
                """,
                (request_id, key, spec.label if spec else field_label_aman(key),
                 _text(siswa.get(key)), _text(baru)),
            )

    for jenis, (nama_asli, isi) in (dokumen or {}).items():
        simpan_dokumen(student_id, jenis, nama_asli, isi, aktor=aktor, request_id=request_id)

    if hanya_hapus_wali:
        # Sistem langsung menerapkan penghapusan data wali (tanpa persetujuan).
        putuskan_pengajuan(request_id, True, aktor="sistem",
                           catatan="Data wali dihapus otomatis oleh sistem.")
        hasil = ambil_pengajuan(request_id) or {}
        hasil["catatan_sistem"] = "Data wali dihapus otomatis oleh sistem."
        return hasil

    lengkap, kurang = dokumen_lengkap(student_id)
    db.execute(
        "UPDATE change_requests SET dokumen_lengkap = ? WHERE id = ?",
        (1 if lengkap else 0, request_id),
    )
    log_audit(aktor, "siswa", "ajukan_perubahan", "change_requests", request_id,
              f"{len(perubahan)} kolom; dokumen {'lengkap' if lengkap else 'kurang: ' + ', '.join(kurang)}")
    hasil = ambil_pengajuan(request_id) or {}
    hasil["catatan_sistem"] = catatan_sistem
    return hasil


def field_label_aman(key: str) -> str:
    spec = FIELD_BY_KEY.get(key)
    return spec.label if spec else key.replace("_", " ").title()


def ambil_pengajuan(request_id: int) -> dict[str, Any] | None:
    data = _pengajuan_dari_row(
        db.query_one("SELECT * FROM change_requests WHERE id = ?", (request_id,))
    )
    if data is None:
        return None
    data["siswa"] = get_student(int(data["student_id"]))
    data["dokumen_siswa"] = dokumen_terbaru(int(data["student_id"]))
    return data


def daftar_pengajuan(status: str | None = None, q: str | None = None,
                     limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    klausa, params = [], []
    if status and status != "semua":
        klausa.append("r.status = ?")
        params.append(status)
    if q:
        klausa.append("(r.nama LIKE ? OR r.nisn LIKE ? OR r.rombel LIKE ?)")
        pola = f"%{q.strip()}%"
        params.extend([pola, pola, pola])
    where = f"WHERE {' AND '.join(klausa)}" if klausa else ""
    return db.rows_to_dicts(
        db.query_all(
            f"""
            SELECT r.*, (SELECT COUNT(*) FROM change_request_items i WHERE i.request_id = r.id) AS item_count,
                   (SELECT COUNT(*) FROM student_documents d WHERE d.request_id = r.id) AS dokumen_count
              FROM change_requests r
              {where}
             ORDER BY CASE r.status WHEN 'menunggu' THEN 0 ELSE 1 END, r.id DESC
             LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        )
    )


def hitung_pengajuan(status: str | None = None) -> int:
    if status:
        return int(db.query_value("SELECT COUNT(*) FROM change_requests WHERE status = ?", (status,)) or 0)
    return int(db.query_value("SELECT COUNT(*) FROM change_requests") or 0)


def statistik_pengajuan() -> dict[str, int]:
    return {
        "menunggu": hitung_pengajuan("menunggu"),
        "disetujui": hitung_pengajuan("disetujui"),
        "ditolak": hitung_pengajuan("ditolak"),
        "total": hitung_pengajuan(),
    }


def pengajuan_siswa(student_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Pengajuan milik seorang siswa, lengkap dengan rincian kolom yang diusulkan."""
    rows = db.rows_to_dicts(
        db.query_all(
            """
            SELECT r.*, (SELECT COUNT(*) FROM change_request_items i WHERE i.request_id = r.id) AS item_count
              FROM change_requests r
             WHERE r.student_id = ?
             ORDER BY r.id DESC LIMIT ?
            """,
            (student_id, limit),
        )
    )
    for row in rows:
        row["items"] = db.rows_to_dicts(
            db.query_all(
                "SELECT field, label, nilai_lama, nilai_baru FROM change_request_items WHERE request_id = ? ORDER BY id",
                (row["id"],),
            )
        )
    return rows


def putuskan_pengajuan(request_id: int, terima: bool, aktor: str, catatan: str = "") -> dict[str, Any]:
    """Setujui atau tolak pengajuan. Bila disetujui, data siswa langsung diperbarui."""
    pengajuan = ambil_pengajuan(request_id)
    if pengajuan is None:
        raise ValueError("Pengajuan tidak ditemukan.")
    if pengajuan["status"] != "menunggu":
        raise ValueError(f"Pengajuan ini sudah diputuskan ({pengajuan['status']}).")

    student_id = int(pengajuan["student_id"])
    jumlah = 0
    if terima:
        nilai = {item["field"]: item["nilai_baru"] for item in pengajuan["items"]}
        nilai = {key: (None if value in (None, "") else value) for key, value in nilai.items()}
        for sumber, flag in (("penerima_kps", "is_kps"), ("penerima_kip", "is_kip"),
                             ("layak_pip", "is_layak_pip")):
            if sumber in nilai:
                nilai[flag] = 1 if str(nilai[sumber] or "").strip().lower().startswith("ya") else 0
        perubahan = update_student(student_id, nilai, actor=aktor, source="pengajuan_siswa")
        jumlah = len(perubahan)
        # Bukti yang dipakai saat menyetujui ikut ditandai diterima: berkas pada
        # pengajuan ini dan berkas terbaru tiap jenis yang jadi rujukan admin.
        for dokumen in pengajuan["dokumen"]:
            periksa_dokumen(int(dokumen["id"]), "diterima", aktor)
        for dokumen in dokumen_terbaru(student_id).values():
            periksa_dokumen(int(dokumen["id"]), "diterima", aktor)

    if not terima:
        for dokumen in pengajuan["dokumen"]:
            periksa_dokumen(int(dokumen["id"]), "ditolak", aktor, catatan or None)

    db.execute(
        """
        UPDATE change_requests
           SET status = ?, catatan_admin = ?, diputuskan_at = datetime('now','localtime'),
               diputuskan_oleh = ?
         WHERE id = ?
        """,
        ("disetujui" if terima else "ditolak", catatan or None, aktor, request_id),
    )
    log_audit(aktor, "admin", "putuskan_pengajuan" if terima else "tolak_pengajuan",
              "change_requests", request_id,
              f"{pengajuan['nama']} ({pengajuan['nisn']}) — {jumlah} kolom diterapkan")
    hasil = ambil_pengajuan(request_id) or {}
    hasil["jumlah_diterapkan"] = jumlah
    return hasil


def batalkan_pengajuan(request_id: int, aktor: str | None = None) -> None:
    db.execute(
        "UPDATE change_requests SET status = 'dibatalkan' WHERE id = ? AND status = 'menunggu'",
        (request_id,),
    )
    log_audit(aktor, "siswa", "batalkan_pengajuan", "change_requests", request_id)
