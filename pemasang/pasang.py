#!/usr/bin/env python3
"""Pemasang (installer) aplikasi SM — memasang di komputer mana pun.

Berkas ini **tidak memakai pustaka luar** (hanya Python bawaan), supaya bisa dijalankan
walaupun aplikasi SM sendiri belum terpasang. Cara pakai::

    python pemasang/pasang.py                     # memasang (lihat di bawah)
    python pemasang/pasang.py --tujuan C:\\SM      # memasang ke folder tertentu
    python pemasang/pasang.py periksa             # periksa kondisi pemasangan
    python pemasang/pasang.py perbarui            # perbarui aplikasi, data tetap
    python pemasang/pasang.py hapus --ya          # menghapus (data di luar folder dibiarkan)
    python pemasang/pasang.py dari-zip --paket SM-0.1.0-paket.zip
    python pemasang/pasang.py buat-paket          # membuat paket ZIP untuk dibawa ke mana-mana

Di Windows, cukup klik dua kali ``PASANG.bat`` (memasang) atau ``HAPUS.bat`` (menghapus).

Yang dipasang:

* program SM (folder ``app``, ``run.py``, dsb.) ke folder tujuan;
* lingkungan Python ``.venv`` berisi pustaka yang dibutuhkan (*kecuali* mode ``--tanpa-venv``);
* basis data di folder data (default ``<tujuan>/data``) — **tidak pernah ditimpa** saat
  memasang ulang / memperbarui;
* berkas peluncur: ``Jalankan-SM.cmd`` (Windows) atau ``jalankan-sm.sh`` (Linux/macOS);
* catatan pemasangan ``.sm-pemasangan.json`` (dipakai perintah ``periksa``/``perbarui``/``hapus``).

Sifat penting: memasang ulang ke folder yang sudah berisi SM = **memperbarui** (kode diganti,
data tetap). Folder yang sudah berisi berkas lain **tidak** akan ditimpa tanpa ``--paksa``.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# Pencabut & pendaftaran Control Panel (berkas di folder yang sama)
# --------------------------------------------------------------------------- #
_FOLDER_INI = Path(__file__).resolve().parent
if str(_FOLDER_INI) not in sys.path:
    sys.path.insert(0, str(_FOLDER_INI))
try:
    import pencabut_sm
except Exception:      # noqa: BLE001 — pemasangan tetap boleh jalan, pendaftaran dilewati
    pencabut_sm = None      # type: ignore[assignment]

# --------------------------------------------------------------------------- #
# Tetapan dasar
# --------------------------------------------------------------------------- #
VERSI_MINIMUM = (3, 10)
NAMA_PENANDA = ".sm-pemasangan.json"          # catatan pemasangan di folder tujuan
NAMA_PELUNCUR_WIN = "Jalankan-SM.cmd"
NAMA_PELUNCUR_NIX = "jalankan-sm.sh"
NAMA_BACAAN = "BACA-INI-SM.txt"

AKAR_PAKET = Path(__file__).resolve().parent.parent

#: Folder/berkas yang TIDAK ikut disalin (data pengguna & sisa pengembangan).
ABAIKAN_FOLDER = {
    ".git", ".venv", "venv", "env", "data", "sample-data", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    "dist", "build",
}
ABAIKAN_POLA = (
    "*.pyc", "*.pyo", "*.sqlite3*", "*.log", ".env", "secrets.env",
    "*.xlsx", "*.xls", "*.xlsb", "*.ods",     # berkas data siswa: jangan pernah ikut
    "laporan-python.txt",
)
#: Berkas contoh/template yang HARUS tetap ikut walaupun berpola di atas.
PENGECUALIAN_POLA = ("template-import/*",)

#: Berkas yang wajib ada setelah pemasangan (untuk memeriksa hasil).
BERKAS_WAJIB = ("run.py", "app/main.py", "requirements.txt", "Jalankan-SM.cmd", "jalankan-sm.sh")


class GalatPemasang(Exception):
    """Kesalahan yang bisa dijelaskan ke pengguna (bukan bug)."""


# --------------------------------------------------------------------------- #
# Alat bantu kecil
# --------------------------------------------------------------------------- #
def _cetak(pesan: str = "", diam: bool = False) -> None:
    if not diam:
        print(pesan, flush=True)


def versi_aplikasi(sumber: Path | None = None) -> str:
    """Versi aplikasi SM, dibaca dari ``app/config.py`` (tanpa mengimpor aplikasi)."""
    berkas = (sumber or AKAR_PAKET) / "app" / "config.py"
    try:
        isi = berkas.read_text(encoding="utf-8")
    except OSError:
        return "?"
    cocok = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', isi)
    return cocok.group(1) if cocok else "?"


def python_venv(tujuan: Path) -> Path:
    """Jalur Python di dalam ``.venv`` folder tujuan."""
    if os.name == "nt":
        return tujuan / ".venv" / "Scripts" / "python.exe"
    return tujuan / ".venv" / "bin" / "python"


def _jalankan(perintah: list[str], cwd: Path | None = None, env: dict | None = None,
              waktu: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(perintah, cwd=str(cwd) if cwd else None, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=waktu)


def _saring_abaikan(akar_sumber: Path):
    """Fungsi ``ignore`` untuk :func:`shutil.copytree`."""

    def saring(direktori: str, nama_nama: list[str]) -> list[str]:
        buang: list[str] = []
        for nama in nama_nama:
            if nama in ABAIKAN_FOLDER:
                buang.append(nama)
                continue
            if any(fnmatch.fnmatch(nama, pola) for pola in ABAIKAN_POLA):
                jalur = Path(direktori) / nama
                relatif = jalur.relative_to(akar_sumber).as_posix()
                if any(fnmatch.fnmatch(relatif, kec) for kec in PENGECUALIAN_POLA):
                    continue
                buang.append(nama)
        return buang

    return saring


def baca_catatan(tujuan: Path) -> dict:
    """Isi ``.sm-pemasangan.json`` bila ada (kalau rusak: dianggap tidak ada)."""
    berkas = tujuan / NAMA_PENANDA
    if not berkas.exists():
        return {}
    try:
        data = json.loads(berkas.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def tulis_catatan(tujuan: Path, data: dict) -> None:
    (tujuan / NAMA_PENANDA).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tujuan_bawaan() -> Path:
    """Folder pemasangan bawaan menurut sistem operasi (tanpa perlu hak admin)."""
    rumah = Path(os.environ.get("HOME") or Path.home())
    if os.name == "nt":
        dasar = os.environ.get("LOCALAPPDATA") or str(rumah / "AppData" / "Local")
        return Path(dasar) / "Programs" / "SM"
    if sys.platform == "darwin":
        return rumah / "Applications" / "SM"
    dasar = os.environ.get("XDG_DATA_HOME") or str(rumah / ".local" / "share")
    return Path(dasar) / "SM"


def folder_beranda() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def port_bebas(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soket:
        soket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            soket.bind((host, port))
        except OSError:
            return False
    return True


def cari_chrome() -> str:
    """Jalur Chrome/Chromium bila ada — bot Dapodik memerlukannya."""
    if os.name == "nt":
        kandidat = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        for jalur in kandidat:
            if jalur.exists():
                return str(jalur)
        return ""
    if sys.platform == "darwin":
        jalur = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return str(jalur) if jalur.exists() else ""
    for nama in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        ada = shutil.which(nama)
        if ada:
            return ada
    return ""


def _cek_pustaka(python: Path, paket: tuple[str, ...]) -> list[str]:
    """Nama pustaka yang GAGAL diimpor oleh ``python`` (kode dijalankan di proses terpisah)."""
    kode = ("import importlib, json, sys\n"
            "kurang = []\n"
            "for nama in sys.argv[1:]:\n"
            "    try:\n"
            "        importlib.import_module(nama)\n"
            "    except Exception:\n"
            "        kurang.append(nama)\n"
            "print(json.dumps(kurang))\n")
    hasil = _jalankan([str(python), "-c", kode, *paket], waktu=120)
    if hasil.returncode != 0:
        return list(paket)
    try:
        return list(json.loads(hasil.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return list(paket)


# --------------------------------------------------------------------------- #
# Menyalin program
# --------------------------------------------------------------------------- #
def salin_program(sumber: Path, tujuan: Path, diam: bool = False) -> int:
    """Salin berkas program dari ``sumber`` ke ``tujuan``. Kembalikan jumlah berkas."""
    if sumber.resolve() == tujuan.resolve():
        raise GalatPemasang("Folder tujuan sama dengan folder paket — pilih folder lain.")
    try:
        tujuan.relative_to(sumber)
    except ValueError:
        pass
    else:
        raise GalatPemasang("Folder tujuan tidak boleh berada DI DALAM folder paket.")
    if not (sumber / "run.py").exists():
        raise GalatPemasang(f"Folder paket tidak lengkap (run.py tidak ada): {sumber}")

    tujuan.mkdir(parents=True, exist_ok=True)
    shutil.copytree(sumber, tujuan, dirs_exist_ok=True, ignore=_saring_abaikan(sumber))

    jumlah = sum(1 for p in tujuan.rglob("*") if p.is_file() and ".venv" not in p.parts)
    _cetak(f"      {jumlah} berkas program disalin ke {tujuan}", diam)
    for wajib in ("run.py", "app/main.py"):
        if not (tujuan / wajib).exists():
            raise GalatPemasang(f"Berkas {wajib} tidak ada setelah penyalinan — paket rusak?")
    return jumlah


# --------------------------------------------------------------------------- #
# Lingkungan Python & dependensi
# --------------------------------------------------------------------------- #
def buat_venv(tujuan: Path, python: Path, diam: bool = False) -> Path:
    """Siapkan ``.venv`` di folder tujuan (dipakai ulang bila sudah ada)."""
    venv_py = python_venv(tujuan)
    if venv_py.exists() and _jalankan([str(venv_py), "-c", "import sys"], waktu=120).returncode == 0:
        _cetak("      Lingkungan Python .venv sudah ada — dipakai ulang.", diam)
        return venv_py
    if (tujuan / ".venv").exists():
        _cetak("      .venv ada tetapi tidak bisa dijalankan — dibuat ulang.", diam)
        shutil.rmtree(tujuan / ".venv", ignore_errors=True)
    _cetak("      Membuat lingkungan Python (.venv) ...", diam)
    hasil = _jalankan([str(python), "-m", "venv", str(tujuan / ".venv")], cwd=tujuan, waktu=600)
    if hasil.returncode != 0 or not venv_py.exists():
        raise GalatPemasang("Gagal membuat .venv:\n" + (hasil.stderr or hasil.stdout or "")[-600:])
    return venv_py


def pasang_dependensi(venv_py: Path, tujuan: Path, bahan: Path | None = None,
                      dengan_bot: bool = False, diam: bool = False) -> str:
    """Pasang pustaka dari ``requirements.txt`` (+ bot bila diminta).

    ``bahan`` = folder berisi berkas .whl (paket offline): pemasangan dilakukan tanpa
    internet (``--no-index --find-links``).
    """
    berkas_req = [tujuan / "requirements.txt"]
    if dengan_bot and (tujuan / "requirements-bot.txt").exists():
        berkas_req.append(tujuan / "requirements-bot.txt")

    dasar = [str(venv_py), "-m", "pip", "install", "--disable-pip-version-check", "--quiet"]
    tambahan: list[str] = []
    if bahan:
        if not bahan.exists():
            raise GalatPemasang(f"Folder bahan (berkas .whl) tidak ada: {bahan}")
        tambahan = ["--no-index", "--find-links", str(bahan)]
    for berkas in berkas_req:
        dasar += ["-r", str(berkas)]

    _cetak("      Memasang pustaka yang dibutuhkan" +
           (" (dari folder bahan, tanpa internet)" if bahan else " — perlu internet, sekali saja") +
           " ...", diam)
    hasil = _jalankan(dasar + tambahan, cwd=tujuan, waktu=3600)
    if hasil.returncode != 0 and bahan:
        # Sebagian pustaka (mis. odfpy) hanya tersedia sebagai kode sumber: bangun memakai
        # perkakas yang ada di .venv, tanpa perlu mengunduh dari internet.
        _cetak("      Ada pustaka yang perlu dibangun dari kode sumber — mencoba sekali lagi ...", diam)
        hasil = _jalankan(dasar + tambahan + ["--no-build-isolation"], cwd=tujuan, waktu=3600)
    if hasil.returncode != 0:
        pesan = (hasil.stderr or hasil.stdout or "").strip()[-800:]
        petunjuk = ("Periksa sambungan internet, atau buat paket lengkap dengan "
                    "`pasang.py buat-paket --dengan-bahan` lalu pasang dengan `--bahan`.")
        raise GalatPemasang(f"Pemasangan pustaka gagal:\n{pesan}\n{petunjuk}")

    kurang = _cek_pustaka(venv_py, ("fastapi", "uvicorn", "jinja2", "multipart",
                                    "itsdangerous", "openpyxl"))
    if kurang:
        raise GalatPemasang("Pustaka ini belum terpasang: " + ", ".join(kurang))
    status = "pustaka inti siap"
    if dengan_bot:
        status += (" · pustaka bot (selenium) siap" if not _cek_pustaka(venv_py, ("selenium",))
                   else " · pustaka bot belum siap")
    _cetak(f"      {status}.", diam)
    return status


# --------------------------------------------------------------------------- #
# Data, peluncur, pintasan, layanan otomatis
# --------------------------------------------------------------------------- #
def siapkan_data(tujuan: Path, python: Path, data: Path, diam: bool = False) -> dict:
    """Siapkan folder data + basis data (tidak pernah menimpa basis data yang sudah ada)."""
    data.mkdir(parents=True, exist_ok=True)
    db_lama = (data / "sm.sqlite3").exists()
    # Lingkungan bersih untuk proses aplikasi: folder data ditentukan di sini, dan penunjuk
    # basis data dari lingkungan luar (mis. saat dijalankan dari skrip pemeriksaan) dibuang
    # supaya basis data benar-benar dibuat di folder data yang dipilih.
    lingkungan = dict(os.environ, SM_DATA_DIR=str(data), PYTHONUTF8="1",
                      PYTHONIOENCODING="utf-8",
                      SM_AUTO_SEED="0", SM_EKSKUL_SEKOLAH="0")   # aplikasi baru: kosong
    lingkungan.pop("SM_DB_PATH", None)
    hasil = _jalankan([str(python), "run.py", "--init-db"], cwd=tujuan, env=lingkungan, waktu=900)
    if hasil.returncode != 0:
        pesan = (hasil.stderr or hasil.stdout or "").strip()[-600:]
        raise GalatPemasang(f"Gagal menyiapkan basis data:\n{pesan}")
    db = data / "sm.sqlite3"
    _cetak("      Basis data " + ("lama dipakai kembali (data sekolah tetap utuh)"
                                  if db_lama else "baru dibuat") + f": {db}", diam)
    return {"folder": str(data), "basis_data": str(db), "sudah_ada": db_lama}


def tulis_peluncur(tujuan: Path, python: Path, data: Path, port: int, diam: bool = False) -> list[str]:
    """Tulis berkas peluncur (Windows & Linux/macOS sekaligus) + bacaan singkat."""
    peluncur_win = tujuan / NAMA_PELUNCUR_WIN
    peluncur_nix = tujuan / NAMA_PELUNCUR_NIX

    # Peluncur tanpa jendela terminal: SM.vbs menjalankan SM-latar.py lewat pythonw.
    pythonw = python.parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = python
    (tujuan / "SM.vbs").write_text(
        "' Dibuat oleh pemasang SM — menjalankan aplikasi di belakang layar (tanpa terminal).\r\n"
        'Option Explicit\r\n'
        'Dim sh\r\n'
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.CurrentDirectory = "{tujuan}"\r\n'
        f'sh.Run """{pythonw}"" ""{tujuan / "SM-latar.py"}"" --port {port}", 0, False\r\n',
        encoding="utf-8")
    (tujuan / "Hentikan-SM.vbs").write_text(
        "' Dibuat oleh pemasang SM — mematikan aplikasi yang berjalan di belakang layar.\r\n"
        'Option Explicit\r\n'
        'Dim sh\r\n'
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run """{pythonw}"" ""{tujuan / "SM-latar.py"}"" --hentikan", 0, True\r\n',
        encoding="utf-8")

    peluncur_win.write_text(
        "@echo off\r\n"
        "REM Dibuat otomatis oleh pemasang SM — jangan diubah manual.\r\n"
        "setlocal EnableExtensions\r\n"
        "chcp 65001 >nul 2>nul\r\n"
        "cd /d \"%~dp0\"\r\n"
        f"set \"SM_DATA_DIR={data}\"\r\n"
        "set \"PYTHONUTF8=1\"\r\n"
        "set \"PYTHONIOENCODING=utf-8\"\r\n"
        f"set \"PY={python}\"\r\n"
        "if not exist \"%PY%\" set \"PY=python\"\r\n"
        "echo ============================================================\r\n"
        "echo   SM - Sistem Informasi Manajemen Sekolah\r\n"
        "echo ============================================================\r\n"
        f"echo   Buka di peramban: http://localhost:{port}\r\n"
        "echo   (Jendela ini hanya untuk memeriksa; jalankan SM.vbs bila ingin "
        "tanpa jendela.)\r\n"
        "echo.\r\n"
        f"\"%PY%\" run.py --host 0.0.0.0 --port {port}\r\n"
        "echo.\r\n"
        "echo Server berhenti. Tekan tombol apa pun untuk menutup jendela ini.\r\n"
        "pause\r\n",
        encoding="utf-8", newline="")

    peluncur_nix.write_text(
        "#!/usr/bin/env sh\n"
        "# Dibuat otomatis oleh pemasang SM — jangan diubah manual.\n"
        "cd \"$(dirname \"$0\")\" || exit 1\n"
        f"SM_DATA_DIR=\"{data}\"\n"
        "PYTHONUTF8=1\n"
        "PYTHONIOENCODING=utf-8\n"
        "export SM_DATA_DIR PYTHONUTF8 PYTHONIOENCODING\n"
        f"PY=\"{python}\"\n"
        "if [ ! -x \"$PY\" ]; then PY=$(command -v python3 || command -v python); fi\n"
        "echo '============================================================'\n"
        "echo '  SM - Sistem Informasi Manajemen Sekolah'\n"
        "echo '============================================================'\n"
        f"echo '  Buka di peramban: http://localhost:{port}'\n"
        "echo\n"
        f"exec \"$PY\" run.py --host 0.0.0.0 --port {port}\n",
        encoding="utf-8")
    peluncur_nix.chmod(0o755)

    (tujuan / NAMA_BACAAN).write_text(
        "SM - Sistem Informasi Manajemen Sekolah\n"
        "======================================\n\n"
        f"Versi aplikasi : {versi_aplikasi(tujuan)}\n"
        f"Folder program : {tujuan}\n"
        f"Folder data    : {data}\n"
        f"Alamat         : http://localhost:{port}\n\n"
        "Cara menjalankan\n"
        "----------------\n"
        f"  Windows     : klik dua kali {NAMA_PELUNCUR_WIN}\n"
        f"  Linux/macOS : ./{NAMA_PELUNCUR_NIX}\n\n"
        "Login\n"
        "-----\n"
        "  Petugas/admin : admin / admin123  (segera ganti sandinya di Pengaturan)\n"
        "  Siswa         : cukup NISN\n\n"
        "Catatan penting\n"
        "---------------\n"
        "* Semua data sekolah (basis data, berkas unggahan, hasil ekspor) ada di folder data\n"
        "  di atas. MENGGANTI aplikasi / memperbarui TIDAK menghapus data itu.\n"
        "* Cadangkan folder data secara berkala (mis. salin ke flashdisk/Drive).\n"
        "* Memperbarui versi  : python pemasang/pasang.py perbarui\n"
        "* Memeriksa kondisi  : python pemasang/pasang.py periksa\n"
        "* Menghapus aplikasi : python pemasang/pasang.py hapus --ya\n",
        encoding="utf-8")

    # Pencabut (Windows): matikan → bersihkan → hapus. Disimpan juga di LUAR folder aplikasi
    # supaya entri Control Panel tetap bisa mencabut walau foldernya terlanjur dihapus orang.
    info_pencabut: dict = {}
    if pencabut_sm is not None:
        try:
            info_pencabut = pencabut_sm.tulis_pencabut(tujuan, data, python, pythonw)
        except Exception as exc:      # noqa: BLE001 — jangan gagalkan pemasangan
            _cetak(f"      [!] Berkas pencabut gagal dibuat: {exc}", diam)

    berkas_pencabut = list(info_pencabut.get("berkas", []))
    _cetak(f"      Peluncur dibuat: {NAMA_PELUNCUR_WIN} & {NAMA_PELUNCUR_NIX} "
           "(Windows juga: SM.vbs tanpa jendela, Hentikan-SM.vbs, Hapus-SM.cmd/vbs)", diam)
    if info_pencabut.get("folder"):
        _cetak(f"      Pencabut disiapkan di luar folder aplikasi: {info_pencabut['folder']} "
               "(dipakai Control Panel)", diam)
    return [str(peluncur_win), str(peluncur_nix), str(tujuan / "SM.vbs"),
            str(tujuan / "Hentikan-SM.vbs"), *berkas_pencabut]


def _desktop_dir() -> Path:
    rumah = folder_beranda()
    if os.name == "nt":
        return rumah / "Desktop"
    if sys.platform == "darwin":
        return rumah / "Desktop"
    return Path(os.environ.get("XDG_DESKTOP_DIR") or rumah / "Desktop")


def buat_pintasan(tujuan: Path, diam: bool = False) -> list[str]:
    """Buat pintasan (ikon di desktop / menu aplikasi). Mengembalikan jalur yang dibuat."""
    dibuat: list[str] = []

    if os.name == "nt":
        peluncur = tujuan / NAMA_PELUNCUR_WIN
        vbs = tujuan / "SM.vbs"
        wscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"
        target = str(wscript) if vbs.exists() else str(peluncur)
        argumen = f'"{vbs}"' if vbs.exists() else ""
        skrip = (
            "$w = New-Object -ComObject WScript.Shell; "
            f"$s = $w.CreateShortcut('{_desktop_dir() / 'SM.lnk'}'); "
            f"$s.TargetPath = '{target}'; $s.Arguments = '{argumen}'; "
            f"$s.WorkingDirectory = '{tujuan}'; "
            "$s.Description = 'SM - Sistem Informasi Manajemen Sekolah'; $s.Save()")
        hasil = _jalankan(["powershell", "-NoProfile", "-NonInteractive", "-Command", skrip],
                          waktu=120)
        if hasil.returncode == 0:
            dibuat.append(str(_desktop_dir() / "SM.lnk"))
    else:
        aplikasi = (Path(os.environ.get("XDG_DATA_HOME") or folder_beranda() / ".local" / "share")
                    / "applications" / "sm-sekolah.desktop")
        aplikasi.parent.mkdir(parents=True, exist_ok=True)
        aplikasi.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=SM - Sistem Informasi Manajemen Sekolah\n"
            f"Exec={tujuan / NAMA_PELUNCUR_NIX}\n"
            f"Path={tujuan}\n"
            "Terminal=true\n"
            "Categories=Office;Education;\n", encoding="utf-8")
        aplikasi.chmod(0o755)
        dibuat.append(str(aplikasi))
        desktop = _desktop_dir()
        if desktop.is_dir():
            pintasan = desktop / "SM.desktop"
            shutil.copy2(aplikasi, pintasan)
            pintasan.chmod(0o755)
            dibuat.append(str(pintasan))

    if dibuat:
        _cetak("      Pintasan dibuat: " + ", ".join(dibuat), diam)
    else:
        _cetak("      Pintasan tidak bisa dibuat pada sistem ini (aplikasi tetap bisa dipakai).", diam)
    return dibuat


def berkas_otomatis() -> dict:
    """Jalur berkas «jalankan otomatis saat komputer menyala» menurut sistem."""
    rumah = folder_beranda()
    if os.name == "nt":
        startup = Path(os.environ.get("APPDATA", str(rumah / "AppData/Roaming"))) / \
            "Microsoft/Windows/Start Menu/Programs/Startup"
        return {"berkas": startup / "SM.cmd", "jenis": "windows"}
    if sys.platform == "darwin":
        return {"berkas": rumah / "Library/LaunchAgents/id.sekolah.sm.plist", "jenis": "launchd"}
    dasar = Path(os.environ.get("XDG_CONFIG_HOME") or rumah / ".config")
    return {"berkas": dasar / "systemd/user/sm-sekolah.service", "jenis": "systemd",
            "cadangan": dasar / "autostart/sm-sekolah.desktop"}


def pasang_otomatis(tujuan: Path, python: Path, data: Path, port: int,
                    aktif: bool = True, diam: bool = False) -> list[str]:
    """Nyalakan/matikan «SM ikut menyala saat komputer dinyalakan»."""
    info = berkas_otomatis()
    berkas: Path = info["berkas"]
    hasil: list[str] = []

    if not aktif:
        for jalur in (berkas, info.get("cadangan")):
            if jalur and Path(jalur).exists():
                Path(jalur).unlink()
                hasil.append(f"dihapus: {jalur}")
        if info["jenis"] == "systemd" and shutil.which("systemctl"):
            _jalankan(["systemctl", "--user", "disable", "sm-sekolah.service"], waktu=60)
        _cetak("      «Jalankan otomatis» dimatikan.", diam)
        return hasil

    berkas.parent.mkdir(parents=True, exist_ok=True)
    if info["jenis"] == "windows":
        berkas.write_text(
            "@echo off\r\n"
            "REM Dibuat otomatis oleh pemasang SM — SM ikut menyala saat Windows masuk.\r\n"
            f"start \"SM\" /min \"{tujuan / NAMA_PELUNCUR_WIN}\"\r\n", encoding="utf-8", newline="")
    elif info["jenis"] == "systemd":
        berkas.write_text(
            "[Unit]\n"
            "Description=SM - Sistem Informasi Manajemen Sekolah\n"
            "After=network.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"WorkingDirectory={tujuan}\n"
            f"Environment=SM_DATA_DIR={data}\n"
            "Environment=PYTHONUTF8=1\n"
            f"ExecStart={python} run.py --host 0.0.0.0 --port {port}\n"
            "Restart=on-failure\n"
            "RestartSec=3\n\n"
            "[Install]\n"
            "WantedBy=default.target\n", encoding="utf-8")
        if shutil.which("systemctl"):
            _jalankan(["systemctl", "--user", "daemon-reload"], waktu=60)
            _jalankan(["systemctl", "--user", "enable", "sm-sekolah.service"], waktu=60)
        else:
            # Tanpa systemd: pakai mekanisme autostart desktop yang lebih sederhana.
            cadangan: Path = info["cadangan"]
            cadangan.parent.mkdir(parents=True, exist_ok=True)
            cadangan.write_text(
                "[Desktop Entry]\nType=Application\nName=SM Sekolah\n"
                f"Exec={tujuan / NAMA_PELUNCUR_NIX}\nPath={tujuan}\nTerminal=true\n"
                "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")
            hasil.append(str(cadangan))
    else:      # macOS
        berkas.write_text(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
            "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
            "<plist version=\"1.0\"><dict>\n"
            "  <key>Label</key><string>id.sekolah.sm</string>\n"
            "  <key>ProgramArguments</key><array>"
            f"<string>{python}</string><string>{tujuan}/run.py</string>"
            f"<string>--port</string><string>{port}</string></array>\n"
            f"  <key>WorkingDirectory</key><string>{tujuan}</string>\n"
            "  <key>EnvironmentVariables</key><dict>"
            f"<key>SM_DATA_DIR</key><string>{data}</string></dict>\n"
            "  <key>RunAtLoad</key><true/>\n"
            "</dict></plist>\n", encoding="utf-8")
    hasil.append(str(berkas))
    _cetak("      «Jalankan otomatis» disiapkan: " + str(berkas), diam)
    return hasil


# --------------------------------------------------------------------------- #
# Perintah: pasang / perbarui
# --------------------------------------------------------------------------- #
def pasang(args, sumber: Path | None = None) -> dict:
    """Pasang (atau perbarui) aplikasi SM."""
    sumber = Path(sumber or AKAR_PAKET).resolve()
    tujuan = Path(args.tujuan).expanduser().resolve() if args.tujuan else tujuan_bawaan()
    diam = bool(args.diam or args.json)
    portabel = bool(args.tanpa_venv)
    # PENTING: jangan `.resolve()` — di lingkungan .venv, `bin/python` adalah tautan ke
    # Python sistem; bila tautannya diikuti, pustaka milik .venv ikut hilang.
    python = Path(sys.executable).expanduser().absolute()
    catatan_lama = baca_catatan(tujuan)
    perbarui = bool(catatan_lama)
    if not args.port:
        args.port = int(catatan_lama.get("port") or 8000)

    if sys.version_info < VERSI_MINIMUM:
        raise GalatPemasang(
            "Python terlalu tua: versi {}.{}.{} — SM butuh Python {} atau lebih baru.".format(
                *sys.version_info[:3], ".".join(str(x) for x in VERSI_MINIMUM)))

    if tujuan.exists() and any(tujuan.iterdir()) and not perbarui and not args.paksa:
        raise GalatPemasang(
            f"Folder tujuan sudah berisi berkas lain:\n  {tujuan}\n"
            "Agar tidak ada berkas yang tertimpa, pemasangan dihentikan. Pilihan:\n"
            "  * pakai folder lain            : --tujuan <folder lain>\n"
            "  * tetap memasang ke folder itu : tambahkan --paksa")

    _cetak("=" * 66, diam)
    _cetak("  SM — pemasang aplikasi", diam)
    _cetak("=" * 66, diam)
    _cetak(f"  Versi paket    : {versi_aplikasi(sumber)}", diam)
    _cetak(f"  Folder paket   : {sumber}", diam)
    _cetak(f"  Folder tujuan  : {tujuan}"
           + ("   (pemasangan sudah ada → diperbarui)" if perbarui else ""), diam)
    _cetak(f"  Modus Python   : {'portabel (pakai Python yang ini)' if portabel else 'lingkungan .venv sendiri'}",
           diam)
    _cetak("", diam)

    # 1) salin program
    _cetak("[1/5] Menyalin program ...", diam)
    jumlah_berkas = salin_program(sumber, tujuan, diam)

    # 2) lingkungan Python
    if portabel:
        _cetak("[2/5] Lingkungan Python: memakai Python yang sedang dipakai (portabel) ...", diam)
        venv_py = python
        kurang = _cek_pustaka(venv_py, ("fastapi", "uvicorn", "jinja2", "multipart",
                                        "itsdangerous", "openpyxl"))
        if kurang:
            raise GalatPemasang(
                "Modus portabel memakai Python yang sudah ada, dan pustaka ini belum ada: "
                + ", ".join(kurang) + ".\nJalankan tanpa --tanpa-venv agar pemasang membuat "
                ".venv sendiri, atau pasang dulu: pip install -r requirements.txt")
        status_pustaka = "portabel (pustaka dari Python yang dipakai)"
    else:
        _cetak("[2/5] Lingkungan Python (.venv) ...", diam)
        venv_py = buat_venv(tujuan, python, diam)

    # 3) data
    data = Path(args.data).expanduser().resolve() if args.data else tujuan / "data"
    _cetak(f"[3/5] Menyiapkan folder data ({data}) ...", diam)

    # 4) dependensi + basis data
    if not portabel:
        status_pustaka = pasang_dependensi(
            venv_py, tujuan, bahan=Path(args.bahan).expanduser().resolve() if args.bahan else None,
            dengan_bot=bool(args.dengan_bot), diam=diam)
    info_data = siapkan_data(tujuan, venv_py, data, diam)

    # 5) peluncur & catatan
    _cetak("[4/5] Membuat peluncur & catatan ...", diam)
    peluncur = tulis_peluncur(tujuan, venv_py, data, args.port, diam)
    pintasan: list[str] = []
    otomatis: list[str] = []
    if args.pintasan:
        pintasan = buat_pintasan(tujuan, diam)
    if args.otomatis:
        otomatis = pasang_otomatis(tujuan, venv_py, data, args.port, True, diam)

    daftar_app: list[str] = []
    if not args.tanpa_daftar:
        daftar_app = daftarkan_control_panel(tujuan, data, versi_aplikasi(tujuan), diam)

    _cetak("[5/5] Selesai.", diam)
    catatan = {
        "versi": versi_aplikasi(tujuan),
        "dipasang_pada": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tujuan": str(tujuan),
        "data": str(data),
        "port": args.port,
        "modus": "portabel" if portabel else "venv",
        "python": str(venv_py),
        "python_dasar": str(python),
        "berkas": jumlah_berkas,
        "pustaka": status_pustaka,
        "peluncur": peluncur,
        "pintasan": pintasan,
        "otomatis": otomatis,
        "pencabut": str(pencabut_sm.folder_pencabut()) if pencabut_sm else "",
        "control_panel": daftar_app,
        "catatan_sebelumnya": catatan_lama.get("dipasang_pada", ""),
    }
    tulis_catatan(tujuan, catatan)

    hasil = {
        "ok": True,
        "perintah": "perbarui" if perbarui else "pasang",
        "menimpa_pemasangan_lama": perbarui,
        "peluncur_nix": str(tujuan / NAMA_PELUNCUR_NIX),
        "peluncur_win": str(tujuan / NAMA_PELUNCUR_WIN),
        **catatan,
        **info_data,
    }
    if not args.json:
        diam = False
        _cetak("", diam)
        _cetak("  Aplikasi SM siap dipakai.", diam)
        _cetak(f"  Folder program : {tujuan}", diam)
        _cetak(f"  Folder data    : {data}", diam)
        _cetak(f"  Menjalankan    : {tujuan / NAMA_PELUNCUR_WIN}  (Windows)", diam)
        _cetak(f"                   {tujuan / NAMA_PELUNCUR_NIX}   (Linux/macOS)", diam)
        _cetak(f"  Alamat         : http://localhost:{args.port}", diam)
        _cetak("  Login petugas  : admin / admin123   ·   siswa: cukup NISN", diam)
        _cetak("", diam)
        _cetak("  Perintah lain: periksa · perbarui · hapus --ya · dari-zip · buat-paket", diam)
    return hasil


# --------------------------------------------------------------------------- #
# Perintah: periksa (dokter)
# --------------------------------------------------------------------------- #
def daftarkan_control_panel(tujuan: Path, data: Path, versi: str, diam: bool = False) -> list[str]:
    """Daftarkan SM di **Control Panel → Programs and Features** (Windows; HKCU tanpa admin)."""
    if pencabut_sm is None:
        return []
    ikon = tujuan / "bodap.ico"
    try:
        kunci = pencabut_sm.daftarkan(tujuan, data, versi, ikon if ikon.exists() else None)
    except Exception as exc:      # noqa: BLE001 — bukan syarat pemasangan
        _cetak(f"      [!] Pendaftaran di Control Panel gagal: {exc}", diam)
        return []
    if kunci:
        _cetak("      Terdaftar di Control Panel → «Programs and Features» "
               "(bisa dicabut dari sana).", diam)
    return kunci


def periksa(args) -> dict:
    """Periksa kondisi pemasangan & ceritakan apa adanya (tanpa mengubah apa pun)."""
    diam = bool(args.diam or args.json)
    tujuan = Path(args.tujuan).expanduser().resolve() if args.tujuan else tujuan_bawaan()
    catatan = baca_catatan(tujuan)
    data = Path(args.data).expanduser().resolve() if args.data else \
        Path(catatan.get("data") or (tujuan / "data"))
    port = args.port or int(catatan.get("port") or 8000)
    modus = catatan.get("modus", "venv")
    python = Path(catatan.get("python") or sys.executable)

    ada_peluncur = (tujuan / NAMA_PELUNCUR_WIN).exists() or (tujuan / NAMA_PELUNCUR_NIX).exists()
    db = data / "sm.sqlite3"
    kurang: list[str] = []
    if python.exists():
        kurang = _cek_pustaka(python, ("fastapi", "uvicorn", "jinja2", "multipart",
                                       "itsdangerous", "openpyxl"))
    else:
        kurang = ["python tidak ditemukan"]

    terdaftar_cp = bool(pencabut_sm and pencabut_sm.terdaftar())
    _jalur_pencabut = catatan.get("pencabut") or \
        (str(pencabut_sm.folder_pencabut()) if pencabut_sm else "")
    folder_pencabut = Path(_jalur_pencabut) if _jalur_pencabut else None
    laporan = {
        "ok": bool(catatan) and ada_peluncur and db.exists() and not kurang,
        "perintah": "periksa",
        "control_panel": terdaftar_cp,
        "pencabut": str(folder_pencabut) if folder_pencabut else "",
        "pencabut_ada": bool(pencabut_sm and folder_pencabut
                             and (folder_pencabut / pencabut_sm.NAMA_VBS).exists()),
        "terpasang": bool(catatan),
        "versi": catatan.get("versi", versi_aplikasi(tujuan)),
        "tujuan": str(tujuan),
        "data": str(data),
        "port": port,
        "port_bebas": port_bebas(port),
        "modus": modus,
        "python": str(python),
        "python_versi": platform.python_version() if python == Path(sys.executable)
        else _versi_python(python),
        "pustaka_kurang": kurang,
        "dependensi_siap": not kurang,
        "basis_data_ada": db.exists(),
        "basis_data_ukuran": db.stat().st_size if db.exists() else 0,
        "data_bisa_ditulis": _bisa_ditulis(data),
        "peluncur": ada_peluncur,
        "selenium": not _cek_pustaka(python, ("selenium",)) if python.exists() else None,
        "chrome": cari_chrome(),
        "sistem": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "disk_bebas_mb": round(shutil.disk_usage(_ada_atau(tujuan)).free / 1024 / 1024),
    }

    if not args.json:
        _cetak("=" * 66, diam)
        _cetak("  SM — pemeriksaan pemasangan", diam)
        _cetak("=" * 66, diam)
        _cetak(f"  Terpasang       : {'ya' if laporan['terpasang'] else 'BELUM'}  (versi {laporan['versi']})", diam)
        _cetak(f"  Folder program  : {tujuan}", diam)
        _cetak(f"  Folder data     : {data}", diam)
        _cetak(f"  Basis data      : {'ada' if db.exists() else 'belum ada'}"
               f" ({laporan['basis_data_ukuran'] / 1024:.0f} KB)", diam)
        _cetak(f"  Python          : {python} ({modus}) — {laporan['python_versi']}", diam)
        _cetak(f"  Pustaka kurang  : {', '.join(kurang) if kurang else 'tidak ada'}", diam)
        _cetak(f"  Port {port}       : {'bebas' if laporan['port_bebas'] else 'SUDAH DIPAKAI proses lain'}", diam)
        _cetak(f"  Peluncur        : {'ada' if ada_peluncur else 'belum ada'}", diam)
        _cetak(f"  Control Panel   : " + ("terdaftar — bisa dicabut dari sana"
                                           if laporan["control_panel"]
                                           else "belum terdaftar di «Aplikasi & Fitur»"), diam)
        if laporan["pencabut"]:
            _cetak(f"  Pencabut        : {laporan['pencabut']} "
                   f"({'ada' if laporan['pencabut_ada'] else 'TIDAK ADA'})", diam)
        _cetak(f"  Selenium (bot)  : {'siap' if laporan['selenium'] else 'belum terpasang'}", diam)
        _cetak(f"  Chrome (bot)    : {laporan['chrome'] or 'tidak ditemukan — bot Dapodik butuh Chrome'}", diam)
        _cetak(f"  Sistem          : {laporan['sistem']} · sisa disk {laporan['disk_bebas_mb']} MB", diam)
        _cetak("", diam)
        _cetak("  Hasil: " + ("SEMUA SIAP — jalankan aplikasi dari peluncurnya." if laporan["ok"]
                               else "ADA YANG PERLU DIBERESKAN (lihat baris di atas)."), diam)
    return laporan


def _versi_python(python: Path) -> str:
    hasil = _jalankan([str(python), "-c", "import sys; print(sys.version.split()[0])"], waktu=60)
    return hasil.stdout.strip() or "tidak diketahui"


def _bisa_ditulis(folder: Path) -> bool:
    """Bisakah berkas dibuat di folder ini? — TIDAK membuat foldernya (periksa = tanpa perubahan)."""
    uji_di = folder
    while not uji_di.exists() and uji_di != uji_di.parent:
        uji_di = uji_di.parent
    try:
        uji = uji_di / ".sm-uji-tulis"
        uji.write_text("ok", encoding="utf-8")
        uji.unlink()
        return True
    except OSError:
        return False


def _ada_atau(folder: Path) -> Path:
    return folder if folder.exists() else folder.parent


# --------------------------------------------------------------------------- #
# Perintah: hapus
# --------------------------------------------------------------------------- #
def hapus(args) -> dict:
    """Hapus aplikasi. Data di luar folder program TIDAK dihapus (kecuali diminta)."""
    diam = bool(args.diam or args.json)
    tujuan = Path(args.tujuan).expanduser().resolve() if args.tujuan else tujuan_bawaan()
    catatan = baca_catatan(tujuan)
    data = Path(catatan.get("data") or (tujuan / "data")).expanduser().resolve()

    terpasang = (tujuan / NAMA_PENANDA).exists() or (tujuan / "run.py").exists()
    if tujuan.exists() and not terpasang and not getattr(args, "paksa", False):
        raise GalatPemasang(f"Folder ini tidak terlihat sebagai pemasangan SM: {tujuan}\n"
                            "  (tidak ada .sm-pemasangan.json / run.py). Pakai --paksa bila yakin.")

    if not args.ya:
        raise GalatPemasang("Perintah hapus perlu penegasan. Tambahkan --ya, mis.:\n"
                            f"  python pemasang/pasang.py hapus --tujuan \"{tujuan}\" --ya")

    data_di_luar = data != (tujuan / "data") and not str(data).startswith(str(tujuan) + os.sep)
    dihapus: list[str] = []

    # 1) jalankan-otomatis & pintasan
    pasang_otomatis(tujuan, sys.executable, data, 0, aktif=False, diam=True)
    pintasan = [
        _desktop_dir() / "SM.desktop",
        (Path(os.environ.get("XDG_DATA_HOME") or folder_beranda() / ".local" / "share")
         / "applications" / "sm-sekolah.desktop"),
        _desktop_dir() / "SM.lnk",
    ]
    for jalur in pintasan:
        try:
            if jalur.exists():
                jalur.unlink()
                dihapus.append(str(jalur))
        except OSError:
            pass

    # 2) folder program
    if tujuan.exists():
        shutil.rmtree(tujuan)
        dihapus.append(str(tujuan))

    # 2b) entri Control Panel + berkas pencabut di luar folder aplikasi
    if pencabut_sm is not None:
        if pencabut_sm.hapus_pendaftaran():
            dihapus.append(pencabut_sm.KUNCI_ARP)
        luar = pencabut_sm.hapus_folder_pencabut(tujuan, catatan.get("pencabut"))
        if luar:
            dihapus.append(luar)

    # 3) data
    if args.dengan_data:
        if data.exists():
            shutil.rmtree(data)
            dihapus.append(str(data))
    elif data_di_luar:
        _cetak(f"      Data sekolah DIBIARKAN di: {data}", diam)
    elif not data_di_luar:
        pass      # data ada di dalam folder program → ikut terhapus bersama folder itu

    hasil = {"ok": True, "perintah": "hapus", "tujuan": str(tujuan),
             "dihapus": dihapus, "data_dibiarkan": str(data) if (data.exists() and not args.dengan_data) else "",
             "dengan_data": bool(args.dengan_data)}
    if not args.json:
        _cetak("  Pemasangan SM dihapus.", diam)
        for jalur in dihapus:
            _cetak(f"    - {jalur}", diam)
        if hasil["data_dibiarkan"]:
            _cetak(f"  Data sekolah tetap ada di: {hasil['data_dibiarkan']}", diam)
    return hasil


# --------------------------------------------------------------------------- #
# Perintah: dari-zip
# --------------------------------------------------------------------------- #
def dari_zip(args) -> dict:
    """Pasang dari berkas ZIP paket (mis. ``SM-0.1.0-paket.zip``)."""
    paket = Path(args.paket).expanduser().resolve()
    if not paket.exists():
        raise GalatPemasang(f"Berkas paket tidak ada: {paket}")
    with tempfile.TemporaryDirectory(prefix="sm-pasang-") as sementara:
        shutil.unpack_archive(str(paket), sementara)
        akar = Path(sementara)
        # ZIP buatan Windows kadang punya satu folder pembungkus di dalamnya.
        if not (akar / "run.py").exists():
            kandidat = [p for p in akar.iterdir() if (p / "run.py").exists()]
            if not kandidat:
                raise GalatPemasang("Di dalam ZIP tidak ada run.py — bukan paket SM.")
            akar = kandidat[0]
        bahan = None
        for mungkin in (akar / "bahan" / "pip", akar / "bahan"):
            if mungkin.is_dir() and any(mungkin.glob("*.whl")):
                bahan = mungkin
                break
        if bahan and not args.bahan:
            args.bahan = str(bahan)
        return pasang(args, sumber=akar)


# --------------------------------------------------------------------------- #
# Perintah: buat-paket (delegasi ke buat_paket.py)
# --------------------------------------------------------------------------- #
def buat_paket(args) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import buat_paket as bp       # noqa: PLC0415 — diimpor hanya saat dipakai

    return bp.buat(args)


# --------------------------------------------------------------------------- #
# Baris perintah
# --------------------------------------------------------------------------- #
def buat_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pasang.py",
        description="Pemasang aplikasi SM (Sistem Informasi Manajemen Sekolah).",
        epilog="Contoh: python pemasang/pasang.py --tujuan C:\\SM "
               "| python pemasang/pasang.py periksa --json")
    parser.add_argument("perintah", nargs="?", default="pasang",
                        choices=["pasang", "perbarui", "hapus", "periksa", "info",
                                 "dari-zip", "buat-paket"],
                        help="tindakan yang dijalankan (bawaan: pasang)")
    parser.add_argument("--tujuan", help="folder pemasangan (bawaan: folder aplikasi pengguna)")
    parser.add_argument("--data", help="folder data sekolah (bawaan: <tujuan>/data)")
    parser.add_argument("--port", type=int, default=None, help="port aplikasi (bawaan 8000)")
    parser.add_argument("--tanpa-venv", action="store_true",
                        help="modus portabel: pakai Python yang sedang menjalankan pemasang")
    parser.add_argument("--dengan-bot", action="store_true",
                        help="sekalian pasang pustaka Bot Dapodik (selenium)")
    parser.add_argument("--bahan", help="folder berisi berkas .whl untuk pemasangan tanpa internet")
    parser.add_argument("--pintasan", action="store_true", help="buat pintasan di desktop/menu")
    parser.add_argument("--otomatis", action="store_true",
                        help="jalankan SM otomatis saat komputer dinyalakan")
    parser.add_argument("--paksa", action="store_true",
                        help="izinkan memasang ke folder yang sudah berisi berkas lain")
    parser.add_argument("--tanpa-daftar", action="store_true",
                        help="jangan daftarkan di Control Panel / Pengaturan → Aplikasi (Windows)")
    parser.add_argument("--ya", action="store_true", help="penegasan untuk perintah hapus")
    parser.add_argument("--dengan-data", action="store_true",
                        help="saat hapus: ikut hapus folder data (data sekolah!)")
    parser.add_argument("--paket", help="berkas ZIP untuk perintah dari-zip")
    parser.add_argument("--json", action="store_true", help="keluarkan ringkasan dalam bentuk JSON")
    parser.add_argument("--diam", action="store_true", help="tidak menampilkan langkah-langkah")
    # khusus buat-paket
    parser.add_argument("--keluar", help="(buat-paket) nama berkas ZIP hasil")
    parser.add_argument("--dengan-bahan", action="store_true",
                        help="(buat-paket) ikutkan berkas .whl sehingga bisa dipasang tanpa internet")
    parser.add_argument("--untuk-platform", default="",
                        help="(buat-paket) mis. win_amd64 / manylinux2014_x86_64")
    parser.add_argument("--untuk-python", default="",
                        help="(buat-paket) mis. 3.12")
    parser.add_argument("--bahan-hasil", help="(buat-paket) folder bahan yang dibuat")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = buat_parser()
    args = parser.parse_args(argv)
    if args.perintah == "info":
        args.perintah = "periksa"
    if args.perintah == "perbarui":       # perbarui = pasang ke folder yang sudah ada
        args.perintah = "pasang"
    try:
        if args.perintah == "pasang":
            hasil = pasang(args)
        elif args.perintah == "periksa":
            hasil = periksa(args)
        elif args.perintah == "hapus":
            hasil = hapus(args)
        elif args.perintah == "dari-zip":
            if not args.paket:
                raise GalatPemasang("Perintah dari-zip perlu --paket <berkas.zip>")
            hasil = dari_zip(args)
        else:
            hasil = buat_paket(args)
    except GalatPemasang as exc:
        if args.json:
            print(json.dumps({"ok": False, "galat": str(exc)}, ensure_ascii=False))
        else:
            print(f"\n[!] {exc}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[!] Dibatalkan.", file=sys.stderr)
        return 130

    if args.json:
        print(json.dumps(hasil, ensure_ascii=False))
    return 0 if hasil.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
