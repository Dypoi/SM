#!/usr/bin/env python3
"""bodap — pemasang SM satu berkas untuk Windows (Next → Next → Install → Finish).

Berkas ini adalah **mesin pemasangan** sekaligus **wizard**-nya. Setelah dibungkus
PyInstaller menjadi ``bodap.exe`` (lihat ``pemasang/bodap.spec``), seluruh isi paket ikut
di dalam satu berkas itu:

* ``payload/app.zip``          — seluruh program SM (tanpa data siswa);
* ``payload/python-embed.zip`` — Python bawaan (bila ada) sehingga komputer tujuan
  **tidak perlu** memasang Python sendiri;
* ``payload/bootstrap/*.whl``  — pip & setuptools untuk menyiapkan pip pada Python bawaan.

Cara pakai:

* **Klik dua kali** ``bodap.exe`` → wizard: Sambutan → Folder & pilihan → Proses → Selesai,
  lengkap dengan ikon **SM** di Desktop.
* **Tanpa wizard** (untuk skrip/uji otomatis)::

      bodap.exe --sunyi --tujuan C:\\SM --data C:\\SM\\data --port 8000
      bodap.exe --periksa
      bodap.exe --hapus --tujuan C:\\SM --data C:\\SM\\data --ya

Semua langkah ada di kelas :class:`Pemasang`, sehingga jalur wizard dan jalur sunyi
memakai logika yang sama — yang diuji otomatis pun persis yang dijalankan pengguna.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

VERSI_MINIMUM = (3, 10)
NAMA_MARKER = ".sm-pemasangan.json"

#: Folder payload yang dipaksa (dipakai uji otomatis lewat ``--payload``).
_PAYLOAD_PAKSA: Path | None = None


# --------------------------------------------------------------------------- #
# Lokasi berkas bawaan (di dalam EXE, atau folder repo saat dijalankan sebagai skrip)
# --------------------------------------------------------------------------- #
def akar_bawaan() -> Path:
    """Folder tempat berkas bawaan berada (``_MEIPASS`` bila sudah dibungkus EXE)."""
    bawaan = getattr(sys, "_MEIPASS", None)
    if bawaan:
        return Path(bawaan)
    for kandidat in (Path(__file__).resolve().parent / "payload",
                     Path(__file__).resolve().parents[1] / "payload"):
        if (kandidat / "app.zip").exists():
            return kandidat.parent
    return Path(__file__).resolve().parent


def folder_payload(akar: Path | None = None) -> Path:
    """Folder berisi ``app.zip`` (+ ``python-embed.zip``/``bootstrap``/``wheels``)."""
    if _PAYLOAD_PAKSA is not None:
        return _PAYLOAD_PAKSA
    akar = akar or akar_bawaan()
    for kandidat in (akar / "payload", akar):
        if (kandidat / "app.zip").exists():
            return kandidat
    return akar / "payload"


def ada_jendela_gui() -> bool:
    """Bisakah wizard (tkinter) ditampilkan? — tkinter diimpor hanya di sini."""
    try:
        import tkinter  # noqa: F401
    except Exception:      # noqa: BLE001 — tanpa tkinter, jalur sunyi tetap bekerja
        return False
    if os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def tanpa_jendela() -> int:
    """Bendera agar proses anak tidak memunculkan jendela hitam di Windows."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GalatPasang(Exception):
    """Kesalahan yang bisa dijelaskan ke pengguna (bukan bug)."""


# --------------------------------------------------------------------------- #
# Alat bantu
# --------------------------------------------------------------------------- #
def tujuan_bawaan() -> Path:
    if os.name == "nt":
        dasar = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(dasar) / "Programs" / "SM"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "SM"


def _jalankan(perintah: list, cwd: Path | None = None, waktu: int | None = None,
              env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(p) for p in perintah], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=waktu, env=env, creationflags=tanpa_jendela())


def versi_aplikasi(dari: Path) -> str:
    try:
        isi = (Path(dari) / "app" / "config.py").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "?"
    cocok = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', isi)
    return cocok.group(1) if cocok else "?"


def versi_bodap() -> str:
    akar = akar_bawaan()
    for kandidat in (akar / "BODAP_VERSI.txt", akar / "payload" / "VERSI.txt"):
        if kandidat.exists():
            isi = kandidat.read_text(encoding="utf-8", errors="replace").strip()
            if isi:
                return isi
    return versi_aplikasi(folder_payload())


def versi_python(jalur: Path) -> tuple[int, ...]:
    if not jalur or not Path(jalur).exists():
        return ()
    hasil = _jalankan([jalur, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
                      waktu=180)
    if hasil.returncode != 0:
        return ()
    try:
        return tuple(int(x) for x in hasil.stdout.strip().split("."))
    except ValueError:
        return ()


def cari_python() -> tuple[Path, str]:
    """Python 3.10+ yang sudah ada di komputer tujuan (bila ada)."""
    kandidat: list[tuple[Path, str]] = []
    if os.name == "nt":
        peluncur = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "py.exe"
        if peluncur.exists():
            kandidat.append((peluncur, "peluncur py"))
        for nama in ("python.exe", "python3.exe"):
            ada = shutil.which(nama)
            if ada:
                kandidat.append((Path(ada), "PATH"))
        for pola in (r"%LOCALAPPDATA%\Programs\Python",
                     r"%ProgramFiles%", r"%ProgramFiles(x86)%", r"%SystemDrive%"):
            dasar = Path(os.path.expandvars(pola))
            if dasar.is_dir():
                kandidat.extend((p, "folder pemasangan Python")
                                for p in sorted(dasar.glob("Python3*/python.exe"), reverse=True))
    else:
        for nama in ("python3", "python"):
            ada = shutil.which(nama)
            if ada:
                kandidat.append((Path(ada), nama))
    for jalur, sumber in kandidat:
        if versi_python(jalur) >= VERSI_MINIMUM:
            return jalur, sumber
    return Path(), ""


def folder_python(tujuan: Path) -> Path:
    """Python bawaan aplikasi di dalam folder pemasangan (Windows & Linux/macOS)."""
    tujuan = Path(tujuan)
    if os.name == "nt":
        kandidat = sorted((tujuan / "python").glob("python*.exe"))
    else:
        kandidat = sorted((tujuan / "python" / "bin").glob("python3*"))
    return kandidat[0] if kandidat else tujuan / "python" / ("python.exe" if os.name == "nt"
                                                             else "bin/python3")


def python_atau_venv(tujuan: Path) -> Path:
    """Python yang dipakai folder terpasang (bawaan aplikasi → .venv → Python komputer)."""
    bawaan = folder_python(tujuan)
    if bawaan.exists():
        return bawaan
    venv = Path(tujuan) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if venv.exists():
        return venv
    jalur, _ = cari_python()
    return jalur or Path(sys.executable)


def _pip_siap(python: Path) -> bool:
    if not python.exists():
        return False
    return _jalankan([python, "-c", "import pip"], waktu=300).returncode == 0


def _pustaka_kurang(python: Path, paket: tuple[str, ...]) -> list[str]:
    """Nama pustaka yang gagal diimpor oleh ``python`` (dijalankan di proses terpisah)."""
    kode = ("import importlib, json, sys\n"
            "kurang = []\n"
            "for nama in sys.argv[1:]:\n"
            "    try:\n"
            "        importlib.import_module(nama)\n"
            "    except Exception:\n"
            "        kurang.append(nama)\n"
            "print(json.dumps(kurang))\n")
    hasil = _jalankan([python, "-c", kode, *paket], waktu=300)
    if hasil.returncode != 0:
        return list(paket)
    try:
        return list(json.loads(hasil.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return list(paket)


def _ikon_bawaan() -> Path | None:
    for nama in ("bodap.ico", "sm.ico", "bodap.png"):
        jalur = akar_bawaan() / nama
        if jalur.exists():
            return jalur
    return None


def _desktop() -> Path:
    if os.name == "nt":
        try:
            hasil = _jalankan(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                               "[Environment]::GetFolderPath('Desktop')"], waktu=120)
            jalur = (hasil.stdout or "").strip()
            if jalur and Path(jalur).is_dir():
                return Path(jalur)
        except Exception:      # noqa: BLE001
            pass
        return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"
    return Path(os.environ.get("XDG_DESKTOP_DIR") or Path.home() / "Desktop")


def pintasan_sm() -> list[Path]:
    """Semua jalur pintasan yang mungkin dibuat (untuk pembersihan saat menghapus)."""
    jalur: list[Path] = []
    if os.name == "nt":
        jalur.append(_desktop() / "SM.lnk")
        appdata = os.environ.get("APPDATA")
        if appdata:
            jalur.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs/SM.lnk")
    else:
        jalur.append(Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
                     / "applications/sm-sekolah.desktop")
        jalur.append(_desktop() / "SM.desktop")
    return jalur


def buat_peluncur_latar(tujuan: Path, python: Path, data: Path, port: int,
                        ikon: Path | None = None) -> dict:
    """Buat peluncur **tanpa jendela terminal** (SM.vbs) beserta pencabutnya.

    Intinya: ``SM-latar.py`` dijalankan lewat **pythonw.exe** (Python tanpa konsol) sehingga
    aplikasi berjalan di belakang layar — tidak ada jendela hitam yang harus dibiarkan terbuka.
    Pintasan Desktop mengarah ke berkas VBS ini lewat ``wscript.exe``.
    """
    tujuan = Path(tujuan)
    pythonw = python.parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = python
    latar = tujuan / "SM-latar.py"
    if not latar.exists():
        # pemasangan lama (sebelum ada SM-latar.py): salin dari paket bila tersedia
        sumber = folder_payload() / "app.zip"
        if sumber.exists():
            with zipfile.ZipFile(sumber) as z:
                for nama in z.namelist():
                    if nama == "SM-latar.py":
                        (tujuan / nama).write_bytes(z.read(nama))
                        break

    sm_vbs = tujuan / "SM.vbs"
    sm_vbs.write_text(
        "' Dibuat oleh bodap.exe — menjalankan SM di belakang layar (tanpa jendela terminal).\r\n"
        "' Buka aplikasi: klik dua kali berkas ini, atau pintasan «SM» di Desktop.\r\n"
        'Option Explicit\r\n'
        'Dim sh\r\n'
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.CurrentDirectory = "{tujuan}"\r\n'
        f'sh.Run """{pythonw}"" ""{tujuan}\\SM-latar.py"" --port {int(port)}", 0, False\r\n',
        encoding="utf-8")

    hentikan = tujuan / "Hentikan-SM.vbs"
    hentikan.write_text(
        "' Dibuat oleh bodap.exe — mematikan SM yang berjalan di belakang layar.\r\n"
        'Option Explicit\r\n'
        'Dim sh\r\n'
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run """{pythonw}"" ""{tujuan}\\SM-latar.py"" --hentikan", 0, True\r\n',
        encoding="utf-8")

    # Pencabut: matikan dulu, bersihkan pintasan & daftar aplikasi, lalu hapus foldernya
    # dari luar folder itu (folder aplikasi tidak bisa menghapus dirinya sendiri).
    (tujuan / "Hapus-SM.cmd").write_text(
        "@echo off\r\n"
        "REM Menghapus aplikasi SM. Data sekolah TIDAK dihapus.\r\n"
        "setlocal EnableExtensions\r\n"
        "chcp 65001 >nul 2>nul\r\n"
        "cd /d \"%~dp0\"\r\n"
        f"set \"PY={python}\"\r\n"
        f"set \"PYW={pythonw}\"\r\n"
        "set \"SM_DATA=" + str(data) + "\"\r\n"
        "echo Mematikan aplikasi SM bila sedang berjalan ...\r\n"
        "if exist \"%PYW%\" (\"%PYW%\" \"%~dp0SM-latar.py\" --hentikan) else "
        "(\"%PY%\" \"%~dp0SM-latar.py\" --hentikan)\r\n"
        "echo Menghapus pintasan & pendaftaran aplikasi ...\r\n"
        "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SM\" "
        "/f >nul 2>nul\r\n"
        "del /q \"%USERPROFILE%\\Desktop\\SM.lnk\" >nul 2>nul\r\n"
        "del /q \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\SM.lnk\" >nul 2>nul\r\n"
        "echo Menghapus berkas aplikasi ...\r\n"
        "set \"SM_TUJUAN=%~dp0\"\r\n"
        "> \"%TEMP%\\sm-hapus.cmd\" (\r\n"
        "  echo @echo off\r\n"
        "  echo timeout /t 3 /nobreak ^>nul\r\n"
        "  echo rmdir /s /q \"%SM_TUJUAN%\"\r\n"
        "  echo echo Aplikasi SM sudah dihapus. Data sekolah tetap ada di: %SM_DATA%\r\n"
        "  echo pause\r\n"
        ")\r\n"
        "start \"\" /min cmd /c \"%TEMP%\\sm-hapus.cmd\"\r\n"
        "exit /b 0\r\n", encoding="utf-8", newline="")

    (tujuan / "Hapus-SM.vbs").write_text(
        "' Dibuat oleh bodap.exe — pencabut tanpa jendela (dipakai Daftar Aplikasi Windows).\r\n"
        'Option Explicit\r\n'
        'Dim sh\r\n'
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run """{tujuan}\\Hapus-SM.cmd""", 0, False\r\n', encoding="utf-8")

    return {"sm_vbs": str(sm_vbs), "hentikan_vbs": str(hentikan),
            "python_latar": str(pythonw)}


def daftarkan_aplikasi(tujuan: Path, ikon: Path | None, versi: str) -> list[str]:
    """Daftarkan di «Pengaturan → Aplikasi» Windows (HKCU — tanpa hak admin)."""
    if os.name != "nt":
        return []
    kunci = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SM"
    nilai = {
        "DisplayName": "SM — Sistem Informasi Manajemen Sekolah",
        "DisplayVersion": versi or "0",
        "Publisher": "SM",
        "InstallLocation": str(tujuan),
        "UninstallString": f'wscript.exe "{Path(tujuan) / "Hapus-SM.vbs"}"',
        "QuietUninstallString": f'wscript.exe "{Path(tujuan) / "Hapus-SM.vbs"}"',
        "NoModify": "1",
        "NoRepair": "1",
    }
    if ikon:
        nilai["DisplayIcon"] = str(ikon)
    skrip = ["$ErrorActionPreference = 'SilentlyContinue'",
             f"New-Item -Path '{kunci}' -Force | Out-Null"]
    for nama, isi in nilai.items():
        skrip.append(f"New-ItemProperty -Path '{kunci}' -Name '{nama}' "
                     f"-Value '{isi}' -PropertyType String -Force | Out-Null")
    try:
        ukuran = sum(p.stat().st_size for p in Path(tujuan).rglob("*") if p.is_file()) // 1024
        skrip.append(f"New-ItemProperty -Path '{kunci}' -Name 'EstimatedSize' "
                     f"-Value {ukuran} -PropertyType DWord -Force | Out-Null")
    except OSError:
        pass
    hasil = _jalankan(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                       "; ".join(skrip)], waktu=180)
    if hasil.returncode != 0:
        return []
    return [kunci]


def buat_pintasan(tujuan: Path, ikon: Path | None = None) -> list[str]:
    """Ikon di Desktop & menu Start (Windows) atau berkas .desktop (Linux/macOS)."""
    tujuan = Path(tujuan)
    peluncur = tujuan / "Jalankan-SM.cmd"
    if not peluncur.exists():
        peluncur = tujuan / "SM.cmd"
    dibuat: list[str] = []

    if os.name == "nt":
        vbs = tujuan / "SM.vbs"
        wscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"
        jalankan = f'"{wscript}" "{vbs}"' if vbs.exists() else f'"{peluncur}"'
        sasaran_daftar = [("Desktop", _desktop() / "SM.lnk")]
        appdata = os.environ.get("APPDATA")
        if appdata:
            sasaran_daftar.append(
                ("menu Start", Path(appdata) / "Microsoft/Windows/Start Menu/Programs/SM.lnk"))
        for nama, sasaran in sasaran_daftar:
            try:
                sasaran.parent.mkdir(parents=True, exist_ok=True)
                ikon_baris = f"$s.IconLocation = '{ikon}'; " if ikon else ""
                if vbs.exists():
                    # Lewat wscript + SM.vbs: aplikasi jalan di belakang layar —
                    # tidak ada jendela terminal sekejap pun.
                    target, argumen = str(wscript), f'"{vbs}"'
                else:
                    target, argumen = str(peluncur), ""
                skrip = (
                    "$w = New-Object -ComObject WScript.Shell; "
                    f"$s = $w.CreateShortcut('{sasaran}'); "
                    f"$s.TargetPath = '{target}'; "
                    f"$s.Arguments = '{argumen}'; "
                    f"$s.WorkingDirectory = '{tujuan}'; "
                    "$s.WindowStyle = 1; "
                    "$s.Description = 'SM - Sistem Informasi Manajemen Sekolah'; "
                    f"{ikon_baris}$s.Save()")
                hasil = _jalankan(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                   skrip], waktu=180)
                if hasil.returncode == 0 and sasaran.exists():
                    dibuat.append(f"{nama}: {sasaran}")
            except Exception as exc:      # noqa: BLE001 — jangan gagalkan pemasangan
                print(f"[!] Pintasan {nama} gagal dibuat: {exc}")
        return dibuat

    aplikasi = pintasan_sm()[0]
    aplikasi.parent.mkdir(parents=True, exist_ok=True)
    aplikasi.write_text(
        "[Desktop Entry]\nType=Application\n"
        "Name=SM - Sistem Informasi Manajemen Sekolah\n"
        f"Exec={peluncur}\nPath={tujuan}\nTerminal=true\nCategories=Office;Education;\n",
        encoding="utf-8")
    aplikasi.chmod(0o755)
    dibuat.append(str(aplikasi))
    desktop = _desktop()
    if desktop.is_dir():
        pintasan = desktop / "SM.desktop"
        shutil.copy2(aplikasi, pintasan)
        pintasan.chmod(0o755)
        dibuat.append(str(pintasan))
    return dibuat


def pasang_otomatis(tujuan: Path) -> list[str]:
    """Jalankan SM otomatis saat komputer dinyalakan (Windows)."""
    if os.name != "nt":
        return []
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    berkas = Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup/SM.cmd"
    berkas.parent.mkdir(parents=True, exist_ok=True)
    berkas.write_text(
        "@echo off\r\n"
        "REM Dibuat oleh bodap.exe — SM menyala otomatis saat Windows masuk.\r\n"
        f"start \"SM\" /min \"{Path(tujuan) / 'Jalankan-SM.cmd'}\"\r\n",
        encoding="utf-8", newline="")
    return [str(berkas)]


def berkas_otomatis() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup/SM.cmd"
    return None


# --------------------------------------------------------------------------- #
# Mesin pemasangan
# --------------------------------------------------------------------------- #
class Pemasang:
    """Seluruh langkah pemasangan — dipakai wizard maupun jalur sunyi."""

    LANGKAH = 7

    def __init__(self, tujuan: Path, data: Path, port: int = 8000, dengan_bot: bool = False,
                 pintasan: bool = True, otomatis: bool = False, payload: Path | None = None,
                 python_bawaan: bool = True, izinkan_unduh_python: bool = False,
                 daftar_aplikasi: bool = True, ekskul_contoh: bool = False,
                 catat=None, maju=None, berhenti=None) -> None:
        self.tujuan = Path(tujuan)
        self.data = Path(data)
        self.port = int(port)
        self.dengan_bot = bool(dengan_bot)
        self.pintasan = bool(pintasan)
        self.otomatis = bool(otomatis)
        self.payload = Path(payload) if payload else folder_payload()
        self.python_bawaan = bool(python_bawaan)
        self.izinkan_unduh_python = bool(izinkan_unduh_python)
        self.daftar_aplikasi = bool(daftar_aplikasi)
        self.ekskul_contoh = bool(ekskul_contoh)
        self._catat = catat or (lambda pesan: None)
        self._maju = maju or (lambda langkah, persen: None)
        self._berhenti = berhenti or (lambda: False)
        self.python: Path = Path()

    # -- pelaporan ---------------------------------------------------------- #
    def catat(self, pesan: str) -> None:
        self._catat(pesan)

    def maju(self, langkah: int, persen: int | None = None) -> None:
        persen = persen if persen is not None else int(langkah / self.LANGKAH * 100)
        self._maju(langkah, min(100, persen))

    def cek_batal(self) -> None:
        if self._berhenti():
            raise GalatPasang("Pemasangan dibatalkan.")

    # -- langkah 1: periksa -------------------------------------------------- #
    def periksa_awal(self) -> None:
        self.maju(0, 2)
        self.catat(f"Versi bodap   : {versi_bodap()}")
        self.catat(f"Folder paket  : {self.payload}")
        if not (self.payload / "app.zip").exists():
            raise GalatPasang(
                "Isi paket tidak lengkap: payload/app.zip tidak ada di dalam berkas ini.\n"
                "Unduh ulang bodap.exe (atau buat sendiri dengan pemasang\\BUAT-BODAP.bat).")
        self.catat(f"Folder tujuan : {self.tujuan}")
        self.catat(f"Folder data   : {self.data}")
        if self.tujuan.exists() and any(self.tujuan.iterdir()):
            punya_kita = ((self.tujuan / NAMA_MARKER).exists()
                          or (self.tujuan / "run.py").exists())
            if not punya_kita:
                raise GalatPasang(
                    f"Folder tujuan sudah berisi berkas lain:\n{self.tujuan}\n"
                    "Pilih folder lain supaya tidak ada berkas yang tertimpa.")
            self.catat("Pemasangan SM sebelumnya ditemukan — kode akan diperbarui, "
                       "data sekolah tidak diubah.")
        if str(self.data).startswith(str(self.tujuan)):
            self.catat("Catatan: folder data berada di dalam folder aplikasi. Aman, tetapi "
                       "menyimpan data di folder terpisah (mis. Drive) lebih tahan terhadap "
                       "penghapusan aplikasi.")

    # -- langkah 2: salin program ------------------------------------------- #
    def salin_program(self) -> int:
        self.cek_batal()
        self.maju(1, 12)
        self.catat("Menyalin program SM ...")
        baru = not (self.tujuan / "run.py").exists()
        self.tujuan.mkdir(parents=True, exist_ok=True)
        jumlah = 0
        with zipfile.ZipFile(self.payload / "app.zip") as z:
            for info in z.infolist():
                nama = info.filename
                if not nama or nama.endswith("/"):
                    continue
                keluar = self.tujuan / nama
                keluar.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as sumber, open(keluar, "wb") as sasaran:
                    shutil.copyfileobj(sumber, sasaran)
                jumlah += 1
        if not (self.tujuan / "run.py").exists():
            raise GalatPasang("Penyalinan gagal: run.py tidak ada setelah program disalin.")
        self.catat(f"{jumlah} berkas program disalin."
                   + ("  (pemasangan baru)" if baru else "  (memperbarui pemasangan lama)"))
        return jumlah

    # -- langkah 3: Python --------------------------------------------------- #
    def siapkan_python(self) -> tuple[Path, str]:
        """Python untuk menjalankan SM: bawaan paket, Python komputer, atau unduhan."""
        self.cek_batal()
        self.maju(2, 30)

        # (a) Python bawaan dari pemasangan sebelumnya
        bawaan = folder_python(self.tujuan)
        if bawaan.exists() and versi_python(bawaan) >= VERSI_MINIMUM:
            self.catat(f"Python bawaan aplikasi sudah ada: {bawaan}")
            self._pasang_pip_bila_perlu(bawaan)
            return bawaan, "bawaan aplikasi"

        # (b) Python bawaan di dalam paket
        embed = self.payload / "python-embed.zip"
        if self.python_bawaan and embed.exists():
            self.catat("Menyiapkan Python bawaan aplikasi "
                       "(Python milik komputer ini tidak diubah) ...")
            target = self.tujuan / "python"
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(embed) as z:
                z.extractall(target)
            self._aktifkan_site(target)
            python = folder_python(self.tujuan)
            self._tanam_pip(target, python)
            self.catat(f"Python bawaan siap: {python} ({'.'.join(str(x) for x in versi_python(python))})")
            return python, "bawaan aplikasi"

        # (c) Python yang sudah ada di komputer tujuan → dipakai lewat .venv pribadi aplikasi.
        #     Alasannya penting: memasang pustaka langsung ke Python milik komputer bisa
        #     ditolak sistem (PEP 668 «externally-managed-environment» di Linux) atau mengotori
        #     Python pengguna. .venv membuat pemasangan ini mandiri & aman.
        jalur, sumber = cari_python()
        if jalur:
            self.catat(f"Memakai Python komputer ini ({sumber}): {jalur}")
            venv_py = self._siapkan_venv(jalur)
            if venv_py:
                return venv_py, f"{sumber} + .venv aplikasi"
            if not _pip_siap(jalur):
                self.catat("Menyiapkan pip pada Python komputer ...")
                _jalankan([jalur, "-m", "ensurepip", "--default-pip"], waktu=1200)
            return jalur, sumber

        # (d) unduh Python (perlu internet, hanya bila disetujui)
        if self.izinkan_unduh_python:
            return self._unduh_python(), "unduhan python.org"
        raise GalatPasang(
            "Komputer ini belum punya Python 3.10+ dan paket ini tidak membawa Python bawaan.\n"
            "Langkah pilihan:\n"
            "  * centang «Bila perlu, unduh Python dari python.org» pada wizard, lalu jalankan lagi;\n"
            "  * atau pasang Python manual dari https://www.python.org/downloads/ "
            "(centang «Add python.exe to PATH»).")

    def _siapkan_venv(self, python: Path) -> Path:
        """Buat ``.venv`` pribadi aplikasi dari Python komputer (aman & mandiri).

        Bila tak bisa dibuat (mis. modul ``venv`` tidak ada), kembalikan ``Path()`` supaya
        pemanggil memakai Python komputer apa adanya.
        """
        venv_dir = self.tujuan / ".venv"
        venv_py = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if venv_py.exists() and versi_python(venv_py) >= VERSI_MINIMUM:
            self.catat(f"Lingkungan pribadi aplikasi (.venv) sudah ada: {venv_py}")
            return venv_py
        self.catat("Membuat lingkungan pribadi aplikasi (.venv) agar Python komputer "
                   "tidak diubah ...")
        hasil = _jalankan([python, "-m", "venv", str(venv_dir)], waktu=1800)
        if hasil.returncode != 0 or not venv_py.exists():
            self.catat("[!] .venv tidak bisa dibuat — memakai Python komputer apa adanya.")
            return Path()
        if not _pip_siap(venv_py):
            _jalankan([venv_py, "-m", "ensurepip", "--default-pip"], waktu=1800)
        self.catat(f"Lingkungan pribadi aplikasi siap: {venv_py}")
        return venv_py

    def _aktifkan_site(self, target: Path) -> None:
        """Izinkan Python bawaan memuat paket dari ``Lib\\site-packages`` (berkas ``._pth``)."""
        for pth in list(target.glob("python*._pth")) + list(target.glob("*._pth")):
            baris = [b.rstrip("\r") for b in pth.read_text(encoding="utf-8").splitlines()]
            bersih = [b.strip() for b in baris]
            if "import site" not in bersih:
                baris = [b for b in baris if b.strip() != "#import site"]
                baris.append("import site")
            if "Lib\\site-packages" not in bersih:
                baris.append("Lib\\site-packages")
            pth.write_text("\n".join(baris) + "\n", encoding="utf-8")
            self.catat(f"Python bawaan disiapkan untuk memuat pustaka ({pth.name}).")

    def _pasang_pip_bila_perlu(self, python: Path) -> None:
        if not _pip_siap(python):
            self._tanam_pip(python.parent, python)

    def _tanam_pip(self, target: Path, python: Path) -> None:
        """Tanam pip dari berkas .whl bawaan — tanpa internet."""
        if _pip_siap(python):
            return
        site = target / "Lib" / "site-packages"
        site.mkdir(parents=True, exist_ok=True)
        dipasang = 0
        for whl in sorted((self.payload / "bootstrap").glob("*.whl")):
            self.catat(f"Menanam {whl.name} ...")
            with zipfile.ZipFile(whl) as z:
                z.extractall(site)
            dipasang += 1
        if not dipasang:
            raise GalatPasang("Berkas pip bawaan (payload/bootstrap/*.whl) tidak ada di paket.")
        if not _pip_siap(python):
            raise GalatPasang("Pip belum bisa dipakai pada Python bawaan aplikasi.")

    def _unduh_python(self) -> Path:
        import urllib.request

        rilis = "3.12.8"
        nama = (f"python-{rilis}-embed-amd64.zip" if _windows_64bit()
                else f"python-{rilis}-embed-win32.zip")
        alamat = f"https://www.python.org/ftp/python/{rilis}/{nama}"
        sementara = self.tujuan / nama
        self.catat(f"Mengunduh Python {rilis} dari python.org (perlu internet) ...")
        try:
            urllib.request.urlretrieve(alamat, sementara)
        except Exception as exc:      # noqa: BLE001
            raise GalatPasang(
                f"Unduhan Python gagal ({type(exc).__name__}: {exc}).\n"
                "Periksa sambungan internet, atau pasang Python manual dari "
                "https://www.python.org/downloads/ lalu jalankan bodap.exe lagi.") from exc
        target = self.tujuan / "python"
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(sementara) as z:
            z.extractall(target)
        self._aktifkan_site(target)
        python = folder_python(self.tujuan)
        self._tanam_pip(target, python)
        return python

    # -- langkah 4: pustaka -------------------------------------------------- #
    def pasang_pustaka(self, python: Path) -> str:
        """Pasang pustaka aplikasi — berkas bawaan dulu, lanjut internet bila perlu.

        Urutannya sengaja begitu: (1) ``payload/wheels`` dipakai tanpa internet (``--no-index``);
        (2) bila berkas bawaan **tidak cocok atau kurang** (versi berbeda dari yang dipatok
        aplikasi, atau platformnya lain), pemasangan **dilanjutkan dengan unduhan internet** —
        berkas bawaan tetap dipakai untuk yang sudah ada; (3) kalau Python komputer menolak
        pemasangan (PEP 668), dipakai ``--break-system-packages`` dengan pemberitahuan jujur.
        """
        self.cek_batal()
        self.maju(3, 55)
        berkas_req = [self.tujuan / "requirements.txt"]
        if self.dengan_bot and (self.tujuan / "requirements-bot.txt").exists():
            berkas_req.append(self.tujuan / "requirements-bot.txt")

        roda = [p for p in (self.payload / "wheels", self.payload / "bootstrap")
                if p.is_dir() and any(p.glob("*.whl"))]
        dasar: list = [python, "-m", "pip", "install", "--disable-pip-version-check",
                       "--no-warn-script-location"]
        for b in berkas_req:
            dasar += ["-r", b]
        for folder in roda:
            dasar += ["--find-links", folder]

        self.catat("Memasang pustaka yang dibutuhkan"
                   + (" termasuk pustaka bot Dapodik" if self.dengan_bot else "") + " ...")
        if roda:
            jumlah = sum(len(list(f.glob("*.whl"))) + len(list(f.glob("*.tar.gz")))
                         for f in roda)
            self.catat(f"Berkas pustaka bawaan: {jumlah} berkas di "
                       + ", ".join(str(f) for f in roda))
            terlewat = self.payload / "wheels-terlewat.txt"
            if terlewat.exists():
                for baris in terlewat.read_text(encoding="utf-8").splitlines():
                    if baris.strip():
                        self.catat(f"  ! tidak ada di paket → {baris.strip()}")
            hasil = _jalankan([*dasar, "--no-index"], cwd=self.tujuan, waktu=7200)
            if hasil.returncode == 0:
                return self._selesaikan_pustaka(python, "dari berkas bawaan, tanpa internet")
            pesan = (hasil.stderr or hasil.stdout or "").strip().splitlines()
            sebab = next((b for b in pesan if b.startswith("ERROR")), "")[:200]
            self.catat("Berkas pustaka bawaan belum cukup untuk versi yang diminta aplikasi "
                       f"({sebab or 'tidak cocok'}) — dilanjutkan dengan unduhan internet "
                       "(sekali saja; berkas bawaan tetap dipakai untuk yang sudah ada) ...")
        else:
            self.catat("Paket ini tidak membawa berkas pustaka — diunduh dari internet "
                       "(sekali saja) ...")

        hasil = _jalankan(dasar, cwd=self.tujuan, waktu=7200)
        pesan = (hasil.stderr or hasil.stdout or "")
        if hasil.returncode != 0 and "externally-managed-environment" in pesan:
            self.catat("[!] Python komputer ini menolak pemasangan pustaka (PEP 668) — "
                       "dipakai opsi «--break-system-packages» untuk melanjutkan ...")
            hasil = _jalankan([*dasar, "--break-system-packages"], cwd=self.tujuan, waktu=7200)
        if hasil.returncode != 0 and "--find-links" in dasar:
            # Terakhir: buang berkas bawaan yang menyesatkan, murni dari internet.
            bersih = [b for b in dasar if b not in ("--find-links",)
                      and not str(b).startswith(str(self.payload))]
            bersih = [b for i, b in enumerate(bersih)
                      if not (i > 0 and bersih[i - 1] == "--find-links")]
            self.catat("Mencoba sekali lagi tanpa berkas pustaka bawaan ...")
            hasil = _jalankan(bersih, cwd=self.tujuan, waktu=7200)
        if hasil.returncode != 0:
            rinci = (hasil.stderr or hasil.stdout or "").strip()[-900:]
            raise GalatPasang(
                "Pemasangan pustaka gagal.\n" + rinci +
                "\nSaran: periksa sambungan internet di komputer itu, atau buat ulang bodap.exe "
                "dengan «BUAT-BODAP.bat» (berkas pustaka bawaan akan dibuat ulang dari daftar "
                "versi aplikasi). Berkas yang sudah tersalin tidak perlu diulang.")
        return self._selesaikan_pustaka(python, "diunduh dari internet")

    def _selesaikan_pustaka(self, python: Path, cara: str) -> str:
        """Periksa pustaka inti benar-benar bisa diimpor, lalu kembalikan catatannya."""
        kurang = _pustaka_kurang(python, ("fastapi", "uvicorn", "jinja2", "multipart",
                                          "itsdangerous", "openpyxl"))
        if kurang:
            raise GalatPasang("Pustaka ini belum terpasang: " + ", ".join(kurang)
                              + ".\nJalankan bodap.exe lagi (berkas yang sudah tersalin tidak "
                                "perlu diulang).")
        catatan = f"{cara}"
        if self.dengan_bot:
            bot_kurang = _pustaka_kurang(python, ("selenium",))
            catatan += (" · pustaka bot siap" if not bot_kurang
                        else " · pustaka bot belum siap (bisa dipasang dari halaman Bot Dapodik)")
        self.catat(f"Pustaka terpasang ({catatan}).")
        return catatan

    # -- langkah 5: data ----------------------------------------------------- #
    def siapkan_data(self, python: Path) -> dict:
        self.cek_batal()
        self.maju(4, 75)
        self.data.mkdir(parents=True, exist_ok=True)
        sudah = (self.data / "sm.sqlite3").exists()
        self.catat("Basis data lama dipakai kembali — data sekolah tetap utuh."
                   if sudah else "Menyiapkan basis data baru (kosong — tanpa data contoh) ...")
        # Pemasangan baru harus BERSIH: tidak ada siswa/ekskul contoh dari mana pun.
        # Bila sekolah memang ingin daftar 14 ekskul resmi, itu diminta lewat wizard.
        lingkungan = dict(os.environ, SM_DATA_DIR=str(self.data), PYTHONUTF8="1",
                          PYTHONIOENCODING="utf-8",
                          SM_AUTO_SEED="0",
                          SM_EKSKUL_SEKOLAH="1" if self.ekskul_contoh else "0")
        lingkungan.pop("SM_DB_PATH", None)      # jangan tertipu penunjuk dari luar
        hasil = _jalankan([python, "run.py", "--init-db"], cwd=self.tujuan, waktu=1800,
                          env=lingkungan)
        if hasil.returncode != 0:
            raise GalatPasang("Gagal menyiapkan basis data:\n"
                              + (hasil.stderr or hasil.stdout or "").strip()[-700:])
        self.catat(f"Basis data siap: {self.data / 'sm.sqlite3'}")
        return {"basis_data": str(self.data / "sm.sqlite3"), "sudah_ada": sudah}

    # -- langkah 6: peluncur, ikon, otomatis --------------------------------- #
    def tulis_peluncur(self, python: Path) -> dict:
        self.cek_batal()
        self.maju(5, 88)
        peluncur = self.tujuan / "SM.cmd"
        peluncur.write_text(
            "@echo off\r\n"
            "REM Dibuat oleh bodap.exe — jangan diubah manual.\r\n"
            "setlocal EnableExtensions\r\n"
            "chcp 65001 >nul 2>nul\r\n"
            "cd /d \"%~dp0\"\r\n"
            f"set \"SM_DATA_DIR={self.data}\"\r\n"
            "set \"PYTHONUTF8=1\"\r\n"
            "set \"PYTHONIOENCODING=utf-8\"\r\n"
            f"set \"PY={python}\"\r\n"
            "if not exist \"%PY%\" set \"PY=python\"\r\n"
            "echo ============================================================\r\n"
            "echo   SM - Sistem Informasi Manajemen Sekolah\r\n"
            "echo ============================================================\r\n"
            f"echo   Buka di peramban: http://localhost:{self.port}\r\n"
            "echo   Jendela ini biarkan terbuka selama aplikasi dipakai.\r\n"
            "echo   Menutup jendela ini berarti mematikan aplikasi.\r\n"
            "echo.\r\n"
            f"\"%PY%\" run.py --host 0.0.0.0 --port {self.port}\r\n"
            "echo.\r\n"
            "echo Server berhenti. Tekan tombol apa pun untuk menutup jendela ini.\r\n"
            "pause\r\n", encoding="utf-8", newline="")
        shutil.copy2(peluncur, self.tujuan / "Jalankan-SM.cmd")

        # Peluncur tanpa jendela terminal + pencabut + ikon (di dalam folder aplikasi).
        ikon = _ikon_bawaan()
        ikon_tujuan = None
        if ikon:
            try:
                shutil.copy2(ikon, self.tujuan / ikon.name)
                ikon_tujuan = self.tujuan / ikon.name
            except OSError:
                ikon_tujuan = ikon
        info_latar = buat_peluncur_latar(self.tujuan, python, self.data, self.port, ikon_tujuan)

        (self.tujuan / "BACA-INI-SM.txt").write_text(
            "SM - Sistem Informasi Manajemen Sekolah\n"
            "======================================\n\n"
            f"Versi aplikasi : {versi_aplikasi(self.tujuan)}\n"
            f"Folder program : {self.tujuan}\n"
            f"Folder data    : {self.data}\n"
            f"Alamat         : http://localhost:{self.port}\n\n"
            "Menjalankan\n"
            "-----------\n"
            "  Klik dua kali ikon «SM» di Desktop (atau «SM.vbs» di folder ini).\n"
            "  Aplikasi berjalan di BELAKANG LAYAR: tidak ada jendela hitam/terminal yang\n"
            "  perlu dibiarkan terbuka, peramban terbuka sendiri di alamat di atas.\n"
            "  Mematikan aplikasi: menu Start → «Hentikan SM» (atau «Hentikan-SM.vbs»).\n"
            "  Bila ada masalah: periksa <<folder data>>\\log-server.txt, atau jalankan\n"
            "  «Jalankan-SM.cmd» yang menampilkan pesan aplikasi di jendelanya.\n\n"
            "Login\n"
            "-----\n"
            "  Petugas : admin / admin123  (segera ganti sandinya di menu Pengaturan)\n"
            "  Siswa   : cukup NISN\n\n"
            "Penting\n"
            "-------\n"
            "* Seluruh data sekolah ada di folder data di atas. Memasang ulang atau\n"
            "  memperbarui TIDAK menghapus data itu.\n"
            "* Pemasangan baru mulai KOSONG: belum ada data siswa & daftar ekskul. Bila\n"
            "  sekolah memakai 14 ekskul resmi, tekan tombol «Isi daftar ekskul resmi (14)»\n"
            "  di halaman Ekstrakurikuler.\n"
            "* Cadangkan folder data secara berkala (salin ke flashdisk/Drive).\n"
            "* Menghapus aplikasi: jalankan «Hapus-SM.cmd» di folder ini.\n"
            "* Bot Dapodik memerlukan Google Chrome dan aplikasi Dapodik yang sedang berjalan.\n",
            encoding="utf-8")

        pintasan: list[str] = []
        if self.pintasan:
            self.catat("Membuat ikon «SM» di Desktop & menu Start (aplikasi jalan tanpa "
                       "jendela terminal) ...")
            pintasan = buat_pintasan(self.tujuan, ikon_tujuan)
            if not pintasan:
                self.catat("[!] Ikon Desktop tidak bisa dibuat otomatis. Pintasan bisa dibuat "
                           "manual: klik kanan «SM.vbs» → Kirim ke → Desktop (buat pintasan).")
        otomatis: list[str] = []
        if self.otomatis:
            self.catat("Menyiapkan agar SM ikut menyala saat komputer dinyalakan ...")
            otomatis = pasang_otomatis(self.tujuan)
        daftar: list[str] = []
        if self.daftar_aplikasi:
            daftar = daftarkan_aplikasi(self.tujuan, ikon_tujuan, versi_aplikasi(self.tujuan))
            if daftar:
                self.catat("Terdaftar di «Pengaturan → Aplikasi» Windows "
                           "(bisa dihapus dari sana).")
        self.catat("Peluncur dibuat: SM.vbs (tanpa jendela), Hentikan-SM.vbs, Jalankan-SM.cmd, "
                   "Hapus-SM.cmd, BACA-INI-SM.txt.")
        return {"pintasan": pintasan, "otomatis": otomatis, "ikon": str(ikon_tujuan or ""),
                "peluncur_latar": info_latar, "daftar_aplikasi": daftar}

    # -- langkah 7: catatan -------------------------------------------------- #
    def tulis_catatan(self, info: dict) -> None:
        self.maju(6, 96)
        catatan = {
            "versi": versi_aplikasi(self.tujuan),
            "bodap": versi_bodap(),
            "dipasang_pada": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tujuan": str(self.tujuan),
            "data": str(self.data),
            "port": self.port,
            "python": str(self.python),
            "modus": info.get("modus_python", ""),
            "pintasan": info.get("pintasan", []),
            "otomatis": info.get("otomatis", []),
            "peluncur_latar": info.get("peluncur_latar", {}),
            "daftar_aplikasi": info.get("daftar_applikasi", info.get("daftar_aplikasi", [])),
            "dengan_bot": self.dengan_bot,
        }
        (self.tujuan / NAMA_MARKER).write_text(
            json.dumps(catatan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # -- seluruh rangkaian --------------------------------------------------- #
    def jalankan(self) -> dict:
        t0 = time.time()
        self.periksa_awal()
        jumlah = self.salin_program()
        python, sumber_python = self.siapkan_python()
        self.python = python
        pustaka = self.pasang_pustaka(python)
        info_data = self.siapkan_data(python)
        info = self.tulis_peluncur(python)
        info["modus_python"] = sumber_python
        info["pustaka"] = pustaka
        self.tulis_catatan(info)
        self.maju(self.LANGKAH, 100)
        self.catat(f"Pemasangan selesai dalam {time.time() - t0:.0f} detik — "
                   f"buka http://localhost:{self.port}")
        return {"ok": True, "versi": versi_aplikasi(self.tujuan), "tujuan": str(self.tujuan),
                "data": str(self.data), "port": self.port, "berkas": jumlah,
                "python": str(python), "sumber_python": sumber_python, "pustaka": pustaka,
                **info_data, **info}


def _windows_64bit() -> bool:
    if os.name != "nt":
        return platform.machine().lower() in ("x86_64", "amd64")
    return bool(os.environ.get("PROCESSOR_ARCHITECTURE", "").endswith("64")
                or os.environ.get("PROCESSOR_ARCHITEW6432"))


# --------------------------------------------------------------------------- #
# Jalur sunyi (tanpa wizard) — dipakai uji otomatis & pemasangan massal
# --------------------------------------------------------------------------- #
def jalankan_sunyi(args) -> dict:
    dicatat: list[str] = []

    def catat(pesan: str) -> None:
        dicatat.append(pesan)
        if not args.diam:
            print("      " + pesan, flush=True)

    tujuan = Path(args.tujuan) if args.tujuan else tujuan_bawaan()
    data = Path(args.data) if args.data else tujuan / "data"
    if not args.diam:
        print("=" * 66)
        print("  SM — pemasangan (mode sunyi)")
        print("=" * 66)
        print(f"  Versi bodap : {versi_bodap()}")
        print(f"  Tujuan      : {tujuan}")
        print(f"  Data        : {data}")
        print("")
    pemasang = Pemasang(
        tujuan=tujuan, data=data, port=args.port, dengan_bot=args.dengan_bot,
        pintasan=not args.tanpa_pintasan, otomatis=args.otomatis,
        payload=Path(args.payload) if args.payload else None,
        python_bawaan=not args.python_komputer,
        izinkan_unduh_python=args.izinkan_unduh_python,
        daftar_aplikasi=not args.tanpa_daftar_aplikasi,
        ekskul_contoh=args.ekskul_contoh, catat=catat)
    hasil = pemasang.jalankan()
    hasil["perintah"] = "pasang"
    hasil["catatan"] = dicatat
    if not args.diam:
        print("")
        print(f"  Aplikasi SM siap : {hasil['tujuan']}")
        print(f"  Data sekolah     : {hasil['data']}")
        print(f"  Jalankan         : {Path(hasil['tujuan']) / 'Jalankan-SM.cmd'}")
        print(f"  Alamat           : http://localhost:{hasil['port']}")
        print("  Login petugas    : admin / admin123   ·   siswa: cukup NISN")
    return hasil


def jalankan_periksa(args) -> dict:
    tujuan = Path(args.tujuan) if args.tujuan else tujuan_bawaan()
    catatan: dict = {}
    berkas_catatan = tujuan / NAMA_MARKER
    if berkas_catatan.exists():
        try:
            catatan = json.loads(berkas_catatan.read_text(encoding="utf-8"))
        except ValueError:
            catatan = {}
    data = Path(args.data or catatan.get("data") or tujuan / "data")
    python = Path(catatan.get("python") or python_atau_venv(tujuan))
    db = data / "sm.sqlite3"
    kurang = (_pustaka_kurang(python, ("fastapi", "uvicorn", "jinja2", "multipart",
                                       "itsdangerous", "openpyxl"))
              if python.exists() else ["python"])
    pintasan = [p for p in pintasan_sm() if p.exists()]
    otomatis = berkas_otomatis()
    laporan = {
        "ok": bool(catatan) and db.exists() and not kurang,
        "perintah": "periksa",
        "versi": catatan.get("versi", "?"),
        "bodap": versi_bodap(),
        "terpasang": bool(catatan) or (tujuan / "run.py").exists(),
        "tujuan": str(tujuan),
        "data": str(data),
        "python": str(python),
        "python_versi": ".".join(str(x) for x in versi_python(python)) if python.exists() else "?",
        "pustaka_kurang": kurang,
        "basis_data_ada": db.exists(),
        "basis_data_ukuran": db.stat().st_size if db.exists() else 0,
        "pintasan": [str(p) for p in pintasan],
        "otomatis": str(otomatis) if otomatis and otomatis.exists() else "",
        "chrome": _cari_chrome(),
        "sistem": f"{platform.system()} {platform.release()} ({platform.machine()})",
    }
    if not args.diam:
        print("=" * 66)
        print("  SM — pemeriksaan pemasangan (bodap)")
        print("=" * 66)
        print(f"  Versi bodap   : {laporan['bodap']}")
        print(f"  Terpasang     : {'ya' if laporan['terpasang'] else 'BELUM'} "
              f"(versi {laporan['versi']})")
        print(f"  Folder program: {tujuan}")
        print(f"  Folder data   : {data}")
        print(f"  Python        : {python} — {laporan['python_versi']}")
        print(f"  Pustaka kurang: {', '.join(kurang) if kurang else 'tidak ada'}")
        print(f"  Basis data    : {'ada' if db.exists() else 'belum ada'} "
              f"({laporan['basis_data_ukuran'] / 1024:.0f} KB)")
        print(f"  Chrome (bot)  : {laporan['chrome'] or 'tidak ditemukan'}")
        for p in laporan["pintasan"]:
            print(f"  Pintasan      : {p}")
        if laporan["otomatis"]:
            print(f"  Otomatis      : {laporan['otomatis']}")
        print("")
        print("  Hasil: " + ("SEMUA SIAP — buka ikon «SM» di Desktop." if laporan["ok"]
                               else "ADA YANG PERLU DIBERESKAN (lihat baris di atas)."))
    return laporan


def _cari_chrome() -> str:
    if os.name == "nt":
        for dasar in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                      os.environ.get("LOCALAPPDATA")):
            if dasar:
                jalur = Path(dasar) / "Google/Chrome/Application/chrome.exe"
                if jalur.exists():
                    return str(jalur)
        return ""
    for nama in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        ada = shutil.which(nama)
        if ada:
            return ada
    return ""


def jalankan_hapus(args) -> dict:
    tujuan = Path(args.tujuan) if args.tujuan else tujuan_bawaan()
    catatan: dict = {}
    if (tujuan / NAMA_MARKER).exists():
        try:
            catatan = json.loads((tujuan / NAMA_MARKER).read_text(encoding="utf-8"))
        except ValueError:
            catatan = {}
    data = Path(args.data or catatan.get("data") or tujuan / "data")
    if not args.ya:
        raise GalatPasang("Hapus perlu penegasan: tambahkan --ya.")

    dihapus: list[str] = []
    for jalur in [*pintasan_sm(),
                  *[Path(str(p).split(": ", 1)[-1]) for p in catatan.get("pintasan", [])],
                  *[Path(str(p)) for p in catatan.get("otomatis", [])]]:
        try:
            if jalur.exists():
                jalur.unlink()
                dihapus.append(str(jalur))
        except OSError:
            pass
    otomatis = berkas_otomatis()
    if otomatis and otomatis.exists():
        try:
            otomatis.unlink()
            dihapus.append(str(otomatis))
        except OSError:
            pass
    if tujuan.exists():
        shutil.rmtree(tujuan, ignore_errors=True)
        dihapus.append(str(tujuan))
    data_di_luar = bool(data.exists()) and not str(data).startswith(str(tujuan))
    hasil = {"ok": True, "perintah": "hapus", "dihapus": dihapus,
             "data_dibiarkan": str(data) if data_di_luar else "",
             "sisa_folder": str(tujuan) if tujuan.exists() else ""}
    if not args.diam:
        print("  Aplikasi SM dihapus.")
        for jalur in dihapus:
            print(f"    - {jalur}")
        if hasil["data_dibiarkan"]:
            print(f"  Data sekolah tetap ada di: {hasil['data_dibiarkan']}")
        if hasil["sisa_folder"]:
            print(f"  [!] Sebagian berkas masih terkunci (mis. Python yang sedang berjalan): "
                  f"{hasil['sisa_folder']}\n      Jalankan Hapus-SM.cmd, atau hapus foldernya "
                  "setelah jendela SM ditutup.")
    return hasil


# --------------------------------------------------------------------------- #
# Uji mandiri (dipakai GitHub Actions & ``bodap.exe --uji``)
# --------------------------------------------------------------------------- #
def jalankan_uji(args) -> dict:
    """Buktikan isi paket ini benar-benar bisa dipasang: pasang → jalankan → periksa → hapus.

    Dipakai dua tempat: alur GitHub Actions setelah ``bodap.exe`` dibangun, dan Anda sendiri
    (``bodap.exe --uji``) untuk memastikan berkas yang dibawa tidak rusak. Semuanya di folder
    sementara; pemasangan SM yang sudah ada di komputer **tidak** disentuh.
    """
    import http.client
    import tempfile

    langkah: list[str] = []
    galat: list[str] = []

    def cek(syarat: bool, pesan: str) -> None:
        (langkah if syarat else galat).append(("OK   " if syarat else "GAGAL") + " — " + pesan)

    def port_bebas() -> int:
        import socket as _socket

        with _socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    with tempfile.TemporaryDirectory(prefix="bodap-uji-") as sementara:
        sementara = Path(sementara)
        tujuan = sementara / "SM"
        data = sementara / "data-sekolah"      # di LUAR folder aplikasi: harus tetap ada
        port = port_bebas()

        catatan: list[str] = []
        pemasang = Pemasang(
            tujuan=tujuan, data=data, port=port, dengan_bot=args.dengan_bot,
            pintasan=False, otomatis=False,
            payload=Path(args.payload) if args.payload else None,
            python_bawaan=not args.python_komputer,
            izinkan_unduh_python=args.izinkan_unduh_python,
            catat=lambda pesan: (catatan.append(pesan),
                                 print("      " + pesan, flush=True)))
        try:
            hasil = pemasang.jalankan()
        except Exception as exc:      # noqa: BLE001 — laporkan, jangan hentikan uji
            cek(False, f"pemasangan berjalan: {type(exc).__name__}: {exc}")
            return _ringkas_uji(langkah, galat, catatan, {})

        for berkas in ("run.py", "Jalankan-SM.cmd", "SM.cmd", "Hapus-SM.cmd",
                       "BACA-INI-SM.txt", NAMA_MARKER, "app/main.py"):
            cek((tujuan / berkas).exists(), f"berkas hasil pemasangan: {berkas}")

        # r23: aplikasi harus bisa dijalankan TANPA jendela terminal (peluncur latar).
        for berkas in ("SM.vbs", "Hentikan-SM.vbs", "Hapus-SM.vbs", "SM-latar.py"):
            cek((tujuan / berkas).exists(), f"berkas peluncur latar: {berkas}")
        try:
            isi_vbs = (tujuan / "SM.vbs").read_text(encoding="utf-8", errors="replace")
        except OSError:
            isi_vbs = ""
        # Di Windows peluncur memakai pythonw.exe (tanpa konsol); di Linux/macOS pengembang
        # pythonw tidak ada, yang penting jendelanya disembunyikan (, 0, False).
        cek(all(bagian in isi_vbs for bagian in ("SM-latar.py", "--port", ", 0, False"))
            and (os.name != "nt" or "pythonw" in isi_vbs),
            "SM.vbs menjalankan SM-latar.py lewat pythonw (jendela konsol disembunyikan)")
        try:
            isi_hentikan = (tujuan / "Hentikan-SM.vbs").read_text(encoding="utf-8", errors="replace")
        except OSError:
            isi_hentikan = ""
        cek("--hentikan" in isi_hentikan,
            "Hentikan-SM.vbs bisa mematikan aplikasi yang berjalan di belakang")
        try:
            isi_baca = (tujuan / "BACA-INI-SM.txt").read_text(encoding="utf-8", errors="replace")
        except OSError:
            isi_baca = ""
        cek(all(bagian in isi_baca for bagian in ("BELAKANG LAYAR", "Hentikan-SM", "log-server.txt",
                                                  "Isi daftar ekskul resmi")),
            "BACA-INI-SM.txt menjelaskan jalan di belakang layar, mematikannya, & data kosong")

        db = data / "sm.sqlite3"
        cek(db.exists() and db.stat().st_size > 10_000, f"basis data dibuat: {db}")

        # r23: hasil pemasangan harus FRESH — tidak ada siswa/ekstrakurikuler bawaan.
        try:
            import sqlite3

            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as koneksi:
                jumlah = {tabel: koneksi.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]
                          for tabel in ("students", "extracurriculars", "ekskul_members")}
            cek(all(nilai == 0 for nilai in jumlah.values()),
                "basis data hasil pemasangan kosong (fresh): "
                + ", ".join(f"{t} {n}" for t, n in jumlah.items()))
        except Exception as exc:      # noqa: BLE001 — laporkan, jangan hentikan uji
            cek(False, f"basis data hasil pemasangan bisa dibaca: {type(exc).__name__}: {exc}")
        cek(not (tujuan / "data").exists(), "folder data di luar aplikasi tidak dibuat ganda")
        try:
            catatan_pasang = json.loads((tujuan / NAMA_MARKER).read_text(encoding="utf-8"))
            cek(catatan_pasang.get("versi") == hasil.get("versi"),
                f"catatan pemasangan memuat versi {catatan_pasang.get('versi')}")
        except Exception as exc:      # noqa: BLE001
            cek(False, f"catatan pemasangan bisa dibaca: {exc}")

        # Aplikasi benar-benar dijalankan sebentar & halaman utamanya menjawab.
        python = Path(hasil["python"])
        proses = subprocess.Popen([str(python), "run.py", "--port", str(port)], cwd=str(tujuan),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  env=dict(os.environ, SM_DATA_DIR=str(data), PYTHONUTF8="1"),
                                  creationflags=tanpa_jendela())
        kode_jawab = 0
        try:
            batas = time.time() + 60
            while time.time() < batas:
                time.sleep(1.0)
                try:
                    koneksi = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    koneksi.request("GET", "/")
                    jawab = koneksi.getresponse()
                    kode_jawab = jawab.status
                    jawab.read()
                    koneksi.close()
                    break
                except OSError:
                    if proses.poll() is not None:
                        break
        finally:
            proses.terminate()
            try:
                proses.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proses.kill()
        cek(kode_jawab in (200, 303), f"aplikasi hasil pemasangan menjawab HTTP {kode_jawab}")

        # r23: dijalankan lewat peluncur latar — tanpa jendela, lalu dimatikan dari berkas ini.
        import urllib.error
        import urllib.request

        def menjawab(port_: int) -> bool:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port_}/", timeout=3) as jawab:
                    return jawab.status in (200, 303)
            except urllib.error.HTTPError as exc:
                return exc.code in (200, 303, 401, 403)
            except Exception:      # noqa: BLE001 — belum siap, bukan galat
                return False

        port_latar = port_bebas()
        lingkungan = dict(os.environ, SM_DATA_DIR=str(data), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        peluncur = subprocess.run(
            [str(python), str(tujuan / "SM-latar.py"), "--port", str(port_latar), "--tanpa-buka"],
            cwd=str(tujuan), capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=lingkungan, timeout=240, creationflags=tanpa_jendela())
        keadaan = data / "server.json"
        cek(peluncur.returncode == 0 and menjawab(port_latar),
            "SM-latar.py menjalankan aplikasi di belakang layar (tanpa jendela terminal) "
            f"port {port_latar}: {(peluncur.stdout or peluncur.stderr or '').strip()[:120]}")
        cek(keadaan.exists() and (data / "log-server.txt").exists(),
            "peluncur latar menulis catatan keadaan & catatan aplikasi di folder data")
        subprocess.run([str(python), str(tujuan / "SM-latar.py"), "--hentikan"], cwd=str(tujuan),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=lingkungan, timeout=120, creationflags=tanpa_jendela())
        batas = time.time() + 20
        while time.time() < batas and (menjawab(port_latar) or keadaan.exists()):
            time.sleep(0.5)
        cek(not menjawab(port_latar), "aplikasi latar benar-benar berhenti setelah --hentikan")
        cek(not keadaan.exists(), "catatan keadaan dibersihkan setelah aplikasi dihentikan")

        # periksa → hapus → data di luar folder aplikasi harus tetap ada
        kelas_args = argparse.Namespace(tujuan=str(tujuan), data=None, diam=True, ya=True)
        laporan = jalankan_periksa(kelas_args)
        cek(bool(laporan.get("ok")), f"periksa melaporkan siap (pustaka kurang: "
                                     f"{laporan.get('pustaka_kurang')})")
        jalankan_hapus(kelas_args)
        cek(not tujuan.exists(), "hapus membuang folder aplikasi")
        cek(db.exists(), "hapus membiarkan folder data di luar aplikasi")

    return _ringkas_uji(langkah, galat, catatan, {**hasil, "data": str(data), "port": port})


def _ringkas_uji(langkah: list[str], galat: list[str], catatan: list[str],
                 hasil: dict) -> dict:
    for baris in langkah + galat:
        print("  " + baris, flush=True)
    print(f"\n  HASIL: {'SEMUA LULUS' if not galat else f'{len(galat)} PEMERIKSAAN GAGAL'}"
          f"  ({len(langkah)} pemeriksaan lolos)", flush=True)
    return {"ok": not galat, "perintah": "uji", "pemeriksaan": langkah + galat,
            "gagal": galat, "catatan": catatan, **hasil}


# --------------------------------------------------------------------------- #
# Wizard (tkinter)
# --------------------------------------------------------------------------- #
class Wizard:
    """Jendela pemasangan: Sambutan → Folder & pilihan → Proses → Selesai."""

    JUDUL = "Pemasangan SM — Sistem Informasi Manajemen Sekolah"

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.akar = tk.Tk()
        self.akar.title(self.JUDUL)
        self.akar.geometry("760x580")
        self.akar.minsize(700, 540)
        self.akar.configure(bg="#f4f6fb")
        try:
            ikon = _ikon_bawaan()
            if ikon and ikon.suffix.lower() == ".ico":
                self.akar.iconbitmap(default=str(ikon))
        except Exception:      # noqa: BLE001
            pass

        self.antre: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.batal = threading.Event()
        self.hasil: dict = {}
        self.halaman = 0

        bawaan = tujuan_bawaan()
        self.var_tujuan = tk.StringVar(value=str(bawaan))
        self.var_data = tk.StringVar(value=str(bawaan / "data"))
        self.var_port = tk.StringVar(value="8000")
        self.var_pintasan = tk.BooleanVar(value=True)
        self.var_otomatis = tk.BooleanVar(value=False)
        self.var_bot = tk.BooleanVar(value=False)
        self.var_python_bawaan = tk.BooleanVar(value=True)
        self.var_unduh = tk.BooleanVar(value=True)
        self.var_buka = tk.BooleanVar(value=True)
        self.var_daftar = tk.BooleanVar(value=True)
        self.var_ekskul = tk.BooleanVar(value=False)

        gaya = ttk.Style()
        try:
            gaya.theme_use("vista" if os.name == "nt" else "clam")
        except Exception:      # noqa: BLE001
            pass
        gaya.configure("Judul.TLabel", font=("Segoe UI", 15, "bold"))
        gaya.configure("Kecil.TLabel", foreground="#555555")

        self.bingkai = ttk.Frame(self.akar, padding=18)
        self.bingkai.pack(fill="both", expand=True)
        self.bawah = ttk.Frame(self.akar, padding=(18, 8))
        self.bawah.pack(fill="x")
        self.tombol_kembali = ttk.Button(self.bawah, text="< Kembali", command=self.mundur)
        self.tombol_lanjut = ttk.Button(self.bawah, text="Lanjut >", command=self.maju)
        self.tombol_batal = ttk.Button(self.bawah, text="Batal", command=self.tutup)
        self.tombol_kembali.pack(side="left")
        self.tombol_batal.pack(side="right")
        self.tombol_lanjut.pack(side="right", padx=(0, 8))

        self.tampilkan(0)
        self.akar.after(120, self.periksa_antre)

    # -- halaman ------------------------------------------------------------- #
    def _bersih(self) -> None:
        for anak in self.bingkai.winfo_children():
            anak.destroy()

    def tampilkan(self, nomor: int) -> None:
        self.halaman = nomor
        self._bersih()
        self.tombol_lanjut.configure(command=self.maju, text="Lanjut >")
        self.tombol_lanjut.state(["!disabled"])
        if nomor == 0:
            self.halaman_sambutan()
        elif nomor == 1:
            self.halaman_pilihan()
        elif nomor == 2:
            self.halaman_proses()
        else:
            self.halaman_selesai()
        self.tombol_kembali.state(["!disabled"] if nomor == 1 else ["disabled"])

    def halaman_sambutan(self) -> None:
        ttk = self.ttk
        ttk.Label(self.bingkai, text="Selamat datang di pemasang SM",
                  style="Judul.TLabel").pack(anchor="w")
        ttk.Label(self.bingkai, style="Kecil.TLabel", wraplength=680,
                  text="Sistem Informasi Manajemen Sekolah — data siswa, ekstrakurikuler, "
                       "portal siswa, dan bot Dapodik.").pack(anchor="w", pady=(4, 14))
        kotak = ttk.LabelFrame(self.bingkai, text="Yang akan dilakukan pemasang ini", padding=12)
        kotak.pack(fill="x")
        ttk.Label(kotak, justify="left", text=(
            f"1. Menyalin program SM (versi {versi_bodap()}) ke komputer ini.\n"
            "2. Menyiapkan Python bawaan aplikasi — Python milik komputer tidak diubah.\n"
            "3. Memasang pustaka yang dibutuhkan.\n"
            "4. Menyiapkan basis data (data lama TIDAK pernah dihapus).\n"
            "5. Membuat ikon «SM» di Desktop supaya bisa dibuka dengan sekali klik."
        )).pack(anchor="w")
        ttk.Label(self.bingkai, style="Kecil.TLabel", wraplength=680, justify="left",
                  text="Tombol «Lanjut» untuk melanjutkan; pemasangan bisa dibatalkan kapan saja."
                  ).pack(anchor="w", pady=(14, 0))
        ttk.Label(self.bingkai, foreground="#8a5a00", wraplength=680, justify="left",
                  text="Catatan: langkah «Memasang pustaka» perlu sambungan internet "
                       "sekali saja. Bila paket ini memuat berkas pustaka bawaan, sekalipun "
                       "tanpa internet pun pemasangan tetap berjalan."
                  ).pack(anchor="w", pady=(14, 0))

    def halaman_pilihan(self) -> None:
        tk, ttk = self.tk, self.ttk
        ttk.Label(self.bingkai, text="Folder & pilihan pemasangan",
                  style="Judul.TLabel").pack(anchor="w")
        ttk.Label(self.bingkai, style="Kecil.TLabel",
                  text="Boleh dibiarkan seperti bawaan, lalu tekan «Lanjut»."
                  ).pack(anchor="w", pady=(4, 12))

        for label, variabel, perintah in (("Folder aplikasi", self.var_tujuan, self.pilih_tujuan),
                                          ("Folder data sekolah", self.var_data, self.pilih_data)):
            baris = ttk.Frame(self.bingkai)
            baris.pack(fill="x", pady=4)
            ttk.Label(baris, text=label, width=20).pack(side="left")
            ttk.Entry(baris, textvariable=variabel).pack(side="left", fill="x", expand=True,
                                                         padx=(0, 8))
            ttk.Button(baris, text="Pilih ...", command=perintah).pack(side="left")

        baris_port = ttk.Frame(self.bingkai)
        baris_port.pack(fill="x", pady=(10, 4))
        ttk.Label(baris_port, text="Port aplikasi", width=20).pack(side="left")
        ttk.Entry(baris_port, textvariable=self.var_port, width=10).pack(side="left")
        ttk.Label(baris_port, style="Kecil.TLabel",
                  text="   alamat aplikasi: http://localhost:<port>").pack(side="left")

        kotak = ttk.LabelFrame(self.bingkai, text="Pilihan", padding=12)
        kotak.pack(fill="x", pady=14)
        ttk.Checkbutton(kotak, variable=self.var_pintasan,
                        text="Buat ikon «SM» di Desktop dan menu Start"
                        ).pack(anchor="w")
        ttk.Checkbutton(kotak, variable=self.var_otomatis,
                        text="Jalankan SM otomatis saat komputer dinyalakan").pack(anchor="w")
        ttk.Checkbutton(kotak, variable=self.var_bot,
                        text="Pasang sekalian pustaka Bot Dapodik (selenium)").pack(anchor="w")
        ttk.Checkbutton(kotak, variable=self.var_python_bawaan,
                        text="Gunakan Python bawaan aplikasi (disarankan)").pack(anchor="w")
        ttk.Checkbutton(kotak, variable=self.var_unduh,
                        text="Bila perlu, unduh Python dari python.org (butuh internet)"
                        ).pack(anchor="w")
        ttk.Checkbutton(kotak, variable=self.var_daftar,
                        text="Daftarkan di «Pengaturan → Aplikasi» Windows (ada tombol Hapus)"
                        ).pack(anchor="w")
        ttk.Checkbutton(kotak, variable=self.var_ekskul,
                        text="Isi daftar 14 ekstrakurikuler resmi sekolah (kalau tidak "
                             "dicentang: aplikasi benar-benar kosong)"
                        ).pack(anchor="w")

        ttk.Label(self.bingkai, style="Kecil.TLabel", wraplength=680, justify="left",
                  text="Data siswa disimpan di folder data di atas. Bila folder data diletakkan "
                       "di luar folder aplikasi (mis. Drive atau flashdisk), data tetap aman "
                       "walau aplikasi dihapus atau dipasang ulang."
                  ).pack(anchor="w")

    def halaman_proses(self) -> None:
        tk, ttk = self.tk, self.ttk
        ttk.Label(self.bingkai, text="Memasang SM ...", style="Judul.TLabel").pack(anchor="w")
        self.bilah = ttk.Progressbar(self.bingkai, mode="determinate", maximum=100)
        self.bilah.pack(fill="x", pady=(10, 4))
        self.status = ttk.Label(self.bingkai, text="Menyiapkan ...")
        self.status.pack(anchor="w")
        kotak = ttk.LabelFrame(self.bingkai, text="Catatan pemasangan", padding=6)
        kotak.pack(fill="both", expand=True, pady=10)
        self.log = tk.Text(kotak, height=15, wrap="word", state="disabled",
                           font=("Consolas", 9))
        bilah = ttk.Scrollbar(kotak, command=self.log.yview)
        self.log.configure(yscrollcommand=bilah.set)
        bilah.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        ttk.Label(self.bingkai, style="Kecil.TLabel",
                  text="Jangan tutup jendela ini sampai selesai.").pack(anchor="w")
        self.tombol_kembali.state(["disabled"])
        self.tombol_lanjut.state(["disabled"])
        self.tombol_batal.configure(text="Batalkan")

    def halaman_selesai(self) -> None:
        ttk = self.ttk
        ttk.Label(self.bingkai, text="Pemasangan selesai", style="Judul.TLabel").pack(anchor="w")
        self.ringkas = ttk.Label(self.bingkai, justify="left", wraplength=680)
        self.ringkas.pack(anchor="w", pady=(10, 12))
        kotak = ttk.LabelFrame(self.bingkai, text="Langkah berikutnya", padding=12)
        kotak.pack(fill="x")
        ttk.Checkbutton(kotak, variable=self.var_buka,
                        text="Buka aplikasi SM sekarang (peramban terbuka sendiri)"
                        ).pack(anchor="w")
        ttk.Label(kotak, justify="left", text=(
            "• Login petugas: admin / admin123 — segera ganti sandinya di menu Pengaturan.\n"
            "• Login siswa: cukup NISN.\n"
            "• Jendela hitam «SM» biarkan terbuka selama aplikasi dipakai.\n"
            "• Lain kali buka lewat ikon «SM» di Desktop."
        )).pack(anchor="w", pady=(8, 0))
        self.tombol_lanjut.configure(text="Selesai", command=self.penutup)
        self.tombol_batal.configure(text="Tutup")

    # -- navigasi ------------------------------------------------------------ #
    def maju(self) -> None:
        if self.halaman == 0:
            self.tampilkan(1)
            return
        if self.halaman == 1:
            try:
                port = int(self.var_port.get())
                if not (1 <= port <= 65535):
                    raise ValueError
            except ValueError:
                self.pesan("Port harus berupa angka antara 1 dan 65535.")
                return
            self.var_port.set(str(port))
            tujuan = Path(self.var_tujuan.get()).expanduser()
            if (tujuan.exists() and any(tujuan.iterdir())
                    and not (tujuan / NAMA_MARKER).exists()
                    and not (tujuan / "run.py").exists()):
                self.pesan(f"Folder ini sudah berisi berkas lain:\n{tujuan}\n\n"
                           "Pilih folder lain supaya tidak ada berkas yang tertimpa.")
                return
            tujuan.mkdir(parents=True, exist_ok=True)
            self.var_tujuan.set(str(tujuan))
            self.var_data.set(str(Path(self.var_data.get()).expanduser()))
            self.tampilkan(2)
            threading.Thread(target=self.kerja, daemon=True).start()
            return
        self.penutup()

    def mundur(self) -> None:
        if self.halaman == 1:
            self.tampilkan(0)

    def tutup(self) -> None:
        if self.halaman == 2:
            self.batal.set()
            self.pesan("Pemasangan akan berhenti setelah langkah yang sedang berjalan.")
            return
        self.akar.destroy()

    def penutup(self) -> None:
        if self.hasil and self.var_buka.get():
            self.buka_aplikasi()
        self.akar.destroy()

    def buka_aplikasi(self) -> None:
        tujuan = Path(self.hasil.get("tujuan") or self.var_tujuan.get())
        port = int(self.hasil.get("port") or self.var_port.get())
        peluncur = tujuan / "Jalankan-SM.cmd"
        vbs = tujuan / "SM.vbs"
        try:
            if os.name == "nt" and vbs.exists():
                # Lewat SM.vbs: aplikasi jalan di belakang layar — tanpa jendela terminal.
                wscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"
                subprocess.Popen([str(wscript), str(vbs)], creationflags=tanpa_jendela())
            elif os.name == "nt" and peluncur.exists():
                os.startfile(str(peluncur))      # noqa: S606 — cadangan (tanpa SM.vbs)
            else:
                subprocess.Popen([str(python_atau_venv(tujuan)), "run.py", "--port", str(port)],
                                 cwd=str(tujuan), creationflags=tanpa_jendela())
            import webbrowser
            threading.Thread(target=lambda: (time.sleep(4),
                                             webbrowser.open(f"http://localhost:{port}")),
                             daemon=True).start()
        except Exception as exc:      # noqa: BLE001
            self.pesan(f"Aplikasi tidak bisa dibuka otomatis ({exc}).\n"
                       "Klik dua kali ikon «SM» di Desktop.")

    def pilih_tujuan(self) -> None:
        from tkinter import filedialog

        jalur = filedialog.askdirectory(title="Pilih folder pemasangan SM",
                                       initialdir=str(Path(self.var_tujuan.get()).parent))
        if jalur:
            self.var_tujuan.set(jalur)
            if self.var_data.get().startswith(str(tujuan_bawaan())):
                self.var_data.set(str(Path(jalur) / "data"))

    def pilih_data(self) -> None:
        from tkinter import filedialog

        jalur = filedialog.askdirectory(title="Pilih folder data sekolah",
                                       initialdir=str(Path(self.var_data.get()).parent))
        if jalur:
            self.var_data.set(jalur)

    def pesan(self, teks: str) -> None:
        from tkinter import messagebox

        messagebox.showinfo(self.JUDUL, teks)

    # -- pekerjaan berat ----------------------------------------------------- #
    def kerja(self) -> None:
        pemasang = Pemasang(
            tujuan=Path(self.var_tujuan.get()), data=Path(self.var_data.get()),
            port=int(self.var_port.get()), dengan_bot=self.var_bot.get(),
            pintasan=self.var_pintasan.get(), otomatis=self.var_otomatis.get(),
            python_bawaan=self.var_python_bawaan.get(),
            izinkan_unduh_python=self.var_unduh.get(),
            daftar_aplikasi=self.var_daftar.get(), ekskul_contoh=self.var_ekskul.get(),
            catat=lambda pesan: self.antre.put(("catat", pesan)),
            maju=lambda langkah, persen: self.antre.put(("maju", persen)),
            berhenti=self.batal.is_set)
        try:
            self.antre.put(("selesai", pemasang.jalankan()))
        except Exception as exc:      # noqa: BLE001 — apa pun salahnya, pengguna harus tahu
            self.antre.put(("galat", f"{type(exc).__name__}: {exc}"))

    def periksa_antre(self) -> None:
        try:
            while True:
                jenis, isi = self.antre.get_nowait()
                if jenis == "catat":
                    self.tulis(str(isi))
                elif jenis == "maju":
                    self.bilah["value"] = isi
                elif jenis == "selesai":
                    self.hasil = dict(isi)          # type: ignore[arg-type]
                    self.selesaikan()
                    return
                elif jenis == "galat":
                    self.tulis("")
                    self.tulis("[GAGAL] " + str(isi))
                    self.status.configure(text="Pemasangan gagal.")
                    self.tombol_lanjut.state(["!disabled"])
                    self.tombol_lanjut.configure(text="Tutup", command=self.akar.destroy)
                    self.tombol_batal.state(["disabled"])
                    from tkinter import messagebox
                    messagebox.showerror(self.JUDUL, "Pemasangan gagal:\n\n" + str(isi))
                    return
        except queue.Empty:
            pass
        self.akar.after(120, self.periksa_antre)

    def tulis(self, pesan: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", pesan + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        if pesan.endswith("..."):
            self.status.configure(text=pesan)

    def selesaikan(self) -> None:
        self.tampilkan(3)
        pintasan = self.hasil.get("pintasan") or []
        ikon_desktop = next((p for p in pintasan if str(p).lower().startswith("desktop")), "")
        self.ringkas.configure(text="\n".join([
            f"Versi aplikasi : {self.hasil.get('versi', '?')}",
            f"Folder program : {self.hasil.get('tujuan')}",
            f"Folder data    : {self.hasil.get('data')}",
            f"Alamat         : http://localhost:{self.hasil.get('port')}",
            f"Ikon Desktop   : {ikon_desktop or ('ada' if pintasan else 'tidak dibuat')}",
        ]))


def jalankan_wizard() -> int:
    if not ada_jendela_gui():
        print("[!] Jendela pemasangan tidak bisa dibuka di lingkungan ini (tkinter tidak ada "
              "atau tanpa layar).\n    Pakai mode sunyi, mis.:  bodap --sunyi --tujuan \"D:\\SM\"")
        return 2
    wizard = Wizard()
    wizard.akar.mainloop()
    return 0


# --------------------------------------------------------------------------- #
# Baris perintah
# --------------------------------------------------------------------------- #
def buat_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bodap",
        description="Pemasang SM (Sistem Informasi Manajemen Sekolah) satu berkas.",
        epilog="Tanpa argumen: jendela pemasangan terbuka (Next → Next → Install → Finish).")
    p.add_argument("--sunyi", action="store_true",
                   help="pasang tanpa jendela (untuk skrip/uji otomatis)")
    p.add_argument("--periksa", action="store_true", help="periksa pemasangan yang ada")
    p.add_argument("--hapus", action="store_true", help="hapus pemasangan")
    p.add_argument("--tujuan", help="folder pemasangan (bawaan: folder aplikasi pengguna)")
    p.add_argument("--data", help="folder data sekolah (bawaan: <tujuan>/data)")
    p.add_argument("--port", type=int, default=8000, help="port aplikasi (bawaan 8000)")
    p.add_argument("--dengan-bot", action="store_true",
                   help="sekalian pasang pustaka bot Dapodik (selenium)")
    p.add_argument("--tanpa-pintasan", action="store_true", help="jangan buat ikon Desktop")
    p.add_argument("--tanpa-daftar-aplikasi", action="store_true",
                   help="jangan daftarkan SM di «Pengaturan → Aplikasi» Windows")
    p.add_argument("--ekskul-contoh", action="store_true",
                   help="isi daftar 14 ekstrakurikuler resmi saat memasang "
                        "(bawaan: aplikasi kosong)")
    p.add_argument("--otomatis", action="store_true",
                   help="jalankan SM otomatis saat komputer dinyalakan")
    p.add_argument("--python-komputer", action="store_true",
                   help="pakai Python yang sudah ada di komputer (bukan Python bawaan)")
    p.add_argument("--izinkan-unduh-python", action="store_true",
                   help="izinkan mengunduh Python dari python.org bila belum ada")
    p.add_argument("--payload", help="folder berisi app.zip/python-embed.zip (untuk uji)")
    p.add_argument("--uji", action="store_true",
                   help="uji mandiri: pasang ke folder sementara, jalankan, periksa, hapus")
    p.add_argument("--laporan", help="tuliskan hasil (JSON) ke berkas ini")
    p.add_argument("--ya", action="store_true", help="penegasan untuk --hapus")
    p.add_argument("--json", action="store_true", help="keluarkan ringkasan JSON")
    p.add_argument("--diam", action="store_true", help="jangan cetak langkah-langkah")
    return p


def main(argv: list[str] | None = None) -> int:
    global _PAYLOAD_PAKSA
    args = buat_parser().parse_args(argv)
    if args.payload:
        _PAYLOAD_PAKSA = Path(args.payload).expanduser().resolve()
    try:
        if args.uji:
            hasil = jalankan_uji(args)
        elif args.periksa:
            hasil = jalankan_periksa(args)
        elif args.hapus:
            hasil = jalankan_hapus(args)
        elif args.sunyi or args.json or not ada_jendela_gui():
            hasil = jalankan_sunyi(args)
        else:
            return jalankan_wizard()
    except GalatPasang as exc:
        if args.json:
            print(json.dumps({"ok": False, "galat": str(exc)}, ensure_ascii=False))
        else:
            print(f"\n[!] {exc}\n", file=sys.stderr)
        if args.laporan:
            Path(args.laporan).write_text(
                json.dumps({"ok": False, "galat": str(exc)}, indent=2, ensure_ascii=False),
                encoding="utf-8")
        return 1
    except KeyboardInterrupt:
        print("\n[!] Dibatalkan.", file=sys.stderr)
        return 130

    if args.json:
        print(json.dumps(hasil, ensure_ascii=False))
    if args.laporan:
        try:
            Path(args.laporan).write_text(
                json.dumps(hasil, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"[!] Laporan tidak bisa ditulis ke {args.laporan}: {exc}", file=sys.stderr)
    return 0 if hasil.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
