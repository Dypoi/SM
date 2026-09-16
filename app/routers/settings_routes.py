"""Pengaturan aplikasi, identitas sekolah, pengguna, dan audit."""

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import auth, config, db, services
from ..security import new_api_key
from ..web import render

router = APIRouter()

PROFIL_KEYS = (
    "school_nama", "school_npsn", "school_alamat", "school_kecamatan",
    "school_kabupaten", "school_provinsi", "school_kepala", "school_email",
    "school_telepon",
)


def _redirect(pesan: str, level: str = "ok", anchor: str = ""):
    return RedirectResponse(f"/pengaturan?level={level}&msg={quote_plus(pesan)}{anchor}", status_code=303)


@router.get("/pengaturan")
def halaman_pengaturan(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    return render(
        request,
        "settings.html",
        {
            "page_title": "Pengaturan",
            "settings": services.get_settings(),
            "pengguna": auth.list_users(),
            "audit": services.recent_audit(limit=60),
            "api_key": services.get_setting("api_key") or "",
            "db_path": str(config.DB_PATH),
            "data_dir": str(config.DATA_DIR),
            "jumlah_impor": int(db.query_value("SELECT COUNT(*) FROM imports") or 0),
            "jumlah_siswa": int(db.query_value("SELECT COUNT(*) FROM students") or 0),
            "jumlah_ekskul": int(db.query_value("SELECT COUNT(*) FROM extracurriculars") or 0),
            "readiness": services.dapodik_readiness(),
        },
    )


@router.post("/pengaturan/sekolah")
async def simpan_sekolah(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    form = await request.form()
    values = {key: str(form.get(key) or "").strip() for key in PROFIL_KEYS}
    services.update_settings(values)
    services.log_audit(user.username, user.role, "ubah_profil_sekolah")
    return _redirect("Identitas sekolah disimpan.", anchor="#sekolah")


@router.post("/pengaturan/preferensi")
async def simpan_preferensi(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    form = await request.form()
    values = {
        "tahun_ajaran": str(form.get("tahun_ajaran") or config.TAHUN_AJARAN_DEFAULT).strip(),
        "semester": str(form.get("semester") or config.SEMESTER_DEFAULT).strip(),
        "login_siswa_pakai_tanggal_lahir": "1" if form.get("login_siswa_pakai_tanggal_lahir") else "0",
        "pengajuan_aktif": "1" if form.get("pengajuan_aktif") else "0",
        "pengajuan_wajib_dokumen": "1" if form.get("pengajuan_wajib_dokumen") else "0",
        "ekskul_aktif": "1" if form.get("ekskul_aktif") else "0",
        "dapodik_sync_aktif": "1" if form.get("dapodik_sync_aktif") else "0",
    }
    try:
        per_page = int(str(form.get("rows_per_page") or config.ROWS_PER_PAGE))
        values["rows_per_page"] = str(min(200, max(10, per_page)))
    except ValueError:
        pass
    services.update_settings(values)
    services.log_audit(user.username, user.role, "ubah_preferensi", detail=", ".join(values))
    return _redirect("Preferensi aplikasi disimpan.", anchor="#preferensi")


@router.post("/pengaturan/pengguna")
def tambah_pengguna(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    nama: str = Form(""),
    role: str = Form("operator"),
    user: auth.SessionUser = Depends(auth.require_admin),
):
    try:
        auth.create_user(username, password, nama, role)
    except ValueError as exc:
        return _redirect(str(exc), level="err", anchor="#pengguna")
    services.log_audit(user.username, user.role, "tambah_pengguna", "users", None, username)
    return _redirect(f"Pengguna {username} dibuat.", anchor="#pengguna")


@router.post("/pengaturan/pengguna/{user_id}")
def ubah_pengguna(
    request: Request,
    user_id: int,
    nama: str = Form(""),
    role: str = Form("operator"),
    password: str = Form(""),
    aktif: str = Form("0"),
    user: auth.SessionUser = Depends(auth.require_admin),
):
    try:
        auth.update_user(
            user_id,
            nama=nama.strip() or None,
            role=role,
            aktif=aktif in {"1", "on", "true"},
            password=password or None,
        )
    except ValueError as exc:
        return _redirect(str(exc), level="err", anchor="#pengguna")
    services.log_audit(user.username, user.role, "ubah_pengguna", "users", user_id)
    return _redirect("Pengguna diperbarui.", anchor="#pengguna")


@router.post("/pengaturan/pengguna/{user_id}/hapus")
def hapus_pengguna(request: Request, user_id: int, user: auth.SessionUser = Depends(auth.require_admin)):
    if user.id == user_id:
        return _redirect("Tidak bisa menghapus akun yang sedang dipakai.", level="err", anchor="#pengguna")
    try:
        auth.delete_user(user_id, actor=user.username)
    except ValueError as exc:
        return _redirect(str(exc), level="err", anchor="#pengguna")
    return _redirect("Pengguna dihapus.", anchor="#pengguna")


@router.post("/pengaturan/api-key")
def putar_api_key(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    import datetime as dt

    key = new_api_key()
    services.update_settings({"api_key": key, "api_key_created_at": dt.datetime.now().isoformat(timespec="seconds")})
    services.log_audit(user.username, user.role, "putar_api_key")
    return _redirect("Kunci API baru dibuat. Perbarui konfigurasi bot Dapodik Anda.", anchor="#integrasi")


@router.get("/pengaturan/dokumentasi-api")
def dokumentasi_api(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    return render(
        request,
        "settings_api.html",
        {
            "page_title": "Dokumentasi API",
            "api_key": services.get_setting("api_key") or "",
            "base_url": str(request.base_url).rstrip("/"),
        },
    )
