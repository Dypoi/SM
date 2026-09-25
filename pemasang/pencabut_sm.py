#!/usr/bin/env python3
"""Pencabut SM + pendaftaran di **Control Panel → Programs and Features** (Windows).

Berkas ini dipakai dua pemasang sekaligus: ``pemasang/bodap_win.py`` (bodap.exe) dan
``pemasang/pasang.py`` (pemasang lintas sistem). Isinya hanya memakai pustaka bawaan Python,
supaya tetap bisa dipakai walaupun aplikasi SM sendiri belum terpasang.

Yang penting di sini:

* **Entri Control Panel** ditulis di registry ``HKCU\\...\\Uninstall\\SM`` (tanpa hak admin)
  lengkap dengan ``DisplayName``, ``DisplayVersion``, ``Publisher``, ``InstallLocation``,
  ``UninstallString``, ``QuietUninstallString``, ``DisplayIcon``, dan ukuran terpasang —
  itulah yang dibaca *Control Panel → Programs and Features* dan *Pengaturan → Aplikasi*.
  Tanpa ``DisplayName`` (dan tanpa `UninstallString`) entri tidak muncul atau tidak bisa dipakai.
* **Berkas pencabut** (``Hapus-SM.cmd`` + ``Hapus-SM.vbs``) disimpan **di luar** folder
  aplikasi, yaitu ``%LOCALAPPDATA%\\Programs\\SM-Pencabut``. Bila berkas pencabut hanya ada di
  dalam folder aplikasi, entri Control Panel jadi tidak berguna begitu folder itu dibuang
  orang (atau gagal dihapus sendiri) — karena itu ada salinan di luar.
* Pencabut **tidak pernah menghapus data sekolah**: hanya program, pintasan, pendaftaran
  aplikasi, dan berkas pencabutnya sendiri. Folder data disebutkan pada pesan penutup.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: Nama yang tampil di Control Panel / Pengaturan → Aplikasi.
NAMA_APLIKASI = "SM — Sistem Informasi Manajemen Sekolah"

#: Kunci registry «Aplikasi & Fitur» (HKCU = tanpa hak admin, tampil untuk pengguna itu).
KUNCI_ARP = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SM"

#: Nama berkas pencabut (dipakai UninstallString).
NAMA_CMD = "Hapus-SM.cmd"
NAMA_VBS = "Hapus-SM.vbs"


# --------------------------------------------------------------------------- #
# Lokasi
# --------------------------------------------------------------------------- #
def folder_pencabut() -> Path:
    """Folder pencabut **di luar** folder aplikasi (lihat penjelasan di kepala berkas)."""
    dari_env = os.environ.get("SM_PENCABUT_DIR")
    if dari_env:
        return Path(dari_env).expanduser()
    if os.name == "nt":
        dasar = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(dasar) / "Programs" / "SM-Pencabut"
    dasar = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(dasar) / "SM-Pencabut"


def _wscript() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"


def _reg() -> str:
    if os.name != "nt":
        return "reg"
    ada = shutil.which("reg")
    if ada:
        return ada
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "reg.exe")


def ukuran_kb(tujuan: Path) -> int:
    """Ukuran folder aplikasi dalam KB (dipakai Control Panel untuk kolom «Ukuran»)."""
    try:
        return sum(p.stat().st_size for p in Path(tujuan).rglob("*") if p.is_file()) // 1024
    except OSError:
        return 0


# --------------------------------------------------------------------------- #
# Entri Control Panel
# --------------------------------------------------------------------------- #
def nilai_arp(tujuan, data=None, versi: str = "", ikon=None, pencabut=None
              ) -> dict[str, tuple[str, object]]:
    """Nilai registry untuk Control Panel (fungsi murni supaya bisa diperiksa uji otomatis).

    Mengembalikan ``{nama: (jenis_registry, isi)}``.
    """
    tujuan = Path(tujuan)
    pencabut_dir = Path(pencabut or folder_pencabut())
    vbs = pencabut_dir / NAMA_VBS
    data_dir = Path(data) if data else tujuan / "data"
    nilai: dict[str, tuple[str, object]] = {
        "DisplayName": ("REG_SZ", NAMA_APLIKASI),
        "DisplayVersion": ("REG_SZ", versi or "0"),
        "Publisher": ("REG_SZ", "SM — aplikasi sekolah"),
        "InstallLocation": ("REG_SZ", str(tujuan)),
        "InstallDate": ("REG_SZ", time.strftime("%Y%m%d")),
        "UninstallString": ("REG_SZ", f'"{_wscript()}" "{vbs}"'),
        "QuietUninstallString": ("REG_SZ", f'"{_wscript()}" "{vbs}" sunyi'),
        "NoModify": ("REG_DWORD", 1),
        "NoRepair": ("REG_DWORD", 1),
        "Comments": ("REG_SZ", f"Data sekolah ada di {data_dir} dan tidak dihapus "
                               "saat aplikasi dicabut."),
    }
    ikon_ada = Path(ikon) if ikon else None
    if ikon_ada and ikon_ada.exists():
        nilai["DisplayIcon"] = ("REG_SZ", str(ikon_ada))
    elif (tujuan / "bodap.ico").exists():
        nilai["DisplayIcon"] = ("REG_SZ", str(tujuan / "bodap.ico"))
    return nilai


def perintah_registri(nilai: dict[str, tuple[str, object]], kunci: str = KUNCI_ARP
                      ) -> list[list[str]]:
    """Perintah ``reg`` (tanpa kata ``reg`` di depan) untuk menulis nilai Control Panel."""
    perintah = [["add", kunci, "/f"]]
    for nama, (jenis, isi) in nilai.items():
        perintah.append(["add", kunci, "/v", nama, "/t", jenis, "/d", str(isi), "/f"])
    return perintah


def daftarkan(tujuan, data=None, versi: str = "", ikon=None, pencabut=None) -> list[str]:
    """Tulis entri Control Panel. Mengembalikan daftar kunci yang ditulis (kosong = gagal)."""
    if os.name != "nt":
        return []
    tujuan = Path(tujuan)
    nilai = nilai_arp(tujuan, data, versi, ikon, pencabut)
    ukuran = ukuran_kb(tujuan)
    if ukuran:
        nilai["EstimatedSize"] = ("REG_DWORD", ukuran)
    reg = _reg()
    for perintah in perintah_registri(nilai):
        try:
            hasil = subprocess.run([reg, *perintah], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=120,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            return []
        if hasil.returncode != 0:
            return []
    return [KUNCI_ARP]


def hapus_pendaftaran(kunci: str = KUNCI_ARP) -> bool:
    """Buang entri Control Panel. ``True`` bila entri memang sudah tidak ada."""
    if os.name != "nt":
        return False
    try:
        hasil = subprocess.run([_reg(), "delete", kunci, "/f"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return False
    return hasil.returncode == 0


def terdaftar(kunci: str = KUNCI_ARP) -> bool:
    """Apakah SM terdaftar di Control Panel (dipakai ``--periksa``)."""
    if os.name != "nt":
        return False
    try:
        hasil = subprocess.run([_reg(), "query", kunci, "/v", "DisplayName"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return False
    return hasil.returncode == 0


# --------------------------------------------------------------------------- #
# Berkas pencabut
# --------------------------------------------------------------------------- #
def isi_skrip(tujuan, data, python, pythonw, pencabut) -> dict[str, str]:
    """Isi ``Hapus-SM.cmd`` (pekerja) & ``Hapus-SM.vbs`` (tanpa jendela) — teks siap tulis."""
    tujuan = Path(tujuan)
    data = Path(data)
    pencabut = Path(pencabut)
    python = Path(python)
    pythonw = Path(pythonw)

    # -- Hapus-SM.cmd ------------------------------------------------------- #
    cmd = (
        "@echo off\r\n"
        "REM Dibuat oleh pemasang SM — mencabut aplikasi SM. Data sekolah TIDAK dihapus.\r\n"
        f"REM SM_TUJUAN={tujuan}\r\n"
        "setlocal EnableExtensions\r\n"
        "chcp 65001 >nul 2>nul\r\n"
        "set \"SUNYI=%~1\"\r\n"
        f"set \"SM_TUJUAN={tujuan}\"\r\n"
        f"set \"SM_PENCABUT={pencabut}\"\r\n"
        f"set \"SM_DATA={data}\"\r\n"
        f"set \"PY={python}\"\r\n"
        f"set \"PYW={pythonw}\"\r\n"
        "if /i \"%SUNYI%\"==\"sunyi\" goto :kerja\r\n"
        "echo ============================================================\r\n"
        "echo   Mencabut aplikasi SM dari komputer ini\r\n"
        "echo ============================================================\r\n"
        "echo   Data sekolah TIDAK dihapus. Folder data:\r\n"
        "echo   \"%SM_DATA%\"\r\n"
        "echo.\r\n"
        "echo   Mematikan aplikasi SM bila sedang berjalan ...\r\n"
        ":kerja\r\n"
        "if exist \"%PYW%\" \"%PYW%\" \"%SM_TUJUAN%\\SM-latar.py\" --hentikan >nul 2>nul\r\n"
        "if not exist \"%PYW%\" if exist \"%PY%\" \"%PY%\" \"%SM_TUJUAN%\\SM-latar.py\" --hentikan "
        ">nul 2>nul\r\n"
        "if /i \"%SUNYI%\"==\"sunyi\" goto :bersih\r\n"
        "echo   Membersihkan pendaftaran aplikasi & pintasan ...\r\n"
        ":bersih\r\n"
        "reg delete \"" + KUNCI_ARP + "\" /f >nul 2>nul\r\n"
        "del /q \"%USERPROFILE%\\Desktop\\SM.lnk\" >nul 2>nul\r\n"
        "del /q \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\SM.lnk\" >nul 2>nul\r\n"
        "del /q \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\SM.cmd\" "
        ">nul 2>nul\r\n"
        "if /i \"%SUNYI%\"==\"sunyi\" goto :pesan_berkas\r\n"
        "echo   Menghapus berkas aplikasi ...\r\n"
        ":pesan_berkas\r\n"
        "> \"%TEMP%\\sm-hapus.cmd\" (\r\n"
        "  echo @echo off\r\n"
        "  echo timeout /t 3 /nobreak ^>nul\r\n"
        "  echo rmdir /s /q \"%SM_TUJUAN%\"\r\n"
        "  echo rmdir /s /q \"%SM_PENCABUT%\"\r\n"
        ")\r\n"
        "if /i \"%SUNYI%\"==\"sunyi\" exit /b 0\r\n"
        ">> \"%TEMP%\\sm-hapus.cmd\" (\r\n"
        "  echo echo.\r\n"
        "  echo echo Aplikasi SM sudah dicabut.\r\n"
        "  echo echo Data sekolah tetap ada di: %SM_DATA%\r\n"
        "  echo pause\r\n"
        ")\r\n"
        "start \"\" /min cmd /c \"%TEMP%\\sm-hapus.cmd\"\r\n"
        "echo.\r\n"
        "echo Aplikasi SM sedang dicabut di belakang layar (beberapa detik).\r\n"
        "echo Data sekolah tetap ada di: \"%SM_DATA%\"\r\n"
        "timeout /t 3 /nobreak >nul\r\n"
        "exit /b 0\r\n")

    # -- Hapus-SM.vbs ------------------------------------------------------- #
    vbs = (
        "' Dibuat oleh pemasang SM — pencabut tanpa jendela.\r\n"
        "' Dipakai oleh Control Panel / Pengaturan → Aplikasi (UninstallString) dan oleh\r\n"
        "' berkas Hapus-SM.cmd di folder aplikasi.\r\n"
        "' Pakai: wscript.exe Hapus-SM.vbs [sunyi]\r\n"
        f"' SM_TUJUAN={tujuan}\r\n"
        "Option Explicit\r\n"
        "Dim fso, sh, folder, cmd, deleter, sunyi, pesan\r\n"
        "Set fso = CreateObject(\"Scripting.FileSystemObject\")\r\n"
        "Set sh = CreateObject(\"WScript.Shell\")\r\n"
        "folder = fso.GetParentFolderName(WScript.ScriptFullName)\r\n"
        "sunyi = False\r\n"
        "If WScript.Arguments.Count > 0 Then\r\n"
        "  If LCase(Trim(WScript.Arguments(0))) = \"sunyi\" Then sunyi = True\r\n"
        "End If\r\n"
        f"cmd = \"{pencabut}\\{NAMA_CMD}\"\r\n"
        "If Not fso.FileExists(cmd) Then cmd = folder & \"\\" + NAMA_CMD + "\"\r\n"
        "If Not fso.FileExists(cmd) Then\r\n"
        "  MsgBox \"Berkas pencabut SM tidak ditemukan.\" & vbCrLf & vbCrLf & _\r\n"
        "         \"Hapus folder aplikasi ini secara manual:\" & vbCrLf & _\r\n"
        f"         \"{tujuan}\", 16, \"SM\"\r\n"
        "  WScript.Quit 1\r\n"
        "End If\r\n"
        "sh.Run \"cmd /c \"\"\" & cmd & \"\"\" sunyi\", 0, True\r\n"
        "deleter = sh.ExpandEnvironmentStrings(\"%TEMP%\") & \"\\sm-hapus.cmd\"\r\n"
        "If fso.FileExists(deleter) Then\r\n"
        "  sh.Run \"cmd /c \"\"\" & deleter & \"\"\"\", 0, False\r\n"
        "  WScript.Sleep 7000\r\n"
        "End If\r\n"
        "If sunyi Then WScript.Quit 0\r\n"
        "pesan = \"Aplikasi SM sudah dicabut dari komputer ini.\" & vbCrLf & vbCrLf & _\r\n"
        "        \"Data sekolah tetap ada di:\" & vbCrLf & _\r\n"
        f"        \"{data}\"\r\n"
        f"If fso.FolderExists(\"{tujuan}\") Then\r\n"
        "  pesan = pesan & vbCrLf & vbCrLf & _\r\n"
        "          \"Sebagian berkas masih terkunci (aplikasi mungkin baru saja berhenti). \" & _\r\n"
        "          \"Hapus folder ini nanti secara manual:\" & vbCrLf & _\r\n"
        f"          \"{tujuan}\"\r\n"
        "End If\r\n"
        "MsgBox pesan, 64, \"SM — pencabutan\"\r\n")

    return {NAMA_CMD: cmd, NAMA_VBS: vbs}


def tulis_pencabut(tujuan, data, python, pythonw=None, pencabut=None) -> dict:
    """Tulis berkas pencabut ke folder pencabut (luar) **dan** ke folder aplikasi."""
    tujuan = Path(tujuan)
    folder = Path(pencabut or folder_pencabut())
    isi = isi_skrip(tujuan, data, python, pythonw or python, folder)
    berkas: list[str] = []
    for tempat in (folder, tujuan):
        try:
            tempat.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for nama, teks in isi.items():
            try:
                (tempat / nama).write_text(teks, encoding="utf-8", newline="")
                berkas.append(str(tempat / nama))
            except OSError:
                continue
    return {"folder": str(folder), "berkas": berkas,
            "cmd": str(folder / NAMA_CMD), "vbs": str(folder / NAMA_VBS)}


def folder_milik(tujuan, pencabut=None) -> str:
    """Folder pencabut yang **milik pemasangan ini** (isi skripnya menyebut folder aplikasi).

    Dipakai saat mencabut: kalau SM terpasang dua kali di komputer yang sama, pencabut milik
    pemasangan lain tidak boleh ikut dibuang.
    """
    folder = Path(pencabut or folder_pencabut())
    try:
        isi = (folder / NAMA_VBS).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tujuan = str(Path(tujuan))
    # Penanda pasti: «SM_TUJUAN=<folder aplikasi>» (ditulis pencabut versi ini). Cadangannya
    # pencocokan jalur dengan batas kata — pencocokan substring biasa salah: jalur
    # «…\SM» juga cocok di dalam «…\SM-lain».
    if re.search(r"SM_TUJUAN=" + re.escape(tujuan) + r"(?![0-9A-Za-z._-])", isi):
        return str(folder)
    if re.search(re.escape(tujuan) + r"[\\/]", isi):
        return str(folder)
    return ""


def hapus_folder_pencabut(tujuan, pencabut=None) -> str:
    """Buang folder pencabut bila memang milik pemasangan ini. Mengembalikan jalurnya."""
    jalur = folder_milik(tujuan, pencabut)
    if not jalur:
        return ""
    shutil.rmtree(jalur, ignore_errors=True)
    return "" if Path(jalur).exists() else jalur


def main(argv: list[str] | None = None) -> int:
    """Utilitas kecil: ``python pemasang/pencabut_sm.py informasi`` (untuk pemeriksaan)."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Pencabut SM & entri Control Panel")
    parser.add_argument("perintah", choices=["informasi"], nargs="?", default="informasi")
    parser.add_argument("--tujuan", default="")
    parser.add_argument("--data", default="")
    args = parser.parse_args(argv)
    if args.perintah == "informasi":
        tujuan = Path(args.tujuan) if args.tujuan else Path(sys.argv[0]).resolve().parent
        print(json.dumps({
            "folder_pencabut": str(folder_pencabut()),
            "kunci_control_panel": KUNCI_ARP,
            "terdaftar": terdaftar(),
            "nilai": {nama: isi for nama, (_jenis, isi) in
                      nilai_arp(tujuan, args.data or None).items()},
        }, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
