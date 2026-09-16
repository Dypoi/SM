"""Portal siswa: siswa login memakai NISN lalu melihat & memperbaiki datanya."""

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from .. import auth, services
from ..dapodik import FIELD_BY_KEY
from ..services import FIELD_PENTING, FIELD_WAJIB
from ..web import render

router = APIRouter()

# Field yang boleh diusulkan perbaikannya sendiri oleh siswa.
FIELD_BOLEH_DIUBAH = ("alamat", "rt", "rw", "dusun", "kelurahan", "kecamatan", "kode_pos",
                      "transportasi", "telepon", "hp", "email", "jenis_tinggal")


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


@router.get("/portal")
def beranda_siswa(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    if user.role != auth.ROLE_SISWA:
        return RedirectResponse("/", status_code=303)

    siswa = _siswa_aktif(user)
    if siswa is None:
        return render(
            request,
            "error.html",
            {"kode": 404, "pesan": "Data siswa tidak ditemukan. Hubungi tata usaha."},
            status_code=404,
        )

    return render(
        request,
        "portal/home.html",
        {
            "page_title": "Beranda Saya",
            "siswa": siswa,
            "kelengkapan": _kelengkapan(siswa),
            "ekskul": services.student_ekskul(siswa["id"]),
            "profil": services.school_profile(),
        },
    )


@router.get("/portal/ekstrakurikuler")
def ekskul_siswa(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    if user.role != auth.ROLE_SISWA:
        return RedirectResponse("/ekstrakurikuler", status_code=303)

    siswa = _siswa_aktif(user)
    if siswa is None:
        return RedirectResponse("/portal", status_code=303)

    return render(
        request,
        "portal/ekskul.html",
        {
            "page_title": "Ekstrakurikuler",
            "siswa": siswa,
            "diikuti": services.student_ekskul(siswa["id"]),
            "tersedia": services.list_ekskul(aktif_only=True),
        },
    )


@router.get("/portal/profil")
def profil_siswa(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    if user.role != auth.ROLE_SISWA:
        return RedirectResponse("/profil-akun", status_code=303)

    siswa = _siswa_aktif(user)
    if siswa is None:
        return RedirectResponse("/portal", status_code=303)

    boleh_ubah = services.get_setting("siswa_boleh_edit_data", "1") == "1"
    return render(
        request,
        "portal/profile.html",
        {
            "page_title": "Perbaiki Data Saya",
            "siswa": siswa,
            "kelengkapan": _kelengkapan(siswa),
            "field_boleh_diubah": [
                ("", "Pilih kolom…"),
                *[(key, FIELD_BY_KEY[key].label) for key in FIELD_BOLEH_DIUBAH if key in FIELD_BY_KEY],
            ],
            "boleh_ubah": boleh_ubah,
        },
    )


@router.post("/portal/profil")
async def ubah_profil_siswa(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    if user.role != auth.ROLE_SISWA:
        return RedirectResponse("/profil-akun", status_code=303)

    if services.get_setting("siswa_boleh_edit_data", "1") != "1":
        return RedirectResponse("/portal/profil?level=err&msg=Perbaikan+data+oleh+siswa+dinonaktifkan", status_code=303)

    siswa = _siswa_aktif(user)
    if siswa is None:
        return RedirectResponse("/portal", status_code=303)

    form = await request.form()
    perubahan: dict[str, str] = {}
    for key in FIELD_BOLEH_DIUBAH:
        if key not in form:
            continue
        nilai_baru = str(form.get(key) or "").strip()
        nilai_lama = str(siswa.get(key) or "").strip()
        if nilai_baru != nilai_lama:
            perubahan[key] = nilai_baru

    if not perubahan:
        return RedirectResponse("/portal/profil?level=info&msg=Tidak+ada+perubahan+data", status_code=303)

    services.update_student(
        siswa["id"], perubahan, actor=f"siswa:{user.nisn}", source="portal_siswa"
    )
    pesan = f"{len(perubahan)} kolom data dikirim dan langsung tercatat pada riwayat perubahan."
    return RedirectResponse(f"/portal/profil?level=ok&msg={quote_plus(pesan)}", status_code=303)
