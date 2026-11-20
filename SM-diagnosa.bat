@echo off
REM ============================================================================
REM  SM - laporan kondisi komputer.
REM  Jalankan berkas ini bila aplikasi tidak mau menyala (mis. Python dianggap
REM  tidak ada), lalu kirim isi laporan-python.txt kepada petugas IT/developer.
REM ============================================================================
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"
set "LAPORAN=%~dp0laporan-python.txt"

echo Membuat laporan kondisi ...
>"%LAPORAN%" echo SM - laporan kondisi komputer
>>"%LAPORAN%" echo Waktu : %DATE% %TIME%
>>"%LAPORAN%" echo Folder aplikasi : %CD%
>>"%LAPORAN%" echo Windows : %OS% %PROCESSOR_ARCHITECTURE%
>>"%LAPORAN%" echo VIRTUAL_ENV : %VIRTUAL_ENV%
>>"%LAPORAN%" echo COMSPEC : %COMSPEC%
>>"%LAPORAN%" echo.
>>"%LAPORAN%" echo --- where py / where python ---
>>"%LAPORAN%" 2>&1 where py
>>"%LAPORAN%" 2>&1 where python
>>"%LAPORAN%" echo.
>>"%LAPORAN%" echo --- versi Python ---
>>"%LAPORAN%" 2>&1 py -3 -V
>>"%LAPORAN%" 2>&1 python -V
>>"%LAPORAN%" 2>&1 "%SystemRoot%\py.exe" -0p
>>"%LAPORAN%" echo.
>>"%LAPORAN%" echo --- lingkungan .venv aplikasi ---
if exist ".venv\Scripts\python.exe" >>"%LAPORAN%" echo .venv\Scripts\python.exe : ADA
if not exist ".venv\Scripts\python.exe" >>"%LAPORAN%" echo .venv\Scripts\python.exe : TIDAK ADA
>>"%LAPORAN%" 2>&1 ".venv\Scripts\python.exe" -V
>>"%LAPORAN%" 2>&1 ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, jinja2, openpyxl; print('dependensi: lengkap')"
>>"%LAPORAN%" echo.
>>"%LAPORAN%" echo --- folder pemasangan Python yang ditemukan ---
>>"%LAPORAN%" 2>&1 dir /b /ad "%LOCALAPPDATA%\Programs\Python"
>>"%LAPORAN%" 2>&1 dir /b /ad "%ProgramFiles%\Python*"
>>"%LAPORAN%" echo.
>>"%LAPORAN%" echo --- PATH dan PATHEXT ---
>>"%LAPORAN%" 2>&1 set PATH
>>"%LAPORAN%" echo.
>>"%LAPORAN%" echo --- versi aplikasi ---
>>"%LAPORAN%" 2>&1 git -C "%~dp0" log -1 --oneline

echo Selesai.
echo Berkas laporan: %LAPORAN%
echo Silakan kirim isi berkas tersebut kepada petugas IT/developer.
echo.
pause
exit /b 0
