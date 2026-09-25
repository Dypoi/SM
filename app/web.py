"""Helper rendering template & utilitas tampilan."""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import auth, config, online, services
from .dapodik import FIELD_BY_KEY, GROUP_LABELS, fields_by_group

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]
HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


# --------------------------------------------------------------------------- #
# Filter tampilan
# --------------------------------------------------------------------------- #
def tanggal_id(value: Any, with_day: bool = False) -> str:
    """'2011-08-22' -> '22 Agustus 2011'."""
    if not value:
        return "-"
    text = str(value)[:10]
    try:
        date = dt.date.fromisoformat(text)
    except ValueError:
        return str(value)
    hasil = f"{date.day} {BULAN_ID[date.month]} {date.year}"
    if with_day:
        hasil = f"{HARI_ID[date.weekday()]}, {hasil}"
    return hasil


def tanggal_waktu(value: Any) -> str:
    if not value:
        return "-"
    text = str(value).replace("T", " ")
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return text
    return f"{moment.day} {BULAN_ID[moment.month]} {moment.year} {moment:%H:%M}"


def static_url(path: str) -> str:
    """URL berkas statis + penanda waktu ubah berkas.

    Tanpa penanda ini browser bisa memakai app.css/app.js lama dari cache,
    sehingga perbaikan tampilan tidak terlihat walau server sudah diperbarui.
    """
    bersih = str(path).lstrip("/").replace("\\", "/")
    target = config.STATIC_DIR / bersih
    try:
        penanda = int(target.stat().st_mtime)
    except OSError:
        penanda = 0
    return f"/static/{bersih}?v={penanda}"


def angka_id(value: Any) -> str:
    """1234 -> '1.234'."""
    if value is None or value == "":
        return "0"
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,}".replace(",", ".")


def umur(value: Any) -> str:
    if not value:
        return "-"
    try:
        lahir = dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return "-"
    today = dt.date.today()
    years = today.year - lahir.year - ((today.month, today.day) < (lahir.month, lahir.day))
    return f"{years} tahun" if years >= 0 else "-"


def badge_status(value: Any) -> str:
    text = (str(value) if value is not None else "").strip().lower()
    mapping = {
        "aktif": "badge-success",
        "sukses": "badge-success",
        "ya": "badge-success",
        "lulus": "badge-info",
        "sebagian": "badge-warning",
        "draft": "badge-muted",
        "menunggu": "badge-muted",
        "mutasi": "badge-warning",
        "keluar": "badge-danger",
        "gagal": "badge-danger",
        "non-aktif": "badge-muted",
        "tidak": "badge-muted",
    }
    return mapping.get(text, "badge-muted")


# Label untuk kolom yang ada di database namun tidak berasal dari berkas impor.
EXTRA_LABELS = {
    "status": "Status",
    "catatan": "Catatan Internal",
    "is_kip": "Penerima KIP (ya/tidak)",
    "is_kps": "Penerima KPS (ya/tidak)",
    "is_layak_pip": "Layak PIP (ya/tidak)",
    "id": "ID",
    "updated_at": "Terakhir diubah",
    "created_at": "Dibuat",
}


def field_label(key: str) -> str:
    """Nama tampilan sebuah kolom, aman walau kolomnya bukan field impor."""
    spec = FIELD_BY_KEY.get(key)
    if spec is not None:
        return spec.label
    return EXTRA_LABELS.get(key, key.replace("_", " ").title())


def singkat(value: Any, length: int = 40) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= length else text[: length - 1] + "…"


#: Kerangka halaman HTML mandiri (tanpa template). Dipakai saat template tidak
#: boleh atau gagal disusun: berkas template sudah baru sementara proses masih
#: memakai kode lama (beberapa saat sesudah menarik pembaruan), atau ada galat
#: pada template. Halaman ini tidak bergantung pada berkas apa pun sehingga
#: selalu bisa dikirim.
_HALAMAN_MANDIRI = """<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0f172a">
  <title>__JUDUL__ - __APP__</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%232563eb'/%3E%3Cpath d='M9 21V11l7-4 7 4v10' stroke='white' stroke-width='2.2' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 1.5rem;
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #2563eb 100%);
      font-family: "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif; color: #0f172a;
    }
    .kotak {
      background: #fff; border-radius: 18px; padding: 2rem 1.9rem; max-width: 30rem; width: 100%;
      box-shadow: 0 24px 60px rgba(2, 6, 23, .35); text-align: center;
    }
    .lambang {
      width: 52px; height: 52px; border-radius: 15px; margin: 0 auto .9rem;
      display: grid; place-items: center; background: #eff6ff; color: #2563eb;
    }
    h1 { font-size: 1.22rem; margin: 0 0 .5rem; }
    p { margin: 0 0 .85rem; color: #475569; font-size: .92rem; line-height: 1.55; }
    code { background: #f1f5f9; border-radius: 6px; padding: .12rem .38rem; font-size: .82rem; }
    .tombol {
      display: inline-flex; align-items: center; gap: .45rem; text-decoration: none;
      background: #2563eb; color: #fff; font-weight: 600; font-size: .92rem;
      padding: .72rem 1.15rem; border-radius: 10px; border: 0; cursor: pointer;
    }
    .tombol:hover { background: #1d4ed8; }
    .tombol.polos { background: #f1f5f9; color: #1e293b; }
    .status { margin-top: 1rem; font-size: .82rem; color: #64748b; }
    .denyut {
      width: 8px; height: 8px; border-radius: 50%; background: #2563eb; display: inline-block;
      margin-right: .4rem; animation: denyut 1s ease-in-out infinite;
    }
    @keyframes denyut { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) { .denyut { animation: none; opacity: .8; } }
  </style>
</head>
<body>
  <main class="kotak">
    <div class="lambang">__LAMBANG__</div>
    <h1>__JUDUL__</h1>
    __ISI__
  </main>
</body>
</html>
"""

_IKON_JAM = (
    '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>'
)
_IKON_SEGITIGA = (
    '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
    '<path d="M12 9v4"/><path d="M12 17h.01"/></svg>'
)

_SKRIP_JEDA = """<script>
var tujuan = "__TUJUAN__";
var percobaan = 0;
function cekServer() {
  percobaan += 1;
  var status = document.getElementById("status");
  if (status) {
    status.innerHTML = '<span class="denyut"></span>Menunggu server siap ... (' + percobaan + ')';
  }
  fetch("/health", { cache: "no-store" }).then(function (balasan) {
    if (balasan.ok) { window.location.replace(tujuan); }
  }).catch(function () {
    /* server belum siap - coba lagi */
  }).then(function () {
    if (percobaan < 20) {
      window.setTimeout(cekServer, 2500);
    } else if (status) {
      status.textContent = "Server belum siap juga. Klik \\"Buka aplikasi sekarang\\" sebentar lagi.";
    }
  });
}
window.setTimeout(cekServer, __DETIK__);
</script>"""


def halaman_jeda(judul: str, pesan: str, tujuan: str = "/", detik: int = 3) -> HTMLResponse:
    """Halaman mandiri "server sedang dimuat ulang" (tanpa template).

    Dipakai sesudah pembaruan ditarik: proses server menggantikan dirinya dalam
    beberapa detik, halaman ini menunggu sampai /health menjawab lagi lalu
    membuka halaman tujuan. Karena tidak memakai template, halaman ini tetap
    terkirim walau berkas template sudah berubah sementara kode lama masih
    berjalan (penyebab galat 500 sesaat sesudah menarik pembaruan).
    """
    isi = (
        f"<p>{pesan}</p>"
        '<p class="status" id="status"><span class="denyut"></span>Menunggu server siap ...</p>'
        f'<p><a class="tombol" href="{tujuan}">Buka aplikasi sekarang</a></p>'
    )
    skrip = (
        _SKRIP_JEDA.replace("__TUJUAN__", tujuan)
        .replace("__DETIK__", str(max(1, int(detik)) * 1000))
    )
    halaman = (
        _HALAMAN_MANDIRI.replace("__JUDUL__", judul)
        .replace("__APP__", config.APP_NAME)
        .replace("__LAMBANG__", _IKON_JAM)
        .replace("__ISI__", isi + skrip)
    )
    return HTMLResponse(halaman, status_code=200, headers={"Cache-Control": "no-store"})


def _halaman_darurat(template: str, galat: Exception) -> HTMLResponse:
    """Balasan terakhir bila template gagal disusun - jangan sampai 500 kosong."""
    isi = (
        "<p>Halaman tidak dapat disusun. Bila Bapak/Ibu baru saja menekan "
        "<strong>Tarik pembaruan</strong>, tunggu beberapa detik lalu buka kembali: "
        "server sedang memakai kode terbaru.</p>"
        f'<p class="status">Rincian teknis: <code>{type(galat).__name__}: {galat}</code></p>'
        f'<p class="status">Template: <code>{template}</code></p>'
        '<p><a class="tombol" href="/">Buka dasbor</a></p>'
    )
    print(f"[!] Template '{template}' gagal disusun: {type(galat).__name__}: {galat}")
    halaman = (
        _HALAMAN_MANDIRI.replace("__JUDUL__", "Halaman gagal disusun")
        .replace("__APP__", config.APP_NAME)
        .replace("__LAMBANG__", _IKON_SEGITIGA)
        .replace("__ISI__", isi)
    )
    return HTMLResponse(halaman, status_code=500, headers={"Cache-Control": "no-store"})


def qs_set(qs: str, **nilai: Any) -> str:
    """Query string dengan beberapa parameter diubah/ditambah.

    Dipakai tautan urut tabel: mempertahankan filter yang sedang aktif sehingga
    mengurutkan kolom tidak menghapus pencarian pengguna.
    """
    pasangan = dict(parse_qsl((qs or "").lstrip("?"), keep_blank_values=True))
    for kunci, isi in nilai.items():
        if isi in (None, ""):
            pasangan.pop(kunci, None)
        else:
            pasangan[kunci] = str(isi)
    hasil = urlencode(pasangan)
    return f"?{hasil}" if hasil else ""


def qs_tanpa(qs: str, *kunci: str) -> str:
    """Query string tanpa parameter tertentu (tombol × pada chip filter)."""
    pasangan = [(k, v) for k, v in parse_qsl((qs or "").lstrip("?"), keep_blank_values=True)
                if k not in kunci]
    hasil = urlencode(pasangan)
    return f"?{hasil}" if hasil else ""


def hari_ini(with_day: bool = True) -> str:
    """Tanggal hari ini dalam bahasa Indonesia (untuk kepala cetak)."""
    return tanggal_id(dt.date.today().isoformat(), with_day=with_day)


#: Akronim yang huruf besarnya harus dipertahankan saat label dirapikan.
AKRONIM_LABEL = {
    "NISN", "NIS", "NIPD", "NIK", "KK", "KPS", "KIP", "PIP", "KM", "KG", "CM",
    "RT", "RW", "HP", "NPSN", "PAUD", "TK", "SD", "SMP", "SMA", "SMK", "MI",
    "MTs", "MA", "NIP", "KKG", "NKT", "KIP", "KG", "D1", "D2", "D3", "D4", "S1",
    "S2", "S3", "PKBM", "SLB", "SKHUN", "UN",
}


def rapikan_label(teks: Any) -> str:
    """Rapikan label data untuk dibaca siswa: ``Nama Lengkap`` → ``Nama lengkap``.

    Akronim (NISN, NIK, KK, RT/RW, KM) dan kata berisi angka dibiarkan apa adanya,
    supaya tidak ada istilah yang berubah arti. Dipakai halaman siswa; label resmi
    Dapodik untuk petugas tidak diubah.
    """
    akronim_besar = {kata.upper() for kata in AKRONIM_LABEL}
    hasil: list[str] = []
    for indeks, kata in enumerate(str(teks or "").split()):
        bersih = kata.strip(".,;:()[]")
        # "SD/MTs" harus tetap huruf besar walau bukan satu kata tunggal.
        bagian = [b for b in bersih.split("/") if b]
        akronim = bool(bagian) and all(b.upper() in akronim_besar for b in bagian)
        if (akronim or any(ch.isdigit() for ch in bersih)
                or (bersih and bersih.isupper() and len(bersih) > 1)):
            hasil.append(kata)
        elif indeks == 0:
            hasil.append(kata[:1].upper() + kata[1:].lower())
        else:
            hasil.append(kata.lower())
    return " ".join(hasil).replace(" /", "/").replace("/ ", "/")


templates.env.globals["field_label"] = field_label
templates.env.globals["static_url"] = static_url
templates.env.globals["qs_set"] = qs_set
templates.env.globals["qs_tanpa"] = qs_tanpa
templates.env.globals["hari_ini"] = hari_ini
#: «Nama Lengkap» → «Nama lengkap» untuk halaman siswa (akronim tetap: NISN, NIK, KK).
templates.env.globals["rapikan_label"] = rapikan_label
templates.env.globals["GROUP_LABELS"] = GROUP_LABELS
#: Kolom yang tidak dapat diubah dari formulir (rombel & tingkat) — dipakai
#: template untuk menampilkan kolom sebagai "tidak dapat diubah".
templates.env.globals["FIELD_TERKUNCI"] = services.FIELD_TERKUNCI


templates.env.filters.update(
    {
        "tanggal_id": tanggal_id,
        "tanggal_waktu": tanggal_waktu,
        "angka_id": angka_id,
        "umur": umur,
        "badge": badge_status,
        "singkat": singkat,
    }
)


# --------------------------------------------------------------------------- #
# Data global untuk semua template
# --------------------------------------------------------------------------- #
def nav_items(user: auth.SessionUser | None) -> list[dict[str, str]]:
    if user is None:
        return []
    if user.role == auth.ROLE_EKSKUL:
        return [
            {"href": user.halaman_ekskul, "label": user.ekskul_nama or "Ekstrakurikuler", "icon": "flag"},
        ]
    if user.role == auth.ROLE_SISWA:
        return [
            {"href": "/portal", "label": "Beranda Saya", "icon": "home"},
            {"href": "/portal/pengajuan", "label": "Ajukan Perubahan", "icon": "edit"},
            {"href": "/portal/profil", "label": "Data Saya", "icon": "user"},
            {"href": "/portal/ekstrakurikuler", "label": "Ekstrakurikuler", "icon": "flag"},
        ]
    items = [
        {"href": "/", "label": "Dasbor", "icon": "home"},
        {"href": "/data-siswa", "label": "Data Siswa", "icon": "users"},
        {"href": "/pengajuan", "label": "Persetujuan Data", "icon": "check",
         "badge": services.hitung_pengajuan("menunggu")},
        {"href": "/impor", "label": "Impor Excel/CSV", "icon": "upload"},
        {"href": "/ekstrakurikuler", "label": "Ekstrakurikuler", "icon": "flag"},
        {"href": "/statistik", "label": "Statistik", "icon": "chart"},
        {"href": "/kualitas-data", "label": "Kualitas Data", "icon": "check"},
        {"href": "/bot-dapodik", "label": "Bot Dapodik", "icon": "robot",
         "badge": services.bot_menunggu_kira()},
        {"href": "/pengaturan", "label": "Pengaturan", "icon": "cog"},
        {"href": "/pembaruan", "label": "Pembaruan", "icon": "refresh"},
    ]
    if user.role != auth.ROLE_ADMIN:
        items = [item for item in items if item["href"] not in
                 {"/pengaturan", "/pembaruan", "/pengajuan", "/bot-dapodik"}]
        items.append({"href": "/profil-akun", "label": "Akun Saya", "icon": "user"})
    return items


#: Kelompok menu samping supaya daftar menu mudah dipindai.
NAV_GRUP = {
    "/": "Utama",
    "/data-siswa": "Utama",
    "/pengajuan": "Utama",
    "/impor": "Data & Laporan",
    "/kualitas-data": "Data & Laporan",
    "/bot-dapodik": "Sistem",
    "/statistik": "Data & Laporan",
    "/ekstrakurikuler": "Data & Laporan",
    "/pengaturan": "Sistem",
    "/pembaruan": "Sistem",
    "/profil-akun": "Sistem",
}


def nav_grup(user: auth.SessionUser | None) -> list[dict[str, Any]]:
    """Menu samping dikelompokkan (label kosong bila menunya sedikit)."""
    items = nav_items(user)
    if len(items) <= 4:
        return [{"label": "", "items": items}]
    hasil: list[dict[str, Any]] = []
    for item in items:
        label = NAV_GRUP.get(item["href"], "Sistem")
        if hasil and hasil[-1]["label"] == label:
            hasil[-1]["items"].append(item)
        else:
            hasil.append({"label": label, "items": [item]})
    return hasil


PAGE_TITLES = {
    "/": "Dasbor",
    "/data-siswa": "Data Siswa",
    "/impor": "Impor Berkas",
    "/ekstrakurikuler": "Ekstrakurikuler",
    "/statistik": "Statistik",
    "/kualitas-data": "Kualitas Data",
    "/bot-dapodik": "Bot Dapodik",
    "/pengaturan": "Pengaturan",
    "/pembaruan": "Pembaruan Aplikasi",
    "/pengajuan": "Persetujuan Perubahan Data",
    "/portal/pengajuan": "Ajukan Perubahan Data",
    "/portal": "Beranda Saya",
    "/portal/ekstrakurikuler": "Ekstrakurikuler Saya",
    "/portal/profil": "Perbaiki Data Saya",
    "/login": "Masuk",
}


def render(request: Request, template: str, context: dict[str, Any] | None = None,
           status_code: int = 200):
    """Render template dengan konteks standar (pengguna, profil, notifikasi)."""
    user = auth.current_user(request)
    ctx: dict[str, Any] = {
        "request": request,
        "user": user,
        "profil": services.school_profile(),
        "nav": nav_items(user),
        "nav_grup": nav_grup(user),
        "app_name": config.APP_NAME,
        "app_long_name": config.APP_LONG_NAME,
        "app_version": config.APP_VERSION,
        "current_path": request.url.path,
        "msg": request.query_params.get("msg", ""),
        "msg_level": request.query_params.get("level", "ok"),
        "page_title": PAGE_TITLES.get(request.url.path, config.APP_NAME),
        "peringatan_online": online.peringatan_aman(user),
        "mode_vercel": config.VERCEL,
    }
    if context:
        ctx.update(context)
    try:
        return templates.TemplateResponse(
            request=request, name=template, context=ctx, status_code=status_code
        )
    except Exception as galat:  # noqa: BLE001 - kirim halaman darurat, bukan 500 kosong
        return _halaman_darurat(template, galat)


# --------------------------------------------------------------------------- #
# Paginasi
# --------------------------------------------------------------------------- #
def paginate(total: int, page: int, per_page: int) -> dict[str, Any]:
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    page = min(max(1, page), pages)
    start = (page - 1) * per_page + 1 if total else 0
    end = min(page * per_page, total)

    window: list[int | None] = []
    for number in range(1, pages + 1):
        if number <= 2 or number > pages - 2 or abs(number - page) <= 1:
            window.append(number)
        elif window and window[-1] is not None:
            window.append(None)
    return {
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "start": start,
        "end": end,
        "window": window,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def field_groups() -> dict[str, list]:
    return fields_by_group()


def field_spec(key: str):
    return FIELD_BY_KEY.get(key)


def query_string(request: Request, **updates: Any) -> str:
    """Bangun query string dengan nilai yang diubah (untuk tautan filter)."""
    params = dict(request.query_params)
    for key, value in updates.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = str(value)
    if not params:
        return ""
    parts = "&".join(f"{key}={value}" for key, value in params.items() if value not in (None, ""))
    return f"?{parts}" if parts else ""
