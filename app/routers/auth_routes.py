"""Halaman masuk & keluar."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import auth, services
from ..web import render

router = APIRouter()


def _safe_next(target: str | None) -> str:
    """Cegah open-redirect: hanya izinkan path internal."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return ""
    return target


@router.get("/login", include_in_schema=False)
def halaman_login(request: Request):
    user = auth.current_user(request)
    if user is not None:
        return RedirectResponse("/portal" if user.role == auth.ROLE_SISWA else "/", status_code=303)
    return render(
        request,
        "login.html",
        {
            "next": request.query_params.get("next", ""),
            "keluar": request.query_params.get("keluar") == "1",
            "pakai_tanggal_lahir": auth.student_requires_birthdate(),
        },
    )


@router.post("/login", include_in_schema=False)
def proses_login(
    request: Request,
    mode: str = Form("staff"),
    username: str = Form(""),
    password: str = Form(""),
    nisn: str = Form(""),
    tanggal_lahir: str = Form(""),
    next: str = Form(""),
):
    ip = request.client.host if request.client else None
    tujuan = _safe_next(next)

    if mode == "siswa":
        nisn_bersih = (nisn or "").strip()
        if not nisn_bersih and username:
            # Toleransi: pengguna mengetik NISN di kolom username.
            nisn_bersih = username.strip()
        student = services.get_student_by_nisn(nisn_bersih) if nisn_bersih else None

        if student is not None and auth.student_requires_birthdate():
            if not auth.verify_student_birthdate(student, tanggal_lahir):
                services.log_audit(nisn_bersih, "siswa", "login_siswa_gagal", "students",
                                   student["id"], "tanggal lahir tidak cocok", ip)
                return render(
                    request,
                    "login.html",
                    {
                        "pesan_error": "Tanggal lahir tidak cocok dengan data sekolah.",
                        "next": next,
                        "pakai_tanggal_lahir": True,
                        "form_mode": "siswa",
                        "form_nisn": nisn_bersih,
                    },
                    status_code=400,
                )

        user, error = auth.authenticate_student(nisn_bersih)
        if user is None:
            services.log_audit(nisn_bersih, "siswa", "login_siswa_gagal", None, None, error, ip)
            return render(
                request,
                "login.html",
                {
                    "pesan_error": error,
                    "next": next,
                    "pakai_tanggal_lahir": auth.student_requires_birthdate(),
                    "form_mode": "siswa",
                    "form_nisn": nisn_bersih,
                },
                status_code=400,
            )
        response = RedirectResponse(tujuan or "/portal", status_code=303)
        auth.start_session(response, user)
        return response

    user, error = auth.authenticate_staff(username, password)
    if user is None:
        services.log_audit(username, None, "login_staff_gagal", None, None, error, ip)
        return render(
            request,
            "login.html",
            {
                "pesan_error": error,
                "next": next,
                "pakai_tanggal_lahir": auth.student_requires_birthdate(),
                "form_mode": "staff",
                "form_username": username,
            },
            status_code=400,
        )
    response = RedirectResponse(tujuan or ("/portal" if user.role == auth.ROLE_SISWA else "/"), status_code=303)
    auth.start_session(response, user)
    return response


@router.post("/logout", include_in_schema=False)
def proses_logout(request: Request):
    user = auth.current_user(request)
    if user:
        services.log_audit(user.username, user.role, "logout")
    response = RedirectResponse("/login?keluar=1", status_code=303)
    auth.end_session(response)
    return response


@router.get("/logout", include_in_schema=False)
def logout_get(request: Request):
    return proses_logout(request)
