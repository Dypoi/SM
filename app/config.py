"""Konfigurasi terpusat aplikasi SIMSEK.

Semua nilai dapat dioverride lewat environment variable berawalan ``SM_``
sehingga aman dipakai di banyak sekolah tanpa mengubah kode.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

# --------------------------------------------------------------------------- #
# Path
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SM_DATA_DIR") or BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = Path(os.getenv("SM_DB_PATH") or DATA_DIR / "simsek.sqlite3")
SAMPLE_DIR = BASE_DIR / "sample-data"
TEMPLATE_DIR = BASE_DIR / "template-import"
STATIC_DIR = BASE_DIR / "app" / "static"


def ensure_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Identitas aplikasi
# --------------------------------------------------------------------------- #
APP_NAME = "SIMSEK"
APP_LONG_NAME = "Sistem Informasi Manajemen Sekolah"
APP_VERSION = "0.1.0"

# --------------------------------------------------------------------------- #
# Sesi & keamanan
# --------------------------------------------------------------------------- #
SESSION_COOKIE = "simsek_session"
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
DAPODIK_AGENT_NAME = os.getenv("SM_DAPODIK_AGENT", "simsek-bot")
