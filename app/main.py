"""Entry point aplikasi SM (FastAPI).

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
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, config, db, migrations, online, services, updater
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
log = logging.getLogger("sm")


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

# --------------------------------------------------------------------------- #
# Pengaman permintaan (menyala otomatis bila ada pengunjung dari internet)
# --------------------------------------------------------------------------- #
METODE_AMAN = {"GET", "HEAD", "OPTIONS"}
CSP_DASAR = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
)
DOKUMENTASI_API = {"/api/docs", "/api/openapi.json", "/api/redoc"}


def _host_asal(request: Request) -> str:
    return (urlparse(request.headers.get("origin") or "").netloc or "").lower()


@app.middleware("http")
async def pengaman_permintaan(request: Request, call_next):
    """Pengaman tambahan saat aplikasi terjangkau dari internet.

    * menolak permintaan tulis yang berasal dari situs lain (penjaga CSRF),
    * menyembunyikan dokumentasi API di balik login,
    * memasang header keamanan + CSP, serta HSTS bila lewat HTTPS,
    * menandai aplikasi sebagai "online" bila ada akses dari alamat IP publik.
    """
    ip = request.client.host if request.client else None
    publik = online.dari_luar(ip)
    if not online.ip_privat(ip):
        online.tandai_akses_luar(ip)

    if publik and request.method not in METODE_AMAN:
        asal = _host_asal(request)
        tujuan = (request.headers.get("host") or "").lower()
        if asal and tujuan and asal != tujuan:
            services.log_audit(None, None, "tolak_asal_luar", "http", request.url.path, asal, ip)
            return render(
                request,
                "error.html",
                {"kode": 403, "pesan": "Permintaan dari situs lain ditolak demi keamanan data."},
                status_code=403,
            )

    if publik and request.url.path in DOKUMENTASI_API and auth.current_user(request) is None:
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)

    respons = await call_next(request)
    kepala = respons.headers
    kepala.setdefault("X-Content-Type-Options", "nosniff")
    kepala.setdefault("X-Frame-Options", "DENY")
    kepala.setdefault("Referrer-Policy", "same-origin")
    kepala.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if publik or request.url.scheme == "https":
        kepala.setdefault("Content-Security-Policy", CSP_DASAR)
    if request.url.scheme == "https":
        kepala.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path in {"/login", "/portal"} or request.url.path.startswith("/portal/"):
        kepala["Cache-Control"] = "no-store"
    return respons

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


@app.exception_handler(RequestValidationError)
async def validasi_request_handler(request: Request, exc: RequestValidationError) -> Response:
    """Parameter alamat yang tidak sah memakai halaman galat ramah, bukan JSON mentah."""
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Parameter permintaan tidak sah."}, status_code=400)

    rincian = "; ".join(
        f"{'.'.join(str(bagian) for bagian in item.get('loc', []))}: {item.get('msg', '')}"
        for item in exc.errors()[:3]
    )
    return render(
        request,
        "error.html",
        {
            "kode": 400,
            "pesan": "Permintaan tidak dapat diproses.",
            "detail": rincian or None,
        },
        status_code=400,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Alihkan ke halaman login/notifikasi yang ramah, bukan JSON mentah."""
    if exc.status_code == 303 and exc.headers and exc.headers.get("Location"):
        return RedirectResponse(exc.headers["Location"], status_code=303)

    if exc.status_code == 401:
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

    if exc.status_code == 404:
        # Permintaan bawaan peramban (favicon/robots) tidak perlu halaman galat;
        # ikon aplikasi sudah tertanam sebagai data URI di setiap template.
        if request.url.path in {"/favicon.ico", "/robots.txt"}:
            return Response(status_code=204)

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
