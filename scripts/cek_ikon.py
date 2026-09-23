#!/usr/bin/env python3
"""Ukur & periksa ikon SVG di ``app/templates/_macros.html`` (makro ``icon``).

Latar belakang (masukan sekolah ronde 33): *«icon-nya seperti tidak pas»*. Setiap
ikon garis digambar di kanvas 24×24, jadi supaya semuanya terlihat rapi ada aturan
yang bisa diperiksa mesin:

1. **Kotak aman** — gambar hanya boleh berada di 2,0–22,0 (tepi luar hanya untuk
   stroke), supaya tidak menempel/terpotong tepi kotak.
2. **Titik pusat** — pusat gambar harus (12, 12) dengan toleransi ±0,8 supaya ikon
   tidak miring ke kiri/kanan atau naik/turun saat dipasang di tombol/kartu.
3. **Ukuran** — sisi terpanjang ≥ 14 supaya ikon tidak terlihat kekecilan.
4. **Nama ikon** — setiap nama yang dipakai template harus ada di makro; kalau
   tidak, makro menampilkan penanda ``icon-kosong`` (segi empat kecil).

Geometri dihitung dari primitif (circle, rect, line, polyline) dan dari ``d``
path termasuk busur (arc) yang disampel 64 titik, jadi pengukurannya nyata —
bukan menebak dari angka di dalam string.

Pemakaian::

    python scripts/cek_ikon.py            # laporan lengkap
"""

from __future__ import annotations

import math
import re
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
BERKAS_MAKRO = AKAR / "app/templates/_macros.html"
FOLDER_TEMPLATE = AKAR / "app/templates"

ANGKA = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")
PERINTAH = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)")

BATAS_AMAN = 2.0          # koordinat gambar minimal/maksimal (kanvas 0–24)
TOLERANSI_PUSAT = 0.8
UKURAN_MINIMAL = 14.0


# --------------------------------------------------------------------------- #
# Pembacaan geometri
# --------------------------------------------------------------------------- #
def _busur(x1: float, y1: float, rx: float, ry: float, rot: float,
           besar: bool, searah: bool, x2: float, y2: float) -> list[tuple[float, float]]:
    """Titik-titik di sepanjang busur SVG (algoritma konversi endpoint→center)."""
    if rx == 0 or ry == 0:
        return [(x1, y1), (x2, y2)]
    phi = math.radians(rot % 360)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        akar = math.sqrt(lam)
        rx, ry = rx * akar, ry * akar
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    koef = 0.0 if den == 0 else math.sqrt(max(0.0, num / den))
    if besar == searah:
        koef = -koef
    cxp = koef * rx * y1p / ry
    cyp = -koef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def sudut(ux: float, uy: float, vx: float, vy: float) -> float:
        titik = (ux * vx + uy * vy) / (math.hypot(ux, uy) * math.hypot(vx, vy) or 1)
        tanda = 1 if (ux * vy - uy * vx) >= 0 else -1
        return tanda * math.acos(max(-1.0, min(1.0, titik)))

    u = ((x1p - cxp) / rx, (y1p - cyp) / ry)
    v = ((-x1p - cxp) / rx, (-y1p - cyp) / ry)
    t1 = sudut(1, 0, *u)
    delta = sudut(*u, *v)
    if not searah and delta > 0:
        delta -= 2 * math.pi
    elif searah and delta < 0:
        delta += 2 * math.pi
    langkah = 64
    keluar = []
    for i in range(langkah + 1):
        t = t1 + delta * i / langkah
        px, py = rx * math.cos(t), ry * math.sin(t)
        keluar.append((cx + cos_p * px - sin_p * py, cy + sin_p * px + cos_p * py))
    return keluar


def titik_path(d: str) -> list[tuple[float, float]]:
    """Kumpulkan titik absolut dari sebuah ``d`` path (termasuk titik kendali & busur)."""
    keluar: list[tuple[float, float]] = []
    x = y = 0.0
    x_awal = y_awal = 0.0
    for huruf, badan in PERINTAH.findall(d):
        n = [float(v) for v in ANGKA.findall(badan)]
        kecil = huruf.islower()
        if huruf in "Mm":
            for i in range(0, len(n) - 1, 2):
                x, y = (n[i], n[i + 1]) if not kecil else (x + n[i], y + n[i + 1])
                keluar.append((x, y))
            x_awal, y_awal = x, y
        elif huruf in "Ll":
            for i in range(0, len(n) - 1, 2):
                x, y = (n[i], n[i + 1]) if not kecil else (x + n[i], y + n[i + 1])
                keluar.append((x, y))
        elif huruf in "Hh":
            for v in n:
                x = v if not kecil else x + v
                keluar.append((x, y))
        elif huruf in "Vv":
            for v in n:
                y = v if not kecil else y + v
                keluar.append((x, y))
        elif huruf in "Cc":
            for i in range(0, len(n) - 5, 6):
                titik = [(n[i], n[i + 1]), (n[i + 2], n[i + 3]), (n[i + 4], n[i + 5])]
                if kecil:
                    titik = [(x + a, y + b) for a, b in titik]
                keluar += titik
                x, y = titik[-1]
        elif huruf in "SsQqTt":
            for i in range(0, len(n) - 3, 4):
                titik = [(n[i], n[i + 1]), (n[i + 2], n[i + 3])]
                if kecil:
                    titik = [(x + a, y + b) for a, b in titik]
                keluar += titik
                x, y = titik[-1]
        elif huruf in "Aa":
            for i in range(0, len(n) - 6, 7):
                rx, ry, rot, besar, searah, px, py = n[i:i + 7]
                px, py = (px, py) if not kecil else (x + px, y + py)
                keluar += _busur(x, y, abs(rx), abs(ry), rot,
                                 bool(int(besar)), bool(int(searah)), px, py)
                x, y = px, py
        elif huruf in "Zz":
            x, y = x_awal, y_awal
            keluar.append((x, y))
    return keluar


class Kotak:
    """Kotak batas gambar (tanpa dataclass supaya aman dimuat lewat importlib)."""

    def __init__(self, x0: float, x1: float, y0: float, y1: float) -> None:
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1

    @property
    def pusat(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    @property
    def lebar(self) -> float:
        return self.x1 - self.x0

    @property
    def tinggi(self) -> float:
        return self.y1 - self.y0

    def __repr__(self) -> str:  # memudahkan saat diperiksa manual
        return f"Kotak({self.x0:.1f}, {self.x1:.1f}, {self.y0:.1f}, {self.y1:.1f})"


def kotak_kode(kode: str) -> Kotak | None:
    """Kotak batas sebuah potongan SVG (gambar satu ikon), dari titik hasil sampel."""
    xs: list[float] = []
    ys: list[float] = []
    for polilin in polylinien(kode):
        for px, py in polilin:
            xs.append(px)
            ys.append(py)
    if xs:
        return Kotak(min(xs), max(xs), min(ys), max(ys))



    def tambah(daftar: list[tuple[float, float]]) -> None:
        for px, py in daftar:
            xs.append(px)
            ys.append(py)

    for m in re.finditer(r'<circle[^>]*cx="([\d.\-]+)"[^>]*cy="([\d.\-]+)"[^>]*r="([\d.\-]+)"', kode):
        cx, cy, r = map(float, m.groups())
        tambah([(cx - r, cy - r), (cx + r, cy + r)])
    for m in re.finditer(r'<ellipse[^>]*cx="([\d.\-]+)"[^>]*cy="([\d.\-]+)"'
                         r'[^>]*rx="([\d.\-]+)"[^>]*ry="([\d.\-]+)"', kode):
        cx, cy, rx, ry = map(float, m.groups())
        tambah([(cx - rx, cy - ry), (cx + rx, cy + ry)])
    for m in re.finditer(r'<rect[^>]*x="([\d.\-]+)"[^>]*y="([\d.\-]+)"'
                         r'[^>]*width="([\d.\-]+)"[^>]*height="([\d.\-]+)"', kode):
        x, y, w, h = map(float, m.groups())
        tambah([(x, y), (x + w, y + h)])
    for m in re.finditer(r'<line[^>]*x1="([\d.\-]+)"[^>]*y1="([\d.\-]+)"'
                         r'[^>]*x2="([\d.\-]+)"[^>]*y2="([\d.\-]+)"', kode):
        x1, y1, x2, y2 = map(float, m.groups())
        tambah([(x1, y1), (x2, y2)])
    for m in re.finditer(r'<(?:polyline|polygon)[^>]*points="([^"]+)"', kode):
        nilai = [float(v) for v in ANGKA.findall(m.group(1))]
        tambah(list(zip(nilai[0::2], nilai[1::2])))
    for m in re.finditer(r'<path[^>]*d="([^"]+)"', kode):
        tambah(titik_path(m.group(1)))
    if not xs:
        return None
    return Kotak(min(xs), max(xs), min(ys), max(ys))


def _sampel_bezier(p0, p1, p2, p3, langkah: int = 24):
    keluar = []
    for i in range(1, langkah + 1):
        t = i / langkah
        u = 1 - t
        keluar.append((
            u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
            u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
        ))
    return keluar


def polylinien(kode: str) -> list[list[tuple[float, float]]]:
    """Semua garis gambar pada potongan SVG ikon (kurva & busur sudah disampel)."""
    keluar: list[list[tuple[float, float]]] = []

    for m in re.finditer(r'<circle[^>]*cx="([\d.\-]+)"[^>]*cy="([\d.\-]+)"[^>]*r="([\d.\-]+)"', kode):
        cx, cy, r = map(float, m.groups())
        keluar.append([(cx + r * math.cos(2 * math.pi * i / 64),
                        cy + r * math.sin(2 * math.pi * i / 64)) for i in range(65)])
    for m in re.finditer(r'<rect[^>]*x="([\d.\-]+)"[^>]*y="([\d.\-]+)"'
                         r'[^>]*width="([\d.\-]+)"[^>]*height="([\d.\-]+)"', kode):
        x, y, w, h = map(float, m.groups())
        sudut = float(re.search(r'rx="([\d.\-]+)"', m.group(0)).group(1)) if 'rx=' in m.group(0) else 0.0
        if sudut <= 0:
            keluar.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])
        else:
            r = min(sudut, w / 2, h / 2)
            titik = []
            for cx, cy, mulai in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0),
                                  (x + r, y + h - r, 90), (x + r, y + r, 180)):
                for i in range(13):
                    a = math.radians(mulai + i * 90 / 12)
                    titik.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            keluar.append(titik + [titik[0]])
    for m in re.finditer(r'<line[^>]*x1="([\d.\-]+)"[^>]*y1="([\d.\-]+)"'
                         r'[^>]*x2="([\d.\-]+)"[^>]*y2="([\d.\-]+)"', kode):
        x1, y1, x2, y2 = map(float, m.groups())
        keluar.append([(x1, y1), (x2, y2)])
    for m in re.finditer(r'<(?:polyline|polygon)[^>]*points="([^"]+)"', kode):
        nilai = [float(v) for v in ANGKA.findall(m.group(1))]
        keluar.append(list(zip(nilai[0::2], nilai[1::2])))

    for m in re.finditer(r'<path[^>]*d="([^"]+)"', kode):
        d = m.group(1)
        kini: list[tuple[float, float]] = []
        x = y = 0.0
        x0 = y0 = 0.0
        x_ctrl = y_ctrl = None      # titik kendali sebelumnya (untuk S/T)
        perintah_awal = None
        def tutup():
            nonlocal kini
            if kini:
                keluar.append(kini)
                kini = []

        for huruf, badan in PERINTAH.findall(d):
            n = [float(v) for v in ANGKA.findall(badan)]
            kecil = huruf.islower()
            if huruf in "Mm":
                tutup()
                for i in range(0, len(n) - 1, 2):
                    x, y = (n[i], n[i + 1]) if not kecil else (x + n[i], y + n[i + 1])
                    kini.append((x, y))
                x0, y0 = x, y
                perintah_awal = "M"
            elif huruf in "Ll":
                for i in range(0, len(n) - 1, 2):
                    x, y = (n[i], n[i + 1]) if not kecil else (x + n[i], y + n[i + 1])
                    kini.append((x, y))
            elif huruf in "Hh":
                for v in n:
                    x = v if not kecil else x + v
                    kini.append((x, y))
            elif huruf in "Vv":
                for v in n:
                    y = v if not kecil else y + v
                    kini.append((x, y))
            elif huruf in "Cc":
                for i in range(0, len(n) - 5, 6):
                    titik = [(n[i], n[i + 1]), (n[i + 2], n[i + 3]), (n[i + 4], n[i + 5])]
                    if kecil:
                        titik = [(x + a, y + b) for a, b in titik]
                    kini += _sampel_bezier((x, y), titik[0], titik[1], titik[2])
                    x_ctrl, y_ctrl = titik[1]
                    x, y = titik[2]
            elif huruf in "Ss":
                for i in range(0, len(n) - 3, 4):
                    kendali1 = (n[i], n[i + 1])
                    akhir = (n[i + 2], n[i + 3])
                    if kecil:
                        kendali1 = (x + kendali1[0], y + kendali1[1])
                        akhir = (x + akhir[0], y + akhir[1])
                    if x_ctrl is not None:
                        kendali1 = (2 * x - x_ctrl, 2 * y - y_ctrl)
                    kini += _sampel_bezier((x, y), kendali1, kendali1, akhir)
                    x_ctrl, y_ctrl = kendali1
                    x, y = akhir
            elif huruf in "Qq":
                for i in range(0, len(n) - 3, 4):
                    kendali = (n[i], n[i + 1])
                    akhir = (n[i + 2], n[i + 3])
                    if kecil:
                        kendali = (x + kendali[0], y + kendali[1])
                        akhir = (x + akhir[0], y + akhir[1])
                    k1 = (x + 2 / 3 * (kendali[0] - x), y + 2 / 3 * (kendali[1] - y))
                    k2 = (akhir[0] + 2 / 3 * (kendali[0] - akhir[0]),
                          akhir[1] + 2 / 3 * (kendali[1] - akhir[1]))
                    kini += _sampel_bezier((x, y), k1, k2, akhir)
                    x_ctrl, y_ctrl = kendali
                    x, y = akhir
            elif huruf in "Aa":
                for i in range(0, len(n) - 6, 7):
                    rx, ry, rot, besar, searah, px, py = n[i:i + 7]
                    px, py = (px, py) if not kecil else (x + px, y + py)
                    kini += _busur(x, y, abs(rx), abs(ry), rot, bool(int(besar)),
                                   bool(int(searah)), px, py)
                    x, y = px, py
            elif huruf in "Zz":
                if kini:
                    kini.append(kini[0])
                    tutup()
                x, y = x0, y0
        tutup()
    return keluar



# --------------------------------------------------------------------------- #
# Membaca makro
# --------------------------------------------------------------------------- #
def baca_makro(teks: str | None = None) -> dict[str, str]:
    """Kembalikan ``{nama_ikon: potongan_svg}`` dari makro ``icon``."""
    teks = teks if teks is not None else BERKAS_MAKRO.read_text(encoding="utf-8")
    blok = teks.split("{% macro icon(", 1)[1].split("{% endmacro %}", 1)[0]
    potong = re.split(r'\{%-?\s*(?:if|elif)\s+nama\s*==\s*"([a-z0-9_\-]+)"\s*-?%\}', blok)
    hasil: dict[str, str] = {}
    for i in range(1, len(potong), 2):
        nama = potong[i]
        badan = potong[i + 1]
        for pemisah in ("{%- elif", "{%- else", "{%- endif"):
            badan = badan.split(pemisah)[0]
        hasil[nama] = badan
    return hasil


def ukur_semua(teks: str | None = None) -> dict[str, Kotak]:
    return {nama: kotak_kode(kode) for nama, kode in baca_makro(teks).items() if kotak_kode(kode)}


def periksa_makro(teks: str | None = None) -> list[str]:
    """Daftar masalah geometri ikon (kosong = semua ikon «pas»)."""
    masalah: list[str] = []
    for nama, kode in baca_makro(teks).items():
        kotak = kotak_kode(kode)
        if kotak is None:
            masalah.append(f"{nama}: gambarnya tidak terbaca")
            continue
        px, py = kotak.pusat
        if abs(px - 12) > TOLERANSI_PUSAT or abs(py - 12) > TOLERANSI_PUSAT:
            masalah.append(f"{nama}: pusat gambar ({px:.1f}, {py:.1f}) — seharusnya (12, 12)")
        if (kotak.x0 < BATAS_AMAN or kotak.x1 > 24 - BATAS_AMAN
                or kotak.y0 < BATAS_AMAN or kotak.y1 > 24 - BATAS_AMAN):
            masalah.append(f"{nama}: keluar kotak aman ({BATAS_AMAN:g}–{24 - BATAS_AMAN:g}) "
                           f"— x {kotak.x0:.1f}–{kotak.x1:.1f}, y {kotak.y0:.1f}–{kotak.y1:.1f}")
        if max(kotak.lebar, kotak.tinggi) < UKURAN_MINIMAL:
            masalah.append(f"{nama}: terlalu kecil ({kotak.lebar:.1f}×{kotak.tinggi:.1f}, "
                           f"minimal {UKURAN_MINIMAL:g})")
    return masalah


def periksa_pemakaian(folder: Path = FOLDER_TEMPLATE) -> tuple[set[str], list[str]]:
    """(nama yang dipakai template, masalah nama ikon yang tidak ada di makro)."""
    tersedia = set(baca_makro())
    dipakai: set[str] = set()
    masalah: list[str] = []
    for berkas in sorted(folder.rglob("*.html")):
        for nomor, baris in enumerate(berkas.read_text(encoding="utf-8").splitlines(), start=1):
            for m in re.finditer(r"""icon\(\s*['"]([a-z0-9_\-]+)['"]""", baris):
                nama = m.group(1)
                dipakai.add(nama)
                if nama not in tersedia:
                    masalah.append(f"{berkas.relative_to(AKAR)}:{nomor} memakai ikon «{nama}» "
                                   f"yang tidak ada di makro")
    return dipakai, masalah


def laporan() -> tuple[bool, list[str]]:
    baris: list[str] = []
    kotak = ukur_semua()
    masalah = periksa_makro()
    dipakai, masalah_nama = periksa_pemakaian()
    for nama, k in sorted(kotak.items()):
        baris.append(f"  {nama:9} pusat ({k.pusat[0]:4.1f},{k.pusat[1]:4.1f})  "
                     f"{k.lebar:4.1f}×{k.tinggi:4.1f}")
    tak_terpakai = sorted(set(kotak) - dipakai)
    if tak_terpakai:
        baris.append(f"  (belum dipakai di template: {', '.join(tak_terpakai)})")
    baris.append("")
    baris += [f"  MASALAH {m}" for m in masalah + masalah_nama]
    if not masalah and not masalah_nama:
        baris.append(f"  {len(kotak)} ikon & {len(dipakai)} nama pemakaian: semua pas "
                     f"(pusat 12,12 · kotak aman · ukuran ≥{UKURAN_MINIMAL:g} · nama dikenal)")
    return (not masalah and not masalah_nama), baris


if __name__ == "__main__":
    ok, baris = laporan()
    print("\n".join(baris))
    raise SystemExit(0 if ok else 1)
