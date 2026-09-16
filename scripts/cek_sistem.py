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
    return f"{len(tabel)} tabel, {db.query_value('SELECT COUNT(*) FROM settings')} pengaturan, {config.DB_PATH.name}"


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


@cek("10. Ekstrakurikuler: kegiatan, anggota, dan nilai")
def cek_ekskul():
    from app import db, services

    jumlah_seed = services.seed_ekskul_if_empty()
    ekskul_id = services.save_ekskul({"nama": "Klub Uji", "kategori": "Teknologi",
                                      "hari": "Senin", "aktif": 1}, actor="cek")
    siswa = db.query_one("SELECT id FROM students LIMIT 1")
    member_id = services.add_ekskul_member(ekskul_id, int(siswa["id"]), jabatan="Ketua", actor="cek")
    assert member_id, "gagal menambah anggota"
    duplikat = services.add_ekskul_member(ekskul_id, int(siswa["id"]), actor="cek")
    assert duplikat is None, "anggota ganda seharusnya ditolak"
    services.update_ekskul_member(member_id, {"nilai": 90, "predikat": "A"}, actor="cek")
    anggota = services.ekskul_members(ekskul_id)
    stats = services.ekskul_stats()
    assert anggota and anggota[0]["nilai"] == 90
    services.remove_ekskul_member(member_id, actor="cek")
    return (f"{jumlah_seed} contoh kegiatan dibuat, {len(anggota)} anggota teruji, "
            f"total kegiatan {stats['total']}")


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
    assert len(services.FIELD_DAPAT_DIAJUKAN) == len(STUDENT_FIELDS) - 1

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
    return (f"{len(services.FIELD_DAPAT_DIAJUKAN)} kolom dapat diajukan (NISN terkunci); "
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
                     "/pengaturan/dokumentasi-api", "/profil-akun", "/pembaruan"]

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
        return f"{len(halaman_admin)} halaman petugas + portal siswa + 3 endpoint API diuji"

    return asyncio.run(jalankan())


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
