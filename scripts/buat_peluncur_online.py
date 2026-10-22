#!/usr/bin/env python3
"""Tulis ``SM-online.bat`` (peluncur Windows) dengan akhir baris CRLF.

Berkas batch Windows harus memakai CRLF; menyimpannya lewat skrip ini
menghindari berkas berakhir LF karena penyunting teks bawaan.

Jalankan::

    python scripts/buat_peluncur_online.py
"""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TUJUAN = BASE_DIR / "SM-online.bat"

ISI = r"""@echo off
REM ============================================================================
REM  SM - menjalankan aplikasi dalam mode online (gratis).
REM
REM  Klik dua kali berkas ini. Petunjuk lengkap ada di README bagian
REM  "Menjalankan online". Jendela ".venv" TIDAK perlu diaktifkan lebih dulu.
REM ============================================================================
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

REM Pastikan perintah bawaan Windows selalu terjangkau walau PATH berubah.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"
set "PYTHONUTF8=1"
set "SM_PUBLIK=1"

echo ============================================================
echo   SM - mode online (gratis)
echo ============================================================
echo   Folder aplikasi: %CD%
echo.

if exist "%~dp0.venv\Scripts\python.exe" goto pakai_venv
if exist "%SystemRoot%\py.exe" goto pakai_py
where python >nul 2>nul
if errorlevel 1 goto tanpa_python
python "%~dp0SM-online.py" %*
goto selesai

:pakai_py
"%SystemRoot%\py.exe" -3 "%~dp0SM-online.py" %*
goto selesai

:pakai_venv
"%~dp0.venv\Scripts\python.exe" "%~dp0SM-online.py" %*
goto selesai

:tanpa_python
echo [!] Python tidak ditemukan di komputer ini.
echo.
echo     Cara memasang:
echo       1. Buka https://www.python.org/downloads/
echo       2. Unduh Python 3.10 atau lebih baru
echo       3. Saat memasang, centang "Add python.exe to PATH"
echo       4. Jalankan run.bat lebih dulu, lalu SM-online.bat lagi
echo.

:selesai
if errorlevel 1 pause
endlocal
"""


def main() -> int:
    teks = ISI.replace("\r\n", "\n").replace("\n", "\r\n")
    TUJUAN.write_bytes(teks.encode("utf-8"))
    jumlah = teks.count("\r\n")
    assert "\n" not in teks.replace("\r\n", ""), "masih ada LF tanpa CR"
    print(f"[OK] {TUJUAN.name} ditulis: {len(teks)} bita, {jumlah} baris CRLF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
