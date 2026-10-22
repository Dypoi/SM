"""Pembuat PDF ringan — tanpa dependensi tambahan.

Aplikasi SM sengaja tetap ringan: agar bisa dipasang di komputer sekolah yang
belum tentu punya internet, PDF dibuat sendiri di sini alih-alih menambah
pustaka besar. Yang dihasilkan adalah PDF 1.4 sederhana berisi **satu tabel**
(judul, sub-judul, beberapa kolom) dengan huruf bawaan Helvetica sehingga
berkasnya kecil dan pasti terbuka di semua pembaca PDF.

Pemakaian::

    from app.pdf import buat_pdf_tabel

    pdf = buat_pdf_tabel(
        judul="Daftar Anggota Ekstrakurikuler",
        subjudul=["SMP Negeri 2 Contoh", "OSIS · Pembina: Budi Santoso"],
        kolom=[("No", 26), ("Nama", 150)],
        baris=[["1", "Ahmad Fauzi"]],
        catatan_kaki=["Dicetak dari aplikasi SM"],
    )
    Path("anggota.pdf").write_bytes(pdf)
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable, Sequence

# --------------------------------------------------------------------------- #
# Ukuran halaman & huruf
# --------------------------------------------------------------------------- #
A4_LEBAR = 595.28
A4_TINGGI = 841.89
#: Legal landscape (dipakai absensi & SPJ insentif): 14 × 8,5 inci.
LEGAL_LEBAR = 1008.0
LEGAL_TINGGI = 612.0
MARGIN = 36.0
TINGGI_BARIS = 16.0
UKURAN_TEKS = 9.0
UKURAN_JUDUL = 13.0

# Lebar karakter Helvetica (per 1000 satuan) untuk ASCII 32-126.
_LEBAR_BIASA = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)
_LEBAR_TEBAL = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
)

#: Penggantian huruf yang tidak ada di Helvetica standar (WinAnsi sederhana).
_GANTI = {
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...",
    "·": "-", "•": "-", "×": "x", "→": "->", "≤": "<=", "≥": ">=", "\u00a0": " ",
}


def _bersihkan(teks: object) -> str:
    """Ubah nilai apa pun menjadi teks ASCII yang aman untuk PDF."""
    if teks is None:
        return ""
    hasil = str(teks)
    for asal, ganti in _GANTI.items():
        hasil = hasil.replace(asal, ganti)
    return "".join(karakter if 32 <= ord(karakter) < 127 else "?" for karakter in hasil)


def _lebar(teks: str, ukuran: float, tebal: bool = False) -> float:
    tabel = _LEBAR_TEBAL if tebal else _LEBAR_BIASA
    total = 0
    for karakter in teks:
        kode = ord(karakter)
        total += tabel[kode - 32] if 32 <= kode <= 126 else 556
    return total * ukuran / 1000.0


def _potong(teks: str, ukuran: float, maks: float, tebal: bool = False) -> str:
    """Potong teks agar muat pada lebar kolom (ditandai "...")."""
    teks = _bersihkan(teks)
    if _lebar(teks, ukuran, tebal) <= maks:
        return teks
    potongan = teks
    while potongan and _lebar(potongan + "...", ukuran, tebal) > maks:
        potongan = potongan[:-1]
    return (potongan + "...") if potongan else ""


def _esc(teks: str) -> str:
    """Escape karakter khusus di dalam string PDF."""
    return teks.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _teks_pdf(x: float, y: float, teks: str, ukuran: float, tebal: bool = False) -> str:
    huruf = "/F2" if tebal else "/F1"
    return f"BT {huruf} {ukuran:g} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_esc(teks)}) Tj ET"


def _buat_halaman(judul: str, subjudul: Sequence[str], kolom: Sequence[tuple[str, float]],
                  baris: Sequence[Sequence[object]], nomor: int, jumlah: int,
                  catatan_kaki: Sequence[str], total_baris: int) -> tuple[bytes, int]:
    """Susun satu halaman; kembalikan (isi halaman, banyaknya baris terpakai)."""
    isi: list[str] = []
    y = A4_TINGGI - MARGIN

    isi.append(_teks_pdf(MARGIN, y, _potong(judul, UKURAN_JUDUL, A4_LEBAR - 2 * MARGIN, True),
                         UKURAN_JUDUL, True))
    y -= 16
    for baris_sub in subjudul:
        if baris_sub:
            isi.append(_teks_pdf(MARGIN, y, _potong(baris_sub, 10, A4_LEBAR - 2 * MARGIN), 10))
            y -= 13

    # Garis pemisah kepala halaman
    y -= 4
    isi.append(f"0.6 w {MARGIN:.2f} {y:.2f} m {A4_LEBAR - MARGIN:.2f} {y:.2f} l S")
    y -= 14

    # Kepala tabel
    x = MARGIN
    for label, lebar_kolom in kolom:
        isi.append(_teks_pdf(x + 2, y, _potong(label, 9, lebar_kolom - 4, True), 9, True))
        x += lebar_kolom
    y -= 5
    isi.append(f"0.6 w {MARGIN:.2f} {y:.2f} m {A4_LEBAR - MARGIN:.2f} {y:.2f} l S")
    y -= TINGGI_BARIS

    # Baris data
    terpakai = 0
    batas_bawah = MARGIN + 34
    for nilai_baris in baris:
        if y < batas_bawah:
            break
        x = MARGIN
        for (label, lebar_kolom), nilai_sel in zip(kolom, nilai_baris):
            rata_kanan = label.strip().lower() in {"no", "nilai", "jumlah", "l", "p"}
            teks = _potong(nilai_sel, UKURAN_TEKS, lebar_kolom - 6)
            posisi = x + 2
            if rata_kanan:
                posisi = x + lebar_kolom - 4 - _lebar(teks, UKURAN_TEKS)
            isi.append(_teks_pdf(max(posisi, x + 2), y, teks, UKURAN_TEKS))
            x += lebar_kolom
        y -= TINGGI_BARIS
        terpakai += 1

    if not baris:
        isi.append(_teks_pdf(MARGIN, y, "(belum ada data)", UKURAN_TEKS))
        terpakai = 0

    # Kaki halaman: setiap catatan ditulis pada barisnya sendiri supaya tidak
    # terpotong, dan nomor halaman di kanan bawah.
    baris_kaki = [baris for baris in catatan_kaki if baris][:3]
    y_kaki = MARGIN
    isi.append(f"0.6 w {MARGIN:.2f} {y_kaki + 12 + 10 * max(0, len(baris_kaki) - 1):.2f} m "
               f"{A4_LEBAR - MARGIN:.2f} {y_kaki + 12 + 10 * max(0, len(baris_kaki) - 1):.2f} l S")
    for urutan, baris_kaki_satu in enumerate(baris_kaki):
        y_baris = y_kaki + 10 * (len(baris_kaki) - 1 - urutan)
        lebar_teks = A4_LEBAR - 2 * MARGIN if urutan < len(baris_kaki) - 1 else A4_LEBAR - 2 * MARGIN - 150
        isi.append(_teks_pdf(MARGIN, y_baris, _potong(baris_kaki_satu, 8, lebar_teks), 8))
    isi.append(_teks_pdf(A4_LEBAR - MARGIN - 140, y_kaki,
                         f"Halaman {nomor} dari {jumlah}  ({total_baris} data)", 8))
    return ("\n".join(isi) + "\n").encode("latin-1", "replace"), terpakai


def buat_pdf_tabel(
    judul: str,
    kolom: Sequence[tuple[str, float]],
    baris: Iterable[Sequence[object]],
    subjudul: Sequence[str] = (),
    catatan_kaki: Sequence[str] = (),
) -> bytes:
    """Buat berkas PDF satu tabel; otomatis berpindah halaman bila panjang."""
    semua_baris = [list(item) for item in baris]
    batas_bawah = MARGIN + 34
    tinggi_tersedia = A4_TINGGI - MARGIN - (len([s for s in subjudul if s]) * 13 + 60) - batas_bawah
    per_halaman = max(1, int(tinggi_tersedia // TINGGI_BARIS))

    kelompok: list[list[list[object]]] = [
        semua_baris[i:i + per_halaman] for i in range(0, max(len(semua_baris), 1), per_halaman)
    ] or [[]]

    if not catatan_kaki:
        catatan_kaki = [f"Dicetak {dt.datetime.now().strftime('%d-%m-%Y %H:%M')}"]

    halaman: list[bytes] = []
    for nomor, potongan in enumerate(kelompok, start=1):
        isi, _ = _buat_halaman(judul, subjudul, kolom, potongan, nomor, len(kelompok),
                               catatan_kaki, len(semua_baris))
        halaman.append(isi)

    return _rakit_pdf(halaman)


def _rakit_pdf(halaman: Sequence[bytes], lebar: float = A4_LEBAR,
               tinggi: float = A4_TINGGI) -> bytes:
    """Rakit objek PDF lengkap dengan tabel xref yang benar."""
    objek: list[bytes] = []

    def tambah(isi: bytes) -> int:
        objek.append(isi)
        return len(objek)

    # 1 katalog, 2 daftar halaman, 3-4 huruf
    id_katalog = tambah(b"")     # diisi setelah nomor halaman diketahui
    id_pages = tambah(b"")
    id_f1 = tambah(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    id_f2 = tambah(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    id_halaman: list[int] = []
    for isi in halaman:
        id_isi = tambah(b"<< /Length %d >>\nstream\n" % len(isi) + isi + b"endstream")
        halaman_obj = (
            f"<< /Type /Page /Parent {id_pages} 0 R /MediaBox [0 0 {lebar:g} {tinggi:g}] "
            f"/Resources << /Font << /F1 {id_f1} 0 R /F2 {id_f2} 0 R >> >> "
            f"/Contents {id_isi} 0 R >>"
        ).encode("latin-1")
        id_halaman.append(tambah(halaman_obj))

    anak = " ".join(f"{nomor} 0 R" for nomor in id_halaman)
    objek[id_pages - 1] = f"<< /Type /Pages /Count {len(id_halaman)} /Kids [{anak}] >>".encode("latin-1")
    objek[id_katalog - 1] = f"<< /Type /Catalog /Pages {id_pages} 0 R >>".encode("latin-1")

    keluaran = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posisi: list[int] = []
    for nomor, isi in enumerate(objek, start=1):
        posisi.append(len(keluaran))
        keluaran += f"{nomor} 0 obj\n".encode("latin-1") + isi + b"\nendobj\n"

    mulai_xref = len(keluaran)
    keluaran += f"xref\n0 {len(objek) + 1}\n".encode("latin-1")
    keluaran += b"0000000000 65535 f \n"
    for pos in posisi:
        keluaran += f"{pos:010d} 00000 n \n".encode("latin-1")
    keluaran += (
        f"trailer\n<< /Size {len(objek) + 1} /Root {id_katalog} 0 R >>\n"
        f"startxref\n{mulai_xref}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(keluaran)


# --------------------------------------------------------------------------- #
# Mesin grid Legal landscape (absensi & SPJ insentif)
# --------------------------------------------------------------------------- #
#: Warna isi sel (RGB 0-1): merah libur, abu nama hari, abu sel tanpa tanggal.
WARNA_MERAH = (1.0, 0.0, 0.0)
WARNA_ABU = (0.851, 0.851, 0.851)
WARNA_ABU_TUA = (0.75, 0.75, 0.75)


def _warna(isi: list[str], rgb: tuple[float, float, float]) -> None:
    isi.append(f"{rgb[0]:g} {rgb[1]:g} {rgb[2]:g} rg")


def muat(teks: str, ukuran: float, maks: float, tebal: bool = False,
         terkecil: float = 6.0) -> tuple[str, float]:
    """Kecilkan huruf sampai teks muat (minimal ``terkecil`` lalu dipotong)."""
    teks = _bersihkan(teks)
    ukuran_kini = ukuran
    while ukuran_kini > terkecil and _lebar(teks, ukuran_kini, tebal) > maks:
        ukuran_kini -= 0.5
    return _potong(teks, ukuran_kini, maks, tebal), ukuran_kini


def bungkus(teks: str, ukuran: float, maks: float, tebal: bool = False,
            maksimal_baris: int = 4) -> list[str]:
    """Bagi teks menjadi beberapa baris agar muat pada lebar ``maks``."""
    teks = _bersihkan(teks).strip()
    if not teks:
        return []
    if _lebar(teks, ukuran, tebal) <= maks:
        return [teks]
    kata = teks.split()
    baris: list[str] = []
    kini = ""
    for potong in kata:
        usul = f"{kini} {potong}".strip()
        if _lebar(usul, ukuran, tebal) <= maks or not kini:
            kini = usul
        else:
            baris.append(kini)
            kini = potong
    if kini:
        baris.append(kini)
    # Kata raksasa (NIP dsb.) yang tetap kepanjangan: potong paksa.
    pecah: list[str] = []
    for satu in baris:
        while _lebar(satu, ukuran, tebal) > maks and len(satu) > 1:
            pecah.append(_potong(satu, ukuran, maks, tebal).rstrip("."))
            satu = satu[len(pecah[-1]):].lstrip()
        if satu:
            pecah.append(satu)
    if len(pecah) > maksimal_baris:
        pecah = pecah[:maksimal_baris - 1] + [
            _potong(" ".join(pecah[maksimal_baris - 1:]), ukuran, maks, tebal)]
    return pecah


def kotak(isi: list[str], x: float, y_atas: float, lebar_kotak: float,
          tinggi_kotak: float, teks: str = "", ukuran: float = 9.0,
          tebal: bool = False, rata: str = "kiri",
          isi_warna: tuple[float, float, float] | None = None,
          garis: float = 0.5, bingkai: bool = True,
          maksimal_baris: int = 4) -> None:
    """Gambar satu sel: isi warna + bingkai + teks rata & terbungkus.

    ``y_atas`` adalah sisi ATAS sel (gaya koordinat modul ini: y membesar
    ke atas, teks halaman disusun dari atas ke bawah).
    """
    bawah = y_atas - tinggi_kotak
    if isi_warna is not None:
        _warna(isi, isi_warna)
        isi.append(f"{x:.2f} {bawah:.2f} {lebar_kotak:.2f} {tinggi_kotak:.2f} re f")
    if bingkai:
        isi.append(f"0 0 0 RG {garis:g} w "
                   f"{x:.2f} {bawah:.2f} {lebar_kotak:.2f} {tinggi_kotak:.2f} re S")
    baris = bungkus(teks, ukuran, lebar_kotak - 4, tebal, maksimal_baris)
    if not baris:
        return
    tinggi_baris = ukuran * 1.2
    total = tinggi_baris * len(baris)
    # Baris pertama: teks seluruhnya di tengah vertikal sel.
    y = y_atas - (tinggi_kotak - total) / 2 - ukuran * 0.85
    huruf = "/F2" if tebal else "/F1"
    for satu in baris:
        if rata == "tengah":
            tx = x + (lebar_kotak - _lebar(satu, ukuran, tebal)) / 2
        elif rata == "kanan":
            tx = x + lebar_kotak - 2 - _lebar(satu, ukuran, tebal)
        else:
            tx = x + 2
        isi.append(f"0 0 0 rg BT {huruf} {ukuran:g} Tf 1 0 0 1 {tx:.2f} {y:.2f} "
                   f"Tm ({_esc(satu)}) Tj ET")
        y -= tinggi_baris


def teks_bebas(isi: list[str], x: float, y_dasar: float, teks: str,
               ukuran: float = 10.0, tebal: bool = False,
               rata: str = "kiri", batas_kanan: float = 0.0) -> None:
    """Teks tanpa sel (judul, kaki, tanda tangan)."""
    bersih = _bersihkan(teks)
    if rata == "tengah" and batas_kanan > x:
        x = x + (batas_kanan - x - _lebar(bersih, ukuran, tebal)) / 2
    elif rata == "kanan" and batas_kanan > x:
        x = batas_kanan - _lebar(bersih, ukuran, tebal)
    huruf = "/F2" if tebal else "/F1"
    isi.append(f"0 0 0 rg BT {huruf} {ukuran:g} Tf 1 0 0 1 {x:.2f} {y_dasar:.2f} "
               f"Tm ({_esc(bersih)}) Tj ET")
