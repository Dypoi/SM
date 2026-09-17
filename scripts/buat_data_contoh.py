#!/usr/bin/env python3
"""Buat berkas Excel **data contoh (fiktif)** untuk uji coba & pemeriksaan mandiri.

Berkas asli dari Dapodik berisi data pribadi siswa asli dan tidak boleh
disimpan di repositori. Skrip ini membuat berkas tiruan dengan susunan kolom
yang sama seperti ekspor Dapodik (judul bergabung "Data Ayah/Ibu/Wali", kolom
lama yang sudah tidak dipakai, dan seterusnya) sehingga aplikasi tetap dapat
diuji tanpa menyentuh data asli.

Jalankan::

    python scripts/buat_data_contoh.py                 # 816 siswa (bawaan)
    python scripts/buat_data_contoh.py --jumlah 120    # lebih cepat untuk uji
    python scripts/buat_data_contoh.py --keluaran sample-data/contoh.xlsx

Semua nama, NISN, NIK, dan alamat di berkas ini **karangan**.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.dapodik import (  # noqa: E402  (butuh sys.path di atas)
    LABEL_DIHAPUS,
    PENGHASILAN_OPTIONS,
    PEKERJAAN_OPTIONS,
    PENDIDIKAN_OPTIONS,
    STUDENT_FIELDS,
)

DEPAN_PRIA = ("Ahmad", "Bagus", "Cahyo", "Dimas", "Eko", "Fajar", "Gilang", "Hendra", "Ilham",
              "Joko", "Krisna", "Lukman", "Maulana", "Nanda", "Oka", "Putra", "Rizky", "Surya",
              "Taufik", "Umar", "Wahyu", "Yoga", "Zaki", "Arif", "Bima", "Dedi")
DEPAN_WANITA = ("Ayu", "Bella", "Citra", "Dewi", "Eka", "Fitri", "Gita", "Hana", "Indah", "Jihan",
                "Kartika", "Lestari", "Maya", "Nadia", "Oktavia", "Putri", "Rina", "Sari",
                "Tiara", "Umi", "Vina", "Wulan", "Yuni", "Zahra", "Anisa", "Bunga")
BELAKANG = ("Santoso", "Wijaya", "Nugroho", "Pratama", "Saputra", "Hidayat", "Ramadhan", "Kurniawan",
            "Setiawan", "Maulida", "Anggraini", "Puspita", "Rahmawati", "Safitri", "Handayani",
            "Firmansyah", "Gunawan", "Siregar", "Simatupang", "Hakim", "Susanto", "Utami")
AGAMA = ("Islam", "Islam", "Islam", "Islam", "Kristen", "Katolik", "Hindu", "Buddha")
KECAMATAN = ("Takokak", "Sukanagara", "Pagelaran", "Cibodas", "Sindangbarang")
DESA = ("Sindanghayu", "Pasiripis", "Waringinsari", "Cimaskara", "Sukagalih", "Mekarsari")
JALAN = ("Kp. Cibodas", "Jl. Raya Takokak", "Kp. Babakan", "Jl. Pasiripis", "Kp. Cikaret")
SEKOLAH_ASAL = ("SDN 1 Takokak", "SDN 2 Sukanagara", "SDN Pasiripis", "MI Al-Hidayah",
                "SDN Cimaskara", "SDN 3 Pagelaran")
ROMBEL_PREFIX = ("7", "8", "9")
ROMBEL_SUFIX = ("A", "B", "C", "D", "E", "F")
NEGARA = "Indonesia"


def nama_acak(rng: random.Random, perempuan: bool) -> str:
    depan = rng.choice(DEPAN_WANITA if perempuan else DEPAN_PRIA)
    return f"{depan} {rng.choice(BELAKANG)}"


def judul_kolom() -> tuple[list[str], list[str]]:
    """Susun baris judul & sub-judul seperti ekspor Dapodik."""
    atas: list[str] = ["No"]
    bawah: list[str] = [""]
    grup_terakhir = ""
    for spec in STUDENT_FIELDS:
        if spec.group in {"ayah", "ibu", "wali"}:
            grup = {"ayah": "Data Ayah", "ibu": "Data Ibu", "wali": "Data Wali"}[spec.group]
            label = spec.label
            for awalan in ("Ayah - ", "Ibu - ", "Wali - "):
                if label.startswith(awalan):
                    label = label[len(awalan):]
                    break
            if grup != grup_terakhir:
                atas.append(grup)          # sel pertama grup: nama grup
                grup_terakhir = grup
            else:
                atas.append("")            # sel gabungan: dikosongkan
            bawah.append(label)
        else:
            grup_terakhir = ""
            atas.append(spec.label)
            bawah.append("")
    # Kolom lama yang sudah tidak dipakai (ikut muncul pada berkas Dapodik asli).
    for label in LABEL_DIHAPUS:
        atas.append(label)
        bawah.append("")
    return atas, bawah


def nilai_baris(spec, rng: random.Random, konteks: dict) -> object:
    """Nilai contoh untuk satu field."""
    kunci = spec.key
    if kunci == "nama":
        return konteks["nama"]
    if kunci == "nisn":
        return konteks["nisn"]
    if kunci == "nipd":
        return konteks["nisn"][-7:]
    if kunci == "jk":
        return "P" if konteks["perempuan"] else "L"
    if kunci == "tempat_lahir":
        return rng.choice(KECAMATAN)
    if kunci == "tanggal_lahir":
        return konteks["tanggal_lahir"]
    if kunci == "nik":
        return konteks["nik"]
    if kunci == "no_kk":
        return konteks["no_kk"]
    if kunci == "agama":
        return konteks["agama"]
    if kunci == "sekolah_asal":
        return konteks["sekolah_asal"]
    if kunci == "alamat":
        return konteks["alamat"]
    if kunci == "rt":
        return f"{rng.randint(1, 8):03d}"
    if kunci == "rw":
        return f"{rng.randint(1, 6):03d}"
    if kunci == "kelurahan":
        return konteks["desa"]
    if kunci == "kecamatan":
        return konteks["kecamatan"]
    if kunci == "kode_pos":
        return "43165"
    if kunci == "hp":
        return "08" + "".join(str(rng.randint(0, 9)) for _ in range(10))
    if kunci == "jarak_rumah":
        return round(rng.uniform(0.3, 9.5), 1)
    if kunci == "rombel":
        return konteks["rombel"]
    if kunci == "status":
        return "Aktif"
    if kunci == "tahun_ajaran_masuk" or kunci == "tahun_masuk":
        return rng.choice(["2024/2025", "2025/2026"])
    if kunci.endswith("_nama"):
        return konteks["ayah"] if kunci.startswith("ayah") else (
            konteks["ibu"] if kunci.startswith("ibu") else konteks["wali"])
    if kunci.endswith("_tahun_lahir"):
        return rng.randint(1975, 1990)
    if kunci.endswith("_pendidikan"):
        # Sebagian kecil memakai nilai lama di luar daftar (seperti berkas asli).
        if kunci.startswith("ibu") and rng.random() < 0.08:
            return "SLTA/Sederajat"
        return rng.choice(PENDIDIKAN_OPTIONS)
    if kunci.endswith("_pekerjaan"):
        if kunci.startswith("ayah") and rng.random() < 0.07:
            return "Buruh Harian Lepas"
        return rng.choice(PEKERJAAN_OPTIONS)
    if kunci.endswith("_penghasilan"):
        if rng.random() < 0.6:
            return "Rp. 1,000,000 - Rp. 2,000,000"
        return rng.choice(PENGHASILAN_OPTIONS)
    if kunci.endswith("_nik"):
        return konteks["nik_orangtua"] if kunci.startswith("ayah") else (
            konteks["nik_ibu"] if kunci.startswith("ibu") else konteks["nik_wali"])
    if spec.kind == "ya_tidak":
        return "Tidak"
    if spec.kind == "int":
        return rng.randint(1, 12)
    if spec.kind == "float":
        return round(rng.uniform(1, 90), 1)
    if kunci in {"penerima_kps", "penerima_kip", "layak_pip", "kebutuhan_khusus"}:
        return "Tidak"
    if kunci.startswith("berat") or kunci.startswith("tinggi"):
        return rng.randint(30, 70)
    if kunci.startswith("lingkar"):
        return rng.randint(50, 70)
    if kunci == "jumlah_saudara":
        return rng.randint(0, 5)
    if kunci == "anak_ke":
        return rng.randint(1, 5)
    return ""


def buat_berkas(tujuan: Path, jumlah: int, rng: random.Random) -> tuple[int, int]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    atas, bawah = judul_kolom()
    wb = Workbook()
    ws = wb.active
    ws.title = "Daftar Peserta Didik"

    ws.append(["Daftar Peserta Didik"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"NPSN: 2020{jumlah % 10000:04d}", "SMP NEGERI 2 CONTOH", "Tahun Ajaran 2026/2027"])
    ws.append([])
    ws.append(atas)
    ws.append(bawah)
    for sel in ws[4]:
        sel.font = Font(bold=True)
        sel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    baris_judul = 5

    for nomor in range(1, jumlah + 1):
        perempuan = rng.random() < 0.52
        tahun = rng.randint(2011, 2013)
        konteks = {
            "perempuan": perempuan,
            "nama": nama_acak(rng, perempuan),
            "nisn": f"39{nomor:08d}",
            "nik": f"32041{tahun}{nomor:06d}"[:16],
            "no_kk": f"32041{tahun - 12}{nomor:06d}"[:16],
            "agama": rng.choice(AGAMA),
            "sekolah_asal": rng.choice(SEKOLAH_ASAL),
            "alamat": f"{rng.choice(JALAN)} No. {rng.randint(1, 90)}",
            "desa": rng.choice(DESA),
            "kecamatan": rng.choice(KECAMATAN),
            "rombel": f"{rng.choice(ROMBEL_PREFIX)}{rng.choice(ROMBEL_SUFIX)}",
            "tanggal_lahir": f"{tahun}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        }
        konteks["ayah"] = nama_acak(rng, False)
        konteks["ibu"] = nama_acak(rng, True)
        konteks["wali"] = ""
        konteks["nik_orangtua"] = f"32040{rng.randint(1970, 1990)}{nomor:06d}"[:16]
        konteks["nik_ibu"] = f"32041{rng.randint(1972, 1992)}{nomor:06d}"[:16]
        konteks["nik_wali"] = ""
        baris = [nomor] + [nilai_baris(spec, rng, konteks) for spec in STUDENT_FIELDS]
        baris += ["" for _ in LABEL_DIHAPUS]   # kolom lama: dikosongkan
        ws.append(baris)

    lebar = max(len(atas), len(bawah)) + 1
    ws.freeze_panes = f"A{baris_judul + 1}"
    for urutan, kolom in enumerate(ws.iter_cols(min_row=4, max_row=4, max_col=lebar), start=1):
        nilai = kolom[0].value or ""
        ws.column_dimensions[ws.cell(row=4, column=urutan).column_letter].width = min(24, max(11, len(str(nilai)) + 2))

    tujuan.parent.mkdir(parents=True, exist_ok=True)
    wb.save(tujuan)
    return jumlah, len(atas)


def main() -> int:
    parser = argparse.ArgumentParser(description="Buat berkas Excel data contoh (fiktif)")
    parser.add_argument("--jumlah", type=int, default=816, help="banyaknya baris siswa")
    parser.add_argument("--keluaran", default=str(BASE_DIR / "sample-data" / "daftar-pd-contoh.xlsx"))
    parser.add_argument("--benih", type=int, default=20260916, help="benih angka acak (hasil tetap)")
    args = parser.parse_args()

    tujuan = Path(args.keluaran)
    rng = random.Random(args.benih)
    jumlah, kolom = buat_berkas(tujuan, args.jumlah, rng)
    print(f"[OK] {tujuan} — {jumlah} baris siswa, {kolom + 1} kolom (1 kolom nomor + {kolom})")
    print("     Seluruh nama, NISN, NIK, dan alamat di berkas ini KARANGAN (bukan data asli).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
