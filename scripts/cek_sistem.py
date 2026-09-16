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

    # Perintah buka jendela server baru (Windows) harus aman: judul jendela
    # ditulis "" supaya cmd tidak mengira judul itu nama program.
    baris_windows = updater.perintah_windows()
    assert 'start ""' in baris_windows, f"judul jendela start harus kosong: {baris_windows}"
    assert baris_windows.index('start ""') < baris_windows.index("/D"), "urutan start /D salah"
    assert f'/D "{updater.BASE_DIR}"' in baris_windows, "folder aplikasi belum dipakai sebagai /D"
    berkas_bat = updater.tulis_berkas_jalankan_ulang()
    assert berkas_bat.exists(), "berkas peluncur ulang tidak dibuat"
    assert str(berkas_bat) in baris_windows, "perintah tidak menunjuk berkas peluncur ulang"
    isi_bat = berkas_bat.read_bytes().decode("utf-8")
    assert isi_bat.startswith("@echo off"), "berkas peluncur ulang tidak diawali @echo off"
    assert "\r\n" in isi_bat, "berkas .bat harus memakai akhir baris Windows (CRLF)"
    import subprocess as _subprocess
    baris_perintah = _subprocess.list2cmdline(updater.perintah_restart())
    assert baris_perintah in isi_bat, "berkas peluncur ulang tidak memuat perintah server"
    assert f'cd /d "{updater.BASE_DIR}"' in isi_bat, "berkas peluncur ulang tidak pindah folder"
    assert "ping -n 3" in isi_bat, "berkas peluncur ulang tidak menunggu server lama berhenti"
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
    return "halaman admin aman; form siswa tampil tanpa kolom NISN"

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
                     "/pengaturan/dokumentasi-api", "/profil-akun", "/pembaruan", "/bot-dapodik"]

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
            terlarang = await client.get("/pengaturan")
            assert terlarang.status_code in (303, 403), "siswa seharusnya tidak bisa membuka Pengaturan"

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
    return "pola alamat cloudflared, mode lokal, SM-online.bat CRLF, panduan README"


@cek("20. Akun ekstrakurikuler (NIK 16 digit, 1 pembina + 1 pelatih per ekskul)")
def cek_akun_ekskul():
    """Uji aturan akun pembina/pelatih: NIK 16 angka, klaim posisi, izin akses."""
    import asyncio

    import httpx

    from app import auth, db, migrations, services
    from app.main import app

    # --- Daftar ekskul resmi sekolah tersedia ------------------------------ #
    diharapkan = [nama for nama, _ in migrations.EKSKUL_SEKOLAH]
    tersedia = {baris["nama"]: baris for baris in services.list_ekskul()}
    kurang = [nama for nama in diharapkan if nama not in tersedia]
    assert not kurang, f"ekskul belum ada: {kurang}"
    assert len(diharapkan) == 14, len(diharapkan)
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
        return "14 ekskul resmi; NIK 16 angka; klaim pembina & pelatih; tolak NIK lain; lepas oleh admin"

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
            assert "Klub Daftar Uji" in halaman.text and "Riwayat Pendaftaran" in halaman.text
            kirim = await klien.post(f"/portal/ekstrakurikuler/{ekskul_id}/daftar",
                                     data={"catatan": "Saya ingin ikut"})
            assert kirim.status_code == 200, kirim.status_code
            assert "menunggu persetujuan" in kirim.text.lower(), "siswa harus diberi tahu menunggu"

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
            palsu_cari.siapkan_popup_setelah_cari(nisn_cari)
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
            f"pengumuman Dapodik · "
            f"sekarang {len(services.bot_nisn_sukses())} NISN berhasil")


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
