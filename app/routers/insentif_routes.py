"""Menu Insentif — SPJ + absensi PNS/PPPK bulanan otomatis.

Alurnya: **pilih bulan → periksa draf → unduh PDF siap cetak**. Daftar
orang, tarif, PPh, tanggal merah, dan penandatangan terisi sendiri dari
data GTK + kalender bawaan; semuanya tetap bisa diubah per bulan.
"""

from __future__ import annotations

import datetime as dt
import logging
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from .. import auth, gtk, insentif, insentif_pdf, services
from ..web import render

log = logging.getLogger("sm.insentif.web")

router = APIRouter()

NAMA_BERKAS = {"pns": "absensi-pns", "pppk": "absensi-pppk", "spj": "spj-insentif"}


def _kembali(alamat: str, level: str, pesan: str) -> RedirectResponse:
    return RedirectResponse(f"{alamat}?level={level}&msg={quote_plus(pesan)}", status_code=303)


@router.get("/insentif")
def halaman_insentif(
    request: Request,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Beranda insentif: buat draf bulan + arsip periode + prasyarat."""
    kini = dt.date.today()
    return render(
        request,
        "insentif/index.html",
        {
            "page_title": "Insentif",
            "tahun_ini": kini.year,
            "bulan_ini": kini.month,
            "daftar_bulan": list(enumerate(insentif.NAMA_BULAN_KECIL))[1:],
            "periode": insentif.daftar_periode(),
            "pengaturan": insentif.baca_pengaturan(),
            "ringkas_gtk": gtk.ringkas_pegawai(),
        },
    )


@router.post("/insentif/periode/buat")
def buat_periode(
    request: Request,
    tahun: int = Form(0),
    bulan: int = Form(0),
    salin_dari: int = Form(0),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    if not tahun or not bulan:
        return _kembali("/insentif", "err", "Pilih tahun dan bulan dulu.")
    try:
        periode_id = insentif.buat_periode(
            tahun, bulan, salin_dari=salin_dari or None, actor=user.username)
    except ValueError as galat:
        return _kembali("/insentif", "err", str(galat))
    nama = f"{insentif.NAMA_BULAN_KECIL[bulan]} {tahun}"
    services.log_audit(user.username, user.role, "insentif_buat", "insentif_periode",
                 periode_id, f"draf {nama}" + (" (salinan)" if salin_dari else ""))
    return RedirectResponse(f"/insentif/periode/{periode_id}", status_code=303)


@router.post("/insentif/periode/{periode_id}/hapus")
def hapus_periode(
    request: Request,
    periode_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    periode = insentif.get_periode(periode_id)
    if periode is None:
        return _kembali("/insentif", "err", "Periode itu tidak ditemukan.")
    insentif.hapus_periode(periode_id)
    nama = f"{insentif.NAMA_BULAN_KECIL[int(periode['bulan'])]} {periode['tahun']}"
    services.log_audit(user.username, user.role, "insentif_hapus", "insentif_periode",
                 periode_id, f"draf {nama} dihapus")
    return _kembali("/insentif", "ok", f"Draf {nama} dihapus.")


@router.get("/insentif/periode/{periode_id}")
def buka_periode(
    request: Request,
    periode_id: int,
    dokumen: str = "spj",
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Editor draf: roster tiga dokumen + libur + tanda tangan + unduh."""
    periode = insentif.get_periode(periode_id)
    if periode is None:
        return _kembali("/insentif", "err", "Periode itu tidak ditemukan.")
    if dokumen not in ("pns", "pppk", "spj"):
        dokumen = "spj"
    merah = insentif.baca_libur_periode(periode)
    grid = insentif.grid_absensi(int(periode["tahun"]), int(periode["bulan"]), merah)
    return render(
        request,
        "insentif/periode.html",
        {
            "page_title": f"Insentif {insentif.NAMA_BULAN_KECIL[int(periode['bulan'])]} "
                          f"{periode['tahun']}",
            "periode": periode,
            "nama_bulan": insentif.NAMA_BULAN[int(periode["bulan"])],
            "nama_bulan_kecil": insentif.NAMA_BULAN_KECIL[int(periode["bulan"])],
            "dokumen": dokumen,
            "roster": {nama: insentif.roster_periode(periode_id, nama)
                       for nama, _label in insentif.DOKUMEN},
            "luar": {nama: insentif.luar_roster(periode_id, nama)
                     for nama, _label in insentif.DOKUMEN},
            "merah": sorted(merah.items()),
            "grid": grid,
            "ttd": insentif.baca_ttd(periode),
            "ringkas": insentif.ringkas_spj(insentif.roster_periode(periode_id, "spj")),
            "pengaturan": insentif.baca_pengaturan(),
        },
    )


@router.post("/insentif/periode/{periode_id}/tambah")
def tambah_orang(
    request: Request,
    periode_id: int,
    dokumen: str = Form(...),
    gtk_id: int = Form(0),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    try:
        insentif.tambah_dari_gtk(periode_id, dokumen, gtk_id)
    except ValueError as galat:
        return _kembali(f"/insentif/periode/{periode_id}?dokumen={dokumen}",
                        "err", str(galat))
    return _kembali(f"/insentif/periode/{periode_id}?dokumen={dokumen}",
                    "ok", "Satu orang ditambahkan ke daftar.")


@router.post("/insentif/roster/{baris_id}/ubah")
def ubah_orang(
    request: Request,
    baris_id: int,
    dokumen: str = Form("spj"),
    nama_tampil: str = Form(""),
    nip: str = Form(""),
    npwp: str = Form(""),
    rekening: str = Form(""),
    nik: str = Form(""),
    gol: str = Form(""),
    jabatan: str = Form(""),
    tarif: str = Form(""),
    pph_nominal: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    from .. import db as _db
    kini = _db.row_to_dict(_db.query_one(
        "SELECT * FROM insentif_roster WHERE id = ?", (baris_id,)))
    if kini is None:
        return _kembali("/insentif", "err", "Baris daftar tidak ditemukan.")
    try:
        insentif.ubah_roster(baris_id, {"nama_tampil": nama_tampil, "nip": nip,
                                       "npwp": npwp, "rekening": rekening,
                                       "nik": nik, "gol": gol, "jabatan": jabatan,
                                       "tarif": tarif, "pph_nominal": pph_nominal})
    except ValueError as galat:
        return _kembali(f"/insentif/periode/{kini['periode_id']}?dokumen={dokumen}",
                        "err", str(galat))
    return _kembali(f"/insentif/periode/{kini['periode_id']}?dokumen={dokumen}",
                    "ok", "Perubahan disimpan.")


@router.post("/insentif/roster/{baris_id}/hapus")
def hapus_orang(
    request: Request,
    baris_id: int,
    dokumen: str = Form("spj"),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    from .. import db as _db
    kini = _db.row_to_dict(_db.query_one(
        "SELECT * FROM insentif_roster WHERE id = ?", (baris_id,)))
    if kini is None:
        return _kembali("/insentif", "err", "Baris daftar tidak ditemukan.")
    insentif.hapus_roster(baris_id)
    return _kembali(f"/insentif/periode/{kini['periode_id']}?dokumen={dokumen}",
                    "ok", f"«{kini.get('nama_tampil')}» dikeluarkan dari daftar.")


@router.post("/insentif/roster/{baris_id}/geser")
def geser_orang(
    request: Request,
    baris_id: int,
    dokumen: str = Form("spj"),
    arah: int = Form(0),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    from .. import db as _db
    kini = _db.row_to_dict(_db.query_one(
        "SELECT * FROM insentif_roster WHERE id = ?", (baris_id,)))
    if kini is None:
        return _kembali("/insentif", "err", "Baris daftar tidak ditemukan.")
    insentif.geser_roster(baris_id, arah)
    return RedirectResponse(
        f"/insentif/periode/{kini['periode_id']}?dokumen={dokumen}", status_code=303)


@router.post("/insentif/roster/{baris_id}/bawaan")
def bawaan_orang(
    request: Request,
    baris_id: int,
    dokumen: str = Form("spj"),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    from .. import db as _db
    kini = _db.row_to_dict(_db.query_one(
        "SELECT * FROM insentif_roster WHERE id = ?", (baris_id,)))
    if kini is None:
        return _kembali("/insentif", "err", "Baris daftar tidak ditemukan.")
    try:
        insentif.jadikan_bawaan(baris_id)
    except ValueError as galat:
        return _kembali(f"/insentif/periode/{kini['periode_id']}?dokumen={dokumen}",
                        "err", str(galat))
    return _kembali(f"/insentif/periode/{kini['periode_id']}?dokumen={dokumen}",
                    "ok", "Nama & jabatan ini dipakai sebagai bawaan bulan-bulan berikut.")


@router.post("/insentif/periode/{periode_id}/ttd")
def simpan_tanda_tangan(
    request: Request,
    periode_id: int,
    tgl_absensi: str = Form("31"),
    tgl_spj: str = Form("31"),
    ks_nama: str = Form(""),
    ks_nip: str = Form(""),
    bendahara_nama: str = Form(""),
    bendahara_nip: str = Form(""),
    pengawas_nama: str = Form(""),
    pengawas_nip: str = Form(""),
    catatan: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    try:
        insentif.simpan_ttd(periode_id, {"tgl_absensi": tgl_absensi, "tgl_spj": tgl_spj,
                                        "ks_nama": ks_nama, "ks_nip": ks_nip,
                                        "bendahara_nama": bendahara_nama,
                                        "bendahara_nip": bendahara_nip,
                                        "pengawas_nama": pengawas_nama,
                                        "pengawas_nip": pengawas_nip,
                                        "catatan": catatan})
    except ValueError as galat:
        return _kembali(f"/insentif/periode/{periode_id}", "err", str(galat))
    return _kembali(f"/insentif/periode/{periode_id}", "ok",
                    "Tanggal & penandatangan disimpan.")


def _pdf_response(isi: bytes, nama: str) -> Response:
    return Response(
        content=isi,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )


@router.get("/insentif/periode/{periode_id}/pdf/{dokumen}")
def unduh_pdf(
    request: Request,
    periode_id: int,
    dokumen: str,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    periode = insentif.get_periode(periode_id)
    if periode is None:
        return _kembali("/insentif", "err", "Periode itu tidak ditemukan.")
    if dokumen not in (*NAMA_BERKAS, "gabungan"):
        return _kembali(f"/insentif/periode/{periode_id}", "err",
                        "Dokumen tidak dikenal.")
    kode = f"{int(periode['tahun']):04d}{int(periode['bulan']):02d}"
    if dokumen == "gabungan":
        isi = insentif_pdf.pdf_gabungan(periode)
        nama = f"insentif-{kode}-gabungan.pdf"
    elif dokumen == "spj":
        isi = insentif_pdf.pdf_spj(
            periode, insentif.roster_periode(periode_id, "spj"))
        nama = f"insentif-{kode}-{NAMA_BERKAS[dokumen]}.pdf"
    else:
        isi = insentif_pdf.pdf_absensi(
            dokumen, periode, insentif.roster_periode(periode_id, dokumen))
        nama = f"insentif-{kode}-{NAMA_BERKAS[dokumen]}.pdf"
    services.log_audit(user.username, user.role, "insentif_pdf", "insentif_periode",
                 periode_id, f"unduh {dokumen} {kode}")
    return _pdf_response(isi, nama)


@router.get("/insentif/pengaturan")
def halaman_pengaturan(
    request: Request,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    return render(
        request,
        "insentif/pengaturan.html",
        {
            "page_title": "Pengaturan Insentif",
            "pengaturan": insentif.baca_pengaturan(),
            "pegawai": gtk.daftar_pegawai(batas=500),
        },
    )


@router.post("/insentif/pengaturan")
def simpan_pengaturan(
    request: Request,
    tarif_ks: str = Form("7000000"),
    tarif_waka: str = Form("2700000"),
    tarif_guru: str = Form("1350000"),
    tarif_pelatih: str = Form("650000"),
    pph_guru_3: str = Form("67500"),
    pph_guru_4: str = Form("202500"),
    pph_waka_3: str = Form("135000"),
    pph_waka_4: str = Form("405000"),
    pph_ks_3: str = Form("350000"),
    pph_ks_4: str = Form("1050000"),
    pph_nonasn: str = Form("0"),
    unit_kerja: str = Form(""),
    kecamatan: str = Form(""),
    kota: str = Form(""),
    bendahara_gtk_id: str = Form(""),
    pengawas_nama: str = Form(""),
    pengawas_nip: str = Form(""),
    ks_nama: str = Form(""),
    ks_nip: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    insentif.simpan_pengaturan({
        "tarif_ks": tarif_ks, "tarif_waka": tarif_waka,
        "tarif_guru": tarif_guru, "tarif_pelatih": tarif_pelatih,
        "pph_guru_3": pph_guru_3, "pph_guru_4": pph_guru_4,
        "pph_waka_3": pph_waka_3, "pph_waka_4": pph_waka_4,
        "pph_ks_3": pph_ks_3, "pph_ks_4": pph_ks_4, "pph_nonasn": pph_nonasn,
        "unit_kerja": unit_kerja, "kecamatan": kecamatan, "kota": kota,
        "bendahara_gtk_id": bendahara_gtk_id, "pengawas_nama": pengawas_nama,
        "pengawas_nip": pengawas_nip, "ks_nama": ks_nama, "ks_nip": ks_nip,
    })
    services.log_audit(user.username, user.role, "insentif_pengaturan", "-", None,
                 "tarif, PPh & penandatangan diperbarui")
    return _kembali("/insentif/pengaturan", "ok",
                    "Pengaturan disimpan; dipakai mulai draf berikutnya.")


@router.get("/insentif/libur")
def halaman_libur(
    request: Request,
    tahun: int = 0,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    if not tahun:
        tahun = dt.date.today().year
    return render(
        request,
        "insentif/libur.html",
        {
            "page_title": "Kelola Libur Insentif",
            "tahun": tahun,
            "daftar": insentif.daftar_libur_tahun(tahun),
        },
    )


@router.post("/insentif/libur/simpan")
def simpan_libur(
    request: Request,
    tahun: int = Form(0),
    tanggal: str = Form(""),
    nama: str = Form(""),
    jenis: str = Form("kustom"),
    aktif: str = Form("1"),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    try:
        insentif.simpan_libur(tanggal.strip(), nama.strip(), jenis.strip(),
                             aktif.strip() == "1")
    except ValueError as galat:
        return _kembali(f"/insentif/libur?tahun={tahun or dt.date.today().year}",
                        "err", f"Tanggal tidak sah: {galat}")
    if not nama.strip() and aktif.strip() == "1":
        return _kembali(f"/insentif/libur?tahun={tahun or dt.date.today().year}",
                        "err", "Nama libur wajib diisi.")
    return _kembali(f"/insentif/libur?tahun={tahun or dt.date.today().year}",
                    "ok", "Kalender libur diperbarui; dipakai mulai draf berikutnya.")


@router.post("/insentif/libur/hapus")
def hapus_libur(
    request: Request,
    tahun: int = Form(0),
    tanggal: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    insentif.hapus_libur(tanggal.strip())
    return _kembali(f"/insentif/libur?tahun={tahun or dt.date.today().year}",
                    "ok", "Aturan manual tanggal itu dihapus (kembali ke bawaan).")


@router.get("/insentif/profil")
def halaman_profil(
    request: Request,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    return render(
        request,
        "insentif/profil.html",
        {
            "page_title": "Profil Insentif Pegawai",
            "daftar": insentif.daftar_profil(),
        },
    )


@router.post("/insentif/profil/{profil_id}")
def simpan_satu_profil(
    request: Request,
    profil_id: int,
    nama_tampil: str = Form(""),
    jabatan: str = Form(""),
    tarif_override: str = Form(""),
    ikut_pns: str = Form(""),
    ikut_pppk: str = Form(""),
    ikut_spj: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    insentif.simpan_profil(profil_id, {"nama_tampil": nama_tampil,
                                      "jabatan": jabatan,
                                      "tarif_override": tarif_override,
                                      "ikut_pns": ikut_pns == "1",
                                      "ikut_pppk": ikut_pppk == "1",
                                      "ikut_spj": ikut_spj == "1"})
    return _kembali("/insentif/profil", "ok",
                    "Profil disimpan; dipakai mulai draf berikutnya.")