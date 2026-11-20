"""Rute halaman & API **Ollama** — aktivasi, uji koneksi, obrolan, status."""

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import auth, ollama, services
from ..web import render

router = APIRouter()


def _kembali(pesan: str, level: str = "ok", anchor: str = "") -> RedirectResponse:
    return RedirectResponse(
        f"/ollama?level={level}&msg={quote_plus(pesan)}{'#' + anchor if anchor else ''}",
        status_code=303)


@router.get("/ollama")
def halaman_ollama(request: Request,
                   user: auth.SessionUser = Depends(auth.require_admin)):
    """Halaman «Ollama»: aktivasi, uji koneksi, daftar alat, dan obrolan uji."""
    return render(
        request,
        "ollama.html",
        {
            "page_title": "Ollama",
            "cfg": ollama.pengaturan(),
            "status": ollama.status_cepat(),
            "alat": ollama.daftar_alat(),
        },
    )


@router.post("/ollama/pengaturan")
def simpan_pengaturan(
    aktif: str = Form(""),
    url: str = Form(""),
    model: str = Form(""),
    kunci: str = Form(""),
    eksekusi: str = Form(""),
    detik: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_admin),
):
    """Simpan pengaturan Ollama (aktivasi + alamat + model + izin eksekusi)."""
    berubah = ollama.simpan_pengaturan({
        "ollama_aktif": "1" if aktif else "0",
        "ollama_url": url,
        "ollama_model": model,
        "ollama_kunci": kunci,
        "ollama_eksekusi": "1" if eksekusi else "0",
        "ollama_detik": detik,
    })
    pesan = ("Pengaturan Ollama disimpan." + (f" ({len(berubah)} kolom berubah.)"
                                              if berubah else " Tiada yang berubah."))
    return _kembali(pesan, anchor="aktivasi")


@router.post("/ollama/uji")
def uji_koneksi(user: auth.SessionUser = Depends(auth.require_admin)):
    """Uji koneksi ke Ollama dan simpan laporan (dipakai halaman)."""
    laporan = ollama.cek_koneksi()
    ollama.simpan_laporan_uji(laporan)
    if laporan.get("ok"):
        model = laporan.get("model") or []
        memuat = (ollama.pengaturan().get(ollama.KUNCI_MODEL) or "")
        cocok = memuat in model if model else True
        pesan = laporan.get("pesan") or "Ollama terhubung."
        if not cocok:
            pesan += (f" Perhatikan: model «{memuat}» belum terdaftar di Ollama — "
                      f"pilih model yang ada ({', '.join(model[:5]) or 'kosong'}).")
        return _kembali(pesan, level="ok" if cocok else "warn", anchor="aktivasi")
    return _kembali(str(laporan.get("pesan") or "Uji koneksi gagal."),
                    level="err", anchor="aktivasi")


@router.get("/ollama/status.json")
def status_json(user: auth.SessionUser = Depends(auth.require_admin)):
    """Status ringkas (dipakai halaman untuk memperbarui badge)."""
    return ollama.status_cepat()


@router.post("/ollama/chat")
async def chat(request: Request):
    """Satu pesan → Ollama → alat bodap → jawaban.

    Dipakai halaman obrolan **dan** jembatan WhatsApp (ronde berikutnya):
    header ``X-API-Key`` yang sah atau sesi admin. Galat dikembalikan sebagai
    JSON langsung (bukan halaman galat/redirect) supaya jembatan dapat
    membacanya secara program.
    """
    kunci_api = request.headers.get("x-api-key") or ""
    expected = services.get_setting("api_key") or ""
    if not (kunci_api and expected and kunci_api == expected):
        pengguna = auth.current_user(request)
        if pengguna is None or pengguna.role != auth.ROLE_ADMIN:
            return JSONResponse({"detail": "Butuh sesi admin atau kunci API yang sah."},
                                status_code=401)
    try:
        isi = await request.json()
    except ValueError:
        return JSONResponse({"detail": "Isi permintaan harus JSON."}, status_code=400)
    if not isinstance(isi, dict):
        return JSONResponse({"detail": "Isi permintaan harus JSON objek."},
                            status_code=400)
    pesan = str(isi.get("pesan") or "").strip()
    if not pesan:
        return JSONResponse({"detail": "Pesan kosong."}, status_code=400)
    riwayat = isi.get("riwayat") or []
    if not isinstance(riwayat, list):
        return JSONResponse({"detail": "Riwayat harus berupa daftar."}, status_code=400)
    sumber = str(isi.get("sumber") or "web").strip().lower()
    try:
        hasil = ollama.bicara(pesan, riwayat=riwayat, sumber=sumber)
    except ollama.OllamaTidakAktif as galat:
        return JSONResponse({"detail": str(galat)}, status_code=400)
    except ollama.OllamaGalat as galat:
        return JSONResponse({"detail": str(galat)}, status_code=502)
    return JSONResponse(hasil)
