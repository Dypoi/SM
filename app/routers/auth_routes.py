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


def _pesan_tunggu(sisa: int) -> str:
    menit = max(1, (sisa + 59) // 60)
    return (f"Terlalu banyak percobaan masuk dari perangkat ini. Coba lagi dalam {menit} menit, "
            "atau minta bantuan petugas sekolah.")


def _halaman_login(request: Request, *, pesan_error: str, mode: str, next: str,
                   nisn: str = "", username: str = "", status: int = 400):
    return render(
        request,
        "login.html",
        {
            "pesan_error": pesan_error,
            "next": next,
            "pakai_tanggal_lahir": auth.student_requires_birthdate(),
            "form_mode": mode,
            "form_nisn": nisn,
            "form_username": username,
        },
        status_code=status,
    )


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
            # /login?mode=siswa membuka langsung tab siswa.
            "form_mode": request.query_params.get("mode", ""),
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
    identitas = (nisn or "").strip() if mode == "siswa" else (username or "").strip().lower()

    # Pengaman 1: penangguhan sementara setelah percobaan gagal berulang.
    sisa = auth.tunggu_sebelum_login(mode, identitas, ip)
    if sisa > 0:
        services.log_audit(identitas or None, mode, "login_ditangguhkan", None, None,
                           f"percobaan berlebih; ditahan {sisa} detik", ip)
        respons = _halaman_login(request, pesan_error=_pesan_tunggu(sisa), mode=mode, next=next,
                                 nisn=nisn, username=username, status=429)
        respons.headers["Retry-After"] = str(sisa)
        return respons

    if mode == "siswa":
        nisn_bersih = (nisn or "").strip()
        if not nisn_bersih and username:
            # Toleransi: pengguna mengetik NISN di kolom username.
            nisn_bersih = username.strip()
        identitas = nisn_bersih
        student = services.get_student_by_nisn(nisn_bersih) if nisn_bersih else None

        if student is not None and auth.student_requires_birthdate():
            if not auth.verify_student_birthdate(student, tanggal_lahir):
                auth.catat_login_gagal(mode, identitas, ip)
                services.log_audit(nisn_bersih, "siswa", "login_siswa_gagal", "students",
                                   student["id"], "tanggal lahir tidak cocok", ip)
                return _halaman_login(
                    request,
                    pesan_error="Tanggal lahir tidak cocok dengan data sekolah.",
                    mode="siswa", next=next, nisn=nisn_bersih,
                )

        user, error = auth.authenticate_student(nisn_bersih)
        if user is None:
            auth.catat_login_gagal(mode, identitas, ip)
            services.log_audit(nisn_bersih, "siswa", "login_siswa_gagal", None, None, error, ip)
            return _halaman_login(request, pesan_error=error, mode="siswa", next=next, nisn=nisn_bersih)
        auth.catat_login_berhasil(mode, identitas, ip)
        response = RedirectResponse(tujuan or "/portal", status_code=303)
        auth.start_session(response, user, request)
        return response

    user, error = auth.authenticate_staff(username, password)
    if user is None:
        auth.catat_login_gagal(mode, identitas, ip)
        services.log_audit(username, None, "login_staff_gagal", None, None, error, ip)
        return _halaman_login(request, pesan_error=error, mode="staff", next=next, username=username)
    auth.catat_login_berhasil(mode, identitas, ip)
    response = RedirectResponse(tujuan or ("/portal" if user.role == auth.ROLE_SISWA else "/"),
                                status_code=303)
    auth.start_session(response, user, request)
    return response


@router.post("/logout", include_in_schema=False)
def proses_logout(request: Request):
    user = auth.current_user(request)
    siswa = bool(user and user.role == auth.ROLE_SISWA)
    if user:
        services.log_audit(user.username, user.role, "logout")
    # Siswa dikembalikan ke tab siswa, petugas ke tab admin/guru.
    tujuan = "/login?keluar=1&mode=siswa" if siswa else "/login?keluar=1"
    response = RedirectResponse(tujuan, status_code=303)
    auth.end_session(response)
    return response


@router.get("/logout", include_in_schema=False)
def logout_get(request: Request):
    return proses_logout(request)
