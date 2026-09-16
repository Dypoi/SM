"""Modul ekstrakurikuler."""

from __future__ import annotations

import csv
import io
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from .. import auth, services
from ..web import render

router = APIRouter()


def _redirect(pesan: str, level: str = "ok", target: str = "/ekstrakurikuler"):
    return RedirectResponse(f"{target}?level={level}&msg={quote_plus(pesan)}", status_code=303)


@router.get("/ekstrakurikuler")
def daftar_ekskul(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    edit_id = request.query_params.get("edit", "")
    edit_item = services.get_ekskul(int(edit_id)) if edit_id.isdigit() else None
    return render(
        request,
        "ekskul/list.html",
        {
            "page_title": "Ekstrakurikuler",
            "daftar": services.list_ekskul(),
            "stats": services.ekskul_stats(),
            "kategori_options": services.EKSKUL_KATEGORI,
            "hari_options": services.HARI_OPTIONS,
            "edit_item": edit_item,
            "kategori": services.ekskul_by_kategori(),
        },
    )


@router.post("/ekstrakurikuler/simpan")
def simpan_ekskul(
    request: Request,
    ekskul_id: str = Form(""),
    kode: str = Form(""),
    nama: str = Form(""),
    kategori: str = Form("Lainnya"),
    pembina: str = Form(""),
    hari: str = Form(""),
    jam_mulai: str = Form(""),
    jam_selesai: str = Form(""),
    tempat: str = Form(""),
    kuota: str = Form(""),
    deskripsi: str = Form(""),
    aktif: str = Form("0"),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    data = {
        "kode": kode.strip().upper() or None,
        "nama": nama.strip(),
        "kategori": kategori or "Lainnya",
        "pembina": pembina.strip() or None,
        "hari": hari or None,
        "jam_mulai": jam_mulai or None,
        "jam_selesai": jam_selesai or None,
        "tempat": tempat.strip() or None,
        "kuota": int(kuota) if str(kuota).strip().isdigit() else None,
        "deskripsi": deskripsi.strip() or None,
        "aktif": 1 if aktif in {"1", "on", "true"} else 0,
    }
    try:
        new_id = services.save_ekskul(data, ekskul_id=int(ekskul_id) if ekskul_id.isdigit() else None,
                                      actor=user.username)
    except ValueError as exc:
        return _redirect(str(exc), level="err")

    if ekskul_id.isdigit():
        return _redirect(f"Ekstrakurikuler {data['nama']} diperbarui.", target=f"/ekstrakurikuler/{new_id}")
    return _redirect(f"Ekstrakurikuler {data['nama']} ditambahkan.", target=f"/ekstrakurikuler/{new_id}")


@router.get("/ekstrakurikuler/{ekskul_id}")
def detail_ekskul(request: Request, ekskul_id: int, user: auth.SessionUser = Depends(auth.require_staff)):
    ekskul = services.get_ekskul(ekskul_id)
    if ekskul is None:
        return render(request, "error.html", {"kode": 404, "pesan": "Ekstrakurikuler tidak ditemukan."}, status_code=404)
    return render(
        request,
        "ekskul/detail.html",
        {
            "page_title": ekskul["nama"],
            "ekskul": ekskul,
            "anggota": services.ekskul_members(ekskul_id),
            "kategori_options": services.EKSKUL_KATEGORI,
            "hari_options": services.HARI_OPTIONS,
            "opsi_rombel": services.distinct_values("rombel"),
        },
    )


@router.post("/ekstrakurikuler/{ekskul_id}/hapus")
def hapus_ekskul(request: Request, ekskul_id: int, user: auth.SessionUser = Depends(auth.require_staff)):
    ekskul = services.get_ekskul(ekskul_id)
    services.delete_ekskul(ekskul_id, actor=user.username)
    return _redirect(f"Ekstrakurikuler {ekskul['nama'] if ekskul else ''} dihapus.")


@router.post("/ekstrakurikuler/{ekskul_id}/anggota")
def tambah_anggota(
    request: Request,
    ekskul_id: int,
    student_id: str = Form(""),
    nisn: str = Form(""),
    jabatan: str = Form("Anggota"),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    target = f"/ekstrakurikuler/{ekskul_id}"
    siswa = None
    if student_id.isdigit():
        siswa = services.get_student(int(student_id))
    elif nisn.strip():
        siswa = services.get_student_by_nisn(nisn.strip())

    if siswa is None:
        return _redirect("Siswa tidak ditemukan. Masukkan NISN yang benar.", level="err", target=target)

    member_id = services.add_ekskul_member(ekskul_id, siswa["id"], jabatan=jabatan or "Anggota",
                                           actor=user.username)
    if member_id is None:
        return _redirect(f"{siswa['nama']} sudah terdaftar di ekstrakurikuler ini.", level="warn", target=target)
    return _redirect(f"{siswa['nama']} ditambahkan ke ekstrakurikuler.", target=target)


@router.post("/ekstrakurikuler/anggota/{member_id}/hapus")
def hapus_anggota(request: Request, member_id: int,
                  user: auth.SessionUser = Depends(auth.require_staff)):
    row = services.db.query_one("SELECT ekskul_id FROM ekskul_members WHERE id = ?", (member_id,))
    services.remove_ekskul_member(member_id, actor=user.username)
    target = f"/ekstrakurikuler/{row['ekskul_id']}" if row else "/ekstrakurikuler"
    return _redirect("Anggota dikeluarkan dari ekstrakurikuler.", target=target)


@router.post("/ekstrakurikuler/anggota/{member_id}")
def perbarui_anggota(
    request: Request,
    member_id: int,
    jabatan: str = Form("Anggota"),
    nilai: str = Form(""),
    predikat: str = Form(""),
    status: str = Form("aktif"),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    row = services.db.query_one("SELECT ekskul_id FROM ekskul_members WHERE id = ?", (member_id,))
    data = {
        "jabatan": jabatan or "Anggota",
        "nilai": float(nilai) if str(nilai).replace(".", "", 1).isdigit() else None,
        "predikat": predikat or None,
        "status": status or "aktif",
    }
    services.update_ekskul_member(member_id, data, actor=user.username)
    target = f"/ekstrakurikuler/{row['ekskul_id']}" if row else "/ekstrakurikuler"
    return _redirect("Data anggota diperbarui.", target=target)


@router.get("/ekstrakurikuler/{ekskul_id}/anggota.csv")
def ekspor_anggota(request: Request, ekskul_id: int, user: auth.SessionUser = Depends(auth.require_staff)):
    ekskul = services.get_ekskul(ekskul_id)
    if ekskul is None:
        return RedirectResponse("/ekstrakurikuler", status_code=303)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["No", "Nama", "NISN", "Rombel", "JK", "Jabatan", "Nilai", "Predikat", "Status", "Tahun Ajaran"])
    for index, member in enumerate(services.ekskul_members(ekskul_id), start=1):
        writer.writerow([
            index, member["nama"], member["nisn"], member["rombel"], member["jk"],
            member["jabatan"], member["nilai"] if member["nilai"] is not None else "",
            member["predikat"] or "", member["status"], member["tahun_ajaran"] or "",
        ])
    nama_berkas = f"anggota-{(ekskul['kode'] or ekskul['id'])}.csv"
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nama_berkas}"'},
    )
