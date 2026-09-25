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
    "bot_isi_bio": "0",          # dinyalakan pada skenario BIO (lihat skenario 10-11)
}
SISWA = {
    "nisn": "0113374384", "nipd": "24257001", "nama": "Uji",
    "sekolah_asal": "SD NEGERI TAMAN SUKARYA 1", "tinggi_badan": 155.0,
    "berat_badan": 45.0, "lingkar_kepala": 52, "jml_saudara": 1, "jarak_rumah": 2,
    # Kolom jendela «Ubah» (BIO) — persis kolom yang diisi skrip sekolah. «No. Registrasi
    # Akta Lahir» sengaja dibiarkan kosong: bot harus melewatinya dengan jujur, bukan
    # mengosongkan kolom Dapodik.
    "no_kk": "3201234567890001", "no_registrasi_akta": "", "alamat": "Jl. Melati No. 7",
    "rt": "3", "rw": "5", "kode_pos": "15157", "anak_ke": 2,
    "ayah_nama": "Bapak Uji", "ayah_nik": "3201234567890002",
    "ayah_tahun_lahir": 1980, "ayah_pendidikan": "SMA / sederajat",
    # Kolom dropdown (combo): nama kolomnya dari DOM asli halaman Dapodik (ronde 17) —
    # «pekerjaan_id_ayah» / «penghasilan_id_ayah» — persis seperti yang dikirim sekolah.
    # dengan aplikasi SM; pendidikannya sengaja berbeda («SMA / sederajat» vs «SMA» di
    # Dapodik pada tangkapan layar sekolah) supaya pencocokan pilihannya benar-benar diuji.
    "ayah_pekerjaan": "Petani", "ayah_penghasilan": "Rp. 500,000 - Rp. 999,999",
    "ibu_nik": "3201234567890003", "ibu_tahun_lahir": 1983,
    "ibu_pendidikan": "SMP / sederajat",
    "ibu_pekerjaan": "Tidak Bekerja", "ibu_penghasilan": "Tidak Berpenghasilan",
}

#: Kolom BIO yang diisi skrip sekolah — (kunci data siswa, nama kolom Dapodik, nilai uji).
BIO_UJI: tuple[tuple[str, str, str], ...] = (
    ("no_kk", "no_kk", "3201234567890001"),
    ("alamat", "alamat_jalan", "Jl. Melati No. 7"),
    ("rt", "rt", "3"),
    ("rw", "rw", "5"),
    ("kode_pos", "kode_pos", "15157"),
    ("anak_ke", "anak_keberapa", "2"),
    ("ayah_nama", "nama_ayah", "Bapak Uji"),
    ("ayah_nik", "nik_ayah", "3201234567890002"),
    ("ayah_tahun_lahir", "tahun_lahir_ayah", "1980"),
    # Kolom dropdown: nilai yang tersimpan adalah TEKS PILIHAN Dapodik (mis. «SMA»),
    # bukan teks data SM («SMA / sederajat») — itulah bedanya memilih dari daftar dengan
    # mengetikkan teksnya.
    ("ayah_pendidikan", "jenjang_pendidikan_ayah", "SMA"),
    ("ayah_pekerjaan", "pekerjaan_id_ayah", "Petani"),
    ("ayah_penghasilan", "penghasilan_id_ayah", "Rp. 500,000 - Rp. 999,999"),
    ("ibu_nik", "nik_ibu", "3201234567890003"),
    ("ibu_tahun_lahir", "tahun_lahir_ibu", "1983"),
    ("ibu_pendidikan", "jenjang_pendidikan_ibu", "SMP"),
    ("ibu_pekerjaan", "pekerjaan_id_ibu", "Tidak Bekerja"),
    ("ibu_penghasilan", "penghasilan_id_ibu", "Tidak Berpenghasilan"),
)


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


def jalankan(judul: str, jarak, atur=None, tampilkan: bool = False, opsi: dict | None = None,
             ubah_siswa: dict | None = None):
    """Jalankan bot untuk satu siswa pada keadaan halaman tertentu.

    ``opsi`` menimpa pengaturan bot untuk skenario ini (mis. menyalakan langkah BIO).
    """
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
        bot = bot_dapodik.BotDapodik(0, [], [], dict(OPSI, **(opsi or {})), kepala=jejak.append)
        bot._login(peramban)
        bot._proses_satu(peramban, {**SISWA, "jarak_rumah": jarak, **(ubah_siswa or {})}, None)
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
    if peramban.bio_aktif:
        print(f"    BIO tersimpan: {peramban.bio_tersimpan} · kolom terisi: "
              f"{sum(1 for nilai in peramban.data_bio_tersimpan.values() if nilai != 'LAMA')}"
              f"/{len(peramban.data_bio_tersimpan)} · gulir jendela: {peramban.gulir_bio}x · "
              f"jendela terbuka: {peramban.bio_terbuka} · «Ubah» palsu ditekan: "
              f"{peramban.bio_ubah_palsu_diklik}x · «Simpan» palsu ditekan: "
              f"{peramban.bio_simpan_palsu_diklik}x · kandidat «Ubah» dicoba: "
              f"{peramban.bio_ubah_dicoba}x")
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

    # 5) Keadaan paling halus: klik mengubah DOM (input checked) TETAPI model Ext JS tidak
    #    ikut — penanda x-form-cb-checked tetap di pilihan lama, sehingga kolom kilometer
    #    tetap NONAKTIF. Bot harus menyadarinya dan naik ke Ext.getCmp(...).setValue(...).
    p7, j7 = jalankan("5. DOM berubah tapi model Ext JS tidak → naik ke Ext.getCmp", 2,
                      atur=lambda p: p.siapkan_model_ext_tidak_ikut(), tampilkan=True)
    cek(p7.jarak_pilihan == "Lebih dari 1 km", f"radio salah: {p7.jarak_pilihan!r}")
    cek(p7.ext_setvalue_dipakai >= 1, "bot tidak naik ke Ext.getCmp saat penandanya tidak pindah")
    cek(any("nilai Ext JS belum" in baris for baris in j7), [b for b in j7 if "periodik" in b])
    km7 = next(unsur for unsur in p7.unsur if unsur.name == "jarak_rumah_ke_sekolah_km")
    cek(km7.enabled, "kolom km tetap nonaktif setelah Ext.getCmp menyetel nilainya")
    cek(p7.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "2",
        f"kolom km tidak tersimpan: {p7.data_periodik_tersimpan}")

    # 6) Data jarak ≤ 1 km → pilihan «kurang dari 1 km», km tidak diisi.
    p5, _ = jalankan("6. jarak 0,7 km → «kurang dari 1 km», km tidak diisi", 0.7)
    cek(p5.jarak_pilihan == "Kurang dari 1 km", f"radio salah: {p5.jarak_pilihan!r}")
    cek(not str(p5.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") or "").strip(),
        "kolom km terisi untuk jarak ≤ 1 km")

    # 6) Data jarak kosong → tidak ada pilihan yang ditebak.
    p6, j6 = jalankan("7. jarak kosong → tidak ada pilihan ditebak", "")
    cek(p6.jarak_pilihan == "", f"radio seharusnya kosong: {p6.jarak_pilihan!r}")
    cek(any("Jarak Rumah ke Sekolah) kosong" in baris for baris in j6), j6[-4:])

    # 8) XPath/CSS meleset (tata letak Dapodik berbeda) → pilihannya dilacak lewat TEKS
    #    labelnya, dibaca JavaScript. Inilah jalan keluar dari «kotak … tidak ada di halaman
    #    ini» yang dulu membuat pemilihan jarak gagal di PC sekolah.
    p8, j8 = jalankan("8. XPath meleset → kotak & label dilacak lewat teks (JavaScript)", 2,
                      atur=lambda p: p.siapkan_jarak_tanpa_xpath(), tampilkan=True)
    cek(p8.jarak_pilihan == "Lebih dari 1 km", f"radio salah: {p8.jarak_pilihan!r}")
    cek(p8.kotak_lewat_teks_dipakai >= 1, "bot tidak melacak kotaknya lewat teks labelnya")
    cek(any("lewat teks labelnya" in baris for baris in j8), j8[-6:])
    cek(p8.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "2",
        f"kolom km tidak tersimpan: {p8.data_periodik_tersimpan}")

    # 9) Versi Dapodik tanpa baris «Jarak rumah ke sekolah» → tidak menebak, dilewati jujur,
    #    dan log menyebutkan apa yang terlihat di panel (bukan sekadar gagal diam-diam).
    p9, j9 = jalankan("9. baris jarak tidak ada → dilewati jujur + isi panel dilaporkan", 2,
                      atur=lambda p: p.hapus_baris_jarak(), tampilkan=True)
    cek(p9.jarak_pilihan == "", f"seharusnya tidak ada pilihan: {p9.jarak_pilihan!r}")
    cek(any("tidak ada di halaman ini" in b and "yang terlihat di panel" in b for b in j9),
        [b for b in j9 if "tidak ada di halaman ini" in b] or j9[-4:])
    cek(not str(p9.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") or "").strip(),
        "kolom km terisi padahal baris jaraknya tidak ada")

    # 10) BIO lewat tombol «Ubah»: jendelanya panjang, jadi kolomnya harus DIBawa KE LAYAR
    #     dulu (jendela & halaman) — lalu diisi dari data siswa SM dan disimpan dengan
    #     tombol «Simpan». Urutannya: pilih baris → BIO → Data Periodik → Registrasi.
    p10, j10 = jalankan("10. BIO lewat «Ubah»: kolom dibawa ke layar → diisi → Simpan", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"})
    cek(p10.bio_tersimpan, "tombol «Simpan» jendela «Ubah» tidak ditekan bot")
    for kunci, nama_kolom, nilai in BIO_UJI:
        tersimpan = str(p10.data_bio_tersimpan.get(nama_kolom) or "").strip()
        cek(tersimpan == nilai,
            f"kolom BIO {nama_kolom} salah: {tersimpan!r} (seharusnya {nilai!r})")
    cek(str(p10.data_bio_tersimpan.get("reg_akta_lahir") or "") == "LAMA",
        "kolom akta dikosongkan padahal datanya kosong (seharusnya dibiarkan)")
    cek(p10.bio_siap(), "jendela «Ubah» tidak pernah digulir — kolomnya tidak akan terjangkau")
    cek(any("jendela «Edit Peserta Didik» terbuka" in b for b in j10),
        [b for b in j10 if "[bio]" in b][:4] or j10[:6])
    cek(any("No. Registrasi Akta Lahir: data siswa kosong — dilewati" in b for b in j10),
        [b for b in j10 if "[bio]" in b])
    cek(any("jendela «Ubah» tertutup" in b for b in j10), [b for b in j10 if "[bio]" in b])
    i_bio = next((i for i, b in enumerate(j10)
                  if "jendela «Edit Peserta Didik» terbuka" in b), -1)
    i_periodik = next((i for i, b in enumerate(j10) if "mengisi Data Periodik" in b), -1)
    cek(0 <= i_bio < i_periodik, f"urutan salah: BIO#{i_bio} periodik#{i_periodik}")
    cek(p10.jarak_pilihan == "Lebih dari 1 km" and
        p10.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "2",
        "langkah Data Periodik terganggu oleh langkah BIO")

    # 11) Versi Dapodik tanpa tombol «Ubah» → langkah BIO dilewati dengan jujur, siswa tetap
    #     diproses sampai Registrasi berhasil.
    p11, j11 = jalankan("11. tombol «Ubah» tidak ada → BIO dilewati jujur", 2,
                        atur=lambda p: p.siapkan_bio(ada_tombol=False), tampilkan=True,
                        opsi={"bot_isi_bio": "1"})
    cek(not p11.bio_tersimpan, "jendela BIO terbuat padahal tombol «Ubah» tidak ada")
    cek(any("tombol «Ubah» tidak ada" in b and "dilewati" in b for b in j11),
        [b for b in j11 if "[bio]" in b] or j11[-5:])
    hasil11 = [b for b in j11 if b.startswith(("[OK]", "[GAGAL]"))]
    cek(bool(hasil11) and hasil11[-1].startswith("[OK]"), hasil11[-2:] or j11[-3:])

    # 12) Halaman sekolah: di bawah jendela ada panel «Data Rincian PD» dengan tombol
    #     «Ubah» (ungu) & «Simpan» SENDIRI — dan jendela «Ubah» punya area gulirnya sendiri
    #     (menggulir halaman tidak menolong; lihat tangkapan layar sekolah). Bot harus:
    #     membuka jendela «Edit Peserta Didik» yang benar, menggulir ISI jendelanya, dan
    #     menyimpan lewat tombol «Simpan» yang ada DI DALAM jendela itu.
    p12, j12 = jalankan("12. dua set tombol «Ubah»/«Simpan» + gulir di dalam jendela", 2,
                        atur=lambda p: p.siapkan_bio(panel_rincian=True), tampilkan=True,
                        opsi={"bot_isi_bio": "1"})
    cek(p12.bio_tersimpan, "jendela «Ubah» tidak tersimpan (tombol «Simpan» yang benar tidak ketemu)")
    cek(p12.bio_ubah_palsu_diklik == 0,
        f"bot menekan «Ubah» milik panel «Data Rincian PD» ({p12.bio_ubah_palsu_diklik}x)")
    cek(p12.bio_simpan_palsu_diklik == 0,
        f"bot menekan «Simpan» milik panel «Data Rincian PD» ({p12.bio_simpan_palsu_diklik}x) — "
        "itulah yang membuat jendela «Ubah» tetap terbuka")
    cek(not p12.bio_terbuka, "jendela «Ubah» masih terbuka setelah disimpan")
    cek(p12.gulir_bio >= 1, "bot tidak menggulir ISI jendela «Ubah» sama sekali")
    cek(p12.data_bio_tersimpan.get("jenjang_pendidikan_ibu") == "SMP",
        f"kolom paling bawah tidak terisi: {p12.data_bio_tersimpan.get('jenjang_pendidikan_ibu')!r}")
    cek(any("jendela «Edit Peserta Didik» terbuka" in b for b in j12), [b for b in j12 if "[bio]" in b][:4])
    cek(any("digeser 250 px bertahap" in b for b in j12),
        [b for b in j12 if "[bio]" in b][:8])

    # 13) «Ubah» palsu di luar panel «Data Rincian» (petunjuk tampilan tidak menolong): bot
    #     harus mencobanya, melihat jendelanya tidak terbuka, lalu mencoba kandidat berikutnya.
    p13, j13 = jalankan("13. «Ubah» pertama tidak membuka jendela → dicoba kandidat berikutnya", 2,
                        atur=lambda p: p.siapkan_bio(ubah_palsu_di_luar=True), tampilkan=True,
                        opsi={"bot_isi_bio": "1"})
    cek(p13.bio_tersimpan, "jendela «Ubah» tidak tersimpan setelah kandidat kedua dicoba")
    cek(p13.bio_ubah_palsu_diklik >= 1, "kandidat «Ubah» palsu tidak pernah dicoba (uji tidak bermakna)")
    cek(p13.bio_ubah_dicoba >= 2, f"bot tidak mencoba kandidat «Ubah» berikutnya: {p13.bio_ubah_dicoba}")
    cek(any("tidak membuka jendela" in b for b in j13),
        [b for b in j13 if "[bio]" in b][:6] or j13[-4:])
    cek(not p13.bio_terbuka, "jendela «Ubah» masih terbuka setelah disimpan")

    # 14) Posisi gulir jendela menentukan: kolom yang berada di luar bagian jendela yang
    #     terlihat TIDAK bisa dicari/ditulis (persis dugaan sekolah: «scroll kebanyakan atau
    #     kurang banyak»). Bot harus menggulir bertahap — 250 px sekali geser — sambil mencari
    #     ulang, sampai semua kolom terisi; bukan mengandalkan satu lompatan gulir.
    p14, j14 = jalankan("14. posisi gulir jendela menentukan → digulir bertahap sampai terisi", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"})
    cek(p14.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji posisi gulir")
    cek(p14.gulir_bio >= 4,
        f"bot tidak menggulir isi jendela bertahap: {p14.gulir_bio} kali geser")
    salah = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
             if str(p14.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah, f"kolom yang tidak terisi pada uji posisi gulir: {salah}")
    cek(any("dikembalikan ke atas" in b for b in j14), [b for b in j14 if "[bio]" in b][:4])

    # 15) Versi Dapodik yang menolak SEMUA ketikan pada kolom BIO (hanya model Ext JS yang
    #     diterima): bot harus mundur ke Ext.getCmp(...).setValue(...) dan memastikan nilainya
    #     benar-benar ada — bukan mengaku selesai padahal kolomnya masih berisi data lama.
    p15, j15 = jalankan("15. ketikan ditolak → nilai dicoba lewat Ext JS (Ext.getCmp)", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "bio_hanya_ext", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p15.bio_tersimpan, "jendela «Ubah» tidak tersimpan saat ketikan ditolak Dapodik")
    cek(p15.ketikan_diabaikan >= 1,
        "uji tidak bermakna: Dapodik tiruan tidak pernah menolak ketikan")
    cek(p15.ext_setvalue_dipakai >= 1,
        "bot tidak memakai Ext.getCmp saat ketikan ke kolom BIO ditolak Dapodik")
    salah15 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p15.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah15, f"kolom yang tidak terisi lewat Ext JS: {salah15}")
    cek(any("Ext JS" in b for b in j15), [b for b in j15 if "[bio]" in b][:8])

    # 16) Wadah jendela «Ubah» TIDAK terbaca bot (mis. formulirnya berupa panel dengan judul
    #     yang tak dikenali). Skrip sekolah mengisi kolomnya lewat `find_element(By.NAME, …)`
    #     tanpa mempedulikan jendelanya — jadi bot harus punya jalan itu juga, sambil
    #     menggulir halaman bila kolomnya belum tampil. Ini jalan keluar terakhir bila
    #     pengenalan jendela meleset di Dapodik sekolah.
    p16, j16 = jalankan("16. wadah jendela tak terbaca → kolom dicari lewat namanya (ala skrip)", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "bio_tanpa_wadah", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p16.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada jalur cadangan global")
    salah16 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p16.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah16, f"kolom yang tidak terisi pada jalur cadangan global: {salah16}")
    cek(any("dilacak lewat namanya seperti skrip sekolah" in b for b in j16),
        [b for b in j16 if "[bio]" in b][:5])
    cek(any("lewat namanya di halaman (cara skrip sekolah)" in b for b in j16),
        [b for b in j16 if "cara skrip sekolah" in b][:3])
    cek(any(b.startswith("[bio-rincian]") for b in j16), [b for b in j16 if "[bio]" in b][:3])

    # 17) Kolom dropdown (combo Ext JS): «Pendidikan/Pekerjaan/Penghasilan ayah-ibu» pada
    #     tangkapan layar sekolah. Inilah yang tidak tertangani sebelumnya: teksnya diketik,
    #     tulisannya tampak benar di layar, tetapi NILAI MODEL Ext JS tetap kosong — dan
    #     Dapodik hanya menyimpan yang benar-benar dipilih dari daftarnya. Uji ini menuntut
    #     bot memilih dari daftar, dan nilai yang tersimpan adalah teks pilihan Dapodik.
    p17, j17 = jalankan("17. kolom dropdown → pilihan diambil dari daftarnya", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"})
    cek(p17.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji dropdown")
    cek(p17.dropdown_item_diklik >= 6,
        f"bot tidak memilih dari daftar dropdown: {p17.dropdown_item_diklik} pilihan "
        f"(seharusnya 6 kolom: pendidikan, pekerjaan, penghasilan ayah & ibu)")
    salah17 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p17.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah17, f"kolom yang tidak terisi pada uji dropdown: {salah17}")
    cek(str(p17.data_bio_tersimpan.get("jenjang_pendidikan_ayah") or "") == "SMA",
        "kolom pendidikan ayah tidak berisi TEKS PILIHAN Dapodik («SMA»), "
        f"melainkan {p17.data_bio_tersimpan.get('jenjang_pendidikan_ayah')!r}")
    cek(any("dropdown dibuka lewat" in b for b in j17), [b for b in j17 if "[bio]" in b][:8])
    cek(any("dibaca sebagai «SMA»" in b for b in j17),
        [b for b in j17 if "Pendidikan ayah" in b][:4])

    # 18) Pilihan yang TIDAK ADA di daftar Dapodik: bot tidak boleh menebak (mis. memilih
    #     «Lainnya» sendiri). Yang benar: mencatat pilihan yang terlihat pada daftarnya,
    #     melewati kolom itu, dan tetap menyelesaikan siswa.
    p18, j18 = jalankan("18. pilihan di luar daftar → dilaporkan, tidak ditebak", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"ayah_pendidikan": "Sarjana Luar Negeri",
                                    "ibu_pekerjaan": "Astronaut"})
    cek(p18.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji pilihan di luar daftar")
    cek(not str(p18.data_bio_tersimpan.get("jenjang_pendidikan_ayah") or "").strip(),
        "kolom pendidikan ayah terisi padahal pilihannya tidak ada di daftar dropdown")
    cek(not str(p18.data_bio_tersimpan.get("pekerjaan_ibu") or "").strip(),
        "kolom pekerjaan ibu terisi padahal pilihannya tidak ada di daftar dropdown")
    cek(any("TIDAK ADA di daftar dropdown Dapodik" in b for b in j18),
        [b for b in j18 if "[bio]" in b][:8])
    cek(any("yang terlihat:" in b for b in j18), [b for b in j18 if "[bio]" in b][:8])
    cek(str(p18.data_bio_tersimpan.get("nama_ayah") or "").strip() == "Bapak Uji",
        "kolom lain ikut gagal padahal hanya dua kolom yang di luar daftar")

    # 19) Klik pada pilihan dropdown TIDAK berpengaruh (ditelan lapisan Dapodik — persis yang
    #     terjadi di PC sekolah: daftarnya terlihat, pilihannya diklik, tetapi nilainya tidak
    #     tersimpan). Bot harus memilih lewat MODEL Ext JS (select/setValue) dan memastikan
    #     nilainya benar-benar masuk.
    p19, j19 = jalankan("19. klik pilihan ditelan → dipilih lewat model Ext JS", 2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "dropdown_item_ditelan", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p19.bio_tersimpan, "jendela «Ubah» tidak tersimpan saat klik pilihan ditelan")
    cek(p19.dropdown_item_ditelan_kali >= 1,
        "uji tidak bermakna: tidak ada klik pilihan yang ditelan")
    cek(p19.dropdown_ext_pilih >= 6,
        f"bot tidak memilih lewat model Ext JS: {p19.dropdown_ext_pilih} pilihan "
        "(seharusnya 6 kolom dropdown)")
    salah19 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p19.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah19, f"kolom yang tidak terisi lewat model Ext JS: {salah19}")
    cek(any("dipilih lewat model Ext JS" in b for b in j19), [b for b in j19 if "[bio]" in b][:8])

    # 20) Daftar dropdown TIDAK MAU TERBUKA sama sekali (tombol panah, kolomnya, dan
    #     Ext.expand() semuanya gagal). Bot harus tetap bisa mengisi kolomnya dari DATA
    #     komponen Ext JS (store) — bukan menyerah karena daftarnya tidak terlihat.
    p20, j20 = jalankan("20. daftar tak mau terbuka → pilihan dibaca dari data komponen", 2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "dropdown_tak_bisa_dibuka", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p20.bio_tersimpan, "jendela «Ubah» tidak tersimpan saat daftar dropdown tak terbuka")
    cek(p20.dropdown_dibuka == 0,
        f"uji tidak bermakna: daftar dropdown sempat terbuka {p20.dropdown_dibuka}x")
    cek(p20.dropdown_ext_pilih >= 6,
        f"bot tidak memilih lewat data komponen/model Ext JS: {p20.dropdown_ext_pilih} "
        "pilihan (seharusnya 6 kolom dropdown)")
    salah20 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p20.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah20, f"kolom yang tidak terisi pada jalur data komponen: {salah20}")
    cek(any("data komponen Ext JS" in b for b in j20), [b for b in j20 if "[bio]" in b][:8])

    # 21) Daftar dropdown sekolah: **datanya muncul setelah ditunggu** dan **daftarnya
    #     panjang** (hanya sebagian pilihan terlihat sekaligus) — persis yang dikatakan
    #     sekolah: "untuk datanya muncul harus nunggu sebentar, dan di dropdown itu juga bisa
    #     discroll kalo datanya ga ada". Bot harus: klik dropdownnya → tunggu pilihannya
    #     muncul → gulir isi daftarnya sampai pilihan yang dicari terlihat → klik.
    p21, j21 = jalankan("21. daftar dropdown lambat muncul + harus digulir", 2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "dropdown_muat_perlu", 2),
                                        setattr(p, "dropdown_band", 5)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p21.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji daftar yang lambat")
    cek(p21.dropdown_dibuka >= 6,
        f"bot tidak membuka daftar dropdownnya: {p21.dropdown_dibuka}x")
    cek(p21.dropdown_gulir_kali >= 1,
        "bot tidak menggulir isi daftar dropdown (pilihan di bawah tidak akan terjangkau)")
    cek(p21.dropdown_item_tak_terlihat == 0,
        f"bot mencoba mengklik pilihan yang belum terlihat: {p21.dropdown_item_tak_terlihat}x")
    cek(p21.dropdown_item_diklik >= 6,
        f"bot tidak memilih dari daftar: {p21.dropdown_item_diklik} pilihan diklik "
        "(seharusnya 6 kolom dropdown)")
    salah21 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p21.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah21, f"kolom yang tidak terisi pada uji daftar lambat: {salah21}")
    cek(any("menunggu" in b and "pilihan tampil" in b for b in j21),
        [b for b in j21 if "dropdown" in b][:6])
    cek(any("digeser" in b and "sampai ketemu" in b for b in j21),
        [b for b in j21 if "belum tampil" in b][:4] or j21[-6:])

    # 22) Keadaan terberat: daftar panjang + lambat + klik pilihannya ditelan Dapodik.
    #     Bot menggulir, mencoba mengklik, lalu memilih lewat MODEL Ext JS (select/setValue)
    #     dan tetap berhasil — tanpa pernah mengklik pilihan yang belum terlihat.
    p22, j22 = jalankan("22. daftar lambat + klik ditelan → digulir lalu dipilih lewat model", 2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "dropdown_muat_perlu", 2),
                                        setattr(p, "dropdown_band", 4),
                                        setattr(p, "dropdown_item_ditelan", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p22.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji daftar lambat + klik ditelan")
    cek(p22.dropdown_gulir_kali >= 1,
        "bot tidak menggulir isi daftar dropdown pada uji daftar lambat + klik ditelan")
    cek(p22.dropdown_item_ditelan_kali >= 1,
        "uji tidak bermakna: tidak ada klik pilihan yang ditelan")
    cek(p22.dropdown_item_tak_terlihat == 0,
        f"bot mencoba mengklik pilihan yang belum terlihat: {p22.dropdown_item_tak_terlihat}x")
    cek(p22.dropdown_ext_pilih >= 6,
        f"bot tidak memilih lewat model Ext JS: {p22.dropdown_ext_pilih} pilihan")
    salah22 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p22.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah22, f"kolom yang tidak terisi pada uji terberat: {salah22}")
    cek(any("dipilih lewat model Ext JS" in b for b in j22), [b for b in j22 if "[bio]" in b][:8])

    # 23) Keadaan paling berat di sekolah: ``Ext`` TIDAK BISA DIPANGGIL dari skrip (semua
    #     jalur Ext.getCmp/store/select mati) DAN tombol panah combonya tidak ada — jadi
    #     satu-satunya jalan adalah menekan tombol ↓ pada kolomnya lalu membaca daftarnya
    #     LANGSUNG DARI DOM (``aria-owns="…-picker-listEl"``, persis DOM yang dikirim
    #     sekolah), menggulirnya sampai bawah, lalu mengklik pilihannya. Daftarnya juga
    #     panjang (hanya sebagian terlihat) dan lambat muncul.
    p23, j23 = jalankan("23. tanpa Ext & tanpa tombol panah → tombol ↓ + daftar dibaca dari DOM",
                        2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "dropdown_tanpa_ext", True),
                                        setattr(p, "dropdown_tanpa_panah", True),
                                        setattr(p, "dropdown_muat_perlu", 2),
                                        setattr(p, "dropdown_band", 5)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p23.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji tanpa Ext")
    cek(p23.dropdown_aria_dipakai >= 6,
        f"bot tidak membaca daftar dropdown dari DOM/aria-owns: {p23.dropdown_aria_dipakai}x")
    cek(any("tombol ↓" in b for b in j23),
        [b for b in j23 if "[bio]" in b][:10] or j23[-6:])
    cek(p23.dropdown_dibuka >= 6,
        f"bot tidak membuka daftar dropdownnya tanpa tombol panah: {p23.dropdown_dibuka}x")
    cek(p23.dropdown_gulir_kali >= 1,
        "bot tidak menggulir isi daftar dropdown pada uji tanpa Ext")
    cek(p23.dropdown_item_tak_terlihat == 0,
        f"bot mencoba mengklik pilihan yang belum terlihat: {p23.dropdown_item_tak_terlihat}x")
    cek(p23.dropdown_item_diklik >= 6,
        f"bot tidak memilih dari daftar: {p23.dropdown_item_diklik} pilihan diklik "
        "(seharusnya 6 kolom dropdown)")
    salah23 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p23.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah23, f"kolom yang tidak terisi pada uji tanpa Ext: {salah23}")
    cek(str(p23.data_bio_tersimpan.get("jenjang_pendidikan_ayah") or "") == "SMA",
        "pilihan yang SAMA PERSIS («SMA») tidak didahulukan atas nama lain («SLTA»): "
        f"{p23.data_bio_tersimpan.get('jenjang_pendidikan_ayah')!r}")
    cek(any("disusuri" in b for b in j23),
        [b for b in j23 if "Pendidikan ayah" in b][:4] or j23[-6:])

    print(f"\n[SELESAI] {pemeriksaan} pemeriksaan lolos pada 23 skenario")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
