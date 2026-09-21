#!/usr/bin/env python3
"""Peluncur latar belakang SM — menjalankan aplikasi **tanpa jendela terminal**.

Di Windows, aplikasi SM dijalankan lewat berkas ini memakai ``pythonw.exe`` (Python tanpa
jendela konsol), sehingga tidak ada jendela hitam yang muncul dan tidak ada yang perlu
dibiarkan terbuka: aplikasi berjalan di belakang layar, peramban terbuka sendiri, dan bisa
dimatikan lewat pintasan **Hentikan SM**.

Pemakaian::

    pythonw SM-latar.py                 # jalankan di belakang layar + buka peramban
    pythonw SM-latar.py --tanpa-buka    # jangan buka peramban
    pythonw SM-latar.py --port 9000     # port lain
    pythonw SM-latar.py --hentikan      # matikan aplikasi yang sedang jalan
    pythonw SM-latar.py --status        # keadaan aplikasi (untuk skrip/pemeriksaan)
    python SM-latar.py --tampak         # jalankan DI JENDELA INI (untuk mencari masalah)

Catatan keadaan disimpan di ``data/server.json`` (pid, port, waktu mulai) dan catatan
keluaran aplikasi ditulis ke ``data/log-server.txt`` — jadi bila ada masalah, isinya bisa
diperiksa tanpa jendela terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

PORT_BAWAAN = 8000


def _data_dir() -> Path:
    """Folder data aplikasi (menghormati ``SM_DATA_DIR`` seperti aplikasi utama)."""
    dari_env = os.environ.get("SM_DATA_DIR")
    if dari_env:
        return Path(dari_env).expanduser()
    return BASE_DIR / "data"


def berkas_keadaan() -> Path:
    return _data_dir() / "server.json"


def berkas_log() -> Path:
    return _data_dir() / "log-server.txt"


def _python_latar() -> Path:
    """Python **tanpa jendela** (``pythonw.exe``) — itulah kunci «tanpa terminal».

    Dipilih dari folder Python yang sama dengan Python server, supaya pustaka aplikasi tetap
    terbaca; kalau ``pythonw.exe`` tidak ada, dipakai Python server apa adanya.
    """
    server = _python_server()
    if os.name == "nt":
        for folder in (server.parent, BASE_DIR / "python",
                       BASE_DIR / ".venv" / "Scripts", Path(sys.executable).parent):
            jalur = folder / "pythonw.exe"
            if jalur.exists():
                return jalur
    elif shutil.which("pythonw"):
        return Path(shutil.which("pythonw"))      # type: ignore[arg-type]
    return server


def _python_server() -> Path:
    """Python untuk menjalankan server aplikasi (bawaan aplikasi → .venv → Python ini)."""
    kandidat = [BASE_DIR / "python" / ("python.exe" if os.name == "nt" else "bin/python3")]
    if os.name == "nt":
        kandidat += [BASE_DIR / "python" / "python.exe", BASE_DIR / ".venv" / "Scripts/python.exe"]
    else:
        kandidat += [BASE_DIR / "python" / "bin/python", BASE_DIR / ".venv" / "bin/python"]
    kandidat.append(Path(sys.executable))
    for jalur in kandidat:
        if jalur.exists():
            return jalur
    return Path(sys.executable)


def tanpa_jendela() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)


def port_terpakai(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soket:
        soket.settimeout(0.6)
        try:
            soket.connect((host, port))
        except OSError:
            return False
    return True


def alamat_menjawab(port: int, jalur: str = "/") -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{jalur}", timeout=2) as jawab:
            return jawab.status in (200, 303, 304)
    except urllib.error.HTTPError as exc:
        return exc.code in (200, 303, 304, 401, 403)
    except Exception:      # noqa: BLE001 — belum siap, bukan galat
        return False


def baca_keadaan() -> dict:
    berkas = berkas_keadaan()
    if not berkas.exists():
        return {}
    try:
        return json.loads(berkas.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tulis_keadaan(data: dict) -> None:
    berkas = berkas_keadaan()
    berkas.parent.mkdir(parents=True, exist_ok=True)
    berkas.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def hapus_keadaan() -> None:
    berkas_keadaan().unlink(missing_ok=True)


def pid_hidup(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        hasil = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True,
                               text=True, errors="replace", creationflags=tanpa_jendela())
        return str(pid) in (hasil.stdout or "")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def pid_dari_port(port: int) -> int:
    """Cari PID yang sedang mendengarkan sebuah port (bila catatan keadaan tidak ada)."""
    try:
        if os.name == "nt":
            hasil = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                   text=True, errors="replace", creationflags=tanpa_jendela())
            for baris in (hasil.stdout or "").splitlines():
                bagian = baris.split()
                if len(bagian) >= 5 and bagian[1].endswith(f":{port}") and bagian[3] == "LISTENING":
                    return int(bagian[4])
        else:
            hasil = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True)
            for baris in (hasil.stdout or "").splitlines():
                if f":{port}" in baris and "pid=" in baris:
                    potong = baris.split("pid=")[1].split(",")[0]
                    return int(potong)
    except Exception:      # noqa: BLE001 — pencarian tambahan saja
        pass
    return 0


def buka_peramban(port: int) -> None:
    import webbrowser

    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:      # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Perintah
# --------------------------------------------------------------------------- #
def jalankan(args) -> int:
    """Jalankan server di belakang layar (tanpa jendela), lalu buka peramban."""
    if args.tampak:
        # Menjalankan langsung di jendela ini: berguna saat mencari masalah.
        os.environ.setdefault("SM_DATA_DIR", str(_data_dir()))
        return subprocess.call([str(_python_server()), "run.py", "--port", str(args.port)],
                               cwd=str(BASE_DIR))

    keadaan = baca_keadaan()
    port = args.port or int(keadaan.get("port") or PORT_BAWAAN)
    if keadaan.get("pid") and pid_hidup(int(keadaan["pid"])) and alamat_menjawab(port):
        print(f"SM sudah berjalan (pid {keadaan['pid']}, http://localhost:{port}).")
        if not args.tanpa_buka:
            buka_peramban(port)
        return 0
    if port_terpakai(port) and not alamat_menjawab(port):
        # Port dipakai program lain → pakai port bebas berikutnya supaya tidak gagal diam-diam.
        for kandidat in range(port + 1, port + 20):
            if not port_terpakai(kandidat):
                print(f"Port {port} dipakai program lain — memakai port {kandidat}.")
                port = kandidat
                break
        else:
            print(f"[!] Port {port} dan sekitarnya sedang dipakai program lain.", file=sys.stderr)
            return 1

    log = berkas_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    python = _python_latar()
    lingkungan = dict(os.environ, SM_DATA_DIR=str(_data_dir()), PYTHONUTF8="1",
                      PYTHONIOENCODING="utf-8")
    lingkungan.pop("SM_DB_PATH", None)
    with open(log, "a", encoding="utf-8") as keluaran:
        keluaran.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} menjalankan SM "
                       f"di http://localhost:{port} =====\n")
        proses = subprocess.Popen(
            [str(python), str(BASE_DIR / "run.py"), "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(BASE_DIR), stdout=keluaran, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=lingkungan, creationflags=tanpa_jendela(),
            start_new_session=(os.name != "nt"))
    tulis_keadaan({"pid": proses.pid, "port": port, "mulai": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "log": str(log), "python": str(python)})

    batas = time.time() + 90
    while time.time() < batas:
        if proses.poll() is not None:
            print("[!] Aplikasi berhenti saat mulai. Isi catatan terakhir:", file=sys.stderr)
            try:
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]),
                      file=sys.stderr)
            except OSError:
                pass
            hapus_keadaan()
            return 1
        if alamat_menjawab(port):
            print(f"SM berjalan di http://localhost:{port} (pid {proses.pid}).")
            print(f"Catatan aplikasi: {log}")
            if not args.tanpa_buka:
                buka_peramban(port)
            return 0
        time.sleep(0.7)
    print(f"[!] Aplikasi belum menjawab setelah 90 detik. Periksa {log}", file=sys.stderr)
    return 1


def hentikan(_args) -> int:
    """Matikan aplikasi yang sedang berjalan (tanpa jendela apa pun)."""
    keadaan = baca_keadaan()
    port = int(keadaan.get("port") or PORT_BAWAAN)
    pid = int(keadaan.get("pid") or 0) or pid_dari_port(port)
    if not pid:
        print("Tidak ada aplikasi SM yang sedang berjalan.")
        hapus_keadaan()
        return 0
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       text=True, errors="replace", creationflags=tanpa_jendela())
    else:
        for sinyal in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sinyal)
            except OSError:
                break
            time.sleep(1.2)
            if not pid_hidup(pid):
                break
    time.sleep(1.0)
    sisa = pid_hidup(pid)
    hapus_keadaan()
    print(f"Aplikasi SM (pid {pid}) {'masih menutup' if sisa else 'sudah dimatikan'}."
          f" Data sekolah di {_data_dir()} tidak dihapus.")
    return 0 if not sisa else 1


def status(args) -> int:
    """Keadaan aplikasi: berjalan atau tidak, di port berapa, sejak kapan."""
    keadaan = baca_keadaan()
    port = int(args.port or keadaan.get("port") or PORT_BAWAAN)
    pid = int(keadaan.get("pid") or 0)
    hidup = bool(pid and pid_hidup(pid)) or port_terpakai(port)
    data = {
        "berjalan": hidup,
        "menjawab": alamat_menjawab(port) if hidup else False,
        "pid": pid or pid_dari_port(port),
        "port": port,
        "alamat": f"http://localhost:{port}",
        "mulai": keadaan.get("mulai", ""),
        "data": str(_data_dir()),
        "log": str(berkas_log()),
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print("=" * 60)
        print("  SM — keadaan aplikasi")
        print("=" * 60)
        print(f"  Berjalan    : {'ya' if data['berjalan'] else 'tidak'}")
        print(f"  Menjawab    : {'ya' if data['menjawab'] else 'belum'}")
        print(f"  Alamat      : {data['alamat']}")
        print(f"  PID         : {data['pid'] or '—'}")
        print(f"  Mulai       : {data['mulai'] or '—'}")
        print(f"  Folder data : {data['data']}")
        print(f"  Catatan     : {data['log']}")
    return 0 if data["berjalan"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="SM-latar.py",
        description="Menjalankan aplikasi SM di belakang layar (tanpa jendela terminal).")
    parser.add_argument("--port", type=int, help=f"port aplikasi (bawaan {PORT_BAWAAN})")
    parser.add_argument("--tanpa-buka", action="store_true", help="jangan buka peramban")
    parser.add_argument("--tampak", action="store_true",
                        help="jalankan di jendela ini (untuk mencari masalah)")
    parser.add_argument("--hentikan", action="store_true", help="matikan aplikasi yang berjalan")
    parser.add_argument("--status", action="store_true", help="tampilkan keadaan aplikasi")
    parser.add_argument("--json", action="store_true", help="keluaran JSON (untuk --status)")
    args = parser.parse_args(argv)

    if args.hentikan:
        return hentikan(args)
    if args.status:
        return status(args)
    return jalankan(args)


if __name__ == "__main__":
    raise SystemExit(main())
