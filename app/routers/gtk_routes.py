"""Menu Guru & Tendik (GTK) — impor berkas mentah Dapodik lalu menyimpannya.

Alurnya sama seperti impor data siswa: **unggah → pratinjau → simpan**, supaya
tidak ada data yang masuk sebelum dilihat manusia. Berkas «daftar guru» dan
«daftar tendik» yang diunduh dari Dapodik langsung terbaca apa adanya (judul
kolom ditemukan sendiri pada baris 5, kop baris 1-4 dilewati).
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import auth, config, db, gtk, insentif, services
from ..readers import UnsupportedFormatError, format_label, supported_extensions
from ..web import render

log = logging.getLogger("sm.gtk.web")

router = APIRouter()


def _kembali(alamat: str, level: str, pesan: str) -> RedirectResponse:
    return RedirectResponse(f"{alamat}?level={level}&msg={quote_plus(pesan)}", status_code=303)


@router.get("/gtk")
def halaman_gtk(
    request: Request,
    jenis: str = "",
    status: str = "",
    cari: str = "",
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Halaman utama GTK: unggah berkas, riwayat impor, daftar pegawai."""
    pegawai = gtk.daftar_pegawai(jenis=jenis, status=status, cari=cari, batas=500)
    manual = insentif.daftar_jabatan_set()
    for baris in pegawai:
        jabatan, diset = insentif.jabatan_efektif(baris, manual.get(int(baris["id"])))
        baris["jabatan_insentif"] = jabatan
        baris["jabatan_manual"] = diset
    return render(
        request,
        "gtk/index.html",
        {
            "page_title": "Guru & Tendik",
            "format_didukung": [(ext, format_label(ext)) for ext in supported_extensions()],
            "maks_ukuran": config.MAX_UPLOAD_MB,
            "ringkas": gtk.ringkas_pegawai(),
            "riwayat": gtk.daftar_impor(limit=20),
            "pegawai": pegawai,
            "daftar_jenis": gtk.daftar_jenis(),
            "daftar_status": gtk.daftar_status(),
            "filter": {"jenis": jenis, "status": status, "cari": cari},
        },
    )


@router.post("/gtk/unggah")
async def unggah_gtk(
    request: Request,
    berkas: UploadFile = File(...),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Baca berkas mentah Dapodik (daftar guru / daftar tendik) lalu pratinjau."""
    nama = berkas.filename or "unggahan.xlsx"
    isi = await berkas.read()
    ext = Path(nama).suffix.lower()

    if not isi:
        return _kembali("/gtk", "err", "Berkas kosong atau gagal dibaca.")
    if ext not in gtk.EKSTENSI_GTK:
        return _kembali("/gtk", "err",
                        f"Jenis berkas «{ext or 'tanpa ekstensi'}» belum didukung menu ini. "
                        "Yang didukung: " + ", ".join(gtk.EKSTENSI_GTK))
    if len(isi) > config.MAX_UPLOAD_BYTES:
        return _kembali("/gtk", "err", f"Ukuran berkas melebihi {config.MAX_UPLOAD_MB} MB.")

    try:
        simpan = services.save_upload(nama, isi)
        sheet, hasil, fmt = gtk.baca_berkas(simpan.path, simpan.extension)
    except UnsupportedFormatError as galat:
        return _kembali("/gtk", "err", str(galat))
    except gtk.GtkError as galat:
        return _kembali("/gtk", "err", f"Gagal membaca berkas: {galat}")
    except Exception as galat:  # noqa: BLE001
        log.exception("Gagal membaca berkas GTK %s", nama)
        return _kembali("/gtk", "err", f"Gagal membaca berkas: {galat}")

    if not hasil.records:
        simpan.path.unlink(missing_ok=True)
        return _kembali("/gtk", "err",
                        "Tidak ada baris data yang terbaca pada berkas ini. Pastikan berkasnya "
                        "adalah hasil unduhan Dapodik (daftar guru / daftar tendik).")

    import_id = gtk.buat_impor(nama_berkas=nama, path=simpan.path, ext=simpan.extension,
                               ukuran=simpan.size, sheet=sheet, hasil=hasil, fmt=fmt,
                               actor=user.username)
    return RedirectResponse(f"/gtk/impor/{import_id}", status_code=303)


@router.get("/gtk/impor/{import_id}")
def pratinjau_gtk(
    request: Request,
    import_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Pratinjau hasil pembacaan sebelum disimpan."""
    kepala = gtk.get_impor(import_id)
    if kepala is None:
        return _kembali("/gtk", "err", "Pratinjau impor itu tidak ditemukan.")

    sumber = Path(kepala.get("sumber_path") or "")
    daftar: list[dict] = []
    ringkas = {"error": 0, "warning": 0, "info": 0}
    galat = ""
    if sumber.exists():
        try:
            _, hasil, _ = gtk.baca_berkas(sumber, kepala.get("ext") or sumber.suffix.lower())
            daftar = [
                {
                    "row_number": item.row_number,
                    "nama": item.values.get("nama") or "-",
                    "nuptk": item.values.get("nuptk") or "",
                    "nip": item.values.get("nip") or "",
                    "jenis_ptk": item.values.get("jenis_ptk") or "",
                    "status": item.values.get("status_kepegawaian") or "",
                    "error": item.has_error,
                    "temuan": [t.message for t in item.issues],
                }
                for item in hasil.records
            ]
            ringkas = gtk.ringkas_temuan(hasil.issues)
        except gtk.GtkError as exc:
            galat = str(exc)
    else:
        galat = "Berkas sumber sudah tidak ada di folder unggahan — unggah ulang berkasnya."

    return render(
        request,
        "gtk/pratinjau.html",
        {
            "page_title": "Pratinjau GTK",
            "kepala": kepala,
            "daftar": daftar,
            "ringkas": ringkas,
            "catatan": (kepala.get("catatan") or "").splitlines(),
            "kolom": kepala.get("kolom") or {},
            "galat": galat,
            "batas_tampil": 200,
        },
    )


@router.post("/gtk/impor/{import_id}/simpan")
def simpan_gtk(
    request: Request,
    import_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Simpan baris GTK ke daftar pegawai (baris yang sama tidak digandakan)."""
    kepala = gtk.get_impor(import_id)
    if kepala is None:
        return _kembali("/gtk", "err", "Pratinjau impor itu tidak ditemukan.")
    if kepala.get("status") == "tersimpan":
        return _kembali(f"/gtk/impor/{import_id}", "warn",
                        "Impor ini sudah pernah disimpan — simpan ulang tidak menggandakan data. "
                        "Bila berkasnya diperbarui, unggah lagi sebagai impor baru.")
    sumber = Path(kepala.get("sumber_path") or "")
    if not sumber.exists():
        return _kembali("/gtk", "err", "Berkas sumber sudah tidak ada; unggah ulang berkasnya.")

    try:
        _, hasil, _ = gtk.baca_berkas(sumber, kepala.get("ext") or sumber.suffix.lower())
    except gtk.GtkError as galat:
        return _kembali(f"/gtk/impor/{import_id}", "err", str(galat))

    if not hasil.records:
        return _kembali(f"/gtk/impor/{import_id}", "warn",
                        "Tidak ada baris data yang terbaca, jadi tidak ada yang disimpan.")

    simpan = gtk.simpan_banyak(import_id, hasil.records, source_file=kepala.get("berkas"))
    gtk.tandai_impor(import_id, status="tersimpan", baru=simpan["baru"],
                     diperbarui=simpan["diperbarui"], dilewati=simpan["dilewati"],
                     gagal=simpan["gagal"])
    services.log_audit(user.username, user.role, "gtk_simpan", "gtk_imports", import_id,
                 f"«{kepala.get('berkas')}»: {simpan['baru']} baru, {simpan['diperbarui']} "
                 f"diperbarui, {simpan['dilewati']} sama, {simpan['gagal']} gagal")
    pesan = (f"{simpan['baru']} pegawai baru disimpan"
             + (f", {simpan['diperbarui']} diperbarui" if simpan["diperbarui"] else "")
             + (f", {simpan['dilewati']} sudah sama (tidak diubah)" if simpan["dilewati"] else "")
             + (f", {simpan['gagal']} gagal" if simpan["gagal"] else "") + ".")
    if simpan["daftar_gagal"]:
        pesan += " Contoh yang gagal: " + "; ".join(simpan["daftar_gagal"][:3])
    return _kembali(f"/gtk/impor/{import_id}", "ok", pesan)


@router.post("/gtk/impor/{import_id}/hapus")
def hapus_impor_gtk(
    request: Request,
    import_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    kepala = gtk.get_impor(import_id)
    if kepala is None:
        return _kembali("/gtk", "err", "Impor itu tidak ditemukan.")
    gtk.hapus_impor(import_id)
    services.log_audit(user.username, user.role, "gtk_hapus_impor", "gtk_imports", import_id,
                 f"impor «{kepala.get('berkas')}» dihapus beserta pegawainya")
    return _kembali("/gtk", "ok",
                    f"Impor «{kepala.get('berkas')}» dan pegawai hasil impor itu dihapus.")


@router.get("/gtk/pegawai/{pegawai_id}")
def detail_pegawai(
    request: Request,
    pegawai_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Detail satu pegawai: seluruh isi berkas apa adanya, dikelompokkan."""
    baris = gtk.get_pegawai(pegawai_id)
    if baris is None:
        return _kembali("/gtk", "err", "Data pegawai itu tidak ditemukan.")
    return render(
        request,
        "gtk/detail.html",
        {
            "page_title": baris.get("nama") or "Detail Pegawai",
            "item": baris,
            "insentif_info": insentif.info_insentif_pegawai(pegawai_id),
            "grup": gtk.fields_by_group(),
            "label_grup": gtk.GROUP_LABELS,
        },
    )


@router.post("/gtk/pegawai/{pegawai_id}/jabatan-insentif")
def set_jabatan_insentif(
    request: Request,
    pegawai_id: int,
    jabatan: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    """Set jabatan insentif pegawai (kosong = otomatis dari data GTK)."""
    baris = gtk.get_pegawai(pegawai_id)
    if baris is None:
        return _kembali("/gtk", "err", "Data pegawai itu tidak ditemukan.")
    jabatan = jabatan.strip()
    if jabatan and jabatan not in ("Kepala Sekolah", "Wakil Kepala Sekolah",
                                   "Guru", "Tenaga Kependidikan", "Pelatih"):
        return _kembali(f"/gtk/pegawai/{pegawai_id}", "err",
                        "Jabatan itu tidak dikenal.")
    profil = insentif.profil_untuk_gtk(pegawai_id)
    insentif.db.execute(
        "UPDATE insentif_profil SET jabatan = ?, diubah = datetime('now','localtime') "
        "WHERE id = ?",
        (jabatan or None, profil["id"]),
    )
    services.log_audit(user.username, user.role, "gtk_jabatan_insentif", "gtk_pegawai",
                 pegawai_id,
                 f"{baris['nama']}: jabatan insentif → «{jabatan or 'otomatis'}»")
    return _kembali(f"/gtk/pegawai/{pegawai_id}", "ok",
                    "Jabatan insentif disimpan; dipakai mulai draf bulan berikutnya.")


@router.post("/gtk/pegawai/{pegawai_id}/hapus")
def hapus_pegawai_satu(
    request: Request,
    pegawai_id: int,
    user: auth.SessionUser = Depends(auth.require_staff),
):
    baris = db.query_one("SELECT * FROM gtk_pegawai WHERE id = ?", (pegawai_id,))
    if baris is None:
        return _kembali("/gtk", "err", "Data pegawai itu tidak ditemukan.")
    gtk.hapus_satu(pegawai_id)
    services.log_audit(user.username, user.role, "gtk_hapus", "gtk_pegawai", pegawai_id,
                 f"{baris['nama']} dihapus dari daftar pegawai")
    return _kembali("/gtk", "ok", f"«{baris['nama']}» dihapus dari daftar pegawai.")


@router.post("/gtk/hapus")
def hapus_daftar_gtk(
    request: Request,
    jenis: str = Form(""),
    status: str = Form(""),
    cari: str = Form(""),
    user: auth.SessionUser = Depends(auth.require_staff),
):
    jumlah = gtk.hapus_pegawai(jenis=jenis.strip(), status=status.strip(), cari=cari.strip())
    services.log_audit(user.username, user.role, "gtk_hapus_daftar", "gtk_pegawai", None,
                 f"{jumlah} pegawai dihapus (jenis «{jenis or 'semua'}», "
                 f"status «{status or 'semua'}»)")
    return _kembali("/gtk", "ok", f"{jumlah} data pegawai dihapus.")


@router.get("/gtk/ekspor.csv")
def ekspor_gtk_csv(
    request: Request,
    jenis: str = "",
    status: str = "",
    cari: str = "",
    user: auth.SessionUser = Depends(auth.require_staff),
):
    isi = gtk.ekspor_csv(jenis=jenis, status=status, cari=cari)
    return Response(
        content=isi,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="daftar-gtk.csv"'},
    )


@router.get("/gtk/ekspor.xlsx")
def ekspor_gtk_xlsx(
    request: Request,
    jenis: str = "",
    status: str = "",
    cari: str = "",
    user: auth.SessionUser = Depends(auth.require_staff),
):
    isi = gtk.ekspor_xlsx(jenis=jenis, status=status, cari=cari)
    return Response(
        content=isi,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="daftar-gtk.xlsx"'},
    )
