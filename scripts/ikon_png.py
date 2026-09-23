#!/usr/bin/env python3
"""Gambar semua ikon menjadi **berkas PNG** supaya bisa diperiksa dengan mata.

Masukan sekolah seperti «icon-nya seperti tidak pas» sulit dijawab hanya dengan
angka. Alat ini merender ikon dari makro ``icon`` menjadi satu lembar PNG
(beberapa ukuran: 22 px, 44 px, dan versi besar untuk melihat bentuknya), sehingga
bentuk ikon bisa dilihat langsung — tanpa perlu peramban.

Pemakaian::

    .venv/bin/python scripts/ikon_png.py                 # → pratinjau/ikon.png
    .venv/bin/python scripts/ikon_png.py --skala 2       # lebih besar

Catatan: butuh Pillow (``.venv/bin/pip install pillow``) — hanya untuk alat
pengembangan ini, aplikasi SM sendiri tidak memakainya.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def muat_pengukur():
    """Muat scripts/cek_ikon.py (untuk membaca makro & memecah gambar jadi garis)."""
    jalur = Path(__file__).resolve().parent / "cek_ikon.py"
    spesifikasi = importlib.util.spec_from_file_location("cek_ikon", jalur)
    modul = importlib.util.module_from_spec(spesifikasi)
    sys.modules["cek_ikon"] = modul
    spesifikasi.loader.exec_module(modul)
    return modul


def gambar_ikon(gambar, kode: str, kiri: int, atas: int, ukuran: int,
                pensil: float = 1.8, warna=(37, 99, 235)) -> None:
    """Gambar satu ikon (kanvas 24×24) ke ``gambar`` pada kotak ``ukuran`` px.

    ``ukuran`` sudah termasuk penskalaan (supaya hasilnya tidak pecah): gambar
    dibuat 8× lebih besar lalu diperkecil.
    """
    from PIL import Image, ImageDraw

    perbesaran = 8
    sisi = ukuran * perbesaran
    lapis = Image.new("RGBA", (sisi, sisi), (0, 0, 0, 0))
    kuas = ImageDraw.Draw(lapis)
    faktor = sisi / 24.0
    tebal = max(1, round(pensil * faktor))
    for polilin in modul_pengukur.polylinien(kode):
        titik = [(x * faktor, y * faktor) for x, y in polilin]
        if len(titik) < 2:
            continue
        kuas.line(titik, fill=warna + (255,), width=tebal, joint="curve")
        # Ujung garis dibuat bulat seperti stroke-linecap="round" di peramban.
        for px, py in (titik[0], titik[-1]):
            r = tebal / 2
            kuas.ellipse([px - r, py - r, px + r, py + r], fill=warna + (255,))
    lapis = lapis.resize((ukuran, ukuran), Image.LANCZOS)
    gambar.paste(lapis, (kiri, atas), lapis)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render ikon SM menjadi PNG")
    parser.add_argument("--keluaran", default="pratinjau/ikon.png", help="berkas hasil")
    parser.add_argument("--skala", type=int, default=1, help="perbesaran lembar (bawaan 1)")
    args = parser.parse_args()

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[!] Pillow belum dipasang. Jalankan: .venv/bin/pip install pillow")
        return 1

    global modul_pengukur
    modul_pengukur = muat_pengukur()
    ikon = modul_pengukur.baca_makro()
    nama_urut = sorted(ikon)
    kotak = {nama: modul_pengukur.kotak_kode(kode) for nama, kode in ikon.items()}

    kolom = 6
    sel_w, sel_h = 150, 190
    S = max(1, args.skala)
    margin, kepala = 24, 96
    lebar = margin * 2 + kolom * sel_w
    tinggi = kepala + ((len(nama_urut) + kolom - 1) // kolom) * sel_h + margin
    gambar = Image.new("RGB", (lebar * S, tinggi * S), (243, 247, 253))
    kuas = ImageDraw.Draw(gambar)

    font_jalur = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font_tebal_jalur = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    font = ImageFont.truetype(str(font_jalur), 15 * S) if font_jalur.exists() else ImageFont.load_default()
    font_judul = (ImageFont.truetype(str(font_tebal_jalur), 26 * S)
                  if font_tebal_jalur.exists() else font)
    font_kecil = ImageFont.truetype(str(font_jalur), 12 * S) if font_jalur.exists() else font

    kuas.text((margin * S, 26 * S), "Ikon SM — dilihat langsung (kanvas 24×24)",
              fill=(23, 35, 61), font=font_judul)
    kuas.text((margin * S, 62 * S),
              "Kiri: ukuran asli 22 px · kanan: 44 px. Angka di bawah: pusat & ukuran gambar "
              "(harus pusat 12,12).",
              fill=(91, 104, 132), font=font_kecil)

    for nomor, nama in enumerate(nama_urut):
        baris, kolom_ke = divmod(nomor, kolom)
        kiri = (margin + kolom_ke * sel_w) * S
        atas = (kepala + baris * sel_h) * S
        kuas.rounded_rectangle([kiri, atas, kiri + (sel_w - 16) * S, atas + (sel_h - 16) * S],
                               radius=16 * S, fill=(255, 255, 255), outline=(230, 237, 248), width=S)
        gambar_ikon(gambar, ikon[nama], (kiri + 20 * S) // S * S, (atas + 22 * S) // S * S,
                    22 * S)
        gambar_ikon(gambar, ikon[nama], kiri + 64 * S, atas + 16 * S, 44 * S)
        gambar_ikon(gambar, ikon[nama], kiri + 26 * S, atas + 74 * S, 66 * S, pensil=1.4)
        k = kotak[nama]
        keterangan = f"pusat {k.pusat[0]:.1f},{k.pusat[1]:.1f} · {k.lebar:.1f}×{k.tinggi:.1f}" if k else "?"
        kuas.text((kiri + 20 * S, atas + 150 * S), nama, fill=(23, 35, 61), font=font)
        kuas.text((kiri + 20 * S, atas + 168 * S), keterangan, fill=(91, 104, 132), font=font_kecil)

    tujuan = BASE / args.keluaran
    tujuan.parent.mkdir(parents=True, exist_ok=True)
    if S > 1:
        gambar = gambar.resize((lebar, tinggi), Image.LANCZOS)
    gambar.save(tujuan)
    print(f"[OK] {len(nama_urut)} ikon → {args.keluaran} ({gambar.width}×{gambar.height} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
