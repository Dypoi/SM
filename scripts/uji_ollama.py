#!/usr/bin/env python3
"""Uji menyeluruh integrasi **Ollama** — aktivasi, alat, obrolan, titik akhir HTTP.

Yang dibuktikan:

1. pengaturan: bawaan, simpan, baca kembali, aktivasi wajib sebelum obrolan;
2. koneksi: daftar model dari Ollama (server palsu), galat ramah bila mati;
3. siklus obrolan: model meminta alat → alat dijalankan → jawaban akhir;
4. riwayat diperpendek (hanya 20 pesan terakhir + sistem);
5. pengaman: eksekusi mati → alat aksi hanya memberi saran; alat tak dikenal;
6. alat bodap: lihat status bot/insentif/SPJ, unggah berkas SPJ, buat SPJ (PDF);
7. batas putaran alat (model berputar → dihentikan);
8. titik akhir HTTP: halaman, status.json, chat dengan kunci API, tanpa kunci.

Ollama palsu: server HTTP lokal yang menjawab ``/api/tags`` & ``/api/chat``
sesuai skenario — tidak perlu Ollama sungguhan di komputer.

Jalankan::

    .venv/bin/python scripts/uji_ollama.py
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AKAR))

# --- Database sementara: HARUS diatur sebelum mengimpor modul app ---
_SEMENTARA = Path(tempfile.mkdtemp(prefix="sm-uji-ollama-"))
os.environ["SM_DATA_DIR"] = str(_SEMENTARA / "data")
os.environ["SM_DB_PATH"] = str(_SEMENTARA / "uji.sqlite3")
os.environ["SM_AUTO_SEED"] = "0"

from app import bot_dapodik, insentif_impor, migrations, ollama, services  # noqa: E402

migrations.init_database()

HASIL: list[tuple[str, bool, str]] = []
SKENARIO: list[str] = []
_SKENARIO_KINI = ""


def skenario(nama: str) -> None:
    global _SKENARIO_KINI
    _SKENARIO_KINI = nama
    SKENARIO.append(nama)
    print(f"\n=== {nama} ===", flush=True)


def cek(nama: str, syarat: bool, keterangan: str = "") -> None:
    HASIL.append((f"{_SKENARIO_KINI} → {nama}", bool(syarat), keterangan))
    tanda = "  OK  " if syarat else " GAGAL"
    print(f"[{tanda}] {nama}" + ("" if syarat or not keterangan else f" — {keterangan}"),
          flush=True)


# --------------------------------------------------------------------------- #
# Ollama palsu
# --------------------------------------------------------------------------- #
class OllamaPalsu(ThreadingHTTPServer):
    """Server Ollama tiruan: skenario jawaban bisa diatur sebelum tiap uji."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _PenolakOllama)
        self.model = ["qwen2.5:14b-instruct", "llama3.1:8b"]
        self.chat_skrip: list[dict] = []
        self.chat_terakhir: dict = {}

    @property
    def alamat(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _PenolakOllama(BaseHTTPRequestHandler):
    def log_message(self, *_args):  # jangan berisik
        pass

    def _kirim(self, tubuh: dict, kode: int = 200) -> None:
        mentah = json.dumps(tubuh).encode("utf-8")
        self.send_response(kode)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(mentah)))
        self.end_headers()
        self.wfile.write(mentah)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/tags"):
            self._kirim({"models": [{"name": n} for n in self.server.model]})  # type: ignore[attr-defined]
        else:
            self._kirim({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        panjang = int(self.headers.get("Content-Length") or 0)
        tubuh = json.loads(self.rfile.read(panjang) or b"{}")
        self.server.chat_terakhir = tubuh  # type: ignore[attr-defined]
        skrip = self.server.chat_skrip or []  # type: ignore[attr-defined]
        if skrip:
            self._kirim(skrip.pop(0))
        else:
            self._kirim({"message": {"role": "assistant",
                                     "content": "(tanpa skenario)"}, "done": True})


def chat_alat(nama: str, argumen: dict | None = None) -> dict:
    return {"message": {"role": "assistant", "content": None,
                        "tool_calls": [{"id": "panggilan-1",
                                        "function": {"name": nama,
                                                     "arguments": argumen or {}}}]},
            "done": True}


def chat_bicara(teks: str) -> dict:
    return {"message": {"role": "assistant", "content": teks, "tool_calls": []},
            "done": True}


# --------------------------------------------------------------------------- #
# Persiapan
# --------------------------------------------------------------------------- #
OLLAMA = OllamaPalsu()
threading.Thread(target=OLLAMA.serve_forever, daemon=True).start()

CFG_AKTIF = {ollama.KUNCI_AKTIF: "1", ollama.KUNCI_URL: OLLAMA.alamat,
             ollama.KUNCI_MODEL: "qwen2.5:14b-instruct", ollama.KUNCI_KUNCI: "",
             ollama.KUNCI_EKSEKUSI: "1"}
CFG_SARAN = dict(CFG_AKTIF, **{ollama.KUNCI_EKSEKUSI: "0"})


def _berkas_rekening_b64() -> str:
    from openpyxl import Workbook

    buku = Workbook()
    lembar = buku.active
    lembar["A1"] = "BULAN : OKTOBER TAHUN ANGGARAN 2025"
    header = ["NAMA", "NO REKENING", "NIP", "NPWP", "NIK", "JABATAN",
              "GOL", "JUMLAH YANG DI BAYAR", "PPH"]
    for kolom, nama in enumerate(header, start=1):
        lembar.cell(row=3, column=kolom, value=nama)
    baris = [
        ["Andi Wijaya", "1234567890", "198701011987010001", "00.000.000.0-00.000",
         "3201010101000001", "Guru", "III", "3350000", "167500"],
        ["Budi Santoso", "0987654321", "199002021990020002", "00.000.000.1-00.000",
         "3201020202000002", "Guru", "IV", "4050000", "202500"],
        ["Cahya Permana", "1122334455", "199503031995030003", "00.000.000.2-00.000",
         "3201030303000003", "Guru", "V", "5000000", "0"],
    ]
    for i, baris_data in enumerate(baris, start=4):
        for kolom, nilai in enumerate(baris_data, start=1):
            lembar.cell(row=i, column=kolom, value=nilai)
    pipa = io.BytesIO()
    buku.save(pipa)
    return base64.b64encode(pipa.getvalue()).decode("ascii")


BERKAS_EGov = (AKAR / "daftar_hadir_bulanan_2025_10_UPT_Sekolah_Menengah_"
               "Pertama_Negeri_2_Tangerang.xlsx")


def _berkas_egov_b64() -> str:
    return base64.b64encode(BERKAS_EGov.read_bytes()).decode("ascii")


# --------------------------------------------------------------------------- #
# 1. Pengaturan
# --------------------------------------------------------------------------- #
skenario("1. Pengaturan & aktivasi")

bawaan = ollama.pengaturan()
cek("bawaaan lima kunci lengkap",
    set(bawaan) == set(ollama.OLLAMA_KEYS) and bawaan[ollama.KUNCI_AKTIF] == "0",
    str(bawaan))
cek("alamat bawaan localhost:11434",
    bawaan[ollama.KUNCI_URL] == "http://localhost:11434", bawaan[ollama.KUNCI_URL])
cek("model bawaan qwen2.5:14b-instruct",
    bawaan[ollama.KUNCI_MODEL] == "qwen2.5:14b-instruct", bawaan[ollama.KUNCI_MODEL])

berubah = ollama.simpan_pengaturan(CFG_AKTIF)
cek("simpan mengubah 5 kunci", len(berubah) == 5, str(berubah))
setelah = ollama.pengaturan()
cek("baca kembali sama", setelah[ollama.KUNCI_URL] == OLLAMA.alamat
    and setelah[ollama.KUNCI_MODEL] == "qwen2.5:14b-instruct"
    and setelah[ollama.KUNCI_AKTIF] == "1", str(setelah))

# --------------------------------------------------------------------------- #
# 2. Koneksi
# --------------------------------------------------------------------------- #
skenario("2. Uji koneksi Ollama")

laporan = ollama.cek_koneksi(CFG_AKTIF)
cek("koneksi OK", laporan.get("ok") is True, str(laporan.get("pesan")))
cek("daftar model ada qwen2.5:14b-instruct",
    "qwen2.5:14b-instruct" in (laporan.get("model") or []), str(laporan.get("model")))

laporan_mati = ollama.cek_koneksi({ollama.KUNCI_URL: "http://127.0.0.1:1",
                                   ollama.KUNCI_KUNCI: ""})
cek("alamat mati → ok False + pesan ramah",
    laporan_mati.get("ok") is False and "Tidak dapat menghubungi" in
    (laporan_mati.get("pesan") or ""), str(laporan_mati.get("pesan")))

ollama.simpan_laporan_uji(laporan)
cek("laporan uji tersimpan & terbaca",
    ollama.baca_laporan_uji().get("ok") is True, str(ollama.baca_laporan_uji()))

# --------------------------------------------------------------------------- #
# 3. Bicara: model meminta alat → alat dijalankan → jawaban
# --------------------------------------------------------------------------- #
skenario("3. Siklus obrolan (alat dijalankan)")

ollama.simpan_pengaturan({ollama.KUNCI_AKTIF: "0"})
try:
    ollama.bicara("lihat status bot")
    cek("belum aktif → OllamaTidakAktif", False, "tidak mengutip galat")
except ollama.OllamaTidakAktif as galat:
    cek("belum aktif → OllamaTidakAktif", True, str(galat))
ollama.simpan_pengaturan({ollama.KUNCI_AKTIF: "1"})

OLLAMA.chat_skrip = [chat_alat("lihat_status_bot"),
                     chat_bicara("Bot Dapodik sedang menganggur, tidak ada pekerjaan.")]
hasil = ollama.bicara("lihat status bot", cfg=CFG_AKTIF)
cek("jawaban akhir dari model", hasil.get("jawaban") ==
    "Bot Dapodik sedang menganggur, tidak ada pekerjaan.", str(hasil.get("jawaban")))
cek("jejak alat 1 pemanggilan", len(hasil.get("alat") or []) == 1
    and hasil["alat"][0]["alat"] == "lihat_status_bot",
    str([a.get("alat") for a in hasil.get("alat") or []]))
cek("alat dijalankan & ok", (hasil.get("alat") or [{}])[0].get("hasil", {}).get("ok") is True,
    str((hasil.get("alat") or [{}])[0].get("hasil")))
cek("tidak ada batas putaran", hasil.get("batas") is False)
cek("riwayat dikembalikan (sistem + user + assistant-alat + tool)",
    isinstance(hasil.get("riwayat"), list)
    and len(hasil["riwayat"]) == 4
    and hasil["riwayat"][0]["role"] == "system"
    and hasil["riwayat"][-1]["role"] == "tool",
    str(len(hasil.get("riwayat") or [])))

# --------------------------------------------------------------------------- #
# 4. Riwayat diperpendek
# --------------------------------------------------------------------------- #
skenario("4. Riwayat diperpendek")

riwayat = [{"role": "user", "content": f"pesan {i}"} for i in range(30)]
OLLAMA.chat_skrip = [chat_bicara("sudah")]
hasil = ollama.bicara("pesan terbaru", riwayat=riwayat, cfg=CFG_AKTIF)
cek("hanya 20 riwayat terakhir + sistem + pesan baru",
    len(hasil.get("riwayat") or []) == ollama.BATAS_RIWAYAT + 2
    and hasil["riwayat"][1]["content"] == "pesan 10",
    f"{len(hasil.get('riwayat') or [])} pesan")

# --------------------------------------------------------------------------- #
# 5. Pengaman
# --------------------------------------------------------------------------- #
skenario("5. Pengaman alat")

hasil_alat = ollama.jalankan_alat("jalankan_bot_dapodik", {}, CFG_SARAN)
cek("eksekusi mati → alat aksi hanya saran",
    hasil_alat.get("ok") is False and "Mode saran" in (hasil_alat.get("pesan") or ""),
    str(hasil_alat))
hasil_alat = ollama.jalankan_alat("alat_tak_ada", {}, CFG_AKTIF)
cek("alat tak dikenal ditolak",
    hasil_alat.get("ok") is False and "tidak dikenal" in (hasil_alat.get("pesan") or ""),
    str(hasil_alat))
cek("daftar alat 8 nama",
    {a["nama"] for a in ollama.daftar_alat()} == set(ollama._PELAKU),
    str(sorted(ollama._PELAKU)))

# --------------------------------------------------------------------------- #
# 6. Alat bodap: status
# --------------------------------------------------------------------------- #
skenario("6. Alat status (bot / insentif / SPJ)")

status_bot = ollama.jalankan_alat("lihat_status_bot", {}, CFG_AKTIF)
cek("status bot ok + struktur",
    status_bot.get("ok") is True and "berjalan" in status_bot
    and "hitung" in status_bot, str(status_bot)[:160])

status_insentif = ollama.jalankan_alat("lihat_status_insentif", {}, CFG_AKTIF)
cek("status insentif ok + periode",
    status_insentif.get("ok") is True and isinstance(status_insentif.get("periode"), list),
    str(status_insentif)[:160])

status_spj = ollama.jalankan_alat("lihat_status_spj", {}, CFG_AKTIF)
cek("status SPJ awal: belum ada berkas",
    status_spj.get("ok") is True and status_spj.get("ada_berkas") is False,
    str(status_spj))

# --------------------------------------------------------------------------- #
# 7. Alat bodap: unggah berkas SPJ
# --------------------------------------------------------------------------- #
skenario("7. Alat unggah berkas SPJ")

argumen = {"nama_berkas": "rekening-dummy.xlsx",
           "isi_berkas": _berkas_rekening_b64(),
           "nama_absensi": "absensi-egov.xlsx",
           "isi_absensi": _berkas_egov_b64()}
hasil_unggah = ollama.jalankan_alat("unggah_berkas_spj", argumen, CFG_AKTIF)
cek("unggah kedua berkas ok", hasil_unggah.get("ok") is True, str(hasil_unggah))
cek("draf rekening tersimpan",
    (insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK) or {}).get("nama") == "rekening-dummy.xlsx",
    str(insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK)))
cek("draf absensi e-gov tersimpan",
    bool(insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK_EGov)),
    str(insentif_impor.baca_draf(insentif_impor.KUNCI_CETAK_EGov)))

status_spj = ollama.jalankan_alat("lihat_status_spj", {}, CFG_AKTIF)
cek("status SPJ setelah unggah",
    status_spj.get("ok") is True and status_spj.get("ada_berkas") is True
    and status_spj.get("penerima") == 3 and status_spj.get("bulan") == 10
    and status_spj.get("tahun") == 2025,
    str({k: status_spj.get(k) for k in ("penerima", "bulan", "tahun", "tanggal_dl")}))

hasil_unggah_salah = ollama.jalankan_alat(
    "unggah_berkas_spj",
    {"nama_berkas": "bad.xls", "isi_berkas": base64.b64encode(b"bukan xls").decode(),
     "nama_absensi": "a.xlsx", "isi_absensi": "bukan-base64!!!"},
    CFG_AKTIF)
cek("isi berkas bukan base64 → ditolak ramah",
    hasil_unggah_salah.get("ok") is False and "base64" in
    (hasil_unggah_salah.get("pesan") or ""), str(hasil_unggah_salah))

# --------------------------------------------------------------------------- #
# 8. Alat bodap: buat SPJ
# --------------------------------------------------------------------------- #
skenario("8. Alat buat SPJ")

hasil_spj = ollama.jalankan_alat("buat_spj", {"dokumen": "spj"}, CFG_AKTIF)
cek("buat SPJ ok", hasil_spj.get("ok") is True, str(hasil_spj))
lokasi = Path(hasil_spj.get("lokasi") or "")
cek("berkas PDF di data/ollama", lokasi.exists()
    and lokasi.read_bytes().startswith(b"%PDF") and lokasi.stat().st_size > 1000,
    str(lokasi))

hasil_pns = ollama.jalankan_alat("buat_spj", {"dokumen": "pns", "tgl": 15}, CFG_AKTIF)
cek("buat absensi PNS ok + tgl 15",
    hasil_pns.get("ok") is True and hasil_pns.get("tgl") == 15
    and Path(hasil_pns.get("lokasi") or "").read_bytes().startswith(b"%PDF"),
    str(hasil_pns.get("nama")))

hasil_pppk = ollama.jalankan_alat("buat_spj", {"dokumen": "pppk"}, CFG_AKTIF)
cek("buat absensi PPPK ok", hasil_pppk.get("ok") is True, str(hasil_pppk))

hasil_spj_kosong = ollama.jalankan_alat("buat_spj", {"dokumen": "spj"},
                                        {**CFG_AKTIF, ollama.KUNCI_URL: ""})
cek("buat SPJ tanpa Ollama: alat tetap jalan (tidak bergantung Ollama)",
    hasil_spj_kosong.get("ok") is True, str(hasil_spj_kosong)[:120])

# --------------------------------------------------------------------------- #
# 9. Batas putaran alat
# --------------------------------------------------------------------------- #
skenario("9. Batas putaran alat")

OLLAMA.chat_skrip = [chat_alat("lihat_status_bot") for _ in range(ollama.BATAS_LOOP + 3)]
hasil = ollama.bicara("putar terus", cfg=CFG_AKTIF)
cek("putaran dihentikan di batas", hasil.get("batas") is True
    and len(hasil.get("alat") or []) == ollama.BATAS_LOOP,
    f"{len(hasil.get('alat') or [])}/{ollama.BATAS_LOOP}")
cek("pesan batas jelas", "dihentikan" in (hasil.get("jawaban") or ""),
    str(hasil.get("jawaban")))
OLLAMA.chat_skrip = []

# --------------------------------------------------------------------------- #
# 10. Titik akhir HTTP
# --------------------------------------------------------------------------- #
skenario("10. Titik akhir HTTP")

async def uji_http() -> None:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://uji",
                                 follow_redirects=True) as klien:
        await klien.post("/login", data={"mode": "staff", "username": "admin",
                                         "password": "admin123"})
        halaman = await klien.get("/ollama")
        cek("GET /ollama 200 + aktivasi + obrolan",
            halaman.status_code == 200 and "Aktivasi Ollama" in halaman.text
            and "Obrolan dengan Ollama" in halaman.text
            and "lihat_status_bot" in halaman.text,
            f"status {halaman.status_code}")

        status = await klien.get("/ollama/status.json")
        cek("status.json aktif + model",
            status.status_code == 200 and status.json().get("aktif") is True
            and status.json().get("model") == "qwen2.5:14b-instruct",
            str(status.json()))

        ollama.simpan_pengaturan({ollama.KUNCI_AKTIF: "0"})
        chat_mati = await klien.post("/ollama/chat",
                                     json={"pesan": "hallo"})
        cek("chat tanpa aktivasi → 400", chat_mati.status_code == 400
            and "belum diaktifkan" in (chat_mati.json().get("detail") or ""),
            f"status {chat_mati.status_code} {str(chat_mati.json())[:120]}")
        ollama.simpan_pengaturan({ollama.KUNCI_AKTIF: "1"})

        OLLAMA.chat_skrip = [chat_alat("lihat_status_spj"),
                             chat_bicara("SPJ sudah ada drafnya, 3 penerima.")]
        chat_ok = await klien.post("/ollama/chat",
                                   json={"pesan": "lihat status SPJ", "riwayat": []})
        cek("chat dengan sesi admin → 200 + jawaban",
            chat_ok.status_code == 200
            and chat_ok.json().get("jawaban") == "SPJ sudah ada drafnya, 3 penerima."
            and chat_ok.json().get("alat", [{}])[0].get("alat") == "lihat_status_spj",
            f"status {chat_ok.status_code} {str(chat_ok.json())[:160]}")

        uji = await klien.post("/ollama/uji")
        cek("POST /ollama/uji → laporan ok",
            uji.status_code == 200 and "Ollama terhubung" in uji.text,
            uji.text[-200:])

        simpan = await klien.post("/ollama/pengaturan",
                                  data={"aktif": "1", "url": OLLAMA.alamat,
                                        "model": "qwen2.5:14b-instruct", "kunci": "",
                                        "eksekusi": "1"})
        cek("POST /ollama/pengaturan simpan",
            simpan.status_code == 200 and "Pengaturan Ollama disimpan" in simpan.text,
            simpan.text[-200:])

        await klien.post("/logout")
        tanpa_kunci = await klien.post("/ollama/chat", json={"pesan": "hallo"})
        cek("chat tanpa kunci & tanpa sesi → 401 JSON",
            tanpa_kunci.status_code == 401
            and "kunci API" in (tanpa_kunci.json().get("detail") or ""),
            f"status {tanpa_kunci.status_code} {str(tanpa_kunci.json())[:120]}")

        services.set_setting("api_key", "uji-kunci-ollama")
        OLLAMA.chat_skrip = [chat_bicara("Insentif siap.")]
        dengan_kunci = await klien.post(
            "/ollama/chat", json={"pesan": "lihat status insentif"},
            headers={"X-API-Key": "uji-kunci-ollama"})
        cek("chat dengan X-API-Key → 200",
            dengan_kunci.status_code == 200
            and dengan_kunci.json().get("jawaban") == "Insentif siap.",
            f"status {dengan_kunci.status_code} {str(dengan_kunci.json())[:160]}")


import asyncio  # noqa: E402

asyncio.run(uji_http())

# --------------------------------------------------------------------------- #
OLLAMA.shutdown()

SAMPUL = 0
for nama, lolos, keterangan in HASIL:
    if not lolos:
        SAMPUL += 1
print(f"\nDiperiksa {len(HASIL)} pemeriksaan — {len(SKENARIO)} skenario — "
      f"{SAMPUL} GAGAL")
sys.exit(1 if SAMPUL else 0)
