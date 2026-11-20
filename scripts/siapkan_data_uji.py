#!/usr/bin/env python3
"""Siapkan basis data contoh untuk pengembangan tampilan (816 siswa + 3 ekskul).

Jalankan setelah ``python run.py --init-db``::

    .venv/bin/python scripts/buat_data_contoh.py

Lalu::

    .venv/bin/python scripts/siapkan_data_uji.py
"""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import db, services  # noqa: E402

sheet, parsed, fmt = services.read_and_parse(BASE / "sample-data/daftar-pd-contoh.xlsx")
hasil = services.import_students(parsed, mode="upsert", actor="r34",
                                 source_file="daftar-pd-contoh.xlsx")
print(f"impor: {hasil.total} baris")

# Daftar ekskul resmi (14) seperti yang dipakai sekolah.
ditambah, total = services.isi_ekskul_resmi()
print(f"ekskul resmi: {ditambah} baru (total {total})")

bagus = services.get_student_by_nisn("3900000009")
for nama in ("BASKET", "FUTSAL"):
    ekskul = next((x for x in services.list_ekskul() if x["nama"] == nama), None)
    if ekskul is not None:
        services.add_ekskul_member(int(ekskul["id"]), int(bagus["id"]), actor="r34")

# Satu pendaftaran yang masih menunggu persetujuan pembina.
pmr = next((x for x in services.list_ekskul() if x["nama"] == "PMR"), None)
if pmr is not None:
    services.ajukan_pendaftaran_ekskul(int(bagus["id"]), int(pmr["id"]), actor="r34")

print("ekskul:", [e["nama"] for e in services.list_ekskul()])
print("anggota:", services.student_ekskul(bagus["id"]))
print("siswa:", db.query_value("SELECT COUNT(*) FROM students"))
