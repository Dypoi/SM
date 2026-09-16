"""Helper rendering template & utilitas tampilan."""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import auth, config, services
from .dapodik import FIELD_BY_KEY, GROUP_LABELS, fields_by_group

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]
HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


# --------------------------------------------------------------------------- #
# Filter tampilan
# --------------------------------------------------------------------------- #
def tanggal_id(value: Any, with_day: bool = False) -> str:
    """'2011-08-22' -> '22 Agustus 2011'."""
    if not value:
        return "-"
    text = str(value)[:10]
    try:
        date = dt.date.fromisoformat(text)
    except ValueError:
        return str(value)
    hasil = f"{date.day} {BULAN_ID[date.month]} {date.year}"
    if with_day:
        hasil = f"{HARI_ID[date.weekday()]}, {hasil}"
    return hasil


def tanggal_waktu(value: Any) -> str:
    if not value:
        return "-"
    text = str(value).replace("T", " ")
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return text
    return f"{moment.day} {BULAN_ID[moment.month]} {moment.year} {moment:%H:%M}"


def angka_id(value: Any) -> str:
    """1234 -> '1.234'."""
    if value is None or value == "":
        return "0"
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,}".replace(",", ".")


def umur(value: Any) -> str:
    if not value:
        return "-"
    try:
        lahir = dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return "-"
    today = dt.date.today()
    years = today.year - lahir.year - ((today.month, today.day) < (lahir.month, lahir.day))
    return f"{years} tahun" if years >= 0 else "-"


def badge_status(value: Any) -> str:
    text = (str(value) if value is not None else "").strip().lower()
    mapping = {
        "aktif": "badge-success",
        "sukses": "badge-success",
        "ya": "badge-success",
        "lulus": "badge-info",
        "sebagian": "badge-warning",
        "draft": "badge-muted",
        "menunggu": "badge-muted",
        "mutasi": "badge-warning",
        "keluar": "badge-danger",
        "gagal": "badge-danger",
        "non-aktif": "badge-muted",
        "tidak": "badge-muted",
    }
    return mapping.get(text, "badge-muted")


# Label untuk kolom yang ada di database namun tidak berasal dari berkas impor.
EXTRA_LABELS = {
    "status": "Status",
    "catatan": "Catatan Internal",
    "is_kip": "Penerima KIP (ya/tidak)",
    "is_kps": "Penerima KPS (ya/tidak)",
    "is_layak_pip": "Layak PIP (ya/tidak)",
    "id": "ID",
    "updated_at": "Terakhir diubah",
    "created_at": "Dibuat",
}


def field_label(key: str) -> str:
    """Nama tampilan sebuah kolom, aman walau kolomnya bukan field impor."""
    spec = FIELD_BY_KEY.get(key)
    if spec is not None:
        return spec.label
    return EXTRA_LABELS.get(key, key.replace("_", " ").title())


def singkat(value: Any, length: int = 40) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= length else text[: length - 1] + "…"


templates.env.globals["field_label"] = field_label
templates.env.globals["GROUP_LABELS"] = GROUP_LABELS


templates.env.filters.update(
    {
        "tanggal_id": tanggal_id,
        "tanggal_waktu": tanggal_waktu,
        "angka_id": angka_id,
        "umur": umur,
        "badge": badge_status,
        "singkat": singkat,
    }
)


# --------------------------------------------------------------------------- #
# Data global untuk semua template
# --------------------------------------------------------------------------- #
def nav_items(user: auth.SessionUser | None) -> list[dict[str, str]]:
    if user is None:
        return []
    if user.role == auth.ROLE_SISWA:
        return [
            {"href": "/portal", "label": "Beranda Saya", "icon": "home"},
            {"href": "/portal/pengajuan", "label": "Ajukan Perubahan", "icon": "edit"},
            {"href": "/portal/profil", "label": "Data Saya", "icon": "user"},
            {"href": "/portal/ekstrakurikuler", "label": "Ekstrakurikuler", "icon": "flag"},
        ]
    items = [
        {"href": "/", "label": "Dasbor", "icon": "home"},
        {"href": "/data-siswa", "label": "Data Siswa", "icon": "users"},
        {"href": "/pengajuan", "label": "Persetujuan Data", "icon": "check",
         "badge": services.hitung_pengajuan("menunggu")},
        {"href": "/impor", "label": "Impor Excel/CSV", "icon": "upload"},
        {"href": "/ekstrakurikuler", "label": "Ekstrakurikuler", "icon": "flag"},
        {"href": "/statistik", "label": "Statistik", "icon": "chart"},
        {"href": "/kualitas-data", "label": "Kualitas Data", "icon": "check"},
        {"href": "/pengaturan", "label": "Pengaturan", "icon": "cog"},
        {"href": "/pembaruan", "label": "Pembaruan", "icon": "refresh"},
    ]
    if user.role != auth.ROLE_ADMIN:
        items = [item for item in items if item["href"] not in {"/pengaturan", "/pembaruan", "/pengajuan"}]
        items.append({"href": "/profil-akun", "label": "Akun Saya", "icon": "user"})
    return items


PAGE_TITLES = {
    "/": "Dasbor",
    "/data-siswa": "Data Siswa",
    "/impor": "Impor Berkas",
    "/ekstrakurikuler": "Ekstrakurikuler",
    "/statistik": "Statistik",
    "/kualitas-data": "Kualitas Data",
    "/pengaturan": "Pengaturan",
    "/pembaruan": "Pembaruan Aplikasi",
    "/pengajuan": "Persetujuan Perubahan Data",
    "/portal/pengajuan": "Ajukan Perubahan Data",
    "/portal": "Beranda Saya",
    "/portal/ekstrakurikuler": "Ekstrakurikuler Saya",
    "/portal/profil": "Perbaiki Data Saya",
    "/login": "Masuk",
}


def render(request: Request, template: str, context: dict[str, Any] | None = None,
           status_code: int = 200):
    """Render template dengan konteks standar (pengguna, profil, notifikasi)."""
    user = auth.current_user(request)
    ctx: dict[str, Any] = {
        "request": request,
        "user": user,
        "profil": services.school_profile(),
        "nav": nav_items(user),
        "app_name": config.APP_NAME,
        "app_long_name": config.APP_LONG_NAME,
        "app_version": config.APP_VERSION,
        "current_path": request.url.path,
        "msg": request.query_params.get("msg", ""),
        "msg_level": request.query_params.get("level", "ok"),
        "page_title": PAGE_TITLES.get(request.url.path, config.APP_NAME),
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(
        request=request, name=template, context=ctx, status_code=status_code
    )


# --------------------------------------------------------------------------- #
# Paginasi
# --------------------------------------------------------------------------- #
def paginate(total: int, page: int, per_page: int) -> dict[str, Any]:
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    page = min(max(1, page), pages)
    start = (page - 1) * per_page + 1 if total else 0
    end = min(page * per_page, total)

    window: list[int | None] = []
    for number in range(1, pages + 1):
        if number <= 2 or number > pages - 2 or abs(number - page) <= 1:
            window.append(number)
        elif window and window[-1] is not None:
            window.append(None)
    return {
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "start": start,
        "end": end,
        "window": window,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def field_groups() -> dict[str, list]:
    return fields_by_group()


def field_spec(key: str):
    return FIELD_BY_KEY.get(key)


def query_string(request: Request, **updates: Any) -> str:
    """Bangun query string dengan nilai yang diubah (untuk tautan filter)."""
    params = dict(request.query_params)
    for key, value in updates.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = str(value)
    if not params:
        return ""
    parts = "&".join(f"{key}={value}" for key, value in params.items() if value not in (None, ""))
    return f"?{parts}" if parts else ""
