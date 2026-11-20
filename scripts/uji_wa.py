#!/usr/bin/env python3
"""Uji **jembatan WhatsApp (WA)** — sidecar Baileys + sisi Python SM.

Yang dibuktikan:

1. kesiapan: Node.js + Baileys terpasang, status jujur bila belum aktif;
2. mulai/hentikan: subprocess Node jalan (mode uji — tanpa sambungan WhatsApp);
3. status: bridge menjawab HTTP lokal; terhubung/menunggu pairing dilaporkan;
4. uji masuk: pesan masuk → bridge memanggil balik /ollama/chat → jawaban;
5. kirim keluar: /send;
6. QR: bila tidak ada kode QR → graceful (bukan galat).

Bodap palsu: server HTTP lokal yang menjawab /ollama/chat dengan jawaban tetap.
Bridge dijalankan dengan ``SM_WA_NO_CONNECT=1`` agar tidak perlu internet/WA.

Jalankan::

    .venv/bin/python scripts/uji_wa.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AKAR))

# --- Persiapan lingkungan (sebelum mengimpor modul app) ---
_SEMENTARA = Path(tempfile.mkdtemp(prefix="sm-uji-wa-"))
os.environ["SM_DATA_DIR"] = str(_SEMENTARA / "data")
os.environ["SM_DB_PATH"] = str(_SEMENTARA / "uji.sqlite3")
os.environ["SM_AUTO_SEED"] = "0"
# Port app palsu (bodap tiruan) + bridge uji + mode offline WhatsApp.
FAKE_APP_PORT = 8811
BRIDGE_PORT = 8812
os.environ["SM_APP_PORT"] = str(FAKE_APP_PORT)
os.environ["SM_WA_NO_CONNECT"] = "1"

from app import migrations, ollama, services, wa_bridge  # noqa: E402

migrations.init_database()

HASIL: list[tuple[str, bool, str]] = []
SKENARIO: list[str] = []


def skenario(nama: str) -> None:
    SKENARIO.append(nama)
    print(f"\n=== {nama} ===")


def cek(nama: str, syarat: bool, keterangan: str = "") -> None:
    HASIL.append((nama, bool(syarat), keterangan))
    print(f"[{'  OK  ' if syarat else 'GAGAL'}] {nama}"
          + (f" — {keterangan}" if keterangan and not syarat else ""))


# --------------------------------------------------------------------------- #
# Bodap tiruan (menjawab /ollama/chat)
# --------------------------------------------------------------------------- #
class _BodapPalsu(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/ollama/chat":
            self.send_response(404)
            self.end_headers()
            return
        panjang = int(self.headers.get("Content-Length") or 0)
        badan = json.loads(self.rfile.read(panjang) or b"{}")
        # Catat apa yang dikirim bridge (untuk verifikasi sumber="wa").
        _BodapPalsu.terakhir = {"badan": badan, "kunci": self.headers.get("X-API-Key")}
        respons = {"jawaban": "Total siswa seluruhnya adalah 816."}
        keluar = json.dumps(respons).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(keluar)))
        self.end_headers()
        self.wfile.write(keluar)


_BodapPalsu.terakhir = {}
bodap = ThreadingHTTPServer(("127.0.0.1", FAKE_APP_PORT), _BodapPalsu)
threading.Thread(target=bodap.serve_forever, daemon=True).start()


def main() -> int:
    skenario("1. Kesiapan jembatan")
    cek("node tersedia", wa_bridge.node_tersedia(), "")
    cek("baileys terpasang", wa_bridge.baileys_terpasang(), "")
    cek("status awal: tidak aktif",
        wa_bridge.status_cepat().get("aktif") is False, "")

    skenario("2. System prompt conversational (ala Meta AI)")
    cek("SYSTEM_PROMPT_WA ada", bool(ollama.SYSTEM_PROMPT_WA), "")
    cek("SYSTEM_PROMPT_WA membawa aturan keras",
        all(k in ollama.SYSTEM_PROMPT_WA for k in ("jangan mengarang", "alat")),
        "")
    cek("SYSTEM_PROMPT_WA bernada percakapan",
        "asisten" in ollama.SYSTEM_PROMPT_WA.lower(), "")
    cek("SYSTEM_PROMPT_WA beda dari web",
        ollama.SYSTEM_PROMPT_WA != ollama.SYSTEM_PROMPT, "")

    skenario("3. Mulai bridge (mode uji)")
    services.update_settings({wa_bridge.KUNCI_AKTIF: "1",
                              wa_bridge.KUNCI_PORT: str(BRIDGE_PORT)})
    hasil = wa_bridge.mulai(port=BRIDGE_PORT)
    cek("bridge mulai", hasil.get("ok") is True, str(hasil.get("pesan")))
    status = wa_bridge.status_cepat(BRIDGE_PORT)
    cek("bridge menjawab HTTP", status.get("http") is True, str(status))
    cek("bridge siap", status.get("siap") is True, "")
    cek("bridge belum terhubung (mode uji)",
        status.get("terhubung") is False, str(status.get("pesan")))

    skenario("4. Uji masuk: bridge → bodap → jawaban")
    waktu = time.time()
    uji = wa_bridge.uji_masuk("uji@s.whatsapp.net", "berapa jumlah siswa?",
                              BRIDGE_PORT)
    cek("uji masuk ok", uji.get("ok") is True, str(uji))
    cek("jawaban dari bodap",
        "816" in (uji.get("jawaban") or ""), str(uji.get("jawaban")))
    cek("uji masuk cepat (<10s)", (time.time() - waktu) < 10.0,
        f"{time.time() - waktu:.2f}s")
    # Bridge mengirim sumber="wa" + kunci API ke /ollama/chat.
    terakhir = _BodapPalsu.terakhir or {}
    cek("bridge mengirim sumber=wa",
        terakhir.get("badan", {}).get("sumber") == "wa", str(terakhir.get("badan")))
    cek("bridge mengirim X-API-Key",
        bool(terakhir.get("kunci")), "")

    skenario("5. QR & kirim (graceful)")
    ok_qr, png, galat = wa_bridge.qr_png(BRIDGE_PORT)
    cek("QR tidak ada → graceful (bukan galat 500)",
        ok_qr is False and isinstance(galat, str), galat)
    kir = wa_bridge.kirim("628123456789@s.whatsapp.net", "halo", BRIDGE_PORT)
    cek("kirim keluar: graceful (belum terhubung)",
        kir.get("ok") is False and bool(kir.get("pesan")), str(kir))

    skenario("6. Hentikan bridge")
    cek("bridge dihentikan", wa_bridge.hentikan() is True, "")
    cek("status setelah henti: http mati",
        wa_bridge.status_cepat(BRIDGE_PORT).get("http") is False, "")

    bodap.shutdown()
    SAMPUL = 0
    for nama, lolos, keterangan in HASIL:
        if not lolos:
            SAMPUL += 1
    print(f"\nDiperiksa {len(HASIL)} pemeriksaan — {len(SKENARIO)} skenario — "
          f"{SAMPUL} GAGAL")
    return 1 if SAMPUL else 0


if __name__ == "__main__":
    raise SystemExit(main())
