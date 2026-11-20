"""Alur impor berkas Excel/CSV: unggah -> pratinjau -> jalankan -> laporan."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import auth, config, db, services
from ..dapodik import FIELD_BY_KEY, fields_by_group
from ..readers import (
    SpreadsheetError,
    UnsupportedFormatError,
    format_label,
    read_spreadsheet,
    supported_extensions,
)
from ..web import render

router = APIRouter()


@router.get("/impor")
def halaman_impor(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    contoh = [path.name for path in services.find_sample_files()]
    return render(
        request,
        "import/list.html",
        {
            "page_title": "Impor Berkas",
            "riwayat": services.list_imports(limit=50),
            "format_didukung": [
                (ext, format_label(ext)) for ext in supported_extensions()
            ],
            "maks_ukuran": config.MAX_UPLOAD_MB,
            "contoh_berkas": contoh,
            "stats": services.student_stats(),
        },
    )


@router.get("/impor/panduan")
def panduan_impor(request: Request, user: auth.SessionUser = Depends(auth.require_staff)):
    return render(
        request,
        "import/guide.html",
        {
            "page_title": "Panduan Impor",
            "format_didukung": [(ext, format_label(ext)) for ext in supported_extensions()],
            "grup_field": fields_by_group(),
        },
    )


@router.post("/impor/unggah")
async def unggah_berkas(
    request: Request,
    berkas: UploadFile = File(...),
    sheet_index: int = Form(0),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    nama = berkas.filename or "unggahan.csv"
    isi = await berkas.read()

    if not isi:
        return RedirectResponse("/impor?level=err&msg=Berkas+kosong+atau+gagal+dibaca", status_code=303)
    if len(isi) > config.MAX_UPLOAD_BYTES:
        pesan = f"Ukuran berkas melebihi {config.MAX_UPLOAD_MB} MB."
        return RedirectResponse(f"/impor?level=err&msg={quote_plus(pesan)}", status_code=303)

    try:
        stored = services.save_upload(nama, isi)
        sheets = read_spreadsheet(stored.path, stored.extension)
    except UnsupportedFormatError as exc:
        return RedirectResponse(f"/impor?level=err&msg={quote_plus(str(exc))}", status_code=303)
    except SpreadsheetError as exc:
        return RedirectResponse(f"/impor?level=err&msg={quote_plus(str(exc))}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/impor?level=err&msg={quote_plus(f'Gagal membaca berkas: {exc}')}", status_code=303)

    sheet = sheets[min(max(0, sheet_index), len(sheets) - 1)]
    from ..dapodik import parse_sheet

    parsed = parse_sheet(sheet)
    fmt = format_label(stored.extension)
    import_id = services.create_import(
        stored, sheet=sheet, parsed=parsed, fmt=fmt, actor=user.username, mode="upsert"
    )
    sheet_info = f"{len(sheets)} worksheet: " + ", ".join(f"{s.name} ({len(s.rows)} baris)" for s in sheets[:6])
    db.execute("UPDATE imports SET message = ? WHERE id = ?", (sheet_info, import_id))
    return RedirectResponse(f"/impor/{import_id}", status_code=303)


def _load_parsed(import_row: dict):
    """Baca ulang berkas impor dan uraikan isinya dengan pemetaan tersimpan."""
    path = Path(import_row.get("stored_path") or "")
    if not path.exists():
        raise SpreadsheetError("Berkas sumber sudah tidak ada di folder data/uploads.")
    sheets = read_spreadsheet(path, path.suffix.lower())
    target = import_row.get("sheet_name")
    sheet = next((s for s in sheets if s.name == target), sheets[0])

    from ..dapodik import parse_sheet

    return sheet, parse_sheet(sheet)


@router.get("/impor/{import_id}")
def detail_impor(request: Request, import_id: int, user: auth.SessionUser = Depends(auth.require_staff)):
    record = services.get_import(import_id)
    if record is None:
        return render(request, "error.html", {"kode": 404, "pesan": "Riwayat impor tidak ditemukan."}, status_code=404)

    error_baca = None
    sheet = parsed = None
    try:
        sheet, parsed = _load_parsed(record)
    except (SpreadsheetError, UnsupportedFormatError) as exc:
        error_baca = str(exc)

    preview: list[dict] = []
    if parsed is not None:
        head = parsed.records[:config.PREVIEW_ROWS]
        for record_row in head:
            preview.append(
                {
                    "row_number": record_row.row_number,
                    "nama": record_row.values.get("nama") or "-",
                    "nisn": record_row.values.get("nisn") or "",
                    "rombel": record_row.values.get("rombel") or "",
                    "jk": record_row.values.get("jk") or "",
                    "tanggal_lahir": record_row.values.get("tanggal_lahir") or "",
                    "jumlah_field": len(record_row.values),
                    "error": record_row.has_error,
                }
            )

    return render(
        request,
        "import/detail.html",
        {
            "page_title": f"Impor #{import_id}",
            "impor": record,
            "sheet": sheet,
            "parsed": parsed,
            "preview": preview,
            "issue_ringkas": services.count_import_issues(import_id),
            "issues": services.import_issues(import_id, limit=200),
            "error_baca": error_baca,
            "map_json": json.loads(record.get("mapping_json") or "{}"),
            "meta_json": json.loads(record.get("meta_json") or "{}"),
            "field_by_key": FIELD_BY_KEY,
            "kolom_dihapus": parsed.ignored_columns if parsed is not None else [],
            "jumlah_siswa_db": int(db.query_value("SELECT COUNT(*) FROM students") or 0),
        },
    )


@router.post("/impor/{import_id}/jalankan")
def jalankan_impor(
    request: Request,
    import_id: int,
    mode: str = Form("upsert"),
    only_valid: str = Form("1"),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    record = services.get_import(import_id)
    if record is None:
        return RedirectResponse("/impor?level=err&msg=Riwayat+impor+tidak+ditemukan", status_code=303)

    try:
        sheet, parsed = _load_parsed(record)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/impor/{import_id}?level=err&msg={quote_plus(str(exc))}", status_code=303)

    hasil = services.import_students(
        parsed,
        import_id=import_id,
        mode=mode,
        actor=user.username,
        source_file=record.get("filename"),
        only_valid=only_valid == "1",
    )
    pesan = (
        f"{hasil.imported} siswa baru, {hasil.updated} diperbarui, "
        f"{hasil.skipped} dilewati, {hasil.failed} gagal."
    )
    level = "ok" if hasil.imported or hasil.updated else "warn"
    return RedirectResponse(f"/impor/{import_id}?level={level}&msg={quote_plus(pesan)}", status_code=303)


@router.post("/impor/{import_id}/hapus")
def hapus_impor(request: Request, import_id: int, user: auth.SessionUser = Depends(auth.require_admin)):
    services.delete_import(import_id)
    services.log_audit(user.username, user.role, "hapus_impor", "imports", import_id)
    return RedirectResponse("/impor?level=ok&msg=Riwayat+impor+dihapus", status_code=303)


@router.get("/impor/{import_id}/laporan.csv")
def laporan_impor(request: Request, import_id: int, user: auth.SessionUser = Depends(auth.require_staff)):
    record = services.get_import(import_id)
    if record is None:
        return RedirectResponse("/impor", status_code=303)
    issues = services.import_issues(import_id, limit=5000)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Baris", "Level", "Field", "Pesan"])
    for issue in issues:
        writer.writerow([issue["row_number"] or "", issue["level"], issue["field"] or "", issue["message"]])
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="laporan-impor-{import_id}.csv"'},
    )
