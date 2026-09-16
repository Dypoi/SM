"""Skema database & migrasi sederhana berbasis versi.

Setiap perubahan skema ditambahkan sebagai entri baru pada ``MIGRATIONS``.
Migrasi yang sudah pernah dijalankan dicatat di tabel ``schema_migrations``
sehingga aplikasi aman di-update tanpa kehilangan data.
"""

from __future__ import annotations

import logging
from typing import Callable

from . import db
from .security import hash_password

log = logging.getLogger("simsek.migrations")

# --------------------------------------------------------------------------- #
# Daftar migrasi (urut, sekali jalan)
# --------------------------------------------------------------------------- #
MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_skema_awal",
        """
        ---------------------------------------------------------------------
        -- Identitas sekolah / pengaturan aplikasi
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        ---------------------------------------------------------------------
        -- Pengguna aplikasi (admin, operator/guru) & akun siswa (opsional)
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            nama          TEXT,
            role          TEXT NOT NULL DEFAULT 'operator'
                          CHECK (role IN ('admin','operator','siswa')),
            student_id    INTEGER REFERENCES students(id) ON DELETE SET NULL,
            aktif         INTEGER NOT NULL DEFAULT 1,
            last_login    TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime')),
            updated_at    TEXT DEFAULT (datetime('now','localtime'))
        );

        ---------------------------------------------------------------------
        -- Riwayat impor berkas (Excel/CSV)
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS imports (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            filename       TEXT NOT NULL,
            stored_path    TEXT,
            file_ext       TEXT,
            file_size      INTEGER,
            file_format    TEXT,
            sheet_name     TEXT,
            header_row     INTEGER,
            mapping_json   TEXT,
            meta_json      TEXT,
            mode           TEXT NOT NULL DEFAULT 'upsert',
            status         TEXT NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft','running','sukses','gagal','sebagian')),
            rows_total     INTEGER DEFAULT 0,
            rows_imported  INTEGER DEFAULT 0,
            rows_updated   INTEGER DEFAULT 0,
            rows_skipped   INTEGER DEFAULT 0,
            rows_failed    INTEGER DEFAULT 0,
            detected_kind  TEXT,
            message        TEXT,
            created_by     TEXT,
            created_at     TEXT DEFAULT (datetime('now','localtime')),
            finished_at    TEXT
        );

        ---------------------------------------------------------------------
        -- Catatan masalah per baris saat impor
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS import_issues (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id   INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
            row_number  INTEGER,
            level       TEXT NOT NULL DEFAULT 'warning'
                        CHECK (level IN ('error','warning','info')),
            field       TEXT,
            message     TEXT NOT NULL,
            row_json    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_import_issues_import ON import_issues(import_id);

        ---------------------------------------------------------------------
        -- Data peserta didik (mengikuti struktur ekspor Dapodik)
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS students (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            nisn         TEXT UNIQUE,
            nipd         TEXT,
            nama         TEXT NOT NULL,
            jk           TEXT,
            tempat_lahir TEXT,
            tanggal_lahir TEXT,
            nik          TEXT,
            no_kk        TEXT,
            agama        TEXT,
            alamat       TEXT,
            rt           TEXT,
            rw           TEXT,
            dusun        TEXT,
            kelurahan    TEXT,
            kecamatan    TEXT,
            kode_pos     TEXT,
            jenis_tinggal TEXT,
            transportasi TEXT,
            telepon      TEXT,
            hp           TEXT,
            email        TEXT,
            skhun        TEXT,
            penerima_kps TEXT,
            is_kps       INTEGER DEFAULT 0,
            no_kps       TEXT,
            ayah_nama        TEXT,
            ayah_tahun_lahir TEXT,
            ayah_pendidikan  TEXT,
            ayah_pekerjaan   TEXT,
            ayah_penghasilan TEXT,
            ayah_nik         TEXT,
            ibu_nama         TEXT,
            ibu_tahun_lahir  TEXT,
            ibu_pendidikan   TEXT,
            ibu_pekerjaan    TEXT,
            ibu_penghasilan  TEXT,
            ibu_nik          TEXT,
            wali_nama        TEXT,
            wali_tahun_lahir TEXT,
            wali_pendidikan  TEXT,
            wali_pekerjaan   TEXT,
            wali_penghasilan TEXT,
            wali_nik         TEXT,
            rombel       TEXT,
            tingkat      TEXT,
            no_peserta_un TEXT,
            no_seri_ijazah TEXT,
            penerima_kip TEXT,
            is_kip       INTEGER DEFAULT 0,
            nomor_kip    TEXT,
            nama_kip     TEXT,
            nomor_kks    TEXT,
            no_registrasi_akta TEXT,
            bank         TEXT,
            no_rekening  TEXT,
            rekening_atas_nama TEXT,
            layak_pip    TEXT,
            is_layak_pip INTEGER DEFAULT 0,
            alasan_layak_pip TEXT,
            kebutuhan_khusus TEXT,
            sekolah_asal TEXT,
            anak_ke      INTEGER,
            lintang      REAL,
            bujur        REAL,
            berat_badan  REAL,
            tinggi_badan REAL,
            lingkar_kepala REAL,
            jml_saudara  INTEGER,
            jarak_rumah  REAL,
            status       TEXT NOT NULL DEFAULT 'Aktif',
            catatan      TEXT,
            source_file  TEXT,
            import_id    INTEGER REFERENCES imports(id) ON DELETE SET NULL,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            updated_at   TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_students_rombel    ON students(rombel);
        CREATE INDEX IF NOT EXISTS idx_students_tingkat   ON students(tingkat);
        CREATE INDEX IF NOT EXISTS idx_students_nama      ON students(nama);
        CREATE INDEX IF NOT EXISTS idx_students_kelurahan ON students(kelurahan);

        ---------------------------------------------------------------------
        -- Jejak perubahan data (dipakai bot Dapodik untuk audit & rollback)
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS data_changes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER REFERENCES students(id) ON DELETE CASCADE,
            nisn        TEXT,
            field       TEXT NOT NULL,
            old_value   TEXT,
            new_value   TEXT,
            source      TEXT NOT NULL DEFAULT 'manual',
            actor       TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_data_changes_student ON data_changes(student_id);

        ---------------------------------------------------------------------
        -- Ekstrakurikuler
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS extracurriculars (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            kode        TEXT UNIQUE,
            nama        TEXT NOT NULL,
            kategori    TEXT DEFAULT 'Lainnya',
            pembina     TEXT,
            hari        TEXT,
            jam_mulai   TEXT,
            jam_selesai TEXT,
            tempat      TEXT,
            kuota       INTEGER,
            deskripsi   TEXT,
            aktif       INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS ekskul_members (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ekskul_id   INTEGER NOT NULL REFERENCES extracurriculars(id) ON DELETE CASCADE,
            student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            jabatan     TEXT DEFAULT 'Anggota',
            tahun_ajaran TEXT,
            semester    TEXT,
            nilai       REAL,
            predikat    TEXT,
            status      TEXT NOT NULL DEFAULT 'aktif',
            joined_at   TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE (ekskul_id, student_id, tahun_ajaran)
        );
        CREATE INDEX IF NOT EXISTS idx_ekskul_members_ekskul ON ekskul_members(ekskul_id);
        CREATE INDEX IF NOT EXISTS idx_ekskul_members_student ON ekskul_members(student_id);

        ---------------------------------------------------------------------
        -- Antrean pekerjaan bot Dapodik (disiapkan untuk tahap berikutnya)
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS dapodik_jobs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            jenis        TEXT NOT NULL DEFAULT 'validasi',
            mode         TEXT NOT NULL DEFAULT 'dry-run',
            status       TEXT NOT NULL DEFAULT 'menunggu'
                         CHECK (status IN ('menunggu','jalan','sukses','gagal','batal')),
            total_item   INTEGER DEFAULT 0,
            sukses_item  INTEGER DEFAULT 0,
            gagal_item   INTEGER DEFAULT 0,
            payload_json TEXT,
            log          TEXT,
            created_by   TEXT,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            started_at   TEXT,
            finished_at  TEXT
        );

        ---------------------------------------------------------------------
        -- Audit aktivitas pengguna
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            actor      TEXT,
            role       TEXT,
            aksi       TEXT NOT NULL,
            entitas    TEXT,
            entitas_id TEXT,
            detail     TEXT,
            ip         TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
        """,
    ),
]


# --------------------------------------------------------------------------- #
# Seeder
# --------------------------------------------------------------------------- #
def _set_setting(key: str, value: str) -> None:
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        (key, value),
    )


def seed_defaults() -> None:
    """Isi pengaturan awal & akun admin default (hanya sekali)."""
    from . import config

    defaults = {
        "school_nama": "SMP NEGERI 2 TANGERANG",
        "school_npsn": "",
        "school_alamat": "",
        "school_kecamatan": "Kec. Tangerang",
        "school_kabupaten": "Kota Tangerang",
        "school_provinsi": "Banten",
        "school_kepala": "",
        "school_email": "",
        "school_telepon": "",
        "tahun_ajaran": config.TAHUN_AJARAN_DEFAULT,
        "semester": config.SEMESTER_DEFAULT,
        "login_siswa_pakai_tanggal_lahir": "0",
        "ekskul_aktif": "1",
        "dapodik_sync_aktif": "0",
    }
    for key, value in defaults.items():
        _set_setting(key, value)

    existing = db.query_one("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    if existing is None:
        db.execute(
            "INSERT INTO users(username, password_hash, nama, role) VALUES(?,?,?,?)",
            (
                config.DEFAULT_ADMIN_USERNAME,
                hash_password(config.DEFAULT_ADMIN_PASSWORD),
                "Administrator",
                "admin",
            ),
        )
        log.info("Akun admin awal dibuat: %s", config.DEFAULT_ADMIN_USERNAME)

    # Kunci API untuk bot Dapodik (dibuat sekali, bisa dilihat di halaman Pengaturan)
    import secrets

    _set_setting("api_key", secrets.token_urlsafe(32))
    _set_setting("api_key_created_at", "")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def _ensure_migration_table() -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id         TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )


def applied_migrations() -> set[str]:
    _ensure_migration_table()
    return {row["id"] for row in db.query_all("SELECT id FROM schema_migrations")}


def run_migrations(verbose: bool = False) -> list[str]:
    """Jalankan migrasi yang belum pernah diterapkan.

    Catatan: ``Connection.executescript`` milik sqlite3 otomatis menutup
    transaksi yang sedang berjalan, sehingga skrip dijalankan dalam mode
    autocommit dan pencatatan versi dilakukan setelahnya.
    """
    applied = applied_migrations()
    executed: list[str] = []
    connection = db.connection()
    for migration_id, script in MIGRATIONS:
        if migration_id in applied:
            continue
        connection.executescript(script)
        connection.execute("INSERT INTO schema_migrations(id) VALUES(?)", (migration_id,))
        executed.append(migration_id)
        if verbose:
            log.info("Migrasi dijalankan: %s", migration_id)
    seed_defaults()
    return executed


def init_database(verbose: bool = False) -> None:
    """Entry point: pastikan folder ada, jalankan migrasi & seeder."""
    from . import config

    config.ensure_dirs()
    run_migrations(verbose=verbose)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    init_database(verbose=True)
    print(f"Database siap: {__import__('app.config', fromlist=['DB_PATH']).DB_PATH}")
