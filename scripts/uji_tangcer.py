#!/usr/bin/env python3
"""Uji menyeluruh menu **TANGCER** — impor berkas mentah (Excel/CSV/PDF) + penyaringan sekolah.

Berkas mentah dari dinas tidak selalu rapi: ada yang berbentuk Excel/CSV, ada yang
berupa **SK definitif berbentuk PDF**, dan hampir semuanya memuat banyak sekolah
sekaligus. Uji ini membuat berkas contoh **sungguhan** (CSV, XLSX, dan dua tata letak
PDF) lalu membuktikan bahwa:

1. pencocokan nama sekolah tidak salah orang — «SMPN 2 TANGERANG» ≡ «SMP NEGERI 2
   TANGERANG», «SMP NEGERI 02» ≡ «SMP NEGERI 2», sedangkan sekolah lain (SMP 1,
   SMP Swasta, Kabupaten vs Kota) **ditolak** beserta alasannya;
2. pembaca Excel/CSV menemukan baris judul meski ada kop/leher berkas, melewati
   baris rekap, dan membaca NISN/NIK/nominal apa adanya;
3. pembaca PDF menangani dua tata letak: tabel (ada baris judul kolom) dan
   **judul bagian** (nama sekolah berdiri sendiri, baris siswanya di bawahnya);
4. penyaringan hanya meloloskan baris sekolah kita, sisanya dihitung & dilaporkan;
5. penyimpanan ke basis data tidak menggandakan baris (sidik) dan bisa diekspor
   (CSV/XLSX/PDF) serta dihapus lagi.

Jalankan:

    .venv/bin/python scripts/uji_tangcer.py
    .venv/bin/python scripts/uji_tangcer.py --berkas-ke pratinjau/ronde58/berkas
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AKAR))

os.environ.setdefault("SM_DB", str(AKAR / "data" / "sm.sqlite3"))

from app import db, tangcer  # noqa: E402

SEKOLAH_KITA = "SMP NEGERI 2 TANGERANG"
NPSN_KITA = "20631000"
DAERAH_KITA = "Kota Tangerang"

HASIL: list[tuple[str, bool, str]] = []
SKENARIO: list[str] = []
_SKENARIO_KINI = ""


def skenario(nama: str) -> None:
    global _SKENARIO_KINI
    _SKENARIO_KINI = nama
    SKENARIO.append(nama)
    print(f"\n=== {nama} ===", flush=True)


def cek(nama: str, syarat: bool, keterangan: str = "") -> None:
    HASIL.append((f"{_SKENARIO_KINI} → {nama}", bool(syarat), keterangan))
    tanda = "  OK  " if syarat else " GAGAL"
    print(f"[{tanda}] {nama}" + ("" if syarat or not keterangan else f" — {keterangan}"),
          flush=True)


# --------------------------------------------------------------------------- #
# Pembuat berkas contoh
# --------------------------------------------------------------------------- #
#: Baris data mentah yang dipakai di semua berkas contoh: (nisn, nama, sekolah, rombel,
#: jenis, nominal, tahap). Sengaja memuat sekolah lain + penulisan sekolah kita yang
#: berbeda-beda supaya penyaringan benar-benar diuji.
BARIS_CONTOH: list[tuple[str, str, str, str, str, str, str]] = [
    ("0091234501", "Achmad Fauzi Ramadhan", "SMP NEGERI 2 TANGERANG", "7A", "TANGCER", "1.000.000", "Tahap 1"),
    ("0091234502", "Bella Safitri", "SMPN 2 TANGERANG", "7B", "TANGCER", "1.000.000", "Tahap 1"),
    ("0091234503", "Candra Wijaya Kusuma", "SMP NEGERI 2 KOTA TANGERANG", "8A", "TANGCER", "Rp 1.000.000", "Tahap 1"),
    ("0091234504", "Dewi Anggraeni", "SMP NEGERI 02 TANGERANG", "9C", "TANGCER", "1000000", "Tahap 1"),
    ("0091234505", "Eko Prasetyo", "SMP NEGERI 1 TANGERANG", "7A", "TANGCER", "1.000.000", "Tahap 1"),
    ("0091234506", "Fitriani Lestari", "SMP NEGERI 1 TANGERANG", "8B", "TANGCER", "1.000.000", "Tahap 1"),
    ("0091234507", "Gilang Ramadhan", "SMP SWASTA ISLAM AL HIDAYAH", "7C", "TANGCER", "1.000.000", "Tahap 1"),
    ("0091234508", "Hana Salsabila", "SMP NEGERI 2 KABUPATEN TANGERANG", "8C", "TANGCER", "1.000.000", "Tahap 1"),
    ("0091234509", "Indra Gunawan", "SMP NEGERI 5 TANGERANG", "9A", "TANGCER", "500.000", "Tahap 1"),
]

JUDUL = ["NO", "NISN", "NAMA PESERTA DIDIK", "NAMA SEKOLAH", "ROMBEL", "JENIS BANTUAN",
         "NOMINAL", "TAHAP"]


def _sel(nomor: int, baris: tuple[str, ...]) -> list[str]:
    return [str(nomor), baris[0], baris[1], baris[2], baris[3], baris[4], baris[5], baris[6]]


def buat_csv(tujuan: Path, *, pemisah: str = ";", dengan_sekolah: bool = True,
             kop: bool = True) -> Path:
    """CSV mentah seperti unduhan dari dinas (kop + baris rekap di bawah)."""
    baris: list[list[str]] = []
    if kop:
        baris.append(["DAFTAR PENERIMA BANTUAN TANGCER TAHUN 2026", "", "", "", "", "", "", ""])
        baris.append(["DINAS PENDIDIKAN KOTA TANGERANG", "", "", "", "", "", "", ""])
        baris.append([""] * 8)
    judul = JUDUL if dengan_sekolah else [kolom for kolom in JUDUL if kolom != "NAMA SEKOLAH"]
    baris.append(judul)
    for nomor, item in enumerate(BARIS_CONTOH, start=1):
        lengkap = _sel(nomor, item)
        if not dengan_sekolah:
            # Kolom «NAMA SEKOLAH» dibuang: NO · NISN · NAMA · ROMBEL · JENIS · NOMINAL · TAHAP
            lengkap = [lengkap[0], lengkap[1], lengkap[2], lengkap[4],
                       lengkap[5], lengkap[6], lengkap[7]]
        baris.append(lengkap)
    baris.append(["", "", "JUMLAH", "", "", "", "8.500.000", ""])
    teks = "\r\n".join(pemisah.join(sel) for sel in baris) + "\r\n"
    tujuan.write_text(teks, encoding="utf-8")
    return tujuan


def buat_xlsx(tujuan: Path) -> Path:
    import openpyxl

    buku = openpyxl.Workbook()
    lembar = buku.active
    lembar.title = "Penerima"
    lembar["A1"] = "DAFTAR PENERIMA TANGCER 2026 GANJIL"
    lembar["A3"] = "NO"
    for kolom, judul in enumerate(JUDUL):
        sel = lembar.cell(row=4, column=kolom + 1, value=judul)
        sel.font = openpyxl.styles.Font(bold=True)
    for nomor, item in enumerate(BARIS_CONTOH, start=5):
        for kolom, nilai in enumerate(_sel(nomor - 4, item), start=1):
            lembar.cell(row=nomor, column=kolom, value=nilai)
    lembar["C15"] = "JUMLAH"
    lembar["G15"] = 8500000
    buku.save(tujuan)
    return tujuan


def _pdf_teks(baris: list[str]) -> bytes:
    """PDF 1.4 sederhana berisi baris-baris teks (tata letak «judul bagian»)."""
    from app.pdf import _rakit_pdf

    isi = _isi_teks_pdf(baris)
    return _rakit_pdf([isi])


def _isi_teks_pdf(baris: list[str]) -> bytes:
    isi = ["BT", "/F1 9 Tf", "1 0 0 1 40 800 Tm"]
    for urut, teks in enumerate(baris):
        if urut:
            isi.append("0 -12 Td")
        aman = teks.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        isi.append(f"({aman}) Tj")
    isi.append("ET")
    return "\n".join(isi).encode("latin-1", "replace") + b"\n"


def buat_pdf_bagian(tujuan: Path) -> Path:
    """PDF tanpa baris judul kolom: nama sekolah jadi judul, siswanya di bawahnya."""
    baris = [
        "KEPUTUSAN KEPALA DINAS PENDIDIKAN KOTA TANGERANG",
        "NOMOR: 421.3/1234-DISDIK/2026",
        "TENTANG PENETAPAN PENERIMA BANTUAN TANGCER TAHAP 1 TAHUN 2026",
        "",
        "SMP NEGERI 2 TANGERANG",
        "1  0091234501  Achmad Fauzi Ramadhan      7A",
        "2  0091234502  Bella Safitri              7B",
        "3  0091234503  Candra Wijaya Kusuma      8A",
        "",
        "SMP NEGERI 1 TANGERANG",
        "1  0091234505  Eko Prasetyo              7A",
        "2  0091234506  Fitriani Lestari          8B",
        "",
        "SMP SWASTA ISLAM AL HIDAYAH",
        "1  0091234507  Gilang Ramadhan           7C",
    ]
    tujuan.write_bytes(_pdf_teks(baris))
    return tujuan


def buat_pdf_tabel(tujuan: Path) -> Path:
    """PDF berbentuk tabel dengan kolom sekolah (seperti lampiran SK yang dirapikan)."""
    from app.pdf import buat_pdf_tabel

    kolom = [("No", 26), ("NISN", 70), ("Nama Peserta Didik", 150),
             ("Sekolah", 170), ("Rombel", 40), ("Nominal", 60)]
    isi = [[str(nomor), item[0], item[1], item[2], item[3], item[5]]
           for nomor, item in enumerate(BARIS_CONTOH, start=1)]
    # Satu baris yang HANYA ada di PDF ini — dipakai uji untuk memastikan impor PDF
    # benar-benar menyimpan datanya sendiri (tidak tersamar oleh impor lain).
    isi.append(["10", "0091234599", "Zulfa Aulia Nabilah", SEKOLAH_KITA, "8B", "1.000.000"])
    tujuan.write_bytes(buat_pdf_tabel(
        "SK DEFINITIF TANGCER TAHAP 1 TAHUN 2026",
        kolom,
        isi,
        subjudul=["DINAS PENDIDIKAN KOTA TANGERANG", "Tahun 2026 · Semester Ganjil"],
        catatan_kaki=["Lampiran SK definitif (contoh uji)"],
    ))
    return tujuan


def buat_pdf_pindai(tujuan: Path) -> Path:
    """PDF tanpa teks (meniru hasil pindai) — harus dilaporkan jujur, bukan dikarang."""
    from app.pdf import _rakit_pdf

    tujuan.write_bytes(_rakit_pdf([b"q 1 0 0 1 0 0 cm Q\n"]))  # halaman kosong tanpa teks
    return tujuan


# --------------------------------------------------------------------------- #
# Skenario
# --------------------------------------------------------------------------- #
def uji_pencocokan() -> None:
    skenario("1. Pencocokan nama sekolah (jangan salah orang)")
    sama = [
        ("SMP NEGERI 2 TANGERANG", True),
        ("SMPN 2 TANGERANG", True),
        ("smp negeri 2 tangerang", True),
        ("SMP Negeri 2 Kota Tangerang", True),
        ("SMP NEGERI 02 TANGERANG", True),
        ("SMP NEGERI 2 TANGERANG (NPSN 20631000)", True),
    ]
    for teks, harusnya in sama:
        cocok, alasan = tangcer.cocok_sekolah(teks, SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
        cek(f"«{teks}» dianggap sekolah kita", cocok is harusnya, f"alasan: {alasan}")
    beda = [
        "SMP NEGERI 1 TANGERANG",
        "SMP SWASTA ISLAM AL HIDAYAH",
        "SMP NEGERI 2 KABUPATEN TANGERANG",
        "SMP NEGERI 2 TANGERANG SELATAN",
        "SMP NEGERI 5 TANGERANG",
        "SMA NEGERI 2 TANGERANG",
        "SD NEGERI 2 TANGERANG",
    ]
    for teks in beda:
        cocok, alasan = tangcer.cocok_sekolah(teks, SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
        cek(f"«{teks}» TIDAK dianggap sekolah kita", cocok is False, f"alasan: {alasan}")
    cocok, alasan = tangcer.cocok_sekolah("SMP NEGERI 1 TANGERANG (NPSN 20631000)",
                                          SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
    cek("NPSN yang sama menang atas perbedaan tulisan nama", cocok, f"alasan: {alasan}")
    cek("NPSN 8 angka dibaca dari teks bebas",
        tangcer.npsn_dari_teks("SMPN 2 TANGERANG 20631000 BANTEN") == "20631000")
    cek("NPSN tidak dikarang bila tidak ada", tangcer.npsn_dari_teks("SMPN 2 TANGERANG") == "")


def uji_sel() -> None:
    skenario("2. Pembacaan sel: NISN/NIK/nominal apa adanya")
    cek("NISN «0091234501» utuh", tangcer.bersih_nomor("0091234501") == "0091234501")
    cek("NISN dari Excel «91234501.0» → «91234501»", tangcer.bersih_nomor("91234501.0") == "91234501")
    cek("NISN dari angka 91234501", tangcer.bersih_nomor(91234501) == "91234501")
    cek("NISN bernotasi spasi dibersihkan", tangcer.bersih_nomor(" 0091 234 501 ") == "0091234501")
    for teks, harap in [("1.000.000", 1_000_000), ("Rp 1.000.000", 1_000_000),
                        ("1000000", 1_000_000), ("1,000,000", 1_000_000),
                        ("500.000,00", 500_000), (1000000, 1_000_000), ("1juta", None),
                        ("", None)]:
        hasil = tangcer.bersih_nominal(teks)
        cek(f"nominal «{teks}» → {harap}", hasil == (float(harap) if harap is not None else None),
            f"dapat {hasil}")
    cek("teks dibersihkan dari spasi ganda",
        tangcer.bersih_teks("  Achmad   Fauzi  ") == "Achmad Fauzi")
    cek("nama sekolah dinormalkan (titik & kapital)",
        tangcer.kunci_sekolah("S.M.P. Negeri 2 Tangerang") == tangcer.kunci_sekolah(SEKOLAH_KITA))


def uji_csv() -> tangcer.HasilBaca:
    skenario("3. Berkas CSV mentah (kop berkas + baris rekap)")
    with tempfile.TemporaryDirectory(prefix="tangcer-csv-") as tmp:
        berkas = buat_csv(Path(tmp) / "daftar.csv", pemisah=";")
        hasil = tangcer.baca_berkas(berkas, ".csv")
    cek("9 baris penerima terbaca (baris rekap tidak dianggap data)",
        hasil.jumlah_baris == 9, f"terbaca {hasil.jumlah_baris}")
    cek("kolom dikenali: nama, nisn, sekolah, rombel, jenis, nominal",
        {"nama", "nisn", "sekolah", "rombel", "jenis", "nominal"} <= set(hasil.kolom.values()),
        f"kolom: {sorted(hasil.kolom.values())}")
    cek("baris judul ditemukan di baris ke-4 (ada kop di atasnya)", hasil.header_ke == 4,
        f"header_ke={hasil.header_ke}")
    cek("baris rekap «JUMLAH» dilewati & dilaporkan",
        any("rekap" in catatan for catatan in hasil.catatan),
        f"catatan: {hasil.catatan[:3]}")
    baris_pertama = hasil.baris[0]
    cek("baris pertama: nama & NISN benar",
        baris_pertama.nama == "Achmad Fauzi Ramadhan" and baris_pertama.nisn == "0091234501",
        f"{baris_pertama.nama} / {baris_pertama.nisn}")
    cek("nominal «Rp 1.000.000» terbaca 1000000",
        any(item.nominal == 1_000_000 for item in hasil.baris))
    return hasil


def uji_csv_koma() -> None:
    skenario("4. CSV dengan pemisah koma & kutip")
    with tempfile.TemporaryDirectory(prefix="tangcer-csv2-") as tmp:
        berkas = Path(tmp) / "daftar-koma.csv"
        teks = ('NO,NISN,NAMA PESERTA DIDIK,NAMA SEKOLAH,ROMBEL\n'
                '1,0091234501,"Fauzi, Achmad",SMP NEGERI 2 TANGERANG,7A\n'
                '2,0091234505,Eko Prasetyo,SMP NEGERI 1 TANGERANG,7A\n')
        berkas.write_text(teks, encoding="utf-8")
        hasil = tangcer.baca_berkas(berkas, ".csv")
    cek("nama berkutip dibaca utuh", hasil.baris[0].nama == "Fauzi, Achmad",
        f"dapat «{hasil.baris[0].nama}»")
    cek("hanya 2 baris terbaca", hasil.jumlah_baris == 2, f"terbaca {hasil.jumlah_baris}")


def uji_xlsx() -> None:
    skenario("5. Berkas Excel (.xlsx)")
    with tempfile.TemporaryDirectory(prefix="tangcer-xlsx-") as tmp:
        berkas = buat_xlsx(Path(tmp) / "daftar.xlsx")
        hasil = tangcer.baca_berkas(berkas, ".xlsx")
    cek("9 baris penerima terbaca dari Excel", hasil.jumlah_baris == 9,
        f"terbaca {hasil.jumlah_baris}")
    cek("judul kolom ditemukan walau ada baris judul lembar di atasnya",
        {"nama", "nisn", "sekolah"} <= set(hasil.kolom.values()),
        f"kolom: {sorted(hasil.kolom.values())}")
    cek("nomor di sel Excel jadi teks nama (bukan 91234501.0)",
        hasil.baris[0].nisn == "0091234501", f"dapat {hasil.baris[0].nisn}")


def uji_pdf_tabel() -> None:
    skenario("6. PDF berbentuk tabel (ada baris judul kolom)")
    with tempfile.TemporaryDirectory(prefix="tangcer-pdf1-") as tmp:
        berkas = buat_pdf_tabel(Path(tmp) / "sk-tabel.pdf")
        hasil = tangcer.baca_berkas(berkas, ".pdf")
    cek("ada baris penerima terbaca dari PDF", hasil.jumlah_baris >= 5,
        f"terbaca {hasil.jumlah_baris}")
    cek("kolom nama & sekolah dikenali",
        {"nama", "sekolah"} <= set(hasil.kolom.values()),
        f"kolom: {sorted(hasil.kolom.values())}")
    cek("nama siswa terbaca apa adanya",
        any("Achmad Fauzi" in item.nama for item in hasil.baris),
        f"contoh: {[item.nama for item in hasil.baris[:3]]}")
    cek("sekolah ikut terbaca dari PDF",
        any(item.sekolah for item in hasil.baris),
        f"contoh: {[item.sekolah for item in hasil.baris[:3]]}")


def uji_pdf_bagian() -> None:
    skenario("7. PDF tanpa judul kolom (nama sekolah jadi judul bagian)")
    with tempfile.TemporaryDirectory(prefix="tangcer-pdf2-") as tmp:
        berkas = buat_pdf_bagian(Path(tmp) / "sk-bagian.pdf")
        hasil = tangcer.baca_berkas(berkas, ".pdf")
    cek("6 baris siswa terbaca", hasil.jumlah_baris == 6, f"terbaca {hasil.jumlah_baris}")
    cek("3 nama sekolah dikenali sebagai judul bagian",
        len(hasil.sekolah_tanpa_kolom) == 3,
        f"ditemukan: {hasil.sekolah_tanpa_kolom}")
    cek("NISN 10 angka terbaca walau kolomnya tidak berjudul",
        any(item.nisn == "0091234501" for item in hasil.baris),
        f"NISN: {[item.nisn for item in hasil.baris]}")
    cek("nama siswa terbaca",
        any(item.nama == "Achmad Fauzi Ramadhan" for item in hasil.baris),
        f"nama: {[item.nama for item in hasil.baris]}")
    saring = tangcer.saring_sekolah(hasil, SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
    cek("baris di bawah judul «SMP NEGERI 2 TANGERANG» ikut sekolah kita",
        saring.jumlah_diterima == 3, f"diterima {saring.jumlah_diterima}")
    cek("baris SMP 1 dan SMP Swasta ditolak",
        len(saring.ditolak) == 3, f"ditolak {len(saring.ditolak)}")
    cek("sekolah lain dilaporkan beserta jumlah barisnya",
        len(saring.sekolah_lain) == 2, f"sekolah lain: {dict(saring.sekolah_lain)}")


def uji_penyaringan(hasil: tangcer.HasilBaca) -> None:
    skenario("8. Penyaringan: hanya sekolah kita yang masuk")
    saring = tangcer.saring_sekolah(hasil, SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
    cek("4 baris sekolah kita yang diambil (termasuk «SMPN» & «KOTA»)",
        saring.jumlah_diterima == 4, f"diterima {saring.jumlah_diterima}: "
        f"{[item.sekolah for item in saring.diterima]}")
    cek("5 baris sekolah lain diabaikan", len(saring.ditolak) == 5,
        f"ditolak {len(saring.ditolak)}")
    cek("jumlah tiap sekolah lain dihitung",
        saring.sekolah_lain.get("SMP NEGERI 1 TANGERANG") == 2,
        f"rekap: {dict(saring.sekolah_lain)}")
    cek("alasan diterima/ditolak selalu ada",
        all(item.alasan for item in saring.diterima + saring.ditolak))
    cek("catatan penyaringan menyebut jumlah yang diabaikan",
        any("tidak disimpan" in catatan for catatan in saring.catatan),
        f"catatan: {saring.catatan}")
    # sekolah kita tertulis tanpa kata «KOTA» → tetap kebaca
    cocok, alasan = tangcer.cocok_sekolah("SMPN 2 KOTA TANGERANG", SEKOLAH_KITA, "",
                                         DAERAH_KITA)
    cek("«SMPN 2 KOTA TANGERANG» ≡ «SMP NEGERI 2 TANGERANG»", cocok, alasan)
    cocok, alasan = tangcer.cocok_sekolah("SMP Negeri 2", SEKOLAH_KITA, "", DAERAH_KITA)
    cek("«SMP Negeri 2» (tanpa kata wilayah) diambil TAPI ditandai perlu diperiksa",
        cocok and "kata wilayah dibuang" in alasan, alasan)
    cocok, alasan = tangcer.cocok_sekolah("SMP NEGERI 2 TANGE", SEKOLAH_KITA, "", DAERAH_KITA)
    cek("nama sekolah terpotong («…TANGE») TIDAK dianggap sekolah kita", cocok is False, alasan)
    saring2 = tangcer.saring_sekolah(
        tangcer.baca_baris_tabel([["NO", "NISN", "NAMA PESERTA DIDIK", "NAMA SEKOLAH"],
                                  ["1", "0091234599", "Zulfa Aulia", "SMP Negeri 2"]]),
        SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
    cek("baris hasil pencocokan longgar tercatat di daftar «perlu diperiksa»",
        len(saring2.diragukan) == 1 and any("mohon diperiksa" in catatan
                                            for catatan in saring2.catatan),
        f"diragukan={len(saring2.diragukan)} catatan={saring2.catatan}")
    return saring


def uji_tanpa_kolom_sekolah() -> None:
    skenario("9. Berkas tanpa kolom sekolah (SK sudah terpisah per sekolah)")
    with tempfile.TemporaryDirectory(prefix="tangcer-noschool-") as tmp:
        berkas = buat_csv(Path(tmp) / "per-sekolah.csv", dengan_sekolah=False)
        hasil = tangcer.baca_berkas(berkas, ".csv")
    cek("tanpa kolom sekolah, semua baris terbaca", hasil.jumlah_baris == 9,
        f"terbaca {hasil.jumlah_baris}")
    saring = tangcer.saring_sekolah(hasil, SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
    cek("tanpa centang «khusus sekolah kita» → tidak ada yang diambil",
        saring.jumlah_diterima == 0, f"diterima {saring.jumlah_diterima}")
    cek("catatan memberi tahu cara mengatasinya",
        any("khusus sekolah kita" in catatan for catatan in saring.catatan),
        f"catatan: {saring.catatan}")
    saring2 = tangcer.saring_sekolah(hasil, SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA,
                                     tanpa_kolom_sekolah=True)
    cek("dengan centang → semua baris diambil", saring2.jumlah_diterima == 9,
        f"diterima {saring2.jumlah_diterima}")
    cek("penyebabnya dikatakan terus terang di catatan",
        any("seluruh barisnya dianggap" in catatan for catatan in saring2.catatan),
        f"catatan: {saring2.catatan}")


def uji_berkas_bermasalah() -> None:
    skenario("10. Berkas bermasalah dilaporkan apa adanya (tidak dikarang)")
    with tempfile.TemporaryDirectory(prefix="tangcer-bad-") as tmp:
        kosong = Path(tmp) / "kosong.csv"
        kosong.write_text("ini bukan daftar penerima\r\n", encoding="utf-8")
        try:
            tangcer.baca_berkas(kosong, ".csv")
            cek("berkas tanpa kolom NAMA/NISN ditolak", False, "tidak ada galat")
        except tangcer.TangcerError as galat:
            cek("berkas tanpa kolom NAMA/NISN ditolak", "tidak terbaca" in str(galat)
                or "judul kolom tidak ditemukan" in str(galat), str(galat))
        pindai = buat_pdf_pindai(Path(tmp) / "pindai.pdf")
        try:
            tangcer.baca_isi("pindai.pdf", pindai.read_bytes())
            cek("PDF tanpa teks dilaporkan (perlu OCR)", False, "tidak ada galat")
        except tangcer.TangcerError as galat:
            cek("PDF tanpa teks dilaporkan (perlu OCR)",
                "pindai" in str(galat) or "OCR" in str(galat), str(galat))
        rusak = Path(tmp) / "rusak.pdf"
        rusak.write_bytes(b"%PDF-1.4\nini bukan pdf sungguhan")
        try:
            tangcer.baca_isi("rusak.pdf", rusak.read_bytes())
            cek("PDF rusak ditolak dengan pesan jelas", False, "tidak ada galat")
        except tangcer.TangcerError as galat:
            cek("PDF rusak ditolak dengan pesan jelas", "tidak bisa dibaca" in str(galat),
                str(galat))


def uji_basis_data(hasil, saring) -> None:
    skenario("11. Penyimpanan: tidak menggandakan, bisa diekspor & dihapus")
    import datetime as dt

    from app import migrations

    migrations.run_migrations(verbose=False)
    tahun, semester, tahap = "2026", "Ganjil", "Tahap 1"
    # Keadaan awal diukur dulu: basis data kerja bisa sudah berisi data (mis. data
    # sungguhan sekolah), jadi semua pemeriksaan dihitung SEBAGAI SELISIH.
    ringkas_awal = tangcer.ringkas_penerima()
    jumlah_awal = ringkas_awal["total"]
    nominal_awal = ringkas_awal["nominal"]
    tahun_awal = set(tangcer.daftar_tahun())
    periode_awal = len(tangcer.daftar_penerima(tahun=tahun, semester=semester, batas=10_000))
    import_id = tangcer.buat_impor(
        nama_berkas="uji-tangcer.csv", path=None, ext=".csv", ukuran=1000,
        tahun=tahun, semester=semester, tahap=tahap, hasil=hasil, saring=saring,
        kolom=hasil.kolom, actor="uji", tanpa_kolom_sekolah=False)
    cek("kepala impor tercatat (pratinjau)", bool(import_id), f"id={import_id}")
    kepala = tangcer.get_impor(import_id) or {}
    cek("kepala impor menyimpan jumlah diterima & diabaikan",
        kepala.get("diterima") == 4 and kepala.get("sekolah_lain") == 5,
        f"{kepala.get('diterima')} / {kepala.get('sekolah_lain')}")
    cek("ringkasan sekolah lain disimpan sebagai data (bukan teks bebas)",
        isinstance(kepala.get("sekolah_ditemukan"), dict)
        and kepala["sekolah_ditemukan"].get("SMP NEGERI 1 TANGERANG") == 2,
        f"{kepala.get('sekolah_ditemukan')}")
    tersimpan = sum(1 for item in saring.diterima
                    if tangcer.simpan_penerima(import_id, item, tahun=tahun,
                                               semester=semester, tahap=tahap))
    cek("4 baris sekolah kita tersimpan", tersimpan == 4, f"tersimpan {tersimpan}")
    ulang = sum(1 for item in saring.diterima
                if tangcer.simpan_penerima(import_id, item, tahun=tahun,
                                           semester=semester, tahap=tahap))
    cek("berkas yang sama diunggah lagi tidak menambah baris ganda", ulang == 0,
        f"tambahan {ulang}")
    cek("data sekolah lain TIDAK ada di basis data",
        not any(item["sekolah"] == "SMP NEGERI 1 TANGERANG"
                for item in tangcer.daftar_penerima(batas=1000)))
    hitung = tangcer.cocokkan_dengan_siswa()
    cek("pencocokan dengan data siswa berjalan & dilaporkan",
        set(hitung) == {"nisn", "nik", "nama", "tidak_ada"},
        f"hasil: {hitung}")
    ringkas = tangcer.ringkas_penerima()
    cek("ringkasan menambah sesuai yang disimpan",
        ringkas["total"] == jumlah_awal + 4, f"total {ringkas['total']} (awal {jumlah_awal})")
    cek("nominal bertambah tepat sebesar nominal yang diimpor",
        abs(ringkas["nominal"] - nominal_awal - 4_000_000) < 0.01,
        f"naik {ringkas['nominal'] - nominal_awal}")
    csv_isi = tangcer.ekspor_csv(tahun, semester).decode("utf-8-sig")
    cek("ekspor CSV memuat baris yang baru diimpor + kepala",
        csv_isi.count("\r\n") == periode_awal + 4 + 1,
        f"baris: {csv_isi.count(chr(13) + chr(10))} (awal periode {periode_awal})")
    cek("ekspor CSV memuat nama penerima", "Achmad Fauzi Ramadhan" in csv_isi)
    xlsx_isi = tangcer.ekspor_xlsx(tahun, semester)
    cek("ekspor XLSX terbentuk (bukan kosong)", len(xlsx_isi) > 3000, f"{len(xlsx_isi)} bita")
    pdf_isi = tangcer.ekspor_pdf(tahun, semester)
    cek("ekspor PDF terbentuk & berawalan %PDF", pdf_isi.startswith(b"%PDF"), f"{len(pdf_isi)} bita")
    tangcer.tandai_impor(import_id, status="tersimpan")
    cek("kepala impor ditandai tersimpan + waktu simpan",
        bool((tangcer.get_impor(import_id) or {}).get("disimpan")))
    tangcer.hapus_impor(import_id)
    cek("impor bisa dihapus beserta penerimanya",
        tangcer.ringkas_penerima()["total"] == jumlah_awal,
        f"total {tangcer.ringkas_penerima()['total']}")
    cek("daftar tahun kembali seperti semula setelah dihapus",
        set(tangcer.daftar_tahun()) == tahun_awal,
        f"tahun: {tangcer.daftar_tahun()} (awal {sorted(tahun_awal)})")
    print(f"   (waktu uji: {dt.datetime.now():%H:%M:%S})")


def uji_sel_sekolah_bergabung() -> None:
    """Berkas Excel dari dinas sering menggabungkan sel nama sekolah (satu nama untuk blok)."""
    skenario("15. Nama sekolah pada sel bergabung (ditulis sekali untuk beberapa baris)")
    with tempfile.TemporaryDirectory(prefix="tangcer-merge-") as tmp:
        berkas = Path(tmp) / "gabung.csv"
        berkas.write_text(
            "NO;NISN;NAMA PESERTA DIDIK;NAMA SEKOLAH;ROMBEL\r\n"
            "1;0091234501;Achmad Fauzi Ramadhan;SMP NEGERI 2 TANGERANG;7A\r\n"
            "2;0091234502;Bella Safitri;;7B\r\n"
            "3;0091234503;Candra Wijaya Kusuma;;8A\r\n"
            "4;0091234505;Eko Prasetyo;SMP NEGERI 1 TANGERANG;7A\r\n"
            "5;0091234506;Fitriani Lestari;;8B\r\n",
            encoding="utf-8")
        hasil = tangcer.baca_berkas(berkas, ".csv")
    cek("5 baris terbaca walau sel sekolah hanya diisi di baris pertama tiap blok",
        hasil.jumlah_baris == 5, f"terbaca {hasil.jumlah_baris}")
    cek("nama sekolah diteruskan ke baris di bawahnya",
        [item.sekolah for item in hasil.baris[:3]] ==
        ["SMP NEGERI 2 TANGERANG", "SMP NEGERI 2 TANGERANG", "SMP NEGERI 2 TANGERANG"],
        f"sekolah: {[item.sekolah for item in hasil.baris]}")
    cek("penerusan itu dilaporkan di catatan (tidak diam-diam)",
        any("sel bergabung" in catatan for catatan in hasil.catatan),
        f"catatan: {hasil.catatan}")
    saring = tangcer.saring_sekolah(hasil, SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
    cek("penyaringan tetap benar: 3 milik kita, 2 sekolah lain",
        saring.jumlah_diterima == 3 and len(saring.ditolak) == 2,
        f"diterima {saring.jumlah_diterima}, ditolak {len(saring.ditolak)}")


def uji_urutan_kolom_lain() -> None:
    """Berkas dinas datang dengan urutan & istilah kolom yang berbeda-beda."""
    skenario("14. Berkas dengan urutan & istilah kolom berbeda")
    with tempfile.TemporaryDirectory(prefix="tangcer-urutan-") as tmp:
        berkas = Path(tmp) / "Daftar Penerima Tangcer2026 Ganjil.csv"
        teks = (
            "NO;NISN;NAMA;PENERIMA BANTUAN;JUMLAH BANTUAN;NAMA SEKOLAH;TAHAP\r\n"
            "1;0091234501;Achmad Fauzi Ramadhan;TANGCER;1000000;SMP NEGERI 2 TANGERANG;Tahap 1\r\n"
            "2;0091234505;Eko Prasetyo;TANGCER;1000000;SMP NEGERI 1 TANGERANG;Tahap 1\r\n"
        )
        berkas.write_text(teks, encoding="utf-8")
        hasil = tangcer.baca_berkas(berkas, ".csv")
    peta = {bidang: indeks for indeks, bidang in hasil.kolom.items()}
    cek("kolom «PENERIMA BANTUAN» dibaca sebagai jenis (bukan nama)",
        peta.get("jenis") == 3, f"peta: {peta}")
    cek("kolom «NAMA» tetap kolom nama siswa", peta.get("nama") == 2, f"peta: {peta}")
    cek("kolom «JUMLAH BANTUAN» dibaca sebagai nominal", peta.get("nominal") == 4,
        f"peta: {peta}")
    cek("kolom «NAMA SEKOLAH» dibaca sebagai sekolah", peta.get("sekolah") == 5,
        f"peta: {peta}")
    cek("nilai tiap kolom tidak tertukar",
        hasil.baris[0].nama == "Achmad Fauzi Ramadhan" and hasil.baris[0].jenis == "TANGCER"
        and hasil.baris[0].nominal == 1_000_000
        and hasil.baris[0].sekolah == "SMP NEGERI 2 TANGERANG",
        str(hasil.baris[0].ke_dict()))
    saring = tangcer.saring_sekolah(hasil, SEKOLAH_KITA, NPSN_KITA, DAERAH_KITA)
    cek("penyaringan tetap benar pada berkas berurutan lain",
        saring.jumlah_diterima == 1 and len(saring.ditolak) == 1,
        f"diterima {saring.jumlah_diterima}, ditolak {len(saring.ditolak)}")


def uji_halaman() -> None:
    skenario("12. Menu & halaman terdaftar di aplikasi")
    from app import auth, web
    from app.config import APP_VERSION

    petugas = auth.SessionUser(id=1, username="admin", nama="Admin", role=auth.ROLE_ADMIN)
    daftar_menu = web.nav_items(petugas)
    menu = [item for item in daftar_menu if item.get("href") == "/tangcer"]
    cek("menu «TANGCER» muncul di daftar menu aplikasi", bool(menu),
        f"menu: {[item.get('href') for item in daftar_menu]}")
    if menu:
        cek("menu TANGCER punya label & ikon",
            bool(menu[0].get("label")) and bool(menu[0].get("icon")), str(menu[0]))
        cek("menu TANGCER masuk grup «Data & Laporan»",
            web.NAV_GRUP.get("/tangcer") == "Data & Laporan",
            f"grup: {web.NAV_GRUP.get('/tangcer')}")
    cek("versi aplikasi ikut naik (≥ 0.1.18)", APP_VERSION >= "0.1.18", APP_VERSION)


def uji_web(berkas_csv: Path, berkas_pdf: Path) -> int:
    """Uji halaman & alurnya lewat HTTP (klien ASGI, aplikasi sungguhan)."""
    import asyncio

    import httpx

    from app.main import app

    jumlah_penerima = {"id": 0}
    berkas_impor = {"id": 0}

    async def alur() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://uji",
                                     follow_redirects=True) as klien:
            masuk = await klien.post("/login", data={"mode": "staff", "username": "admin",
                                                     "password": "admin123"})
            cek("Masuk sebagai petugas (admin) berhasil",
                masuk.status_code == 200 and "Keluar" in masuk.text,
                f"status {masuk.status_code}")

            halaman = await klien.get("/tangcer")
            cek("Halaman TANGCER terbuka", halaman.status_code == 200
                and "Unggah berkas mentah TANGCER" in halaman.text, f"status {halaman.status_code}")
            cek("Halaman menyebut sekolah kita secara jelas",
                SEKOLAH_KITA in halaman.text, "nama sekolah tidak muncul")
            cek("Formulir unggah menerima PDF (SK definitif)",
                'accept=".xlsx' in halaman.text and ".pdf" in halaman.text,
                "atribut accept tidak memuat .pdf")
            cek("Menu samping memuat TANGCER",
                'href="/tangcer"' in halaman.text and "TANGCER" in halaman.text)

            # Berkas jenis lain ditolak dengan pesan (bukan diam-diam gagal).
            salah = await klien.post("/tangcer/unggah",
                                     files={"berkas": ("catatan.docx", b"PK\x03\x04 palsu",
                                                       "application/vnd.openxmlformats")},
                                     data={"tahun": "2026", "semester": "Ganjil"})
            cek("Berkas .docx ditolak dengan pesan yang jelas",
                "belum didukung" in salah.text or "didukung" in salah.text.lower(),
                "pesan penolakan tidak muncul")

            # Unggah CSV mentah (berisi 4 baris sekolah kita + 5 baris sekolah lain).
            unggah = await klien.post(
                "/tangcer/unggah",
                files={"berkas": (berkas_csv.name, berkas_csv.read_bytes(), "text/csv")},
                data={"tahun": "2026", "semester": "Ganjil", "tahap": "Tahap 1"})
            cek("Unggah CSV diterima & langsung masuk halaman pratinjau",
                unggah.status_code == 200 and "Baris yang akan disimpan" in unggah.text,
                f"status {unggah.status_code}")
            cek("Pratinjau menyebut jumlah baris milik sekolah kita",
                "Milik sekolah kita" in unggah.text, "kartu ringkasan tidak ada")
            cek("Pratinjau menampilkan sekolah lain yang diabaikan",
                "SMP NEGERI 1 TANGERANG" in unggah.text and "diabaikan" in unggah.text)
            cek("Pratinjau memuat alasan tiap baris diambil",
                "Alasan diambil" in unggah.text)
            import_id = unggah.url.path.rsplit("/", 1)[-1] if unggah.url.path else "0"
            berkas_impor["id"] = int(import_id)

            simpan = await klien.post(f"/tangcer/impor/{berkas_impor['id']}/simpan")
            cek("Tombol Simpan benar-benar menyimpan (dengan laporan jumlah)",
                "siswa penerima disimpan" in simpan.text, "pesan simpan tidak muncul")
            cek("Pratinjau setelah simpan menandai «sudah disimpan»",
                "sudah disimpan" in simpan.text or "sudah pernah disimpan" in simpan.text)

            daftar = await klien.get("/tangcer")
            cek("Daftar penerima memuat siswa sekolah kita",
                "Achmad Fauzi Ramadhan" in daftar.text)
            cek("Daftar penerima TIDAK memuat siswa sekolah lain",
                "Eko Prasetyo" not in daftar.text and "Gilang Ramadhan" not in daftar.text)
            cek("Lencana kecocokan muncul di daftar",
                "belum dikenali" in daftar.text or "ya (" in daftar.text)

            # Filter & pencarian.
            cari = await klien.get("/tangcer?cari=Bella")
            cek("Pencarian nama menyaring daftar",
                "Bella Safitri" in cari.text and "Achmad Fauzi Ramadhan" not in cari.text)
            belum = await klien.get("/tangcer?cocok=belum")
            cek("Filter «belum dikenali» bekerja", belum.status_code == 200)

            # Ekspor tiga format.
            csv_ekspor = await klien.get("/tangcer/ekspor.csv?tahun=2026&semester=Ganjil")
            cek("Ekspor CSV dari halaman mengunduh berkas",
                csv_ekspor.status_code == 200 and "attachment" in csv_ekspor.headers.get("content-disposition", "")
                and "Achmad Fauzi Ramadhan" in csv_ekspor.text,
                f"status {csv_ekspor.status_code}")
            xlsx_ekspor = await klien.get("/tangcer/ekspor.xlsx")
            cek("Ekspor Excel mengunduh berkas .xlsx sungguhan",
                xlsx_ekspor.status_code == 200 and xlsx_ekspor.content[:2] == b"PK",
                f"{xlsx_ekspor.content[:4]!r}")
            pdf_ekspor = await klien.get("/tangcer/ekspor.pdf")
            cek("Ekspor PDF mengunduh berkas .pdf sungguhan",
                pdf_ekspor.status_code == 200 and pdf_ekspor.content.startswith(b"%PDF"),
                f"{pdf_ekspor.content[:4]!r}")

            # Detail & perbaikan satu penerima.
            penerima = tangcer.daftar_penerima(tahun="2026", semester="Ganjil", batas=1)
            cek("Ada data penerima untuk diuji pada basis data", bool(penerima))
            if penerima:
                pid = int(penerima[0]["id"])
                jumlah_penerima["id"] = pid
                detail = await klien.get(f"/tangcer/penerima/{pid}")
                cek("Halaman detail penerima terbuka", detail.status_code == 200
                    and "Perbaiki data penerima" in detail.text, f"status {detail.status_code}")
                ubah = await klien.post(f"/tangcer/penerima/{pid}/ubah",
                                        data={"nama": "Achmad Fauzi Ramadhan",
                                              "nisn": penerima[0]["nisn"] or "",
                                              "rombel": "7A", "nominal": "1000000",
                                              "keterangan": "diperiksa petugas"})
                cek("Perubahan data penerima tersimpan",
                    "Perubahan disimpan" in ubah.text)
                sesudah = tangcer.daftar_penerima(tahun="2026", semester="Ganjil", batas=50)
                baris = next((item for item in sesudah if int(item["id"]) == pid), {})
                cek("Nilai baru benar-benar tersimpan di basis data",
                    baris.get("keterangan") == "diperiksa petugas", str(baris.get("keterangan")))

            # Berkas PDF (SK definitif) juga bisa diunggah lewat halaman.
            unggah_pdf = await klien.post(
                "/tangcer/unggah",
                files={"berkas": (berkas_pdf.name, berkas_pdf.read_bytes(), "application/pdf")},
                data={"tahun": "2026", "semester": "Ganjil", "tahap": "Tahap 1"})
            cek("Unggah PDF SK definitif diterima & dipratinjau",
                unggah_pdf.status_code == 200 and "Baris yang akan disimpan" in unggah_pdf.text,
                f"status {unggah_pdf.status_code}")
            cek("Pratinjau PDF melaporkan tata letaknya",
                "tata letak PDF" in unggah_pdf.text, "catatan tata letak tidak ada")
            id_pdf = int(unggah_pdf.url.path.rsplit("/", 1)[-1] or 0)
            berkas_impor["id_pdf"] = id_pdf
            simpan_pdf = await klien.post(f"/tangcer/impor/{id_pdf}/simpan")
            cek("Hasil impor PDF ikut tersimpan",
                "siswa penerima disimpan" in simpan_pdf.text, "pesan simpan tidak muncul")
            cek("Baris PDF milik sekolah kita ikut masuk daftar",
                "Zulfa Aulia Nabilah" in (await klien.get("/tangcer?cari=Zulfa")).text)

            # Hapus impor PDF beserta penerima hasil impor itu (baris dari CSV tidak ikut hilang).
            sisa_sebelum = db.query_value(
                "SELECT COUNT(*) FROM tangcer_penerima WHERE import_id = ?", (id_pdf,), default=0)
            hapus_pdf = await klien.post(f"/tangcer/impor/{id_pdf}/hapus")
            sisa_sesudah = db.query_value(
                "SELECT COUNT(*) FROM tangcer_penerima WHERE import_id = ?", (id_pdf,), default=0)
            cek("Hapus impor menghapus penerima hasil impor itu saja",
                "dihapus" in hapus_pdf.text and sisa_sebelum > 0 and sisa_sesudah == 0,
                f"sebelum {sisa_sebelum}, sesudah {sisa_sesudah}")

            # Kerapian susunan halaman TANGCER (aturan yang sama dengan cek_tampilan).
            import importlib.util
            spesifikasi = importlib.util.spec_from_file_location(
                "cek_tampilan", AKAR / "scripts" / "cek_tampilan.py")
            modul = importlib.util.module_from_spec(spesifikasi)
            spesifikasi.loader.exec_module(modul)
            for jalur in ("/tangcer", f"/tangcer/impor/{berkas_impor['id']}",
                          f"/tangcer/penerima/{jumlah_penerima['id']}"):
                halaman_uji = await klien.get(jalur)
                pemeriksa = modul.PeriksaSusunan()
                pemeriksa.feed(halaman_uji.text)
                temuan = (pemeriksa.blok_dalam_sebaris + pemeriksa.baris_berisi_blok
                          + pemeriksa.kelas_ganda + modul.periksa_kerapian(halaman_uji.text, jalur))
                cek(f"Susunan halaman {jalur} rapi (tanpa blok dalam tag sebaris/gaya sebaris)",
                    not temuan, "; ".join(temuan[:3]))

            await klien.post("/logout")

    skenario("13. Halaman & alurnya lewat HTTP (unggah → pratinjau → simpan → kelola → ekspor)")
    asyncio.run(alur())
    # Bersihkan HANYA data yang dibuat uji ini (data lain di basis data tidak diusik).
    for kunci in ("id", "id_pdf"):
        if berkas_impor.get(kunci):
            tangcer.hapus_impor(berkas_impor[kunci])
    print(f"   (sisa penerima setelah dibersihkan: {tangcer.ringkas_penerima()['total']})")
    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Uji menu TANGCER")
    parser.add_argument("--berkas-ke", default="pratinjau/ronde58/berkas",
                        help="folder untuk menyimpan berkas contoh (bukti uji)")
    argumen = parser.parse_args()

    uji_pencocokan()
    uji_sel()
    hasil = uji_csv()
    uji_csv_koma()
    uji_xlsx()
    uji_pdf_tabel()
    uji_pdf_bagian()
    saring = uji_penyaringan(hasil)
    uji_tanpa_kolom_sekolah()
    uji_berkas_bermasalah()
    uji_basis_data(hasil, saring)
    uji_urutan_kolom_lain()
    uji_sel_sekolah_bergabung()
    uji_halaman()

    # Berkas contoh untuk uji halaman (dibuat di folder sementara).
    with tempfile.TemporaryDirectory(prefix="tangcer-web-") as tmp:
        berkas_csv = buat_csv(Path(tmp) / "Daftar Penerima Tangcer2026 Ganjil.csv")
        berkas_pdf = buat_pdf_tabel(Path(tmp) / "SK DEFINITIF TANGCER SMP TAHAP 1 2026.pdf")
        uji_web(berkas_csv, berkas_pdf)

    # Simpan berkas contoh sebagai bukti (bisa dibuka sendiri oleh user).
    if argumen.berkas_ke:
        tujuan = AKAR / argumen.berkas_ke
        tujuan.mkdir(parents=True, exist_ok=True)
        buat_csv(tujuan / "daftar-penerima-tangcer.csv")
        buat_xlsx(tujuan / "daftar-penerima-tangcer.xlsx")
        buat_pdf_tabel(tujuan / "sk-definitif-tabel.pdf")
        buat_pdf_bagian(tujuan / "sk-definitif-bagian.pdf")
        buat_csv(tujuan / "daftar-tanpa-kolom-sekolah.csv", dengan_sekolah=False)
        (tujuan / "daftar-sel-sekolah-bergabung.csv").write_text(
            "NO;NISN;NAMA PESERTA DIDIK;NAMA SEKOLAH;ROMBEL\r\n"
            "1;0091234501;Achmad Fauzi Ramadhan;SMP NEGERI 2 TANGERANG;7A\r\n"
            "2;0091234502;Bella Safitri;;7B\r\n"
            "3;0091234503;Candra Wijaya Kusuma;;8A\r\n"
            "4;0091234505;Eko Prasetyo;SMP NEGERI 1 TANGERANG;7A\r\n"
            "5;0091234506;Fitriani Lestari;;8B\r\n",
            encoding="utf-8")
        (tujuan / "Daftar Penerima Tangcer2026 Ganjil.csv").write_text(
            "NO;NISN;NAMA;PENERIMA BANTUAN;JUMLAH BANTUAN;NAMA SEKOLAH;TAHAP\r\n"
            "1;0091234501;Achmad Fauzi Ramadhan;TANGCER;1000000;SMP NEGERI 2 TANGERANG;Tahap 1\r\n"
            "2;0091234505;Eko Prasetyo;TANGCER;1000000;SMP NEGERI 1 TANGERANG;Tahap 1\r\n",
            encoding="utf-8")
        print(f"\nBerkas contoh disimpan di {tujuan}")

    gagal = [item for item in HASIL if not item[1]]
    print(f"\n[{'SELESAI' if not gagal else 'GAGAL'}] {len(HASIL) - len(gagal)} pemeriksaan lolos "
          f"pada {len(SKENARIO)} skenario" + (f" · {len(gagal)} GAGAL" if gagal else ""))
    for nama, _, keterangan in gagal:
        print(f"  · {nama} — {keterangan}")
    return 1 if gagal else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
