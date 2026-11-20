"""Persetujuan pengajuan perubahan data siswa (khusus admin).

Siswa boleh mengajukan perubahan hampir semua kolom, tetapi data baru hanya
dipakai setelah admin memeriksa bukti (akta kelahiran, kartu keluarga, ijazah)
dan menekan **Setujui**.
"""

from __future__ import annotations

import mimetypes
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse

from .. import auth, config, db, services
from ..web import paginate, render

router = APIRouter()

STATUS_PILIHAN = (
    ("menunggu", "Menunggu persetujuan"),
    ("disetujui", "Disetujui"),
    ("ditolak", "Ditolak"),
    ("dibatalkan", "Dibatalkan siswa"),
    ("semua", "Semua"),
)


def _redirect(pesan: str, level: str = "ok", tujuan: str = "/pengajuan") -> RedirectResponse:
    return RedirectResponse(f"{tujuan}?level={level}&msg={quote_plus(pesan)}", status_code=303)


@router.get("/pengajuan")
def daftar_pengajuan(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    params = request.query_params
    status = params.get("status", "menunggu")
    if status not in {kode for kode, _ in STATUS_PILIHAN}:
        status = "menunggu"
    q = params.get("q", "").strip()
    try:
        page = max(1, int(params.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 25

    total = services.hitung_pengajuan(None if status == "semua" else status)
    if q:
        total = len(services.daftar_pengajuan(status=status, q=q, limit=1000))
    rows = services.daftar_pengajuan(status=status, q=q, limit=per_page,
                                      offset=(page - 1) * per_page)
    return render(
        request,
        "approval/list.html",
        {
            "page_title": "Persetujuan Data Siswa",
            "pengajuan": rows,
            "status_terpilih": status,
            "status_pilihan": STATUS_PILIHAN,
            "q": q,
            "statistik": services.statistik_pengajuan(),
            "pagination": paginate(total, page, per_page),
            "dokumen_max_mb": config.DOKUMEN_MAX_MB,
        },
    )


@router.get("/pengajuan/dokumen/{doc_id}")
def berkas_pengajuan(request: Request, doc_id: int,
                     user: auth.SessionUser = Depends(auth.require_admin)):
    dokumen = services.ambil_dokumen(doc_id)
    if dokumen is None:
        return render(request, "error.html", {"kode": 404, "pesan": "Berkas tidak ditemukan."},
                      status_code=404)
    path = services.path_dokumen(dokumen)
    if not path.exists():
        return render(request, "error.html", {"kode": 404, "pesan": "Berkas sudah tidak ada di server."},
                      status_code=404)
    media = mimetypes.guess_type(dokumen.get("nama_asli") or path.name)[0] or "application/octet-stream"
    nama = (dokumen.get("nama_asli") or path.name).replace('"', "")
    return FileResponse(
        path,
        media_type=media,
        headers={"Content-Disposition": f'inline; filename="{nama}"'},
    )


@router.get("/pengajuan/{request_id}")
def detail_pengajuan(request: Request, request_id: int,
                     user: auth.SessionUser = Depends(auth.require_admin)):
    pengajuan = services.ambil_pengajuan(request_id)
    if pengajuan is None:
        return render(request, "error.html",
                      {"kode": 404, "pesan": "Pengajuan tidak ditemukan."}, status_code=404)

    return render(
        request,
        "approval/detail.html",
        {
            "page_title": f"Pengajuan #{pengajuan['id']}",
            "p": pengajuan,
            "siswa": pengajuan.get("siswa") or {},
            "items": pengajuan.get("items") or [],
            "dokumen": pengajuan.get("dokumen") or [],
            "dokumen_siswa": pengajuan.get("dokumen_siswa") or {},
            "dokumen_jenis": services.DOKUMEN_JENIS,
            "riwayat_siswa": services.student_changes(int(pengajuan["student_id"]), limit=10),
            "wajib_lengkap": services.dokumen_lengkap(int(pengajuan["student_id"]))[0],
        },
    )


@router.post("/pengajuan/{request_id}/putuskan")
def putuskan(request: Request, request_id: int,
             keputusan: str = Form("terima"), catatan: str = Form(""),
             user: auth.SessionUser = Depends(auth.require_admin)):
    tujuan = f"/pengajuan/{request_id}"
    terima = keputusan == "terima"
    try:
        hasil = services.putuskan_pengajuan(
            request_id, terima, aktor=user.username, catatan=catatan.strip()
        )
    except ValueError as exc:
        return _redirect(str(exc), level="err", tujuan=tujuan)

    if terima:
        pesan = (
            f"Pengajuan disetujui. {hasil.get('jumlah_diterapkan', 0)} kolom data "
            f"{hasil.get('nama') or ''} diperbarui dan tercatat pada riwayat perubahan."
        )
    else:
        pesan = f"Pengajuan {hasil.get('nama') or ''} ditolak. Siswa dapat mengajukan ulang."
    return _redirect(pesan, tujuan="/pengajuan")


@router.post("/pengajuan/{request_id}/hapus")
def hapus_pengajuan(request: Request, request_id: int,
                    user: auth.SessionUser = Depends(auth.require_admin)):
    pengajuan = services.ambil_pengajuan(request_id)
    if pengajuan is None:
        return _redirect("Pengajuan tidak ditemukan.", level="err")
    for dokumen in pengajuan.get("dokumen") or []:
        services.hapus_dokumen(int(dokumen["id"]), aktor=user.username)
    db.execute("DELETE FROM change_requests WHERE id = ?", (request_id,))
    services.log_audit(user.username, user.role, "hapus_pengajuan", "change_requests", request_id,
                       pengajuan.get("nama"))
    return _redirect("Pengajuan beserta berkasnya dihapus.", tujuan="/pengajuan")
