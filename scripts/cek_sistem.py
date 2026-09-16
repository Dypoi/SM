#!/usr/bin/env python3
"""Pemeriksaan mandiri SIMSEK (tanpa perlu pytest).

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
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# --- Database sementara: HARUS diatur sebelum mengimpor modul app ---
_SEMENTARA = Path(tempfile.mkdtemp(prefix="simsek-cek-"))
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
    assert parsed.mapped_field_count >= 60, f"hanya {parsed.mapped_field_count} kolom terpetakan"
    assert len(parsed.records) > 100, f"hanya {len(parsed.records)} baris terbaca"
    errors = [i for i in parsed.issues if i.level == "error"]
    assert not errors, f"ada {len(errors)} error tidak terduga: {errors[:2]}"
    return (f"{len(parsed.records)} baris, {parsed.mapped_field_count}/{parsed.total_columns} kolom, "
            f"header baris {parsed.header_row}, sub-header {parsed.sub_header_row}")


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


@cek("14. Halaman HTTP (status 200 & izin akses)")
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
    parser = argparse.ArgumentParser(description="Pemeriksaan mandiri SIMSEK")
    parser.add_argument("--http", action="store_true", help="Sertakan pengujian halaman HTTP")
    args = parser.parse_args()

    print("=" * 78)
    print("  PEMERIKSAAN MANDIRI SIMSEK")
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
    if args.http:
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
