#!/usr/bin/env python3
"""Integrasi **Ollama**: «otak» percakapan yang mengoperasikan bodap lewat alat.

Latar belakang (permintaan sekolah, ronde 73): pengguna ingin mengobrol dengan
model Ollama (mis. lewat jembatan WhatsApp) dan menyuruhnya mengoperasikan bodap —
cek status insentif, unggah berkas lalu membuat SPJ, atau menjalankan Bot Dapodik
dan melaporkan hasilnya. Ollama sendiri tidak punya akses DOM atau basis data;
ia hanya boleh **memanggil alat yang sudah didaftarkan** di sini, dan setiap alat
dipetakan ke fungsi bodap yang sudah teruji.

Aturan keamanan (tetap sesuai prinsip sekolah):
- Ollama harus **diaktifkan** dulu di halaman «Ollama».
- Alat aksi (menjalankan bot, mengunggah, membuat SPJ) hanya berjalan bila
  pengaturan «Eksekusi otomatis» aktif; bila tidak, alat mengembalikan saran saja
  sehingga Ollama melaporkan ke pengguna tanpa mengeksekusi apa pun.
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
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import bot_dapodik, config, insentif, insentif_impor, insentif_pdf, services

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Pengaturan
# --------------------------------------------------------------------------- #
KUNCI_AKTIF = "ollama_aktif"
KUNCI_URL = "ollama_url"
KUNCI_MODEL = "ollama_model"
KUNCI_KUNCI = "ollama_kunci"
KUNCI_EKSEKUSI = "ollama_eksekusi"
KUNCI_UJI = "ollama_uji_terakhir"

OLLAMA_KEYS: tuple[str, ...] = (
    KUNCI_AKTIF, KUNCI_URL, KUNCI_MODEL, KUNCI_KUNCI, KUNCI_EKSEKUSI,
)

OLLAMA_BAWAAN: dict[str, str] = {
    KUNCI_AKTIF: "0",
    KUNCI_URL: "http://localhost:11434",
    KUNCI_MODEL: "qwen2.5:14b-instruct",
    KUNCI_KUNCI: "",
    KUNCI_EKSEKUSI: "0",
}

#: Batas iterasi pemanggilan alat dalam satu percakapan (anti «model berputar»).
BATAS_LOOP = 6
#: Batas riwayat percakapan yang dikirim ke model (yang tertua dipotong).
BATAS_RIWAYAT = 20
#: Batas detik per permintaan HTTP ke Ollama (14B di CPU butuh waktu).
DETIK_PERMINTAAN = 180


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
        raise OllamaGalat(f"Tidak dapat menghubungi Ollama di {url}. "
                          f"Periksa apakah Ollama berjalan dan alamatnya benar "
                          f"({galat.reason}).") from galat
    except OSError as galat:
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
        hasil = _permintaan(f"{url}/api/tags", kunci=(setting.get(KUNCI_KUNCI) or ""))
    except OllamaGalat as galat:
        return {"ok": False, "model": [], "pesan": str(galat)}
    model = [str(m.get("name") or "") for m in (hasil.get("models") or []) if m.get("name")]
    return {"ok": True, "model": model,
            "pesan": f"Ollama terhubung — {len(model)} model tersedia."}


# --------------------------------------------------------------------------- #
# Alat (tool) — skema untuk model + pelaku untuk bodap
# --------------------------------------------------------------------------- #
_ALAT_SKEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lihat_status_bot",
            "description": ("Ringkasan keadaan Bot Dapodik: sedang berjalan atau "
                            "menganggur, kemajuan pekerjaan terakhir (berhasil/gagal/"
                            "dilewati), siswa yang sedang diproses, dan baris-baris "
                            "catatan terbaru."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lihat_status_insentif",
            "description": ("Ringkasan modul insentif: periode insentif yang ada, "
                            "status impor rekening, dan status draf cetak SPJ "
                            "(berkas rekening & berkas absensi e-gov)."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lihat_status_spj",
            "description": ("Status pembuatan SPJ dari berkas: apakah berkas rekening "
                            "dan berkas absensi e-gov sudah diunggah, serta ringkasan "
                            "pratinjau (bulan, jumlah penerima, total dana, tanggal DL)."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jalankan_bot_dapodik",
            "description": ("Memulai Bot Dapodik untuk antrean siswa. Kosongkan "
                            "«rombel» untuk semua rombel; «limit» membatasi jumlah "
                            "siswa; «nisn_manual» untuk NISN tertentu (satu per "
                            "baris). Kembalikan nomor pekerjaan dan jumlah siswa."),
            "parameters": {
                "type": "object",
                "properties": {
                    "rombel": {"type": "string", "description": "Nama rombel (kosong = semua)."},
                    "limit": {"type": "integer", "description": "Batas jumlah siswa (0 = semua)."},
                    "nisn_manual": {"type": "string", "description": "NISN manual, satu per baris."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hentikan_bot_dapodik",
            "description": "Menghentikan Bot Dapodik yang sedang berjalan.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "baca_hasil_bot",
            "description": ("Hasil pekerjaan Bot Dapodik terakhir: hitungan "
                            "berhasil/gagal/dilewati, daftar siswa beserta status "
                            "dan pesan terbaru, serta baris-baris catatan terakhir."),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unggah_berkas_spj",
            "description": ("Mengunggah berkas rekening insentif (.xls/.xlsx) dan "
                            "berkas absensi e-gov (.xlsx/.xls/.xlsb/.ods) untuk "
                            "pembuatan SPJ. Isi berkas dikirim sebagai base64."),
            "parameters": {
                "type": "object",
                "properties": {
                    "nama_berkas": {"type": "string", "description": "Nama berkas rekening."},
                    "isi_berkas": {"type": "string", "description": "Isi berkas rekening (base64)."},
                    "nama_absensi": {"type": "string", "description": "Nama berkas absensi e-gov."},
                    "isi_absensi": {"type": "string", "description": "Isi berkas absensi (base64)."},
                },
                "required": ["nama_berkas", "isi_berkas", "nama_absensi", "isi_absensi"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buat_spj",
            "description": ("Membuat dokumen SPJ dari draf berkas yang sudah "
                            "diunggah. «dokumen»: spj (gabungan), pns, atau pppk; "
                            "«tgl»: tanggal 1–31 (kosong = akhir bulan). Kembalikan "
                            "nama berkas PDF, jalur penyimpanan, dan ukurannya."),
            "parameters": {
                "type": "object",
                "properties": {
                    "dokumen": {"type": "string", "description": "spj, pns, atau pppk."},
                    "tgl": {"type": "integer", "description": "Tanggal 1–31 (kosong = akhir bulan)."},
                },
                "required": [],
            },
        },
    },
]

#: Alat yang mengeksekusi aksi nyata (dibatasi oleh pengaturan eksekusi).
_ALAT_AKSI = frozenset({"jalankan_bot_dapodik", "hentikan_bot_dapodik",
                        "unggah_berkas_spj", "buat_spj"})

SYSTEM_PROMPT = (
    "Anda adalah assistant yang mengoperasikan aplikasi sekolah «SM» (bodap) di "
    "komputer pengguna. Anda hanya dapat menggunakan alat yang tersedia — jangan "
    "mengarang hasil. Aturan:\n"
    "- Beri jawaban dalam bahasa Indonesia, ringkas dan jelas.\n"
    "- Untuk menanyakan keadaan (status), panggil alatnya lalu sampaikan isinya "
    "apa adanya.\n"
    "- Untuk pekerjaan (menjalankan bot, mengunggah berkas, membuat SPJ), panggil "
    "alatnya dan laporkan hasil yang benar-benar dikembalikan alat. Jangan "
    "menyatakan berhasil bila alat melaporkan kegagalan.\n"
    "- Bila alat mengembalikan pesan kesalahan atau saran, sampaikan kepada "
    "pengguna apa adanya bersama cara mengatasinya.\n"
    "- Jangan pernah meminta informasi sensitif (kata sandi, kunci API).\n"
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


def _ringkas_periode(batas: int = 8) -> list[dict[str, Any]]:
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
        return {"ok": False, "ada_berkas": True, "pesan": f"Berkas tersimpan tapi tak terbaca: {galat}"}
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


def _pelaku_jalankan_bot(arg: Mapping[str, Any]) -> dict[str, Any]:
    cfg = services.bot_setting()
    siap, keterangan = services.bot_siap_pakai()
    if not siap:
        return {"ok": False, "pesan": keterangan}
    rombel = str(arg.get("rombel") or "").strip()[:20]
    try:
        limit = max(0, min(2000, int(arg.get("limit") or 0)))
    except (TypeError, ValueError):
        limit = 0
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
    try:
        tgl = int(arg.get("tgl") or 0)
    except (TypeError, ValueError):
        tgl = 0
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


_PELAKU: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "lihat_status_bot": lambda _arg: _pelaku_lihat_status_bot(),
    "lihat_status_insentif": lambda _arg: _pelaku_lihat_status_insentif(),
    "lihat_status_spj": lambda _arg: _pelaku_lihat_status_spj(),
    "jalankan_bot_dapodik": _pelaku_jalankan_bot,
    "hentikan_bot_dapodik": lambda _arg: _pelaku_hentikan_bot(),
    "baca_hasil_bot": lambda _arg: _pelaku_baca_hasil_bot(),
    "unggah_berkas_spj": _pelaku_unggah_berkas_spj,
    "buat_spj": _pelaku_buat_spj,
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
def _chat(url: str, model: str, kunci: str, pesans: list[dict[str, Any]]) -> dict[str, Any]:
    tubuh = {"model": model, "messages": pesans, "tools": _ALAT_SKEMA,
             "stream": False}
    return _permintaan(f"{url}/api/chat", "POST", tubuh, kunci=kunci)


def bicara(pesan: str, riwayat: list[dict[str, Any]] | None = None,
           cfg: Mapping[str, str] | None = None) -> dict[str, Any]:
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

    pesans: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (riwayat or [])[-BATAS_RIWAYAT:]:
        peranan = item.get("role") if isinstance(item, dict) else None
        isi = item.get("content") if isinstance(item, dict) else None
        if peranan in ("user", "assistant") and isi:
            pesans.append({"role": peranan, "content": str(isi)})
    pesans.append({"role": "user", "content": pesan})

    jejak: list[dict[str, Any]] = []
    for _langkah in range(BATAS_LOOP):
        hasil = _chat(url, model, setting.get(KUNCI_KUNCI) or "", pesans)
        pesan_model = hasil.get("message") or {}
        panggilan = pesan_model.get("tool_calls") or []
        if not panggilan:
            return {"jawaban": str(pesan_model.get("content") or ""), "alat": jejak,
                    "batas": False, "riwayat": pesans}
        pesans.append({"role": "assistant",
                       "content": str(pesan_model.get("content") or ""),
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
            hasil_alat = jalankan_alat(nama, argumen, setting)
            jejak.append({"alat": nama, "argumen": argumen, "hasil": hasil_alat})
            pesans.append({"role": "tool", "tool_call_id": id_panggilan,
                           "content": json.dumps(hasil_alat, ensure_ascii=False)})
    return {"jawaban": ("Ollama masih meminta alat setelah "
                        f"{BATAS_LOOP} langkah — percakapan dihentikan untuk "
                        "mencegah putaran tak berujung."),
            "alat": jejak, "batas": True, "riwayat": pesans}


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
