"""Penanda "sedang online" & daftar periksa keamanan aplikasi.

Aplikasi SM biasanya dipakai di jaringan sekolah. Begitu dibuka lewat
terowongan gratis (Tailscale Funnel / Cloudflare quick tunnel), aplikasi perlu
tahu bahwa ia sedang terjangkau dari internet supaya dapat menyalakan pengaman
tambahan dan mengingatkan petugas.

Modul ini menyimpan:

* berkas penanda ``data/online.json`` (ditulis oleh peluncur ``SM-online.py``,
  atau otomatis saat ada permintaan dari alamat IP publik),
* daftar periksa keamanan sederhana untuk halaman **Pengaturan → Sistem →
  Aman Online**.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import time
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
