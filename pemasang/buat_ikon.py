#!/usr/bin/env python3
"""Membuat ikon ``bodap.ico`` (dan ``bodap.png``) tanpa pustaka luar.

Ikonnya dipakai untuk berkas ``bodap.exe``, pintasan desktop «SM», dan jendela pemasang.
Gambarnya sederhana dan sengaja dibuat dari hitungan piksel sendiri: kotak biru bergradasi
dengan sudut membulat, berisi „buku" putih bergaris biru. Tidak ada berkas biner di repo —
ikon dibuat saat pembangunan paket.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

UKURAN = (16, 24, 32, 48, 64, 128, 256)

BIRU_ATAS = (46, 122, 240)      # #2E7AF0
BIRU_BAWAH = (13, 58, 158)      # #0D3A9E
PUTIH = (255, 255, 255)
GARIS = (32, 96, 200)


def _campur(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))     # type: ignore[return-value]


def _dalam_sudut_bulat(x: float, y: float, w: float, h: float, r: float) -> bool:
    """Titik (x, y) di dalam kotak bersudut membulat berukuran w×h, jari-jari r."""
    if x < 0 or y < 0 or x > w or y > h:
        return False
    cx = min(max(x, r), w - r)
    cy = min(max(y, r), h - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def gambar(ukuran: int) -> list[list[tuple[int, int, int, int]]]:
    """Piksel RGBA (baris demi baris) untuk satu ukuran ikon."""
    s = ukuran
    radius = max(2.0, s * 0.22)
    tepi = s * 0.06                      # bingkai luar tipis
    # „buku" putih di tengah
    buku_kiri, buku_kanan = s * 0.24, s * 0.76
    buku_atas, buku_bawah = s * 0.20, s * 0.80
    buku_r = max(1.0, s * 0.04)
    garis_tebal = max(1.0, s * 0.055)
    baris: list[list[tuple[int, int, int, int]]] = []
    for y in range(s):
        baris_piksel = []
        for x in range(s):
            px, py = x + 0.5, y + 0.5
            # latar kotak biru bergradasi + sedikit bayangan tepi
            if _dalam_sudut_bulat(px, py, s - 1, s - 1, radius):
                t = y / max(1, s - 1)
                dasar = _campur(BIRU_ATAS, BIRU_BAWAH, t)
                tepi_gelap = 0.0
                if (_dalam_sudut_bulat(px, py, s - 1, s - 1, radius)
                        and not _dalam_sudut_bulat(px, py, s - 1 - tepi, s - 1 - tepi,
                                                   radius - tepi * 0.6)):
                    tepi_gelap = 0.25
                warna = _campur(dasar, (0, 0, 0), tepi_gelap)
                alpha = 255
                # halaman putih
                if _dalam_sudut_bulat(px - buku_kiri, py - buku_atas,
                                      buku_kanan - buku_kiri, buku_bawah - buku_atas, buku_r):
                    warna = PUTIH
                    # garis-garis biru di halaman
                    rel = (py - buku_atas) / max(1.0, buku_bawah - buku_atas)
                    for posisi in (0.30, 0.50, 0.70):
                        if abs(rel - posisi) < (garis_tebal / (buku_bawah - buku_atas)) / 2:
                            if (buku_kiri + (buku_kanan - buku_kiri) * 0.18
                                    < px
                                    < buku_kanan - (buku_kanan - buku_kiri) * 0.18):
                                warna = GARIS
                baris_piksel.append((warna[0], warna[1], warna[2], alpha))
            else:
                baris_piksel.append((0, 0, 0, 0))
        baris.append(baris_piksel)
    return baris


def _bmp_ikon(baris: list[list[tuple[int, int, int, int]]]) -> bytes:
    """Data gambar DIB (BMP) untuk satu ukuran, seperti yang diminta format ICO."""
    s = len(baris)
    kepala = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0, s * s * 4, 0, 0, 0, 0)
    piksel = bytearray()
    for y in range(s - 1, -1, -1):                       # BMP disusun dari bawah ke atas
        for b, g, r, a in baris[y]:
            piksel += bytes((b, g, r, a))
    topeng_baris = ((s + 31) // 32) * 4
    topeng = bytes(topeng_baris * s)                     # semua nol = tidak ada piksel luaran
    return kepala + bytes(piksel) + topeng


def _png(baris: list[list[tuple[int, int, int, int]]]) -> bytes:
    """PNG sederhana (RGBA) — dipakai untuk pratinjau/dokumen."""
    s = len(baris)
    mentah = bytearray()
    for y in range(s):
        mentah.append(0)
        for r, g, b, a in baris[y]:
            mentah += bytes((r, g, b, a))

    def potongan(jenis: bytes, isi: bytes) -> bytes:
        return (struct.pack(">I", len(isi)) + jenis + isi
                + struct.pack(">I", zlib.crc32(jenis + isi) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + potongan(b"IHDR", struct.pack(">IIBBBBB", s, s, 8, 6, 0, 0, 0))
            + potongan(b"IDAT", zlib.compress(bytes(mentah), 9))
            + potongan(b"IEND", b""))


def buat_ico(ukuran: tuple[int, ...] = UKURAN) -> bytes:
    gambar_semua = [(s, _bmp_ikon(gambar(s))) for s in ukuran]
    kepala = struct.pack("<HHH", 0, 1, len(gambar_semua))
    entri = b""
    data = b""
    posisi = len(kepala) + 16 * len(gambar_semua)
    for s, isi in gambar_semua:
        entri += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s,
                             0, 0, 1, 32, len(isi), posisi)
        posisi += len(isi)
        data += isi
    return kepala + entri + data


def main(argv: list[str] | None = None) -> int:
    tujuan_ico = Path(argv[0]) if argv else Path(__file__).resolve().parent / "bodap.ico"
    tujuan_png = tujuan_ico.with_suffix(".png")
    tujuan_ico.write_bytes(buat_ico())
    tujuan_png.write_bytes(_png(gambar(256)))
    print(f"Ikon dibuat: {tujuan_ico} ({tujuan_ico.stat().st_size / 1024:.1f} KB) "
          f"dan {tujuan_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
