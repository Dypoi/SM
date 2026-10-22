"""Halaman pembaruan aplikasi (git pull) khusus admin."""

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import auth, config, services, updater
from ..web import halaman_jeda, render

router = APIRouter()

ANCHOR = "#pembaruan"


def _redirect(pesan: str, level: str = "ok", anchor: str = "") -> RedirectResponse:
    return RedirectResponse(
        f"/pembaruan?level={level}&msg={quote_plus(pesan)}{anchor}", status_code=303
    )


def _konteks(status: dict | None = None) -> dict:
    status = status or updater.status_pembaruan(periksa_jaringan=False)
    return {
        "page_title": "Pembaruan Aplikasi",
        "status": status,
        "settings": services.get_settings(),
        "cabang_remote": updater.daftar_cabang_remote(status.get("remote") or "origin"),
        "catatan": status.get("catatan") or [],
        "perintah_manual": updater.perintah_manual(),
        "folder_aplikasi": str(config.BASE_DIR),
        "perintah_restart": " ".join(updater.perintah_restart()),
        "versi_aplikasi": config.APP_VERSION,
        "jenis_pasang": "salinan git" if status.get("tersedia") else "salinan tanpa git (ZIP)",
    }


@router.get("/pembaruan")
def halaman_pembaruan(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    perlu = request.query_params.get("cek") == "1"
    status = updater.status_pembaruan(periksa_jaringan=perlu)
    if perlu:
        updater.simpan_hasil_cek(status)
    return render(request, "update.html", _konteks(status))


@router.post("/pembaruan/periksa")
def periksa_pembaruan(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    status = updater.status_pembaruan(periksa_jaringan=True)
    updater.simpan_hasil_cek(status)
    services.log_audit(user.username, user.role, "periksa_pembaruan", "aplikasi", None,
                       f"ketinggalan={status.get('ketinggalan')}")
    if not status.get("jaringan_diperiksa"):
        return _redirect(status.get("pesan") or "Pemeriksaan gagal.", level="err", anchor=ANCHOR)
    if status.get("ada_pembaruan"):
        return _redirect(status.get("pesan") or "Ada pembaruan baru.", anchor=ANCHOR)
    return _redirect("Aplikasi sudah memakai versi terbaru dari GitHub.", anchor=ANCHOR)


@router.post("/pembaruan/tarik")
def tarik_pembaruan(
    request: Request,
    cabang: str = Form(""),
    pasang_pip: str = Form("1"),
    muat_ulang_setelah: str = Form("1"),
    user: auth.SessionUser = Depends(auth.require_admin),
):
    hasil = updater.terapkan_pembaruan(
        cabang=cabang.strip() or None,
        pasang_pip=pasang_pip in {"1", "on", "true"},
        aktor=user.username,
        role=user.role,
    )
    if not hasil["ok"]:
        return _redirect(hasil["pesan"], level="err", anchor=ANCHOR)

    pesan = hasil["pesan"]
    if hasil["berubah"] and muat_ulang_setelah in {"1", "on", "true"}:
        updater.minta_muat_ulang(aktor=user.username, alasan="pembaruan manual")
        # Balasan memakai halaman mandiri (tanpa template): berkas template sudah
        # baru sementara proses ini masih memakai kode lama, jadi templat apa pun
        # belum tentu bisa disusun. Halaman ini menunggu server siap lalu membuka
        # kembali halaman Pembaruan.
        return halaman_jeda(
            "Pembaruan berhasil dipasang",
            f"{pesan} Server sedang dimuat ulang dengan kode terbaru; "
            "halaman akan terbuka sendiri setelah server siap.",
            tujuan="/pembaruan",
            detik=4,
        )
    return _redirect(pesan, anchor=ANCHOR)


@router.post("/pembaruan/preferensi")
async def simpan_preferensi(
    request: Request,
    user: auth.SessionUser = Depends(auth.require_admin),
):
    form = await request.form()
    auto_cek = "1" if form.get("update_auto_cek") else "0"
    auto_tarik = "1" if form.get("update_auto_tarik") and auto_cek == "1" else "0"
    restart_otomatis = "1" if form.get("update_restart_otomatis") and auto_tarik == "1" else "0"
    try:
        interval = int(str(form.get("update_interval_jam") or "6"))
    except ValueError:
        interval = 6
    nilai = {
        "update_auto_cek": auto_cek,
        "update_auto_tarik": auto_tarik,
        "update_restart_otomatis": restart_otomatis,
        "update_interval_jam": str(max(1, min(interval, 24))),
        "update_remote": str(form.get("update_remote") or "origin").strip() or "origin",
        "update_cabang": str(form.get("update_cabang") or "").strip(),
    }
    services.update_settings(nilai)
    services.log_audit(user.username, user.role, "ubah_preferensi_pembaruan", "settings", None,
                       ", ".join(f"{k}={v}" for k, v in nilai.items()))
    return _redirect("Preferensi pembaruan disimpan.", anchor=ANCHOR)


@router.post("/pembaruan/muat-ulang")
def muat_ulang(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    if not updater.AKTIF or not updater.informasi_git()["bisa"]:
        return _redirect(
            "Muat ulang otomatis hanya tersedia bila aplikasi dijalankan dari salinan git. "
            "Tutup jendela server lalu jalankan run.bat kembali.",
            level="err",
            anchor=ANCHOR,
        )
    updater.minta_muat_ulang(aktor=user.username, alasan="diminta admin")
    return halaman_jeda(
        "Server sedang dimuat ulang",
        "Aplikasi memakai kode terbaru dari folder aplikasi. "
        "Halaman akan terbuka sendiri setelah server siap.",
        tujuan="/pembaruan",
        detik=4,
    )


@router.post("/pembaruan/batalkan-muat-ulang")
def batalkan_muat_ulang(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    updater.batalkan_muat_ulang()
    services.log_audit(user.username, user.role, "batalkan_muat_ulang", "aplikasi")
    return _redirect("Permintaan muat ulang dibatalkan.", anchor=ANCHOR)
