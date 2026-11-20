"""Rute halaman & API **WhatsApp (WA)** — pairing, status, uji, kirim keluar.

Jembatan WhatsApp menjalankan subprocess Node (Baileys) yang hanya relay pesan
ke ``/ollama/chat``. Halaman ini untuk admin mengaktifkan, memasang (scan QR),
dan menguji jembatan.
"""

from __future__ import annotations

import asyncio
import base64

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import auth, services, wa_bridge
from ..web import render

router = APIRouter()


def _kembali(pesan: str, level: str = "ok", anchor: str = "") -> RedirectResponse:
    return RedirectResponse(
        f"/wa?level={level}&msg={quote_plus(pesan)}{'#' + anchor if anchor else ''}",
        status_code=303)


@router.get("/wa")
def halaman_wa(request: Request,
               user: auth.SessionUser = Depends(auth.require_admin)):
    """Halaman «WhatsApp»: aktivasi, pasangan (QR), status, dan uji jembatan."""
    return render(
        request,
        "wa.html",
        {
            "page_title": "WhatsApp",
            "cfg": {
                "wa_aktif": services.get_setting(wa_bridge.KUNCI_AKTIF) or "0",
                "wa_port": services.get_setting(wa_bridge.KUNCI_PORT) or str(wa_bridge.DEFAULT_PORT),
            },
            "status": wa_bridge.status_cepat(),
        },
    )


@router.post("/wa/pengaturan")
def simpan_pengaturan(
    aktif: str = Form(""),
    port: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_admin),
):
    """Simpan pengaturan jembatan WhatsApp, lalu mulai/hentikan bridge."""
    berubah = services.update_settings({
        wa_bridge.KUNCI_AKTIF: "1" if aktif else "0",
        wa_bridge.KUNCI_PORT: (port or str(wa_bridge.DEFAULT_PORT)),
    })
    port_baru = wa_bridge.portawal()
    jika_aktif = str(services.get_setting(wa_bridge.KUNCI_AKTIF)) == "1"
    if jika_aktif:
        wa_bridge.hentikan()
        hasil = wa_bridge.mulai(port=port_baru)
        pesan = "Pengaturan WhatsApp disimpan. " + str(hasil.get("pesan") or "")
        level = "ok" if hasil.get("ok") else "warn"
    else:
        wa_bridge.hentikan()
        pesan = "Pengaturan WhatsApp disimpan — jembatan dimatikan."
        level = "ok"
    if berubah:
        pesan += f" ({len(berubah)} kolom berubah.)"
    return _kembali(pesan, level=level, anchor="status")


@router.get("/wa/status.json")
def status_json(user: auth.SessionUser = Depends(auth.require_admin)):
    """Status jembatan WhatsApp (dipakai halaman untuk memperbarui badge)."""
    return wa_bridge.status_cepat()


@router.get("/wa/qr")
def qr(user: auth.SessionUser = Depends(auth.require_admin)):
    """Kode QR pairing. Selalu 200 JSON agar tidak ada 404 yang mengkhawatirkan.

    Mengembalikan ``{"ok": true, "png": "<base64>"}`` bila ada QR, atau
    ``{"ok": false, "detail": "..."}`` bila belum ada.
    """
    ok, png, galat = wa_bridge.qr_png()
    if ok and png:
        return {"ok": True, "png": base64.b64encode(png).decode("ascii")}
    return {"ok": False, "detail": galat or "Belum ada kode QR."}


@router.post("/wa/uji")
async def uji(request: Request,
              user: auth.SessionUser = Depends(auth.require_admin)):
    """Uji jembatan: kirim pesan masuk simulasi → lihat jawaban bodap."""
    try:
        isi = await request.json()
    except Exception:  # noqa: BLE001
        isi = {}
    dari = str(isi.get("dari") or "uji@s.whatsapp.net").strip()
    teks = str(isi.get("teks") or "").strip()
    if not teks:
        return _kembali("Isi teks uji dulu.", level="err", anchor="uji")
    # ssl blocking di thread agar event loop tidak terblokir (bridge memanggil
    # balik /ollama/chat yang butuh loop tetap bebas).
    hasil = await asyncio.to_thread(wa_bridge.uji_masuk, dari, teks)
    if hasil.get("ok"):
        return _kembali(f"Uji WA: {hasil.get('jawaban', '')[:120]}", level="ok", anchor="uji")
    return _kembali(f"Uji WA gagal: {hasil.get('jawaban') or 'tidak terhubung'}",
                    level="err", anchor="uji")


@router.post("/wa/kirim")
def kirim(
    no: str = Form(""),
    teks: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_admin),
):
    """Kirim pesan teks keluar via WhatsApp (admin)."""
    no = no.strip()
    teks = teks.strip()
    if not no or not teks:
        return _kembali("Nomor dan teks wajib diisi.", level="err", anchor="kirim")
    hasil = wa_bridge.kirim(no, teks)
    if hasil.get("ok"):
        return _kembali("Pesan terkirim via WhatsApp.", level="ok", anchor="kirim")
    return _kembali(f"Gagal mengirim: {hasil.get('pesan') or 'tidak terhubung'}",
                    level="err", anchor="kirim")
