"""Halaman «Online» — menyalakan akses internet (Tailscale Funnel) dengan satu tombol.

Petugas di PC sekolah cukup menekan **satu tombol** di aplikasi; perintah
``tailscale funnel`` dijalankan di belakang layar (tanpa jendela Command Prompt),
lalu alamat publiknya ditampilkan di halaman ini supaya bisa dibuka dari HP.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import auth, online, services
from ..web import render

router = APIRouter()

ANCHOR = "#online"


def _redirect(pesan: str, level: str = "ok", anchor: str = "") -> RedirectResponse:
    return RedirectResponse(f"/online?level={level}&msg={quote_plus(pesan)}{anchor}",
                            status_code=303)


def _port_lokal(request: Request) -> int:
    """Port aplikasi yang sedang dipakai — diambil dari alamat yang dibuka petugas."""
    try:
        port = request.url.port
    except (TypeError, ValueError):
        port = None
    return int(port) if port else 8000


def _konteks(request: Request, terowongan: dict | None = None) -> dict:
    terowongan = terowongan if terowongan is not None else online.status_terowongan()
    port_lokal = _port_lokal(request)
    port_funnel = int(terowongan.get("port") or 0)
    return {
        "page_title": "Online",
        "terowongan": terowongan,
        "peringatan_port": ("Funnel ini diarahkan ke port aplikasi lain "
                            f"(port {port_funnel}, aplikasi di {port_lokal}). Matikan lalu "
                            "nyalakan ulang lewat tombol di halaman ini."
                            if port_funnel and port_funnel != port_lokal else ""),
        "pekerjaan": online.status_pekerjaan(),
        "penanda": online.baca_status(),
        "port_lokal": port_lokal,
        "port_publik": 443,
        "menit_tunggu": max(1, online.TUNGGU_FUNNEL * online.RONDE_TUNGGU // 60),
    }


@router.get("/online")
def halaman_online(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    return render(request, "online.html", _konteks(request))


@router.get("/online/status.json")
def status_online(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    """Kemajuan tombol Online (dipantau halaman tiap 2 detik) — tanpa perintah Tailscale."""
    penanda = online.baca_status()
    return JSONResponse({
        "pekerjaan": online.status_pekerjaan(),
        "alamat_tercatat": str(penanda.get("alamat") or ""),
        "aktif": bool(penanda.get("aktif")),
    })


@router.post("/online/nyalakan")
def nyalakan_online(
    request: Request,
    user: auth.SessionUser = Depends(auth.require_admin),
    port: str = Form(""),
    https_port: str = Form(""),
):
    """Tombol «Nyalakan online»: jalankan Tailscale Funnel di belakang layar."""
    port_lokal = int(port) if port.strip().isdigit() else _port_lokal(request)
    publik = int(https_port) if https_port.strip().isdigit() else 443
    if publik not in online.PORT_FUNNEL:
        return _redirect(f"Port publik {publik} tidak diizinkan Tailscale Funnel "
                         f"(pilihan: {', '.join(map(str, online.PORT_FUNNEL))}).", "err", ANCHOR)
    if not online.tailscale_jalur():
        return _redirect("Tailscale belum terpasang di komputer ini — pasang dulu dari "
                         "tailscale.com/download, lalu tekan tombolnya lagi.", "err", ANCHOR)
    keadaan = online.mulai_nyalakan(port_lokal, publik)
    services.log_audit(user.username, user.role, "nyalakan_online", "aplikasi", None,
                       f"port={port_lokal} publik={publik}")
    if keadaan.get("jalan"):
        return _redirect("Meminta Tailscale Funnel menyala — alamat publiknya muncul di "
                         "halaman ini begitu siap.", "info", ANCHOR)
    return _redirect(keadaan.get("pesan") or "Permintaan online tidak bisa dijalankan.",
                     "err", ANCHOR)


@router.post("/online/matikan")
def matikan_online(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    """Tombol «Matikan online»: hentikan akses publik, aplikasi lokal tetap jalan."""
    hasil = online.matikan_terowongan()
    services.log_audit(user.username, user.role, "matikan_online", "aplikasi", None,
                       "berhasil" if hasil.get("berhasil") else str(hasil.get("pesan"))[:120])
    return _redirect(str(hasil.get("pesan") or ""), "ok" if hasil.get("berhasil") else "err",
                     ANCHOR)
