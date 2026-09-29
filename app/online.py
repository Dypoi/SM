"""Penanda "sedang online" & daftar periksa keamanan aplikasi.

Aplikasi SM biasanya dipakai di jaringan sekolah. Begitu dibuka lewat
terowongan gratis (Tailscale Funnel / Cloudflare quick tunnel), aplikasi perlu
tahu bahwa ia sedang terjangkau dari internet supaya dapat menyalakan pengaman
tambahan dan mengingatkan petugas.

Modul ini menyimpan:

* berkas penanda ``data/online.json`` (ditulis oleh peluncur ``SM-online.py``,
  atau otomatis saat ada permintaan dari alamat IP publik),
* daftar periksa keamanan sederhana untuk halaman **Pengaturan → Sistem →
  Aman Online**,
* **tombol «Online»** (halaman ``/online``): menyalakan/mematikan Tailscale
  Funnel sekali klik — perintahnya dijalankan di belakang layar
  (``CREATE_NO_WINDOW``), jadi **tidak ada jendela Command Prompt** yang muncul.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import config, db, security

#: Simpanan sementara supaya pemeriksaan mahal (PBKDF2) tidak jalan tiap halaman.
_kh: dict[str, tuple[float, Any]] = {}


def _kh_simpan(kunci: str, detik: float, hitung: Callable[[], Any]) -> Any:
    sekarang = time.monotonic()
    ada = _kh.get(kunci)
    if ada is not None and sekarang - ada[0] < detik:
        return ada[1]
    nilai = hitung()
    _kh[kunci] = (sekarang, nilai)
    return nilai


def ip_privat(host: str | None) -> bool:
    """True bila alamat berasal dari jaringan lokal (bukan internet)."""
    if not host:
        return True
    if host.lower() in {"localhost", "testclient"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


def dari_luar(host: str | None) -> bool:
    """True bila permintaan datang dari internet (atau mode publik dipaksa)."""
    return config.PUBLIK or not ip_privat(host)


# --------------------------------------------------------------------------- #
# Berkas penanda
# --------------------------------------------------------------------------- #
def baca_status() -> dict[str, Any]:
    """Isi penanda online; ``{"aktif": False}`` bila aplikasi hanya lokal."""
    def hitung() -> dict[str, Any]:
        try:
            data = json.loads(config.ONLINE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("aktif", True)
                return data
        except (OSError, ValueError):
            pass
        return {"aktif": config.PUBLIK, "alat": "dipaksa lewat SM_PUBLIK=1" if config.PUBLIK else ""}

    return _kh_simpan("status", 5.0, hitung)


def simpan_status(alamat: str, alat: str, port: int | None = None) -> dict[str, Any]:
    """Tandai aplikasi sedang online (dipakai peluncur & deteksi otomatis)."""
    config.ensure_dirs()
    data = {
        "aktif": True,
        "alamat": (alamat or "").strip(),
        "alat": alat,
        "port": port,
        "diperbarui": dt.datetime.now().strftime("%d %b %H:%M"),
    }
    config.ONLINE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if data["alamat"]:
        config.ALAMAT_FILE.write_text(data["alamat"] + "\n", encoding="utf-8")
    _kh.pop("status", None)
    _kh.pop("peringatan", None)
    return data


def hapus_status() -> None:
    """Lupakan penanda online (dipakai tombol di halaman Pengaturan)."""
    for berkas in (config.ONLINE_FILE, config.ALAMAT_FILE):
        try:
            berkas.unlink()
        except OSError:
            pass
    _kh.clear()


#: Waktu akses luar terakhir yang belum sempat ditulis ke berkas penanda.
_akses_luar_terakhir: float = 0.0


def tandai_akses_luar(ip: str | None = None, alat: str = "terdeteksi otomatis") -> None:
    """Catat bahwa ada permintaan dari internet (ditulis paling sering 1 jam sekali)."""
    global _akses_luar_terakhir
    sekarang = time.monotonic()
    if sekarang - _akses_luar_terakhir < 3600:
        return
    _akses_luar_terakhir = sekarang
    status = baca_status()
    alamat = status.get("alamat") or ""
    simpan_status(alamat, status.get("alat") or alat, status.get("port"))


# --------------------------------------------------------------------------- #
# Daftar periksa keamanan
# --------------------------------------------------------------------------- #
def sandi_admin_bawaan() -> bool:
    """True bila masih ada admin aktif memakai kata sandi bawaan."""
    def hitung() -> bool:
        baris = db.query_all(
            "SELECT password_hash FROM users WHERE role = 'admin' AND aktif = 1 AND password_hash <> ''"
        )
        for baris_satu in baris:
            if security.verify_password(config.DEFAULT_ADMIN_PASSWORD, baris_satu["password_hash"]):
                return True
        return False

    return bool(_kh_simpan("sandi_bawaan", 60.0, hitung))


def pemeriksaan_keamanan() -> list[dict[str, Any]]:
    """Daftar periksa untuk petugas (True = aman, False = perlu dibenahi)."""
    from . import auth  # impor lokal: hindari lingkaran impor

    status = baca_status()
    alamat = str(status.get("alamat") or "")
    https = alamat.lower().startswith("https://")
    tertahan = auth.ringkasan_penangguhan()

    catatan: list[dict[str, Any]] = []
    catatan.append({
        "label": "Kata sandi admin bukan bawaan",
        "ok": not sandi_admin_bawaan(),
        "pesan": "Masih memakai kata sandi bawaan (admin123) — ganti di tab Pengguna "
                 "sebelum aplikasi dibuka luas.",
    })
    pakai_tanggal_lahir = auth.student_requires_birthdate()
    catatan.append({
        "label": "Login siswa memakai tanggal lahir",
        "ok": pakai_tanggal_lahir,
        "pesan": "Belum menyala: siapa pun yang tahu NISN dapat melihat data pribadi siswa. "
                 "Cara aman: nyalakan pengaman tanggal lahir."
                 if not pakai_tanggal_lahir else
                 "Menyala: siswa memasukkan NISN + tanggal lahir, jauh lebih aman.",
        "aksi": "" if pakai_tanggal_lahir else "nyalakan-tanggal-lahir",
        "tombol": "Nyalakan pengaman",
    })
    catatan.append({
        "label": "Tautan yang dipakai sudah HTTPS",
        "ok": None if not status.get("aktif") else https,
        "pesan": "Terowongan Tailscale Funnel/Cloudflare otomatis memakai HTTPS."
                 if https else
                 "Aplikasi belum dibuka lewat terowongan. Jalankan SM-online.bat bila ingin diakses dari internet.",
    })
    catatan.append({
        "label": "Pembatasan percobaan login",
        "ok": True,
        "pesan": (f"{len(tertahan)} kunci sedang ditangguhkan sementara."
                  if tertahan else
                  f"Aktif: maksimal {config.LOGIN_MAKS_GAGAL_AKUN} percobaan gagal per akun/NISN "
                  f"dan {config.LOGIN_MAKS_GAGAL_IP_PUBLIK} per alamat IP, jeda 10 menit."),
    })
    if config.VERCEL:
        catatan.append({
            "label": "Kunci sesi tetap (SM_SECRET_KEY)",
            "ok": config.SECRET_KEY_DARI_ENV,
            "pesan": ("Sudah diisi lewat environment Vercel — login tidak terputus antar-instans."
                      if config.SECRET_KEY_DARI_ENV else
                      "Belum diisi: setiap instans Vercel membuat kunci sendiri sehingga login "
                      "bisa terputus-putus. Isi SM_SECRET_KEY di dasbor Vercel lalu deploy ulang."),
        })
        catatan.append({
            "label": "Penyimpanan permanen (Vercel)",
            "ok": False,
            "pesan": ("Mode Vercel menyimpan data di /tmp yang tidak permanen: data hilang saat "
                      "fungsi tidur atau dideploy ulang. Untuk data sekolah sesungguhnya, "
                      "jalankan SM di PC sekolah."),
        })
    catatan.append({
        "label": "Salinan cadangan data",
        "ok": None,
        "pesan": "Salin folder data/ (atau jalankan SM-cadangkan.bat) secara berkala; "
                 "berkas berisi seluruh data siswa.",
    })
    return catatan


def pemeriksaan_singkat() -> list[str]:
    """Peringatan penting saja (dipakai peluncur & spanduk di aplikasi)."""
    pesan: list[str] = []
    if sandi_admin_bawaan():
        pesan.append("Kata sandi admin masih bawaan (admin123) — ganti di Pengaturan → Pengguna.")
    from . import auth  # impor lokal

    if not auth.student_requires_birthdate():
        pesan.append("Login siswa masih memakai NISN saja — data pribadi siswa bisa dibaca "
                     "siapa pun yang tahu NISN. Nyalakan pengaman tanggal lahir di "
                     "Pengaturan → Sistem → Aman Online.")
    return pesan


def peringatan_aman(user: Any = None) -> list[str]:
    """Peringatan untuk spanduk aplikasi (hanya petugas & hanya bila online)."""
    def hitung() -> list[str]:
        if user is None or not getattr(user, "is_staff", False):
            return []
        if not baca_status().get("aktif"):
            return []
        return pemeriksaan_singkat()

    if user is None or not getattr(user, "is_staff", False):
        return []
    return list(_kh_simpan("peringatan", 30.0, hitung))


# --------------------------------------------------------------------------- #
# Tailscale Funnel — tombol «Online» di aplikasi (tanpa jendela Command Prompt)
# --------------------------------------------------------------------------- #
#: Kandidat lokasi ``tailscale`` bila tidak ada di PATH (pemasangan Windows/Mac).
TAILSCALE_KANDIDAT = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tailscale" / "tailscale.exe",
    Path(os.environ.get("LOCALAPPDATA", ".")) / "Tailscale" / "tailscale.exe",
    Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
    Path("/usr/local/bin/tailscale"),
    Path("/usr/bin/tailscale"),
    Path("/opt/homebrew/bin/tailscale"),
)

#: Alamat publik Tailscale selalu berakhiran ``.ts.net`` (MagicDNS).
POLA_ALAMAT_TAILSCALE = re.compile(r"https://[A-Za-z0-9][A-Za-z0-9.\-]*\.ts\.net(?::\d+)?")

#: Tautan persetujuan/pengaturan yang dicetak Tailscale saat Funnel belum diizinkan.
POLA_TAUTAN_IZIN = re.compile(r"https://login\.tailscale\.com/[^\s\"'<>]+")

#: Port publik yang diizinkan Tailscale Funnel (batas Tailscale, bukan aplikasi ini).
PORT_FUNNEL = (443, 8443, 10000)

#: Batas tunggu satu ronde ``tailscale funnel`` (detik) & berapa ronde diperpanjang
#: selama perintahnya terlihat masih menunggu persetujuan (total ±9 menit).
TUNGGU_FUNNEL = 180
RONDE_TUNGGU = 3

#: Keadaan pekerjaan tombol Online yang sedang berjalan (dibaca halaman web).
_pekerjaan: dict[str, Any] = {
    "jalan": False, "tahap": "diam", "pesan": "", "alamat": "", "tautan_izin": "",
    "mulai": 0.0, "selesai": 0.0, "port": 0, "kode": None, "log": [],
}

_PEKERJAAN_KUNCI = ("jalan", "tahap", "pesan", "alamat", "tautan_izin", "mulai", "selesai",
                    "port", "kode")


def tanpa_jendela() -> int:
    """Bendera Windows supaya proses anak **tidak** memunculkan jendela cmd sama sekali."""
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def tailscale_jalur() -> str:
    """Cari perintah ``tailscale`` — dari variabel lingkungan, PATH, lalu lokasi pemasangan."""
    khusus = (os.getenv("SM_TAILSCALE") or "").strip()
    if khusus:
        return khusus if (Path(khusus).exists() or shutil.which(khusus)) else ""
    ketemu = shutil.which("tailscale")
    if ketemu:
        return ketemu
    for kandidat in TAILSCALE_KANDIDAT:
        try:
            if kandidat.exists():
                return str(kandidat)
        except OSError:
            continue
    return ""


def _perintah_tailscale(jalur: str, *argumen: str, waktu: int = 60) -> tuple[int, str]:
    """Jalankan perintah Tailscale di belakang layar; kembalikan ``(kode, keluaran)``.

    ``kode == 127`` berarti perintahnya tidak bisa dijalankan sama sekali. Keluaran
    Tailscale digabung (stdout+stderr) supaya pesan galatnya bisa diterjemahkan.
    """
    perintah = [jalur, *argumen]
    try:
        hasil = subprocess.run(
            perintah, capture_output=True, text=True, timeout=waktu,
            creationflags=tanpa_jendela(), stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as galat:
        return 127, f"tidak bisa menjalankan tailscale: {galat}"
    keluaran = ((hasil.stdout or "") + ("\n" + hasil.stderr if hasil.stderr else "")).strip()
    return int(hasil.returncode or 0), keluaran


def baca_alamat_tailscale(keluaran: str) -> tuple[bool, str, int]:
    """Baca ``(funnel_aktif, alamat, port_lokal)`` dari keluaran ``tailscale funnel status``."""
    teks = keluaran or ""
    cocok = POLA_ALAMAT_TAILSCALE.search(teks)
    alamat = cocok.group(0).rstrip("/") if cocok else ""
    rendah = teks.lower()
    aktif = bool(alamat) and ("funnel on" in rendah or "proxy http" in rendah)
    port = 0
    target = re.search(r"proxy\s+https?://[^:\s]+:(\d{2,5})", rendah)
    if target:
        port = int(target.group(1))
    return aktif, alamat, port


def _nama_perangkat(jalur: str) -> str:
    """Nama perangkat Tailscale (MagicDNS) untuk pesan bila alamat publik belum dibaca."""
    kode, keluaran = _perintah_tailscale(jalur, "status", "--json", waktu=25)
    if kode != 0:
        return ""
    try:
        data = json.loads(keluaran or "{}")
    except ValueError:
        return ""
    return str((data.get("Self") or {}).get("DNSName") or "").strip().strip(".")


def status_terowongan(periksa: bool = True) -> dict[str, Any]:
    """Keadaan tombol Online: Tailscale ada/tidak, funnel menyala/tidak, alamat publiknya."""
    jalur = tailscale_jalur()
    hasil: dict[str, Any] = {
        "ada": bool(jalur), "jalur": jalur, "online": False, "alamat": "", "nama": "",
        "funnel": False, "port": 0, "pesan": "", "tautan_izin": "",
    }
    tanda = baca_status()
    if not jalur:
        hasil["pesan"] = ("Tailscale belum terpasang di komputer ini. Setelah dipasang "
                          "(tailscale.com/download) dan masuk dengan akun sekolah, tombol ini "
                          "langsung bisa dipakai.")
        if tanda.get("aktif"):
            hasil.update(online=True, alamat=str(tanda.get("alamat") or ""),
                         pesan="Alamat publik tercatat, tetapi perintah tailscale tidak ditemukan.")
        return hasil
    hasil["nama"] = _nama_perangkat(jalur) if periksa else ""
    if periksa:
        kode, keluaran = _perintah_tailscale(jalur, "funnel", "status", waktu=25)
        aktif, alamat, port = baca_alamat_tailscale(keluaran)
        hasil.update(funnel=aktif, alamat=alamat, port=port)
        if kode == 127:
            hasil["pesan"] = keluaran
        elif kode != 0 and not alamat:
            rendah = keluaran.lower()
            if "no serve config" in rendah or "not found" in rendah:
                hasil["pesan"] = "Funnel belum menyala — tekan tombol «Nyalakan online»."
            else:
                hasil["pesan"] = keluaran.splitlines()[-1][:200] if keluaran.strip() else \
                    f"Perintah funnel status berhenti dengan kode {kode}."
    if not hasil["alamat"] and tanda.get("aktif"):
        hasil["alamat"] = str(tanda.get("alamat") or "")
        hasil["online"] = bool(hasil["alamat"])
    else:
        hasil["online"] = bool(hasil["alamat"])
    return hasil


def status_pekerjaan() -> dict[str, Any]:
    """Keadaan pekerjaan tombol Online (untuk dipantau halaman web)."""
    data = {kunci: _pekerjaan[kunci] for kunci in _PEKERJAAN_KUNCI}
    data["log"] = list(_pekerjaan["log"])[-40:]
    data["detik"] = round(max(0.0, (time.monotonic() - float(_pekerjaan["mulai"] or 0))
                              if _pekerjaan["jalan"] else 0.0), 1)
    return data


def _catat_pekerjaan(baris: str) -> None:
    teks = (baris or "").rstrip()
    if teks:
        _pekerjaan["log"].append(teks[:300])
        del _pekerjaan["log"][:-400]


def mulai_nyalakan(port: int, https_port: int = 443) -> dict[str, Any]:
    """Nyalakan Funnel **di latar belakang** (tombol tidak menggantung); kembalikan keadaannya.

    Pekerjaannya berjalan di thread sendiri supaya halaman web bisa memantau kemajuannya
    (termasuk saat Tailscale menunggu persetujuan Funnel sekali saja untuk tailnet ini).
    """
    if _pekerjaan["jalan"]:
        return status_pekerjaan()
    _pekerjaan.update({"jalan": True, "tahap": "menyiapkan", "pesan": "", "alamat": "",
                       "tautan_izin": "", "kode": None, "port": int(port),
                       "mulai": time.monotonic(), "selesai": 0.0, "log": []})
    threading.Thread(target=_kerja_nyalakan, args=(int(port), int(https_port)),
                     daemon=True).start()
    return status_pekerjaan()


def _kerja_nyalakan(port: int, https_port: int) -> None:
    """Isi pekerjaan latar: jalankan funnel, tunggu (kalau perlu) persetujuan, catat alamat."""
    jalur = tailscale_jalur()
    if not jalur:
        _pekerjaan.update({"jalan": False, "tahap": "gagal", "kode": 127,
                           "pesan": "Tailscale belum terpasang di komputer ini.",
                           "selesai": time.monotonic()})
        return
    if https_port not in PORT_FUNNEL:
        _pekerjaan.update({"jalan": False, "tahap": "gagal", "kode": 1,
                           "pesan": f"Port publik {https_port} tidak diizinkan Tailscale "
                                    f"Funnel (pilihan: {', '.join(map(str, PORT_FUNNEL))}).",
                           "selesai": time.monotonic()})
        return
    _pekerjaan["tahap"] = "menyalakan"
    perintah = [jalur, "funnel", "--bg", f"--https={https_port}", str(port)]
    _catat_pekerjaan("Menjalankan: " + " ".join(perintah[1:]))
    try:
        proses = subprocess.Popen(
            perintah, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            creationflags=tanpa_jendela(),
        )
    except OSError as galat:
        _pekerjaan.update({"jalan": False, "tahap": "gagal", "kode": 127,
                           "pesan": f"Tidak bisa menjalankan Tailscale: {galat}",
                           "selesai": time.monotonic()})
        return

    def baca() -> None:
        if proses.stdout is None:
            return
        for baris in proses.stdout:
            _catat_pekerjaan(baris)
            tautan = POLA_TAUTAN_IZIN.search(baris or "")
            if tautan and not _pekerjaan["tautan_izin"]:
                _pekerjaan["tautan_izin"] = tautan.group(0).rstrip(".,)")
                _pekerjaan["tahap"] = "menunggu-izin"
                _pekerjaan["pesan"] = ("Tailscale menunggu persetujuan Funnel — buka tautan "
                                       "persetujuan sekali saja, lalu prosesnya lanjut sendiri.")

    threading.Thread(target=baca, daemon=True).start()
    kode: int | None = None
    for putaran in range(RONDE_TUNGGU):
        try:
            kode = proses.wait(timeout=TUNGGU_FUNNEL)
            break
        except subprocess.TimeoutExpired:
            teks = "\n".join(_pekerjaan["log"]).lower()
            menunggu = bool(_pekerjaan["tautan_izin"]) or not any(
                tanda in teks for tanda in ("error", "failed", "denied", "not available",
                                            "not enabled", "invalid", "unknown flag"))
            if putaran + 1 < RONDE_TUNGGU and menunggu:
                _pekerjaan["tahap"] = "menunggu-izin"
                _pekerjaan["pesan"] = ("Masih menunggu persetujuan Funnel (bukan gagal) — "
                                       "buka tautan persetujuan, prosesnya lanjut sendiri.")
                continue
            proses.kill()
            kode = None
            break

    _pekerjaan["kode"] = kode
    if kode == 0:
        alamat = ""
        for _ in range(6):
            _, keluaran = _perintah_tailscale(jalur, "funnel", "status", waktu=25)
            aktif, alamat, port_funnel = baca_alamat_tailscale(keluaran)
            if alamat and (port_funnel in (0, port)):
                break
            time.sleep(1.5)
        nama = _nama_perangkat(jalur)
        if not alamat and nama:
            alamat = f"https://{nama}"
        if alamat:
            simpan_status(alamat, f"tailscale funnel → port lokal {port}", port)
            _pekerjaan.update({"tahap": "online", "alamat": alamat, "pesan":
                               "Aplikasi sudah online. Buka alamatnya dari HP atau internet."})
        else:
            _pekerjaan.update({"tahap": "selesai", "pesan":
                               "Funnel menyala, tetapi alamat publiknya belum terbaca. Coba "
                               "«Periksa lagi» sebentar lagi."})
    elif kode is None:
        _pekerjaan.update({"tahap": "menunggu-izin", "pesan":
                           "Belum selesai: Tailscale masih menunggu persetujuan Funnel "
                           "(sekali saja untuk sekolah ini). Buka tautan persetujuan, lalu "
                           "prosesnya lanjut sendiri."})
    else:
        # Hanya keluaran perintahnya yang diterjemahkan — baris «Menjalankan: …»
        # memuat kata «https» pada --https=443 dan dulu menyesatkan diagnosanya.
        keluaran = "\n".join(baris for baris in _pekerjaan["log"]
                             if not baris.startswith("Menjalankan:"))
        _pekerjaan.update({"tahap": "gagal", "pesan": pesan_perbaikan(keluaran)})
    _pekerjaan["jalan"] = False
    _pekerjaan["selesai"] = time.monotonic()


def pesan_perbaikan(keluaran: str) -> str:
    """Terjemahkan galat Tailscale menjadi satu pesan singkat berisi langkah perbaikan."""
    teks = (keluaran or "").lower()
    baris_akhir = ""
    for baris in reversed((keluaran or "").splitlines()):
        if baris.strip():
            baris_akhir = baris.strip()[:200]
            break
    # Urutan penting: keluhan HTTPS/MagicDNS menyebut «not enabled» juga, jadi
    # diperiksa lebih dulu sebelum pesan umum «Funnel belum diizinkan».
    if "magicdns" in teks:
        return ("MagicDNS belum menyala: buka https://login.tailscale.com/admin/dns → "
                "Enable MagicDNS, lalu tekan tombol ini lagi. " + baris_akhir).strip()
    # «Funnel … not enabled» diperiksa sebelum keluhan HTTPS: pesan Tailscale yang
    # menggabungkan keduanya harus diarahkan ke pengaturan Funnel dulu.
    if "not available" in teks or "attribute" in teks or (
            "funnel" in teks and ("not enabled" in teks or "permission" in teks
                                  or "denied" in teks or "unauthorized" in teks)):
        return ("Funnel belum diizinkan untuk perangkat ini. Buka "
                "https://login.tailscale.com/admin/acls → bagian Funnel → «Add Funnel to "
                "policy» → Save, lalu tekan tombol ini lagi. " + baris_akhir).strip()
    if ("https is not enabled" in teks or "enable https" in teks or "certificate" in teks
            or ("https" in teks and "not enabled" in teks)):
        return ("HTTPS Tailscale belum menyala. Buka https://login.tailscale.com/admin/dns → "
                "nyalakan MagicDNS & Enable HTTPS, lalu tekan tombol ini lagi. "
                + baris_akhir).strip()
    if "logged out" in teks or "not logged in" in teks or "no state" in teks:
        return ("Tailscale belum masuk (login) di komputer ini. Buka aplikasi Tailscale, "
                "masuk dengan akun sekolah, lalu tekan tombol ini lagi. " + baris_akhir).strip()
    if "port" in teks and "in use" in teks:
        return ("Port publik itu sedang dipakai proses lain di komputer ini. " + baris_akhir).strip()
    return (baris_akhir or "Perintah Tailscale gagal dijalankan.")


def matikan_terowongan(https_port: int = 443) -> dict[str, Any]:
    """Matikan Funnel publik (aplikasi di jaringan sekolah tetap berjalan seperti biasa)."""
    jalur = tailscale_jalur()
    if not jalur:
        return {"berhasil": False, "pesan": "Tailscale tidak ditemukan di komputer ini."}
    pesan = ""
    for argumen in (("funnel", f"--https={https_port}", "off"), ("funnel", "off"),
                    ("funnel", "--bg", "off")):
        kode, keluaran = _perintah_tailscale(jalur, *argumen, waktu=40)
        if kode == 0:
            hapus_status()
            return {"berhasil": True,
                    "pesan": "Akses publik dimatikan — aplikasi tetap jalan di jaringan sekolah."}
        pesan = keluaran.splitlines()[-1][:200] if keluaran.strip() else f"kode {kode}"
    return {"berhasil": False, "pesan": f"Funnel tidak bisa dimatikan: {pesan}"}
