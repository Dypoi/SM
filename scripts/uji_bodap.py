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
        return {"pemeriksaan": len(diperiksa), "gagal": len(gagal)}


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
                        help="lewati pemasangan pustaka (pakai Python yang menjalankan uji)")
    args = parser.parse_args()

    print("=" * 78)
    print("  UJI PEMASANG SATU BERKAS (bodap)")
    print(f"  Repo: {AKAR}")
    print("=" * 78)
    uji_berkas_pembangunan()
    uji_ikon()
    info_payload = uji_payload()
    uji_periksa_dan_hapus()
    info_uji = uji_bodap_uji(args.cepat)

    berhasil = sum(1 for _, ok, _ in HASIL if ok)
    print("-" * 78)
    for nama, ok, keterangan in HASIL:
        if not ok:
            print(f"  GAGAL: {nama} — {keterangan}")
    print(f"  {berhasil}/{len(HASIL)} pemeriksaan berhasil"
          + (f" · payload {info_payload.get('berkas', '?')} berkas"
             f" · uji internal {info_uji.get('pemeriksaan', '?')} pemeriksaan"
             if info_payload and info_uji else ""))
    print("=" * 78)
    return 0 if berhasil == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
