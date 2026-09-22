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
    python SM-online.py --cek          # periksa kesiapan Tailscale (tanpa menjalankan apa pun)
    python SM-online.py --lokal        # hanya jaringan sekolah
    python SM-online.py --tanpa-server # server sudah jalan, hanya terowongan
    python SM-online.py --buka         # buka alamat publik di peramban
    python SM-online.py --hentikan     # matikan funnel publik (aplikasi lokal tetap aman)

Di Windows cukup klik dua kali ``SM-online.bat``. Petunjuk lengkap langkah demi langkah ada di
``PANDUAN-ONLINE.md``; yang ringkas di README bagian "Menjalankan online".

Catatan Tailscale Funnel: port publik hanya boleh **443, 8443, atau 10000** (batas Tailscale,
bukan aplikasi ini) — aplikasi tetap berjalan di port lokal 8000 seperti biasa. Funnel juga
perlu **MagicDNS**, **HTTPS**, dan izin Funnel pada tailnet; skrip ini memeriksa ketiganya dan
menerjemahkan pesan galat Tailscale menjadi langkah perbaikan.
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

#: Port publik yang diizinkan Tailscale Funnel (batas dari Tailscale, tidak bisa ditawar).
PORT_FUNNEL = (443, 8443, 10000)


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
def mulai_tailscale(jalur: str, port: int, https_port: int = 443) -> tuple[bool, str, str]:
    """Nyalakan Tailscale Funnel; kembalikan (berhasil, alamat, catatan)."""
    if https_port not in PORT_FUNNEL:
        return False, "", (f"port publik {https_port} tidak diizinkan Tailscale Funnel "
                           f"(pilihan: {', '.join(str(p) for p in PORT_FUNNEL)})")
    perintah = [jalur, "funnel", f"--bg", f"--https={https_port}", str(port)]
    try:
        hasil = subprocess.run(perintah, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.SubprocessError) as galat:
        return False, "", f"gagal menjalankan tailscale: {galat}"

    if hasil.returncode != 0:
        keluaran = (hasil.stderr or hasil.stdout or "").strip().splitlines()
        pesan = keluaran[-1][:200] if keluaran else "tailscale menolak permintaan"
        return False, "", pesan

    try:
        status = subprocess.run([jalur, "status", "--json"], capture_output=True, text=True, timeout=60)
        dns = str((json.loads(status.stdout or "{}").get("Self") or {}).get("DNSName") or "")
    except (OSError, ValueError, subprocess.SubprocessError):
        dns = ""
    dns = dns.strip().strip(".")
    alamat = f"https://{dns}" if dns else ""
    if alamat and https_port != 443:
        alamat = f"{alamat}:{https_port}"
    return True, alamat, ""


def _perbaikan_tailscale(pesan: str) -> list[str]:
    """Terjemahkan pesan galat Tailscale menjadi langkah perbaikan yang bisa dikerjakan guru."""
    teks = pesan.lower()
    if "funnel" in teks and ("not enabled" in teks or "disabled" in teks
                             or "attribute" in teks or "permission" in teks):
        return ["Aktifkan izin Funnel: buka https://login.tailscale.com/admin/acls , pastikan",
                "ada `nodeAttrs` berisi `funnel` untuk perangkat ini (Tailscale CLI biasanya",
                "menambahkannya otomatis saat perintah funnel pertama dijalankan sebagai",
                "pemilik/admin tailnet). Setelah itu jalankan SM-online.bat lagi."]
    if "https" in teks and ("not enabled" in teks or "certificate" in teks or "cert" in teks):
        return ["Nyalakan HTTPS: https://login.tailscale.com/admin/dns → bagian HTTPS",
                "Certificates → *Enable HTTPS*. Tailscale lalu membuat sertifikat",
                "Let's Encrypt untuk alamat *.ts.net secara otomatis."]
    if "magicdns" in teks:
        return ["Nyalakan MagicDNS: https://login.tailscale.com/admin/dns → *Enable MagicDNS*."]
    if "logged out" in teks or "not logged in" in teks or "no state" in teks \
            or "starting" in teks or "stopped" in teks:
        return ["Tailscale belum masuk/aktif. Klik ikon Tailscale di sudut kanan bawah",
                "Windows → *Log in*, tunggu tulisan «Connected», lalu coba lagi."]
    if "port" in teks and ("in use" in teks or "already" in teks or "conflict" in teks):
        return ["Port publik itu sudah dipakai layanan lain. Matikan dulu dengan",
                "`tailscale funnel --https=443 off`, atau pakai port lain:",
                "jalankan `SM-online.bat --https-port 8443`."]
    return ["Periksa keadaan Tailscale dengan `tailscale status` dan",
            "`tailscale funnel status` di Command Prompt, lalu jalankan SM-online.bat lagi."]


def _alamat_publik_siap(alamat: str, detik: int = 20) -> tuple[bool, str]:
    """Hubungi alamat publik (lewat relay Tailscale) untuk membuktikan benar-benar bisa dibuka."""
    import urllib.error
    import urllib.request

    batas = time.time() + detik
    galat = ""
    while time.time() < batas:
        try:
            with urllib.request.urlopen(alamat, timeout=10) as jawab:      # noqa: S310
                return True, f"menjawab (HTTP {jawab.status})"
        except urllib.error.HTTPError as exc:
            if exc.code in (200, 303, 401, 403):
                return True, f"menjawab (HTTP {exc.code})"
            galat = f"HTTP {exc.code}"
        except Exception as exc:      # noqa: BLE001 — belum siap, bukan galat aplikasi
            galat = type(exc).__name__
        time.sleep(2)
    return False, galat or "tidak menjawab"


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


def cek_tailscale(jalur: str, port: int, https_port: int = 443) -> int:
    """Periksa kesiapan Tailscale Funnel tanpa menjalankan server (``--cek``)."""
    judul("SM — pemeriksaan Tailscale Funnel")
    print(f"  Tailscale    : {jalur}")

    def jalankan(perintah: list[str], waktu: int = 60) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run([jalur, *perintah], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=waktu)
        except (OSError, subprocess.SubprocessError):
            return None

    versi = jalankan(["version"])
    print(f"  Versi        : {(versi.stdout or '').strip().splitlines()[0] if versi and versi.stdout else '?'}")

    status = jalankan(["status", "--json"])
    terhubung, dns_nama = False, ""
    if status is not None and status.stdout:
        try:
            data = json.loads(status.stdout)
            terhubung = str(data.get("BackendState") or "").lower() == "running"
            dns_nama = str(((data.get("Self") or {}).get("DNSName")) or "").strip(".")
        except ValueError:
            pass
    print(f"  Terhubung    : {'ya' if terhubung else 'BELUM (buka aplikasi Tailscale lalu Log in)'}")
    print(f"  Nama perangkat: {dns_nama or 'tidak diketahui'}")
    if dns_nama:
        print(f"  Alamat publik: https://{dns_nama}"
              + (f":{https_port}" if https_port != 443 else ""))

    funnel = jalankan(["funnel", "status"])
    keluaran_funnel = ((funnel.stdout or "") + (funnel.stderr or "")).strip()
    print("  Funnel       : " + (keluaran_funnel.splitlines()[0] if keluaran_funnel
                                 else "belum ada yang menyala"))
    if "443" not in keluaran_funnel and "8443" not in keluaran_funnel \
            and "10000" not in keluaran_funnel:
        print("                 (belum menyala — jalankan SM-online.bat untuk menyalakannya)")

    # Uji coba menyalakan funnel sungguhan: hasilnya langsung dilaporkan, tanpa server SM.
    berhasil, alamat, catatan = mulai_tailscale(jalur, port, https_port)
    if berhasil:
        print(f"  Uji nyala    : BERHASIL — {alamat or 'alamat belum terbaca'} → "
              f"http://127.0.0.1:{port}")
        if alamat:
            siap, keterangan = _alamat_publik_siap(alamat, detik=15)
            print(f"  Uji dibuka   : {'alamat publik menjawab' if siap else 'BELUM menjawab'}"
                  f" ({keterangan})")
        print("\n  Semua siap. Jalankan SM-online.bat (atau `python SM-online.py`) seperti biasa.")
        return 0
    print(f"  Uji nyala    : GAGAL — {catatan}")
    print("\n  Langkah perbaikan:")
    for baris in _perbaikan_tailscale(catatan):
        print(f"   - {baris}")
    return 1


def hentikan_tailscale(jalur: str, https_port: int = 443) -> int:
    """Matikan funnel publik (``--hentikan``); aplikasi lokal tidak diapa-apakan."""
    from app import online

    judul("SM — mematikan akses publik (Tailscale Funnel)")
    keluar = 0
    for perintah in ([jalur, "funnel", f"--https={https_port}", "off"],
                     [jalur, "funnel", "off"]):
        try:
            hasil = subprocess.run(perintah, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as galat:
            print(f"  [!] {galat}")
            return 1
        if hasil.returncode == 0:
            print(f"  Funnel dimatikan ({' '.join(perintah[1:])}).")
            break
        keluar = hasil.returncode
    else:
        print("  [!] Funnel tidak bisa dimatikan lewat perintah itu. Coba: tailscale funnel off")
    online.hapus_status()
    print("  Penanda «sedang online» di aplikasi dibersihkan.")
    print("  Aplikasi SM di jaringan sekolah tetap berjalan seperti biasa.")
    return 0 if keluar == 0 else 1


def petunjuk_pemasangan() -> None:
    print("""
[2/3] Terowongan belum tersedia — aplikasi tetap jalan di jaringan sekolah.

      A. Tailscale Funnel (disarankan: alamat tetap, gratis, tanpa kartu kredit)
         1. Unduh dari https://tailscale.com/download/windows lalu pasang.
         2. Buka Tailscale dan masuk memakai akun Google/GitHub.
         3. Buka https://login.tailscale.com/admin/dns → nyalakan MagicDNS dan
            HTTPS Certificates. Izin Funnel biasanya ditambahkan otomatis oleh
            perintah funnel (lihat https://login.tailscale.com/admin/acls).
         4. Periksa kesiapan: SM-online.bat --cek
         5. Lalu jalankan SM-online.bat seperti biasa — alamat https://…ts.net muncul.
         Petunjuk bergambar langkah demi langkah: PANDUAN-ONLINE.md

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
    parser.add_argument("--cek", action="store_true",
                        help="Periksa kesiapan Tailscale Funnel lalu keluar (tanpa server)")
    parser.add_argument("--hentikan", action="store_true",
                        help="Matikan akses publik (funnel) tanpa menghentikan aplikasi lokal")
    parser.add_argument("--https-port", type=int, default=443, choices=list(PORT_FUNNEL),
                        help="Port publik Tailscale Funnel (bawaan 443; alternatif 8443/10000)")
    args = parser.parse_args()

    if args.cek:
        tersedia = alat_tersedia()
        if "tailscale" not in tersedia:
            judul("SM — pemeriksaan Tailscale Funnel")
            print("  Tailscale belum terpasang di komputer ini.")
            print("  Unduh & pasang: https://tailscale.com/download/windows")
            print("  Setelah itu jalankan: SM-online.bat --cek")
            return 1
        return cek_tailscale(tersedia["tailscale"], args.port, args.https_port)

    if args.hentikan:
        tersedia = alat_tersedia()
        if "tailscale" not in tersedia:
            judul("SM — mematikan akses publik")
            print("  Tailscale tidak ditemukan. Bila memakai cloudflared, hentikan dengan "
                  "Ctrl+C di jendelanya.")
            return 1
        return hentikan_tailscale(tersedia["tailscale"], args.https_port)

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
            berhasil, alamat, catatan = mulai_tailscale(
                tersedia["tailscale"], args.port, args.https_port)
            if berhasil:
                alat = "Tailscale Funnel (alamat tetap)"
                if alamat:
                    siap, keterangan = _alamat_publik_siap(alamat, detik=25)
                    print(f"      Uji alamat publik: "
                          f"{'menjawab' if siap else 'BELUM menjawab'} ({keterangan})")
                    if not siap:
                        print("      Kalau tetap tidak menjawab: pastikan Tailscale «Connected»,",
                              "HTTPS & Funnel aktif di konsol admin, dan PC tidak sedang tidur.")
            else:
                print(f"      Tailscale belum bisa dipakai: {catatan}")
                for baris in _perbaikan_tailscale(catatan):
                    print(f"      - {baris}")
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
