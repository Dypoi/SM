#!/usr/bin/env python3
"""Peluncur SM mode online (gratis).

Menjalankan server SM **dan** terowongan gratis sehingga aplikasi bisa dibuka
dari internet tanpa IP publik, tanpa membuka port router, dan tanpa biaya:

1. **Tailscale Funnel** (`tailscale`, disarankan) — alamat tetap
   ``https://<nama-perangkat>.<tautan>.ts.net``, gratis untuk pemakaian pribadi,
   tanpa kartu kredit. Cukup pasang Tailscale, masuk, lalu aktifkan Funnel.
2. **Cloudflare quick tunnel** (`cloudflared`) — tanpa akun sama sekali, tetapi
   alamatnya berubah setiap kali dijalankan (``https://xxx.trycloudflare.com``).
3. **Tanpa keduanya** — aplikasi tetap berjalan untuk jaringan sekolah dan
   petunjuk pemasangan ditampilkan.

Alamat publik yang didapat dicatat ke ``data/alamat-publik.txt`` dan
``data/online.json`` supaya muncul di **Pengaturan → Sistem → Aman Online**.

Pemakaian::

    python SM-online.py                # server + terowongan (otomatis)
    python SM-online.py --lokal        # hanya jaringan sekolah
    python SM-online.py --tanpa-server # server sudah jalan, hanya terowongan
    python SM-online.py --buka         # buka alamat publik di peramban

Di Windows cukup klik dua kali ``SM-online.bat``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

POLA_CLOUDFLARE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
LEBAR = 66


def judul(teks: str) -> None:
    print("\n" + "=" * LEBAR)
    print(f"  {teks}")
    print("=" * LEBAR)


def alat_tersedia() -> dict[str, str]:
    """Cari ``tailscale``/``cloudflared`` (PATH maupun lokasi pemasangan umum)."""
    hasil: dict[str, str] = {}
    kandidat_tambahan = {
        "tailscale": [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tailscale" / "tailscale.exe",
            Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
        ],
        "cloudflared": [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "cloudflared" / "cloudflared.exe",
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "cloudflared" / "cloudflared.exe",
            Path(r"C:\cloudflared\cloudflared.exe"),
            Path("/usr/local/bin/cloudflared"),
        ],
    }
    for nama, daftar in kandidat_tambahan.items():
        jalur = shutil.which(nama)
        if not jalur:
            for kandidat in daftar:
                if kandidat.exists():
                    jalur = str(kandidat)
                    break
        if jalur:
            hasil[nama] = jalur
    return hasil


def port_siap(port: int) -> bool:
    with socket.socket() as soket:
        soket.settimeout(1.0)
        return soket.connect_ex(("127.0.0.1", port)) == 0


def tunggu_port(port: int, detik: int = 30) -> bool:
    batas = time.time() + detik
    while time.time() < batas:
        if port_siap(port):
            return True
        time.sleep(0.5)
    return False


def alamat_lokal() -> str:
    """Alamat aplikasi di jaringan sekolah (untuk dibagikan ke petugas)."""
    soket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        soket.connect(("8.8.8.8", 80))
        return soket.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        soket.close()


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #
def mulai_server(port: int) -> subprocess.Popen | None:
    """Nyalakan ``run.py`` dengan mode publik menyala."""
    if port_siap(port):
        print(f"[1/3] Server sudah berjalan di port {port} — dipakai apa adanya.")
        return None
    print("[1/3] Menjalankan server SM ...")
    lingkungan = os.environ.copy()
    lingkungan.setdefault("SM_PUBLIK", "1")       # pengaman mode online menyala
    lingkungan.setdefault("PYTHONUTF8", "1")
    proses = subprocess.Popen(
        [sys.executable, str(BASE_DIR / "run.py"), "--port", str(port)],
        cwd=str(BASE_DIR),
        env=lingkungan,
    )
    if not tunggu_port(port, 40):
        print("[!] Server belum menjawab. Periksa pesan galat di atas.")
        return None
    print(f"      Server siap: http://127.0.0.1:{port}")
    return proses


# --------------------------------------------------------------------------- #
# Terowongan
# --------------------------------------------------------------------------- #
def mulai_tailscale(jalur: str, port: int) -> tuple[bool, str, str]:
    """Nyalakan Tailscale Funnel; kembalikan (berhasil, alamat, catatan)."""
    try:
        hasil = subprocess.run([jalur, "funnel", "--bg", str(port)],
                               capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.SubprocessError) as galat:
        return False, "", f"gagal menjalankan tailscale: {galat}"

    if hasil.returncode != 0:
        pesan = (hasil.stderr or hasil.stdout or "").strip().splitlines()
        return False, "", pesan[-1][:200] if pesan else "tailscale menolak permintaan"

    try:
        status = subprocess.run([jalur, "status", "--json"], capture_output=True, text=True, timeout=60)
        dns = str((json.loads(status.stdout or "{}").get("Self") or {}).get("DNSName") or "")
    except (OSError, ValueError, subprocess.SubprocessError):
        dns = ""
    dns = dns.strip().strip(".")
    return True, (f"https://{dns}" if dns else ""), ""


def _buang_keluaran(proses: subprocess.Popen) -> None:
    """Terus baca keluaran cloudflared agar pipanya tidak penuh."""
    try:
        if proses.stdout:
            for _ in proses.stdout:
                pass
    except (OSError, ValueError):
        pass


def mulai_cloudflared(jalur: str, port: int) -> tuple[subprocess.Popen | None, str]:
    """Jalankan quick tunnel dan tunggu alamat publiknya muncul."""
    proses = subprocess.Popen(
        [jalur, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    batas = time.time() + 60
    while time.time() < batas:
        if proses.stdout is None:
            break
        baris = proses.stdout.readline()
        if not baris:
            if proses.poll() is not None:
                break
            continue
        print("      " + baris.rstrip()[:150])
        ketemu = POLA_CLOUDFLARE.search(baris)
        if ketemu:
            threading.Thread(target=_buang_keluaran, args=(proses,), daemon=True).start()
            return proses, ketemu.group(0)
    return proses, ""


def petunjuk_pemasangan() -> None:
    print("""
[2/3] Terowongan belum tersedia — aplikasi tetap jalan di jaringan sekolah.

      A. Tailscale Funnel (disarankan: alamat tetap, gratis, tanpa kartu kredit)
         1. Unduh dari https://tailscale.com/download/windows lalu pasang.
         2. Buka Tailscale dan masuk memakai akun Google/GitHub.
         3. Di konsol admin Tailscale (login.tailscale.com), buka DNS dan
            aktifkan HTTPS; lalu aktifkan Funnel untuk perangkat ini.
         4. Jalankan SM-online.bat sekali lagi.

      B. Cloudflare quick tunnel (tanpa akun, alamat berubah tiap dijalankan)
         1. Unduh cloudflared-windows-amd64.exe dari
            https://github.com/cloudflare/cloudflared/releases
         2. Simpan sebagai C:\\cloudflared\\cloudflared.exe
         3. Jalankan SM-online.bat sekali lagi.""")


# --------------------------------------------------------------------------- #
# Program utama
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Jalankan SM dengan akses internet gratis")
    parser.add_argument("--port", type=int, default=int(os.getenv("SM_PORT", "8000")))
    parser.add_argument("--lokal", action="store_true", help="Lanjutkan tanpa terowongan")
    parser.add_argument("--tanpa-server", action="store_true", help="Server sudah jalan")
    parser.add_argument("--buka", action="store_true", help="Buka alamat publik di peramban")
    args = parser.parse_args()

    from app import online  # impor setelah BASE_DIR masuk sys.path

    judul("SM — mode online (gratis)")
    print(f"  Folder aplikasi: {BASE_DIR}")
    print(f"  Port           : {args.port}")

    server: subprocess.Popen | None = None
    if not args.tanpa_server:
        server = mulai_server(args.port)
        if server is None and not port_siap(args.port):
            return 1

    alamat, alat, terowongan = "", "", None
    if args.lokal:
        print("[2/3] Mode lokal saja (--lokal): tanpa terowongan.")
    else:
        tersedia = alat_tersedia()
        if "tailscale" in tersedia:
            print("[2/3] Menyalakan Tailscale Funnel ...")
            berhasil, alamat, catatan = mulai_tailscale(tersedia["tailscale"], args.port)
            if berhasil:
                alat = "Tailscale Funnel (alamat tetap)"
            else:
                print(f"      Tailscale belum bisa dipakai: {catatan}")
                print("      Pastikan sudah masuk (login) dan Funnel aktif untuk perangkat ini.")
        if not alamat and "cloudflared" in tersedia:
            print("[2/3] Menyalakan Cloudflare quick tunnel ...")
            terowongan, alamat = mulai_cloudflared(tersedia["cloudflared"], args.port)
            if alamat:
                alat = "Cloudflare quick tunnel (alamat sementara)"
            else:
                print("      Cloudflared tidak memberi alamat publik.")
        if not alamat and not tersedia:
            petunjuk_pemasangan()

    if alamat:
        online.simpan_status(alamat, alat, args.port)
        judul("Aplikasi SM sudah online")
        print(f"  Alamat publik : {alamat}")
        print(f"  Cara dibuka   : {alat}")
        print(f"  Di sekolah    : http://{alamat_lokal()}:{args.port}")
        print("\n  Bagikan alamat publik itu kepada petugas/siswa. Tekan Ctrl+C untuk berhenti.")
    else:
        judul("Aplikasi SM berjalan (jaringan sekolah)")
        print(f"  Alamat        : http://{alamat_lokal()}:{args.port}")
        print("  Aplikasi belum bisa dibuka dari internet.")

    peringatan = online.pemeriksaan_singkat()
    if peringatan:
        print("\n  Perhatian sebelum dipakai luas:")
        for pesan in peringatan:
            print(f"   - {pesan}")

    if args.buka and alamat:
        webbrowser.open(alamat)

    try:
        if server is not None:
            server.wait()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Menghentikan ...")
    finally:
        if terowongan is not None:
            terowongan.terminate()
            # Alamat quick tunnel mati bersama prosesnya: jangan ditampilkan lagi.
            online.hapus_status()
        if server is not None and server.poll() is None:
            server.terminate()
    print("  Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
