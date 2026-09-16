"""Halaman data peserta didik, statistik, dan kualitas data."""

from __future__ import annotations

import datetime as dt

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from .. import auth, config, services
from ..dapodik import FIELD_BY_KEY, fields_by_group
from ..web import paginate, query_string, render

router = APIRouter()

COLUMN_PRESETS = {
    "ringkas": ["nama", "nisn", "nipd", "jk", "rombel", "tempat_lahir", "tanggal_lahir", "status"],
    "kontak": ["nama", "nisn", "rombel", "alamat", "kelurahan", "kecamatan", "hp"],
    "orangtua": ["nama", "nisn", "rombel", "ayah_nama", "ayah_pekerjaan", "ibu_nama", "ibu_pekerjaan", "hp"],
    "bantuan": ["nama", "nisn", "rombel", "penerima_kip", "nomor_kip", "penerima_kps", "layak_pip", "alasan_layak_pip"],
}


def _filters_from_request(request: Request) -> services.StudentFilter:
    params = request.query_params
    return services.StudentFilter(
        q=params.get("q", "").strip(),
        rombel=params.get("rombel", ""),
        tingkat=params.get("tingkat", ""),
        jk=params.get("jk", ""),
        agama=params.get("agama", ""),
        status=params.get("status", ""),
        kelurahan=params.get("kelurahan", ""),
        sort=params.get("sort", "nama"),
        direction=params.get("dir", "asc"),
        incomplete_only=params.get("lengkap") == "0",
    )


@router.get("/data-siswa")
def daftar_siswa(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    filters = _filters_from_request(request)
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        page = 1
    try:
        per_page = min(200, max(10, int(request.query_params.get("per", config.ROWS_PER_PAGE))))
    except ValueError:
        per_page = config.ROWS_PER_PAGE

    preset = request.query_params.get("kolom", "ringkas")
    if preset not in COLUMN_PRESETS:
        preset = "ringkas"

    rows, total = services.list_students(filters, page=page, per_page=per_page)
    return render(
        request,
        "students/list.html",
        {
            "page_title": "Data Siswa",
            "rows": rows,
            "total": total,
            "pagination": paginate(total, page, per_page),
            "filters": filters,
            "filter_aktif": any(
                [filters.q, filters.rombel, filters.tingkat, filters.jk, filters.agama,
                 filters.status, filters.kelurahan, filters.incomplete_only]
            ),
            "opsi_rombel": services.distinct_values("rombel"),
            "opsi_tingkat": services.distinct_values("tingkat"),
            "opsi_agama": services.distinct_values("agama"),
            "opsi_kelurahan": services.distinct_values("kelurahan"),
            "opsi_status": services.STATUS_OPTIONS,
            "statistik": services.student_stats(),
            "kolom": COLUMN_PRESETS[preset],
            "preset": preset,
            "presets": {key: [FIELD_BY_KEY[k].label for k in keys if k in FIELD_BY_KEY] for key, keys in COLUMN_PRESETS.items()},
            "field_by_key": FIELD_BY_KEY,
            "qs": query_string(request),
        },
    )


@router.get("/data-siswa/baru")
def form_siswa_baru(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    return render(
        request,
        "students/form.html",
        {
            "page_title": "Tambah Siswa",
            "siswa": {},
            "grup_field": fields_by_group(),
            "mode": "baru",
            "status_options": services.STATUS_OPTIONS,
            "agama_options": services.AGAMA_OPTIONS,
        },
    )


async def _form_to_values(request: Request) -> dict:
    form = await request.form()
    values: dict = {}
    for key, value in form.items():
        if key not in services.STUDENT_WRITABLE:
            continue
        values[key] = (value or "").strip() or None
    for flag in ("is_kps", "is_kip", "is_layak_pip"):
        values.pop(flag, None)
    return values


@router.post("/data-siswa/baru")
async def simpan_siswa_baru(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    values = await _form_to_values(request)
    if not values.get("nama"):
        return RedirectResponse("/data-siswa/baru?level=err&msg=Nama+s siswa+wajib+diisi", status_code=303)
    duplikat = services.student_exists(values.get("nisn"), values.get("nipd"))
    if duplikat:
        pesan = f"NISN/NIPD sudah dipakai oleh {duplikat['nama']}."
        return RedirectResponse(f"/data-siswa/baru?level=err&msg={quote_plus(pesan)}", status_code=303)

    values["nama"] = values["nama"].upper()
    for source, flag in (("penerima_kps", "is_kps"), ("penerima_kip", "is_kip"), ("layak_pip", "is_layak_pip")):
        values[flag] = 1 if (values.get(source) or "").lower().startswith("ya") else 0
    try:
        services.validasi_keluarga(values)
    except ValueError as exc:
        return RedirectResponse(f"/data-siswa/baru?level=err&msg={quote_plus(str(exc))}", status_code=303)

    student_id = services.create_student(values, actor=user.username)
    return RedirectResponse(f"/data-siswa/{student_id}?msg=Data+siswa+berhasil+disimpan", status_code=303)


@router.get("/data-siswa/{student_id}")
def detail_siswa(request: Request, student_id: int, user: auth.SessionUser = Depends(auth.require_staff)):
    siswa = services.get_student(student_id)
    if siswa is None:
        return render(request, "error.html", {"kode": 404, "pesan": "Data siswa tidak ditemukan."}, status_code=404)
    return render(
        request,
        "students/detail.html",
        {
            "page_title": siswa["nama"],
            "siswa": siswa,
            "grup_field": fields_by_group(),
            "status_options": services.STATUS_OPTIONS,
            "agama_options": services.AGAMA_OPTIONS,
            "perubahan": services.student_changes(student_id, limit=25),
            "ekskul": services.student_ekskul(student_id),
            "field_by_key": FIELD_BY_KEY,
        },
    )


@router.post("/data-siswa/{student_id}")
async def perbarui_siswa(request: Request, student_id: int,
                         user: auth.SessionUser = Depends(auth.require_staff)):
    siswa = services.get_student(student_id)
    if siswa is None:
        return RedirectResponse("/data-siswa?level=err&msg=Siswa+tidak+ditemukan", status_code=303)

    values = await _form_to_values(request)
    if "nama" in values and values["nama"]:
        values["nama"] = values["nama"].upper()
    for source, flag in (("penerima_kps", "is_kps"), ("penerima_kip", "is_kip"), ("layak_pip", "is_layak_pip")):
        if source in values:
            values[flag] = 1 if (values.get(source) or "").lower().startswith("ya") else 0

    duplikat = services.student_exists(values.get("nisn"), values.get("nipd"), exclude_id=student_id)
    if duplikat:
        pesan = f"NISN/NIPD sudah dipakai oleh {duplikat['nama']}."
        return RedirectResponse(f"/data-siswa/{student_id}?level=err&msg={quote_plus(pesan)}", status_code=303)

    try:
        services.validasi_keluarga(values, siswa)
    except ValueError as exc:
        return RedirectResponse(f"/data-siswa/{student_id}?level=err&msg={quote_plus(str(exc))}", status_code=303)

    changes = services.update_student(student_id, values, actor=user.username, source="manual")
    pesan = f"{len(changes)} perubahan disimpan." if changes else "Tidak ada perubahan."
    level = "ok" if changes else "info"
    return RedirectResponse(f"/data-siswa/{student_id}?level={level}&msg={quote_plus(pesan)}", status_code=303)


@router.post("/data-siswa/{student_id}/hapus")
def hapus_siswa(request: Request, student_id: int, user: auth.SessionUser = Depends(auth.require_admin)):
    siswa = services.get_student(student_id)
    services.delete_student(student_id, actor=user.username)
    pesan = f"Data {siswa['nama']} dihapus." if siswa else "Data dihapus."
    return RedirectResponse(f"/data-siswa?level=ok&msg={quote_plus(pesan)}", status_code=303)


# --------------------------------------------------------------------------- #
# Ekspor
# --------------------------------------------------------------------------- #
def _nama_berkas(prefix: str, ext: str) -> str:
    return f"{prefix}-{dt.datetime.now():%Y%m%d-%H%M}.{ext}"


@router.get("/data-siswa/ekspor/csv")
def ekspor_csv(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    filters = _filters_from_request(request)
    content = services.export_students_csv(filters)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_nama_berkas("data-siswa", "csv")}"'},
    )


@router.get("/data-siswa/ekspor/xlsx")
def ekspor_xlsx(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    filters = _filters_from_request(request)
    content = services.export_students_xlsx(filters)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_nama_berkas("data-siswa", "xlsx")}"'},
    )


# --------------------------------------------------------------------------- #
# Statistik & kualitas data
# --------------------------------------------------------------------------- #
@router.get("/statistik")
def halaman_statistik(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    return render(
        request,
        "statistics.html",
        {
            "page_title": "Statistik",
            "stats": services.student_stats(),
            "per_tingkat": services.stats_by_tingkat(),
            "per_rombel": services.stats_by_rombel(),
            "agama": services.stats_by("agama", limit=10),
            "kecamatan": services.stats_by("kecamatan", limit=12),
            "kebutuhan_khusus": services.stats_by("kebutuhan_khusus", limit=8),
            "sekolah_asal": services.stats_by("sekolah_asal", limit=12),
            "ekskul": services.ekskul_stats(),
            "ekskul_kategori": services.ekskul_by_kategori(),
        },
    )


@router.get("/kualitas-data")
def halaman_kualitas(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    return render(
        request,
        "quality.html",
        {
            "page_title": "Kualitas Data",
            "kualitas": services.data_quality(),
            "duplikat": services.students_with_duplicate_nisn(),
            "readiness": services.dapodik_readiness(),
            "jobs": services.list_dapodik_jobs(limit=10),
        },
    )


# --------------------------------------------------------------------------- #
# Akun operator
# --------------------------------------------------------------------------- #
@router.get("/profil-akun")
def profil_akun(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    return render(request, "account.html", {"page_title": "Akun Saya"})


@router.post("/profil-akun")
def ganti_sandi(
    request: Request,
    sandi_lama: str = Form(""),
    sandi_baru: str = Form(""),
    ulangi: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    from urllib.parse import quote_plus

    if sandi_baru != ulangi:
        return RedirectResponse("/profil-akun?level=err&msg=Konfirmasi+sandi+tidak+sama", status_code=303)
    try:
        auth.change_password(user.id or 0, sandi_lama, sandi_baru)
    except ValueError as exc:
        return RedirectResponse(f"/profil-akun?level=err&msg={quote_plus(str(exc))}", status_code=303)
    return RedirectResponse("/profil-akun?level=ok&msg=Kata+sandi+berhasil+diubah", status_code=303)
