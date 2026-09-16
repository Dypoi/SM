"""Dasbor utama."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from .. import auth, db, services
from ..web import render

router = APIRouter()


def _info_pembaruan(user: auth.SessionUser) -> dict | None:
    """Penanda ringan pembaruan di dasbor (tanpa memanggil git)."""
    if not user.is_admin:
        return None
    return {
        "ada": services.get_setting("update_tersedia") == "1",
        "revisi": services.get_setting("update_revisi_remote") or "",
        "pesan": services.get_setting("update_pesan") or "",
        "terakhir": services.get_setting("update_terakhir_cek") or "",
        "ketinggalan": services.get_setting("update_komit_belakang", "0"),
    }


@router.get("/", include_in_schema=False)
def dasbor(request: Request, user: auth.SessionUser = Depends(auth.require_user)):
    if user.role == auth.ROLE_SISWA:
        return RedirectResponse("/portal", status_code=303)

    stats = services.student_stats()
    per_tingkat = services.stats_by_tingkat()
    per_rombel = services.stats_by_rombel()
    quality = services.data_quality()
    ekskul = services.ekskul_stats()

    total_issue = sum(item["jumlah"] for item in quality["temuan"])
    return render(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "per_tingkat": per_tingkat,
            "per_rombel": per_rombel,
            "agama": services.stats_by("agama", limit=6),
            "kecamatan": services.stats_by("kecamatan", limit=6),
            "ekskul": ekskul,
            "ekskul_kategori": services.ekskul_by_kategori(),
            "kualitas": quality,
            "total_temuan": total_issue,
            "pengajuan": services.statistik_pengajuan(),
            "impor_terakhir": services.list_imports(limit=5),
            "pembaruan": _info_pembaruan(user),
            "audit": services.recent_audit(limit=8),
            "jumlah_ekskul": int(db.query_value("SELECT COUNT(*) FROM extracurriculars") or 0),
        },
    )
