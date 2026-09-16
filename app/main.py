"""Entry point aplikasi SIMSEK (FastAPI).

Jalankan dengan::

    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

atau sederhananya::

    python run.py
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db, migrations, services, updater
from .routers import (
    api_routes,
    approval_routes,
    auth_routes,
    dashboard_routes,
    ekskul_routes,
    import_routes,
    portal_routes,
    settings_routes,
    student_routes,
    update_routes,
)
from .web import render

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("simsek")


async def _pemantau_latar() -> None:
    """Pemantau latar belakang: cek pembaruan berkala & muat ulang bila diminta."""
    await asyncio.sleep(4)  # beri waktu startup server selesai lebih dulu
    siklus_berikut = 0.0
    while True:
        if updater.perlu_muat_ulang():
            log.info("Permintaan muat ulang diterima — memuat ulang server dengan kode terbaru.")
            updater.muat_ulang_sekarang()  # proses diganti, tidak kembali ke sini
        if time.time() >= siklus_berikut:
            siklus_berikut = time.time() + updater.interval_detik()
            hasil = await asyncio.to_thread(updater.otomatis_periksa)
            if hasil.get("ada_pembaruan"):
                log.info("Pembaruan tersedia di GitHub: %s", hasil)
        await asyncio.sleep(updater.SELANG_PANTAU)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    migrations.init_database(verbose=True)
    seed = services.auto_seed_sample()
    if seed:
        log.info("Data awal dimuat dari %s (%s siswa)", seed["file"], seed["imported"])
    updater.bersihkan_marker_lama()
    tugas_pemantau = asyncio.create_task(_pemantau_latar())
    log.info("%s siap dijalankan. Database: %s", config.APP_NAME, config.DB_PATH)
    yield
    tugas_pemantau.cancel()
    with suppress(asyncio.CancelledError):
        await tugas_pemantau
    db.close_connection()


app = FastAPI(
    title=f"{config.APP_NAME} — {config.APP_LONG_NAME}",
    description=(
        "Sistem manajemen sekolah ringan: impor Excel/CSV multi-format, data peserta didik, "
        "ekstrakurikuler, portal siswa, dan kesiapan integrasi bot Dapodik."
    ),
    version=config.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

app.include_router(auth_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(student_routes.router)
app.include_router(import_routes.router)
app.include_router(ekskul_routes.router)
app.include_router(portal_routes.router)
app.include_router(settings_routes.router)
app.include_router(update_routes.router)
app.include_router(approval_routes.router)
app.include_router(api_routes.router)


# --------------------------------------------------------------------------- #
# Health check & error handler
# --------------------------------------------------------------------------- #
@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok", "app": config.APP_NAME, "version": config.APP_VERSION}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Alihkan ke halaman login/notifikasi yang ramah, bukan JSON mentah."""
    if exc.status_code == 303 and exc.headers and exc.headers.get("Location"):
        return RedirectResponse(exc.headers["Location"], status_code=303)

    if exc.status_code == 401:
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

    if exc.status_code == 404:
        if request.url.path.startswith("/api/"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": exc.detail or "Tidak ditemukan"}, status_code=404)
        return render(
            request,
            "error.html",
            {"kode": 404, "pesan": "Halaman yang Anda cari tidak ditemukan."},
            status_code=404,
        )

    if exc.status_code == 403:
        return render(
            request,
            "error.html",
            {"kode": 403, "pesan": exc.detail or "Anda tidak berhak mengakses halaman ini."},
            status_code=403,
        )

    return render(request, "error.html", {"kode": exc.status_code, "pesan": str(exc.detail)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    log.exception("Kesalahan tak terduga pada %s", request.url.path)
    return render(
        request,
        "error.html",
        {
            "kode": 500,
            "pesan": "Terjadi kesalahan pada server.",
            "detail": f"{type(exc).__name__}: {exc}",
        },
        status_code=500,
    )
