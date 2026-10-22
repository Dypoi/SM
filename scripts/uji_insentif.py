#!/usr/bin/env python3
"""Uji menyeluruh menu **Insentif** — SPJ + absensi PNS/PPPK otomatis.

Yang dibuktikan:

1. tanggal merah mengikuti kalender bawaan (libur nasional + cuti bersama),
   Senin–Jumat saja, cocok dengan berkas absensi 2025 milik sekolah;
2. grid HARI/TANGGAL dua lajur selaras weekday (Senin di kolom 0/5/10);
3. tarif, PPh, teks pangkat, dan format NIP/NPWP/rupiah benar;
4. daftar awal tiap dokumen tersusun tepat dari GTK (termasuk urutannya);
5. draf periode: buat, salin, ubah roster, geser, jepretan libur & tanda
   tangan, hapus;
6. libur manual menimpa bawaan tanpa mengubah draf yang sudah ada;
7. PDF absensi/SPJ/gabungan sah (Legal landscape, multi-halaman,
   tanggal merah, total SPJ);
8. alur HTTP lengkap dari login sampai unduh PDF.

Jalankan::

    .venv/bin/python scripts/uji_insentif.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AKAR))

# --- Database sementara: HARUS diatur sebelum mengimpor modul app ---
_SEMENTARA = Path(tempfile.mkdtemp(prefix="sm-uji-insentif-"))
os.environ["SM_DATA_DIR"] = str(_SEMENTARA / "data")
os.environ["SM_DB_PATH"] = str(_SEMENTARA / "uji.sqlite3")
os.environ["SM_AUTO_SEED"] = "0"

from app import db, insentif, insentif_pdf, migrations  # noqa: E402

migrations.init_database()

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
# 1. Tanggal merah
# --------------------------------------------------------------------------- #
skenario("1. Tanggal merah kalender bawaan")

jan25 = insentif.tanggal_merah(2025, 1)
cek("Jan 2025 = 1, 27, 28, 29", set(jan25) == {1, 27, 28, 29}, str(sorted(jan25)))
cek("ket 1 Jan", jan25.get(1) == "Tahun Baru Masehi 2025", repr(jan25.get(1)))
cek("ket 28 Jan cuti", "Cuti Bersama" in (jan25.get(28) or ""), repr(jan25.get(28)))

mar25 = insentif.tanggal_merah(2025, 3)
cek("Mar 2025 memuat cuti Nyepi 28", 28 in mar25, str(sorted(mar25)))
cek("Nyepi Sabtu 29 tak merah", 29 not in mar25)
cek("Idul Fitri 31 merah", 31 in mar25)

apr25 = insentif.tanggal_merah(2025, 4)
cek("Apr 2025 = 1,2,3,4,7,18", set(apr25) == {1, 2, 3, 4, 7, 18}, str(sorted(apr25)))
cek("Paskah Minggu 20 tak merah", 20 not in apr25)

mar26 = insentif.tanggal_merah(2026, 3)
cek("Mar 2026 = 18,19,20,23,24 (Idul Fitri di akhir pekan)",
    set(mar26) == {18, 19, 20, 23, 24}, str(sorted(mar26)))

feb26 = insentif.tanggal_merah(2026, 2)
cek("Feb 2026 = 16, 17 (Imlek + cuti)", set(feb26) == {16, 17}, str(sorted(feb26)))

agu25 = insentif.tanggal_merah(2025, 8)
cek("17 Agu 2025 (Minggu) tak merah", 17 not in agu25)
cek("cuti tambahan 18 Agu 2025 merah", 18 in agu25, str(sorted(agu25)))

des26 = insentif.tanggal_merah(2026, 12)
cek("Des 2026 = 24, 25", set(des26) == {24, 25}, str(sorted(des26)))

# Timpaan: tambah + nonaktif
timpa = insentif.tanggal_merah(2026, 5, {"2026-05-02": ("Libur sekolah", "kustom"),
                                        "2026-05-01": None})
cek("libur Sabtu tak merah walau ditambah", 2 not in timpa)
cek("1 Mei bisa dinonaktifkan", 1 not in timpa and 14 in timpa)

# --------------------------------------------------------------------------- #
# 2. Grid absensi
# --------------------------------------------------------------------------- #
skenario("2. Grid HARI/TANGGAL dua lajur")

grid = insentif.grid_absensi(2025, 1, jan25)
b1 = [s["tgl"] if s else None for s in grid["band1"]]
b2 = [s["tgl"] if s else None for s in grid["band2"]]
cek("band1 Jan 2025: kosong,kosong,1,2,3,6..",
    b1 == [None, None, 1, 2, 3, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17], str(b1))
cek("band2 Jan 2025: 20..24,27..31 + kosong",
    b2 == [20, 21, 22, 23, 24, 27, 28, 29, 30, 31, None, None, None, None, None],
    str(b2))
cek("1 Jan ditandai libur", grid["band1"][2]["libur"] == "Tahun Baru Masehi 2025")
cek("6 Jan bukan libur", grid["band1"][5]["libur"] is None)

feb = insentif.grid_absensi(2025, 2, insentif.tanggal_merah(2025, 2))
f1 = [s["tgl"] if s else None for s in feb["band1"]]
cek("band1 Feb 2025: 5 kosong + 3..14",
    f1 == [None] * 5 + [3, 4, 5, 6, 7, 10, 11, 12, 13, 14], str(f1))

# Keselarasan weekday untuk 24 bulan acak: kolom 0/5/10 = Senin.
import datetime as _dt
selaras = True
for th, bl in [(2024, 2), (2024, 12), (2025, 6), (2025, 11), (2026, 3),
               (2026, 8), (2027, 2), (2027, 5)]:
    g = insentif.grid_absensi(th, bl, {})
    for lajur in ("band1", "band2"):
        for i, sel in enumerate(g[lajur]):
            if sel is not None and _dt.date(th, bl, sel["tgl"]).weekday() != i % 5:
                selaras = False
cek("8 bulan acak selaras weekday", selaras)
cek("akhir Feb 2024 kabisat = 29", insentif.tanggal_terakhir(2024, 2) == 29)
cek("akhir Feb 2025 = 28", insentif.tanggal_terakhir(2025, 2) == 28)

# --------------------------------------------------------------------------- #
# 3. Tarif, PPh, pangkat, format
# --------------------------------------------------------------------------- #
skenario("3. Tarif, PPh, pangkat & format tampilan")

atur = insentif.baca_pengaturan()
cek("tarif KS 7jt", insentif.tarif_untuk("Kepala Sekolah", atur) == 7_000_000)
cek("tarif Waka 2,7jt", insentif.tarif_untuk("Wakil Kepala Sekolah", atur) == 2_700_000)
cek("tarif Guru 1,35jt", insentif.tarif_untuk("Guru", atur) == 1_350_000)
cek("tarif Tendik 650rb", insentif.tarif_untuk("Tenaga Kependidikan", atur) == 650_000)
cek("tarif Pelatih 650rb", insentif.tarif_untuk("Pelatih", atur) == 650_000)
cek("override menang", insentif.tarif_untuk("Guru", atur, 2_700_000) == 2_700_000)
cek("override etalase titik", insentif.tarif_untuk("Guru", atur, "2.700.000") == 2_700_000)

cek("PPh Guru III = 67.500",
    insentif.nominal_pph("Guru", "197503312006042004", "III/d", atur) == 67_500)
cek("PPh Guru IX = 67.500",
    insentif.nominal_pph("Guru", "197201292024212001", "IX", atur) == 67_500)
cek("PPh Guru IV = 202.500",
    insentif.nominal_pph("Guru", "196505161990032006", "IV/b", atur) == 202_500)
cek("PPh Waka III = 135.000",
    insentif.nominal_pph("Wakil Kepala Sekolah", "197503312006042004", "III/d", atur)
    == 135_000)
cek("PPh Waka IV = 405.000",
    insentif.nominal_pph("Wakil Kepala Sekolah", "196505161990032006", "IV/b", atur)
    == 405_000)
cek("PPh KS III = 350.000",
    insentif.nominal_pph("Kepala Sekolah", "197503312006042004", "III/d", atur)
    == 350_000)
cek("PPh KS IV = 1.050.000",
    insentif.nominal_pph("Kepala Sekolah", "197405202005011007", "IV/a", atur)
    == 1_050_000)
cek("PPh tanpa NIP = 0", insentif.nominal_pph("Guru", "", "IX", atur) == 0)
cek("PPh Tendik IV ikut Guru = 202.500",
    insentif.nominal_pph("Tenaga Kependidikan", "197410102022211001", "IV/a", atur)
    == 202_500)
cek("PPh Pelatih IX ikut Guru = 67.500",
    insentif.nominal_pph("Pelatih", "197410102022211001", "IX", atur) == 67_500)
cek("PPh jabatan asing ikut Guru",
    insentif.nominal_pph("Instruktur", "197410102022211001", "IV/a", atur) == 202_500)
cek("kelas jabatan", insentif.kelas_jabatan("Kepala Sekolah") == "ks"
    and insentif.kelas_jabatan("Wakil Kepala Sekolah Humas") == "waka"
    and insentif.kelas_jabatan("Guru") == "guru"
    and insentif.kelas_jabatan("Tenaga Kependidikan") == "guru"
    and insentif.kelas_jabatan("") == "guru")
cek("kelas golongan", insentif.kelas_golongan("IV/a") == "4"
    and insentif.kelas_golongan("III/d") == "3"
    and insentif.kelas_golongan("IX") == "3"
    and insentif.kelas_golongan("") == "3")
cek("persen turunan 202.500/1.350.000 = 15",
    insentif.persen_turunan(202_500, 1_350_000) == 15)
cek("persen turunan tarif 0 = 0", insentif.persen_turunan(100, 0) == 0)

cek("pangkat IV/b", insentif.teks_pangkat("IV/b") == "Pembina TK.I - IV/b")
cek("pangkat IX", insentif.teks_pangkat("IX") == "Ahli Pertama - IX")
cek("pangkat III/d", insentif.teks_pangkat("III/d") == "Penata TK.I - III/d")
cek("pangkat asing apa adanya", insentif.teks_pangkat("VII") == "VII")
cek("pangkat kosong", insentif.teks_pangkat("") == "")

cek("NIP spasi", insentif.format_nip_spasi("197405202005011007") == "19740520 200501 1 007")
cek("NIP pendek apa adanya", insentif.format_nip_spasi("123") == "123")
cek("NPWP 15", insentif.format_npwp("498340462451000") == "49.834.046.2-451.000")
cek("NPWP 16", insentif.format_npwp("3671016303750002") == "3671 0163 0375 0002")
cek("rupiah", insentif.rupiah(68350000) == "68.350.000")

# --------------------------------------------------------------------------- #
# 4. Daftar awal dari GTK
# --------------------------------------------------------------------------- #
skenario("4. Calon roster dari GTK")


def _isi_gtk() -> None:
    orang = [
        ("MUHAMMAD", "Kepala Sekolah", "PNS", "197405202005011007", "IV/a", ""),
        ("ARY SETYOWATI", "Guru", "PNS", "197503312006042004", "III/d",
         "Wakil Kepala Sekolah Humas"),
        ("NURBIANTI", "Guru", "PNS", "196505161990032006", "IV/b", ""),
        ("AHMAD BAIJURI", "Guru", "PNS", "197510132009121002", "III/b", ""),
        ("R.TRI PUJI ASTUTI", "Guru", "PPPK", "197201292024212001", "IX", ""),
        ("WIDA SYAIDATUL WAFA", "Guru", "PPPK", "197905102022212002", "IX", ""),
        ("ULFA RAHMAH", "Tenaga Kependidikan", "Tenaga Honor Sekolah", "", "", ""),
        ("ADEN SUDRAJAT", "Tenaga Kependidikan", "PPPK", "197410102022211001", "IX", ""),
    ]
    with db.transaction() as conn:
        for i, o in enumerate(orang):
            conn.execute(
                "INSERT INTO gtk_pegawai(kunci, nama, jenis_ptk, status_kepegawaian,"
                " nip, pangkat_golongan, tugas_tambahan,"
                " npwp, rekening, nik) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f"gtk{i}", o[0], o[1], o[2], o[3], o[4], o[5],
                 "498340462451000", "0009567000111", "3671010101700001"))


_isi_gtk()

pns = insentif.calon_roster("pns")
cek("PNS = 4 (KS + 3 guru)", len(pns) == 4, str(len(pns)))
cek("PNS diawali KS", pns[0]["nama_tampil"] == "MUHAMMAD")
cek("PNS urut gol: IV/b dulu",
    [c["nama_tampil"] for c in pns] == ["MUHAMMAD", "NURBIANTI", "ARY SETYOWATI",
                                       "AHMAD BAIJURI"],
    str([c["nama_tampil"] for c in pns]))

pppk = insentif.calon_roster("pppk")
cek("PPPK = 2 guru (TU dikecualikan)",
    sorted(c["nama_tampil"] for c in pppk) == ["R.TRI PUJI ASTUTI", "WIDA SYAIDATUL WAFA"])

spj = insentif.calon_roster("spj")
cek("SPJ = 7 (guru+KS+honor; TU PPPK tidak)",
    len(spj) == 7, str([c["nama_tampil"] for c in spj]))
cek("SPJ urut KS, Waka, Guru, honor",
    [c["nama_tampil"] for c in spj] == ["MUHAMMAD", "ARY SETYOWATI", "NURBIANTI",
                                       "AHMAD BAIJURI", "R.TRI PUJI ASTUTI",
                                       "WIDA SYAIDATUL WAFA", "ULFA RAHMAH"],
    str([c["nama_tampil"] for c in spj]))
cek("SPJ honor: tarif 650rb PPh 0",
    spj[-1]["tarif"] == 650_000 and spj[-1]["pph_nominal"] == 0)
cek("SPJ NURBIANTI: Guru IV PPh 202.500",
    [c for c in spj if c["nama_tampil"] == "NURBIANTI"][0]["pph_nominal"] == 202_500)
cek("SPJ ARY: Waka III PPh 135.000",
    [c for c in spj if c["nama_tampil"] == "ARY SETYOWATI"][0]["pph_nominal"]
    == 135_000)
cek("SPJ KS: PPh 1.050.000", spj[0]["pph_nominal"] == 1_050_000)

info_ks = insentif.info_insentif_pegawai(1)
cek("info GTK KS: jabatan + tarif 7jt + PPh 1.050.000",
    info_ks["jabatan"] == "Kepala Sekolah" and info_ks["tarif"] == 7_000_000
    and info_ks["pph"] == 1_050_000 and not info_ks["manual"])
cek("jabatan efektif otomatis dari tugas tambahan",
    insentif.jabatan_efektif(
        {"jenis_ptk": "Guru", "tugas_tambahan": "Wakil Kepala Sekolah Kesiswaan"})
    == ("Wakil Kepala Sekolah", False))
cek("jabatan manual menang atas otomatis",
    insentif.jabatan_efektif({"jenis_ptk": "Guru"}, "Pelatih") == ("Pelatih", True))
cek("belum ada jabatan manual", insentif.daftar_jabatan_set() == {})

# --------------------------------------------------------------------------- #
# 5. Draf periode
# --------------------------------------------------------------------------- #
skenario("5. Draf periode: buat, salin, ubah, geser, hapus")

pid = insentif.buat_periode(2026, 3, actor="uji")
cek("periode terbentuk", pid > 0)
cek("roster SPJ tersalin 7", len(insentif.roster_periode(pid, "spj")) == 7)
cek("roster PNS 4", len(insentif.roster_periode(pid, "pns")) == 4)
cek("roster PPPK 2", len(insentif.roster_periode(pid, "pppk")) == 2)
per = insentif.get_periode(pid)
cek("jepretan libur Mar 2026",
    insentif.baca_libur_periode(per) == {18: "Cuti Bersama Hari Suci Nyepi",
                                         19: "Hari Suci Nyepi 1948",
                                         20: "Cuti Bersama Idul Fitri 1447 H",
                                         23: "Cuti Bersama Idul Fitri 1447 H",
                                         24: "Cuti Bersama Idul Fitri 1447 H"},
    str(insentif.baca_libur_periode(per)))
cek("tgl TTD = 31", per["tgl_absensi"] == 31 and per["tgl_spj"] == 31)
ttd = insentif.baca_ttd(per)
cek("TTD KS dari GTK", ttd["ks_nama"] == "MUHAMMAD"
    and ttd["ks_nip"] == "197405202005011007", str(ttd))

try:
    insentif.buat_periode(2026, 3)
    cek("periode ganda ditolak", False)
except ValueError:
    cek("periode ganda ditolak", True)

# Ubah + geser + hapus + tambah
baris = insentif.roster_periode(pid, "spj")
id_pertama = baris[0]["id"]
insentif.ubah_roster(id_pertama, {"nama_tampil": "Muhammad, S.Pd., M.Pd",
                                 "tarif": "7000000"})
cek("ubah nama tampil",
    db.query_value("SELECT nama_tampil FROM insentif_roster WHERE id = ?",
                   (id_pertama,)) == "Muhammad, S.Pd., M.Pd")
insentif.geser_roster(baris[1]["id"], -1)
cek("geser naik menukar urutan",
    insentif.roster_periode(pid, "spj")[0]["id"] == baris[1]["id"])
insentif.geser_roster(baris[1]["id"], +1)
cek("geser turun mengembalikan",
    insentif.roster_periode(pid, "spj")[0]["id"] == id_pertama)
insentif.jadikan_bawaan(id_pertama)
cek("jadikan bawaan tersimpan di profil",
    db.query_value("SELECT nama_tampil FROM insentif_profil WHERE gtk_id = 1")
    == "Muhammad, S.Pd., M.Pd")
id_baijuri = [r for r in baris if r["nama_tampil"] == "AHMAD BAIJURI"][0]["id"]
cek("Baijuri Guru III = 67.500",
    db.query_value("SELECT pph_nominal FROM insentif_roster WHERE id = ?",
                   (id_baijuri,)) == 67_500)
insentif.ubah_roster(id_baijuri, {"tarif": "2000000"})
cek("tarif dioverride → PPh tetap 67.500",
    db.query_value("SELECT pph_nominal FROM insentif_roster WHERE id = ?",
                   (id_baijuri,)) == 67_500)
insentif.ubah_roster(id_baijuri, {"pph_nominal": "100000"})
cek("override PPh per baris",
    db.query_value("SELECT pph_nominal FROM insentif_roster WHERE id = ?",
                   (id_baijuri,)) == 100_000)
insentif.ubah_roster(id_baijuri, {"tarif": "1350000", "pph_nominal": ""})
cek("PPh kosong → kembali otomatis 67.500",
    db.query_value("SELECT pph_nominal FROM insentif_roster WHERE id = ?",
                   (id_baijuri,)) == 67_500)
id_baijuri_gtk = db.query_value(
    "SELECT id FROM gtk_pegawai WHERE nama = 'AHMAD BAIJURI'")
db.execute("UPDATE insentif_profil SET jabatan = 'Wakil Kepala Sekolah' "
           "WHERE gtk_id = ?", (id_baijuri_gtk,))
calon_baijuri = [c for c in insentif.calon_roster("spj")
                 if c["nama_tampil"] == "AHMAD BAIJURI"][0]
cek("jabatan manual dipakai calon baru",
    calon_baijuri["jabatan"] == "Wakil Kepala Sekolah"
    and calon_baijuri["pph_nominal"] == 135_000)
cek("draf lama tak ikut berubah (tetap Guru 67.500)",
    db.query_value("SELECT jabatan FROM insentif_roster WHERE id = ?",
                   (id_baijuri,)) == "Guru"
    and db.query_value("SELECT pph_nominal FROM insentif_roster WHERE id = ?",
                       (id_baijuri,)) == 67_500)
db.execute("UPDATE insentif_profil SET jabatan = NULL WHERE gtk_id = ?",
           (id_baijuri_gtk,))
insentif.hapus_roster(baris[-1]["id"])
cek("hapus baris → 6", len(insentif.roster_periode(pid, "spj")) == 6)
id_tu = db.query_value("SELECT id FROM gtk_pegawai WHERE nama = 'ADEN SUDRAJAT'")
insentif.tambah_dari_gtk(pid, "spj", id_tu)
cek("tambah TU manual → 7", len(insentif.roster_periode(pid, "spj")) == 7)
cek("luar roster berkurang", len(insentif.luar_roster(pid, "spj")) == 1)

# Salin + TTD + hapus
pid2 = insentif.buat_periode(2026, 4, salin_dari=pid)
cek("salin mewarisi 7 baris + urutan",
    [r["nama_tampil"] for r in insentif.roster_periode(pid2, "spj")]
    == [r["nama_tampil"] for r in insentif.roster_periode(pid, "spj")])
insentif.simpan_ttd(pid2, {"tgl_absensi": "99", "tgl_spj": "30",
                           "pengawas_nama": "Ta'ani, S.Pd., M.Si",
                           "pengawas_nip": "196903051995121004", "catatan": "uji"})
per2 = insentif.get_periode(pid2)
cek("tgl dijepit ke akhir bulan", per2["tgl_absensi"] == 30 and per2["tgl_spj"] == 30)
cek("pengawas tersimpan", insentif.baca_ttd(per2)["pengawas_nama"].startswith("Ta'ani"))
ringkas = insentif.ringkas_spj(insentif.roster_periode(pid2, "spj"))
cek("ringkas SPJ konsisten",
    ringkas["total"] - ringkas["pph"] == ringkas["terima"] and ringkas["jumlah_orang"] == 7)
insentif.hapus_periode(pid2)
cek("hapus periode + rosternya",
    insentif.get_periode(pid2) is None and not insentif.roster_periode(pid2))

# --------------------------------------------------------------------------- #
# 6. Libur manual
# --------------------------------------------------------------------------- #
skenario("6. Kalender libur manual")

insentif.simpan_libur("2026-05-02", "Libur sekolah", "kustom", True)
insentif.simpan_libur("2026-03-20", "", "cuti", False)
cek("tambah kustom", "2026-05-02" in insentif.baca_libur_manual())
cek("nonaktif bawaan", insentif.baca_libur_manual()["2026-03-20"]["aktif"] == 0)
cek("Mei 2026 tetap tanpa Sabtu",
    2 not in insentif.tanggal_merah(2026, 5, insentif.tambahan_libur()))
cek("20 Mar nonaktif untuk draf baru",
    20 not in insentif.tanggal_merah(2026, 3, insentif.tambahan_libur()))
cek("draf lama tak ikut berubah (tetap ada 20)",
    20 in insentif.baca_libur_periode(insentif.get_periode(pid)))
tahun26 = {d["tanggal"]: d for d in insentif.daftar_libur_tahun(2026)}
cek("daftar tahun memuat kustom", tahun26["2026-05-02"]["sumber"] == "manual")
cek("daftar tahun menandai nonaktif", tahun26["2026-03-20"]["aktif"] == 0)
insentif.hapus_libur("2026-03-20")
cek("hapus aturan → kembali merah",
    20 in insentif.tanggal_merah(2026, 3, insentif.tambahan_libur()))
insentif.hapus_libur("2026-05-02")

# --------------------------------------------------------------------------- #
# 7. PDF absensi & SPJ
# --------------------------------------------------------------------------- #
skenario("7. PDF siap cetak (Legal landscape, multi-halaman)")

per = insentif.get_periode(pid)
pdf_pns = insentif_pdf.pdf_absensi("pns", per, insentif.roster_periode(pid, "pns"))
cek("PDF diawali %PDF", pdf_pns.startswith(b"%PDF-1.4"))
cek("MediaBox Legal landscape", b"[0 0 1008 612]" in pdf_pns)
cek("judul absensi PNS", b"DAFTAR HADIR TENAGA PENDIDIK \\( PNS \\)" in pdf_pns)
cek("kepala NAMA/NIP tanpa spasi (persis berkas)",
    b"NAMA/NIP" in pdf_pns and b"NAMA / NIP" not in pdf_pns)
cek("kop 3 baris",
    b"PEMERINTAH KOTA TANGERANG" in pdf_pns
    and b"DINAS PENDIDIKAN" in pdf_pns
    and b"UPT SMP NEGERI 2 TANGERANG" in pdf_pns)
cek("logo kop tertanam (2 gambar)",
    b"/LogoPemda Do" in pdf_pns and b"/LogoSekolah Do" in pdf_pns
    and pdf_pns.count(b"/Subtype /Image") == 2)
cek("kolom identitas digabung setinggi kepala (5 kotak 70pt/halaman)",
    pdf_pns.count(b"70.00 re S") == 5 * pdf_pns.count(b"/Type /Page "))
cek("nama + NIP spasi", b"MUHAMMAD" in pdf_pns and b"19740520 200501 1 007" in pdf_pns)
cek("tanggal merah diisi", b"1 0 0 rg" in pdf_pns)
cek("keterangan libur", b"Cuti Bersama Hari Suci Nyepi" in pdf_pns)
cek("legenda S/I/C/DL", b"DINAS LUAR" in pdf_pns)
cek("akhiran EOF", pdf_pns.rstrip().endswith(b"%%EOF"))

pdf_pppk = insentif_pdf.pdf_absensi("pppk", per, insentif.roster_periode(pid, "pppk"))
cek("judul absensi PPPK", b"\\( PPPK \\)" in pdf_pppk)

pdf_spj = insentif_pdf.pdf_spj(per, insentif.roster_periode(pid, "spj"))
cek("judul SPJ", b"DAFTAR PENERIMA DANA INSENTIF" in pdf_spj)
cek("bulan + tahun anggaran", b"BULAN : MARET TAHUN ANGGARAN 2026" in pdf_spj)
cek("baris JUMLAH + total", b"JUMLAH" in pdf_spj)
total = insentif.ringkas_spj(insentif.roster_periode(pid, "spj"))["total"]
cek("total tercetak", insentif.rupiah(total).encode() in pdf_spj, insentif.rupiah(total))
cek("TTD zigzag", b"1." in pdf_spj and b"2." in pdf_spj)
cek("penandatangan", b"Bendahara Pengeluaran" in pdf_spj and b"Pengawas" in pdf_spj)
import re as _re
_kaki_ops: list[str] = []
insentif_pdf._kaki_spj(_kaki_ops, {"total": 0, "pph": 0, "terima": 0}, {}, 31, 3,
                       2026, "KOTA TANGERANG", 500.0)
_titi = _re.search(r"1 0 0 1 [\d.]+ ([\d.]+) Tm \(Tangerang", "\n".join(_kaki_ops))
cek("1 baris kosong sebelum titi mangsa (alas JUMLAH 478 → dasar 459)",
    _titi is not None and _titi.group(1) == "459.00",
    _titi.group(1) if _titi else "tak ketemu")

# Roster besar → multi-halaman dengan kepala berulang
with db.transaction() as conn:
    for i in range(30):
        conn.execute(
            "INSERT INTO gtk_pegawai(kunci, nama, jenis_ptk, status_kepegawaian,"
            " nip, pangkat_golongan) VALUES(?,?,?,?,?,?)",
            (f"bb{i}", f"GURU BESAR {i:02d}", "Guru", "PPPK",
             f"198001012022211{i:03d}"[:18], "IX"))
pid_besar = insentif.buat_periode(2026, 6)
besar = insentif_pdf.pdf_absensi(
    "pppk", insentif.get_periode(pid_besar),
    insentif.roster_periode(pid_besar, "pppk"))
cek("PPPK 32 orang → 4+ halaman",
    besar.count(b"HARI / TANGGAL") >= 4, f"kepala×{besar.count(b'HARI / TANGGAL')}")
cek("nomor urut lanjut halaman", b"32" in besar)
spj_besar = insentif_pdf.pdf_spj(
    insentif.get_periode(pid_besar), insentif.roster_periode(pid_besar, "spj"))
cek("SPJ besar multi-halaman", spj_besar.count(b"/Type /Page ") >= 2
    or spj_besar.count(b"STATUS") >= 2)
gabung = insentif_pdf.pdf_gabungan(insentif.get_periode(pid))
cek("gabungan memuat 3 dokumen",
    b"\\( PNS \\)" in gabung and b"\\( PPPK \\)" in gabung
    and b"DANA INSENTIF" in gabung)
cek("gabungan memuat logo kop",
    b"/LogoPemda Do" in gabung and b"/LogoSekolah Do" in gabung)

# --------------------------------------------------------------------------- #
# 8. Kebenaran vs berkas asli sekolah (Jan–Des 2025)
# --------------------------------------------------------------------------- #
skenario("8. Tanggal merah vs berkas absensi 2025 asli")


def _merah_berkas(path: str, lembar: str) -> set[int]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[lembar]
    hasil = set()
    for baris in (17, 19):
        for kolom in range(5, 20):
            sel = ws.cell(baris, kolom)
            try:
                rgb = sel.fill.start_color.rgb
            except Exception:
                rgb = ""
            if rgb == "FFFF0000" and isinstance(sel.value, (int, float)):
                hasil.add(int(sel.value))
    return hasil


BULAN_XLSX = ["januari", "februari", "maret", "april", "mei", "juni", "juli",
              "agustus", "september", "oktober", "november", "desember"]
beda = []
for urutan, lembar in enumerate(BULAN_XLSX, start=1):
    asli = _merah_berkas(AKAR / "ABSENSI GURU PNS.xlsx", lembar)
    mesin = set(insentif.tanggal_merah(2025, urutan))
    if asli != mesin:
        beda.append((lembar, sorted(asli), sorted(mesin)))
# Pengecualian termaklumi (kesalahan cat merah di berkas sekolah):
# - Maret: 28 (cuti Nyepi) terlewat; - Mei: 16 tercat merah tanpa sebab;
# - Agustus: 18 (cuti tambahan pemerintah) terlewat.
cek("9 bulan identik; Maret/Mei/Agustus hanya selisih cat-error berkas",
    len(beda) == 3 and [b[0] for b in beda] == ["maret", "mei", "agustus"]
    and beda[0][2] == sorted(set(beda[0][1]) | {28})
    and beda[1][1] == sorted(set(beda[1][2]) | {16})
    and beda[2][2] == sorted(set(beda[2][1]) | {18}),
    str(beda))

# --------------------------------------------------------------------------- #
# 9. Alur HTTP
# --------------------------------------------------------------------------- #
skenario("9. Alur HTTP: draf → roster → PDF → pengaturan → libur → profil")


async def alur_http() -> None:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://uji",
                                 follow_redirects=True) as klien:
        await klien.post("/login", data={"mode": "staff", "username": "admin",
                                         "password": "admin123"})
        beranda = await klien.get("/insentif")
        cek("GET /insentif 200", beranda.status_code == 200)
        cek("formulir buat draf", "/insentif/periode/buat" in beranda.text)
        cek("menu Insentif", ">Insentif<" in beranda.text)

        buat = await klien.post("/insentif/periode/buat",
                                data={"tahun": "2026", "bulan": "7", "salin_dari": "0"})
        cek("buat draf → editor", "/insentif/periode/" in str(buat.url), str(buat.url))
        cek("nama KS tampil", "Muhammad, S.Pd., M.Pd" in buat.text)
        pid_http = str(buat.url).rstrip("/").rsplit("/", 1)[-1].split("?")[0]

        pns_http = await klien.get(f"/insentif/periode/{pid_http}",
                                   params={"dokumen": "pns"})
        cek("tab PNS", "Absensi Guru PNS" in pns_http.text)
        ubah = await klien.post(
            f"/insentif/roster/{insentif.roster_periode(int(pid_http), 'spj')[0]['id']}/ubah",
            data={"dokumen": "spj", "nama_tampil": "NAMA UBAH HTTP", "nip": "",
                  "npwp": "", "rekening": "", "nik": "", "gol": "IV/a",
                  "jabatan": "Kepala Sekolah", "tarif": "7000000", "pph_nominal": ""})
        cek("ubah roster via HTTP", "NAMA UBAH HTTP" in ubah.text)

        for dokumen in ("pns", "pppk", "spj", "gabungan"):
            pdf = await klien.get(f"/insentif/periode/{pid_http}/pdf/{dokumen}")
            cek(f"PDF {dokumen}",
                pdf.status_code == 200 and pdf.content.startswith(b"%PDF"),
                f"status {pdf.status_code}")

        atur_get = await klien.get("/insentif/pengaturan")
        cek("pengaturan 200 + tarif", "tarif_guru" in atur_get.text)
        atur_post = await klien.post(
            "/insentif/pengaturan",
            data={"tarif_ks": "7000000", "tarif_waka": "2700000",
                  "tarif_guru": "1400000", "tarif_pelatih": "650000",
                  "pph_guru_3": "67500", "pph_guru_4": "202500",
                  "pph_waka_3": "135000", "pph_waka_4": "405000",
                  "pph_ks_3": "350000", "pph_ks_4": "1050000", "pph_nonasn": "0",
                  "unit_kerja": "SMP NEGERI 2 TANGERANG", "kecamatan": "Kec. Tangerang",
                  "kota": "KOTA TANGERANG", "bendahara_gtk_id": "2",
                  "pengawas_nama": "Ta'ani", "pengawas_nip": "196903051995121004",
                  "ks_nama": "", "ks_nip": ""})
        cek("simpan pengaturan", "Pengaturan disimpan" in atur_post.text)
        cek("tarif baru terbaca",
            insentif.baca_pengaturan()["tarif_guru"] == "1400000")

        libur_get = await klien.get("/insentif/libur", params={"tahun": "2026"})
        cek("libur 200 + Imlek", "Tahun Baru Imlek 2577" in libur_get.text)
        libur_post = await klien.post(
            "/insentif/libur/simpan",
            data={"tahun": "2026", "tanggal": "2026-07-20", "nama": "Libur HTTP",
                  "jenis": "kustom", "aktif": "1"})
        cek("tambah libur", "diperbarui" in libur_post.text
            and "2026-07-20" in (await klien.get("/insentif/libur",
                                                params={"tahun": "2026"})).text)

        profil_get = await klien.get("/insentif/profil")
        cek("profil 200", profil_get.status_code == 200 and "MUHAMMAD" in profil_get.text)

        gtk_daftar = await klien.get("/gtk")
        cek("kolom jabatan di daftar GTK",
            "Jabatan insentif" in gtk_daftar.text
            and "Kepala Sekolah" in gtk_daftar.text)
        gtk_detail = await klien.get("/gtk/pegawai/1")
        cek("Detail KS: kartu PPh + manual dari jadikan-bawaan",
            "PPh insentif" in gtk_detail.text and "1.050.000" in gtk_detail.text
            and "diset manual" in gtk_detail.text)
        gtk_guru = await klien.get("/gtk/pegawai/3")
        cek("Detail guru: otomatis + PPh 202.500",
            "otomatis dari data GTK" in gtk_guru.text
            and "202.500" in gtk_guru.text)
        set_jab = await klien.post("/gtk/pegawai/2/jabatan-insentif",
                                   data={"jabatan": "Pelatih"})
        cek("set jabatan via GTK", "Jabatan insentif disimpan" in set_jab.text)
        cek("detail menandai manual",
            "diset manual" in (await klien.get("/gtk/pegawai/2")).text)
        set_salah = await klien.post("/gtk/pegawai/2/jabatan-insentif",
                                     data={"jabatan": "Menteri"})
        cek("jabatan asing ditolak", "tidak dikenal" in set_salah.text)
        set_auto = await klien.post("/gtk/pegawai/2/jabatan-insentif",
                                    data={"jabatan": ""})
        cek("kembali otomatis",
            "otomatis dari data GTK" in set_auto.text
            and "Wakil Kepala Sekolah" in set_auto.text)

        hapus = await klien.post(f"/insentif/periode/{pid_http}/hapus")
        cek("hapus draf", "dihapus" in hapus.text)


asyncio.run(alur_http())

# --------------------------------------------------------------------------- #
# Laporan
# --------------------------------------------------------------------------- #
print("\n" + "-" * 78)
gagal = [(nama, ket) for nama, ok, ket in HASIL if not ok]
print(f"[SELESAI] {len(HASIL) - len(gagal)} pemeriksaan lolos pada {len(SKENARIO)} skenario"
      + (f", {len(gagal)} GAGAL" if gagal else ""))
for nama, ket in gagal:
    print(f"  GAGAL: {nama}" + (f" — {ket}" if ket else ""))
sys.exit(1 if gagal else 0)


