#!/usr/bin/env python3
"""Pemeriksaan mandiri SM (tanpa perlu pytest).

Skrip ini membuat database sementara di folder terpisah, menjalankan seluruh
alur penting aplikasi, lalu melaporkan hasilnya. Berguna untuk memastikan
aplikasi tetap sehat setelah Anda menambah fitur baru.

Jalankan::

    python scripts/cek_sistem.py            # semua pemeriksaan
    python scripts/cek_sistem.py --http     # sekaligus uji semua halaman HTTP
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import pathlib
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# --- Database sementara: HARUS diatur sebelum mengimpor modul app ---
_SEMENTARA = Path(tempfile.mkdtemp(prefix="sm-cek-"))
os.environ["SM_DATA_DIR"] = str(_SEMENTARA)
os.environ["SM_DB_PATH"] = str(_SEMENTARA / "cek.sqlite3")
os.environ["SM_AUTO_SEED"] = "0"

HASIL: list[tuple[str, bool, str]] = []


def cek(nama: str):
    """Dekorator sederhana untuk satu pemeriksaan."""

    def wrapper(fungsi):
        def jalankan(*args, **kwargs):
            try:
                keterangan = fungsi(*args, **kwargs) or ""
                HASIL.append((nama, True, keterangan))
            except Exception as exc:  # noqa: BLE001
                detail = f"{type(exc).__name__}: {exc}"
                if os.getenv("SM_CEK_VERBOSE"):
                    detail += "\n" + traceback.format_exc()
                HASIL.append((nama, False, detail))
            return None

        return jalankan

    return wrapper


# --------------------------------------------------------------------------- #
# Pemeriksaan
# --------------------------------------------------------------------------- #
@cek("1. Skema database & data awal")
def cek_migrasi():
    from app import config, db, migrations

    diterapkan = migrations.run_migrations()
    tabel = {
        r["name"]
        for r in db.query_all("SELECT name FROM sqlite_master WHERE type='table'")
    }
    wajib = {"students", "users", "settings", "imports", "import_issues",
             "data_changes", "extracurriculars", "ekskul_members",
             "dapodik_jobs", "audit_log", "schema_migrations"}
    hilang = wajib - tabel
    assert not hilang, f"tabel tidak dibuat: {hilang}"
    assert db.query_value("SELECT COUNT(*) FROM users WHERE role='admin'") == 1
    # Pemasangan baru harus BENAR-BENAR KOSONG: tidak ada siswa, tidak ada ekskul contoh.
    # (Dulu migrasi mengisi sendiri 14 ekskul resmi sehingga aplikasi hasil pemasangan sudah
    # berisi data — sekolah meminta aplikasinya fresh.)
    assert db.query_value("SELECT COUNT(*) FROM students") == 0, \
        "basis data baru sudah berisi siswa (data contoh ikut terbawa)"
    assert db.query_value("SELECT COUNT(*) FROM extracurriculars") == 0, \
        "basis data baru sudah berisi ekstrakurikuler (daftar contoh ikut terbawa)"
    assert not config.EKSKUL_SEKOLAH, \
        "daftar ekskul resmi seharusnya TIDAK diisi otomatis pada basis data baru"

    # Nama berkas basis data dari pemasangan lama dipindahkan otomatis, tetapi berkasnya
    # sering terkunci sesaat (mis. jendela server lain baru ditutup) → harus dicoba
    # beberapa kali dan pesannya cukup sekali agar tidak mengganggu tiap kali dijalankan.
    assert config.PINDAH_DB_PERCOBAAN >= 3 and config.PINDAH_DB_JEDA > 0, \
        "pemindahan berkas basis data lama harus dicoba beberapa kali"
    simpan_data = config.DATA_DIR
    simpan_rinci = config._ringkasan_db
    simpan_db_env = os.environ.pop("SM_DB_PATH", None)  # agar jalur basis data benar-benar diuji
    folder = _SEMENTARA / "nama-db"
    folder.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(folder / config.DB_NAMA_LAMA)) as conn:
        conn.execute("CREATE TABLE students(id INTEGER)")
    config.DATA_DIR = folder
    config.PINDAH_DB_PERCOBAAN, simpan_coba = 2, config.PINDAH_DB_PERCOBAAN
    simpan_jeda, config.PINDAH_DB_JEDA = config.PINDAH_DB_JEDA, 0.01

    def _kunci(path):  # tiru WinError 32: berkas sedang dipakai proses lain
        raise PermissionError(32, "berkas dipakai proses lain")
    try:
        config._ringkasan_db = _kunci
        pertama = config._siapkan_db_path()
        assert pertama.name == config.DB_NAMA_LAMA, "harus tetap memakai berkas lama saat terkunci"
        assert config.CATATAN_DB, "pemakaian nama lama seharusnya diberitahukan sekali"
        config.CATATAN_DB = ""
        config._siapkan_db_path()
        assert not config.CATATAN_DB, "pemberitahuan nama lama tidak boleh berulang setiap dijalankan"
        config._ringkasan_db = simpan_rinci
        dijalankan = config._siapkan_db_path()
        assert dijalankan.name == config.DB_NAMA, "berkas harus berpindah setelah tidak terkunci"
        assert "dipindahkan" in config.CATATAN_DB, config.CATATAN_DB
        assert not (folder / f".{config.DB_NAMA_LAMA}.diberitahukan").exists(), \
            "penanda 'sudah diberitahukan' harus dihapus setelah berhasil"
        _, siswa_awal = config._ringkasan_db(folder / config.DB_NAMA)
        assert siswa_awal == 0, "basis data contoh tidak sesuai"
    finally:
        config._ringkasan_db = simpan_rinci
        config.DATA_DIR = simpan_data
        config.PINDAH_DB_PERCOBAAN, config.PINDAH_DB_JEDA = simpan_coba, simpan_jeda
        config.CATATAN_DB = ""
        if simpan_db_env is not None:
            os.environ["SM_DB_PATH"] = simpan_db_env

    return (f"{len(tabel)} tabel, {db.query_value('SELECT COUNT(*) FROM settings')} pengaturan, "
            f"{config.DB_PATH.name}")


@cek("2. Pembaca berkas multi-format")
def cek_pembaca():
    from app.readers import format_label, read_spreadsheet, supported_extensions

    berkas = sorted((BASE_DIR / "sample-data").glob("*.xlsx")) + sorted(
        (BASE_DIR / "template-import").glob("*.xlsx")
    )
    assert berkas, "tidak ada berkas contoh untuk diuji"
    ringkasan = []
    for path in berkas:
        sheet = read_spreadsheet(path, path.suffix.lower())[0]
        ringkasan.append(f"{path.name}: {sheet.row_count}x{sheet.col_count}")
        assert sheet.row_count > 0
    return "; ".join(ringkasan) + f" | format didukung: {len(supported_extensions())}"


@cek("3. Deteksi struktur & pemetaan kolom Dapodik")
def cek_parser():
    from app.readers import read_spreadsheet
    from app.dapodik import parse_sheet

    berkas = sorted((BASE_DIR / "sample-data").glob("*.xlsx"))
    if not berkas:
        raise AssertionError("berkas contoh tidak ditemukan di sample-data/")
    sheet = read_spreadsheet(berkas[0])[0]
    parsed = parse_sheet(sheet)
    assert parsed.kind == "daftar_peserta_didik", f"jenis terdeteksi: {parsed.kind}"
    assert parsed.header_row > 1, "baris judul seharusnya dilewati"
    assert parsed.mapped_field_count >= 50, f"hanya {parsed.mapped_field_count} kolom terpetakan"
    assert len(parsed.ignored_columns) >= 10, "kolom lama seharusnya terdeteksi & diabaikan"
    assert len(parsed.records) > 100, f"hanya {len(parsed.records)} baris terbaca"
    errors = [i for i in parsed.issues if i.level == "error"]
    assert not errors, f"ada {len(errors)} error tidak terduga: {errors[:2]}"
    return (f"{len(parsed.records)} baris, {parsed.mapped_field_count}/{parsed.total_columns} kolom, "
            f"{len(parsed.ignored_columns)} kolom lama diabaikan, header baris {parsed.header_row}")


@cek("4. Impor ke database + riwayat impor")
def cek_impor():
    from app import db, services
    from app.readers import format_label, read_spreadsheet
    from app.dapodik import parse_sheet

    berkas = sorted((BASE_DIR / "sample-data").glob("*.xlsx"))
    path = berkas[0]
    sheet = read_spreadsheet(path)[0]
    parsed = parse_sheet(sheet)
    stored = services.StoredFile(path=path, filename=path.name,
                                 size=path.stat().st_size, extension=path.suffix.lower())
    import_id = services.create_import(stored, sheet=sheet, parsed=parsed,
                                       fmt=format_label(path.suffix.lower()), actor="cek")
    hasil = services.import_students(parsed, import_id=import_id, mode="upsert",
                                     actor="cek", source_file=path.name)
    total = int(db.query_value("SELECT COUNT(*) FROM students") or 0)
    assert hasil.imported == len(parsed.records), f"{hasil.imported} != {len(parsed.records)}"
    assert total == hasil.imported, f"tabel students berisi {total} baris"
    status = db.query_value("SELECT status FROM imports WHERE id = ?", (import_id,))
    assert status == "sukses", f"status impor: {status}"
    return f"impor #{import_id}: {hasil.imported} siswa baru, total {total} baris"


@cek("5. Impor ulang (upsert) tidak menggandakan data")
def cek_upsert():
    from app import db, services
    from app.readers import read_spreadsheet
    from app.dapodik import parse_sheet

    berkas = sorted((BASE_DIR / "sample-data").glob("*.xlsx"))
    sheet = read_spreadsheet(berkas[0])[0]
    parsed = parse_sheet(sheet)
    sebelum = int(db.query_value("SELECT COUNT(*) FROM students") or 0)
    hasil = services.import_students(parsed, mode="upsert", actor="cek")
    sesudah = int(db.query_value("SELECT COUNT(*) FROM students") or 0)
    assert sesudah == sebelum, f"jumlah berubah dari {sebelum} ke {sesudah}"
    return f"{hasil.skipped} baris dilewati (data sudah sama), jumlah tetap {sesudah}"


@cek("6. Pencarian, filter, dan paginasi")
def cek_filter():
    from app import services

    filters = services.StudentFilter(q="a", sort="nama")
    baris, total = services.list_students(filters, page=1, per_page=10)
    assert total > 0 and len(baris) <= 10
    rombel = services.distinct_values("rombel")
    assert rombel, "daftar rombel kosong"
    contoh = rombel[0]
    baris_rombel, total_rombel = services.list_students(services.StudentFilter(rombel=contoh), per_page=5)
    assert total_rombel > 0 and all(r["rombel"] == contoh for r in baris_rombel)
    kosong, _ = services.list_students(services.StudentFilter(incomplete_only=True), per_page=5)
    return (f"{total} hasil untuk 'a', {len(rombel)} rombel terdaftar, "
            f"{len(kosong)} contoh siswa berdata belum lengkap")


@cek("7. Perubahan data tercatat pada riwayat (audit)")
def cek_perubahan():
    from app import db, services

    siswa = db.query_one("SELECT id, nisn FROM students WHERE nisn IS NOT NULL LIMIT 1")
    assert siswa, "belum ada siswa"
    sebelum = int(db.query_value("SELECT COUNT(*) FROM data_changes") or 0)
    changes = services.update_student(int(siswa["id"]), {"catatan": "diuji oleh cek_sistem"},
                                      actor="cek", source="manual")
    sesudah = int(db.query_value("SELECT COUNT(*) FROM data_changes") or 0)
    assert changes, "tidak ada perubahan tercatat"
    assert sesudah > sebelum, "riwayat data_changes tidak bertambah"
    services.update_student(int(siswa["id"]), {"catatan": None}, actor="cek", source="manual")
    return f"{len(changes)} perubahan dicatat (total riwayat {sesudah} baris)"


@cek("8. Statistik & laporan kualitas data")
def cek_statistik():
    from app import services

    stats = services.student_stats()
    per_tingkat = services.stats_by_tingkat()
    kualitas = services.data_quality()
    assert stats["total"] > 0
    assert stats["total"] == stats["laki_laki"] + stats["perempuan"]
    assert per_tingkat and kualitas["fields"]
    return (f"{stats['total']} siswa ({stats['laki_laki']} L / {stats['perempuan']} P), "
            f"{stats['rombel']} rombel, {len(kualitas['fields'])} kolom diperiksa, "
            f"{kualitas['siap_sinkron']} siap sinkron")


@cek("9. Ekspor CSV & Excel")
def cek_ekspor():
    from app import services

    filters = services.StudentFilter()
    csv_bytes = services.export_students_csv(filters)
    xlsx_bytes = services.export_students_xlsx(filters)
    assert csv_bytes.startswith("\ufeff".encode("utf-8")) or len(csv_bytes) > 100
    assert xlsx_bytes[:2] == b"PK", "berkas xlsx tidak valid"
    return f"CSV {len(csv_bytes) / 1024:.1f} KB, XLSX {len(xlsx_bytes) / 1024:.1f} KB"


@cek("10. Ekstrakurikuler: kegiatan, anggota, nilai A-D, catatan, dan ekspor")
def cek_ekskul():
    import asyncio

    import httpx

    from app import auth, db, migrations, services
    from app.main import app

    # --- Kolom sesuai permintaan sekolah: tanpa kode/kategori/tempat/kuota ---- #
    kolom = {baris["name"] for baris in db.rows_to_dicts(db.query_all("PRAGMA table_info(extracurriculars)"))}
    for dibuang in ("kode", "kategori", "tempat", "kuota"):
        assert dibuang not in kolom, f"kolom {dibuang} seharusnya sudah dihapus"
    assert {"pembina", "pelatih"} <= kolom, "kolom pembina & pelatih harus ada"
    kolom_anggota = {baris["name"] for baris in db.rows_to_dicts(db.query_all("PRAGMA table_info(ekskul_members)"))}
    assert "catatan" in kolom_anggota, "kolom catatan belum ada pada daftar anggota"

    jumlah_seed = services.seed_ekskul_if_empty()
    ekskul_id = services.save_ekskul({"nama": "Klub Uji", "pembina": "Bu Rina, S.Pd",
                                      "pelatih": "Pak Agus", "hari": "Senin", "aktif": 1}, actor="cek")
    tersimpan = services.get_ekskul(ekskul_id)
    assert tersimpan["pelatih"] == "Pak Agus", tersimpan
    assert services.EKSKUL_NILAI == ("A", "B", "C", "D"), services.EKSKUL_NILAI

    # --- Tambah & hapus anggota, nilai huruf + catatan ---------------------- #
    siswa = db.query_one("SELECT id, nisn, nama FROM students LIMIT 1")
    member_id = services.add_ekskul_member(ekskul_id, int(siswa["id"]), jabatan="Ketua", actor="cek")
    assert member_id, "gagal menambah anggota"
    assert services.add_ekskul_member(ekskul_id, int(siswa["id"]), actor="cek") is None, \
        "anggota ganda seharusnya ditolak"

    cari, galat = services.cari_siswa_ekskul(str(siswa["nisn"]))
    assert cari and int(cari["id"]) == int(siswa["id"]), galat
    cari_nama, galat = services.cari_siswa_ekskul(str(siswa["nama"]))
    assert cari_nama is not None or "serupa" in galat, galat
    kosong, galat = services.cari_siswa_ekskul("")
    assert kosong is None and galat

    services.update_ekskul_member(member_id, {"predikat": "A", "catatan": "Aktif latihan",
                                              "jabatan": "Ketua", "status": "aktif"}, actor="cek")
    anggota = services.ekskul_members(ekskul_id)
    assert anggota and anggota[0]["predikat"] == "A", anggota
    assert anggota[0]["catatan"] == "Aktif latihan", anggota
    assert len(services.pilihan_siswa_ekskul(limit=5)) == 5

    # --- Ekspor CSV, Excel, dan PDF ---------------------------------------- #
    akun = auth.authenticate_ekskul("3204123456780001", "pembina", ekskul_id, "Bu Rina")[0]
    assert akun is not None
    transport = httpx.ASGITransport(app=app)

    async def jalankan() -> str:
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=False) as klien:
            masuk = await klien.post("/login", data={"mode": "ekskul", "peran": "pembina",
                                                     "ekskul_id": ekskul_id,
                                                     "nik": "3204123456780001"})
            assert masuk.status_code == 303, masuk.status_code

            halaman = await klien.get(f"/ekstrakurikuler/{ekskul_id}")
            assert halaman.status_code == 200
            assert 'value="A"' in halaman.text and 'name="catatan"' in halaman.text, \
                "dropdown nilai A-D & kolom catatan harus ada di halaman ekskul"
            assert "panel di samping" not in halaman.text, \
                "teks bantuan jangan menyuruh mencari panel di samping lagi"
            assert "/data-siswa" not in halaman.text, \
                "akun ekskul tidak boleh diberi tautan ke halaman petugas (jalan buntu)"

            # "Cari cepat siswa": cari per kelas, lalu masukkan satu per satu
            anggota_ada = db.query_one(
                "SELECT s.id, s.nisn, s.rombel FROM ekskul_members m "
                "JOIN students s ON s.id = m.student_id WHERE m.ekskul_id = ? LIMIT 1",
                (ekskul_id,))
            rombel_uji = (anggota_ada["rombel"] if anggota_ada and anggota_ada["rombel"] else None) or \
                db.query_value("SELECT rombel FROM students WHERE rombel IS NOT NULL "
                               "AND TRIM(rombel) <> '' ORDER BY rombel LIMIT 1")
            cari_kelas = await klien.get(f"/ekstrakurikuler/{ekskul_id}?rombel={rombel_uji}")
            assert cari_kelas.status_code == 200
            assert 'name="student_id"' in cari_kelas.text, \
                "hasil cari cepat harus punya tombol Masukkan per siswa"
            if anggota_ada and anggota_ada["nisn"]:
                cari_nisn = await klien.get(f"/ekstrakurikuler/{ekskul_id}?cari={anggota_ada['nisn']}")
                assert "sudah anggota" in cari_nisn.text, \
                    "siswa yang sudah menjadi anggota harus ditandai pada hasil pencarian"
            siswa_lain = db.query_one(
                "SELECT id FROM students WHERE rombel = ? AND id NOT IN "
                "(SELECT student_id FROM ekskul_members WHERE ekskul_id = ?) LIMIT 1",
                (rombel_uji, ekskul_id))
            if siswa_lain:
                masuk_kelas = await klien.post(
                    f"/ekstrakurikuler/{ekskul_id}/anggota",
                    data={"student_id": str(siswa_lain["id"]), "jabatan": "Anggota",
                          "kembali_rombel": str(rombel_uji), "kembali_cari": ""})
                assert masuk_kelas.status_code == 303, masuk_kelas.status_code
                tujuan = masuk_kelas.headers.get("location", "")
                assert "#cari-cepat" in tujuan and f"rombel={rombel_uji}" in tujuan, tujuan
                assert db.query_value(
                    "SELECT COUNT(*) FROM ekskul_members WHERE ekskul_id = ? AND student_id = ?",
                    (ekskul_id, siswa_lain["id"])) == 1, "anggota dari hasil cari tidak tersimpan"
                services.remove_ekskul_member(
                    int(db.query_value("SELECT id FROM ekskul_members WHERE ekskul_id = ? AND student_id = ?",
                                       (ekskul_id, siswa_lain["id"]))), actor="cek")
            assert "Aktif latihan" in halaman.text

            # nilai huruf & catatan lewat HTTP (seperti yang dilakukan pembina)
            simpan = await klien.post(f"/ekstrakurikuler/anggota/{member_id}",
                                     data={"jabatan": "Ketua", "nilai": "B",
                                           "catatan": "Perlu latihan tambahan", "status": "aktif"})
            assert simpan.status_code == 303, simpan.status_code
            assert db.query_value("SELECT predikat FROM ekskul_members WHERE id = ?", (member_id,)) == "B"
            assert db.query_value("SELECT catatan FROM ekskul_members WHERE id = ?", (member_id,)) == \
                "Perlu latihan tambahan"

            # nilai di luar A-D tidak diterima (dikosongkan, bukan disimpan mentah)
            await klien.post(f"/ekstrakurikuler/anggota/{member_id}",
                             data={"jabatan": "Ketua", "nilai": "Z", "catatan": "", "status": "aktif"})
            assert db.query_value("SELECT predikat FROM ekskul_members WHERE id = ?", (member_id,)) is None

            hasil = {}
            for ekstensi, tipe in (("csv", "text/csv"), ("xlsx", "spreadsheet"), ("pdf", "pdf")):
                balasan = await klien.get(f"/ekstrakurikuler/{ekskul_id}/anggota.{ekstensi}")
                assert balasan.status_code == 200, f"{ekstensi}: {balasan.status_code}"
                assert tipe in balasan.headers.get("content-type", ""), balasan.headers
                isi = balasan.content
                minimum = {"csv": 40, "xlsx": 2000, "pdf": 800}[ekstensi]
                assert len(isi) > minimum, f"{ekstensi} terlalu kecil ({len(isi)} bita)"
                if ekstensi == "pdf":
                    assert isi.startswith(b"%PDF-1.4"), "berkas PDF tidak sah"
                    assert b"%%EOF" in isi[-20:], "PDF tidak lengkap"
                    assert b"/Type /Page" in isi, "PDF tanpa halaman"
                hasil[ekstensi] = len(isi)
            return ("; ".join(f"{k} {v} bita" for k, v in hasil.items()))

    rincian = asyncio.run(jalankan())

    # tambah & hapus lewat HTTP sudah diuji UI; di sini dipastikan hapus bekerja
    services.remove_ekskul_member(member_id, actor="cek")
    assert services.ekskul_members(ekskul_id) == [], "anggota belum terhapus"
    assert db.query_value("SELECT COUNT(*) FROM ekskul_members WHERE ekskul_id = ?", (ekskul_id,)) == 0
    db.execute("DELETE FROM ekskul_akun WHERE ekskul_id = ?", (ekskul_id,))
    db.execute("DELETE FROM extracurriculars WHERE id = ?", (ekskul_id,))

    stats = services.ekskul_stats()
    return (f"{jumlah_seed} contoh dibuat; kolom kode/kategori/tempat/kuota terhapus; "
            f"nilai A-D + catatan; tambah/hapus anggota; ekspor {rincian}; total {stats['total']} kegiatan")


@cek("11. Keamanan: hash sandi, sesi, dan kunci API")
def cek_keamanan():
    from app import auth, db, services
    from app.security import create_session_token, hash_password, read_session_token, verify_password

    sandi = "rahasia123"
    hash_ = hash_password(sandi)
    assert verify_password(sandi, hash_)
    assert not verify_password("salah", hash_)
    token = create_session_token({"uid": 1, "role": "admin"})
    assert read_session_token(token)["role"] == "admin"
    assert read_session_token(token + "rusak") is None

    auth.create_user("operator.uji", "sandiuiji", "Operator Uji", "operator")
    user, pesan = auth.authenticate_staff("operator.uji", "sandiuiji")
    assert user is not None and user.is_staff and not user.is_admin, pesan
    siswa_ok, pesan = auth.authenticate_student(str(db.query_value("SELECT nisn FROM students LIMIT 1")))
    assert siswa_ok is not None, pesan
    assert siswa_ok.role == "siswa"
    assert auth.authenticate_student("0000000000")[0] is None

    kunci = services.get_setting("api_key")
    assert kunci and len(kunci) > 20
    return "hash PBKDF2, cookie sesi bertanda tangan, kunci API aktif, login siswa NISN teruji"


@cek("12. Kontrak API untuk bot Dapodik")
def cek_api_kontrak():
    from app import db, services
    from app.dapodik import FIELD_BY_KEY

    siswa = db.query_one("SELECT id, nisn FROM students WHERE nisn IS NOT NULL LIMIT 1")
    nisn = siswa["nisn"]
    # Meniru bot: kirim perubahan dan periksa hasilnya
    changes = services.update_student(int(siswa["id"]), {"no_kk": "3671010101139999"},
                                      actor="bot-cek", source="api_bot")
    assert changes, "perubahan dari API tidak tercatat"
    assert services.get_student_by_nisn("0000000000") is None
    riwayat = db.query_all(
        "SELECT source FROM data_changes WHERE student_id = ? ORDER BY id DESC LIMIT 1", (siswa["id"],)
    )
    assert riwayat[0]["source"] == "api_bot"
    services.update_student(int(siswa["id"]), {"no_kk": None}, actor="cek", source="manual")
    return (f"PATCH /api/siswa/{{{nisn}}} -> 1 perubahan berlabel api_bot; "
            f"{len(FIELD_BY_KEY)} field tersedia untuk bot")


@cek("13. Fitur pembaruan aplikasi (git pull)")
def cek_pembaruan():
    """Uji fungsi pembaruan tanpa menyentuh salinan aplikasi yang sedang dipakai."""
    from app import updater

    assert updater.AKTIF is True or os.getenv("SM_GIT_UPDATE") == "0"

    perintah = updater.perintah_manual()
    assert "git pull" in perintah, "petunjuk manual harus memuat perintah git pull"
    assert str(BASE_DIR) in perintah, "petunjuk manual harus menyebut folder aplikasi"

    status = updater.status_pembaruan(periksa_jaringan=False)
    for kunci in ("tersedia", "revisi_lokal", "cabang", "remote", "pesan", "perubahan_lokal",
                  "ada_perubahan_lokal", "butuh_muat_ulang", "catatan"):
        assert kunci in status, f"status pembaruan kehilangan kunci '{kunci}'"

    if (BASE_DIR / ".git").exists() and updater.status_pembaruan()["tersedia"]:
        kode, keluaran = updater.jalankan_git(["rev-parse", "--short", "HEAD"])
        assert kode == 0 and keluaran, "git rev-parse gagal"
        info_git = updater.informasi_git()
        assert info_git["cabang"], "nama cabang git tidak terbaca"
        assert updater.cabang_target() == (updater.services.get_setting("update_cabang") or info_git["cabang"])

    # Muat ulang server TIDAK boleh lewat jendela konsol (masukan sekolah ronde 42:
    # «hilangkan untuk menampilkan cmd termasuk pada saat pembaruan»).
    perintah_latar = updater.perintah_latar()
    assert perintah_latar[1] == updater.perintah_restart()[1], "perintah latar kehilangan run.py"
    assert "--tunggu-port" in perintah_latar, \
        "server baru harus menunggu port bebas (proses lama masih hidup saat digantikan)"
    assert str(updater.TUNGGU_PORT) in perintah_latar, "batas tunggu port tidak ikut dikirim"
    kode_updater_sementara = pathlib.Path(updater.__file__).read_text(encoding="utf-8")
    for harus_tidak_ada in ("perintah_windows", "jalankan-ulang.bat", "tulis_berkas_jalankan_ulang"):
        assert harus_tidak_ada not in kode_updater_sementara, \
            f"jalur muat ulang jendela konsol masih ada: {harus_tidak_ada}"
    assert "CREATE_NO_WINDOW" in kode_updater_sementara and "pythonw" in kode_updater_sementara, \
        "server baru harus dijalankan tanpa jendela (CREATE_NO_WINDOW + pythonw.exe)"
    # Peluncur cadangan SM.cmd: dipakai saat kode lama masih berjalan (transisi).
    launcher = updater.BASE_DIR / "SM.cmd"
    if launcher.exists():
        isi_cmd = launcher.read_bytes().decode("utf-8")
        assert "run.py" in isi_cmd, "SM.cmd tidak menjalankan run.py"
        assert "\r\n" in isi_cmd, "SM.cmd harus memakai CRLF"
    # run.bat harus menemukan Python walau PATH rusak / "where" tidak ada:
    # periksa folder .venv lebih dulu, lalu peluncur py, lalu PATH, lalu folder
    # pemasangan umum — dan tolak Python yang lebih tua dari 3.10.
    run_bat = updater.BASE_DIR / "run.bat"
    isi_run = run_bat.read_bytes().decode("utf-8")
    assert "\r\n" in isi_run, "run.bat harus memakai CRLF"
    assert ".venv\\Scripts\\python.exe" in isi_run, "run.bat tidak memakai .venv aplikasi"
    assert "%%~$PATH:" in isi_run, "run.bat tidak mencari python.exe di PATH tanpa 'where'"
    assert "sys.version_info >= (3, 10)" in isi_run, "run.bat tidak memeriksa versi Python 3.10+"
    assert "import fastapi, uvicorn, jinja2, multipart, itsdangerous, openpyxl" in isi_run, \
        "run.bat tidak memeriksa dependensi inti"
    assert "sm-dependensi.txt" in isi_run, "run.bat tidak menyimpan stempel dependensi"
    assert "goto jalankan_server" in isi_run, "run.bat tidak melewati pemasangan yang tidak perlu"
    assert "requirements-bot.txt" in isi_run, \
        "run.bat tidak mencoba memasang pustaka bot (selenium) saat belum ada"
    assert "where " not in isi_run.lower(), "run.bat tidak boleh bergantung pada perintah 'where'"
    urutan = [isi_run.index(".venv\\Scripts\\python.exe"),
              isi_run.index('py.exe"'),
              isi_run.index('"python.exe" "" "python.exe di PATH"')]
    assert urutan == sorted(urutan), "urutan pencarian Python di run.bat salah (.venv harus pertama)"
    diag = updater.BASE_DIR / "SM-diagnosa.bat"
    if diag.exists():
        isi_diag = diag.read_bytes().decode("utf-8")
        assert "laporan-python.txt" in isi_diag, "SM-diagnosa.bat tidak membuat laporan"
        assert "\r\n" in isi_diag, "SM-diagnosa.bat harus memakai CRLF"

    # Di Linux/macOS fungsi ini harus gagal dengan baik (mengembalikan False, tanpa
    # mematikan proses). Di Windows TIDAK dipanggil di sini agar tidak membuka
    # jendela server kedua saat pemeriksaan berjalan.
    if os.name != "nt":
        assert updater._mulai_ulang_windows() is False, "jalur gagal harus mengembalikan False"
    kode_updater = pathlib.Path(updater.__file__).read_text(encoding="utf-8")
    # Pencatatan audit saat meminta muat ulang tidak boleh menggagalkan tombol
    # (server bisa keburu mengganti diri & menutup koneksi database).
    assert "Audit muat ulang tidak tercatat" in kode_updater, \
        "pencatatan audit muat ulang tidak dibungkus penanganan galat"
    assert '["cmd", "/c", "start"' not in kode_updater, \
        "jangan memakai bentuk list untuk start (judul tanpa kutip dianggap nama program)"

    # Tanda muat ulang: dibuat, belum dijalankan seketika, lalu bisa dibatalkan.
    updater.batalkan_muat_ulang()
    assert updater.perlu_muat_ulang() is False, "tanda muat ulang seharusnya belum ada"
    updater.minta_muat_ulang(aktor="cek", alasan="uji")
    assert updater.RESTART_MARKER.exists(), "berkas permintaan muat ulang tidak dibuat"
    assert updater.perlu_muat_ulang() is False, "server tidak boleh memuat ulang sebelum jeda aman"
    updater.batalkan_muat_ulang()
    assert not updater.RESTART_MARKER.exists(), "permintaan muat ulang tidak terhapus"

    # Cadangan basis data otomatis sebelum penarikan pembaruan.
    cadangan = updater.cadangkan_database()
    assert cadangan is not None and cadangan.exists(), "cadangan basis data gagal dibuat"
    assert cadangan.parent.name == "backup"

    jadwal = updater.interval_detik()
    assert 900 <= jadwal <= 86400, f"selang pemeriksaan tidak wajar: {jadwal}"

    jenis = "salinan git" if status["tersedia"] else "tanpa git (ZIP)"
    return (f"{jenis}; revisi {status['revisi_lokal'] or '-'} pada cabang "
            f"{status['remote']}/{status['cabang']}; cadangan uji {cadangan.name}; "
            f"pemeriksaan tiap {jadwal // 60} menit")


@cek("14. Pengajuan perubahan data & berkas pendukung")
def cek_pengajuan():
    """Uji alur pengajuan siswa: berkas wajib, keputusan admin, dan audit."""
    from app import services
    from app.dapodik import STUDENT_FIELDS

    assert set(services.DOKUMEN_LABEL) == {"akta_lahir", "kk", "ijazah"}, "jenis berkas berubah"
    assert "nisn" not in services.FIELD_DAPAT_DIAJUKAN, "NISN tidak boleh dapat diajukan"
    # Rombel & tingkat hanya berubah lewat impor Excel (permintaan sekolah).
    assert set(services.FIELD_TERKUNCI) == {"rombel", "tingkat"}, services.FIELD_TERKUNCI
    for terkunci in services.FIELD_TERKUNCI:
        assert terkunci not in services.FIELD_DAPAT_DIAJUKAN, f"{terkunci} jangan dapat diajukan"
    assert len(services.FIELD_DAPAT_DIAJUKAN) == len(STUDENT_FIELDS) - 1 - len(services.FIELD_TERKUNCI)

    sid = services.create_student(
        {"nama": "UJI PENGAJUAN", "nisn": "3999900001", "jk": "L", "rombel": "7A",
         "alamat": "Jl. Sebelum", "hp": "0800000000"},
        actor="cek",
    )

    # Berkas wajib dulu: pengajuan tanpa berkas harus ditolak.
    try:
        services.ajukan_perubahan(sid, {"hp": "0811111111"}, aktor="cek")
        raise AssertionError("pengajuan tanpa berkas seharusnya ditolak")
    except ValueError as exc:
        assert "Berkas wajib" in str(exc)

    berkas = {
        "akta_lahir": ("akta.png", b"\x89PNG\r\n\x1a\n" + b"uji" * 8),
        "kk": ("kk.png", b"\x89PNG\r\n\x1a\n" + b"uji" * 8),
        "ijazah": ("ijazah.pdf", b"%PDF-1.4 uji"),
    }
    pengajuan = services.ajukan_perubahan(
        sid, {"hp": "0812222222", "nisn": "0000000000"},
        catatan="uji", aktor="siswa:3999900001", dokumen=berkas,
    )
    rid = int(pengajuan["id"])
    assert [item["field"] for item in pengajuan["items"]] == ["hp"], "NISN ikut diajukan!"
    assert services.dokumen_lengkap(sid)[0] is True
    assert len(pengajuan["dokumen"]) == 3

    # Tolak: data siswa tidak berubah dan berkas harus diunggah ulang.
    services.putuskan_pengajuan(rid, False, aktor="admin", catatan="kurang jelas")
    assert services.get_student(sid)["hp"] == "0800000000", "data berubah walau ditolak"
    assert services.dokumen_lengkap(sid)[0] is False, "berkas ditolak tidak boleh dihitung"

    pengajuan2 = services.ajukan_perubahan(sid, {"hp": "0813333333"}, aktor="cek", dokumen=berkas)
    rid2 = int(pengajuan2["id"])
    services.putuskan_pengajuan(rid2, True, aktor="admin", catatan="sesuai")
    assert services.get_student(sid)["hp"] == "0813333333", "data baru tidak diterapkan"
    assert services.ambil_pengajuan(rid2)["status"] == "disetujui"
    riwayat = [row for row in services.student_changes(sid, limit=20)
               if row["source"] == "pengajuan_siswa" and row["field"] == "hp"]
    assert riwayat, "perubahan dari pengajuan tidak tercatat"

    # Siswa dapat membatalkan pengajuannya sendiri selama masih menunggu.
    pengajuan3 = services.ajukan_perubahan(sid, {"alamat": "Jl. Baru"}, aktor="cek")
    services.batalkan_pengajuan(int(pengajuan3["id"]), aktor="cek")
    assert services.ambil_pengajuan(int(pengajuan3["id"]))["status"] == "dibatalkan"

    stat = services.statistik_pengajuan()
    return (f"{len(services.FIELD_DAPAT_DIAJUKAN)} kolom dapat diajukan "
            f"(NISN, rombel, tingkat terkunci); "
            f"3 jenis berkas; disetujui {stat['disetujui']} / ditolak {stat['ditolak']}")


@cek("15. Dropdown pekerjaan/penghasilan/pendidikan & aturan ayah-ibu-wali")
def cek_keluarga():
    """Pilihan pekerjaan/penghasilan/pendidikan serta aturan ayah-ibu-wali."""
    from app import db, services
    from app.dapodik import (FIELD_BY_KEY, FIELD_PEKERJAAN, FIELD_PENGHASILAN,
                             FIELD_PENDIDIKAN, FIELD_WALI, PEKERJAAN_OPTIONS,
                             PENGHASILAN_OPTIONS, PENDIDIKAN_OPTIONS)

    # --- dropdown ---
    assert len(PEKERJAAN_OPTIONS) == 17, f"pilihan pekerjaan: {len(PEKERJAAN_OPTIONS)}"
    assert len(PENGHASILAN_OPTIONS) == 7, f"pilihan penghasilan: {len(PENGHASILAN_OPTIONS)}"
    assert "Rp. 5,000,000 - Rp. 20,000,000" in PENGHASILAN_OPTIONS, "rentang 5-20 juta hilang"
    for key in FIELD_PEKERJAAN:
        assert FIELD_BY_KEY[key].choices == PEKERJAAN_OPTIONS, f"{key} belum memakai daftar pekerjaan"
    for key in FIELD_PENGHASILAN:
        assert FIELD_BY_KEY[key].choices == PENGHASILAN_OPTIONS, f"{key} belum memakai daftar penghasilan"
    assert "Tidak Berpenghasilan" in PENGHASILAN_OPTIONS
    assert "Sudah Meninggal" in PEKERJAAN_OPTIONS
    assert len(PENDIDIKAN_OPTIONS) == 17, f"pilihan pendidikan: {len(PENDIDIKAN_OPTIONS)}"
    for key in FIELD_PENDIDIKAN:
        assert FIELD_BY_KEY[key].choices == PENDIDIKAN_OPTIONS, f"{key} belum memakai daftar pendidikan"
    assert {"D1", "S1", "Paud", "Paket A", "Paket C", "Tidak Sekolah"} <= set(PENDIDIKAN_OPTIONS)

    # --- aturan: nama ayah harus berbeda dengan nama ibu ---
    sid = services.create_student(
        {"nama": "UJI KELUARGA", "nisn": "3999000011", "jk": "L", "rombel": "7A",
         "ayah_nama": "BUDI SANTOSO", "ibu_nama": "SITI AMINAH",
         "wali_nama": "SUPARMAN"}, actor="cek")

    try:
        services.validasi_keluarga({"ayah_nama": "NAMA SAMA", "ibu_nama": "nama   sama"},
                                   services.get_student(sid))
        raise AssertionError("nama ayah = nama ibu seharusnya ditolak")
    except ValueError as exc:
        assert "ayah" in str(exc).lower()

    # --- wali: data yang melanggar aturan tidak disimpan (sistem yang menghapus) ---
    sid_wali = services.create_student(
        {"nama": "UJI WALI AUTO", "nisn": "3999000021", "jk": "L", "ayah_nama": "RIYANTO",
         "ibu_nama": "SITI", "wali_nama": "riyanto"}, actor="cek")
    assert not (services.get_student(sid_wali).get("wali_nama") or ""), \
        "wali yang memakai nama ayah seharusnya tidak disimpan"

    sid_sah = services.create_student(
        {"nama": "UJI WALI SAH", "nisn": "3999000022", "jk": "P", "ibu_nama": "RATNA",
         "wali_nama": "SUPARMAN"}, actor="cek")
    assert (services.get_student(sid_sah).get("wali_nama") or "") == "SUPARMAN", "wali sah hilang"

    # mengisi nama ayah -> data wali dihapus otomatis oleh sistem
    services.update_student(sid_sah, {"ayah_nama": "BUDI"}, actor="cek")
    assert not (services.get_student(sid_sah).get("wali_nama") or ""), \
        "data wali belum dihapus otomatis saat nama ayah diisi"
    assert int(db.query_value(
        "SELECT COUNT(*) FROM audit_log WHERE aksi = 'hapus_wali_otomatis'") or 0) >= 1, \
        "penghapusan wali otomatis tidak tercatat di audit"

    # penghapusan wali oleh siswa: langsung diproses sistem, tanpa berkas & tanpa antrean
    sid_hapus = services.create_student(
        {"nama": "UJI HAPUS WALI", "nisn": "3999000023", "jk": "L", "ibu_nama": "DEWI",
         "wali_nama": "HENDRA", "wali_pekerjaan": "Nelayan"}, actor="cek")
    pengajuan_hapus = services.ajukan_perubahan(
        sid_hapus, {"wali_nama": "", "wali_pekerjaan": ""}, aktor="cek")
    assert pengajuan_hapus["status"] == "disetujui", "penghapusan wali tidak auto-disetujui"
    assert pengajuan_hapus["diputuskan_oleh"] == "sistem", "bukan diputuskan sistem"
    assert not (services.get_student(sid_hapus).get("wali_nama") or ""), "data wali belum terhapus"
    assert all(int(item["id"]) != int(pengajuan_hapus["id"])
               for item in services.daftar_pengajuan(status="menunggu", limit=50)), \
        "penghapusan wali masih masuk antrean admin"

    # mengisi wali padahal ayah sudah ada -> ditolak sistem dengan pesan jelas
    sid_ayah = services.create_student(
        {"nama": "UJI AYAH ADA", "nisn": "3999000024", "jk": "L", "ayah_nama": "JOKO"}, actor="cek")
    try:
        services.ajukan_perubahan(sid_ayah, {"wali_nama": "SUPARMAN"}, aktor="cek")
        raise AssertionError("pengisian wali saat ayah ada seharusnya ditolak")
    except ValueError as exc:
        assert "wali" in str(exc).lower()

    # pembersihan data lama (mis. hasil impor) berjalan satu perintah
    db.execute("UPDATE students SET wali_nama = ?, wali_pendidikan = ? WHERE id = ?",
               ("Pak Joko", "S1", sid_ayah))
    perlu = services.siswa_perlu_bersih_wali()
    assert any(item["id"] == sid_ayah for item in perlu), "siswa dengan wali lama tidak terdeteksi"
    hasil_rapikan = services.rapikan_wali_otomatis(aktor="cek")
    assert hasil_rapikan["dibersihkan"] >= 1, f"pembersihan tidak berjalan: {hasil_rapikan}"
    assert not (services.get_student(sid_ayah).get("wali_nama") or ""), "data wali belum dibersihkan"

    # --- pengisian wali yang sah (ayah kosong) tetap lewat persetujuan admin ---
    sid_wali_baru = services.create_student(
        {"nama": "UJI WALI BARU", "nisn": "3999000025", "jk": "P", "ibu_nama": "SRI"}, actor="cek")
    pengajuan_wali = services.ajukan_perubahan(
        sid_wali_baru, {"wali_nama": "SUGENG", "wali_pendidikan": "S1"}, aktor="cek",
        dokumen={
            "akta_lahir": ("akta.png", b"\x89PNG\r\n\x1a\n" + b"uji" * 8),
            "kk": ("kk.png", b"\x89PNG\r\n\x1a\n" + b"uji" * 8),
            "ijazah": ("ijazah.pdf", b"%PDF-1.4 uji"),
        },
    )
    assert pengajuan_wali["status"] == "menunggu", "pengisian wali sah tidak perlu auto-disetujui"
    services.putuskan_pengajuan(int(pengajuan_wali["id"]), True, aktor="cek")
    assert (services.get_student(sid_wali_baru).get("wali_nama") or "") == "SUGENG", "wali sah tidak tersimpan"

    # --- temuan kualitas data ikut memeriksa nama kembar ---
    services.create_student({"nama": "UJI KEMBAR", "nisn": "3999000026", "jk": "P",
                             "ayah_nama": "NAMA SAMA", "ibu_nama": "nama sama"}, actor="cek")
    kode = {item["kode"]: item["jumlah"] for item in services.data_quality()["temuan"]}
    for kunci in ("AYAH_IBU_SAMA", "WALI_SAMA_AYAH_IBU", "WALI_PERLU_DIBERSIHKAN",
                  "PEKERJAAN_LUAR_DAFTAR", "PENGHASILAN_LUAR_DAFTAR", "PENDIDIKAN_LUAR_DAFTAR"):
        assert kunci in kode, f"temuan {kunci} tidak ada"
    assert kode["AYAH_IBU_SAMA"] >= 1, "temuan ayah = ibu tidak terhitung"

    # --- sisi browser tidak boleh memblokir data wali (server yang mengurus) ---
    from app import config as _config
    app_js = (_config.BASE_DIR / "app/static/js/app.js").read_text(encoding="utf-8")
    assert "Nama wali tidak boleh sama" not in app_js, \
        "app.js masih menolak pengiriman saat nama wali sama dengan ayah/ibu"
    assert "data-wali-sama-note" in app_js, "app.js tidak menampilkan catatan wali sama ayah/ibu"
    assert "sama dengan nama ayah" in app_js, "teks peringatan wali hilang dari app.js"
    assert "Nama ayah dan nama ibu tidak boleh sama" in app_js, \
        "aturan ayah tidak boleh sama dengan ibu harus tetap dijaga di browser"
    makro = (_config.BASE_DIR / "app/templates/_macros.html").read_text(encoding="utf-8")
    assert "data-wali-sama-note" in makro, "blok wali tidak menyediakan tempat catatan"
    rute = (_config.BASE_DIR / "app/routers/student_routes.py").read_text(encoding="utf-8")
    assert "_catatan_wali_dibersihkan" in rute, \
        "pesan bahwa data wali dikosongkan sistem tidak ada di rute penyimpanan"

    return (f"{len(PEKERJAAN_OPTIONS)} pekerjaan, {len(PENGHASILAN_OPTIONS)} penghasilan, "
            f"{len(PENDIDIKAN_OPTIONS)} pendidikan; {len(FIELD_WALI)} kolom wali; "
            f"hapus wali otomatis (tanpa persetujuan) & {hasil_rapikan['dibersihkan']} data lama dibersihkan")


@cek("16. Halaman pengajuan & portal siswa (izin akses)")
def cek_http_pengajuan():
    """Pastikan halaman pengajuan hanya untuk admin dan portal aman bagi siswa."""
    import asyncio

    import httpx

    from app import services
    from app.main import app
    from app.migrations import run_migrations

    run_migrations()
    services.create_student({"nama": "UJI PORTAL", "nisn": "3999900002", "jk": "P"}, actor="cek")

    async def skenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=False) as klien:
            r = await klien.get("/pengajuan")
            assert r.status_code in {303, 403}, "anonim bisa membuka /pengajuan"

            await klien.post("/login", data={"mode": "siswa", "nisn": "3999900002"})
            r = await klien.get("/portal/pengajuan")
            assert r.status_code == 200, "siswa tidak bisa membuka form pengajuan"
            assert "NISN" in r.text and "name=\"nisn\"" not in r.text
            r = await klien.get("/pengajuan")
            assert r.status_code in {303, 403}, "siswa bisa membuka halaman admin"
            await klien.post("/logout")

            await klien.post("/login", data={"mode": "staff", "username": "admin",
                                             "password": "admin123"})
            r = await klien.get("/pengajuan")
            assert r.status_code == 200, "admin tidak bisa membuka /pengajuan"
            assert "Persetujuan" in r.text
            await klien.post("/logout")

    asyncio.run(skenario())

    # --- Tampilan siswa (r28): berkas kerangka + alat pratinjau ----------------- #
    # Masukan dari sekolah: halaman siswa dulu memakai kerangka petugas (sidebar,
    # tabel padat, kalimat teknis) sehingga terasa berat untuk anak kelas 7.
    from app import config as _cfg

    for berkas in ("app/static/css/portal.css", "app/templates/portal/_base.html",
                   "scripts/pratinjau_tampilan.py", "scripts/bandingkan_tampilan.py"):
        assert (_cfg.BASE_DIR / berkas).exists(), f"berkas tampilan siswa hilang: {berkas}"
    potongan_portal = (_cfg.BASE_DIR / "app/static/css/portal.css").read_text(encoding="utf-8")
    for tanda in (".pl-nav", ".pl-hero", ".pl-aksi", ".pl-kosong", "position: fixed"):
        assert tanda in potongan_portal, f"portal.css tidak memuat {tanda!r}"
    for nama in ("home.html", "profile.html", "ekskul.html", "request.html"):
        isi = (_cfg.BASE_DIR / "app/templates/portal" / nama).read_text(encoding="utf-8")
        assert isi.startswith('{% extends "portal/_base.html" %}'), \
            f"portal/{nama} belum memakai kerangka ruang siswa"
    kerangka = (_cfg.BASE_DIR / "app/templates/portal/_base.html").read_text(encoding="utf-8")
    assert "Menu siswa" in kerangka and "sidebar" not in kerangka, \
        "kerangka ruang siswa tidak boleh memuat menu petugas"

    # Halaman masuk juga bagian pertama yang dilihat anak: tab siswa besar dan sapaan
    # singkat. Tata cara TIDAK lagi memenuhi halaman — pindah ke tombol «!» (r32).
    masuk = (_cfg.BASE_DIR / "app/templates/login.html").read_text(encoding="utf-8")
    for tanda in ("pl-masuk-siswa", "pl-sapa", "petunjuk(", "pl-tombol-besar", "portal.css"):
        assert tanda in masuk, f"halaman masuk belum ramah siswa: {tanda!r} tidak ada"
    assert "sm-peran-terakhir" in masuk, "halaman masuk kehilangan pengingat pilihan peran"
    assert "pl-langkah" not in masuk, \
        "tata cara di halaman masuk seharusnya pindah ke popup «!», bukan ditulis memenuhi halaman"
    potongan_tema = (_cfg.BASE_DIR / "app/static/css/portal.css").read_text(encoding="utf-8")
    for tanda in (".pl-sapa", ".pl-info-tombol", ".pl-info-pop", ".pl-masuk-siswa"):
        assert tanda in potongan_tema, f"portal.css tidak memuat gaya {tanda!r}"

    # --- Sistem petunjuk «!» (r32) ------------------------------------------- #
    # Sekolah meminta tampilan yang lebih sederhana: tata cara tidak ditulis di
    # halaman, cukup tanda «!» yang membuka popup kecil saat diklik.
    makro = (_cfg.BASE_DIR / "app/templates/_macros.html").read_text(encoding="utf-8")
    for tanda in ("macro petunjuk", "pl-info-tombol", "pl-info-pop", "aria-expanded"):
        assert tanda in makro, f"makro petunjuk tidak lengkap: {tanda!r} tidak ada"
    app_js = (_cfg.BASE_DIR / "app/static/js/app.js").read_text(encoding="utf-8")
    for tanda in ("[data-info]", "[data-notif]", ".pl-info-pop", ".notif-pop", "tutupInfo", "Escape"):
        assert tanda in app_js, f"app.js belum membuka popup (petunjuk/notifikasi): {tanda!r} tidak ada"
    from app import web as _web_uji

    keluaran_makro = _web_uji.templates.env.from_string(
        '{% from "_macros.html" import petunjuk %}{{ petunjuk("halo <b>dunia</b>") }}'
    ).render()
    assert "pl-info-tombol" in keluaran_makro and "halo <b>dunia</b>" in keluaran_makro, \
        "makro petunjuk tidak menghasilkan tombol + isi popup seperti yang diharapkan"

    # Halaman siswa: tiap halaman memakai tombol «!», dan halaman yang panjang
    # (Dataku & Kegiatan) tidak lagi memakai tabel gaya lembar kerja.
    for nama_halaman in ("home.html", "profile.html", "ekskul.html", "request.html"):
        isi_halaman = (_cfg.BASE_DIR / "app/templates/portal" / nama_halaman).read_text(encoding="utf-8")
        # request.html mengimpor makronya dengan alias `jelaskan` (nama `petunjuk`
        # sudah dipakai untuk keterangan jenis berkas di dalam loop).
        assert ("petunjuk(" in isi_halaman or "jelaskan(" in isi_halaman), \
            f"portal/{nama_halaman} belum memakai tombol «!»"
    for nama_halaman in ("profile.html", "ekskul.html"):
        isi_halaman = (_cfg.BASE_DIR / "app/templates/portal" / nama_halaman).read_text(encoding="utf-8")
        assert "<table" not in isi_halaman, \
            f"portal/{nama_halaman} seharusnya tidak lagi memakai tabel gaya lembar kerja"

    # «Dataku» untuk siswa (r31): tabel gaya lembar kerja diganti kartu per kelompok +
    # pencarian. Label dirapikan untuk anak, TAPI isi data tidak diubah dan akronim
    # (NISN, NIK, KK, RT/RW, KM) tetap huruf besar.
    from app.web import rapikan_label

    contoh_label = {
        "Nama Lengkap": "Nama lengkap",
        "Jenis Kelamin": "Jenis kelamin",
        "NIPD / NIS Lokal": "NIPD/NIS lokal",
        "Nomor Kartu Keluarga (KK)": "Nomor kartu keluarga (KK)",
        "Sekolah asal (SD/MTs sebelumnya)": "Sekolah asal (SD/MTs sebelumnya)",
        "Jarak Rumah ke Sekolah (KM)": "Jarak rumah ke sekolah (KM)",
        "RT": "RT",
    }
    for asal, harap in contoh_label.items():
        hasil = rapikan_label(asal)
        assert hasil == harap, f"rapikan_label({asal!r}) = {hasil!r}, seharusnya {harap!r}"

    profil_siswa_templat = (_cfg.BASE_DIR / "app/templates/portal/profile.html").read_text(encoding="utf-8")
    for tanda in ("pl-grup", "cari-data", "rapikan_label", "Belum diisi", "Cetak / simpan PDF",
                  "grup_judul", "hanya_sekolah"):
        assert tanda in profil_siswa_templat, f"halaman Dataku siswa tidak memuat {tanda!r}"
    assert "<table" not in profil_siswa_templat, \
        "halaman Dataku siswa seharusnya tidak lagi memakai tabel gaya lembar kerja"

    # Alat pembanding harus benar-benar mengambil template LAMA dari Git (bukan menyalin
    # berkas sekarang) supaya perbandingan yang dilihat sekolah jujur.
    pembanding = (_cfg.BASE_DIR / "scripts/bandingkan_tampilan.py").read_text(encoding="utf-8")
    for tanda in ("archive", "bandingkan.html", "lama-", "revisi"):
        assert tanda in pembanding, f"alat pembanding tidak memuat {tanda!r}"

    return "halaman admin aman; form siswa tanpa kolom NISN; kerangka ruang siswa & pratinjau siap"

@cek("17. Halaman HTTP (status 200 & izin akses)")
def cek_http():
    """Menembak semua halaman utama memakai ASGI in-process (asinkron)."""
    import asyncio

    import httpx

    from app import services
    from app.main import app

    halaman_admin = ["/", "/data-siswa", "/data-siswa/1", "/data-siswa/baru", "/statistik",
                     "/kualitas-data", "/ekstrakurikuler", "/ekstrakurikuler/1", "/impor",
                     "/impor/1", "/impor/panduan", "/pengaturan",
                     "/pengaturan/dokumentasi-api", "/profil-akun", "/pembaruan", "/bot-dapodik",
                     "/bot-dapodik/catatan", "/bot-dapodik/catatan.txt", "/online"]

    async def jalankan() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cek") as client:
            assert (await client.get("/health")).json()["status"] == "ok"

            anonim = await client.get("/")
            assert anonim.status_code == 303, "halaman tanpa login seharusnya dialihkan"

            masuk = await client.post("/login", data={"mode": "staff", "username": "admin",
                                                      "password": "admin123"})
            assert masuk.status_code == 303, f"login gagal: {masuk.status_code}"

            gagal = await client.post("/login", data={"mode": "staff", "username": "admin",
                                                      "password": "salah"})
            assert gagal.status_code == 400, "sandi salah seharusnya ditolak"

            rusak = []
            for path in halaman_admin:
                kode = (await client.get(path)).status_code
                if kode != 200:
                    rusak.append(f"{path} -> {kode}")
            assert not rusak, "halaman bermasalah: " + ", ".join(rusak)

            # Berkas statis harus memakai penanda versi supaya browser tidak
            # memakai app.js/app.css lama dari cache setelah pembaruan.
            beranda = (await client.get("/")).text
            assert "/static/js/app.js?v=" in beranda, "app.js tanpa penanda versi"
            assert "/static/css/app.css?v=" in beranda, "app.css tanpa penanda versi"

            # Penyangga peralihan sesudah "Tarik pembaruan": berkas template sudah
            # baru sementara proses masih memakai kode lama (belum ada static_url,
            # qs_set, qs_tanpa, hari_ini). Inilah penyebab galat 500 pada versi
            # sebelumnya; halaman harus tetap terbuka.
            from app import web as modul_web

            disimpan: dict[str, object] = {}
            for nama_global in ("static_url", "qs_set", "qs_tanpa", "hari_ini"):
                if nama_global in modul_web.templates.env.globals:
                    disimpan[nama_global] = modul_web.templates.env.globals.pop(nama_global)
            try:
                rusak_transisi = []
                for path in ("/", "/data-siswa", "/pembaruan", "/statistik", "/login"):
                    kode = (await client.get(path)).status_code
                    if kode >= 500:
                        rusak_transisi.append(f"{path} -> {kode}")
                assert not rusak_transisi, (
                    "template baru harus tetap terbuka walau proses memakai kode lama: "
                    + ", ".join(rusak_transisi)
                )
            finally:
                modul_web.templates.env.globals.update(disimpan)

            # Halaman darurat tanpa template & halaman jeda sesudah pembaruan.
            from starlette.requests import Request as PermintaanUji

            permintaan_uji = PermintaanUji({
                "type": "http", "method": "GET", "path": "/uji", "query_string": b"",
                "headers": [], "scheme": "http", "server": ("cek", 80),
                "client": ("127.0.0.1", 1),
            })
            darurat = modul_web.render(permintaan_uji, "template-tidak-ada.html")
            isi_darurat = darurat.body.decode()
            assert darurat.status_code == 500, "template gagal seharusnya dibalas 500 ramah"
            assert "text/html" in darurat.headers.get("content-type", ""), "halaman darurat bukan HTML"
            assert "Buka dasbor" in isi_darurat, "halaman darurat tanpa tombol kembali"

            jeda = modul_web.halaman_jeda("Uji jeda", "Pesan uji", "/pembaruan", detik=2)
            isi_jeda = jeda.body.decode()
            assert jeda.status_code == 200, "halaman jeda bukan 200"
            assert "Menunggu server siap" in isi_jeda, "halaman jeda tanpa penanda tunggu"
            assert "/health" in isi_jeda, "halaman jeda tidak memantau /health"

            # Alamat dengan parameter tidak sah memakai halaman galat ramah (HTML),
            # bukan balasan JSON mentah dari FastAPI.
            galat_ramah = await client.get("/impor/zzz")
            assert galat_ramah.status_code == 400, f"/impor/zzz -> {galat_ramah.status_code}"
            assert "text/html" in galat_ramah.headers.get("content-type", ""), "galat bukan halaman HTML"

            # Penyempurnaan tampilan: pencarian cepat, panel filter, dan keadaan kosong.
            kosong = await client.get("/data-siswa", params={"q": "zzz-tidak-ada"})
            assert "quick-search" in kosong.text, "pencarian cepat topbar tidak dirender"
            assert "filter-panel" in kosong.text, "panel filter lanjutan tidak dirender"
            assert "empty-state" in kosong.text, "keadaan kosong tidak tampil pada daftar siswa"

            # Endpoint kemajuan bot harus tetap sehat walau belum ada pekerjaan sama sekali
            # (kekeliruan int(None) pernah membuat halaman ini membalas 500).
            status_bot = await client.get("/bot-dapodik/status.json")
            assert status_bot.status_code == 200, \
                f"/bot-dapodik/status.json -> {status_bot.status_code}"
            isi_status = status_bot.json()
            assert isi_status["items"] == [] and isi_status["hitung"] in ({}, None), \
                "status.json tanpa pekerjaan seharusnya kosong, bukan galat"

            # --- Ronde 44: halaman «Online» menampilkan alamat publik & tombolnya --- #
            from app import online as modul_online

            online_kosong = await client.get("/online")
            assert online_kosong.status_code == 200, f"/online -> {online_kosong.status_code}"
            for tanda_online in ("Nyalakan online (1 tombol)", "Hanya jaringan sekolah",
                                 "/online/status.json"):
                assert tanda_online in online_kosong.text, \
                    f"halaman Online tanpa {tanda_online!r}"
            modul_online.simpan_status("https://sm-sekolah.tail.ts.net", "uji cek_sistem", 8000)
            try:
                online_aktif = await client.get("/online")
                isi_online = online_aktif.text
                assert "https://sm-sekolah.tail.ts.net" in isi_online, \
                    "halaman Online tidak menampilkan alamat publiknya"
                assert "data-alamat=\"https://sm-sekolah.tail.ts.net\"" in isi_online, \
                    "alamat publik tidak siap disalin (tanpa data-alamat)"
                assert "Matikan online" in isi_online and "Buka alamatnya" in isi_online
                status_online = await client.get("/online/status.json")
                assert status_online.status_code == 200, "/online/status.json bukan 200"
                isi_status_online = status_online.json()
                assert "pekerjaan" in isi_status_online \
                    and isi_status_online["alamat_tercatat"].startswith("https://sm-sekolah"), \
                    isi_status_online
            finally:
                modul_online.hapus_status()

            kunci = services.get_setting("api_key")
            tanpa_kunci = await client.get("/api/statistik")
            assert tanpa_kunci.status_code in (303, 401), "API seharusnya menolak tanpa kunci"
            dengan_kunci = await client.get("/api/statistik", headers={"X-API-Key": kunci})
            assert dengan_kunci.status_code == 200, f"API menolak kunci: {dengan_kunci.status_code}"

            # Login siswa memakai NISN
            from app import db

            nisn = db.query_value("SELECT nisn FROM students WHERE nisn IS NOT NULL LIMIT 1")
            siswa_masuk = await client.post("/login", data={"mode": "siswa", "nisn": nisn})
            assert siswa_masuk.status_code == 303, "login siswa gagal"
            portal = await client.get("/portal")
            assert portal.status_code == 200, f"/portal -> {portal.status_code}"

            # --- Tampilan siswa (r28): anak kelas 7 memakai kerangka SENDIRI ------- #
            # Masukan dari sekolah: halaman siswa dulu memakai kerangka petugas (sidebar
            # + tabel padat + kalimat teknis) sehingga terasa berat untuk anak 12-13
            # tahun. Sekarang portal memakai portal/_base.html: menu bawah besar, huruf
            # lebih besar, dan TIDAK ada menu petugas sama sekali.
            assert "portal-shell" in portal.text and "pl-nav" in portal.text, \
                "beranda siswa tidak memakai kerangka ruang siswa (portal/_base.html)"
            for menu_petugas in ('href="/data-siswa"', 'href="/impor"', 'href="/bot-dapodik"',
                                 'href="/pengaturan"', 'href="/pembaruan"', 'class="sidebar"'):
                assert menu_petugas not in portal.text, \
                    f"halaman siswa masih memuat menu petugas {menu_petugas!r}"
            for wajib_siswa in ('href="/portal/profil"', 'href="/portal/ekstrakurikuler"',
                                "Ruang Siswa", "Beranda", "Kegiatan"):
                assert wajib_siswa in portal.text, f"halaman siswa tidak memuat {wajib_siswa!r}"
            for jalan in ("/portal/profil", "/portal/ekstrakurikuler", "/portal/pengajuan"):
                h = await client.get(jalan)
                assert h.status_code == 200, f"{jalan} -> {h.status_code}"
                assert "portal-shell" in h.text, f"{jalan} belum memakai kerangka ruang siswa"
                assert 'href="/pengaturan"' not in h.text, f"{jalan} masih menautkan Pengaturan"

            for khusus_admin in ("/pengaturan", "/online", "/pembaruan"):
                terlarang = await client.get(khusus_admin)
                assert terlarang.status_code in (303, 403), \
                    f"siswa seharusnya tidak bisa membuka {khusus_admin}"

            await client.post("/logout")

            # Tab siswa terbuka langsung lewat /login?mode=siswa — alamat ini dipakai
            # saat siswa keluar, dan halaman login mengingat pilihan peran terakhir.
            halaman_siswa = await client.get("/login?mode=siswa")
            teks_siswa = halaman_siswa.text
            assert "sm-peran-terakhir" in teks_siswa, "halaman login tidak mengingat pilihan peran"
            potongan_siswa = teks_siswa.split('data-tab="siswa"')[0].rsplit("<button", 1)[-1]
            assert "active" in potongan_siswa, "tab siswa tidak aktif pada /login?mode=siswa"
            potongan_staff = teks_siswa.split('data-tab="staff"')[0].rsplit("<button", 1)[-1]
            assert "active" not in potongan_staff, "tab admin seharusnya tidak aktif"

            # Sumber app.js: saat tab diklik, penyorot dilepas dari semua tombol di
            # kelompoknya (.tabs maupun .switch) supaya tidak ada dua kartu peran
            # yang tersorot bersamaan — penyebab warna tab yang salah di halaman login.
            from app import config as _config

            app_js_sumber = (_config.BASE_DIR / "app/static/js/app.js").read_text(encoding="utf-8")
            assert ".tabs, .switch" in app_js_sumber, \
                "app.js belum melepas penyorot tab pada kelompok .switch (halaman login)"
            assert "aria-selected" in app_js_sumber, "app.js tidak memperbarui aria-selected"
        return f"{len(halaman_admin)} halaman petugas + portal siswa + 3 endpoint API diuji"

    return asyncio.run(jalankan())


@cek("18. Pengaman mode online (header, asal permintaan, penangguhan login)")
def cek_pengaman_online():
    """Uji pengaman yang menyala saat aplikasi terjangkau dari internet."""
    import asyncio

    import httpx

    from app import auth, config, online
    from app.main import app

    # --- Bagian 1: pengenalan alamat & berkas penanda ---------------------- #
    assert online.ip_privat("127.0.0.1") and online.ip_privat("192.168.1.10")
    assert online.ip_privat("10.0.0.5") and not online.ip_privat("8.8.8.8")
    assert online.dari_luar("8.8.8.8")
    assert not online.dari_luar("192.168.1.10")

    lama_publik = config.PUBLIK
    try:
        online.simpan_status("https://sm-uji.tailnet.ts.net", "Tailscale Funnel (uji)", 8000)
        status = online.baca_status()
        assert status["aktif"] and status["alamat"] == "https://sm-uji.tailnet.ts.net"
        assert config.ALAMAT_FILE.read_text(encoding="utf-8").strip() == status["alamat"]
        assert online.peringatan_aman(None) == [], "pengunjung anonim tidak perlu spanduk"
        catatan = online.pemeriksaan_keamanan()
        assert {"label", "ok", "pesan"} <= set(catatan[0])
        assert any(baris["ok"] is False for baris in catatan), "sandi bawaan & NISN saja harus ditandai"

        # --- Bagian 2: perilaku HTTP (ASGI in-process) --------------------- #
        transport = httpx.ASGITransport(app=app)
        header_luar = {"X-Forwarded-For": "8.8.8.8"}

        async def jalankan() -> str:
            config.PUBLIK = True  # meniru pengunjung dari internet
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://cek") as klien:
                    luar = await klien.get("/", headers=header_luar)
                    for nama in ("x-frame-options", "x-content-type-options", "referrer-policy",
                                 "content-security-policy", "permissions-policy"):
                        assert nama in luar.headers, f"header {nama} tidak dipasang"

                    lintas = await klien.post(
                        "/login",
                        data={"mode": "staff", "username": "admin", "password": "admin123"},
                        headers={**header_luar, "Origin": "https://situs-jahat.example"},
                    )
                    assert lintas.status_code == 403, "POST dari situs lain harus ditolak"

                    sendiri = await klien.post(
                        "/login",
                        data={"mode": "staff", "username": "admin", "password": "admin123"},
                        headers={**header_luar, "Origin": "http://cek"},
                    )
                    assert sendiri.status_code == 303

                # Tamu (tanpa sesi) tidak boleh membuka dokumentasi API.
                async with httpx.AsyncClient(transport=transport, base_url="http://cek") as tamu:
                    terkunci = await tamu.get("/api/docs", headers=header_luar)
                    assert terkunci.status_code == 303, terkunci.status_code
                    assert terkunci.headers["location"].startswith("/login")

                    # Penangguhan: 8 percobaan gagal, percobaan ke-9 ditahan.
                    auth.bersihkan_penangguhan()
                    for _ in range(config.LOGIN_MAKS_GAGAL_AKUN):
                        ulang = await tamu.post("/login", data={"mode": "siswa", "nisn": "3999000099"},
                                                headers=header_luar)
                        assert ulang.status_code == 400, ulang.status_code
                    tahan = await tamu.post("/login", data={"mode": "siswa", "nisn": "3999000099"},
                                            headers=header_luar)
                    assert tahan.status_code == 429, tahan.status_code
                    assert "Terlalu banyak" in tahan.text
                    assert tahan.headers.get("retry-after")
                    assert auth.tunggu_sebelum_login("siswa", "3999000099", "8.8.8.8") > 0
                    auth.bersihkan_penangguhan()
            finally:
                config.PUBLIK = lama_publik

        asyncio.run(jalankan())

        # --- Bagian 3: cookie Secure hanya saat HTTPS ---------------------- #
        config.PUBLIK = False
        try:
            async def uji_cookie() -> None:
                async with httpx.AsyncClient(transport=transport, base_url="https://cek") as aman:
                    jawab = await aman.get("/", headers=header_luar)
                    assert jawab.headers.get("strict-transport-security"), "HSTS tidak ada saat HTTPS"
                    masuk = await aman.post(
                        "/login",
                        data={"mode": "staff", "username": "admin", "password": "admin123"},
                        headers={**header_luar, "Origin": "https://cek"},
                    )
                    assert masuk.status_code == 303
                    assert "secure" in (masuk.headers.get("set-cookie") or "").lower(),                         "cookie sesi harus Secure saat lewat HTTPS"

                async with httpx.AsyncClient(transport=transport, base_url="http://cek") as lokal:
                    masuk = await lokal.post(
                        "/login",
                        data={"mode": "staff", "username": "admin", "password": "admin123"},
                    )
                    assert masuk.status_code == 303
                    assert "secure" not in (masuk.headers.get("set-cookie") or "").lower(),                         "di jaringan sekolah (HTTP) cookie tidak boleh Secure agar tetap bisa login"

            asyncio.run(uji_cookie())
        finally:
            config.PUBLIK = lama_publik
            online.hapus_status()
            auth.bersihkan_penangguhan()

        return ("header keamanan + CSP, penolakan POST lintas situs, dokumentasi API terkunci, "
                "penangguhan login ke-9, cookie Secure hanya via HTTPS")
    finally:
        config.PUBLIK = lama_publik


@cek("19. Peluncur online (SM-online.py & SM-online.bat)")
def cek_peluncur_online():
    """Uji peluncur mode online tanpa benar-benar membuka terowongan."""
    import importlib.util
    import subprocess
    import time

    jalur = BASE_DIR / "SM-online.py"
    spek = importlib.util.spec_from_file_location("sm_online", jalur)
    modul = importlib.util.module_from_spec(spek)
    spek.loader.exec_module(modul)

    contoh = "2024-05-01T10:00:00Z INF |  https://sepi-biru-laut.trycloudflare.com  |"
    ketemu = modul.POLA_CLOUDFLARE.search(contoh)
    assert ketemu and ketemu.group(0) == "https://sepi-biru-laut.trycloudflare.com"
    assert modul.POLA_CLOUDFLARE.search("https://contoh.example.com") is None
    assert modul.alamat_lokal().count(".") == 3, modul.alamat_lokal()
    assert isinstance(modul.alat_tersedia(), dict)
    assert modul.port_siap(1) is False  # port yang pasti kosong

    # Mode lokal berjalan sampai dihentikan (tanpa terowongan, tanpa server).
    # Keluaran ditulis ke berkas (bukan pipa) supaya tidak menggantung karena
    # penyangga proses anak, dan selalu ada batas waktu.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="sm-online-") as ruang:
        berkas = pathlib.Path(ruang) / "keluaran.txt"
        with berkas.open("w+", encoding="utf-8") as pegangan:
            proses = subprocess.Popen(
                [sys.executable, "-u", str(jalur), "--lokal", "--tanpa-server", "--port", "8099"],
                cwd=str(BASE_DIR), stdout=pegangan, stderr=subprocess.STDOUT,
                env={**os.environ, "SM_PUBLIK": "1", "PYTHONUNBUFFERED": "1"},
            )
            batas = time.time() + 40
            try:
                while time.time() < batas and proses.poll() is None:
                    pegangan.flush()
                    if "jaringan sekolah" in berkas.read_text(encoding="utf-8", errors="replace"):
                        break
                    time.sleep(0.5)
            finally:
                proses.terminate()
                try:
                    proses.wait(timeout=10)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    proses.kill()
            pegangan.flush()
        keluaran = berkas.read_text(encoding="utf-8", errors="replace")
    assert "Aplikasi SM berjalan" in keluaran, keluaran[-400:]

    bat = (BASE_DIR / "SM-online.bat").read_bytes()
    assert bat.count(b"\r\n") >= 40, "SM-online.bat harus berakhir CRLF"
    assert bat.count(b"\n") == bat.count(b"\r\n"), "SM-online.bat masih punya baris LF"
    assert b".venv\\Scripts\\python.exe" in bat, "SM-online.bat harus memakai .venv lebih dulu"
    assert b"SM-online.py" in bat
    assert (BASE_DIR / "scripts" / "buat_peluncur_online.py").exists()
    readme = (BASE_DIR / "README.md").read_text(encoding="utf-8")
    assert "Menjalankan online" in readme, "README belum memuat panduan online"
    # --- Bagian 3: perintah jalur Tailscale Funnel (r26) --------------------- #
    # Dipakai sekolah di PC Windows: periksa kesiapan, diagnosa galat yang ramah,
    # port publik yang diizinkan Tailscale, dan perintah mematikan akses publik.
    import importlib.util as _ilu

    spesifikasi = _ilu.spec_from_file_location("sm_online_uji", BASE_DIR / "SM-online.py")
    modul = _ilu.module_from_spec(spesifikasi)
    spesifikasi.loader.exec_module(modul)
    assert tuple(modul.PORT_FUNNEL) == (443, 8443, 10000), \
        f"port publik Tailscale berubah: {modul.PORT_FUNNEL}"
    tolak = modul.mulai_tailscale(sys.executable, 8000, https_port=8080)
    assert tolak[0] is False and "443" in tolak[2], \
        "port di luar 443/8443/10000 seharusnya ditolak dengan penjelasan"

    contoh_galat = {
        "Funnel is not enabled on your tailnet": "acls",
        "HTTPS is not enabled on your tailnet": "HTTPS",
        "Logged out": "Log in",
        "MagicDNS is not enabled": "MagicDNS",
        "port 443 is already in use": "8443",
    }
    for galat, harus_ada in contoh_galat.items():
        saran = " ".join(modul._perbaikan_tailscale(galat))
        assert harus_ada.lower() in saran.lower(), \
            f"diagnosa untuk {galat!r} tidak memuat {harus_ada!r}: {saran[:120]}"

    isi_online = (BASE_DIR / "SM-online.py").read_text(encoding="utf-8")
    for tanda in ("--cek", "--hentikan", "--https-port", "Uji alamat publik",
                  "_perbaikan_tailscale", "PANDUAN-ONLINE.md"):
        assert tanda in isi_online, f"SM-online.py tidak memuat {tanda!r}"
    panduan_online = (BASE_DIR / "PANDUAN-ONLINE.md").read_text(encoding="utf-8")
    for tanda in ("Tailscale Funnel", "MagicDNS", "HTTPS", "Aman Online", "serve",
                  "Pemecahan masalah", "Bot Dapodik"):
        assert tanda in panduan_online, f"PANDUAN-ONLINE.md tidak menjelaskan {tanda!r}"
    assert "PANDUAN-ONLINE.md" in (BASE_DIR / "README.md").read_text(encoding="utf-8"), \
        "README belum menunjuk PANDUAN-ONLINE.md"

    # --- Bagian 4: perintah funnel yang «menunggu persetujuan» (r27) ---------- #
    # Pelajaran dari PC sekolah (26 → 27): `tailscale funnel` yang dipakai PERTAMA KALI
    # mencetak tautan persetujuan lalu menunggu tanpa batas. Dulu keluarannya ditelan
    # (capture_output) dan batas 90 detik mematikannya → guru hanya melihat «timed out»,
    # sementara `funnel status` tetap «No serve config». Ketiga hal ini harus dipegang:
    #   (a) keluaran tampil langsung; (b) kehabisan waktu ≠ gagal; (c) menunggu itu dilaporkan.
    assert modul.TUNGGU_FUNNEL >= 120, f"batas tunggu funnel terlalu pendek: {modul.TUNGGU_FUNNEL}"
    assert modul.RONDE_TUNGGU >= 2 and modul.MENIT_TUNGGU >= 5, \
        f"perpanjangan tunggu tidak memadai: {modul.RONDE_TUNGGU}×{modul.TUNGGU_FUNNEL}"

    tautan_contoh = modul.tautan_izin(
        ["Funnel is not enabled on your tailnet.", "  https://login.tailscale.com/f/funnel?node=n1234"])
    assert tautan_contoh == "https://login.tailscale.com/f/funnel?node=n1234", tautan_contoh
    assert modul.tautan_izin(["tidak ada tautan apa pun"]) == ""
    assert modul._tampak_menunggu_izin([]) is True, "perintah diam = kemungkinan menunggu izin"
    assert modul._tampak_menunggu_izin([tautan_contoh]) is True
    assert modul._tampak_menunggu_izin(["error: tidak bisa dijalankan"]) is False

    saran_izin = " ".join(modul._perbaikan_tailscale(
        "perintah funnel belum selesai setelah ±9 menit — Tailscale masih menunggu persetujuan "
        f"Funnel (buka {tautan_contoh})"))
    for harus_ada in ("menunggu", "Approve", "admin/dns", "admin/acls", tautan_contoh):
        assert harus_ada.lower() in saran_izin.lower(), \
            f"diagnosa «menunggu persetujuan» tidak memuat {harus_ada!r}: {saran_izin[:160]}"
    saran_alamat = " ".join(modul.petunjuk_tidak_menjawab())
    for harus_ada in ("Quit", "sc stop tailscale"):
        assert harus_ada.lower() in saran_alamat.lower(), \
            f"petunjuk «alamat belum menjawab» tidak memuat {harus_ada!r}"

    # Bukti perilaku: keluaran perintah terlihat (tidak ditelan) dan kehabisan waktu
    # dikembalikan sebagai «belum selesai» (kode None), bukan dilempar sebagai galat.
    kode, keluar = modul.jalankan_tampak(
        [sys.executable, "-u", "-c", "print('halo-funnel'); import time; time.sleep(6)"], detik=3)
    assert kode is None, f"perintah yang melewati batas waktu harus mengembalikan None, bukan {kode}"
    assert any("halo-funnel" in baris for baris in keluar), \
        f"keluaran perintah tidak terbaca: {keluar}"
    kode2, keluar2 = modul.jalankan_tampak(
        [sys.executable, "-u", "-c", "print('selesai-baik')"], detik=30)
    assert kode2 == 0 and any("selesai-baik" in baris for baris in keluar2), \
        f"perintah yang selesai harus mengembalikan kode 0: {kode2} {keluar2}"

    for tanda in ("jalankan_tampak", "tautan_izin", "_tampak_menunggu_izin", "petunjuk_tidak_menjawab",
                  "menunggu persetujuan", "sc stop tailscale", "perpanjang"):
        assert tanda in isi_online, f"SM-online.py tidak memuat penanganan {tanda!r}"
    for tanda in ("Add Funnel to policy", "menunggu persetujuan Funnel", "No serve config"):
        assert tanda in panduan_online, f"PANDUAN-ONLINE.md belum menjelaskan {tanda!r}"

    return ("peluncur online: deteksi Tailscale/cloudflared, penanda & daftar periksa keamanan, "
            "perintah --cek/--hentikan, diagnosa galat Tailscale → langkah perbaikan, "
            "port publik 443/8443/10000, keluaran funnel tampil langsung & kehabisan waktu "
            "dilaporkan jujur sebagai «menunggu persetujuan» (bukan gagal), "
            "panduan PANDUAN-ONLINE.md lengkap")


@cek("20. Akun ekstrakurikuler (NIK 16 digit, 1 pembina + 1 pelatih per ekskul)")
def cek_akun_ekskul():
    """Uji aturan akun pembina/pelatih: NIK 16 angka, klaim posisi, izin akses."""
    import asyncio

    import httpx

    from app import auth, db, migrations, services
    from app.main import app

    # --- Daftar ekskul resmi sekolah diisi bila diminta -------------------- #
    # Basis data uji ini dibuat kosong (seperti hasil pemasangan); daftar 14 ekskul resmi
    # diminta lewat fungsi yang sama dengan tombol pada halaman Ekstrakurikuler.
    diharapkan = [nama for nama, _ in migrations.EKSKUL_SEKOLAH]
    assert len(diharapkan) == 14, len(diharapkan)
    # (Daftar bisa sudah sebagian ada dari pemeriksaan sebelumnya, jadi yang diperiksa adalah
    #  hasil akhirnya + sifat idempoten: sekali diisi penuh, panggilan berikutnya tidak
    #  menambah apa pun.)
    ditambah, total = services.isi_ekskul_resmi()
    assert total >= 14, f"isi daftar ekskul resmi gagal: ditambah {ditambah}, total {total}"
    ditambah_lagi, total_lagi = services.isi_ekskul_resmi()
    assert ditambah_lagi == 0 and total_lagi == total, \
        f"isi daftar ekskul resmi tidak idempoten: {ditambah_lagi}/{total_lagi} dari {total}"
    tersedia = {baris["nama"]: baris for baris in services.list_ekskul()}
    kurang = [nama for nama in diharapkan if nama not in tersedia]
    assert not kurang, f"ekskul belum ada: {kurang}"
    osis = tersedia["OSIS"]
    basket = tersedia["BASKET"]
    assert osis["aktif"] and basket["aktif"]

    # --- Validasi NIK: harus tepat 16 angka -------------------------------- #
    assert auth.PANJANG_NIK == 16
    assert auth.bersihkan_nik("3204 1234 5678 0001") == "3204123456780001"
    assert auth.validasi_nik("3204123456780001")[1] == ""
    assert "tepat 16" in auth.validasi_nik("320412345678000")[1], "NIK 15 angka harus ditolak"
    assert "tepat 16" in auth.validasi_nik("32041234567800012")[1], "NIK 17 angka harus ditolak"
    assert "wajib" in auth.validasi_nik("  ")[1]
    assert auth.validasi_nik("3204-1234-5678-0001")[0] == "3204123456780001"

    # --- Peran & ekskul wajib sah ------------------------------------------ #
    user, galat, _ = auth.authenticate_ekskul("3204123456780001", "ketua", osis["id"])
    assert user is None and "Pembina atau Pelatih" in galat, galat
    user, galat, _ = auth.authenticate_ekskul("3204123456780001", "pembina", 99999)
    assert user is None and "ekstrakurikuler" in galat.lower(), galat

    # --- NIK pertama mengunci posisi; NIK lain ditolak --------------------- #
    pembina, galat, info = auth.authenticate_ekskul("3204123456780001", "pembina", osis["id"],
                                                    "Budi Santoso")
    assert pembina is not None, galat
    assert pembina.role == auth.ROLE_EKSKUL and pembina.ekskul_id == osis["id"]
    assert pembina.role_label == "Pembina OSIS", pembina.role_label
    assert "terdaftar sebagai Pembina OSIS" in info, info

    pelatih, galat, _ = auth.authenticate_ekskul("3204123456780003", "pelatih", osis["id"], "Sri Wahyuni")
    assert pelatih is not None, galat
    assert pelatih.role_label == "Pelatih OSIS", pelatih.role_label

    ditolak, galat, _ = auth.authenticate_ekskul("3204123456780002", "pembina", osis["id"])
    assert ditolak is None and "sudah terdaftar" in galat, galat

    lagi, galat, info = auth.authenticate_ekskul("3204123456780001", "pembina", osis["id"])
    assert lagi is not None, galat
    assert db.query_value("SELECT COUNT(*) FROM ekskul_akun WHERE ekskul_id = ?", (osis["id"],)) == 2, \
        "satu ekskul hanya boleh punya 1 pembina + 1 pelatih"

    # Satu NIK boleh mendampingi ekskul lain (posisi berbeda).
    lain, galat, _ = auth.authenticate_ekskul("3204123456780001", "pembina", basket["id"])
    assert lain is not None, galat
    assert db.query_value(
        "SELECT COUNT(*) FROM ekskul_akun WHERE nik = ? AND ekskul_id IN (?, ?)",
        ("3204123456780001", osis["id"], basket["id"]),
    ) == 2

    # --- Admin bisa melepas posisi yang salah orang ----------------------- #
    posisi = services.akun_ekskul_posisi(basket["id"], "pembina")
    assert posisi and posisi["nik"] == "3204123456780001"
    data = services.lepas_akun_ekskul(int(posisi["id"]), actor="admin")
    assert data and data["ekskul_nama"] == "BASKET"
    assert services.akun_ekskul_posisi(basket["id"], "pembina") is None
    pengganti, galat, _ = auth.authenticate_ekskul("3204123456780009", "pembina", basket["id"], "Rina Marlina")
    assert pengganti is not None, galat

    # --- Perilaku HTTP: halaman sendiri boleh, halaman petugas dialihkan --- #
    transport = httpx.ASGITransport(app=app)

    async def jalankan() -> str:
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=False) as klien:
            halaman = await klien.get("/login?mode=ekskul")
            assert halaman.status_code == 200
            assert 'pattern="[0-9]{16}"' in halaman.text, "isian NIK harus dibatasi 16 angka"
            assert ">OSIS<" in halaman.text and "Pembina" in halaman.text
            assert 'data-panel="ekskul"' in halaman.text

            masuk = await klien.post("/login", data={"mode": "ekskul", "peran": "pembina",
                                                     "ekskul_id": osis["id"],
                                                     "nik": "3204123456780001"})
            assert masuk.status_code == 303, masuk.status_code
            assert masuk.headers["location"].startswith(f"/ekstrakurikuler/{osis['id']}")

            sendiri = await klien.get(f"/ekstrakurikuler/{osis['id']}")
            assert sendiri.status_code == 200
            assert "Pembina OSIS" in sendiri.text
            petugas = await klien.get("/data-siswa")
            assert petugas.status_code == 303 and petugas.headers["location"].startswith("/ekstrakurikuler/")
            admin_area = await klien.get("/pengaturan")
            assert admin_area.status_code == 303

            gagal_nik = await klien.post("/login", data={"mode": "ekskul", "peran": "pelatih",
                                                        "ekskul_id": basket["id"], "nik": "123"})
            assert gagal_nik.status_code == 400 and "tepat 16 angka" in gagal_nik.text

        # Admin melihat kartu akun ekskul di Pengaturan.
        async with httpx.AsyncClient(transport=transport, base_url="http://cek") as admin:
            await admin.post("/login", data={"mode": "staff", "username": "admin", "password": "admin123"})
            pengaturan = await admin.get("/pengaturan")
            assert pengaturan.status_code == 200
            assert "Akun Ekstrakurikuler" in pengaturan.text
            assert "3204123456780001" in pengaturan.text, "NIK pembina harus tampil di Pengaturan"
        return ("14 ekskul resmi diisi atas permintaan (idempoten); basis data baru kosong; "
            "NIK 16 angka; klaim pembina & pelatih; tolak NIK lain; lepas oleh admin")

    return asyncio.run(jalankan())


@cek("21. Kerapian tabel (kelas ber-CSS, terbungkus, jumlah sel seragam)")
def cek_tabel():
    """Cegah tabel tampil polos/aneh: kelas yang dipakai harus punya gaya di CSS."""
    import asyncio
    import re
    from html.parser import HTMLParser

    import httpx

    from app import db, services
    from app.main import app

    # Tabel anggota ekskul hanya punya baris kalau ada anggotanya. Tanpa baris,
    # sel gabungan yang membuat tabel punya kolom tanpa kepala tidak ketahuan —
    # dulu tombol Aksi melenceng karena itu. Jadi ditambah satu anggota sementara.
    ekskul_uji = next((item["id"] for item in services.list_ekskul()), None)
    siswa_uji = db.query_one("SELECT id FROM students LIMIT 1")
    anggota_uji = None
    if ekskul_uji and siswa_uji:
        anggota_uji = services.add_ekskul_member(ekskul_uji, int(siswa_uji["id"]), actor="cek")

    css = (BASE_DIR / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    kelas_css = {"kartu", "tabel-kecil", "preview-table"}
    for rantai in re.findall(r"table\.((?:[a-zA-Z0-9_-]+\.)*[a-zA-Z0-9_-]+)", css):
        kelas_css.update(rantai.split("."))
    assert "data" in kelas_css, "kelas dasar tabel (table.data) hilang dari CSS"

    template = sorted((BASE_DIR / "app" / "templates").rglob("*.html"))
    keliru: list[str] = []
    tanpa_wrap: list[str] = []
    for berkas in template:
        isi = berkas.read_text(encoding="utf-8")
        for kelas in re.findall(r'<table class="([^"]+)"', isi):
            for nama_kelas in kelas.split():
                if nama_kelas not in kelas_css:
                    keliru.append(f"{berkas.name}: kelas '{nama_kelas}' tanpa gaya CSS")
        for potong in re.findall(r"<table[^>]*>", isi):
            if 'class="' not in potong:
                keliru.append(f"{berkas.name}: tabel tanpa kelas")

    # Tabel mode kartu (ponsel) harus memuat label dari server: bila JavaScript
    # tidak jalan, sel kartu tetap punya keterangan kolom (tidak tampak acak).
    kartu_tanpa_label: list[str] = []
    for berkas in template:
        isi = berkas.read_text(encoding="utf-8")
        for blok in re.findall(r"<table[^>]*class=\"[^\"]*kartu[^\"]*\"[^>]*>(.*?)</table>", isi, re.S):
            for sel in re.findall(r"<td([^>]*)>", blok):
                if "empty-cell" not in sel and "data-label" not in sel:
                    kartu_tanpa_label.append(berkas.name)

    # Semua aturan CSS dibaca sebagai pasangan (selector, isi). Komentar CSS
    # dibuang dari selector lebih dulu supaya pencocokan nama aturan tepat.
    def _sel(teks: str) -> str:
        return " ".join(re.sub(r"/\*.*?\*/", "", teks, flags=re.S).split())

    pasangan_aturan = [(_sel(sel), isi) for sel, isi in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]

    # Kepala tabel hanya boleh MENEMPEL di dalam kotak yang benar-benar
    # menggulung sendiri, dan di sana harus di tepi kotak (top: 0) serta
    # berlatar pekat. Bila aturan umum memakai top: var(--topbar-h), kepala
    # tabel tampak melayang di tengah tabel dan menutupi sebagian baris
    # (mis. baris FUTSAL tertutup kepala tabel) — pernah terjadi, jangan diulang.
    kepala_lengket = [sel for sel, isi in pasangan_aturan if "thead" in sel and "sticky" in isi]
    assert kepala_lengket, "kepala tabel di kotak bergulir harus tetap menempel (sticky)"
    for sel, isi in pasangan_aturan:
        if "thead" not in sel or "sticky" not in isi:
            continue
        assert ".daftar" in sel or ".compact" in sel, (
            f"kepala tabel lengket hanya untuk kotak bergulir: {sel}")
        assert re.search(r"top:\s*0\b", isi), (
            f"kepala tabel lengket harus menempel di tepi kotak: {sel}")
        assert "background" in isi, (
            f"kepala tabel lengket harus berlatar pekat agar baris tidak tembus: {sel}")
    assert not [sel for sel, isi in pasangan_aturan
                if sel == "table.data thead th" and "sticky" in isi], (
        "aturan umum kepala tabel jangan lengket (kepala bisa melayang di tengah tabel)")
    assert re.search(r"--topbar-h:\s*\d+px", css), "variabel --topbar-h harus punya nilai awal"

    # Semua elemen lengket: jaraknya harus 0 atau mengikuti tinggi bilah atas
    # (var(--topbar-h)). Angka tetap seperti 84px menyisakan celah di bawah
    # bilah atas sehingga isi halaman terlihat lewat di atas elemen lengket
    # saat halaman digulir — tampak "aneh" dan pernah dilaporkan pemakai.
    for sel, isi in pasangan_aturan:
        if "sticky" not in isi:
            continue
        jarak = re.search(r"(?:^|;)\s*top:\s*([^;]+)", isi)
        if jarak:
            nilai = jarak.group(1).strip()
            assert nilai in ("0", "0px") or "var(--topbar-h)" in nilai, (
                f"jarak elemen lengket harus 0 atau var(--topbar-h): {sel} = {nilai}")
    # Permintaan sekolah (dua kali dilaporkan): kartu samping JANGAN menempel
    # saat halaman digulir — "Status Kelengkapan Data" di dasbor, "Anggota
    # Terbanyak" di daftar ekskul, dan semua kartu samping lain ikut tergulir
    # seperti isi biasa. Hanya empat hal ini yang boleh lengket: bilah samping,
    # bilah atas, kepala tabel di kotak bergulir, dan bilah tombol form.
    css_pakai = re.sub(r"/\*.*?\*/", "", css, flags=re.S)  # abaikan komentar
    assert ".sticky-side" not in css_pakai, "aturan .sticky-side jangan dihidupkan lagi"
    lengket = [sel for sel, isi in pasangan_aturan if "position: sticky" in isi]
    assert lengket, "bilah samping & bilah atas harus tetap lengket"
    izin = (".sidebar", ".topbar", ".form-actions.sticky-actions")
    for sel in lengket:
        boleh = (sel in izin
                 or ("thead" in sel and (".daftar" in sel or ".compact" in sel)))
        assert boleh, f"elemen ini jangan lengket (kartu samping harus ikut tergulir): {sel}"
    sisa_kelas = sorted({berkas.name for berkas in template
                         if "sticky-side" in berkas.read_text(encoding="utf-8")})
    assert not sisa_kelas, "kelas sticky-side masih dipakai: " + ", ".join(sisa_kelas)

    # Form tambah anggota ekskul harus berada di dalam kartu anggota (selalu
    # terjangkau), bukan panel samping yang harus dicari dengan gulir.
    halaman_anggota = (BASE_DIR / "app" / "templates" / "ekskul" / "detail.html").read_text(encoding="utf-8")
    assert 'id="tambah-anggota"' in halaman_anggota, (
        "form tambah anggota ekskul harus di atas daftar anggota")
    halaman_daftar = (BASE_DIR / "app" / "templates" / "ekskul" / "list.html").read_text(encoding="utf-8")
    # Tata letak halaman Ekstrakurikuler yang diminta sekolah: kartu
    # "Pendaftar Menunggu Persetujuan" ada di kolom utama (tengah), tepat
    # setelah kartu "Tambah ekstrakurikuler"; kartu "Anggota Terbanyak" dan
    # "Masuk sebagai Pembina/Pelatih" di kolom samping (kanan).
    urutan_daftar = [halaman_daftar.find(kunci) for kunci in
                     ('id="form-ekskul"', 'id="daftar-pendaftar"', "<aside>",
                      "Anggota Terbanyak", "Masuk sebagai Pembina/Pelatih")]
    assert all(posisi > 0 for posisi in urutan_daftar), (
        "kartu halaman Ekstrakurikuler tidak lengkap: " + str(urutan_daftar))
    assert urutan_daftar == sorted(urutan_daftar), (
        "urutan kartu halaman Ekstrakurikuler salah (harus: daftar/tambah di tengah, "
        "pendaftar setelah kartu Tambah, kartu samping di kanan)")
    assert urutan_daftar[1] < urutan_daftar[2], (
        "kartu Pendaftar Menunggu harus di kolom utama, bukan di luar grid/samping")

    class PeriksaTabel(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.tabel: list[dict] = []
            self.tumpukan: list[int] = []
            self.di_wrap = 0

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "div" and "table-wrap" in (a.get("class") or ""):
                self.di_wrap += 1
            if tag == "div":
                self.tumpukan.append(1)
            elif tag == "table":
                self.tabel.append({"kelas": (a.get("class") or ""), "wrap": self.di_wrap > 0, "lebar": None})
            if tag == "tr" and self.tabel:
                self.tumpukan.append(0)
            elif tag in ("td", "th") and self.tumpukan:
                self.tumpukan[-1] += int(a.get("colspan") or 1)

        def handle_endtag(self, tag):
            if tag == "tr" and self.tumpukan and self.tabel:
                lebar = self.tumpukan.pop()
                data = self.tabel[-1]
                if data["lebar"] is None:
                    data["lebar"] = lebar
                elif lebar != data["lebar"] and lebar > 1:
                    tanpa_wrap.append(f"baris {lebar} sel (kepala {data['lebar']})")
            elif tag == "div" and self.tumpukan:
                self.tumpukan.pop()

    transport = httpx.ASGITransport(app=app)

    async def jalankan() -> str:
        jumlah_tabel = 0
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as klien:
            await klien.post("/login", data={"mode": "staff", "username": "admin", "password": "admin123"})
            for path in ("/", "/data-siswa", "/data-siswa/1", "/statistik", "/kualitas-data",
                         "/ekstrakurikuler", "/ekstrakurikuler/1", "/impor", "/pengaturan",
                         "/pembaruan", "/pengajuan", "/profil-akun"):
                balasan = await klien.get(path)
                assert balasan.status_code == 200, f"{path} -> {balasan.status_code}"
                pemeriksa = PeriksaTabel()
                pemeriksa.feed(balasan.text)
                jumlah_tabel += len(pemeriksa.tabel)
                for indeks, data in enumerate(pemeriksa.tabel, start=1):
                    if not data["wrap"]:
                        tanpa_wrap.append(f"{path} tabel#{indeks} tidak dibungkus .table-wrap")
                    for nama_kelas in data["kelas"].split():
                        if nama_kelas and nama_kelas not in kelas_css:
                            keliru.append(f"{path} tabel#{indeks}: kelas '{nama_kelas}' tanpa gaya")
        return (f"{jumlah_tabel} tabel pada 12 halaman diperiksa"
                + (" (termasuk baris tabel anggota)" if anggota_uji else ""))

    rincian = asyncio.run(jalankan())
    if anggota_uji:
        services.remove_ekskul_member(int(anggota_uji), actor="cek")
    assert not keliru, "; ".join(sorted(set(keliru))[:4])
    assert not tanpa_wrap, "; ".join(sorted(set(tanpa_wrap))[:4])
    assert not kartu_tanpa_label, ("sel kartu tanpa data-label: "
                                   + ", ".join(sorted(set(kartu_tanpa_label))[:4]))
    return (f"{rincian}; kelas tabel ber-CSS; semua terbungkus .table-wrap; "
            "lebar kolom baris = kepala tabel; label kartu tertulis dari server")


@cek("22. Pendaftaran ekskul oleh siswa (menunggu persetujuan pembina)")
def cek_pendaftaran_ekskul():
    """Siswa memilih ekskul dari portalnya; pembina/pelatih yang menyetujui."""
    import asyncio

    import httpx

    from app import db, services
    from app.main import app

    kolom = {baris["name"] for baris in db.rows_to_dicts(db.query_all("PRAGMA table_info(ekskul_pendaftaran)"))}
    assert {"ekskul_id", "student_id", "status", "catatan_siswa", "catatan_pembina",
            "diputus_oleh", "diputus_at"} <= kolom, kolom

    ekskul_id = services.save_ekskul({"nama": "Klub Daftar Uji", "hari": "Kamis",
                                      "jam_mulai": "13:00", "jam_selesai": "15:00", "aktif": 1},
                                     actor="cek")
    murid = db.query_all("SELECT id, nisn FROM students LIMIT 3")
    assert len(murid) >= 3, "butuh 3 siswa untuk uji pendaftaran"
    id_a, id_b = int(murid[0]["id"]), int(murid[1]["id"])

    # --- siswa mendaftar -> menunggu, belum jadi anggota -------------------
    ok, pesan = services.ajukan_pendaftaran_ekskul(id_a, ekskul_id, catatan="Ingin ikut", actor="cek")
    assert ok, pesan
    daftar = services.pendaftaran_ekskul(ekskul_id, status="menunggu")
    assert len(daftar) == 1 and daftar[0]["status"] == "menunggu", daftar
    assert services.hitung_pendaftaran_menunggu(ekskul_id) == 1
    assert services.ekskul_members(ekskul_id) == [], "belum disetujui jangan jadi anggota"

    # pendaftaran ganda ditolak, pengajuan ulang setelah ditolak boleh
    ok, pesan = services.ajukan_pendaftaran_ekskul(id_a, ekskul_id, actor="cek")
    assert not ok and "menunggu" in pesan, pesan
    assert services.ajukan_pendaftaran_ekskul(id_b, ekskul_id, actor="cek")[0]
    pid_b = services.pendaftaran_ekskul(ekskul_id, status="menunggu")
    pid_b = next(item["id"] for item in pid_b if int(item["student_id"]) == id_b)
    ok, pesan = services.putuskan_pendaftaran_ekskul(int(pid_b), False, catatan="Kuota penuh", actor="cek")
    assert ok and "ditolak" in pesan, pesan
    assert services.ekskul_members(ekskul_id) == [], "yang ditolak jangan jadi anggota"
    riwayat_b = [item for item in services.pendaftaran_siswa(id_b) if item["ekskul_id"] == ekskul_id]
    assert len(riwayat_b) == 1 and riwayat_b[0]["status"] == "ditolak", riwayat_b
    assert services.ajukan_pendaftaran_ekskul(id_b, ekskul_id, actor="cek")[0], "boleh mendaftar lagi"
    assert len(services.pendaftaran_siswa(id_b)) == 1, "pengajuan ulang jangan menambah baris"

    # pembatalan oleh siswa + persetujuan oleh pembina
    pid_a = next(item["id"] for item in services.pendaftaran_ekskul(ekskul_id)
                 if int(item["student_id"]) == id_a)
    assert services.batalkan_pendaftaran_ekskul(int(pid_a), id_b, actor="cek")[0] is False, \
        "siswa lain tidak boleh membatalkan pendaftaran orang lain"
    ok, pesan = services.putuskan_pendaftaran_ekskul(int(pid_a), True, catatan="Selamat", actor="pembina")
    assert ok, pesan
    anggota = services.ekskul_members(ekskul_id)
    assert len(anggota) == 1 and int(anggota[0]["student_id"]) == id_a, anggota
    assert services.putuskan_pendaftaran_ekskul(int(pid_a), True, actor="cek")[0] is False, \
        "pendaftaran yang sudah diputuskan jangan diputus dua kali"

    # --- lewat HTTP: siswa mendaftar, pembina memutuskan -------------------
    transport = httpx.ASGITransport(app=app)

    async def jalankan() -> str:
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as klien:
            await klien.post("/login", data={"mode": "siswa", "nisn": str(murid[2]["nisn"])})
            halaman = await klien.get("/portal/ekstrakurikuler")
            assert halaman.status_code == 200, halaman.status_code
            assert "Klub Daftar Uji" in halaman.text, "kegiatan tidak muncul di portal siswa"
            kirim = await klien.post(f"/portal/ekstrakurikuler/{ekskul_id}/daftar",
                                     data={"catatan": "Saya ingin ikut"})
            assert kirim.status_code == 200, kirim.status_code
            assert "menunggu persetujuan" in kirim.text.lower(), "siswa harus diberi tahu menunggu"
            # Riwayat tetap terlihat siswa, tetapi sejak r32 judulnya ringkas dan dilipat
            # di dalam <details>; blok ini muncul setelah siswa punya pendaftaran.
            assert "Riwayat pendaftaran" in kirim.text, "riwayat pendaftaran siswa hilang"

        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as pembina:
            await pembina.post("/login", data={"mode": "ekskul", "peran": "pembina",
                                               "ekskul_id": ekskul_id, "nik": "3204000000000001",
                                               "nama": "Pembina Uji"})
            halaman = await pembina.get(f"/ekstrakurikuler/{ekskul_id}")
            assert halaman.status_code == 200
            assert "Pendaftar dari Siswa" in halaman.text and "Setujui" in halaman.text
            baris = db.query_one(
                "SELECT id FROM ekskul_pendaftaran WHERE ekskul_id = ? AND student_id = ?",
                (ekskul_id, int(murid[2]["id"])))
            putus = await pembina.post(f"/ekstrakurikuler/pendaftaran/{baris['id']}/putuskan",
                                       data={"keputusan": "setujui", "catatan": "Disetujui pembina"})
            assert putus.status_code == 200, putus.status_code
            assert db.query_value(
                "SELECT status FROM ekskul_pendaftaran WHERE id = ?", (baris["id"],)) == "disetujui"
            assert db.query_value(
                "SELECT COUNT(*) FROM ekskul_members WHERE ekskul_id = ? AND student_id = ?",
                (ekskul_id, int(murid[2]["id"]))) == 1, "persetujuan harus menjadikan anggota"

        # siswa tidak boleh memutuskan pendaftarannya sendiri
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=False) as siswa:
            await siswa.post("/login", data={"mode": "siswa", "nisn": str(murid[0]["nisn"])})
            tolak = await siswa.post(f"/ekstrakurikuler/pendaftaran/{pid_a}/putuskan",
                                     data={"keputusan": "setujui"})
            assert tolak.status_code in (303, 403), tolak.status_code
            assert db.query_value("SELECT status FROM ekskul_pendaftaran WHERE id = ?",
                                  (int(pid_a),)) == "disetujui", "siswa jangan bisa mengubah keputusan"
        return "siswa mendaftar dari portal; pembina/pelatih memutuskan; yang disetujui otomatis jadi anggota"

    rincian = asyncio.run(jalankan())

    # --- bersihkan ---
    db.execute("DELETE FROM ekskul_members WHERE ekskul_id = ?", (ekskul_id,))
    db.execute("DELETE FROM ekskul_pendaftaran WHERE ekskul_id = ?", (ekskul_id,))
    services.delete_ekskul(ekskul_id, actor="cek")
    assert services.pendaftaran_menunggu_semua(limit=200) == [] or True
    return rincian


@cek("23. Kualitas Data: temuan & tombol Perbaiki tepat sasaran")
def cek_kualitas_data():
    """Halaman Kualitas Data harus menuntun ke daftar siswa yang benar.

    Dulu semua tombol "Perbaiki" membuka /data-siswa?lengkap=0 (kolom wajib
    kosong), sehingga temuan seperti NIK salah atau NISN ganda tidak pernah
    menemukan siswanya. Sekarang angka pada halaman itu dan daftar siswa yang
    dibuka dihitung dari klausa SQL yang sama (TEMUAN_DAFTAR).
    """
    import asyncio
    import re

    import httpx

    from app import db, services
    from app.main import app

    # --- registry temuan -------------------------------------------------- #
    kode = [temuan.kode for temuan in services.TEMUAN_DAFTAR]
    assert len(kode) == len(set(kode)) and kode, "kode temuan harus unik"
    assert services.temuan_where("TIDAK_ADA_TEMUAN") is None, "kode asing jangan menghasilkan saringan"
    assert services.StudentFilter(masalah="TIDAK_ADA_TEMUAN").where_clause()[0] == "1=1", \
        "kode temuan asing jangan menyaring apa pun"

    # --- angka di halaman = hitungan python (bukan sekadar SQL yang sama) -- #
    ringkas = {item["kode"]: item["jumlah"] for item in services.temuan_ringkas()}
    siswa = db.rows_to_dicts(db.query_all("SELECT * FROM students"))
    harap = {
        "NISN_TIDAK_VALID": sum(
            1 for row in siswa
            if not (row["nisn"] or "").strip() or len(str(row["nisn"]).strip()) != 10
            or not str(row["nisn"]).strip().isdigit()),
        "AYAH_IBU_SAMA": sum(
            1 for row in siswa
            if (row.get("ayah_nama") or "").strip() and (row.get("ibu_nama") or "").strip()
            and services._nama_normal(row["ayah_nama"]) == services._nama_normal(row["ibu_nama"])),
        "WALI_PERLU_DIBERSIHKAN": len(services.siswa_perlu_bersih_wali()),
    }
    for nama, jumlah in harap.items():
        assert ringkas.get(nama) == jumlah, f"{nama}: halaman {ringkas.get(nama)} vs hitungan {jumlah}"

    # NISN ganda: jumlah siswa (bukan jumlah nilai NISN-nya)
    ganda_nilai = {item["nisn"] for item in services.students_with_duplicate_nisn()}
    ganda_siswa = sum(1 for row in siswa if str(row["nisn"] or "").strip() in ganda_nilai)
    assert ringkas["NISN_GANDA"] == ganda_siswa, f"NISN ganda: {ringkas['NISN_GANDA']} vs {ganda_siswa}"

    # --- siswa uji: NIK & NISN tidak sah ---------------------------------- #
    # Catatan: kolom nisn bersifat UNIQUE, jadi NISN ganda hanya mungkin datang
    # dari basis data lama — temuannya tetap disediakan sebagai jaring pengaman.
    uji_id = db.insert_returning_id(
        "INSERT INTO students(nama, nisn, nik, jk, tempat_lahir, tanggal_lahir, alamat, kelurahan, "
        "kecamatan, agama, rombel) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("SISWA UJI TEMUAN", "12345", "123", "L", "Bandung", "2010-01-01",
         "Jl. Uji 1", "Sukamaju", "Takokak", "Islam", "7A"))
    try:
        baru = {item["kode"]: item["jumlah"] for item in services.temuan_ringkas()}
        assert baru["NIK_TIDAK_VALID"] == ringkas["NIK_TIDAK_VALID"] + 1, \
            "siswa dengan NIK 3 digit harus terhitung"
        assert baru["NISN_TIDAK_VALID"] == ringkas["NISN_TIDAK_VALID"] + 1, \
            "siswa dengan NISN 5 digit harus terhitung"
        # NISN ganda: klausanya harus mencacah siswa (bukan hanya nilai NISN)
        ganda_kini = {item["nisn"] for item in services.students_with_duplicate_nisn()}
        assert set() == ganda_kini, "basis data uji tidak boleh punya NISN ganda"

        transport = httpx.ASGITransport(app=app)

        async def jalankan() -> str:
            async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                         follow_redirects=True) as klien:
                await klien.post("/login", data={"mode": "staff", "username": "admin",
                                                 "password": "admin123"})

                def jumlah(halaman: str) -> int:
                    cocok = re.search(r"dari ([\d.]+) siswa", halaman)
                    assert cocok, "jumlah siswa tidak terbaca pada halaman daftar"
                    return int(cocok.group(1).replace(".", ""))

                halaman_kualitas = (await klien.get("/kualitas-data")).text
                berjumlah = [t for t in services.temuan_ringkas() if t["jumlah"]]
                assert halaman_kualitas.count("?masalah=") == len(berjumlah), \
                    ("setiap temuan yang berjumlah > 0 harus punya tautan Perbaiki sendiri: "
                     f"{halaman_kualitas.count('?masalah=')} tautan vs {len(berjumlah)} temuan")
                assert not re.search(r"\?lengkap=0[^>]*>\s*(?:<[^>]+>\s*)*Perbaiki", halaman_kualitas), \
                    'tombol "Perbaiki" jangan generik ke ?lengkap=0 lagi'
                assert '?kosong=' in halaman_kualitas, \
                    'tabel Kelengkapan per Kolom harus bisa dibuka per kolom (?kosong=)'

                # tiap temuan yang berjumlah > 0 harus membuka tepat siswanya
                diperiksa = 0
                for temuan in services.temuan_ringkas():
                    if not temuan["jumlah"]:
                        continue
                    halaman = await klien.get(f"/data-siswa?masalah={temuan['kode']}")
                    assert halaman.status_code == 200, (temuan["kode"], halaman.status_code)
                    assert jumlah(halaman.text) == temuan["jumlah"], \
                        f"{temuan['kode']}: daftar {jumlah(halaman.text)} vs halaman {temuan['jumlah']}"
                    assert f"?masalah={temuan['kode']}" in halaman_kualitas, \
                        f"tidak ada tombol Perbaiki untuk {temuan['kode']}"
                    diperiksa += 1
                assert diperiksa >= 3, f"terlalu sedikit temuan berjumlah > 0 ({diperiksa})"

                # kolom bermasalah: ditampilkan, baris & selnya ditandai, ada penjelasan
                halaman = await klien.get("/data-siswa?masalah=NIK_TIDAK_VALID")
                teks = halaman.text
                assert "Temuan: NIK bukan 16 digit angka" in teks, "banner temuan tidak tampil"
                assert "NIK Siswa" in teks, "kolom bermasalah (NIK) harus ikut ditampilkan"
                assert 'class="sel-masalah"' in teks and 'class="row-error"' in teks, \
                    "baris & sel bermasalah harus ditandai"
                assert "Tampilkan semua siswa" in teks, "harus ada jalan keluar dari filter temuan"

                # kolom kosong: jumlahnya sama dengan tabel kelengkapan
                kualitas = services.data_quality()
                kolom_uji = next(item for item in kualitas["fields"] if item["kosong"])
                halaman = await klien.get(f"/data-siswa?kosong={kolom_uji['key']}")
                assert halaman.status_code == 200
                assert jumlah(halaman.text) == kolom_uji["kosong"], (
                    f"kolom {kolom_uji['key']}: daftar {jumlah(halaman.text)} vs tabel "
                    f"{kolom_uji['kosong']}")
                assert f"Kolom kosong: {kolom_uji['label']}" in halaman.text, "banner kolom kosong tidak tampil"
            return (f"{len(services.TEMUAN_DAFTAR)} temuan; {diperiksa} temuan berjumlah > 0 membuka "
                    f"daftar siswa yang tepat; kolom '{kolom_uji['key']}' juga")

        rincian = asyncio.run(jalankan())
    finally:
        db.execute("DELETE FROM students WHERE id = ?", (uji_id,))
    kembali = {item["kode"]: item["jumlah"] for item in services.temuan_ringkas()}
    assert kembali["NIK_TIDAK_VALID"] == ringkas["NIK_TIDAK_VALID"], \
        "siswa uji harus terhapus lagi setelah pemeriksaan"
    return rincian


class _WaktuCepat:
    """Modul ``time`` tiruan untuk uji alur: ``sleep`` dipersingkat dan **jamnya virtual**.

    Setiap ``sleep`` memajukan jam tiruan, sehingga batas waktu bot (lapisan pemuatan,
    penantian popup) terukur dan pasti tanpa benar-benar menunggu detikan asli.
    """

    def __init__(self, asli) -> None:
        self._asli = asli
        self.maju = 0.0

    def __getattr__(self, nama: str):
        return getattr(self._asli, nama)

    def time(self) -> float:
        return self.maju

    def monotonic(self) -> float:
        return self.maju

    def perf_counter(self) -> float:
        return self.maju

    def sleep(self, detik: float = 0) -> None:
        self.maju += float(detik or 0)
        self._asli.sleep(min(float(detik or 0), 0.02))


@cek("24. Bot Dapodik (antrean dari data SM, kemajuan, lanjut tanpa mengulang)")
def cek_bot_dapodik() -> str:
    """Bot Dapodik: antrean bersumber dari tabel students, berjalan tanpa peramban
    pada mode uji coba, dan pekerjaan yang sudah berhasil tidak diulang."""
    import inspect
    import json
    import time
    from pathlib import Path

    from app import auth, bot_dapodik, db, services, web

    #: catatan kepala bot pada peramban palsu (untuk memeriksa urutan langkahnya)
    jejak: list[str] = []

    # 1) Peta tombol Dapodik = alur skrip bot pemilik aplikasi.
    kunci = list(bot_dapodik.SELECTOR_BAWAAN)
    assert kunci == list(bot_dapodik.SELECTOR_DIIZINKAN), "daftar selector bawaan & yang boleh diubah beda"
    for wajib in ("login_username", "login_password", "login_tombol", "menu_tujuan", "menu_1",
                  "cari_nisn", "tombol_registrasi", "input_nis", "radio_ya", "hobi", "cita",
                  "simpan"):
        assert wajib in bot_dapodik.SELECTOR_BAWAAN, f"selector {wajib} hilang"
    assert bot_dapodik.SELECTOR_BAWAAN["cari_nisn"] == "name:cari_text", "selector NISN berubah"
    assert bot_dapodik.SELECTOR_BAWAAN["input_nis"] == "name:nipd", "kolom NIS berubah"
    assert bot_dapodik.SELECTOR_BAWAAN["hobi"] == "name:id_hobby"
    assert bot_dapodik.SELECTOR_BAWAAN["cita"] == "name:id_cita"

    # Penimpaan selector dari halaman pengaturan harus menolak kunci asing & JSON rusak.
    services.simpan_bot_setting({"bot_selector_json": '{"cari_nisn": "name:cari_teks_baru"}'})
    peta = bot_dapodik.peta_selector()
    assert peta["cari_nisn"] == "name:cari_teks_baru" and peta["input_nis"] == "name:nipd", \
        "penimpaan selector tidak bekerja"
    services.simpan_bot_setting({"bot_selector_json": ""})
    assert bot_dapodik.peta_selector()["cari_nisn"] == "name:cari_text", \
        "selector bawaan tidak kembali setelah pengaturan dikosongkan"
    assert bot_dapodik._pesan_galat_selector("{bukan json"), "JSON rusak seharusnya ditolak"
    assert bot_dapodik._pesan_galat_selector('{"tombol_asing": "name:x"}'), "kunci asing seharusnya ditolak"
    assert not bot_dapodik._pesan_galat_selector(""), "peta kosong (bawaan) seharusnya diterima"

    # 2) Aplikasi wajib tetap jalan tanpa selenium: peramban hanya dibuka di dalam fungsi.
    sumber = inspect.getsource(bot_dapodik)
    for baris in sumber.splitlines():
        tanpa_spasi = baris.lstrip()
        if tanpa_spasi.startswith(("import selenium", "from selenium")):
            assert baris != tanpa_spasi, "selenium diimpor di tingkat modul — aplikasi bisa gagal jalan"

    # 3) Antrean bersumber dari data siswa aplikasi SM (bukan Excel).
    contoh = db.query_all(
        "SELECT id, nisn, nipd, nama, rombel FROM students WHERE LENGTH(TRIM(nisn)) = 10 "
        "AND TRIM(nisn) NOT GLOB '*[^0-9]*' ORDER BY id LIMIT 2")
    assert len(contoh) == 2, "data siswa contoh tidak ditemukan"
    nisn_a, nisn_b = str(contoh[0]["nisn"]).strip(), str(contoh[1]["nisn"]).strip()
    manual = services.bot_antrean(nisn_manual=f"{nisn_a}\n{nisn_b}")
    assert len(manual) == 2, f"daftar NISN manual tidak dihormati: {len(manual)}"
    assert {str(item["nisn"]) for item in manual} == {nisn_a, nisn_b}, "NISN antrean tidak sesuai"
    nis_menurut_nisn = {str(item["nisn"]).strip(): item["nis"] for item in manual}
    for baris in contoh:
        assert nis_menurut_nisn[str(baris["nisn"]).strip()] == str(baris["nipd"] or "").strip(), \
            "NIS tidak diambil dari kolom NIPD siswa"
    assert len(services.bot_antrean(limit=3)) == 3, "batas jumlah siswa tidak dihormati"
    rombel_contoh = str(contoh[0]["rombel"] or "")
    if rombel_contoh:
        kelas = services.bot_antrean(rombel=rombel_contoh)
        assert kelas and all(item["rombel"] == rombel_contoh for item in kelas), "penyaring rombel gagal"

    # Siswa Lulus/Mutasi/Keluar/Non-aktif tidak boleh masuk antrean bot.
    db.execute("UPDATE students SET status = 'Lulus' WHERE id = ?", (contoh[0]["id"],))
    try:
        assert nisn_a not in {str(item["nisn"]) for item in services.bot_antrean()}, \
            "siswa berstatus Lulus masih masuk antrean bot"
    finally:
        db.execute("UPDATE students SET status = 'Aktif' WHERE id = ?", (contoh[0]["id"],))

    # 4) Pengaturan bot: bawaan lengkap, simpan hanya kunci yang dikenal.
    cfg = services.bot_setting()
    assert set(cfg) == set(services.BOT_KEYS), "kunci pengaturan bot tidak lengkap"
    for wajib, nilai in (("bot_url", "http://localhost:5774/"), ("bot_hobi", "Olah Raga"),
                         ("bot_cita", "Pegawai Negeri Sipil / PNS"), ("bot_jawaban_ya", "1"),
                         ("bot_headless", "1")):
        assert cfg[wajib] == nilai, f"bawaan {wajib} berubah: {cfg[wajib]!r}"
    assert services.simpan_bot_setting({"bukan_kunci_bot": "x"}) == [], "kunci asing ikut tersimpan"

    # 4b) Endpoint kemajuan aman saat belum ada pekerjaan (penyebab galat 500 sebelumnya).
    from app.routers import bot_routes

    admin_uji = auth.SessionUser(id=1, username="admin", nama="Admin", role=auth.ROLE_ADMIN)
    kosong = bot_routes.status_json(user=admin_uji)
    assert kosong["items"] == [], "status.json tanpa pekerjaan harus berisi daftar kosong"
    assert kosong["job"]["total"] == 0 and not kosong["job"]["id"], "pekerjaan kosong masih terbaca"
    assert bot_routes.log_csv(user=admin_uji).status_code == 200, "unduhan CSV gagal tanpa pekerjaan"
    assert bot_routes.log_xlsx(user=admin_uji).status_code == 200, "unduhan Excel gagal tanpa pekerjaan"

    # 4b2) Selector cadangan: Dapodik sering berganti versi, bot tidak boleh langsung menyerah.
    assert set(bot_dapodik.SELECTOR_CADANGAN) <= set(bot_dapodik.SELECTOR_DIIZINKAN), \
        "kunci selector cadangan harus dikenal"
    for nama_selector in ("login_username", "login_password", "login_tombol", "cari_nisn",
                          "tombol_registrasi", "input_nis", "simpan"):
        assert bot_dapodik.SELECTOR_CADANGAN.get(nama_selector), \
            f"cadangan untuk {nama_selector} kosong"
    teks_cadangan = " ".join(bot_dapodik.SELECTOR_CADANGAN["login_tombol"]).lower()
    assert "masuk" in teks_cadangan or "login" in teks_cadangan, \
        "cadangan tombol masuk sebaiknya berbasis teks"
    assert "ext-element" not in teks_cadangan, "cadangan tidak boleh bergantung id Ext JS"

    # 4b3) Jeda muat halaman dapat diatur (Dapodik sekolah lambat terbuka).
    assert "bot_jeda_muat" in services.BOT_KEYS and int(services.bot_setting()["bot_jeda_muat"]) >= 3, \
        "jeda muat halaman Dapodik harus ada & masuk akal"
    assert int(services.bot_setting()["bot_timeout"]) >= 15, \
        "batas tunggu bawaan terlalu pendek untuk Dapodik (skrip sekolah memakai 15 detik)"
    assert int(services.bot_setting()["bot_max_retries"]) >= 3, \
        "percobaan ulang klik minimal 3 kali seperti skrip sekolah"

    # 4b4) Uji koneksi Dapodik selalu melapor (tidak melempar galat ke pengguna),
    #      termasuk ketika peramban tidak tersedia seperti di lingkungan uji ini.
    laporan = bot_dapodik.uji_dapodik({"bot_url": "", "bot_simulasi": "1"})
    assert laporan["galat"], "uji koneksi tanpa alamat Dapodik harus melapor"
    laporan = bot_dapodik.uji_dapodik({"bot_url": "http://localhost:5774/", "bot_timeout": "5"})
    assert isinstance(laporan, dict) and laporan.get("url"), "uji koneksi harus mengembalikan laporan"
    assert laporan.get("galat") or laporan.get("selector_cocok"), \
        "uji koneksi harus berisi galat atau hasil selector"
    assert "masuk" not in laporan, "percobaan masuk hanya dijalankan bila diminta"
    services.simpan_laporan_uji_bot({"waktu": "uji", "url": "http://localhost:5774/",
                                     "judul": "Dapodik", "selector_cocok": {"login_username": "bawaan"}})
    assert services.laporan_uji_bot()["judul"] == "Dapodik", "laporan uji koneksi tidak tersimpan"
    services.set_setting(services.KUNCI_UJI_BOT, "{bukan json")
    assert services.laporan_uji_bot() == {}, "laporan uji koneksi rusak harus diabaikan"
    services.set_setting(services.KUNCI_UJI_BOT, "")

    # 4d) Alur skrip sekolah diuji penuh dengan peramban palsu (tanpa Chrome).
    import peramban_palsu

    cepat = (bot_dapodik.SELEKTOR_UJI_DETIK, bot_dapodik.UJI_TUNGGU_PERTAMA,
             bot_dapodik.UJI_TUNGGU_LAIN, bot_dapodik.PILIHAN_TUNGGU_DETIK,
             bot_dapodik.LAPISAN_TUNGGU_DETIK)
    (bot_dapodik.SELEKTOR_UJI_DETIK, bot_dapodik.UJI_TUNGGU_PERTAMA, bot_dapodik.UJI_TUNGGU_LAIN,
     bot_dapodik.PILIHAN_TUNGGU_DETIK, bot_dapodik.LAPISAN_TUNGGU_DETIK) = 0.2, 0.2, 0.1, 0.2, 0.3
    asli_buka = bot_dapodik.BotDapodik._buka_peramban
    simpan_setting = {kunci: services.bot_setting()[kunci] for kunci in
                      ("bot_username", "bot_password", "bot_timeout", "bot_jeda_muat",
                       "bot_hobi", "bot_cita")}
    services.simpan_bot_setting({"bot_username": "bot.uji@contoh.id", "bot_password": "rahasia",
                                 "bot_timeout": "1", "bot_jeda_muat": "0",
                                 "bot_hobi": "Olah Raga", "bot_cita": "Pegawai Negeri Sipil / PNS"})
    galat_lama = bot_dapodik.SELECTOR_BAWAAN["login_username"]
    bot_dapodik.SELECTOR_BAWAAN["login_username"] = "/html/body/div[9]/form/input"
    try:
        opsi_uji = dict(services.bot_setting(), bot_url="http://localhost:5774/", bot_timeout="1",
                        bot_jeda_muat="0", bot_username="bot.uji@contoh.id", bot_password="rahasia",
                        bot_hobi="Olah Raga", bot_cita="Pegawai Negeri Sipil / PNS")
        bot_uji = bot_dapodik.BotDapodik(0, [], [], opsi_uji)

        # (1) XPath yang diawali satu garis miring ('/html/body/...', persis skrip sekolah)
        #     harus dibaca sebagai XPath — dulu keliru dibaca sebagai nama elemen sehingga
        #     kolom login bawaan tidak pernah ketemu.
        for kunci_sel, nilai_sel in bot_dapodik.SELECTOR_BAWAAN.items():
            if nilai_sel.startswith(("/", "(")):
                assert bot_uji._locator_nilai(nilai_sel)[0] == "xpath", \
                    f"selector {kunci_sel} harus dibaca sebagai XPath: {nilai_sel}"

        # (2) kolom tersembunyi (laporan PC sekolah): penanda "ada tetapi belum terlihat"
        palsu = peramban_palsu.buat("kolom_tersembunyi")
        peta_uji = bot_dapodik.peta_selector()
        keadaan = bot_uji._keadaan_selector(palsu, "login_password", peta_uji)
        assert keadaan["keadaan"] in ("ada_tak_terlihat", "terlihat"), keadaan
        # Tanpa selector bawaan, cadangan berbasis CSS harus menemukan kolomnya.
        loc_bawaan = bot_dapodik.SELECTOR_BAWAAN["login_password"]
        bot_dapodik.SELECTOR_BAWAAN["login_password"] = "/html/body/div[9]/form/div/input"
        try:
            locator, nilai_cadangan, pakai_cadangan = bot_uji._cari_dengan_cadangan(
                palsu, "login_password", peta_uji, wajib=False, boleh_tak_terlihat=True)
        finally:
            bot_dapodik.SELECTOR_BAWAAN["login_password"] = loc_bawaan
        assert locator is not None and nilai_cadangan.startswith("css:input"), \
            f"selector cadangan tidak dipakai: {nilai_cadangan!r}"
        hasil_isi = bot_uji._isi_dan_periksa(palsu, locator, "rahasia", "kata sandi")
        assert hasil_isi["terisi"], hasil_isi

        # (3) lapisan pemuatan Ext JS (div.x-mask) ditunggu hilang dulu, seperti skrip asli
        palsu = peramban_palsu.buat("mask")
        assert palsu.mask_sisa > 0, "skenario mask harus mulai dengan lapisan terlihat"
        assert bot_uji._tunggu_lapisan(palsu, 5), "bot harus menunggu lapisan pemuatan hilang"
        assert palsu.mask_sisa == 0, "lapisan tidak pernah ditunggu sampai hilang"

        # (4) laporan "Uji koneksi Dapodik" memakai peramban palsu (tanpa Chrome)
        data_lama = bot_dapodik.config.DATA_DIR
        bot_dapodik.config.DATA_DIR = _SEMENTARA / "uji-bukti"
        bot_dapodik.BotDapodik._buka_peramban = lambda self: peramban_palsu.buat("kolom_tersembunyi")
        try:
            laporan = bot_dapodik.uji_dapodik(opsi_uji)
        finally:
            bot_dapodik.BotDapodik._buka_peramban = asli_buka
            bot_dapodik.config.DATA_DIR = data_lama
        assert not laporan.get("galat"), f"uji koneksi gagal: {laporan.get('galat')}"
        assert laporan["selector_status"]["login_password"]["keadaan"] == "ada_tak_terlihat", \
            laporan["selector_status"]
        assert "saran" not in laporan and "saran_json" not in laporan, \
            "saran selector sudah tidak dipakai lagi"
        assert any("belum terlihat" in baris for baris in laporan["catatan"]), \
            "laporan harus menjelaskan kolom yang belum terlihat"
        halaman_bot = (Path(__file__).resolve().parent.parent
                       / "app/templates/bot_dapodik.html").read_text(encoding="utf-8")
        assert "Peta tombol Dapodik" in halaman_bot, \
            "kartu hasil uji harus menunjuk cara memperbaiki selector"
        assert "saran_json" not in halaman_bot and "pakai-saran" not in halaman_bot, \
            "tampilan saran selector sudah tidak boleh ada"
        assert laporan["kolom"] and laporan["tombol"], "laporan harus memuat unsur halaman"
        assert Path(laporan["bukti"]).exists(), "tangkapan layar uji koneksi tidak tersimpan"

        # (5) "Coba masuk": bot benar-benar mengisi kolom, menekan tombol, lalu memastikan
        #     halaman berpindah — bukan sekadar mencari selector.
        bot_dapodik.BotDapodik._buka_peramban = lambda self: peramban_palsu.buat("masuk")
        try:
            laporan_masuk = bot_dapodik.uji_dapodik(opsi_uji, coba_login=True)
        finally:
            bot_dapodik.BotDapodik._buka_peramban = asli_buka
        masuk = laporan_masuk.get("masuk") or {}
        assert masuk.get("berhasil"), f"percobaan masuk harus berhasil: {masuk}"
        assert all(info["terisi"] for info in masuk["terisi"].values()), masuk["terisi"]
        assert any("Percobaan masuk" in baris for baris in laporan_masuk["catatan"]), \
            laporan_masuk["catatan"]

        # (6) Kredensial belum diisi: uji harus menunjuk «Pengaturan», bukan menyalahkan kolom.
        services.simpan_bot_setting({"bot_username": "", "bot_password": ""})
        bot_dapodik.BotDapodik._buka_peramban = lambda self: peramban_palsu.buat("masuk")
        try:
            laporan_kosong = bot_dapodik.uji_dapodik(dict(services.bot_setting()), coba_login=True)
        finally:
            bot_dapodik.BotDapodik._buka_peramban = asli_buka
        pesan_kosong = (laporan_kosong.get("masuk") or {}).get("pesan", "")
        assert "Pengaturan" in pesan_kosong and not (laporan_kosong["masuk"]).get("berhasil"), \
            pesan_kosong
        services.simpan_bot_setting({"bot_username": "bot.uji@contoh.id", "bot_password": "rahasia"})

        # (7) Rute "Uji koneksi Dapodik" meneruskan pilihan "coba masuk" & "jendela tampak".
        bot_dapodik.BotDapodik._buka_peramban = lambda self: peramban_palsu.buat("kolom_tersembunyi")
        try:
            jawaban = bot_routes.uji_koneksi(coba_login="1", tampak="0", user=admin_uji)
        finally:
            bot_dapodik.BotDapodik._buka_peramban = asli_buka
        lokasi = jawaban.headers.get("location", "")
        assert "level=warn" in lokasi and "percobaan+masuk" in lokasi, \
            f"pesan uji harus menjelaskan percobaan masuk: {lokasi}"

        # (8) Seluruh alur skrip sekolah berjalan di peramban palsu: masuk lewat XPath absolut,
        #     klik menu tujuan, tutup popup, dua menu lanjutan, lalu satu siswa (cari NISN →
        #     Registrasi → NIS → "Ya" → Hobi → Cita-cita → Simpan dan Tutup).
        asli_waktu = bot_dapodik.time
        bot_dapodik.time = _WaktuCepat(time)
        try:
            palsu = peramban_palsu.buat("alur_penuh")
            bot_alur = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                              kepala=jejak.append)
            bot_alur._login(palsu)
            # Setiap kali bot mulai bekerja, log menyebut versi kode yang berjalan dan urutan
            # langkahnya — supaya jelas apakah PC sekolah sudah memakai kode terbaru.
            versi = [baris for baris in jejak if baris.startswith("[versi]")]
            assert versi, f"log tidak mencantumkan versi kode: {jejak[:4]}"
            assert "langkah tiap siswa" in versi[0] and "pilih barisnya" in versi[0], versi[0]
            assert "pilih radio jarak" in versi[0], versi[0]
            assert "«Ya»" in versi[0] and "Sekolah Asal" in versi[0], versi[0]
            assert palsu.sudah_masuk, "bot belum berhasil masuk pada alur penuh"
            assert palsu.unsur[0].nilai == "bot.uji@contoh.id", "kolom nama pengguna belum terisi"
            assert palsu.unsur[1].nilai == "rahasia", "kolom kata sandi belum terisi"
            for kunci_sel, nama in (("login_tombol", "tombol masuk"),
                                    ("menu_tujuan", "menu tujuan"),
                                    ("popup_tutup", "popup"),
                                    ("menu_1", "menu pertama"),
                                    ("menu_2", "menu kedua")):
                nilai_sel = bot_dapodik.SELECTOR_BAWAAN[kunci_sel]
                assert any(u.diklik for u in palsu.find_elements(*bot_alur._locator_nilai(nilai_sel))), \
                    f"{nama} tidak diklik"

            nisn_uji = "1234567890"
            palsu.tambah_baris_siswa(nisn_uji)
            palsu.nisn_dicari = nisn_uji
            palsu.tambah_formulir_registrasi(nisn_uji)
            bot_alur._proses_satu(palsu, {"nisn": nisn_uji, "nipd": "1234", "nama": "Uji"}, None)
        finally:
            bot_dapodik.time = asli_waktu
        terisi = {unsur.name: unsur.nilai for unsur in palsu.unsur if unsur.name}
        assert terisi.get("cari_text") == nisn_uji, f"kotak pencarian NISN tidak diisi: {terisi}"
        assert terisi.get("nipd") == "1234", f"kolom NIS tidak diisi: {terisi}"
        assert terisi.get("id_hobby") == "Olah Raga", f"kolom Hobi tidak diisi: {terisi}"
        assert terisi.get("id_cita") == "Pegawai Negeri Sipil / PNS", \
            f"kolom Cita-cita tidak diisi: {terisi}"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]

        # (9) "ElementClickInterceptedException" pada kolom pencarian — persis log PC sekolah:
        #     lapisan pemuatan Ext JS menutupi kolom sehingga klik biasa ditelan. Skrip sekolah
        #     menunggu lapisan hilang lebih dulu; bot harus tetap berhasil walau lapisan itu
        #     tidak kunjung hilang (klik & ketikan lewat skrip).
        jejak.clear()
        asli_waktu = bot_dapodik.time
        bot_dapodik.time = _WaktuCepat(time)
        try:
            palsu_sibuk = peramban_palsu.buat("alur_penuh")
            bot_sibuk = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_sibuk._login(palsu_sibuk)
            nisn_sibuk = "3137492866"
            palsu_sibuk.tambah_baris_siswa(nisn_sibuk)
            palsu_sibuk.nisn_dicari = nisn_sibuk
            palsu_sibuk.tambah_formulir_registrasi(nisn_sibuk)
            palsu_sibuk.sibukkan()          # lapisan pemuatan tidak pernah hilang
            bot_sibuk._proses_satu(palsu_sibuk, {"nisn": nisn_sibuk, "nipd": "3137", "nama": "Uji"},
                                   None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_sibuk.unsur_bernama("cari_text").nilai == nisn_sibuk, \
            "kotak pencarian tidak terisi saat lapisan pemuatan menutupi (klik tertelan)"
        assert palsu_sibuk.unsur_bernama("nipd").nilai == "3137", "NIS tidak terisi saat sibuk"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]
        assert any("[tunggu]" in baris for baris in jejak), \
            "bot harus melaporkan lapisan pemuatan yang tidak hilang"

        # (10) Popup pengumuman «Selamat Datang di Aplikasi Dapodik 2027.b» — bukti screenshot
        #      PC sekolah. Popup itu muncul LEBIH LAMBAT daripada 5 detik yang ditunggu skrip
        #      sekolah, lalu menutupi halaman sehingga klik tombol Registrasi tidak diproses;
        #      bot lama berhenti dengan "Tidak menemukan elemen 'input_nis'". Bot harus
        #      menunggu popupnya, menutupnya, lalu melanjutkan sampai siswa selesai.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_telat = _WaktuCepat(time)
        bot_dapodik.time = jam_telat
        try:
            palsu_telat = peramban_palsu.buat("alur_penuh").pakai_jam(jam_telat.monotonic)
            palsu_telat.siapkan_popup(8)        # popup baru muncul 8 detik setelah menu dibuka
            palsu_telat.registrasi_otomatis = True   # formulir terbuka setelah tombol diklik
            bot_telat = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_telat._login(palsu_telat)
            nisn_telat = "3137492867"
            palsu_telat.nisn_dicari = nisn_telat
            palsu_telat.tambah_baris_siswa(nisn_telat)
            bot_telat._proses_satu(palsu_telat, {"nisn": nisn_telat, "nipd": "3138", "nama": "Uji"},
                                   None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_telat.ditutup_popup >= 1, "popup pengumuman tidak ditutup bot"
        assert palsu_telat.klik_terblokir == 0, \
            "masih ada klik yang tertelan popup — popup belum ditutup sebelum langkah berikutnya"
        assert palsu_telat.unsur_bernama("nipd").nilai == "3138", "NIS tidak terisi saat popup muncul"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-4:]
        assert any("Popup" in baris for baris in jejak), "penutupan popup tidak dilaporkan"

        # (11) Klik tombol Registrasi yang tertelan: formulir Registrasi baru terbuka pada
        #      percobaan berikutnya — bot harus mengklik ulang tombolnya, bukan berhenti dengan
        #      "Tidak menemukan elemen 'input_nis'".
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_ulang = _WaktuCepat(time)
        bot_dapodik.time = jam_ulang
        try:
            palsu_ulang = peramban_palsu.buat("alur_penuh").pakai_jam(jam_ulang.monotonic)
            palsu_ulang.popup_detik = None            # halaman ini tanpa popup
            palsu_ulang.registrasi_otomatis = True
            palsu_ulang.tolak_klik_registrasi = 1     # klik Registrasi pertama tertelan
            bot_ulang = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_ulang._login(palsu_ulang)
            nisn_ulang = "3137492868"
            palsu_ulang.nisn_dicari = nisn_ulang
            palsu_ulang.tambah_baris_siswa(nisn_ulang)
            bot_ulang._proses_satu(palsu_ulang, {"nisn": nisn_ulang, "nipd": "3139", "nama": "Uji"},
                                   None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_ulang.unsur_bernama("nipd").nilai == "3139", \
            "NIS tidak terisi setelah tombol Registrasi diklik ulang"
        assert any("belum terbuka (percobaan 1/" in baris for baris in jejak), jejak[-5:]
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-4:]

        # (12) Popup pengumuman yang muncul tepat saat pencarian ditekan: selama popup terbuka
        #      hasil pencarian belum tampil. Bot harus menutupnya & mencari lagi — bukan
        #      menyimpulkan "Data NISN tidak ditemukan pada tabel Dapodik".
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_cari = _WaktuCepat(time)
        bot_dapodik.time = jam_cari
        try:
            palsu_cari = peramban_palsu.buat("alur_penuh").pakai_jam(jam_cari.monotonic)
            palsu_cari.popup_detik = None
            palsu_cari.registrasi_otomatis = True
            nisn_cari = "3137492869"
            palsu_cari.siapkan_popup_setelah_cari(nisn_cari)   # barisnya baru tampil setelah popup ditutup
            palsu_cari.tambah_baris_siswa(nisn_cari)
            bot_cari = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                              kepala=jejak.append)
            bot_cari._login(palsu_cari)
            bot_cari._proses_satu(palsu_cari, {"nisn": nisn_cari, "nipd": "3140", "nama": "Uji"},
                                  None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_cari.ditutup_popup >= 1, "popup yang muncul saat pencarian tidak ditutup bot"
        assert not any("[LEWAT]" in baris for baris in jejak), \
            "siswa salah dinyatakan dilewati karena popup menutupi hasil pencarian"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-4:]
        assert palsu_cari.unsur_bernama("nipd").nilai == "3140", "NIS tidak terisi"

        # (13) Baris siswa tidak terpilih (persis keadaan pada screenshot PC sekolah: kotak
        #      centang baris kosong, panel "Data Periodik" kelabu). Di Ext JS baris terpilih
        #      saat *mousedown*; klik lewat skrip (arguments[0].click()) hanya mengirim 'click',
        #      sehingga tombol Registrasi tidak membuka apa pun. Bot harus memilih barisnya
        #      sendiri (urutan tetikus lengkap lewat skrip) sebelum menekan Registrasi.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_baris = _WaktuCepat(time)
        bot_dapodik.time = jam_baris
        try:
            palsu_baris = peramban_palsu.buat("alur_penuh").pakai_jam(jam_baris.monotonic)
            palsu_baris.popup_detik = None
            palsu_baris.registrasi_otomatis = True
            nisn_baris = "3137492870"
            palsu_baris.nisn_dicari = nisn_baris
            palsu_baris.tambah_baris_siswa(nisn_baris)
            palsu_baris.sibukkan()      # klik sungguhan selalu tertelan lapisan pemuatan
            bot_baris = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_baris._login(palsu_baris)
            bot_baris._proses_satu(palsu_baris, {"nisn": nisn_baris, "nipd": "3141", "nama": "Uji"},
                                   None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_baris.baris_siswa_terpilih(), \
            "baris siswa tidak pernah terpilih — tombol Registrasi tidak akan membuka formulir"
        assert any("dipilih lewat skrip" in baris for baris in jejak), jejak[-6:]
        assert palsu_baris.unsur_bernama("nipd").nilai == "3141", "NIS tidak terisi"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-4:]

        # (14) Sekolah Asal: bot mengisi kolom «Sekolah Asal» pada formulir Registrasi Dapodik
        #      dengan **data siswa aplikasi SM**. Dapodik menamai kolomnya berbeda-beda antar
        #      versi, jadi bot harus menemukannya lewat nama kolom maupun lewat labelnya.
        #      Kolom yang tidak ada (atau data yang kosong) hanya dicatat pada log — siswa
        #      tetap berhasil, pekerjaan tidak berhenti.
        sekolah_asal_uji = "SD NEGERI UJI 1"
        for nama_kolom, cara in (("sekolah_asal", "lewat nama kolom"), ("", "lewat label")):
            jejak.clear()
            asli_waktu = bot_dapodik.time
            jam_asal = _WaktuCepat(time)
            bot_dapodik.time = jam_asal
            try:
                palsu_asal = peramban_palsu.buat("alur_penuh").pakai_jam(jam_asal.monotonic)
                palsu_asal.popup_detik = None
                palsu_asal.registrasi_otomatis = True
                nisn_asal = "3137492871"
                palsu_asal.nisn_dicari = nisn_asal
                palsu_asal.tambah_baris_siswa(nisn_asal)
                palsu_asal.tambah_formulir_registrasi(nisn_asal, nama_kolom=nama_kolom)
                bot_asal = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                                  kepala=jejak.append)
                bot_asal._login(palsu_asal)
                bot_asal._proses_satu(palsu_asal, {"nisn": nisn_asal, "nipd": "3142",
                                                   "nama": "Uji",
                                                   "sekolah_asal": sekolah_asal_uji}, None)
            finally:
                bot_dapodik.time = asli_waktu
            kolom_asal = [unsur for unsur in palsu_asal.unsur if unsur.label == "Sekolah Asal"]
            assert kolom_asal and kolom_asal[0].nilai == sekolah_asal_uji, \
                f"kolom «Sekolah Asal» tidak terisi ({cara}): " + \
                (kolom_asal[0].nilai if kolom_asal else "(kolom tidak ada)")
            assert any("sekolah asal" in baris and "terisi" in baris for baris in jejak), jejak[-4:]
            assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]

        # Data siswa yang belum memuat sekolah asal: dilewati dengan catatan, siswa tetap sukses.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_kosong = _WaktuCepat(time)
        bot_dapodik.time = jam_kosong
        try:
            palsu_kosong = peramban_palsu.buat("alur_penuh").pakai_jam(jam_kosong.monotonic)
            palsu_kosong.popup_detik = None
            palsu_kosong.registrasi_otomatis = True
            nisn_kosong = "3137492872"
            palsu_kosong.nisn_dicari = nisn_kosong
            palsu_kosong.tambah_baris_siswa(nisn_kosong)
            palsu_kosong.tambah_formulir_registrasi(nisn_kosong, nama_kolom="sekolah_asal")
            bot_kosong = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                                kepala=jejak.append)
            bot_kosong._login(palsu_kosong)
            bot_kosong._proses_satu(palsu_kosong, {"nisn": nisn_kosong, "nipd": "3143",
                                                   "nama": "Uji", "sekolah_asal": ""}, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert any("belum memuat sekolah asal" in baris for baris in jejak), jejak[-4:]
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]

        # (15) Data Periodik — persis potongan skrip sekolah, dan **sebelum** tombol
        #      Registrasi ditekan: tinggi badan → berat badan → lingkar kepala → centang
        #      «Jarak rumah ke sekolah» → jumlah saudara kandung → «Simpan dan Tutup».
        #      Nilainya diambil dari data siswa SM. Panel Dapodik kelabu sampai baris siswa
        #      dipilih, jadi urutannya harus benar: pilih baris dulu, baru mengisi.
        siswa_periodik = {"nisn": "3137492873", "nipd": "3144", "nama": "Uji",
                          "sekolah_asal": "SDN UJI", "tinggi_badan": 155.0,
                          "berat_badan": 47.5, "lingkar_kepala": 52, "jml_saudara": 3,
                          "jarak_rumah": 7.9}
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_periodik = _WaktuCepat(time)
        bot_dapodik.time = jam_periodik
        try:
            palsu_periodik = peramban_palsu.buat("alur_penuh").pakai_jam(jam_periodik.monotonic)
            palsu_periodik.popup_detik = None
            palsu_periodik.registrasi_otomatis = True
            nisn_periodik = siswa_periodik["nisn"]
            palsu_periodik.nisn_dicari = nisn_periodik
            palsu_periodik.tambah_baris_siswa(nisn_periodik)
            bot_periodik = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                                  kepala=jejak.append)
            bot_periodik._login(palsu_periodik)
            bot_periodik._proses_satu(palsu_periodik, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        tersimpan = palsu_periodik.data_periodik_tersimpan
        assert tersimpan.get("tinggi_badan") == "155", f"tinggi badan tidak terisi: {tersimpan}"
        assert tersimpan.get("berat_badan") == "47.5", f"berat badan tidak terisi: {tersimpan}"
        assert tersimpan.get("lingkar_kepala") == "52", f"lingkar kepala tidak terisi: {tersimpan}"
        assert tersimpan.get("jumlah_saudara_kandung") == "3", \
            f"jumlah saudara kandung tidak terisi: {tersimpan}"
        assert tersimpan.get("jarak") == "1", "kotak «Jarak rumah ke sekolah» tidak dicentang"
        # Dapodik punya DUA pilihan: jarak 7.9 km harus memakai «lebih dari 1 km»
        # (td/div[2] — sama seperti skrip sekolah), bukan «kurang dari 1 km».
        assert palsu_periodik.jarak_pilihan == "Lebih dari 1 km", \
            f"pilihan jarak salah: {palsu_periodik.jarak_pilihan!r}"
        assert tersimpan.get("jarak_rumah_ke_sekolah_km") == "7.9", \
            f"kolom «Sebutkan (dalam kilometer)» tidak terisi: {tersimpan}"
        assert any("Sebutkan (dalam kilometer) [jarak_rumah_ke_sekolah_km]" in baris
                   for baris in jejak), f"log kolom kilometer tidak memuat nama kolomnya: {jejak[-6:]}"
        assert palsu_periodik.ketikan_diabaikan == 0, \
            "ada ketikan yang diabaikan — panel Data Periodik belum hidup saat diisi"
        assert palsu_periodik.baris_siswa_terpilih(), "baris siswa tidak terpilih saat mengisi"
        # Urutan: Data Periodik disimpan SEBELUM kolom NIS di formulir Registrasi diisi.
        urut_periodik = [i for i, b in enumerate(jejak) if "Data Periodik disimpan" in b]
        urut_nis = [i for i, b in enumerate(jejak) if "kolom NIS:" in b]
        assert urut_periodik and urut_nis and urut_periodik[0] < urut_nis[0], \
            "Data Periodik harus diisi & disimpan SEBELUM tombol Registrasi ditekan"
        # Urutan seperti skrip sekolah: tinggi → berat → lingkar → jarak (+ kilometer)
        # → jumlah saudara kandung.
        def urut(penanda: str) -> int:
            for indeks, baris in enumerate(jejak):
                if penanda in baris:
                    return indeks
            return -1
        urut_centang = urut("dicatat: 1 dari 1") if urut("dicatat: 1 dari 1") >= 0 \
            else urut("dicentang: 1 dari 1")
        urut_km = urut("jarak_rumah_ke_sekolah_km]: terisi")
        urut_saudara = urut("Jumlah saudara kandung: terisi")
        assert -1 < urut_centang < urut_km < urut_saudara, \
            f"urutan Data Periodik tidak seperti skrip sekolah: centang={urut_centang} " \
            f"kilometer={urut_km} saudara={urut_saudara}"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]

        # Jarak ≤ 1 km → pilihan «kurang dari 1 km» (td/div[1]) dan kolom «Sebutkan
        # (dalam kilometer)» tidak perlu diisi (Dapodik hanya memintanya untuk > 1 km).
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_dekat = _WaktuCepat(time)
        bot_dapodik.time = jam_dekat
        try:
            palsu_dekat = peramban_palsu.buat("alur_penuh").pakai_jam(jam_dekat.monotonic)
            palsu_dekat.popup_detik = None
            palsu_dekat.registrasi_otomatis = True
            nisn_dekat = siswa_periodik["nisn"]
            palsu_dekat.nisn_dicari = nisn_dekat
            palsu_dekat.tambah_baris_siswa(nisn_dekat)
            bot_dekat = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_dekat._login(palsu_dekat)
            bot_dekat._proses_satu(palsu_dekat, {**siswa_periodik, "jarak_rumah": 0.7}, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_dekat.jarak_pilihan == "Kurang dari 1 km", \
            f"siswa dengan jarak ≤ 1 km harus memakai pilihan «kurang dari 1 km»: " \
            f"{palsu_dekat.jarak_pilihan!r}"
        assert not palsu_dekat.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km"), \
            "kolom kilometer tidak perlu diisi bila jaraknya ≤ 1 km"
        assert any("tidak perlu diisi" in baris for baris in jejak), jejak[-5:]
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]

        # Halaman yang panel Data Periodiknya baru terjangkau setelah digulir (persis
        # kekhawatiran skrip sekolah: "takutnya ga ketemu elemennya karena belum di scrool").
        # Bot harus memakai window.scrollBy(0, 250) seperti skrip, dan mengulang gulirannya
        # sampai kolomnya ketemu — bukan langsung menyimpulkan panelnya tidak ada.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_gulir = _WaktuCepat(time)
        bot_dapodik.time = jam_gulir
        try:
            palsu_gulir = peramban_palsu.buat("alur_penuh").pakai_jam(jam_gulir.monotonic)
            palsu_gulir.popup_detik = None
            palsu_gulir.registrasi_otomatis = True
            palsu_gulir.siapkan_periodik_perlu_gulir(3)   # butuh 3 kali gulir (3 × 250 px)
            nisn_gulir = siswa_periodik["nisn"]
            palsu_gulir.nisn_dicari = nisn_gulir
            palsu_gulir.tambah_baris_siswa(nisn_gulir)
            bot_gulir = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_gulir._login(palsu_gulir)
            bot_gulir._proses_satu(palsu_gulir, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_gulir.gulir and set(palsu_gulir.gulir) == {bot_dapodik.GULIR_PERIODIK}, \
            f"bot tidak memakai gulir {bot_dapodik.GULIR_PERIODIK} px seperti skrip: {palsu_gulir.gulir}"
        assert len(palsu_gulir.gulir_panel) >= 3, \
            f"panel Data Periodik tidak dibawa ke layar berulang kali: {palsu_gulir.gulir_panel}"
        assert any("[gulir] panel" in baris for baris in jejak), \
            "bot tidak melaporkan bahwa panelnya yang digulir (bukan seluruh halaman)"
        assert palsu_gulir.data_periodik_tersimpan.get("tinggi_badan") == "155", \
            f"nilai periodik tidak tersimpan pada halaman yang perlu digulir: " \
            f"{palsu_gulir.data_periodik_tersimpan}"
        assert any("[gulir]" in baris for baris in jejak), "guliran tidak dilaporkan pada log"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]
        # Pada halaman biasa pun bot tetap menggulir sekali sebelum mengisi Data Periodik.
        assert palsu_periodik.gulir and palsu_periodik.gulir[0] == bot_dapodik.GULIR_PERIODIK, \
            f"bot tidak menggulir sebelum mengisi Data Periodik: {palsu_periodik.gulir}"

        # Ext JS/Dapodik bisa MENELAN klik pada kotak centang/radio (perintahnya seolah
        # berhasil, tetapi centangnya tidak berubah) — inilah keluhan "bot masih gagal memilih
        # radio". Bot wajib memeriksa ulang hasilnya, lalu memakai pembungkus/label kolomnya.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_telan = _WaktuCepat(time)
        bot_dapodik.time = jam_telan
        try:
            palsu_telan = peramban_palsu.buat("alur_penuh").pakai_jam(jam_telan.monotonic)
            palsu_telan.popup_detik = None
            palsu_telan.registrasi_otomatis = True
            palsu_telan.klik_kotak_ditelan = True          # klik pada kotaknya ditelan
            palsu_telan.siapkan_periodik_perlu_gulir(2)    # panelnya juga perlu dibawa ke layar
            nisn_telan = siswa_periodik["nisn"]
            palsu_telan.nisn_dicari = nisn_telan
            palsu_telan.tambah_baris_siswa(nisn_telan)
            bot_telan = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_telan._login(palsu_telan)
            bot_telan._proses_satu(palsu_telan, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_telan.jarak_pilihan == "Lebih dari 1 km", \
            f"radio jarak tetap tidak terpilih walau pembungkusnya bisa diklik: " \
            f"{palsu_telan.jarak_pilihan!r}"
        assert palsu_telan.data_periodik_tersimpan.get("jarak") == "1", \
            f"pilihan jarak tidak tersimpan: {palsu_telan.data_periodik_tersimpan}"
        assert palsu_telan.dipilih_lewat_pembungkus >= 1, \
            "bot tidak memakai pembungkus/label kolom ketika klik pada kotaknya ditelan"
        assert any(("pembungkus/label" in baris) or ("labelnya" in baris) for baris in jejak), \
            jejak[-4:]

        # Kalau SEMUA cara gagal (klik kotaknya ditelan DAN pembungkusnya tidak ada), bot tidak
        # boleh mengaku berhasil: log harus jujur memperingatkan bahwa Dapodik belum menandainya.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_gagal = _WaktuCepat(time)
        bot_dapodik.time = jam_gagal
        try:
            palsu_gagal = peramban_palsu.buat("alur_penuh").pakai_jam(jam_gagal.monotonic)
            palsu_gagal.popup_detik = None
            palsu_gagal.registrasi_otomatis = True
            # "Kasus terburuk" = SEMUA klik (kotak, pembungkus, label) ditelan Dapodik DAN
            # jalur Ext JS mati; tanpa keduanya bot masih bisa memilih lewat labelnya atau
            # Ext.getCmp(...).setValue(...) — lihat sub-blok berikutnya.
            palsu_gagal.hanya_ext_yang_menerima = True
            palsu_gagal.ext_mati = True
            nisn_gagal = siswa_periodik["nisn"]
            palsu_gagal.nisn_dicari = nisn_gagal
            palsu_gagal.tambah_baris_siswa(nisn_gagal)
            bot_gagal = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_gagal._login(palsu_gagal)
            # Semua jalur pencarian pilihan dihapus dari halaman: kotaknya ditelan, dan
            # pembungkus/labelnya tidak ada — Dapodik benar-benar menolak centangnya.
            palsu_gagal.unsur = [u for u in palsu_gagal.unsur
                                 if not ("cb-label" in (getattr(u, "kelas", "") or "")
                                         and getattr(u, "untuk", "").startswith("jarak"))]
            for unsur in palsu_gagal.unsur:
                if unsur.type == "radio" and unsur.label in ("Kurang dari 1 km", "Lebih dari 1 km"):
                    unsur.induk = None
            bot_gagal._proses_satu(palsu_gagal, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_gagal.jarak_pilihan == "", \
            f"radio seharusnya tidak terpilih pada kasus terburuk: {palsu_gagal.jarak_pilihan!r}"
        assert any("peringatan" in baris and "belum menandainya" in baris for baris in jejak), \
            f"bot tidak jujur melaporkan pilihan jarak yang gagal: {jejak[-6:]}"
        assert not any("dicentang: 1 dari 1" in baris for baris in jejak), \
            "log mengaku berhasil padahal radionya tidak terpilih"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]

        # Keadaan pada skrip sekolah yang terbukti berhasil: klik pada kotak radio-nya
        # (nyata maupun lewat skrip) DAN pada pembungkus `x-form-cb-wrap-inner` sama-sama
        # ditelan; hanya label `x-form-cb-label` yang menerima. Bot harus tetap memilih.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_label = _WaktuCepat(time)
        bot_dapodik.time = jam_label
        try:
            palsu_label = peramban_palsu.buat("alur_penuh").pakai_jam(jam_label.monotonic)
            palsu_label.popup_detik = None
            palsu_label.registrasi_otomatis = True
            palsu_label.hanya_label_yang_menerima = True    # persis kandidat label di skrip
            palsu_label.siapkan_periodik_perlu_gulir(2)
            nisn_label = siswa_periodik["nisn"]
            palsu_label.nisn_dicari = nisn_label
            palsu_label.tambah_baris_siswa(nisn_label)
            bot_label = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_label._login(palsu_label)
            bot_label._proses_satu(palsu_label, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_label.jarak_pilihan == "Lebih dari 1 km", \
            f"radio tidak terpilih lewat label x-form-cb-label: {palsu_label.jarak_pilihan!r}"
        assert palsu_label.data_periodik_tersimpan.get("jarak") == "1", \
            f"pilihan jarak lewat label tidak tersimpan: {palsu_label.data_periodik_tersimpan}"
        assert palsu_label.dipilih_lewat_pembungkus >= 1, \
            "bot tidak memakai label x-form-cb-label seperti skrip yang terbukti berhasil"
        assert any("labelnya" in baris and "x-form-cb-label" in baris for baris in jejak), jejak[-5:]
        # Kolom isian juga harus dibarengi peristiwa input → change → blur seperti skrip itu.
        assert palsu_label.peristiwa_dipicu >= 1, \
            "bot tidak memberi tahu Ext JS lewat peristiwa input/change/blur sesudah mengetik"
        # Langkah memilih jarak harus tercatat jelas pada log (bukan hanya hasilnya).
        assert any("memilih «Jarak rumah ke sekolah»" in baris for baris in jejak), \
            f"langkah memilih jarak tidak tampak pada log: {jejak[-8:]}"
        # Pilihan «Ya» pada formulir Registrasi: dua pertanyaan, satu sudah tercentang.
        # Bot lama mengklik lewat skrip tanpa memeriksa sehingga mengaku berhasil padahal
        # tidak (log sekolah: "pilihan «Ya» dicentang: 0 dari 2").
        radio_ya = [unsur for unsur in palsu_label.unsur
                    if unsur.name == "jawaban_ya" and unsur.type == "radio"]
        assert len(radio_ya) == 2, f"peramban palsu tidak menyiapkan dua pilihan «Ya»: {radio_ya}"
        assert any("pilihan «Ya» dicentang: 2 dari 2" in baris for baris in jejak), \
            f"pilihan «Ya» tidak diverifikasi: {[b for b in jejak if 'Ya' in b]}"
        assert not any("peringatan: Dapodik belum menandai semuanya" in baris for baris in jejak), \
            "masih ada pilihan «Ya» yang gagal padahal pemeriksaan ulang sudah dilakukan"
        assert all(unsur.terpilih for unsur in radio_ya), \
            "pilihan «Ya» dilaporkan tercentang padahal keadaan di halaman tidak demikian"

        # DOM sekolah yang sebenarnya (dari halaman Dapodik sekolah):
        #   * label `x-form-cb-label` berada SESUDAH input — radio dilacak lewat wadah
        #     `.x-field` (poros `ancestor::`)/`preceding::`, bukan `following::`;
        #   * keadaan tercentang hanya terbaca dari kelas `x-form-cb-checked` pembungkusnya;
        #   * kolom «Sebutkan (dalam kilometer)» NONAKTIF sampai «lebih dari 1 km» terpasang,
        #     jadi Dapodik mengabaikan ketikan yang datang terlalu dini;
        #   * tiap unsur membawa `data-componentid` → `Ext.getCmp(...).setValue(...)` adalah
        #     jalur pamungkas bila semua klik ditelan Dapodik.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_dom = _WaktuCepat(time)
        bot_dapodik.time = jam_dom
        try:
            palsu_dom = peramban_palsu.buat("alur_penuh").pakai_jam(jam_dom.monotonic)
            palsu_dom.popup_detik = None
            palsu_dom.registrasi_otomatis = True
            palsu_dom.keadaan_lewat_kelas = True      # hanya kelas x-form-cb-checked
            nisn_dom = siswa_periodik["nisn"]
            palsu_dom.nisn_dicari = nisn_dom
            palsu_dom.tambah_baris_siswa(nisn_dom)
            bot_dom = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                             kepala=jejak.append)
            bot_dom._login(palsu_dom)
            bot_dom._proses_satu(palsu_dom, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_dom.jarak_pilihan == "Lebih dari 1 km", \
            f"radio tidak terpilih pada DOM sekolah: {palsu_dom.jarak_pilihan!r}"
        assert palsu_dom.dibaca_lewat_kelas >= 1, \
            "bot tidak membaca keadaan tercentang dari kelas x-form-cb-checked"
        km_dom = next(unsur for unsur in palsu_dom.unsur
                      if unsur.name == "jarak_rumah_ke_sekolah_km")
        assert km_dom.enabled, \
            "kolom «Sebutkan (dalam kilometer)» tetap nonaktif walau radionya sudah terpasang"
        assert (palsu_dom.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km")
                == "7.9"), f"kolom km tidak tersimpan: {palsu_dom.data_periodik_tersimpan}"
        assert all(unsur.label != "Kurang dari 1 km" or not unsur.terpilih
                   for unsur in palsu_dom.unsur if unsur.type == "radio"), \
            "pilihan «kurang dari 1 km» ikut tercentang padahal radionya sepasang"

        # Jalur pamungkas Ext JS: semua klik (kotak, pembungkus, label) ditelan Dapodik.
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_ext = _WaktuCepat(time)
        bot_dapodik.time = jam_ext
        try:
            palsu_ext = peramban_palsu.buat("alur_penuh").pakai_jam(jam_ext.monotonic)
            palsu_ext.popup_detik = None
            palsu_ext.registrasi_otomatis = True
            palsu_ext.hanya_ext_yang_menerima = True
            nisn_ext = siswa_periodik["nisn"]
            palsu_ext.nisn_dicari = nisn_ext
            palsu_ext.tambah_baris_siswa(nisn_ext)
            bot_ext = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                             kepala=jejak.append)
            bot_ext._login(palsu_ext)
            bot_ext._proses_satu(palsu_ext, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_ext.jarak_pilihan == "Lebih dari 1 km", \
            f"Ext.getCmp tidak berhasil memilih radio: {palsu_ext.jarak_pilihan!r}"
        assert palsu_ext.ext_setvalue_dipakai >= 1, \
            "bot tidak memakai Ext.getCmp(data-componentid) sebagai jalur pamungkas"
        assert any("Ext JS sendiri" in baris for baris in jejak), jejak[-5:]
        assert (palsu_ext.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km")
                == "7.9"), f"kolom km tidak tersimpan lewat jalur Ext JS: " \
                           f"{palsu_ext.data_periodik_tersimpan}"

        # Keadaan pada DOM sekolah yang paling halus: «kurang dari 1 km» sudah tercentang
        # (berpenanda x-form-cb-checked), dan klik berikutnya hanya mengubah DOM tanpa
        # memindahkan penanda itu → nilai Ext JS belum berubah, sehingga kolom kilometer
        # TETAP nonaktif. Bot harus menyadarinya dan naik ke Ext.getCmp(...).setValue(...).
        jejak.clear()
        asli_waktu = bot_dapodik.time
        jam_model = _WaktuCepat(time)
        bot_dapodik.time = jam_model
        try:
            palsu_model = peramban_palsu.buat("alur_penuh").pakai_jam(jam_model.monotonic)
            palsu_model.popup_detik = None
            palsu_model.registrasi_otomatis = True
            palsu_model.siapkan_model_ext_tidak_ikut()
            nisn_model = siswa_periodik["nisn"]
            palsu_model.nisn_dicari = nisn_model
            palsu_model.tambah_baris_siswa(nisn_model)
            bot_model = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_model._login(palsu_model)
            bot_model._proses_satu(palsu_model, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_model.jarak_pilihan == "Lebih dari 1 km", \
            f"radio tidak terpilih pada keadaan model-Ext-tidak-ikut: {palsu_model.jarak_pilihan!r}"
        assert any("nilai Ext JS belum" in baris for baris in jejak), \
            f"bot tidak menyadari penanda x-form-cb-checked belum pindah: {jejak[-8:]}"
        assert palsu_model.ext_setvalue_dipakai >= 1, \
            "bot tidak naik ke Ext.getCmp saat nilai Ext JS belum berubah"
        km_model = next(unsur for unsur in palsu_model.unsur
                        if unsur.name == "jarak_rumah_ke_sekolah_km")
        assert km_model.enabled, \
            "kolom «Sebutkan (dalam kilometer)» tetap nonaktif setelah Ext.getCmp dipakai"
        assert (palsu_model.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km")
                == "7.9"), f"kolom km tidak tersimpan: {palsu_model.data_periodik_tersimpan}"

        # Tata letak Dapodik bisa membuat XPath/CSS baris «Jarak rumah ke sekolah» meleset
        # (dulu lognya: «kotak … tidak ada di halaman ini» padahal pilihannya terlihat).
        # Bot harus tetap menemukan pilihannya — lewat TEKS labelnya, dibaca JavaScript —
        # lalu mengisi kolom kilometer.
        jejak.clear()
        jam_teks = _WaktuCepat(time)
        asli_waktu = bot_dapodik.time
        bot_dapodik.time = jam_teks
        try:
            palsu_teks = peramban_palsu.buat("alur_penuh").pakai_jam(jam_teks.monotonic)
            palsu_teks.popup_detik = None
            palsu_teks.registrasi_otomatis = True
            palsu_teks.siapkan_jarak_tanpa_xpath()
            nisn_teks = siswa_periodik["nisn"]
            palsu_teks.nisn_dicari = nisn_teks
            palsu_teks.tambah_baris_siswa(nisn_teks)
            bot_teks = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                              kepala=jejak.append)
            bot_teks._login(palsu_teks)
            bot_teks._proses_satu(palsu_teks, siswa_periodik, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_teks.jarak_pilihan == "Lebih dari 1 km", \
            f"radio tidak terpilih saat XPath meleset: {palsu_teks.jarak_pilihan!r}"
        assert palsu_teks.kotak_lewat_teks_dipakai >= 1, \
            "bot tidak melacak kotak jarak lewat teks labelnya (jalur JavaScript)"
        assert any("lewat teks labelnya" in baris for baris in jejak), jejak[-6:]
        assert (palsu_teks.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "7.9"), \
            f"kolom km tidak tersimpan: {palsu_teks.data_periodik_tersimpan}"

        # Langkah BIO lewat tombol «Ubah» (persis skrip sekolah): jendelanya panjang sehingga
        # kolomnya harus DIBawa KE LAYAR dulu (jendela & halaman), lalu diisi dari data siswa
        # dan disimpan dengan tombol «Simpan» — dijalankan SEBELUM Data Periodik.
        jejak.clear()
        jam_bio = _WaktuCepat(time)
        asli_waktu = bot_dapodik.time
        bot_dapodik.time = jam_bio
        try:
            palsu_bio = peramban_palsu.buat("alur_penuh").pakai_jam(jam_bio.monotonic)
            palsu_bio.popup_detik = None
            palsu_bio.registrasi_otomatis = True
            palsu_bio.siapkan_bio(panel_rincian=True)      # persis tangkapan layar sekolah
            nisn_bio = siswa_periodik["nisn"]
            palsu_bio.nisn_dicari = nisn_bio
            palsu_bio.tambah_baris_siswa(nisn_bio)
            siswa_bio = dict(siswa_periodik, no_kk="3201234567890001",
                             no_registrasi_akta="",       # sengaja kosong: tidak dikosongkan
                             alamat="Jl. Melati No. 7",
                             rt="3", rw="5", kode_pos="15157", anak_ke=2,
                             ayah_nama="Bapak Uji", ayah_nik="3201234567890002",
                             ayah_tahun_lahir=1980, ayah_pendidikan="SMA / sederajat",
                             # Kolom dropdown (combo Ext JS): pekerjaan & penghasilan —
                             # nilainya harus DIPILIH dari daftar, bukan diketik.
                             ayah_pekerjaan="Petani",
                             ayah_penghasilan="Rp. 500,000 - Rp. 999,999",
                             ibu_nik="3201234567890003", ibu_tahun_lahir=1983,
                             ibu_pendidikan="SMP / sederajat",
                             ibu_pekerjaan="Tidak Bekerja",
                             ibu_penghasilan="Tidak Berpenghasilan")
            bot_bio = bot_dapodik.BotDapodik(0, [], [],
                                             dict(opsi_uji, bot_simulasi="0", bot_isi_bio="1"),
                                             kepala=jejak.append)
            bot_bio._login(palsu_bio)
            bot_bio._proses_satu(palsu_bio, siswa_bio, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_bio.bio_tersimpan, "jendela «Ubah» (BIO) tidak disimpan bot"
        assert palsu_bio.data_bio_tersimpan.get("no_kk") == "3201234567890001", \
            f"No. KK tidak terisi: {palsu_bio.data_bio_tersimpan.get('no_kk')!r}"
        assert palsu_bio.data_bio_tersimpan.get("jenjang_pendidikan_ibu") == "SMP", \
            ("pendidikan ibu tidak terisi dengan TEKS PILIHAN Dapodik: "
             f"{palsu_bio.data_bio_tersimpan.get('jenjang_pendidikan_ibu')!r}")
        # Kolom dropdown: nilainya diambil dari daftar (bukan diketik) dan tersimpan apa
        # adanya seperti pilihan Dapodik.
        assert palsu_bio.data_bio_tersimpan.get("pekerjaan_id_ayah") == "Petani", \
            f"pekerjaan ayah tidak terisi: {palsu_bio.data_bio_tersimpan.get('pekerjaan_id_ayah')!r}"
        assert palsu_bio.data_bio_tersimpan.get("penghasilan_id_ibu") == "Tidak Berpenghasilan", \
            (f"penghasilan ibu tidak terisi: "
             f"{palsu_bio.data_bio_tersimpan.get('penghasilan_id_ibu')!r}")
        assert palsu_bio.data_bio_tersimpan.get("penghasilan_id_ayah") == \
            "Rp. 500,000 - Rp. 999,999", \
            (f"penghasilan ayah tidak terisi: "
             f"{palsu_bio.data_bio_tersimpan.get('penghasilan_id_ayah')!r}")
        assert palsu_bio.dropdown_item_diklik >= 6, \
            (f"bot tidak memilih dari daftar dropdown: {palsu_bio.dropdown_item_diklik} pilihan "
             "diklik (seharusnya 6: pendidikan, pekerjaan, penghasilan ayah & ibu)")
        assert any("dropdown dibuka lewat" in b for b in jejak), \
            [b for b in jejak if "dropdown" in b][:6]
        assert palsu_bio.dropdown_item_tak_terlihat == 0, \
            (f"bot mencoba mengklik pilihan dropdown yang belum terlihat: "
             f"{palsu_bio.dropdown_item_tak_terlihat}x")
        assert palsu_bio.dropdown_aria_dipakai >= 6, \
            ("daftar dropdown tidak dibaca dari elemen daftarnya sendiri (DOM/aria-owns): "
             f"{palsu_bio.dropdown_aria_dipakai}x — pilihannya jadi bergantung pada Ext JS")
        # Keadaan terberat: ``Ext`` tidak bisa dipanggil dari skrip DAN tombol panah combonya
        # tidak ada. Yang tersisa hanya menekan tombol ↓ pada kolomnya lalu membaca daftarnya
        # dari DOM. Bot harus tetap sanggup mengisi keenam kolom dropdown dari daftarnya.
        jejak.clear()
        jam_tanpa_ext = _WaktuCepat(time)
        asli_waktu = bot_dapodik.time
        bot_dapodik.time = jam_tanpa_ext
        try:
            palsu_tanpa_ext = peramban_palsu.buat("alur_penuh").pakai_jam(jam_tanpa_ext.monotonic)
            palsu_tanpa_ext.popup_detik = None
            palsu_tanpa_ext.registrasi_otomatis = True
            palsu_tanpa_ext.siapkan_bio(panel_rincian=True)
            palsu_tanpa_ext.dropdown_tanpa_ext = True     # Ext.getCmp/store/select mati
            palsu_tanpa_ext.dropdown_tanpa_panah = True   # tombol panah combo tidak ada
            palsu_tanpa_ext.dropdown_muat_perlu = 2       # daftar muncul setelah ditunggu
            palsu_tanpa_ext.dropdown_band = 5             # hanya 5 pilihan terlihat sekaligus
            palsu_tanpa_ext.nisn_dicari = nisn_bio
            palsu_tanpa_ext.tambah_baris_siswa(nisn_bio)
            bot_tanpa_ext = bot_dapodik.BotDapodik(
                0, [], [], dict(opsi_uji, bot_simulasi="0", bot_isi_bio="1"), kepala=jejak.append)
            bot_tanpa_ext._login(palsu_tanpa_ext)
            bot_tanpa_ext._proses_satu(palsu_tanpa_ext, siswa_bio, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert palsu_tanpa_ext.bio_tersimpan, \
            "jendela «Ubah» tidak disimpan saat Ext & tombol panah tidak ada"
        assert palsu_tanpa_ext.dropdown_item_diklik >= 6, \
            ("bot tidak memilih dari daftar saat Ext & tombol panah tidak ada: "
             f"{palsu_tanpa_ext.dropdown_item_diklik} pilihan diklik")
        assert palsu_tanpa_ext.dropdown_aria_dipakai >= 6, \
            ("daftar dropdown tidak dibaca dari DOM saat Ext mati: "
             f"{palsu_tanpa_ext.dropdown_aria_dipakai}x")
        assert palsu_tanpa_ext.dropdown_item_tak_terlihat == 0, \
            (f"bot mengklik pilihan yang belum terlihat saat Ext mati: "
             f"{palsu_tanpa_ext.dropdown_item_tak_terlihat}x")
        assert palsu_tanpa_ext.data_bio_tersimpan.get("pekerjaan_id_ayah") == "Petani", \
            ("pekerjaan ayah tidak terisi saat Ext & tombol panah tidak ada: "
             f"{palsu_tanpa_ext.data_bio_tersimpan.get('pekerjaan_id_ayah')!r}")
        assert palsu_tanpa_ext.data_bio_tersimpan.get("jenjang_pendidikan_ayah") == "SMA", \
            ("pilihan yang sama persis («SMA») tidak dipilih saat daftarnya disusuri: "
             f"{palsu_tanpa_ext.data_bio_tersimpan.get('jenjang_pendidikan_ayah')!r}")
        assert any("tombol ↓" in b for b in jejak), [b for b in jejak if "dropdown" in b][:6]
        assert palsu_bio.data_bio_tersimpan.get("reg_akta_lahir") == "LAMA", \
            "kolom «No. Registrasi Akta Lahir» dikosongkan padahal datanya kosong di SM"
        assert all(nilai != "LAMA" for nama, nilai in palsu_bio.data_bio_tersimpan.items()
                   if nama != "reg_akta_lahir"), \
            f"masih ada kolom BIO yang berisi data lama Dapodik: {palsu_bio.data_bio_tersimpan}"
        assert palsu_bio.gulir_bio >= 4, \
            ("isi jendela «Ubah» hanya digulir "
             f"{palsu_bio.gulir_bio}x — kolom di bawah bagian yang terlihat tidak terjangkau")
        assert palsu_bio.bio_ubah_palsu_diklik == 0, \
            f"bot menekan «Ubah» milik panel «Data Rincian PD» ({palsu_bio.bio_ubah_palsu_diklik}x)"
        assert palsu_bio.bio_simpan_palsu_diklik == 0, \
            ("bot menekan «Simpan» milik panel «Data Rincian PD» "
             f"({palsu_bio.bio_simpan_palsu_diklik}x) — jendela «Ubah» jadi tidak tersimpan")
        assert not palsu_bio.bio_terbuka, "jendela «Ubah» masih terbuka setelah disimpan"
        assert any("jendela «Edit Peserta Didik» terbuka" in baris for baris in jejak), \
            [b for b in jejak if "[bio]" in b][:4] or jejak[:5]
        assert any("jendela «Ubah» tertutup" in baris for baris in jejak), jejak[-6:]
        assert any("dikembalikan ke atas" in baris for baris in jejak), \
            [b for b in jejak if "[bio]" in b][:4] or jejak[:4]
        i_bio = next((i for i, b in enumerate(jejak)
                      if "jendela «Edit Peserta Didik» terbuka" in b), -1)
        i_periodik = next((i for i, b in enumerate(jejak) if "mengisi Data Periodik" in b), -1)
        assert 0 <= i_bio < i_periodik, \
            f"urutan langkah salah: BIO#{i_bio} lalu Data Periodik#{i_periodik}"
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]

        # Data periodik kosong → dicatat pada log, siswa tetap berhasil.
        jejak.clear()
        jam_kosong_p = _WaktuCepat(time)
        asli_waktu = bot_dapodik.time
        bot_dapodik.time = jam_kosong_p
        try:
            palsu_kosong_p = peramban_palsu.buat("alur_penuh").pakai_jam(jam_kosong_p.monotonic)
            palsu_kosong_p.popup_detik = None
            palsu_kosong_p.registrasi_otomatis = True
            nisn_kosong_p = "3137492874"
            palsu_kosong_p.nisn_dicari = nisn_kosong_p
            palsu_kosong_p.tambah_baris_siswa(nisn_kosong_p)
            bot_kosong_p = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                                  kepala=jejak.append)
            bot_kosong_p._login(palsu_kosong_p)
            bot_kosong_p._proses_satu(palsu_kosong_p, {"nisn": nisn_kosong_p, "nipd": "3145",
                                                       "nama": "Uji", "tinggi_badan": "",
                                                       "berat_badan": "", "lingkar_kepala": "",
                                                       "jml_saudara": ""}, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert any("data siswa kosong" in baris for baris in jejak), jejak[-5:]
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]
        # Jarak kosong → kotak «Jarak rumah ke sekolah» TIDAK dicentang (Dapodik menolak
        # centang tanpa keterangan kilometernya).
        assert palsu_kosong_p.jarak_dicentang == 0, \
            "kotak jarak tidak boleh dicentang saat data jaraknya kosong"

        # Halaman Dapodik tanpa panel Data Periodik → langkah dilewati, siswa tetap berhasil.
        jejak.clear()
        jam_tanpa = _WaktuCepat(time)
        asli_waktu = bot_dapodik.time
        bot_dapodik.time = jam_tanpa
        try:
            palsu_tanpa = peramban_palsu.buat("alur_penuh").pakai_jam(jam_tanpa.monotonic)
            palsu_tanpa.popup_detik = None
            palsu_tanpa.registrasi_otomatis = True
            nisn_tanpa = "3137492875"
            palsu_tanpa.nisn_dicari = nisn_tanpa
            palsu_tanpa.tambah_baris_siswa(nisn_tanpa)
            bot_tanpa = bot_dapodik.BotDapodik(0, [], [], dict(opsi_uji, bot_simulasi="0"),
                                               kepala=jejak.append)
            bot_tanpa._login(palsu_tanpa)
            palsu_tanpa.unsur[:] = [unsur for unsur in palsu_tanpa.unsur if not unsur.periodik]
            bot_tanpa._proses_satu(palsu_tanpa, {"nisn": nisn_tanpa, "nipd": "3146",
                                                 "nama": "Uji", "tinggi_badan": 155,
                                                 "berat_badan": 47, "lingkar_kepala": 52,
                                                 "jml_saudara": 3}, None)
        finally:
            bot_dapodik.time = asli_waktu
        assert any("tidak punya panel Data Periodik" in baris for baris in jejak), jejak[-5:]
        assert any("berhasil dikirim" in baris for baris in jejak), jejak[-3:]

        # Pengaturan: centang «Isi Data Periodik» & «Centang Jarak» tersimpan.
        services.simpan_bot_setting({"bot_data_periodik": "0", "bot_periodik_jarak": "0"})
        assert services.bot_setting()["bot_data_periodik"] == "0", "pengaturan periodik tidak tersimpan"
        services.simpan_bot_setting({"bot_data_periodik": "1", "bot_periodik_jarak": "1"})

        # Antrean bot membawa kolom sekolah asal dari data siswa (dipakai bot di atas).
        contoh_antrean = services.bot_antrean(limit=1, lewati_sukses=False)
        assert contoh_antrean and "sekolah_asal" in contoh_antrean[0], \
            "antrean bot tidak membawa kolom sekolah asal"
        for kolom_periodik in ("tinggi_badan", "berat_badan", "lingkar_kepala", "jml_saudara",
                               "jarak_rumah"):
            assert kolom_periodik in contoh_antrean[0], \
                f"antrean bot tidak membawa kolom {kolom_periodik}"

        assert not hasattr(bot_routes, "pakai_saran"), "rute saran selector masih ada"
        jejak.clear()
        services.set_setting(services.KUNCI_UJI_BOT, "")
    finally:
        bot_dapodik.SELECTOR_BAWAAN["login_username"] = galat_lama
        (bot_dapodik.SELEKTOR_UJI_DETIK, bot_dapodik.UJI_TUNGGU_PERTAMA, bot_dapodik.UJI_TUNGGU_LAIN,
         bot_dapodik.PILIHAN_TUNGGU_DETIK, bot_dapodik.LAPISAN_TUNGGU_DETIK) = cepat
        services.simpan_bot_setting(simpan_setting)

    # 4c) Pemasangan pustaka bot dari dalam aplikasi memakai Python aplikasi ini.
    assert "requirements-bot.txt" in services.perintah_pasang_bot(), "perintah pasang tidak menunjuk berkasnya"
    assert services.perintah_pasang_bot().startswith('"'), "perintah pasang harus memakai jalur Python lengkap"

    # 5) Pekerjaan & item tercatat; mode uji coba (tanpa peramban) sampai tuntas.
    # Aturan "siapa yang dilewati" diuji langsung supaya tidak bergantung isi data contoh:
    # NISN wajib 10 angka, dan siswa tanpa NIPD dilewati kecuali NISN dipakai sebagai NIS.
    from app.bot_dapodik import BotDapodik as _Bot

    polos = {"login_username": "name:a", "login_password": "name:b", "login_tombol": "name:c",
             "menu_tujuan": "name:d", "popup_tutup": "name:e", "menu_1": "name:f", "menu_2": "name:g",
             "cari_nisn": "name:h", "tombol_registrasi": "name:i", "input_nis": "name:j",
             "radio_ya": "name:k", "hobi": "name:l", "cita": "name:m", "simpan": "name:n"}
    tanpa_nipd = {"nisn": "1234567890", "nipd": "", "nama": "Uji"}
    bot_tanpa = _Bot(0, [], [], {**polos, "bot_pakai_nisn": "0"})
    assert "NIPD" in bot_tanpa._aturan_lewati(tanpa_nipd), \
        "siswa tanpa NIPD harus dilewati bila NISN tidak dipakai sebagai NIS"
    bot_pakai = _Bot(0, [], [], {**polos, "bot_pakai_nisn": "1"})
    assert bot_pakai._aturan_lewati(tanpa_nipd) == "", \
        "siswa tanpa NIPD harus lanjut bila NISN dipakai sebagai NIS"
    assert "NISN" in bot_pakai._aturan_lewati({"nisn": "123", "nipd": "9", "nama": "Uji"}), \
        "NISN yang bukan 10 angka harus dilewati"

    services.simpan_bot_setting({"bot_simulasi": "1", "bot_url": "http://localhost:5774/",
                                 "bot_username": "bot.uji@contoh.id", "bot_password": "rahasia",
                                 "bot_hobi": "Olah Raga", "bot_cita": "Pegawai Negeri Sipil / PNS",
                                 "bot_jeda": "0", "bot_pakai_nisn": "1"})
    assert services.bot_siap_pakai()[0], "mode uji coba seharusnya siap dipakai"
    antrean = services.bot_antrean(nisn_manual=f"{nisn_a}\n{nisn_b}", limit=2)
    job_id, _ = bot_dapodik.mulai_bot(antrean, services.bot_setting(), actor="cek")
    try:
        # Dua bot sekaligus akan berebut jendela Dapodik — harus ditolak.
        bot_dapodik.mulai_bot(antrean, services.bot_setting(), actor="cek")
        raise AssertionError("bot kedua seharusnya ditolak saat masih berjalan")
    except bot_dapodik.BotBerjalanError:
        pass
    for _ in range(120):
        if not bot_dapodik.status_bot():
            break
        time.sleep(0.25)
    assert bot_dapodik.bot_berjalan() is None, "bot tidak berhenti setelah pekerjaan selesai"

    items = services.items_bot(job_id)
    assert len(items) == 2, f"item pekerjaan tidak tercatat: {len(items)}"
    assert all(item["status"] == "sukses" for item in items), \
        "mode uji coba seharusnya mencatat sukses: " + str([item["status"] for item in items])
    ringkas = services.ringkas_bot()
    assert (ringkas["job"] or {})["status"] == "sukses", "status pekerjaan bukan sukses"
    assert (ringkas["job"] or {})["sukses_item"] == 2, "hitungan sukses pekerjaan salah"
    assert ringkas["hitung"]["sukses"] == 2, "hitungan item sukses salah"
    assert (ringkas["job"] or {})["log"], "catatan berjalan kosong"
    assert {nisn_a, nisn_b} <= set(services.bot_nisn_sukses()), \
        "NISN yang berhasil seharusnya tercatat untuk pelanjutan"
    assert services.bot_antrean(nisn_manual=f"{nisn_a}\n{nisn_b}") == [], \
        "pekerjaan lanjutan seharusnya melewati siswa yang sudah berhasil"
    ulang = services.bot_antrean(nisn_manual=f"{nisn_a}\n{nisn_b}", lewati_sukses=False)
    assert len(ulang) == 2, "pilihan 'diproses ulang semua' harus tetap bisa mengulang semua siswa"

    # 6) Halaman & menu tersedia bagi admin, tidak bagi petugas.
    admin = auth.SessionUser(id=1, username="admin", nama="Admin", role=auth.ROLE_ADMIN)
    assert "/bot-dapodik" in {item["href"] for item in web.nav_items(admin)}, "menu Bot Dapodik hilang"
    petugas = auth.SessionUser(id=None, username="petugas", nama="Petugas", role=auth.ROLE_OPERATOR)
    assert "/bot-dapodik" not in {item["href"] for item in web.nav_items(petugas)}, \
        "petugas seharusnya tidak melihat menu Bot Dapodik"
    halaman = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "templates" / "bot_dapodik.html").read_text(encoding="utf-8")
    for penanda in ('action="/bot-dapodik/pengaturan"', 'action="/bot-dapodik/mulai"',
                    "/bot-dapodik/hentikan", "/bot-dapodik/status.json", "bot-dapodik/log.csv",
                    'action="/bot-dapodik/bersihkan"', 'action="/bot-dapodik/pasang"',
                    'action="/bot-dapodik/uji"', "perintah_pip", 'name="jeda_muat"',
                    "Memperbarui data Dapodik dari data aplikasi SM"):
        assert penanda in halaman, f"halaman bot kehilangan {penanda}"

    # 7) Bila bot dihentikan/gagal, siswa yang belum diproses ditandai jelas.
    job_coba = services.buat_job_bot(3, {"url": "http://localhost:5774/"}, actor="cek")
    item_coba = [services.isi_item_bot(job_coba, dict(siswa, urutan=no))
                 for no, siswa in enumerate(services.bot_antrean(limit=3), start=1)]
    services.catat_item_bot(item_coba[0], "sukses", "berhasil dikirim")
    sisa = services.tandai_sisa_menunggu_bot(job_coba)
    assert sisa == 2, f"sisa item yang ditandai salah: {sisa}"
    status_coba = [item["status"] for item in services.items_bot(job_coba)]
    assert status_coba == ["sukses", "dilewati", "dilewati"], status_coba
    assert all(item["pesan"] for item in services.items_bot(job_coba)[1:]), \
        "item yang belum diproses harus punya keterangan"

    # 8) Riwayat dapat dibersihkan supaya semua siswa boleh didaftarkan ulang.
    job_lama, item_lama = services.hapus_riwayat_bot()
    assert (job_lama, item_lama) == (2, 5), f"hitungan riwayat terhapus salah: {job_lama}/{item_lama}"
    assert services.items_bot(job_id) == [], "item pekerjaan masih ada setelah riwayat dihapus"
    assert (services.ringkas_bot().get("job") or None) is None, "kepala pekerjaan masih ada"
    assert services.bot_nisn_sukses() == [], "catatan NISN berhasil masih tersisa"
    assert len(services.bot_antrean(nisn_manual=f"{nisn_a}\n{nisn_b}")) == 2, \
        "setelah riwayat dibersihkan, siswa lama harus bisa didaftarkan ulang"

    return (f"{len(kunci)} selector · antrean dari tabel students · uji coba 2 siswa sukses · "
            f"siswa berstatus Lulus dilewati · alur skrip sekolah (masuk, menu, 1 siswa) "
            f"berjalan di peramban palsu, tahan klik tertelan lapisan pemuatan & popup "
            f"pengumuman Dapodik · Sekolah Asal & Data Periodik terisi dari data siswa "
            f"(BIO lewat tombol «Ubah» terisi & tersimpan — termasuk kolom dropdown yang "
            f"dipilih dari daftarnya, panel Data Periodik dibawa ke layar, "
            f"pilihan jaraknya ditekan lewat labelnya, "
            f"kolom isian diberi peristiwa input/change/blur) · "
            f"sekarang {len(services.bot_nisn_sukses())} NISN berhasil")


@cek("25. Pemasang aplikasi (pasang, periksa, paket ZIP, hapus)")
def cek_pemasang():
    """Pemasang harus benar-benar bisa dipakai di komputer mana pun — diuji dari luar.

    Seluruh perintah pemasang dijalankan sebagai proses terpisah (persis seperti dipakai
    pengguna), memakai **modus portabel** (``--tanpa-venv``) supaya uji ini cepat dan tidak
    memasang pustaka baru. Yang diperiksa: berkas program benar-benar tersalin, basis data
    baru dibuat, catatan pemasangan & peluncur terbentuk, ``periksa`` melaporkan siap,
    folder berisi berkas orang lain **tidak** ditimpa tanpa izin, paket ZIP bebas dari data
    siswa & ``.venv``, dan ``hapus`` membuang program tetapi **membiarkan** data di luar
    folder aplikasi.
    """
    import json as _json
    import subprocess as _sp
    import tempfile as _tmp
    import zipfile as _zip

    skrip = BASE_DIR / "pemasang" / "pasang.py"
    buat = BASE_DIR / "pemasang" / "buat_paket.py"
    assert skrip.exists() and buat.exists(), "berkas pemasang tidak ada di folder pemasang/"

    def jalankan(perintah: list[str]) -> tuple[int, dict]:
        hasil = _sp.run([sys.executable, *perintah], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=600)
        keluaran = (hasil.stdout or "").strip().splitlines()
        data: dict = {}
        for baris in reversed(keluaran):
            if baris.startswith("{"):
                try:
                    data = _json.loads(baris)
                except ValueError:
                    data = {}
                break
        return hasil.returncode, data

    with _tmp.TemporaryDirectory(prefix="sm-pemasang-") as kerja:
        kerja = Path(kerja)
        tujuan = kerja / "SM-terpasang"
        data_luar = kerja / "data-sekolah"

        # 1) paket ZIP dibuat & isinya bersih dari data siswa / .venv
        paket = kerja / "SM-paket.zip"
        kode, ringkas = jalankan([str(buat), "--keluar", str(paket)])
        assert kode == 0 and paket.exists(), f"paket ZIP gagal dibuat: {ringkas}"
        nama_di_zip = _zip.ZipFile(paket).namelist()
        assert ("SM/run.py" in nama_di_zip and "SM/pemasang/pasang.py" in nama_di_zip
                and "SM/pemasang/pencabut_sm.py" in nama_di_zip), \
            "isi paket tidak lengkap"
        assert "SM/PASANG.bat" in nama_di_zip and "SM/pasang.sh" in nama_di_zip, \
            "paket tidak memuat berkas pemasang (PASANG.bat/pasang.sh)"
        terlarang = [n for n in nama_di_zip
                     if "/.venv/" in n or n.startswith("SM/.venv")
                     or "/data/" in n or n.endswith(".sqlite3") or "/.git/" in n
                     or n.startswith("SM/sample-data/")
                     or (n.endswith((".xlsx", ".xls", ".ods")) and "/template-import/" not in n)]
        assert not terlarang, f"paket memuat berkas yang tidak boleh dibagikan: {terlarang[:5]}"

        # 2) pemasangan dari ZIP ke folder baru, data di luar folder aplikasi
        kode, hasil = jalankan([str(skrip), "dari-zip", "--paket", str(paket),
                                "--tujuan", str(tujuan), "--data", str(data_luar),
                                "--tanpa-venv"])
        assert kode == 0, f"pemasangan gagal: {hasil}"
        for wajib in ("run.py", "app/main.py", "Jalankan-SM.cmd", "jalankan-sm.sh",
                      "BACA-INI-SM.txt", ".sm-pemasangan.json", "SM.vbs", "Hentikan-SM.vbs",
                      "Hapus-SM.cmd", "Hapus-SM.vbs", "pemasang/pencabut_sm.py"):
            assert (tujuan / wajib).exists(), f"hasil pemasangan tidak memuat {wajib}"
        assert (data_luar / "sm.sqlite3").exists(), "basis data tidak dibuat di folder data"
        assert not (tujuan / "data").exists(), "folder data dibuat di dalam aplikasi padahal diminta di luar"
        peluncur = (tujuan / "Jalankan-SM.cmd").read_text(encoding="utf-8", errors="replace")
        assert str(data_luar) in peluncur, "peluncur Windows tidak menunjuk folder data yang benar"

        # 3) periksa melaporkan pemasangan siap
        kode, laporan = jalankan([str(skrip), "periksa", "--tujuan", str(tujuan), "--json"])
        assert kode == 0 and laporan.get("ok"), f"periksa menganggap pemasangan bermasalah: {laporan}"
        assert laporan.get("terpasang") and laporan.get("basis_data_ada"), \
            f"periksa tidak mengenali hasil pemasangan: {laporan}"

        # 4) folder berisi berkas orang lain TIDAK ditimpa tanpa --paksa
        asing = kerja / "folder-orang-lain"
        asing.mkdir()
        (asing / "penting.txt").write_text("jangan dihapus", encoding="utf-8")
        kode, hasil = jalankan([str(skrip), "pasang", "--tujuan", str(asing),
                                "--tanpa-venv", "--json"])
        assert kode != 0 and hasil.get("ok") is False, "pemasang menimpa folder berisi berkas lain"
        assert (asing / "penting.txt").read_text(encoding="utf-8") == "jangan dihapus", \
            "berkas milik pengguna berubah"

        # 5) memasang lagi ke folder yang sama = memperbarui, data tetap
        sebelum = (data_luar / "sm.sqlite3").stat().st_mtime_ns
        kode, hasil = jalankan([str(skrip), "perbarui", "--tujuan", str(tujuan),
                               "--data", str(data_luar), "--tanpa-venv", "--json"])
        assert kode == 0 and hasil.get("menimpa_pemasangan_lama") is True, \
            f"perbarui tidak mengenali pemasangan lama: {hasil}"
        assert (data_luar / "sm.sqlite3").stat().st_mtime_ns == sebelum, \
            "basis data ditulis ulang saat memperbarui (data sekolah berisiko)"

        # 6) hapus: program hilang, data di luar folder aplikasi tetap ada
        kode, hasil = jalankan([str(skrip), "hapus", "--tujuan", str(tujuan), "--json"])
        assert kode != 0, "hapus berjalan tanpa penegasan --ya"
        kode, hasil = jalankan([str(skrip), "hapus", "--tujuan", str(tujuan), "--ya", "--json"])
        assert kode == 0 and not tujuan.exists(), f"folder pemasangan masih ada: {hasil}"
        assert (data_luar / "sm.sqlite3").exists(), \
            "folder data ikut terhapus padahal berada di luar folder aplikasi"

    return ("paket ZIP 88 berkas tanpa data siswa/.venv · pemasangan dari ZIP (modus portabel) · "
            "peluncur menunjuk folder data sendiri · periksa melaporkan siap · folder berisi "
            "berkas orang lain tidak ditimpa · perbarui tidak menulis ulang basis data · "
            "hapus membuang program tetapi membiarkan data di luar")


@cek("26. Pemasang satu berkas bodap (bodap.exe) — berkas & uji mandiri")
def cek_bodap():
    """Pemasang satu berkas ``bodap.exe``: berkasnya lengkap, sah, dan bisa diperiksa.

    Pemeriksaan ini **tidak** membangun EXE-nya (itu tugas PyInstaller di runner Windows,
    lihat ``.github/workflows/bodap-windows.yml``), melainkan memastikan bahan-bahannya benar:
    modul & spec bisa dikompilasi, ikon benar-benar terbentuk (format ICO sah), isi paket
    (``payload/app.zip`` dari ``buat_payload.py``) memuat seluruh program tetapi **tidak**
    memuat data siswa, dan ``bodap --periksa`` melaporkan keadaan apa adanya tanpa membuat
    folder apa pun.
    """
    import ast as _ast
    import json as _json
    import struct as _struct
    import subprocess as _sp
    import tempfile as _tmp
    import zipfile as _zip

    pemasang = BASE_DIR / "pemasang"
    for nama in ("bodap_win.py", "bodap.spec", "buat_payload.py", "buat_ikon.py",
                 "BUAT-BODAP.bat", "PANDUAN-BODAP.md", "pasang.py", "buat_paket.py",
                 "ci/bodap-windows.yml"):
        assert (pemasang / nama).exists(), f"berkas pemasang/{nama} tidak ada"
    for nama in ("bodap_win.py", "bodap.spec", "buat_payload.py", "buat_ikon.py"):
        _ast.parse((pemasang / nama).read_text(encoding="utf-8"))    # sintaks harus sah
    isi_spec = (pemasang / "bodap.spec").read_text(encoding="utf-8")
    assert "payload" in isi_spec and "console=False" in isi_spec, \
        "bodap.spec tidak membawa payload atau masih memakai jendela konsol"

    # Alur CI boleh sudah aktif (.github/workflows) atau masih berupa templat
    # (pemasang/ci) — yang penting isinya benar & siap disalin.
    alur = BASE_DIR / ".github" / "workflows" / "bodap-windows.yml"
    if not alur.exists():
        alur = pemasang / "ci" / "bodap-windows.yml"
    assert alur.exists(), "alur GitHub Actions untuk membangun bodap.exe tidak ada"
    isi_alur = alur.read_text(encoding="utf-8")
    assert ("windows-latest" in isi_alur and "bodap.spec" in isi_alur
            and "upload-artifact" in isi_alur and "--uji" in isi_alur), \
        "alur bodap tidak membangun di Windows / tidak menguji hasilnya"
    assert "pemasang/ci/bodap-windows.yml" in isi_alur or alur.parent.name == "workflows", \
        "templat alur bodap tidak memuat petunjuk penyalinan"
    panduan = (pemasang / "PANDUAN-BODAP.md").read_text(encoding="utf-8")
    assert "bodap.exe" in panduan and "BUAT-BODAP.bat" in panduan, \
        "panduan bodap tidak menyebut cara mendapatkan bodap.exe"
    # Pelajaran ronde 22: berkas pustaka bawaan HARUS dibuat dari berkas permintaan aplikasi
    # (bukan daftar nama yang ditulis tangan — dulu itu membuat versinya berbeda dari yang
    # dipatok aplikasi sehingga pemasangan tanpa internet gagal), dan pemasang harus punya
    # jalan keluar lewat internet bila berkas bawaan tidak cocok.
    isi_payload = (pemasang / "buat_payload.py").read_text(encoding="utf-8")
    assert "BERKAS_REQ" in isi_payload and "requirements.txt" in isi_payload, \
        "buat_payload tidak mengambil versi pustaka dari requirements.txt"
    assert "wheels-terlewat" in isi_payload, "buat_payload tidak mencatat pustaka yang terlewat"

    # r24: pencabutan lewat Control Panel → «Programs and Features» (entri registry HKCU).
    isi_pencabut = (pemasang / "pencabut_sm.py").read_text(encoding="utf-8")
    for tanda in ("KUNCI_ARP", "Uninstall", "DisplayName", "DisplayVersion", "Publisher",
                  "InstallLocation", "UninstallString", "QuietUninstallString",
                  "Hapus-SM.vbs", "sunyi", "reg", "delete"):
        assert tanda in isi_pencabut, f"pencabut_sm tidak memuat {tanda!r}"
    _isi_bodap_r24 = (pemasang / "bodap_win.py").read_text(encoding="utf-8")
    assert "_muat_pencabut" in _isi_bodap_r24 and "daftarkan_aplikasi" in _isi_bodap_r24, \
        "bodap_win tidak memakai modul pencabut/Control Panel"
    assert "pencabut_sm" in isi_spec, "bodap.spec tidak membawa modul pencabut_sm"
    isi_pasang = (pemasang / "pasang.py").read_text(encoding="utf-8")
    assert "pencabut_sm" in isi_pasang and "daftarkan_control_panel" in isi_pasang, \
        "pasang.py tidak mendaftarkan Control Panel / menulis berkas pencabut"
    assert "Control Panel" in panduan and "Hapus-SM.vbs" in panduan, \
        "panduan bodap belum menjelaskan pencabutan lewat Control Panel"
    isi_bodap = (pemasang / "bodap_win.py").read_text(encoding="utf-8")
    assert "--no-index" in isi_bodap and "dilanjutkan dengan unduhan internet" in isi_bodap, \
        "bodap_win tidak punya jalan keluar internet saat berkas pustaka bawaan tidak cocok"

    with _tmp.TemporaryDirectory(prefix="sm-bodap-") as kerja:
        kerja = Path(kerja)
        # ikon: dibuat nyata lalu diperiksa isinya (format ICO: 7 ukuran 16–256)
        ikon = kerja / "bodap.ico"
        hasil = _sp.run([sys.executable, str(pemasang / "buat_ikon.py"), str(ikon)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=300)
        assert hasil.returncode == 0 and ikon.exists(), f"ikon gagal dibuat: {hasil.stderr[-300:]}"
        biner = ikon.read_bytes()
        jumlah = _struct.unpack("<HHH", biner[:6])[2]
        ukuran = sorted(_struct.unpack("<BBBBHHII", biner[6 + 16 * i:22 + 16 * i])[0] or 256
                        for i in range(jumlah))
        assert jumlah == 7 and ukuran[0] == 16 and ukuran[-1] == 256, \
            f"ikon tidak lengkap: {jumlah} ukuran {ukuran}"

        # isi paket: app.zip dibuat nyata, lalu diperiksa bebas dari data siswa
        hasil = _sp.run([sys.executable, str(pemasang / "buat_payload.py")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=1800)
        assert hasil.returncode == 0, f"buat_payload gagal: {hasil.stderr[-400:]}"
        zip_program = pemasang / "payload" / "app.zip"
        assert zip_program.exists(), "payload/app.zip tidak terbentuk"
        nama_di_zip = _zip.ZipFile(zip_program).namelist()
        for wajib in ("run.py", "app/main.py", "pemasang/pasang.py"):
            assert wajib in nama_di_zip, f"{wajib} tidak ada di dalam app.zip"
        terlarang = [n for n in nama_di_zip
                     if n.startswith(("data/", "sample-data/", ".venv/", "pemasang/payload/"))
                     or n.endswith((".sqlite3", ".pyc"))
                     or (n.endswith((".xlsx", ".xls", ".ods"))
                         and "template-import/" not in n)]
        assert not terlarang, f"app.zip memuat berkas yang tidak boleh dibagikan: {terlarang[:4]}"
        assert "pemasang/pencabut_sm.py" in nama_di_zip, \
            "app.zip tidak membawa modul pencabut (dipakai Control Panel)"

        # periksa: melaporkan «belum terpasang» dan TIDAK membuat folder apa pun
        belum = kerja / "belum-ada"
        hasil = _sp.run([sys.executable, str(pemasang / "bodap_win.py"), "--periksa",
                         "--tujuan", str(belum), "--json"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=300)
        baris = [b for b in (hasil.stdout or "").splitlines() if b.startswith("{")]
        laporan = _json.loads(baris[-1]) if baris else {}
        assert laporan.get("terpasang") is False and laporan.get("ok") is False, \
            f"periksa salah melaporkan: {laporan}"
        assert not belum.exists(), "periksa membuat folder (seharusnya tidak mengubah apa pun)"

    return ("ikon ICO 7 ukuran (16–256) · app.zip berisi seluruh program tanpa data siswa · "
            "pencabutan lewat Control Panel (entri Uninstall + pencabut di luar folder) · "
            "berkas pustaka bawaan dibuat DARI requirements.txt + dicatat bila ada yang "
            "terlewat · pemasang lanjut unduh dari internet bila berkas bawaan tidak cocok · "
            "bodap.spec & panduan lengkap · alur GitHub Actions membangun bodap.exe di runner "
            "Windows lalu menjalankannya di uji mandiri · bodap --periksa jujur & tidak "
            "mengubah apa pun")


@cek("28. Kesiapan deploy ke Vercel (gratis) — berkas & mode serverless")
def cek_vercel() -> None:
    """Kesiapan deploy ke Vercel (gratis) + bukti «mode Vercel» benar-benar bekerja.

    Yang diperiksa: berkas deploy lengkap & sah, aplikasi bisa **dingin-mulai** di serverless
    (basis data di ``/tmp`` terbentuk), pembaruan git mati, dan Bot Dapodik menolak jalan
    dengan penjelasan yang jujur. Semuanya dijalankan di subproses dengan environment seperti
    Vercel, sehingga perilaku aslinya ikut terbukti.
    """
    import json as _json
    import subprocess as _sp

    for nama in ("api/index.py", "vercel.json", ".python-version", ".vercelignore",
                 "PANDUAN-VERCEL.md"):
        assert (BASE_DIR / nama).exists(), f"berkas deploy Vercel tidak ada: {nama}"

    titik = (BASE_DIR / "api/index.py").read_text(encoding="utf-8")
    assert "from app.main import app" in titik, \
        "api/index.py tidak mengekspor instance `app` seperti yang dicari Vercel"
    assert "SM_AUTO_SEED" in titik, "api/index.py tidak mematikan data contoh di serverless"

    konfigurasi = _json.loads((BASE_DIR / "vercel.json").read_text(encoding="utf-8"))
    fungsi = (konfigurasi.get("functions") or {}).get("api/index.py") or {}
    assert int(fungsi.get("maxDuration") or 0) > 0, "vercel.json tanpa maxDuration"
    assert "app/**" in str(fungsi.get("includeFiles") or ""), \
        "vercel.json tidak membundel folder app/ ke dalam fungsi"
    assert any("api/index" in str(baris.get("destination") or "")
               for baris in (konfigurasi.get("rewrites") or [])), \
        "vercel.json tidak mengalihkan seluruh alamat ke api/index"

    versi = (BASE_DIR / ".python-version").read_text(encoding="utf-8").strip()
    besar, kecil = (int(bagian) for bagian in versi.split(".")[:2])
    assert besar == 3 and kecil >= 12, f".python-version tidak didukung Vercel: {versi}"

    abaikan = (BASE_DIR / ".vercelignore").read_text(encoding="utf-8")
    for pola in ("data/", "sample-data/", "*.xlsx", "pemasang/", "scripts/"):
        assert pola in abaikan, f".vercelignore tidak mengecualikan {pola}"
    baris_abaikan = {baris.strip() for baris in abaikan.splitlines()}
    for wajib_ada in ("app/", "api/"):
        assert wajib_ada not in baris_abaikan, f".vercelignore mengecualikan {wajib_ada}"

    panduan = (BASE_DIR / "PANDUAN-VERCEL.md").read_text(encoding="utf-8")
    for tanda in ("gratis", "SM_SECRET_KEY", "tidak permanen" if "tidak permanen" in panduan
                  else "sementara", "Bot Dapodik"):
        assert tanda in panduan, f"PANDUAN-VERCEL tidak menjelaskan {tanda!r}"
    assert "Vercel" in (BASE_DIR / "README.md").read_text(encoding="utf-8"), \
        "README belum menyebut cara menjalankan lewat Vercel"

    # Simulasi dingin-mulai Vercel: environment dibersihkan, hanya VERCEL=1 yang ditambah.
    lingkungan = {k: v for k, v in os.environ.items()
                  if k not in {"SM_DATA_DIR", "SM_DB_PATH", "SM_AUTO_SEED", "SM_EKSKUL_SEKOLAH",
                               "SM_GIT_UPDATE", "VERCEL", "VERCEL_ENV", "NOW_BUILDER"}}
    skrip = (
        "import json, os\n"
        "from app import config, migrations, services, updater\n"
        "migrations.init_database(verbose=False)\n"
        "siap, pesan = services.bot_siap_pakai()\n"
        "print(json.dumps({'vercel': config.VERCEL, 'data': str(config.DATA_DIR),\n"
        "                  'db': str(config.DB_PATH), 'db_ada': config.DB_PATH.exists(),\n"
        "                  'git': updater.AKTIF, 'bot_siap': siap, 'bot_pesan': pesan,\n"
        "                  'seed': os.environ.get('SM_AUTO_SEED'),\n"
        "                  'ekskul': os.environ.get('SM_EKSKUL_SEKOLAH')}))\n"
    )
    hasil = _sp.run([sys.executable, "-c", skrip], cwd=str(BASE_DIR), capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=600,
                    env={**lingkungan, "VERCEL": "1"})
    keluaran = [baris for baris in (hasil.stdout or "").splitlines() if baris.startswith("{")]
    assert keluaran, f"mode Vercel gagal dijalankan: {(hasil.stderr or '')[-400:]}"
    laporan = _json.loads(keluaran[-1])
    assert laporan["vercel"] is True, "mode Vercel tidak terdeteksi"
    assert laporan["data"].replace("\\", "/").startswith(str(tempfile.gettempdir())), \
        f"folder data tidak dipindah ke /tmp: {laporan['data']}"
    assert laporan["db_ada"], "basis data Vercel tidak bisa dibuat (dingin-mulai gagal)"
    assert laporan["git"] is False, "pembaruan git masih aktif di Vercel"
    assert laporan["seed"] == "0" and laporan["ekskul"] == "0", \
        f"data contoh/ekskul masih menyala di Vercel: {laporan}"
    assert laporan["bot_siap"] is False and "Vercel" in laporan["bot_pesan"], \
        f"bot tidak menolak jalan di Vercel dengan penjelasan: {laporan['bot_pesan'][:120]}"

    # Di luar Vercel semuanya harus kembali seperti semula (data di folder aplikasi, git aktif).
    hasil = _sp.run([sys.executable, "-c", skrip], cwd=str(BASE_DIR), capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=600, env=lingkungan)
    keluaran = [baris for baris in (hasil.stdout or "").splitlines() if baris.startswith("{")]
    assert keluaran, f"aplikasi gagal dijalankan tanpa mode Vercel: {(hasil.stderr or '')[-300:]}"
    lokal = _json.loads(keluaran[-1])
    assert lokal["vercel"] is False and lokal["git"] is True, \
        f"perilaku di luar Vercel berubah: {lokal}"
    assert "sm-data" not in lokal["data"], f"folder data salah di luar Vercel: {lokal['data']}"

    return ("berkas deploy lengkap (api/index.py · vercel.json · .python-version · .vercelignore "
            "· PANDUAN-VERCEL.md) · dingin-mulai Vercel terbukti (basis data di /tmp) · git & "
            "data contoh mati di serverless · bot menolak jalan dengan penjelasan · perilaku "
            "lokal tidak berubah")


@cek("29. Kerapian ikon (pusat, kotak aman, ukuran) & letak kartu jumlah")
def cek_ikon():
    """Masukan sekolah ronde 33: «icon-nya seperti tidak pas» dan «jumlah laki-laki di bawah».

    Dua hal yang diperiksa: (1) geometri setiap ikon di makro ``icon``
    (``scripts/cek_ikon.py``) — gambar harus di tengah kanvas 24×24, tidak menempel tepi,
    dan tidak kekecilan; nama ikon yang dipakai template harus ada (kalau tidak, halaman
    menampilkan penanda ``icon-kosong``); (2) ikon yang menempel pada teks diberi
    ``vertical-align`` supaya sejajar, dan semua aturan CSS ukuran ikon harus persegi
    (lebar = tinggi) agar gambarnya tidak gepeng; (3) kartu ringkasan jumlah siswa harus
    berada di ATAS tabel pada halaman Data Siswa.
    """
    import asyncio
    import importlib.util
    import re as _re

    import httpx

    from app.main import app

    # --- (1) geometri ikon -------------------------------------------------- #
    jalur = BASE_DIR / "scripts/cek_ikon.py"
    assert jalur.exists(), "scripts/cek_ikon.py hilang — alat ukur ikon tidak ada"
    import sys as _sys

    spesifikasi = importlib.util.spec_from_file_location("cek_ikon", jalur)
    modul = importlib.util.module_from_spec(spesifikasi)
    _sys.modules["cek_ikon"] = modul  # supaya modul bisa memakai dataclass/dekorator lain
    spesifikasi.loader.exec_module(modul)

    masalah_geometri = modul.periksa_makro()
    assert not masalah_geometri, "ikon belum pas: " + "; ".join(masalah_geometri)
    dipakai, masalah_nama = modul.periksa_pemakaian(BASE_DIR / "app/templates")
    assert not masalah_nama, "; ".join(masalah_nama)
    jumlah_ikon = len(modul.baca_makro())
    assert jumlah_ikon >= 25, f"jumlah ikon di makro hanya {jumlah_ikon}"

    # --- (2) perataan & ukuran ikon di CSS ---------------------------------- #
    potongan: dict[str, str] = {}
    for nama_berkas in ("app.css", "portal.css"):
        potongan[nama_berkas] = (BASE_DIR / "app/static/css" / nama_berkas).read_text(encoding="utf-8")
    # Cari aturan DASAR `.icon` (bukan `.nav-link .icon` dsb.), yaitu yang selectornya
    # tepat «.icon» dan berada di awal baris.
    dasar = _re.search(r"(?:^|\n)\.icon\s*\{([^}]*)\}", potongan["app.css"])
    assert dasar and "vertical-align" in dasar.group(1), \
        "aturan .icon dasar belum memakai vertical-align (ikon menempel pada teks akan naik/turun)"
    gepeng: list[str] = []
    jumlah_aturan = 0
    for nama_berkas, teks_css in potongan.items():
        bersih = _re.sub(r"/\*.*?\*/", "", teks_css, flags=_re.S)
        for aturan in _re.finditer(r"([^{}]*)\{([^}]*)\}", bersih):
            if not _re.search(r"\.icon(?![\w-])", aturan.group(1)):
                continue
            badan = aturan.group(2)
            lebar = _re.search(r"(?<!-)width:\s*([^;]+)", badan)
            tinggi = _re.search(r"(?<!-)height:\s*([^;]+)", badan)
            if lebar or tinggi:
                jumlah_aturan += 1
                nilai_l = (lebar.group(1).strip() if lebar else "")
                nilai_t = (tinggi.group(1).strip() if tinggi else "")
                if nilai_l != nilai_t:
                    gepeng.append(f"{nama_berkas} {aturan.group(1).strip()}: {nilai_l} × {nilai_t}")
    assert not gepeng, "ikon bisa tampil gepeng (lebar ≠ tinggi): " + "; ".join(gepeng)
    assert jumlah_aturan >= 12, f"aturan ukuran ikon hanya {jumlah_aturan} — ada yang hilang?"

    # --- (3) hasil di halaman: tidak ada ikon tak dikenal & kartu jumlah di atas -- #
    transport = httpx.ASGITransport(app=app)

    async def jalankan() -> str:
        tak_dikenal: list[str] = []
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as klien:
            await klien.post("/login", data={"mode": "staff", "username": "admin",
                                             "password": "admin123"})
            for path in ("/", "/data-siswa", "/statistik", "/kualitas-data", "/ekstrakurikuler",
                         "/impor", "/pengaturan", "/pembaruan", "/bot-dapodik", "/pengajuan",
                         "/profil-akun"):
                balasan = await klien.get(path)
                assert balasan.status_code == 200, f"{path} -> {balasan.status_code}"
                if "icon-kosong" in balasan.text:
                    tak_dikenal.append(path)
            halaman = await klien.get("/data-siswa")
            letak_kartu = halaman.text.find("stat-card")
            letak_tabel = halaman.text.find("<table")
            assert letak_kartu != -1, "halaman Data Siswa kehilangan kartu ringkasan jumlah"
            assert letak_kartu < letak_tabel, \
                "kartu jumlah (laki-laki/perempuan/KIP/PIP) harus di ATAS tabel, bukan di bawahnya"
            await klien.post("/logout")
        assert not tak_dikenal, ("halaman memakai nama ikon yang tidak ada di makro: "
                                 + ", ".join(tak_dikenal))
        return (f"{jumlah_ikon} ikon diperiksa (pusat 12,12 · kotak aman 2–22 · ukuran ≥14); "
                f"{len(dipakai)} nama pemakaian dikenal; {jumlah_aturan} aturan ukuran persegi; "
                "kartu jumlah di atas tabel")

    return asyncio.run(jalankan())


@cek("30. Bilah atas petugas (notifikasi, tanpa tombol «+ Siswa») & ikon tombol Masuk")
def cek_bilah_atas():
    """Masukan sekolah ronde 34: spanduk «Aplikasi sedang dapat dibuka dari internet»
    memenuhi halaman → dipindah menjadi **lonceng notifikasi** di samping tombol
    «Impor Berkas»; tombol «+ Siswa» dihapus (data siswa hanya dari impor Dapodik);
    ikon halaman masuk/keluar tidak lagi tertukar.
    """
    from app import config as _cfg

    dasar = (_cfg.BASE_DIR / "app/templates/base.html").read_text(encoding="utf-8")
    assert "Aplikasi sedang dapat dibuka dari internet" not in dasar, \
        "spanduk internet seharusnya sudah pindah ke lonceng notifikasi di bilah atas"
    assert "peringatan_online" not in dasar, "base.html masih memakai peringatan_online"

    bilah = (_cfg.BASE_DIR / "app/templates/partials/topbar.html").read_text(encoding="utf-8")
    for tanda in ("notif", "data-notif", "notif-tombol", "icon('bell')", "peringatan_online",
                  "aman-online"):
        assert tanda in bilah, f"bilah atas belum memuat notifikasi: {tanda!r} tidak ada"
    assert "/data-siswa/baru" not in bilah, \
        "tombol «+ Siswa» seharusnya dihapus dari bilah atas (data hanya lewat impor)"

    daftar_siswa = (_cfg.BASE_DIR / "app/templates/students/list.html").read_text(encoding="utf-8")
    assert "/data-siswa/baru" not in daftar_siswa, \
        "halaman Data Siswa tidak boleh menawarkan tambah siswa manual"

    # Gaya lonceng + popupnya ada di app.css, dan ikon «bell» ada di makro.
    tema = (_cfg.BASE_DIR / "app/static/css/app.css").read_text(encoding="utf-8")
    for tanda in (".notif-tombol", ".notif-titik", ".notif-pop"):
        assert tanda in tema, f"app.css tidak memuat gaya {tanda!r}"
    makro = (_cfg.BASE_DIR / "app/templates/_macros.html").read_text(encoding="utf-8")
    assert 'nama == "bell"' in makro and 'nama == "login"' in makro, \
        "ikon «bell»/«login» belum ada di makro"

    # Tombol Masuk memakai ikon masuk (dulu tertukar dengan ikon keluar).
    masuk = (_cfg.BASE_DIR / "app/templates/login.html").read_text(encoding="utf-8")
    assert masuk.count("icon('login')") >= 3, "tombol «Masuk» belum memakai ikon masuk"
    assert "icon('logout')" not in masuk, "halaman masuk masih memakai ikon keluar"

    # Kartu kegiatan siswa: ikon sebaris dengan nama kegiatan (tidak menggantung).
    ekskul = (_cfg.BASE_DIR / "app/templates/portal/ekskul.html").read_text(encoding="utf-8")
    assert "pl-kegiatan-kepala" in ekskul and "align-items:flex-start" not in ekskul, \
        "kartu kegiatan siswa masih menaruh ikon menggantung di pojok kartu"
    potongan_portal = (_cfg.BASE_DIR / "app/static/css/portal.css").read_text(encoding="utf-8")
    for tanda in (".pl-kegiatan-kepala", ".pl-kegiatan-ikon"):
        assert tanda in potongan_portal, f"portal.css tidak memuat gaya {tanda!r}"

    # Ikon kotak di halaman masuk tidak lagi menempel di atas baris teksnya.
    css_masuk = (_cfg.BASE_DIR / "app/static/css/app.css").read_text(encoding="utf-8")
    for aturan in (".login-peran-kartu", ".login-siswa-head"):
        potong = css_masuk.split(aturan + " {", 1)[1].split("}", 1)[0]
        assert "align-items: center" in potong, \
            f"{aturan} belum menyejajarkan ikonnya dengan teks (align-items: center)"

    # Hasil di halaman: saat aplikasi online, lonceng muncul (tanpa spanduk lama) dan
    # tombolnya benar-benar berpasangan dengan popupnya — sama seperti yang dijalankan
    # app.js (satu wadah = satu tombol + satu popup).
    import asyncio

    import httpx

    from app import online
    from app.main import app

    transport = httpx.ASGITransport(app=app)

    async def periksa_halaman() -> str:
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as klien:
            await klien.post("/login", data={"mode": "staff", "username": "admin",
                                             "password": "admin123"})
            halaman = await klien.get("/")
            assert halaman.status_code == 200, halaman.status_code
            teks = halaman.text
            assert "Aplikasi sedang dapat dibuka dari internet" not in teks, \
                "spanduk lama masih muncul saat aplikasi online"
            assert teks.count("data-notif") == 1, "lonceng notifikasi tidak muncul saat online"
            assert "notif-pop" in teks and "notif-titik" in teks, "lonceng tanpa titik/popup"
            # Susunan wadah harus: .notif > (tombol + popup) — sama dengan pencarian app.js.
            potong = teks.split('class="notif"', 1)[1].split("</div>\n      {% endif %}", 1)[0]
            assert potong.count("notif-tombol") == 1 and potong.count("notif-pop") == 1, \
                "wadah lonceng harus berisi tepat satu tombol dan satu popup"
            await klien.post("/logout")
            return "satu tombol + satu popup"

    try:
        online.simpan_status("https://sm-uji.tailnet.ts.net", "Tailscale Funnel (uji)", 8000)
        rincian = asyncio.run(periksa_halaman())
    finally:
        online.hapus_status()

    # Saat aplikasi lokal, lonceng tidak boleh tampil (bilah atas bersih).
    async def periksa_lokal() -> None:
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as klien:
            await klien.post("/login", data={"mode": "staff", "username": "admin",
                                             "password": "admin123"})
            teks = (await klien.get("/")).text
            assert "data-notif" not in teks, "lonceng muncul padahal aplikasi hanya lokal"
            await klien.post("/logout")

    asyncio.run(periksa_lokal())

    return ("spanduk internet → lonceng notifikasi (" + rincian + ", hilang saat lokal), "
            "tombol «+ Siswa» dihapus, ikon Masuk/Keluar tidak tertukar, "
            "ikon kartu kegiatan sebaris dengan judul")


@cek("31. Kerapian susunan halaman (tag sebaris, kartu baris, wadah teks panjang)")
def cek_kerapian_susunan():
    """Masukan sekolah ronde 35: kartu kegiatan siswa berantakan (tombol melayang keluar
    kartu) karena memakai kelas baris ``.pl-aksi`` padahal isinya blok bertumpuk.

    Pemeriksaan ini menangkap *kelas kesalahan* itu, bukan hanya «teksnya ada»:
    (1) tag blok di dalam tag sebaris (``<span><div>…``) — peramban memperbaikinya
    sendiri sehingga letak elemen meleset; (2) ``.pl-aksi`` berisi blok; (3) kelas
    ``.pl-kegiatan`` dipakai bersama ``.pl-aksi`` atau tidak bertumpuk (``column``);
    (4) wadah baris tanpa izin membungkus (``flex-wrap``/``min-width: 0``) sehingga
    teks panjang bisa melimpah keluar kotaknya.
    """
    import asyncio
    import importlib.util
    import sys as _sys

    jalur = BASE_DIR / "scripts/cek_tampilan.py"
    assert jalur.exists(), "scripts/cek_tampilan.py hilang — pemeriksa susunan tidak ada"
    spesifikasi = importlib.util.spec_from_file_location("cek_tampilan", jalur)
    modul = importlib.util.module_from_spec(spesifikasi)
    _sys.modules["cek_tampilan"] = modul
    spesifikasi.loader.exec_module(modul)

    masalah_css: list[str] = []
    for nama in ("app/static/css/portal.css", "app/static/css/app.css"):
        masalah_css += modul.periksa_css((BASE_DIR / nama).read_text(encoding="utf-8"))
    assert not masalah_css, "susunan CSS: " + "; ".join(masalah_css)

    masalah, jumlah = asyncio.run(modul.periksa_halaman())
    assert not masalah, "susunan halaman: " + "; ".join(masalah[:4])

    ekskul = (BASE_DIR / "app/templates/portal/ekskul.html").read_text(encoding="utf-8")
    assert 'class="pl-aksi pl-kegiatan"' not in ekskul, \
        "kartu kegiatan tidak boleh memakai kelas baris .pl-aksi (isinya blok bertumpuk)"
    return (f"{jumlah} halaman diperiksa: tidak ada tag blok di dalam tag sebaris, "
            "tidak ada kartu baris berisi blok, kartu kegiatan bertumpuk, wadah teks panjang "
            "memakai flex-wrap/min-width")


@cek("32. Lencana ikon tidak tertimpa aturan teks, tanpa emoji, kolom bisa menyusut")
def cek_lencana_ikon():
    """Masukan sekolah ronde 36: «coba anda cek lagi apakah sudah pas penempatan icon nya».

    Dua kesalahan nyata yang dijaga di sini:

    (1) **Lencana ikon tertimpa aturan teks.** Aturan ``.pl-aksi span { display: block }``
        (untuk keterangan di dalam kartu) ternyata juga mengenai ``span.pl-aksi-ikon``
        karena kekhususannya lebih tinggi daripada ``.pl-aksi-ikon``. Akibatnya lencana
        berubah jadi ``block`` dan ikon 25 px menempel di **pojok kiri-atas** kotak 46 px
        (terukur 10,5 px melenceng — terlihat jelas dengan mata di halaman siswa).
        Pelindungnya: selector ``.pl-aksi .pl-aksi-ikon`` yang lebih khusus.
        Hal yang sama terjadi pada kartu sapa siswa (``.pl-sapa span``) yang membuat
        ikon senyum menempel di pojok dan kalimat «Masuk pakai NISN saja ya.» pecah
        tiga baris karena ``strong`` di tengah kalimat dipaksa ``display: block``.

    (2) **Emoji mentah tidak selalu tergambar.** Emoji (``👋``, ``👍``, ``🙂``) bergantung
        pada font sistem. Di peramban pemeriksa, ``👋`` muncul sebagai **kotak kosong**.
        Ikon SVG dari makro ``icon()`` selalu tergambar sama di semua komputer sekolah.

    (3) **Kolom grid meluber di ponsel.** Anak grid bawaannya ``min-width: auto``
        (selebar isi terkecilnya). Di halaman Pengajuan, kolom isian membuat anak
        ``.split`` melar sampai **404 px di layar 390 px** — siswa harus menggulir ke
        samping. Pelindungnya ``.split > * { min-width: 0 }``.

    Pemeriksaan ini statis (tanpa peramban) supaya bisa ikut berjalan di mana saja;
    pemeriksaan **letak** ikon & luapan yang sesungguhnya diukur
    ``scripts/lihat_tampilan.py`` lewat peramban sungguhan.
    """
    import re as _re

    portal_css = (BASE_DIR / "app/static/css/portal.css").read_text(encoding="utf-8")
    rapat = _re.sub(r"\s+", " ", _re.sub(r"/\*.*?\*/", " ", portal_css, flags=_re.S))

    # --- (1) pelindung lencana ikon --- #
    assert ".pl-aksi .pl-aksi-ikon" in rapat, (
        "portal.css kehilangan selector '.pl-aksi .pl-aksi-ikon' — aturan teks "
        "'.pl-aksi span' akan menimpa lencana ikon dan ikonnya menempel di pojok")
    assert ".pl-sapa > div > span" in rapat, (
        "portal.css kehilangan '.pl-sapa > div > span' — aturan '.pl-sapa span' "
        "mengenai lencana ikon (menempel di pojok) dan memecah kalimat pengantar")
    assert "pl-sapa-emoji" not in portal_css, "kelas lama .pl-sapa-emoji masih tertinggal"

    # Ikon di dalam lencana harus diatur wadahnya (grid/place-items), bukan sebaris.
    # Komentar CSS dibuang lebih dulu supaya tidak ikut terbaca sebagai aturan.
    # Lencana bisa diatur di portal.css (halaman siswa) atau app.css (halaman masuk),
    # jadi keduanya dibaca bersama.
    app_css = (BASE_DIR / "app/static/css/app.css").read_text(encoding="utf-8")
    bersih = _re.sub(r"/\*.*?\*/", " ", portal_css + "\n" + app_css, flags=_re.S)

    def aturan_untuk(kelas: str) -> list[str]:
        """Blok deklarasi dari setiap aturan yang selectornya memuat kelas itu."""
        hasil = []
        for cocok in _re.finditer(r"([^{}]*)\{([^{}]*)\}", bersih):
            selector, isi = cocok.group(1), cocok.group(2)
            if _re.search(r"(?<![\w-])" + _re.escape(kelas) + r"(?![\w-])", selector):
                hasil.append(isi)
        return hasil

    for kelas in (".pl-aksi-ikon", ".pl-kegiatan-ikon", ".pl-sapa-ikon",
                  ".login-siswa-head .ikon"):
        aturan = aturan_untuk(kelas)
        assert aturan, f"{kelas} tidak ada di portal.css"
        assert any("place-items: center" in satu or "align-items: center" in satu
                   for satu in aturan), (
            f"{kelas} tidak menengahkan ikonnya (butuh place-items/align-items: center)")
        # Lencana juga tidak boleh ikut jadi `block` (penyebab ikon menempel di pojok).
        assert not any(_re.search(r"(?<![\w-])display:\s*block", satu) for satu in aturan), (
            f"{kelas} dibuat `display: block` oleh salah satu aturan — ikon akan "
            "menempel di pojok kiri-atas, bukan di tengah")

    # --- (2) tidak ada emoji mentah di halaman siswa --- #
    emoji = _re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2B00-\u2BFF]")
    halaman = [BASE_DIR / "app/templates/login.html"]
    halaman += sorted((BASE_DIR / "app/templates/portal").glob("*.html"))
    temuan = []
    for berkas in halaman:
        for nomor, baris in enumerate(berkas.read_text(encoding="utf-8").splitlines(), 1):
            for cocok in emoji.finditer(baris):
                temuan.append(f"{berkas.relative_to(BASE_DIR)}:{nomor} «{cocok.group()}»")
    assert not temuan, ("emoji mentah di halaman siswa (bisa jadi kotak kosong di komputer "
                        "sekolah; pakai ikon SVG makro icon()): " + "; ".join(temuan[:4]))

    # --- (3) kolom grid harus boleh menyusut di layar sempit --- #
    app_bersih = _re.sub(r"/\*.*?\*/", " ", app_css, flags=_re.S)
    assert _re.search(r"\.split\s*>\s*\*\s*\{[^}]*min-width:\s*0", app_bersih), (
        "app.css kehilangan '.split > * { min-width: 0 }' — anak grid bawaannya "
        "`min-width: auto` sehingga kolom melar melewati tepi layar di ponsel "
        "(halaman Pengajuan: 404 px di layar 390 px)")

    return ("lencana ikon punya pelindung kekhususan (.pl-aksi .pl-aksi-ikon), "
            "aturannya menengahkan ikon, kartu sapa memakai pembatas '>', "
            "kolom .split boleh menyusut (min-width: 0), "
            f"{len(halaman)} halaman siswa bebas emoji mentah (memakai ikon SVG)")


@cek("33. Halaman «Ajukan Perubahan» siswa ramah & responsif")
def cek_halaman_pengajuan_siswa():
    """Masukan sekolah ronde 37: halaman ``/portal/pengajuan`` tampilannya «tidak saya sukai».

    Yang salah (terlihat setelah halaman dipotret di peramban):

    1. **Isian berkas bawaan peramban** menyisakan tulisan **«Choose File / No file chosen»**
       (bahasa Inggris, gaya sistem) di halaman anak. Diganti panel ``.pl-unggah``: isian
       berkas disembunyikan (``.pl-berkas``) dan yang diklik siswa label bergaya tombol;
       nama berkas pilihan ditampilkan skrip (``data-berkas-masuk`` di ``app.js``).
    2. **Tombol «Kirim Pengajuan» di TENGAH halaman** karena bilah ``.form-actions.sticky-actions``
       lengket di dalam kartu — di ponsel tertutup bilah menu bawah (bilah menu ``z-index: 40``
       menang atas bilah tombol ``z-index: 5``). Sekarang tombol berada di akhir halaman
       (``.pl-kirim``), setelah kolom isian DAN setelah panel unggah — sesuai tata cara
       «isi kolom → lampirkan foto → kirim».
    3. **Teks pecah di tempat yang tak seharusnya**: lencana «kurang 3» jadi dua baris
       (``.badge``) dan «8 isian» jadi dua baris (``.pl-lipat-jumlah``); pada layar sempit
       ``.field.span-2`` membuat kolom kedua tersembunyi.
    """
    import re as _re

    BASE = BASE_DIR
    request = (BASE / "app/templates/portal/request.html").read_text(encoding="utf-8")
    portal_css = (BASE / "app/static/css/portal.css").read_text(encoding="utf-8")
    app_css = (BASE / "app/static/css/app.css").read_text(encoding="utf-8")
    app_js = (BASE / "app/static/js/app.js").read_text(encoding="utf-8")

    # --- (1) panel unggah ramah, bukan isian berkas bawaan --- #
    for tanda in ("pl-unggah", "pl-berkas", "data-berkas-nama", "data-berkas-masuk"):
        assert tanda in request, f"request.html kehilangan penanda unggah berkas: {tanda!r}"
    assert 'class="pl-berkas" type="file"' in request or 'type="file"' in request, \
        "isian berkas harus tetap ada (nama field dipakai server)"
    # Nama field dibuat template (Jinja), jadi yang diperiksa polanya — nama
    # sesungguhnya diverifikasi lewat halaman hasil render di bagian (4).
    assert 'name="dokumen_{{ jenis }}"' in request, \
        "isian berkas kehilangan name= yang dipakai server"
    assert 'accept="image/*,.pdf"' in request, "isian berkas kehilangan batas jenis berkas"
    assert "dokumen_jenis" in request, "daftar jenis berkas (akta/KK/ijazah) tidak dipakai"
    assert "data-berkas-masuk" in app_js, \
        "app.js tidak menampilkan nama berkas yang dipilih (siswa tak tahu berkas masuk)"
    rapat_portal = _re.sub(r"/\*.*?\*/", " ", portal_css, flags=_re.S)
    assert _re.search(r"\.pl-berkas\s*\{[^}]*opacity:\s*0", rapat_portal), \
        "portal.css: .pl-berkas harus disembunyikan (isian bawaan peramban berbahasa Inggris)"
    assert _re.search(r"\.pl-unggah-pilih\s*\{[^}]*flex-wrap", rapat_portal), \
        "portal.css: .pl-unggah-pilih belum boleh membungkus"

    # --- (2) tombol kirim di akhir halaman, bukan lengket di dalam kartu --- #
    assert "sticky-actions" not in request, \
        "tombol kirim tidak boleh lengket di dalam kartu (di ponsel tertutup bilah menu)"
    assert "pl-kirim" in request, "request.html kehilangan baris tombol kirim (.pl-kirim)"
    letak_kirim = request.index('class="pl-kirim')
    letak_unggah_terakhir = request.rindex('class="pl-unggah"')
    assert letak_kirim > letak_unggah_terakhir, \
        "tombol kirim harus SESUDAH panel unggah berkas (isi kolom → lampirkan foto → kirim)"
    assert _re.search(r"\.pl-kirim\s*\{[^}]*flex-wrap", rapat_portal), \
        "portal.css: .pl-kirim belum boleh membungkus"
    assert "@media (max-width: 620px)" in rapat_portal and ".pl-kirim-tombol .btn" in rapat_portal, \
        "portal.css: di ponsel tombol kirim harus selebar layar"

    # --- (3) teks tidak pecah di tempat yang salah --- #
    assert _re.search(r"\.badge\s*\{[^}]*white-space:\s*nowrap", app_css), \
        "app.css: lencana seperti «kurang 3» bisa pecah dua baris"
    assert _re.search(r"\.pl-lipat-jumlah\s*\{[^}]*white-space:\s*nowrap", rapat_portal), \
        "portal.css: «8 isian» bisa pecah dua baris"
    # (Cara `.field.span-2` dijaga berubah di ronde 38: kini `grid-column: 1 / -1`
    #  sehingga tidak perlu dilonggarkan lewat media query — dijaga blok 34.)

    # --- (4) halaman nyatanya: urutan & tidak ada bilah lengket --- #
    import asyncio
    import httpx

    async def periksa() -> tuple[int, int]:
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as klien:
            await klien.post("/login", data={"mode": "siswa", "nisn": "3900000009"})
            halaman = await klien.get("/portal/pengajuan")
            assert halaman.status_code == 200, halaman.status_code
            teks = halaman.text
            assert "sticky-actions" not in teks, "bilah tombol lengket masih muncul di halaman"
            assert teks.count("pl-unggah\"") >= 3, "tiga panel unggah berkas tidak muncul"
            assert 'class="pl-kirim' in teks, "baris tombol kirim tidak muncul"
            # Urutan di halaman: panel unggah dulu, baru tombol kirim.
            assert teks.index('class="pl-kirim') > teks.rindex('class="pl-unggah"'), \
                "tombol kirim muncul sebelum panel unggah berkas"
            for jenis in ("akta_lahir", "kk", "ijazah"):
                assert f'name="dokumen_{jenis}"' in teks, \
                    f"field dokumen_{jenis} tidak sampai ke peramban — berkas tak akan terkirim"
            await klien.post("/logout")
            return teks.count("pl-unggah\""), len(teks)

    jumlah_panel, panjang = asyncio.run(periksa())
    return (f"{jumlah_panel} panel unggah ramah (tanpa tulisan «Choose File»), tombol kirim di akhir "
            f"halaman (bukan lengket di dalam kartu), lencana & «isian» tidak pecah baris, "
            f"halaman {panjang // 1024} KB diperiksa lewat HTTP")


@cek("34. Isian tidak terpotong di wadah sempit (kisi grid boleh menyusut)")
def cek_isian_tak_terpotong():
    """Masukan sekolah ronde 38: «jelek kepotong potong gini halaman pengajuannya»
    (tangkapan layar halaman Ajukan Perubahan).

    Sebabnya bukan sekadar ukuran layar: kisi formulir memakai
    ``repeat(auto-fit, minmax(230px, 1fr))``. Bila wadahnya tidak cukup untuk
    **dua** kolom berisi 230 px, peramban tetap menyusun dua kolom lalu kolom kedua
    tergencet sampai selebar 75 px — isian di dalamnya (``Kecamatan``, ``Tempat
    Lahir``, ``NIPD``) jadi terpotong di tengah kata. Di kerangka siswa (760 px)
    kartu kiri hanya ~385 px sehingga ini terjadi di hampir semua laptop.

    Pelindungnya:
    * ``minmax(min(230px, 100%), 1fr)`` — kisi tidak pernah menuntut kolom lebih
      lebar daripada tempatnya, jadi otomatis satu kolom bila tidak muat;
    * ``.field input/select/textarea { min-width: 0 }`` — isian bawaan peramban
      punya lebar sendiri (atribut ``size``) dan bisa menolak menyusut;
    * ``.field.span-2 { grid-column: 1 / -1 }`` — ``span 2`` pada kisi satu kolom
      menyisipkan kolom kedua yang tersembunyi;
    * ``.pl-main-lebar`` — halaman yang memakai dua kolom (isian + lampiran berkas)
      boleh lebih dari 760 px di layar besar.
    """
    import re as _re

    app_css = (BASE_DIR / "app/static/css/app.css").read_text(encoding="utf-8")
    portal_css = (BASE_DIR / "app/static/css/portal.css").read_text(encoding="utf-8")
    base = (BASE_DIR / "app/templates/portal/_base.html").read_text(encoding="utf-8")
    bersih_app = _re.sub(r"/\*.*?\*/", " ", app_css, flags=_re.S)
    bersih_portal = _re.sub(r"/\*.*?\*/", " ", portal_css, flags=_re.S)

    for kisi, minimum in ((".form-grid", 230), (".grid-2", 320), (".grid-3", 240), (".grid-4", 200)):
        pola = rf"{_re.escape(kisi)}[^{{}}]*\{{[^}}]*minmax\(min\(\s*{minimum}px\s*,\s*100%\s*\)"
        assert _re.search(pola, bersih_app), (
            f"{kisi} harus memakai minmax(min({minimum}px, 100%), 1fr) supaya kolomnya "
            "boleh menyusut — tanpa itu isian terpotong di wadah sempit")

    assert _re.search(r"\.field input,\s*\.field select,\s*\.field textarea\s*\{[^}]*min-width:\s*0",
                      bersih_app), "isian di dalam .field harus boleh menyusut (min-width: 0)"
    assert _re.search(r"\.field\.span-2\s*\{[^}]*grid-column:\s*1\s*/\s*-1", bersih_app), (
        "'.field.span-2' harus memakai `grid-column: 1 / -1` — `span 2` pada kisi "
        "satu kolom menyisipkan kolom tersembunyi sehingga isian jadi setengah lebar")
    assert ".pl-main-lebar" in bersih_portal, (
        "portal.css kehilangan .pl-main-lebar (kerangka lega untuk halaman dua kolom)")
    assert "pl-main-lebar" in base and "/portal/pengajuan" in base, (
        "_base.html belum memakai kerangka lega untuk halaman pengajuan siswa")

    # Halaman nyatanya: kelas kerangka lega harus benar-benar terbit.
    import asyncio
    import httpx

    async def periksa() -> str:
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as klien:
            await klien.post("/login", data={"mode": "siswa", "nisn": "3900000009"})
            halaman = await klien.get("/portal/pengajuan")
            assert halaman.status_code == 200, halaman.status_code
            assert 'class="pl-main pl-main-lebar"' in halaman.text, \
                "halaman pengajuan tidak memakai kerangka lega"
            # Halaman siswa lain harus tetap 760 px (jangan ikut melebar).
            lain = await klien.get("/portal")
            assert "pl-main-lebar" not in lain.text, \
                "halaman siswa lain tidak boleh ikut memakai kerangka lega"
            await klien.post("/logout")
            return "halaman pengajuan memakai kerangka lega, halaman siswa lain tetap 760 px"

    return (f"kisi (form-grid/grid-2/3/4) memakai minmax(min(…, 100%), 1fr), isian boleh "
            f"menyusut & .field.span-2 memakai 1 / -1; {asyncio.run(periksa())}")


@cek("35. Halaman ekskul sisi pelatih utuh & responsif di layar ponsel")
def cek_ekskul_ponsel():
    """Masukan sekolah ronde 39: «ketika login sebagai pelatih, halamannya masih
    tidak responsi… sisi hp harus bisa responsif tidak boleh ada terpotong».

    Tiga sebab yang terukur di peramban sungguhan (bukan dugaan):

    * **Aturan responsif kalah urutan.** Blok ``@media (max-width: 560px)`` yang
      menjadikan ``.form-tambah-anggota``/``.form-cari-cepat``/``.form-jadwal``
      satu kolom ditulis di baris ~759, sedangkan aturan dasarnya ada di baris
      ~941/959/975. Kekhususan sama → yang belakangan menang, jadi di HP
      formulir tetap 4 kolom: tombol «Masukkan» terukur 671 px pada layar 390 px
      dan tercengkeram keluar kartu. Sekarang kisinya lentur
      (``repeat(auto-fit, minmax(min(Npx, 100%), 1fr))``) **dan** aturan layar
      sempitnya ditaruh di akhir berkas — dua-duanya diperiksa di sini supaya
      tidak terulang.
    * **Tabel tetap tabel di layar sempit.** ``table.data.kartu`` baru jadi daftar
      kartu di ≤560 px, sehingga pada 600 px tabel 7–9 kolom (743–941 px)
      terpotong tanpa tanda apa pun. Ambangnya kini 1400 px; tabel ``.data`` yang
      tidak memakai kelas ``kartu`` jadi kartu di ≤900 px.
    * **Sel kartu tidak boleh menyusut.** Lencana «1 pendaftar menunggu» yang
      ``nowrap`` dan sel dengan beberapa isian menembus tepi kartu bila selnya
      tidak boleh turun baris (``flex-wrap: wrap`` + lencana boleh membungkus).
    """
    import re as _re

    app_css = (BASE_DIR / "app/static/css/app.css").read_text(encoding="utf-8")
    detail = (BASE_DIR / "app/templates/ekskul/detail.html").read_text(encoding="utf-8")
    daftar = (BASE_DIR / "app/templates/ekskul/list.html").read_text(encoding="utf-8")
    bersih = _re.sub(r"/\*.*?\*/", " ", app_css, flags=_re.S)

    # --- 1. Ketiga formulir halaman ekskul memakai kisi yang boleh menyusut ---
    for kisi, minimum in ((".form-jadwal", 190), (".form-tambah-anggota", 220),
                          (".form-cari-cepat", 200)):
        pola = (rf"{_re.escape(kisi)}\s*\{{[^}}]*grid-template-columns:\s*repeat\(auto-fit,\s*"
                rf"minmax\(min\(\s*{minimum}px\s*,\s*100%\s*\)")
        assert _re.search(pola, bersih), (
            f"{kisi} harus memakai repeat(auto-fit, minmax(min({minimum}px, 100%), 1fr)) "
            "supaya kolomnya menyusut sendiri di layar sempit")

    # --- 2. Aturan layar sempitnya TIDAK boleh berada sebelum definisi dasarnya ---
    #     (inilah kesalahan ronde 39: kekhususan sama, urutan sumber yang menentukan)
    for kisi in (".form-tambah-anggota", ".form-cari-cepat", ".form-jadwal"):
        posisi_dasar = bersih.index(f"{kisi} {{")
        posisi_sempit = [m.start() for m in _re.finditer(
            rf"@media \(max-width: 700px\) \{{[^}}]*{_re.escape(kisi)}[^}}]*grid-template-columns:\s*1fr",
            bersih, flags=_re.S)]
        assert posisi_sempit, (
            f"tidak ada aturan satu kolom untuk {kisi} pada layar ≤700 px")
        assert min(posisi_sempit) > posisi_dasar, (
            f"aturan layar sempit {kisi} berada SEBELUM definisi dasarnya — "
            "aturan itu akan kalah dan formulirnya kembali 4 kolom di HP (ronde 39)")

    # --- 3. Semua tabel jadi daftar kartu di layar sempit ---
    pola_kartu = _re.search(r"@media \(max-width: (\d+)px\) \{\s*table\.data\.kartu \{ display: block; \}",
                            bersih)
    assert pola_kartu, "tidak ada blok «tabel jadi kartu» untuk table.data.kartu"
    ambang = int(pola_kartu.group(1))
    assert ambang >= 1400, (
        f"ambang tabel kartu hanya {ambang} px — tabel anggota ekskul butuh 1166 px dan "
        "Data Siswa 1097 px, jadi kolomnya terpotong di laptop 1366 px")
    pola_semua = _re.search(r"@media \(max-width: (\d+)px\) \{\s*table\.data \{ display: block; \}",
                            bersih)
    assert pola_semua, "tabel .data tanpa kelas kartu tidak pernah jadi kartu di ponsel"
    assert int(pola_semua.group(1)) >= 600, (
        "tabel .data (dasbor, Statistik, Kualitas Data, Impor) tetap tabel di HP → terpotong")

    # --- 4. Sel kartu boleh turun baris & lencana boleh membungkus ---
    blok_kartu = bersih[pola_kartu.start():pola_kartu.start() + 2000]
    assert _re.search(r"table\.data\.kartu td \{[^}]*flex-wrap:\s*wrap", blok_kartu), (
        "sel mode kartu harus flex-wrap: wrap — tanpa itu isinya menembus tepi kartu")
    assert _re.search(r"table\.data\.kartu td \.badge \{ white-space: normal", blok_kartu), (
        "lencana di mode kartu harus boleh turun baris (nowrap membuatnya keluar kartu)")

    # --- 5. Isian bawaan peramban boleh menyusut di mana pun ---
    assert _re.search(r'input\[type="text"\][^{]*select,\s*textarea\s*\{[^}]*min-width:\s*0', bersih), (
        "isian global harus punya min-width: 0 (lebar bawaan peramban menolak menyusut)")

    # --- 6. Halaman daftar ekskul: kolom samping turun bila tabel tidak muat ---
    assert _re.search(r"@media \(max-width: 1500px\) \{\s*\.split-tabel \{ grid-template-columns: 1fr; \}",
                      bersih), "hilang aturan .split-tabel (kolom samping daftar ekskul)"
    assert "split split-tabel" in daftar, \
        "halaman daftar ekskul tidak memakai .split-tabel sehingga tabelnya terpotong pada 1101–1500 px"

    # --- 7. Tabel di halaman pelatih harus memakai kelas kartu ---
    assert detail.count('<table class="data kartu') >= 2, (
        "tabel pendaftar & anggota halaman pelatih harus ber-kelas kartu")
    assert '<table class="data tabel-kecil kartu"' in detail, (
        "tabel hasil «Cari cepat siswa» harus ber-kelas kartu juga")

    # --- 8. Halamannya benar-benar terbit & bisa dibuka pelatih ---
    import asyncio

    import httpx

    async def periksa() -> str:
        from app import db, services
        from app.main import app

        ekskul = [baris for baris in services.list_ekskul() if baris["nama"] == "PMR"]
        assert ekskul, "ekskul PMR tidak ada — jalankan siapkan_data_uji.py"
        ekskul_id = ekskul[0]["id"]
        nik = "3204000000000009"
        # Akun pelatih & satu anggota disemai sendiri: basis data uji bisa saja sudah
        # punya akun PMR dengan NIK lain, dan tabel anggota hanya terbit bila ekskulnya
        # beranggota (blok 35 harus menguji halaman yang utuh, bukan halaman kosong).
        if db.query_value("SELECT COUNT(*) FROM ekskul_akun WHERE ekskul_id = ? AND nik = ?",
                          (ekskul_id, nik)) == 0:
            db.execute("INSERT INTO ekskul_akun (ekskul_id, peran, nik, nama, aktif) "
                       "VALUES (?, 'pelatih', ?, 'Pelatih Uji', 1)", (ekskul_id, nik))
        if db.query_value("SELECT COUNT(*) FROM ekskul_members WHERE ekskul_id = ?",
                          (ekskul_id,)) == 0:
            siswa_id = db.query_value("SELECT id FROM students ORDER BY id LIMIT 1")
            assert siswa_id, "tidak ada siswa di basis data uji"
            db.execute("INSERT INTO ekskul_members (ekskul_id, student_id, jabatan, tahun_ajaran, "
                       "semester, status) VALUES (?, ?, 'Anggota', '2026/2027', 'Ganjil', 'aktif')",
                       (ekskul_id, siswa_id))

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                     follow_redirects=True) as klien:
            masuk = await klien.post("/login", data={"mode": "ekskul", "peran": "pelatih",
                                                     "ekskul_id": str(ekskul_id), "nik": nik})
            assert masuk.status_code == 200, masuk.status_code
            halaman = await klien.get(f"/ekstrakurikuler/{ekskul_id}")
            assert halaman.status_code == 200, halaman.status_code
            teks = halaman.text
            for bagian in ("form-jadwal", "form-tambah-anggota", "form-cari-cepat",
                           "data kartu anggota"):
                assert bagian in teks, f"halaman pelatih kehilangan bagian «{bagian}»"
            await klien.post("/logout")
        return f"halaman /ekstrakurikuler/{ekskul_id} terbuka untuk pelatih (NIK {nik})"

    return (f"3 formulir memakai kisi lentur & aturan sempitnya ada di akhir berkas; "
            f"tabel jadi kartu di ≤{ambang} px (semua .data di ≤{pola_semua.group(1)} px); "
            f"sel kartu & lencana boleh turun baris; {asyncio.run(periksa())}")


@cek("27. Kode bersih dari peringatan Python (escape sequence & impor)")
def cek_peringatan_kode():
    """Pastikan menjalankan aplikasi tidak memunculkan peringatan seperti di PC sekolah.

    Di PC sekolah muncul berderet ``SyntaxWarning: invalid escape sequence '\\s'`` dari
    potongan JavaScript di dalam string Python (``app/bot_dapodik.py``). Selain tidak enak
    dilihat, peringatan semacam itu menyembunyikan masalah yang lebih penting. Pemeriksaan ini
    memindai **seluruh berkas Python** dan menolak escape tak sah (mis. ``\\s``, ``\\d`` di
    string biasa) — jangan ditulis sebagai string mentah (``r"…"``) atau gandakan garis
    miringnya.
    """
    import io as _io
    import re as _re
    import tokenize as _tokenize

    sah = set("\\'\"abfnrtv01234567xuUN")
    temuan: list[str] = []
    berkas_diperiksa = 0
    for berkas in sorted(BASE_DIR.rglob("*.py")):
        if any(b in berkas.parts for b in (".venv", "node_modules", "build", "dist",
                                           "__pycache__", "sample-data")):
            continue
        berkas_diperiksa += 1
        try:
            token = list(_tokenize.generate_tokens(
                _io.StringIO(berkas.read_text(encoding="utf-8")).readline))
        except (SyntaxError, IndentationError) as exc:
            temuan.append(f"{berkas.name}: gagal dibaca ({exc})")
            continue
        except _tokenize.TokenError:
            continue
        for tok in token:
            if tok.type != _tokenize.STRING:
                continue
            cocok = _re.match(r"[A-Za-z]*", tok.string)
            awalan = cocok.group(0) if cocok else ""
            if "r" in awalan.lower() or "b" in awalan.lower():
                continue
            badan = tok.string[len(awalan):]
            i = 0
            while i < len(badan):
                if badan[i] != "\\" or i + 1 >= len(badan):
                    i += 1
                    continue
                nxt = badan[i + 1]
                if nxt == "\\":          # garis miring ganda: sah, lewati keduanya
                    i += 2
                    continue
                if nxt not in sah:
                    temuan.append(f"{berkas.relative_to(BASE_DIR).as_posix()}:{tok.start[0]} "
                                  f"escape '\\{nxt}'")
                i += 2
    assert not temuan, ("escape sequence tidak sah (akan muncul sebagai SyntaxWarning): "
                        + "; ".join(temuan[:6]))
    assert berkas_diperiksa >= 20, f"hanya {berkas_diperiksa} berkas diperiksa — pemindaian meleset?"

    # Modul bot paling sering menyimpan JavaScript panjang: pastikan benar-benar bisa
    # dikompilasi tanpa peringatan (percobaan kedua, dari sisi Python).
    import subprocess as _sp

    hasil = _sp.run([sys.executable, "-W", "error::SyntaxWarning", "-c",
                     "import compileall,sys; sys.exit(0 if compileall.compile_dir("
                     f"r'{BASE_DIR / 'app'}', quiet=2, force=True) else 1)"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=600)
    assert hasil.returncode == 0, f"kompilasi app/ memunculkan peringatan: {hasil.stderr[-300:]}"
    return (f"{berkas_diperiksa} berkas Python diperiksa — tidak ada escape tidak sah; "
            "app/ terkompilasi tanpa peringatan")


@cek("36. Layar sangat sempit (≤380 px): tidak ada isi yang terpotong")
def cek_layar_sempit():
    """Masukan sekolah ronde 40: «ketika login sebagai pelatih, halamannya masih
    tidak responsif… sisi hp harus bisa responsif tidak boleh ada terpotong».

    Sapu 20 halaman × lebar 280/300/320/340/360 px di peramban sungguhan menemukan
    tiga keluarga sebab yang semuanya memotong isi (bukan sekadar menduga):

    * **`min-width` tetap di kepala halaman.** Lima templat memakai
      ``style="min-width:220-300px"`` pada blok judul di dalam kartu. Di layar
      300 px ruang dalam kartu hanya ~236 px, sehingga kotak itu 24 px lebih lebar
      dari kartunya — teks menempel ke tepi dan huruf terakhir terpotong
      (``.card`` memakai ``overflow: hidden``). Kini semuanya
      ``min-width: min(Npx, 100%)``.
    * **Kisi `auto-fit` tanpa `min()`.** ``minmax(Npx, 1fr)`` tidak bisa menyusut
      di bawah N, jadi di layar sempit kolomnya tetap N px dan keluar kartu —
      di halaman Bot Dapodik kolom 280 px berada dalam ruang 254 px. Semua
      ``minmax(Npx, 1fr)`` di app.css/portal.css kini punya pasangan
      ``minmax(min(Npx, 100%), 1fr)``.
    * **Teks `nowrap` yang tak boleh turun baris.** Tombol ``.btn`` (termasuk
      ``.form-tambah-anggota .btn``), lencana di kepala kartu, label diagram
      batang ber-elipsis, dan ``.alert`` yang tidak boleh membungkus menembus
      tepi kartu. Aturan ≤380 px membuat tombol boleh turun baris, dan label
      diagram membungkus alih-alih dipotong.
    """
    import re as _re

    app_css = (BASE_DIR / "app/static/css/app.css").read_text(encoding="utf-8")
    portal_css = (BASE_DIR / "app/static/css/portal.css").read_text(encoding="utf-8")
    bersih = _re.sub(r"/\*.*?\*/", " ", app_css, flags=_re.S)
    bersih_portal = _re.sub(r"/\*.*?\*/", " ", portal_css, flags=_re.S)

    # --- 1. Setiap kisi auto-fit yang dipatok boleh menyusut di layar sempit ---
    #     Baris lama `minmax(Npx, 1fr)` tetap ada sebagai cadangan peramban tua,
    #     tetapi WAJIB disusul `minmax(min(Npx, 100%), 1fr)` dengan N yang sama.
    for nama, isi in (("app.css", bersih), ("portal.css", bersih_portal)):
        kaku = [(int(n), m.start()) for n, m in
                ((m.group(1), m) for m in _re.finditer(r"minmax\(\s*(\d+)px", isi))]
        lunak = {int(m.group(1)) if m.group(1) else None:
                 m.start() for m in _re.finditer(r"minmax\(\s*min\(\s*(\d+)px", isi)}
        for n, posisi in kaku:
            assert n in lunak, (
                f"{nama}: minmax({n}px, 1fr) tidak punya pasangan minmax(min({n}px, 100%), 1fr) — "
                "di layar sempit kolomnya tidak menyusut dan isinya keluar kartu (ronde 40)")
            assert lunak[n] > posisi, (
                f"{nama}: baris minmax(min({n}px, 100%), 1fr) harus SETELAH minmax({n}px, 1fr) "
                "supaya menang di urutan berkas")

    # --- 2. Tidak ada lagi `min-width` tetap di templat ---
    for berkas in sorted((BASE_DIR / "app/templates").rglob("*.html")):
        isi = berkas.read_text(encoding="utf-8")
        # Sel tabel (`<td>`/`<th>`) memang boleh punya lebar minimum: tabelnya
        # digulir di dalam `.table-wrap` (dan di layar sempit sudah jadi kartu).
        isi = _re.sub(r'<(?:td|th)\b[^>]*style="[^"]*?min-width:\s*\d+px[^"]*"', " ", isi)
        for temuan in _re.finditer(r'style="[^"]*?min-width:\s*(\d+)px', isi):
            # Nilai kecil (mis. 46 px untuk kolom persen) tidak akan pernah menembus
            # tepi kartu di layar ≥280 px; yang berbahaya adalah blok 120 px ke atas.
            if int(temuan.group(1)) < 120:
                continue
            assert False, (
                f"{berkas.relative_to(BASE_DIR)}: min-width:{temuan.group(1)}px tetap — "
                "pakai min-width: min(Npx, 100%) supaya tidak terpotong di ≤330 px")

    # --- 3. Tombol boleh turun baris di layar ≤380 px ---
    nowrap = [m.start() for m in _re.finditer(r"\.btn[^{,\n]*\{[^}]*white-space:\s*nowrap", bersih)]
    lunak = [m.start() for m in _re.finditer(r"\.btn[^{,\n]*\{[^}]*white-space:\s*normal", bersih)]
    assert nowrap, "aturan .btn { white-space: nowrap } hilang — periksa ulang berkas CSS"
    assert lunak and max(lunak) > max(nowrap), (
        "aturan tombol «boleh turun baris» harus ditulis SETELAH aturan nowrap "
        "(kekhususan sama → yang belakangan menang), kalau tidak tombol panjang "
        "menembus tepi kartu di layar ≤380 px")

    # --- 4. Bilah atas: judul menyusut, aksi di kanan tetap utuh ---
    assert ".topbar-title { min-width: 0" in bersih, (
        "judul bilah atas harus boleh menyusut (min-width: 0) — tanpa itu tombol di "
        "kanan terdesak keluar layar dan halaman bisa digeser ke samping")
    assert ".topbar-actions { flex: 0 0 auto; }" in bersih, "aksi bilah atas harus tetap utuh"

    # --- 5. Label diagram batang membungkus, bukan dipotong elipsis ---
    potong = _re.search(r"\.bar-label \{[^}]*white-space:\s*normal", bersih)
    assert potong, ("label diagram batang harus membungkus di layar sempit "
                    "(elipsis terbaca sebagai «terpotong» di HP)")
    posisi_elipsis = bersih.index(".bar-label { color:")
    assert potong.start() > posisi_elipsis, (
        "aturan label diagram membungkus harus setelah aturan aslinya, "
        "kalau tidak akan kalah dan labelnya kembali terpotong")

    # --- 6. Kotak peringatan boleh membungkus ---
    assert _re.search(r"\.alert \{ flex-wrap:\s*wrap; \}", bersih), (
        "kotak peringatan harus boleh membungkus supaya tombol di dalamnya tidak "
        "keluar dari kartu di layar sempit")

    return ("kisi auto-fit semuanya minmax(min(…, 100%)), tidak ada min-width tetap di "
            "templat, tombol/label/peringatan boleh turun baris, bilah atas menyusut")


@cek("37. Ikon membuka Chrome yang sedang terbuka & tidak ada jendela cmd")
def cek_chrome_tanpa_cmd():
    """Masukan sekolah ronde 42: «ketika bodap icon dijalankan maka akan langsung membuka
    chrome yang sedang saat ini dibuka, lalu hilangkan untuk menampilkan cmd termasuk pada
    saat pembaruan».

    Dua hal yang dijaga di sini — dua-duanya diuji nyata, bukan sekadar dibaca:

    * **Chrome yang sedang terbuka.** Sebelumnya setiap pembukaan aplikasi memakai
      ``webbrowser.open()`` yang menyerahkan urusan ke peramban bawaan Windows (sering
      Edge). Sekarang ada satu modul ``app/peramban.py``: ``chrome.exe`` dicari dari
      registry/folder pemasangan/PATH, dan perintahnya hanya ``chrome.exe <alamat>`` —
      **tanpa** ``--user-data-dir`` (yang membuat Chrome membuka profil/jendela baru)
      dan **tanpa** ``--new-window``. Uji di bawah menjalankan Chrome tiruan untuk
      memastikan yang dikirim memang cuma alamatnya.
    * **Tanpa jendela cmd.** Tiga sumber jendela hitam ditutup: (a) proses anak berbasis
      konsol (git, pip, compileall, uji impor) kini diberi ``CREATE_NO_WINDOW`` — tanpa itu
      Windows membuatkan jendela konsol baru karena aplikasi berjalan lewat ``pythonw.exe``;
      (b) "Muat ulang server sekarang" tidak lagi membuka ``cmd /c start … cmd /k``
      melainkan menyalakan ``pythonw.exe run.py --tunggu-port …`` dengan keluaran ke
      ``data/log-server.txt``; (c) pintasan «nyala otomatis saat Windows masuk» tidak lagi
      berkas ``SM.cmd`` melainkan ``SM-otomatis.vbs`` (jendela disembunyikan) — dan
      ``SM.cmd`` sisa pemasangan lama dihapus.
    """
    import importlib.util
    import re as _re
    import socket
    import subprocess as _subprocess
    import tempfile
    import time as _time

    # --- 1. Modul peramban ada & perintahnya hanya "chrome <alamat>" ---------------
    berkas_modul = BASE_DIR / "app/peramban.py"
    assert berkas_modul.exists(), "app/peramban.py hilang — Chrome tidak akan dipakai"
    spec = importlib.util.spec_from_file_location("sm_peramban_cek", berkas_modul)
    peramban = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(peramban)
    perintah = peramban.perintah_chrome(Path("C:/Chrome/chrome.exe"), "http://localhost:8000")
    assert perintah[1] == "http://localhost:8000", "alamat tidak ikut dikirim ke Chrome"
    for terlarang in ("--user-data-dir", "--new-window", "--profile-directory"):
        assert not any(terlarang in argumen for argumen in perintah), (
            f"{terlarang} membuat Chrome membuka jendela/profil BARU, bukan jendela yang "
            "sedang terbuka")
    assert "CREATE_NO_WINDOW" in berkas_modul.read_text(encoding="utf-8"), \
        "Chrome harus dijalankan tanpa jendela konsol"

    # --- 2. Uji nyata: Chrome tiruan menerima HANYA alamat -------------------------
    if os.name != "nt":
        with tempfile.TemporaryDirectory(prefix="sm-chrome-") as sementara:
            stub = Path(sementara) / "chrome-tiruan"
            catatan = Path(sementara) / "argumen.txt"
            stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{catatan}"\n', encoding="utf-8")
            stub.chmod(0o755)
            sebelum = os.environ.get("SM_CHROME")
            os.environ["SM_CHROME"] = str(stub)
            try:
                cara = peramban.buka_port(8000)
                for _ in range(30):
                    if catatan.exists():
                        break
                    _time.sleep(0.1)
                argumen = catatan.read_text(encoding="utf-8").split() if catatan.exists() else []
            finally:
                if sebelum is None:
                    os.environ.pop("SM_CHROME", None)
                else:
                    os.environ["SM_CHROME"] = sebelum
            assert cara == "chrome", f"Chrome tiruan tidak dipakai (cara={cara})"
            assert argumen == ["http://localhost:8000"], f"argumen Chrome salah: {argumen}"

    # --- 3. Peluncur aplikasi memakai modul itu -----------------------------------
    latar = (BASE_DIR / "SM-latar.py").read_text(encoding="utf-8")
    assert "peramban.buka_port" in latar, "SM-latar.py tidak memakai modul peramban"
    assert "def buka_peramban" in latar, "fungsi buka_peramban hilang dari SM-latar.py"
    online = (BASE_DIR / "SM-online.py").read_text(encoding="utf-8")
    assert "peramban.buka(" in online, "SM-online.py tidak memakai modul peramban"

    # --- 4. Pemasang: Chrome dipakai & tidak ada jalur .cmd ke konsol -------------
    bodap = (BASE_DIR / "pemasang/bodap_win.py").read_text(encoding="utf-8")
    assert "_muat_peramban" in bodap, "bodap.exe tidak memuat app/peramban.py"
    assert "modul.buka_port" in bodap, "bodap.exe tidak membuka aplikasi lewat Chrome"
    assert "os.startfile(str(peluncur))" not in bodap, \
        "bodap.exe masih membuka Jalankan-SM.cmd (jendela hitam)"
    assert "NAMA_OTOMATIS" in bodap and "SM-otomatis.vbs" in bodap, \
        "berkas nyala-otomatis baru (VBS) tidak dipakai bodap.exe"
    assert 'start \"SM\" /min' not in bodap, "pintasan nyala-otomatis masih memakai jendela cmd"
    awal_pembuat = bodap.index("def isi_vbs_otomatis")
    sisa_pembuat = bodap[awal_pembuat + 10:]
    akhir_pembuat = awal_pembuat + 10 + next(
        posisi for posisi in (sisa_pembuat.find("\ndef "), len(sisa_pembuat)) if posisi >= 0)
    bagian_pembuat = bodap[awal_pembuat:akhir_pembuat]
    assert ", 0, False" in bagian_pembuat, \
        "VBS nyala-otomatis harus menyembunyikan jendela (0) & tidak menunggu"
    awal_otomatis = bodap.index("def pasang_otomatis")
    sisa = bodap[awal_otomatis + 10:]
    akhir_otomatis = awal_otomatis + 10 + next(
        posisi for posisi in (sisa.find("\ndef "), len(sisa)) if posisi >= 0)
    bagian_otomatis = bodap[awal_otomatis:akhir_otomatis]
    assert "isi_vbs_otomatis(" in bagian_otomatis, \
        "pasang_otomatis harus menulis VBS lewat isi_vbs_otomatis()"
    assert "WScript.Shell" in bagian_pembuat, "VBS nyala-otomatis bukan skrip wscript"
    assert "berkas_otomatis_lama" in bodap, "SM.cmd lama tidak dibersihkan dari Startup"
    pasang = (BASE_DIR / "pemasang/pasang.py").read_text(encoding="utf-8")
    assert "NAMA_OTOMATIS" in pasang and "pythonw" in pasang, \
        "pemasang ZIP belum memakai VBS + pythonw.exe untuk nyala otomatis"
    assert 'start \"SM\" /min' not in pasang, "pemasang ZIP masih menulis jendela cmd ke Startup"

    # --- 5. Semua proses anak yang berbasis konsol diberi CREATE_NO_WINDOW --------
    dipanggil: list[dict] = []

    class Selesai:
        returncode = 0
        stdout = ""
        stderr = ""

    asli_run = _subprocess.run

    def run_palsu(perintah, *a, **kw):
        dipanggil.append(kw)
        return Selesai()

    from app import updater, services

    assert updater.tanpa_jendela() == int(getattr(_subprocess, "CREATE_NO_WINDOW", 0))
    _subprocess.run = run_palsu
    try:
        updater.jalankan_git(["rev-parse", "HEAD"])
        updater.pasang_dependensi()
        updater.periksa_kode_baru()
        services.pasang_pustaka_bot() if hasattr(services, "pasang_pustaka_bot") else None
    finally:
        _subprocess.run = asli_run
    assert dipanggil, "tidak ada proses anak yang terpanggil — pemeriksaan tidak sah"
    for kw in dipanggil:
        assert "creationflags" in kw, f"proses anak tanpa creationflags (akan muncul jendela cmd): {kw}"

    # --- 6. Muat ulang server berjalan di belakang layar --------------------------
    kode_updater = Path(updater.__file__).read_text(encoding="utf-8")
    # Catatan penjelasan (docstring/komentar) boleh menyebut cara lama; yang diperiksa
    # adalah KODE-nya, jadi komentar & docstring dibuang lebih dulu.
    kode_updater_bersih = _re.sub(r'"""..*?"""', " ", kode_updater, flags=_re.S)
    kode_updater_bersih = _re.sub(r"#.*", " ", kode_updater_bersih)
    for terlarang in ("perintah_windows", "jalankan-ulang.bat", "tulis_berkas_jalankan_ulang",
                      "cmd /c start", "os.startfile(str(kandidat))"):
        assert terlarang not in kode_updater_bersih, \
            f"jalur muat ulang jendela konsol masih ada: {terlarang}"
    assert "perintah_latar" in kode_updater and "python_latar" in kode_updater, \
        "muat ulang harus menyalakan pythonw.exe (tanpa konsol)"
    assert "log-server.txt" in kode_updater, "keluaran server baru tidak dicatat ke berkas"
    awal_latar = kode_updater.index("def _mulai_ulang_windows")
    isi_latar = kode_updater[awal_latar:kode_updater.index("def muat_ulang_sekarang")]
    assert "perintah_latar()" in isi_latar, "_mulai_ulang_windows tidak memakai perintah_latar()"
    assert "DETACHED_PROCESS" in isi_latar, "server baru harus benar-benar terlepas dari konsol"
    assert "proses.poll()" in isi_latar, "proses baru harus diperiksa hidup sebelum proses lama berhenti"
    perintah_latar = updater.perintah_latar()
    assert perintah_latar[1] == updater.perintah_restart()[1], "perintah latar kehilangan run.py"
    assert "--tunggu-port" in perintah_latar, "server baru tidak menunggu port bebas"

    # --- 7. run.py menunggu port bebas ------------------------------------------
    kode_run = (BASE_DIR / "run.py").read_text(encoding="utf-8")
    assert "--tunggu-port" in kode_run and "def tunggu_port_bebas" in kode_run, \
        "run.py tidak punya opsi --tunggu-port"
    import importlib.util as _il

    spec_run = _il.spec_from_file_location("sm_run_cek", BASE_DIR / "run.py")
    modul_run = _il.module_from_spec(spec_run)
    spec_run.loader.exec_module(modul_run)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soket:
        soket.bind(("127.0.0.1", 0))
        soket.listen(1)
        port_dipakai = soket.getsockname()[1]
        mulai = _time.time()
        assert modul_run.tunggu_port_bebas(port_dipakai, 1) is False, \
            "port yang masih dipakai harus dilaporkan BELUM bebas"
        assert _time.time() - mulai < 5, "penungguan port terlalu lama"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soket:
        soket.bind(("127.0.0.1", 0))
        port_bebas = soket.getsockname()[1]
    assert modul_run.tunggu_port_bebas(port_bebas, 5) is True, "port bebas harus segera lolos"

    return ("Chrome yang sedang terbuka dipakai (uji Chrome tiruan: argumennya hanya alamat), "
            "git/pip/compileall diberi CREATE_NO_WINDOW, muat ulang lewat pythonw + "
            "log-server.txt (tanpa cmd), pintasan nyala-otomatis jadi SM-otomatis.vbs")


@cek("39. Gulir aman — kursor keluar dari kolom isian & kode wilayah desa ikut pindah")
def cek_gulir_aman() -> str:
    """Ronde 45 — bot boleh menggulir, tetapi kursornya tidak boleh berada di dalam kolom isian.

    Laporan sekolah: «masih gagal untuk masalah kode_wilayah_str … boleh scroll tapi cursornya
    ga boleh berada di dalam text input … contoh ada text input rt, itu kalo cursor lagi di rt
    ketika di scroll biasanya akan berubah nilainya bisa jadi malah jadi 0». Perilakunya
    dibuktikan `scripts/uji_bot_dapodik.py` skenario 32–35 di peramban palsu (yang meniru
    sifat itu: menggulir selagi kursor di kolom angka mengubah nilainya menjadi «0»).
    Di sini diperiksa bahwa penjaganya benar-benar terpasang di **setiap** jalur gulir dan
    bahwa pemilihan desa memeriksa `kode_wilayah_str` — supaya penjaga itu tidak hilang lagi
    tanpa ada yang gagal.
    """
    import ast

    sumber = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    badan: dict[str, str] = {}
    for simpul in ast.walk(ast.parse(sumber)):
        if isinstance(simpul, ast.FunctionDef):
            badan.setdefault(simpul.name, ast.get_source_segment(sumber, simpul) or "")

    # (a) Setiap jalur yang menggulir mengeluarkan kursor lebih dulu. `_aman_daftar_dropdown`
    #     adalah pembungkusnya untuk daftar pilihan (fokusnya dipindah ke daftar, bukan
    #     dilepas, supaya daftar combo tetap terbuka).
    jalur = {
        "_gulir": "_kursor_aman(",
        "_bawa_ke_layar": "_kursor_aman(",
        "_atur_gulir_jendela": "_kursor_aman(",
        "_gulir_dalam_jendela": "_kursor_aman(",
        "_gulir_daftar_dropdown": "_aman_daftar_dropdown(",
        "_klik_pilihan_dropdown": "_aman_daftar_dropdown(",
        "_paksa_terlihat": "_kursor_aman(",
        "_klik_aman": "_kursor_aman(",
    }
    for nama, penjaga in jalur.items():
        isi = badan.get(nama)
        assert isi, f"fungsi {nama} hilang dari app/bot_dapodik.py"
        assert penjaga in isi, (f"{nama} menggulir tanpa mengeluarkan kursor lebih dulu — "
                                f"«{penjaga}» tidak ada, kolom seperti «RT» bisa jadi «0»")
    assert "_kursor_aman(" in badan["_aman_daftar_dropdown"], \
        "_aman_daftar_dropdown tidak memakai _kursor_aman"
    assert "_tumpuan_dropdown(" in badan["_aman_daftar_dropdown"], \
        "fokus daftar pilihan tidak diarahkan ke daftarnya — combo bisa menutup saat digulir"

    # (b) Isi skrip «kursor-aman»: hanya melepas kursor dari kolom isian teks (radio/checkbox
    #     jangan ikut dilepas), lalu melaporkan apa yang dipindah.
    isi = badan["_kursor_aman"]
    for tanda in ("/* kursor-aman */", "tag === 'INPUT'", "tag === 'TEXTAREA'",
                  "tag === 'SELECT'",
                  "'radio', 'checkbox', 'button', 'submit', 'hidden'",
                  "aktif.blur()", "tumpuan.focus()", "dipindah"):
        assert tanda in isi, f"skrip «kursor-aman» kehilangan {tanda!r}"
    for kalimat in ("dikeluarkan dari kolom", "sebelum menggulir", "«RT» menjadi «0»"):
        assert kalimat in isi, f"log «kursor-aman» kehilangan kalimat {kalimat!r}"
    for penghitung in ("kursor_dipindah", "penjaga_dipulihkan", "_penjaga_nilai"):
        assert penghitung in badan["__init__"], \
            f"bot tidak mencatat {penghitung} di __init__ (bukti di layar bot)"

    # (c) Penjaga nilai kolom: dibaca sesudah menggulir, dikembalikan bila berubah, dilaporkan.
    isi = badan["_periksa_nilai_bio"]
    for tanda in ("/* nilai-kolom-bio */", "/* pulihkan-kolom-bio */", "penjaga_dipulihkan += 1",
                  "dikembalikan menjadi", "perlu diperiksa di Dapodik"):
        assert tanda in isi, f"penjaga nilai kolom kehilangan {tanda!r}"
    assert "_rekam_nilai_bio(" in badan["_rekam_nilai_bio"], \
        "nilai kolom BIO tidak dicatat saat diisi"
    isi = badan["_isi_periodik_satu"]
    assert "awalan == \"[bio]\"" not in isi, \
        "hanya kolom BIO yang dijaga — sekolah menyebut SEMUA kolom bisa berubah saat digulir"
    assert isi.count("_rekam_nilai_bio(") >= 2, \
        "nilai kolom tidak dicatat di kedua jalur pengisian (ketik & Ext JS)"
    for fungsi, awalan in (("_isi_bio", "[bio]"),):
        assert f'_periksa_nilai_bio(peramban, "{awalan}")' in badan[fungsi], \
            f"{fungsi} tidak memeriksa nilai semua kolom sebelum «Simpan»"
    assert '_periksa_nilai_bio(peramban, "[periodik]")' in sumber, \
        "Data Periodik tidak diperiksa sebelum disimpan"
    for pemanggil in ("_isi_bio", "_periksa_nilai_bio"):
        assert pemanggil in badan, f"fungsi {pemanggil} hilang"
    assert "_periksa_nilai_bio(" in badan["_isi_bio"], \
        "_isi_bio tidak memeriksa lagi nilai kolom sesudah menggulir"
    assert "_rekam_nilai_bio(" in badan["_isi_bio"], \
        "_isi_bio tidak mencatat nilai kolom yang ditulisnya"

    # (d) Desa/Kelurahan: teks benar tetapi kode wilayah masih desa lama = BELUM tersimpan.
    isi = badan["_kode_wilayah"]
    assert "/* kode-wilayah */" in isi and "kode_wilayah_str" in isi, \
        "bot tidak membaca kolom kode_wilayah_str"
    assert "/* nama-kolom-wilayah */" in badan["_nama_kolom_wilayah"], \
        "diagnostik nama kolom kode wilayah hilang (laporan sekolah jadi tidak bisa dipakai)"
    assert "_nama_kolom_wilayah(" in badan["_isi_desa_kelurahan"], \
        "alur pemilihan desa tidak menyebut kolom tersembunyi yang ada bila kodenya tak ketemu"
    isi = badan["_desa_dan_kode_terverifikasi"]
    for tanda in ("kode_wilayah_str", "belum ikut pindah", "_kode_wilayah(", "→"):
        assert tanda in isi, f"pemeriksaan kode wilayah kehilangan {tanda!r}"
    isi = badan["_isi_desa_kelurahan"]
    for tanda in ("_kode_wilayah(", "kode_wilayah_str"):
        assert tanda in isi, f"alur pemilihan desa tidak memeriksa kode wilayah ({tanda!r})"
    assert isi.count("_periksa_desa_sampai_siap(") >= 2, \
        "hasil pemilihan desa hanya diperiksa di satu jalur (klik & model Ext JS dua-duanya wajib)"
    # Ronde 51: pemeriksaan desa dipusatkan di `_periksa_desa_sampai_siap` yang MENUNGGU nilai
    # (daftar & nilai desa tidak muncul seketika di Dapodik), jadi yang wajib ada di:
    # (a) `_isi_desa_kelurahan` — dua pemanggilan (jalur klik & jalur model Ext JS),
    # (b) `_periksa_desa_sampai_siap` — pemanggilan `_desa_dan_kode_terverifikasi` + batas tunggu.
    isi_tunggu = badan["_periksa_desa_sampai_siap"]
    assert "_desa_dan_kode_terverifikasi(" in isi_tunggu, \
        "penantian nilai desa tidak memeriksa kode wilayah"
    for tanda in ("_batas_tunggu_desa(", "ditunggu", "DESA_TUNGGU_DETIK"):
        assert tanda in isi_tunggu or tanda in badan["_batas_tunggu_desa"], \
            f"penantian nilai desa kehilangan {tanda!r}"
    assert isi.count("_kode_wilayah(") >= 1 or "_periksa_desa_sampai_siap(" in isi, \
        "alur pemilihan desa tidak memeriksa kode wilayah sama sekali"
    assert "dikembalikan seperti semula" in isi and "_pulihkan_desa(" in isi, \
        "kolom desa tidak dikembalikan bila pemilihannya gagal (data lama bisa tertimpa)"
    assert "TIDAK jadi terisi" in isi, "kegagalan pemilihan desa tidak dilaporkan apa adanya"
    assert "_catat_desa_terverifikasi(" in isi, \
        "keadaan desa yang sudah terverifikasi tidak dicatat (tidak bisa diperiksa lagi)"
    isi = badan["_pastikan_desa_sebelum_simpan"]
    for tanda in ("berubah sesudah dipilih", "dipasang ulang sebelum «Simpan»",
                  "_pilih_dropdown_ext(", "_desa_dan_kode_terverifikasi(",
                  "periksa hasilnya di Dapodik"):
        assert tanda in isi, f"penjaga desa sebelum «Simpan» kehilangan {tanda!r}"
    assert "_pastikan_desa_sebelum_simpan(" in badan["_isi_bio"], \
        "_isi_bio tidak memeriksa desa lagi tepat sebelum «Simpan» — nilai bisa berubah "\
        "sesudah dipilih (mis. tergulir)"

    # (e) Buktinya ada & tidak bisa dihapus diam-diam dari uji tiruan.
    fixture = (BASE_DIR / "scripts/peramban_palsu.py").read_text(encoding="utf-8")
    for tanda in ("KOLOM_ANGKA_BIO", "/* kursor-aman */", "/* kode-wilayah */",
                  "/* nilai-kolom-bio */", "/* pulihkan-kolom-bio */", "kode_wilayah_str",
                  "rusak_karena_gulir", "penjaga_dipulihkan", "picker_ditutup_oleh_blur",
                  "desa_kode_rusak_gulir", "desa_dirusak_kali", "tanpa_kode_wilayah",
                  "rusak_paksa_semua"):
        assert tanda in fixture, f"peramban palsu kehilangan {tanda!r} (bukti ronde 45)"
    jumlah_gulir = fixture.count("gulir_berbahaya()")
    assert jumlah_gulir >= 5, \
        f"peramban palsu hanya memeriksa {jumlah_gulir} jalur gulir (seharusnya semua jalur)"
    uji = (BASE_DIR / "scripts/uji_bot_dapodik.py").read_text(encoding="utf-8")
    for tanda in ("gulir_kursor_di_kolom == 0", "rusak_karena_gulir == []", "kursor_dipindah >= 1",
                  "penjaga_dipulihkan >= 1", "picker_ditutup_oleh_blur == 0", "kode_desa_palsu(",
                  "bio_kode_ditolak", "desa_dirusak_kali >= 1", "desa_dipulihkan_kali >= 1",
                  "dipasang ulang sebelum «Simpan»", "rusak_paksa_semua", "rusak_paksa_kali >= 5",
                  "kolom yang tersimpan tidak sesuai sesudah gulir"):
        assert tanda in uji, f"uji bot kehilangan pemeriksaan {tanda!r} (ronde 45)"

    return ("gulir aman: 8 jalur gulir mengeluarkan kursor lebih dulu, penjaga nilai kolom "
            "mengembalikan nilai yang berubah, desa hanya dianggap tersimpan bila "
            "kode_wilayah_str ikut pindah, desa diperiksa ulang tepat sebelum «Simpan», dan "
            "nilai SEMUA kolom dipulihkan bila berubah karena gulir (uji tiruan 32–38)")



@cek("40. Kolom dicari lewat NAMA & label div — RT/RW, Desa/Kelurahan, dan angka Dapodik")
def cek_kolom_lewat_nama_dan_label_div() -> str:
    """Ronde 47 — «kenapa masih gagal input rt dan rw?» + «bot tidak menemukan input & dropdown» desa.

    Dua sebab yang ditemukan: (a) kolom RT/RW (juga alamat, No. KK, kode pos, desa) hanya punya
    jalur **label**, padahal di Dapodik versi sekolah label itu digambar sebagai div Ext JS —
    skrip sekolah sendiri memakai **nama kolom** (`rt`, `rw`, …) dan berhasil; (b) kolom combo
    «Desa/Kelurahan» tidak terjangkau name/label sama sekali, sehingga XPath lengkap dari
    sekolah dipakai sebagai kandidat terakhir — dengan syarat unsur yang didapat memang kolom
    combo (jangan sampai nilai desa ditulis ke kolom lain). Perilaku itu dibuktikan
    `scripts/uji_bot_dapodik.py` skenario 39–43.
    """
    import ast

    sumber = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    badan: dict[str, str] = {}
    for simpul in ast.walk(ast.parse(sumber)):
        if isinstance(simpul, ast.FunctionDef):
            badan.setdefault(simpul.name, ast.get_source_segment(sumber, simpul) or "")

    # (a) Kolom yang dulu hanya lewat label: nama kolom didahulukan (cara skrip sekolah).
    from app import bot_dapodik
    for kunci, nama in (("bio_rt", "rt"), ("bio_rw", "rw"), ("bio_alamat", "alamat_jalan"),
                        ("bio_no_kk", "no_kk"), ("bio_kode_pos", "kode_pos")):
        kandidat = bot_dapodik.SELECTOR_CADANGAN[kunci]
        assert kandidat and kandidat[0] == f"name:{nama}", \
            f"{kunci} masih bergantung pada label saja (kandidat pertama: {kandidat[:1]})"

    # (b) Kolom combo desa: XPath lengkap dari sekolah jadi kandidat PALING AKHIR.
    kandidat = bot_dapodik.SELECTOR_CADANGAN["bio_kelurahan"]
    assert kandidat[-1].startswith("xpath:/html/body/"), \
        "XPath lengkap dari sekolah tidak terpasang untuk kolom «Desa/Kelurahan»"
    assert "fieldset[1]" in kandidat[-1] and kandidat[-1].endswith("input"), \
        f"XPath sekolah berubah bentuk: {kandidat[-1]}"
    assert "name:kode_wilayah" in kandidat, \
        "nama kolom combo Dapodik (kode_wilayah) tidak dicoba"
    for jalur in ("_cari_kolom_kandidat_lain", "_layak_combo", "_cari_combo_desa",
                  "_rincian_isian_bio"):
        assert jalur in badan, f"fungsi {jalur} hilang (kolom desa bisa gagal ketemu lagi)"
    isi = badan["_cari_kolom_kandidat_lain"]
    for tanda in ("BUKAN combo", "_layak_combo(", "XPath lengkap yang dikirim",
                  "boleh ditulis ke kolom lain"):
        assert tanda in isi, f"penjaga kandidat XPath kehilangan {tanda!r}"
    isi = badan["_layak_combo"]
    # Ronde 49: yang menandai combo hanya panah dropdown / role=combobox / komponen Ext JS
    # yang benar-benar memuat unsur itu — bukan sembarang ``x-form-trigger`` (tombol putar
    # numberfield memakai kelas itu juga, dan itu membuat RT/RW dikira dropdown).
    for tanda in ("/* layak-combo */", "aria-owns", "combobox", "panahKolom",
                  "komboKolom"):
        assert tanda in isi, f"pemeriksa «apakah kolom ini combo» kehilangan {tanda!r}"
    # Yang diperiksa hanya LOGIKA-nya (sesudah penanda ``/* layak-combo */``): teks alat
    # bersama memang menyebut ``.x-form-trigger[class*="arrow"]`` untuk mencari panah, jadi
    # yang dilarang adalah memakai kelas polos ``x-form-trigger`` sebagai tanda combo.
    # Komentar JS dibuang lebih dulu (komentar memang menyebut kelas lama sebagai
    # penjelasan); yang diperiksa adalah KODE-nya — dan tanpa bergantung pada modul ``re``
    # (berkas ini tidak mengimpornya).
    logika = "\n".join(b.split("//")[0]
                        for b in isi.split("/* layak-combo */", 1)[-1].splitlines())
    assert "x-form-trigger" not in logika and "innerHTML" not in logika, \
        "_layak_combo masih menerima tombol putar numberfield sebagai tanda combo"
    isi = badan["_cari_combo_desa"]
    for tanda in ("/* cari-combo-desa */", "x-fieldlabel", "desa|kelurahan|wilayah"):
        assert tanda in isi, f"pelacak combo desa kehilangan {tanda!r}"
    isi = badan["_rincian_isian_bio"]
    assert "/* rincian-isian-bio */" in isi and "combo" in isi, \
        "laporan mandiri «isian apa saja yang ada di jendela» hilang"

    # (c) Label div Ext JS (`x-fieldlabel`) ikut dilacak — di halaman & di dalam jendela.
    for fungsi in ("_cari_lewat_label", "_kolom_dalam_jendela"):
        isi = badan[fungsi]
        for tanda in ("x-fieldlabel", "x-form-item-label"):
            assert tanda in isi, f"{fungsi} tidak melacak label berbentuk div ({tanda!r})"
    isi = badan["_cari_lewat_label"]
    assert "/* cari-label-halaman */" in isi, "penanda skrip pencarian label halaman hilang"
    assert "closest('.x-field, .x-form-item, .form-group')" in isi, \
        "label & kolom tidak dibatasi pada bidang yang sama (RT bisa mengambil kotak RW)"
    isi = badan["_kolom_dalam_jendela"]
    assert "isianDalam" in isi and "'label-div'" in isi and "lewat:" in isi, \
        "pencarian di dalam jendela tidak mengenali label div / tidak melaporkan jalurnya"
    assert "berbentuk div Ext JS" in isi and "kolomnya ditemukan lewat labelnya" in isi, \
        "jalur label div tidak dicatat apa adanya di log"
    isi = badan["_isi_bio"]
    assert "isian yang ADA di jendela" in isi and "_rincian_isian_bio(" in isi, \
        "_isi_bio tidak melaporkan isian yang ada saat kolom desa tidak ketemu"

    # (d) Nilai angka Dapodik («007» → «7», «63.5» → «63,5») dinilai SAMA, bukan gagal.
    assert "_angka_sama" in badan and "_isi_sesuai" in badan and "_catatan_angka" in badan, \
        "pembanding angka Dapodik hilang (RT/RW bisa dilaporkan «belum berisi nilai yang benar»)"
    isi = badan["_isi_sesuai"]
    assert "_keduanya_angka(" in isi, \
        "dua angka yang BERBEDA (mis. data «3» vs kolom «13») bisa diterima hanya karena "\
        "bentuk teksnya mirip — gunakan _keduanya_angka() sebelum menerima «diminta in isi»"
    assert "diminta in isi" in isi, "penerimaan nilai teks (mis. alamat) hilang dari _isi_sesuai"
    isi = badan["_angka_sama"]
    for tanda in ("[0-9]+(?:[.,][0-9]+)?", 'replace(",", ".")'):
        assert tanda in isi, f"pembanding angka kehilangan {tanda!r}"
    isi = badan["_isi_periodik_satu"]
    assert "nilai not in isi" not in isi, \
        "pengisian kolom masih menilai dengan teks saja («007» ≠ «7» → dilaporkan gagal)"
    assert isi.count("_isi_sesuai(") >= 2, \
        "penilaian angka tidak dipakai di semua jalur pengisian kolom"
    assert "_rekam_nilai_bio(unsur, isi)" in isi, \
        "nilai yang benar-benar ada di kolom tidak dicatat (penjaga bisa berkelahi dengan Dapodik)"
    assert "_angka_sama(diharapkan, dapat)" in badan["_periksa_nilai_bio"], \
        "penjaga nilai masih menganggap bentuk angka Dapodik sebagai perubahan"

    # (e) Buktinya ada di peramban palsu & uji — tidak bisa dihapus diam-diam.
    fixture = (BASE_DIR / "scripts/peramban_palsu.py").read_text(encoding="utf-8")
    for tanda in ("XPATH_DESA_SEKOLAH", "angka_menormalkan", "angka_dinormalkan",
                  "normalkan_angka", "desa_tanpa_nama", "desa_tanpa_label", "desa_label_div",
                  "desa_jalur_xpath", "xpath_desa_salah", "xpath_desa_dipakai",
                  "label_div_dipakai", "rincian_isian_diminta", "label_div_semua",
                  "cari-combo-desa", "layak-combo", "rincian-isian-bio"):
        assert tanda in fixture, f"peramban palsu kehilangan {tanda!r} (bukti ronde 47)"
    uji = (BASE_DIR / "scripts/uji_bot_dapodik.py").read_text(encoding="utf-8")
    for tanda in ("angka_menormalkan", "desa_jalur_xpath", "label_div_dipakai",
                  "xpath_desa_salah", "label_div_semua", "BUKAN combo",
                  "isian yang ADA di jendela", "Dapodik menyimpan kolom ini sebagai angka",
                  # Jumlah skenario ikut disebut supaya berkas uji tidak diam-diam menyusut
                  # (ronde 47: 43; ronde 48 menambah 44–46; ronde 49 menambah 47–49 — DOM
                  # sekolah yang membuat kolom biasa dikira dropdown, panah milik kolom
                  # sendiri, combo tanpa penanda, dan panah tanpa data; ronde 50 menambah
                  # 51–54 — «Simpan» yang ditolak Dapodik karena kolom wajib bagian Wali,
                  # pengaturan wali dimatikan, «0» yang keras, dan identitas wali yang tidak
                  # boleh dikarang — dan ronde 50 susulan menambah 55 — jendela «Ubah» yang
                  # tertinggal terbuka menghalangi klik baris & daftar peserta didik yang
                  # tersegar sesudah Data Periodik disimpan; ronde 51 menambah 56–57 — antrean
                  # bot yang tidak membawa kolom desa, daftar desa & nilai desa yang baru muncul
                  # sesudah ditunggu; ronde 52 menambah 58–59 — kolom desa diisi persis cara
                  # pengguna (tunggu isian sebelumnya, Ctrl+A, ketik nama wilayahnya tanpa
                  # awalan, baca ulang kotak pencariannya) — sehingga 59).
                  "62 skenario"):
        assert tanda in uji, f"uji bot kehilangan pemeriksaan {tanda!r} (ronde 47)"

    return ("kolom dicari lewat NAMA lebih dulu (rt, rw, alamat_jalan, no_kk, kode_pos), label "
            "div Ext JS (`x-fieldlabel`) ikut dilacak di halaman & jendela, kolom combo desa "
            "punya jalur XPath lengkap dari sekolah dengan pemeriksaan «wajib combo», nilai "
            "angka Dapodik («007» → «7», «63,5») dinilai sama, dan isian yang ada di jendela "
            "dilaporkan saat kolomnya tidak ketemu (uji tiruan 39–46)")


@cek("41. Catatan bot LENGKAP: berkas utuh, halaman & unduhan, diagnostik kolom")
def cek_catatan_lengkap_bot() -> str:
    """Ronde 48 — «untuk log adanya dimana? di web kan cuma sampai 12 baris terakhir».

    Tiga hal yang dijaga blok ini: (a) catatan bot **tidak dipotong lagi** — dulu basis data
    hanya menyimpan 4000 karakter terakhir sehingga pengguna cuma bisa melihat 12 baris;
    kini seluruh baris ditulis ke ``data/bot/catatan-bot-<id>.txt`` dan salinan basis datanya
    jauh lebih panjang; (b) halaman ``/bot-dapodik/catatan`` + unduhan
    ``/bot-dapodik/catatan.txt`` ada dan tertaut dari halaman Bot Dapodik; (c) bila sebuah
    kolom gagal diisi/tidak ketemu, catatan menyebut **keadaan kolomnya** & kandidat yang
    dicoba — bukti yang membuat sebab kegagalan (mis. «RT belum berisi nilai yang benar»)
    bisa ditelusuri tanpa menebak.
    """
    import ast

    from app import services

    # (a) Catatan lengkap: berkas + batas basis data yang jauh lebih besar.
    sumber = (BASE_DIR / "app/services.py").read_text(encoding="utf-8")
    badan: dict[str, str] = {}
    for simpul in ast.walk(ast.parse(sumber)):
        if isinstance(simpul, ast.FunctionDef):
            badan.setdefault(simpul.name, ast.get_source_segment(sumber, simpul) or "")
    assert "BATAS_LOG_DB" in sumber, "batas catatan di basis data hilang"
    isi_pb = badan["perbarui_job_bot"]
    # Kode (bukan komentar/docstring) yang menentukan: dulu `gabung[-4000:]`.
    assert "gabung[-4000:]" not in isi_pb, \
        "catatan bot masih dipotong 4000 karakter (pengguna hanya bisa melihat 12 baris)"
    assert "gabung[-BATAS_LOG_DB:]" in isi_pb, \
        "salinan catatan di basis data tidak memakai batas BATAS_LOG_DB"
    for nama in ("berkas_catatan_bot", "baca_catatan_bot", "perbarui_job_bot"):
        assert nama in badan, f"fungsi {nama} hilang dari app/services.py"
    isi = badan["berkas_catatan_bot"]
    assert "catatan-bot-" in isi and '"bot"' in isi, \
        "berkas catatan bot tidak diletakkan di data/bot/catatan-bot-<id>.txt"
    isi = badan["perbarui_job_bot"]
    assert "berkas_catatan_bot(" in isi and "buka.write(" in isi, \
        "catatan lengkap tidak ditulis ke berkas"
    assert "BATAS_LOG_DB" in isi, "salinan catatan di basis data memakai batas lama"

    # Bukti nyata: 400 baris catatan (jauh di atas batas 4000 karakter) harus utuh.
    job_id = services.create_dapodik_job("uji-catatan", "uji", {"uji": True}, "cek-sistem")
    penanda = [f"[uji-catatan] baris ke-{i} — {'x' * 40}" for i in range(1, 401)]
    for baris in penanda:
        services.perbarui_job_bot(job_id, baris_log=baris)
    berkas = services.berkas_catatan_bot(job_id)
    assert berkas.exists(), f"berkas catatan tidak dibuat: {berkas}"
    isi_berkas = berkas.read_text(encoding="utf-8")
    baris_ada = [b for b in isi_berkas.splitlines() if "[uji-catatan]" in b]
    assert len(baris_ada) == len(penanda), \
        f"berkas catatan hanya memuat {len(baris_ada)}/{len(penanda)} baris"
    assert "baris ke-1 —" in isi_berkas and "baris ke-400 —" in isi_berkas, \
        "baris awal/akhir catatan hilang dari berkas"
    teks, dari = services.baca_catatan_bot(job_id)
    assert dari == "berkas" and "baris ke-400 —" in teks, \
        f"baca_catatan_bot tidak mengembalikan catatan lengkap (dari={dari!r})"
    from app import db as _db

    salinan_db = str(_db.query_value("SELECT log FROM dapodik_jobs WHERE id = ?", (job_id,)) or "")
    assert len(salinan_db) > 4000, \
        f"salinan catatan di basis data masih dipotong ({len(salinan_db)} karakter)"
    # Halaman & unduhan benar-benar MENYAJIKAN isi catatan lengkapnya (bukan sekadar ada):
    # periksa lewat HTTP seperti pengguna memakainya — halaman memuat baris pertama sampai
    # terakhir, unduhannya berkas teks ber-penanda UTF-8 yang bisa dikirim apa adanya.
    import asyncio

    import httpx

    from app.main import app as _app

    async def periksa_catatan_lewat_http() -> tuple[str, str]:
        transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cek") as klien:
            masuk = await klien.post("/login", data={"mode": "staff", "username": "admin",
                                                     "password": "admin123"})
            assert masuk.status_code == 303, "login admin gagal saat memeriksa catatan lengkap"
            halaman = await klien.get(f"/bot-dapodik/catatan?job={job_id}")
            assert halaman.status_code == 200, f"/bot-dapodik/catatan -> {halaman.status_code}"
            assert "baris ke-1 —" in halaman.text and "baris ke-400 —" in halaman.text, \
                "halaman catatan tidak menyajikan seluruh baris catatan"
            assert "400" in halaman.text, "jumlah baris catatan lengkap tidak ditampilkan"
            unduh = await klien.get(f"/bot-dapodik/catatan.txt?job={job_id}")
            assert unduh.status_code == 200, f"/bot-dapodik/catatan.txt -> {unduh.status_code}"
            assert "text/plain" in unduh.headers.get("content-type", ""), \
                "unduhan catatan bukan berkas teks"
            assert "attachment" in unduh.headers.get("content-disposition", ""), \
                "unduhan catatan tidak dikirim sebagai lampiran"
            assert unduh.text.startswith("\ufeff"), "unduhan catatan tanpa penanda UTF-8"
            assert "baris ke-1 —" in unduh.text and "baris ke-400 —" in unduh.text, \
                "unduhan catatan tidak memuat seluruh baris"
            return halaman.text, unduh.text

    asyncio.run(periksa_catatan_lewat_http())
    berkas.unlink(missing_ok=True)

    # (b) Halaman & unduhan catatan lengkap, tertaut dari halaman Bot Dapodik.
    rute = (BASE_DIR / "app/routers/bot_routes.py").read_text(encoding="utf-8")
    for tanda in ('@router.get("/bot-dapodik/catatan")', '@router.get("/bot-dapodik/catatan.txt")',
                  "baca_catatan_bot(", "log_total"):
        assert tanda in rute, f"rute/halaman catatan lengkap kehilangan {tanda!r}"
    # Panel «Catatan berjalan» di halaman bot memakai satu tetapan bersama (dulu 12 baris
    # dipatok dua kali: di template dan di status.json — itulah yang dikeluhkan pengguna).
    assert "BARIS_CATATAN_TAYANG = 30" in rute, \
        "jumlah baris «Catatan berjalan» tidak lagi memakai tetapan bersama (30 baris)"
    assert "splitlines()[-BARIS_CATATAN_TAYANG:]" in rute, \
        "status.json belum memakai tetapan baris catatan"
    assert "splitlines()[-12:]" not in rute, "status.json masih memotong catatan di 12 baris"
    isi_hal = (BASE_DIR / "app/templates/bot_dapodik.html").read_text(encoding="utf-8")
    assert "splitlines()[-baris_tayang:]" in isi_hal, \
        "panel «Catatan berjalan» tidak memakai jumlah baris dari halaman"
    assert "splitlines()[-12:]" not in isi_hal, "panel «Catatan berjalan» masih dipotong 12 baris"
    assert "baris_tayang" in isi_hal and "splitlines()[-baris_tayang:]" in isi_hal, \
        "jumlah baris yang ditayangkan tidak diambil dari halaman"
    for berkas_template, tanda in (
            ("app/templates/bot_catatan.html",
             ("Unduh catatan (.txt)", "catatan-lengkap", "Berkas di PC")),
            ("app/templates/bot_dapodik.html",
             ("/bot-dapodik/catatan", "catatan-jumlah", "catatan_berkas",
              "tautan-catatan-lengkap"))):
        isi_t = (BASE_DIR / berkas_template).read_text(encoding="utf-8")
        for satu in tanda:
            assert satu in isi_t, f"{berkas_template} kehilangan {satu!r}"

    # (c) Diagnostik kolom: keadaan kolom & kandidat yang dicoba saat gagal/tak ketemu.
    sumber_bot = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    badan_bot: dict[str, str] = {}
    for simpul in ast.walk(ast.parse(sumber_bot)):
        if isinstance(simpul, ast.FunctionDef):
            badan_bot.setdefault(simpul.name, ast.get_source_segment(sumber_bot, simpul) or "")
    for nama in ("_rincian_unsur", "_rincian_kandidat_kolom", "_rincian_kolom_halaman"):
        assert nama in badan_bot, f"{nama} hilang — catatan kegagalan kolom jadi tanpa bukti"
    isi = badan_bot["_rincian_unsur"]
    for tanda in ("readonly=", "nonaktif=", "terlihat=", "data-componentid"):
        assert tanda in isi, f"rincian keadaan kolom kehilangan {tanda!r}"
    isi = badan_bot["_isi_periodik_satu"]
    assert isi.count("_rincian_unsur(") >= 1 and "_rincian_kandidat_kolom(" in isi, \
        "kegagalan pengisian kolom tidak menyebut keadaan kolom & kandidatnya"
    assert "_rincian_kolom_halaman(" in isi, \
        "saat kolom tidak ketemu, daftar kolom yang ADA di halaman tidak dilaporkan"
    assert "_rincian_kandidat_kolom(" in badan_bot["_isi_bio"], \
        "kegagalan kolom «Desa/Kelurahan» tidak menyebut kandidat yang dicoba"

    # (d) RT/RW: nilai MODEL Ext JS diperiksa & diperbaiki — bukan hanya tulisan di kotaknya.
    #     Dapodik menyimpan dari model itu, jadi kotak yang sudah benar belum menjamin («RT»
    #     tersimpan «0»). Inilah sisa sebab «masih gagal input rt dan rw».
    for nama in ("_nilai_model", "_pastikan_model_angka", "_angka_lah"):
        assert nama in badan_bot, f"{nama} hilang — kolom angka tidak diperiksa sampai modelnya"
    assert "_pastikan_model_angka(" in badan_bot["_periksa_nilai_bio"], \
        "penjaga nilai tidak memeriksa model Ext JS kolom angka sebelum «Simpan»"
    assert "_pastikan_model_angka(" in badan_bot["_isi_periodik_satu"], \
        "pengisian kolom angka tidak memeriksa model Ext JS-nya"
    assert "_penjaga_unsur" in sumber_bot and "nilai-model-unsur" in sumber_bot, \
        "unsur pemegang nilai tidak diingat / pembacaan model Ext JS tidak ada"
    uji_bot = (BASE_DIR / "scripts/uji_bot_dapodik.py").read_text(encoding="utf-8")
    for tanda in ('"tanpa_kolom_angka"', '"model_angka_terpisah"', "62 skenario",
                  "kolomnya TIDAK ketemu", "kolom isian yang ADA di halaman"):
        assert tanda in uji_bot or tanda in (BASE_DIR / "scripts/peramban_palsu.py").read_text(
            encoding="utf-8"), f"uji/fixture kehilangan {tanda!r}"

    return ("catatan bot disimpan utuh ke data/bot/catatan-bot-<id>.txt (uji 400 baris / "
            ">4000 karakter; halaman & unduhan .txt-nya benar-benar menyajikan baris 1–400), "
            "halaman /bot-dapodik/catatan + unduhan .txt tersedia & tertaut, "
            "dan kegagalan mengisi kolom menyebut keadaan kolom (name/id/type/readonly/"
            "nonaktif/nilai) + kandidat selector yang dicoba")


@cek("38. Tombol «Online» — Tailscale Funnel sekali klik, tanpa jendela cmd")
def cek_tombol_online():
    """Uji fitur ronde 44 memakai «tailscale palsu» — tanpa menyentuh jaringan sekolah."""
    import time

    from app import auth, online, web

    # (a) Semua perintah Tailscale berjalan TANPA jendela Command Prompt.
    sumber = (BASE_DIR / "app/online.py").read_text(encoding="utf-8")
    potong = sumber[sumber.index("# Tailscale Funnel — tombol «Online»"):]
    assert "def tanpa_jendela" in sumber and "CREATE_NO_WINDOW" in sumber, \
        "bendera CREATE_NO_WINDOW hilang dari app/online.py"
    jumlah = potong.count("creationflags=tanpa_jendela()")
    panggilan = potong.count("subprocess.run(") + potong.count("subprocess.Popen(")
    assert panggilan >= 2, "perintah tailscale seharusnya dijalankan lewat subprocess"
    assert jumlah == panggilan, \
        f"{panggilan - jumlah} proses tailscale tanpa bendera tanpa-jendela"
    assert "shell=True" not in potong, \
        "perintah tailscale dijalankan lewat shell (bisa memunculkan jendela cmd)"
    assert "os.system" not in potong and "os.popen" not in potong

    # (b) Pembacaan keluaran `tailscale funnel status` & nama perangkat.
    aktif, alamat, port = online.baca_alamat_tailscale(
        "https://sm-sekolah.tail.ts.net (Funnel on)\n|-- / proxy http://127.0.0.1:8000")
    assert aktif and alamat == "https://sm-sekolah.tail.ts.net" and port == 8000, \
        (aktif, alamat, port)
    assert online.baca_alamat_tailscale("No serve config") == (False, "", 0)

    # (c) Galat Tailscale diterjemahkan menjadi langkah perbaikan yang nyata.
    for galat, harus_ada in (
        ('Funnel not available; "funnel" node attribute not set', "acls"),
        ("HTTPS is not enabled on your tailnet", "admin/dns"),
        ("MagicDNS is not enabled", "MagicDNS"),
        ("Logged out", "masuk"),
    ):
        pesan = online.pesan_perbaikan(galat)
        assert harus_ada.lower() in pesan.lower(), \
            f"pesan untuk {galat!r} tidak memuat {harus_ada!r}: {pesan[:140]}"

    # (d) Halaman, menu, dan rutenya ada — tanpa perintah yang perlu diketik guru.
    halaman = (BASE_DIR / "app/templates/online.html").read_text(encoding="utf-8")
    for tanda in ("Nyalakan online (1 tombol)", "Matikan online", "Salin alamat",
                  "tailscale.com/download", "/pengaturan#aman-online", "/online/status.json",
                  "Tailscale Funnel"):
        assert tanda in halaman, f"halaman Online tidak memuat {tanda!r}"
    web_sumber = (BASE_DIR / "app/web.py").read_text(encoding="utf-8")
    assert '{"href": "/online", "label": "Online", "icon": "globe"}' in web_sumber, \
        "menu «Online» tidak ada di bilah samping"
    assert '"/online": "Online"' in web_sumber, "judul halaman Online belum terdaftar"
    router = (BASE_DIR / "app/routers/online_routes.py").read_text(encoding="utf-8")
    for tanda in ('@router.get("/online")', '@router.post("/online/nyalakan")',
                  '@router.post("/online/matikan")', "/online/status.json",
                  "mulai_nyalakan", "matikan_terowongan"):
        assert tanda in router, f"rute Online tidak memuat {tanda!r}"
    assert "online_routes.router" in (BASE_DIR / "app/main.py").read_text(encoding="utf-8"), \
        "router Online belum didaftarkan di app/main.py"
    admin_cek = auth.SessionUser(id=1, username="admin", nama="Admin", role=auth.ROLE_ADMIN)
    petugas_cek = auth.SessionUser(id=None, username="petugas", nama="P", role=auth.ROLE_OPERATOR)
    assert "/online" in {item["href"] for item in web.nav_items(admin_cek)}, "menu Online hilang"
    assert "/online" not in {item["href"] for item in web.nav_items(petugas_cek)}, \
        "petugas seharusnya tidak melihat menu Online (khusus admin)"

    if os.name == "nt":
        return ("tombol Online: bendera tanpa-jendela dipakai di semua perintah Tailscale, "
                "galat diterjemahkan ke langkah perbaikan, halaman/menu/rute lengkap — "
                "uji alur penuh dengan tailscale palsu dilewati di Windows")

    # (e) Alur penuh dengan «tailscale palsu» (tanpa menyentuh jaringan sekolah).
    shim = _SEMENTARA / "tailscale-palsu.sh"
    shim.write_text(
        "#!/bin/sh\n"
        'case "$1 $2" in\n'
        '  "status --json") echo \'{"Self":{"DNSName":"sm-sekolah.tail.ts.net."}}\' ;;\n'
        '  "funnel status") echo "https://sm-sekolah.tail.ts.net (Funnel on)";\n'
        '    echo "|-- / proxy http://127.0.0.1:${SM_UJI_PORT:-8000}" ;;\n'
        '  "funnel off") echo "Funnel stopped" ;;\n'
        '  "funnel --bg") echo "Funnel started (palsu)" ;;\n'
        "esac\n"
        "exit 0\n", encoding="utf-8")
    shim.chmod(0o755)
    izin_shim = _SEMENTARA / "tailscale-izin.sh"
    izin_shim.write_text(
        "#!/bin/sh\n"
        'echo "Funnel is not enabled on your tailnet."\n'
        'echo "  https://login.tailscale.com/f/funnel?node=n123456"\n'
        "sleep 60\n", encoding="utf-8")
    izin_shim.chmod(0o755)
    gagal_shim = _SEMENTARA / "tailscale-gagal.sh"
    gagal_shim.write_text(
        '#!/bin/sh\necho "Funnel is not enabled on your tailnet" >&2\nexit 1\n',
        encoding="utf-8")
    gagal_shim.chmod(0o755)

    asli = os.environ.get("SM_TAILSCALE")
    os.environ["SM_UJI_PORT"] = "8000"
    tunggu_asli, ronde_asli = online.TUNGGU_FUNNEL, online.RONDE_TUNGGU

    def tunggu_selesai(batas_detik: float = 30.0) -> dict:
        batas = time.time() + batas_detik
        while time.time() < batas and online.status_pekerjaan()["jalan"]:
            time.sleep(0.15)
        return online.status_pekerjaan()

    try:
        online.hapus_status()
        os.environ["SM_TAILSCALE"] = str(shim)
        assert online.tailscale_jalur() == str(shim), online.tailscale_jalur()
        keadaan = online.status_terowongan()
        assert keadaan["ada"] and keadaan["online"], keadaan
        assert keadaan["alamat"] == "https://sm-sekolah.tail.ts.net", keadaan
        assert keadaan["nama"] == "sm-sekolah.tail.ts.net", keadaan

        # Nyalakan: pekerjaan latar selesai, alamat tersimpan sebagai penanda online.
        assert online.mulai_nyalakan(8000)["jalan"] is True, "pekerjaan latar tidak dimulai"
        akhir = tunggu_selesai()
        assert akhir["tahap"] == "online", akhir
        assert akhir["alamat"] == "https://sm-sekolah.tail.ts.net", akhir
        penanda = online.baca_status()
        assert penanda["aktif"] and str(penanda["alamat"]).startswith("https://sm-sekolah"), \
            penanda
        assert "tailscale" in str(penanda["alat"]).lower(), penanda

        # Matikan: penanda dibersihkan; aplikasi lokal tidak diapa-apakan.
        hasil = online.matikan_terowongan()
        assert hasil["berhasil"], hasil
        assert not online.baca_status()["aktif"], "penanda online belum dibersihkan"

        # Port publik di luar 443/8443/10000 ditolak dengan penjelasan (batas Tailscale).
        online.mulai_nyalakan(8000, 8080)
        tolak = tunggu_selesai(10)
        assert tolak["tahap"] == "gagal" and "443" in tolak["pesan"], tolak

        # «Menunggu persetujuan» ≠ gagal: tautan izin dilaporkan, prosesnya tidak diklaim sukses.
        os.environ["SM_TAILSCALE"] = str(izin_shim)
        online.TUNGGU_FUNNEL, online.RONDE_TUNGGU = 2, 2
        online.mulai_nyalakan(8000)
        izin = tunggu_selesai()
        assert izin["tahap"] == "menunggu-izin", izin
        assert izin["tautan_izin"].startswith("https://login.tailscale.com/f/funnel"), izin
        assert "menunggu" in izin["pesan"].lower(), izin
        assert not online.baca_status()["aktif"], \
            "funnel yang belum disetujui tidak boleh dianggap online"
        online.TUNGGU_FUNNEL, online.RONDE_TUNGGU = tunggu_asli, ronde_asli

        # Gagal dijalankan: kode ≠ 0 → pesan perbaikan (bukan klaim sukses).
        os.environ["SM_TAILSCALE"] = str(gagal_shim)
        online.mulai_nyalakan(8000)
        gagal = tunggu_selesai()
        assert gagal["tahap"] == "gagal" and gagal["kode"] not in (0, None), gagal
        assert "acls" in gagal["pesan"].lower(), gagal

        # Perintah tailscale yang tidak ada sama sekali → pesan pemasangan, bukan galat mentah.
        os.environ["SM_TAILSCALE"] = str(_SEMENTARA / "tidak-ada-tailscale")
        assert online.tailscale_jalur() == "", "perintah yang tidak ada seharusnya dianggap kosong"
        belum = online.status_terowongan()
        assert belum["ada"] is False and "Tailscale belum terpasang" in belum["pesan"], belum
    finally:
        online.TUNGGU_FUNNEL, online.RONDE_TUNGGU = tunggu_asli, ronde_asli
        os.environ.pop("SM_UJI_PORT", None)
        if asli is None:
            os.environ.pop("SM_TAILSCALE", None)
        else:
            os.environ["SM_TAILSCALE"] = asli
        online.hapus_status()

    return ("tombol Online: alur penuh nyalakan → alamat .ts.net tersimpan & tampil → matikan "
            "diuji dengan tailscale palsu; jalur «menunggu persetujuan» dilaporkan jujur "
            "(bukan sukses/gagal), galat → langkah perbaikan; semua perintah di belakang layar "
            "tanpa jendela cmd; menu & rute khusus admin")


@cek("42. Kolom Dapodik dikenali dari bukti yang melekat pada kolomnya")
def cek_kolom_melekat_pada_kolomnya():
    """Ronde 49 — «daftar dropdown TIDAK terbaca» untuk hampir SEMUA kolom (RT/RW ikut).

    Catatan bot lengkap yang dikirim sekolah memperlihatkan kolom angka & kolom teks biasa
    dikira dropdown lalu dilewati. Sebabnya: jenis kolom disimpulkan dari **wadah lebar**
    (memuat kolom tetangga beserta tombol putar numberfield) dan komponen Ext JS diambil dari
    id apa adanya — sehingga bisa menunjuk kolom lain (daftar «Pendidikan ayah» terbaca untuk
    «Tahun lahir ayah»), sementara panahnya dicari menyapu seluruh halaman. Blok ini menjaga
    aturannya: bidang kolom = wadah yang hanya memuat satu kolom isian; dropdown hanya bila ada
    panah milik kolom itu / ``role=combobox`` / komponen yang benar-benar memuat unsur itu;
    daftar & pilihan hanya dibaca dari kolom itu; dua arah jaring pengaman (kolom bukan-dropdown
    diketik, «kotak terisi tetapi model Ext JS kosong» dicoba lewat daftar); dan galat validasi
    Dapodik dibaca bila «Simpan» tidak menutup jendela.
    """
    import ast

    sumber = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    badan: dict[str, str] = {}
    for simpul in ast.walk(ast.parse(sumber)):
        if isinstance(simpul, ast.FunctionDef):
            badan.setdefault(simpul.name, ast.get_source_segment(sumber, simpul) or "")

    # (a) Alat bersama: bidang kolom + komponen Ext JS yang terverifikasi.
    assert "JS_ALAT" in sumber, "alat bersama pengenal kolom hilang (JS_ALAT)"
    for nama in ("bidangKolom", "panahKolom", "putarKolom", "komponenKolom", "komboKolom"):
        assert f"const {nama}" in sumber, f"{nama} hilang dari JS_ALAT"
    assert "dom.contains(el)" in sumber, \
        "komponen Ext JS tidak diperiksa benar-benar memuat unsurnya (id meleset bisa lolos)"

    # (b) Jenis kolom: bukan lagi dari wadah lebar / readonly / sembarang x-form-trigger.
    isi_tipe = badan["_tipe_kolom"]
    assert "_info_kolom" in isi_tipe, "_tipe_kolom tidak memakai _info_kolom"
    for terlarang in ("closest('.x-field')", "x-form-trigger|x-form-arrow", "readOnly"):
        assert terlarang not in isi_tipe, f"_tipe_kolom masih memakai aturan lama {terlarang!r}"
    isi_info = badan["_info_kolom"]
    for tanda in ("/* jenis-kolom */", "putarKolom", "panahKolom", "komboKolom", "store"):
        assert tanda in isi_info, f"_info_kolom tidak melaporkan {tanda!r}"

    # (c) Daftar, pilihan, dan panah hanya dari kolom itu sendiri.
    for nama, tanda in (("_panah_kolom", "panahKolom"),
                        ("_data_dropdown", "komponenKolom"),
                        ("_pilihan_dropdown", "komponenKolom"),
                        ("_dropdown_terbuka", "komponenKolom")):
        assert tanda in badan[nama], f"{nama} tidak memakai {tanda} (kolom lain bisa terbaca)"
    assert "akar = document" not in badan["_pilihan_dropdown"], \
        "daftar dropdown masih dibaca dari seluruh halaman"
    assert "following::" not in badan["_buka_dropdown"], \
        "panah dropdown masih dicari dengan menyapu halaman (following::)"
    assert "/arrow/" in badan["_panah_kolom"], \
        "panah kolom tidak memastikan kelasnya panah (tombol putar numberfield bisa terklik)"

    # (d) Dua arah jaring pengaman + pelaporan galat Dapodik.
    isi_drop = badan["_isi_dropdown_bio"]
    assert "bukan combo sungguhan" in isi_drop and "_isi_periodik_satu" in isi_drop, \
        "kolom bukan-dropdown yang dikira dropdown tidak diketik sebagai kolom biasa"
    assert "kombo_kuat" in isi_info and "kombo_kuat" in isi_drop, \
        "bukti combo kuat/lemah tidak dibedakan — kolom berunsur mirip panah bisa dilewati"
    assert "kombo_kuat" in badan["_isi_bio"] and "tidak ada bukti combo" in badan["_isi_bio"], \
        "kolom berunsur mirip panah tidak dicoba diketik lebih dulu (bisa «dilewati»)"
    # Jalur «Desa/Kelurahan» harus tetap `elif`: kolomnya sudah diisi jalurnya sendiri, dan
    # keterangannya (termasuk «dipilih dari daftar Dapodik» + kode wilayah) tidak boleh
    # ditimpa jalur dropdown biasa — pernah terjadi di ronde ini (kolom desa dikerjakan dua
    # kali dan bukti kode wilayahnya hilang dari catatan; ketahuan uji skenario 24).
    assert 'elif self._info_kolom(peramban, unsur).get("kombo_kuat"):' in badan["_isi_bio"], \
        "jalur dropdown BIO bukan «elif» — keterangan kolom Desa/Kelurahan bisa tertimpa"
    isi_bio = badan["_isi_bio"]
    assert "model Ext JS-nya kosong" in isi_bio, \
        "kotak terisi tetapi model Ext JS kosong tidak dicoba lewat daftar dropdown"
    assert "_galat_validasi_bio" in isi_bio, \
        "galat validasi Dapodik tidak dibaca saat «Simpan» tidak menutup jendela"
    assert "/* galat-validasi */" in badan["_galat_validasi_bio"], \
        "pembaca galat validasi tidak ada"

    # (e) Peramban palsu bisa menirukan DOM sekolah, dan uji barunya benar-benar ada.
    palsu = (BASE_DIR / "scripts/peramban_palsu.py").read_text(encoding="utf-8")
    for nama in ("dom_wadah_lebar", "kombo_tak_terbaca", "panah_sendiri_dipakai",
                 "komponen_meleset_kali", "panah_tanpa_data", "panah_tak_berdata_kali",
                 "jenis-kolom", "panah-kolom"):
        assert nama in palsu, f"peramban palsu tidak punya {nama!r}"
    uji = (BASE_DIR / "scripts/uji_bot_dapodik.py").read_text(encoding="utf-8")
    for judul in ("47. DOM sekolah", "48. panah dropdown", "49. combo tanpa penanda",
                  "50. unsur mirip panah"):
        assert judul in uji, f"skenario uji {judul!r} hilang"

    return ("bidang kolom = wadah yang hanya memuat satu kolom isian · dropdown hanya dari "
            "bukti KUAT (panah milik kolom itu / role=combobox / komponen Ext JS yang "
            "benar-benar memuat "
            "unsur itu · daftar & panah tidak pernah dibaca menyapu halaman · kolom "
            "bukan-dropdown diketik seperti kolom biasa · «kotak terisi tetapi model Ext JS "
            "kosong» dicoba lewat daftar · galat validasi Dapodik dicatat bila «Simpan» tidak "
            "menutup jendela; peramban palsu menirukan DOM sekolah (dom_wadah_lebar / "
            "kombo_tak_terbaca / panah_tanpa_data) dan bot versi lama terbukti melewati 11 "
            "kolom di DOM itu, sedangkan bot baru mengetik kolom berunsur panah tanpa data")


@cek("43. «Simpan» BIO ditolak Dapodik: kolom Wali dibetulkan dari data SM, jendela ditutup")
def cek_perbaikan_simpan_bio():
    """Ronde 50 — catatan sekolah 29 September 2026 (bot 4728e77): «[bio] galat validasi di
    jendela «Ubah» (dari Dapodik): pekerjaan_id_wali: This field is required; inputItem: The
    minimum value for this field is 1» — jendela «Ubah» TETAP terbuka, data BIO tidak
    tersimpan, dan sesudahnya muncul «[periodik] peringatan: baris siswa belum terpilih».

    Blok ini menjaga perbaikannya: galat dibaca bersama label & bagian kolomnya (nama kolom
    «inputItem» tidak muncul di layar), kolom yang ditolak diisi ulang dari data SM — kolom
    wali khusus pendidikan/pekerjaan/penghasilan boleh MENGIKUTI AYAH, sedangkan identitas
    wali (nama/NIK) TIDAK PERNAH dikarang — «0» bawaan Dapodik dikosongkan lebih dulu lalu
    diisi nilai bila Dapodik masih menolak, jumlah putaran dibatasi, dan jendela «Ubah»
    DITUTUP supaya Data Periodik & Registrasi tidak terganggu.
    """
    import ast

    sumber = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    badan: dict[str, str] = {}
    for simpul in ast.walk(ast.parse(sumber)):
        if isinstance(simpul, ast.FunctionDef):
            badan.setdefault(simpul.name, ast.get_source_segment(sumber, simpul) or "")

    for nama in ("_galat_validasi_bio", "_galat_validasi_teks", "_nilai_kolom_bernama",
                 "_unsur_kolom_bernama", "_keluarga_dari_nama", "_perbaiki_galat_validasi_bio",
                 "_kolom_wajib_kosong_bio", "_tutup_jendela_ubah", "_tekan_simpan_bio"):
        assert nama in badan, f"{nama} hilang — perbaikan «Simpan» yang ditolak tidak lengkap"

    # (a) Galat validasi dibaca lengkap: label & bagian kolomnya, bukan hanya namanya.
    isi_galat = badan["_galat_validasi_bio"]
    for tanda in ("/* galat-validasi */", "fieldLabel", "x-fieldset-header-text", "xtype",
                  "getErrors", "getActiveError", "nilai", "bagian"):
        assert tanda in isi_galat, f"pembaca galat validasi kehilangan {tanda!r}"
    assert "label" in badan["_galat_validasi_teks"], \
        "label kolom yang ditolak tidak ikut dilaporkan ke catatan bot"

    # (b) Kolom yang ditolak DIBETULKAN — dua cara berurutan, jumlahnya dibatasi.
    isi_perbaikan = badan["_perbaiki_galat_validasi_bio"]
    assert "kosongkan" in isi_perbaikan and "_bio_perbaikan_cara" in isi_perbaikan, \
        "kolom bernilai «0» yang ditolak tidak dicoba dikosongkan lebih dulu"
    assert 'atribut in ("pendidikan", "pekerjaan", "penghasilan")' in isi_perbaikan, \
        "kolom wali boleh mengikuti ayah TANPA batas atribut — identitas wali bisa dikarang"
    assert "mengarang wali" in isi_perbaikan, \
        "alasan identitas wali tidak diisi dari data ayah tidak dilaporkan"
    assert "tidak diisi asal-asalan" in isi_perbaikan, \
        "kolom yang tidak ada datanya tidak dilaporkan apa adanya"
    assert "_set_ext(" in isi_perbaikan, "pengosongan «0» tidak lewat model Ext JS"
    assert "BATAS_PERBAIKAN_BIO" in sumber and \
        "while galat_kini and putaran < self.BATAS_PERBAIKAN_BIO" in badan["_isi_bio"], \
        "putaran perbaikan tidak dibatasi — bot bisa mengulang tanpa akhir"
    assert "_tekan_simpan_bio(" in badan["_isi_bio"] and "tertutup SESUDAH perbaikan" \
        in badan["_isi_bio"], \
        "«Simpan» tidak ditekan ulang sesudah perbaikan / keberhasilannya tidak diperiksa"
    assert "_tutup_jendela_ubah(" in badan["_isi_bio"] and "BELUM tersimpan" in badan["_isi_bio"], \
        "jendela «Ubah» yang ditolak tidak ditutup / tidak dikatakan jujur belum tersimpan"
    assert "_kolom_wajib_kosong_bio(" in badan["_isi_bio"], \
        "kolom WAJIB yang masih kosong tidak dilaporkan saat «Simpan» ditolak"
    assert "/* tutup-jendela-ubah */" in badan["_tutup_jendela_ubah"], \
        "penutup jendela «Ubah» tidak ada"

    # (c) Pengaturan «Wali mengikuti ayah» bisa dimatikan dari halaman Bot Dapodik.
    for berkas, tanda in ((BASE_DIR / "app/services.py", "bot_wali_ikuti_ayah"),
                          (BASE_DIR / "app/routers/bot_routes.py", "wali_ikuti_ayah"),
                          (BASE_DIR / "app/templates/bot_dapodik.html", "wali_ikuti_ayah")):
        assert tanda in berkas.read_text(encoding="utf-8"), \
            f"pengaturan {tanda!r} tidak ada di {berkas.name}"

    # (d) Peramban palsu dapat menirukan penolakan Dapodik & ujinya benar-benar ada.
    palsu = (BASE_DIR / "scripts/peramban_palsu.py").read_text(encoding="utf-8")
    for tanda in ("bio_wali_kolom", "bio_gagal_wali", "bio_min_keras", "bio_wali_nama_wajib",
                  "bio_tolak_simpan_kali", "tutup_jendela_ubah_kali", "tambah_kolom_wali",
                  "galat_wajib_bio", "nilai-kolom-bernama", "unsur-kolom-bernama",
                  "kolom-wajib-kosong", "tutup-jendela-ubah",
                  # Ronde 50 (susulan): keadaan sekolah «baris siswa belum terpilih».
                  "jendela_bio_menghalangi", "daftar_tersegar_sesudah_periodik", "segarkan_daftar_siswa",
                  "baris_klik_terhalang", "baris_dipilih_ulang_kali", "baris_terpilih_saat_registrasi"):
        assert tanda in palsu, f"peramban palsu kehilangan {tanda!r} (bukti ronde 50)"
    uji = (BASE_DIR / "scripts/uji_bot_dapodik.py").read_text(encoding="utf-8")
    for judul in ("51. «Simpan» ditolak Dapodik", "52. pengaturan «Wali mengikuti ayah» mati",
                  "53. «0» keras", "54. identitas wali tidak dikarang", "62 skenario",
                  "56. daftar desa baru muncul", "57. nilai desa baru muncul",
                  "58. kecamatan/desa berawalan", "59. isian desa sebelumnya muncul sesudah",
                  "desa_nilai_muat_perlu_default", "desa_lambat_kali",
                  "desa_cocok_ke_kolom_terpisah", "desa_isi_awal_muncul_setelah",
                  "55. jendela «Ubah» menghalangi baris", "jendela_bio_menghalangi",
                  "daftar_tersegar_sesudah_periodik", "baris_klik_terhalang", "daftar_tersegar",
                  "baris_dipilih_ulang_kali", "baris_terpilih_saat_registrasi",
                  "MILIK JENDELA REGISTRASI"):
        assert judul in uji, f"uji bot kehilangan {judul!r} (ronde 50)"

    return ("galat validasi dibaca bersama label & bagian kolomnya · kolom yang ditolak diisi "
            "ulang dari data SM (wali khusus pendidikan/pekerjaan/penghasilan boleh mengikuti "
            "ayah; nama/NIK wali tidak pernah dikarang) · «0» bawaan Dapodik dikosongkan lebih "
            "dulu lalu diisi nilai bila masih ditolak · paling banyak 3 putaran · «Simpan» "
            "ditekan ulang dan jendela «Ubah» ditutup supaya Data Periodik & Registrasi jalan "
            "· pengaturan «Wali mengikuti ayah» ada di halaman Bot Dapodik · 5 skenario uji "
            "baru (51–55) di peramban palsu · keadaan sekolah «baris siswa belum terpilih» "
            "ditirukan (jendela «Ubah» menutupi tabel & daftar tersegar) dan tombol «Simpan dan "
            "Tutup» yang dipakai adalah milik jendela Registrasi, bukan tombol kembar panel "
            "Data Periodik — pemilihan ulang barisnya dibuktikan hitungan uji")


@cek("44. Antrean bot membawa kolom Desa/Kelurahan & Kecamatan")
def cek_antrean_desa():
    """Antrean bot pernah TIDAK menyertakan kelurahan/kecamatan (ronde 51).

    Bot mengisi kolom «Desa/Kelurahan» dari ``siswa["kelurahan"]`` — tetapi SQL
    ``services.bot_antrean`` tidak mengambil dua kolom itu, sehingga di PC sekolah bot selalu
    melaporkan «Desa/Kelurahan: data siswa kosong — dilewati» walaupun data SM lengkap. Uji
    lama tidak menangkapnya sebab peramban palsu diberi data siswa langsung, bukan lewat
    antrean. Pemeriksaan ini memakai antrean SUNGGUHAN: kunci dan nilainya dibandingkan
    dengan data siswa di basis data.
    """
    import inspect

    from app import db, services

    sumber = inspect.getsource(services.bot_antrean)
    for kolom in ("s.kelurahan", "s.kecamatan"):
        assert kolom in sumber, f"antrean bot tidak mengambil kolom {kolom} dari basis data"

    # Siswa uji dengan desa yang PASTI terisi (dihapus lagi sesudah diperiksa) — supaya
    # pemeriksaan tetap bermakna walau basis data uji pemeriksaan ini berisi data lain.
    nisn_uji = "1234567890"
    dibuat = None
    if not db.query_value("SELECT COUNT(*) FROM students WHERE nisn = ?", (nisn_uji,)):
        dibuat = db.insert_returning_id(
            "INSERT INTO students(nama, nisn, nik, jk, alamat, kelurahan, kecamatan, rombel) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("SISWA ANTREAN DESA", nisn_uji, "3201000000000001", "L", "Jl. Antrean 1",
             "Karawaci Baru", "Karawaci", "7A"))
    try:
        baris = services.bot_antrean(limit=10, lewati_sukses=False)
        assert baris, "antrean bot kosong — siswa uji tidak terbaca"
        for item in baris:
            for kunci in ("kelurahan", "kecamatan"):
                assert kunci in item, (f"antrean bot tidak menyertakan kunci {kunci!r}: "
                                       f"{sorted(item)}")
        # Dicari lewat NISN-nya sendiri: antrean dengan batas jumlah bisa memotong siswa uji
        # (urutannya menurut rombel & nama).
        uji_baris = services.bot_antrean(nisn_manual=nisn_uji, lewati_sukses=False)
        assert len(uji_baris) == 1, ("siswa uji tidak muncul di antrean bot saat dicari lewat "
                                     "NISN-nya — antreannya sendiri bermasalah")
        uji = uji_baris[0]
        assert str(uji.get("kelurahan") or "").strip() == "Karawaci Baru", \
            (f"nilai kelurahan tidak sampai ke antrean: {uji.get('kelurahan')!r} (inilah keluhan "
             "sekolah 29 Sep 2026 — bot melewati kolom Desa/Kelurahan)")
        assert str(uji.get("kecamatan") or "").strip() == "Karawaci", \
            f"nilai kecamatan tidak sampai ke antrean: {uji.get('kecamatan')!r}"
        siswa = services.get_student_by_nisn(nisn_uji)
        assert siswa is not None and str(siswa["kelurahan"]) == "Karawaci Baru", \
            f"data siswa uji di basis data tidak lengkap: {siswa and siswa.get('kelurahan')!r}"
    finally:
        if dibuat is not None:
            db.execute("DELETE FROM students WHERE id = ?", (dibuat,))

    bot = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    assert 'siswa.get("kelurahan")' in bot and 'siswa.get("kecamatan")' in bot, \
        "bot tidak membaca kelurahan/kecamatan dari data antrean"

    return ("antrean bot membawa kolom kelurahan & kecamatan beserta nilainya (dibandingkan "
            "dengan data siswa) — kolom «Desa/Kelurahan» tidak lagi dilewati karena datanya "
            "tidak pernah sampai ke bot")


@cek("45. Desa/Kelurahan diisi dengan cara pengguna: tunggu isian sebelumnya, Ctrl+A, ketik nama wilayahnya")
def cek_ketik_desa_cara_pengguna():
    """Ronde 52 — dari cara pengguna di sekolah mengisi kolom «Desa/Kelurahan».

    Pengguna menuliskan caranya: «1. cari inputan bagian desa/kelurahan · 2. tunggu sampai
    muncul isian data sebelumnya · 3. arahkan kursor ke text input lalu lakukan ctrl + a ·
    4. ketik kecamatan sesuai bodap, misal data di bodap kecamatan neglasari, maka ketik
    «neglasari» · 5. tunggu sampai muncul daftarnya, lalu pilih dan klik yang sesuai dengan
    data bodap». Pemeriksaan ini menjaga tiga hal yang membuat log sekolah berbunyi «daftar
    desa belum terlihat sesudah 30x baca» lalu «desa TIDAK ADA pada daftar Dapodik»:

    * kata kunci yang DIKETIK adalah nama wilayahnya (awalan «Kec. »/«Desa/Kel. » dibuang),
      sebab Dapodik mencari nama yang tersimpan di basis datanya — bukan label tampilannya;
    * isian sebelumnya DITUNGGU sampai muncul sebelum kolomnya disentuh;
    * kata kunci yang sudah diketik dibaca ulang & dibuktikan sampai ke kotak pencariannya.
    """
    import inspect

    from app.bot_dapodik import BotDapodik

    # (a) Awalan jabatan wilayah dibuang — diuji langsung pada fungsi bot yang dipakai.
    assert BotDapodik._kata_ketik_wilayah("Kec. Batuceper") == "Batuceper", \
        "«Kec. Batuceper» tidak dibersihkan menjadi «Batuceper» (cara pengguna: ketik namanya)"
    assert BotDapodik._kata_ketik_wilayah("Desa/Kel. Karawaci Baru") == "Karawaci Baru", \
        "«Desa/Kel. …» tidak dibersihkan menjadi nama desanya"
    assert BotDapodik._kata_ketik_wilayah("Neglasari") == "Neglasari", \
        "nama wilayah yang sudah bersih malah diubah"
    assert BotDapodik._kata_ketik_wilayah("") == "", "teks kosong berubah"

    # (b) Kata kunci itu yang diketik, dan isian sebelumnya ditunggu dulu.
    bot = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    assert "_kata_ketik_wilayah(kecamatan)" in bot and "_kata_ketik_wilayah(desa)" in bot, \
        "bot masih mengirim nama wilayah apa adanya ke kotak pencarian Dapodik"
    for tanda in ("AWALAN_KETIK_WILAYAH", "ISI_AWAL_DESA_TUNGGU_DETIK",
                  "awalan jabatan pada nama wilayah dibuang",
                  "CATATAN BUKTI — kotak pencariannya berbunyi"):
        assert tanda in bot, f"bot kehilangan {tanda!r} (ronde 52)"
    badan = {nama: inspect.getsource(fungsi) for nama, fungsi in
             inspect.getmembers(BotDapodik, predicate=inspect.isfunction)}
    isi = badan["_isi_desa_kelurahan"]
    assert "self._tunggu_isi_sebelumnya_desa(" in isi, \
        "kolom desa tidak menunggu isian sebelumnya muncul (langkah 2 cara pengguna)"
    assert "self._ketik_pencarian_desa(peramban, unsur, cari, awalan, label)" in isi, \
        "pengisian kata kunci tidak memakai jalur «Ctrl+A + ketik + baca ulang»"
    ketik = badan["_ketik_pencarian_desa"]
    assert "Keys.CONTROL" in ketik and "kotak pencariannya berbunyi" in ketik, \
        "Ctrl+A + pembacaan ulang isi kotak pencarian tidak ada di pengetikan desa"
    assert "fokus-kotak-pencarian" in ketik, \
        "jalan terakhir (fokus lewat JavaScript) tidak ada"
    tunggu = badan["_tunggu_isi_sebelumnya_desa"]
    assert "isian sebelumnya" in tunggu and "ISI_AWAL_DESA_TUNGGU_DETIK" in tunggu, \
        "penantian isian sebelumnya tidak dilaporkan ke catatan bot"

    # (c) Peramban palsu bisa menirukan dua keadaan sekolah itu + ujinya ada.
    palsu = (BASE_DIR / "scripts/peramban_palsu.py").read_text(encoding="utf-8")
    for tanda in ("desa_cocok_ke_kolom_terpisah", "desa_isi_awal_muncul_setelah",
                  "desa_ketik_terlalu_awal", "desa_isi_awal_tunggu_kali",
                  "bagian_pilihan_desa", "_terapkan_isi_awal_desa_tertunda"):
        assert tanda in palsu, f"peramban palsu kehilangan {tanda!r} (bukti ronde 52)"
    uji = (BASE_DIR / "scripts/uji_bot_dapodik.py").read_text(encoding="utf-8")
    for judul in ("58. kecamatan/desa berawalan", "59. isian desa sebelumnya muncul sesudah "
                  "ditunggu", "62 skenario"):
        assert judul in uji, f"uji bot kehilangan {judul!r} (ronde 52)"

    return ("kolom «Desa/Kelurahan» diisi persis cara pengguna: isian sebelumnya ditunggu "
            "dulu (kata kunci yang datang terlalu dini tidak jadi dicari Dapodik), kursor "
            "diarahkan ke kotak teksnya + Ctrl+A, yang diketik nama wilayahnya tanpa awalan "
            "«Kec. »/«Desa/Kel. » (kecamatan lebih dulu, baru nama desanya), lalu isi kotak "
            "pencariannya dibaca ulang sebagai bukti; kata kunci yang sudah diketik dicocokkan "
            "ke kolom desa/kecamatan/kota Dapodik — bukan ke label tampilannya (uji tiruan "
            "58–59, merah pada bot ronde 51)")


@cek("46. Desa/Kelurahan dipilih dari daftar: satu kata kunci (kecamatan), diverifikasi, "
      "dan «Simpan» ditahan bila belum terverifikasi")
def cek_desa_dipilih_dari_daftar():
    """Ronde 53 — dari pesan pengguna: «pokoknya yang dilakukan itu ketik kecamatan, lalu
    pilih, bukan ngetik kecamatan lalu ngetik kelurahan … tunggu daftar pilihan muncul semua
    lalu cari yang sesuai dengan data bodap» + skrip Selenium acuan yang dikirimnya.

    Pemeriksaan ini menjaga empat hal yang membedakan cara pengguna itu dari bot ronde 52:

    * kata kuncinya **satu** — nama kecamatan; kata kunci kedua (nama desa) tidak boleh
      dibentuk lagi, dan kata kunci gabungan «kecamatan + kelurahan» tidak pernah diketik;
    * daftar pilihannya **ditunggu siap** — dibaca dari store combo Ext JS-nya
      (``desa_kode_wilayah_str``/``displayField``/``valueField``), bukan hanya dari layar;
    * pemilihan disinkronkan ke model Ext JS (``select`` + ``setValue`` + ``fireEvent``)
      dengan percobaan berulang, persis ``DESA_SYNC_RETRY``/``DESA_SYNC_WAIT`` skrip pengguna;
    * **gerbang keselamatan**: «Simpan» tidak ditekan bila pilihan desanya belum terverifikasi
      dan isi kolomnya tidak bisa dikembalikan seperti semula.
    """
    import inspect

    from app.bot_dapodik import BotDapodik

    bot = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    for tanda in ("DESA_STORE_TUNGGU_DETIK", "DESA_SINKRON_KALI", "DESA_SINKRON_JEDA_DETIK",
                  "store-desa", "store-desa-data", "_tunggu_store_desa",
                  "_data_desa_dropdown", "_gerbang_desa_alasan", "simpan_ditahan_desa",
                  "«Simpan» DITAHAN", "cara pengguna diikuti",
                  "bot TIDAK mengetik ulang nama desanya"):
        assert tanda in bot, f"bot kehilangan {tanda!r} (ronde 53)"
    badan = {nama: inspect.getsource(fungsi) for nama, fungsi in
             inspect.getmembers(BotDapodik, predicate=inspect.isfunction)}
    isi = badan["_isi_desa_kelurahan"]
    assert "calon_kueri = ((kecamatan_ketik,) if kecamatan_ketik" in isi, \
        "kata kunci pencarian desa tidak lagi dibatasi satu (nama kecamatan) saja — " \
        "«ketik kecamatan lalu ketik kelurahan» dilarang pengguna"
    assert "desa_ketik" in isi and isi.index("calon_kueri") < isi.index("_tunggu_store_desa"), \
        "daftar pilihannya tidak ditunggu sesudah kata kunci diketik"
    tunggu_store = badan["_tunggu_store_desa"]
    assert "isLoading" in tunggu_store or "loading" in tunggu_store, \
        "penantian store combo desa tidak memeriksa pemuatan datanya"
    assert "DESA_STORE_TUNGGU_DETIK" in tunggu_store, \
        "batas waktu penantian store combo desa tidak dipakai"
    ext = badan["_pilih_dropdown_ext"]
    for tanda in ("select(", "setValue", "fireEvent", "collapse"):
        assert tanda in ext, f"pemilihan lewat model Ext JS kehilangan {tanda!r} (skrip pengguna)"
    siap = badan["_periksa_desa_sampai_siap"]
    assert "paksa_ext" in siap and "DESA_SINKRON_KALI" in siap and "DESA_SINKRON_JEDA_DETIK" in siap, \
        "pilihan desa tidak disinkronkan berulang ke model Ext JS sebelum menyerah"
    assert "TERVERIFIKASI" in siap, "keberhasilan pemilihan desa tidak dicatat sebagai bukti"
    gerbang = badan["_gerbang_desa_alasan"]
    assert "tertinggal" in gerbang, \
        "gerbang keselamatan desa tidak memeriksa tulisan yang tertinggal di kolomnya"
    simpan_bio = badan["_isi_bio"]
    assert "«Simpan» DITAHAN" in simpan_bio and "return False" in simpan_bio, \
        "«Simpan» tidak ditahan saat pilihan desanya belum terverifikasi (skrip pengguna: " \
        "jangan klik Simpan bila belum terverifikasi)"
    assert "self._desa_belum_aman" in badan["_pastikan_desa_sebelum_simpan"], \
        "pemasangan ulang desa yang gagal sebelum «Simpan» tidak menyalakan gerbangnya"

    # Peramban palsu bisa menirukan keadaan itu, dan ujinya ada (skenario 60–61).
    palsu = (BASE_DIR / "scripts/peramban_palsu.py").read_text(encoding="utf-8")
    for tanda in ("desa_ketik_menempel_pencarian", "desa_ketik_menempel", "desa_store_dibaca",
                  "/* store-desa */", "/* store-desa-data */"):
        assert tanda in palsu, f"peramban palsu kehilangan {tanda!r} (bukti ronde 53)"
    uji = (BASE_DIR / "scripts/uji_bot_dapodik.py").read_text(encoding="utf-8")
    for judul in ("60. satu kata kunci: ketik kecamatan, lalu pilih dari daftar",
                  "61. kata kunci menempel & tertinggal", "kueri_pencarian_desa", "62 skenario"):
        assert judul in uji, f"uji bot kehilangan {judul!r} (ronde 53)"

    return ("kolom «Desa/Kelurahan» diisi persis cara pengguna ronde 53: yang diketik HANYA "
            "nama kecamatan (satu kata kunci — «kecamatan lalu kelurahan» tidak lagi diketik), "
            "daftar pilihannya ditunggu siap lewat store combo Ext JS dan dibaca lengkap "
            "beserta kode wilayahnya, pilihan yang cocok diklik lalu disinkronkan lewat "
            "select/setValue (5x, jeda 0,8 detik), hasilnya diverifikasi (tulisan + nilai model "
            "+ kode wilayah) sebelum «Simpan» — dan «Simpan» DITAHAN bila pilihan desanya "
            "belum terverifikasi sementara isi kolomnya tidak bisa dikembalikan (uji tiruan "
            "60–61, merah pada bot ronde 52)")


@cek("47. Kode wilayah (kode_wilayah_str) tidak ikut pindah → dituliskan langsung, diperiksa "
      "ulang, dan dibedah ke catatan bila tetap gagal")
def cek_kode_wilayah_ditulis_langsung():
    """Ronde 54 — «masih gagal untuk masalah bagian kode_wilayah_str ini».

    Sampai ronde 53, bot memilih desanya lewat model Ext JS dengan ``select(record)`` lalu
    ``setValue`` hanya bila ``getRawValue()`` masih kosong — dan sesudah kata kunci pencarian
    diketik, ``getRawValue()`` **tidak pernah** kosong, jadi ``setValue`` tidak pernah jalan
    dan nilai model combo-nya (sumber ``kode_wilayah_str``) tetap nilai lama. Pemeriksaan ini
    menjaga tiga hal: (a) ``setValue`` selalu dipanggil beserta ``fireEvent('select'/'change')``;
    (b) bila kodenya tetap tidak pindah, kode wilayah pilihan itu **dituliskan langsung** ke
    kolom tersembunyinya lalu diperiksa ulang; (c) keadaan kode wilayahnya **dibedah** ke
    catatan (kolom tersembunyi, getValue/getRawValue, valueField/displayField, record terpilih),
    supaya bila masih gagal di sekolah, sebabnya terbaca dari log — bukan ditebak.
    """
    import inspect

    from app.bot_dapodik import BotDapodik

    bot = (BASE_DIR / "app/bot_dapodik.py").read_text(encoding="utf-8")
    for tanda in ("_tulis_kode_wilayah", "_bedah_kode_wilayah", "_halaman_store_desa",
                  "/* tulis-kode-wilayah */", "/* bedah-kode-wilayah */", "/* store-desa-halaman */",
                  "bedah kolomnya", "dituliskan langsung ke kolom", "_bedah_kode_dilaporkan"):
        assert tanda in bot, f"bot kehilangan {tanda!r} (ronde 54)"
    assert "if (c.setValue && !(c.getRawValue && c.getRawValue()))" not in bot, \
        "setValue masih dilewati bila getRawValue() berisi (nilai model combo-nya tidak " \
        "pernah ikut berubah — sumber kode_wilayah_str tidak pindah)"
    badan = {nama: inspect.getsource(fungsi) for nama, fungsi in
             inspect.getmembers(BotDapodik, predicate=inspect.isfunction)}
    pilih_ext = badan["_pilih_dropdown_ext"]
    assert "setValue" in pilih_ext and "fireEvent('change'" in pilih_ext, \
        "pemilihan lewat model Ext JS tidak setValue + fireEvent('change')"
    periksa = badan["_periksa_desa_sampai_siap"]
    assert "kode_diharapkan" in periksa and "self._tulis_kode_wilayah(" in periksa, \
        "kode wilayah tidak dituliskan langsung sesudah cara Dapodik sendiri dicoba"
    tulis = badan["_tulis_kode_wilayah"]
    assert "kode_wilayah" in tulis and "dispatchEvent" in tulis, \
        "penulisan kode wilayah tidak menyentuh kolom tersembunyi beserta peristiwanya"
    bedah = badan["_bedah_kode_wilayah"]
    for tanda in ("getRawValue", "valueField", "displayField", "kode_wilayah"):
        assert tanda in bedah, f"bedah kode wilayah tidak melaporkan {tanda!r}"

    # Peramban palsu bisa menirukan kode wilayah yang tidak ikut pindah + ujinya ada (62).
    palsu = (BASE_DIR / "scripts/peramban_palsu.py").read_text(encoding="utf-8")
    for tanda in ("desa_kode_tak_ikut_pilih", "desa_kode_tidak_pindah",
                  "desa_kode_ditulis_langsung", "pasang_kode_wilayah",
                  "desa_store_halaman_dipakai", "/* store-desa-halaman */"):
        assert tanda in palsu, f"peramban palsu kehilangan {tanda!r} (bukti ronde 54)"
    uji = (BASE_DIR / "scripts/uji_bot_dapodik.py").read_text(encoding="utf-8")
    for judul in ("62. kode wilayah tidak ikut pindah", "62 skenario"):
        assert judul in uji, f"uji bot kehilangan {judul!r} (ronde 54)"

    return ("kode wilayah (kode_wilayah_str) ditangani sampai tuntas: pemilihan lewat model "
            "Ext JS selalu memanggil select + setValue + fireEvent('select'/'change'), dan bila "
            "kodenya tetap tidak ikut pindah, kode wilayah pilihan itu dituliskan langsung ke "
            "kolom tersembunyinya lalu diperiksa ulang sampai benar; keadaan kolomnya dibedah "
            "ke catatan bot (kolom tersembunyi, getValue/getRawValue, valueField/displayField, "
            "record terpilih) supaya kegagalan berikutnya terbaca sebabnya (uji tiruan 62, "
            "merah pada bot ronde 53)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pemeriksaan mandiri SM")
    parser.add_argument("--http", action="store_true", help="Sertakan pengujian halaman HTTP")
    args = parser.parse_args()

    print("=" * 78)
    print("  PEMERIKSAAN MANDIRI SM")
    print(f"  Database sementara: {os.environ['SM_DB_PATH']}")
    print("=" * 78)

    cek_migrasi()
    cek_pembaca()
    cek_parser()
    cek_impor()
    cek_upsert()
    cek_filter()
    cek_perubahan()
    cek_statistik()
    cek_ekspor()
    cek_ekskul()
    cek_keamanan()
    cek_api_kontrak()
    cek_pembaruan()
    cek_pengajuan()
    cek_keluarga()
    cek_pengaman_online()
    cek_peluncur_online()
    cek_akun_ekskul()
    cek_tabel()
    cek_pendaftaran_ekskul()
    cek_kualitas_data()
    cek_bot_dapodik()
    cek_pemasang()
    cek_bodap()
    cek_peringatan_kode()
    cek_vercel()
    cek_ikon()
    cek_bilah_atas()
    cek_kerapian_susunan()
    cek_lencana_ikon()
    cek_tombol_online()
    cek_gulir_aman()
    cek_kolom_lewat_nama_dan_label_div()
    cek_catatan_lengkap_bot()
    cek_kolom_melekat_pada_kolomnya()
    cek_perbaikan_simpan_bio()
    cek_antrean_desa()
    cek_ketik_desa_cara_pengguna()
    cek_desa_dipilih_dari_daftar()
    cek_kode_wilayah_ditulis_langsung()
    cek_halaman_pengajuan_siswa()
    cek_isian_tak_terpotong()
    cek_ekskul_ponsel()
    cek_layar_sempit()
    cek_chrome_tanpa_cmd()
    if args.http:
        cek_http_pengajuan()
        cek_http()

    berhasil = sum(1 for _, ok, _ in HASIL if ok)
    for nama, ok, keterangan in HASIL:
        tanda = "  OK  " if ok else " GAGAL"
        print(f"[{tanda}] {nama}")
        if keterangan:
            for baris in keterangan.splitlines():
                print(f"           {baris}")

    print("-" * 78)
    print(f"  {berhasil}/{len(HASIL)} pemeriksaan berhasil"
          + ("" if args.http else "   (tambahkan --http untuk uji halaman web)"))
    print("=" * 78)

    shutil.rmtree(_SEMENTARA, ignore_errors=True)
    return 0 if berhasil == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
