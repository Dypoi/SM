"""Menu TANGCER — pengelolaan siswa penerima bantuan (Tangerang Cerdas).

Alurnya sengaja dibuat sama seperti impor data siswa: **unggah → pratinjau → simpan**,
supaya tidak ada data yang masuk sebelum dilihat manusia. Bedanya, berkas mentah dari
dinas memuat banyak sekolah sekaligus, jadi pratinjau menampilkan:

* berapa baris milik **sekolah kita** (yang akan disimpan),
* berapa baris milik sekolah lain (diabaikan) beserta rekap per sekolah,
* apa saja yang terbaca/dilewati dari berkas (catatan pembacaan),
* dan berkas PDF juga dilaporkan tata letaknya.

Berkas yang didukung: semua format spreadsheet aplikasi (``.xlsx .xlsm .xltx .xls .xlsb
.ods .csv .txt .tsv``) **dan** ``.pdf`` (SK definitif yang memuat teks).
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import auth, config, db, services, tangcer
from ..readers import UnsupportedFormatError, format_label, supported_extensions
from ..web import render

log = logging.getLogger("sm.tangcer.web")

router = APIRouter()

#: Berkas yang diterima menu ini = format spreadsheet yang sudah didukung aplikasi + PDF.
EKSTENSI_TANGCER = tuple(supported_extensions()) + tangcer.FORMAT_PDF


def _kembali(alamat: str, level: str, pesan: str) -> RedirectResponse:
    return RedirectResponse(f"{alamat}?level={level}&msg={quote_plus(pesan)}", status_code=303)


def _angka(teks: str | None, bawaan: float = 0.0) -> float:
    nilai = tangcer.bersih_nominal(teks if teks is not None else "")
    return bawaan if nilai is None else nilai


def _profil_sekolah() -> tuple[str, str, str]:
    profil = services.school_profile()
    return profil["nama"], profil["npsn"], profil.get("kabupaten", "")


@router.get("/tangcer")
def halaman_tangcer(
    request: Request,
    tahun: str = "",
    semester: str = "",
    cari: str = "",
    cocok: str = "",
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Halaman utama TANGCER: unggah berkas, riwayat impor, daftar penerima."""
    nama_sekolah, npsn, _ = _profil_sekolah()
    ringkas = tangcer.ringkas_penerima()
    return render(
        request,
        "tangcer/index.html",
        {
            "page_title": "TANGCER",
            "sekolah_kita": nama_sekolah,
            "npsn_kita": npsn,
            "format_didukung": [(ext, format_label(ext)) if ext != ".pdf" else (ext, "PDF (SK definitif)")
                                for ext in EKSTENSI_TANGCER],
            "maks_ukuran": config.MAX_UPLOAD_MB,
            "ringkas": ringkas,
            "riwayat": tangcer.daftar_impor(limit=20),
            "penerima": tangcer.daftar_penerima(tahun=tahun, semester=semester, cari=cari,
                                                cocok=cocok, batas=500),
            "tahun_terpakai": tangcer.daftar_tahun(),
            "filter": {"tahun": tahun, "semester": semester, "cari": cari, "cocok": cocok},
            "tahun_ajaran": services.school_profile().get("tahun_ajaran", ""),
            "semester_default": services.school_profile().get("semester", "Ganjil"),
        },
    )


@router.post("/tangcer/unggah")
async def unggah_tangcer(
    request: Request,
    berkas: UploadFile = File(...),
    tahun: str = Form(""),
    semester: str = Form(""),
    tahap: str = Form(""),
    khusus_sekolah: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Baca berkas mentah (Excel/CSV/PDF) lalu tampilkan pratinjau penyaringan."""
    nama = berkas.filename or "unggahan.csv"
    isi = await berkas.read()
    ext = Path(nama).suffix.lower()

    if not isi:
        return _kembali("/tangcer", "err", "Berkas kosong atau gagal dibaca.")
    if ext not in EKSTENSI_TANGCER:
        return _kembali("/tangcer", "err",
                        f"Jenis berkas «{ext or 'tanpa ekstensi'}» belum didukung menu ini. "
                        "Yang didukung: " + ", ".join(EKSTENSI_TANGCER))
    if len(isi) > config.MAX_UPLOAD_BYTES:
        return _kembali("/tangcer", "err", f"Ukuran berkas melebihi {config.MAX_UPLOAD_MB} MB.")

    try:
        hasil = tangcer.baca_isi(nama, isi)
    except UnsupportedFormatError as galat:
        return _kembali("/tangcer", "err", str(galat))
    except tangcer.TangcerError as galat:
        return _kembali("/tangcer", "err", f"Gagal membaca berkas: {galat}")
    except Exception as galat:  # noqa: BLE001
        log.exception("Gagal membaca berkas TANGCER %s", nama)
        return _kembali("/tangcer", "err", f"Gagal membaca berkas: {galat}")

    nama_sekolah, npsn, kabupaten = _profil_sekolah()
    tanpa_kolom = khusus_sekolah.strip() not in {"", "0"}
    saring = tangcer.saring_sekolah(hasil, nama_sekolah, npsn, kabupaten,
                                    tanpa_kolom_sekolah=tanpa_kolom)

    try:
        tersimpan = services.save_upload(nama, isi)
    except Exception as galat:  # noqa: BLE001
        log.exception("Gagal menyimpan unggahan TANGCER")
        return _kembali("/tangcer", "err", f"Berkas tidak bisa disimpan: {galat}")

    import_id = tangcer.buat_impor(
        nama_berkas=nama, path=tersimpan.path, ext=tersimpan.extension, ukuran=tersimpan.size,
        tahun=tahun.strip(), semester=semester.strip(), tahap=tahap.strip(),
        hasil=hasil, saring=saring, kolom=hasil.kolom, actor=user.username,
        tanpa_kolom_sekolah=tanpa_kolom)
    services.log_audit(user.username, user.role, "tangcer_unggah", "tangcer_imports", import_id,
                 f"{nama}: {saring.jumlah_diterima} dari {hasil.jumlah_baris} baris")
    return RedirectResponse(f"/tangcer/impor/{import_id}", status_code=303)


@router.get("/tangcer/impor/{import_id}")
def pratinjau_tangcer(
    request: Request,
    import_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Pratinjau hasil pembacaan & penyaringan sebelum disimpan."""
    kepala = tangcer.get_impor(import_id)
    if kepala is None:
        return _kembali("/tangcer", "err", "Pratinjau impor itu tidak ditemukan.")

    sumber = Path(kepala.get("sumber_path") or "")
    diterima: list[dict] = []
    ditolak: list[dict] = []
    hasil = None
    galat = ""
    if sumber.exists():
        try:
            hasil = tangcer.baca_berkas(sumber, kepala.get("ext") or sumber.suffix.lower())
            saring = tangcer.saring_sekolah(
                hasil, kepala.get("sekolah_kita") or services.school_profile()["nama"],
                services.school_profile()["npsn"], services.school_profile().get("kabupaten", ""),
                tanpa_kolom_sekolah=bool(kepala.get("tanpa_kolom_sekolah")))
            diterima = [item.ke_dict() for item in saring.diterima]
            ditolak = [item.ke_dict() for item in saring.ditolak]
        except tangcer.TangcerError as exc:
            galat = str(exc)
    else:
        galat = "Berkas sumber sudah tidak ada di folder unggahan — simpan ulang berkasnya."

    return render(
        request,
        "tangcer/pratinjau.html",
        {
            "page_title": "Pratinjau TANGCER",
            "kepala": kepala,
            "diterima": diterima,
            "ditolak": ditolak,
            "catatan": (kepala.get("catatan") or "").splitlines(),
            "kolom": kepala.get("kolom") or {},
            "sekolah_lain": kepala.get("sekolah_ditemukan") or {},
            "galat": galat,
            "batas_tampil": 200,
        },
    )


@router.post("/tangcer/impor/{import_id}/simpan")
def simpan_tangcer(
    request: Request,
    import_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Simpan baris milik sekolah kita (baris sekolah lain tetap tidak disimpan)."""
    kepala = tangcer.get_impor(import_id)
    if kepala is None:
        return _kembali("/tangcer", "err", "Pratinjau impor itu tidak ditemukan.")
    if kepala.get("status") == "tersimpan":
        return _kembali(f"/tangcer/impor/{import_id}", "warn",
                        "Impor ini sudah pernah disimpan — baris yang sama tidak digandakan.")
    sumber = Path(kepala.get("sumber_path") or "")
    if not sumber.exists():
        return _kembali("/tangcer", "err",
                        "Berkas sumber sudah tidak ada; unggah ulang berkasnya.")

    profile = services.school_profile()
    try:
        hasil = tangcer.baca_berkas(sumber, kepala.get("ext") or sumber.suffix.lower())
        saring = tangcer.saring_sekolah(
            hasil, kepala.get("sekolah_kita") or profile["nama"], profile["npsn"],
            profile.get("kabupaten", ""),
            tanpa_kolom_sekolah=bool(kepala.get("tanpa_kolom_sekolah")))
    except tangcer.TangcerError as galat:
        return _kembali(f"/tangcer/impor/{import_id}", "err", str(galat))

    tahun = kepala.get("tahun") or ""
    semester = kepala.get("semester") or ""
    tahap = kepala.get("tahap") or ""
    baru, ganda = tangcer.simpan_banyak(import_id, saring.diterima, tahun=tahun,
                                        semester=semester, tahap=tahap)
    hitung = tangcer.cocokkan_dengan_siswa(import_id)
    tangcer.tandai_impor(import_id, status="tersimpan", diterima=baru,
                         catatan="\n".join(tangcer.catatan_impor(hasil, saring)))
    services.log_audit(user.username, user.role, "tangcer_simpan", "tangcer_imports", import_id,
                 f"{baru} baris baru, {ganda} sudah ada, ditemukan di data siswa: {hitung}")
    pesan = (f"{baru} siswa penerima disimpan"
             + (f", {ganda} baris sudah ada sebelumnya (tidak digandakan)" if ganda else "")
             + f". Dikenali pada data siswa: {hitung['nisn'] + hitung['nik'] + hitung['nama']} "
               f"dari {baru} baris.")
    return _kembali(f"/tangcer/impor/{import_id}", "ok", pesan)


@router.post("/tangcer/impor/{import_id}/hapus")
def hapus_impor_tangcer(
    request: Request,
    import_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    kepala = tangcer.get_impor(import_id)
    if kepala is None:
        return _kembali("/tangcer", "err", "Impor itu tidak ditemukan.")
    tangcer.hapus_impor(import_id)
    services.log_audit(user.username, user.role, "tangcer_hapus_impor", "tangcer_imports", import_id,
                 f"impor «{kepala.get('berkas')}» dihapus beserta penerimanya")
    return _kembali("/tangcer", "ok",
                    f"Impor «{kepala.get('berkas')}» dan penerima hasil impor itu dihapus.")


@router.get("/tangcer/penerima/{penerima_id}")
def detail_penerima(
    request: Request,
    penerima_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    baris = db.query_one(
        """
        SELECT p.*, s.nama AS nama_siswa, s.rombel AS rombel_siswa, s.nisn AS nisn_siswa,
               s.status AS status_siswa
          FROM tangcer_penerima p LEFT JOIN students s ON s.id = p.student_id
         WHERE p.id = ?
        """,
        (penerima_id,),
    )
    if baris is None:
        return _kembali("/tangcer", "err", "Data penerima itu tidak ditemukan.")
    return render(
        request,
        "tangcer/penerima.html",
        {
            "page_title": "Data Penerima TANGCER",
            "item": dict(baris),
            "cocok_label": tangcer.COCOK_LABEL,
        },
    )


@router.post("/tangcer/penerima/{penerima_id}/ubah")
def ubah_penerima(
    request: Request,
    penerima_id: int,
    nama: str = Form(""),
    nisn: str = Form(""),
    nik: str = Form(""),
    rombel: str = Form(""),
    jenis: str = Form(""),
    nominal: str = Form(""),
    keterangan: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    baris = db.query_one("SELECT * FROM tangcer_penerima WHERE id = ?", (penerima_id,))
    if baris is None:
        return _kembali("/tangcer", "err", "Data penerima itu tidak ditemukan.")
    db.execute(
        """
        UPDATE tangcer_penerima
           SET nama = ?, nisn = ?, nik = ?, rombel = ?, jenis = ?, nominal = ?,
               keterangan = ?, cocok = 'belum_dicek', student_id = NULL
         WHERE id = ?
        """,
        (tangcer.bersih_teks(nama), tangcer.bersih_nomor(nisn), tangcer.bersih_nomor(nik),
         tangcer.bersih_teks(rombel), tangcer.bersih_teks(jenis), _angka(nominal),
         tangcer.bersih_teks(keterangan), penerima_id),
    )
    hitung = tangcer.cocokkan_dengan_siswa()
    services.log_audit(user.username, user.role, "tangcer_ubah", "tangcer_penerima", penerima_id,
                 f"{baris['nama']} diubah; pencocokan ulang: {hitung}")
    return _kembali(f"/tangcer/penerima/{penerima_id}", "ok", "Perubahan disimpan.")


@router.post("/tangcer/penerima/{penerima_id}/hapus")
def hapus_penerima(
    request: Request,
    penerima_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    baris = db.query_one("SELECT * FROM tangcer_penerima WHERE id = ?", (penerima_id,))
    if baris is None:
        return _kembali("/tangcer", "err", "Data penerima itu tidak ditemukan.")
    tangcer.hapus_satu(penerima_id)
    services.log_audit(user.username, user.role, "tangcer_hapus", "tangcer_penerima", penerima_id,
                 f"{baris['nama']} dihapus dari daftar penerima")
    return _kembali("/tangcer", "ok", f"«{baris['nama']}» dihapus dari daftar penerima.")


@router.post("/tangcer/cocokkan")
def cocokkan_semua(
    request: Request,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    hitung = tangcer.cocokkan_dengan_siswa()
    pesan = (f"Pencocokan selesai: {hitung['nisn']} lewat NISN, {hitung['nik']} lewat NIK, "
             f"{hitung['nama']} lewat nama, {hitung['tidak_ada']} belum ada di data siswa.")
    services.log_audit(user.username, user.role, "tangcer_cocokkan", "tangcer_penerima", None, pesan)
    return _kembali("/tangcer", "ok", pesan)


@router.post("/tangcer/hapus")
def hapus_daftar(
    request: Request,
    tahun: str = Form(""),
    semester: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    jumlah = tangcer.hapus_penerima(tahun.strip(), semester.strip())
    services.log_audit(user.username, user.role, "tangcer_hapus_daftar", "tangcer_penerima", None,
                 f"{jumlah} penerima dihapus (tahun «{tahun or 'semua'}», semester «{semester or 'semua'}»)")
    return _kembali("/tangcer", "ok",
                    f"{jumlah} data penerima dihapus"
                    + (f" (tahun {tahun}, semester {semester})." if tahun or semester else "."))


@router.get("/tangcer/ekspor.csv")
def ekspor_tangcer_csv(
    tahun: str = "",
    semester: str = "",
    user: auth.SessionUser = Depends(auth.require_staff),
):
    isi = tangcer.ekspor_csv(tahun, semester)
    nama = f"daftar-penerima-tangcer-{tahun or 'semua'}-{semester or 'semua'}.csv".replace(" ", "-")
    return Response(isi, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nama}"'})


@router.get("/tangcer/ekspor.xlsx")
def ekspor_tangcer_xlsx(
    tahun: str = "",
    semester: str = "",
    user: auth.SessionUser = Depends(auth.require_staff),
):
    isi = tangcer.ekspor_xlsx(tahun, semester)
    nama = f"daftar-penerima-tangcer-{tahun or 'semua'}-{semester or 'semua'}.xlsx".replace(" ", "-")
    return Response(
        isi, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'})


@router.get("/tangcer/ekspor.pdf")
def ekspor_tangcer_pdf(
    tahun: str = "",
    semester: str = "",
    user: auth.SessionUser = Depends(auth.require_staff),
):
    isi = tangcer.ekspor_pdf(tahun, semester)
    nama = f"daftar-penerima-tangcer-{tahun or 'semua'}-{semester or 'semua'}.pdf".replace(" ", "-")
    return Response(isi, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nama}"'})
