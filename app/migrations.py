"""Skema database & migrasi sederhana berbasis versi.

Setiap perubahan skema ditambahkan sebagai entri baru pada ``MIGRATIONS``.
Migrasi yang sudah pernah dijalankan dicatat di tabel ``schema_migrations``
sehingga aplikasi aman di-update tanpa kehilangan data.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable

from . import db
from .security import hash_password

log = logging.getLogger("sm.migrations")

# --------------------------------------------------------------------------- #
# Daftar ekstrakurikuler yang dipakai sekolah (nama resmi + kategori)
# --------------------------------------------------------------------------- #
EKSKUL_SEKOLAH: tuple[tuple[str, str], ...] = (
    ("OSIS", "Kepemimpinan"),
    ("BASKET", "Olahraga"),
    ("FUTSAL", "Olahraga"),
    ("HADROH", "Keagamaan"),
    ("MADING", "Akademik"),
    ("PADUAN SUARA", "Seni"),
    ("PASKIBRA", "Kepemimpinan"),
    ("PENCAK SILAT", "Olahraga"),
    ("PMR", "Kepemimpinan"),
    ("PRAMUKA", "Kepemimpinan"),
    ("ROHIS", "Keagamaan"),
    ("TARI", "Seni"),
    ("VOLLY", "Olahraga"),
    ("WUSHU", "Olahraga"),
)


def _kode_ekskul(nama: str) -> str:
    """Kode ringkas dari nama ekskul (maksimal 20 huruf/angka)."""
    return "".join(karakter for karakter in nama.upper() if karakter.isalnum())[:20]


def _migrasi_004(conn: sqlite3.Connection) -> None:
    """Akun ekstrakurikuler (pembina/pelatih dengan NIK 16 digit) + daftar ekskul resmi.

    Satu ekskul hanya boleh punya **satu pembina** dan **satu pelatih**; NIK yang
    masuk pertama kali untuk sebuah posisi langsung terdaftar (dikunci) di posisi
    itu. Admin dapat melepaskannya dari halaman Pengaturan.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ekskul_akun (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ekskul_id       INTEGER NOT NULL REFERENCES extracurriculars(id) ON DELETE CASCADE,
            peran           TEXT NOT NULL,
            nik             TEXT NOT NULL,
            nama            TEXT,
            aktif           INTEGER NOT NULL DEFAULT 1,
            login_terakhir  TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE (ekskul_id, peran),
            UNIQUE (ekskul_id, nik)
        );
        CREATE INDEX IF NOT EXISTS idx_ekskul_akun_ekskul ON ekskul_akun(ekskul_id);
        CREATE INDEX IF NOT EXISTS idx_ekskul_akun_nik ON ekskul_akun(nik);
        """
    )

    # Rapikan/masukkan nama ekskul resmi sekolah tanpa mengganggu ekskul lain
    # yang sudah ada (mis. tambahan dari sekolah).
    for nama, kategori in EKSKUL_SEKOLAH:
        baris = conn.execute(
            """
            SELECT id FROM extracurriculars
             WHERE UPPER(TRIM(nama)) = ?
                OR UPPER(TRIM(COALESCE(kode, ''))) = ?
                OR UPPER(REPLACE(TRIM(COALESCE(kode, '')), ' ', '')) = ?
             ORDER BY id LIMIT 1
            """,
            (nama, nama, nama.replace(" ", "")),
        ).fetchone()
        kode = _kode_ekskul(nama)
        if baris is not None:
            conn.execute(
                "UPDATE extracurriculars SET nama = ?, kode = ?, kategori = COALESCE(NULLIF(kategori, ''), ?),"
                " aktif = 1, updated_at = datetime('now','localtime') WHERE id = ?",
                (nama, kode, kategori, baris[0]),
            )
            continue
        try:
            conn.execute(
                "INSERT INTO extracurriculars (kode, nama, kategori, aktif) VALUES (?, ?, ?, 1)",
                (kode, nama, kategori),
            )
        except sqlite3.IntegrityError:  # kode sudah dipakai baris lain
            conn.execute(
                "INSERT INTO extracurriculars (kode, nama, kategori, aktif) VALUES (NULL, ?, ?, 1)",
                (nama, kategori),
            )
    log.info("Daftar ekskul resmi sekolah disiapkan (%s kegiatan).", len(EKSKUL_SEKOLAH))


def _migrasi_005(conn: sqlite3.Connection) -> None:
    """Sederhanakan modul ekstrakurikuler sesuai permintaan sekolah.

    * Kolom **kode, kategori, tempat, kuota** dibuang (tidak dipakai).
    * Kolom **pelatih** ditambahkan (sebelumnya hanya ada pembina).
    * Kolom **catatan** ditambahkan pada daftar anggota (catatan per siswa).

    Tabel ``extracurriculars`` dibuat ulang karena kolom ``kode`` memakai
    batasan UNIQUE sehingga tidak bisa dibuang langsung oleh SQLite. Kunci asing
    dimatikan sesaat agar data anggota & akun ekskul tetap utuh.
    """
    kolom_member = _kolom_tabel(conn, "ekskul_members")
    if "catatan" not in kolom_member:
        conn.execute("ALTER TABLE ekskul_members ADD COLUMN catatan TEXT")
        log.info("Kolom catatan ditambahkan pada tabel ekskul_members.")

    kolom = _kolom_tabel(conn, "extracurriculars")
    dibuang = [nama for nama in ("kode", "kategori", "tempat", "kuota") if nama in kolom]
    if not dibuang and "pelatih" in kolom:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS extracurriculars_baru (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nama        TEXT NOT NULL,
                pembina     TEXT,
                pelatih     TEXT,
                hari        TEXT,
                jam_mulai   TEXT,
                jam_selesai TEXT,
                deskripsi   TEXT,
                aktif       INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                updated_at  TEXT DEFAULT (datetime('now','localtime'))
            );
            """
        )
        asal = [nama for nama in ("id", "nama", "pembina", "pelatih", "hari", "jam_mulai",
                                  "jam_selesai", "deskripsi", "aktif", "created_at", "updated_at")
                if nama in kolom]
        tujuan = ", ".join(asal)
        conn.execute(
            f"INSERT INTO extracurriculars_baru ({tujuan}) SELECT {tujuan} FROM extracurriculars"
        )
        sebelum = conn.execute("SELECT COUNT(*) FROM extracurriculars").fetchone()[0]
        sesudah = conn.execute("SELECT COUNT(*) FROM extracurriculars_baru").fetchone()[0]
        if sebelum != sesudah:
            raise RuntimeError(f"jumlah ekskul berubah saat disalin ({sebelum} -> {sesudah})")
        conn.execute("DROP TABLE extracurriculars")
        conn.execute("ALTER TABLE extracurriculars_baru RENAME TO extracurriculars")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ekskul_nama ON extracurriculars(nama COLLATE NOCASE)")
    finally:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    log.info("Kolom ekskul dibuang (%s); kolom pelatih & catatan disiapkan.", ", ".join(dibuang) or "-")


# --------------------------------------------------------------------------- #
# Daftar migrasi (urut, sekali jalan)
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Fungsi migrasi Python (dipakai bila perlu logika)
# --------------------------------------------------------------------------- #
def _kolom_tabel(conn: sqlite3.Connection, tabel: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({tabel})")]


def _bersihkan_kolom_tidak_dipakai(conn: sqlite3.Connection) -> None:
    """Buang field yang sudah tidak dipakai: riwayat, temuan, butir pengajuan, kolom.

    Daftarnya diambil dari :data:`app.dapodik.FIELD_DIHAPUS`, jadi penambahan
    kolom yang dihapus cukup dilakukan di satu tempat itu.
    """
    from .dapodik import FIELD_DIHAPUS

    daftar = ",".join("?" * len(FIELD_DIHAPUS))
    conn.execute(f"DELETE FROM data_changes WHERE field IN ({daftar})", FIELD_DIHAPUS)
    conn.execute(f"DELETE FROM import_issues WHERE field IN ({daftar})", FIELD_DIHAPUS)
    # Butir pengajuan siswa yang menunjuk kolom tidak terpakai dibuang; pengajuan
    # yang jadi kosong otomatis dibatalkan supaya tidak menggantung.
    conn.execute(f"DELETE FROM change_request_items WHERE field IN ({daftar})", FIELD_DIHAPUS)
    conn.execute(
        """
        UPDATE change_requests
           SET status = 'dibatalkan',
               catatan_admin = 'Dibatalkan otomatis: kolom yang diajukan sudah tidak dipakai aplikasi.'
         WHERE status = 'menunggu'
           AND id NOT IN (SELECT request_id FROM change_request_items)
        """
    )

    # Buang kolomnya. SQLite 3.35+ mendukung DROP COLUMN; versi lama cukup
    # dikosongkan nilainya (kolom tak terpakai tidak dipakai aplikasi).
    ada = set(_kolom_tabel(conn, "students"))
    target = [kolom for kolom in FIELD_DIHAPUS if kolom in ada]
    if not target:
        return
    if sqlite3.sqlite_version_info >= (3, 35, 0):
        for kolom in target:
            conn.execute(f"ALTER TABLE students DROP COLUMN {kolom}")
        log.info("Kolom tidak terpakai dihapus dari tabel students: %s", ", ".join(target))
    else:
        set_clause = ", ".join(f"{kolom} = NULL" for kolom in target)
        conn.execute(f"UPDATE students SET {set_clause}")
        log.warning(
            "SQLite %s belum mendukung DROP COLUMN; nilai %s dikosongkan.",
            sqlite3.sqlite_version, ", ".join(target),
        )


def _migrasi_002(conn: sqlite3.Connection) -> None:
    """Tabel pengajuan perubahan data siswa + berkas pendukung."""
    conn.executescript(
        """
        ---------------------------------------------------------------------
        -- Pengajuan perubahan data oleh siswa (menunggu persetujuan admin)
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS change_requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            nisn            TEXT,
            nama            TEXT,
            rombel          TEXT,
            status          TEXT NOT NULL DEFAULT 'menunggu'
                            CHECK (status IN ('menunggu','disetujui','ditolak','dibatalkan')),
            catatan_siswa   TEXT,
            catatan_admin   TEXT,
            jumlah_field    INTEGER NOT NULL DEFAULT 0,
            dokumen_lengkap INTEGER NOT NULL DEFAULT 0,
            diajukan_at     TEXT DEFAULT (datetime('now','localtime')),
            diputuskan_at   TEXT,
            diputuskan_oleh TEXT,
            ip              TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pengajuan_status  ON change_requests(status);
        CREATE INDEX IF NOT EXISTS idx_pengajuan_siswa   ON change_requests(student_id);
        CREATE INDEX IF NOT EXISTS idx_pengajuan_diajukan ON change_requests(diajukan_at);

        CREATE TABLE IF NOT EXISTS change_request_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id  INTEGER NOT NULL REFERENCES change_requests(id) ON DELETE CASCADE,
            field       TEXT NOT NULL,
            label       TEXT,
            nilai_lama  TEXT,
            nilai_baru  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pengajuan_item ON change_request_items(request_id);

        ---------------------------------------------------------------------
        -- Berkas pendukung siswa: akta kelahiran, kartu keluarga, ijazah
        ---------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS student_documents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            jenis         TEXT NOT NULL
                          CHECK (jenis IN ('akta_lahir','kk','ijazah')),
            nama_asli     TEXT,
            nama_simpan   TEXT NOT NULL,
            ukuran        INTEGER,
            tipe          TEXT,
            request_id    INTEGER REFERENCES change_requests(id) ON DELETE SET NULL,
            status        TEXT NOT NULL DEFAULT 'menunggu'
                          CHECK (status IN ('menunggu','diterima','ditolak')),
            catatan       TEXT,
            diunggah_at   TEXT DEFAULT (datetime('now','localtime')),
            diperiksa_at  TEXT,
            diperiksa_oleh TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dokumen_siswa  ON student_documents(student_id, jenis);
        CREATE INDEX IF NOT EXISTS idx_dokumen_status ON student_documents(status);
        """
    )


def _migrasi_006(conn: sqlite3.Connection) -> None:
    """Pendaftaran ekstrakurikuler oleh siswa (menunggu persetujuan pembina).

    Siswa memilih ekskul yang ingin diikuti dari portalnya; permintaan masuk
    sebagai ``menunggu`` dan baru menjadi anggota setelah pembina/pelatih
    menyetujui. Satu siswa satu baris per ekskul — pengajuan ulang setelah
    ditolak cukup memperbarui baris yang sama.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ekskul_pendaftaran (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ekskul_id       INTEGER NOT NULL REFERENCES extracurriculars(id) ON DELETE CASCADE,
            student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            status          TEXT NOT NULL DEFAULT 'menunggu',
            catatan_siswa   TEXT,
            catatan_pembina TEXT,
            diputus_oleh    TEXT,
            diputus_at      TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pendaftaran_unik
            ON ekskul_pendaftaran(ekskul_id, student_id);
        CREATE INDEX IF NOT EXISTS idx_pendaftaran_status
            ON ekskul_pendaftaran(ekskul_id, status);
        CREATE INDEX IF NOT EXISTS idx_pendaftaran_siswa
            ON ekskul_pendaftaran(student_id, status);
        """
    )
    log.info("Tabel ekskul_pendaftaran siap (pendaftaran ekskul oleh siswa).")

#: Setiap entri: (id_migrasi, skrip SQL) atau (id_migrasi, fungsi(conn)).
Migrasi: Callable[[sqlite3.Connection], None]

MIGRATIONS: list[tuple[str, str | Callable[[sqlite3.Connection], None]]] = [
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

    # ======================================================================= #
    # 002 — Pengajuan perubahan data oleh siswa + berkas pendukung.
    # ======================================================================= #
    (
        "002_pengajuan_perubahan",
        _migrasi_002,
    ),

    # ======================================================================= #
    # 003 — Menghapus kolom yang tidak dipakai lagi (mengikuti FIELD_DIHAPUS:
    #        13 kolom lama + "Kebutuhan Khusus" yang dihapus atas permintaan
    #        sekolah), termasuk membersihkan riwayat & butir pengajuan terkait.
    # ======================================================================= #
    (
        "003_hapus_kolom_tidak_dipakai",
        _bersihkan_kolom_tidak_dipakai,
    ),
    (
        "004_akun_ekskul",
        _migrasi_004,
    ),
    (
        "005_ekskul_sederhana",
        _migrasi_005,
    ),
    (
        "006_pendaftaran_ekskul",
        _migrasi_006,
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
        "pengajuan_aktif": "1",
        "pengajuan_wajib_dokumen": "1",
        "pengajuan_kunci_field": "nisn",
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
        if callable(script):
            script(connection)
        else:
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
