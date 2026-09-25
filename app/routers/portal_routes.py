"""Portal siswa: data pribadi, ekstrakurikuler, dan pengajuan perubahan data.

Siswa masuk memakai NISN. Seluruh perubahan data diajukan lewat **pengajuan**
yang harus disetujui admin; NISN tidak dapat diubah sama sekali.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse

from .. import auth, config, services
from ..dapodik import FIELD_BY_KEY
from ..services import FIELD_PENTING, FIELD_WAJIB
from ..web import field_groups, render

router = APIRouter()


def _siswa_aktif(user: auth.SessionUser) -> dict | None:
    if user.student_id:
        return services.get_student(user.student_id)
    if user.nisn:
        return services.get_student_by_nisn(user.nisn)
    return None


def _kelengkapan(siswa: dict) -> dict:
    def terisi(key: str) -> bool:
        value = siswa.get(key)
        return value is not None and str(value).strip() != ""

    wajib = [{"key": key, "label": FIELD_BY_KEY[key].label, "terisi": terisi(key)} for key in FIELD_WAJIB]
    lain = [{"key": key, "label": FIELD_BY_KEY[key].label, "terisi": terisi(key)} for key in FIELD_PENTING]
    terisi_wajib = sum(1 for item in wajib if item["terisi"])
    total = len(wajib) + len(lain)
    terisi_total = terisi_wajib + sum(1 for item in lain if item["terisi"])
    return {
        "wajib": wajib,
        "lain": lain,
        "persen": round(terisi_total / total * 100) if total else 0,
        "belum": [item for item in wajib + lain if not item["terisi"]],
    }


def _pesan(teks: str, level: str = "ok", tujuan: str = "/portal/pengajuan") -> RedirectResponse:
    return RedirectResponse(f"{tujuan}?level={level}&msg={quote_plus(teks)}", status_code=303)


def _siapkan_siswa(user: auth.SessionUser, request: Request):
    """Ambil data siswa; kembalikan (siswa, respons_error) bila tidak ada."""
    if user.role != auth.ROLE_SISWA:
        return None, RedirectResponse("/", status_code=303)
    siswa = _siswa_aktif(user)
    if siswa is None:
        return None, render(
            request,
            "error.html",
            {"kode": 404, "pesan": "Data siswa tidak ditemukan. Hubungi tata usaha."},
            status_code=404,
        )
    return siswa, None


@router.get("/portal")
def beranda_siswa(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    siswa, error = _siapkan_siswa(user, request)
    if error:
        return error

    pengajuan = services.pengajuan_siswa(int(siswa["id"]), limit=5)
    return render(
        request,
        "portal/home.html",
        {
            "page_title": "Beranda Saya",
            "siswa": siswa,
            "kelengkapan": _kelengkapan(siswa),
            "ekskul": services.student_ekskul(siswa["id"]),
            "pendaftaran_ekskul": services.pendaftaran_siswa(siswa["id"]),
            "profil": services.school_profile(),
            "pengajuan": pengajuan,
            "menunggu": sum(1 for item in pengajuan if item["status"] == "menunggu"),
            "dokumen": services.dokumen_terbaru(int(siswa["id"])),
            # Dipakai beranda gaya baru (ruang siswa): daftar berkas + apakah
            # sekolah sedang membuka pengajuan perubahan data.
            "dokumen_jenis": services.DOKUMEN_JENIS,
            "pengajuan_aktif": services.pengajuan_aktif(),
        },
    )


@router.get("/portal/ekstrakurikuler")
def ekskul_siswa(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    if user.role != auth.ROLE_SISWA:
        return RedirectResponse("/ekstrakurikuler", status_code=303)
    siswa = _siswa_aktif(user)
    if siswa is None:
        return RedirectResponse("/portal", status_code=303)

    pendaftaran = {item["ekskul_id"]: item for item in services.pendaftaran_siswa(siswa["id"])}
    return render(
        request,
        "portal/ekskul.html",
        {
            "page_title": "Ekstrakurikuler",
            "siswa": siswa,
            "diikuti": services.student_ekskul(siswa["id"]),
            "tersedia": services.list_ekskul(aktif_only=True),
            "pendaftaran": pendaftaran,
            "status_label": services.PENDAFTARAN_LABEL,
        },
    )


@router.post("/portal/ekstrakurikuler/{ekskul_id}/daftar")
def daftar_ekskul(
    request: Request,
    ekskul_id: int,
    catatan: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_user),
):
    """Siswa memilih ekskul yang ingin diikuti — menunggu persetujuan pembina/pelatih."""
    if user.role != auth.ROLE_SISWA:
        return RedirectResponse("/ekstrakurikuler", status_code=303)
    siswa = _siswa_aktif(user)
    if siswa is None:
        return RedirectResponse("/portal", status_code=303)
    berhasil, pesan = services.ajukan_pendaftaran_ekskul(
        siswa["id"], ekskul_id, catatan=catatan, actor=user.username)
    return RedirectResponse(
        f"/portal/ekstrakurikuler?level={'ok' if berhasil else 'warn'}&msg={quote_plus(pesan)}",
        status_code=303)


@router.post("/portal/ekstrakurikuler/pendaftaran/{pendaftaran_id}/batalkan")
def batal_daftar_ekskul(
    request: Request,
    pendaftaran_id: int,
    user: auth.SessionUser = Depends(auth.require_user),
):
    if user.role != auth.ROLE_SISWA:
        return RedirectResponse("/ekstrakurikuler", status_code=303)
    siswa = _siswa_aktif(user)
    if siswa is None:
        return RedirectResponse("/portal", status_code=303)
    berhasil, pesan = services.batalkan_pendaftaran_ekskul(
        pendaftaran_id, siswa["id"], actor=user.username)
    return RedirectResponse(
        f"/portal/ekstrakurikuler?level={'ok' if berhasil else 'warn'}&msg={quote_plus(pesan)}",
        status_code=303)


@router.get("/portal/profil")
def profil_siswa(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    if user.role != auth.ROLE_SISWA:
        return RedirectResponse("/profil-akun", status_code=303)
    siswa = _siswa_aktif(user)
    if siswa is None:
        return RedirectResponse("/portal", status_code=303)

    grup_medan = field_groups()
    return render(
        request,
        "portal/profile.html",
        {
            "page_title": "Data Saya",
            "siswa": siswa,
            "grup_field": grup_medan,
            # Dipakai halaman «Dataku» gaya baru: jumlah baris ditampilkan pada keterangan
            # pencarian supaya anak tahu berapa banyak data yang ada.
            "jumlah_medan": sum(len(d) for d in grup_medan.values()),
            "kelengkapan": _kelengkapan(siswa),
            "dokumen": services.dokumen_terbaru(int(siswa["id"])),
            "pengajuan": services.pengajuan_siswa(int(siswa["id"]), limit=10),
            "dokumen_jenis": services.DOKUMEN_JENIS,
            "pengajuan_aktif": services.pengajuan_aktif(),
        },
    )


@router.get("/portal/pengajuan")
def form_pengajuan(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    siswa, error = _siapkan_siswa(user, request)
    if error:
        return error

    lengkap, kurang = services.dokumen_lengkap(int(siswa["id"]))
    return render(
        request,
        "portal/request.html",
        {
            "page_title": "Ajukan Perubahan Data",
            "siswa": siswa,
            "grup_field": field_groups(),
            "agama_options": services.AGAMA_OPTIONS,
            "dokumen": services.dokumen_terbaru(int(siswa["id"])),
            "dokumen_jenis": services.DOKUMEN_JENIS,
            "dokumen_lengkap": lengkap,
            "dokumen_kurang": kurang,
            "pengajuan": services.pengajuan_siswa(int(siswa["id"]), limit=10),
            "pengajuan_aktif": services.pengajuan_aktif(),
            "wajib_dokumen": services.pengajuan_dokumen_wajib(),
            "dokumen_max_mb": config.DOKUMEN_MAX_MB,
        },
    )


@router.post("/portal/pengajuan")
async def kirim_pengajuan(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    siswa, error = _siapkan_siswa(user, request)
    if error:
        return error

    form = await request.form()
    nilai: dict[str, str] = {}
    for key in services.FIELD_DAPAT_DIAJUKAN:
        if key in form:
            nilai[key] = str(form.get(key) or "").strip()

    dokumen: dict[str, tuple[str, bytes]] = {}
    for jenis, _, _ in services.DOKUMEN_JENIS:
        berkas = form.get(f"dokumen_{jenis}")
        if berkas is None or not getattr(berkas, "filename", ""):
            continue
        isi = await berkas.read()
        if isi:
            dokumen[jenis] = (berkas.filename, isi)

    try:
        pengajuan = services.ajukan_perubahan(
            int(siswa["id"]),
            nilai,
            catatan=str(form.get("catatan_siswa") or "").strip(),
            aktor=f"siswa:{user.nisn}",
            ip=request.client.host if request.client else None,
            dokumen=dokumen,
        )
    except ValueError as exc:
        return _pesan(str(exc), level="err")

    catatan = pengajuan.get("catatan_sistem") or ""
    if pengajuan.get("status") == "disetujui":
        return _pesan(
            catatan or "Data wali dihapus otomatis oleh sistem.",
            tujuan="/portal/profil",
        )
    jumlah = pengajuan.get("jumlah_field", 0)
    pesan = (
        f"Pengajuan terkirim: {jumlah} kolom menunggu persetujuan admin. "
        "Anda akan melihat statusnya di halaman ini."
    )
    if catatan:
        pesan = f"{catatan} {pesan}"
    return _pesan(pesan)


@router.post("/portal/pengajuan/{request_id}/batalkan")
def batalkan_pengajuan(request: Request, request_id: int,
                       user: auth.SessionUser = Depends(auth.require_user)):
    siswa, error = _siapkan_siswa(user, request)
    if error:
        return error
    pengajuan = services.ambil_pengajuan(request_id)
    if pengajuan is None or int(pengajuan["student_id"]) != int(siswa["id"]):
        return _pesan("Pengajuan tidak ditemukan.", level="err")
    if pengajuan["status"] != "menunggu":
        return _pesan("Pengajuan ini sudah diputuskan admin.", level="err")
    services.batalkan_pengajuan(request_id, aktor=f"siswa:{user.nisn}")
    return _pesan("Pengajuan dibatalkan.")


@router.get("/portal/dokumen/{doc_id}")
def unduh_dokumen(request: Request, doc_id: int,
                  user: auth.SessionUser = Depends(auth.require_user)):
    """Sajikan berkas pendukung hanya untuk pemiliknya (atau admin)."""
    dokumen = services.ambil_dokumen(doc_id)
    if dokumen is None:
        return render(request, "error.html", {"kode": 404, "pesan": "Berkas tidak ditemukan."},
                      status_code=404)

    siswa = _siswa_aktif(user)
    milik_sendiri = siswa is not None and int(dokumen["student_id"]) == int(siswa["id"])
    if not milik_sendiri and not user.is_admin:
        return render(request, "error.html", {"kode": 403, "pesan": "Berkas ini bukan milik Anda."},
                      status_code=403)

    path: Path = services.path_dokumen(dokumen)
    if not path.exists():
        return render(request, "error.html", {"kode": 404, "pesan": "Berkas sudah tidak ada di server."},
                      status_code=404)

    media = mimetypes.guess_type(dokumen.get("nama_asli") or path.name)[0] or "application/octet-stream"
    nama = (dokumen.get("nama_asli") or path.name).replace('"', "")
    return FileResponse(
        path,
        media_type=media,
        filename=None if request.query_params.get("unduh") else nama,
        headers={"Content-Disposition": f'inline; filename="{nama}"'},
    )
