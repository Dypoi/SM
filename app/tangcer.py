"""TANGCER — impor & pengelolaan siswa penerima bantuan (Tangerang Cerdas).

Menu ini mengolah **berkas mentah** dari dinas: daftar penerima berbentuk
Excel/CSV maupun **SK Definitif berbentuk PDF**. Karena berkas itu memuat banyak
sekolah sekaligus, baris yang disimpan ke aplikasi **hanya yang sekolahnya cocok
dengan sekolah kita** (nama pada Pengaturan Sekolah) — sisanya dihitung dan
dilaporkan, bukan disimpan.

Tiga hal yang dijaga modul ini:

1. **Kejujuran** — hasil baca (kolom yang dikenali, jumlah baris, sekolah yang
   ditemukan di berkas, alasan baris dilewati) selalu bisa dilihat sebelum
   disimpan; yang tidak terbaca dilaporkan apa adanya, bukan dikarang.
2. **Tidak menebak sekolah** — nama sekolah dinormalkan lebih dulu (huruf besar,
   tanda baca, singkatan ``SMPN`` → ``SMP NEGERI``, ``S.L.T.P.`` → ``SMP``, angka nol
   di depan disamakan), lalu dibandingkan berjenjang: NPSN → kata kunci → penanda
   (jenjang, ``NEGERI``/``SWASTA``, ``KOTA``/``KABUPATEN``) yang tidak boleh
   bertabrakan → penanda/wilayah yang boleh berbeda. Bila tetap tidak sama, baris itu
   **tidak** diambil — dan alasan tiap keputusan bisa dibaca di pratinjau.
3. **Tidak menggandakan baris** — setiap baris punya ``sidik`` (sidik jari) unik
   sehingga berkas yang diunggah dua kali tidak menghasilkan data ganda.

Format berkas: semua format spreadsheet yang sudah didukung aplikasi
(``.xlsx .xlsm .xltx .xls .xlsb .ods .csv .txt .tsv``) **dan** ``.pdf`` (teks,
bukan hasil pindai).

PDF dibaca **pembaca bawaan SM** (:mod:`app.pdf_baca`) yang hanya memakai modul
standar Python — jadi SK definitif tetap terbaca walau komputer sekolah belum
memasang pustaka tambahan apa pun (``pypdf`` hanya cadangan/pembanding bila
kebetulan terpasang). Tambahan **bedah berkas** (:func:`bedah_berkas`) dipakai
halaman TANGCER untuk memperlihatkan isi sebuah berkas apa adanya beserta
unduhan teksnya, supaya bagian yang belum terbaca bisa diperiksa/dilaporkan.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Sequence

from . import config, db, pdf_baca, services

log = logging.getLogger("sm.tangcer")


class TangcerError(RuntimeError):
    """Berkas tidak bisa dibaca / tidak berisi daftar penerima."""


# =========================================================================== #
# Nama sekolah: normalisasi & pencocokan
# =========================================================================== #
#: Kata yang **tidak** membedakan sekolah (dibuang sebelum membandingkan nama).
#: Jenjang (SMP/SMA/…) justru **dibiarkan** — SMP 2 dan SMA 2 jelas sekolah berbeda.
KATA_UMUM_SEKOLAH = {
    "NEGERI", "SWASTA", "N", "S", "NS",
    "PROV", "PROVINSI", "WILAYAH",
}
#: Jenjang yang ditulis dengan nama lama disamakan.
ALIAS_JENJANG = {
    "SLTP": "SMP", "SLTPN": "SMP NEGERI",
    "SLTA": "SMA", "SMU": "SMA", "SLTAN": "SMA NEGERI",
}
#: Penanda jenis daerah — **membedakan** sekolah («KOTA» ≠ «KABUPATEN»).
PENANDA_DAERAH = {"KOTA", "KOTAMADYA", "KAB", "KABUPATEN"}
#: Kata wilayah yang boleh berbeda tanpa membuat sekolah dianggap lain.
KATA_WILAYAH_UMUM = {"BANTEN", "JAWA", "BARAT", "INDONESIA", "JABODETABEK", "TANGERANG"}

#: Singkatan yang lazim dipakai pada berkas dinas.
SINGKATAN_SEKOLAH = {
    "SMPN": "SMP NEGERI",
    "SMAN": "SMA NEGERI",
    "SMKN": "SMK NEGERI",
    "MTSN": "MTS NEGERI",
    "MAN": "MA NEGERI",
    "SDN": "SD NEGERI",
}


def norm_teks(teks: Any) -> str:
    """Huruf besar, tanda baca → spasi, spasi ganda dirapikan."""
    if teks is None:
        return ""
    isi = unicodedata.normalize("NFKD", str(teks))
    isi = isi.upper()
    isi = re.sub(r"[^A-Z0-9]+", " ", isi)
    isi = re.sub(r"\b0+(\d)", r"\1", isi)  # «02» → «2», «007» → «7»
    return re.sub(r"\s+", " ", isi).strip()


def token_sekolah(nama: Any) -> list[str]:
    """Potong nama sekolah menjadi kata, dengan singkatan dibuka lebih dulu.

    Dua hal yang sering berbeda antar berkas dirapikan di sini: penulisan
    bertitik («S.M.P. Negeri 2») digabung kembali menjadi «SMP», dan singkatan
    («SMPN») dibuka menjadi «SMP NEGERI».
    """
    isi = norm_teks(nama)
    for singkat, panjang in SINGKATAN_SEKOLAH.items():
        isi = re.sub(rf"\b{singkat}\b", panjang, isi)
    for lama, baru in ALIAS_JENJANG.items():
        isi = re.sub(rf"\b{lama}\b", baru, isi)
    kata = [bagian for bagian in isi.split() if bagian]
    hasil: list[str] = []
    urut = 0
    while urut < len(kata):
        if len(kata[urut]) == 1:
            gabung = []
            while urut < len(kata) and len(kata[urut]) == 1:
                gabung.append(kata[urut])
                urut += 1
            hasil.append("".join(gabung) if len(gabung) > 1 else gabung[0])
            continue
        hasil.append(kata[urut])
        urut += 1
    return hasil


def kunci_sekolah(nama: Any, *, longgar: bool = False, tanpa_penanda: bool = False) -> frozenset[str]:
    """Kata kunci pembeda sekolah.

    ``longgar`` juga membuang kata wilayah (BANTEN, TANGERANG, …);
    ``tanpa_penanda`` membuang penanda KOTA/KABUPATEN.
    """
    buang = set(KATA_UMUM_SEKOLAH)
    if longgar:
        buang |= KATA_WILAYAH_UMUM
    if tanpa_penanda:
        buang |= PENANDA_DAERAH
    return frozenset(kata for kata in token_sekolah(nama) if kata not in buang)


def penanda_status(nama: Any) -> frozenset[str]:
    """«NEGERI» / «SWASTA» pada nama sekolah (kalau disebutkan)."""
    penanda = {kata for kata in token_sekolah(nama) if kata in {"NEGERI", "SWASTA"}}
    return frozenset(penanda)


def penanda_daerah(nama: Any) -> frozenset[str]:
    """«KOTA» / «KABUPATEN» pada nama sekolah (dibakukan jadi satu bentuk)."""
    penanda = {kata for kata in token_sekolah(nama) if kata in PENANDA_DAERAH}
    return {"KABUPATEN"} if penanda & {"KAB", "KABUPATEN"} else (
        {"KOTA"} if penanda else frozenset())


def npsn_dari_teks(teks: Any) -> str:
    """Ambil NPSN (8 angka) dari teks bebas, mis. «SMPN 2 TANGERANG (NPSN 20631000)»."""
    for angka in re.findall(r"\b\d{8}\b", str(teks or "")):
        return angka
    return ""


def cocok_sekolah(nama_berkas: Any, nama_kita: Any, npsn_kita: str = "",
                  daerah_kita: str = "") -> tuple[bool, str]:
    """Apakah nama sekolah pada berkas = sekolah kita? (beserta alasannya).

    Urutan pemeriksaan, dari yang paling kuat:

    1. **NPSN** sama pada teks berkas → cocok;
    2. kata kunci pembeda sama persis → cocok;
    3. penanda daerah bertabrakan (berkas «KABUPATEN», sekolah kita «KOTA» atau
       sebaliknya) → **tidak cocok** — dua sekolah bisa sebutannya sama;
    4. kata kunci sama setelah «KOTA/KABUPATEN» dibuang → cocok (nama sekolah kita
       sering ditulis tanpa penanda daerah);
    5. kata kunci sama setelah kata wilayah dibuang → cocok.

    Sisanya **tidak cocok**, dan alasannya selalu bisa dibaca.
    """
    teks = str(nama_berkas or "").strip()
    if not teks:
        return False, "nama sekolah kosong"
    if npsn_kita:
        npsn = npsn_dari_teks(teks)
        if npsn and npsn == str(npsn_kita).strip():
            return True, f"NPSN sama ({npsn})"
    kita = kunci_sekolah(nama_kita)
    mereka = kunci_sekolah(teks)
    ringkas_kita = " ".join(sorted(kita)) or "—"
    ringkas_mereka = " ".join(sorted(mereka)) or "—"
    if not kita or not mereka:
        return False, f"nama tidak lengkap («{teks}»)"
    if mereka == kita:
        return True, f"kata kunci sama ({ringkas_kita})"

    status_berkas = penanda_status(teks)
    status_kita = penanda_status(nama_kita)
    if status_berkas and status_kita and status_berkas != status_kita:
        return False, (f"status berbeda — berkas menyebut «{sorted(status_berkas)[0]}», "
                       f"sekolah kita «{sorted(status_kita)[0]}» («{teks}»)")

    daerah_berkas = penanda_daerah(teks)
    daerah_sekolah = penanda_daerah(nama_kita) or penanda_daerah(daerah_kita)
    if daerah_berkas and daerah_sekolah and daerah_berkas != daerah_sekolah:
        return False, (f"jenis daerah berbeda — berkas menyebut «{sorted(daerah_berkas)[0]}», "
                       f"sekolah kita «{sorted(daerah_sekolah)[0]}» («{teks}»)")

    tanpa_kita = kunci_sekolah(nama_kita, tanpa_penanda=True)
    tanpa_mereka = kunci_sekolah(teks, tanpa_penanda=True)
    if tanpa_mereka == tanpa_kita:
        return True, f"kata kunci sama setelah penanda KOTA/KABUPATEN dibuang ({ringkas_kita})"
    if kunci_sekolah(teks, longgar=True) == kunci_sekolah(nama_kita, longgar=True):
        beda = sorted(mereka.symmetric_difference(kita))
        return True, f"kata kunci sama setelah kata wilayah dibuang ({' '.join(beda)})"
    return False, (f"sekolah lain («{teks}» → {ringkas_mereka}, "
                   f"sekolah kita {ringkas_kita})")


# =========================================================================== #
# Pengenalan kolom
# =========================================================================== #
def _kunci_judul(judul: str) -> str:
    """Kunci judul kolom **tanpa spasi**.

    Judul bertingkat hasil gabungan potongan (mis. «NOMOR KARTU» + «KELUARGA», atau
    «TEMPA» + «T» + «LA» + «HIR») harus tetap dikenali sebagai satu judul — karena itu
    spasi dibuang sebelum dibandingkan.
    """
    return norm_teks(judul).replace(" ", "")


#: Sinonim judul kolom → nama bidang internal. Diperiksa berurutan.
SINONIM_KOLOM: list[tuple[str, tuple[str, ...]]] = [
    ("nisn", ("NISN",)),
    # Urutan penting: «NIK AYAH»/«NIK IBU» diperiksa SEBELUM «NIK» supaya tidak tertukar
    # dengan NIK siswa, dan «NAMA AYAH»/«NAMA IBU» sebelum «NAMA».
    ("nik_ayah", ("NIK AYAH", "NIK AYAH KANDUNG", "NIK AYAH/WALI")),
    ("nik_ibu", ("NIK IBU", "NIK IBU KANDUNG", "NIK IBU/WALI")),
    ("nik", ("NIK", "NIK SISWA", "NIK PESERTA DIDIK", "NOMOR INDUK KEPENDUDUKAN")),
    ("kk", ("NOMOR KARTU KELUARGA", "NO KARTU KELUARGA", "NOMOR KK", "NO KK",
            "KARTU KELUARGA", "NOMOR KARTU KELUARGA (KK)")),
    ("rekening", ("NO REKENING", "NOMOR REKENING", "REKENING", "NOREK", "NO BUKU TABUNGAN")),
    ("nama_ayah", ("NAMA AYAH", "NAMA AYAH KANDUNG", "AYAH", "NAMA AYAH/WALI")),
    ("nama_ibu", ("NAMA IBU", "NAMA IBU KANDUNG", "IBU", "NAMA IBU/WALI")),
    ("kelamin", ("JENIS KELAMIN", "KELAMIN", "L/P", "LP", "JENIS KELAMIN (L/P)")),
    ("tempat_lahir", ("TEMPAT LAHIR", "TEMPAT & TANGGAL LAHIR", "TEMPAT")),
    ("tanggal_lahir", ("TANGGAL LAHIR", "TGL LAHIR", "TANGGAL")),
    ("sekolah", ("NAMA SEKOLAH", "SEKOLAH", "SATUAN PENDIDIKAN", "SEKOLAH INDUK",
                 "UNIT SEKOLAH", "NAMA SATUAN PENDIDIKAN", "SEKOLAH PENERIMA",
                 "NAMA SEKOLAH PENERIMA")),
    # `jenis` diperiksa SEBELUM `nama`: berkas sering memakai judul «PENERIMA BANTUAN»,
    # dan kalau urutannya tertukar, judul itu terbaca sebagai kolom nama.
    ("jenis", ("JENIS BANTUAN", "JENIS", "KATEGORI", "PROGRAM", "KOMPONEN",
               "BENTUK BANTUAN", "PENERIMA BANTUAN", "BANTUAN")),
    ("nama", ("NAMA PESERTA DIDIK", "NAMA SISWA", "NAMA LENGKAP", "NAMA PENERIMA BANTUAN",
              "NAMA PENERIMA", "NAMA", "PENERIMA")),
    ("rombel", ("ROMBEL", "KELAS", "TINGKAT", "JENJANG", "ROMBEL SAAT INI")),
    ("nominal", ("NOMINAL", "JUMLAH BANTUAN", "BESAR BANTUAN", "BESARAN", "JUMLAH",
                 "NILAI", "TOTAL")),
    ("tahap", ("TAHAP",)),
    ("tahun", ("TAHUN ANGGARAN", "TAHUN PELAJARAN", "PERIODE", "TAHUN", "ANGKATAN")),
    ("keterangan", ("KETERANGAN", "CATATAN", "STATUS", "ALASAN")),
    ("no", ("NO", "NOMOR", "NO URUT", "NO.", "NO PENERIMA")),
    ("alamat", ("ALAMAT", "ALAMAT TINGGAL", "ALAMAT TINGGAL SISWA", "NAMA JALAN",
                "JALAN", "KAMPUNG")),
    ("kelurahan", ("KELURAHAN", "DESA", "DESA/KELURAHAN")),
    ("kecamatan", ("KECAMATAN", "KORWIL", "KORWIL/KECAMATAN")),
]

#: Kata yang menandakan baris rekap — jangan dianggap data penerima.
KATA_REKAP = ("JUMLAH", "TOTAL", "SUBTOTAL", "REKAPITULASI", "REKAP",
              "KETERANGAN", "CATATAN", "HALAMAN", "HAL ")


def tebak_bidang(judul: Any) -> str | None:
    """Tebak bidang internal dari judul kolom (mis. «Nama Peserta Didik» → nama)."""
    kunci = _kunci_judul(judul)
    if not kunci:
        return None
    for bidang, sinonim in SINONIM_KOLOM:
        for satu in sinonim:
            if kunci == _kunci_judul(satu):
                return bidang
    for bidang, sinonim in SINONIM_KOLOM:
        for satu in sinonim:
            padat = _kunci_judul(satu)
            if padat and (kunci.startswith(padat) or padat.endswith(kunci)):
                return bidang
    return None


def peta_kolom(header: Sequence[Any]) -> dict[int, str]:
    """Peta indeks kolom → bidang internal, dari satu baris judul."""
    peta: dict[int, str] = {}
    terpakai: set[str] = set()
    for indeks, judul in enumerate(header):
        bidang = tebak_bidang(judul)
        if not bidang or bidang in terpakai:
            continue
        peta[indeks] = bidang
        terpakai.add(bidang)
        if len(terpakai) == len(SINONIM_KOLOM):
            break
    return peta


def skor_header(baris: Sequence[Any]) -> int:
    """Berapa banyak kolom penting yang dikenali pada satu baris (untuk cari judul)."""
    peta = peta_kolom(baris)
    penting = sum(1 for bidang in peta.values() if bidang in {"nama", "nisn", "sekolah", "nik"})
    return penting * 2 + len(peta)


# =========================================================================== #
# Hasil baca
# =========================================================================== #
@dataclass
class BarisPenerima:
    """Satu calon penerima hasil pembacaan berkas (belum disimpan)."""

    nama: str = ""
    nisn: str = ""
    nik: str = ""
    nik_ayah: str = ""
    nik_ibu: str = ""
    kk: str = ""
    rekening: str = ""
    nama_ayah: str = ""
    nama_ibu: str = ""
    kelamin: str = ""
    tempat_lahir: str = ""
    tanggal_lahir: str = ""
    alamat: str = ""
    kelurahan: str = ""
    kecamatan: str = ""
    sekolah: str = ""
    rombel: str = ""
    jenis: str = ""
    nominal: float | None = None
    tahap: str = ""
    tahun: str = ""
    keterangan: str = ""
    no: str = ""
    student_id: int | None = None
    status_cocok: str = "belum_dicek"
    baris_ke: int = 0
    cocok: bool = False
    alasan: str = ""
    masalah: list[str] = dataclass_field(default_factory=list)

    @property
    def lengkap(self) -> bool:
        return bool(self.nama or self.nisn)

    @property
    def nama_orangtua(self) -> str:
        """Nama orang tua untuk SPJ: ayah dulu, kalau kosong ibu (dilaporkan apa adanya)."""
        return self.nama_ayah or self.nama_ibu

    @property
    def kelamin_rapi(self) -> str:
        """«L»/«P» dari kolom jenis kelamin apa pun tulisannya."""
        kunci = norm_teks(self.kelamin)
        if kunci in ("L", "LAKI LAKI", "LAKI-LAKI", "PRIA", "L P"):
            return "L"
        if kunci in ("P", "PEREMPUAN", "WANITA", "P R"):
            return "P"
        return bersih_teks(self.kelamin)

    def ke_dict(self) -> dict[str, Any]:
        return {
            "nama": self.nama, "nisn": self.nisn, "nik": self.nik,
            "nik_ayah": self.nik_ayah, "nik_ibu": self.nik_ibu, "kk": self.kk,
            "rekening": self.rekening, "nama_ayah": self.nama_ayah,
            "nama_ibu": self.nama_ibu, "nama_orangtua": self.nama_orangtua,
            "kelamin": self.kelamin, "tempat_lahir": self.tempat_lahir,
            "tanggal_lahir": self.tanggal_lahir, "alamat": self.alamat,
            "kelurahan": self.kelurahan, "kecamatan": self.kecamatan,
            "sekolah": self.sekolah,
            "rombel": self.rombel, "jenis": self.jenis, "nominal": self.nominal,
            "tahap": self.tahap, "tahun": self.tahun, "keterangan": self.keterangan,
            "no": self.no, "baris_ke": self.baris_ke, "cocok": self.cocok,
            "alasan": self.alasan, "masalah": self.masalah,
        }


@dataclass
class HasilBaca:
    """Hasil pembacaan satu berkas (mentah, sebelum disaring per sekolah)."""

    format: str = ""
    kolom: dict[int, str] = dataclass_field(default_factory=dict)
    baris: list[BarisPenerima] = dataclass_field(default_factory=list)
    sekolah_ditemukan: Counter = dataclass_field(default_factory=Counter)
    sekolah_tanpa_kolom: list[str] = dataclass_field(default_factory=list)
    catatan: list[str] = dataclass_field(default_factory=list)
    header_ke: int = 0
    #: TAHAP/SEMESTER/TAHUN ANGGARAN yang **tertulis** di kepala berkas (bila ada) — dipakai
    #: mengisi isian tahap supaya baris tahap 1 dan tahap 2 tidak tertukar (ronde 61).
    tahap: str = ""
    semester: str = ""
    tahun: str = ""

    @property
    def jumlah_baris(self) -> int:
        return len(self.baris)


# =========================================================================== #
# Pembacaan sel
# =========================================================================== #
def bersih_teks(nilai: Any) -> str:
    if nilai is None:
        return ""
    if isinstance(nilai, float) and nilai.is_integer():
        nilai = int(nilai)
    return re.sub(r"\s+", " ", str(nilai)).strip()


def bersih_nomor(nilai: Any) -> str:
    """NISN/NIK: buang tanda bukan angka (Excel kadang memberi «1234.0» atau «1234E+09»)."""
    teks = bersih_teks(nilai)
    if not teks:
        return ""
    if re.fullmatch(r"\d+\.0+", teks):
        teks = teks.split(".")[0]
    angka = re.sub(r"\D", "", teks)
    return angka


def bersih_nominal(nilai: Any) -> float | None:
    """«Rp 1.000.000», «1.000.000», «1,000,000», 1000000 → 1000000.0."""
    if nilai is None or nilai == "":
        return None
    if isinstance(nilai, (int, float)):
        return float(nilai)
    teks = str(nilai).upper().replace("RP", "").replace("IDR", "").strip()
    teks = re.sub(r"\s+", "", teks)
    if not re.fullmatch(r"[0-9][0-9.,]*", teks):
        return None  # «1juta», «-», «tidak ada» → tidak dikarang
    # Bentuk Indonesia: titik = ribuan, koma = desimal (dan sebaliknya).
    if "," in teks and "." in teks:
        if teks.rfind(",") > teks.rfind("."):
            teks = teks.replace(".", "").replace(",", ".")
        else:
            teks = teks.replace(",", "")
    elif "," in teks:
        teks = teks.replace(",", ".") if len(teks.split(",")[-1]) <= 2 else teks.replace(",", "")
    elif teks.count(".") > 1 or (teks.count(".") == 1 and len(teks.split(".")[-1]) == 3):
        teks = teks.replace(".", "")
    try:
        return float(teks)
    except ValueError:
        return None


def awal_rekap(baris: Sequence[Any]) -> str:
    """Teks sel pertama yang berisi, bila baris itu baris rekap/keterangan (bukan data)."""
    for sel in baris:
        teks = bersih_teks(sel)
        if not teks:
            continue
        return teks.upper() if any(teks.upper().startswith(kata) for kata in KATA_REKAP) else ""
    return ""


def isi_baris(baris: Sequence[Any], peta: dict[int, str]) -> BarisPenerima:
    """Ubah satu baris mentah menjadi calon penerima sesuai peta kolom."""
    item = BarisPenerima()
    for indeks, bidang in peta.items():
        if indeks >= len(baris):
            continue
        nilai = baris[indeks]
        if bidang in {"nisn", "nik", "nik_ayah", "nik_ibu", "kk", "rekening"}:
            setattr(item, bidang, bersih_nomor(nilai))
        elif bidang == "nominal":
            item.nominal = bersih_nominal(nilai)
        elif bidang == "no":
            item.no = bersih_teks(nilai)
        else:
            setattr(item, bidang, bersih_teks(nilai))
    return item


# =========================================================================== #
# Pembacaan spreadsheet (Excel/CSV)
# =========================================================================== #
def baca_baris_tabel(rows: Sequence[Sequence[Any]], *, sumber: str = "") -> HasilBaca:
    """Cari baris judul pada baris-baris spreadsheet, lalu uraikan isinya."""
    hasil = HasilBaca(format=sumber)
    kandidat = [(indeks, skor_header(baris)) for indeks, baris in enumerate(rows[:40])]
    kandidat = [(indeks, skor) for indeks, skor in kandidat if skor >= 6]
    if not kandidat:
        raise TangcerError(
            "Baris judul kolom tidak ditemukan — berkas ini tidak terbaca sebagai daftar "
            "penerima (butuh setidaknya kolom NAMA, NISN, atau NIK)."
        )
    indeks_judul, _ = max(kandidat, key=lambda item: (item[1], -item[0]))
    hasil.header_ke = indeks_judul + 1
    hasil.kolom = peta_kolom(rows[indeks_judul])
    if "nama" not in hasil.kolom.values() and "nisn" not in hasil.kolom.values():
        raise TangcerError(
            "Kolom «NAMA»/«NISN» tidak ada pada baris judul berkas ini — "
            "kolom yang terbaca: " + (", ".join(hasil.kolom.values()) or "—")
        )

    # Kolom sekolah bisa ditulis sekali untuk beberapa baris (sel bergabung di Excel):
    # nama itu diteruskan ke baris di bawahnya, dan jumlahnya dilaporkan di catatan.
    indeks_sekolah = next((indeks for indeks, bidang in hasil.kolom.items()
                           if bidang == "sekolah"), None)
    sekolah_aktif = ""
    diteruskan = 0

    for nomor, baris in enumerate(rows[indeks_judul + 1:], start=indeks_judul + 2):
        if not any(bersih_teks(sel) for sel in baris):
            continue
        teks_awal = awal_rekap(baris)
        if teks_awal:
            hasil.catatan.append(f"baris {nomor} dilewati (baris rekap/keterangan: {teks_awal[:60]})")
            continue
        if skor_header(baris) >= 6:
            continue  # judul berulang (halaman baru)
        item = isi_baris(baris, hasil.kolom)
        if not item.lengkap:
            hasil.catatan.append(f"baris {nomor} dilewati (tidak ada nama/NISN)")
            continue
        if indeks_sekolah is not None:
            nilai_sekolah = bersih_teks(baris[indeks_sekolah]) if indeks_sekolah < len(baris) else ""
            if nilai_sekolah:
                sekolah_aktif = nilai_sekolah
            elif sekolah_aktif:
                item.sekolah = sekolah_aktif
                diteruskan += 1
        item.baris_ke = nomor
        hasil.baris.append(item)

    if diteruskan:
        hasil.catatan.append(
            f"{diteruskan} baris memakai nama sekolah dari baris di atasnya (sel bergabung)")
    return hasil


# =========================================================================== #
# Pembacaan PDF
# =========================================================================== #
BATAS_KOLOM = re.compile(r"\s{2,}")


@dataclass
class GarisPdf:
    """Satu baris cetak pada PDF: potongan teks beserta posisi X-nya."""

    nomor: int
    y: float
    potongan: list[tuple[float, str]] = dataclass_field(default_factory=list)
    #: potongan mentah dari pembaca PDF (x, y, teks[, lebar]) — dipakai menyusun spasi
    potongan_asli: list[Any] = dataclass_field(default_factory=list)
    #: lebar tiap potongan pada :attr:`potongan` (sejajar indeksnya)
    lebar_potongan: list[float] = dataclass_field(default_factory=list)

    def sel(self) -> list[str]:
        """Potongan-potongan pada baris ini (satu potongan dipecah bila berjarak jauh).

        Kalau barisnya hanya satu potongan, teksnya diambil dari potongan **mentah** — di sana
        jarak antarsel masih berupa spasi ganda, sementara di potongan gabungan spasi ganda
        sudah dirapikan sehingga batas selnya hilang.
        """
        if len(self.potongan) == 1:
            asli = "".join(str(butir[2]) for butir in sorted(self.potongan_asli,
                                                             key=lambda b: b[0]))
            return _pisah(asli or self.potongan[0][1])
        return [teks for _, teks in self.potongan if teks.strip()]

    def teks(self) -> str:
        if self.potongan_asli:
            return pdf_baca._teks_satu_baris(self.potongan_asli).strip()
        return " ".join(teks for _, teks in self.potongan if teks.strip()).strip()


def _pisah(baris: str) -> list[str]:
    return [sel.strip() for sel in BATAS_KOLOM.split(baris.strip()) if sel.strip() != ""]


def _tampak_sekolah(teks: str) -> bool:
    """Apakah baris ini nama sekolah (untuk tata letak «judul bagian»)?"""
    kunci = norm_teks(teks)
    if not kunci or len(kunci.split()) < 2:
        return False
    kata = kunci.split()
    ada_jenjang = any(kata_satu in kata for kata_satu in
                      ("SMP", "SMA", "SMK", "MTS", "MA", "SD", "SMPN", "SMAN", "SMKN"))
    ada_status = any(kata_satu in kata for kata_satu in ("NEGERI", "SWASTA"))
    return ada_jenjang and ada_status


#: Awal nama sekolah yang cukup khas untuk dikenali **di tengah** teks yang sudah menempel.
#: Dipakai ronde 61: teks satu sel yang melimpah ke kolom sebelah bisa menempelkan nama
#: sekolah pada nama orang tanpa spasi («ERLIN YUSNAWATISMP NEGERI 8 TANGERANG»). Hanya
#: jenjang tiga huruf ke atas yang dipakai — «MA»/«MI»/«SD» terlalu mudah muncul di dalam
#: nama orang (mis. «ASMA», «MIRNA»).
TOKEN_SEKOLAH_TENGAH = ("SMPN", "SMPK", "SMP", "SMKN", "SMK", "SMAN", "SMA",
                        "MTSN", "MTSS", "MTS", "SLB", "SKH")
_POLA_AWAL_SEKOLAH = re.compile("|".join(TOKEN_SEKOLAH_TENGAH))
#: Kata yang menandakan nama sekolah (bukan nama orang) sesudah jenjangnya.
KATA_STATUS_SEKOLAH = ("NEGERI", "SWASTA", "SWATA", "KOTA", "KABUPATEN")
#: Jenjang yang hanya boleh dipisah dari teks sebelumnya bila ada kata status sesudahnya —
#: «SMA RANI» pada nama «DINI ASMA RANI» tidak ikut terbelah.
TOKEN_SEKOLAH_LEMAH = frozenset({"SMP", "SMPN", "SMA", "SMAN", "SMK", "SMKN"})
#: Jenjang yang berdiri sendiri sebagai satu potongan («SMP» pada «SMP NEGERI 8 TANGERANG»).
_POLA_JENJANG_SENDIRI = re.compile(r"^(SMPN|SMPK|SMP|SMKN|SMK|SMAN|SMA|MTSN|MTSS|MTS|SLB|SKH)$")
#: Penanda kelas yang ditulis apa adanya di dalam sel («Kelas 8.6», «Kelas 7I»).
_POLA_AWAL_KELAS = re.compile(
    r"^KELAS\s*(?P<angka>VIII|VII|IX|IV|VI|V|III|II|I|\d{1,2})"
    r"(?:\s*[.]\s*(?P<sub>\d{1,2}))?"
    # Huruf bagian kelas («VII A», «7I») hanya diambil kalau memang berdiri sendiri —
    # «Kelas 8.6AJAT SUDRAJAT» berhenti di «8.6» supaya nama ayahnya utuh.
    r"(?:\s*(?P<huruf>[A-Z])(?=\s|$))?",
    re.IGNORECASE)


def _nilai_kelas(cocok: re.Match) -> str:
    """Nilai kelas dari hasil :data:`_POLA_AWAL_KELAS` («Kelas 8.6» → «8.6»).

    Awalan «Kelas » dibuang, spasi di dalamnya dirapikan — nilai yang tersimpan sama
    bentuknya dengan kelas di dokumen («IX B», «8.6», «7I»).
    """
    teks = cocok.group(0).strip()
    potong = len("KELAS")
    while potong < len(teks) and teks[potong].isspace():
        potong += 1
    return re.sub(r"\s+", " ", teks[potong:]).strip()


def _awal_sekolah(teks: str) -> int:
    """Titik awal nama sekolah di dalam teks yang menempel, atau -1 bila tidak ada.

    Nama sekolah dianggap sah kalau sesudah jenjangnya masih ada kata lain (mis.
    «… YUSNAWATISMP NEGERI 8 TANGERANG» → titik «SMP»). Satu kata pendek seperti «SMA»
    saja tidak dianggap sekolah, supaya nama orang seperti «SITI ASMA» tidak terbelah.
    """
    bersih = bersih_teks(teks)
    if not bersih:
        return -1
    for cocok in _POLA_AWAL_SEKOLAH.finditer(bersih.upper()):
        mulai = cocok.start()
        token = cocok.group(0)
        if mulai == 0:
            continue
        if bersih[mulai:mulai + len(token)] != token:
            continue                       # hanya jenjang yang memang tertulis HURUF BESAR
        sisa = bersih[mulai:].strip()
        if len(sisa.split()) < 2 or len(sisa) < 8:
            continue
        if not _ekor_sekolah_yakin(sisa, token, bersih[:mulai]):
            continue                       # bukan nama sekolah (mis. «SMA RANI» pada nama)
        return mulai
    return -1


def _ekor_sekolah_yakin(ekor: str, token: str, kepala: str) -> bool:
    """Yakin ini nama sekolah, bukan bagian nama orang yang kebetulan sepotong.

    Dipakai untuk jenjang yang dipisah spasi — di situ batasnya lebih samar («DINI ASMA RANI»).
    Jenjang yang khas (MTs/MTSS/SKh/SMPK) langsung diterima; «SMP»/«SMA»/«SMK» baru diterima
    kalau ada kata status (NEGERI/SWASTA/…) atau kata sebelum jenjangnya jelas panjang —
    sisa satu huruf seperti «DINI **A**SMA» tidak dihitung.
    """
    kata = ekor.upper().split()
    if any(k in kata for k in KATA_STATUS_SEKOLAH):
        return True
    if token not in TOKEN_SEKOLAH_LEMAH:
        return True
    bagian_kepala = kepala.split()
    return bool(bagian_kepala) and len(bagian_kepala[-1]) >= 3


def _kembalikan_nama(item: BarisPenerima, nama: str) -> None:
    """Taruh kembali nama yang tertelan kolom sekolah ke kolom nama yang masih kosong."""
    for bidang in ("nama_ibu", "nama_ayah", "nama"):
        if not bersih_teks(getattr(item, bidang, "")):
            setattr(item, bidang, nama)
            return


#: Awal nama sekolah yang lazim pada berkas dinas (termasuk Sekolah Khusus & Luar Biasa).
POLA_AWAL_NAMA_SEKOLAH = re.compile(
    r"^(SMP|SMPN|SMPK|SMP-?IT|SMA|SMAN|SMK|SMKN|MTSS|MTSN|MTS|MA|MAN|MI|MIN|SD|SDN|SKH|SLB"
    r"|SEKOLAH|PONPES|PESANTREN|PKBM|KB|TK|PAUD)\b", re.IGNORECASE)


def _tampak_nama_sekolah(teks: str) -> bool:
    """Apakah nilai kolom sekolah memang berbentuk nama sekolah (bukan nama orang)."""
    return bool(POLA_AWAL_NAMA_SEKOLAH.match(bersih_teks(teks)))


def _pisah_bocor(item: BarisPenerima) -> list[str]:
    """Kembalikan isi sel yang tertelan kolom sebelah (ronde 61).

    Dua bentuk yang benar-benar ditemui pada berkas SK dinas:

    * **penanda kelas menempel pada nama** — «Kelas 8.6AJAT SUDRAJAT» pada kolom nama ayah
      (jarak antar-potongannya nol, jadi tidak bisa dibedakan lewat posisi);
    * **nama sekolah menempel pada nama orang** — «ERLIN YUSNAWATISMP NEGERI 8 TANGERANG».

    Isinya dipindahkan ke kolom yang benar (kelas → rombel, sekolah → sekolah) dan sisanya
    tetap di kolom asalnya. Bila nama orang justru yang menempel di kolom sekolah, namanya
    dikembalikan ke kolom nama yang masih kosong (ibu lebih dulu — sel di sebelah kiri kolom
    sekolah) dan dicatat supaya bisa diperiksa.
    """
    catatan: list[str] = []
    # 1) «Kelas …» yang menempel di depan teks sebuah kolom.
    for bidang in ("nama", "nama_ayah", "nama_ibu", "tempat_lahir"):
        nilai = bersih_teks(getattr(item, bidang, ""))
        if not nilai:
            continue
        cocok = _POLA_AWAL_KELAS.match(nilai)
        if not cocok:
            continue
        sisa = nilai[cocok.end():].strip()
        if not sisa:
            continue
        kelas = _nilai_kelas(cocok)
        lama = bersih_teks(item.rombel)
        if not lama or len(lama) <= 2:
            catatan.append(f"kelas «{kelas}» dipisah dari kolom {bidang}")
            item.rombel = kelas
        setattr(item, bidang, sisa)
    # 1b) Kebalikannya: nama yang tertelan kolom kelas.
    if bersih_teks(item.rombel):
        cocok = _POLA_AWAL_KELAS.match(bersih_teks(item.rombel))
        sisa = bersih_teks(item.rombel)[cocok.end():].strip() if cocok else ""
        if cocok and sisa and sum(1 for h in sisa if h.isalpha()) >= 3:
            for bidang_nama in ("nama_ayah", "nama_ibu"):
                if not bersih_teks(getattr(item, bidang_nama, "")):
                    catatan.append(f"«{sisa[:28]}» dikembalikan ke kolom {bidang_nama}")
                    setattr(item, bidang_nama, sisa)
                    break
            item.rombel = _nilai_kelas(cocok)
    # 2) Nama sekolah yang menempel di belakang teks sebuah kolom.
    for bidang in ("nama_ibu", "nama_ayah", "nama", "tempat_lahir", "kelamin", "rombel",
                   "sekolah"):
        nilai = bersih_teks(getattr(item, bidang, ""))
        if not nilai:
            continue
        mulai = _awal_sekolah(nilai)
        if mulai < 0:
            continue
        kepala, ekor = nilai[:mulai].strip(), nilai[mulai:].strip()
        if bidang == "sekolah":
            catatan.append(f"nama «{kepala[:32]}» dipisah dari kolom sekolah")
            item.sekolah = ekor
            _kembalikan_nama(item, kepala)
            continue
        if bersih_teks(item.sekolah):
            continue
        catatan.append(f"sekolah «{ekor[:32]}» dipisah dari kolom {bidang}")
        item.sekolah = ekor
        setattr(item, bidang, kepala)
    return catatan


#: Pembaca PDF yang dipakai lebih dulu — bawaan SM, tanpa pustaka tambahan.
MESIN_PDF_BAWAAN = "bawaan"
#: Pembaca cadangan bila pustaka pypdf kebetulan terpasang.
MESIN_PDF_PYPF = "pypdf"


def _halaman_pdf_pypdf(isi: bytes, catatan: list[str]) -> list[list[GarisPdf]]:
    """Cadangan: baca PDF memakai pustaka ``pypdf`` bila memang terpasang."""
    import pypdf  # noqa: PLC0415

    pembaca = pypdf.PdfReader(io.BytesIO(isi))
    halaman: list[list[GarisPdf]] = []
    jumlah_potongan = 0
    for nomor_halaman, halaman_pdf_satu in enumerate(pembaca.pages, start=1):
        potongan: list[tuple[float, float, str]] = []

        def visitor(teks, cm, tm, font_dict, ukuran, tampung=potongan):  # noqa: ANN001
            # Jarak lebar antar sel (≥2 spasi) justru penanda batas kolom — jangan dipadatkan.
            bersih = str(teks or "").strip()
            if bersih:
                tampung.append((float(tm[4]), float(tm[5]), bersih))

        try:
            halaman_pdf_satu.extract_text(visitor_text=visitor)
        except Exception:  # noqa: BLE001 - sebagian PDF aneh; jatuh ke mode teks biasa
            potongan = []
        if not potongan:
            try:
                try:
                    teks_halaman = halaman_pdf_satu.extract_text(extraction_mode="layout")
                except (TypeError, ValueError, NotImplementedError):
                    teks_halaman = halaman_pdf_satu.extract_text()
            except Exception as exc:  # noqa: BLE001
                raise TangcerError(
                    f"Teks PDF halaman {nomor_halaman} tidak bisa dibaca: {exc}") from exc
            for nomor_baris, baris in enumerate((teks_halaman or "").splitlines(), start=1):
                if baris.strip():
                    potongan.append((0.0, -float(nomor_baris), baris.strip()))
        jumlah_potongan += len(potongan)
        halaman.append(_kelompok_baris(potongan, nomor_halaman))
    catatan.append(f"pembaca pypdf: {len(pembaca.pages)} halaman · "
                   f"{jumlah_potongan} potongan teks")
    return halaman


def halaman_pdf(isi: bytes, *, catatan: list[str] | None = None,
                mesin: str = "otomatis") -> list[list[GarisPdf]]:
    """Teks PDF per halaman, dikelompokkan menjadi baris **beserta posisi X tiap potongan**.

    Posisi X dipakai supaya kolom yang berdekatan (mis. nomor urut yang mepet kolom NISN)
    tidak salah dipotong — hal yang sering terjadi bila hanya mengandalkan jarak spasi.

    Berkas PDF dibaca dengan **pembaca bawaan SM** (``app.pdf_baca``) lebih dulu, sehingga
    menu TANGCER tetap bisa membaca SK definitif walau pustaka tambahan (``pypdf``) belum
    terpasang di komputer sekolah. Pustaka ``pypdf`` — bila kebetulan ada — hanya dipakai
    sebagai **cadangan** ketika pembaca bawaan tidak menemukan teks, dan pilihan mesinnya
    selalu disebutkan di ``catatan`` (tidak menebak, tidak menyembunyikan).
    """
    kumpul: list[str] = []
    halaman_bawaan: list[list[GarisPdf]] = []
    pesan_bawaan = ""

    if mesin in ("otomatis", MESIN_PDF_BAWAAN):
        try:
            hasil_bawaan = pdf_baca.baca_pdf(isi)
        except pdf_baca.PdfBacaError as galat:
            pesan_bawaan = str(galat)
            kumpul.append(f"pembaca PDF bawaan SM: {galat}")
        else:
            for nomor, potongan in enumerate(hasil_bawaan.halaman, start=1):
                halaman_bawaan.append(_kelompok_baris(potongan, nomor))
            if hasil_bawaan.ada_teks:
                kumpul.extend(hasil_bawaan.catatan)
                kumpul.append("pembaca: bawaan SM (tanpa pustaka tambahan) — PDF tetap "
                              "terbaca walau «pypdf» belum terpasang")
                if catatan is not None:
                    catatan.extend(kumpul)
                return halaman_bawaan
            pesan_bawaan = hasil_bawaan.catatan[-1] if hasil_bawaan.catatan else pesan_bawaan
            kumpul.extend(hasil_bawaan.catatan)

    if mesin in ("otomatis", MESIN_PDF_PYPF):
        if pdf_baca.ada_pembaca_pypdf():
            try:
                halaman_pypf = _halaman_pdf_pypdf(isi, kumpul)
            except Exception as galat:  # noqa: BLE001 - cadangan, jangan menggagalkan semuanya
                kumpul.append(f"pembaca pypdf gagal: {galat}")
            else:
                ada_teks = any(garis.potongan for satu_halaman in halaman_pypf
                               for garis in satu_halaman)
                if ada_teks:
                    kumpul.append("pembaca: pypdf (cadangan) — pembaca bawaan tidak "
                                  "menemukan teks pada berkas ini")
                    if catatan is not None:
                        catatan.extend(kumpul)
                    return halaman_pypf
        elif mesin == MESIN_PDF_PYPF:
            raise TangcerError(
                "Pustaka pembaca PDF (pypdf) belum terpasang. Pembaca bawaan SM tidak "
                "diminta (mesin='pypdf') — gunakan mesin bawaan yang tidak butuh pustaka.")

    if mesin == MESIN_PDF_BAWAAN and halaman_bawaan:
        if catatan is not None:
            catatan.extend(kumpul)
        return halaman_bawaan

    if catatan is not None:
        catatan.extend(kumpul)
    raise TangcerError(
        "Teks PDF ini tidak bisa dibaca: "
        + (pesan_bawaan or "tidak ada teks yang bisa diambil dari halamannya")
        + " Bila berkasnya hasil pindai (scan/gambar), isinya perlu di-OCR lebih dulu. "
          "Berkasnya juga bisa diperiksa lewat «Bedah berkas» di halaman TANGCER supaya "
          "apa yang terbaca (atau tidak terbaca) bisa dilihat apa adanya.")


def _kelompok_baris(potongan: Sequence[Sequence[Any]], nomor_halaman: int) -> list[GarisPdf]:
    """Kelompokkan potongan teks menjadi baris berdasarkan posisi Y (toleransi 3 pt).

    Potongan yang bersambung erat (satu sel dipecah beberapa show-string oleh Word/
    OpenOffice/PdfLaTeX) digabung kembali lewat :func:`pdf_baca.rapatkan_potongan`
    supaya satu sel tidak terhitung sebagai beberapa kolom.
    """
    # Hanya diurutkan berdasarkan baris (y). Urutan di dalam satu baris dibiarkan seperti
    # urutan penulisan PDF — itu yang membuat pemisahan sel tidak tertukar pada nama panjang.
    terurut = sorted(potongan, key=lambda item: -float(item[1]))
    garis: list[GarisPdf] = []
    for butir in terurut:
        y = float(butir[1])
        if garis and abs(garis[-1].y - y) <= 3.0:
            garis[-1].potongan_asli.append(butir)
        else:
            satu = GarisPdf(nomor=0, y=y, potongan=[])
            satu.potongan_asli.append(butir)
            garis.append(satu)
    for nomor, satu in enumerate(garis, start=1):
        satu.nomor = nomor
        rapat = pdf_baca.rapatkan_potongan_lebar(satu.potongan_asli)
        satu.potongan = [(x, teks) for x, teks, _ in rapat]
        satu.lebar_potongan = [lebar for _, _, lebar in rapat]
    return garis


def teks_pdf(isi: bytes, *, catatan: list[str] | None = None) -> list[str]:
    """Teks per baris dari seluruh halaman PDF (untuk pratinjau/diagnosa)."""
    return [garis.teks() for halaman in halaman_pdf(isi, catatan=catatan) for garis in halaman
            if garis.teks()]


#: Jarak (pt) maksimum antar potongan judul yang masih dianggap satu kolom.
JARAK_KOLOM_JUDUL = 4.0
#: Toleransi (pt) potongan yang dianggap sejajar kiri dengan judul kolomnya.
TOLERANSI_SEJAJAR = 3.0
#: Lebar (pt) dan jumlah kata maksimum sebuah potongan agar masih dianggap judul kolom —
#: kalimat pembuka dokumen («TENTANG : DAFTAR DEFINITIF PENERIMA …») jelas bukan judul
#: kolom, dan kalau ikut dihitung ia menelan semua kolom judul di sebelahnya.
LEBAR_JUDUL_MAKS = 150.0
KATA_JUDUL_MAKS = 4


def _tampak_data(garis: GarisPdf) -> bool:
    """Apakah baris ini tampak baris DATA (bukan judul) — dipakai saat menggabung judul."""
    if len(garis.potongan) >= 8:
        return True
    return any(re.fullmatch(r"\d{6,}", teks.strip()) for _, teks in garis.potongan)


def _tampak_judul_kolom(teks: str, lebar: float) -> bool:
    """Potongan ini masih masuk akal sebagai judul kolom (bukan kalimat panjang)."""
    bersih = teks.strip()
    if not bersih:
        return False
    return lebar <= LEBAR_JUDUL_MAKS and len(bersih.split()) <= KATA_JUDUL_MAKS


def _jarak_baris(datar: Sequence[GarisPdf]) -> float:
    """Jarak baris tipikal (median) pada satu halaman, untuk batas penggabungan judul."""
    tinggi = [abs(datar[i].y - datar[i + 1].y) for i in range(min(len(datar) - 1, 40))]
    tinggi = sorted(t for t in tinggi if 1.0 < t < 200.0)
    return tinggi[len(tinggi) // 2] if tinggi else 14.0


def _judul_lengkap(datar: Sequence[GarisPdf], indeks: int) -> list[tuple[float, float, str]]:
    """Gabungkan judul tabel yang berlapis menjadi daftar kolom ``(x_awal, x_tengah, judul)``.

    Judul tabel dinas sering ditulis dua–tiga baris («NOMOR KARTU» di atas, «KELUARGA» di
    bawahnya) dan selnya sempit sehingga judulnya terpotong («TEMPA»/«T»/«LA»/«HIR»). Kolom
    karena itu ditentukan dari **posisi X** lalu judulnya digabungkan — bukan dari urutan
    teks, yang bisa menukar kolom.
    """
    potongan: list[tuple[float, float, str, float]] = []

    def tambah(garis: GarisPdf) -> None:
        lebar = list(garis.lebar_potongan)
        for nomor, (x, teks) in enumerate(garis.potongan):
            luas = lebar[nomor] if nomor < len(lebar) else 0.5 * max(1, len(teks))
            if _tampak_judul_kolom(teks, luas):
                potongan.append((x, x + luas, teks, garis.y))

    tambah(datar[indeks])
    # Rantai ke atas & ke bawah hanya berlanjut selama jarak antara dua baris berturut-turut
    # jauh lebih rapat daripada jarak baris data — begitu ketemu baris berjarak normal
    # (mis. kalimat pembuka dokumen), penggabungan berhenti.
    batas = _jarak_baris(datar) * 0.6
    for arah in (-1, 1):
        i = indeks + arah
        while 0 <= i < len(datar):
            tetangga = datar[i - arah]
            if abs(datar[i].y - tetangga.y) > batas or _tampak_data(datar[i]):
                break
            tambah(datar[i])
            i += arah
    potongan.sort(key=lambda butir: butir[0])
    kolom: list[dict[str, object]] = []
    for x, akhir, teks, y in potongan:
        if kolom and x <= float(kolom[-1]["akhir"]) + JARAK_KOLOM_JUDUL:
            isi = kolom[-1]["teks"]
            assert isinstance(isi, list)
            isi.append((y, x, teks))
            kolom[-1]["akhir"] = max(float(kolom[-1]["akhir"]), akhir)
        else:
            kolom.append({"awal": x, "akhir": akhir, "teks": [(y, x, teks)]})
    keluaran: list[tuple[float, float, str]] = []
    for satu in kolom:
        isi = satu["teks"]
        assert isinstance(isi, list)
        urut = sorted(isi, key=lambda butir: (-butir[0], butir[1]))
        label = " ".join(str(teks) for _, _, teks in urut).strip()
        awal = float(satu["awal"])
        akhir = max(float(satu["akhir"]), awal + 1.0)
        keluaran.append((awal, (awal + akhir) / 2.0, label))
    return keluaran


#: Bidang yang isinya angka (nomor induk, nomor rekening, tanggal).
BIDANG_ANGKA = frozenset({"no", "nisn", "nik", "nik_ayah", "nik_ibu", "kk", "rekening",
                          "tanggal_lahir"})
#: Bidang yang isinya kata (nama orang, sekolah, alamat, tempat lahir).
BIDANG_HURUF = frozenset({"nama", "alamat", "kelurahan", "kecamatan", "sekolah", "nama_ayah",
                          "nama_ibu", "nama_orangtua", "tempat_lahir"})


def _tipe_potongan(teks: str) -> str:
    """«angka», «huruf», atau «campur» — dipakai supaya nama tidak masuk kolom NISN dsb."""
    bersih = teks.strip()
    angka = sum(1 for huruf in bersih if huruf.isdigit())
    lain = sum(1 for huruf in bersih if huruf.isalpha())
    if lain >= 2 and lain >= angka:
        return "huruf"
    if angka >= 2 and lain == 0:
        return "angka"
    return "campur"


def _pilih_kolom(x: float, x_akhir: float, kolom: Sequence[tuple[float, float, str]]) -> str:
    """Bidang kolom untuk satu potongan teks.

    Dua aturan, berurutan: (1) potongan yang **sejajar kiri** dengan judul kolomnya (tabel
    rata kiri) langsung masuk kolom itu; (2) selebihnya memakai **titik tengah** potongan —
    perlu, karena sel tabel dinas umumnya di tengah, dan nilai yang lebih panjang daripada
    judulnya bisa mulai di sebelah kiri judul (mis. NISN yang mulai 14 pt sebelum judulnya).
    """
    for awal, _, bidang in kolom:
        if abs(x - awal) <= TOLERANSI_SEJAJAR:
            return bidang
    tengah = (x + x_akhir) / 2.0
    return min(kolom, key=lambda satu: abs(satu[1] - tengah))[2]


def _pilih_kolom_isi(x: float, x_akhir: float, kolom: Sequence[tuple[float, float, str]],
                     teks: str) -> str:
    """Seperti :func:`_pilih_kolom`, tetapi jenis isi potongan ikut dipertimbangkan.

    Nama siswa pada SK dinas bisa mulai di kiri judulnya (sel lebih lebar daripada judulnya),
    sehingga titik tengahnya justru lebih dekat ke kolom nomor. Potongan yang berisi kata
    karena itu hanya dicocokkan ke kolom teks, dan potongan angka hanya ke kolom angka.
    """
    bersih = teks.strip()
    bidang_tersedia = {satu[2] for satu in kolom}
    # Isi yang jelas milik sel lain: potongan nama sekolah berdiri sendiri («SMP» di depan
    # «NEGERI 8 TANGERANG») sering terukur lebih dekat ke kolom nama ibu karena teksnya
    # melimpah ke kiri. Dikenali dari isinya (ronde 61), bukan dari posisinya.
    if "sekolah" in bidang_tersedia and (_tampak_sekolah(bersih)
                                         or _POLA_JENJANG_SENDIRI.match(bersih)):
        return "sekolah"
    if "rombel" in bidang_tersedia and _POLA_AWAL_KELAS.match(bersih):
        return "rombel"
    awal = _pilih_kolom(x, x_akhir, kolom)
    tipe = _tipe_potongan(teks)
    kandidat = [satu for satu in kolom
                if (tipe == "huruf" and satu[2] in BIDANG_HURUF)
                or (tipe == "angka" and satu[2] in BIDANG_ANGKA)]
    if not kandidat:
        return awal
    pilihan = awal if any(satu[2] == awal for satu in kandidat) else None
    if pilihan is None:
        tengah = (x + x_akhir) / 2.0
        pilihan = min(kandidat, key=lambda satu: abs(satu[1] - tengah))[2]
    return pilihan


#: Jarak (pt) antar potongan yang masih dianggap satu sel. Potongan yang lebih jauh dari ini
#: pada kolom sempit (KELAS, JENIS KELAMIN, NO) berasal dari kolom lain yang judulnya tidak
#: ada di PDF — mis. ALAMAT pada SK dinas — dan tidak diikutkan supaya kolomnya tidak kotor.
JARAK_DALAM_SEL = 6.0
#: Kolom sempit yang hanya boleh berisi satu sel pendek pada satu baris.
BIDANG_SEMPIT = frozenset({"no", "rombel", "kelamin"})


def _lanjutan_nama(garis: GarisPdf, kolom_x: Sequence[tuple[float, float, str]],
                   sebelumnya: BarisPenerima | None) -> str:
    """Nama siswa yang **terbawa ke baris berikutnya** karena selnya sempit.

    Word/Excel membungkus nama panjang menjadi dua baris tabel; baris keduanya tidak punya
    nomor urut dan tidak punya NISN, sehingga kalau dibiarkan ia jadi baris kosong dan nama
    siswa hilang. Kalau potongannya jatuh di kolom NAMA (dan baris sebelumnya memang belum
    punya nama), teks itu ditempelkan ke nama sebelumnya.
    """
    if sebelumnya is None or (sebelumnya.nama or "").strip():
        return ""
    if not garis.potongan or len(garis.potongan) > 3:
        return ""
    teks = " ".join(dua.strip() for _, dua in garis.potongan if dua.strip()).strip()
    if sum(1 for huruf in teks if huruf.isalpha()) < 3:
        return ""
    if any(re.fullmatch(r"\d{4,}", dua.strip()) for _, dua in garis.potongan):
        return ""
    letak = list(garis.lebar_potongan)
    bidang = {_pilih_kolom(x, x + (letak[nomor] if nomor < len(letak) else 0.5 * len(dua)),
                           kolom_x)
              for nomor, (x, dua) in enumerate(garis.potongan)}
    return teks if "nama" in bidang else ""


def _gabung_potongan(butir: Sequence[tuple[float, str, float]]) -> str:
    """Gabungkan potongan satu kolom: huruf bersambung tidak diberi spasi.

    Jarak antar-potongan di dalam satu sel hampir selalu nol — yang memisahkan kata adalah
    spasi yang memang tertulis di potongannya. Spasi hanya ditambahkan kalau jaraknya memang
    selebar lebih dari setengah huruf (kata yang terpisah tanpa spasi di PDF).
    """
    hasil = ""
    akhir: float | None = None
    for x, teks, luas in butir:
        if hasil and akhir is not None:
            jarak = x - akhir
            lebar_huruf = max(1.0, (luas or len(teks)) / max(1, len(teks.strip()) or 1))
            # Jarak negatif yang dalam berarti kedua potongan sebenarnya dari sel berbeda yang
            # tertampung di kolom yang sama — diberi spasi supaya tidak menempel.
            if ((jarak > max(0.5, 0.35 * lebar_huruf) or jarak < -1.0)
                    and not hasil.endswith(" ") and not teks.startswith(" ")):
                hasil += " "
        hasil += teks
        akhir = max(akhir or 0.0, x + (luas or 0.0))
    return re.sub(r"\s+", " ", hasil).strip()


def _baris_dari_kolom(garis: GarisPdf, kolom_x: Sequence[tuple[float, float, str]]
                      ) -> tuple[BarisPenerima, list[str]]:
    """Susun calon penerima dari potongan teks satu baris, dibagi menurut kolom.

    Kembalikan juga catatan potongan yang dilewati (mis. alamat tak berkolom judul).
    """
    bagian: dict[str, list[tuple[float, str, float]]] = {}
    letak: dict[str, float] = {}
    catatan: list[str] = []
    lebar = list(garis.lebar_potongan)
    for nomor, (x, teks) in enumerate(garis.potongan):
        bersih = teks.strip()
        if not bersih or bersih == "-":
            continue
        luas = lebar[nomor] if nomor < len(lebar) else 0.5 * len(bersih)
        pilih = _pilih_kolom_isi(x, x + luas, kolom_x, bersih)
        if pilih in BIDANG_SEMPIT and pilih in letak and (x - letak[pilih]) > JARAK_DALAM_SEL:
            catatan.append(f"«{bersih}» di luar kolom {pilih} (baris {garis.nomor})")
            continue
        bagian.setdefault(pilih, []).append((x, teks, luas))
        letak[pilih] = x + luas

    item = BarisPenerima()
    for bidang, potongan in bagian.items():
        if bidang.startswith("__"):
            continue
        teks = _gabung_potongan(potongan)
        if bidang in {"nisn", "nik"}:
            setattr(item, bidang, bersih_nomor(teks))
        elif bidang == "nominal":
            item.nominal = bersih_nominal(teks)
        elif bidang == "no":
            item.no = bersih_teks(teks)
        else:
            setattr(item, bidang, bersih_teks(teks))
    for satu in _pisah_bocor(item):
        if satu not in catatan:
            catatan.append(satu)
    if bersih_teks(item.rombel):
        cocok_kelas = _POLA_AWAL_KELAS.match(bersih_teks(item.rombel))
        if cocok_kelas:
            nilai = _nilai_kelas(cocok_kelas)
            sisa = bersih_teks(item.rombel)[cocok_kelas.end():].strip()
            item.rombel = f"{nilai} {sisa}".strip() if sisa else nilai
    return item, catatan


#: «… SEMESTER 1 TAHUN ANGGARAN 2026 TAHAP 2» pada kepala SK dinas.
_POLA_KEPALA = (
    ("tahap", re.compile(r"\bTAHAP\s+([0-9]{1,2}|[IVX]{1,4})\b")),
    ("semester", re.compile(r"\bSEMESTER\s+([0-9]{1,2}|GANJIL|GENAP|[IVX]{1,4})\b")),
    ("tahun", re.compile(r"\bTAHUN\s+ANGGARAN\s+([0-9]{4})\b")),
)


def kepala_berkas(datar: Sequence[GarisPdf], batas: int = 40) -> dict[str, str]:
    """TAHAP/SEMESTER/TAHUN ANGGARAN yang tertulis di kepala berkas (bila ada).

    Judul SK dinas menyebutkannya («… SEMESTER 1 TAHUN ANGGARAN 2026 TAHAP 2»), dan judul itu
    yang dipakai mengisi isian tahap di halaman TANGCER — supaya baris tahap 1 dan tahap 2
    tidak tercampur tanpa sengaja.
    """
    teks = " ".join(garis.teks() for garis in datar[:batas] if garis.teks())
    teks = re.sub(r"\s+", " ", teks).upper()
    temuan: dict[str, str] = {}
    for nama, pola in _POLA_KEPALA:
        cocok = pola.search(teks)
        if cocok:
            temuan[nama] = cocok.group(1).strip()
    return temuan


def baca_baris_pdf(halaman: Sequence[str] | Sequence[list[GarisPdf]],
                   *, sumber: str = "PDF") -> HasilBaca:
    """Uraikan teks PDF menjadi calon penerima.

    Dua tata letak yang lazim dipakai berkas dinas ditangani:

    * **tabel** — ada baris judul kolom (NO · NISN · NAMA · SEKOLAH · …); kolom
      dicocokkan lewat posisi X judulnya, sehingga kolom yang mepet tetap benar;
    * **judul bagian** — nama sekolah berdiri sendiri pada satu baris, lalu baris
      siswanya di bawahnya (kolom sekolahnya tidak ada).
    """
    halaman_garis: list[list[GarisPdf]] = []
    for isi_halaman in halaman:
        if isinstance(isi_halaman, str):
            halaman_garis.append([
                GarisPdf(nomor=nomor, y=-float(nomor), potongan=[(0.0, baris.strip())])
                for nomor, baris in enumerate(isi_halaman.splitlines(), start=1) if baris.strip()
            ])
        else:
            halaman_garis.append(list(isi_halaman))

    datar: list[GarisPdf] = [garis for satu_halaman in halaman_garis for garis in satu_halaman]
    hasil = HasilBaca(format=sumber)
    kepala = kepala_berkas(datar)
    if kepala:
        hasil.tahap = kepala.get("tahap", "")
        hasil.semester = kepala.get("semester", "")
        hasil.tahun = kepala.get("tahun", "")
        rincian = " · ".join(f"{nama.upper()} {nilai}"
                             for nama, nilai in (("semester", hasil.semester),
                                                 ("tahun anggaran", hasil.tahun),
                                                 ("tahap", hasil.tahap)) if nilai)
        hasil.catatan.append(f"kepala berkas menyebut: {rincian}")
    if not datar:
        raise TangcerError(
            "Tidak ada baris yang terbaca dari PDF ini. Bila PDF-nya hasil pindai (scan), "
            "berkas itu perlu di-OCR lebih dulu agar isinya bisa dibaca."
        )

    # 1) Cari baris judul kolom.
    indeks_judul = -1
    for indeks, garis in enumerate(datar[:60]):
        if skor_header(garis.sel()) >= 6:
            indeks_judul = indeks
            break

    if indeks_judul >= 0:
        garis_judul = datar[indeks_judul]
        blok = _judul_lengkap(datar, indeks_judul)
        hasil.kolom = peta_kolom([label for _, _, label in blok])
        hasil.header_ke = garis_judul.nomor
        kolom_x = [(awal, pusat, hasil.kolom.get(nomor, f"__{nomor}"))
                   for nomor, (awal, pusat, _) in enumerate(blok)]
        berlapis = len(blok) > len(garis_judul.potongan)
        # Bila judul kolom hanya satu potongan (dipisah spasi), posisinya tidak diketahui:
        # jatuh ke pencocokan berdasarkan urutan sel.
        pakai_posisi = len(blok) >= 3
        rincian = f"{len(hasil.kolom)} kolom dikenali dari {len(blok)} kolom judul"
        if berlapis:
            rincian += " (judul berlapis digabung)"
        hasil.catatan.append(
            "tata letak PDF: tabel" + (f" ({rincian}, dicocokkan lewat posisi)"
                                       if pakai_posisi else " (dicocokkan lewat urutan sel)"))
        for garis in datar[indeks_judul + 1:]:
            teks = garis.teks()
            if not teks:
                continue
            if awal_rekap(garis.sel()):
                hasil.catatan.append(f"baris {garis.nomor} dilewati (keterangan/rekap: {teks[:60]})")
                continue
            if skor_header(garis.sel()) >= 6:
                continue  # judul berulang di halaman berikutnya
            if pakai_posisi:
                item, dilewati = _baris_dari_kolom(garis, kolom_x)
                for satu in dilewati:
                    if satu not in hasil.catatan and len(hasil.catatan) < 40:
                        hasil.catatan.append(satu)
            else:
                item = isi_baris(garis.sel(), hasil.kolom)
            if not item.lengkap:
                lanjutan = _lanjutan_nama(garis, kolom_x, hasil.baris[-1] if hasil.baris else None)
                if lanjutan:
                    hasil.baris[-1].nama = f"{hasil.baris[-1].nama} {lanjutan}".strip()
                    hasil.catatan.append(
                        f"baris {garis.nomor} digabung ke nama sebelumnya: «{lanjutan[:40]}»")
                continue
            item.baris_ke = garis.nomor
            hasil.baris.append(item)
        if hasil.baris:
            return hasil

    # 2) Tata letak «judul bagian»: nama sekolah berdiri sendiri.
    hasil.kolom = {}
    hasil.catatan.append("tata letak PDF: judul bagian (nama sekolah jadi judul, siswa di bawahnya)")
    sekolah_aktif = ""
    for garis in datar:
        teks = garis.teks()
        if not teks:
            continue
        if awal_rekap(garis.sel()):
            hasil.catatan.append(f"baris {garis.nomor} dilewati (keterangan/rekap: {teks[:60]})")
            continue
        sel = garis.sel()
        if len(sel) < 2:
            if _tampak_sekolah(teks):
                sekolah_aktif = teks
                hasil.sekolah_tanpa_kolom.append(teks)
            continue
        item = _baris_pdf_tanpa_judul(sel)
        if item is None:
            if _tampak_sekolah(teks):
                sekolah_aktif = teks
                hasil.sekolah_tanpa_kolom.append(teks)
            continue
        if not item.sekolah:
            item.sekolah = sekolah_aktif
        item.baris_ke = garis.nomor
        hasil.baris.append(item)

    if not hasil.baris:
        contoh = " | ".join(garis.teks()[:70] for garis in datar[:5] if garis.teks())
        raise TangcerError(
            "Tidak ada baris penerima yang terbaca dari PDF ini. Baris yang terlihat: "
            + (contoh or "—")
        )
    return hasil


def _bidang_urut(garis_judul: GarisPdf) -> list[str]:
    """Bidang internal untuk tiap potongan judul (sejajar posisinya)."""
    peta = peta_kolom([teks for _, teks in garis_judul.potongan])
    return [peta.get(nomor, f"__{nomor}") for nomor in range(len(garis_judul.potongan))]


def _baris_pdf_tanpa_judul(sel: Sequence[str]) -> BarisPenerima | None:
    """Baris penerima pada PDF tanpa baris judul: cari NISN (10 angka) & nama."""
    item = BarisPenerima()
    sisa: list[str] = []
    for bagian in sel:
        angka_saja = re.fullmatch(r"[\d.\s]+", bagian or "")
        nomor = bersih_nomor(bagian)
        if angka_saja and len(nomor) == 10 and not item.nisn:
            item.nisn = nomor
            continue
        if angka_saja and len(nomor) == 16 and not item.nik:
            item.nik = nomor
            continue
        if angka_saja and re.fullmatch(r"\d{1,4}", nomor) and not item.no:
            item.no = nomor
            continue
        sisa.append(bagian)
    if not sisa:
        return None
    nama = max((bagian for bagian in sisa if re.search(r"[A-Za-z]{3}", bagian)),
               key=len, default="")
    if not nama:
        return None
    item.nama = nama
    for bagian in sisa:
        if bagian != nama and _tampak_sekolah(bagian):
            item.sekolah = bagian
    return item


# =========================================================================== #
# Pembacaan berkas (termasuk .pdf)
# =========================================================================== #
FORMAT_PDF = (".pdf",)


def baca_berkas(path: Path, ext: str) -> HasilBaca:
    """Baca berkas daftar penerima (spreadsheet apa pun yang didukung, atau PDF)."""
    ext = (ext or path.suffix).lower()
    if ext in FORMAT_PDF:
        return baca_baris_pdf(halaman_pdf(path.read_bytes()), sumber="PDF")
    from .readers import read_spreadsheet  # noqa: PLC0415

    sheets = read_spreadsheet(path, ext)
    dicoba: list[str] = []
    for sheet in sheets:
        try:
            hasil = baca_baris_tabel(sheet.rows, sumber=sheet.name)
        except TangcerError as galat:
            dicoba.append(f"{sheet.name}: {galat}")
            continue
        hasil.catatan.insert(0, f"worksheet «{sheet.name}» — {len(sheet.rows)} baris terbaca")
        return hasil
    raise TangcerError(" / ".join(dicoba) or "Berkas tidak memuat daftar penerima.")


def baca_isi(nama: str, isi: bytes) -> HasilBaca:
    """Baca berkas dari isi di memori (dipakai pratinjau sebelum disimpan)."""
    ext = Path(nama).suffix.lower()
    if ext in FORMAT_PDF:
        catatan: list[str] = []
        halaman = halaman_pdf(isi, catatan=catatan)
        hasil = baca_baris_pdf(halaman, sumber="PDF")
        hasil.catatan = catatan + hasil.catatan
        return hasil
    import tempfile  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as berkas:
        berkas.write(isi)
        sementara = Path(berkas.name)
    try:
        return baca_berkas(sementara, ext)
    finally:
        sementara.unlink(missing_ok=True)


# =========================================================================== #
# Penyaringan per sekolah
# =========================================================================== #
@dataclass
class HasilSaring:
    diterima: list[BarisPenerima] = dataclass_field(default_factory=list)
    ditolak: list[BarisPenerima] = dataclass_field(default_factory=list)
    sekolah_lain: Counter = dataclass_field(default_factory=Counter)
    tanpa_sekolah: list[BarisPenerima] = dataclass_field(default_factory=list)
    #: Baris yang kolom sekolahnya **tidak berbentuk nama sekolah** (mis. masih menempel pada
    #: nama orang) — dipisahkan supaya laporannya jujur, bukan disebut «sekolah lain» (ronde 61).
    sekolah_aneh: list[BarisPenerima] = dataclass_field(default_factory=list)
    #: Baris yang cocok **setelah kata wilayah dibuang** — diambil, tapi perlu diperiksa manusia.
    diragukan: list[BarisPenerima] = dataclass_field(default_factory=list)
    catatan: list[str] = dataclass_field(default_factory=list)

    @property
    def jumlah_diterima(self) -> int:
        return len(self.diterima)


def saring_sekolah(hasil: HasilBaca, nama_kita: str, npsn_kita: str = "",
                   daerah_kita: str = "", *, tanpa_kolom_sekolah: bool = False) -> HasilSaring:
    """Pisahkan baris milik sekolah kita dari baris sekolah lain.

    ``tanpa_kolom_sekolah`` dipakai untuk berkas yang memang **tidak punya kolom
    sekolah** (mis. SK yang sudah terpisah per sekolah): seluruh baris dianggap
    milik sekolah kita — dan itu dikatakan terus terang pada catatan.
    """
    hasil_saring = HasilSaring()
    ada_kolom = "sekolah" in hasil.kolom.values()
    if not ada_kolom and not hasil.sekolah_tanpa_kolom:
        if tanpa_kolom_sekolah:
            hasil_saring.catatan.append(
                "Berkas ini tidak punya kolom sekolah — seluruh barisnya dianggap milik "
                f"«{nama_kita}» sesuai pilihan yang dicentang.")
            hasil_saring.diterima = list(hasil.baris)
        else:
            hasil_saring.catatan.append(
                "Kolom sekolah tidak ada pada berkas ini. Bila berkas memang sudah khusus "
                f"untuk «{nama_kita}», centang «Berkas sudah khusus sekolah kita» lalu ulangi.")
        return hasil_saring

    for item in hasil.baris:
        if not item.sekolah:
            hasil_saring.tanpa_sekolah.append(item)
            continue
        if not _tampak_nama_sekolah(item.sekolah):
            hasil_saring.sekolah_aneh.append(item)
            item.alasan = f"kolom sekolah tidak berbentuk nama sekolah: «{item.sekolah[:40]}»"
            continue
        cocok, alasan = cocok_sekolah(item.sekolah, nama_kita, npsn_kita, daerah_kita)
        item.cocok = cocok
        item.alasan = alasan
        if cocok:
            hasil_saring.diterima.append(item)
            if "kata wilayah dibuang" in alasan:
                hasil_saring.diragukan.append(item)
        else:
            hasil_saring.ditolak.append(item)
            hasil_saring.sekolah_lain[item.sekolah] += 1

    if hasil_saring.tanpa_sekolah:
        hasil_saring.catatan.append(
            f"{len(hasil_saring.tanpa_sekolah)} baris tidak menyebut sekolahnya"
            + (" dan ikut diambil karena berkasnya khusus satu sekolah."
               if tanpa_kolom_sekolah else " — tidak diambil (centang «Berkas sudah khusus sekolah kita» bila memang cocok)."))
        if tanpa_kolom_sekolah:
            hasil_saring.diterima.extend(hasil_saring.tanpa_sekolah)
    if hasil_saring.sekolah_aneh:
        contoh = "; ".join(sorted({item.sekolah for item in hasil_saring.sekolah_aneh})[:3])
        hasil_saring.catatan.append(
            f"{len(hasil_saring.sekolah_aneh)} baris kolom sekolahnya tidak berbentuk nama "
            f"sekolah ({contoh}) — tidak diambil, mohon diperiksa pada daftar di bawah.")
    if hasil_saring.sekolah_lain:
        hasil_saring.catatan.append(
            f"{sum(hasil_saring.sekolah_lain.values())} baris milik {len(hasil_saring.sekolah_lain)} "
            "sekolah lain — tidak disimpan.")
        if not hasil_saring.diterima:
            terbanyak = ", ".join(f"{nama} ({jumlah} baris)" for nama, jumlah
                                  in hasil_saring.sekolah_lain.most_common(6))
            hasil_saring.catatan.append(
                f"Tidak ada satu baris pun untuk «{nama_kita}» di berkas ini. Sekolah yang ada "
                f"di dalamnya: {terbanyak}"
                + (" …" if len(hasil_saring.sekolah_lain) > 6 else "")
                + ". SK TANGCER dicetak bertahap — periksa berkas tahap lain bila sekolah kita "
                  "belum ada di sini.")
    if hasil_saring.diragukan:
        nama_contoh = "; ".join(sorted({item.sekolah for item in hasil_saring.diragukan})[:3])
        hasil_saring.catatan.append(
            f"{len(hasil_saring.diragukan)} baris diambil karena namanya sama setelah kata wilayah "
            f"dibuang ({nama_contoh}) — mohon diperiksa pada daftar hasil.")
    return hasil_saring


# =========================================================================== #
# Penyimpanan (basis data)
# =========================================================================== #
def sidik_baris(tahun: str, semester: str, tahap: str, item: BarisPenerima) -> str:
    bahan = "|".join([
        norm_teks(tahun), norm_teks(semester), norm_teks(tahap),
        item.nisn or norm_teks(item.nama), norm_teks(item.nama),
        norm_teks(item.sekolah), norm_teks(item.rombel),
    ])
    return hashlib.sha1(bahan.encode("utf-8")).hexdigest()


#: Batas jumlah nama sekolah yang disimpan dari satu berkas mentah. Dipakai halaman
#: pratinjau untuk menyebut «Sekolah lain di berkas». Dulu hanya 15 teratas sehingga berkas
#: tahap 2 yang memuat 57 sekolah tampak seolah-olah hanya berisi 15 sekolah (ronde 61).
BATAS_SEKOLAH_SIMPAN = 500


def ringkas_sekolah_lain(saring: HasilSaring) -> dict[str, int]:
    """Jumlah baris tiap sekolah lain pada berkas — **semuanya**, bukan 15 teratas.

    Dipakai halaman pratinjau: «Sekolah lain di berkas 57», dan daftarnya bisa ditelusuri
    sekolah demi sekolah. Urutannya dari yang barisnya terbanyak.
    """
    urut = sorted(saring.sekolah_lain.items(), key=lambda pasang: (-pasang[1], pasang[0]))
    return {nama: jumlah for nama, jumlah in urut[:BATAS_SEKOLAH_SIMPAN]}


def buat_impor(*, nama_berkas: str, path: Path | None, ext: str, ukuran: int,
               tahun: str, semester: str, tahap: str, hasil: HasilBaca,
               saring: HasilSaring, kolom: dict[int, str], actor: str,
               tanpa_kolom_sekolah: bool) -> int:
    """Catat kepala impor (pratinjau) — belum menyimpan penerimanya."""
    ringkas_sekolah = ringkas_sekolah_lain(saring)
    with db.transaction() as conn:
        kursor = conn.execute(
            """
            INSERT INTO tangcer_imports
                (berkas, ext, ukuran, sumber_path, tahun, semester, tahap, sekolah_kita,
                 total_baris, diterima, sekolah_lain, sekolah_ditemukan, kolom, catatan,
                 status, actor, tanpa_kolom_sekolah)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                nama_berkas, ext, ukuran, str(path) if path else "",
                tahun, semester, tahap, services.school_profile()["nama"],
                hasil.jumlah_baris, saring.jumlah_diterima,
                sum(saring.sekolah_lain.values()),
                json.dumps(ringkas_sekolah, ensure_ascii=False),
                json.dumps({str(k): v for k, v in kolom.items()}, ensure_ascii=False),
                "\n".join(catatan_impor(hasil, saring)),
                "pratinjau", actor, 1 if tanpa_kolom_sekolah else 0,
            ),
        )
        return int(kursor.lastrowid or 0)


_POLA_CATATAN_BARIS = re.compile(r"^(?P<inti>.*?)\s*\(baris (?P<nomor>\d+)\)\s*$")


def ringkas_catatan(catatan: Sequence[str], batas_contoh: int = 4) -> list[str]:
    """Gabungkan catatan yang sama pada banyak baris menjadi satu kalimat.

    Berkas SK yang panjang sempat menghasilkan belasan baris catatan kembar (««0» di luar kolom
    rombel (baris 11)» … «(baris 26)») sehingga catatan penting seperti «sekolah … dipisah dari
    kolom nama_ibu» tenggelam. Catatan yang hanya berbeda nomor barisnya diringkas jadi satu —
    jumlah barisnya tetap disebut apa adanya (ronde 61).
    """
    keluaran: list[str] = []
    kelompok: dict[str, list[int]] = {}
    urutan: list[tuple[str, str]] = []
    for pesan in catatan:
        cocok = _POLA_CATATAN_BARIS.match(str(pesan).strip())
        if not cocok:
            keluaran.append(str(pesan))
            continue
        inti = cocok.group("inti").strip()
        nomor = int(cocok.group("nomor"))
        if inti not in kelompok:
            kelompok[inti] = []
            urutan.append(("kelompok", inti))
        kelompok[inti].append(nomor)
    for jenis, kunci in urutan:
        nomor_list = sorted(set(kelompok[kunci]))
        if len(nomor_list) == 1:
            keluaran.append(f"{kunci} (baris {nomor_list[0]})")
            continue
        contoh = ", ".join(str(n) for n in nomor_list[:batas_contoh])
        keluaran.append(f"{kunci} ({len(nomor_list)} baris: {contoh}"
                        + (" …" if len(nomor_list) > batas_contoh else "") + ")")
    return keluaran


def catatan_impor(hasil: HasilBaca, saring: HasilSaring) -> list[str]:
    catatan = list(hasil.catatan) + list(saring.catatan)
    if hasil.kolom:
        urut = [f"{bidang}" for _, bidang in sorted(hasil.kolom.items())]
        catatan.insert(0, f"kolom terbaca: {', '.join(urut)}")
    return ringkas_catatan(catatan)


def get_impor(import_id: int) -> dict[str, Any] | None:
    baris = db.query_one("SELECT * FROM tangcer_imports WHERE id = ?", (import_id,))
    if baris is None:
        return None
    data = dict(baris)
    for kunci in ("sekolah_ditemukan", "kolom"):
        try:
            data[kunci] = json.loads(data.get(kunci) or "{}")
        except (TypeError, ValueError):
            data[kunci] = {}
    return data


def daftar_impor(limit: int = 25) -> list[dict[str, Any]]:
    return db.rows_to_dicts(db.query_all(
        "SELECT * FROM tangcer_imports ORDER BY id DESC LIMIT ?", (limit,)))


def simpan_banyak(import_id: int, item_list: Sequence[BarisPenerima], *, tahun: str,
                 semester: str, tahap: str) -> tuple[int, int]:
    """Simpan baris milik sekolah kita dalam satu transaksi.

    Kembalikan ``(baru, ganda)``: ``ganda`` adalah baris yang sidik jarinya sudah ada
    di basis data (mis. berkas yang sama diunggah dua kali) — baris seperti itu
    **dilewati**, bukan ditimpa dan bukan digandakan.
    """
    baru = 0
    ganda = 0
    with db.transaction() as conn:
        for item in item_list:
            sidik = sidik_baris(tahun, semester, tahap, item)
            ada = conn.execute("SELECT 1 FROM tangcer_penerima WHERE sidik = ?",
                               (sidik,)).fetchone()
            if ada:
                ganda += 1
                continue
            conn.execute(
                """
                INSERT INTO tangcer_penerima
                    (import_id, tahun, semester, tahap, nisn, nik, nama, sekolah, rombel,
                     jenis, nominal, keterangan, student_id, cocok, sidik,
                     rekening, nama_ayah, nama_ibu, nama_orangtua, kelamin,
                     nik_ayah, nik_ibu, kk, tempat_lahir, tanggal_lahir)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (import_id, tahun, semester, tahap, item.nisn, item.nik, item.nama, item.sekolah,
                 item.rombel, item.jenis, item.nominal, item.keterangan,
                 item.student_id, item.status_cocok or "belum_dicek", sidik,
                 item.rekening, item.nama_ayah, item.nama_ibu, item.nama_orangtua,
                 item.kelamin_rapi, item.nik_ayah, item.nik_ibu, item.kk,
                 item.tempat_lahir, item.tanggal_lahir),
            )
            baru += 1
    return baru, ganda


def simpan_penerima(import_id: int, item: BarisPenerima, *, tahun: str, semester: str,
                    tahap: str) -> bool:
    """Simpan satu penerima; kembalikan False bila barisnya sudah ada (tidak ganda)."""
    baru, _ = simpan_banyak(import_id, [item], tahun=tahun, semester=semester, tahap=tahap)
    return baru == 1


def tandai_impor(import_id: int, *, status: str, diterima: int | None = None,
                 catatan: str | None = None) -> None:
    potongan = ["status = ?"]
    nilai: list[Any] = [status]
    if diterima is not None:
        potongan.append("diterima = ?")
        nilai.append(diterima)
    if catatan is not None:
        potongan.append("catatan = ?")
        nilai.append(catatan)
    if status == "tersimpan":
        potongan.append("disimpan = datetime('now','localtime')")
    nilai.append(import_id)
    db.execute(f"UPDATE tangcer_imports SET {', '.join(potongan)} WHERE id = ?", nilai)


def hapus_impor(import_id: int) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM tangcer_penerima WHERE import_id = ?", (import_id,))
        conn.execute("DELETE FROM tangcer_imports WHERE id = ?", (import_id,))


# =========================================================================== #
# Pencocokan dengan data siswa SM
# =========================================================================== #
def cocokkan_dengan_siswa(import_id: int | None = None) -> dict[str, int]:
    """Cocokkan penerima dengan data siswa (NISN → NIK → nama) & simpan hasilnya."""
    where = "WHERE import_id = ?" if import_id else ""
    params: tuple[Any, ...] = (import_id,) if import_id else ()
    baris = db.query_all(f"SELECT * FROM tangcer_penerima {where}", params)
    hitung = {"nisn": 0, "nik": 0, "nama": 0, "tidak_ada": 0}
    with db.transaction() as conn:
        for item in baris:
            siswa_id, cara = _cari_siswa(dict(item))
            hitung[cara] += 1
            conn.execute(
                "UPDATE tangcer_penerima SET student_id = ?, cocok = ? WHERE id = ?",
                (siswa_id, cara, item["id"]),
            )
    return hitung


def _cari_siswa(item: dict[str, Any]) -> tuple[int | None, str]:
    if item.get("nisn"):
        baris = db.query_one("SELECT id FROM students WHERE nisn = ?", (item["nisn"],))
        if baris:
            return int(baris["id"]), "nisn"
    if item.get("nik"):
        baris = db.query_one("SELECT id FROM students WHERE nik = ?", (item["nik"],))
        if baris:
            return int(baris["id"]), "nik"
    if item.get("nama"):
        kunci = norm_teks(item["nama"])
        for siswa in db.query_all("SELECT id, nama FROM students WHERE nama IS NOT NULL"):
            if norm_teks(siswa["nama"]) == kunci:
                return int(siswa["id"]), "nama"
    return None, "tidak_ada"


# =========================================================================== #
# Daftar & ringkasan
# =========================================================================== #
def daftar_penerima(*, tahun: str = "", semester: str = "", cari: str = "",
                    cocok: str = "", batas: int = 500) -> list[dict[str, Any]]:
    potongan: list[str] = []
    nilai: list[Any] = []
    if tahun:
        potongan.append("p.tahun = ?")
        nilai.append(tahun)
    if semester:
        potongan.append("p.semester = ?")
        nilai.append(semester)
    if cocok == "ada":
        potongan.append("p.cocok IN ('nisn','nik','nama')")
    elif cocok == "belum":
        potongan.append("(p.cocok IS NULL OR p.cocok = 'tidak_ada' OR p.cocok = 'belum_dicek')")
    if cari:
        potongan.append("(p.nama LIKE ? OR p.nisn LIKE ? OR p.nik LIKE ? OR p.rombel LIKE ?"
                        " OR p.rekening LIKE ?)")
        nilai.extend([f"%{cari}%"] * 5)
    where = ("WHERE " + " AND ".join(potongan)) if potongan else ""
    return db.rows_to_dicts(db.query_all(
        f"""
        SELECT p.*, s.rombel AS rombel_siswa, s.status AS status_siswa
          FROM tangcer_penerima p
          LEFT JOIN students s ON s.id = p.student_id
          {where}
         ORDER BY p.nama COLLATE NOCASE
         LIMIT ?
        """,
        (*nilai, batas),
    ))


def ringkas_penerima() -> dict[str, Any]:
    total = db.query_one("SELECT COUNT(*) AS n FROM tangcer_penerima")
    nominal = db.query_one("SELECT COALESCE(SUM(nominal), 0) AS n FROM tangcer_penerima")
    cocok = db.query_one(
        "SELECT COUNT(*) AS n FROM tangcer_penerima WHERE cocok IN ('nisn','nik','nama')")
    belum = db.query_one(
        "SELECT COUNT(*) AS n FROM tangcer_penerima "
        "WHERE cocok IS NULL OR cocok IN ('tidak_ada','belum_dicek')")
    per_tahun = db.rows_to_dicts(db.query_all(
        """
        SELECT tahun, semester, COUNT(*) AS jumlah, COALESCE(SUM(nominal), 0) AS nominal
          FROM tangcer_penerima GROUP BY tahun, semester
         ORDER BY tahun DESC, semester
        """))
    per_rombel = db.rows_to_dicts(db.query_all(
        """
        SELECT COALESCE(NULLIF(TRIM(rombel), ''), '(tanpa rombel)') AS rombel, COUNT(*) AS jumlah
          FROM tangcer_penerima GROUP BY rombel ORDER BY jumlah DESC LIMIT 12
        """))
    return {
        "total": int(total["n"] if total else 0),
        "nominal": float(nominal["n"] if nominal else 0),
        "cocok": int(cocok["n"] if cocok else 0),
        "belum_cocok": int(belum["n"] if belum else 0),
        "per_tahun": per_tahun,
        "per_rombel": per_rombel,
    }


def daftar_tahun() -> list[str]:
    return [baris["tahun"] for baris in db.query_all(
        "SELECT DISTINCT tahun FROM tangcer_penerima WHERE tahun <> '' ORDER BY tahun DESC")]


def hapus_penerima(tahun: str = "", semester: str = "") -> int:
    potongan: list[str] = []
    nilai: list[Any] = []
    if tahun:
        potongan.append("tahun = ?")
        nilai.append(tahun)
    if semester:
        potongan.append("semester = ?")
        nilai.append(semester)
    where = ("WHERE " + " AND ".join(potongan)) if potongan else ""
    with db.transaction() as conn:
        jumlah = conn.execute(f"SELECT COUNT(*) FROM tangcer_penerima {where}", nilai).fetchone()[0]
        conn.execute(f"DELETE FROM tangcer_penerima {where}", nilai)
    return int(jumlah)


def hapus_satu(penerima_id: int) -> None:
    db.execute("DELETE FROM tangcer_penerima WHERE id = ?", (penerima_id,))


# =========================================================================== #
# Ekspor
# =========================================================================== #
KOLOM_EKSPOR: list[tuple[str, str]] = [
    ("no", "No"),
    ("nama", "Nama Penerima"),
    ("nisn", "NISN"),
    # Nomor rekening dipakai menyusun SPJ — ikut di daftar & ekspor (ronde 62).
    ("rekening", "Nomor Rekening"),
    ("nik", "NIK"),
    ("rombel", "Rombel/Kelas"),
    ("jenis", "Jenis Bantuan"),
    ("nominal", "Nominal"),
    ("tahun", "Tahun"),
    ("semester", "Semester"),
    ("tahap", "Tahap"),
    ("sekolah", "Sekolah pada Berkas"),
    ("cocok", "Cocok dengan Data Siswa"),
    ("keterangan", "Keterangan"),
]

COCOK_LABEL = {
    "nisn": "ya (NISN)", "nik": "ya (NIK)", "nama": "ya (nama)",
    "tidak_ada": "belum ada di data siswa", "belum_dicek": "belum diperiksa",
}


def nilai_ekspor(nomor: int, item: dict[str, Any]) -> dict[str, Any]:
    """Isi tiap kolom ekspor untuk satu penerima (kuncinya sama dengan :data:`KOLOM_EKSPOR`).

    Disusun per-nama kolom — bukan berurutan menurut posisi — supaya menambah kolom baru
    (mis. nomor rekening) tidak membuat nilai kolom lain ikut bergeser.
    """
    return {
        "no": nomor,
        "nama": item.get("nama") or "",
        "nisn": item.get("nisn") or "",
        "rekening": item.get("rekening") or "",
        "nik": item.get("nik") or "",
        "rombel": item.get("rombel") or "",
        "jenis": item.get("jenis") or "",
        "nominal": item.get("nominal") if item.get("nominal") is not None else "",
        "tahun": item.get("tahun") or "",
        "semester": item.get("semester") or "",
        "tahap": item.get("tahap") or "",
        "sekolah": item.get("sekolah") or "",
        "cocok": COCOK_LABEL.get(item.get("cocok") or "", item.get("cocok") or ""),
        "keterangan": item.get("keterangan") or "",
    }


def baris_ekspor(tahun: str = "", semester: str = "") -> list[list[Any]]:
    data = daftar_penerima(tahun=tahun, semester=semester, batas=100_000)
    keluaran: list[list[Any]] = []
    for nomor, item in enumerate(data, start=1):
        nilai = nilai_ekspor(nomor, item)
        keluaran.append([nilai.get(kunci, "") for kunci, _ in KOLOM_EKSPOR])
    return keluaran


def ekspor_csv(tahun: str = "", semester: str = "") -> bytes:
    buffer = io.StringIO()
    penulis = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    penulis.writerow([label for _, label in KOLOM_EKSPOR])
    for baris in baris_ekspor(tahun, semester):
        penulis.writerow(baris)
    return buffer.getvalue().encode("utf-8-sig")


def ekspor_xlsx(tahun: str = "", semester: str = "") -> bytes:
    import openpyxl  # noqa: PLC0415
    from openpyxl.styles import Alignment, Font, PatternFill  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415

    profil = services.school_profile()
    buku = openpyxl.Workbook()
    lembar = buku.active
    lembar.title = "Penerima TANGCER"
    lembar["A1"] = "Daftar Penerima TANGCER"
    lembar["A1"].font = Font(size=14, bold=True)
    lembar["A2"] = profil["nama"]
    lembar["A3"] = (f"Tahun {tahun or 'semua'} · Semester {semester or 'semua'} · "
                    f"diekspor {dt.datetime.now():%Y-%m-%d %H:%M}")
    for kolom, (_, label) in enumerate(KOLOM_EKSPOR, start=1):
        sel = lembar.cell(row=5, column=kolom, value=label)
        sel.font = Font(bold=True, color="FFFFFF")
        sel.fill = PatternFill("solid", fgColor="1D4ED8")
        sel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    isi = baris_ekspor(tahun, semester)
    for nomor, baris in enumerate(isi, start=6):
        for kolom, nilai in enumerate(baris, start=1):
            lembar.cell(row=nomor, column=kolom, value=nilai)
    lembar.freeze_panes = "A6"
    lembar.auto_filter.ref = f"A5:{get_column_letter(len(KOLOM_EKSPOR))}{max(5, 5 + len(isi))}"
    for kolom, lebar in enumerate([5, 30, 14, 18, 20, 12, 22, 14, 8, 10, 8, 34, 22, 24],
                                  start=1):
        lembar.column_dimensions[get_column_letter(kolom)].width = lebar
    aliran = io.BytesIO()
    buku.save(aliran)
    return aliran.getvalue()


def ekspor_pdf(tahun: str = "", semester: str = "") -> bytes:
    from .pdf import buat_pdf_tabel  # noqa: PLC0415

    profil = services.school_profile()
    baris = baris_ekspor(tahun, semester)
    kolom = [("No", 24), ("Nama Penerima", 150), ("NISN", 78), ("Nomor Rekening", 84),
             ("Rombel", 50), ("Nominal", 70), ("Status", 62)]
    letak = {kunci: nomor for nomor, (kunci, _) in enumerate(KOLOM_EKSPOR)}
    isi = [[item[letak["no"]], item[letak["nama"]], item[letak["nisn"]],
            item[letak["rekening"]] or "-",
            item[letak["rombel"]],
            f"{(item[letak['nominal']] or 0):,.0f}".replace(",", ".")
            if item[letak["nominal"]] != "" else "-",
            item[letak["cocok"]]] for item in baris]
    return buat_pdf_tabel(
        "Daftar Penerima TANGCER",
        kolom,
        isi,
        subjudul=[profil["nama"],
                  f"Tahun {tahun or 'semua'} · Semester {semester or 'semua'}"],
        catatan_kaki=[f"Dicetak dari aplikasi SM · {dt.datetime.now():%d-%m-%Y %H:%M}"],
    )


# =========================================================================== #
# Ringkasan untuk halaman
# =========================================================================== #
def format_rupiah(nilai: Any) -> str:
    try:
        angka = float(nilai or 0)
    except (TypeError, ValueError):
        angka = 0.0
    teks = f"{angka:,.0f}".replace(",", ".")
    return f"Rp {teks}"




# =========================================================================== #
# Bedah berkas — «apa isi berkas ini sebenarnya?»
# =========================================================================== #
#: Folder penyimpanan teks hasil bedah (bisa diunduh supaya ikut dilaporkan).
FOLDER_BEDAH = "bedah"
#: Batas panjang teks yang disimpan supaya berkasnya tetap ringan dikirim.
BATAS_TEKS_BEDAH = 300_000
#: Berapa baris yang ditampilkan di halaman (sisanya tetap ada di berkas teks).
BARIS_TAMPIL_BEDAH = 60


def _nama_aman(nama: str) -> str:
    bersih = re.sub(r"[^A-Za-z0-9._-]+", "-", (nama or "berkas").strip()).strip("-._")
    return (bersih or "berkas")[:60]


def _baris_dari_potongan(potongan: Sequence[Sequence[Any]]) -> list[str]:
    """Susun potongan teks satu halaman menjadi baris siap dibaca manusia."""
    terurut = sorted(potongan, key=lambda item: (-float(item[1]), float(item[0])))
    baris: list[list[Any]] = []
    for butir in terurut:
        y = float(butir[1])
        if baris and abs(baris[-1][0] - y) <= 3.0:
            baris[-1][1].append(butir)
        else:
            baris.append([y, [butir]])
    keluaran: list[str] = []
    for _, isi in baris:
        teks = pdf_baca._teks_satu_baris(isi)
        if teks.strip():
            keluaran.append(teks)
    return keluaran


def simpan_teks_bedah(nama: str, teks: str) -> str:
    """Simpan hasil bedah sebagai berkas teks yang bisa diunduh & dikirim.

    Hanya 12 berkas terbaru yang disimpan — ini alat laporan sementara, bukan arsip.
    """
    folder = config.DATA_DIR / FOLDER_BEDAH
    folder.mkdir(parents=True, exist_ok=True)
    cap = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    token = f"{cap}-{_nama_aman(Path(nama).stem)}.txt"
    (folder / token).write_text(teks, encoding="utf-8")
    lama = sorted(folder.glob("*.txt"))[:-12]
    for berkas in lama:
        berkas.unlink(missing_ok=True)
    return token


def berkas_bedah(token: str) -> Path | None:
    """Cari berkas teks hasil bedah berdasarkan tokennya (dijaga dari keluar folder)."""
    if not token or token.startswith(".") or "/" in token or "\\" in token:
        return None
    jalur = config.DATA_DIR / FOLDER_BEDAH / token
    return jalur if jalur.is_file() else None


def bedah_berkas(nama: str, isi: bytes) -> dict[str, Any]:
    """Periksa isi berkas apa adanya (PDF maupun spreadsheet) untuk dilaporkan.

    Hasilnya sengaja **tidak** menyimpulkan apa pun tentang sekolah: yang dilaporkan
    hanya apa yang benar-benar terbaca (mesin pembaca, jumlah halaman/baris, kolom yang
    dikenali) beserta catatan bila ada yang tidak terbaca. Teks lengkapnya disimpan
    supaya bisa diunduh dan dikirim untuk pemeriksaan lanjutan.
    """
    ext = Path(nama).suffix.lower()
    hasil: dict[str, Any] = {
        "nama": nama, "ext": ext or "(tanpa ekstensi)", "ukuran": len(isi), "jenis": "",
        "pembaca": [], "catatan": [], "bagian": [], "jumlah_baris": 0,
        "baris_tampil": BARIS_TAMPIL_BEDAH, "teks": "", "token": "", "saran": "",
    }
    teks_berkas: list[str] = [f"Berkas : {nama}", f"Jenis  : {ext or '(tanpa ekstensi)'}",
                              f"Ukuran : {len(isi)} bita",
                              f"Waktu  : {dt.datetime.now():%Y-%m-%d %H:%M:%S}", ""]

    if ext in FORMAT_PDF:
        hasil["jenis"] = "PDF (SK definitif)"
        try:
            bawaan = pdf_baca.baca_pdf(isi)
        except pdf_baca.PdfBacaError as galat:
            hasil["catatan"].append(f"pembaca bawaan SM: {galat}")
            teks_berkas.append(f"[pembaca bawaan SM] {galat}")
        else:
            hasil["pembaca"].append(
                f"pembaca bawaan SM (tanpa pustaka tambahan): {bawaan.jumlah_halaman} halaman · "
                f"{bawaan.jumlah_potongan} potongan teks")
            hasil["catatan"].extend(bawaan.catatan)
            for nomor, halaman in enumerate(bawaan.halaman, start=1):
                baris = _baris_dari_potongan(halaman)
                hasil["jumlah_baris"] += len(baris)
                hasil["bagian"].append({"judul": f"Halaman {nomor}", "jumlah": len(baris),
                                        "baris": baris})
                teks_berkas.append(f"=== Halaman {nomor} ({len(baris)} baris) ===")
                teks_berkas.extend(baris or ["(tidak ada teks pada halaman ini)"])
                teks_berkas.append("")
        if pdf_baca.ada_pembaca_pypdf():
            try:
                halaman_pypf = halaman_pdf(isi, mesin=MESIN_PDF_PYPF)
            except TangcerError as galat:
                hasil["pembaca"].append(f"pustaka pypdf: {galat}")
            else:
                jumlah = sum(len(garis.potongan) for halaman in halaman_pypf for garis in halaman)
                hasil["pembaca"].append(
                    f"pustaka pypdf (pembanding): {len(halaman_pypf)} halaman · "
                    f"{jumlah} potongan teks")
        else:
            hasil["pembaca"].append("pustaka pypdf: tidak terpasang — tidak masalah, "
                                    "pembaca bawaan SM sudah dipakai")
        if not hasil["jumlah_baris"]:
            hasil["saran"] = ("Berkas ini tidak memuat teks yang bisa dibaca — kemungkinan "
                              "hasil pindai (scan/gambar). Berkas seperti itu perlu di-OCR "
                              "lebih dulu; potret (screenshot) halamannya juga bisa dipakai.")
        else:
            hasil["saran"] = ("Teks di bawah persis seperti yang terbaca aplikasi. Unduh "
                              "berkas teksnya lalu kirimkan bila ada baris yang seharusnya "
                              "masuk tetapi belum terbaca.")
    else:
        from .readers import UnsupportedFormatError, read_spreadsheet  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        hasil["jenis"] = "berkas tabel (Excel/CSV)"
        if not ext:
            raise TangcerError("Berkas ini tanpa ekstensi — beri nama dengan .xlsx/.csv/.pdf "
                               "supaya isinya bisa dibaca.")
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as berkas:
            berkas.write(isi)
            sementara = Path(berkas.name)
        try:
            sheets = read_spreadsheet(sementara, ext)
        finally:
            sementara.unlink(missing_ok=True)
        for sheet in sheets:
            baris_sheet = ["  |  ".join(bersih_teks(sel) for sel in baris)
                           for baris in sheet.rows if any(bersih_teks(sel) for sel in baris)]
            hasil["jumlah_baris"] += len(baris_sheet)
            hasil["bagian"].append({"judul": f"worksheet «{sheet.name}»",
                                    "jumlah": len(baris_sheet), "baris": baris_sheet})
            teks_berkas.append(f"=== worksheet «{sheet.name}» ({len(baris_sheet)} baris) ===")
            teks_berkas.extend(baris_sheet or ["(kosong)"])
            teks_berkas.append("")
        hasil["pembaca"].append(f"pembaca spreadsheet bawaan aplikasi: {len(sheets)} worksheet · "
                                f"{hasil['jumlah_baris']} baris")
        hasil["saran"] = ("Berkas tabel bisa langsung diunggah lewat «Baca & Pratinjau»; "
                          "halaman ini hanya memperlihatkan isinya apa adanya.")

    teks_penuh = "\n".join(teks_berkas)
    hasil["teks"] = teks_penuh[:BATAS_TEKS_BEDAH]
    hasil["token"] = simpan_teks_bedah(nama, teks_penuh[:BATAS_TEKS_BEDAH])
    return hasil
