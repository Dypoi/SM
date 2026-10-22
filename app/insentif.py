"""Insentif guru & tendik — SPJ + absensi bulanan otomatis.

Menu ini menjawab kebutuhan sekolah: setiap bulan bendahara harus menyusun
**SPJ insentif** (daftar penerima + tarif + PPh + tanda tangan) dan **absensi
guru PNS/PPPK** (kalender kehadiran dengan tanggal merah). Semuanya dibuat
otomatis dari data GTK yang sudah ada, tinggal unduh PDF siap cetak.

Sumber format: tiga berkas kerja sekolah tahun 2025 (``ABSENSI GURU PNS.xlsx``,
``ABSENSI GURU PPPK.xlsx``, ``SPJ 2025.xls``). Aturan main yang disalin:

* absensi: judul «DAFTAR HADIR TENAGA PENDIDIK ( PNS / PPPK )», grid
  HARI/TANGGAL dua lajur (3 minggu pertama + sisanya, Senin–Jumat),
  tanggal merah + keterangan libur, legenda S/I/C/DL, tanda tangan
  Kepala Sekolah;
* SPJ: format baku terbaru (18 kolom: NO … BULAN … TTD), tarif
  Kepala Sekolah 7.000.000 / Wakasek 2.700.000 / Guru 1.350.000 /
  pelatih 650.000, PPh 15% (gol IV) / 5% (gol III/IX) / 0% (non-ASN),
  ditandatangani bendahara + pengawas + Kepala Sekolah.

Tanggal merah memakai kalender bawaan 2024–2027 (libur nasional + cuti
bersama sesuai SKB 3 Menteri) yang bisa ditambah/dinonaktifkan per tanggal
dari halaman Kelola Libur. Yang berwarna merah dan masuk keterangan hanya
hari Senin–Jumat (Sabtu/Minggu memang tidak ada di grid absensi).
"""

from __future__ import annotations

import calendar
import datetime as dt
from typing import Any, Mapping, Sequence

from . import db

log = __import__("logging").getLogger("sm.insentif")

# --------------------------------------------------------------------------- #
# Nama bulan & hari
# --------------------------------------------------------------------------- #
NAMA_BULAN = (
    "", "JANUARI", "FEBRUARI", "MARET", "APRIL", "MEI", "JUNI", "JULI",
    "AGUSTUS", "SEPTEMBER", "OKTOBER", "NOVEMBER", "DESEMBER",
)
NAMA_BULAN_KECIL = (
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
    "Agustus", "September", "Oktober", "November", "Desember",
)
#: Label hari pada grid absensi (kolom Senin–Jumat).
NAMA_HARI = ("SENIN", "SELASA", "RABU", "KAMIS", "JUM'AT")

DOKUMEN = (
    ("pns", "Absensi Guru PNS"),
    ("pppk", "Absensi Guru PPPK"),
    ("spj", "SPJ Insentif"),
)

# --------------------------------------------------------------------------- #
# Kalender bawaan: libur nasional + cuti bersama 2024–2027
# --------------------------------------------------------------------------- #
#: tanggal ISO -> (keterangan, jenis). Jenis: 'nasional' | 'cuti'.
#: Disalin dari data SKB 3 Menteri (paket `nusaindex`, dicek silang dengan
#: berkas absensi 2025 milik sekolah: seluruh tanggal merah Januari–Desember
#: cocok, kecuali 28 Mar 2025 yang terlewat di berkas sekolah dan 18 Agu 2025
#: yang ditambahkan pemerintah belakangan — keduanya sudah benar di sini).
LIBUR_BAWAAN: dict[str, tuple[str, str]] = {
    # ---- 2024 ----
    "2024-01-01": ("Tahun Baru Masehi 2024", "nasional"),
    "2024-02-08": ("Isra Mi'raj Nabi Muhammad SAW", "nasional"),
    "2024-02-09": ("Cuti Bersama Tahun Baru Imlek 2575", "cuti"),
    "2024-02-10": ("Tahun Baru Imlek 2575", "nasional"),
    "2024-02-14": ("Pemungutan Suara Pemilu 2024", "nasional"),
    "2024-03-11": ("Hari Suci Nyepi 1946", "nasional"),
    "2024-03-12": ("Cuti Bersama Hari Suci Nyepi", "cuti"),
    "2024-03-29": ("Wafat Yesus Kristus", "nasional"),
    "2024-03-31": ("Paskah/Kebangkitan Yesus Kristus", "nasional"),
    "2024-04-08": ("Cuti Bersama Idul Fitri 1445 H", "cuti"),
    "2024-04-09": ("Cuti Bersama Idul Fitri 1445 H", "cuti"),
    "2024-04-10": ("Hari Raya Idul Fitri 1445 H", "nasional"),
    "2024-04-11": ("Hari Raya Idul Fitri 1445 H", "nasional"),
    "2024-04-12": ("Cuti Bersama Idul Fitri 1445 H", "cuti"),
    "2024-04-15": ("Cuti Bersama Idul Fitri 1445 H", "cuti"),
    "2024-05-01": ("Hari Buruh Internasional", "nasional"),
    "2024-05-09": ("Kenaikan Yesus Kristus", "nasional"),
    "2024-05-10": ("Cuti Bersama Kenaikan Yesus Kristus", "cuti"),
    "2024-05-23": ("Hari Raya Waisak 2568 BE", "nasional"),
    "2024-05-24": ("Cuti Bersama Hari Raya Waisak", "cuti"),
    "2024-06-01": ("Hari Lahir Pancasila", "nasional"),
    "2024-06-17": ("Hari Raya Idul Adha 1445 H", "nasional"),
    "2024-06-18": ("Cuti Bersama Idul Adha 1445 H", "cuti"),
    "2024-07-07": ("Tahun Baru Islam 1446 H", "nasional"),
    "2024-08-17": ("Hari Kemerdekaan RI", "nasional"),
    "2024-09-16": ("Maulid Nabi Muhammad SAW", "nasional"),
    "2024-11-27": ("Pemungutan Suara Pilkada Serentak 2024", "nasional"),
    "2024-12-25": ("Hari Raya Natal", "nasional"),
    "2024-12-26": ("Cuti Bersama Natal", "cuti"),
    # ---- 2025 ----
    "2025-01-01": ("Tahun Baru Masehi 2025", "nasional"),
    "2025-01-27": ("Isra Mi'raj Nabi Muhammad SAW", "nasional"),
    "2025-01-28": ("Cuti Bersama Tahun Baru Imlek 2576", "cuti"),
    "2025-01-29": ("Tahun Baru Imlek 2576", "nasional"),
    "2025-03-28": ("Cuti Bersama Hari Suci Nyepi", "cuti"),
    "2025-03-29": ("Hari Suci Nyepi 1947", "nasional"),
    "2025-03-31": ("Hari Raya Idul Fitri 1446 H", "nasional"),
    "2025-04-01": ("Hari Raya Idul Fitri 1446 H", "nasional"),
    "2025-04-02": ("Cuti Bersama Idul Fitri 1446 H", "cuti"),
    "2025-04-03": ("Cuti Bersama Idul Fitri 1446 H", "cuti"),
    "2025-04-04": ("Cuti Bersama Idul Fitri 1446 H", "cuti"),
    "2025-04-07": ("Cuti Bersama Idul Fitri 1446 H", "cuti"),
    "2025-04-18": ("Wafat Yesus Kristus", "nasional"),
    "2025-04-20": ("Paskah/Kebangkitan Yesus Kristus", "nasional"),
    "2025-05-01": ("Hari Buruh Internasional", "nasional"),
    "2025-05-12": ("Hari Raya Waisak 2569 BE", "nasional"),
    "2025-05-13": ("Cuti Bersama Hari Raya Waisak", "cuti"),
    "2025-05-29": ("Kenaikan Yesus Kristus", "nasional"),
    "2025-05-30": ("Cuti Bersama Kenaikan Yesus Kristus", "cuti"),
    "2025-06-01": ("Hari Lahir Pancasila", "nasional"),
    "2025-06-06": ("Hari Raya Idul Adha 1446 H", "nasional"),
    "2025-06-09": ("Cuti Bersama Idul Adha 1446 H", "cuti"),
    "2025-06-27": ("Tahun Baru Islam 1447 H", "nasional"),
    "2025-08-17": ("Hari Kemerdekaan RI", "nasional"),
    "2025-08-18": ("Cuti Bersama Proklamasi Kemerdekaan", "cuti"),
    "2025-09-05": ("Maulid Nabi Muhammad SAW", "nasional"),
    "2025-12-25": ("Hari Raya Natal", "nasional"),
    "2025-12-26": ("Cuti Bersama Natal", "cuti"),
    # ---- 2026 ----
    "2026-01-01": ("Tahun Baru Masehi 2026", "nasional"),
    "2026-01-16": ("Isra Mi'raj Nabi Muhammad SAW", "nasional"),
    "2026-02-16": ("Cuti Bersama Tahun Baru Imlek 2577", "cuti"),
    "2026-02-17": ("Tahun Baru Imlek 2577", "nasional"),
    "2026-03-18": ("Cuti Bersama Hari Suci Nyepi", "cuti"),
    "2026-03-19": ("Hari Suci Nyepi 1948", "nasional"),
    "2026-03-20": ("Cuti Bersama Idul Fitri 1447 H", "cuti"),
    "2026-03-21": ("Hari Raya Idul Fitri 1447 H", "nasional"),
    "2026-03-22": ("Hari Raya Idul Fitri 1447 H", "nasional"),
    "2026-03-23": ("Cuti Bersama Idul Fitri 1447 H", "cuti"),
    "2026-03-24": ("Cuti Bersama Idul Fitri 1447 H", "cuti"),
    "2026-04-03": ("Wafat Yesus Kristus", "nasional"),
    "2026-04-05": ("Paskah/Kebangkitan Yesus Kristus", "nasional"),
    "2026-05-01": ("Hari Buruh Internasional", "nasional"),
    "2026-05-14": ("Kenaikan Yesus Kristus", "nasional"),
    "2026-05-15": ("Cuti Bersama Kenaikan Yesus Kristus", "cuti"),
    "2026-05-27": ("Hari Raya Idul Adha 1447 H", "nasional"),
    "2026-05-28": ("Cuti Bersama Idul Adha 1447 H", "cuti"),
    "2026-05-31": ("Hari Raya Waisak 2570 BE", "nasional"),
    "2026-06-01": ("Hari Lahir Pancasila", "nasional"),
    "2026-06-16": ("Tahun Baru Islam 1448 H", "nasional"),
    "2026-08-17": ("Hari Kemerdekaan RI", "nasional"),
    "2026-08-25": ("Maulid Nabi Muhammad SAW", "nasional"),
    "2026-12-24": ("Cuti Bersama Natal", "cuti"),
    "2026-12-25": ("Hari Raya Natal", "nasional"),
    # ---- 2027 ----
    "2027-01-01": ("Tahun Baru Masehi 2027", "nasional"),
    "2027-01-05": ("Isra Mi'raj Nabi Muhammad SAW", "nasional"),
    "2027-02-05": ("Cuti Bersama Tahun Baru Imlek 2578", "cuti"),
    "2027-02-06": ("Tahun Baru Imlek 2578", "nasional"),
    "2027-03-08": ("Hari Suci Nyepi 1949", "nasional"),
    "2027-03-09": ("Cuti Bersama Idul Fitri 1448 H", "cuti"),
    "2027-03-10": ("Hari Raya Idul Fitri 1448 H", "nasional"),
    "2027-03-11": ("Hari Raya Idul Fitri 1448 H", "nasional"),
    "2027-03-12": ("Cuti Bersama Idul Fitri 1448 H", "cuti"),
    "2027-03-15": ("Cuti Bersama Idul Fitri 1448 H", "cuti"),
    "2027-03-25": ("Cuti Bersama Wafat Yesus Kristus", "cuti"),
    "2027-03-26": ("Wafat Yesus Kristus", "nasional"),
    "2027-03-28": ("Paskah/Kebangkitan Yesus Kristus", "nasional"),
    "2027-05-01": ("Hari Buruh Internasional", "nasional"),
    "2027-05-06": ("Kenaikan Yesus Kristus", "nasional"),
    "2027-05-17": ("Hari Raya Idul Adha 1448 H", "nasional"),
    "2027-05-18": ("Cuti Bersama Idul Adha 1448 H", "cuti"),
    "2027-05-19": ("Cuti Bersama Hari Raya Waisak", "cuti"),
    "2027-05-20": ("Hari Raya Waisak 2571 BE", "nasional"),
    "2027-06-01": ("Hari Lahir Pancasila", "nasional"),
    "2027-06-06": ("Tahun Baru Islam 1449 H", "nasional"),
    "2027-08-15": ("Maulid Nabi Muhammad SAW", "nasional"),
    "2027-08-17": ("Hari Kemerdekaan RI", "nasional"),
    "2027-12-24": ("Cuti Bersama Natal", "cuti"),
    "2027-12-25": ("Hari Raya Natal", "nasional"),
    "2027-12-26": ("Isra Mi'raj Nabi Muhammad SAW", "nasional"),
}


def tanggal_merah(tahun: int, bulan: int,
                 tambahan: Mapping[str, tuple[str, str] | None] | None = None
                 ) -> dict[int, str]:
    """Tanggal merah bulan ini: ``{tanggal: keterangan}`` (Senin–Jumat saja).

    ``tambahan`` menimpa kalender bawaan: nilai ``None`` menonaktifkan
    tanggal itu, selebihnya ``(keterangan, jenis)`` menambah/mengganti.
    """
    hasil: dict[int, str] = {}
    gabung: dict[str, tuple[str, str] | None] = dict(LIBUR_BAWAAN)
    if tambahan:
        gabung.update(tambahan)
    awal = f"{tahun:04d}-{bulan:02d}-"
    for iso, nilai in gabung.items():
        if nilai is None or not iso.startswith(awal):
            continue
        nama, _jenis = nilai
        try:
            tanggal = dt.date.fromisoformat(iso)
        except ValueError:
            continue
        if tanggal.weekday() < 5:  # Senin=0 .. Jumat=4
            hasil[tanggal.day] = nama
    return hasil


def grid_absensi(tahun: int, bulan: int,
                merah: Mapping[int, str] | None = None
                ) -> dict[str, list[dict[str, Any] | None]]:
    """Grid HARI/TANGGAL absensi: dua lajur @ 15 sel (3 minggu × Sen–Jum).

    Lajur 1 = hari kerja pada 3 minggu kalender pertama yang menyentuh
    bulan ini; lajur 2 = sisanya. Tiap sel berisi ``None`` (tanpa tanggal)
    atau ``{"tgl": int, "libur": str | None}``. Selalu selaras weekday:
    kolom ke-0/5/10 = Senin, ke-4/9/14 = Jumat.
    """
    merah = merah or {}
    pertama = dt.date(tahun, bulan, 1)
    # Senin pada minggu yang memuat tanggal 1 (bisa mundur ke bulan lalu).
    senin = pertama - dt.timedelta(days=pertama.weekday())
    lajur1: list[dict[str, Any] | None] = []
    lajur2: list[dict[str, Any] | None] = []
    pekan = 0
    while True:
        for geser in range(5):  # Senin..Jumat
            hari = senin + dt.timedelta(days=geser)
            sel = ({"tgl": hari.day, "libur": merah.get(hari.day)}
                   if hari.month == bulan else None)
            (lajur1 if pekan < 3 else lajur2).append(sel)
        pekan += 1
        senin += dt.timedelta(days=7)
        if senin.month != bulan and (senin - dt.timedelta(days=7)).month != bulan:
            break
        if pekan > 6:  # pengaman, takkan terjadi
            break
    # Kedua lajur selalu 15 sel (grid tetap); lajur 2 dipadatkan.
    while len(lajur2) < 15:
        lajur2.append(None)
    return {"band1": lajur1[:15], "band2": lajur2[:15]}


def tanggal_terakhir(tahun: int, bulan: int) -> int:
    """Tanggal terakhir kalender (dipakai tanggal tanda tangan)."""
    return calendar.monthrange(tahun, bulan)[1]


# --------------------------------------------------------------------------- #
# Pangkat, tarif & PPh
# --------------------------------------------------------------------------- #
#: Golongan -> nama pangkat (persis gaya berkas sekolah).
PANGKAT = {
    "IV/E": "Pembina Utama", "IV/D": "Pembina Utama Madya",
    "IV/C": "Pembina Utama Muda", "IV/B": "Pembina TK.I", "IV/A": "Pembina",
    "III/D": "Penata TK.I", "III/C": "Penata", "III/B": "Penata Muda TK.I",
    "III/A": "Penata Muda",
    "II/D": "Pengatur TK.I", "II/C": "Pengatur", "II/B": "Pengatur Muda TK.I",
    "II/A": "Pengatur Muda",
    "I/D": "Juru TK.I", "I/C": "Juru", "I/B": "Juru Muda TK.I",
    "I/A": "Juru Muda",
    "IX": "Ahli Pertama",
}


def teks_pangkat(gol: Any) -> str:
    """«Pembina - IV/a» / «Ahli Pertama - IX» / kode apa adanya bila asing."""
    kode = (str(gol or "").strip())
    if not kode:
        return ""
    nama = PANGKAT.get(kode.upper())
    return f"{nama} - {kode}" if nama else kode


def _peringkat_gol(gol: Any) -> int:
    kode = str(gol or "").strip().upper()
    urut = ["I/A", "I/B", "I/C", "I/D", "II/A", "II/B", "II/C", "II/D",
            "III/A", "III/B", "III/C", "III/D",
            "IV/A", "IV/B", "IV/C", "IV/D", "IV/E"]
    try:
        return urut.index(kode.replace(" ", ""))
    except ValueError:
        if kode in ("VII", "VIII"):
            return 8
        if kode == "IX":
            return 9
        return -1


def tarif_untuk(jabatan: Any, pengaturan: Mapping[str, Any],
               override: Any = None) -> int:
    """Tarif insentif: override per orang menang, selebihnya per jabatan."""
    try:
        if override is not None and str(override).strip() != "":
            return max(0, int(float(str(override).replace(".", "").replace(",", "."))))
    except (ValueError, TypeError):
        pass
    jab = str(jabatan or "").strip().lower()
    kunci = "tarif_guru"
    if "kepala sekolah" in jab and "wakil" not in jab:
        kunci = "tarif_ks"
    elif "wakil" in jab:
        kunci = "tarif_waka"
    elif jab in ("guru", "") or "guru" in jab:
        kunci = "tarif_guru"
    else:  # pelatih / instruktur / tenaga kependidikan / lainnya
        kunci = "tarif_pelatih"
    try:
        return max(0, int(pengaturan.get(kunci, 0) or 0))
    except (ValueError, TypeError):
        return 0


def persen_pph(nip: Any, gol: Any, pengaturan: Mapping[str, Any]) -> int:
    """PPh 21: 15% gol IV, 5% ASN lain, 0% tanpa NIP (mengikuti berkas 2025)."""
    if not str(nip or "").strip():
        return _angka_pengaturan(pengaturan, "pph_nonasn", 0)
    if str(gol or "").strip().upper().startswith("IV"):
        return _angka_pengaturan(pengaturan, "pph_4", 15)
    return _angka_pengaturan(pengaturan, "pph_3", 5)


def _angka_pengaturan(pengaturan: Mapping[str, Any], kunci: str, bawaan: int) -> int:
    try:
        return int(pengaturan.get(kunci, bawaan) or 0)
    except (ValueError, TypeError):
        return bawaan


# --------------------------------------------------------------------------- #
# Format tampilan angka & identitas
# --------------------------------------------------------------------------- #
def rupiah(nilai: Any) -> str:
    """2.700.000 — gaya angka berkas sekolah (pemisah titik)."""
    try:
        angka = int(float(nilai or 0))
    except (ValueError, TypeError):
        angka = 0
    return f"{angka:,}".replace(",", ".")


def hanya_digit(teks: Any) -> str:
    return "".join(k for k in str(teks or "") if k.isdigit())


def format_nip_spasi(nip: Any) -> str:
    """NIP 18 digit -> «19740520 200501 1 007» (gaya absensi)."""
    digit = hanya_digit(nip)
    if len(digit) != 18:
        return str(nip or "").strip()
    return f"{digit[:8]} {digit[8:14]} {digit[14:15]} {digit[15:]}"


def format_npwp(npwp: Any) -> str:
    """NPWP 15 digit -> «49.834.046.2-451.000»; 16 digit dikelompokkan 4-4."""
    digit = hanya_digit(npwp)
    if len(digit) == 15:
        return f"{digit[:2]}.{digit[2:5]}.{digit[5:8]}.{digit[8]}-{digit[9:12]}.{digit[12:]}"
    if len(digit) == 16:
        return f"{digit[:4]} {digit[4:8]} {digit[8:12]} {digit[12:]}"
    return str(npwp or "").strip()


# --------------------------------------------------------------------------- #
# Pengaturan
# --------------------------------------------------------------------------- #
PENGATURAN_BAWAAN = {
    "tarif_ks": "7000000",
    "tarif_waka": "2700000",
    "tarif_guru": "1350000",
    "tarif_pelatih": "650000",
    "pph_4": "15",
    "pph_3": "5",
    "pph_nonasn": "0",
    "unit_kerja": "SMP NEGERI 2 TANGERANG",
    "kecamatan": "Kec. Tangerang",
    "kota": "KOTA TANGERANG",
    "bendahara_gtk_id": "",
    "pengawas_nama": "",
    "pengawas_nip": "",
    "ks_nama": "",
    "ks_nip": "",
}


def baca_pengaturan() -> dict[str, str]:
    hasil = dict(PENGATURAN_BAWAAN)
    for baris in db.query_all("SELECT key, value FROM insentif_setting"):
        hasil[baris["key"]] = baris["value"] if baris["value"] is not None else ""
    return hasil


def simpan_pengaturan(nilai: Mapping[str, Any]) -> None:
    with db.transaction() as conn:
        for kunci in PENGATURAN_BAWAAN:
            if kunci in nilai:
                conn.execute(
                    "INSERT INTO insentif_setting(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (kunci, str(nilai[kunci])),
                )


# --------------------------------------------------------------------------- #
# Profil pegawai (nama tampil, jabatan & tarif bawaan — diisi sekali)
# --------------------------------------------------------------------------- #
def _pastikan_profil(gtk_id: int | None, nama_kunci: str = "") -> dict[str, Any]:
    if gtk_id is not None:
        ada = db.query_one("SELECT * FROM insentif_profil WHERE gtk_id = ?", (gtk_id,))
        if ada is not None:
            return db.row_to_dict(ada)  # type: ignore[return-value]
        db.execute(
            "INSERT INTO insentif_profil(gtk_id, nama_kunci) VALUES(?, '')", (gtk_id,))
        return db.row_to_dict(db.query_one(  # type: ignore[return-value]
            "SELECT * FROM insentif_profil WHERE gtk_id = ?", (gtk_id,)))
    ada = db.query_one(
        "SELECT * FROM insentif_profil WHERE gtk_id IS NULL AND nama_kunci = ?",
        (nama_kunci,))
    if ada is not None:
        return db.row_to_dict(ada)  # type: ignore[return-value]
    db.execute("INSERT INTO insentif_profil(gtk_id, nama_kunci) VALUES(NULL, ?)",
               (nama_kunci,))
    return db.row_to_dict(db.query_one(  # type: ignore[return-value]
        "SELECT * FROM insentif_profil WHERE gtk_id IS NULL AND nama_kunci = ?",
        (nama_kunci,)))


def profil_untuk_gtk(gtk_id: int) -> dict[str, Any]:
    return _pastikan_profil(gtk_id)


def daftar_profil() -> list[dict[str, Any]]:
    return db.rows_to_dicts(db.query_all(
        """
        SELECT p.*, g.nama AS nama_gtk, g.jenis_ptk, g.status_kepegawaian,
               g.nip AS nip_gtk, g.pangkat_golongan AS gol_gtk
          FROM insentif_profil p
          LEFT JOIN gtk_pegawai g ON g.id = p.gtk_id
         ORDER BY COALESCE(NULLIF(TRIM(p.nama_tampil), ''), g.nama, p.nama_kunci)
        """))


def simpan_profil(profil_id: int, nilai: Mapping[str, Any]) -> None:
    db.execute(
        """
        UPDATE insentif_profil
           SET nama_tampil = ?, jabatan = ?, tarif_override = ?,
               ikut_pns = ?, ikut_pppk = ?, ikut_spj = ?,
               diubah = datetime('now','localtime')
         WHERE id = ?
        """,
        (str(nilai.get("nama_tampil") or "").strip() or None,
         str(nilai.get("jabatan") or "").strip() or None,
         _angka_atau_none(nilai.get("tarif_override")),
         1 if nilai.get("ikut_pns") else 0,
         1 if nilai.get("ikut_pppk") else 0,
         1 if nilai.get("ikut_spj") else 0,
         profil_id),
    )


def _angka_atau_none(nilai: Any) -> int | None:
    if nilai is None or str(nilai).strip() == "":
        return None
    try:
        return max(0, int(float(str(nilai).replace(".", "").replace(",", "."))))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Libur: gabungan bawaan + atur manual
# --------------------------------------------------------------------------- #
def baca_libur_manual() -> dict[str, dict[str, Any]]:
    hasil: dict[str, dict[str, Any]] = {}
    for baris in db.query_all("SELECT * FROM insentif_libur ORDER BY tanggal"):
        hasil[baris["tanggal"]] = db.row_to_dict(baris)
    return hasil


def tambahan_libur() -> dict[str, tuple[str, str] | None]:
    """Timpaan kalender bawaan dari tabel manual (None = dinonaktifkan)."""
    hasil: dict[str, tuple[str, str] | None] = {}
    for iso, baris in baca_libur_manual().items():
        if not baris.get("aktif"):
            hasil[iso] = None
        else:
            hasil[iso] = (baris.get("nama") or "", baris.get("jenis") or "kustom")
    return hasil


def daftar_libur_tahun(tahun: int) -> list[dict[str, Any]]:
    """Seluruh libur setahun: bawaan + manual, bertanda sumbernya."""
    manual = baca_libur_manual()
    gabung: dict[str, dict[str, Any]] = {}
    for iso, (nama, jenis) in LIBUR_BAWAAN.items():
        if iso.startswith(f"{tahun:04d}-"):
            gabung[iso] = {"tanggal": iso, "nama": nama, "jenis": jenis,
                           "sumber": "bawaan", "aktif": 1}
    for iso, baris in manual.items():
        if iso.startswith(f"{tahun:04d}-"):
            gabung[iso] = {"tanggal": iso, "nama": baris.get("nama") or "",
                           "jenis": baris.get("jenis") or "kustom",
                           "sumber": "bawaan" if iso in LIBUR_BAWAAN else "manual",
                           "aktif": 1 if baris.get("aktif") else 0}
    daftar = sorted(gabung.values(), key=lambda item: item["tanggal"])
    for item in daftar:
        try:
            item["hari"] = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat",
                            "Sabtu", "Minggu")[dt.date.fromisoformat(item["tanggal"]).weekday()]
        except ValueError:
            item["hari"] = ""
    return daftar


def simpan_libur(tanggal: str, nama: str, jenis: str = "kustom",
                aktif: bool = True) -> None:
    dt.date.fromisoformat(tanggal)  # validasi format
    if jenis not in ("nasional", "cuti", "kustom"):
        jenis = "kustom"
    db.execute(
        "INSERT INTO insentif_libur(tanggal, nama, jenis, aktif) VALUES(?,?,?,?) "
        "ON CONFLICT(tanggal) DO UPDATE SET nama = excluded.nama, "
        "jenis = excluded.jenis, aktif = excluded.aktif",
        (tanggal, nama.strip(), jenis, 1 if aktif else 0),
    )


def hapus_libur(tanggal: str) -> None:
    db.execute("DELETE FROM insentif_libur WHERE tanggal = ?", (tanggal,))


# --------------------------------------------------------------------------- #
# Periode bulanan + roster
# --------------------------------------------------------------------------- #
def daftar_periode() -> list[dict[str, Any]]:
    daftar = db.rows_to_dicts(db.query_all(
        "SELECT * FROM insentif_periode ORDER BY tahun DESC, bulan DESC"))
    for item in daftar:
        hitung = db.rows_to_dicts(db.query_all(
            "SELECT dokumen, COUNT(*) AS jumlah FROM insentif_roster "
            "WHERE periode_id = ? GROUP BY dokumen", (item["id"],)))
        item["jumlah"] = {baris["dokumen"]: baris["jumlah"] for baris in hitung}
    return daftar


def get_periode(periode_id: int) -> dict[str, Any] | None:
    return db.row_to_dict(db.query_one(
        "SELECT * FROM insentif_periode WHERE id = ?", (periode_id,)))


def get_periode_bulan(tahun: int, bulan: int) -> dict[str, Any] | None:
    return db.row_to_dict(db.query_one(
        "SELECT * FROM insentif_periode WHERE tahun = ? AND bulan = ?",
        (tahun, bulan)))


def _kepala_sekolah() -> dict[str, Any] | None:
    return db.row_to_dict(db.query_one(
        "SELECT * FROM gtk_pegawai WHERE jenis_ptk = 'Kepala Sekolah' "
        "ORDER BY id LIMIT 1"))


def _ttd_awal(pengaturan: Mapping[str, Any]) -> dict[str, str]:
    ks = _kepala_sekolah()
    if ks is not None:
        profil = profil_untuk_gtk(int(ks["id"]))
        ks_nama = (profil.get("nama_tampil") or ks.get("nama") or "").strip()
        ks_nip = str(ks.get("nip") or "").strip()
    else:
        ks_nama = str(pengaturan.get("ks_nama") or "").strip()
        ks_nip = str(pengaturan.get("ks_nip") or "").strip()
    bendahara_nama = bendahara_nip = ""
    try:
        bid = int(str(pengaturan.get("bendahara_gtk_id") or "").strip() or 0)
    except ValueError:
        bid = 0
    if bid:
        orang = db.row_to_dict(db.query_one(
            "SELECT * FROM gtk_pegawai WHERE id = ?", (bid,)))
        if orang is not None:
            profil = profil_untuk_gtk(int(orang["id"]))
            bendahara_nama = (profil.get("nama_tampil") or orang.get("nama") or "").strip()
            bendahara_nip = str(orang.get("nip") or "").strip()
    return {"ks_nama": ks_nama, "ks_nip": ks_nip,
            "bendahara_nama": bendahara_nama, "bendahara_nip": bendahara_nip,
            "pengawas_nama": str(pengaturan.get("pengawas_nama") or "").strip(),
            "pengawas_nip": str(pengaturan.get("pengawas_nip") or "").strip()}


def buat_periode(tahun: int, bulan: int, *, salin_dari: int | None = None,
                actor: str | None = None) -> int:
    """Buat draf periode; roster disalin dari bulan lain atau dibangun dari GTK."""
    if not 1 <= bulan <= 12:
        raise ValueError("Bulan harus 1–12.")
    if get_periode_bulan(tahun, bulan) is not None:
        raise ValueError(f"Periode {NAMA_BULAN_KECIL[bulan]} {tahun} sudah ada.")
    import json

    merah = tanggal_merah(tahun, bulan, tambahan_libur())
    libur_json = json.dumps({str(tgl): nama for tgl, nama in sorted(merah.items())},
                            ensure_ascii=False)
    pengaturan = baca_pengaturan()
    ttd_json = json.dumps(_ttd_awal(pengaturan), ensure_ascii=False)
    akhir = tanggal_terakhir(tahun, bulan)
    periode_id = db.insert_returning_id(
        """
        INSERT INTO insentif_periode(tahun, bulan, libur_json, ttd_json,
            tgl_absensi, tgl_spj, actor)
        VALUES(?,?,?,?,?,?,?)
        """,
        (tahun, bulan, libur_json, ttd_json, akhir, akhir, actor),
    )
    if salin_dari:
        asal = get_periode(salin_dari)
        if asal is None:
            raise ValueError("Periode asal tidak ditemukan.")
        for baris in roster_periode(salin_dari):
            tambah_roster(periode_id, baris["dokumen"], dict(baris))
    else:
        for dokumen, _label in DOKUMEN:
            for calon in calon_roster(dokumen, pengaturan):
                tambah_roster(periode_id, dokumen, calon)
    return periode_id


def hapus_periode(periode_id: int) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM insentif_roster WHERE periode_id = ?", (periode_id,))
        conn.execute("DELETE FROM insentif_periode WHERE id = ?", (periode_id,))


def simpan_ttd(periode_id: int, nilai: Mapping[str, Any]) -> None:
    import json

    kini = get_periode(periode_id)
    if kini is None:
        raise ValueError("Periode tidak ditemukan.")
    try:
        ttd = json.loads(kini.get("ttd_json") or "{}")
    except ValueError:
        ttd = {}
    for kunci in ("ks_nama", "ks_nip", "bendahara_nama", "bendahara_nip",
                  "pengawas_nama", "pengawas_nip"):
        if kunci in nilai:
            ttd[kunci] = str(nilai[kunci] or "").strip()
    try:
        akhir = tanggal_terakhir(int(kini["tahun"]), int(kini["bulan"]))
        tgl_absensi = min(max(1, int(nilai.get("tgl_absensi", akhir))), akhir)
        tgl_spj = min(max(1, int(nilai.get("tgl_spj", akhir))), akhir)
    except (ValueError, TypeError):
        tgl_absensi = tgl_spj = tanggal_terakhir(int(kini["tahun"]), int(kini["bulan"]))
    db.execute(
        "UPDATE insentif_periode SET ttd_json = ?, tgl_absensi = ?, tgl_spj = ?, "
        "catatan = ?, diubah = datetime('now','localtime') WHERE id = ?",
        (json.dumps(ttd, ensure_ascii=False), tgl_absensi, tgl_spj,
         str(nilai.get("catatan") or "").strip() or None, periode_id),
    )


def baca_ttd(periode: Mapping[str, Any]) -> dict[str, str]:
    import json

    try:
        ttd = json.loads(periode.get("ttd_json") or "{}")
    except ValueError:
        ttd = {}
    hasil = {"ks_nama": "", "ks_nip": "", "bendahara_nama": "", "bendahara_nip": "",
             "pengawas_nama": "", "pengawas_nip": ""}
    hasil.update({kunci: str(nilai or "") for kunci, nilai in ttd.items()
                  if kunci in hasil})
    return hasil


def baca_libur_periode(periode: Mapping[str, Any]) -> dict[int, str]:
    """Tanggal merah tersimpan (hasil jepretan saat periode dibuat)."""
    import json

    try:
        mentah = json.loads(periode.get("libur_json") or "{}")
    except ValueError:
        mentah = {}
    hasil: dict[int, str] = {}
    for kunci, nama in mentah.items():
        try:
            hasil[int(kunci)] = str(nama)
        except (ValueError, TypeError):
            continue
    return hasil


# --------------------------------------------------------------------------- #
# Calon roster dari GTK
# --------------------------------------------------------------------------- #
def _jabatan_spj(orang: Mapping[str, Any], profil: Mapping[str, Any]) -> str:
    if profil.get("jabatan"):
        return str(profil["jabatan"]).strip()
    if str(orang.get("jenis_ptk") or "") == "Kepala Sekolah":
        return "Kepala Sekolah"
    if "wakil" in str(orang.get("tugas_tambahan") or "").lower():
        return "Wakil Kepala Sekolah"
    if str(orang.get("jenis_ptk") or "") == "Guru":
        return "Guru"
    return "Tenaga Kependidikan"


def _nama_tampil(orang: Mapping[str, Any], profil: Mapping[str, Any]) -> str:
    if profil.get("nama_tampil"):
        return str(profil["nama_tampil"]).strip()
    return str(orang.get("nama") or "").strip()


def _baris_calon(orang: Mapping[str, Any], pengaturan: Mapping[str, Any]) -> dict[str, Any]:
    profil = profil_untuk_gtk(int(orang["id"]))
    jabatan = _jabatan_spj(orang, profil)
    tarif = tarif_untuk(jabatan, pengaturan, profil.get("tarif_override"))
    persen = persen_pph(orang.get("nip"), orang.get("pangkat_golongan"), pengaturan)
    return {"gtk_id": orang["id"], "nama_tampil": _nama_tampil(orang, profil),
            "nip": str(orang.get("nip") or "").strip(),
            "npwp": str(orang.get("npwp") or "").strip(),
            "rekening": str(orang.get("rekening") or "").strip(),
            "nik": str(orang.get("nik") or "").strip(),
            "gol": str(orang.get("pangkat_golongan") or "").strip(),
            "pangkat": teks_pangkat(orang.get("pangkat_golongan")),
            "jabatan": jabatan, "tarif": tarif, "pph_persen": persen,
            "pph_nominal": tarif * persen // 100}


def _semua_pegawai() -> list[dict[str, Any]]:
    return db.rows_to_dicts(db.query_all("SELECT * FROM gtk_pegawai"))


def calon_roster(dokumen: str,
                pengaturan: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Daftar awal dokumen dari GTK (boleh diubah per periode).

    * PNS  : guru + Kepala Sekolah berstatus PNS;
    * PPPK : guru berstatus PPPK;
    * SPJ  : guru + Kepala Sekolah semua status + Tenaga Honor Sekolah.
    """
    pengaturan = pengaturan or baca_pengaturan()
    pegawai = _semua_pegawai()
    if dokumen == "pns":
        saring = [orang for orang in pegawai
                  if str(orang.get("status_kepegawaian") or "") == "PNS"
                  and str(orang.get("jenis_ptk") or "") in ("Guru", "Kepala Sekolah")]
        saring.sort(key=lambda o: (0 if o.get("jenis_ptk") == "Kepala Sekolah" else 1,
                                   -_peringkat_gol(o.get("pangkat_golongan")),
                                   str(o.get("nama") or "")))
    elif dokumen == "pppk":
        saring = [orang for orang in pegawai
                  if str(orang.get("status_kepegawaian") or "") == "PPPK"
                  and str(orang.get("jenis_ptk") or "") == "Guru"]

        def _kunci_pppk(o: Mapping[str, Any]) -> tuple:
            ikut = profil_untuk_gtk(int(o["id"])).get("ikut_pppk")
            return (0 if ikut else 1, str(o.get("nama") or ""))

        saring.sort(key=_kunci_pppk)
    elif dokumen == "spj":
        saring = [orang for orang in pegawai
                  if str(orang.get("jenis_ptk") or "") in ("Guru", "Kepala Sekolah")
                  or str(orang.get("status_kepegawaian") or "") == "Tenaga Honor Sekolah"]

        def _kunci_spj(o: Mapping[str, Any]) -> tuple:
            profil = profil_untuk_gtk(int(o["id"]))
            jabatan = _jabatan_spj(o, profil).lower()
            if "kepala sekolah" in jabatan and "wakil" not in jabatan:
                kelompok = 0
            elif "wakil" in jabatan:
                kelompok = 1
            elif "guru" in jabatan:
                kelompok = 2
            else:
                kelompok = 3
            pns = 0 if str(o.get("status_kepegawaian") or "") == "PNS" else 1
            return (kelompok, pns, -_peringkat_gol(o.get("pangkat_golongan")),
                    str(o.get("nama") or ""))

        saring.sort(key=_kunci_spj)
    else:
        raise ValueError(f"Dokumen «{dokumen}» tidak dikenal.")
    hasil = [_baris_calon(orang, pengaturan) for orang in saring]
    # Tandai keikutsertaan bawaan dari profil (1 = ikut, 0 = tidak).
    kunci_ikut = {"pns": "ikut_pns", "pppk": "ikut_pppk", "spj": "ikut_spj"}[dokumen]
    ditandai = [baris for baris in hasil
                if profil_untuk_gtk(int(baris["gtk_id"])).get(kunci_ikut)]
    return ditandai or hasil


def roster_periode(periode_id: int, dokumen: str = "") -> list[dict[str, Any]]:
    if dokumen:
        return db.rows_to_dicts(db.query_all(
            "SELECT * FROM insentif_roster WHERE periode_id = ? AND dokumen = ? "
            "ORDER BY urutan, id", (periode_id, dokumen)))
    return db.rows_to_dicts(db.query_all(
        "SELECT * FROM insentif_roster WHERE periode_id = ? "
        "ORDER BY dokumen, urutan, id", (periode_id,)))


def tambah_roster(periode_id: int, dokumen: str, nilai: Mapping[str, Any]) -> int:
    if dokumen not in ("pns", "pppk", "spj"):
        raise ValueError(f"Dokumen «{dokumen}» tidak dikenal.")
    hitung = db.query_value(
        "SELECT COUNT(*) FROM insentif_roster WHERE periode_id = ? AND dokumen = ?",
        (periode_id, dokumen), default=0) or 0
    return db.insert_returning_id(
        """
        INSERT INTO insentif_roster(periode_id, dokumen, gtk_id, nama_tampil, nip,
            npwp, rekening, nik, gol, pangkat, jabatan, tarif, pph_persen,
            pph_nominal, urutan)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (periode_id, dokumen, nilai.get("gtk_id"), str(nilai.get("nama_tampil") or ""),
         str(nilai.get("nip") or ""), str(nilai.get("npwp") or ""),
         str(nilai.get("rekening") or ""), str(nilai.get("nik") or ""),
         str(nilai.get("gol") or ""), str(nilai.get("pangkat") or ""),
         str(nilai.get("jabatan") or "Guru"),
         _angka_atau_none(nilai.get("tarif")) or 0,
         _angka_atau_none(nilai.get("pph_persen")) or 0,
         _angka_atau_none(nilai.get("pph_nominal")) or 0,
         int(nilai.get("urutan") or 0) or int(hitung) + 1),
    )


def tambah_dari_gtk(periode_id: int, dokumen: str, gtk_id: int) -> int:
    orang = db.row_to_dict(db.query_one(
        "SELECT * FROM gtk_pegawai WHERE id = ?", (gtk_id,)))
    if orang is None:
        raise ValueError("Pegawai tidak ditemukan.")
    return tambah_roster(periode_id, dokumen, _baris_calon(orang, baca_pengaturan()))


def ubah_roster(baris_id: int, nilai: Mapping[str, Any]) -> None:
    kini = db.row_to_dict(db.query_one(
        "SELECT * FROM insentif_roster WHERE id = ?", (baris_id,)))
    if kini is None:
        raise ValueError("Baris roster tidak ditemukan.")
    tarif = _angka_atau_none(nilai.get("tarif"))
    if tarif is None:
        tarif = int(kini.get("tarif") or 0)
    persen = _angka_atau_none(nilai.get("pph_persen"))
    if persen is None:
        persen = persen_pph(nilai.get("nip", kini.get("nip")),
                            nilai.get("gol", kini.get("gol")), baca_pengaturan())
    gol = str(nilai.get("gol", kini.get("gol") or "")).strip()
    pangkat = str(nilai.get("pangkat", "") or "").strip() or teks_pangkat(gol)
    db.execute(
        """
        UPDATE insentif_roster
           SET nama_tampil = ?, nip = ?, npwp = ?, rekening = ?, nik = ?,
               gol = ?, pangkat = ?, jabatan = ?, tarif = ?, pph_persen = ?,
               pph_nominal = ?
         WHERE id = ?
        """,
        (str(nilai.get("nama_tampil", kini.get("nama_tampil") or "")).strip(),
         str(nilai.get("nip", kini.get("nip") or "")).strip(),
         str(nilai.get("npwp", kini.get("npwp") or "")).strip(),
         str(nilai.get("rekening", kini.get("rekening") or "")).strip(),
         str(nilai.get("nik", kini.get("nik") or "")).strip(),
         gol, pangkat, str(nilai.get("jabatan", kini.get("jabatan") or "Guru")).strip(),
         tarif, persen, tarif * persen // 100, baris_id),
    )


def hapus_roster(baris_id: int) -> None:
    db.execute("DELETE FROM insentif_roster WHERE id = ?", (baris_id,))


def geser_roster(baris_id: int, arah: int) -> None:
    """Tukar urutan dengan tetangga (arah -1 naik, +1 turun)."""
    kini = db.row_to_dict(db.query_one(
        "SELECT * FROM insentif_roster WHERE id = ?", (baris_id,)))
    if kini is None:
        return
    baris = roster_periode(int(kini["periode_id"]), str(kini["dokumen"]))
    posisi = [item["id"] for item in baris].index(baris_id)
    tujuan = posisi + (1 if arah > 0 else -1)
    if not 0 <= tujuan < len(baris):
        return
    with db.transaction() as conn:
        conn.execute("UPDATE insentif_roster SET urutan = ? WHERE id = ?",
                     (tujuan + 1, baris_id))
        conn.execute("UPDATE insentif_roster SET urutan = ? WHERE id = ?",
                     (posisi + 1, baris[tujuan]["id"]))


def luar_roster(periode_id: int, dokumen: str) -> list[dict[str, Any]]:
    """Pegawai GTK yang belum masuk roster dokumen ini (untuk ditambahkan)."""
    return db.rows_to_dicts(db.query_all(
        """
        SELECT * FROM gtk_pegawai
         WHERE id NOT IN (SELECT gtk_id FROM insentif_roster
                           WHERE periode_id = ? AND dokumen = ? AND gtk_id IS NOT NULL)
         ORDER BY nama COLLATE NOCASE
        """, (periode_id, dokumen)))


def ringkas_spj(roster: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    total = sum(int(item.get("tarif") or 0) for item in roster)
    pph = sum(int(item.get("pph_nominal") or 0) for item in roster)
    return {"jumlah_orang": len(roster), "total": total, "pph": pph,
            "terima": total - pph}


def jadikan_bawaan(baris_id: int) -> None:
    """Salin nama & jabatan baris roster menjadi profil bawaan pegawai."""
    kini = db.row_to_dict(db.query_one(
        "SELECT * FROM insentif_roster WHERE id = ?", (baris_id,)))
    if kini is None or not kini.get("gtk_id"):
        raise ValueError("Baris roster tidak tertaut ke pegawai GTK.")
    db.execute(
        "UPDATE insentif_profil SET nama_tampil = ?, jabatan = ?, "
        "diubah = datetime('now','localtime') WHERE gtk_id = ?",
        (str(kini.get("nama_tampil") or "").strip() or None,
         str(kini.get("jabatan") or "").strip() or None, kini.get("gtk_id")),
    )


def hitung_periode() -> int:
    return int(db.query_value("SELECT COUNT(*) FROM insentif_periode", default=0) or 0)
