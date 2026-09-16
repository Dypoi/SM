"""Pembaruan aplikasi langsung dari dalam SIMSEK (``git pull``).

Modul ini dipakai halaman **Pengaturan → Pembaruan Aplikasi** agar admin dapat
menarik pembaruan kode (``git pull``) tanpa membuka Command Prompt.

Yang tersedia:

* :func:`status_pembaruan` — ringkasan kondisi salinan aplikasi (cabang,
  komit terakhir, jumlah komit tertinggal, perubahan lokal yang belum
  disimpan, dan riwayat pembaruan terakhir).
* :func:`terapkan_pembaruan` — menjalankan ``git fetch`` + ``git pull
  --ff-only`` lalu memasang dependensi baru bila ``requirements.txt`` berubah.
* :func:`minta_muat_ulang` / :func:`perlu_muat_ulang` — mekanisme memuat ulang
  server (proses diganti dengan ``os.execv``) supaya kode baru langsung aktif.
* :func:`otomatis_periksa` — dipanggil berkala oleh pemantau latar belakang.

Semua operasi aman saat gagal: pesannya berbahasa Indonesia dan tidak pernah
melempar pengecualian ke halaman web. Bila aplikasi tidak dijalankan dari
salinan git (misalnya hasil unduh ZIP), modul ini otomatis memberi petunjuk
manual.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, db, services

BASE_DIR = config.BASE_DIR
GIT_TIMEOUT = int(os.getenv("SM_GIT_TIMEOUT", "180"))
PIP_TIMEOUT = int(os.getenv("SM_PIP_TIMEOUT", "900"))

#: Menonaktifkan fitur pembaruan: ``SM_GIT_UPDATE=0``.
AKTIF = os.getenv("SM_GIT_UPDATE", "1").lower() not in {"0", "false", "no"}

RESTART_MARKER = config.DATA_DIR / "restart-request.json"
STATUS_FILE = config.DATA_DIR / "update-status.json"
LOG_DIR = config.DATA_DIR / "logs"

#: Waktu modul dimuat — dipakai untuk memastikan server hanya memuat ulang
#: sekali untuk setiap permintaan (menghindari gelung muat ulang).
PROSES_MULAI = time.time()

#: Jeda minimal antara tombol "muat ulang" dan proses penggantian diri,
#: supaya balasan HTTP (pengalihan + pesan) sempat terkirim lebih dulu.
JEDA_MUAT_ULANG = 3.0

#: Selang pemeriksaan tanda muat ulang oleh pemantau latar belakang (detik).
SELANG_PANTAU = 3.0

SETTING_DEFAULT = {
    "update_auto_cek": "1",
    "update_interval_jam": "6",
    "update_auto_tarik": "0",
    "update_restart_otomatis": "0",
    "update_remote": "origin",
    "update_cabang": "",
}


# --------------------------------------------------------------------------- #
# Utilitas git
# --------------------------------------------------------------------------- #
def _git_path() -> str | None:
    """Cari berkas ``git`` yang bisa dipanggil."""
    kandidat = [
        os.getenv("SM_GIT_BIN") or "",
        shutil.which("git") or "",
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        "/usr/bin/git",
        "/usr/local/bin/git",
    ]
    for kandidat_path in kandidat:
        if kandidat_path and Path(kandidat_path).exists():
            return kandidat_path
    return None


def _env_git() -> dict[str, str]:
    """Environment bersih: tanpa prompt, tanpa variabel git dari proses induk."""
    env = os.environ.copy()
    for key in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
        "GIT_ASKPASS", "SSH_ASKPASS", "GIT_CONFIG_PARAMETERS", "GIT_CEILING_DIRECTORIES",
    ):
        env.pop(key, None)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "LC_ALL": "C", "LANG": "C"})
    return env


def jalankan_git(perintah: list[str], timeout: int = GIT_TIMEOUT) -> tuple[int, str]:
    """Jalankan perintah git. Mengembalikan ``(kode_keluar, keluaran)``."""
    git = _git_path()
    if git is None:
        return 127, "Perintah git tidak ditemukan. Pasang Git lalu coba lagi."
    try:
        hasil = subprocess.run(
            [git, *perintah],
            cwd=str(BASE_DIR),
            env=_env_git(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"Perintah 'git {' '.join(perintah)}' melebihi batas {timeout} detik."
    except OSError as exc:  # pragma: no cover - lingkungan aneh
        return 126, f"Gagal menjalankan git: {exc}"
    keluaran = ((hasil.stdout or "") + (hasil.stderr or "")).strip()
    return hasil.returncode, keluaran


def _rev(ref: str = "HEAD") -> str:
    kode, keluaran = jalankan_git(["rev-parse", "--short", ref])
    return keluaran if kode == 0 else ""


def _ref_remote(remote: str, cabang: str) -> str:
    """Nama ref pelacak remote, mis. ``origin/arena/01a0a87a-sm``."""
    return f"{remote}/{cabang}"


def ambil_pembaruan(remote: str, cabang: str) -> tuple[int, str]:
    """``git fetch`` dengan refspec eksplisit agar ref pelacak remote ikut dibuat.

    Tanpa refspec eksplisit, salinan yang di-``clone`` dengan ``--single-branch``
    tidak menyimpan ``origin/<cabang>`` sehingga perbandingan revisi gagal.
    """
    refspec = f"+refs/heads/{cabang}:refs/remotes/{remote}/{cabang}"
    return jalankan_git(["fetch", "--prune", remote, refspec])


def _ada_berkas_git() -> bool:
    return (BASE_DIR / ".git").exists()


def informasi_git() -> dict[str, Any]:
    """Info dasar: ketersediaan git, versi, cabang, remote, dan url remote."""
    git = _git_path()
    info: dict[str, Any] = {
        "git": git or "",
        "versi": "",
        "repo": _ada_berkas_git(),
        "cabang": "",
        "remote": "origin",
        "url": "",
        "bisa": False,
        "alasan": "",
    }
    if not AKTIF:
        info["alasan"] = "Fitur pembaruan dinonaktifkan lewat SM_GIT_UPDATE=0."
        return info
    if git is None:
        info["alasan"] = (
            "Git belum terpasang di komputer ini. Unduh di https://git-scm.com/downloads "
            "lalu jalankan ulang aplikasi, atau perbarui secara manual."
        )
        return info
    if not info["repo"]:
        info["alasan"] = (
            "Folder aplikasi ini bukan salinan git (kemungkinan hasil unduh ZIP), "
            "jadi pembaruan otomatis belum bisa dipakai. Lihat petunjuk di bawah."
        )
        return info

    kode, keluaran = jalankan_git(["rev-parse", "--is-inside-work-tree"])
    if kode != 0 or keluaran.strip() != "true":
        info["alasan"] = "Folder aplikasi bukan repositori git yang sah."
        return info

    _, versi = jalankan_git(["version"])
    info["versi"] = versi
    _, cabang = jalankan_git(["rev-parse", "--abbrev-ref", "HEAD"])
    info["cabang"] = "" if cabang.strip() in {"", "HEAD"} else cabang.strip()
    remote = services.get_setting("update_remote") or "origin"
    _, daftar_remote = jalankan_git(["remote"])
    if remote not in daftar_remote.split():
        remote = (daftar_remote.split() or ["origin"])[0]
    info["remote"] = remote
    _, url = jalankan_git(["remote", "get-url", remote])
    info["url"] = url.strip()
    info["bisa"] = True
    return info


def cabang_target(info: dict[str, Any] | None = None) -> str:
    """Cabang yang dipakai untuk menarik pembaruan (default: cabang aktif)."""
    info = info or informasi_git()
    dipilih = (services.get_setting("update_cabang") or "").strip()
    if dipilih:
        return dipilih
    return info.get("cabang") or "main"


def daftar_cabang_remote(remote: str = "origin") -> list[str]:
    """Daftar cabang di GitHub (mis. ``origin/main``) untuk pilihan di halaman."""
    kode, keluaran = jalankan_git(["branch", "--remotes", f"--format=%(refname:short)"])
    if kode != 0:
        return []
    cabang = [baris.strip() for baris in keluaran.splitlines() if baris.strip().endswith("HEAD") is False]
    return [item for item in cabang if item.startswith(f"{remote}/")]


def komit_terakhir(ref: str = "HEAD") -> dict[str, str]:
    kode, keluaran = jalankan_git(["log", "-1", "--pretty=format:%h%x1f%ci%x1f%an%x1f%s", ref])
    if kode != 0 or not keluaran:
        return {}
    bagian = keluaran.split("\x1f")
    if len(bagian) < 4:
        return {}
    return {"kode": bagian[0], "tanggal": bagian[1], "penulis": bagian[2], "subjek": bagian[3]}


def catatan_perubahan(ref: str = "HEAD", batas: int = 15) -> list[dict[str, str]]:
    """Daftar komit untuk ditampilkan sebagai catatan perubahan."""
    kode, keluaran = jalankan_git(
        ["log", f"-{max(1, min(batas, 50))}", "--pretty=format:%h%x1f%ci%x1f%an%x1f%s", ref]
    )
    if kode != 0 or not keluaran:
        return []
    hasil: list[dict[str, str]] = []
    for baris in keluaran.splitlines():
        bagian = baris.split("\x1f")
        if len(bagian) < 4:
            continue
        hasil.append({"kode": bagian[0], "tanggal": bagian[1], "penulis": bagian[2], "subjek": bagian[3]})
    return hasil


def perubahan_lokal() -> list[str]:
    """Daftar berkas yang diubah di komputer ini dan belum di-commit."""
    kode, keluaran = jalankan_git(["status", "--porcelain"])
    if kode != 0:
        return []
    return [baris.rstrip() for baris in keluaran.splitlines() if baris.strip()]


def berkas_berbeda(ref_lama: str, ref_baru: str) -> list[str]:
    if not ref_lama or not ref_baru or ref_lama == ref_baru:
        return []
    kode, keluaran = jalankan_git(["diff", "--name-only", ref_lama, ref_baru])
    if kode != 0:
        return []
    return [baris.strip() for baris in keluaran.splitlines() if baris.strip()]


# --------------------------------------------------------------------------- #
# Status & pemeriksaan
# --------------------------------------------------------------------------- #
def perintah_manual() -> str:
    """Perintah yang bisa disalin admin bila pembaruan otomatis tak tersedia."""
    cabang = cabang_target()
    return (
        f"cd /d {BASE_DIR}\n"
        f"git pull origin {cabang}\n"
        f".venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
        f".venv\\Scripts\\python.exe run.py"
    )


def status_pembaruan(periksa_jaringan: bool = False, remote: str | None = None,
                     cabang: str | None = None) -> dict[str, Any]:
    """Ringkasan kondisi salinan aplikasi.

    ``periksa_jaringan=True`` menjalankan ``git fetch`` lebih dulu sehingga
    jumlah komit tertinggal benar-benar terbaru (butuh internet).
    """
    info = informasi_git()
    remote = remote or info["remote"]
    cabang = cabang or cabang_target(info)
    status: dict[str, Any] = {
        "info": info,
        "tersedia": info["bisa"],
        "remote": remote,
        "cabang": cabang,
        "cabang_aktif": info["cabang"],
        "url": info["url"],
        "revisi_lokal": _rev("HEAD"),
        "revisi_remote": "",
        "jaringan_diperiksa": False,
        "ketinggalan": None,
        "ada_pembaruan": None,
        "komit_lokal": komit_terakhir("HEAD"),
        "komit_remote": {},
        "berkas_berubah": [],
        "perubahan_lokal": [],
        "ada_perubahan_lokal": False,
        "log": [],
        "pesan": "",
        "waktu_cek": services.get_setting("update_cek_terakhir") or "",
        "ketinggalan_terakhir": _angka(services.get_setting("update_komit_belakang")),
        "butuh_muat_ulang": RESTART_MARKER.exists(),
        "status_terakhir": _baca_status(),
        "catatan": [],
        "belum_diperiksa": False,
    }

    if not info["bisa"]:
        status["pesan"] = info["alasan"]
        return status

    ubah = perubahan_lokal()
    status["perubahan_lokal"] = ubah[:15]
    status["ada_perubahan_lokal"] = bool(ubah)
    status["berkas_lokal_total"] = len(ubah)

    if periksa_jaringan:
        kode, keluaran = ambil_pembaruan(remote, cabang)
        status["jaringan_diperiksa"] = kode == 0
        status["log"].append(keluaran or "git fetch selesai.")
        if kode != 0:
            status["pesan"] = (
                "Gagal menghubungi GitHub. Periksa sambungan internet komputer server, "
                "lalu coba lagi."
            )
            return status

    ref = _ref_remote(remote, cabang)
    status["revisi_remote"] = _rev(ref) or _rev("FETCH_HEAD")
    if not status["revisi_remote"]:
        # Belum pernah diperiksa & ref pelacak belum ada: bukan kesalahan.
        status["belum_diperiksa"] = not periksa_jaringan
        status["catatan"] = catatan_perubahan("HEAD", batas=12)
        status["pesan"] = (
            "Revisi GitHub belum diperiksa. Klik “Periksa pembaruan” untuk membandingkan "
            "dengan versi di GitHub (butuh internet)."
            if status["belum_diperiksa"]
            else f"Cabang '{cabang}' tidak ditemukan di remote '{remote}'. Pilih cabang lain "
                 "pada bagian pengaturan pembaruan."
        )
        return status

    ref_banding = ref if _rev(ref) else "FETCH_HEAD"
    kode, keluaran = jalankan_git(["rev-list", "--count", f"HEAD..{ref_banding}"])
    if kode == 0 and keluaran.strip().isdigit():
        status["ketinggalan"] = int(keluaran.strip())
        status["ada_pembaruan"] = status["ketinggalan"] > 0
    status["komit_remote"] = komit_terakhir(ref_banding)
    status["catatan"] = catatan_perubahan(ref_banding, batas=12)
    status["berkas_berubah"] = berkas_berbeda("HEAD", ref_banding)[:20]

    if status["ada_pembaruan"]:
        status["pesan"] = (
            f"Ada {status['ketinggalan']} komit baru di GitHub "
            f"({status['revisi_lokal']} → {status['revisi_remote']})."
        )
        if status["ada_perubahan_lokal"]:
            status["pesan"] += (
                " Namun ada perubahan berkas lokal yang belum di-commit, jadi penarikan "
                "otomatis belum aman dijalankan."
            )
    elif status["ada_pembaruan"] is False:
        status["pesan"] = "Aplikasi sudah memakai versi terbaru dari GitHub."
    return status


def _angka(nilai: Any) -> int | None:
    try:
        return int(str(nilai))
    except (TypeError, ValueError):
        return None


def _baca_status() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return {}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _catat_status(**nilai: Any) -> dict[str, Any]:
    data = _baca_status()
    data.update(nilai)
    data["diperbarui"] = datetime.now().isoformat(timespec="seconds")
    config.ensure_dirs()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return data


def simpan_hasil_cek(status: dict[str, Any]) -> None:
    """Simpan hasil pemeriksaan ke tabel settings agar bisa ditampilkan nanti."""
    nilai = {
        "update_cek_terakhir": datetime.now().isoformat(timespec="seconds"),
        "update_revisi_lokal": status.get("revisi_lokal") or "",
        "update_revisi_remote": status.get("revisi_remote") or "",
    }
    if status.get("ketinggalan") is not None:
        nilai["update_komit_belakang"] = str(status["ketinggalan"])
        nilai["update_tersedia"] = "1" if status.get("ada_pembaruan") else "0"
    services.update_settings(nilai)


# --------------------------------------------------------------------------- #
# Penarikan pembaruan
# --------------------------------------------------------------------------- #
def _pip_perintah() -> list[str]:
    return [sys.executable, "-m", "pip", "install", "-r", str(BASE_DIR / "requirements.txt"), "--upgrade"]


def pasang_dependensi() -> tuple[bool, str]:
    """Jalankan ``pip install -r requirements.txt`` memakai Python yang aktif."""
    try:
        hasil = subprocess.run(
            _pip_perintah(),
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PIP_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"Pemasangan dependensi melebihi {PIP_TIMEOUT} detik."
    except OSError as exc:  # pragma: no cover
        return False, f"Gagal menjalankan pip: {exc}"
    keluaran = ((hasil.stdout or "") + (hasil.stderr or "")).strip()
    return hasil.returncode == 0, keluaran[-4000:]


def periksa_kode_baru(timeout: int = 120) -> tuple[bool, str]:
    """Pastikan kode hasil pembaruan bisa dijalankan sebelum server dimuat ulang.

    Dua lapis: ``compileall`` untuk seluruh modul Python, lalu uji impor
    ``app.main`` di proses terpisah memakai folder data sementara supaya basis
    data asli tidak tersentuh.
    """
    import tempfile

    if _git_path() is None and not (BASE_DIR / "app").exists():  # pragma: no cover
        return True, "Pemeriksaan kode dilewati."

    try:
        selesai = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(BASE_DIR / "app"), str(BASE_DIR / "run.py")],
            cwd=str(BASE_DIR), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Pemeriksaan sintaks gagal dijalankan: {exc}"
    if selesai.returncode != 0:
        catatan = ((selesai.stdout or "") + (selesai.stderr or "")).strip().splitlines()
        return False, "Sintaks Python bermasalah: " + " | ".join(catatan[-3:])

    sementara = tempfile.mkdtemp(prefix="simsek-uji-kode-")
    lingkungan = os.environ.copy()
    lingkungan["SM_DATA_DIR"] = sementara
    lingkungan["SM_DB_PATH"] = str(Path(sementara) / "uji.sqlite3")
    lingkungan["SM_AUTO_SEED"] = "0"
    try:
        impor = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=str(BASE_DIR), env=lingkungan, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Uji impor kode baru gagal dijalankan: {exc}"
    finally:
        shutil.rmtree(sementara, ignore_errors=True)

    if impor.returncode != 0:
        catatan = ((impor.stdout or "") + (impor.stderr or "")).strip().splitlines()
        return False, "Kode baru gagal dimuat: " + " | ".join(catatan[-3:])
    return True, "Pemeriksaan kode baru lolos (sintaks + impor aplikasi)."


def cadangkan_database() -> Path | None:
    """Salin basis data (backup API SQLite) sebelum kode diperbarui."""
    if not config.DB_PATH.exists():
        return None
    folder = config.DATA_DIR / "backup"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"simsek-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    try:
        sumber = sqlite3.connect(str(config.DB_PATH))
        tujuan = sqlite3.connect(str(target))
        with tujuan:
            sumber.backup(tujuan)
        tujuan.close()
        sumber.close()
    except sqlite3.Error:
        return None
    cadangan = sorted(folder.glob("simsek-*.sqlite3"))
    for lama in cadangan[:-10]:  # simpan 10 cadangan terbaru saja
        try:
            lama.unlink()
        except OSError:
            pass
    return target


def terapkan_pembaruan(cabang: str | None = None, remote: str | None = None,
                       pasang_pip: bool = False, aktor: str | None = None,
                       role: str | None = None) -> dict[str, Any]:
    """Jalankan ``git pull --ff-only`` dan laporkan hasilnya."""
    hasil: dict[str, Any] = {
        "ok": False, "log": [], "sebelum": "", "sesudah": "", "berubah": False,
        "perlu_dependensi": False, "pip_ok": None, "pip_catatan": "", "cadangan": "",
        "pesan": "", "muat_ulang": False,
    }

    info = informasi_git()
    if not info["bisa"]:
        hasil["pesan"] = info["alasan"]
        return hasil

    remote = remote or info["remote"]
    cabang = cabang or cabang_target(info)
    lokal = perubahan_lokal()
    if lokal:
        hasil["log"].append("Perubahan lokal terdeteksi: " + ", ".join(lokal[:8]))
        hasil["pesan"] = (
            "Ada perubahan berkas di komputer ini yang belum disimpan ke git, jadi pembaruan "
            "dibatalkan agar tidak ada pekerjaan yang hilang. Simpan perubahan tersebut "
            "(git commit) atau kembalikan berkasnya (git restore), lalu ulangi."
        )
        return hasil

    sebelum = _rev("HEAD")
    hasil["sebelum"] = sebelum
    hasil["log"].append(f"Versi lokal: {sebelum or 'tidak diketahui'} (cabang {info['cabang'] or '-'})")

    kode, keluaran = ambil_pembaruan(remote, cabang)
    hasil["log"].append(keluaran or f"git fetch {remote} {cabang} selesai.")
    if kode != 0:
        hasil["pesan"] = (
            "Gagal mengambil data dari GitHub (git fetch). Periksa sambungan internet "
            "komputer server lalu coba lagi."
        )
        return hasil

    kode, keluaran = jalankan_git(["pull", "--ff-only", remote, cabang])
    hasil["log"].append(keluaran or f"git pull {remote} {cabang} selesai.")
    if kode != 0:
        hasil["pesan"] = (
            f"Penarikan pembaruan gagal. Cabang lokal '{info['cabang']}' mungkin berbeda "
            f"dari '{cabang}' atau riwayatnya bercabang. Jalankan manual di folder aplikasi:\n"
            f"git pull {remote} {cabang}"
        )
        return hasil

    sesudah = _rev("HEAD")
    hasil["sesudah"] = sesudah
    hasil["berubah"] = sebelum != sesudah
    if not hasil["berubah"]:
        hasil["ok"] = True
        hasil["pesan"] = "Tidak ada perubahan baru — aplikasi sudah memakai versi terbaru."
        return hasil

    berkas = berkas_berbeda(sebelum, sesudah)
    hasil["berkas"] = berkas[:40]
    hasil["log"].append(f"{len(berkas)} berkas diperbarui: " + ", ".join(berkas[:12]))

    simpan = cadangkan_database()
    hasil["cadangan"] = str(simpan) if simpan else ""
    if simpan:
        hasil["log"].append(f"Cadangan basis data dibuat: {simpan}")

    # Pintu pengaman: kode baru harus bisa dikompilasi & diimpor. Bila tidak,
    # salinan dikembalikan ke versi sebelumnya agar server tetap bisa dijalankan.
    if any(b.startswith(("app/", "run.py", "scripts/")) for b in berkas):
        sehat, catatan = periksa_kode_baru()
        hasil["log"].append(catatan)
        if not sehat:
            kode_balik, keluaran = jalankan_git(["reset", "--hard", sebelum])
            hasil["log"].append(
                (keluaran or "") + f" -> dikembalikan ke {sebelum}"
                if kode_balik == 0 else f"Gagal mengembalikan kode: {keluaran}"
            )
            hasil["ok"] = False
            hasil["dikembalikan"] = kode_balik == 0
            hasil["sesudah"] = _rev("HEAD")
            hasil["berubah"] = False
            hasil["pesan"] = (
                f"Pembaruan ditolak karena kode barunya bermasalah ({catatan}). "
                + (f"Aplikasi sudah dikembalikan ke versi {sebelum} dan tetap berjalan. "
                   if kode_balik == 0 else
                   f"Kembalikan manual dengan 'git reset --hard {sebelum}'. ")
                + "Laporkan ini ke pengembang agar diperbaiki di GitHub."
            )
            _catat_status(aksi="tarik_pembaruan", hasil="dikembalikan", sebelum=sebelum,
                          sesudah=hasil["sesudah"], aktor=aktor or "", alasan=catatan)
            services.log_audit(aktor, role or "admin", "pembaruan_dikembalikan", "aplikasi",
                               sebelum, catatan)
            return hasil

    hasil["perlu_dependensi"] = any(b == "requirements.txt" for b in berkas)
    if hasil["perlu_dependensi"]:
        if pasang_pip:
            hasil["log"].append("requirements.txt berubah — memasang dependensi baru…")
            pip_ok, pip_catatan = pasang_dependensi()
            hasil["pip_ok"] = pip_ok
            hasil["pip_catatan"] = pip_catatan
            hasil["log"].append(
                "Dependensi berhasil dipasang." if pip_ok
                else "Pemasangan dependensi gagal — jalankan manual: pip install -r requirements.txt"
            )
        else:
            hasil["log"].append(
                "requirements.txt berubah. Jalankan 'pip install -r requirements.txt' bila ada "
                "fitur yang error."
            )

    hasil["ok"] = True
    hasil["pesan"] = (
        f"Pembaruan berhasil ditarik: {sebelum} → {sesudah} "
        f"({len(berkas)} berkas). Muat ulang server agar kode baru dipakai."
    )
    _catat_status(
        aksi="tarik_pembaruan", hasil="sukses", sebelum=sebelum, sesudah=sesudah,
        aktor=aktor or "", berkas=berkas[:40],
    )
    services.log_audit(aktor, role or "admin", "perbarui_aplikasi", "aplikasi", sesudah,
                       f"{sebelum} -> {sesudah} ({len(berkas)} berkas)")
    return hasil


# --------------------------------------------------------------------------- #
# Muat ulang server (kode baru langsung dipakai)
# --------------------------------------------------------------------------- #
def perintah_restart() -> list[str]:
    """Perintah yang dipakai untuk memulai ulang server setelah pembaruan."""
    khusus = os.getenv("SM_RESTART_CMD")
    if khusus:
        return shlex.split(khusus)
    argv = list(sys.argv) or ["run.py"]
    if not os.path.isabs(argv[0]):
        argv[0] = str((BASE_DIR / argv[0]).resolve())
    return [sys.executable, *argv]


def minta_muat_ulang(aktor: str | None = None, alasan: str = "pembaruan") -> None:
    """Beri tanda agar proses server menggantikan dirinya dengan kode terbaru."""
    config.ensure_dirs()
    RESTART_MARKER.write_text(
        json.dumps(
            {"diminta": datetime.now().isoformat(timespec="seconds"), "aktor": aktor or "",
             "alasan": alasan, "revisi": _rev("HEAD"), "perintah": " ".join(perintah_restart())},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    services.log_audit(aktor, "admin", "muat_ulang_server", "aplikasi", None, alasan)


def batalkan_muat_ulang() -> None:
    try:
        RESTART_MARKER.unlink()
    except OSError:
        pass


def perlu_muat_ulang() -> bool:
    """True bila tanda muat ulang sudah cukup umur untuk dijalankan."""
    if not RESTART_MARKER.exists():
        return False
    try:
        umur = time.time() - RESTART_MARKER.stat().st_mtime
    except OSError:
        return False
    return umur >= JEDA_MUAT_ULANG


def _mulai_ulang_windows() -> None:
    """Buka jendela konsol baru yang menjalankan server (khusus Windows).

    ``os.execv`` di Windows membuat proses baru ber-PID berbeda sehingga jendela
    ``run.bat`` yang ber-``pause`` bisa ikut tertutup dan mematikan server. Karena
    itu server dijalankan di jendela konsol baru yang terpisah.
    """
    perintah = perintah_restart()
    baris = subprocess.list2cmdline(perintah)
    bendera = 0
    for nama in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        bendera |= int(getattr(subprocess, nama, 0))
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "SIMSEK", "/D", str(BASE_DIR), "cmd", "/k", baris],
            cwd=str(BASE_DIR),
            creationflags=bendera,
            close_fds=True,
            stdin=subprocess.DEVNULL,
        )
        print("Jendela server baru dibuka. Jendela ini dapat ditutup.")
    except OSError as exc:  # pragma: no cover - Windows tanpa cmd?
        print(f"Gagal membuka jendela server baru: {exc}")
        print("Tutup jendela ini, lalu jalankan run.bat kembali.")


def muat_ulang_sekarang() -> None:
    """Jalankan ulang server memakai kode terbaru (proses diganti)."""
    _catat_status(
        aksi="muat_ulang", hasil="dijalankan", revisi=_rev("HEAD"),
        perintah=" ".join(perintah_restart()),
    )
    try:
        db.close_connection()
    except Exception:  # noqa: BLE001 - jangan gagalkan muat ulang
        pass
    sys.stdout.flush()
    sys.stderr.flush()

    if os.name == "nt":
        _mulai_ulang_windows()
        os._exit(0)

    os.execv(perintah_restart()[0], perintah_restart())


def bersihkan_marker_lama() -> None:
    """Dipanggil saat startup: buang tanda muat ulang dari proses sebelumnya."""
    if not RESTART_MARKER.exists():
        return
    try:
        umur = RESTART_MARKER.stat().st_mtime
    except OSError:
        return
    if umur < PROSES_MULAI - 1:
        data = _baca_status()
        data.setdefault("aksi", "muat_ulang")
        _catat_status(aksi="muat_ulang", hasil="selesai", revisi=_rev("HEAD"))
        batalkan_muat_ulang()


# --------------------------------------------------------------------------- #
# Pemantau latar belakang
# --------------------------------------------------------------------------- #
def interval_detik() -> int:
    jam = _angka(services.get_setting("update_interval_jam")) or _angka(SETTING_DEFAULT["update_interval_jam"]) or 6
    return max(15 * 60, min(jam * 3600, 24 * 3600))


def otomatis_periksa() -> dict[str, Any]:
    """Satu siklus pemeriksaan latar belakang (dipanggil dari event loop server)."""
    if not AKTIF:
        return {"dilewati": "nonaktif"}
    if (services.get_setting("update_auto_cek") or SETTING_DEFAULT["update_auto_cek"]) == "0":
        return {"dilewati": "pemeriksaan otomatis dimatikan"}

    info = informasi_git()
    if not info["bisa"]:
        return {"dilewati": "bukan salinan git"}

    status = status_pembaruan(periksa_jaringan=True)
    simpan_hasil_cek(status)
    if not status.get("jaringan_diperiksa"):
        return {"gagal": status.get("pesan")}

    auto_tarik = (services.get_setting("update_auto_tarik") or SETTING_DEFAULT["update_auto_tarik"]) == "1"
    if status.get("ada_pembaruan") and auto_tarik and not status.get("ada_perubahan_lokal"):
        hasil = terapkan_pembaruan(aktor="pemantau-otomatis", role="admin")
        if hasil.get("ok") and hasil.get("berubah"):
            if (services.get_setting("update_restart_otomatis") or SETTING_DEFAULT["update_restart_otomatis"]) == "1":
                minta_muat_ulang(aktor="pemantau-otomatis", alasan="pembaruan otomatis")
            return {"ditarik": True, "pesan": hasil.get("pesan", "")}
        return {"ditarik": False, "pesan": hasil.get("pesan", "")}
    return {"ketinggalan": status.get("ketinggalan"), "ada_pembaruan": status.get("ada_pembaruan")}
