"""Pembaca teks PDF **bawaan SM** — tanpa pustaka tambahan.

Menu TANGCER harus bisa membaca SK definitif berbentuk PDF di komputer sekolah,
sedangkan pustaka ``pypdf`` bisa belum terpasang (pemasangan lama, atau komputer
tanpa internet). Modul ini karena itu **berdiri sendiri**: hanya memakai modul
standar Python (``re``, ``zlib``, ``base64``) untuk mengambil teks — beserta
posisi X/Y tiap potongan — dari berkas PDF biasa.

Yang ditangani:

* struktur objek + tabel xref (dan pemindaian ulang bila xref rusak),
* aliran data terkompresi (FlateDecode) termasuk **object stream** (PDF 1.5 ke atas,
  yang biasa dihasilkan Word/Excel) dan **predictor PNG**,
* penyaring ASCIIHex, ASCII85, dan RunLength,
* huruf sederhana (WinAnsi/MacRoman/Differences) dan huruf gabungan (Type0/Identity-H)
  lewat peta ``ToUnicode`` — inilah yang membuat teks SK terbaca sebagai huruf, bukan angka,
* operator teks: ``Tj``/``TJ``/``'``/``"`` dengan matriks teks (``Td``/``TD``/``Tm``/``T*``)
  dan ``cm``/``q``/``Q``, termasuk teks di dalam Form XObject.

Yang **tidak** dikarang: berkas terenkripsi, hasil pindai (gambar tanpa teks), atau
huruf yang tidak punya peta ``ToUnicode`` dilaporkan apa adanya di ``catatan`` /
``huruf_tak_terbaca`` — bukan diterka.
"""

from __future__ import annotations

import base64
import re
import unicodedata
import zlib
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Sequence

__all__ = ["PdfBacaError", "HasilPdf", "baca_pdf", "ada_pembaca_pypdf"]


class PdfBacaError(RuntimeError):
    """Berkas bukan PDF, rusak, atau isinya tidak bisa diurai."""


# --------------------------------------------------------------------------- #
# Nilai dasar PDF
# --------------------------------------------------------------------------- #
class Nama(str):
    """Nama PDF (mis. ``/FlateDecode``) — disimpan bersama garis miringnya."""

    __slots__ = ()

    def bersih(self) -> str:
        return str(self).lstrip("/")


@dataclass(frozen=True)
class Ref:
    """Rujukan tidak langsung: ``12 0 R``."""

    nomor: int
    generasi: int = 0


@dataclass
class Aliran:
    """Objek aliran: kamus + data mentah."""

    kamus: dict[str, Any]
    mentah: bytes


_SPASI = b"\x00\t\n\x0c\r "
_PEMISAH = b"()<>[]{}/%"


def _angka(teks: bytes) -> int | float:
    try:
        return int(teks)
    except ValueError:
        try:
            return float(teks)
        except ValueError:  # pragma: no cover - pemanggil selalu memberi angka
            return 0


def _lewati(p: bytes, i: int) -> int:
    """Lewati spasi dan komentar (``%`` sampai akhir baris)."""
    n = len(p)
    while i < n:
        c = p[i:i + 1]
        if c in (b" ", b"\t", b"\n", b"\r", b"\f", b"\x00"):
            i += 1
        elif c == b"%":
            j = p.find(b"\n", i)
            i = n if j < 0 else j + 1
        else:
            break
    return i


def _teks_literal(p: bytes, i: int) -> tuple[bytes, int]:
    """Baca teks di dalam ``( … )`` beserta aturan pemisahnya."""
    i += 1                                    # lewati '('
    keluaran = bytearray()
    dalam = 1
    n = len(p)
    while i < n:
        c = p[i]
        if c == 0x5C:                         # garis miring terbalik
            i += 1
            if i >= n:
                break
            d = p[i]
            if d in b"nrtbf":
                keluaran += {0x6E: b"\n", 0x72: b"\r", 0x74: b"\t",
                             0x62: b"\b", 0x66: b"\f"}[d]
                i += 1
            elif d in b"()\\":
                keluaran.append(d)
                i += 1
            elif d == 0x0D:                   # lanjutan baris
                i += 2 if p[i + 1:i + 2] == b"\n" else 1
            elif d == 0x0A:
                i += 1
            elif 0x30 <= d <= 0x37:           # oktal 1–3 angka
                j = i
                while j < n and j - i < 3 and 0x30 <= p[j] <= 0x37:
                    j += 1
                keluaran.append(int(p[i:j], 8) & 0xFF)
                i = j
            else:
                keluaran.append(d)
                i += 1
        elif c == 0x28:
            dalam += 1
            keluaran.append(c)
            i += 1
        elif c == 0x29:
            dalam -= 1
            if not dalam:
                i += 1
                break
            keluaran.append(c)
            i += 1
        else:
            keluaran.append(c)
            i += 1
    return bytes(keluaran), i


def _teks_hex(p: bytes, i: int) -> tuple[bytes, int]:
    """Baca teks heksadesimal ``<00410042>``."""
    j = p.find(b">", i)
    if j < 0:
        raise PdfBacaError("teks heksadesimal PDF tidak ditutup")
    angka = re.sub(rb"[^0-9A-Fa-f]", b"", p[i + 1:j])
    if len(angka) % 2:
        angka += b"0"
    return bytes.fromhex(angka.decode("ascii")), j + 1


def baca_benda(p: bytes, i: int = 0) -> tuple[Any, int]:
    """Baca satu benda PDF (kamus, larik, angka, teks, nama, rujukan)."""
    i = _lewati(p, i)
    if i >= len(p):
        raise PdfBacaError("benda PDF terpotong")
    c = p[i:i + 1]
    if c == b"<":
        if p[i + 1:i + 2] == b"<":
            return _kamus(p, i)
        return _teks_hex(p, i)
    if c == b"(":
        return _teks_literal(p, i)
    if c == b"[":
        larik: list[Any] = []
        i = _lewati(p, i + 1)
        while i < len(p) and p[i:i + 1] != b"]":
            benda, i = baca_benda(p, i)
            larik.append(benda)
            i = _lewati(p, i)
        return larik, i + 1
    if c == b"/":
        j = i + 1
        while j < len(p) and p[j:j + 1] not in _PEMISAH and p[j:j + 1] not in _SPASI:
            j += 1
        return Nama(p[i:j].decode("latin-1")), j
    if c in b"+-.0123456789":
        j = i
        while j < len(p) and p[j:j + 1] in b"+-.0123456789eE":
            j += 1
        teks = p[i:j]
        m = re.match(rb"\s+(\d{1,5})\s+R(?![A-Za-z])", p[j:j + 48])
        if m is not None and re.fullmatch(rb"\d+", teks.strip() or b"x"):
            return Ref(int(teks), int(m.group(1))), j + m.end()
        return _angka(teks), j
    m = re.match(rb"[A-Za-z]+", p[i:i + 12])
    if m:
        kata = m.group(0)
        if kata == b"true":
            return True, i + len(kata)
        if kata == b"false":
            return False, i + len(kata)
        if kata == b"null":
            return None, i + len(kata)
        return Nama("/" + kata.decode("latin-1")), i + len(kata)
    raise PdfBacaError(f"benda PDF tidak dikenal di posisi {i}")


def _kamus(p: bytes, i: int) -> tuple[dict[str, Any], int]:
    """Baca kamus ``<< … >>`` menjadi dict Python."""
    hasil: dict[str, Any] = {}
    i = _lewati(p, i + 2)
    while i < len(p) and p[i:i + 2] != b">>":
        if p[i:i + 1] == b"/":
            kunci, i = baca_benda(p, i)
        else:                                        # kamus tidak sah — hentikan
            break
        i = _lewati(p, i)
        if p[i:i + 2] == b">>":                      # nama tanpa nilai
            hasil[str(kunci)] = None
            break
        nilai, i = baca_benda(p, i)
        hasil[str(kunci)] = nilai
        i = _lewati(p, i)
    return hasil, i + 2


# --------------------------------------------------------------------------- #
# Penyaring data & predictor
# --------------------------------------------------------------------------- #
def _predictor_png(data: bytes, kolom: int, warna: int, bpc: int) -> bytes:
    """Lepas predictor PNG (dipakai aliran xref/objek di PDF 1.5+)."""
    lebar = max(1, (kolom * warna * bpc + 7) // 8)
    bpp = max(1, (warna * bpc + 7) // 8)
    keluaran = bytearray()
    sebelumnya = bytearray(lebar)
    i = 0
    while i + 1 + lebar <= len(data):
        jenis = data[i]
        baris = bytearray(data[i + 1:i + 1 + lebar])
        i += 1 + lebar
        if jenis == 1:                                # Sub
            for j in range(bpp, lebar):
                baris[j] = (baris[j] + baris[j - bpp]) & 0xFF
        elif jenis == 2:                              # Up
            for j in range(lebar):
                baris[j] = (baris[j] + sebelumnya[j]) & 0xFF
        elif jenis == 3:                              # Average
            for j in range(lebar):
                kiri = baris[j - bpp] if j >= bpp else 0
                baris[j] = (baris[j] + ((kiri + sebelumnya[j]) >> 1)) & 0xFF
        elif jenis == 4:                              # Paeth
            for j in range(lebar):
                kiri = baris[j - bpp] if j >= bpp else 0
                atas = sebelumnya[j]
                kiri_atas = sebelumnya[j - bpp] if j >= bpp else 0
                pk = kiri + atas - kiri_atas
                pa, pb, pc = abs(pk - kiri), abs(pk - atas), abs(pk - kiri_atas)
                prediksi = kiri if (pa <= pb and pa <= pc) else (atas if pb <= pc else kiri_atas)
                baris[j] = (baris[j] + prediksi) & 0xFF
        keluaran += baris
        sebelumnya = baris
    return bytes(keluaran)


def _predictor_tiff(data: bytes, kolom: int, warna: int, bpc: int) -> bytes:
    """Lepas predictor TIFF (jenis 2) — umum untuk data 8 bit."""
    if bpc != 8:
        return data
    lebar = kolom * warna
    keluaran = bytearray()
    for mulai in range(0, len(data) - lebar + 1, lebar):
        baris = bytearray(data[mulai:mulai + lebar])
        for j in range(warna, lebar):
            baris[j] = (baris[j] + baris[j - warna]) & 0xFF
        keluaran += baris
    return bytes(keluaran)


def _terapkan_predictor(data: bytes, parms: Any, ambil: Any) -> bytes:
    p = ambil(parms)
    if not isinstance(p, dict):
        return data
    try:
        jenis = int(ambil(p.get("/Predictor")) or 1)
    except (TypeError, ValueError):
        return data
    if jenis <= 1:
        return data
    kolom = int(ambil(p.get("/Columns")) or 1)
    warna = int(ambil(p.get("/Colors")) or 1)
    bpc = int(ambil(p.get("/BitsPerComponent")) or 8)
    if jenis >= 10:
        return _predictor_png(data, kolom, warna, bpc)
    return _predictor_tiff(data, kolom, warna, bpc)


def _satu_penyaring(nama: str, data: bytes, catatan: list[str]) -> bytes:
    if nama in ("FlateDecode", "Fl"):
        try:
            return zlib.decompress(data)
        except zlib.error:
            try:
                return zlib.decompress(data, -15)
            except zlib.error as exc:
                catatan.append(f"aliran FlateDecode tidak bisa dibuka ({exc})")
                return b""
    if nama in ("ASCIIHexDecode", "AHx"):
        angka = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
        if len(angka) % 2:
            angka += b"0"
        return bytes.fromhex(angka.decode("ascii", "ignore"))
    if nama in ("ASCII85Decode", "A85"):
        try:
            return base64.a85decode(re.sub(rb"\s", b"", data), adobe=True, ignorechars=b"z")
        except Exception:                              # noqa: BLE001
            try:
                return base64.a85decode(re.sub(rb"\s", b"", data), ignorechars=b"z")
            except Exception as exc:                   # noqa: BLE001
                catatan.append(f"aliran ASCII85Decode tidak bisa dibuka ({exc})")
                return b""
    if nama in ("RunLengthDecode", "RL"):
        keluaran = bytearray()
        i = 0
        while i < len(data):
            pjg = data[i]
            i += 1
            if pjg == 128:
                break
            if pjg < 128:
                keluaran += data[i:i + pjg + 1]
                i += pjg + 1
            else:
                if i < len(data):
                    keluaran += bytes([data[i]]) * (257 - pjg)
                i += 1
        return bytes(keluaran)
    if nama in ("LZWDecode", "LZW"):
        catatan.append("aliran LZWDecode belum didukung pembaca bawaan")
        return b""
    if nama in ("DCTDecode", "JPXDecode", "CCITTFaxDecode", "JBIG2Decode"):
        catatan.append(f"aliran {nama} berisi gambar (bukan teks)")
        return b""
    catatan.append(f"penyaring {nama} belum dikenal pembaca bawaan")
    return b""


def buka_aliran(mentah: bytes, kamus: dict[str, Any], ambil: Any,
                catatan: list[str]) -> bytes:
    """Terapkan seluruh penyaring (``/Filter``) beserta predictornya."""
    saring = ambil(kamus.get("/Filter"))
    if saring is None:
        return mentah
    daftar = saring if isinstance(saring, list) else [saring]
    parms = ambil(kamus.get("/DecodeParms"))
    if parms is None:
        parms = ambil(kamus.get("/DP"))
    daftar_parms = parms if isinstance(parms, list) else [parms] * len(daftar)
    data = mentah
    for nomor, satu in enumerate(daftar):
        nama = ambil(satu)
        nama = nama.bersih() if isinstance(nama, Nama) else str(nama).lstrip("/")
        data = _satu_penyaring(nama, data, catatan)
        if nomor < len(daftar_parms):
            data = _terapkan_predictor(data, daftar_parms[nomor], ambil)
    return data


# --------------------------------------------------------------------------- #
# Nama huruf (untuk font yang memakai /Differences)
# --------------------------------------------------------------------------- #
_ALIAS_GLIF = {
    "space": " ", "hyphen": "-", "period": ".", "comma": ",", "colon": ":",
    "semicolon": ";", "slash": "/", "backslash": "\\", "parenleft": "(",
    "parenright": ")", "bracketleft": "[", "bracketright": "]", "braceleft": "{",
    "braceright": "}", "quotesingle": "'", "quotedbl": '"', "endash": "\u2013",
    "emdash": "\u2014", "bullet": "\u2022", "asterisk": "*", "plus": "+",
    "equal": "=", "underscore": "_", "percent": "%", "ampersand": "&",
    "numbersign": "#", "at": "@", "dollar": "$", "exclam": "!", "question": "?",
    "less": "<", "greater": ">", "bar": "|", "zero": "0", "one": "1", "two": "2",
    "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "adieresis": "\u00e4", "odieresis": "\u00f6", "udieresis": "\u00fc",
    "germandbls": "\u00df", "oslash": "\u00f8", "ae": "\u00e6", "ccedilla": "\u00e7",
    "degree": "\u00b0", "section": "\u00a7", "paragraph": "\u00b6", "sterling": "\u00a3",
    "euro": "\u20ac", "yen": "\u00a5", "cent": "\u00a2",
}
_AKSEN = {
    "grave": "\u0300", "acute": "\u0301", "circumflex": "\u0302", "tilde": "\u0303",
    "dieresis": "\u0308", "ring": "\u030a", "cedilla": "\u0327", "macron": "\u0304",
    "breve": "\u0306", "ogonek": "\u0328", "caron": "\u030c", "dotaccent": "\u0307",
    "hungarumlaut": "\u030b",
}


def huruf_dari_nama(nama: Any) -> str:
    """Ubah nama glif PDF (``Aacute``, ``uni00E9``) menjadi huruf sesungguhnya."""
    if not nama:
        return ""
    dasar = str(nama).split(".")[0]
    if dasar in _ALIAS_GLIF:
        return _ALIAS_GLIF[dasar]
    if len(dasar) == 1:
        return dasar
    m = re.fullmatch(r"u(?:ni)?([0-9A-Fa-f]{4,6})", dasar)
    if m:
        return chr(int(m.group(1), 16))
    for akhiran, gabung in _AKSEN.items():
        if dasar.endswith(akhiran):
            inti = dasar[: -len(akhiran)]
            if len(inti) in (1, 2):
                return unicodedata.normalize("NFC", inti + gabung)
    try:                                               # nama resmi Unicode
        return unicodedata.lookup(dasar.upper())
    except KeyError:
        return ""


# --------------------------------------------------------------------------- #
# Peta ToUnicode (huruf gabungan / Identity-H)
# --------------------------------------------------------------------------- #
_POLA_BFCHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_POLA_BFRANGE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_POLA_HEX = re.compile(rb"<([0-9A-Fa-f\s]*)>")
_POLA_TOKEN_MAP = re.compile(rb"<([0-9A-Fa-f\s]*)>|\[(.*?)\]", re.S)


def _hex_ke_teks(angka: bytes) -> str:
    bersih = re.sub(rb"\s", b"", angka)
    if len(bersih) % 2:
        bersih += b"0"
    try:
        data = bytes.fromhex(bersih.decode("ascii"))
    except ValueError:
        return ""
    if len(data) >= 2 and len(data) % 2 == 0:
        try:
            return data.decode("utf-16-be")
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", "replace")


_HURUF_NOL = "\x00"


def baca_cmap(data: bytes) -> dict[int, str]:
    """Baca peta ``ToUnicode`` PDF (bfchar & bfrange) menjadi {kode: huruf}."""
    peta: dict[int, str] = {}
    for blok in _POLA_BFCHAR.findall(data):
        angka = _POLA_HEX.findall(blok)
        for kode_hex, teks_hex in zip(angka[0::2], angka[1::2]):
            kunci = re.sub(rb"\s", b"", kode_hex)
            if not kunci:
                continue
            peta[int(kunci, 16)] = _hex_ke_teks(teks_hex).replace(_HURUF_NOL, "")
    for blok in _POLA_BFRANGE.findall(data):
        token: list[Any] = []
        for cocok in _POLA_TOKEN_MAP.finditer(blok):
            if cocok.group(1) is not None:
                token.append(("hex", cocok.group(1)))
            else:
                token.append(("larik", _POLA_HEX.findall(cocok.group(2))))
        i = 0
        while i + 1 < len(token):
            if token[i][0] != "hex" or token[i + 1][0] != "hex":
                i += 1
                continue
            awal = int(re.sub(rb"\s", b"", token[i][1]) or b"0", 16)
            akhir = int(re.sub(rb"\s", b"", token[i + 1][1]) or b"0", 16)
            tujuan = token[i + 2] if i + 2 < len(token) else None
            if tujuan is None:
                break
            if tujuan[0] == "hex":
                awal_teks = _hex_ke_teks(tujuan[1]).replace(_HURUF_NOL, "")
                if awal_teks:
                    for langkah, kode in enumerate(range(awal, akhir + 1)):
                        peta[kode] = chr(ord(awal_teks[0]) + langkah) + awal_teks[1:]
                i += 3
            else:
                for langkah, angka in enumerate(tujuan[1]):
                    peta[awal + langkah] = _hex_ke_teks(angka).replace(_HURUF_NOL, "")
                i += 3
    return peta


@dataclass
class Huruf:
    """Cara membaca kode huruf pada satu font.

    Urutan pembacaan untuk huruf sederhana (Type1/TrueType): ``peta`` (ToUnicode dan
    /Differences) lebih dulu, lalu ``dasar`` (penyandi WinAnsi/MacRoman/Standard). Lapisan
    ``dasar`` penting: banyak PDF buatan Word/OpenOffice hanya memetakan beberapa kode di
    ``/Differences`` + ``ToUnicode``, sedangkan huruf lainnya tetap memakai penyandi standar —
    tanpa lapisan ini berkas seperti itu terbaca kosong.
    """

    dua_byte: bool = False
    peta: dict[int, str] | None = None
    penyandi: str = "cp1252"
    lebar: dict[int, float] | None = None
    dasar: dict[int, str] | None = None
    lebar_rata: float = 0.0
    #: lebar bawaan tiap kode (satuan em) bila tidak ada di ``lebar`` — 0,5 em untuk huruf
    #: sederhana, /DW font CID kalau ada
    lebar_bawaan: float = 0.5

    def baca(self, data: bytes) -> tuple[str, int]:
        """Ubah data teks PDF menjadi huruf; kembalikan (teks, jumlah kode gagal)."""
        if self.dua_byte:
            keluaran: list[str] = []
            gagal = 0
            for i in range(0, len(data) - 1, 2):
                kode = (data[i] << 8) | data[i + 1]
                huruf = self.peta.get(kode) if self.peta is not None else None
                if huruf is None:
                    gagal += 1
                    continue
                keluaran.append(huruf)
            return "".join(keluaran), gagal
        keluaran = []
        gagal = 0
        for b in data:
            huruf = self.peta.get(b) if self.peta is not None else None
            if huruf is None and self.dasar is not None:
                huruf = self.dasar.get(b)
            if huruf is None:
                if b < 32 or b == 127:
                    continue
                gagal += 1
                continue
            keluaran.append(huruf)
        return "".join(keluaran), gagal

    def lebar_kode(self, ukuran: float) -> float:
        """Perkiraan lebar satu kode huruf (hanya untuk jarak antar potongan)."""
        return max(0.2, self.lebar_rata or self.lebar_bawaan) * ukuran

    def ukur(self, data: bytes) -> float:
        """Jumlah lebar huruf untuk data teks ini (satuan em, 1 em = ukuran huruf).

        Dipakai menghitung jarak antar potongan — kalau lebarnya hanya diperkirakan dari
        rata-rata, potongan bisa dianggap menempel padahal dipisahkan spasi.
        """
        if self.dua_byte:
            kode = [(data[i] << 8) | data[i + 1] for i in range(0, len(data) - 1, 2)]
        else:
            kode = list(data)
        if not self.lebar:
            return len(kode) * self.lebar_bawaan
        return sum(self.lebar.get(k, self.lebar_bawaan) for k in kode)


# --------------------------------------------------------------------------- #
# Dokumen PDF
# --------------------------------------------------------------------------- #
_POLA_OBJ = re.compile(rb"(?<![0-9])(\d{1,7})\s+(\d{1,5})\s+obj\b")


def _panjang(a: float, b: float) -> float:
    """Panjang vektor (a, b) — dipakai menghitung skala matriks tanpa modul ``math``."""
    return (a * a + b * b) ** 0.5


def rapatkan_potongan_lebar(potongan: Sequence[Sequence[Any]]) -> list[tuple[float, str, float]]:
    """Gabungkan potongan bersambung erat menjadi satu sel; kembalikan ``(x, teks, lebar)``.

    Potongan hasil pembaca bawaan membawa perkiraan lebarnya (unsur ke-4). Banyak PDF
    (Word/OpenOffice/PdfLaTeX) memecah satu sel menjadi beberapa show-string; tanpa
    penggabungan, kolom TANGCER bisa terbaca terpotong-potong. Lebarnya dikembalikan karena
    dipakai menebak kolom tabel: nilai yang lebih panjang daripada judulnya sering mulai
    di sebelah kiri judul, jadi titik tengah potongan yang menentukan kolomnya.
    """
    # Sengaja TIDAK diurutkan berdasarkan x: PDF menulis teks dalam urutan baca, dan pada
    # dokumen dinas nama siswa yang panjang bisa melewati batas kolomnya sehingga posisi x
    # (NISN di sebelah kanan judul nama) menyisip di tengah nama. Dengan urutan penulisan,
    # potongan «…NUGRA» + «HA» tetap bersambung dan NISN dipisah karena x-nya melompat mundur.
    terurut = list(potongan)
    sel: list[list[Any]] = []      # [x, teks, akhir_kanan]
    rata = 0.0                     # perkiraan lebar satu huruf
    for butir in terurut:
        x = float(butir[0])
        teks = str(butir[2])
        if not teks.strip():
            continue
        lebar = float(butir[3]) if len(butir) > 3 and butir[3] else 0.0
        huruf = len(teks.strip()) or 1
        if not sel:
            sel.append([x, teks, x + lebar])
            rata = lebar / huruf
            continue
        # Spasi di ujung potongan = batas kata di dalam satu sel: digabung, tetap dengan syarat
        # jaraknya masih sepanjang satu spasi. Tanpa syarat itu, dua judul kolom berjauhan
        # («NOMOR KARTU» dan «TANGGAL») ikut menyatu karena potongan pertama berakhir spasi.
        jarak = x - sel[-1][2]
        # Tumpang-tindih (jarak negatif) hanya boleh sebesar derau pembulatan PDF: sekitar
        # sepersepuluh lebar huruf, paling banyak 0,35 pt. Nilai yang tumpang-tindih lebih
        # dalam daripada itu berarti potongan ini milik SEL LAIN yang teksnya melimpah ke
        # kolom sebelahnya — mis. «Kelas 8.6» yang bersambung dengan nama ayah, atau nama ibu
        # yang menyentuh kolom nama sekolah (ronde 61). Dulu batasnya -1,5 pt sehingga nama
        # ayah/ibu dan nama sekolah ikut tertelan jadi satu sel.
        tumpang = -min(0.35, max(0.12, 0.10 * (rata or 1.0)))
        dekat = tumpang <= jarak <= max(0.6 * (rata or 1.0), 1.5)
        rapat = dekat and (teks[:1] == " " or sel[-1][1].endswith(" "))
        batas = 0.22 * (rata or (lebar / huruf) or 0.0)
        # Spasi tidak dibuang saat menggabung: banyak PDF menaruh spasi di ujung show-string
        # («…a » + «Nu»), dan kalau di-strip nama seperti «Adelia Nur Barokah» jadi menempel.
        if rapat or (batas > 0 and tumpang <= jarak <= batas):
            sel[-1][1] += teks                  # satu sel dipecah show-string bertetangga
        else:
            sel.append([x, teks, x + lebar])
        sel[-1][2] = max(sel[-1][2], x + lebar)
        if lebar and huruf:
            rata = lebar / huruf
    hasil: list[tuple[float, str, float]] = []
    for x, teks, akhir in sorted(sel, key=lambda butir: butir[0]):
        rapi = re.sub(r"\s{2,}", " ", str(teks)).strip()
        if rapi:
            hasil.append((x, rapi, max(0.5 * len(rapi), akhir - x)))
    return hasil


def rapatkan_potongan(potongan: Sequence[Sequence[Any]]) -> list[tuple[float, str]]:
    """Seperti :func:`rapatkan_potongan_lebar`, tanpa lebar (untuk pemakaian lama)."""
    return [(x, teks) for x, teks, _ in rapatkan_potongan_lebar(potongan)]


def _kali(m1: Sequence[float], m2: Sequence[float]) -> tuple[float, ...]:
    """Perkalian matriks PDF (a b c d e f) — m1 dikerjakan lebih dulu."""
    a1, b1, c1, d1, e1, f1 = (float(v) for v in m1[:6])
    a2, b2, c2, d2, e2, f2 = (float(v) for v in m2[:6])
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


class PdfDokumen:
    """Dokumen PDF yang sudah diurai (objek, aliran, halaman, huruf, teks)."""

    def __init__(self, isi: bytes) -> None:
        self.isi = isi
        self.catatan: list[str] = []
        self.benda: dict[int, Any] = {}
        self.trailer: dict[str, Any] = {}
        self.terkunci = False
        self._aliran_terbuka: dict[int, bytes] = {}
        if not isi[:1024].lstrip().startswith(b"%PDF-"):
            raise PdfBacaError("Berkas ini bukan PDF (penanda «%PDF» tidak ditemukan).")
        if b"/Encrypt" in isi[:4096] or b"/Encrypt" in isi[-4096:]:
            self.terkunci = True
            self.catatan.append("PDF bertanda terenkripsi — sebagian teks mungkin tidak terbaca")
        self._urai()

    # -- penguraian objek ---------------------------------------------------- #
    def _badan_objek(self, mulai: int) -> tuple[bytes, bool, bytes]:
        """Ambil badan objek: teks kamus, ada-tidaknya aliran, dan data alirannya."""
        sisa = self.isi
        pos_stream = sisa.find(b"stream", mulai)
        pos_endobj = sisa.find(b"endobj", mulai)
        if pos_stream >= 0 and (pos_endobj < 0 or pos_stream < pos_endobj):
            kamus_teks = sisa[mulai:pos_stream]
            awal = pos_stream + len(b"stream")
            if sisa[awal:awal + 2] == b"\r\n":
                awal += 2
            elif sisa[awal:awal + 1] in (b"\n", b"\r"):
                awal += 1
            akhir = sisa.find(b"endstream", awal)
            if akhir < 0:
                akhir = len(sisa)
            return kamus_teks, True, sisa[awal:akhir]
        return sisa[mulai:pos_endobj if pos_endobj >= 0 else len(sisa)], False, b""

    def _urai(self) -> None:
        for cocok in _POLA_OBJ.finditer(self.isi):
            nomor = int(cocok.group(1))
            kamus_teks, ada_stream, mentah = self._badan_objek(cocok.end())
            try:
                nilai, akhir = baca_benda(kamus_teks, 0)
            except PdfBacaError:
                continue
            sisa = kamus_teks[akhir:].lstrip()
            bila_stream = ada_stream and (not sisa or sisa.startswith(b"stream")
                                          or sisa[:1] in (b"<", b"/", b"["))
            if bila_stream and isinstance(nilai, dict):
                self.benda[nomor] = Aliran(nilai, mentah)
            elif nilai is not None:
                self.benda[nomor] = nilai
        self._urai_kamus_trailer()
        self._urai_aliran_objek()

    def _urai_kamus_trailer(self) -> None:
        for m in re.finditer(rb"trailer", self.isi):
            try:
                nilai, _ = baca_benda(self.isi, m.end())
            except PdfBacaError:
                continue
            if isinstance(nilai, dict):
                self.trailer.update(nilai)
                if "/Encrypt" in nilai:
                    self.terkunci = True
        for benda in list(self.benda.values()):
            kamus = benda.kamus if isinstance(benda, Aliran) else benda
            if not isinstance(kamus, dict):
                continue
            jenis = kamus.get("/Type")
            jenis = jenis.bersih() if isinstance(jenis, Nama) else ""
            if jenis in ("XRef", "Catalog") and "/Root" in kamus:
                self.trailer.setdefault("/Root", kamus["/Root"])
            if jenis == "XRef" and "/Encrypt" in kamus:
                self.terkunci = True

    def _urai_aliran_objek(self) -> None:
        """Buka object stream (PDF 1.5+): objek-objek yang disimpan di dalam aliran."""
        for nomor, benda in list(self.benda.items()):
            if not isinstance(benda, Aliran):
                continue
            jenis = benda.kamus.get("/Type")
            if not (isinstance(jenis, Nama) and jenis.bersih() == "ObjStm"):
                continue
            data = self.data_aliran(benda)
            try:
                jumlah = int(self.ambil(benda.kamus.get("/N")) or 0)
                awal = int(self.ambil(benda.kamus.get("/First")) or 0)
            except (TypeError, ValueError):
                continue
            kepala = data[:awal]
            angka = [int(a) for a in re.findall(rb"\d+", kepala)]
            pasangan = list(zip(angka[0::2], angka[1::2]))[:jumlah]
            for urutan, (nomor_objek, geser) in enumerate(pasangan):
                akhir = (awal + pasangan[urutan + 1][1]) if urutan + 1 < len(pasangan) else len(data)
                if nomor_objek in self.benda:
                    continue
                try:
                    nilai, _ = baca_benda(data, awal + geser)
                except PdfBacaError:
                    continue
                if nilai is not None:
                    self.benda[nomor_objek] = nilai

    # -- rujukan & aliran ---------------------------------------------------- #
    def ambil(self, benda: Any, batas: int = 64) -> Any:
        """Selesaikan rujukan tidak langsung (``12 0 R``) berulang."""
        langkah = 0
        while isinstance(benda, Ref) and langkah < batas:
            benda = self.benda.get(benda.nomor)
            langkah += 1
        return benda

    def data_aliran(self, benda: Any) -> bytes:
        """Buka (dekompresi) aliran data sebuah objek."""
        benda = self.ambil(benda)
        if not isinstance(benda, Aliran):
            return b""
        nomor = next((n for n, b in self.benda.items() if b is benda), None)
        if nomor is not None and nomor in self._aliran_terbuka:
            return self._aliran_terbuka[nomor]
        data = buka_aliran(benda.mentah, benda.kamus, self.ambil, self.catatan)
        if nomor is not None:
            self._aliran_terbuka[nomor] = data
        return data

    def adakah_gambar(self) -> bool:
        """Apakah PDF ini memuat gambar (penanda berkas hasil pindai)."""
        for benda in self.benda.values():
            kamus = benda.kamus if isinstance(benda, Aliran) else benda
            if isinstance(kamus, dict):
                jenis = kamus.get("/Subtype")
                if isinstance(jenis, Nama) and jenis.bersih() in ("Image", "DCTDecode"):
                    return True
        return b"/Image" in self.isi

    # -- halaman ------------------------------------------------------------- #
    def _telusuri(self, pohon: Any, warisan: dict[str, Any], hasil: list) -> None:
        pohon = self.ambil(pohon)
        if not isinstance(pohon, dict):
            return
        baru = dict(warisan)
        for kunci in ("/Resources", "/MediaBox", "/Rotate", "/CropBox"):
            if kunci in pohon:
                baru[kunci] = pohon[kunci]
        jenis = pohon.get("/Type")
        jenis = jenis.bersih() if isinstance(jenis, Nama) else ""
        if jenis == "Page" or ("/Contents" in pohon and "/Kids" not in pohon):
            hasil.append((pohon, baru))
            return
        anak = self.ambil(pohon.get("/Kids"))
        if isinstance(anak, list):
            for satu in anak:
                self._telusuri(satu, baru, hasil)

    def daftar_halaman(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Daftar halaman dokumen beserta sumber daya (resources) yang berlaku."""
        hasil: list[tuple[dict[str, Any], dict[str, Any]]] = []
        katalog = self.ambil(self.trailer.get("/Root"))
        if isinstance(katalog, dict):
            self._telusuri(katalog.get("/Pages"), {}, hasil)
        if not hasil:
            for nomor in sorted(self.benda):
                benda = self.benda[nomor]
                if isinstance(benda, dict):
                    jenis = benda.get("/Type")
                    if isinstance(jenis, Nama) and jenis.bersih() == "Page":
                        hasil.append((benda, {}))
        return hasil

    # -- huruf --------------------------------------------------------------- #
    def _huruf_dari_kamus(self, kamus: dict[str, Any]) -> Huruf:
        sub = self.ambil(kamus.get("/Subtype"))
        sub = sub.bersih() if isinstance(sub, Nama) else ""
        huruf = Huruf(dua_byte=(sub == "Type0"))
        peta_unicode = self.data_aliran(kamus.get("/ToUnicode"))
        if peta_unicode:
            peta = baca_cmap(peta_unicode)
            if peta:
                huruf.peta = peta
        penyandi = self.ambil(kamus.get("/Encoding"))
        if isinstance(penyandi, Nama):
            nama = penyandi.bersih()
            huruf.penyandi = {"WinAnsiEncoding": "cp1252", "MacRomanEncoding": "mac_roman",
                              "StandardEncoding": "latin-1"}.get(nama, "latin-1")
        elif isinstance(penyandi, dict):
            dasar = self.ambil(penyandi.get("/BaseEncoding"))
            if isinstance(dasar, Nama):
                huruf.penyandi = {"WinAnsiEncoding": "cp1252", "MacRomanEncoding": "mac_roman",
                                  "StandardEncoding": "latin-1"}.get(dasar.bersih(), "latin-1")
        if not huruf.dua_byte:
            # Lapisan cadangan: kode yang tidak disebut Differences/ToUnicode tetap dibaca
            # memakai penyandinya (WinAnsi/MacRoman/Standard) — perilaku ini yang dipakai
            # pustaka pembaca PDF lain, dan membuat berkas Word/OpenOffice terbaca penuh.
            huruf.dasar = {b: bytes([b]).decode(huruf.penyandi, "replace") for b in range(32, 256)}
        beda = self.ambil(penyandi.get("/Differences")) if isinstance(penyandi, dict) else None
        if isinstance(beda, list):
            # /Differences dipakai untuk kode yang TIDAK dipetakan ToUnicode; kalau ToUnicode
            # sudah memetakan sebuah kode, peta ToUnicode yang menang (paling tepercaya).
            peta = dict(huruf.peta or {})
            kode = 0
            for butir in beda:
                butir = self.ambil(butir)
                if isinstance(butir, (int, float)):
                    kode = int(butir)
                    continue
                if isinstance(butir, Nama):
                    if kode not in peta:
                        peta[kode] = huruf_dari_nama(butir.bersih())
                    kode += 1
            huruf.peta = peta
        if huruf.dua_byte:
            # Lebar huruf gabungan (CID) TIDAK ada di /Widths, melainkan di /W + /DW milik
            # font turunannya. Tanpa ini semua posisi (x) hasil pembaca melenceng — kolom
            # tabel jadi saling menimpa dan barisnya tercampur.
            huruf.lebar, huruf.lebar_bawaan = self._lebar_cid(kamus)
        lebar = self.ambil(kamus.get("/Widths"))
        awal = self.ambil(kamus.get("/FirstChar"))
        if isinstance(lebar, list):
            try:
                mulai = int(awal or 0)
                huruf.lebar = {mulai + i: (float(v) / 1000.0)
                               for i, v in enumerate(lebar)
                               if isinstance(v, (int, float))}
            except (TypeError, ValueError):
                huruf.lebar = None
            if huruf.lebar:
                huruf.lebar_rata = max(0.2, sum(huruf.lebar.values()) / len(huruf.lebar))
        return huruf

    def _lebar_cid(self, kamus: dict[str, Any]) -> tuple[dict[int, float] | None, float]:
        """Lebar huruf per kode (em) dari font turunan CID: ``/W`` dan ``/DW``.

        Bentuk ``/W`` ada dua: ``[awal [w1 w2 …]]`` (berurutan) dan ``[awal akhir lebar]``
        (rentang). Keduanya dibaca; kode yang tidak disebut memakai ``/DW`` (bawaan 1000).
        """
        turunan = self.ambil(kamus.get("/DescendantFonts"))
        cid = self.ambil(turunan[0]) if isinstance(turunan, list) and turunan else None
        if not isinstance(cid, dict):
            return None, 0.9 if kamus.get("/Subtype") == "/Type0" else 0.5
        dw = self.ambil(cid.get("/DW"))
        bawaan = float(dw) / 1000.0 if isinstance(dw, (int, float)) and dw else 1.0
        daftar = self.ambil(cid.get("/W"))
        lebar: dict[int, float] = {}
        if isinstance(daftar, list):
            i = 0
            while i < len(daftar):
                awal = self.ambil(daftar[i])
                if not isinstance(awal, (int, float)):
                    break
                i += 1
                if i >= len(daftar):
                    break
                kedua = self.ambil(daftar[i])
                if isinstance(kedua, list):
                    for urutan, nilai in enumerate(kedua):
                        nilai = self.ambil(nilai)
                        if isinstance(nilai, (int, float)):
                            lebar[int(awal) + urutan] = float(nilai) / 1000.0
                    i += 1
                elif isinstance(kedua, (int, float)):
                    i += 1
                    if i >= len(daftar):
                        break
                    akhir = self.ambil(daftar[i])
                    i += 1
                    if isinstance(akhir, (int, float)):
                        for kode in range(int(awal), int(akhir) + 1):
                            lebar[kode] = float(kedua) / 1000.0
                else:
                    i += 1
        return (lebar or None), bawaan

    def huruf_peta(self, sumber_daya: dict[str, Any] | None) -> dict[str, Huruf]:
        """Kumpulan font halaman: nama di konten → cara membacanya."""
        peta: dict[str, Huruf] = {}
        sumber = self.ambil((sumber_daya or {}).get("/Resources"))
        if sumber is None:
            sumber = sumber_daya if isinstance(sumber_daya, dict) else {}
        sumber = self.ambil(sumber)
        if not isinstance(sumber, dict):
            return peta
        kumpulan = self.ambil(sumber.get("/Font"))
        if isinstance(kumpulan, dict):
            for nama, kamus in kumpulan.items():
                kamus = self.ambil(kamus)
                if isinstance(kamus, dict):
                    peta[str(nama)] = self._huruf_dari_kamus(kamus)
        return peta

    def data_konten(self, halaman: dict[str, Any]) -> bytes:
        """Gabungkan seluruh aliran konten halaman (menjadi satu)."""
        isi = self.ambil(halaman.get("/Contents"))
        bagian: list[bytes] = []
        if isinstance(isi, list):
            bagian = [self.data_aliran(satu) for satu in isi]
        else:
            bagian = [self.data_aliran(isi)]
        return b"\n".join(b for b in bagian if b)

    def teks_halaman(self, halaman: dict[str, Any],
                     sumber_daya: dict[str, Any] | None = None,
                     ) -> tuple[list[tuple[float, float, str]], int]:
        """Ambil potongan teks (x, y, teks) dari satu halaman."""
        data = self.data_konten(halaman)
        if not data:
            return [], 0
        tafsir = _Tafsir(self, self.huruf_peta(sumber_daya))
        tafsir.jalan(data, sumber_daya)
        return tafsir.keluaran, tafsir.tak_terbaca


# --------------------------------------------------------------------------- #
# Penafsir aliran konten
# --------------------------------------------------------------------------- #
_IDENTITAS = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


class _Tafsir:
    """Jalankan operator konten PDF dan kumpulkan potongan teks beserta posisinya."""

    def __init__(self, dok: PdfDokumen, huruf: dict[str, Huruf]) -> None:
        self.dok = dok
        self.huruf = huruf
        self.keluaran: list[tuple[float, float, str]] = []
        self.tak_terbaca = 0

    def _tampilkan(self, data: Any, nama_huruf: str, ukuran: float,
                   tm: tuple[float, ...], ctm: tuple[float, ...],
                   jarak_kata: float, jarak_huruf: float) -> tuple[float, ...]:
        if not isinstance(data, (bytes, bytearray)):
            return tm
        huruf = self.huruf.get(nama_huruf) or Huruf()
        teks, gagal = huruf.baca(bytes(data))
        self.tak_terbaca += gagal
        bersih = teks.strip()
        jumlah = len(data) // 2 if huruf.dua_byte else len(data)
        geser = (huruf.ukur(bytes(data)) * ukuran + jumlah * jarak_huruf
                 + max(0, jumlah - 1) * jarak_kata)
        if bersih:
            x = tm[4] * ctm[0] + tm[5] * ctm[2] + ctm[4]
            y = tm[4] * ctm[1] + tm[5] * ctm[3] + ctm[5]
            teks = teks.replace("\r", " ").replace("\n", " ")
            # Lebar potongan di ruang tampilan diperkirakan dari matriks teks & CTM — dipakai
            # untuk memutuskan "huruf ini masih satu kata" atau "ini sel/kolom terpisah".
            skala = _panjang(tm[0], tm[1]) * _panjang(ctm[0], ctm[1])
            self.keluaran.append((round(x, 2), round(y, 2), teks, round(geser * skala, 2)))
        if len(self.keluaran) > 400000:
            return tm
        return _kali((1, 0, 0, 1, geser, 0), tm)

    def _xobject(self, nama: Any, sumber: dict[str, Any] | None,
                 ctm: tuple[float, ...], kedalaman: int) -> None:
        if kedalaman >= 3 or not isinstance(nama, Nama):
            return
        nyata = self.dok.ambil((sumber or {}).get("/Resources"))
        if not isinstance(nyata, dict):
            nyata = sumber if isinstance(sumber, dict) else {}
        kotak = self.dok.ambil(nyata.get("/XObject"))
        if not isinstance(kotak, dict):
            return
        aliran = self.dok.ambil(kotak.get(str(nama)))
        if not isinstance(aliran, Aliran):
            return
        sub = self.dok.ambil(aliran.kamus.get("/Subtype"))
        if not (isinstance(sub, Nama) and sub.bersih() == "Form"):
            return
        data = self.dok.data_aliran(aliran)
        matriks = self.dok.ambil(aliran.kamus.get("/Matrix")) or _IDENTITAS
        sumber_baru = self.dok.ambil(aliran.kamus.get("/Resources")) or sumber
        if len(self.keluaran) > 400000 or len(data) > 8_000_000:
            return
        self.jalan(data, sumber_baru, _kali(tuple(float(v) for v in matriks[:6]), ctm),
                   kedalaman + 1)

    def jalan(self, data: bytes, sumber: dict[str, Any] | None = None,
              ctm: tuple[float, ...] = _IDENTITAS, kedalaman: int = 0) -> None:
        """Jalankan operator: ambil teks dari Tj/TJ/'/" termasuk di dalam Form XObject."""
        operand: list[Any] = []
        tm: tuple[float, ...] = _IDENTITAS
        tlm: tuple[float, ...] = _IDENTITAS
        nama_huruf = ""
        ukuran = 12.0
        leading = 0.0
        jarak_kata = 0.0
        jarak_huruf = 0.0
        simpanan: list[tuple[tuple[float, ...], str, float]] = []
        i = 0
        n = len(data)
        while i < n:
            i = _lewati(data, i)
            if i >= n:
                break
            c = data[i:i + 1]
            if c in (b"(", b"<", b"[", b"/", b"+", b"-", b".", b"]") or c.isdigit():
                if c == b"]":
                    i += 1
                    continue
                try:
                    benda, i = baca_benda(data, i)
                except PdfBacaError:
                    i += 1
                    continue
                operand.append(benda)
                continue
            m = re.match(rb"[A-Za-z'\"*]+", data[i:i + 16])
            if not m:
                i += 1
                continue
            op = m.group(0)
            i += len(op)
            arg = operand
            operand = []
            if op == b"BT":
                tm = tlm = _IDENTITAS
            elif op == b"Tf" and len(arg) >= 2:
                nama_huruf = str(arg[-2]) if isinstance(arg[-2], Nama) else ""
                try:
                    ukuran = float(arg[-1])
                except (TypeError, ValueError):
                    ukuran = 12.0
            elif op in (b"Td", b"TD") and len(arg) >= 2:
                try:
                    tx, ty = float(arg[-2]), float(arg[-1])
                except (TypeError, ValueError):
                    tx = ty = 0.0
                tlm = _kali((1, 0, 0, 1, tx, ty), tlm)
                tm = tlm
                if op == b"TD":
                    leading = -ty
            elif op == b"Tm" and len(arg) >= 6:
                try:
                    tm = tlm = tuple(float(v) for v in arg[-6:])
                except (TypeError, ValueError):
                    tm = tlm = _IDENTITAS
            elif op == b"T*":
                tlm = _kali((1, 0, 0, 1, 0, -leading), tlm)
                tm = tlm
            elif op == b"TL" and arg:
                try:
                    leading = float(arg[-1])
                except (TypeError, ValueError):
                    leading = 0.0
            elif op == b"Tc" and arg:
                try:
                    jarak_huruf = float(arg[-1])
                except (TypeError, ValueError):
                    jarak_huruf = 0.0
            elif op == b"Tw" and arg:
                try:
                    jarak_kata = float(arg[-1])
                except (TypeError, ValueError):
                    jarak_kata = 0.0
            elif op == b"Tj" and arg:
                tm = self._tampilkan(arg[-1], nama_huruf, ukuran, tm, ctm,
                                     jarak_kata, jarak_huruf)
            elif op == b"'" and arg:
                tlm = _kali((1, 0, 0, 1, 0, -leading), tlm)
                tm = self._tampilkan(arg[-1], nama_huruf, ukuran, tlm, ctm,
                                     jarak_kata, jarak_huruf)
            elif op == b'"' and len(arg) >= 3:
                try:
                    jarak_kata, jarak_huruf = float(arg[-3]), float(arg[-2])
                except (TypeError, ValueError):
                    pass
                tlm = _kali((1, 0, 0, 1, 0, -leading), tlm)
                tm = self._tampilkan(arg[-1], nama_huruf, ukuran, tlm, ctm,
                                     jarak_kata, jarak_huruf)
            elif op == b"TJ" and arg and isinstance(arg[-1], list):
                for butir in arg[-1]:
                    if isinstance(butir, (bytes, bytearray)):
                        tm = self._tampilkan(butir, nama_huruf, ukuran, tm, ctm,
                                             jarak_kata, jarak_huruf)
                    elif isinstance(butir, (int, float)):
                        tm = _kali((1, 0, 0, 1, -float(butir) / 1000.0 * ukuran, 0), tm)
            elif op == b"cm" and len(arg) >= 6:
                try:
                    ctm = _kali(tuple(float(v) for v in arg[-6:]), ctm)
                except (TypeError, ValueError):
                    pass
            elif op == b"q":
                simpanan.append((ctm, nama_huruf, ukuran))
            elif op == b"Q" and simpanan:
                ctm, nama_huruf, ukuran = simpanan.pop()
            elif op == b"Do":
                self._xobject(arg[-1] if arg else None, sumber, ctm, kedalaman)


# --------------------------------------------------------------------------- #
# API publik
# --------------------------------------------------------------------------- #
@dataclass
class HasilPdf:
    """Hasil pembacaan PDF bawaan: potongan teks per halaman + catatan jujur."""

    halaman: list[list[tuple[float, float, str]]] = dataclass_field(default_factory=list)
    jumlah_potongan: int = 0
    huruf_tak_terbaca: int = 0
    catatan: list[str] = dataclass_field(default_factory=list)
    terkunci: bool = False

    @property
    def jumlah_halaman(self) -> int:
        return len(self.halaman)

    @property
    def ada_teks(self) -> bool:
        return self.jumlah_potongan > 0

    def baris(self) -> list[str]:
        """Seluruh teks sebagai daftar baris (potongan yang sebaris digabung).

        Potongan yang bersambung erat digabung tanpa spasi; potongan yang berjarak
        sedang diberi satu spasi; jarak lebar (antar kolom) diberi dua spasi supaya
        batas kolom tetap terlihat.
        """
        keluaran: list[str] = []
        for halaman in self.halaman:
            terurut = sorted(halaman, key=lambda item: (-item[1], item[0]))
            baris: list[list[Any]] = []
            for butir in terurut:
                if baris and abs(baris[-1][0] - butir[1]) <= 3.0:
                    baris[-1][1].append(butir)
                else:
                    baris.append([butir[1], [butir]])
            for _, potongan in baris:
                teks = _teks_satu_baris(potongan)
                if teks.strip():
                    keluaran.append(teks)
        return keluaran


def _teks_satu_baris(potongan: Sequence[Sequence[Any]]) -> str:
    """Susun teks satu baris dari potongan-potongannya (spasi mengikuti jarak X)."""
    terurut = sorted(potongan, key=lambda item: (float(item[0]),))
    keluaran: list[str] = []
    akhir = 0.0
    rata = 0.0
    for butir in terurut:
        x = float(butir[0])
        teks = str(butir[2])
        if not teks:
            continue
        lebar = float(butir[3]) if len(butir) > 3 and butir[3] else 0.0
        huruf = max(1, len(teks.strip()))
        ada_spasi = bool(keluaran) and (keluaran[-1].endswith(" ") or teks.startswith(" "))
        if keluaran and not ada_spasi:
            jarak = x - akhir
            acuan = rata or (lebar / huruf) or 0.0
            if acuan and jarak > 1.6 * acuan:
                keluaran.append("  ")
            elif acuan and jarak > 0.45 * acuan:
                keluaran.append(" ")
            elif not acuan:
                keluaran.append("  ")
        keluaran.append(teks)
        akhir = x + lebar
        if lebar:
            rata = lebar / huruf
    return "".join(keluaran)


def ada_pembaca_pypdf() -> bool:
    """Apakah pustaka ``pypdf`` tersedia (dipakai hanya sebagai pembanding/cadangan)."""
    try:
        import importlib.util

        return importlib.util.find_spec("pypdf") is not None
    except (ImportError, ValueError):  # pragma: no cover - lingkungan aneh
        return False


def baca_pdf(isi: bytes, *, batas_halaman: int = 400) -> HasilPdf:
    """Baca teks PDF tanpa pustaka tambahan.

    Mengembalikan :class:`HasilPdf`. Bila berkas tidak memuat teks (hasil pindai,
    atau huruf gabungan tanpa peta ToUnicode) itu **dilaporkan** di ``catatan`` —
    pemanggil memutuskan sendiri apa yang mau dikatakan ke pengguna.
    """
    if not isinstance(isi, (bytes, bytearray)):
        raise PdfBacaError("Isi berkas PDF harus berupa data biner.")
    dokumen = PdfDokumen(bytes(isi))
    hasil = HasilPdf(catatan=list(dokumen.catatan), terkunci=dokumen.terkunci)
    daftar = dokumen.daftar_halaman()
    if not daftar:
        if dokumen.terkunci:
            raise PdfBacaError("PDF ini terkunci (dilindungi kata sandi). Isinya hanya bisa "
                               "dibaca setelah kata sandinya dibuka lebih dulu.")
        raise PdfBacaError("PDF ini tidak memuat halaman yang bisa dibaca "
                           "(struktur berkasnya tidak dikenali).")
    for halaman, sumber in daftar[:batas_halaman]:
        potongan, gagal = dokumen.teks_halaman(halaman, sumber)
        hasil.halaman.append(potongan)
        hasil.jumlah_potongan += len(potongan)
        hasil.huruf_tak_terbaca += gagal
    if not hasil.ada_teks:
        sebab = ("PDF memuat gambar (kemungkinan hasil pindai/scan) — berkas seperti itu "
                 "perlu di-OCR lebih dulu" if dokumen.adakah_gambar()
                 else "tidak ada operator teks di dalam halamannya")
        hasil.catatan.append(f"PDF tidak memuat teks yang bisa dibaca: {sebab}.")
    else:
        if hasil.huruf_tak_terbaca:
            hasil.catatan.append(f"{hasil.huruf_tak_terbaca} huruf tidak terbaca "
                                 "(font tanpa peta ToUnicode — hasil bisa tidak lengkap)")
        # Sebagian halaman bisa berupa hasil pindai walau halaman lain bertulisan — biasanya
        # justru sampul & lampiran (tanda tangan, daftar penerima). Dilaporkan apa adanya
        # supaya berkas yang "kok barisnya kurang" bisa ditelusuri (ronde 61).
        tanpa_teks = [nomor for nomor, isi_halaman in enumerate(hasil.halaman, start=1)
                      if not isi_halaman]
        if tanpa_teks:
            contoh = ", ".join(str(nomor) for nomor in tanpa_teks[:12])
            hasil.catatan.append(
                f"{len(tanpa_teks)} halaman tanpa teks (kemungkinan hasil pindai): {contoh}"
                + (" …" if len(tanpa_teks) > 12 else "")
                + " — isinya tidak ikut terbaca, perlu OCR bila halaman itu memuat data.")
    hasil.catatan.append(f"pembaca PDF bawaan SM · {hasil.jumlah_halaman} halaman · "
                         f"{hasil.jumlah_potongan} potongan teks")
    return hasil
