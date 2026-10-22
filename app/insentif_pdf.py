"""PDF siap cetak insentif: absensi PNS/PPPK + SPJ (Legal landscape).

Susunannya meniru berkas kerja sekolah 2025 sekolom mungkin: judul,
grid HARI/TANGGAL dua lajur dengan tanggal merah, legenda + keterangan
libur, tanda tangan; untuk SPJ: 18 kolom format baku terbaru + baris
JUMLAH + tiga penandatangan. Dokumen yang panjang otomatis bersambung
ke halaman berikut dengan kepala grid diulang.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from . import insentif
from .pdf import (
    LEGAL_LEBAR,
    LEGAL_TINGGI,
    WARNA_ABU,
    WARNA_ABU_TUA,
    WARNA_MERAH,
    _rakit_pdf,
    bungkus,
    gambar,
    kotak,
    muat,
    teks_bebas,
)

ML = 30.0          # margin kiri
MR = LEGAL_LEBAR - 30.0   # margin kanan
ATAS = LEGAL_TINGGI - 30.0  # garis atas isi
BAWAH = 30.0       # garis bawah isi


# --------------------------------------------------------------------------- #
# Absensi
# --------------------------------------------------------------------------- #
#: NO | NAMA/NIP | PANGKAT/GOL | JABATAN | 15×HARI | JUMLAH (total 948).
ABS_LEBAR = [30.0, 164.0, 110.0, 94.0] + [34.0] * 15 + [40.0]
ABS_TINGGI_ORANG = 52.0
ABS_SUB = 26.0

#: Kop absensi: logo pemda (kiri) + logo sekolah (kanan) + 3 baris teks.
#: Berkas logo diekstrak dari «ABSENSI GURU PNS.xlsx» lalu dikecilkan ke
#: tinggi 120px + RGB + zlib (lihat pratinjau/ronde67/CATATAN.md).
KOP_TINGGI = 78.0
KOP_LOGO_T = 56.0
_ASET = Path(__file__).resolve().parent / "assets"
_KOP_BERKAS = (("LogoPemda", "kop-pemda.dat", 105, 120),
               ("LogoSekolah", "kop-sekolah.dat", 120, 120))


def gambar_kop() -> dict[str, tuple[int, int, bytes]]:
    """Logo kop absensi siap daftar ke _rakit_pdf (nama → w, h, data)."""
    hasil = {}
    for nama, berkas, lebar, tinggi in _KOP_BERKAS:
        hasil[nama] = (lebar, tinggi, (_ASET / berkas).read_bytes())
    return hasil


def _sumbu_x(lebar: Sequence[float]) -> list[float]:
    posisi = [ML]
    for w in lebar:
        posisi.append(posisi[-1] + w)
    return posisi


def bagi_halaman(jumlah_baris: int, tinggi_baris: float, ruang_1: float,
                 ruang_lanjut: float, tinggi_kaki: float,
                 ) -> list[int]:
    """Bagi baris ke halaman; halaman terakhir menyisakan ruang kaki+judul.

    ``ruang_1``/``ruang_lanjut`` = ruang bersih untuk baris (tanpa kepala).
    Hasil: banyaknya baris tiap halaman, disebar rata supaya rapi.
    """
    if jumlah_baris <= 0:
        return [0]
    kap1 = max(1, int(ruang_1 // tinggi_baris))
    kap = max(1, int(ruang_lanjut // tinggi_baris))
    kap_akhir = max(1, int((ruang_lanjut - tinggi_kaki) // tinggi_baris))
    halaman = 1
    while True:
        if halaman == 1:
            muat = max(1, int((ruang_1 - tinggi_kaki) // tinggi_baris))
        else:
            muat = kap1 + kap * (halaman - 2) + kap_akhir
        if muat >= jumlah_baris:
            break
        halaman += 1
    if halaman == 1:
        return [jumlah_baris]
    # Sebar rata: halaman terakhir dibatasi kap_akhir.
    sisa = jumlah_baris
    hasil: list[int] = []
    for urutan in range(halaman):
        tinggal = halaman - urutan
        if urutan == 0:
            batas = kap1
        elif tinggal == 1:
            batas = kap_akhir
        else:
            batas = kap
        ambil = min(batas, -(-sisa // tinggal))  # bagi rata ke atas
        # Jangan sampai halaman berikut kekurangan jatah minimumnya.
        while sisa - ambil > sum(
                kap1 if i == 0 else (kap_akhir if i == halaman - 1 else kap)
                for i in range(urutan + 1, halaman)):
            ambil += 1
        hasil.append(ambil)
        sisa -= ambil
    return hasil


def _kepala_absensi(isi: list[str], grid: Mapping[str, list],
                    y: float) -> float:
    x = _sumbu_x(ABS_LEBAR)
    # Kolom identitas + JUMLAH digabung setinggi kepala (70): di berkas
    # A16:A20, B16:B20, C16:C20, D16:D20, T16:T20 memang sel gabung.
    tinggi_penuh = 18 + 15 + 11 + 15 + 11
    judul = ["NO", "NAMA/NIP", "PANGKAT /\nGOL.RUANG", "JABATAN"]
    for i, label in enumerate(judul):
        kotak(isi, x[i], y, ABS_LEBAR[i], tinggi_penuh, label.replace("\n", " "),
              8.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[4], y, sum(ABS_LEBAR[4:19]), 18, "HARI / TANGGAL",
          9.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[19], y, ABS_LEBAR[19], tinggi_penuh, "JUMLAH HADIR",
          7.0, True, "tengah", WARNA_ABU, 0.6)
    y -= 18
    for lajur in ("band1", "band2"):
        # Baris angka tanggal.
        for i, sel in enumerate(grid[lajur]):
            warna = None
            teks = ""
            if sel is None:
                warna = WARNA_ABU_TUA
            else:
                teks = str(sel["tgl"])
                if sel["libur"]:
                    warna = WARNA_MERAH
            kotak(isi, x[4 + i], y, 34.0, 15, teks, 9.0, True, "tengah", warna, 0.5)
        y -= 15
        # Baris nama hari.
        for i in range(15):
            sel = grid[lajur][i] if i < len(grid[lajur]) else None
            warna = WARNA_ABU
            teks = insentif.NAMA_HARI[i % 5]
            if sel is None:
                warna = WARNA_ABU_TUA
                teks = "" if lajur == "band2" else teks
            elif sel["libur"]:
                warna = WARNA_MERAH
            kotak(isi, x[4 + i], y, 34.0, 11, teks, 6.5, True, "tengah", warna, 0.5)
        y -= 11
    return y


def _baris_absensi(isi: list[str], grid: Mapping[str, list], nomor: int,
                   orang: Mapping[str, Any], y: float) -> float:
    x = _sumbu_x(ABS_LEBAR)
    nama = str(orang.get("nama_tampil") or "")
    nip = insentif.format_nip_spasi(orang.get("nip"))
    nip_baris = f"NIP. {nip}" if nip else ""
    jabatan = str(orang.get("jabatan") or "")
    jab_absen = "Kepala Sekolah" if jabatan.lower() == "kepala sekolah" else "Guru"
    # Kolom identitas setinggi dua sub-baris.
    kotak(isi, x[0], y, ABS_LEBAR[0], ABS_TINGGI_ORANG, str(nomor),
          9.0, False, "tengah", None, 0.5)
    nama_muat, ukuran_nama = muat(nama, 9.0, ABS_LEBAR[1] - 4, True)
    nip_muat, ukuran_nip = muat(nip_baris, 8.5, ABS_LEBAR[1] - 4, True)
    isi.append(f"0 0 0 RG 0.5 w {x[1]:.2f} {y - ABS_TINGGI_ORANG:.2f} "
               f"{ABS_LEBAR[1]:.2f} {ABS_TINGGI_ORANG:.2f} re S")
    teks_bebas(isi, x[1] + 3, y - 17, nama_muat, ukuran_nama, True)
    teks_bebas(isi, x[1] + 3, y - 17 - 15, nip_muat, ukuran_nip, True)
    kotak(isi, x[2], y, ABS_LEBAR[2], ABS_TINGGI_ORANG,
          str(orang.get("pangkat") or orang.get("gol") or ""),
          8.5, False, "tengah", None, 0.5)
    kotak(isi, x[3], y, ABS_LEBAR[3], ABS_TINGGI_ORANG, jab_absen,
          9.0, False, "tengah", None, 0.5)
    kotak(isi, x[19], y, ABS_LEBAR[19], ABS_TINGGI_ORANG, "",
          9.0, False, "tengah", None, 0.5)
    # Dua sub-baris tanda kehadiran (dibiarkan kosong untuk diisi tangan).
    for lajur in ("band1", "band2"):
        for i, sel in enumerate(grid[lajur]):
            warna = None
            if sel is None:
                warna = WARNA_ABU_TUA
            elif sel["libur"]:
                warna = WARNA_MERAH
            kotak(isi, x[4 + i], y, 34.0, ABS_SUB, "", 10.0, False,
                  "tengah", warna, 0.5)
        y -= ABS_SUB
    return y


def _kaki_absensi(isi: list[str], merah: Mapping[int, str], ttd: Mapping[str, str],
                  tgl: int, bulan: int, tahun: int, y: float) -> float:
    isi.append(f"0.6 w {ML:.2f} {y:.2f} m {MR:.2f} {y:.2f} l S")
    y -= 14
    x_ket = ML + 2
    teks_bebas(isi, x_ket, y, "Keterangan :", 10.0, True)
    y_kanan = y
    y -= 14
    for kode, arti in (("S", "SAKIT"), ("I", "IZIN"), ("C", "CUTI"),
                       ("DL", "DINAS LUAR")):
        teks_bebas(isi, x_ket, y, f"{kode}  :  {arti}", 10.0, False)
        y -= 13
    y -= 3
    teks_bebas(isi, x_ket, y, "Keterangan lainnya :", 10.0, True)
    y -= 14
    for tanggal in sorted(merah):
        teks_bebas(isi, x_ket, y, f"{tanggal}  :  {merah[tanggal]}", 10.0, False)
        y -= 13
    # Blok tanda tangan (kanan).
    x_ttd = ML + 640
    nama_bulan = insentif.NAMA_BULAN_KECIL[bulan]
    teks_bebas(isi, x_ttd, y_kanan, f"Tangerang, {tgl} {nama_bulan} {tahun}", 10.0)
    teks_bebas(isi, x_ttd, y_kanan - 14, "Kepala Sekolah", 10.0)
    teks_bebas(isi, x_ttd, y_kanan - 28, "UPT SMP Negeri 2 Tangerang,", 10.0)
    nama_ks, uk = muat(ttd.get("ks_nama") or "", 10.0, MR - x_ttd, True)
    teks_bebas(isi, x_ttd, y_kanan - 96, nama_ks, uk, True)
    nip_ks = insentif.format_nip_spasi(ttd.get("ks_nip"))
    teks_bebas(isi, x_ttd, y_kanan - 110, f"NIP. {nip_ks}" if nip_ks else "", 10.0)
    return min(y, y_kanan - 124)


def _kop_absensi(isi: list[str], y: float) -> float:
    """Kop sekolah di halaman pertama absensi (logo + 3 baris + garis ganda).

    Teks kop mengikuti data milik sekolah: «PEMERINTAH {kota}» dari
    Pengaturan, «UPT {unit kerja}» dari Pengaturan + kaki berkas 2025.
    """
    try:
        atur = insentif.baca_pengaturan()
    except Exception:
        atur = {}
    baris1 = f"PEMERINTAH {str(atur.get('kota') or 'KOTA TANGERANG').strip()}"
    baris3 = f"UPT {str(atur.get('unit_kerja') or 'SMP NEGERI 2 TANGERANG').strip()}"
    lebar_logo = KOP_LOGO_T * 105 / 120
    gambar(isi, ML + 6, y - 4, lebar_logo, KOP_LOGO_T, "LogoPemda")
    gambar(isi, MR - 6 - KOP_LOGO_T, y - 4, KOP_LOGO_T, KOP_LOGO_T, "LogoSekolah")
    teks_bebas(isi, ML, y - 20, baris1, 12.0, True, "tengah", MR)
    teks_bebas(isi, ML, y - 38, "DINAS PENDIDIKAN", 12.0, True, "tengah", MR)
    teks_bebas(isi, ML, y - 58, baris3, 14.0, True, "tengah", MR)
    garis = y - KOP_TINGGI + 8
    isi.append(f"0 0 0 RG 1.6 w {ML:.2f} {garis:.2f} m {MR:.2f} {garis:.2f} l S")
    isi.append(f"0 0 0 RG 0.6 w {ML:.2f} {garis - 3:.2f} m {MR:.2f} {garis - 3:.2f} l S")
    return y - KOP_TINGGI


def halaman_absensi(dokumen: str, periode: Mapping[str, Any],
                    roster: Sequence[Mapping[str, Any]]) -> list[bytes]:
    """Susun halaman-halaman PDF absensi (PNS/PPPK)."""
    tahun = int(periode["tahun"])
    bulan = int(periode["bulan"])
    merah = insentif.baca_libur_periode(periode)
    grid = insentif.grid_absensi(tahun, bulan, merah)
    ttd = insentif.baca_ttd(periode)
    try:
        tgl = int(periode.get("tgl_absensi") or 0) or insentif.tanggal_terakhir(tahun, bulan)
    except (ValueError, TypeError):
        tgl = insentif.tanggal_terakhir(tahun, bulan)
    label = "PNS" if dokumen == "pns" else "PPPK"

    tinggi_judul = 3 * 17 + 8
    tinggi_kepala = 18 + 15 + 11 + 15 + 11
    tinggi_kaki = 14 + 4 * 13 + 3 + 14 + max(0, len(merah)) * 13 + 8
    tinggi_kaki = max(tinggi_kaki, 140.0)
    ruang = ATAS - BAWAH
    kelompok = bagi_halaman(len(roster), ABS_TINGGI_ORANG,
                            ruang - KOP_TINGGI - tinggi_judul - tinggi_kepala,
                            ruang - tinggi_kepala, tinggi_kaki)

    halaman: list[bytes] = []
    nomor = 0
    for urutan, banyak in enumerate(kelompok):
        isi: list[str] = []
        y = ATAS
        if urutan == 0:
            y = _kop_absensi(isi, y)
            judul = f"DAFTAR HADIR TENAGA PENDIDIK ( {label} )"
            teks_bebas(isi, ML, y - 13, judul, 13.0, True, "tengah", MR)
            teks_bebas(isi, ML, y - 30, f"TAHUN ANGGARAN {tahun}", 11.0, True,
                       "tengah", MR)
            teks_bebas(isi, ML, y - 47,
                       f"BULAN : {insentif.NAMA_BULAN[bulan]} {tahun}", 11.0, True)
            y -= tinggi_judul
        y = _kepala_absensi(isi, grid, y)
        for orang in roster[nomor:nomor + banyak]:
            nomor += 1
            y = _baris_absensi(isi, grid, nomor, orang, y)
        if urutan == len(kelompok) - 1:
            _kaki_absensi(isi, merah, ttd, tgl, bulan, tahun, y - 6)
        halaman.append(("\n".join(isi) + "\n").encode("latin-1", "replace"))
    return halaman


def pdf_absensi(dokumen: str, periode: Mapping[str, Any],
               roster: Sequence[Mapping[str, Any]]) -> bytes:
    """PDF absensi PNS/PPPK siap cetak."""
    return _rakit_pdf(halaman_absensi(dokumen, periode, roster),
                      LEGAL_LEBAR, LEGAL_TINGGI, gambar_kop())


# --------------------------------------------------------------------------- #
# SPJ
# --------------------------------------------------------------------------- #
#: 18 kolom format baku: NO Nama NIP NPWP Rek NIK ASN NONASN GOL Jabatan
#: Unit Kec Bulan Bayar PPh Terima TTD1 TTD2 (total 948).
SPJ_LEBAR = [16.0, 100.0, 76.0, 69.0, 56.0, 67.0, 20.0, 40.0, 33.0, 48.0,
             96.0, 60.0, 41.0, 43.0, 39.0, 47.0, 46.0, 51.0]
SPJ_TINGGI_BARIS = 22.0


def _kepala_spj(isi: list[str], bulan: int, y: float) -> float:
    x = _sumbu_x(SPJ_LEBAR)
    nama_bulan = insentif.NAMA_BULAN_KECIL[bulan]
    sel = [
        (0, 1, "NO"), (1, 2, "Nama"), (2, 3, "NIP"), (3, 4, "NPWP"),
        (4, 5, "NO REKENING"), (5, 6, "NIK"), (8, 9, "GOL RUANG"),
        (9, 10, "JABATAN"), (10, 11, "UNIT KERJA"),
        (11, 12, "KECAMATAN UNIT KERJA"), (14, 15, "PPh"),
    ]
    for awal, akhir, label in sel:
        kotak(isi, x[awal], y, sum(SPJ_LEBAR[awal:akhir]), 30, label,
              7.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[6], y, SPJ_LEBAR[6] + SPJ_LEBAR[7], 15, "STATUS",
          7.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[6], y - 15, SPJ_LEBAR[6], 15, "ASN",
          7.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[7], y - 15, SPJ_LEBAR[7], 15, "NON ASN",
          7.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[12], y, SPJ_LEBAR[12], 15, "BULAN",
          7.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[12], y - 15, SPJ_LEBAR[12], 15, nama_bulan,
          7.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[13], y, SPJ_LEBAR[13], 30, "JUMLAH YANG DI BAYAR",
          7.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[15], y, SPJ_LEBAR[15], 30, "JUMLAH YANG DI TERIMA",
          7.5, True, "tengah", WARNA_ABU, 0.6)
    kotak(isi, x[16], y, SPJ_LEBAR[16] + SPJ_LEBAR[17], 30, "TTD",
          7.5, True, "tengah", WARNA_ABU, 0.6)
    return y - 30


def _titik_ttd(nomor: int, lebar_tersedia: float) -> str:
    from .pdf import _lebar
    angka = str(nomor)
    sisa = lebar_tersedia - _lebar(angka, 7.0, False)
    jumlah = max(3, int(sisa // _lebar(".", 7.0, False)))
    return angka + "." * jumlah


def _baris_spj(isi: list[str], nomor: int, orang: Mapping[str, Any],
               unit: str, kecamatan: str, y: float) -> float:
    x = _sumbu_x(SPJ_LEBAR)
    h = SPJ_TINGGI_BARIS
    nip = insentif.hanya_digit(orang.get("nip"))
    asn = bool(nip)
    tarif = int(orang.get("tarif") or 0)
    pph = int(orang.get("pph_nominal") or 0)
    npwp = insentif.format_npwp(orang.get("npwp"))
    npwp_muat, uk_npwp = muat(npwp, 7.0, SPJ_LEBAR[3] - 4, False)
    rek = str(orang.get("rekening") or "")
    rek_muat, uk_rek = muat(rek, 7.0, SPJ_LEBAR[4] - 4, False)
    nik = str(orang.get("nik") or "")
    nik_muat, uk_nik = muat(nik, 7.0, SPJ_LEBAR[5] - 4, False)
    kotak(isi, x[0], y, SPJ_LEBAR[0], h, str(nomor), 7.0, False, "tengah")
    kotak(isi, x[1], y, SPJ_LEBAR[1], h, str(orang.get("nama_tampil") or ""),
          7.0, False, "kiri", None, 0.5, True, 2)
    nip_muat, uk_nip = muat(nip, 7.0, SPJ_LEBAR[2] - 4, False)
    kotak(isi, x[2], y, SPJ_LEBAR[2], h, nip_muat, uk_nip, False, "tengah")
    kotak(isi, x[3], y, SPJ_LEBAR[3], h, npwp_muat, uk_npwp, False, "tengah")
    kotak(isi, x[4], y, SPJ_LEBAR[4], h, rek_muat, uk_rek, False, "tengah")
    kotak(isi, x[5], y, SPJ_LEBAR[5], h, nik_muat, uk_nik, False, "tengah")
    kotak(isi, x[6], y, SPJ_LEBAR[6], h, "ASN" if asn else "", 7.0, False, "tengah")
    kotak(isi, x[7], y, SPJ_LEBAR[7], h, "" if asn else "NON ASN",
          7.0, False, "tengah")
    kotak(isi, x[8], y, SPJ_LEBAR[8], h, str(orang.get("gol") or ""),
          7.0, False, "tengah")
    kotak(isi, x[9], y, SPJ_LEBAR[9], h, str(orang.get("jabatan") or ""),
          7.0, False, "kiri", None, 0.5, True, 2)
    unit_muat, uk_unit = muat(unit, 7.0, SPJ_LEBAR[10] - 4, False)
    kotak(isi, x[10], y, SPJ_LEBAR[10], h, unit_muat, uk_unit, False, "tengah")
    kec_muat, uk_kec = muat(kecamatan, 7.0, SPJ_LEBAR[11] - 4, False)
    kotak(isi, x[11], y, SPJ_LEBAR[11], h, kec_muat, uk_kec, False, "tengah")
    kotak(isi, x[12], y, SPJ_LEBAR[12], h, insentif.rupiah(tarif),
          7.0, False, "tengah")
    kotak(isi, x[13], y, SPJ_LEBAR[13], h, insentif.rupiah(tarif),
          7.0, False, "tengah")
    kotak(isi, x[14], y, SPJ_LEBAR[14], h, insentif.rupiah(pph),
          7.0, False, "tengah")
    kotak(isi, x[15], y, SPJ_LEBAR[15], h, insentif.rupiah(tarif - pph),
          7.0, False, "tengah")
    ganjil = nomor % 2 == 1
    ttd1 = _titik_ttd(nomor, SPJ_LEBAR[16] - 4) if ganjil else ""
    ttd2 = "" if ganjil else _titik_ttd(nomor, SPJ_LEBAR[17] - 4)
    kotak(isi, x[16], y, SPJ_LEBAR[16], h, ttd1, 7.0, False, "kiri")
    kotak(isi, x[17], y, SPJ_LEBAR[17], h, ttd2, 7.0, False, "kiri")
    return y - h


def _kaki_spj(isi: list[str], ringkas: Mapping[str, int], ttd: Mapping[str, str],
              tgl: int, bulan: int, tahun: int, kota: str, y: float) -> float:
    x = _sumbu_x(SPJ_LEBAR)
    h = SPJ_TINGGI_BARIS
    kotak(isi, x[0], y, sum(SPJ_LEBAR[0:12]), h, "JUMLAH", 8.0, True, "kiri")
    for i, kunci in ((12, "total"), (13, "total"), (14, "pph"), (15, "terima")):
        angka, uk_angka = muat(insentif.rupiah(ringkas[kunci]), 7.0,
                               SPJ_LEBAR[i] - 4, True)
        kotak(isi, x[i], y, SPJ_LEBAR[i], h, angka, uk_angka, True, "tengah")
    kotak(isi, x[16], y, SPJ_LEBAR[16] + SPJ_LEBAR[17], h, "", 7.0)
    # Satu baris kosong sebelum titi mangsa — persis berkas (R52 kosong
    # antara JUMLAH R51 dan judul kaki R53).
    y -= h + 19
    nama_bulan = insentif.NAMA_BULAN_KECIL[bulan]
    x_kiri = x[1] + 2
    x_tengah = ML + 420
    x_kanan = x[15] + 2
    teks_bebas(isi, x_kiri, y, "Mengetahui/Menyetujui", 10.0, False)
    teks_bebas(isi, x_kanan, y, f"Tangerang, {tgl} {nama_bulan} {tahun}", 10.0)
    y -= 15
    teks_bebas(isi, x_kiri, y, "Bendahara Pengeluaran", 10.0, False)
    teks_bebas(isi, x_tengah, y, "Pengawas", 10.0, False, "tengah", x_tengah + 120)
    teks_bebas(isi, x_kanan, y, "Kepala Sekolah", 10.0, False)
    y -= 64
    bend, uk = muat(ttd.get("bendahara_nama") or "", 10.0, 220.0, True)
    teks_bebas(isi, x_kiri, y, bend, uk, True)
    awas, uk = muat(ttd.get("pengawas_nama") or "", 10.0, 220.0, True)
    teks_bebas(isi, x_tengah, y, awas, uk, True)
    ks, uk = muat(ttd.get("ks_nama") or "", 10.0, MR - x_kanan, True)
    teks_bebas(isi, x_kanan, y, ks, uk, True)
    y -= 14
    for x_pos, kunci in ((x_kiri, "bendahara_nip"), (x_tengah, "pengawas_nip"),
                         (x_kanan, "ks_nip")):
        nip = insentif.hanya_digit(ttd.get(kunci))
        teks_bebas(isi, x_pos, y, f"NIP. {nip}" if nip else "", 10.0)
    return y - 14


def halaman_spj(periode: Mapping[str, Any],
                roster: Sequence[Mapping[str, Any]]) -> list[bytes]:
    """Susun halaman-halaman PDF SPJ insentif."""
    tahun = int(periode["tahun"])
    bulan = int(periode["bulan"])
    ttd = insentif.baca_ttd(periode)
    try:
        tgl = int(periode.get("tgl_spj") or 0) or insentif.tanggal_terakhir(tahun, bulan)
    except (ValueError, TypeError):
        tgl = insentif.tanggal_terakhir(tahun, bulan)
    pengaturan = insentif.baca_pengaturan()
    unit = str(pengaturan.get("unit_kerja") or "")
    kecamatan = str(pengaturan.get("kecamatan") or "")
    kota = str(pengaturan.get("kota") or "")
    ringkas = insentif.ringkas_spj(roster)

    tinggi_judul = 3 * 16 + 8
    tinggi_kepala = 30.0
    tinggi_kaki = SPJ_TINGGI_BARIS + 10 + 15 + 64 + 14 + 14 + 4
    ruang = ATAS - BAWAH
    kelompok = bagi_halaman(len(roster), SPJ_TINGGI_BARIS,
                            ruang - tinggi_judul - tinggi_kepala,
                            ruang - tinggi_kepala, tinggi_kaki)

    halaman: list[bytes] = []
    nomor = 0
    for urutan, banyak in enumerate(kelompok):
        isi: list[str] = []
        y = ATAS
        if urutan == 0:
            teks_bebas(isi, ML, y - 13,
                       "DAFTAR PENERIMA DANA INSENTIF PENDIDIK DAN TENAGA "
                       "KEPENDIDIKAN NON PNS JENJANG SMP", 12.0, True, "tengah", MR)
            teks_bebas(isi, ML, y - 29,
                       f"BULAN : {insentif.NAMA_BULAN[bulan]} TAHUN ANGGARAN {tahun}",
                       11.0, True, "tengah", MR)
            teks_bebas(isi, ML, y - 45, kota or "KOTA TANGERANG",
                       11.0, True, "tengah", MR)
            y -= tinggi_judul
        y = _kepala_spj(isi, bulan, y)
        for orang in roster[nomor:nomor + banyak]:
            nomor += 1
            y = _baris_spj(isi, nomor, orang, unit, kecamatan, y)
        if urutan == len(kelompok) - 1:
            _kaki_spj(isi, ringkas, ttd, tgl, bulan, tahun, kota, y - 4)
        halaman.append(("\n".join(isi) + "\n").encode("latin-1", "replace"))
    return halaman


def pdf_spj(periode: Mapping[str, Any],
            roster: Sequence[Mapping[str, Any]]) -> bytes:
    """PDF SPJ insentif siap cetak."""
    return _rakit_pdf(halaman_spj(periode, roster), LEGAL_LEBAR, LEGAL_TINGGI)


def pdf_gabungan(periode: Mapping[str, Any]) -> bytes:
    """Satu PDF berisi absensi PNS + absensi PPPK + SPJ."""
    pid = int(periode["id"])
    halaman = halaman_absensi("pns", periode, insentif.roster_periode(pid, "pns"))
    halaman += halaman_absensi("pppk", periode, insentif.roster_periode(pid, "pppk"))
    halaman += halaman_spj(periode, insentif.roster_periode(pid, "spj"))
    return _rakit_pdf(halaman, LEGAL_LEBAR, LEGAL_TINGGI, gambar_kop())