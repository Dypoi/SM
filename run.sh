#!/usr/bin/env bash
# ============================================================================
#  SM - Sistem Informasi Manajemen Sekolah
#  Skrip peluncur untuk Linux / macOS.
#
#  Pemakaian:
#      ./run.sh                 # jalankan server di port 8000
#      ./run.sh --port 9000     # ganti port
#      ./run.sh --init-db       # siapkan database lalu keluar
# ============================================================================
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  SM - Sistem Informasi Manajemen Sekolah"
echo "============================================================"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] Python 3 belum terpasang."
  echo "    Debian/Ubuntu : sudo apt install python3 python3-venv"
  echo "    macOS         : brew install python3"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Membuat lingkungan Python di folder .venv ..."
  python3 -m venv .venv
else
  echo "[1/3] Lingkungan Python sudah ada, dilewati."
fi

echo "[2/3] Memasang / memeriksa dependensi - perlu internet, sekali saja ..."
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet

echo "[3/3] Menjalankan server ..."
exec .venv/bin/python run.py "$@"
