#!/usr/bin/env python3
"""Menyiapkan isi paket bodap (``payload/``) — dipakai sebelum ``bodap.exe`` dibangun.

Isi yang dibuat:

| Berkas | Guna |
| --- | --- |
| ``payload/app.zip`` | seluruh program SM (tanpa data siswa, tanpa ``.venv``/``.git``) |
| ``payload/VERSI.txt`` | versi bodap (tampil di wizard & log) |
| ``payload/python-embed.zip`` | Python bawaan Windows (``--dengan-python``) |
| ``payload/bootstrap/*.whl`` | pip, setuptools, wheel — untuk menanam pip tanpa internet |
| ``payload/wheels/*.whl`` | seluruh pustaka aplikasi (``--dengan-bahan``) → pasang tanpa internet |

Contoh::

    python pemasang/buat_payload.py                    # app.zip + bootstrap (perlu internet)
    python pemasang/buat_payload.py --dengan-python    # + Python bawaan Windows
    python pemasang/buat_payload.py --dengan-python --dengan-bahan \\
        --untuk-python 3.12 --untuk-platform win_amd64
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
PAYLOAD = AKAR / "pemasang" / "payload"

#: Sama dengan aturan pemasang: data pengguna & sisa pengembangan tidak pernah ikut.
ABAIKAN_FOLDER = {
    ".git", ".venv", "venv", "env", "data", "sample-data", "node_modules", "payload",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    "dist", "build",
}
ABAIKAN_POLA = (
    "*.pyc", "*.pyo", "*.sqlite3*", "*.log", ".env", "secrets.env",
    "*.xlsx", "*.xls", "*.xlsb", "*.ods",
    "laporan-python.txt", "SM-*-paket.zip", "bodap.exe",
)
PENGECUALIAN_POLA = ("template-import/*",)

#: Pustaka yang harus ada di paket agar pip bisa ditanam tanpa internet.
BOOTSTRAP = ("pip", "setuptools", "wheel")

#: Berkas permintaan pustaka milik aplikasi — inilah sumber kebenaran versinya.
#: Sengaja TIDAK memakai daftar nama yang ditulis tangan: dulu itu membuat berkas pustaka
#: bawaan berisi versi terbaru (mis. python-multipart 0.0.32) padahal aplikasi meminta versi
#: yang dipatok (0.0.20) — pemasangan tanpa internet jadi gagal walau internet tersedia.
BERKAS_REQ = ("requirements.txt", "requirements-bot.txt")

PYTHON_EMBED_RILIS = "3.12.8"


def _cetak(pesan: str) -> None:
    print(pesan, flush=True)


def _abaikan(direktori: str, nama_nama: list[str]) -> list[str]:
    buang = []
    for nama in nama_nama:
        if nama in ABAIKAN_FOLDER:
            buang.append(nama)
            continue
        if any(fnmatch.fnmatch(nama, pola) for pola in ABAIKAN_POLA):
            relatif = (Path(direktori) / nama).relative_to(AKAR).as_posix()
            if any(fnmatch.fnmatch(relatif, kec) for kec in PENGECUALIAN_POLA):
                continue
            buang.append(nama)
    return buang


def buat_app_zip() -> Path:
    """Bungkus seluruh program SM menjadi ``payload/app.zip``."""
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    sasaran = PAYLOAD / "app.zip"
    berkas = 0
    with zipfile.ZipFile(sasaran, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        # pemasang/bodap.exe tidak perlu ikut ke dalam paket (ukurannya besar & tidak dipakai)
        for jalur in sorted(AKAR.rglob("*")):
            if jalur.is_dir():
                continue
            relatif = jalur.relative_to(AKAR)
            if any(bagian in ABAIKAN_FOLDER for bagian in relatif.parts[:-1]):
                continue
            if any(fnmatch.fnmatch(jalur.name, pola) for pola in ABAIKAN_POLA) and not any(
                    fnmatch.fnmatch(relatif.as_posix(), kec) for kec in PENGECUALIAN_POLA):
                continue
            if relatif.as_posix() == "pemasang/bodap.spec":
                # ikut disertakan (kecil) supaya pengguna bisa membangun ulang sendiri
                pass
            z.write(jalur, relatif.as_posix())
            berkas += 1
    ukuran = sasaran.stat().st_size / 1024
    _cetak(f"  app.zip      : {berkas} berkas, {ukuran:.0f} KB")
    return sasaran


def _unduh(alamat: str, sasaran: Path) -> bool:
    sasaran.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(alamat, timeout=120) as jawab, open(sasaran, "wb") as keluar:
            shutil.copyfileobj(jawab, keluar)
        return sasaran.stat().st_size > 1024
    except Exception as exc:      # noqa: BLE001 — dikembalikan ke pemanggil
        _cetak(f"  [!] gagal mengunduh {alamat}: {type(exc).__name__}: {exc}")
        sasaran.unlink(missing_ok=True)
        return False


def ambil_bootstrap() -> int:
    """pip/setuptools/wheel (py3-none-any) ke ``payload/bootstrap`` — supaya pip bisa ditanam."""
    import tempfile

    folder = PAYLOAD / "bootstrap"
    folder.mkdir(parents=True, exist_ok=True)
    jumlah = 0
    with tempfile.TemporaryDirectory(prefix="sm-bootstrap-") as tmp:
        for nama in BOOTSTRAP:
            hasil = subprocess.run(
                [sys.executable, "-m", "pip", "download", "--dest", tmp, "--no-deps",
                 "--only-binary=:all:", "--disable-pip-version-check", "--quiet", nama],
                capture_output=True, text=True, timeout=1200)
            if hasil.returncode != 0:
                _cetak(f"  [!] {nama} gagal diunduh: {(hasil.stderr or '').strip()[-200:]}")
                continue
        for berkas in sorted(Path(tmp).glob("*.whl")):
            shutil.copy2(berkas, folder / berkas.name)
            jumlah += 1
    if jumlah:
        _cetak(f"  bootstrap    : {jumlah} berkas (pip, setuptools, wheel)")
    return jumlah


def _pin_permintaan() -> list[tuple[str, str]]:
    """Daftar (nama, permintaan) dari ``requirements*.txt`` — mis. ``("odfpy", "odfpy==1.4.1")``."""
    hasil: list[tuple[str, str]] = []
    for nama_berkas in BERKAS_REQ:
        berkas = AKAR / nama_berkas
        if not berkas.exists():
            continue
        for baris in berkas.read_text(encoding="utf-8").splitlines():
            baris = baris.split("#", 1)[0].strip()
            if not baris or baris.startswith("-"):
                continue
            nama = re.split(r"[<>=!~\[]", baris, 1)[0].strip()
            if nama:
                hasil.append((nama, baris))
    return hasil


def _pip_download(tujuan: Path, argumen: list[str], waktu: int = 3600) -> bool:
    perintah = [sys.executable, "-m", "pip", "download", "--dest", str(tujuan),
                "--disable-pip-version-check", "--quiet", *argumen]
    hasil = subprocess.run(perintah, capture_output=True, text=True, timeout=waktu)
    if hasil.returncode != 0:
        pesan = (hasil.stderr or hasil.stdout or "").strip().splitlines()
        if pesan:
            _cetak("        " + pesan[-1][:160])
    return hasil.returncode == 0


def _berkas_cocok(folder: Path, nama: str, versi: str = "") -> bool:
    """Apakah ``folder`` sudah memuat berkas pustaka untuk ``nama`` (opsional versi tertentu)."""
    pola = nama.lower().replace("_", "-").replace("-", "[-_]")
    cocok = [p for p in folder.iterdir()
             if re.match(rf"^{pola}-", p.name.lower().replace("_", "-"))]
    if not versi:
        return bool(cocok)
    return any(re.match(rf"^{pola}-{re.escape(versi)}[-.]", p.name.lower().replace("_", "-"))
               for p in cocok)


def _keperluan_sumber(berkas: Path) -> list[str]:
    """Nama pustaka yang dibutuhkan sebuah berkas kode sumber.

    Dibaca dari tiga tempat, karena tidak semuanya lengkap: ``PKG-INFO``/``METADATA``
    (``Requires-Dist``), lalu ``setup.py``/``setup.cfg``/``pyproject.toml``
    (``install_requires``/``dependencies``) — inilah yang melewatkan ``defusedxml`` milik
    ``odfpy``: metadatanya kosong, tetapi ``setup.py``-nya memintanya.
    """
    import tarfile

    nama: list[str] = []
    try:
        with tarfile.open(berkas) as tar:
            for info in tar.getmembers():
                if not info.isfile():
                    continue
                pendek = info.name.rsplit("/", 1)[-1]
                if pendek not in ("PKG-INFO", "METADATA", "setup.py", "setup.cfg",
                                  "pyproject.toml"):
                    continue
                isi = tar.extractfile(info).read().decode("utf-8", "replace")
                nama += _nama_dari_teks_metadata(isi)
    except (tarfile.TarError, OSError, AttributeError):
        return []
    keluaran: list[str] = []
    for satu in nama:
        bersih = satu.strip()
        if bersih and bersih not in keluaran:
            keluaran.append(bersih)
    return keluaran


def _nama_dari_teks_metadata(isi: str) -> list[str]:
    """Ambil nama pustaka dari teks metadata (``Requires-Dist``/``install_requires``/…)."""
    hasil: list[str] = []
    for baris in isi.splitlines():
        if baris.lower().startswith("requires-dist:"):
            hasil.append(baris.split(":", 1)[1])
    for kunci in ("install_requires", "dependencies", "requires"):
        posisi = isi.find(kunci)
        while posisi >= 0:
            potong = isi.find("[", posisi)
            if potong < 0:
                break
            dalam = isi.find("]", potong)
            if dalam < 0:
                break
            isi_daftar = isi[potong + 1:dalam]
            hasil += re.findall(r"['\"]([A-Za-z0-9_.\-]+)", isi_daftar)
            posisi = isi.find(kunci, dalam)
    bersih: list[str] = []
    for satu in hasil:
        nama = re.split(r"[<>=!~;,\s\[\]]", satu.strip(), 1)[0].strip()
        if nama and nama.lower() not in ("python",) and nama not in bersih:
            bersih.append(nama)
    return bersih


def ambil_wheels(untuk_python: str, untuk_platform: str) -> int:
    """Seluruh pustaka aplikasi ke ``payload/wheels`` → pemasangan bisa tanpa internet.

    Versinya diambil dari ``requirements.txt``/``requirements-bot.txt`` (persis yang diminta
    aplikasi), bukan daftar nama. Untuk paket yang hanya ada sebagai kode sumber (mis.
    ``odfpy``), berkas sumbernya diunduh beserta keperluannya supaya bisa dibangun saat
    pemasangan tanpa internet.
    """
    folder = PAYLOAD / "wheels"
    folder.mkdir(parents=True, exist_ok=True)
    flags: list[str] = []
    if untuk_platform:
        flags += ["--platform", untuk_platform]
    if untuk_python:
        flags += ["--python-version", untuk_python]
    batas = flags + ["--only-binary=:all:"]

    _cetak(f"  Mengunduh pustaka aplikasi ({untuk_platform or 'platform ini'}, "
           f"Python {untuk_python or 'versi ini'}) dari {', '.join(BERKAS_REQ)} ...")

    # 1) cara utama: seluruh berkas permintaan sekaligus (versi ikut apa yang dipatok aplikasi)
    if not _pip_download(folder, batas + ["-r", "requirements.txt"]
                         + (["-r", "requirements-bot.txt"] if (AKAR / "requirements-bot.txt").exists()
                            else [])):
        _cetak("      Ada pustaka yang tidak punya berkas siap-pasang untuk platform tujuan "
               "— diunduh satu per satu ...")
        # 2) satu per satu: supaya satu pustaka bermasalah tidak menggagalkan semuanya
        for nama, permintaan in _pin_permintaan():
            versi = permintaan.split("==", 1)[1] if "==" in permintaan else ""
            if _berkas_cocok(folder, nama, versi):
                continue
            if _pip_download(folder, batas + [permintaan]):
                continue
            # 3) belum ada: coba berkas sumbernya (tanpa keperluan), lalu keperluannya menyusul
            if _pip_download(folder, flags + ["--no-deps", "--no-binary", ":none:", permintaan]):
                # Berkas kode sumber ikut dibawa + keperluannya (rekursif, maksimal 3 lapis)
                antre = [p for p in sorted(folder.iterdir())
                         if p.name.endswith((".tar.gz", ".zip"))
                         and p.name.lower().startswith(nama.lower().replace("_", "-").split("==")[0])]
                lapis = 0
                while antre and lapis < 3:
                    lapis += 1
                    berikutnya: list[Path] = []
                    for berkas in antre:
                        for keperluan in _keperluan_sumber(berkas):
                            if _berkas_cocok(folder, keperluan):
                                continue
                            if _pip_download(folder, batas + [keperluan]):
                                continue
                            if _pip_download(folder, flags + ["--no-deps", "--no-binary",
                                                              ":none:", keperluan]):
                                berikutnya += [p for p in sorted(folder.iterdir())
                                               if p.name.endswith((".tar.gz", ".zip"))
                                               and p.name.lower().startswith(
                                                   keperluan.lower().replace("_", "-"))]
                                _cetak(f"        {keperluan} dibawa sebagai kode sumber "
                                       "(dibangun saat pemasangan)")
                    antre = berikutnya
                continue
            _cetak(f"      [!] {permintaan} tidak bisa diunduh untuk platform tujuan "
                   "(akan diunduh saat pemasangan, perlu internet).")

    # 4) pip/setuptools/wheel ikut disalin: dibutuhkan saat membangun pustaka dari kode sumber
    #    tanpa internet (build isolation).
    for berkas in (PAYLOAD / "bootstrap").glob("*.whl"):
        if not (folder / berkas.name).exists():
            shutil.copy2(berkas, folder / berkas.name)

    # 5) periksa: setiap pin aplikasi harus punya berkasnya — yang kurang dicatat terang-terangan
    kurang: list[str] = []
    for nama, permintaan in _pin_permintaan():
        versi = permintaan.split("==", 1)[1] if "==" in permintaan else ""
        if not _berkas_cocok(folder, nama, versi):
            kurang.append(f"{permintaan} ({nama}: berkas untuk platform {untuk_platform or 'ini'}"
                          f" / Python {untuk_python or 'ini'} tidak tersedia sebagai paket siap-pasang"
                          " — akan diunduh saat pemasangan, perlu internet)")
    (PAYLOAD / "wheels-terlewat.txt").write_text(
        "\n".join(kurang) + ("\n" if kurang else ""), encoding="utf-8")

    berkas = sorted(p for p in folder.iterdir() if p.suffix in (".whl", ".gz", ".zip"))
    ukuran = sum(p.stat().st_size for p in berkas) / 1024 / 1024
    _cetak(f"  wheels       : {len(berkas)} berkas, {ukuran:.0f} MB"
           + (f", {len(kurang)} pustaka perlu internet" if kurang else " (lengkap)"))
    if kurang:
        for baris in kurang:
            _cetak(f"      ! {baris}")
    return len(berkas)


def ambil_python_embed() -> bool:
    """Python bawaan Windows (embeddable) ke ``payload/python-embed.zip``."""
    for arsitektur in ("amd64", "win32"):
        nama = f"python-{PYTHON_EMBED_RILIS}-embed-{arsitektur}.zip"
        alamat = f"https://www.python.org/ftp/python/{PYTHON_EMBED_RILIS}/{nama}"
        sasaran = PAYLOAD / "python-embed.zip"
        _cetak(f"  Mengunduh {nama} ...")
        if _unduh(alamat, sasaran):
            _cetak(f"  python-embed : {sasaran.stat().st_size / 1024 / 1024:.1f} MB ({arsitektur})")
            return True
    _cetak("  [!] Python bawaan tidak bisa diunduh. bodap.exe tetap bisa dibangun, tetapi "
           "komputer tujuan harus sudah punya Python 3.10+ (atau mengizinkan unduhan saat "
           "pemasangan).")
    return False


def tulis_versi() -> str:
    versi = "0.1.0"
    try:
        for baris in (AKAR / "app" / "config.py").read_text(encoding="utf-8").splitlines():
            if baris.strip().startswith("APP_VERSION"):
                versi = baris.split("=", 1)[1].strip().strip('"\'')
                break
    except OSError:
        pass
    isi = f"{versi} (bodap {time.strftime('%Y-%m-%d')})"
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    (PAYLOAD / "VERSI.txt").write_text(isi + "\n", encoding="utf-8")
    (AKAR / "pemasang" / "BODAP_VERSI.txt").write_text(isi + "\n", encoding="utf-8")
    _cetak(f"  versi        : {isi}")
    return versi


def buat(args) -> dict:
    global PAYLOAD
    if getattr(args, "keluar", None):
        PAYLOAD = Path(args.keluar).expanduser().resolve()
    _cetak(f"Menyiapkan payload bodap di {PAYLOAD} ...")
    versi = tulis_versi()
    app = buat_app_zip()
    bootstrap = ambil_bootstrap()
    python_ada = ambil_python_embed() if args.dengan_python else False
    wheels = (ambil_wheels(args.untuk_python, args.untuk_platform) if args.dengan_bahan else 0)
    ukuran = sum(p.stat().st_size for p in PAYLOAD.rglob("*") if p.is_file()) / 1024 / 1024
    _cetak(f"Selesai: payload {ukuran:.1f} MB "
           f"(app.zip, bootstrap {bootstrap}, python bawaan {'ada' if python_ada else 'tidak ada'}"
           f"{f', wheels {wheels}' if wheels else ''})")
    return {"ok": True, "versi": versi, "app_zip": str(app), "bootstrap": bootstrap,
            "python_embed": python_ada, "wheels": wheels, "ukuran_mb": round(ukuran, 1)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Menyiapkan payload bodap (app.zip, Python, wheels)")
    p.add_argument("--dengan-python", action="store_true",
                   help="sertakan Python bawaan Windows (perlu internet)")
    p.add_argument("--dengan-bahan", action="store_true",
                   help="sertakan seluruh pustaka (.whl) supaya bisa dipasang tanpa internet")
    p.add_argument("--untuk-python", default="3.12", help="versi Python tujuan (bawaan 3.12)")
    p.add_argument("--untuk-platform", default="win_amd64",
                   help="platform tujuan (bawaan win_amd64)")
    p.add_argument("--keluar", help="folder payload lain (mis. untuk uji)")
    args = p.parse_args(argv)
    hasil = buat(args)
    return 0 if hasil.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
