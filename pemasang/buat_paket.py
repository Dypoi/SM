#!/usr/bin/env python3
"""Pembuat paket ZIP aplikasi SM — supaya bisa dibawa & dipasang di komputer mana pun.

Contoh::

    python pemasang/buat_paket.py                          # SM-<versi>-paket.zip
    python pemasang/buat_paket.py --keluar D:\\SM-paket.zip
    python pemasang/buat_paket.py --dengan-bahan           # + berkas .whl (pasang tanpa internet)
    python pemasang/buat_paket.py --dengan-bahan --untuk-platform win_amd64 --untuk-python 3.12

Isi paket:

* seluruh program SM (folder ``app``, skrip, template) — **tanpa** data siswa, tanpa ``.venv``,
  tanpa ``.git``;
* ``PASANG.bat`` / ``HAPUS.bat`` (Windows) dan ``pasang.sh`` / ``hapus.sh`` (Linux/macOS);
* folder ``pemasang/`` berisi skrip pemasangnya;
* (opsional) folder ``bahan/`` berisi berkas ``.whl`` — kalau ada, komputer tujuan bisa
  memasang **tanpa internet sama sekali**.

Berkas ``.whl`` hanya berlaku untuk satu jenis sistem + versi Python tertentu; karena itu
``--untuk-platform``/``--untuk-python`` harus disebutkan bila berbeda dari komputer ini
(mis. membangun paket dari Linux untuk PC Windows).
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AKAR / "pemasang"))

from pasang import ABAIKAN_FOLDER, ABAIKAN_POLA, PENGECUALIAN_POLA, versi_aplikasi  # noqa: E402

POLA_BAHAN = ("fastapi", "uvicorn", "jinja2", "python-multipart", "itsdangerous", "openpyxl",
              "xlrd", "pyxlsb", "odfpy", "selenium")


def _cetak(pesan: str) -> None:
    print(pesan, flush=True)


def _abaikan(akar: Path, dikunci: set[str]):
    import fnmatch

    def saring(direktori: str, nama_nama: list[str]) -> list[str]:
        buang = []
        for nama in nama_nama:
            if nama in ABAIKAN_FOLDER or nama in dikunci:
                buang.append(nama)
                continue
            if any(fnmatch.fnmatch(nama, pola) for pola in ABAIKAN_POLA):
                relatif = (Path(direktori) / nama).relative_to(akar).as_posix()
                if any(fnmatch.fnmatch(relatif, kec) for kec in PENGECUALIAN_POLA):
                    continue
                buang.append(nama)
        return buang

    return saring


def siapkan_hirarki(sumber: Path, kerja: Path) -> Path:
    """Salin program ke folder kerja ``SM/`` lalu tulis berkas pemasang & peluncur."""
    tujuan = kerja / "SM"
    shutil.copytree(sumber, tujuan, dirs_exist_ok=True,
                    ignore=_abaikan(sumber, {"pemasang", "PASANG.bat", "HAPUS.bat",
                                             "pasang.sh", "hapus.sh", "BACA-INI.txt"}))
    (tujuan / "pemasang").mkdir(parents=True, exist_ok=True)
    for nama in ("pasang.py", "pencabut_sm.py", "buat_paket.py", "__init__.py"):
        asal = AKAR / "pemasang" / nama
        if asal.exists():
            shutil.copy2(asal, tujuan / "pemasang" / nama)
    (tujuan / "pemasang" / "__init__.py").touch()

    versi = versi_aplikasi(sumber)
    (tujuan / "PASANG.bat").write_text(
        "@echo off\r\n"
        "REM ============================================================\r\n"
        "REM  Memasang aplikasi SM di komputer ini.\r\n"
        "REM  Klik dua kali berkas ini, lalu ikuti petunjuknya.\r\n"
        "REM ============================================================\r\n"
        "setlocal EnableExtensions\r\n"
        "chcp 65001 >nul 2>nul\r\n"
        "cd /d \"%~dp0\"\r\n"
        "set \"PATH=%SystemRoot%\\System32;%SystemRoot%;%SystemRoot%\\System32\\Wbem;%PATH%\"\r\n"
        "echo ============================================================\r\n"
        "echo   Pemasang SM - Sistem Informasi Manajemen Sekolah\r\n"
        "echo ============================================================\r\n"
        "echo.\r\n"
        "set \"PY=\"\r\n"
        "if exist \"%~dp0.venv\\Scripts\\python.exe\" set \"PY=%~dp0.venv\\Scripts\\python.exe\"\r\n"
        "if not defined PY if exist \"%SystemRoot%\\py.exe\" set \"PY=%SystemRoot%\\py.exe -3\"\r\n"
        "if not defined PY where python >nul 2>nul && set \"PY=python\"\r\n"
        "if defined PY goto mulai\r\n"
        "echo [!] Python belum terpasang di komputer ini.\r\n"
        "echo     1. Buka https://www.python.org/downloads/\r\n"
        "echo     2. Unduh Python 3.10 atau lebih baru, lalu pasang\r\n"
        "echo     3. Centang \"Add python.exe to PATH\" saat memasang\r\n"
        "echo     4. Jalankan PASANG.bat ini lagi\r\n"
        "pause\r\n"
        "exit /b 1\r\n"
        ":mulai\r\n"
        "%PY% \"%~dp0pemasang\\pasang.py\" pasang --pintasan %*\r\n"
        "echo.\r\n"
        "pause\r\n",
        encoding="utf-8", newline="")

    (tujuan / "HAPUS.bat").write_text(
        "@echo off\r\n"
        "REM Menghapus aplikasi SM dari komputer ini (data sekolah dibiarkan).\r\n"
        "setlocal EnableExtensions\r\n"
        "chcp 65001 >nul 2>nul\r\n"
        "cd /d \"%~dp0\"\r\n"
        "set \"PATH=%SystemRoot%\\System32;%SystemRoot%;%SystemRoot%\\System32\\Wbem;%PATH%\"\r\n"
        "set \"PY=\"\r\n"
        "if exist \"%~dp0.venv\\Scripts\\python.exe\" set \"PY=%~dp0.venv\\Scripts\\python.exe\"\r\n"
        "if not defined PY if exist \"%SystemRoot%\\py.exe\" set \"PY=%SystemRoot%\\py.exe -3\"\r\n"
        "if not defined PY set \"PY=python\"\r\n"
        "echo Menghapus pemasangan SM ...\r\n"
        "set /p TUJUAN=Folder pemasangan (kosongkan untuk bawaan): \r\n"
        "if \"%TUJUAN%\"==\"\" ( %PY% \"%~dp0pemasang\\pasang.py\" hapus --ya ) "
        "else ( %PY% \"%~dp0pemasang\\pasang.py\" hapus --tujuan \"%TUJUAN%\" --ya )\r\n"
        "pause\r\n",
        encoding="utf-8", newline="")

    (tujuan / "pasang.sh").write_text(
        "#!/usr/bin/env sh\n"
        "# Memasang aplikasi SM di komputer ini (Linux/macOS).\n"
        "cd \"$(dirname \"$0\")\" || exit 1\n"
        "if [ -x \".venv/bin/python\" ]; then PY=\".venv/bin/python\"; "
        "else PY=$(command -v python3 || command -v python); fi\n"
        "if [ -z \"$PY\" ]; then echo '[!] Python 3 belum terpasang.'; exit 1; fi\n"
        "exec \"$PY\" pemasang/pasang.py pasang \"$@\"\n", encoding="utf-8")
    (tujuan / "pasang.sh").chmod(0o755)

    (tujuan / "hapus.sh").write_text(
        "#!/usr/bin/env sh\n"
        "# Menghapus aplikasi SM (data sekolah dibiarkan).\n"
        "cd \"$(dirname \"$0\")\" || exit 1\n"
        "PY=$(command -v python3 || command -v python)\n"
        "exec \"$PY\" pemasang/pasang.py hapus --ya \"$@\"\n", encoding="utf-8")
    (tujuan / "hapus.sh").chmod(0o755)

    (tujuan / "BACA-INI.txt").write_text(
        "SM - Sistem Informasi Manajemen Sekolah (PEMASANG)\n"
        "=================================================\n\n"
        f"Versi paket: {versi}\n\n"
        "Cara memasang\n"
        "-------------\n"
        "  Windows      : klik dua kali PASANG.bat\n"
        "  Linux/macOS  : jalankan ./pasang.sh\n"
        "  Cara lain    : python pemasang/pasang.py\n\n"
        "Pemasang akan menyalin program ke folder aplikasi pengguna, membuat lingkungan\n"
        "Python (.venv), memasang pustaka, menyiapkan basis data, lalu membuat tombol\n"
        "peluncur di folder pemasangan (dan pintasan desktop bila diminta).\n\n"
        "Data sekolah disimpan di folder «data» di dalam folder pemasangan. Memasang ulang\n"
        "atau memperbarui TIDAK menghapus data itu.\n\n"
        "Perintah lain\n"
        "-------------\n"
        "  periksa   : python pemasang/pasang.py periksa\n"
        "  perbarui  : python pemasang/pasang.py perbarui\n"
        "  menghapus : python pemasang/pasang.py hapus --ya\n"
        "  folder lain: python pemasang/pasang.py --tujuan D:\\SM\n\n"
        "Setelah terpasang: buka folder pemasangan, jalankan «Jalankan-SM.cmd»\n"
        "(Windows) atau «jalankan-sm.sh», lalu buka http://localhost:8000\n"
        "Login petugas: admin / admin123  ·  Login siswa: cukup NISN\n", encoding="utf-8")
    return tujuan


def buat_bahan(folder: Path, untuk_platform: str, untuk_python: str) -> int:
    """Unduh berkas .whl (beserta seluruh keperluannya) ke ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    perintah = [sys.executable, "-m", "pip", "download", "--dest", str(folder),
                "--disable-pip-version-check", "--quiet"]
    if untuk_platform:
        perintah += ["--platform", untuk_platform, "--only-binary=:all:"]
    if untuk_python:
        perintah += ["--python-version", untuk_python]
    perintah += POLA_BAHAN
    _cetak("      Mengunduh pustaka (sekali saja, perlu internet) ...")
    hasil = subprocess.run(perintah, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=3600)
    if hasil.returncode != 0:
        _cetak("      [!] Pengunduhan gagal — paket dibuat tanpa bahan (perlu internet saat memasang).")
        _cetak("          " + (hasil.stderr or hasil.stdout or "").strip()[-400:])
        return 0
    jumlah = len(list(folder.glob("*.whl"))) + len(list(folder.glob("*.tar.gz")))
    ukuran = sum(p.stat().st_size for p in folder.iterdir() if p.is_file()) / 1024 / 1024
    _cetak(f"      {jumlah} berkas pustaka ({ukuran:.0f} MB) siap dibawa.")
    return jumlah


def buat(args) -> dict:
    """Bangun paket ZIP. Kembalikan ringkasannya."""
    sumber = AKAR
    versi = versi_aplikasi(sumber)
    keluar = Path(args.keluar).expanduser().resolve() if getattr(args, "keluar", None) else \
        AKAR / f"SM-{versi}-paket.zip"

    with tempfile.TemporaryDirectory(prefix="sm-paket-") as sementara:
        kerja = Path(sementara)
        _cetak("[1/3] Menyiapkan isi paket ...")
        tujuan = siapkan_hirarki(sumber, kerja)

        jumlah_bahan = 0
        if getattr(args, "dengan_bahan", False):
            _cetak("[2/3] Menyiapkan bahan pemasangan (berkas pustaka) ...")
            jumlah_bahan = buat_bahan(tujuan / "bahan",
                                      getattr(args, "untuk_platform", "") or "",
                                      getattr(args, "untuk_python", "") or "")
        else:
            _cetak("[2/3] Tanpa bahan — komputer tujuan perlu internet saat memasang.")

        _cetak(f"[3/3] Menulis {keluar.name} ...")
        keluar.parent.mkdir(parents=True, exist_ok=True)
        berkas = 0
        with zipfile.ZipFile(keluar, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for jalur in sorted(tujuan.rglob("*")):
                if jalur.is_file():
                    z.write(jalur, jalur.relative_to(kerja).as_posix())
                    berkas += 1
        ukuran = keluar.stat().st_size / 1024 / 1024
        _cetak("")
        _cetak(f"  Paket siap: {keluar}")
        _cetak(f"  {berkas} berkas · {ukuran:.1f} MB · versi {versi}"
               + (f" · {jumlah_bahan} berkas pustaka" if jumlah_bahan else ""))
        _cetak("  Cara pakai di komputer lain: ekstrak, lalu jalankan PASANG.bat (Windows) "
               "atau ./pasang.sh (Linux/macOS).")
    return {"ok": True, "perintah": "buat-paket", "paket": str(keluar),
            "ukuran_mb": round(ukuran, 1), "berkas": berkas, "versi": versi,
            "bahan": jumlah_bahan}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pembuat paket ZIP aplikasi SM")
    parser.add_argument("--keluar", help="nama berkas ZIP hasil")
    parser.add_argument("--dengan-bahan", action="store_true", help="ikutkan berkas .whl")
    parser.add_argument("--untuk-platform", default="", help="mis. win_amd64")
    parser.add_argument("--untuk-python", default="", help="mis. 3.12")
    args = parser.parse_args(argv)
    hasil = buat(args)
    return 0 if hasil.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
