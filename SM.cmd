@echo off
REM ============================================================================
REM  SM - Sistem Informasi Manajemen Sekolah
REM  Peluncur cepat untuk Windows (tanpa memasang ulang dependensi).
REM  Dipakai juga oleh tombol "Muat ulang server" pada versi sebelumnya.
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

REM Tunggu sebentar supaya server lama sempat melepas port 8000.
ping -n 3 127.0.0.1 >nul 2>&1

if not exist ".venv\Scripts\python.exe" (
  echo [!] Lingkungan .venv belum ada. Menjalankan run.bat ...
  call "%~dp0run.bat"
  exit /b %errorlevel%
)

echo ============================================================
echo   SM - Sistem Informasi Manajemen Sekolah
echo ============================================================
echo.
".venv\Scripts\python.exe" run.py %*
echo.
echo Server berhenti. Tekan tombol apa pun untuk menutup jendela ini.
pause
exit /b 0
