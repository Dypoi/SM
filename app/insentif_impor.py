"""Impor rekening awal insentif — sekali pakai dari berkas lama.

Latar: nomor rekening tidak perlu dipindah satu per satu dari berkas
lama (mis. «DAFTAR-PENERIMA-DANA-INSENTIF (11).xls»); cukup unggah
sekali, cocokkan dengan data GTK Dapodik, lalu terapkan. Yang diambil
HANYA nomor rekening; NIP/nama hanya dipakai mencocokkan.

Alur: **unggah → pratinjau (cocok/tak-cocok) → terapkan**. Draf
unggahan dicatat di pengaturan (satu slot); penerapan hanya mengisi
rekening GTK yang masih kosong — yang sudah terisi tak pernah
ditimpa.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

from . import db, insentif

log = logging.getLogger("sm.insentif.impor")

#: Ekstensi yang diterima halaman impor rekening.
EKSTENSI = (".xls", ".xlsx")

#: Kunci pengaturan: draf unggahan + hasil impor terakhir.
KUNCI_DRAF = "impor_rekening_draf"
KUNCI_HASIL = "impor_rekening_terakhir"
KUNCI_CETAK = "cetak_berkas_draf"

#: Token gelar (tanpa titik, huruf kecil) yang diabaikan saat
#: mencocokkan nama berkas («Ary Setyowati») vs GTK («... , S.Pd»).
_GELAR = frozenset({
    "dr", "dra", "drs", "hj", "h", "ir",
    "spd", "mpd", "spdi", "spdsi", "spdsd", "mgr",
    "msi", "mkom", "skom", "se", "mm", "sag", "sh", "shum",
    "ssi", "st", "ssos", "sip", "sp", "mpfis", "ssn", "mhum",
    "gr", "sgr", "pd", "si",
})


def nama_kunci(nama: Any) -> str:
    """Kunci pembanding nama: kecil, tanpa gelar & tanda baca."""
    s = str(nama or "")
    s = re.sub(r"^(dra?|drs|ir|hj|h)\.\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r",\s*[a-z][a-z. ]*$", "", s, flags=re.IGNORECASE)
    kata = re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
    kata = [k for k in kata if k and k not in _GELAR]
    return " ".join(kata)


class _PengorekTabel(HTMLParser):
    """Pengorek tabel HTML sederhana (berkas .xls hasil ekspor web)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabels: list[list[list[str]]] = []
        self._tbl: list[list[str]] | None = None
        self._baris: list[str] | None = None
        self._sel: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "table":
            self._tbl = []
        elif tag == "tr":
            self._baris = []
        elif tag in ("td", "th"):
            self._sel = ""
            try:
                self._rentang = max(1, int(dict(attrs).get("colspan", 1)))
            except (ValueError, TypeError):
                self._rentang = 1

    def handle_data(self, data: str) -> None:
        if self._sel is not None:
            self._sel += data

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            assert self._baris is not None and self._sel is not None
            isi = " ".join(self._sel.split())
            for _ in range(getattr(self, "_rentang", 1)):
                self._baris.append(isi)
            self._sel = None
        elif tag == "tr":
            assert self._tbl is not None and self._baris is not None
            self._tbl.append(self._baris)
            self._baris = None
        elif tag == "table":
            assert self._tbl is not None
            self.tabels.append(self._tbl)
            self._tbl = None


def _sel_teks(nilai: Any) -> str:
    if nilai is None:
        return ""
    if isinstance(nilai, float) and nilai.is_integer():
        return str(int(nilai))
    return str(nilai).strip()


def _peta_kolom(kepala: list[str]) -> dict[str, int] | None:
    """Peta nama kolom baku → indeks; None bila bukan tabel penerima."""
    peta: dict[str, int] = {}
    for i, sel in enumerate(kepala):
        bersih = _sel_teks(sel).lower().replace(".", "")
        if bersih in ("nama", "nama lengkap", "nama pegawai"):
            peta.setdefault("nama", i)
        elif bersih == "nip":
            peta.setdefault("nip", i)
        elif bersih == "npwp":
            peta.setdefault("npwp", i)
        elif bersih in ("no rekening", "nomor rekening", "nom rekening", "rekening",
                       "no rek", "nomor rek"):
            peta.setdefault("rekening", i)
        elif bersih == "nik":
            peta.setdefault("nik", i)
        elif bersih in ("jumlah yang di bayar", "jumlah yg dibayar",
                        "jumlah dibayar", "di bayar", "dibayar"):
            peta.setdefault("bayar", i)
        elif bersih in ("pph", "pph 21", "potongan pph"):
            peta.setdefault("pph", i)
        elif bersih in ("jumlah yang di terima", "jumlah yg diterima",
                        "jumlah diterima", "di terima", "diterima"):
            peta.setdefault("terima", i)
        elif bersih in ("unit kerja", "unit"):
            peta.setdefault("unit", i)
        elif bersih.startswith("kecamatan"):
            peta.setdefault("kecamatan", i)
        elif bersih.startswith("gol"):
            peta.setdefault("gol", i)
        elif bersih == "jabatan":
            peta.setdefault("jabatan", i)
    if "nama" in peta and "rekening" in peta:
        return peta
    return None


def baris_dari_tabel(basis: list[list[Any]]) -> list[dict[str, str]]:
    """Ubah matriks sel menjadi daftar penerima {nama, nip, rekening, …}.

    Baris kepala dicari (maksimal 10 baris pertama) lewat kolom
    «NO REKENING»; baris JUMLAH/sub-kepala dilewati.
    """
    for awal in range(min(10, len(basis))):
        peta = _peta_kolom([_sel_teks(s) for s in basis[awal]])
        if peta is None:
            continue
        hasil: list[dict[str, str]] = []
        for baris in basis[awal + 1:]:
            ambil = lambda kunci: (_sel_teks(baris[peta[kunci]])
                if peta.get(kunci) is not None and peta[kunci] < len(baris) else "")
            pertama = _sel_teks(baris[0]) if baris else ""
            if pertama.lower() == "jumlah":
                break
            nama, nip, rek = ambil("nama"), ambil("nip"), ambil("rekening")
            if not nama or (not nip and not rek):
                continue  # sub-kepala / baris kosong
            hasil.append({"nama": nama, "nip": nip, "npwp": ambil("npwp"),
                          "rekening": rek, "nik": ambil("nik"),
                          "gol": ambil("gol"), "jabatan": ambil("jabatan"),
                          "bayar": ambil("bayar"), "pph": ambil("pph"),
                          "terima": ambil("terima"), "unit": ambil("unit"),
                          "kecamatan": ambil("kecamatan")})
        return hasil
    return []


def _cari_tabel(isi: str) -> list[list[str]] | None:
    """Tabel pertama berkas HTML yang memuat kolom NO REKENING."""
    pengorek = _PengorekTabel()
    pengorek.feed(isi)
    for tabel in pengorek.tabels:
        for baris in tabel[:10]:
            if any("rekening" in sel.lower() for sel in baris):
                return tabel
    return pengorek.tabels[0] if pengorek.tabels else None


def baca_berkas_rekening(lokasi: str | Path, ekstensi: str = "") -> list[dict[str, str]]:
    """Baca berkas lama → daftar penerima (HTML-.xls, .xls, .xlsx)."""
    lokasi = Path(lokasi)
    ekstensi = (ekstensi or lokasi.suffix).lower()
    if ekstensi not in EKSTENSI:
        raise ValueError(f"Jenis berkas «{ekstensi}» tak didukung; pakai .xls/.xlsx.")
    mentah = lokasi.read_bytes()
    if b"<table" in mentah[:2000].lower():
        tabel = _cari_tabel(mentah.decode("utf-8", errors="replace"))
        if tabel is None:
            raise ValueError("Berkas HTML ini tidak memuat tabel data.")
        return baris_dari_tabel(tabel)
    from .readers import SpreadsheetError, read_spreadsheet
    try:
        lembar = read_spreadsheet(lokasi, ekstensi)
    except Exception as galat:
        raise ValueError(f"Gagal membaca berkas: {galat}") from galat
    for sheet in lembar:
        hasil = baris_dari_tabel([[c for c in baris] for baris in sheet.rows])
        if hasil:
            return hasil
    raise ValueError("Kolom «NO REKENING» tidak ditemukan di berkas ini.")


def _gtk_semua() -> list[dict[str, Any]]:
    return db.rows_to_dicts(db.query_all(
        "SELECT id, nama, nip, status_kepegawaian, "
        "COALESCE(rekening, '') AS rekening FROM gtk_pegawai ORDER BY nama"))


def cocokan(daftar: list[Mapping[str, str]]) -> dict[str, Any]:
    """Cocokkan daftar berkas vs GTK (NIP dulu, lalu nama).

    Tiap yang cocok beraksi: ISI (GTK kosong → diisi), SAMA (sudah
    sama → dilewati), BEDA (terisi tapi beda → dipertahankan).
    """
    gtk = _gtk_semua()
    by_nip: dict[str, dict[str, Any]] = {}
    by_nama: dict[str, dict[str, Any]] = {}
    for orang in gtk:
        digit = insentif.hanya_digit(orang.get("nip"))
        if digit:
            by_nip.setdefault(digit, orang)
        kunci = nama_kunci(orang.get("nama"))
        if kunci:
            by_nama.setdefault(kunci, orang)
    cocok, tak_di_gtk = [], []
    terpakai: set[int] = set()
    for baris in daftar:
        orang = None
        digit = insentif.hanya_digit(baris.get("nip"))
        if digit and digit in by_nip:
            orang = by_nip[digit]
        if orang is None:
            orang = by_nama.get(nama_kunci(baris.get("nama")))
        if orang is None or orang["id"] in terpakai:
            tak_di_gtk.append(dict(baris))
            continue
        terpakai.add(orang["id"])
        rek_gtk = insentif.hanya_digit(orang.get("rekening"))
        rek_file = insentif.hanya_digit(baris.get("rekening"))
        if rek_gtk == rek_file:
            aksi = "SAMA"   # sudah sama (termasuk sama-sama kosong)
        elif not rek_gtk:
            aksi = "ISI"    # GTK kosong, berkas ada → diisi
        else:
            aksi = "BEDA"   # GTK terisi beda → dipertahankan
        cocok.append({"gtk_id": orang["id"], "gtk_nama": orang.get("nama"),
                      "gtk_nip": orang.get("nip") or "",
                      "gtk_rekening": str(orang.get("rekening") or ""),
                      "status": orang.get("status_kepegawaian") or "",
                      "aksi": aksi, "berkas": dict(baris)})
    tak_di_berkas = [o for o in gtk if o["id"] not in terpakai]
    jumlah_aksi = {"ISI": 0, "SAMA": 0, "BEDA": 0}
    for baris in cocok:
        jumlah_aksi[baris["aksi"]] += 1
    return {"cocok": cocok, "tak_di_gtk": tak_di_gtk,
            "tak_di_berkas": tak_di_berkas, "aksi": jumlah_aksi}


def simpan_draf(path: Path, nama_berkas: str, kunci: str = KUNCI_DRAF) -> None:
    insentif.simpan_pengaturan({kunci: json.dumps(
        {"path": str(path), "nama": nama_berkas,
         "waktu": _dt.datetime.now().strftime("%Y-%m-%d %H:%M")})})


def baca_draf(kunci: str = KUNCI_DRAF) -> dict[str, str] | None:
    try:
        draf = json.loads(insentif.baca_pengaturan().get(kunci) or "")
        if isinstance(draf, dict) and Path(draf.get("path", "")).exists():
            return draf
    except (ValueError, TypeError):
        pass
    return None


def hapus_draf(kunci: str = KUNCI_DRAF) -> None:
    db.execute("DELETE FROM insentif_setting WHERE key = ?", (kunci,))


def terapkan() -> dict[str, Any]:
    """Isi rekening GTK yang kosong dari draf; kembalikan ringkasan."""
    draf = baca_draf()
    if draf is None:
        raise ValueError("Tidak ada draf impor; unggah dulu berkas lamanya.")
    daftar = baca_berkas_rekening(draf["path"])
    hasil = cocokan(daftar)
    terisi = 0
    with db.transaction() as conn:
        for baris in hasil["cocok"]:
            if baris["aksi"] != "ISI":
                continue
            conn.execute("UPDATE gtk_pegawai SET rekening = ? WHERE id = ?",
                         (baris["berkas"]["rekening"].strip(), baris["gtk_id"]))
            terisi += 1
    hapus_draf()
    Path(draf["path"]).unlink(missing_ok=True)
    ringkas = {"waktu": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
               "berkas": draf.get("nama", ""), "baris": len(daftar),
               "cocok": len(hasil["cocok"]), "terisi": terisi,
               "sama": hasil["aksi"]["SAMA"], "beda": hasil["aksi"]["BEDA"],
               "tak_di_gtk": len(hasil["tak_di_gtk"]),
               "tak_di_berkas": len(hasil["tak_di_berkas"])}
    insentif.simpan_pengaturan({KUNCI_HASIL: json.dumps(ringkas)})
    log.info("Impor rekening: %d terisi dari %s", terisi, draf.get("nama"))
    return ringkas


def status() -> dict[str, Any]:
    """Status impor untuk beranda & halaman impor."""
    kurang = int(db.query_value(
        "SELECT COUNT(*) FROM gtk_pegawai "
        "WHERE TRIM(COALESCE(rekening, '')) = ''", default=0) or 0)
    try:
        terakhir = json.loads(insentif.baca_pengaturan().get(KUNCI_HASIL) or "")
        if not isinstance(terakhir, dict):
            terakhir = None
    except (ValueError, TypeError):
        terakhir = None
    return {"kurang": kurang, "terakhir": terakhir, "draf": baca_draf()}


# --------------------------------------------------------------------------- #
# Cetak SPJ langsung dari berkas mentah
# --------------------------------------------------------------------------- #

def _uang(teks: Any) -> int:
    """"2.700.000" → 2700000; kosong/rusak → 0."""
    try:
        return int(re.sub(r"\D", "", _sel_teks(teks)) or 0)
    except (ValueError, TypeError):
        return 0


def bulan_tahun_judul(lokasi: str | Path) -> tuple[int | None, int | None]:
    """Ambil (bulan, tahun) dari judul berkas («BULAN : X TAHUN ANGGARAN»)."""
    lokasi = Path(lokasi)
    mentah = lokasi.read_bytes()
    teks = ""
    if b"<table" in mentah[:2000].lower():
        teks = mentah.decode("utf-8", errors="replace")
    else:
        from .readers import read_spreadsheet
        try:
            for sheet in read_spreadsheet(lokasi):
                for baris in sheet.rows[:12]:
                    teks += " ".join(_sel_teks(sel) for sel in baris) + "\n"
        except Exception:
            return None, None
    cari = re.search(r"BULAN\s*:?\s*([A-Z]+)\s+TAHUN\s+ANGGARAN\s+(\d{4})",
                     teks.upper())
    if not cari:
        return None, None
    peta = {nama.lower(): i for i, nama in enumerate(insentif.NAMA_BULAN)
            if nama}
    return peta.get(cari.group(1).lower()), int(cari.group(2))


def roster_dari_berkas(daftar: list[Mapping[str, str]]) -> list[dict[str, Any]]:
    """Ubah baris berkas → baris SPJ (urutan berkas dipertahankan)."""
    hasil = []
    for baris in daftar:
        hasil.append({
            "nama_tampil": str(baris.get("nama") or "").strip(),
            "nip": str(baris.get("nip") or "").strip(),
            "npwp": str(baris.get("npwp") or "").strip(),
            "rekening": str(baris.get("rekening") or "").strip(),
            "nik": str(baris.get("nik") or "").strip(),
            "gol": str(baris.get("gol") or "").strip(),
            "jabatan": str(baris.get("jabatan") or "Guru").strip() or "Guru",
            "tarif": _uang(baris.get("bayar")),
            "pph_nominal": _uang(baris.get("pph"))})
    return hasil


def ttd_bawaan() -> dict[str, str]:
    """Penandatangan bawaan (KS + bendahara + pengawas) untuk cetak berkas."""
    kosong = {"ks_nama": "", "ks_nip": "", "bendahara_nama": "",
              "bendahara_nip": "", "pengawas_nama": "", "pengawas_nip": ""}
    try:
        awal = insentif._ttd_awal(insentif.baca_pengaturan())
    except Exception:
        return kosong
    kosong.update({k: str(v or "") for k, v in awal.items() if k in kosong})
    return kosong
