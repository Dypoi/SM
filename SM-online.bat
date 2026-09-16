@echo off
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
