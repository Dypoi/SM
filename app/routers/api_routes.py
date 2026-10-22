"""API JSON untuk integrasi otomatis (persiapan bot Dapodik).

Autentikasi memakai header ``X-API-Key`` yang nilainya diambil dari halaman
Pengaturan -> Integrasi. Endpoint baca juga bisa dipakai tanpa kunci bila
``SM_API_PUBLIC=1`` (default 0/tertutup).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from .. import config, db, services
from ..dapodik import FIELD_BY_KEY

router = APIRouter(prefix="/api", tags=["API"])

API_PUBLIC = os.getenv("SM_API_PUBLIC", "0") == "1"


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = services.get_setting("api_key") or ""
    if x_api_key and expected and x_api_key == expected:
        return
    if API_PUBLIC:
        return
    raise HTTPException(status_code=401, detail="X-API-Key tidak valid atau belum diisi.")


@router.get("/health")
def api_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "siswa": int(db.query_value("SELECT COUNT(*) FROM students") or 0),
    }


@router.get("/sekolah", dependencies=[Depends(require_api_key)])
def api_sekolah() -> dict[str, Any]:
    return services.school_profile()


@router.get("/statistik", dependencies=[Depends(require_api_key)])
def api_statistik() -> dict[str, Any]:
    return {
        "ringkasan": services.student_stats(),
        "per_tingkat": services.stats_by_tingkat(),
        "per_rombel": services.stats_by_rombel(),
        "ekstrakurikuler": services.ekskul_stats(),
    }


@router.get("/siswa", dependencies=[Depends(require_api_key)])
def api_daftar_siswa(
    q: str = Query("", description="Cari nama/NISN/NIPD/NIK"),
    rombel: str = "",
    tingkat: str = "",
    jk: str = "",
    status: str = "",
    page: int = 1,
    per_page: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    filters = services.StudentFilter(q=q, rombel=rombel, tingkat=tingkat, jk=jk, status=status)
    rows, total = services.list_students(filters, page=page, per_page=per_page)
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "data": rows,
    }


@router.get("/siswa/{nisn}", dependencies=[Depends(require_api_key)])
def api_detail_siswa(nisn: str) -> dict[str, Any]:
    siswa = services.get_student_by_nisn(nisn)
    if siswa is None:
        raise HTTPException(status_code=404, detail=f"Siswa dengan NISN {nisn} tidak ditemukan.")
    siswa["ekstrakurikuler"] = services.student_ekskul(siswa["id"])
    return siswa


@router.patch("/siswa/{nisn}", dependencies=[Depends(require_api_key)])
async def api_ubah_siswa(nisn: str, request: Request) -> dict[str, Any]:
    """Ubah sebagian data siswa (dipakai bot Dapodik setelah validasi).

    Body JSON: ``{"nik": "...", "no_kk": "...", "catatan": "..."}``
    """
    siswa = services.get_student_by_nisn(nisn)
    if siswa is None:
        raise HTTPException(status_code=404, detail=f"Siswa dengan NISN {nisn} tidak ditemukan.")

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body harus berupa objek JSON.")

    actor = payload.pop("_actor", "api-bot")
    unknown = [key for key in payload if key not in services.STUDENT_WRITABLE]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Kolom tidak dikenal: {', '.join(unknown)}")

    changes = services.update_student(siswa["id"], payload, actor=actor, source="api_bot")
    return {
        "nisn": nisn,
        "perubahan": [{"field": field, "lama": old, "baru": new} for field, old, new in changes],
        "jumlah": len(changes),
    }


@router.get("/kualitas-data", dependencies=[Depends(require_api_key)])
def api_kualitas() -> dict[str, Any]:
    quality = services.data_quality()
    return {
        "total": quality["total"],
        "siap_sinkron": quality["siap_sinkron"],
        "belum_lengkap": quality["belum_lengkap"],
        "temuan": quality["temuan"],
    }


@router.get("/field", dependencies=[Depends(require_api_key)])
def api_daftar_field() -> dict[str, Any]:
    """Daftar field yang bisa ditulis melalui API (kontrak untuk bot Dapodik)."""
    return {
        "field": [
            {
                "key": spec.key,
                "label": spec.label,
                "grup": spec.group,
                "tipe": spec.kind,
                "wajib": spec.required,
            }
            for spec in FIELD_BY_KEY.values()
        ]
    }


@router.get("/ekskul", dependencies=[Depends(require_api_key)])
def api_ekskul() -> dict[str, Any]:
    return {"data": services.list_ekskul(), "statistik": services.ekskul_stats()}


@router.post("/impor", dependencies=[Depends(require_api_key)])
async def api_impor(
    berkas: UploadFile = File(...),
    mode: str = Query("upsert", pattern="^(insert|upsert|replace|dry)$"),
    dry_run: bool = Query(False, description="Hanya validasi, tidak menulis ke database"),
) -> JSONResponse:
    """Impor berkas Excel/CSV secara otomatis (tanpa interaksi UI)."""
    content = await berkas.read()
    if not content:
        raise HTTPException(status_code=400, detail="Berkas kosong.")

    stored = services.save_upload(berkas.filename or "unggahan.csv", content)
    try:
        sheet, parsed, fmt = services.read_and_parse(stored.path, stored.extension)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Gagal membaca berkas: {exc}") from exc

    import_id = services.create_import(
        stored, sheet=sheet, parsed=parsed, fmt=fmt, actor="api-bot", mode=mode
    )
    if dry_run:
        return JSONResponse(
            {
                "import_id": import_id,
                "mode": "dry-run",
                "terdeteksi": parsed.kind,
                "baris": len(parsed.records),
                "kolom_terpetakan": parsed.mapped_field_count,
                "ringkasan_masalah": {
                    "error": len(parsed.issues_for("error")),
                    "peringatan": len(parsed.issues_for("warning")),
                },
            }
        )

    hasil = services.import_students(
        parsed, import_id=import_id, mode=mode, actor="api-bot",
        source_file=berkas.filename, only_valid=True,
    )
    return JSONResponse(
        {
            "import_id": import_id,
            "dibuat": hasil.imported,
            "diperbarui": hasil.updated,
            "dilewati": hasil.skipped,
            "gagal": hasil.failed,
            "total": hasil.total,
        }
    )


@router.get("/audit", dependencies=[Depends(require_api_key)])
def api_audit(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    return {"data": services.recent_audit(limit)}


@router.get("/perubahan", dependencies=[Depends(require_api_key)])
def api_perubahan(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    """Riwayat perubahan data — bahan rekonsiliasi bot Dapodik."""
    rows = db.query_all(
        """
        SELECT c.*, s.nama AS siswa_nama, s.rombel
          FROM data_changes c LEFT JOIN students s ON s.id = c.student_id
         ORDER BY c.id DESC LIMIT ?
        """,
        (limit,),
    )
    return {"data": db.rows_to_dicts(rows)}
