#!/usr/bin/env python3
"""Uji menyeluruh untuk **bodap** — pemasang SM satu berkas (``bodap.exe``).

Yang diuji di sini (semuanya nyata, bukan tiruan):

1. ikon ``bodap.ico`` benar-benar terbentuk & isinya sah (7 ukuran, format ICO);
2. ``buat_payload.py`` menyiapkan ``payload/`` (``app.zip`` bersih dari data siswa + pip);
3. **uji mandiri bodap** — ``bodap_win.py --uji``: memasang ke folder sementara, memeriksa
   berkas hasil, **menjalankan aplikasinya sampai halaman utama menjawab HTTP**, menjalankan
   ``--periksa``, lalu ``--hapus`` dan memastikan **folder data di luar aplikasi tetap ada**;
4. berkas pembangunan Windows ada & sah: ``bodap.spec`` (bisa dikompilasi),
   ``BUAT-BODAP.bat``, dan alur GitHub Actions (``.github/workflows/bodap-windows.yml``)
   yang membangun ``bodap.exe`` di runner Windows lalu menjalankan uji ini juga.

Jalankan::

    python scripts/uji_bodap.py              # lengkap (perlu internet: memasang pustaka)
    python scripts/uji_bodap.py --cepat      # lewati pemasangan pustaka (pakai Python ini)
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
PEMASANG = AKAR / "pemasang"
HASIL: list[tuple[str, bool, str]] = []


def cek(nama: str, syarat: bool, keterangan: str = "") -> None:
    HASIL.append((nama, bool(syarat), keterangan if not syarat else ""))
    print(f"[{'  OK  ' if syarat else ' GAGAL'}] {nama}"
          + ("" if syarat or not keterangan else f" — {keterangan}"), flush=True)


def jalankan(perintah: list[str], waktu: int = 1800, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(p) for p in perintah], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=waktu, **kwargs)


def uji_ikon() -> None:
    import importlib.util

    with tempfile.TemporaryDirectory(prefix="bodap-ikon-") as tmp:
        sasaran = Path(tmp) / "bodap.ico"
        spesifikasi = importlib.util.spec_from_file_location("buat_ikon", PEMASANG / "buat_ikon.py")
        modul = importlib.util.module_from_spec(spesifikasi)
        spesifikasi.loader.exec_module(modul)
        sasaran.write_bytes(modul.buat_ico())
        isi = sasaran.read_bytes()
        jumlah = struct.unpack("<HHH", isi[:6])[2]
        ukuran = sorted(struct.unpack("<BBBBHHII", isi[6 + 16 * i:22 + 16 * i])[0] or 256
                        for i in range(jumlah))
        cek("Ikon bodap.ico sah (7 ukuran: 16–256)", jumlah == 7 and ukuran[0] == 16
            and ukuran[-1] == 256, f"jumlah={jumlah} ukuran={ukuran}")
        png = sasaran.with_suffix(".png").read_bytes() if sasaran.with_suffix(".png").exists() else b""
        modul.main([str(sasaran)])
        png = sasaran.with_suffix(".png").read_bytes()
        cek("Ikon PNG ikut dibuat (pratinjau/dokumen)",
            png.startswith(b"\x89PNG") and sasaran.stat().st_size > 10_000,
            f"png={len(png)} byte")


def uji_payload() -> dict:
    hasil = jalankan([sys.executable, str(PEMASANG / "buat_payload.py")], waktu=1800)
    cek("buat_payload.py berjalan", hasil.returncode == 0,
        (hasil.stderr or hasil.stdout or "")[-400:])
    sasaran = PEMASANG / "payload"
    zip_program = sasaran / "app.zip"
    cek("payload/app.zip terbentuk", zip_program.exists(),
        f"{zip_program} tidak ada")
    if not zip_program.exists():
        return {}
    import zipfile

    with zipfile.ZipFile(zip_program) as z:
        nama = z.namelist()
    wajib = {"run.py", "requirements.txt", "app/main.py", "pemasang/pasang.py",
             "pemasang/buat_paket.py", "template-import/contoh-template-import.xlsx"}
    cek("app.zip memuat seluruh program SM", wajib.issubset(set(nama)),
        f"kurang: {sorted(wajib - set(nama))}")
    terlarang = [n for n in nama
                 if n.startswith(("data/", "sample-data/", ".venv/", "pemasang/payload/"))
                 or n.endswith((".sqlite3", ".pyc"))
                 or (n.endswith((".xlsx", ".xls", ".ods"))
                     and "template-import/" not in n)]
    cek("app.zip bersih dari data siswa & sisa pengembangan", not terlarang,
        f"terlarang: {terlarang[:4]}")
    roda = list((sasaran / "bootstrap").glob("*.whl"))
    cek("pip bawaan ada di payload/bootstrap (untuk menanam pip tanpa internet)",
        len(roda) >= 2, f"{len(roda)} berkas")
    return {"app_zip": str(zip_program), "berkas": len(nama), "bootstrap": len(roda)}


def uji_bodap_uji(cepat: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="bodap-laporan-") as tmp:
        laporan = Path(tmp) / "hasil-uji.json"
        perintah = [sys.executable, str(PEMASANG / "bodap_win.py"), "--uji",
                    "--laporan", str(laporan), "--diam", "--tanpa-pintasan"]
        if cepat:
            perintah.append("--python-komputer")
        hasil = jalankan(perintah, waktu=3000)
        keluaran = (hasil.stdout or "")[-1500:]
        cek("bodap --uji berjalan tanpa galat", hasil.returncode == 0,
            (hasil.stderr or keluaran)[-500:])
        cek("bodap --uji menulis laporan JSON", laporan.exists(),
            f"{laporan} tidak dibuat")
        data = {}
        if laporan.exists():
            data = json.loads(laporan.read_text(encoding="utf-8"))
        diperiksa = data.get("pemeriksaan") or []
        gagal = data.get("gagal") or []
        cek(f"bodap --uji: {len(diperiksa)} pemeriksaan internal lolos", bool(diperiksa) and not gagal,
            f"gagal: {gagal[:3]}")
        gabung = " | ".join(diperiksa)
        cek("bodap --uji: aplikasi hasil pemasangan menjawab HTTP",
            "menjawab HTTP 2" in gabung or "menjawab HTTP 3" in gabung,
            gabung[:200])
        cek("bodap --uji: data di luar folder aplikasi selamat saat hapus",
            "membiarkan folder data di luar aplikasi" in gabung, gabung[:200])
        cek("bodap --uji: peluncur latar (SM.vbs → SM-latar.py) ikut terpasang",
            "berkas peluncur latar: SM-latar.py" in gabung
            and "jendela konsol disembunyikan" in gabung, gabung[:300])
        cek("bodap --uji: aplikasi jalan di belakang layar lalu bisa dihentikan",
            "menjalankan aplikasi di belakang layar" in gabung
            and "benar-benar berhenti setelah --hentikan" in gabung, gabung[:300])
        cek("bodap --uji: basis data hasil pasang kosong (fresh)",
            "basis data hasil pemasangan kosong (fresh)" in gabung, gabung[:300])
        return {"pemeriksaan": len(diperiksa), "gagal": len(gagal)}


def _pin_aplikasi() -> list[tuple[str, str]]:
    """(nama, versi) yang dipatok berkas permintaan aplikasi."""
    pin: list[tuple[str, str]] = []
    for nama_berkas in ("requirements.txt", "requirements-bot.txt"):
        berkas = AKAR / nama_berkas
        if not berkas.exists():
            continue
        for baris in berkas.read_text(encoding="utf-8").splitlines():
            baris = baris.split("#", 1)[0].strip()
            if not baris or baris.startswith("-") or "==" not in baris:
                continue
            nama, versi = baris.split("==", 1)
            pin.append((nama.strip().split("[")[0], versi.strip().split(";")[0].strip()))
    return pin


def uji_pustaka_bawaan_cocok() -> dict:
    """Berkas pustaka bawaan harus berisi versi yang PERSIS dipatok aplikasi."""
    with tempfile.TemporaryDirectory(prefix="bodap-wheels-") as tmp:
        payload = Path(tmp) / "payload"
        hasil = jalankan([sys.executable, str(PEMASANG / "buat_payload.py"), "--keluar",
                          str(payload), "--dengan-bahan", "--untuk-python", "",
                          "--untuk-platform", ""], waktu=3000)
        cek("buat_payload --dengan-bahan berjalan", hasil.returncode == 0,
            (hasil.stderr or hasil.stdout or "")[-400:])
        roda = payload / "wheels"
        berkas = sorted(p.name.lower().replace("_", "-")
                        for p in roda.glob("*") if p.suffix in (".whl", ".gz", ".zip")) \
            if roda.is_dir() else []
        kurang: list[str] = []
        for nama, versi in _pin_aplikasi():
            pola = nama.lower().replace("_", "-")
            if not any(b.startswith(f"{pola}-{versi}") for b in berkas):
                kurang.append(f"{nama}=={versi}")
        cek(f"berkas pustaka bawaan memuat SEMUA versi yang dipatok aplikasi "
            f"({len(_pin_aplikasi())} pin)", not kurang, f"kurang: {kurang}")
        terlewat = payload / "wheels-terlewat.txt"
        isi_terlewat = terlewat.read_text(encoding="utf-8").strip() if terlewat.exists() else ""
        cek("tidak ada pustaka yang ditandai «perlu internet»", not isi_terlewat,
            isi_terlewat[:200])
        return {"wheels": len(berkas), "kurang": len(kurang)}


def uji_pustaka_bawaan_tidak_cocok() -> dict:
    """Berkas bawaan yang tidak cocok TIDAK boleh menggagalkan pemasangan selama ada internet."""
    import shutil as _shutil

    sumber = PEMASANG / "payload"
    if not (sumber / "app.zip").exists():
        cek("payload tersedia untuk uji berkas bawaan tidak cocok", False,
            "jalankan buat_payload.py lebih dulu")
        return {}
    with tempfile.TemporaryDirectory(prefix="bodap-salah-") as tmp:
        tmp = Path(tmp)
        salah = tmp / "payload"
        _shutil.copytree(sumber, salah, dirs_exist_ok=True)
        roda = salah / "wheels"
        if roda.is_dir():
            _shutil.rmtree(roda)
        roda.mkdir(parents=True, exist_ok=True)
        # berkas bawaan yang sengaja salah versi (seperti yang terjadi di PC sekolah)
        unduh = jalankan([sys.executable, "-m", "pip", "download", "--dest", str(roda),
                          "--no-deps", "--quiet", "python-multipart==0.0.32"], waktu=900)
        cek("berkas bawaan palsu (versi salah) siap dipakai uji",
            unduh.returncode == 0 and any(roda.glob("*.whl")),
            (unduh.stderr or "")[-200:])

        laporan = tmp / "hasil.json"
        hasil = jalankan([sys.executable, str(PEMASANG / "bodap_win.py"), "--uji",
                          "--payload", str(salah), "--laporan", str(laporan), "--diam",
                          "--tanpa-pintasan", "--dengan-bot"], waktu=3000)
        data = json.loads(laporan.read_text(encoding="utf-8")) if laporan.exists() else {}
        gabung = " | ".join(data.get("pemeriksaan") or []) + " | " + " | ".join(data.get("catatan") or [])
        cek("pemasangan tetap berhasil walau berkas bawaan tidak cocok", hasil.returncode == 0,
            (hasil.stderr or "")[-400:])
        cek("log menyebut berkas bawaan tidak cocok & dilanjutkan dari internet",
            "belum cukup untuk versi yang diminta" in gabung
            and "dilanjutkan dengan unduhan internet" in gabung, gabung[:300])
        cek("aplikasi hasil pemasangan menjawab HTTP setelah jatuh ke internet",
            "menjawab HTTP 2" in gabung or "menjawab HTTP 3" in gabung, gabung[:300])
        return {"jatuh_ke_internet": "dilanjutkan dengan unduhan internet" in gabung}


def uji_periksa_dan_hapus() -> None:
    with tempfile.TemporaryDirectory(prefix="bodap-periksa-") as tmp:
        tujuan = Path(tmp) / "belum-ada"
        hasil = jalankan([sys.executable, str(PEMASANG / "bodap_win.py"), "--periksa",
                          "--tujuan", str(tujuan), "--json"], waktu=300)
        keluaran = [b for b in (hasil.stdout or "").splitlines() if b.startswith("{")]
        laporan = json.loads(keluaran[-1]) if keluaran else {}
        cek("bodap --periksa melaporkan «belum terpasang» dengan benar",
            laporan.get("terpasang") is False and laporan.get("ok") is False,
            f"keluaran: {keluaran[-1][:200] if keluaran else hasil.stderr[-200:]}")
        cek("bodap --periksa tidak membuat folder apa pun", not tujuan.exists())


def uji_berkas_pembangunan() -> None:
    for nama in ("bodap_win.py", "bodap.spec", "buat_payload.py", "buat_ikon.py",
                 "BUAT-BODAP.bat", "pasang.py", "buat_paket.py",
                 "ci/bodap-windows.yml", "PANDUAN-BODAP.md"):
        cek(f"berkas pemasang ada: pemasang/{nama}", (PEMASANG / nama).exists())
    try:
        ast.parse((PEMASANG / "bodap.spec").read_text(encoding="utf-8"))
        sah = True
    except SyntaxError as exc:
        sah = False
        print("      ", exc)
    cek("bodap.spec bisa dikompilasi (siap dipakai PyInstaller)", sah)
    spec = (PEMASANG / "bodap.spec").read_text(encoding="utf-8")
    cek("bodap.spec memuat payload, ikon, dan mode tanpa jendela konsol",
        "payload" in spec and "bodap.ico" in spec and "console=False" in spec)
    alur = AKAR / ".github" / "workflows" / "bodap-windows.yml"
    if not alur.exists():
        alur = PEMASANG / "ci" / "bodap-windows.yml"
    cek("alur GitHub Actions untuk bodap.exe ada", alur.exists(),
        "tidak ada di .github/workflows maupun pemasang/ci")
    if alur.exists():
        isi = alur.read_text(encoding="utf-8")
        cek("alur memakai runner Windows, membangun spec, & mengunggah artifact",
            "windows-latest" in isi and "bodap.spec" in isi and "upload-artifact" in isi
            and "--uji" in isi)
    hasil = jalankan([sys.executable, str(PEMASANG / "bodap_win.py"), "--help"], waktu=300)
    cek("bodap_win.py --help berjalan (argumen lengkap)", hasil.returncode == 0
        and "--sunyi" in (hasil.stdout or ""), (hasil.stderr or "")[-300:])


def main() -> int:
    parser = argparse.ArgumentParser(description="Uji menyeluruh pemasang bodap")
    parser.add_argument("--cepat", action="store_true",
                        help="lewati pemasangan pustaka & uji berkas pustaka bawaan "
                             "(pakai Python yang menjalankan uji)")
    args = parser.parse_args()

    print("=" * 78)
    print("  UJI PEMASANG SATU BERKAS (bodap)")
    print(f"  Repo: {AKAR}")
    print("=" * 78)
    uji_berkas_pembangunan()
    uji_ikon()
    info_payload = uji_payload()
    uji_periksa_dan_hapus()
    info_wheels: dict = {}
    info_jatuh: dict = {}
    if not args.cepat:
        info_wheels = uji_pustaka_bawaan_cocok()
        info_jatuh = uji_pustaka_bawaan_tidak_cocok()
    info_uji = uji_bodap_uji(args.cepat)

    berhasil = sum(1 for _, ok, _ in HASIL if ok)
    print("-" * 78)
    for nama, ok, keterangan in HASIL:
        if not ok:
            print(f"  GAGAL: {nama} — {keterangan}")
    print(f"  {berhasil}/{len(HASIL)} pemeriksaan berhasil"
          + (f" · payload {info_payload.get('berkas', '?')} berkas"
             f" · uji internal {info_uji.get('pemeriksaan', '?')} pemeriksaan"
             if info_payload and info_uji else "")
          + (f" · wheels {info_wheels.get('wheels', '?')} berkas"
             if info_wheels else "")
          + (" · tahan berkas bawaan tidak cocok" if info_jatuh else ""))
    print("=" * 78)
    return 0 if berhasil == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
