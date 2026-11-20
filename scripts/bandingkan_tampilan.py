#!/usr/bin/env python3
"""Bandingkan **tampilan lama** (sebelum aturan «ruang siswa») dengan tampilan sekarang.

Halaman siswa sebelum ronde 28 memakai kerangka petugas (sidebar + tabel padat).
Berkas lama diambil apa adanya dari Git (tanpa mengubah riwayat), lalu dirender
dengan data siswa yang sama supaya perbandingannya adil — bukan tangkapan layar,
tapi hasil render sungguhan dari template lama.

Hasil: ``pratinjau/bandingkan.html`` (lama ⇄ baru berdampingan) + berkas
``pratinjau/lama-*.html``. Lihat ``scripts/pratinjau_tampilan.py`` untuk sisi baru.

Pemakaian::

    python scripts/bandingkan_tampilan.py                 # revisi lama: r27 (56…)
    python scripts/bandingkan_tampilan.py --revisi abcc66f^   # banding lain
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

HALAMAN = (
    ("portal", "portal/home.html", "lama-beranda.html", "beranda.html", "Beranda siswa"),
    ("profil", "portal/profile.html", "lama-dataku.html", "dataku.html", "Dataku"),
    ("kegiatan", "portal/ekskul.html", "lama-kegiatan.html", "kegiatan.html", "Kegiatan / klub"),
    ("perbaikan", "portal/request.html", "lama-perbaikan.html", "perbaikan.html", "Minta perbaikan"),
)

#: Kepala perbandingan pada berkas HTML gabungan (dibuat di bawah).
_CSS_BANDING = """
body { font-family: "Segoe UI", system-ui, Roboto, Arial, sans-serif; margin: 0; background: #eef3fb; color: #17233d; }
header { padding: 1rem clamp(1rem, 4vw, 2rem); background: #fff; border-bottom: 1px solid #e6edf8; }
h1 { margin: 0 0 .2rem; font-size: 1.25rem; }
header p { margin: 0; color: #5b6884; font-size: .9rem; max-width: 90ch; }
.pilih { display: flex; flex-wrap: wrap; gap: .5rem; padding: .8rem clamp(1rem, 4vw, 2rem); background: #fff; border-bottom: 1px solid #e6edf8; }
.pilih button { font: inherit; font-size: .9rem; font-weight: 600; padding: .45rem .9rem; border-radius: 999px;
                border: 1px solid #cfe0ff; background: #f4f8ff; color: #1d4ed8; cursor: pointer; }
.pilih button[aria-pressed="true"] { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.pasangan { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; padding: 1rem clamp(1rem, 4vw, 2rem) 2rem; }
.pasangan figure { margin: 0; background: #fff; border: 1px solid #e6edf8; border-radius: 14px; overflow: hidden; }
.pasangan figcaption { padding: .5rem .8rem; font-size: .85rem; font-weight: 700; border-bottom: 1px solid #e6edf8; }
.pasangan figcaption.lama { background: #fff7ed; color: #9a3412; }
.pasangan figcaption.baru { background: #ecfdf5; color: #065f46; }
.pasangan iframe { width: 100%; height: 70vh; border: 0; background: #fff; }
[hidden] { display: none !important; }
@media (max-width: 900px) { .pasangan { grid-template-columns: 1fr; } .pasangan iframe { height: 60vh; } }
"""

_JS_BANDING = """
document.querySelectorAll(".pilih button").forEach(function (b) {
  b.addEventListener("click", function () {
    document.querySelectorAll(".pasangan").forEach(function (p) { p.hidden = p.dataset.nama !== b.dataset.nama; });
    document.querySelectorAll(".pilih button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
  });
});
"""


def berkas_lama(revisi: str, ruang: Path) -> None:
    """Keluarkan folder template dari revisi Git tertentu ke ``ruang``."""
    arsip = subprocess.run(["git", "archive", revisi, "app/templates"], cwd=BASE_DIR,
                           capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(ruang)], input=arsip.stdout, check=True)


def konteks_siswa(siswa: dict) -> dict:
    """Konteks standar seperti yang dikirim ``app/web.py:render`` untuk siswa."""
    from starlette.requests import Request

    from app import auth, online, services
    from app import web as modul_web

    pengguna = auth.SessionUser(id=1, username=str(siswa.get("nisn") or ""), nama=siswa.get("nama") or "Siswa",
                                role=auth.ROLE_SISWA, student_id=int(siswa["id"]),
                                nisn=siswa.get("nisn"), rombel=siswa.get("rombel"))
    permintaan = Request({
        "type": "http", "method": "GET", "path": "/portal", "query_string": b"",
        "headers": [], "scheme": "http", "server": ("banding", 80), "client": ("127.0.0.1", 1),
    })
    return {
        "request": permintaan,
        "user": pengguna,
        "profil": services.school_profile(),
        "nav": modul_web.nav_items(pengguna),
        "nav_grup": modul_web.nav_grup(pengguna),
        "current_path": "/portal",
        "msg": "", "msg_level": "ok",
        "page_title": "Beranda Saya",
        "peringatan_online": online.peringatan_aman(pengguna),
        "mode_vercel": False,
        "siswa": siswa,
        "kelengkapan": _kelengkapan_siswa(siswa),
        "ekskul": services.student_ekskul(siswa["id"]),
        "pendaftaran_ekskul": services.pendaftaran_siswa(siswa["id"]),
        "pengajuan": services.pengajuan_siswa(int(siswa["id"]), limit=5),
        "dokumen": services.dokumen_terbaru(int(siswa["id"])),
        "dokumen_jenis": services.DOKUMEN_JENIS,
        # Halaman Kegiatan (lama & baru) memakai kunci berikut.
        "diikuti": services.student_ekskul(siswa["id"]),
        "tersedia": services.list_ekskul(aktif_only=True),
        "pendaftaran": {item["ekskul_id"]: item
                        for item in services.pendaftaran_siswa(siswa["id"])},
        "status_label": services.PENDAFTARAN_LABEL,
        "grup_field": modul_web.field_groups(),
        "pengajuan_aktif": services.pengajuan_aktif(),
        "agama_options": services.AGAMA_OPTIONS,
        "dokumen_max_mb": 5,
        "wajib_dokumen": services.pengajuan_dokumen_wajib(),
        "dokumen_lengkap": services.dokumen_lengkap(int(siswa["id"]))[0],
        "dokumen_kurang": services.dokumen_lengkap(int(siswa["id"]))[1],
    }


def _kelengkapan_siswa(siswa: dict) -> dict:
    from app.routers.portal_routes import _kelengkapan

    return _kelengkapan(siswa)


def _sisipkan_css(isi: str, css: str) -> str:
    """Ganti app.css dengan isi berkasnya supaya HTML lama tetap tampil apa adanya."""
    if "</head>" in isi and "<style>" not in isi:
        isi = isi.replace("</head>", f"<style>\n{css}\n</style>\n</head>", 1)
    return isi


def main() -> int:
    parser = argparse.ArgumentParser(description="Bandingkan tampilan lama vs sekarang")
    parser.add_argument("--revisi", default="abcc66f^",
                        help="Revisi Git tampilan LAMA (bawaan: abcc66f^, yaitu sebelum ronde 28)")
    parser.add_argument("--nisn", default="", help="NISN yang dipakai (bawaan: siswa contoh pertama)")
    parser.add_argument("--keluaran", default="pratinjau", help="Folder hasil (bawaan: pratinjau)")
    args = parser.parse_args()

    from app import db, services
    from app import web as modul_web

    if args.nisn:
        siswa = services.get_student_by_nisn(args.nisn)
    else:
        baris = db.query_one(
            """SELECT s.nisn FROM students s
               LEFT JOIN ekskul_members m ON m.student_id = s.id
               WHERE s.nisn IS NOT NULL AND s.nisn <> ''
               ORDER BY (m.id IS NOT NULL) DESC, (s.rombel LIKE '%7%') DESC, s.nama LIMIT 1""")
        siswa = services.get_student_by_nisn(baris["nisn"]) if baris else None
    if siswa is None:
        print("[!] Tidak ada siswa di basis data ini (impor berkas contoh dulu).")
        return 1

    tujuan = BASE_DIR / args.keluaran
    tujuan.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sm-lama-") as ruang:
        ruang_lama = Path(ruang)
        try:
            berkas_lama(args.revisi, ruang_lama)
        except subprocess.CalledProcessError as galat:
            print(f"[!] Gagal mengambil revisi {args.revisi!r} dari Git: {galat}")
            return 1

        from jinja2 import FileSystemLoader

        lingkungan = modul_web.templates.env
        loader_asli = lingkungan.loader
        css_app = (BASE_DIR / "app/static/css/app.css").read_text(encoding="utf-8")
        konteks = konteks_siswa(siswa)
        print(f"[i] Membandingkan revisi lama {args.revisi} dengan kode sekarang "
              f"untuk {siswa['nama']} ({siswa['nisn']})")
        try:
            lingkungan.loader = FileSystemLoader(str(ruang_lama / "app/templates"))
            for nama, templat, berkas_lama_nama, berkas_baru, judul in HALAMAN:
                isi = lingkungan.get_template(templat).render(**konteks)
                isi = _sisipkan_css(isi, css_app)
                (tujuan / berkas_lama_nama).write_text(isi, encoding="utf-8")
                ada_baru = (tujuan / berkas_baru).exists()
                print(f"[OK] lama → {berkas_lama_nama} ({len(isi) // 1024} KB)"
                      + ("" if ada_baru else f"  [!] {berkas_baru} belum ada — "
                         f"jalankan scripts/pratinjau_tampilan.py dulu"))
        finally:
            lingkungan.loader = loader_asli

    _tulis_banding(tujuan, args.revisi)
    print(f"[OK] halaman pembanding → {args.keluaran}/bandingkan.html")
    return 0


def _tulis_banding(tujuan: Path, revisi: str) -> None:
    bagian = []
    tombol = []
    for i, (nama, _templat, berkas_lama_nama, berkas_baru, judul) in enumerate(HALAMAN):
        tombol.append(f'<button type="button" data-nama="{nama}" aria-pressed="{"true" if i == 0 else "false"}">'
                      f"{judul}</button>")
        bagian.append(f"""<section class="pasangan" data-nama="{nama}"{'' if i == 0 else ' hidden'}>
  <figure><figcaption class="lama">Tampilan lama (sebelum ronde 28) — {judul}</figcaption>
    <iframe src="{berkas_lama_nama}" title="Lama: {judul}" loading="lazy"></iframe></figure>
  <figure><figcaption class="baru">Tampilan sekarang (ruang siswa) — {judul}</figcaption>
    <iframe src="{berkas_baru}" title="Baru: {judul}" loading="lazy"></iframe></figure>
</section>""")
    isi = f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bandingkan tampilan siswa — lama vs sekarang</title>
<style>{_CSS_BANDING}</style></head>
<body>
<header>
  <h1>Tampilan siswa: lama ⇄ sekarang</h1>
  <p>Kiri = halaman siswa sebagaimana adanya <strong>sebelum</strong> ronde 28 (mengikuti
  kerangka petugas: sidebar, tabel, tulisan kecil). Kanan = halaman <strong>sekarang</strong>
  (ruang siswa: menu bawah besar, huruf lebih besar, bahasa sederhana). Isi datanya sama —
  hanya cara menyajikannya yang berbeda. Pratinjau ini dibuat dari template sungguhan
  (revisi lama diambil dari Git <code>{revisi}</code>) supaya penilaiannya tidak menebak.</p>
</header>
<div class="pilih" role="group" aria-label="Pilih halaman">{''.join(tombol)}</div>
{''.join(bagian)}
<script>{_JS_BANDING}</script>
</body></html>
"""
    (tujuan / "bandingkan.html").write_text(isi, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
