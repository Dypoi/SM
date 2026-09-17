"""Uji khusus bot Dapodik di peramban palsu (tanpa Chrome).

Menjalankan bot sungguhan (`app.bot_dapodik`) di atas `scripts.peramban_palsu` yang
menirukan Dapodik, lalu memeriksa **keadaan halaman yang sebenarnya** — bukan sekadar
apa yang tertulis pada log. Dipakai untuk memastikan perbaikan pada baris «Jarak rumah
ke sekolah» (radio + kolom kilometer) benar-benar bekerja pada struktur DOM sekolah:

* label ``x-form-cb-label`` berada SESUDAH input (poros ``preceding::``/``ancestor::``);
* keadaan tercentang hanya terbaca dari kelas ``x-form-cb-checked`` pembungkusnya;
* kolom ``jarak_rumah_ke_sekolah_km`` **nonaktif** sampai «lebih dari 1 km» terpasang;
* setiap unsur Ext JS membawa ``data-componentid`` sehingga ``Ext.getCmp(...)`` bisa
  dipakai sebagai jalur pamungkas bila semua klik ditelan Dapodik.

Jalankan:  python scripts/uji_bot_dapodik.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bot_dapodik, config, migrations  # noqa: E402
from scripts import peramban_palsu  # noqa: E402

config.ensure_dirs()
migrations.run_migrations()

OPSI = {
    "bot_url": "http://dapodik.local", "bot_username": "u@c.id", "bot_password": "r",
    "bot_simulasi": "0", "bot_timeout": "15", "bot_jeda_muat": "5", "bot_max_retries": "3",
    "bot_hobi": "Olah Raga", "bot_cita": "Pegawai Negeri Sipil / PNS", "bot_jawaban_ya": "1",
    "bot_sekolah_asal": "1", "bot_data_periodik": "1", "bot_periodik_jarak": "1",
}
SISWA = {
    "nisn": "0113374384", "nipd": "24257001", "nama": "Uji",
    "sekolah_asal": "SD NEGERI TAMAN SUKARYA 1", "tinggi_badan": 155.0,
    "berat_badan": 45.0, "lingkar_kepala": 52, "jml_saudara": 1, "jarak_rumah": 2,
}


class _WaktuCepat:
    """Jam palsu: ``time.sleep`` jadi instan tapi urutannya tetap sama."""

    def __init__(self, asli) -> None:
        self._asli = asli
        self.maju = 0.0

    def __getattr__(self, nama):
        return getattr(self._asli, nama)

    def time(self) -> float:
        return self.maju

    def monotonic(self) -> float:
        return self.maju

    def sleep(self, detik: float = 0) -> None:
        self.maju += float(detik or 0)
        self._asli.sleep(min(float(detik or 0), 0.02))


def jalankan(judul: str, jarak, atur=None, tampilkan: bool = False):
    """Jalankan bot untuk satu siswa pada keadaan halaman tertentu."""
    jejak: list[str] = []
    jam = _WaktuCepat(time)
    asli = bot_dapodik.time
    bot_dapodik.time = jam
    try:
        peramban = peramban_palsu.buat("alur_penuh").pakai_jam(jam.monotonic)
        peramban.popup_detik = None
        peramban.registrasi_otomatis = True
        if atur:
            atur(peramban)
        peramban.nisn_dicari = SISWA["nisn"]
        peramban.tambah_baris_siswa(SISWA["nisn"])
        bot = bot_dapodik.BotDapodik(0, [], [], dict(OPSI), kepala=jejak.append)
        bot._login(peramban)
        bot._proses_satu(peramban, {**SISWA, "jarak_rumah": jarak}, None)
    finally:
        bot_dapodik.time = asli
    km = next(unsur for unsur in peramban.unsur
              if unsur.name == "jarak_rumah_ke_sekolah_km")
    print(f"--- {judul} ---")
    if tampilkan:
        print("\n".join("    " + baris for baris in jejak if "[periodik]" in baris))
    print(f"    radio: {peramban.jarak_pilihan!r} | km aktif: {km.enabled} | km tersimpan: "
          f"{peramban.data_periodik_tersimpan.get('jarak_rumah_ke_sekolah_km')!r}")
    print(f"    Ext.setValue {peramban.ext_setvalue_dipakai}x · dibaca lewat kelas "
          f"{peramban.dibaca_lewat_kelas}x · klik ditelan {peramban.klik_diabaikan}x")
    hasil = [baris for baris in jejak if baris.startswith(("[OK]", "[GAGAL]"))]
    print(f"    hasil: {hasil[-1] if hasil else '(tidak ada hasil)'}")
    return peramban, jejak


def main() -> int:
    """Jalankan semua skenario; kembalikan 0 bila semuanya lolos."""
    pemeriksaan = 0

    def cek(syarat: bool, pesan: str) -> None:
        nonlocal pemeriksaan
        assert syarat, pesan
        pemeriksaan += 1

    # 1) Keadaan biasa pada DOM sekolah: radio dipilih lewat labelnya, kolom km baru
    #    aktif setelah itu, lalu terisi.
    p1, j1 = jalankan("1. DOM sekolah: pilih lewat label → kolom km aktif lalu diisi", 2,
                      tampilkan=True)
    cek(p1.jarak_pilihan == "Lebih dari 1 km", f"radio salah: {p1.jarak_pilihan!r}")
    cek(p1.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "2",
        f"kolom km tidak tersimpan: {p1.data_periodik_tersimpan}")
    cek(any("dipilih lewat labelnya" in baris for baris in j1), j1[-4:])

    # 2) Keadaan tercentang hanya terbaca dari kelas x-form-cb-checked (persis DOM sekolah).
    p2, j2 = jalankan("2. tercentang hanya terbaca dari kelas x-form-cb-checked", 2,
                      atur=lambda p: setattr(p, "keadaan_lewat_kelas", True))
    cek(p2.jarak_pilihan == "Lebih dari 1 km", f"radio salah: {p2.jarak_pilihan!r}")
    cek(p2.dibaca_lewat_kelas >= 1, "bot tidak membaca keadaan lewat kelas x-form-cb-checked")
    cek(p2.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "2", "km tidak tersimpan")

    # 3) Semua klik ditelan → jalur pamungkas Ext.getCmp(...).setValue(...) lewat componentid.
    p3, j3 = jalankan("3. semua klik ditelan → Ext.getCmp(id).setValue(true)", 2,
                      atur=lambda p: setattr(p, "hanya_ext_yang_menerima", True),
                      tampilkan=True)
    cek(p3.jarak_pilihan == "Lebih dari 1 km", f"radio salah: {p3.jarak_pilihan!r}")
    cek(p3.ext_setvalue_dipakai >= 1, "bot tidak memakai Ext.getCmp sebagai jalur pamungkas")
    cek(any("Ext JS sendiri" in baris for baris in j3), [b for b in j3 if "periodik" in b])

    # 4) Radio benar-benar gagal → kolom km dilewati dengan jujur (Dapodik menonaktifkannya).
    p4, j4 = jalankan("4. radio gagal total → kolom km dilewati dengan jujur", 2,
                      atur=lambda p: (setattr(p, "hanya_ext_yang_menerima", True),
                                      setattr(p, "ext_mati", True)), tampilkan=True)
    cek(p4.jarak_pilihan == "", f"radio seharusnya tidak terpilih: {p4.jarak_pilihan!r}")
    cek(not str(p4.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") or "").strip(),
        f"kolom km terisi padahal radionya gagal: {p4.data_periodik_tersimpan}")
    cek(any("belum menandainya terpilih" in baris for baris in j4), j4[-4:])
    cek(any("dilewati" in baris and "belum terpasang" in baris for baris in j4), j4[-4:])

    # 5) Data jarak ≤ 1 km → pilihan «kurang dari 1 km», km tidak diisi.
    p5, _ = jalankan("5. jarak 0,7 km → «kurang dari 1 km», km tidak diisi", 0.7)
    cek(p5.jarak_pilihan == "Kurang dari 1 km", f"radio salah: {p5.jarak_pilihan!r}")
    cek(not str(p5.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") or "").strip(),
        "kolom km terisi untuk jarak ≤ 1 km")

    # 6) Data jarak kosong → tidak ada pilihan yang ditebak.
    p6, j6 = jalankan("6. jarak kosong → tidak ada pilihan ditebak", "")
    cek(p6.jarak_pilihan == "", f"radio seharusnya kosong: {p6.jarak_pilihan!r}")
    cek(any("Jarak Rumah ke Sekolah) kosong" in baris for baris in j6), j6[-4:])

    print(f"\n[SELESAI] {pemeriksaan} pemeriksaan lolos pada 6 skenario")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
