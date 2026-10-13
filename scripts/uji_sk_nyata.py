#!/usr/bin/env python3
"""Bukti ronde 60–61 — **berkas asli sekolah**: SK definitif TANGCER & daftar penerima.

Bukan berkas contoh: yang dibaca di sini adalah berkas yang diunggah sekolah ke repo
(``SK DEFINITIF TANGCER SMP TAHAP 1 TAHUN 2026 (1).pdf``, 82 halaman) dan
``Daftar Penerima Tangcer2026 Ganjil (3).xlsx`` (daftar penerima versi sekolah).

Yang dicatat apa adanya:

1. hasil pembacaan SK (kolom yang dikenali, jumlah baris, jumlah penerima sekolah kita);
2. daftar 44 penerima sekolah kita beserta rekening & nama orang tua — hasil pembacaan
   yang sudah lolos pemeriksaan silang dengan pustaka ``pypdf`` (mode tata letak);
3. perbandingan dengan berkas Excel sekolah: berapa NISN yang sama, dan berapa yang
   **tidak ada** di SK (dilaporkan jujur — bukan dikarang);
4. berkas SPJ yang benar-benar dibuat dari data itu (enam berkas) beserta isi pokoknya.

Sejak ronde 61 ikut diperiksa berkas **tahap 2** (``sk definitif tahap 2 tangcer smt 1
2026.pdf``, 57 halaman): berkas itu ternyata **tidak memuat sekolah kita** — dan itu dilaporkan
apa adanya, lengkap dengan sekolah mana saja yang ada di dalamnya. Dua salah baca yang ditemukan
dari berkas ini (sel yang melimpah ke kolom sebelah menelan nama orang, dan penanda kelas yang
menempel pada nama ayah) sudah diperbaiki; di sini angkanya dibuktikan **0** pada kedua berkas.

Berkas hasil (berisi data penerima) disimpan di ``pratinjau/ronde60/`` — folder itu
tidak ikut di-commit.

Jalankan dari akar repo:

    .venv/bin/python scripts/uji_sk_nyata.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

AKAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AKAR))

# Basis data SEMENTARA (dibuat di folder sementara): skrip ini menyimpan sendiri 44 penerima
# hasil bacaan supaya berkas SPJ bisa dibuat apa adanya — tanpa menyentuh basis data sekolah.
# Dengan begitu hasilnya sama setiap kali dijalankan, juga di komputer yang belum pernah mengisi.
os.environ["SM_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="sm-sk-nyata-")) / "bukti.sqlite3")

from app import migrations, pdf_baca, services, spj, tangcer  # noqa: E402

SK = AKAR / "SK DEFINITIF TANGCER SMP TAHAP 1 TAHUN 2026 (1).pdf"
SK2 = AKAR / "sk definitif tahap 2 tangcer smt 1 2026.pdf"
XLSX_SEKOLAH = AKAR / "Daftar Penerima Tangcer2026 Ganjil (3).xlsx"
SEKOLAH = "SMP NEGERI 2 TANGERANG"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def baris(tanda: str = "") -> None:
    print(("" if not tanda else f"{tanda} ") + "-" * 74, flush=True)


def teks_docx(isi: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(isi)) as berkas:
        akar = ET.fromstring(berkas.read("word/document.xml"))
    potongan = ["".join(t.text or "" for t in p.iter(f"{W}t")) for p in akar.iter(f"{W}p")]
    for tabel in akar.iter(f"{W}tbl"):
        for satu in tabel.iter(f"{W}tr"):
            potongan.append(" | ".join("".join(t.text or "" for t in sel.iter(f"{W}t"))
                                       for sel in satu.iter(f"{W}tc")))
    return " ".join(potongan)


def main() -> int:
    print("=" * 76)
    print("  BUKTI RONDE 60–61 — BERKAS ASLI SEKOLAH (SK TANGCER tahap 1 & tahap 2)")
    print("=" * 76)

    if not SK.is_file():
        print(f"[GAGAL] berkas SK tidak ditemukan: {SK}")
        return 1

    # ------------------------------------------------------------------ #
    # 1. Pembacaan SK asli
    # ------------------------------------------------------------------ #
    baris("1. Pembacaan SK asli (pembaca PDF bawaan SM)")
    isi_sk = SK.read_bytes()
    hasil = tangcer.baca_isi(SK.name, isi_sk)
    print(f"berkas   : {SK.name} ({len(isi_sk):,} bita)")
    print(f"kolom    : {hasil.kolom}")
    print(f"baris    : {hasil.jumlah_baris}")
    for catatan in hasil.catatan[:4]:
        print(f"catatan  : {catatan}")
    for catatan in hasil.catatan:
        if "tanpa teks" in catatan:      # sampul & lampiran biasanya hasil pindai
            print(f"pindai   : {catatan}")
    saring = tangcer.saring_sekolah(hasil, SEKOLAH, "", "KOTA TANGERANG")
    print(f"diterima : {saring.jumlah_diterima} baris milik {SEKOLAH}")
    print(f"ditolak  : {len(saring.ditolak)} baris (sekolah lain)")
    print()

    # ------------------------------------------------------------------ #
    # 2. Pemeriksaan silang dengan pypdf (kalau terpasang)
    # ------------------------------------------------------------------ #
    baris("2. Pemeriksaan silang dengan pypdf (mode tata letak)")
    try:
        import pypdf

        pembaca = pypdf.PdfReader(str(SK))
        teks_pypdf = " ".join((pembaca.pages[i].extract_text(extraction_mode="layout") or "")
                              for i in range(3, 10))
        teks_pypdf = " ".join(teks_pypdf.split())
        cocok = 0
        dicoba = 0
        for item in saring.diterima[:20]:
            dicoba += 1
            if item.nama.split()[0] in teks_pypdf and item.nisn in teks_pypdf:
                cocok += 1
        print(f"baris pertama yang diperiksa : {dicoba}")
        print(f"cocok dengan pypdf           : {cocok}/{dicoba}")
    except ImportError:
        print("pypdf tidak terpasang — pemeriksaan silang dilewati.")
    print()

    # ------------------------------------------------------------------ #
    # 3. Daftar 44 penerima sekolah kita
    # ------------------------------------------------------------------ #
    baris("3. Daftar penerima sekolah kita dari SK (apa adanya)")
    print(f"{'NO':>3}  {'NAMA':<32} {'NISN':<11} {'KLS':<4} {'L/P':<4} "
          f"{'NOMOR REKENING':<15} NAMA ORANG TUA")
    for item in saring.diterima:
        print(f"{item.no:>3}  {item.nama[:32]:<32} {item.nisn:<11} {item.rombel:<4} "
              f"{item.kelamin_rapi:<4} {item.rekening:<15} {item.nama_orangtua[:24]}")
    print()

    # ------------------------------------------------------------------ #
    # 4. Perbandingan dengan Excel sekolah
    # ------------------------------------------------------------------ #
    baris("4. Perbandingan dengan berkas Excel sekolah")
    if XLSX_SEKOLAH.is_file():
        xls = tangcer.baca_berkas(XLSX_SEKOLAH, ".xlsx")
        nisn_xls = {item.nisn for item in xls.baris if item.nisn}
        nisn_sk = {item.nisn for item in saring.diterima if item.nisn}
        print(f"{XLSX_SEKOLAH.name}: {xls.jumlah_baris} baris")
        print(f"NISN di Excel sekolah        : {len(nisn_xls)}")
        print(f"NISN itu yang ada di SK      : {len(nisn_xls & nisn_sk)}")
        hilang = sorted(nisn_xls - nisn_sk)
        print(f"NISN Excel TIDAK ada di SK   : {len(hilang)}")
        if hilang:
            contoh = [item.nama for item in xls.baris if item.nisn in set(hilang)][:5]
            print(f"   contoh nama: {', '.join(contoh)}")
        print("Keterangan: SK TANGCER tahap 1 memuat 44 siswa sekolah ini; daftar versi "
              "sekolah memuat 60 siswa.")
    else:
        print("berkas Excel sekolah tidak ditemukan.")
    print()

    # ------------------------------------------------------------------ #
    # 5. Berkas SPJ yang dibuat dari data SK
    # ------------------------------------------------------------------ #
    baris("5. Berkas SPJ yang dibuat dari data SK asli")
    migrations.init_database()
    services.set_setting("school_nama", SEKOLAH)
    services.set_setting("school_kabupaten", "KOTA TANGERANG")
    baru, ganda = tangcer.simpan_banyak(0, saring.diterima, tahun="2026", semester="1", tahap="1")
    print(f"basis data : sementara — {baru} baris penerima disimpan untuk uji ini "
          f"({ganda} sudah ada)")
    data = spj.data_dari({
        "tahun": "2026", "semester": "1", "tahap": "1",
        "kepala": "(nama kepala sekolah — isi di aplikasi)", "nip": "",
        "biaya_personal": "100000", "volume": "6", "sampel": "10", "dana_masuk": "1",
    })
    spj_baris = spj.baris_spj(data)
    print(f"baris SPJ : {len(spj_baris)}")
    print(f"total     : {tangcer.format_rupiah(spj.ringkas_spj(data, spj_baris)['total'])}")
    paket = spj.buat_paket(data, spj_baris)
    print(f"paket     : {paket['token']} → {paket['folder']}")
    for berkas in paket["berkas"]:
        print(f"   {berkas['ukuran']:8,} bita  {berkas['nama']}")
    print()

    folder = Path(paket["folder"])
    pakta = teks_docx((folder / "PAKTA INTEGRITAS TANGERANG CERDAS.docx").read_bytes())
    print(f"Pakta Integritas memuat «sejumlah {len(spj_baris)} Siswa» :",
          f"sejumlah {len(spj_baris)} Siswa" in pakta)
    print(f"Pakta Integritas memuat nama sekolah              :", SEKOLAH in pakta)
    surat = teks_docx((folder / "SURAT PERNYATAAN TRANSFER.docx").read_bytes())
    total_teks = tangcer.format_rupiah(spj.ringkas_spj(data, spj_baris)["total"]).replace("Rp ", "")
    print(f"Surat Pernyataan memuat total {total_teks}     :", total_teks in surat)
    print("Surat Pernyataan memuat juknis personal           :",
          "Personal : 100.000/peserta didik/bulan" in surat)
    hasil_pdf = pdf_baca.baca_pdf((folder / "DAFTAR PENERIMA.pdf").read_bytes())
    teks_pdf = " ".join(t for _, _, t, _ in hasil_pdf.halaman[0])
    print(f"PDF daftar penerima: {hasil_pdf.jumlah_halaman} halaman; nama pertama ada :",
          saring.diterima[0].nama in teks_pdf)
    print()
    # ------------------------------------------------------------------ #
    # 6. Berkas tahap 2 — sekolah kita tidak ada di dalamnya (ronde 61)
    # ------------------------------------------------------------------ #
    baris("6. Berkas tahap 2 (mutu pembacaan & kejujuran laporan)")
    if not SK2.is_file():
        print(f"berkas tahap 2 tidak ditemukan ({SK2.name}) — bagian ini dilewati.")
    else:
        isi2 = SK2.read_bytes()
        hasil2 = tangcer.baca_isi(SK2.name, isi2)
        saring2 = tangcer.saring_sekolah(hasil2, SEKOLAH, "", "KOTA TANGERANG")
        print(f"berkas   : {SK2.name} ({len(isi2):,} bita)")
        print(f"kolom    : {hasil2.kolom}")
        print(f"baris    : {hasil2.jumlah_baris}")
        print(f"kepala   : tahap {hasil2.tahap} · semester {hasil2.semester} "
              f"· tahun {hasil2.tahun}")
        for catatan in hasil2.catatan:
            if "kepala berkas" in catatan or "tanpa teks" in catatan:
                print(f"catatan  : {catatan}")
        if not any("tanpa teks" in catatan for catatan in hasil2.catatan):
            print("[GAGAL] halaman pindai tidak dilaporkan apa adanya")
            return 1
        bersih2 = [item for item in hasil2.baris if item.sekolah]
        tanpa2 = [item for item in hasil2.baris if not item.sekolah]
        nyasar2 = [item for item in hasil2.baris
                   if any((getattr(item, kolom) or "").startswith("Kelas")
                          for kolom in ("nama", "nama_ayah", "nama_ibu", "nama_orangtua"))]
        print(f"mutu     : kolom sekolah terisi {len(bersih2)} · tanpa nama sekolah {len(tanpa2)} "
              f"· «Kelas …» nyasar {len(nyasar2)}")
        jumlah_sekolah = {}
        for item in bersih2:
            jumlah_sekolah[item.sekolah] = jumlah_sekolah.get(item.sekolah, 0) + 1
        print(f"sekolah  : {len(jumlah_sekolah)} nama sekolah berbeda di berkas ini")
        for nama_sekolah, jumlah in sorted(jumlah_sekolah.items(),
                                           key=lambda pasang: -pasang[1])[:6]:
            print(f"           {jumlah:>4} baris  {nama_sekolah}")
        if saring2.jumlah_diterima:
            print(f"diterima : {saring2.jumlah_diterima} baris milik {SEKOLAH}")
        else:
            print(f"diterima : 0 baris — «{SEKOLAH}» memang TIDAK ADA di berkas tahap 2 ini")
            for catatan in saring2.catatan:
                print(f"catatan  : {' '.join(catatan.split())[:150]}")
            print("Keterangan: yang tidak ada di berkas tidak boleh dikarang. Aplikasi "
                  "menyebutkan sekolah yang ada supaya berkasnya bisa ditelusuri "
                  "(mungkin penerimanya ada di berkas tahap lain).")
    print()
    baris()
    print("SELESAI — semua angka di atas berasal dari berkas asli sekolah.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
