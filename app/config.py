"""Konfigurasi terpusat aplikasi SM.

Semua nilai dapat dioverride lewat environment variable berawalan ``SM_``
sehingga aman dipakai di banyak sekolah tanpa mengubah kode.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path

# --------------------------------------------------------------------------- #
# Path
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SM_DATA_DIR") or BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
DB_NAMA = "sm.sqlite3"
DB_NAMA_LAMA = "simsek.sqlite3"
#: Diisi bila berkas basis data lama dipindahkan/dipertahankan (dibaca run.py).
CATATAN_DB = ""


def _ringkasan_db(path: Path) -> tuple[int, int]:
    """(jumlah tabel, jumlah siswa) pada sebuah berkas basis data."""
    with sqlite3.connect(str(path)) as conn:
        tabel = len(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        try:
            siswa = int(conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])
        except sqlite3.Error:  # tabel belum ada pada basis data kosong
            siswa = -1
    return tabel, siswa


def _siapkan_db_path() -> Path:
    """Tentukan lokasi basis data; pemasangan lama (nama ``simsek.sqlite3``)
    dipindahkan sekali ke ``sm.sqlite3`` agar tidak ada data yang hilang."""
    global CATATAN_DB
    kustom = os.getenv("SM_DB_PATH")
    if kustom:
        return Path(kustom)

    baru = DATA_DIR / DB_NAMA
    lama = DATA_DIR / DB_NAMA_LAMA
    if baru.exists() or not lama.exists():
        return baru

    akhiran = ("", "-wal", "-shm")
    try:
        sebelum = _ringkasan_db(lama)
        for sisa in akhiran:
            sumber = Path(f"{lama}{sisa}")
            if sumber.exists():
                sumber.rename(Path(f"{baru}{sisa}"))
        sesudah = _ringkasan_db(baru)
        if sebelum != sesudah:
            raise RuntimeError(f"isi basis data berbeda setelah dipindahkan ({sebelum} -> {sesudah})")
        CATATAN_DB = f"Berkas basis data lama dipindahkan ke {DB_NAMA} ({sesudah[1]} siswa)."
        return baru
    except Exception as exc:  # noqa: BLE001 - apa pun sebabnya, data tetap harus terbaca
        for sisa in akhiran:
            sumber = Path(f"{baru}{sisa}")
            if sumber.exists():
                try:
                    sumber.rename(Path(f"{lama}{sisa}"))
                except OSError:
                    pass
        CATATAN_DB = f"Berkas basis data masih memakai nama lama ({DB_NAMA_LAMA}): {exc}"
        return lama


DB_PATH = _siapkan_db_path()
DOKUMEN_DIR = UPLOAD_DIR / "dokumen"
SAMPLE_DIR = BASE_DIR / "sample-data"
TEMPLATE_DIR = BASE_DIR / "template-import"
STATIC_DIR = BASE_DIR / "app" / "static"


DOKUMEN_MAX_MB = int(os.getenv("SM_DOKUMEN_MAX_MB", 8))
DOKUMEN_MAX_BYTES = DOKUMEN_MAX_MB * 1024 * 1024


def ensure_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Identitas aplikasi
# --------------------------------------------------------------------------- #
APP_NAME = "SM"
APP_LONG_NAME = "Sistem Informasi Manajemen Sekolah"
APP_VERSION = "0.1.0"

# --------------------------------------------------------------------------- #
# Mode online (aplikasi dibuka dari luar jaringan sekolah)
# --------------------------------------------------------------------------- #
def _env_bool(nama: str, bawaan: bool = False) -> bool:
    """Baca saklar lingkungan; 1/ya/on dianggap menyala."""
    nilai = os.getenv(nama)
    if nilai is None:
        return bawaan
    return nilai.strip().lower() not in {"", "0", "false", "no", "off", "tidak"}


#: ``SM_PUBLIK=1`` memaksa pengaman mode online menyala walaupun pengunjung
#: datang dari jaringan lokal (mis. saat diuji lewat terowongan).
PUBLIK = _env_bool("SM_PUBLIK")

#: Batas percobaan login gagal sebelum ditangguhkan sementara.
#: Per akun/NISN dijaga ketat; per alamat IP lebih longgar karena satu sekolah
#: umumnya keluar lewat satu alamat IP (NAT) sehingga siswa tidak saling blokir.
LOGIN_MAKS_GAGAL_AKUN = int(os.getenv("SM_LOGIN_MAKS_GAGAL_AKUN", "8"))
LOGIN_MAKS_GAGAL_IP_PUBLIK = int(os.getenv("SM_LOGIN_MAKS_GAGAL_IP_PUBLIK", "40"))
LOGIN_MAKS_GAGAL_IP_LOKAL = int(os.getenv("SM_LOGIN_MAKS_GAGAL_IP_LOKAL", "200"))
LOGIN_JEDA_DETIK = int(os.getenv("SM_LOGIN_JEDA_DETIK", "600"))

#: Penanda bahwa aplikasi sedang dipakai online (ditulis peluncur/otomatis).
ONLINE_FILE = DATA_DIR / "online.json"
ALAMAT_FILE = DATA_DIR / "alamat-publik.txt"

#: Proxy lokal yang boleh dipercaya meneruskan header X-Forwarded-*.
FORWARDED_ALLOW = os.getenv("SM_FORWARDED_ALLOW", "127.0.0.1")

# --------------------------------------------------------------------------- #
# Sesi & keamanan
# --------------------------------------------------------------------------- #
SESSION_COOKIE = "sm_session"
SESSION_MAX_AGE = int(os.getenv("SM_SESSION_MAX_AGE", 60 * 60 * 12))  # 12 jam
PBKDF2_ROUNDS = int(os.getenv("SM_PBKDF2_ROUNDS", 180_000))


def _secret_key() -> str:
    """Ambil SECRET_KEY dari env, kalau tidak ada buat file persisten."""
    env = os.getenv("SM_SECRET_KEY")
    if env:
        return env
    ensure_dirs()
    key_file = DATA_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:  # pragma: no cover - Windows/FS tanpa chmod
        pass
    return key


SECRET_KEY = _secret_key()

# --------------------------------------------------------------------------- #
# Akun admin pertama (hanya dipakai saat seeding awal)
# --------------------------------------------------------------------------- #
DEFAULT_ADMIN_USERNAME = os.getenv("SM_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("SM_ADMIN_PASSWORD", "admin123")

# --------------------------------------------------------------------------- #
# Impor
# --------------------------------------------------------------------------- #
MAX_UPLOAD_MB = int(os.getenv("SM_MAX_UPLOAD_MB", 64))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
PREVIEW_ROWS = 25  # jumlah baris pratinjau di halaman impor

SPREADSHEET_EXTENSIONS = {
    ".xlsx", ".xlsm", ".xltx", ".xltm",   # Excel 2007+ (openpyxl)
    ".xls",                                # Excel 97-2003 (xlrd)
    ".xlsb",                               # Excel binary (pyxlsb)
    ".ods",                                # LibreOffice / OpenOffice (odfpy)
    ".csv", ".txt", ".tsv",                # teks berpemisah (csv stdlib)
}

# Nama berkas contoh Dapodik yang otomatis diimpor saat database masih kosong.
AUTO_SEED = os.getenv("SM_AUTO_SEED", "1").lower() not in {"0", "false", "no"}

# --------------------------------------------------------------------------- #
# Tampilan
# --------------------------------------------------------------------------- #
ROWS_PER_PAGE = int(os.getenv("SM_ROWS_PER_PAGE", 25))

TAHUN_AJARAN_DEFAULT = os.getenv("SM_TAHUN_AJARAN", "2026/2027")
SEMESTER_DEFAULT = os.getenv("SM_SEMESTER", "1")

# --------------------------------------------------------------------------- #
# Integrasi bot Dapodik (roadmap)
# --------------------------------------------------------------------------- #
DAPODIK_AGENT_NAME = os.getenv("SM_DAPODIK_AGENT", "sm-bot")
