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
    ("/login?mode=siswa", "masuk.html", "Halaman masuk — tab Siswa (yang dilihat anak)"),
    ("/portal", "beranda.html", "Beranda siswa"),
    ("/portal/profil", "dataku.html", "Dataku (data lengkap)"),
    ("/portal/ekstrakurikuler", "kegiatan.html", "Kegiatan / klub"),
    ("/portal/pengajuan", "perbaikan.html", "Minta perbaikan data"),
)

# Halaman petugas (opsional, perlu sandi admin bawaan): ikut dipratinjaukan supaya
# perubahan tata letak — mis. kartu jumlah siswa yang dipindah ke atas tabel —
# bisa dilihat tanpa menjalankan aplikasi.
HALAMAN_PETUGAS = (
    ("/", "dasbor.html", "Dasbor petugas"),
    ("/data-siswa", "data-siswa.html", "Data Siswa — kartu jumlah di atas tabel"),
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
    if (BASE_DIR / "pratinjau" / "bandingkan.html").exists():
        kartu += ('<a class="kartu" href="bandingkan.html"><strong>Lama \u21c4 Sekarang</strong>'
                  '<span>Bandingkan tampilan sebelum ronde 28 dengan tampilan sekarang '
                  '(berdampingan)</span></a>')
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


def _galeri_ikon() -> str:
    """Galeri semua ikon + hasil ukurannya (bukti ikon «pas»), untuk dilihat sekolah."""
    import importlib.util

    from app import web as web_uji

    jalur = Path(__file__).resolve().parent / "cek_ikon.py"
    spesifikasi = importlib.util.spec_from_file_location("cek_ikon", jalur)
    modul = importlib.util.module_from_spec(spesifikasi)
    sys.modules["cek_ikon"] = modul
    spesifikasi.loader.exec_module(modul)

    templat = web_uji.templates.env.from_string(
        '{% from "_macros.html" import icon %}{{ icon(nama, kelas) }}')

    def svg(nama: str, kelas: str = "") -> str:
        return templat.render(nama=nama, kelas=kelas)

    kotak = modul.ukur_semua()
    baris = []
    for nama in sorted(kotak):
        k = kotak[nama]
        px, py = k.pusat
        pas = abs(px - 12) <= 0.8 and abs(py - 12) <= 0.8
        baris.append(
            f'<tr><td class="nama">{html.escape(nama)}</td>'
            f'<td class="tengah"><span class="panggung">{svg(nama)}</span></td>'
            f'<td class="tengah"><button class="btn btn-outline btn-sm">{svg(nama)} Contoh</button></td>'
            f'<td class="tengah"><span class="keping">{svg(nama)}</span></td>'
            f'<td>Contoh teks {svg(nama)} sejajar dengan ikon</td>'
            f'<td class="angka">{px:.1f}, {py:.1f}</td>'
            f'<td class="angka">{k.lebar:.1f} &times; {k.tinggi:.1f}</td>'
            f'<td>{"pas" if pas else "PERIKSA"}</td></tr>')

    halaman = """<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Galeri ikon — SM</title>
<link rel="stylesheet" href="app-galeri.css">
<style>
 body { font-family: "Segoe UI", system-ui, Roboto, Arial, sans-serif; background:#f3f7fd; color:#17233d;
        margin:0; padding:1.5rem clamp(1rem,4vw,2.5rem); }
 h1 { font-size:1.35rem; margin:0 0 .3rem; }
 p.ket { color:#5b6884; margin:0 0 1.1rem; max-width:78ch; }
 table { border-collapse:collapse; background:#fff; border:1px solid #e6edf8; border-radius:14px;
         overflow:hidden; box-shadow:0 6px 20px rgba(23,35,61,.06); }
 th, td { padding:.5rem .7rem; border-bottom:1px solid #eef2fa; font-size:.88rem; text-align:left;
          vertical-align:middle; }
 th { background:#f7faff; font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; color:#5b6884; }
 td.nama, td.angka { font-variant-numeric:tabular-nums; }
 td.nama { font-weight:700; }
 td.tengah { text-align:center; }
 .panggung { display:inline-grid; place-items:center; width:40px; height:40px; border:1px dashed #cfe0ff;
             border-radius:10px; color:#2563eb; }
 .keping { display:inline-grid; place-items:center; width:44px; height:44px; border-radius:12px;
           background:#eff5ff; color:#2563eb; }
 .panggung svg, .keping svg { width:22px; height:22px; }
 .catatan { margin-top:1.2rem; max-width:80ch; color:#5b6884; font-size:.88rem; }
 code { background:#eef2fa; padding:.05rem .3rem; border-radius:5px; }
</style></head>
<body>
<h1>Galeri ikon — __JUMLAH__ ikon</h1>
<p class="ket">Masukan sekolah: «icon-nya seperti tidak pas». Semua ikon garis digambar pada kanvas
<strong>24&times;24</strong> dengan titik pusat <strong>(12, 12)</strong>, di dalam kotak aman 2–22, dan
sisi terpanjangnya minimal 14 — jadi bobotnya seragam dan tidak ada yang menempel tepi. Dua kolom
terakhir adalah <em>hasil pengukuran otomatis</em> (<code>scripts/cek_ikon.py</code>), bukan perkiraan.</p>
<table>
<thead><tr><th>Nama</th><th>Ukuran wajar (22 px)</th><th>Di dalam tombol</th><th>Di keping 44 px</th>
<th>Sejajar teks</th><th>Pusat</th><th>Lebar &times; tinggi</th><th>Hasil</th></tr></thead>
<tbody>
__BARIS__
</tbody></table>
<p class="catatan">Ikon yang sama dipakai di halaman aplikasi. Pemeriksaannya ikut berjalan pada
<code>python scripts/cek_sistem.py</code> (blok «Kerapian ikon»), jadi ikon baru yang tidak pas
langsung ketahuan sebelum dipakai di PC sekolah.</p>
</body></html>
"""
    return halaman.replace("__JUMLAH__", str(len(kotak))).replace("__BARIS__", "\n".join(baris))

def _demo_notifikasi() -> str:
    """Bilah atas petugas dengan lonceng notifikasi (tertutup & terbuka).

    Peringatan «aplikasi dapat dibuka dari internet» tidak lagi memenuhi halaman;
    contoh ini memperlihatkan bentuk barunya supaya sekolah bisa menilai.
    """
    from app import online, web as web_uji

    pesan = online.pemeriksaan_singkat() or [
        "Kata sandi admin masih bawaan (admin123) — ganti di Pengaturan → Pengguna.",
        "Login siswa masih memakai NISN saja — nyalakan pengaman tanggal lahir.",
    ]
    env = web_uji.templates.env
    ikon = env.from_string('{% from "_macros.html" import icon %}{{ icon(nama) }}')

    def popup(buka: bool) -> str:
        daftar = "".join(f"<li>{html.escape(teks)}</li>" for teks in pesan)
        tanda = "" if buka else " hidden"
        return (
            f'<div class="notif-pop"{tanda}>'
            f'<strong class="notif-judul">{ikon.render(nama="warning")} Aplikasi dapat dibuka '
            "dari internet</strong>"
            f"<ul>{daftar}</ul>"
            '<a class="btn btn-outline btn-sm btn-block">Buka Pengaturan → Sistem → Aman Online</a>'
            "</div>"
        )

    def bilah(buka: bool) -> str:
        return (
            '<div class="bilah-demo">'
            f'<a class="btn btn-primary btn-sm">{ikon.render(nama="upload")} Impor Berkas</a>'
            '<div class="notif"><button type="button" class="notif-tombol" aria-expanded="false">'
            f'{ikon.render(nama="bell")}<span class="notif-titik">{len(pesan)}</span></button>'
            f"{popup(buka)}</div>"
            '<div class="avatar">A</div>'
            "</div>"
        )

    return f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Notifikasi bilah atas — SM</title>
<link rel="stylesheet" href="app-galeri.css">
<style>
 body {{ font-family: "Segoe UI", system-ui, Roboto, Arial, sans-serif; background:#f3f7fd; color:#17233d;
        margin:0; padding:1.5rem clamp(1rem,4vw,2.5rem); }}
 h1 {{ font-size:1.3rem; margin:0 0 .3rem; }}
 h2 {{ font-size:1rem; margin:1.6rem 0 .5rem; color:#5b6884; }}
 p.ket {{ color:#5b6884; margin:0 0 .4rem; max-width:78ch; }}
 .bilah-demo {{ display:flex; align-items:center; gap:.5rem; padding:.85rem 1.4rem; background:#fff;
                border:1px solid #e6edf8; border-radius:14px; box-shadow:0 6px 20px rgba(23,35,61,.06);
                min-height:76px; }}
 .bilah-demo .notif {{ margin-left:auto; }}
 .bilah-demo .avatar {{ margin-left:0; }}
 code {{ background:#eef2fa; padding:.05rem .3rem; border-radius:5px; }}
</style></head>
<body>
<h1>Peringatan penting → lonceng notifikasi</h1>
<p class="ket">Masukan sekolah: spanduk kuning <em>«Aplikasi sedang dapat dibuka dari internet»</em> yang
memenuhi halaman dihapus. Peringatannya sekarang berupa <strong>lonceng kecil di samping tombol
«Impor Berkas»</strong> dengan angka jumlah peringatan; isinya muncul saat lonceng diklik
(klik di luar atau <code>Esc</code> menutup). Lonceng hanya tampil bila aplikasi memang sedang
dibuka dari internet — saat lokal, bilah atas bersih.</p>

<h2>1. Keadaan biasa (popup tertutup)</h2>
{bilah(False)}

<h2>2. Setelah lonceng diklik</h2>
{bilah(True)}

<p class="ket" style="margin-top:1.4rem">Isi peringatannya tetap sama dengan yang dulu ditulis di spanduk,
dan tautan ke <code>Pengaturan → Sistem → Aman Online</code> tidak hilang. Tombol <strong>«+ Siswa»</strong>
sudah dihapus dari bilah atas karena data siswa hanya masuk lewat impor Dapodik.</p>
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
                    if not jalur.startswith("/login"):
                        continue
                    jawab = await tamu.get(jalur)
                    if jawab.status_code == 200:
                        isi = _arahkan_tautan(_sisipkan_statis(jawab.text, css, js))
                        (tujuan / berkas).write_text(isi, encoding="utf-8")
                        hasil.append((jalur, berkas, ket))
                        print(f"[OK] {jalur:26} → {args.keluaran}/{berkas} ({len(isi) // 1024} KB)")
            for jalur, berkas, ket in HALAMAN:
                jawab = await klien.get(jalur)
                if jalur.startswith("/login") or jawab.status_code != 200:
                    if not jalur.startswith("/login"):
                        print(f"[!] {jalur} → {jawab.status_code} (dilewati)")
                    continue
                isi = _arahkan_tautan(_sisipkan_statis(jawab.text, css, js))
                (tujuan / berkas).write_text(isi, encoding="utf-8")
                hasil.append((jalur, berkas, ket))
                print(f"[OK] {jalur:26} → {args.keluaran}/{berkas} ({len(isi) // 1024} KB)")

        # --- halaman petugas (opsional) ---------------------------------------- #
        async with httpx.AsyncClient(transport=transport, base_url="http://pratinjau") as petugas:
            masuk_petugas = await petugas.post(
                "/login", data={"mode": "staff", "username": "admin", "password": "admin123"},
                follow_redirects=False)
            if masuk_petugas.status_code in (303, 307):
                for jalur, berkas, ket in HALAMAN_PETUGAS:
                    jawab = await petugas.get(jalur)
                    if jawab.status_code != 200:
                        print(f"[!] {jalur} → {jawab.status_code} (dilewati)")
                        continue
                    isi = _arahkan_tautan(_sisipkan_statis(jawab.text, css, js))
                    (tujuan / berkas).write_text(isi, encoding="utf-8")
                    hasil.append((jalur, berkas, ket))
                    print(f"[OK] {jalur:26} → {args.keluaran}/{berkas} ({len(isi) // 1024} KB)")
            else:
                print("[i] Halaman petugas dilewati (sandi admin bukan bawaan).")

        # --- demo notifikasi: bentuk baru peringatan «online» ------------------- #
        (tujuan / "notifikasi.html").write_text(_demo_notifikasi(), encoding="utf-8")
        hasil.append(("/notifikasi", "notifikasi.html",
                      "Peringatan online → lonceng notifikasi (dulu spanduk kuning)"))
        print(f"[OK] demo notifikasi          → {args.keluaran}/notifikasi.html")

        # --- galeri ikon: bukti semua ikon «pas» -------------------------------- #
        (tujuan / "app-galeri.css").write_text(css["app.css"], encoding="utf-8")
        (tujuan / "ikon.html").write_text(_galeri_ikon(), encoding="utf-8")
        hasil.append(("/ikon", "ikon.html", "Galeri semua ikon + hasil ukur (uji perataan)"))
        print(f"[OK] galeri ikon              → {args.keluaran}/ikon.html")

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
