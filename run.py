#!/usr/bin/env python3
"""Skrip peluncur SM.

Contoh pemakaian::

    python run.py                 # http://0.0.0.0:8000
    python run.py --port 9000     # ganti port
    python run.py --reload        # mode pengembangan (auto-restart)
    python run.py --init-db       # siapkan/upgrade database lalu keluar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def tunggu_port_bebas(port: int, batas: int, host: str = "127.0.0.1") -> bool:
    """Tunggu sampai tidak ada lagi yang menjawab di ``port`` (maksimal ``batas`` detik)."""
    import socket
    import time

    selesai = time.time() + max(0, int(batas))
    while time.time() < selesai:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soket:
            soket.settimeout(0.5)
            try:
                soket.connect((host, int(port)))
            except OSError:
                return True       # port sudah bebas
        time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Jalankan server SM")
    parser.add_argument("--host", default="0.0.0.0", help="Alamat bind (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default 8000)")
    parser.add_argument("--reload", action="store_true", help="Mode pengembangan")
    parser.add_argument("--tunggu-port", type=int, default=0, metavar="DETIK",
                        help="Tunggu sampai port bebas sebelum menyala (dipakai saat "
                             "server menggantikan dirinya setelah pembaruan)")
    parser.add_argument("--init-db", action="store_true", help="Siapkan database lalu keluar")
    parser.add_argument("--seed-ekskul", action="store_true", help="Isi contoh data ekstrakurikuler")
    parser.add_argument("--isi-ekskul-resmi", action="store_true",
                        help="Isi 14 daftar ekstrakurikuler resmi sekolah lalu keluar")
    args = parser.parse_args()

    from app import config, migrations, services

    config.ensure_dirs()
    if config.CATATAN_DB:
        print(f"  {config.CATATAN_DB}")
    executed = migrations.run_migrations(verbose=True)

    if args.init_db:
        print(f"Database siap: {config.DB_PATH}")
        if executed:
            print("Migrasi dijalankan: " + ", ".join(executed))
        return 0

    if args.isi_ekskul_resmi:
        ditambah, total = services.isi_ekskul_resmi()
        print(f"Daftar ekskul resmi: {ditambah} ditambahkan, {total} ekskul aktif sekarang.")
        return 0

    if args.seed_ekskul:
        jumlah = services.seed_ekskul_if_empty()
        print("Contoh ekstrakurikuler dimasukkan: " if jumlah else "Ekstrakurikuler sudah ada, dilewati.")
        if jumlah:
            print(f"  {jumlah} ekstrakurikuler")
        return 0

    if args.tunggu_port > 0:
        # Dipakai "Muat ulang server sekarang": proses baru dinyalakan SEBELUM proses lama
        # benar-benar berhenti (supaya aplikasi tidak mati), jadi portnya belum bebas.
        tunggu_port_bebas(args.port, args.tunggu_port)

    import uvicorn

    print("=" * 68)
    print(f"  {config.APP_NAME} — {config.APP_LONG_NAME}")
    print(f"  Versi {config.APP_VERSION}  |  Database: {config.DB_PATH}")
    print(f"  Buka: http://localhost:{args.port}")
    print(f"  Login admin: {config.DEFAULT_ADMIN_USERNAME} / {config.DEFAULT_ADMIN_PASSWORD}")
    print("  Login siswa: cukup masukkan NISN")
    print("=" * 68)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        # Terowongan (Tailscale Funnel / cloudflared) berjalan di komputer yang
        # sama dan meneruskan alamat asli pengunjung lewat X-Forwarded-*. Tanpa
        # ini seluruh pengunjung tampak berasal dari 127.0.0.1.
        proxy_headers=True,
        forwarded_allow_ips=config.FORWARDED_ALLOW,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
