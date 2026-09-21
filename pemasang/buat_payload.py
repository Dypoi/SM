#!/usr/bin/env python3
"""Menyiapkan isi paket bodap (``payload/``) — dipakai sebelum ``bodap.exe`` dibangun.

Isi yang dibuat:

| Berkas | Guna |
| --- | --- |
| ``payload/app.zip`` | seluruh program SM (tanpa data siswa, tanpa ``.venv``/``.git``) |
| ``payload/VERSI.txt`` | versi bodap (tampil di wizard & log) |
| ``payload/python-embed.zip`` | Python bawaan Windows (``--dengan-python``) |
| ``payload/bootstrap/*.whl`` | pip, setuptools, wheel — untuk menanam pip tanpa internet |
| ``payload/wheels/*.whl`` | seluruh pustaka aplikasi (``--dengan-bahan``) → pasang tanpa internet |

Contoh::

    python pemasang/buat_payload.py                    # app.zip + bootstrap (perlu internet)
    python pemasang/buat_payload.py --dengan-python    # + Python bawaan Windows
    python pemasang/buat_payload.py --dengan-python --dengan-bahan \\
        --untuk-python 3.12 --untuk-platform win_amd64
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
PAYLOAD = AKAR / "pemasang" / "payload"

#: Sama dengan aturan pemasang: data pengguna & sisa pengembangan tidak pernah ikut.
ABAIKAN_FOLDER = {
    ".git", ".venv", "venv", "env", "data", "sample-data", "node_modules", "payload",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    "dist", "build",
}
ABAIKAN_POLA = (
    "*.pyc", "*.pyo", "*.sqlite3*", "*.log", ".env", "secrets.env",
    "*.xlsx", "*.xls", "*.xlsb", "*.ods",
    "laporan-python.txt", "SM-*-paket.zip", "bodap.exe",
)
PENGECUALIAN_POLA = ("template-import/*",)

#: Pustaka yang harus ada di paket agar pip bisa ditanam tanpa internet.
BOOTSTRAP = ("pip", "setuptools", "wheel")

#: Seluruh pustaka aplikasi (untuk pemasangan tanpa internet).
PUSTAKA = ("fastapi", "uvicorn[standard]", "jinja2", "python-multipart", "itsdangerous",
           "openpyxl", "xlrd", "pyxlsb", "odfpy", "selenium")

PYTHON_EMBED_RILIS = "3.12.8"


def _cetak(pesan: str) -> None:
    print(pesan, flush=True)


def _abaikan(direktori: str, nama_nama: list[str]) -> list[str]:
    buang = []
    for nama in nama_nama:
        if nama in ABAIKAN_FOLDER:
            buang.append(nama)
            continue
        if any(fnmatch.fnmatch(nama, pola) for pola in ABAIKAN_POLA):
            relatif = (Path(direktori) / nama).relative_to(AKAR).as_posix()
            if any(fnmatch.fnmatch(relatif, kec) for kec in PENGECUALIAN_POLA):
                continue
            buang.append(nama)
    return buang


def buat_app_zip() -> Path:
    """Bungkus seluruh program SM menjadi ``payload/app.zip``."""
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    sasaran = PAYLOAD / "app.zip"
    berkas = 0
    with zipfile.ZipFile(sasaran, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        # pemasang/bodap.exe tidak perlu ikut ke dalam paket (ukurannya besar & tidak dipakai)
        for jalur in sorted(AKAR.rglob("*")):
            if jalur.is_dir():
                continue
            relatif = jalur.relative_to(AKAR)
            if any(bagian in ABAIKAN_FOLDER for bagian in relatif.parts[:-1]):
                continue
            if any(fnmatch.fnmatch(jalur.name, pola) for pola in ABAIKAN_POLA) and not any(
                    fnmatch.fnmatch(relatif.as_posix(), kec) for kec in PENGECUALIAN_POLA):
                continue
            if relatif.as_posix() == "pemasang/bodap.spec":
                # ikut disertakan (kecil) supaya pengguna bisa membangun ulang sendiri
                pass
            z.write(jalur, relatif.as_posix())
            berkas += 1
    ukuran = sasaran.stat().st_size / 1024
    _cetak(f"  app.zip      : {berkas} berkas, {ukuran:.0f} KB")
    return sasaran


def _unduh(alamat: str, sasaran: Path) -> bool:
    sasaran.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(alamat, timeout=120) as jawab, open(sasaran, "wb") as keluar:
            shutil.copyfileobj(jawab, keluar)
        return sasaran.stat().st_size > 1024
    except Exception as exc:      # noqa: BLE001 — dikembalikan ke pemanggil
        _cetak(f"  [!] gagal mengunduh {alamat}: {type(exc).__name__}: {exc}")
        sasaran.unlink(missing_ok=True)
        return False


def ambil_bootstrap() -> int:
    """pip/setuptools/wheel (py3-none-any) ke ``payload/bootstrap`` — supaya pip bisa ditanam."""
    import tempfile

    folder = PAYLOAD / "bootstrap"
    folder.mkdir(parents=True, exist_ok=True)
    jumlah = 0
    with tempfile.TemporaryDirectory(prefix="sm-bootstrap-") as tmp:
        for nama in BOOTSTRAP:
            hasil = subprocess.run(
                [sys.executable, "-m", "pip", "download", "--dest", tmp, "--no-deps",
                 "--only-binary=:all:", "--disable-pip-version-check", "--quiet", nama],
                capture_output=True, text=True, timeout=1200)
            if hasil.returncode != 0:
                _cetak(f"  [!] {nama} gagal diunduh: {(hasil.stderr or '').strip()[-200:]}")
                continue
        for berkas in sorted(Path(tmp).glob("*.whl")):
            shutil.copy2(berkas, folder / berkas.name)
            jumlah += 1
    if jumlah:
        _cetak(f"  bootstrap    : {jumlah} berkas (pip, setuptools, wheel)")
    return jumlah


def ambil_wheels(untuk_python: str, untuk_platform: str) -> int:
    """Seluruh pustaka aplikasi ke ``payload/wheels`` → pemasangan bisa tanpa internet."""
    folder = PAYLOAD / "wheels"
    folder.mkdir(parents=True, exist_ok=True)
    perintah = [sys.executable, "-m", "pip", "download", "--dest", str(folder),
                "--disable-pip-version-check", "--quiet"]
    if untuk_platform:
        perintah += ["--platform", untuk_platform, "--only-binary=:all:"]
    if untuk_python:
        perintah += ["--python-version", untuk_python]
    perintah += list(PUSTAKA)
    _cetak(f"  Mengunduh pustaka aplikasi ({untuk_platform or 'platform ini'}, "
           f"Python {untuk_python or 'versi ini'}) ...")
    hasil = subprocess.run(perintah, capture_output=True, text=True, timeout=3600)
    if hasil.returncode != 0:
        _cetak("  [!] Sebagian pustaka gagal diunduh; mencoba lagi tanpa odfpy/selenium ...")
        perintah2 = [p for p in perintah if p not in ("odfpy", "selenium")]
        subprocess.run(perintah2, capture_output=True, text=True, timeout=3600)
    berkas = sorted(folder.glob("*.whl")) + sorted(folder.glob("*.tar.gz"))
    ukuran = sum(p.stat().st_size for p in berkas) / 1024 / 1024
    _cetak(f"  wheels       : {len(berkas)} berkas, {ukuran:.0f} MB")
    return len(berkas)


def ambil_python_embed() -> bool:
    """Python bawaan Windows (embeddable) ke ``payload/python-embed.zip``."""
    for arsitektur in ("amd64", "win32"):
        nama = f"python-{PYTHON_EMBED_RILIS}-embed-{arsitektur}.zip"
        alamat = f"https://www.python.org/ftp/python/{PYTHON_EMBED_RILIS}/{nama}"
        sasaran = PAYLOAD / "python-embed.zip"
        _cetak(f"  Mengunduh {nama} ...")
        if _unduh(alamat, sasaran):
            _cetak(f"  python-embed : {sasaran.stat().st_size / 1024 / 1024:.1f} MB ({arsitektur})")
            return True
    _cetak("  [!] Python bawaan tidak bisa diunduh. bodap.exe tetap bisa dibangun, tetapi "
           "komputer tujuan harus sudah punya Python 3.10+ (atau mengizinkan unduhan saat "
           "pemasangan).")
    return False


def tulis_versi() -> str:
    versi = "0.1.0"
    try:
        for baris in (AKAR / "app" / "config.py").read_text(encoding="utf-8").splitlines():
            if baris.strip().startswith("APP_VERSION"):
                versi = baris.split("=", 1)[1].strip().strip('"\'')
                break
    except OSError:
        pass
    isi = f"{versi} (bodap {time.strftime('%Y-%m-%d')})"
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    (PAYLOAD / "VERSI.txt").write_text(isi + "\n", encoding="utf-8")
    (AKAR / "pemasang" / "BODAP_VERSI.txt").write_text(isi + "\n", encoding="utf-8")
    _cetak(f"  versi        : {isi}")
    return versi


def buat(args) -> dict:
    _cetak("Menyiapkan payload bodap ...")
    versi = tulis_versi()
    app = buat_app_zip()
    bootstrap = ambil_bootstrap()
    python_ada = ambil_python_embed() if args.dengan_python else False
    wheels = (ambil_wheels(args.untuk_python, args.untuk_platform) if args.dengan_bahan else 0)
    ukuran = sum(p.stat().st_size for p in PAYLOAD.rglob("*") if p.is_file()) / 1024 / 1024
    _cetak(f"Selesai: payload {ukuran:.1f} MB "
           f"(app.zip, bootstrap {bootstrap}, python bawaan {'ada' if python_ada else 'tidak ada'}"
           f"{f', wheels {wheels}' if wheels else ''})")
    return {"ok": True, "versi": versi, "app_zip": str(app), "bootstrap": bootstrap,
            "python_embed": python_ada, "wheels": wheels, "ukuran_mb": round(ukuran, 1)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Menyiapkan payload bodap (app.zip, Python, wheels)")
    p.add_argument("--dengan-python", action="store_true",
                   help="sertakan Python bawaan Windows (perlu internet)")
    p.add_argument("--dengan-bahan", action="store_true",
                   help="sertakan seluruh pustaka (.whl) supaya bisa dipasang tanpa internet")
    p.add_argument("--untuk-python", default="3.12", help="versi Python tujuan (bawaan 3.12)")
    p.add_argument("--untuk-platform", default="win_amd64",
                   help="platform tujuan (bawaan win_amd64)")
    args = p.parse_args(argv)
    hasil = buat(args)
    return 0 if hasil.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
