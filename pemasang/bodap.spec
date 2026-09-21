# -*- mode: python ; coding: utf-8 -*-
"""Berkas spec PyInstaller untuk membangun **bodap.exe** (pemasang SM satu berkas).

Cara membangun (di komputer Windows yang ada internet)::

    build_windows.bat                 # dari folder pemasang\\  (lihat BUAT-BODAP.bat)
    # atau langsung:
    python pemasang/buat_payload.py --dengan-python
    pyinstaller --noconfirm pemasang/bodap.spec

Hasil: ``dist/bodap.exe`` — satu berkas berisi program SM, Python bawaan Windows, dan
berkas pip (bootstrap). Di komputer tujuan cukup klik dua kali berkas itu.

Isi ``datas`` di bawah ini di-*bundle* ke dalam EXE:

* ``pemasang/payload/``      → ``payload/`` (app.zip, python-embed.zip, bootstrap, wheels)
* ``pemasang/bodap.ico``     → ikon EXE, pintasan desktop, dan jendela wizard
* ``pemasang/BODAP_VERSI.txt`` → ``BODAP_VERSI.txt`` (ditampilkan di wizard & log)
"""

import os
from pathlib import Path

AKAR = Path(os.environ.get("SM_AKAR") or os.path.abspath(os.path.join(SPECPATH, "..")))
PAYLOAD = AKAR / "pemasang" / "payload"

datas = []
if PAYLOAD.is_dir():
    datas.append((str(PAYLOAD), "payload"))
ikon = AKAR / "pemasang" / "bodap.ico"
versi = AKAR / "pemasang" / "BODAP_VERSI.txt"
if ikon.exists():
    datas.append((str(ikon), "."))
if versi.exists():
    datas.append((str(versi), "."))

a = Analysis(
    [str(AKAR / "pemasang" / "bodap_win.py")],
    pathex=[str(AKAR)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
        "tkinter.constants", "tkinter.font",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # aplikasi SM dijalankan dari app.zip oleh Python bawaan — tidak perlu di dalam EXE
        "app", "scripts", "fastapi", "uvicorn", "jinja2", "openpyxl", "selenium",
        "numpy", "pandas", "matplotlib", "PIL",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="bodap",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # pemasangan lewat jendela (wizard) — tanpa jendela hitam
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ikon) if ikon.exists() else None,
    version=None,
)
