#!/usr/bin/env python3
"""Periksa **kerapian susunan** halaman (bukan sekadar "ada atau tidak").

Latar belakang (ronde 34 → 35): halaman kegiatan siswa terlihat berantakan —
kartu kegiatan memakai kelas ``.pl-aksi`` (yang sebenarnya **baris mendatar**)
padahal isinya blok bertumpuk, sehingga tombol melayang ke luar kartu. Masalah
seperti ini tidak ketahuan oleh uji "status 200" atau "teksnya ada": yang salah
adalah *susunan*.

Alat ini memeriksa empat hal yang bisa dibuktikan dari berkas:

1. **Tag blok di dalam tag sebaris** (``<span><div>…``, ``<a><p>…``, ``<span><form>…``).
   Peramban memperbaiki sendiri HTML seperti itu dengan menutup tag di luar dugaan,
   jadi letaknya meleset — penyebab umum tampilan «janggal».
2. **Wadah baris berisi blok**: elemen berkelas ``.pl-aksi`` (baris mendatar) tidak
   boleh berisi ``<div>/<p>/<ul>/<dl>``; isinya harus sebaris (span/strong/button/form).
3. **Kelas yang dipakai bersama tapi saling bertabrakan**: ``.pl-kegiatan`` tidak
   boleh dipakai bersama ``.pl-aksi``; ``.pl-kegiatan`` wajib ``flex-direction: column``.
4. **Teks yang bisa melimpah**: elemen baris (``.pl-aksi``, ``.pl-mini-baris``,
   ``.pl-baris``, ``.notif-pop``) harus memakai ``flex-wrap`` atau ``min-width: 0``
   pada anak yang berisi teks panjang.

Pemakaian::

    python scripts/cek_tampilan.py            # halaman siswa & halaman masuk
"""

from __future__ import annotations

import asyncio
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

SEBARIS = {"span", "a", "strong", "small", "b", "i", "em", "label", "button", "code", "time"}
BLOK = {"div", "p", "ul", "ol", "dl", "dt", "dd", "table", "form", "section", "article",
        "header", "footer", "nav", "h1", "h2", "h3", "h4", "details", "summary", "fieldset",
        "li", "figure", "blockquote", "aside", "main"}

HALAMAN_SISWA = ("/portal", "/portal/profil", "/portal/ekstrakurikuler", "/portal/pengajuan")


class PeriksaSusunan(HTMLParser):
    """Kumpulkan pelanggaran susunan pada satu halaman."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tumpukan: list[dict] = []
        self.blok_dalam_sebaris: list[str] = []
        self.baris_berisi_blok: list[str] = []
        self.kelas_ganda: list[str] = []

    # -- pembantu ---------------------------------------------------------- #
    def _kelas(self, attrs) -> list[str]:
        for nama, nilai in attrs:
            if nama == "class":
                return (nilai or "").split()
        return []

    def _jejak(self) -> str:
        potong = [f"{t['tag']}.{'.'.join(t['kelas'])}" if t["kelas"] else t["tag"]
                  for t in self.tumpukan[-3:]]
        return " > ".join(potong)

    def handle_starttag(self, tag, attrs):
        kelas = self._kelas(attrs)
        # 1) tag blok di dalam tag sebaris
        if tag in BLOK:
            for atas in self.tumpukan:
                if atas["tag"] in SEBARIS:
                    self.blok_dalam_sebaris.append(
                        f"<{atas['tag']}{' class=' + chr(34) + ' '.join(atas['kelas']) + chr(34) if atas['kelas'] else ''}>"
                        f" berisi <{tag}>  ({self._jejak()})")
                    break
        # 2) wadah baris (.pl-aksi) yang berisi blok
        if tag in {"div", "p", "ul", "ol", "dl", "table", "form", "details"}:
            for atas in self.tumpukan:
                if "pl-aksi" in atas["kelas"]:
                    self.baris_berisi_blok.append(f".pl-aksi berisi <{tag}>  ({self._jejak()})")
                    break
        # 3) kelas yang bertabrakan
        if "pl-aksi" in kelas and "pl-kegiatan" in kelas:
            self.kelas_ganda.append("elemen memakai .pl-aksi bersama .pl-kegiatan")
        if tag not in {"br", "img", "input", "meta", "link", "hr", "source", "path", "circle",
                       "rect", "line", "polyline", "polygon", "ellipse", "use"}:
            self.tumpukan.append({"tag": tag, "kelas": kelas})

    def handle_endtag(self, tag):
        for i in range(len(self.tumpukan) - 1, -1, -1):
            if self.tumpukan[i]["tag"] == tag:
                del self.tumpukan[i:]
                break


def periksa_css(teks_css: str) -> list[str]:
    """Aturan CSS yang wajib benar supaya susunan kartu tidak meleset."""
    masalah: list[str] = []
    bersih = re.sub(r"/\*.*?\*/", "", teks_css, flags=re.S)

    def aturan(nama: str) -> str:
        potongan = []
        for m in re.finditer(r"([^{}]*)\{([^}]*)\}", bersih):
            if re.search(rf"(^|[\s,]){re.escape(nama)}([\s,{{:]|$)", m.group(1)):
                potongan.append(m.group(2))
        return " ".join(potongan)

    if ".pl-kegiatan" in bersih and "flex-direction: column" not in aturan(".pl-kegiatan"):
        masalah.append("portal.css: .pl-kegiatan belum `flex-direction: column` "
                       "(isinya harus bertumpuk: kepala → jadwal → tombol)")
    for wadah, wajib in ((".pl-aksi", ("flex-wrap", "min-width: 0")),
                         (".pl-mini-baris", ("flex-wrap", "min-width: 0")),
                         (".pl-baris", ("flex-wrap", "overflow-wrap", "min-width: 0")),
                         (".pl-unggah-pilih", ("flex-wrap", "min-width: 0")),
                         (".pl-kirim", ("flex-wrap",)),
                         (".pl-kirim-tombol", ("flex-wrap",)),
                         (".notif-pop", ("max-width",))):
        if wadah not in bersih:
            continue          # kelas ini tidak ada di berkas ini (mis. .notif-pop di app.css)
        isi = aturan(wadah)
        if not any(k in isi for k in wajib):
            masalah.append(f"{wadah} belum memakai salah satu dari {wajib} "
                           "sehingga teks panjang bisa melimpah keluar kotaknya")
    return masalah


async def periksa_halaman() -> tuple[list[str], int]:
    import httpx

    from app.main import app

    masalah: list[str] = []
    transport = httpx.ASGITransport(app=app)
    jumlah = 0
    async with httpx.AsyncClient(transport=transport, base_url="http://cek",
                                 follow_redirects=True) as klien:
        # Halaman masuk (tanpa sesi) lebih dulu.
        for jalur in ("/login?mode=siswa", "/login"):
            halaman = await klien.get(jalur)
            jumlah += 1
            pemeriksa = PeriksaSusunan()
            pemeriksa.feed(halaman.text)
            for temuan_kecil in (pemeriksa.blok_dalam_sebaris + pemeriksa.baris_berisi_blok
                                 + pemeriksa.kelas_ganda):
                masalah.append(f"{jalur}: {temuan_kecil}")
        # Halaman siswa (perlu sesi siswa).
        await klien.post("/login", data={"mode": "siswa", "nisn": "3900000009"})
        for jalur in HALAMAN_SISWA:
            halaman = await klien.get(jalur)
            assert halaman.status_code == 200, f"{jalur} -> {halaman.status_code}"
            jumlah += 1
            pemeriksa = PeriksaSusunan()
            pemeriksa.feed(halaman.text)
            for temuan_kecil in (pemeriksa.blok_dalam_sebaris + pemeriksa.baris_berisi_blok
                                 + pemeriksa.kelas_ganda):
                masalah.append(f"{jalur}: {temuan_kecil}")
        await klien.post("/logout")
    return masalah, jumlah


def main() -> int:
    masalah_css: list[str] = []
    for nama in ("app/static/css/portal.css", "app/static/css/app.css"):
        masalah_css += periksa_css((BASE / nama).read_text(encoding="utf-8"))

    masalah_html, jumlah = asyncio.run(periksa_halaman())
    semua = masalah_css + masalah_html
    print(f"Diperiksa {jumlah} halaman (halaman masuk + ruang siswa).")
    if semua:
        for temuan in semua:
            print(f"  MASALAH {temuan}")
        return 1
    print("  Susunan rapi: tidak ada tag blok di dalam tag sebaris, tidak ada kartu baris "
          "yang berisi blok, kartu kegiatan bertumpuk (column), dan wadah teks panjang "
          "memakai pembungkus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
