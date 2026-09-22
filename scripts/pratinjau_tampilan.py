#!/usr/bin/env python3
"""Buat **pratinjau tampilan** (HTML statis) dari halaman siswa, tanpa PC sekolah.

Halaman dibuat dari aplikasi yang sama (dirender langsung oleh aplikasi), lalu
disimpan sebagai berkas HTML mandiri: CSS & JS disisipkan, dan tautan antar
halaman diarahkan ke berkas pratinjaunya. Gunanya: menilai tampilan yang dilihat
siswa (dan memamerkannya ke guru/kepala sekolah) tanpa harus memasang aplikasi.

Pemakaian::

    python scripts/pratinjau_tampilan.py                    # siswa contoh pertama
    python scripts/pratinjau_tampilan.py --nisn 3900000009  # siswa tertentu
    python scripts/pratinjau_tampilan.py --keluaran pratinjau

Cara menyajikannya ke peramban::

    python -m http.server 8090 --directory pratinjau        # buka http://localhost:8090

Catatan: berkas hasil **berisi data siswa** (dari basis data yang dipakai) — jangan
dibagikan ke luar sekolah dan jangan dimasukkan ke Git (folder ``pratinjau/``
sudah diabaikan).
"""

from __future__ import annotations

import argparse
import asyncio
import html
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

HALAMAN = (
    ("/login", "masuk.html", "Halaman masuk (petugas / siswa / pembina)"),
    ("/portal", "beranda.html", "Beranda siswa"),
    ("/portal/profil", "dataku.html", "Dataku (data lengkap)"),
    ("/portal/ekstrakurikuler", "kegiatan.html", "Kegiatan / klub"),
    ("/portal/pengajuan", "perbaikan.html", "Minta perbaikan data"),
)


def _baca_statis(nama: str) -> str:
    return (BASE_DIR / "app" / "static" / nama).read_text(encoding="utf-8")


def _sisipkan_statis(isi: str, css: dict[str, str], js: str) -> str:
    """Ganti tautan /static/... dengan isi berkasnya supaya HTML mandiri."""
    gabung = "\n".join(f"/* ==== {nama} ==== */\n{kode}" for nama, kode in css.items())
    # Ganti dengan fungsi (bukan string) supaya garis miring di dalam CSS/JS
    # tidak diperlakukan sebagai kode pengganti oleh re.sub.
    isi = re.sub(r'<link rel="stylesheet" href="[^"]*app\.css[^"]*">',
                 lambda _m: f"<style>\n{gabung}\n</style>", isi)
    if 'name="viewport"' in isi and "<style>" not in isi:
        isi = isi.replace("</head>", f"<style>\n{gabung}\n</style>\n</head>", 1)
    isi = re.sub(r'<script src="[^"]*app\.js[^"]*" defer></script>',
                 lambda _m: f"<script>\n{js}\n</script>", isi)
    return isi


def _arahkan_tautan(isi: str) -> str:
    """Tautan antar halaman → berkas pratinjaunya; tautan lain dibuat mati."""
    for jalur, berkas, _ in HALAMAN:
        pola = re.compile(r'href="' + re.escape(jalur) + r'(#[^"]*)?"')
        isi = pola.sub(lambda _m, b=berkas: f'href="{b}"', isi)
    # sisa tautan internal (mis. /logout, /portal/dokumen/3) tidak bisa diklik di
    # pratinjau statis → dijadikan penanda saja supaya tidak menuju halaman galat.
    isi = re.sub(r'href="/(?!/)[^"]*"', 'href="#"', isi)
    isi = isi.replace("<form method=\"post\"", "<form onsubmit=\"return false\" method=\"post\"")
    return isi


def _index(judul: str, catatan: str, hasil: list[tuple[str, str, str]]) -> str:
    kartu = "\n".join(
        f'<a class="kartu" href="{berkas}"><strong>{html.escape(judul_h)}</strong>'
        f'<span>{html.escape(ket)}</span></a>'
        for _, berkas, ket in hasil
        for judul_h in [ket]
    )
    return f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(judul)}</title>
<style>
 body {{ font-family: "Segoe UI", system-ui, Roboto, Arial, sans-serif; background:#f3f7fd; color:#17233d;
        margin:0; padding:1.5rem clamp(1rem,4vw,2.5rem); }}
 h1 {{ font-size:1.4rem; margin:0 0 .3rem; }}
 p.ket {{ color:#5b6884; margin:0 0 1.3rem; max-width:64ch; }}
 .daftar {{ display:grid; gap:.8rem; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); max-width:900px; }}
 .kartu {{ display:block; padding:1rem 1.1rem; background:#fff; border:1px solid #e6edf8; border-radius:16px;
          text-decoration:none; color:inherit; box-shadow:0 6px 20px rgba(23,35,61,.06); }}
 .kartu strong {{ display:block; font-size:1.05rem; }}
 .kartu span {{ color:#5b6884; font-size:.88rem; }}
 .catatan {{ margin-top:1.5rem; max-width:70ch; color:#5b6884; font-size:.88rem; }}
 a.kartu:hover {{ border-color:#cfe0ff; }}
</style></head>
<body>
<h1>{html.escape(judul)}</h1>
<p class="ket">{html.escape(catatan)}</p>
<div class="daftar">{kartu}</div>
<p class="catatan">Catatan: ini pratinjau tampilan (berkas HTML yang sudah jadi), jadi tombol
simpan/unggah sengaja tidak berfungsi — untuk mencoba alurnya, jalankan aplikasi SM yang asli.
Pratinjau dibuat otomatis dengan <code>python scripts/pratinjau_tampilan.py</code>.</p>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Buat pratinjau HTML halaman siswa (statis)")
    parser.add_argument("--nisn", default="", help="NISN siswa yang dipakai (bawaan: siswa pertama)")
    parser.add_argument("--keluaran", default="pratinjau", help="Folder hasil (bawaan: pratinjau)")
    args = parser.parse_args()

    import httpx

    from app import db, services
    from app.main import app

    siswa = None
    if args.nisn:
        siswa = services.get_student_by_nisn(args.nisn)
        if siswa is None:
            print(f"[!] NISN {args.nisn} tidak ada di basis data ini.")
            return 1
    else:
        # Utamakan siswa kelas 7 yang sudah ikut kegiatan, supaya pratinjaunya
        # benar-benar menggambarkan halaman anak kelas 7 (bukan halaman kosong).
        baris = db.query_one(
            """SELECT s.nisn FROM students s
               LEFT JOIN ekskul_members m ON m.student_id = s.id
               WHERE s.nisn IS NOT NULL AND s.nisn <> ''
               ORDER BY (m.id IS NOT NULL) DESC, (s.rombel LIKE '%7%') DESC, s.nama
               LIMIT 1""")
        if baris is None:
            print("[!] Belum ada siswa di basis data ini. Impor berkas contoh dulu "
                  "(lihat scripts/buat_data_contoh.py).")
            return 1
        siswa = services.get_student_by_nisn(baris["nisn"])

    css = {"app.css": _baca_statis("css/app.css"), "portal.css": _baca_statis("css/portal.css")}
    js = _baca_statis("js/app.js")

    async def buat() -> int:
        tujuan = BASE_DIR / args.keluaran
        tujuan.mkdir(parents=True, exist_ok=True)
        transport = httpx.ASGITransport(app=app)
        hasil: list[tuple[str, str, str]] = []
        async with httpx.AsyncClient(transport=transport, base_url="http://pratinjau") as klien:
            masuk = await klien.post("/login", data={"mode": "siswa", "nisn": siswa["nisn"]},
                                     follow_redirects=False)
            if masuk.status_code != 303:
                print(f"[!] Login siswa gagal (status {masuk.status_code}).")
                return 1
            print(f"[i] Masuk sebagai {siswa['nama']} ({siswa['nisn']})")
            # Halaman masuk diambil tanpa sesi (klien terpisah) — kalau memakai
            # klien yang sudah masuk, /login hanya mengalihkan ke beranda.
            async with httpx.AsyncClient(transport=transport, base_url="http://pratinjau") as tamu:
                for jalur, berkas, ket in HALAMAN:
                    if jalur != "/login":
                        continue
                    jawab = await tamu.get(jalur)
                    if jawab.status_code == 200:
                        isi = _arahkan_tautan(_sisipkan_statis(jawab.text, css, js))
                        (tujuan / berkas).write_text(isi, encoding="utf-8")
                        hasil.append((jalur, berkas, ket))
                        print(f"[OK] {jalur:26} → {args.keluaran}/{berkas} ({len(isi) // 1024} KB)")
            for jalur, berkas, ket in HALAMAN:
                jawab = await klien.get(jalur)
                if jalur == "/login" or jawab.status_code != 200:
                    if jalur != "/login":
                        print(f"[!] {jalur} → {jawab.status_code} (dilewati)")
                    continue
                isi = _arahkan_tautan(_sisipkan_statis(jawab.text, css, js))
                (tujuan / berkas).write_text(isi, encoding="utf-8")
                hasil.append((jalur, berkas, ket))
                print(f"[OK] {jalur:26} → {args.keluaran}/{berkas} ({len(isi) // 1024} KB)")

        (tujuan / "index.html").write_text(
            _index(f"Pratinjau tampilan siswa — {services.school_profile()['nama']}",
                   "Buka satu per satu untuk melihat halaman siswa seperti yang dilihat anak "
                   "kelas 7 (bisa juga dibuka dari HP).", hasil),
            encoding="utf-8",
        )
        print(f"[OK] daftar halaman → {args.keluaran}/index.html")
        return 0

    return asyncio.run(buat())


if __name__ == "__main__":
    sys.exit(main())
