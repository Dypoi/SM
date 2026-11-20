"""Jembatan WhatsApp (Baileys) — mulai, hentikan, dan pantau subprocess Node.

Jembatan ini **hanya relay**: menerima pesan WhatsApp → memanggil balik
``/ollama/chat`` di SM → mengirim jawaban. Otak, alat, dan penjaga nilai tetap
di Python; bridge tidak menjalankan alat dan tidak mengarang jawaban.

Proses Node (``wa-bridge/index.js``) diluncurkan oleh aplikasi sebagai
subprocess tanpa jendela konsol (CREATE_NO_WINDOW di Windows). Bila Node atau
Baileys belum terpasang, aplikasi tetap berjalan dan status dilaporkan jujur.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config, services

#: Folder jembatan WhatsApp (berisi index.js + node_modules).
BRIDGE_DIR = config.BASE_DIR / "wa-bridge"
#: Folder session WhatsApp (di luar repo, di data aplikasi).
SESSION_DIR = config.DATA_DIR / "wa"

#: Kunci pengaturan.
KUNCI_AKTIF = "wa_aktif"
KUNCI_PORT = "wa_port"
DEFAULT_PORT = 8799

_proses: subprocess.Popen | None = None
_pesan_mulai: str = ""


def portawal() -> int:
    """Port lokal bridge (dari pengaturan, bawaan 8799)."""
    nilai = str(services.get_setting(KUNCI_PORT) or "").strip()
    try:
        port = int(nilai) if nilai else DEFAULT_PORT
        return port if 1 < port < 65536 else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


def url_bridge(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or portawal()}"


def _tanpa_jendela() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def node_tersedia() -> bool:
    return shutil.which("node") is not None


def baileys_terpasang() -> bool:
    return (BRIDGE_DIR / "node_modules" / "@whiskeysockets" / "baileys" /
            "package.json").exists()


def siap() -> bool:
    return node_tersedia() and baileys_terpasang()


def _api_key() -> str:
    return str(services.get_setting("api_key") or "")


def mulai(port: int | None = None, tunggu_detik: float = 8.0) -> dict:
    """Nyalakan proses Node bridge (jika belum jalan) dan tunggu siap."""
    global _proses, _pesan_mulai
    port = port or portawal()
    if _proses is not None and _proses.poll() is None:
        return {"ok": True, "port": port, "pesan": "Jembatan sudah jalan."}
    if not siap():
        _pesan_mulai = ("Node.js atau Baileys belum terpasang. Pasang Node.js lalu "
                        "jalankan `npm install` di folder wa-bridge.")
        return {"ok": False, "port": port, "pesan": _pesan_mulai}

    env = dict(os.environ)
    env.update({
        "SM_WA_PORT": str(port),
        "SM_WA_DIR": str(SESSION_DIR),
        "SM_BASE_URL": f"http://127.0.0.1:{config.PORT}",
        "SM_API_KEY": _api_key(),
        "SM_WA_ENABLED": "1" if str(services.get_setting(KUNCI_AKTIF)) == "1" else "0",
    })
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        _proses = subprocess.Popen(
            ["node", "index.js"],
            cwd=str(BRIDGE_DIR),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=_tanpa_jendela() | int(getattr(subprocess, "DETACH_PROCESS", 0))
            if os.name == "nt" else 0,
        )
    except OSError as galat:
        _pesan_mulai = f"Gagal menyalakan jembatan: {galat}"
        return {"ok": False, "port": port, "pesan": _pesan_mulai}

    # Tunggu sampai HTTP bridge menjawab (maksimal tunggu_detik).
    tenggat = time.time() + max(0.0, tunggu_detik)
    sementara = {"ok": False, "pesan": "Menunggu jembatan menyala..."}
    while time.time() < tenggat:
        sementara = status_cepat(port)
        if sementara.get("http"):
            sementara["ok"] = True
            break
        time.sleep(0.3)
    _pesan_mulai = str(sementara.get("pesan") or "")
    return sementara


def hentikan() -> bool:
    """Hentikan proses Node bridge (jika jalan)."""
    global _proses
    if _proses is None:
        return True
    try:
        if _proses.poll() is None:
            _proses.terminate()
            try:
                _proses.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proses.kill()
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        _proses = None


def _ambil(path: str, port: int | None = None, detik: float = 4.0):
    """Ambil URL dari bridge; kembalikan (ok, data/bytes atau None, galat)."""
    url = url_bridge(port) + path
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=detik) as respons:
            return True, respons.read(), None
    except urllib.error.HTTPError as galat:
        return False, None, str(galat)
    except Exception as galat:  # noqa: BLE001
        return False, None, str(galat)


def _kirim_json(path: str, badan: dict, port: int | None = None,
                detik: float = 30.0) -> tuple[bool, dict, str]:
    url = url_bridge(port) + path
    data = json.dumps(badan).encode("utf-8")
    # Rute /send, /test/inbound, /reset meminta kunci API di header X-API-Key.
    headers = {"Content-Type": "application/json"}
    kunci = _api_key()
    if kunci:
        headers["X-API-Key"] = kunci
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=detik) as respons:
            return True, json.loads(respons.read() or b"{}"), ""
    except urllib.error.HTTPError as galat:
        # Ambil isi tubuh galat (biasa {"detail": ...}) supaya pesan ramah
        # tersampaikan, bukan sekadar «HTTP Error 503».
        detail = ""
        try:
            isi = galat.read().decode("utf-8", "replace")
            detail = json.loads(isi).get("detail") or isi
        except Exception:  # noqa: BLE001
            detail = str(galat)
        return False, {}, str(detail)
    except Exception as galat:  # noqa: BLE001
        return False, {}, str(galat)


def status_cepat(port: int | None = None) -> dict:
    """Status sambungan WhatsApp + kesiapan bridge."""
    port = port or portawal()
    hasil = {
        "aktif": str(services.get_setting(KUNCI_AKTIF)) == "1",
        "port": port,
        "node": node_tersedia(),
        "baileys": baileys_terpasang(),
        "siap": siap(),
        "http": False,
        "terhubung": False,
        "menunggu_pairing": False,
        "nomor": "",
        "pesan": "",
    }
    if not hasil["aktif"]:
        hasil["pesan"] = "WhatsApp dimatikan di pengaturan."
        return hasil
    if not hasil["siap"]:
        hasil["pesan"] = ("Node.js atau Baileys belum terpasang — jembatan tidak siap. "
                          "Pasang Node.js lalu `npm install` di wa-bridge.")
        return hasil
    ok, data, galat = _ambil("/status", port)
    if ok and isinstance(data, bytes):
        try:
            info = json.loads(data.decode("utf-8"))
            hasil.update({
                "http": True,
                "terhubung": bool(info.get("terhubung")),
                "menunggu_pairing": bool(info.get("menunggu_pairing")),
                "nomor": info.get("nomor") or "",
                "pesan": info.get("pesan") or "",
            })
        except ValueError:
            hasil["pesan"] = "Status jembatan tidak terbaca."
    else:
        hasil["pesan"] = f"Jembatan belum menjawab di port {port} ({galat})."
    return hasil


def qr_png(port: int | None = None) -> tuple[bool, bytes | None, str]:
    """Ambil PNG kode QR pairing (bila menunggu pairing)."""
    if not str(services.get_setting(KUNCI_AKTIF)) == "1":
        return False, None, "WhatsApp dimatikan."
    ok, data, galat = _ambil("/qr", port)
    if ok and isinstance(data, bytes) and data:
        return True, data, ""
    if galat and "404" in galat:
        return False, None, "Belum ada kode QR (mungkin sudah terhubung)."
    return False, None, f"QR tidak tersedia ({galat})."


def kirim(no: str, teks: str, port: int | None = None) -> dict:
    """Kirim pesan teks keluar via WhatsApp (jika terhubung)."""
    ok, data, galat = _kirim_json("/send", {"no": no, "teks": teks}, port)
    if ok:
        return {"ok": bool(data.get("ok")), "pesan": ""}
    return {"ok": False, "pesan": galat or "Gagal mengirim."}


def uji_masuk(dari: str, teks: str, port: int | None = None) -> dict:
    """Simulasi pesan masuk (tanpa WhatsApp sungguhan) — untuk pengujian."""
    ok, data, galat = _kirim_json("/test/inbound", {"dari": dari, "teks": teks},
                                  port, detik=60.0)
    if ok:
        return {"ok": bool(data.get("ok")), "jawaban": data.get("jawaban") or ""}
    return {"ok": False, "jawaban": galat or "Gagal."}
