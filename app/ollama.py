#!/usr/bin/env python3
"""Integrasi **Ollama**: «otak» percakapan yang mengoperasikan bodap lewat alat.

Latar belakang (permintaan sekolah, ronde 73–74): pengguna ingin mengobrol dengan
model Ollama (mis. lewat jembatan WhatsApp) dan menyuruhnya mengoperasikan
**semua fitur bodap** — cek status insentif/SPJ, melihat data siswa & GTK,
menyetujui pengajuan, mengelola periode insentif (roster, libur), menyusun SPJ
insentif & SPJ TANGCER, atau menjalankan Bot Dapodik dan melaporkan hasilnya.
Ollama sendiri tidak punya akses DOM atau basis data; ia hanya boleh
**memanggil alat yang sudah didaftarkan** di sini, dan setiap alat dipetakan ke
fungsi bodap yang sudah teruji.

Aturan keamanan (tetap sesuai prinsip sekolah):
- Ollama harus **diaktifkan** dulu di halaman «Ollama».
- Alat aksi (mengubah/menghapus data, menjalankan bot) hanya berjalan bila
  pengaturan «Eksekusi otomatis» aktif; bila tidak, alat mengembalikan saran
  saja sehingga Ollama melaporkan ke pengguna tanpa mengeksekusi apa pun.
  Bila menghapus data, pastikan ID diambil dari hasil alat «lihat_...» dulu.
- Model hanya dapat memanggil nama alat yang terdaftar — tidak ada akses bebas.
- Hasil alat wajib dikembalikan apa adanya; Ollama hanya menyampaikan isinya.

Ollama dihubungkan lewat HTTP lokal (``http://localhost:11434``). Permintaan
JSON dibangun memakai ``urllib`` bawaan Python — tidak ada dependensi baru.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import (bot_dapodik, config, db, gtk, insentif, insentif_impor,
               insentif_pdf, services, spj, tangcer)

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Pengaturan
# --------------------------------------------------------------------------- #
KUNCI_AKTIF = "ollama_aktif"
KUNCI_URL = "ollama_url"
KUNCI_MODEL = "ollama_model"
KUNCI_KUNCI = "ollama_kunci"
KUNCI_EKSEKUSI = "ollama_eksekusi"
KUNCI_DETIK = "ollama_detik"
KUNCI_UJI = "ollama_uji_terakhir"

OLLAMA_KEYS: tuple[str, ...] = (
    KUNCI_AKTIF, KUNCI_URL, KUNCI_MODEL, KUNCI_KUNCI, KUNCI_EKSEKUSI, KUNCI_DETIK,
)

OLLAMA_BAWAAN: dict[str, str] = {
    KUNCI_AKTIF: "0",
    KUNCI_URL: "http://localhost:11434",
    KUNCI_MODEL: "qwen2.5:14b-instruct",
    KUNCI_KUNCI: "",
    # Sekolah memilih eksekusi langsung (ronde 74): alat aksi langsung berjalan
    # bila Ollama aktif. Bila ingin mode saran saja, matikan di halaman Ollama.
    KUNCI_EKSEKUSI: "1",
    # Model besar (14B) di CPU butuh inference lama, apalagi dengan pemanggilan
    # alat (beberapa putaran). Batas bawaan diperbesar supaya tidak galat timeout.
    KUNCI_DETIK: "300",
}

#: Batas iterasi pemanggilan alat dalam satu percakapan (anti «model berputar»).
BATAS_LOOP = 6
#: Batas riwayat percakapan yang dikirim ke model (yang tertua dipotong).
BATAS_RIWAYAT = 20
#: Batas detik per permintaan HTTP ke Ollama (7B/14B di CPU butuh waktu).
DETIK_PERMINTAAN = 180

#: Jabaran insentif yang sah (sejajar dengan menu insentif).
JABATAN_INSENTIF = ("Kepala Sekolah", "Wakil Kepala Sekolah", "Guru",
                    "Tenaga Kependidikan", "Pelatih")
#: Status persetujuan yang sah.
STATUS_PERSETUJUAN = ("menunggu", "disetujui", "ditolak", "dibatalkan", "semua")


class OllamaGalat(RuntimeError):
    """Gagal menghubungi atau membaca jawaban Ollama."""


class OllamaTidakAktif(OllamaGalat):
    """Ollama belum diaktifkan di pengaturan bodap."""


def pengaturan() -> dict[str, str]:
    """Pengaturan Ollama (nilai kosong diisi bawaan)."""
    return {key: (services.get_setting(key) or OLLAMA_BAWAAN.get(key, ""))
            for key in OLLAMA_KEYS}


def simpan_pengaturan(nilai: Mapping[str, Any]) -> list[str]:
    """Simpan pengaturan Ollama. Kembalikan daftar kunci yang berubah."""
    berubah: list[str] = []
    for key in OLLAMA_KEYS:
        if key not in nilai:
            continue
        nilai_baru = "" if nilai.get(key) is None else str(nilai.get(key)).strip()
        if key == KUNCI_URL:
            nilai_baru = nilai_baru.rstrip("/")
        if services.get_setting(key) != nilai_baru:
            services.set_setting(key, nilai_baru)
            berubah.append(key)
    services.log_audit(None, "admin", "simpan_pengaturan_ollama", "settings",
                       "ollama", ", ".join(berubah))
    return berubah


def simpan_laporan_uji(laporan: dict[str, Any]) -> None:
    services.set_setting(KUNCI_UJI, json.dumps(laporan, ensure_ascii=False))


def baca_laporan_uji() -> dict[str, Any]:
    mentah = services.get_setting(KUNCI_UJI) or ""
    if not mentah.strip():
        return {}
    try:
        laporan = json.loads(mentah)
    except (ValueError, TypeError):
        return {}
    return laporan if isinstance(laporan, dict) else {}


# --------------------------------------------------------------------------- #
# Klien HTTP Ollama (urllib — tanpa dependensi baru)
# --------------------------------------------------------------------------- #
def _detik_pengaturan(setting: Mapping[str, str]) -> int:
    """Batas detik per permintaan HTTP — dari pengaturan, dibatasi 10–1800."""
    try:
        nilai = int(str(setting.get(KUNCI_DETIK) or DETIK_PERMINTAAN).strip())
    except (TypeError, ValueError):
        nilai = DETIK_PERMINTAAN
    return max(10, min(1800, nilai))


def _tampaknya_pesan_meta(isi: str) -> bool:
    """Tangkap jawaban model yang berupa pesan meta, bukan jawaban nyata.

    Model kadang mengembalikan teks seperti «saya akan menjawab… mohon berikan
    hasil alat…» alih-alih menyebutkan jawaban, padahal hasil alat sudah
    tersedia. Deteksi pola itu supaya bisa dipaksa menjawab dari hasil alat.
    """
    jika_tidak = (not isi or len(isi.strip()) < 8)
    if jika_tidak:
        return False
    teks = isi.lower()
    meta = ("saya akan", "mohon berikan", "agar saya dapat", "saya dapat membantu",
            "berikan saya", "sudah tersedia", "saya akan menjawab", "tunggu",
            "silakan berikan", "mohon informasi")
    if not any(kata in teks for kata in meta):
        return False
    # Bila sudah menyebut angka konkret, dianggap jawaban — bukan pesan meta.
    return not re.search(r"\d", isi)


def _pesan_kosong(model: str) -> str:
    """Pesan bila model kembali tanpa jawaban — model mungkin terlalu kecil."""
    return (
        "Ollama tidak memberikan jawaban (model «" + (model or "—") + "» mungkin "
        "terlalu kecil untuk panggilan alat atau sedang memproses). Coba "
        "ulangi, atau gunakan model yang lebih besar (mis. qwen2.5:14b-instruct)."
    )


def _pesan_timeout(detik: int) -> str:
    """Pesan galat timeout yang membantu — model besar di CPU memang lambat."""
    return (
        "Ollama terlalu lama menjawab (melebihi " + str(detik) + " detik). Model besar "
        "di CPU memang lambat — tunggu lalu coba lagi, gunakan model yang "
        "lebih kecil (mis. qwen2.5:7b-instruct), atau naikkan batas waktu "
        "di pengaturan Ollama."
    )


def _potong_hasil(isi: str, batas: int = 3000) -> str:
    """Potong hasil alat yang terlalu besar agar konteks tidak membanjiri model.

    Hasil alat yang panjang (mis. daftar 200 baris) akan memenuhi konteks model
    kecil. Dipotong dengan tanda «dipotong» supaya model tahu harus mempersempit
    saringan/limit bila butuh detail lebih lanjut.
    """
    if len(isi) <= batas:
        return isi
    return isi[:batas] + "… (dipotong; persempit saringan/limit)"


def _format_detik(detik: float) -> str:
    """Format durasi menjadi teks ramah («12 detik» / «1 menit 20 detik»)."""
    jika = max(0.0, float(detik))
    jika_menit, sisa = divmod(jika, 60)
    jika_menit = int(jika_menit)
    sisa = int(round(sisa))
    if jika_menit <= 0:
        return f"{sisa} detik"
    return f"{jika_menit} menit {sisa} detik" if sisa else f"{jika_menit} menit"


def _permintaan(url: str, metode: str = "GET", tubuh: dict[str, Any] | None = None,
                kunci: str = "", detik: int = DETIK_PERMINTAAN) -> dict[str, Any]:
    """Kirim permintaan JSON ke Ollama dan baca jawaban JSON."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if kunci:
        headers["Authorization"] = f"Bearer {kunci}"
    data = json.dumps(tubuh, ensure_ascii=False).encode("utf-8") if tubuh is not None else None
    permintaan = urllib.request.Request(url, data=data, headers=headers, method=metode)
    try:
        with urllib.request.urlopen(permintaan, timeout=detik) as jawaban:
            mentah = jawaban.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as galat:
        rincian = ""
        try:
            rincian = galat.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001 - rincian hanya pelengkap pesan
            pass
        raise OllamaGalat(f"Ollama menjawab galat HTTP {galat.code}"
                          f"{(': ' + rincian) if rincian else ''}") from galat
    except urllib.error.URLError as galat:
        alasan = str(galat.reason or "").lower()
        if "timed out" in alasan or "timeout" in alasan:
            raise OllamaGalat(_pesan_timeout(detik)) from galat
        raise OllamaGalat(f"Tidak dapat menghubungi Ollama di {url}. "
                          f"Periksa apakah Ollama berjalan dan alamatnya benar "
                          f"({galat.reason}).") from galat
    except TimeoutError as galat:
        raise OllamaGalat(_pesan_timeout(detik)) from galat
    except OSError as galat:
        if "timed out" in str(galat).lower() or "timeout" in str(galat).lower():
            raise OllamaGalat(_pesan_timeout(detik)) from galat
        raise OllamaGalat(f"Gagal menghubungi Ollama di {url}: {galat}") from galat
    try:
        return json.loads(mentah)
    except ValueError as galat:
        raise OllamaGalat(f"Jawaban Ollama bukan JSON: {mentah[:200]}") from galat


def cek_koneksi(cfg: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Uji koneksi: daftar model yang tersedia di Ollama."""
    setting = cfg if cfg is not None else pengaturan()
    url = (setting.get(KUNCI_URL) or "").strip().rstrip("/")
    if not url:
        return {"ok": False, "model": [], "pesan": "Alamat Ollama belum diisi."}
    try:
        hasil = _permintaan(f"{url}/api/tags",
                            kunci=(setting.get(KUNCI_KUNCI) or ""),
                            detik=_detik_pengaturan(setting))
    except OllamaGalat as galat:
        return {"ok": False, "model": [], "pesan": str(galat)}
    model = [str(m.get("name") or "") for m in (hasil.get("models") or []) if m.get("name")]
    return {"ok": True, "model": model,
            "pesan": f"Ollama terhubung — {len(model)} model tersedia."}


# --------------------------------------------------------------------------- #
# Skema alat (tool) — untuk model + pelaku untuk bodap
# --------------------------------------------------------------------------- #
def _alat(nama: str, deskripsi: str, sifat: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function",
            "function": {"name": nama, "description": deskripsi,
                         "parameters": sifat}}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


_STR = {"type": "string"}
_INT = {"type": "integer"}

_ALAT_SKEMA: list[dict[str, Any]] = [
    # ------------------------------------------------------------- status -- #
    _alat("lihat_status_bot",
          "Ringkasan Bot Dapodik: berjalan/idle, kemajuan, siswa yang diproses, "
          "catatan terbaru.",
          _obj({})),
    _alat("lihat_status_insentif",
          "Ringkasan modul insentif: periode, status impor rekening, draf SPJ.",
          _obj({})),
    _alat("lihat_status_spj",
          "Status pembuatan SPJ: apakah berkas rekening & absensi e-gov sudah "
          "diunggah + ringkasan.",
          _obj({})),
    _alat("baca_hasil_bot",
          "Hasil Bot Dapodik terakhir: hitungan berhasil/gagal/dilewati + catatan.",
          _obj({})),
    # ------------------------------------------------------------------ data -- #
    _alat("lihat_daftar_siswa",
          "Daftar siswa (lihat sejumlah baris). Saring q/rombel/tingkat/status; "
          "limit 1–200. Untuk hitung jumlah, pakai lihat_jumlah_siswa.",
          _obj({"q": {**_STR, "description": "Pencarian nama/NISN."},
                "rombel": {**_STR, "description": "Nama rombel."},
                "tingkat": {**_STR, "description": "Tingkat kelas."},
                "status": {**_STR, "description": "Status siswa."},
                "limit": {**_INT, "description": "Batas baris (1–200)."}})),
    _alat("lihat_jumlah_siswa",
          "Hitung jumlah siswa eksak (tanpa daftar baris). Pakai untuk semua "
          "pertanyaan jumlah siswa. Opsional pecahan_rombel/tingkat/status.",
          _obj({"q": {**_STR, "description": "Pencarian nama/NISN."},
                "rombel": {**_STR, "description": "Nama rombel."},
                "tingkat": {**_STR, "description": "Tingkat kelas."},
                "status": {**_STR, "description": "Status siswa."},
                "pecahan_rombel": {"type": "boolean",
                                   "description": "Jumlah per rombel."},
                "pecahan_tingkat": {"type": "boolean",
                                    "description": "Jumlah per tingkat."},
                "pecahan_status": {"type": "boolean",
                                   "description": "Jumlah per status."}})),
    _alat("lihat_siswa",
          "Detail lengkap satu siswa berdasarkan NISN (10 digit).",
          _obj({"nisn": {**_STR, "description": "NISN siswa (10 digit)."}},
               ["nisn"])),
    _alat("lihat_daftar_gtk",
          "Daftar guru & tendik (GTK). Saring jenis/status/cari; limit 1–500.",
          _obj({"jenis": {**_STR, "description": "guru atau tendik."},
                "status": {**_STR, "description": "Status pegawai."},
                "cari": {**_STR, "description": "Teks pencarian."},
                "limit": {**_INT, "description": "Batas baris (1–500)."}})),
    _alat("lihat_antrean_persetujuan",
          "Pengajuan perubahan data siswa. Saring status (menunggu/disetujui/"
          "ditolak/dibatalkan/semua) atau q.",
          _obj({"status": {**_STR, "description": "Status pengajuan (kosong = menunggu)."},
                "q": {**_STR, "description": "Pencarian nama/NISN."}})),
    _alat("lihat_ekskul",
          "Daftar ekstrakurikuler + jumlah anggota. aktif_hanya=true untuk aktif.",
          _obj({"aktif_hanya": {"type": "boolean", "description": "Hanya ekskul aktif."}})),
    _alat("lihat_status_tangcer",
          "Ringkasan TANGCER: penerima tersimpan + daftar penerima (tahun/semester/cari).",
          _obj({"tahun": {**_STR, "description": "Tahun (mis. 2026)."},
                "semester": {**_STR, "description": "Ganjil atau Genap."},
                "cari": {**_STR, "description": "Pencarian nama."}})),
    _alat("lihat_pengaturan",
          "Pengaturan bodap: identitas sekolah, tahun/semester, tarif insentif, "
          "fitur aktif. Baca saja.",
          _obj({})),
    # -------------------------------------------------------------- bot/SPJ -- #
    _alat("jalankan_bot_dapodik",
          "Mulai Bot Dapodik untuk antrean siswa. rombel kosong=semua; limit; "
          "nisn_manual (satu per baris).",
          _obj({"rombel": {**_STR, "description": "Nama rombel (kosong = semua)."},
                "limit": {**_INT, "description": "Batas jumlah siswa (0 = semua)."},
                "nisn_manual": {**_STR, "description": "NISN manual, satu per baris."}})),
    _alat("hentikan_bot_dapodik",
          "Hentikan Bot Dapodik yang sedang berjalan.",
          _obj({})),
    _alat("buat_spj",
          "Buat dokumen SPJ dari draf yang diunggah. dokumen: spj/pns/pppk; "
          "tgl 1–31 (kosong = akhir bulan).",
          _obj({"dokumen": {**_STR, "description": "spj, pns, atau pppk."},
                "tgl": {**_INT, "description": "Tanggal 1–31 (kosong = akhir bulan)."}})),
    _alat("buat_spj_tangcer",
          "Susun paket SPJ TANGCER (docx+xlsx+PDF) dari penerima tersimpan. "
          "Hanya isi tahun & semester; sisanya diisi otomatis dari pengaturan "
          "sekolah dan pengisian terakhir. Pastikan ada data penerima TANGCER.",
          _obj({"tahun": {**_STR, "description": "Tahun (mis. 2026)."},
                "semester": {**_STR, "description": "Ganjil atau Genap."}},
               ["tahun", "semester"])),
    # ------------------------------------------------------ insentif tulis -- #
    _alat("putuskan_pengajuan",
          "Setujui (terima) atau tolak pengajuan siswa. Ambil request_id dari "
          "lihat_antrean_persetujuan.",
          _obj({"request_id": {**_INT, "description": "ID pengajuan."},
                "keputusan": {**_STR, "description": "terima atau tolak."},
                "catatan": {**_STR, "description": "Catatan (opsional)."}},
               ["request_id", "keputusan"])),
    _alat("buat_periode_insentif",
          "Buat draf periode insentif baru. tahun; bulan 1–12; salin_dari opsional.",
          _obj({"tahun": {**_INT, "description": "Tahun (mis. 2027)."},
                "bulan": {**_INT, "description": "Bulan 1–12."},
                "salin_dari": {**_INT, "description": "ID periode untuk salin roster."}},
               ["tahun", "bulan"])),
    _alat("hapus_periode_insentif",
          "Hapus draf periode + semua rosternya. Permanen — pastikan periode_id benar.",
          _obj({"periode_id": {**_INT, "description": "ID periode insentif."}},
               ["periode_id"])),
    _alat("tambah_orang_insentif",
          "Tambah satu baris penerima ke roster. dokumen: pns/pppk/spj; nilai: "
          "JSON (nama_tampil wajib).",
          _obj({"periode_id": {**_INT, "description": "ID periode insentif."},
                "dokumen": {**_STR, "description": "pns, pppk, atau spj."},
                "nilai": {"type": "object", "description": "Bidang penerima (JSON)."}},
               ["periode_id", "dokumen", "nilai"])),
    _alat("ubah_orang_insentif",
          "Ubah baris roster. nilai: JSON bidang yang diubah.",
          _obj({"baris_id": {**_INT, "description": "ID baris roster."},
                "nilai": {"type": "object", "description": "Bidang yang diubah (JSON)."}},
               ["baris_id", "nilai"])),
    _alat("hapus_orang_insentif",
          "Hapus baris roster. Permanen — pastikan baris_id benar.",
          _obj({"baris_id": {**_INT, "description": "ID baris roster."}},
               ["baris_id"])),
    _alat("geser_orang_insentif",
          "Geser urutan baris roster: arah -1 naik, +1 turun.",
          _obj({"baris_id": {**_INT, "description": "ID baris roster."},
                "arah": {**_INT, "description": "-1 naik, +1 turun."}},
               ["baris_id", "arah"])),
    _alat("tambah_libur",
          "Tambah/ganti tanggal libur. tanggal YYYY-MM-DD, nama, jenis "
          "(nasional/cuti/kustom).",
          _obj({"tanggal": {**_STR, "description": "Tanggal YYYY-MM-DD."},
                "nama": {**_STR, "description": "Nama libur."},
                "jenis": {**_STR, "description": "nasional, cuti, kustom."}},
               ["tanggal", "nama"])),
    _alat("hapus_libur",
          "Hapus tanggal libur. Pastikan tanggal benar.",
          _obj({"tanggal": {**_STR, "description": "Tanggal YYYY-MM-DD."}},
               ["tanggal"])),
    _alat("ubah_jabatan_insentif",
          "Ubah jabatan insentif pegawai GTK. jabatan: Kepala Sekolah/Wakil/"
          "Guru/Tendik/Pelatih; kosong = otomatis.",
          _obj({"pegawai_id": {**_INT, "description": "ID pegawai GTK."},
                "jabatan": {**_STR, "description": "Jabatan insentif (kosong = otomatis)."}},
               ["pegawai_id"])),
]

#: Alat yang mengeksekusi aksi nyata (dibatasi oleh pengaturan eksekusi).
_ALAT_AKSI = frozenset({
    "jalankan_bot_dapodik", "hentikan_bot_dapodik", "unggah_berkas_spj",
    "buat_spj", "buat_spj_tangcer", "putuskan_pengajuan", "buat_periode_insentif",
    "hapus_periode_insentif", "tambah_orang_insentif", "ubah_orang_insentif",
    "hapus_orang_insentif", "geser_orang_insentif", "tambah_libur",
    "hapus_libur", "ubah_jabatan_insentif",
})

#: Alat hapus/ubah yang berbahaya: ID yang dipakai harus pernah muncul di hasil
#: alat lihat_* sebelumnya pada jejak — supaya model kecil tidak mengarang ID.
_ALAT_BUTUH_ID: dict[str, str] = {
    "hapus_periode_insentif": "periode_id",
    "hapus_orang_insentif": "baris_id",
    "ubah_orang_insentif": "baris_id",
    "geser_orang_insentif": "baris_id",
    "ubah_jabatan_insentif": "pegawai_id",
    "putuskan_pengajuan": "request_id",
}


def _id_terlihat(nama: str, argumen: dict[str, Any], jejak: list[dict[str, Any]]) -> bool:
    """Cek ID alat hapus/ubah sudah pernah muncul di hasil alat lihat_*."""
    kunci = _ALAT_BUTUH_ID.get(nama)
    if not kunci or kunci not in argumen:
        return True
    id_nilai = str(argumen.get(kunci) or "").strip()
    if not id_nilai:
        return True
    untuk = id_nilai.lower()
    for satu in jejak:
        if not str(satu.get("alat") or "").startswith("lihat_"):
            continue
        teks = str(satu.get("hasil") or "")
        if untuk in teks.lower():
            return True
    return False


SYSTEM_PROMPT = (
    "Anda assistant yang mengoperasikan aplikasi sekolah «SM» (bodap) di komputer "
    "pengguna, **hanya dengan memanggil alat** yang tersedia. Aturan keras:\n"
    "- **Selalu panggil alat** untuk data. **JANGAN mengarang** angka, nama, ID, "
    "atau hasil. Jawaban HANYA dari hasil alat yang dikembalikan.\n"
    "- **JANGAN** menulis pemanggilan alat sebagai JSON di teks; panggil alatnya, "
    "tunggu hasil, jangan menulis hasil fiktif.\n"
    "- Jawab bahasa Indonesia, ringkas. Peta alat: «jumlah siswa» → HANYA «lihat_"
    "jumlah_siswa»; «daftar siswa» → «lihat_daftar_siswa»; bot → «lihat_status_bot»; "
    "insentif/SPJ → «lihat_status_insentif»/«lihat_status_spj».\n"
    "- Untuk pekerjaan (bot, unggahan/pembuatan berkas, ubah data), panggil alatnya "
    "dan laporkan hasil yang benar; jangan menyatakan berhasil bila alat gagal.\n"
    "- **Setelah alat mengembalikan hasil, langsung sebutkan jawabannya.** JANGAN "
    "pesan meta atau meminta data yang sudah ada.\n"
    "- Bila butuh ID (periode, roster, pengajuan, pegawai), ambil dari alat "
    "lihat_... — jangan mengarang. Alat «hapus_...» permanen; pastikan ID benar.\n"
    "- Sampaikan pesan kesalahan/saran alat kepada pengguna apa adanya."
)

#: System prompt untuk **jembatan WhatsApp** — nada percakapan alami seperti
#: Meta AI, tetapi aturan keras akurasi alat tetap sama (tidak mengarang, jawab
#: dari alat, jawab langsung setelah alat). WA bukan tempat tabel besar.
SYSTEM_PROMPT_WA = (
    "Anda asisten sekolah «SM» yang ramah, mengobrol natural seperti Meta AI. "
    "Anda mengoperasikan aplikasi hanya dengan memanggil alat yang tersedia. "
    "Aturan keras (tidak boleh dilanggar):\n"
    "- **Selalu panggil alat** untuk data. **JANGAN mengarang** angka, nama, ID, "
    "atau hasil. Jawaban HANYA dari hasil alat yang dikembalikan.\n"
    "- **JANGAN** menulis pemanggilan alat sebagai JSON di teks; panggil alatnya, "
    "tunggu hasil, jangan menulis hasil fiktif.\n"
    "- Peta alat: «jumlah siswa» → HANYA «lihat_jumlah_siswa»; «daftar siswa» → «lihat_"
    "daftar_siswa»; bot → «lihat_status_bot»; insentif/SPJ → «lihat_status_insentif»/«lihat_"
    "status_spj».\n"
    "- Untuk pekerjaan (bot, unggahan/pembuatan berkas, ubah data), panggil alatnya "
    "dan laporkan hasil yang benar; jangan menyatakan berhasil bila alat gagal.\n"
    "- **Setelah alat mengembalikan hasil, langsung sebutkan jawabannya.** JANGAN "
    "pesan meta atau meminta data yang sudah ada.\n"
    "- Bila butuh ID (periode, roster, pengajuan, pegawai), ambil dari alat "
    "lihat_... — jangan mengarang. Alat «hapus_...» permanen; pastikan ID benar.\n"
    "- Nada: hangat, ringkas, seperti mengobrol. WA bukan tempat tabel besar — "
    "beri ringkasan pendek; untuk daftar lengkap, tawarkan/beri tautan ke halaman "
    "aplikasi. Sampaikan pesan kesalahan/saran alat apa adanya."
)


# --------------------------------------------------------------------------- #
# Pelaku alat — setiap alat dipetakan ke fungsi bodap yang sudah teruji
# --------------------------------------------------------------------------- #
def _orang_egov() -> list[dict[str, Any]]:
    """Orang + tanggal DL dari draf unggahan absensi e-gov (bisa kosong)."""
    draf = insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK_EGov)
    if not draf:
        return []
    try:
        return insentif_impor.baca_absensi_egov(draf["path"])
    except ValueError as galat:
        log.warning("Absensi e-gov tak terbaca: %s", galat)
        return []


def _ringkas_periode(batas: int = 12) -> list[dict[str, Any]]:
    periode = []
    for baris in insentif.daftar_periode()[:batas]:
        periode.append({
            "id": baris.get("id"),
            "bulan": baris.get("bulan"),
            "tahun": baris.get("tahun"),
            "nama": baris.get("nama") or "",
        })
    return periode


def _pelaku_lihat_status_bot() -> dict[str, Any]:
    hidup = bot_dapodik.status_bot()
    ringkas = services.ringkas_bot()
    job = ringkas.get("job") or {}
    hitung = ringkas.get("hitung") or {}
    return {
        "ok": True,
        "berjalan": bool(hidup.get("berjalan")),
        "job": {
            "id": job.get("id"), "status": job.get("status"),
            "total": job.get("total_item") or 0,
            "berhasil": job.get("sukses_item") or 0,
            "gagal": job.get("gagal_item") or 0,
            "mode": job.get("mode"),
            "mulai": job.get("started_at"), "selesai": job.get("finished_at"),
        },
        "hitung": {kunci: hitung.get(kunci, 0) for kunci in
                   ("sukses", "gagal", "dilewati", "menunggu")},
        "sedang": (ringkas.get("sedang") or {}).get("nama") or "",
        "catatan_terakhir": (job.get("log") or "").splitlines()[-8:],
    }


def _pelaku_lihat_status_insentif() -> dict[str, Any]:
    draf_cetak = insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK) or {}
    draf_egov = insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK_EGov) or {}
    return {
        "ok": True,
        "periode": _ringkas_periode(),
        "impor": insentif_impor.status(),
        "draf_cetak_spj": {"ada": bool(draf_cetak), "nama": draf_cetak.get("nama", "")},
        "draf_absensi_egov": {"ada": bool(draf_egov), "nama": draf_egov.get("nama", "")},
    }


def _pelaku_lihat_status_spj() -> dict[str, Any]:
    draf = insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK)
    if not draf:
        return {"ok": True, "ada_berkas": False,
                "pesan": "Belum ada berkas rekening yang diunggah."}
    try:
        baris = insentif_impor.baca_berkas_rekening(draf["path"])
        bln, thn = insentif_impor.bulan_tahun_judul(draf["path"])
        roster = insentif_impor.roster_dari_berkas(baris)
        grup = insentif_impor.bagi_absensi(baris)
        dl = insentif_impor.tanda_dl(_orang_egov())
    except ValueError as galat:
        return {"ok": False, "ada_berkas": True,
                "pesan": f"Berkas tersimpan tapi tak terbaca: {galat}"}
    orang_e = _orang_egov()
    by_kunci = {insentif_impor.kunci_orang(o): o for o in orang_e}
    return {
        "ok": True, "ada_berkas": True, "nama": draf.get("nama", ""),
        "bulan": bln, "tahun": thn,
        "penerima": len(roster),
        "pns": len(grup.get("pns") or []), "pppk": len(grup.get("pppk") or []),
        "total_dana": sum(r.get("tarif") or 0 for r in roster),
        "draf_absensi_egov": bool(insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK_EGov)),
        "tanggal_dl": sum(len(v) for v in dl.values()),
        "orang_dl": len(dl),
        "contoh_nama_dl": [by_kunci.get(k, {}).get("nama", k) for k in list(dl)[:6]],
    }


def _pelaku_baca_hasil_bot() -> dict[str, Any]:
    ringkas = services.ringkas_bot()
    job = ringkas.get("job") or {}
    job_id = int(job["id"]) if job.get("id") else 0
    items = services.items_bot(job_id, limit=25) if job_id else []
    catatan, _dari = services.baca_catatan_bot(job_id) if job_id else ("", "")
    return {
        "ok": True,
        "job": {
            "id": job_id, "status": job.get("status"),
            "berhasil": job.get("sukses_item") or 0,
            "gagal": job.get("gagal_item") or 0,
            "dilewati": (ringkas.get("hitung") or {}).get("dilewati", 0),
            "mode": job.get("mode"),
        },
        "items": [{"nisn": i.get("nisn"), "nama": i.get("nama"),
                   "status": i.get("status"), "pesan": i.get("pesan")}
                  for i in items],
        "catatan_terakhir": catatan.splitlines()[-15:],
    }


def _angka_batas(nilai: Any, bawaan: int, minimum: int, maksimum: int) -> int:
    try:
        angka = int(nilai)
    except (TypeError, ValueError):
        return bawaan
    return max(minimum, min(maksimum, angka))


def _pelaku_lihat_daftar_siswa(arg: Mapping[str, Any]) -> dict[str, Any]:
    batas = _angka_batas(arg.get("limit"), 20, 1, 200)
    penyaring = services.StudentFilter(
        q=str(arg.get("q") or "").strip(),
        rombel=str(arg.get("rombel") or "").strip(),
        tingkat=str(arg.get("tingkat") or "").strip(),
        status=str(arg.get("status") or "").strip(),
    )
    baris, total = services.list_students(penyaring, page=1, per_page=batas)
    return {
        "ok": True, "total": total, "limit": batas,
        "baris": [{"id": baris_satu.get("id"), "nisn": baris_satu.get("nisn"),
                   "nama": baris_satu.get("nama"), "rombel": baris_satu.get("rombel"),
                   "tingkat": baris_satu.get("tingkat"),
                   "status": baris_satu.get("status")}
                  for baris_satu in baris],
    }


def _pelaku_lihat_jumlah_siswa(arg: Mapping[str, Any]) -> dict[str, Any]:
    """Hitung jumlah siswa secara eksak — murah (COUNT/*) walau ribuan."""
    penyaring = services.StudentFilter(
        q=str(arg.get("q") or "").strip(),
        rombel=str(arg.get("rombel") or "").strip(),
        tingkat=str(arg.get("tingkat") or "").strip(),
        status=str(arg.get("status") or "").strip(),
    )
    # per_page=1: COUNT(*) tetap dihitung penuh, tetapi baris tidak dimuat.
    _, total = services.list_students(penyaring, page=1, per_page=1)
    where, params = penyaring.where_clause()
    pecahan: dict[str, list[dict[str, Any]]] = {}
    if str(arg.get("pecahan_rombel") or "").strip().lower() in ("1", "true", "yes"):
        pecahan["per_rombel"] = _hitung_kelompok("rombel", where, params)
    if str(arg.get("pecahan_tingkat") or "").strip().lower() in ("1", "true", "yes"):
        pecahan["per_tingkat"] = _hitung_kelompok("tingkat", where, params)
    if str(arg.get("pecahan_status") or "").strip().lower() in ("1", "true", "yes"):
        pecahan["per_status"] = _hitung_kelompok("status", where, params)
    hasil = {"ok": True, "total": total}
    hasil.update(pecahan)
    hasil["pesan"] = (f"Total siswa yang cocok: {total}."
                      + (" Tersedia juga ringkasan per kelompok." if pecahan else ""))
    return hasil


def _hitung_kelompok(kolom: str, where: str, params: list[Any]) -> list[dict[str, Any]]:
    """Jumlah per nilai kolom (GROUP BY) — hanya untuk kolom sebaris."""
    if kolom not in ("rombel", "tingkat", "status"):
        return []
    baris = db.query_all(
        f"SELECT {kolom} AS nilai, COUNT(*) AS jumlah FROM students s "
        f"WHERE {where} GROUP BY {kolom} ORDER BY jumlah DESC, nilai ASC",
        params)
    return [{"nilai": (b["nilai"] or "—"), "jumlah": int(b["jumlah"] or 0)}
            for b in baris]


def _pelaku_lihat_siswa(arg: Mapping[str, Any]) -> dict[str, Any]:
    nisn = str(arg.get("nisn") or "").strip()
    if not nisn:
        return {"ok": False, "pesan": "NISN wajib diisi."}
    baris = services.get_student_by_nisn(nisn)
    if baris is None:
        return {"ok": False, "pesan": f"Siswa dengan NISN «{nisn}» tidak ditemukan."}
    return {"ok": True, "siswa": baris}


def _pelaku_lihat_daftar_gtk(arg: Mapping[str, Any]) -> dict[str, Any]:
    batas = _angka_batas(arg.get("limit"), 50, 1, 500)
    baris = gtk.daftar_pegawai(jenis=str(arg.get("jenis") or "").strip(),
                              status=str(arg.get("status") or "").strip(),
                              cari=str(arg.get("cari") or "").strip(),
                              batas=batas)
    return {
        "ok": True, "jumlah": len(baris),
        "baris": [{"id": b.get("id"), "nama": b.get("nama"),
                   "jenis": b.get("jenis_ptk"),
                   "status": b.get("status_kepegawaian"),
                   "nip": b.get("nip"),
                   "pangkat": b.get("pangkat_golongan"),
                   "rekening_ada": bool(str(b.get("rekening") or "").strip())}
                  for b in baris],
    }


def _pelaku_lihat_antrean_persetujuan(arg: Mapping[str, Any]) -> dict[str, Any]:
    status = str(arg.get("status") or "menunggu").strip()
    if status not in STATUS_PERSETUJUAN:
        return {"ok": False, "pesan": f"Status tidak dikenal. Pilih: {', '.join(STATUS_PERSETUJUAN)}."}
    q = str(arg.get("q") or "").strip()
    daftar = services.daftar_pengajuan(status=None if status == "semua" else status,
                                       q=q, limit=50)
    return {
        "ok": True, "status": status,
        "statistik": services.statistik_pengajuan(),
        "pengajuan": [{"id": p.get("id"), "nisn": p.get("nisn"),
                       "nama": p.get("nama"), "rombel": p.get("rombel"),
                       "status": p.get("status"),
                       "jumlah_field": p.get("jumlah_field")}
                      for p in daftar],
    }


def _pelaku_lihat_ekskul(arg: Mapping[str, Any]) -> dict[str, Any]:
    aktif_hanya = str(arg.get("aktif_hanya") or "").strip().lower() in ("1", "true", "yes")
    daftar = services.list_ekskul(aktif_only=aktif_hanya)
    return {
        "ok": True, "jumlah": len(daftar),
        "ekskul": [{"id": e.get("id"), "nama": e.get("nama"),
                    "pembina": e.get("pembina"), "pelatih": e.get("pelatih"),
                    "hari": e.get("hari"),
                    "jam": f"{e.get('jam_mulai')}–{e.get('jam_selesai')}",
                    "anggota": e.get("jumlah_anggota"), "aktif": e.get("aktif")}
                   for e in daftar],
    }


def _pelaku_lihat_status_tangcer(arg: Mapping[str, Any]) -> dict[str, Any]:
    ringkas = tangcer.ringkas_penerima()
    daftar = tangcer.daftar_penerima(
        tahun=str(arg.get("tahun") or "").strip(),
        semester=str(arg.get("semester") or "").strip(),
        cari=str(arg.get("cari") or "").strip(),
        cocok="", batas=20)
    return {
        "ok": True, "ringkas": ringkas, "jumlah": len(daftar),
        "penerima": [{"tahun": p.get("tahun"), "semester": p.get("semester"),
                      "tahap": p.get("tahap"), "nisn": p.get("nisn"),
                      "nama": p.get("nama"), "jenis": p.get("jenis"),
                      "nominal": p.get("nominal"), "cocok": p.get("cocok")}
                     for p in daftar],
    }


def _pelaku_lihat_pengaturan() -> dict[str, Any]:
    profil = services.school_profile()
    pengaturan_insentif = insentif.baca_pengaturan()
    preferensi = services.get_settings()
    return {
        "ok": True,
        "sekolah": {"nama": profil.get("nama"), "npsn": profil.get("npsn"),
                    "alamat": profil.get("alamat")},
        "tahun_ajaran": profil.get("tahun_ajaran"),
        "semester": profil.get("semester"),
        "tarif_insentif": {kunci: pengaturan_insentif.get(kunci) for kunci in
                           ("tarif_ks", "tarif_waka", "tarif_guru", "tarif_pelatih")},
        "fitur_aktif": {"pengajuan": preferensi.get("pengajuan_aktif") == "1",
                        "ekskul": preferensi.get("ekskul_aktif") == "1",
                        "dapodik_sync": preferensi.get("dapodik_sync_aktif") == "1",
                        "ollama": preferensi.get(KUNCI_AKTIF) == "1"},
    }


def _pelaku_jalankan_bot(arg: Mapping[str, Any]) -> dict[str, Any]:
    cfg = services.bot_setting()
    siap, keterangan = services.bot_siap_pakai()
    if not siap:
        return {"ok": False, "pesan": keterangan}
    rombel = str(arg.get("rombel") or "").strip()[:20]
    limit = _angka_batas(arg.get("limit"), 0, 0, 2000)
    nisn_manual = str(arg.get("nisn_manual") or "")
    antrean = services.bot_antrean(rombel=rombel, limit=limit, nisn_manual=nisn_manual)
    if not antrean:
        return {"ok": False, "pesan": "Antrean kosong: tidak ada siswa yang cocok dengan pilihan."}
    try:
        job_id, _bot = bot_dapodik.mulai_bot(antrean, cfg, actor="ollama")
    except bot_dapodik.BotBerjalanError as galat:
        return {"ok": False, "pesan": str(galat)}
    mode = ("simulasi" if cfg.get("bot_simulasi") == "1" else
            "di belakang layar" if cfg.get("bot_headless") == "1" else "dengan jendela Chrome")
    services.log_audit("ollama", "admin", "bot_mulai", "dapodik_jobs", str(job_id),
                       f"{len(antrean)} siswa (rombel={rombel or 'semua'})")
    return {"ok": True, "job_id": job_id, "jumlah_siswa": len(antrean), "mode": mode}


def _pelaku_hentikan_bot() -> dict[str, Any]:
    berhenti = bot_dapodik.hentikan_bot()
    services.log_audit("ollama", "admin", "bot_hentikan", "dapodik_jobs", "-",
                       "berhasil" if berhenti else "tidak ada bot berjalan")
    return {"ok": True, "dihentikan": berhenti,
            "pesan": "Bot dihentikan." if berhenti else "Tidak ada bot yang sedang berjalan."}


def _b64_decode(isi: str, nama: str) -> bytes:
    sisi = (isi or "").strip()
    if not sisi:
        raise ValueError(f"Isi berkas «{nama}» kosong.")
    try:
        return base64.b64decode(sisi, validate=True)
    except (binascii.Error, ValueError) as galat:
        raise ValueError(f"Isi berkas «{nama}» bukan base64 yang sah.") from galat


def _pelaku_unggah_berkas_spj(arg: Mapping[str, Any]) -> dict[str, Any]:
    nama = str(arg.get("nama_berkas") or "").strip()
    nama_e = str(arg.get("nama_absensi") or "").strip()
    if not nama or not nama_e:
        return {"ok": False, "pesan": "Nama berkas rekening dan berkas absensi wajib diisi."}
    try:
        isi = _b64_decode(str(arg.get("isi_berkas") or ""), nama)
        isi_e = _b64_decode(str(arg.get("isi_absensi") or ""), nama_e)
    except ValueError as galat:
        return {"ok": False, "pesan": str(galat)}
    if len(isi) > config.MAX_UPLOAD_BYTES or len(isi_e) > config.MAX_UPLOAD_BYTES:
        return {"ok": False, "pesan": f"Ukuran berkas melebihi {config.MAX_UPLOAD_MB} MB."}
    simpan = services.save_upload(nama, isi)
    if Path(simpan.path).suffix.lower() not in insentif_impor.EKSTENSI:
        simpan.path.unlink(missing_ok=True)
        return {"ok": False, "pesan": f"Jenis berkas «{simpan.extension}» belum didukung. "
                f"Yang didukung: {', '.join(insentif_impor.EKSTENSI)}."}
    try:
        baris = insentif_impor.baca_berkas_rekening(simpan.path, simpan.extension)
    except ValueError as galat:
        simpan.path.unlink(missing_ok=True)
        return {"ok": False, "pesan": str(galat)}
    if not baris:
        simpan.path.unlink(missing_ok=True)
        return {"ok": False, "pesan": "Tidak ada baris penerima yang terbaca. "
                "Pastikan berkas memuat kolom NO REKENING."}
    insentif_impor.simpan_draf(simpan.path, nama, insentif_impor.KUNCI_CETAK)
    # --- Absensi e-gov: dibaca sendiri, gagal tak menghapus draf rekening. ---
    simpan_e = services.save_upload(nama_e, isi_e)
    if Path(simpan_e.path).suffix.lower() not in insentif_impor.EGov_EKSTENSI:
        simpan_e.path.unlink(missing_ok=True)
        return {"ok": False, "pesan": f"Jenis berkas absensi «{simpan_e.extension}» "
                f"belum didukung. Yang didukung: {', '.join(insentif_impor.EGov_EKSTENSI)}."}
    try:
        orang_e = insentif_impor.baca_absensi_egov(simpan_e.path, simpan_e.extension)
    except ValueError as galat:
        simpan_e.path.unlink(missing_ok=True)
        return {"ok": False, "pesan": f"Absensi e-gov tak terbaca: {galat}"}
    if not orang_e:
        simpan_e.path.unlink(missing_ok=True)
        return {"ok": False, "pesan": "Tidak ada baris kehadiran yang terbaca dari "
                "berkas absensi e-gov."}
    insentif_impor.simpan_draf(simpan_e.path, nama_e, insentif_impor.KUNCI_CETAK_EGov)
    bln, thn = insentif_impor.bulan_tahun_judul(simpan.path)
    services.log_audit("ollama", "admin", "cetak_berkas_unggah", "cetak_berkas",
                       "-", f"{nama} + {nama_e}")
    return {"ok": True, "berkas": nama, "absensi": nama_e,
            "penerima": len(baris), "orang_absensi": len(orang_e),
            "bulan": bln, "tahun": thn,
            "pesan": "Berkas rekening dan absensi e-gov tersimpan — siap dibuat SPJ."}


def _pelaku_buat_spj(arg: Mapping[str, Any]) -> dict[str, Any]:
    draf = insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK)
    if not draf:
        return {"ok": False, "pesan": "Belum ada berkas rekening yang diunggah. "
                "Unggah dulu dengan alat unggah_berkas_spj."}
    try:
        baris = insentif_impor.baca_berkas_rekening(draf["path"])
    except ValueError as galat:
        return {"ok": False, "pesan": str(galat)}
    bln, thn = insentif_impor.bulan_tahun_judul(draf["path"])
    tahun = thn or datetime.now().year
    bulan = bln or datetime.now().month
    akhir = insentif.tanggal_terakhir(tahun, bulan)
    dokumen = str(arg.get("dokumen") or "spj").strip().lower()
    if dokumen not in ("spj", "pns", "pppk"):
        return {"ok": False, "pesan": "Dokumen tidak dikenal. Pilih: spj, pns, atau pppk."}
    tgl = _angka_batas(arg.get("tgl"), 0, 0, 31)
    if not 1 <= tgl <= 31:
        tgl = akhir
    ttd = insentif_impor.ttd_bawaan()
    ttd_json = json.dumps(ttd, ensure_ascii=False)
    try:
        if dokumen == "spj":
            periode = {"tahun": tahun, "bulan": bulan, "tgl_spj": tgl,
                       "ttd_json": ttd_json}
            roster = insentif_impor.roster_dari_berkas(baris)
            isi = insentif_pdf.pdf_spj(periode, roster)
            nama = f"spj-insentif-{tahun:04d}{bulan:02d}.pdf"
        else:
            merah = insentif.tanggal_merah(tahun, bulan, insentif.tambahan_libur())
            dl = insentif_impor.tanda_dl(_orang_egov())
            periode = {"tahun": tahun, "bulan": bulan, "tgl_absensi": tgl,
                       "libur_json": json.dumps({str(k): v for k, v in sorted(merah.items())},
                                                ensure_ascii=False),
                       "dl_json": json.dumps({k: v for k, v in sorted(dl.items())},
                                             ensure_ascii=False),
                       "ttd_json": ttd_json}
            grup = insentif_impor.bagi_absensi(baris)
            roster = insentif_impor.roster_dari_berkas(grup[dokumen])
            isi = insentif_pdf.pdf_absensi(dokumen, periode, roster)
            nama = f"absensi-{dokumen}-{tahun:04d}{bulan:02d}.pdf"
    except Exception as galat:  # noqa: BLE001 - kesalahan pembangkit PDF dilaporkan saja
        log.exception("Pembuatan SPJ via Ollama gagal")
        return {"ok": False, "pesan": f"Pembuatan dokumen gagal: {galat}"}
    folder = config.DATA_DIR / "ollama"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = folder / f"{stamp}__{nama}"
        target.write_bytes(isi)
    except OSError as galat:
        return {"ok": False, "pesan": f"Berkas hasil tidak dapat disimpan: {galat}"}
    services.log_audit("ollama", "admin", "insentif_pdf", "cetak_berkas",
                       "-", f"ollama buat {nama}")
    return {"ok": True, "dokumen": dokumen, "nama": nama, "lokasi": str(target),
            "ukuran": len(isi), "tgl": tgl,
            "pesan": f"Dokumen «{nama}» siap di unduh dari jalur {target}."}


def _pelaku_buat_spj_tangcer(arg: Mapping[str, Any]) -> dict[str, Any]:
    def _teks(kunci: str) -> str:
        return str(arg.get(kunci) or "").strip()
    form = {
        "tahun": _teks("tahun"), "semester": _teks("semester"),
        "tahap": _teks("tahap") or "1",
        "kepala": _teks("kepala"), "nip": _teks("nip"),
        "jabatan": _teks("jabatan") or "Kepala Sekolah", "alamat": _teks("alamat"),
        "kota": _teks("kota"), "tanggal": _teks("tanggal"),
        "biaya_personal": _teks("biaya_personal"), "volume": _teks("volume"),
        "sampel": _teks("sampel"),
        "dana_masuk": str(arg.get("dana_masuk") or "").strip().lower()
        in ("1", "true", "yes"),
    }
    # Penjaga nilai: tahun harus cocok dengan data penerima tersimpan — SPJ
    # pantang dicetak dari data tahun lain.
    tahun = _teks("tahun")
    peserta = tangcer.daftar_penerima(tahun=tahun, semester=_teks("semester"))
    if not peserta:
        return {"ok": False,
                "pesan": (f"Tidak ada data penerima tersimpan untuk tahun {tahun or '—'} "
                          f"semester {_teks('semester') or '—'}. Isi dulu menu TANGCER, "
                          f"atau pastikan tahunnya benar.")}
    try:
        data = spj.data_dari(form)
        baris = spj.baris_spj(data)
        paket = spj.buat_paket(data, baris)
    except tangcer.TangcerError as galat:
        return {"ok": False, "pesan": str(galat)}
    except Exception as galat:  # noqa: BLE001
        log.exception("Pembuatan SPJ TANGCER via Ollama gagal")
        return {"ok": False, "pesan": f"Gagal menyusun SPJ TANGCER: {galat}"}
    services.log_audit("ollama", "admin", "tangcer_spj", "spj", paket["token"],
                       f"{paket['ringkas'].get('jumlah_siswa', 0)} siswa, "
                       f"{len(paket['berkas'])} berkas")
    return {
        "ok": True, "token": paket["token"], "folder": paket["folder"],
        "sekolah": paket.get("sekolah"), "tahun": paket.get("tahun"),
        "semester": paket.get("semester"), "dibuat": paket.get("dibuat"),
        "ringkasan": paket.get("ringkas"),
        "berkas": paket.get("berkas"),
        "pesan": (f"Berkas SPJ TANGCER siap: {len(paket.get('berkas') or [])} berkas "
                  f"di {paket['folder']} (token {paket['token']})."),
    }


def _pelaku_putuskan_pengajuan(arg: Mapping[str, Any]) -> dict[str, Any]:
    try:
        request_id = int(arg.get("request_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "pesan": "request_id harus angka."}
    keputusan = str(arg.get("keputusan") or "").strip().lower()
    if keputusan not in ("terima", "tolak"):
        return {"ok": False, "pesan": "«keputusan» harus «terima» atau «tolak»."}
    try:
        hasil = services.putuskan_pengajuan(request_id, keputusan == "terima",
                                             aktor="ollama",
                                             catatan=str(arg.get("catatan") or "").strip())
    except ValueError as galat:
        return {"ok": False, "pesan": str(galat)}
    nama = hasil.get("nama") or ""
    if keputusan == "terima":
        pesan = (f"Pengajuan «{nama}» disetujui. "
                 f"{hasil.get('jumlah_diterapkan', 0)} kolom data diperbarui "
                 "dan tercatat pada riwayat perubahan.")
    else:
        pesan = f"Pengajuan «{nama}» ditolak. Siswa dapat mengajukan ulang."
    return {"ok": True, "keputusan": keputusan, "pengajuan": nama, "pesan": pesan}


def _pelaku_buat_periode_insentif(arg: Mapping[str, Any]) -> dict[str, Any]:
    try:
        tahun = int(arg.get("tahun") or 0)
        bulan = int(arg.get("bulan") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "pesan": "tahun dan bulan harus angka."}
    try:
        salin_dari = int(arg.get("salin_dari") or 0) or None
    except (TypeError, ValueError):
        salin_dari = None
    try:
        periode_id = insentif.buat_periode(tahun, bulan, salin_dari=salin_dari,
                                           actor="ollama")
    except ValueError as galat:
        return {"ok": False, "pesan": str(galat)}
    services.log_audit("ollama", "admin", "insentif_periode_buat", "insentif_periode",
                       str(periode_id), f"{bulan}/{tahun} salin_dari={salin_dari or '-'}")
    return {"ok": True, "periode_id": periode_id, "bulan": bulan, "tahun": tahun,
            "pesan": f"Periode {insentif.NAMA_BULAN_KECIL[bulan]} {tahun} dibuat "
                     f"(ID {periode_id})."}


def _pelaku_hapus_periode_insentif(arg: Mapping[str, Any]) -> dict[str, Any]:
    try:
        periode_id = int(arg.get("periode_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "pesan": "periode_id harus angka."}
    periode = insentif.get_periode(periode_id)
    if periode is None:
        return {"ok": False, "pesan": f"Periode ID {periode_id} tidak ditemukan."}
    insentif.hapus_periode(periode_id)
    services.log_audit("ollama", "admin", "insentif_periode_hapus", "insentif_periode",
                       str(periode_id), f"{periode.get('bulan')}/{periode.get('tahun')}")
    return {"ok": True, "dihapus": periode_id,
            "pesan": f"Periode ID {periode_id} dan semua rosternya dihapus."}


def _nilai_mapping(arg: Mapping[str, Any], kunci: str) -> Mapping[str, Any] | None:
    nilai = arg.get(kunci)
    if not isinstance(nilai, dict):
        return None
    return {str(k): v for k, v in nilai.items()}


def _pelaku_tambah_orang_insentif(arg: Mapping[str, Any]) -> dict[str, Any]:
    try:
        periode_id = int(arg.get("periode_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "pesan": "periode_id harus angka."}
    dokumen = str(arg.get("dokumen") or "").strip().lower()
    if dokumen not in ("pns", "pppk", "spj"):
        return {"ok": False, "pesan": "«dokumen» harus pns, pppk, atau spj."}
    nilai = _nilai_mapping(arg, "nilai")
    if nilai is None:
        return {"ok": False, "pesan": "«nilai» harus objek JSON dengan bidang penerima."}
    if not str(nilai.get("nama_tampil") or "").strip():
        return {"ok": False, "pesan": "Bidang «nama_tampil» wajib diisi."}
    if insentif.get_periode(periode_id) is None:
        return {"ok": False, "pesan": f"Periode ID {periode_id} tidak ditemukan."}
    try:
        baris_id = insentif.tambah_roster(periode_id, dokumen, nilai)
    except ValueError as galat:
        return {"ok": False, "pesan": str(galat)}
    services.log_audit("ollama", "admin", "insentif_roster_tambah", "insentif_roster",
                       str(baris_id), f"periode {periode_id} dokumen {dokumen}")
    return {"ok": True, "baris_id": baris_id,
            "pesan": f"Baris penerima «{nilai.get('nama_tampil')}» ditambahkan ke "
                     f"dokumen {dokumen} (baris ID {baris_id})."}


def _pelaku_ubah_orang_insentif(arg: Mapping[str, Any]) -> dict[str, Any]:
    try:
        baris_id = int(arg.get("baris_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "pesan": "baris_id harus angka."}
    nilai = _nilai_mapping(arg, "nilai")
    if nilai is None:
        return {"ok": False, "pesan": "«nilai» harus objek JSON dengan bidang yang diubah."}
    try:
        insentif.ubah_roster(baris_id, nilai)
    except ValueError as galat:
        return {"ok": False, "pesan": str(galat)}
    services.log_audit("ollama", "admin", "insentif_roster_ubah", "insentif_roster",
                       str(baris_id), ", ".join(sorted(nilai)))
    return {"ok": True, "baris_id": baris_id,
            "pesan": f"Baris roster ID {baris_id} diperbarui ({len(nilai)} bidang)."}


def _pelaku_hapus_orang_insentif(arg: Mapping[str, Any]) -> dict[str, Any]:
    try:
        baris_id = int(arg.get("baris_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "pesan": "baris_id harus angka."}
    baris = _ambil_roster(baris_id)
    if baris is None:
        return {"ok": False, "pesan": f"Baris roster ID {baris_id} tidak ditemukan."}
    insentif.hapus_roster(baris_id)
    services.log_audit("ollama", "admin", "insentif_roster_hapus", "insentif_roster",
                       str(baris_id), str(baris.get("nama_tampil") or ""))
    return {"ok": True, "dihapus": baris_id,
            "pesan": f"Baris roster ID {baris_id} ({baris.get('nama_tampil')}) dihapus."}


def _ambil_roster(baris_id: int) -> dict[str, Any] | None:
    from . import db
    return db.row_to_dict(db.query_one(
        "SELECT * FROM insentif_roster WHERE id = ?", (baris_id,)))


def _pelaku_geser_orang_insentif(arg: Mapping[str, Any]) -> dict[str, Any]:
    try:
        baris_id = int(arg.get("baris_id") or 0)
        arah = int(arg.get("arah") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "pesan": "baris_id dan arah harus angka."}
    if arah not in (-1, 1):
        return {"ok": False, "pesan": "«arah» harus -1 (naik) atau +1 (turun)."}
    if _ambil_roster(baris_id) is None:
        return {"ok": False, "pesan": f"Baris roster ID {baris_id} tidak ditemukan."}
    insentif.geser_roster(baris_id, arah)
    services.log_audit("ollama", "admin", "insentif_roster_geser", "insentif_roster",
                       str(baris_id), f"arah {arah}")
    return {"ok": True, "baris_id": baris_id, "arah": arah,
            "pesan": f"Baris roster ID {baris_id} digeser "
                     f"{'naik' if arah < 0 else 'turun'}."}


def _pelaku_tambah_libur(arg: Mapping[str, Any]) -> dict[str, Any]:
    tanggal = str(arg.get("tanggal") or "").strip()
    nama = str(arg.get("nama") or "").strip()
    if not tanggal or not nama:
        return {"ok": False, "pesan": "tanggal dan nama libur wajib diisi."}
    jenis = str(arg.get("jenis") or "kustom").strip()
    if jenis not in ("nasional", "cuti", "kustom"):
        jenis = "kustom"
    # Penjaga nilai: libur nasional/cuti bawaan tidak perlu dicatat ulang —
    # tolak duplikat, laporkan bawaan yang sudah ada.
    if tanggal in insentif.LIBUR_BAWAAN:
        nama_bawaan, jenis_bawaan = insentif.LIBUR_BAWAAN[tanggal]
        return {"ok": False,
                "pesan": (f"Tanggal {tanggal} sudah ada sebagai libur "
                          f"{jenis_bawaan} bawaan ({nama_bawaan}) — tidak perlu "
                          f"dicatat ulang.")}
    try:
        insentif.simpan_libur(tanggal, nama, jenis)
    except ValueError as galat:
        return {"ok": False, "pesan": f"Tanggal tidak sah: {galat}"}
    services.log_audit("ollama", "admin", "insentif_libur_simpan", "insentif_libur",
                       tanggal, f"{nama} ({jenis})")
    return {"ok": True, "tanggal": tanggal, "nama": nama, "jenis": jenis,
            "pesan": f"Tanggal {tanggal} ({nama}) disimpan sebagai libur {jenis}."}


def _pelaku_hapus_libur(arg: Mapping[str, Any]) -> dict[str, Any]:
    tanggal = str(arg.get("tanggal") or "").strip()
    if not tanggal:
        return {"ok": False, "pesan": "tanggal wajib diisi."}
    nama = ""
    if tanggal[:4].isdigit():
        for baris in insentif.daftar_libur_tahun(int(tanggal[:4])):
            if str(baris.get("tanggal") or "") == tanggal:
                nama = str(baris.get("nama") or "")
                break
    insentif.hapus_libur(tanggal)
    services.log_audit("ollama", "admin", "insentif_libur_hapus", "insentif_libur",
                       tanggal, nama)
    return {"ok": True, "tanggal": tanggal,
            "pesan": f"Tanggal {tanggal} ({nama or 'libur'}) dihapus."}


def _pelaku_ubah_jabatan_insentif(arg: Mapping[str, Any]) -> dict[str, Any]:
    try:
        pegawai_id = int(arg.get("pegawai_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "pesan": "pegawai_id harus angka."}
    baris = gtk.get_pegawai(pegawai_id)
    if baris is None:
        return {"ok": False, "pesan": f"Pegawai GTK ID {pegawai_id} tidak ditemukan."}
    jabatan = str(arg.get("jabatan") or "").strip()
    if jabatan and jabatan not in JABATAN_INSENTIF:
        return {"ok": False,
                "pesan": f"Jabatan «{jabatan}» tidak dikenal. Pilih: {', '.join(JABATAN_INSENTIF)}."}
    profil = insentif.profil_untuk_gtk(pegawai_id)
    insentif.db.execute(
        "UPDATE insentif_profil SET jabatan = ?, diubah = datetime('now','localtime') "
        "WHERE id = ?", (jabatan or None, profil["id"]))
    services.log_audit("ollama", "admin", "gtk_jabatan_insentif", "gtk_pegawai",
                       str(pegawai_id),
                       f"{baris['nama']}: jabatan insentif → «{jabatan or 'otomatis'}»")
    return {"ok": True, "pegawai_id": pegawai_id, "jabatan": jabatan or "otomatis",
            "pesan": f"Jabatan insentif «{baris['nama']}» disimpan "
                     f"({jabatan or 'otomatis'})."}


_PELAKU: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "lihat_status_bot": lambda _arg: _pelaku_lihat_status_bot(),
    "lihat_status_insentif": lambda _arg: _pelaku_lihat_status_insentif(),
    "lihat_status_spj": lambda _arg: _pelaku_lihat_status_spj(),
    "baca_hasil_bot": lambda _arg: _pelaku_baca_hasil_bot(),
    "lihat_daftar_siswa": _pelaku_lihat_daftar_siswa,
    "lihat_jumlah_siswa": _pelaku_lihat_jumlah_siswa,
    "lihat_siswa": _pelaku_lihat_siswa,
    "lihat_daftar_gtk": _pelaku_lihat_daftar_gtk,
    "lihat_antrean_persetujuan": _pelaku_lihat_antrean_persetujuan,
    "lihat_ekskul": _pelaku_lihat_ekskul,
    "lihat_status_tangcer": _pelaku_lihat_status_tangcer,
    "lihat_pengaturan": lambda _arg: _pelaku_lihat_pengaturan(),
    "jalankan_bot_dapodik": _pelaku_jalankan_bot,
    "hentikan_bot_dapodik": lambda _arg: _pelaku_hentikan_bot(),
    "unggah_berkas_spj": _pelaku_unggah_berkas_spj,
    "buat_spj": _pelaku_buat_spj,
    "buat_spj_tangcer": _pelaku_buat_spj_tangcer,
    "putuskan_pengajuan": _pelaku_putuskan_pengajuan,
    "buat_periode_insentif": _pelaku_buat_periode_insentif,
    "hapus_periode_insentif": _pelaku_hapus_periode_insentif,
    "tambah_orang_insentif": _pelaku_tambah_orang_insentif,
    "ubah_orang_insentif": _pelaku_ubah_orang_insentif,
    "hapus_orang_insentif": _pelaku_hapus_orang_insentif,
    "geser_orang_insentif": _pelaku_geser_orang_insentif,
    "tambah_libur": _pelaku_tambah_libur,
    "hapus_libur": _pelaku_hapus_libur,
    "ubah_jabatan_insentif": _pelaku_ubah_jabatan_insentif,
}


def _catat_alat(nama: str, argumen: Mapping[str, Any], hasil: Mapping[str, Any]) -> None:
    """Log setiap pemanggilan alat ke berkas ``data/ollama/alat.log``."""
    try:
        folder = config.DATA_DIR / "ollama"
        folder.mkdir(parents=True, exist_ok=True)
        baris = {"waktu": datetime.now().isoformat(timespec="seconds"), "alat": nama,
                 "argumen": dict(argumen), "ok": bool(hasil.get("ok")),
                 "pesan": str(hasil.get("pesan") or "")[:200]}
        with (folder / "alat.log").open("a", encoding="utf-8") as gagang:
            gagang.write(json.dumps(baris, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("Log alat Ollama tidak dapat ditulis", exc_info=True)
    if hasil.get("ok"):
        services.log_audit("ollama", "admin", "ollama_alat", "ollama", nama,
                           str(hasil.get("pesan") or "ok"))


def jalankan_alat(nama: str, argumen: Mapping[str, Any],
                  cfg: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Jalankan satu alat dengan pengaman (nama terdaftar + izin eksekusi)."""
    setting = cfg if cfg is not None else pengaturan()
    if nama not in _PELAKU:
        return {"ok": False, "pesan": f"Alat «{nama}» tidak dikenal."}
    if nama in _ALAT_AKSI and setting.get(KUNCI_EKSEKUSI) != "1":
        return {"ok": False,
                "pesan": ("Mode saran saja: Ollama belum diberi hak menjalankan aksi. "
                          "Aktifkan «Eksekusi otomatis» di halaman Ollama, atau lakukan "
                          "sendiri lewat halaman web bodap.")}
    try:
        hasil = _PELAKU[nama](argumen)
    except Exception as galat:  # noqa: BLE001 - kesalahan alat dilaporkan ke model
        log.exception("Alat Ollama «%s» gagal", nama)
        hasil = {"ok": False, "pesan": f"Alat «{nama}» gagal dijalankan: {galat}"}
    _catat_alat(nama, argumen, hasil)
    return hasil


def daftar_alat() -> list[dict[str, str]]:
    """Daftar alat (untuk ditampilkan di halaman Ollama)."""
    return [{"nama": f["function"]["name"],
             "deskripsi": f["function"]["description"]}
            for f in _ALAT_SKEMA]


# --------------------------------------------------------------------------- #
# Siklus percakapan: pesan → Ollama → alat → jawaban
# --------------------------------------------------------------------------- #
def _chat(url: str, model: str, kunci: str, pesans: list[dict[str, Any]],
          detik: int = DETIK_PERMINTAAN,
          alat: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    tubuh = {"model": model, "messages": pesans,
             "tools": alat if alat is not None else _ALAT_SKEMA,
             "stream": False, "keep_alive": "30m",
             # Model 7B/14B di CPU: suhu nol agar pemanggilan alat stabil dan
             # tidak degeneratif (tidak mengulang/mengarang). num_ctx dibatasi
             # agar konteks/KV cache tidak membesar tak terkendali.
             "options": {"temperature": 0, "num_ctx": 8192}}
    return _permintaan(f"{url}/api/chat", "POST", tubuh, kunci=kunci, detik=detik)


def _objek_json_dari_teks(isi: str) -> list[dict[str, Any]]:
    """Kumpulkan semua objek JSON (kurung seimbang, termasuk bersarang)."""
    objek: list[dict[str, Any]] = []
    i = 0
    n = len(isi)
    while i < n:
        if isi[i] != "{":
            i += 1
            continue
        tingkat = 0
        dalam_string = False
        escape = False
        akhir = -1
        for j in range(i, n):
            kar = isi[j]
            if dalam_string:
                if escape:
                    escape = False
                elif kar == "\\":
                    escape = True
                elif kar == '"':
                    dalam_string = False
                continue
            if kar == '"':
                dalam_string = True
            elif kar == "{":
                tingkat += 1
            elif kar == "}":
                tingkat -= 1
                if tingkat == 0:
                    akhir = j
                    break
        if akhir < 0:
            break
        potongan = isi[i:akhir + 1]
        try:
            beban = json.loads(potongan)
        except ValueError:
            beban = None
        if isinstance(beban, dict):
            objek.append(beban)
        i = akhir + 1
    return objek


def _panggilan_dari_teks(isi: str) -> tuple[str, dict[str, Any]] | None:
    """Tangkap model yang menulis pemanggilan alat sebagai JSON di teks.

    Model 7B kadang menulis ``{"name": "lihat_...", "arguments": {...}}`` di
    dalam pesan alih-alih mengeluarkan ``tool_calls``. Kalau ditemukan, kita
    menjalankannya — jangan membiarkannya jadi jawaban akhir yang mengarang.
    Hanya bentuk pemanggilan (nama alat terdaftar + argumen) yang ditangkap,
    bukan hasil alat fiktif.
    """
    if not isi:
        return None
    for beban in _objek_json_dari_teks(isi):
        nama = beban.get("name") or beban.get("alat") or beban.get("tool")
        if not isinstance(nama, str) or nama not in _PELAKU:
            continue
        argumen = beban.get("arguments", beban.get("argumen", {}))
        if isinstance(argumen, str):
            try:
                argumen = json.loads(argumen)
            except ValueError:
                argumen = {}
        if not isinstance(argumen, dict):
            argumen = {}
        return nama, argumen
    return None


def _pertanyaan_hitung_siswa(pesan: str) -> bool:
    """Tangkap pertanyaan yang jelas meminta jumlah siswa (hitung, bukan daftar).

    Penjaga nilai: untuk pertanyaan seperti ini kita panggilkan
    «lihat_jumlah_siswa» langsung di server agar model tidak salah pilih alat
    (mis. melaporkan status insentif). Hanya dipicu bila ada kata «siswa» +
    kata hitung; pertanyaan «daftar siswa» tidak terpicu.
    """
    teks = (pesan or "").lower()
    if "siswa" not in teks:
        return False
    hitung = ("jumlah", "berapa", "banyak", "total", "hitung",
              "sebanyak", "kuantitas")
    if not any(kata in teks for kata in hitung):
        return False
    # Jangan salah tangkap «berapa banyak penerima insentif» dsb — harus ada
    # «siswa» (sudah dicek) dan bukan pertanyaan daftar/filter murni.
    if any(kata in teks for kata in ("daftar", "lihat", "rinci", "detail")):
        return False
    return True


def _saringan_hitung_siswa(pesan: str) -> dict[str, str]:
    """Ambil saringan rombel/tingkat dari pertanyaan hitung siswa.

    Mis. «berapa siswa kelas 7A?» → rombel «7A»; «berapa siswa tingkat 8?»
    → tingkat «8». Penjaga nilai memakai ini supaya tidak menjawab total seluruh
    sekolah untuk pertanyaan yang sebenarnya meminta kelompok tertentu.
    """
    teks = (pesan or "").lower()
    saringan: dict[str, str] = {}
    m = re.search(r"(?:kelas|tingkat)\s*[:]?\s*([0-9])", teks)
    if m:
        saringan["tingkat"] = m.group(1)
    m = re.search(r"rombel\s*[:]?\s*([0-9][a-z]?)", teks)
    if m:
        saringan["rombel"] = m.group(1).upper()
    else:
        m = re.search(r"\b([0-9][a-z])\b", teks)
        if m:
            saringan["rombel"] = m.group(1).upper()
    return saringan


#: Pemetaan kata kunci → alat yang relevan. Model kecil (2B/4B) sulit memilih
#: bila 27 alat dikirim sekaligus; kirim hanya alat yang relevan per pesan.
_KELOMPOK: dict[tuple[str, ...], tuple[str, ...]] = {
    ("siswa",): ("lihat_jumlah_siswa", "lihat_daftar_siswa", "lihat_siswa"),
    ("gtk", "guru", "tendik"): ("lihat_daftar_gtk", "ubah_jabatan_insentif"),
    ("bot", "dapodik"): ("lihat_status_bot", "baca_hasil_bot",
                         "jalankan_bot_dapodik", "hentikan_bot_dapodik"),
    ("insentif", "periode", "roster", "libur"): (
        "lihat_status_insentif", "tambah_libur", "hapus_libur",
        "buat_periode_insentif", "tambah_orang_insentif"),
    ("spj",): ("lihat_status_spj", "buat_spj", "buat_spj_tangcer"),
    ("pengajuan", "setuju", "tolak"): ("lihat_antrean_persetujuan",
                                      "putuskan_pengajuan"),
    ("tangcer",): ("lihat_status_tangcer", "buat_spj_tangcer"),
    ("ekskul",): ("lihat_ekskul",),
    ("pengaturan", "profil", "sekolah"): ("lihat_pengaturan",),
}


def _pilih_alat(pesan: str) -> list[dict[str, Any]]:
    """Pilih alat yang relevan dengan pesan — kirim hanya itu ke model kecil."""
    teks = (pesan or "").lower()
    nama: set[str] = set()
    for kata, alat in _KELOMPOK.items():
        if any(k in teks for k in kata):
            nama.update(alat)
    if not nama:
        # Tak terdeteksi: hanya alat baca ringan yang selalu relevan.
        nama = {"lihat_status_bot", "lihat_status_insentif", "lihat_pengaturan"}
    return [a for a in _ALAT_SKEMA if a["function"]["name"] in nama]


def bicara(pesan: str, riwayat: list[dict[str, Any]] | None = None,
           cfg: Mapping[str, str] | None = None,
           sumber: str = "web") -> dict[str, Any]:
    """Satu percakapan lengkap: jawaban akhir + jejak alat yang dipakai.

    ``riwayat`` adalah pesan-pesan sebelumnya (dimiliki jembatan WA / halaman);
    hanya ``BATAS_RIWAYAT`` pesan terakhir yang dikirim supaya konteks tidak
    membengkak.
    """
    setting = cfg if cfg is not None else pengaturan()
    if setting.get(KUNCI_AKTIF) != "1":
        raise OllamaTidakAktif(
            "Ollama belum diaktifkan. Buka halaman «Ollama» di bodap dan aktifkan "
            "dengan alamat serta model yang sudah dipasang.")
    url = (setting.get(KUNCI_URL) or "").strip().rstrip("/")
    model = (setting.get(KUNCI_MODEL) or "").strip()
    if not url or not model:
        raise OllamaGalat("Alamat atau model Ollama belum diisi di pengaturan.")

    sistem = SYSTEM_PROMPT_WA if (sumber or "web") == "wa" else SYSTEM_PROMPT
    pesans: list[dict[str, Any]] = [{"role": "system", "content": sistem}]
    for item in (riwayat or [])[-BATAS_RIWAYAT:]:
        peranan = item.get("role") if isinstance(item, dict) else None
        isi = item.get("content") if isinstance(item, dict) else None
        if peranan in ("user", "assistant") and isi:
            pesans.append({"role": peranan, "content": str(isi)})
    pesans.append({"role": "user", "content": pesan})

    jejak: list[dict[str, Any]] = []
    detik = _detik_pengaturan(setting)
    # Pencatat waktu: total «berpikir» sampai jawaban, dan per panggilan model.
    mulai = time.perf_counter()
    waktu_langkah: list[float] = []

    # Penjaga nilai: pertanyaan hitung siswa yang jelas → panggil alat
    # «lihat_jumlah_siswa» langsung di server, agar model tidak salah pilih
    # alat (mis. melaporkan status insentif). Hasil disuntikkan sebagai hasil
    # alat yang sah; model menjawab dari data ini.
    if _pertanyaan_hitung_siswa(pesan):
        _id_hitung = f"hitung-{len(jejak) + 1}"
        arg_hitung = _saringan_hitung_siswa(pesan)
        hasil_hitung = jalankan_alat("lihat_jumlah_siswa", arg_hitung, setting)
        jejak.append({"alat": "lihat_jumlah_siswa", "argumen": arg_hitung,
                      "hasil": hasil_hitung, "otomatis": True})
        pesans.append({"role": "assistant",
                       "content": "Saya menghitung jumlah siswa terlebih dahulu.",
                       "tool_calls": [{"id": _id_hitung, "type": "function",
                                       "function": {"name": "lihat_jumlah_siswa",
                                                    "arguments": arg_hitung}}]})
        pesans.append({"role": "tool", "tool_call_id": _id_hitung,
                       "content": _potong_hasil(
                           json.dumps(hasil_hitung, ensure_ascii=False))})
        pesans.append({"role": "user",
                       "content": ("Hasil alat «lihat_jumlah_siswa» sudah tersimpan. Jawab SEKARANG pertanyaan pengguna berdasarkan angka dari hasil tersebut — sebutkan angka itu dalam jawaban. Jangan meminta data lagi, datanya sudah ada. Jika pertanyaan meminta kelompok tertentu, panggil alat itu lagi dengan saringan yang diminta.")})

    coba_ulang_meta = False
    _sudah_dipakai: set[tuple[str, str]] = set()
    alat_relevan = _pilih_alat(pesan)
    for _langkah in range(BATAS_LOOP):
        _t0 = time.perf_counter()
        hasil = _chat(url, model, setting.get(KUNCI_KUNCI) or "", pesans,
                      detik=detik, alat=alat_relevan)
        waktu_langkah.append(round(time.perf_counter() - _t0, 2))
        pesan_model = hasil.get("message") or {}
        panggilan = pesan_model.get("tool_calls") or []
        isi_model = str(pesan_model.get("content") or "")
        if not panggilan:
            # Penangkal model 7B yang menulis pemanggilan alat sebagai JSON di
            # teks: jalankan saja, jangan dibiarkan jadi jawaban yang mengarang.
            dari_teks = _panggilan_dari_teks(isi_model)
            if dari_teks:
                panggilan = [{"id": f"panggilan-{len(jejak) + 1}",
                              "type": "function",
                              "function": {"name": dari_teks[0],
                                            "arguments": dari_teks[1]}}]
            else:
                # Penjaga: model kadang mengembalikan pesan meta («saya akan
                # menjawab… mohon berikan hasil alat») alih-alih jawaban, padahal
                # hasil alat sudah ada. Paksa sekali menjawab dari hasil alat.
                if (not coba_ulang_meta and jejak
                        and _tampaknya_pesan_meta(isi_model)):
                    coba_ulang_meta = True
                    pesans.append({"role": "user",
                                   "content": ("Jawab SEKARANG dengan menyebutkan "
                                               "hasil alat yang sudah tersedia. "
                                               "Jangan menulis pesan tentang proses "
                                               "atau meminta data lagi — datanya "
                                               "sudah ada di hasil alat sebelumnya.")})
                    continue
                jawaban = isi_model.strip() or _pesan_kosong(model)
                _selesai = time.perf_counter() - mulai
                return {"jawaban": jawaban, "alat": jejak,
                        "batas": False, "riwayat": pesans,
                        "waktu": round(_selesai, 2), "langkah": len(waktu_langkah),
                        "waktu_teks": _format_detik(_selesai)}
        pesans.append({"role": "assistant",
                       "content": isi_model,
                       "tool_calls": panggilan})
        for panggilan_satu in panggilan:
            fungsi = panggilan_satu.get("function") or {}
            nama = str(fungsi.get("name") or "")
            argumen = fungsi.get("arguments") or {}
            if isinstance(argumen, str):
                try:
                    argumen = json.loads(argumen)
                except ValueError:
                    argumen = {}
            if not isinstance(argumen, dict):
                argumen = {}
            id_panggilan = str(panggilan_satu.get("id") or f"panggilan-{len(jejak) + 1}")
            # Penjaga: panggilan berulang (nama + argumen sama) tidak dijalankan
            # ulang — suruh model menjawab dari hasil sebelumnya.
            _kunci = (nama, json.dumps(argumen, sort_keys=True, ensure_ascii=False))
            if _kunci in _sudah_dipakai:
                hasil_alat = {"ok": False, "pesan": f"Alat «{nama}» dengan argumen ini sudah dijalankan — gunakan hasil sebelumnya, jangan memanggilnya lagi."}
                jejak.append({"alat": nama, "argumen": argumen, "hasil": hasil_alat,
                              "ulang": True})
                pesans.append({"role": "tool", "tool_call_id": id_panggilan,
                               "content": json.dumps(hasil_alat, ensure_ascii=False)})
                continue
            _sudah_dipakai.add(_kunci)
            # Penjaga: alat hapus/ubah — ID harus pernah muncul di hasil lihat_*.
            if not _id_terlihat(nama, argumen, jejak):
                hasil_alat = {"ok": False, "pesan": f"Sebelum «{nama}», ambil ID dulu dari alat lihat_... — pastikan ID benar, jangan mengarang."}
                jejak.append({"alat": nama, "argumen": argumen, "hasil": hasil_alat,
                              "id_tidak_terlihat": True})
                pesans.append({"role": "tool", "tool_call_id": id_panggilan,
                               "content": json.dumps(hasil_alat, ensure_ascii=False)})
                continue
            hasil_alat = jalankan_alat(nama, argumen, setting)
            jejak.append({"alat": nama, "argumen": argumen, "hasil": hasil_alat})
            pesans.append({"role": "tool", "tool_call_id": id_panggilan,
                           "content": _potong_hasil(
                               json.dumps(hasil_alat, ensure_ascii=False))})
    _selesai = time.perf_counter() - mulai
    return {"jawaban": ("Ollama masih meminta alat setelah "
                        f"{BATAS_LOOP} langkah — percakapan dihentikan untuk "
                        "mencegah putaran tak berujung."),
            "alat": jejak, "batas": True, "riwayat": pesans,
            "waktu": round(_selesai, 2), "langkah": len(waktu_langkah),
            "waktu_teks": _format_detik(_selesai)}


def status_cepat() -> dict[str, Any]:
    """Status ringkas untuk halaman: aktif, model, alamat, laporan uji terakhir."""
    setting = pengaturan()
    return {
        "aktif": setting.get(KUNCI_AKTIF) == "1",
        "url": setting.get(KUNCI_URL) or "",
        "model": setting.get(KUNCI_MODEL) or "",
        "eksekusi": setting.get(KUNCI_EKSEKUSI) == "1",
        "uji": baca_laporan_uji(),
    }
