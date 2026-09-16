@echo off
REM ============================================================================
REM  SM - Sistem Informasi Manajemen Sekolah
REM  Skrip peluncur untuk Windows. Cukup klik dua kali berkas ini,
REM  atau jalankan dari Command Prompt:  run.bat
REM
REM  Jendela ".venv" TIDAK perlu diaktifkan lebih dulu: berkas ini mencari
REM  Python sendiri, mulai dari folder .venv aplikasi.
REM ============================================================================
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

REM Pastikan perintah bawaan Windows (dir, find, dll.) selalu terjangkau walau
REM PATH pengguna berubah atau terpotong. Sebagian komputer kehilangan
REM C:\Windows\System32 dari PATH sehingga "where" gagal dan Python seolah
REM tidak ditemukan padahal ada.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"

echo ============================================================
echo   SM - Sistem Informasi Manajemen Sekolah
echo ============================================================
echo   Folder aplikasi: %CD%
echo.

REM --- 1. Cari Python ---------------------------------------------------------
REM Urutan: .venv aplikasi -> .venv yang aktif -> python.exe di folder aplikasi
REM -> peluncur "py" -> folder pemasangan umum -> python.exe di PATH.
REM Setiap calon diuji: harus benar-benar bisa dijalankan dan versinya 3.10+.
set "PY="
set "PYARGS="
set "PYSUMBER="
set "PYTERLALU_TUA="

call :coba_python "%~dp0.venv\Scripts\python.exe" "" "folder .venv aplikasi"
if not defined PY if defined VIRTUAL_ENV call :coba_python "%VIRTUAL_ENV%\Scripts\python.exe" "" "lingkungan .venv yang sedang aktif"
if not defined PY call :coba_python "%~dp0python.exe" "" "python.exe di folder aplikasi"
if not defined PY call :coba_python "%SystemRoot%\py.exe" "-3" "peluncur py"
if not defined PY call :cari_folder_python
REM python.exe di PATH dicoba paling akhir: pada komputer tanpa Python, yang
REM ditemukan biasanya hanya tautan Microsoft Store (bukan Python asli).
if not defined PY call :coba_python "python.exe" "" "python.exe di PATH"

if not defined PY (
  echo [!] Python 3.10 atau lebih baru tidak ditemukan.
  echo.
  if defined PYTERLALU_TUA echo     Catatan: ada Python terpasang, tetapi versinya lebih tua dari 3.10.
  echo     Yang sudah dicoba:
  echo       - .venv\Scripts\python.exe   ^(lingkungan aplikasi^)
  echo       - python.exe di folder aplikasi
  echo       - py -3                      ^(peluncur resmi Python^)
  echo       - folder pemasangan umum: %%LOCALAPPDATA%%\Programs\Python\Python3*
  echo         dan %%ProgramFiles%%\Python3*
  echo       - python.exe pada PATH
  echo.
  echo     Cara memasang:
  echo       1. Buka https://www.python.org/downloads/
  echo       2. Unduh Python 3.10 atau lebih baru
  echo       3. Saat memasang, centang "Add python.exe to PATH"
  echo       4. Tutup jendela ini, lalu jalankan run.bat lagi
  echo.
  echo     Sudah punya Python yang bisa dijalankan? Coba perintah ini di jendela
  echo     Command Prompt, lalu kirim pesan galatnya bila tetap gagal:
  echo         python run.py
  echo.
  echo     Laporan kondisi lengkap: jalankan SM-diagnosa.bat
  echo.
  pause
  exit /b 1
)

echo [1/3] Python ditemukan pada %PYSUMBER%
%PY% %PYARGS% --version
echo.

REM --- 2. Siapkan lingkungan .venv -------------------------------------------
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
"%VENV_PY%" -c "import sys" >nul 2>nul
if errorlevel 1 goto buat_venv
if not exist "%VENV_PY%" goto buat_venv
echo [2/3] Lingkungan Python .venv sudah ada, dilewati.
goto venv_siap

:buat_venv
if exist "%~dp0.venv" (
  echo [2/3] Lingkungan .venv ada tetapi tidak dapat dijalankan, dibuat ulang ...
  rmdir /s /q "%~dp0.venv" >nul 2>nul
) else (
  echo [2/3] Membuat lingkungan Python pada folder .venv ...
)
%PY% %PYARGS% -m venv .venv
if errorlevel 1 goto gagal_venv
if not exist "%VENV_PY%" goto gagal_venv

:venv_siap

REM --- 3. Pasang / periksa dependensi -----------------------------------------
REM Pemasangan hanya dijalankan bila dependensi inti belum bisa diimpor atau
REM berkas requirements.txt berubah. Jadi komputer tanpa internet tetap bisa
REM menjalankan aplikasi dengan dependensi yang sudah terpasang.
set "STEMPEL=%~dp0.venv\sm-dependensi.txt"
set "PERLU_PIP="
"%VENV_PY%" -c "import fastapi, uvicorn, jinja2, multipart, itsdangerous, openpyxl" >nul 2>nul
if errorlevel 1 set "PERLU_PIP=1"
set "REQ_INFO="
for %%F in ("requirements.txt") do set "REQ_INFO=%%~zF-%%~tF"
set "STEMPEL_ISI="
if exist "%STEMPEL%" set /p STEMPEL_ISI=<"%STEMPEL%"
if not "%STEMPEL_ISI%"=="%REQ_INFO%" set "PERLU_PIP=1"
if not defined PERLU_PIP (
  echo [3/3] Dependensi sudah lengkap, pemasangan dilewati.
  goto jalankan_server
)
echo [3/3] Memasang dependensi - perlu internet, sekali saja ...
"%VENV_PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VENV_PY%" -m pip install -r requirements.txt --quiet --disable-pip-version-check
"%VENV_PY%" -c "import fastapi, uvicorn, jinja2, multipart, itsdangerous, openpyxl" >nul 2>nul
if errorlevel 1 goto gagal_dependensi
>"%STEMPEL%" echo %REQ_INFO%
echo     Dependensi siap.
echo.

REM --- 4. Jalankan ------------------------------------------------------------
:jalankan_server
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
echo Menjalankan server ... jendela ini biarkan tetap terbuka.
echo.
"%VENV_PY%" run.py %*
echo.
echo Server berhenti. Tekan tombol apa pun untuk menutup jendela ini.
pause
exit /b 0

:gagal_venv
echo.
echo [!] Lingkungan Python (.venv) gagal dibuat.
echo     Tips: pastikan Python 3.10+ terpasang, lalu jalankan run.bat lagi.
echo.
pause
exit /b 1

:gagal_dependensi
echo.
echo [!] Dependensi belum lengkap dan pemasangan gagal.
echo     Tips: periksa koneksi internet, lalu jalankan run.bat lagi.
echo.
pause
exit /b 1

REM ============================================================================
REM  Subrutin
REM ============================================================================

:coba_python
REM %1 = jalur atau nama berkas Python, %2 = argumen tambahan (mis. -3),
REM %3 = label sumber untuk pesan.
if defined PY goto :eof
set "UJI=%~1"
if "%UJI%"=="" goto :eof

REM Nama polos (mis. python.exe) dicari di PATH tanpa memakai "where".
if not exist "%UJI%" (
  set "UJI="
  for %%X in (%~nx1) do set "UJI=%%~$PATH:X"
)
if "%UJI%"=="" goto :eof
if not exist "%UJI%" goto :eof

REM Harus benar-benar dapat dijalankan dan versinya minimal 3.10.
"%UJI%" %~2 -c "import sys" >nul 2>nul
if errorlevel 1 goto :eof
"%UJI%" %~2 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 9)" >nul 2>nul
if errorlevel 9 (
  set "PYTERLALU_TUA=1"
  goto :eof
)
if errorlevel 1 goto :eof

set "PY="%UJI%""
set "PYARGS=%~2"
set "PYSUMBER=%~3"
goto :eof

:cari_folder_python
REM Cari Python pada folder pemasangan yang umum (versi terbaru lebih dulu).
if defined PY goto :eof
for /f "delims=" %%D in ('dir /b /ad /o-n "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do call :coba_python "%LOCALAPPDATA%\Programs\Python\%%D\python.exe" "" "folder pemasangan Python (pengguna)"
if defined PY goto :eof
for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles%\Python3*" 2^>nul') do call :coba_python "%ProgramFiles%\%%D\python.exe" "" "folder Program Files"
if defined PY goto :eof
for /f "delims=" %%D in ('dir /b /ad /o-n "%SystemDrive%\Python3*" 2^>nul') do call :coba_python "%SystemDrive%\%%D\python.exe" "" "folder %SystemDrive%"
if defined PY goto :eof
for /f "delims=" %%D in ('dir /b /ad /o-n "%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3*" 2^>nul') do call :coba_python "%LOCALAPPDATA%\Microsoft\WindowsApps\%%D\python.exe" "" "Python dari Microsoft Store"
goto :eof
