"""Halaman Bot Dapodik: jalankan registrasi peserta didik di Dapodik lokal.

Bot bekerja **di belakang layar** (Chrome headless) memakai antrean dari data
siswa aplikasi SM, dan kemajuannya tampil di halaman ini secara langsung.
"""

from __future__ import annotations

import csv
import io
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from .. import auth, bot_dapodik, services
from ..web import render

router = APIRouter()

#: Jumlah riwayat pekerjaan yang ditampilkan.
RIWAYAT_LIMIT = 10


def _pesan(teks: str, level: str = "ok", anchor: str = "") -> RedirectResponse:
    ujung = f"#{anchor}" if anchor else ""
    return RedirectResponse(f"/bot-dapodik?level={level}&msg={quote_plus(teks)}{ujung}",
                            status_code=303)


def _angka(nilai: str, bawaan: int = 0, minimum: int = 0, maksimum: int = 100000) -> int:
    try:
        return max(minimum, min(maksimum, int(str(nilai).strip() or bawaan)))
    except (TypeError, ValueError):
        return bawaan


def _opsi_antrean(request: Request) -> dict[str, object]:
    """Baca pilihan sumber antrean dari query/form."""
    q = request.query_params
    return {
        "rombel": (q.get("rombel") or "").strip()[:20],
        "limit": _angka(q.get("limit") or "0", 0),
        "nisn_manual": (q.get("nisn_manual") or "")[:20000],
        "lewati_sukses": q.get("lewati_sukses") != "0",
        "hanya_tanpa_nipd": q.get("hanya_tanpa_nipd") == "1",
    }


def _konteks(request: Request, **tambahan) -> dict:
    cfg = services.bot_setting()
    siap, keterangan = services.bot_siap_pakai()
    ringkas = services.ringkas_bot()
    job_terakhir = (ringkas.get("job") or {}).get("id")
    data = {
        "page_title": "Bot Dapodik",
        "cfg": cfg,
        "siap": siap,
        "keterangan_siap": keterangan,
        "ringkas": ringkas,
        "items": services.items_bot(int(job_terakhir)) if job_terakhir else [],
        "riwayat": services.list_dapodik_jobs(limit=RIWAYAT_LIMIT),
        "status_hidup": bot_dapodik.status_bot(),
        "opsi_rombel": services.distinct_values("rombel"),
        "jumlah_berhasil": len(services.bot_nisn_sukses()),
        "laporan_uji": services.laporan_uji_bot(),
        "punya_selenium": services.bot_punya_selenium(),
        "perintah_pip": services.perintah_pasang_bot(),
        "selector_bawaan": bot_dapodik.SELECTOR_BAWAAN,
        "selector_kunci": bot_dapodik.SELECTOR_DIIZINKAN,
        "antrean": [],
        "antrean_total": 0,
    }
    data.update(tambahan)
    return data


@router.get("/bot-dapodik")
def halaman_bot(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    opsi = _opsi_antrean(request)
    pratinjau = bool(request.query_params.get("pratinjau"))
    antrean = []
    if pratinjau:
        # Batas jumlah siswa ikut diterapkan di pratinjau supaya angka pada tombol
        # "Mulai bot untuk N siswa" benar-benar sama dengan yang akan diproses.
        antrean = services.bot_antrean(
            rombel=str(opsi["rombel"]), limit=int(opsi["limit"]), nisn_manual=str(opsi["nisn_manual"]),
            lewati_sukses=bool(opsi["lewati_sukses"]),
            hanya_tanpa_nipd=bool(opsi["hanya_tanpa_nipd"]))
    return render(request, "bot_dapodik.html",
                  _konteks(request, opsi=opsi, pratinjau=pratinjau,
                           antrean=antrean[:100], antrean_total=len(antrean)))


@router.post("/bot-dapodik/pengaturan")
def simpan_pengaturan(
    url: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    hobi: str = Form(""),
    cita: str = Form(""),
    timeout: str = Form("15"),
    retries: str = Form("3"),
    jeda: str = Form("1"),
    jeda_muat: str = Form("8"),
    jawaban_ya: str = Form(""),
    headless: str = Form(""),
    simulasi: str = Form(""),
    pakai_nisn: str = Form(""),
    sekolah_asal: str = Form(""),
    selector_json: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_admin),
):
    galat = bot_dapodik._pesan_galat_selector(selector_json)
    if galat:
        return _pesan(galat, level="err", anchor="pengaturan-bot")
    data = {
        "bot_url": url, "bot_username": username, "bot_hobi": hobi, "bot_cita": cita,
        "bot_timeout": _angka(timeout, 15, 3, 120), "bot_max_retries": _angka(retries, 3, 1, 10),
        "bot_jeda": _angka(jeda, 1, 0, 60),
        "bot_jeda_muat": _angka(jeda_muat, 8, 0, 120),
        "bot_jawaban_ya": "1" if jawaban_ya else "0",
        "bot_headless": "1" if headless else "0",
        "bot_simulasi": "1" if simulasi else "0",
        "bot_pakai_nisn": "1" if pakai_nisn else "0",
        "bot_sekolah_asal": "1" if sekolah_asal else "0",
        "bot_selector_json": selector_json,
    }
    # Kata sandi Dapodik hanya diganti bila diisi (tidak ditampilkan lagi di halaman).
    if password.strip():
        data["bot_password"] = password
    berubah = services.simpan_bot_setting(data)
    return _pesan(f"Pengaturan bot disimpan ({len(berubah)} kolom berubah).", anchor="pengaturan-bot")


@router.post("/bot-dapodik/mulai")
async def mulai_bot(request: Request, user: auth.SessionUser = Depends(auth.require_admin)):
    isian = await request.form()
    kelas = str(isian.get("rombel") or "").strip()[:20]
    batas = _angka(str(isian.get("limit") or "0"), 0)
    manual = str(isian.get("nisn_manual") or "")
    lewati = str(isian.get("lewati_sukses") or "1") == "1"
    tanpa_nipd = str(isian.get("hanya_tanpa_nipd") or "") == "1"

    cfg = services.bot_setting()
    siap, keterangan = services.bot_siap_pakai()
    if not siap:
        return _pesan(keterangan, level="err", anchor="jalankan")

    antrean = services.bot_antrean(rombel=kelas, limit=batas, nisn_manual=manual,
                                   lewati_sukses=lewati, hanya_tanpa_nipd=tanpa_nipd)
    if not antrean:
        return _pesan("Antrean kosong: tidak ada siswa yang cocok dengan pilihan Anda.",
                      level="warn", anchor="jalankan")
    try:
        job_id, _bot = bot_dapodik.mulai_bot(antrean, cfg, actor=user.username)
    except bot_dapodik.BotBerjalanError as exc:
        return _pesan(str(exc), level="warn", anchor="jalankan")
    mode = "uji coba" if cfg["bot_simulasi"] == "1" else (
        "di belakang layar" if cfg["bot_headless"] == "1" else "dengan jendela Chrome")
    return _pesan(f"Bot mulai bekerja ({mode}) untuk {len(antrean)} siswa. "
                  f"Pekerjaan #{job_id} — pantau kemajuannya di halaman ini.",
                  anchor="kemajuan")


def _ringkas_selector(laporan: dict) -> str:
    """Kalimat ringkas keadaan selector login untuk pesan di halaman."""
    status = laporan.get("selector_status") or {}
    terlihat = [k for k, v in status.items() if v.get("keadaan") == "terlihat"]
    belum = [k for k, v in status.items() if v.get("keadaan") == "ada_tak_terlihat"]
    hilang = [k for k, v in status.items() if v.get("keadaan") == "tidak_ada"]
    kalimat = f"selector login cocok {len(terlihat)}/{len(status) or 3}"
    if belum:
        kalimat += f", {len(belum)} ada tetapi belum terlihat ({', '.join(belum)})"
    if hilang:
        kalimat += f", tidak ditemukan: {', '.join(hilang)}"
    return kalimat


@router.post("/bot-dapodik/uji")
def uji_koneksi(coba_login: str = Form("0"), tampak: str = Form("0"),
                user: auth.SessionUser = Depends(auth.require_admin)):
    """Buka Dapodik sebentar & laporkan apa yang terlihat (alat bantu selector).

    Pilihan ``coba_login`` membuat bot sekalian mengisi kolom login & menekan tombol
    masuk seperti pekerjaan sungguhan, sehingga jawabannya pasti: berhasil masuk, atau
    pesan penolakan dari Dapodik. ``tampak`` menjalankan uji ini dengan jendela Chrome
    terlihat (untuk membandingkan dengan mode di belakang layar).
    """
    if bot_dapodik.bot_berjalan() is not None:
        return _pesan("Hentikan bot dulu sebelum menguji koneksi Dapodik.", level="warn",
                      anchor="jalankan")
    siap, keterangan = services.bot_siap_pakai()
    if not siap and "selenium" in keterangan:
        return _pesan(keterangan, level="err", anchor="jalankan")
    opsi = dict(services.bot_setting())
    if tampak == "1":
        opsi["bot_headless"] = "0"      # hanya untuk uji kali ini
    percobaan_masuk = coba_login == "1"
    alasan_lewat = ""
    if percobaan_masuk and not (opsi.get("bot_username", "").strip() and opsi.get("bot_password", "")):
        percobaan_masuk = False
        alasan_lewat = (" Percobaan masuk dilewati karena nama pengguna/kata sandi belum diisi "
                        "pada «Pengaturan».")
    laporan = bot_dapodik.uji_dapodik(opsi, coba_login=percobaan_masuk)
    services.simpan_laporan_uji_bot(laporan)
    if laporan.get("galat"):
        return _pesan(f"Uji koneksi gagal: {laporan['galat']}", level="err", anchor="catatan-uji")
    masuk = laporan.get("masuk") or {}
    if percobaan_masuk and masuk.get("dicoba"):
        if masuk.get("berhasil"):
            return _pesan("Uji koneksi + percobaan masuk: BERHASIL. " + str(masuk.get("pesan") or "") +
                          " Rincian & bukti ada pada kartu di bawah.", anchor="catatan-uji")
        return _pesan("Uji koneksi selesai, tetapi percobaan masuk BELUM berhasil: " +
                      str(masuk.get("pesan") or "tanpa keterangan") +
                      " Rincian dan status selector ada pada kartu di bawah.",
                      level="warn", anchor="catatan-uji")
    if laporan.get("formulir_tampil"):
        return _pesan(
            f"Uji koneksi selesai. Formulir login tampil (judul: "
            f"'{laporan.get('judul') or '(tanpa judul)'}'), {_ringkas_selector(laporan)}." +
            alasan_lewat + " Rincian & bukti pemeriksaan ada pada kartu di bawah.",
            level="warn" if alasan_lewat else "ok", anchor="catatan-uji")
    return _pesan(
        f"Uji koneksi selesai, tetapi formulir login BELUM tampil (judul: "
        f"'{laporan.get('judul') or '(tanpa judul)'}', {_ringkas_selector(laporan)}). "
        f"Naikkan «Jeda muat halaman Dapodik» lalu uji lagi — atau ulangi uji dengan "
        f"pilihan «sekalian coba masuk» supaya bot benar-benar mencoba mengisi & menekan tombol." +
        alasan_lewat,
        level="warn", anchor="catatan-uji")


@router.post("/bot-dapodik/pasang")
def pasang_pustaka(user: auth.SessionUser = Depends(auth.require_admin)):
    """Pasang selenium dari dalam aplikasi (memakai Python aplikasi ini)."""
    if bot_dapodik.bot_berjalan() is not None:
        return _pesan("Hentikan bot dulu sebelum memasang pustaka.", level="warn", anchor="jalankan")
    berhasil, pesan = services.bot_pasang_pustaka()
    return _pesan(pesan, level="ok" if berhasil else "err", anchor="jalankan")


@router.post("/bot-dapodik/hentikan")
def hentikan(user: auth.SessionUser = Depends(auth.require_admin)):
    if bot_dapodik.hentikan_bot():
        return _pesan("Permintaan berhenti dikirim. Bot menyelesaikan siswa yang sedang "
                      "diproses dulu, lalu berhenti.", level="warn", anchor="kemajuan")
    return _pesan("Tidak ada bot yang sedang berjalan.", level="info", anchor="kemajuan")


@router.post("/bot-dapodik/bersihkan")
def bersihkan_riwayat(user: auth.SessionUser = Depends(auth.require_admin)):
    if bot_dapodik.bot_berjalan() is not None:
        return _pesan("Hentikan bot dulu sebelum menghapus riwayat.", level="warn", anchor="kemajuan")
    job, item = services.hapus_riwayat_bot()
    return _pesan(f"Riwayat bot dihapus ({job} pekerjaan, {item} item). Semua siswa "
                  "akan dianggap belum pernah didaftarkan.", level="info", anchor="kemajuan")


@router.get("/bot-dapodik/status.json")
def status_json(user: auth.SessionUser = Depends(auth.require_admin)):
    """Kemajuan terkini (dipakai halaman untuk memperbarui tampilan otomatis)."""
    ringkas = services.ringkas_bot()
    job = ringkas.get("job") or {}
    job_id = int(job["id"]) if job.get("id") else 0
    hidup = bot_dapodik.status_bot()
    hitung = ringkas.get("hitung", {})
    return {
        "hidup": hidup,
        "job": {
            "id": job_id,
            "status": job.get("status"),
            "total": job.get("total_item") or 0,
            "sukses": job.get("sukses_item") or 0,
            "gagal": job.get("gagal_item") or 0,
            "mode": job.get("mode"),
            "mulai": job.get("started_at"),
            "selesai": job.get("finished_at"),
        },
        "hitung": hitung,
        "diproses": sum(int(hitung.get(kunci, 0)) for kunci in ("sukses", "gagal", "dilewati")),
        "sedang": (ringkas.get("sedang") or {}).get("nama"),
        "items": [
            {"nisn": item["nisn"], "nis": item["nipd"], "nama": item["nama"],
             "status": item["status"], "pesan": item["pesan"], "waktu": item["waktu"]}
            for item in (services.items_bot(job_id) if job_id else [])
        ],
        "log": (job.get("log") or "").splitlines()[-12:],
    }


def _job_terakhir() -> int:
    """Nomor pekerjaan bot terakhir (0 bila belum ada) — aman untuk basis data kosong."""
    ringkas = services.ringkas_bot()
    return int((ringkas.get("job") or {}).get("id") or 0)


def _data_item(job_id: int) -> list[dict]:
    return services.items_bot(job_id, limit=100000)


@router.get("/bot-dapodik/log.csv")
def log_csv(user: auth.SessionUser = Depends(auth.require_admin)):
    job_id = _job_terakhir()
    baris = _data_item(job_id) if job_id else []
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["No", "NISN", "NIS/NIPD", "Nama", "Status", "Pesan", "Waktu"])
    for indeks, item in enumerate(baris, start=1):
        writer.writerow([indeks, item["nisn"] or "", item["nipd"] or "", item["nama"] or "",
                         item["status"], item["pesan"] or "", item["waktu"] or ""])
    return Response(buffer.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="bot-dapodik-{job_id or 0}.csv"'})


@router.get("/bot-dapodik/log.xlsx")
def log_xlsx(user: auth.SessionUser = Depends(auth.require_admin)):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    job_id = _job_terakhir()
    wb = Workbook()
    ws = wb.active
    ws.title = "Bot Dapodik"
    kepala = ["No", "NISN", "NIS/NIPD", "Nama", "Status", "Pesan", "Waktu"]
    ws.append(kepala)
    for sel in ws[1]:
        sel.font = Font(bold=True)
    for indeks, item in enumerate(_data_item(job_id) if job_id else [], start=1):
        ws.append([indeks, item["nisn"] or "", item["nipd"] or "", item["nama"] or "",
                   item["status"], item["pesan"] or "", item["waktu"] or ""])
    for kolom, lebar in zip("ABCDEFG", (5, 14, 14, 30, 11, 60, 20)):
        ws.column_dimensions[kolom].width = lebar
    for sel in ws["F"]:
        sel.alignment = Alignment(wrap_text=True, vertical="top")
    buffer = io.BytesIO()
    wb.save(buffer)
    return Response(
        buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="bot-dapodik-{job_id or 0}.xlsx"'})
