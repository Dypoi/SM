@echo off
REM ============================================================================
REM  Membangun bodap.exe (pemasang SM satu berkas) di komputer Windows ini.
REM
REM  Kebutuhan:
REM    * Python 3.10+ terpasang
REM    * sambungan internet (untuk mengambil Python bawaan, pip, dan pustaka)
REM
REM  Hasil: dist\bodap.exe  ->  berkas inilah yang dibawa ke laptop/PC lain,
REM  cukup klik dua kali di sana (Next -> Next -> Install -> Finish + ikon Desktop).
REM ============================================================================
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0.."

set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"
set "PYTHONUTF8=1"

echo ============================================================
echo   Membangun bodap.exe
echo ============================================================
echo   Folder repo: %CD%
echo.

REM --- 1. Python -------------------------------------------------------------
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "%SystemRoot%\py.exe" set "PY=%SystemRoot%\py.exe -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [!] Python 3.10+ tidak ditemukan. Pasang dari https://www.python.org/downloads/
  echo     lalu jalankan berkas ini lagi.
  pause
  exit /b 1
)

REM --- 2. PyInstaller --------------------------------------------------------
%PY% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
  echo [1/4] Memasang PyInstaller ^(perlu internet^) ...
  %PY% -m pip install --upgrade pip --quiet --disable-pip-version-check
  %PY% -m pip install pyinstaller --quiet --disable-pip-version-check
) else (
  echo [1/4] PyInstaller sudah ada.
)
%PY% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 goto gagal

REM --- 3. Ikon & payload -----------------------------------------------------
echo [2/4] Membuat ikon ...
%PY% pemasang\buat_ikon.py || goto gagal

echo [3/4] Menyiapkan isi paket ^(app.zip, Python bawaan, pip, pustaka^) ...
echo       Perlu internet; unduhan Python bawaan ± 11 MB, pustaka ± 40 MB.
%PY% pemasang\buat_payload.py --dengan-python --dengan-bahan --untuk-python 3.12 --untuk-platform win_amd64 || goto gagal

REM --- 4. Bungkus jadi satu berkas -------------------------------------------
echo [4/4] Membungkus menjadi dist\bodap.exe ...
%PY% -m PyInstaller --noconfirm --clean pemasang\bodap.spec || goto gagal

echo.
if not exist "dist\bodap.exe" goto gagal
echo ============================================================
echo   SELESAI
echo ============================================================
for %%F in ("dist\bodap.exe") do echo   Berkas  : %%~fF
for %%F in ("dist\bodap.exe") do echo   Ukuran  : %%~zF byte
echo   Bawa berkas dist\bodap.exe ke laptop/PC lain, klik dua kali di sana.
echo.
echo   Uji cepat isi paket di komputer ini:
echo       dist\bodap.exe --uji --laporan hasil-uji.json
echo.
pause
exit /b 0

:gagal
echo.
echo [!] Pembangunan gagal. Baca pesan galat di atas.
echo     Tips: pastikan internet aktif, lalu jalankan BUAT-BODAP.bat lagi.
pause
exit /b 1
