@echo off
REM ============================================================================
REM  SIMSEK - Sistem Informasi Manajemen Sekolah
REM  Skrip peluncur untuk Windows. Cukup klik dua kali berkas ini,
REM  atau jalankan dari Command Prompt:  run.bat
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo   SIMSEK - Sistem Informasi Manajemen Sekolah
echo ============================================================
echo.

REM --- 1. Cari Python ---------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [!] Python tidak ditemukan di komputer ini.
  echo.
  echo     Cara memasang:
  echo       1. Buka https://www.python.org/downloads/
  echo       2. Unduh Python 3.10 atau lebih baru
  echo       3. Saat memasang, centang "Add python.exe to PATH"
  echo       4. Tutup jendela ini, lalu jalankan run.bat lagi
  echo.
  pause
  exit /b 1
)

REM --- 2. Siapkan lingkungan .venv -------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Membuat lingkungan Python di folder .venv ...
  %PY% -m venv .venv
  if errorlevel 1 goto gagal
) else (
  echo [1/3] Lingkungan Python sudah ada, dilewati.
)

REM --- 3. Pasang dependensi ---------------------------------------------------
echo [2/3] Memasang / memeriksa dependensi - perlu internet, sekali saja ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
if errorlevel 1 goto gagal

REM --- 4. Jalankan ------------------------------------------------------------
echo [3/3] Menjalankan server ...
echo.
".venv\Scripts\python.exe" run.py %*
echo.
echo Server berhenti. Tekan tombol apa pun untuk menutup jendela ini.
pause
exit /b 0

:gagal
echo.
echo [!] Terjadi kesalahan saat menyiapkan aplikasi. Periksa pesan di atas.
echo     Tips: pastikan koneksi internet aktif, lalu jalankan run.bat lagi.
echo.
pause
exit /b 1
