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
from scripts import peramban_palsu
from scripts.peramban_palsu import DESA_LAMA_BIO as DESA_LAMA_PALSU  # noqa: E402
from scripts.peramban_palsu import DESA_LAMA_ID  # noqa: E402
from scripts.peramban_palsu import kode_desa_palsu  # noqa: E402


#: Kalimat log yang wajib muncul — gulir tidak boleh mengubah nilai kolom isian (ronde 45).
JEJAK_KURSOR = "kursor dikeluarkan dari kolom"
JEJAK_KODE_WILAYAH = "kode wilayah (kode_wilayah_str)"

#: Desa yang dipilih pada uji kode wilayah (desa pertama Kec. Karawaci versi peramban palsu).
DESA_PILIH_PALSU = "Desa/Kel. Karawaci Baru - Kec. Karawaci - Kota Tangerang"

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
    # Combo «Desa/Kelurahan» (ronde 43): satu kolom memuat desa + kecamatan + kota, dan
    # daftarnya diambil Dapodik dari basis datanya setelah nama kecamatan diketik.
    "kelurahan": "Karawaci Baru", "kecamatan": "Karawaci",
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
    # Nilai yang tersimpan adalah TEKS PILIHAN Dapodik lengkap (desa + kecamatan + kota),
    # bukan nama desa dari data SM — itu bedanya memilih dari daftar dengan mengetiknya.
    ("kelurahan", "kelurahan", "Desa/Kel. Karawaci Baru - Kec. Karawaci - Kota Tangerang"),
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


#: Bot yang terakhir dijalankan — dipakai uji untuk memeriksa catatan bot itu sendiri
#: (mis. berapa kali ia memasang ulang pilihan desa sebelum «Simpan»).
BOT_TERAKHIR = None


def jalankan(judul: str, jarak, atur=None, tampilkan: bool = False, opsi: dict | None = None,
             ubah_siswa: dict | None = None, bio_wali: bool = False):
    """Jalankan bot untuk satu siswa pada keadaan halaman tertentu.

    ``opsi`` menimpa pengaturan bot untuk skenario ini (mis. menyalakan langkah BIO).
    """
    global BOT_TERAKHIR
    jejak: list[str] = []
    jam = _WaktuCepat(time)
    asli = bot_dapodik.time
    bot_dapodik.time = jam
    try:
        peramban = peramban_palsu.buat("alur_penuh").pakai_jam(jam.monotonic)
        if bio_wali:
            # Jendela «Ubah» memuat bagian «Data Wali» (galat sekolah 29 September 2026).
            peramban.bio_wali_kolom = True
        peramban.popup_detik = None
        peramban.registrasi_otomatis = True
        if atur:
            atur(peramban)
        peramban.nisn_dicari = SISWA["nisn"]
        peramban.tambah_baris_siswa(SISWA["nisn"])
        bot = bot_dapodik.BotDapodik(0, [], [], dict(OPSI, **(opsi or {})), kepala=jejak.append)
        BOT_TERAKHIR = bot
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

    # 24) Combo «Desa/Kelurahan» — mekanisme Dapodik terbaru seperti dikirim sekolah:
    #     pengguna mengetik nama KECAMATAN lebih dulu, lalu Dapodik menampilkan daftar
    #     desa/kelurahan di bawah kecamatan itu. Daftarnya punya area gulir & BILAH HALAMAN
    #     («Page 1 of 2»): desa yang dicari berada di halaman kedua, jadi halamannya harus
    #     benar-benar dibuka — bukan disimpulkan "tidak ada" dari halaman pertama.
    p24, j24 = jalankan("24. desa/kelurahan: ketik kecamatan → daftar digulir & halaman dibuka",
                        2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "dropdown_band", 5),
                                        setattr(p, "desa_muat_perlu_default", 4)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p24.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji desa/kelurahan")
    cek(p24.data_bio_tersimpan.get("kelurahan")
        == "Desa/Kel. Karawaci Baru - Kec. Karawaci - Kota Tangerang",
        f"desa/kelurahan salah tersimpan: {p24.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p24.desa_kueri_dipakai and p24.desa_kueri_dipakai[0] == "Karawaci",
        f"kata kunci pertama bukan nama kecamatan: {p24.desa_kueri_dipakai}")
    cek(p24.dropdown_halaman_kali >= 1,
        "bot tidak membuka halaman kedua daftar desa — desanya tidak akan ketemu")
    cek(p24.dropdown_gulir_kali >= 1, "isi daftar desa tidak pernah digulir")
    cek(p24.dropdown_item_diklik >= 7,
        f"pilihan desa tidak diklik dari daftarnya: {p24.dropdown_item_diklik} klik")
    cek(any("mengetik «Karawaci»" in b for b in j24),
        [b for b in j24 if "Desa/Kelurahan" in b][:6] or j24[-6:])
    cek(any("membuka halaman berikutnya" in b for b in j24),
        [b for b in j24 if "Desa/Kelurahan" in b][:8] or j24[-8:])
    cek(any("dipilih dari daftar Dapodik" in b for b in j24),
        [b for b in j24 if "Desa/Kelurahan" in b][:8] or j24[-8:])
    cek(any("ditunggu" in b and "baca" in b for b in j24),
        [b for b in j24 if "Desa/Kelurahan" in b][:6] or j24[-6:])

    # 25) Klik pada pilihan desa ditelan Dapodik (daftarnya terlihat, pilihannya diklik,
    #     tetapi nilainya tidak tersimpan) → bot memilih lewat MODEL Ext JS dan memastikan
    #     nilainya benar-benar masuk.
    p25, j25 = jalankan("25. desa: klik pilihan ditelan → dipilih lewat model Ext JS", 2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "dropdown_item_ditelan", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"kelurahan": "Nusajaya", "kecamatan": "Karawaci"})
    cek(p25.bio_tersimpan, "jendela «Ubah» tidak tersimpan saat klik pilihan desa ditelan")
    cek(p25.data_bio_tersimpan.get("kelurahan")
        == "Desa/Kel. Nusajaya - Kec. Karawaci - Kota Tangerang",
        f"desa/kelurahan salah tersimpan: {p25.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p25.dropdown_item_ditelan_kali >= 1, "uji tidak bermakna: tidak ada klik yang ditelan")
    cek(any("dipilih lewat model Ext JS" in b for b in j25),
        [b for b in j25 if "Desa/Kelurahan" in b][:8] or j25[-8:])

    # 26) Desa yang diminta TIDAK ADA pada daftar Dapodik: bot tidak menebak, tidak mengisi
    #     kolomnya dengan ketikan, dan nilai lama di Dapodik TIDAK ditimpa.
    p26, j26 = jalankan("26. desa tidak ada di daftar → dilewati jujur (tidak menebak)", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"kelurahan": "Desa Karangan", "kecamatan": "Karawaci"})
    cek(p26.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji desa tidak ada")
    cek(p26.data_bio_tersimpan.get("kelurahan") == DESA_LAMA_PALSU,
        "isi kolom desa berubah padahal pilihannya tidak ada di daftar Dapodik "
        f"({p26.data_bio_tersimpan.get('kelurahan')!r}) — data lama Dapodik jangan ikut "
        "tertimpa kata kunci pencarian")
    cek(any("dikembalikan seperti semula" in b for b in j26),
        [b for b in j26 if "Desa/Kelurahan" in b][:8] or j26[-8:])
    cek(len(p26.desa_kueri_dipakai) >= 2,
        f"kueri kedua (nama desa) tidak pernah dicoba: {p26.desa_kueri_dipakai}")
    cek(any("TIDAK ADA pada daftar Dapodik" in b for b in j26),
        [b for b in j26 if "Desa/Kelurahan" in b][:8] or j26[-8:])
    cek(str(p26.data_bio_tersimpan.get("nama_ayah") or "").strip() == "Bapak Uji",
        "kolom lain ikut gagal padahal hanya desa yang tidak ada di daftar")

    # 27) Kecamatan di SM keliru/tidak sama dengan Dapodik: kueri pertama (kecamatan) tidak
    #     menemukan desanya, lalu bot mencoba kueri kedua (nama desa) — dan tetap memeriksa
    #     hasilnya, dengan catatan bila kecamatan pada pilihan Dapodik berbeda dari data SM.
    p27, j27 = jalankan("27. desa: kecamatan SM keliru → kueri nama desa dipakai", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"kelurahan": "Cimone Jaya", "kecamatan": "Cibodas"})
    cek(p27.data_bio_tersimpan.get("kelurahan")
        == "Desa/Kel. Cimone Jaya - Kec. Karawaci - Kota Tangerang",
        f"desa/kelurahan salah tersimpan: {p27.data_bio_tersimpan.get('kelurahan')!r}")
    cek(any("berbeda dari data SM" in b for b in j27),
        [b for b in j27 if "Desa/Kelurahan" in b][:8] or j27[-8:])
    cek(p27.desa_kueri_dipakai[:2] == ["Cibodas", "Cimone Jaya"],
        f"urutan kueri salah: {p27.desa_kueri_dipakai}")
    cek(any("kecamatan pada pilihan Dapodik" in b for b in j27),
        [b for b in j27 if "Desa/Kelurahan" in b][:8] or j27[-8:])

    # 28) Kecamatan kosong di SM: bot mengetik nama desanya langsung (tetap menunggu daftar
    #     dari Dapodik dan tetap memeriksa hasilnya) — bukan menyerah tanpa mencoba.
    p28, j28 = jalankan("28. desa: kecamatan kosong di SM → kueri nama desa", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"kelurahan": "Koangjaya", "kecamatan": ""})
    cek(p28.data_bio_tersimpan.get("kelurahan")
        == "Desa/Kel. Koangjaya - Kec. Karawaci - Kota Tangerang",
        f"desa/kelurahan salah tersimpan: {p28.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p28.desa_kueri_dipakai and p28.desa_kueri_dipakai[0] == "Koangjaya",
        f"kata kunci bukan nama desa: {p28.desa_kueri_dipakai}")
    cek(any("kecamatan kosong di SM" in b for b in j28),
        [b for b in j28 if "Desa/Kelurahan" in b][:4] or j28[-6:])

    # 29) Nama desa yang sama di dua kecamatan: kecamatan dari SM menentukan pilihannya —
    #     dan bila kecamatannya tidak ada (ambigu), bot TIDAK menebak.
    p29, j29 = jalankan("29. desa: nama desa sama di dua kecamatan → kecamatan menentukan", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"kelurahan": "Sukajadi", "kecamatan": "Cibodas"})
    cek(p29.data_bio_tersimpan.get("kelurahan")
        == "Desa/Kel. Sukajadi - Kec. Cibodas - Kota Tangerang",
        f"desa/kelurahan salah tersimpan: {p29.data_bio_tersimpan.get('kelurahan')!r}")
    bot_uji = bot_dapodik.BotDapodik(0, [], [], dict(OPSI), kepala=lambda _b: None)
    pilihan_dua = ["Desa/Kel. Sukajadi - Kec. Karawaci - Kota Tangerang",
                   "Desa/Kel. Sukajadi - Kec. Cibodas - Kota Tangerang"]
    cocok29, catatan29 = bot_uji._cocokkan_desa("Sukajadi", "Cibodas", pilihan_dua)
    cek(cocok29.endswith("Kec. Cibodas - Kota Tangerang"),
        f"kecamatan tidak dipakai untuk memilih: {cocok29!r}")
    cek("kecamatan" in catatan29, f"catatan pencocokan tidak menyebut kecamatan: {catatan29!r}")
    cek(bot_uji._cocokkan_desa("Sukajadi", "", pilihan_dua) == ("", ""),
        "nama desa yang sama di dua kecamatan TANPA kecamatan pembanding seharusnya "
        "TIDAK ditebak")
    cek(bot_uji._cocokkan_desa("Desa Karangan", "Karawaci", pilihan_dua) == ("", ""),
        "desa yang tidak ada di daftar seharusnya tidak dicocokkan dengan apa pun")

    # 30) Ejaan desa beda pemisahan kata (kejadian nyata di sekolah): di SM tertulis
    #     «Karang Sari», di basis data Dapodik tertulis «Karangsari». Bot harus mengenali
    #     keduanya (kecamatan tetap penentu) dan melaporkannya apa adanya.
    p30, j30 = jalankan("30. desa «Karang Sari» ↔ Dapodik «Karangsari» (ejaan spasi)", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"kelurahan": "Karang Sari", "kecamatan": "Cibodas"})
    cek(p30.data_bio_tersimpan.get("kelurahan")
        == "Desa/Kel. Karangsari - Kec. Cibodas - Kota Tangerang",
        f"desa/kelurahan salah tersimpan: {p30.data_bio_tersimpan.get('kelurahan')!r}")
    cek(any("ejaan berbeda (spasi)" in b for b in j30),
        [b for b in j30 if "Desa/Kelurahan" in b][:8] or j30[-8:])

    # 31) Kecamatan kosong di SM + ejaan beda spasi: kueri pertama (ejaan SM) tidak ketemu,
    #     lalu bot mencoba bentuk rapat (tanpa spasi) dan tetap memilih dari daftar Dapodik —
    #     bukan menyerah atau mengisi kolomnya dengan ketikan.
    p31, j31 = jalankan("31. desa «Karang Sari» tanpa kecamatan → kueri bentuk rapat", 2,
                        atur=lambda p: p.siapkan_bio(), tampilkan=True,
                        opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"kelurahan": "Karang Sari", "kecamatan": ""})
    cek(p31.data_bio_tersimpan.get("kelurahan")
        == "Desa/Kel. Karangsari - Kec. Cibodas - Kota Tangerang",
        f"desa/kelurahan salah tersimpan: {p31.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p31.desa_kueri_dipakai == ["Karang Sari", "karangsari"],
        f"urutan kueri salah: {p31.desa_kueri_dipakai}")
    cek(any("ditulis rapat (tanpa spasi)" in b for b in j31),
        [b for b in j31 if "Desa/Kelurahan" in b][:8] or j31[-8:])
    cek(any("dipilih dari daftar Dapodik" in b for b in j31),
        [b for b in j31 if "Desa/Kelurahan" in b][:8] or j31[-8:])

    # 32) Gulir tidak boleh mengubah nilai kolom isian: bot mengeluarkan kursor dari kolom
    #     lebih dulu. Peramban palsu kini meniru sifat Dapodik/Chrome yang dilaporkan sekolah:
    #     menggulir selagi kursor ada di dalam kolom angka mengubah nilainya menjadi «0».
    p32, j32 = jalankan("32. gulir: kursor keluar dari kolom isian → nilai tidak rusak", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "dropdown_band", 5)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p32.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji gulir aman")
    cek(p32.rusak_karena_gulir == [],
        f"nilai kolom rusak karena digulir selagi kursor di dalamnya: "
        f"{p32.rusak_karena_gulir}")
    cek(p32.gulir_kursor_di_kolom == 0,
        f"ada {p32.gulir_kursor_di_kolom}x gulir yang masih memegang kursor di dalam kolom")
    cek(p32.kursor_dipindah >= 1,
        "bot tidak pernah memindahkan kursor sebelum menggulir (log «kursor dikeluarkan…» "
        "tidak ada)")
    salah32 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p32.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah32, f"kolom yang nilainya tidak benar sesudah menggulir: {salah32}")
    cek(any(JEJAK_KURSOR in b for b in j32), [b for b in j32 if "kursor" in b][:4] or j32[-6:])
    cek(p32.picker_ditutup_oleh_blur == 0,
        f"daftar pilihan desa sampai menutup karena fokus dilepas: "
        f"{p32.picker_ditutup_oleh_blur}x")

    # 33) Laporan sekolah «masih gagal untuk masalah kode_wilayah_str»: teks desanya berubah,
    #     tetapi kode wilayah (kolom tersembunyi ``kode_wilayah_str``) masih menunjuk desa LAMA
    #     — kalau dibiarkan, «Simpan» tetap menyimpan desa yang lama. Bot harus mengenali itu
    #     dan memindahkan kodenya (lewat model Ext JS), bukan menganggapnya selesai.
    p33, j33 = jalankan("33. kode wilayah basi (kode_wilayah_str) → desa benar-benar pindah", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "desa_kode_basi", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p33.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji kode wilayah basi")
    cek(p33.data_bio_tersimpan.get("kelurahan") == DESA_PILIH_PALSU,
        f"desa tidak berpindah (kode wilayah basi tidak ditangani): "
        f"{p33.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p33.bio_kode_ditolak == 0,
        "Dapodik masih menolak/ mengembalikan desanya saat «Simpan» — kode wilayahnya belum "
        "ikut pindah")
    cek(p33.kode_wilayah() == kode_desa_palsu(DESA_PILIH_PALSU),
        f"kode_wilayah_str masih menunjuk desa lain (basi): {p33.kode_wilayah()!r} "
        f"(seharusnya {kode_desa_palsu(DESA_PILIH_PALSU)!r})")
    cek(any("dipilih lewat model Ext JS" in b or "lewat model Ext JS" in b for b in j33),
        "bot tidak memakai jalur model Ext JS untuk memindahkan kode wilayahnya: "
        f"{[b for b in j33 if 'kode wilayah' in b][:4]}")
    cek(any("kode wilayah" in b and "→" in b for b in j33),
        f"perubahan kode wilayah tidak dicatat apa adanya: "
        f"{[b for b in j33 if 'kode wilayah' in b][:4]}")
    cek(any(JEJAK_KODE_WILAYAH in b for b in j33), [b for b in j33 if "kode wilayah" in b][:4]
        or j33[-6:])
    cek(p33.gulir_kursor_di_kolom == 0,
        f"ada {p33.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom (kode wilayah)")

    # 34) Kode wilayah basi DAN jalur Ext JS tidak tersedia: bot tidak boleh mengklaim
    #     berhasil — kolomnya dikembalikan seperti semula supaya data lama Dapodik tidak
    #     berubah, dan alasannya dilaporkan apa adanya.
    p34, j34 = jalankan("34. kode wilayah basi & Ext mati → dilaporkan jujur, kolom dipulihkan",
                        2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "desa_kode_basi", True),
                                        setattr(p, "dropdown_tanpa_ext", True),
                                        setattr(p, "dropdown_ext_mati", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p34.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji kode wilayah + Ext mati")
    cek(p34.data_bio_tersimpan.get("kelurahan") == DESA_LAMA_PALSU,
        "isi kolom desa berubah padahal kode wilayahnya tidak ikut pindah — data lama "
        f"Dapodik jangan ikut berubah ({p34.data_bio_tersimpan.get('kelurahan')!r})")
    cek(any(JEJAK_KODE_WILAYAH in b for b in j34), [b for b in j34 if "kode wilayah" in b][:4]
        or j34[-6:])
    cek(any("dikembalikan seperti semula" in b for b in j34),
        [b for b in j34 if "Desa/Kelurahan" in b][:8] or j34[-8:])
    cek(any("TIDAK jadi terisi" in b for b in j34),
        [b for b in j34 if "Desa/Kelurahan" in b][:8] or j34[-8:])
    cek(p34.bio_kode_ditolak >= 1,
        "uji tidak bermakna: Dapodik palsu tidak pernah menolak desa berkode basi")
    cek(p34.kode_wilayah() == str(DESA_LAMA_ID),
        f"kode wilayah desa lama ikut berubah padahal pemilihannya gagal: "
        f"{p34.kode_wilayah()!r} (seharusnya {DESA_LAMA_ID!r})")

    # 35) Penjaga nilai: gulir yang tidak bisa dicegah bot (mis. pengguna menggulir sendiri
    #     selagi menonton) mengubah «RT» menjadi «0». Bot memeriksa nilai kolom yang sudah
    #     ditulis sesudah setiap gulir, mengembalikannya, dan melaporkannya apa adanya.
    p35, j35 = jalankan("35. penjaga nilai: «RT» berubah jadi «0» sesudah digulir → dipulihkan",
                        2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "dropdown_band", 5),
                                        setattr(p, "rusak_paksa_kolom", "rt")),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p35.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji penjaga nilai")
    cek(p35.rusak_paksa_kali >= 1, "uji tidak bermakna: nilai «RT» tidak pernah dirusak gulir")
    cek(str(p35.data_bio_tersimpan.get("rt") or "").strip() == "3",
        f"nilai «RT» tersimpan dalam keadaan rusak: {p35.data_bio_tersimpan.get('rt')!r} "
        "(seharusnya dikembalikan menjadi «3»)")
    cek(p35.penjaga_dipulihkan >= 1,
        "penjaga nilai tidak pernah mengembalikan nilai kolom yang berubah")
    cek(any("berubah sesudah menggulir" in b for b in j35),
        [b for b in j35 if "penjaga" in b][:4] or j35[-6:])
    cek(any("dikembalikan menjadi «3»" in b for b in j35),
        [b for b in j35 if "penjaga" in b][:4] or j35[-6:])
    cek(p35.gulir_kursor_di_kolom == 0,
        f"ada {p35.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom (penjaga nilai)")
    salah35 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p35.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah35, f"kolom yang nilainya tidak benar sesudah dirusak gulir: {salah35}")

    # 36) Versi Dapodik yang tidak punya kolom ``kode_wilayah_str``: bot TIDAK boleh berhenti
    #     atau mengklaim sudah terverifikasi — pemilihan dinilai dari nilai model combo-nya,
    #     keterbatasan itu ditulis di log, dan desanya tetap tersimpan.
    p36, j36 = jalankan("36. kode_wilayah_str tidak ada di halaman → keterbatasan dilaporkan", 2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "tanpa_kode_wilayah", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p36.bio_tersimpan, "jendela «Ubah» tidak tersimpan saat kode wilayah tak ada di halaman")
    cek(p36.data_bio_tersimpan.get("kelurahan") == DESA_PILIH_PALSU,
        f"desa tidak tersimpan padahal hanya kolom kode wilayahnya yang tidak ada: "
        f"{p36.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p36.bio_kode_ditolak == 0,
        f"Dapodik menolak desanya {p36.bio_kode_ditolak}x — padahal nilai modelnya benar")
    cek(any("kode_wilayah_str) tidak ada di halaman" in b for b in j36),
        f"keterbatasan «kolom kode wilayah tidak ada» tidak dilaporkan: "
        f"{[b for b in j36 if 'kode wilayah' in b][:4]}")
    cek(any("dinilai dari nilai model" in b for b in j36),
        "bot tidak menjelaskan dari apa hasil pemilihannya dinilai: "
        f"{[b for b in j36 if 'kode wilayah' in b][:4]}")
    cek(p36.gulir_kursor_di_kolom == 0,
        f"ada {p36.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom (tanpa kode wilayah)")

    # 37) Kode wilayah desa berubah LAGI sesudah desanya dipilih (nilai kolom berubah karena
    #     gulir — kelas masalah yang sama dengan «RT» menjadi «0»). Bot memeriksa desa sekali
    #     lagi tepat sebelum «Simpan», memasang ulang pilihannya lewat model Ext JS, dan
    #     melaporkan apa yang dilakukannya.
    p37, j37 = jalankan("37. kode wilayah berubah sesudah dipilih → dipasang ulang sebelum "
                        "«Simpan»", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "dropdown_band", 5),
                                        setattr(p, "desa_kode_rusak_gulir", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p37.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji «kode berubah sesudah dipilih»")
    cek(p37.desa_dirusak_kali >= 1,
        "uji tidak bermakna: kode wilayah desa tidak pernah dikembalikan gulir ke desa lama")
    cek(p37.data_bio_tersimpan.get("kelurahan") == DESA_PILIH_PALSU,
        f"desa yang tersimpan bukan desa yang dipilih: "
        f"{p37.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p37.kode_wilayah() == kode_desa_palsu(DESA_PILIH_PALSU),
        f"kode_wilayah_str sesudah «Simpan» masih menunjuk desa lain: {p37.kode_wilayah()!r}")
    cek(p37.bio_kode_ditolak == 0,
        f"Dapodik mengembalikan desanya {p37.bio_kode_ditolak}x — pilihan tidak dipasang ulang "
        "sebelum «Simpan»")
    cek(BOT_TERAKHIR is not None and BOT_TERAKHIR.desa_dipulihkan_kali >= 1,
        "bot tidak memasang ulang pilihan desanya sesudah kodenya berubah "
        f"({getattr(BOT_TERAKHIR, 'desa_dipulihkan_kali', None)}x)")
    cek(any("berubah sesudah dipilih" in b for b in j37),
        f"perubahan kode wilayah tidak dilaporkan: {[b for b in j37 if 'Desa/Kelurahan' in b][-4:]}")
    cek(any("dipasang ulang sebelum «Simpan»" in b for b in j37),
        f"pemasangan ulang sebelum «Simpan» tidak dicatat: "
        f"{[b for b in j37 if 'Desa/Kelurahan' in b][-4:]}")
    cek(p37.gulir_kursor_di_kolom == 0,
        f"ada {p37.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom (desa berubah)")

    # 38) «Semua kolom bisa berubah ketika di-scroll» — bukan hanya kolom angka. Di skenario ini
    #     setiap gulir mengubah nilai SEMUA kolom yang sudah diisi (keadaan terkeras: gulir oleh
    #     orang di depan layar). Bot harus mengembalikannya sebelum «Simpan», sehingga data yang
    #     tersimpan di Dapodik tetap utuh.
    p38, j38 = jalankan("38. semua kolom berubah sesudah digulir → dikembalikan sebelum «Simpan»",
                        2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "dropdown_band", 5),
                                        setattr(p, "rusak_paksa_semua", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p38.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji «semua kolom berubah»")
    cek(p38.rusak_paksa_kali >= 5,
        f"uji tidak bermakna: hanya {p38.rusak_paksa_kali} kolom yang dirusak gulir "
        "(seharusnya banyak kolom)")
    cek(p38.penjaga_dipulihkan >= 1,
        "penjaga nilai tidak pernah mengembalikan kolom yang berubah")
    salah38 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p38.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah38, f"kolom yang tersimpan tidak sesuai sesudah gulir merusak semua kolom: {salah38}")
    cek(p38.data_bio_tersimpan.get("kelurahan") == DESA_PILIH_PALSU,
        f"desa tidak tersimpan benar: {p38.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p38.bio_kode_ditolak == 0,
        f"Dapodik menolak desanya {p38.bio_kode_ditolak}x pada uji «semua kolom berubah»")
    cek(any("dikembalikan" in b and "nilai" in b for b in j38),
        f"pengembalian nilai tidak dicatat: {[b for b in j38 if 'penjaga' in b][:3]}")
    cek(any("berubah sesudah menggulir" in b for b in j38),
        f"perubahan nilai tidak dilaporkan apa adanya: {[b for b in j38 if 'penjaga' in b][:3]}")
    cek(p38.gulir_kursor_di_kolom == 0,
        f"ada {p38.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom")

    # 39) Dapodik menyimpan kolom angka dengan caranya sendiri: «007» → «7» dan «63.5» →
    #     «63,5» (numberfield, pemisah desimal gaya Indonesia). Bentuk yang berbeda itu BUKAN
    #     kegagalan pengisian — dulu bot melaporkannya «kolom belum berisi nilai yang benar»
    #     (keluhan ronde 47: «masih gagal input rt dan rw»), dan penjaga nilainya berkelahi
    #     dengan Dapodik dengan menuliskan kembali bentuk lamanya.
    p39, j39 = jalankan("39. kolom angka Dapodik: «007» → «7», «63.5» → «63,5» (bukan gagal)", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "angka_menormalkan", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"},
                        ubah_siswa={"rt": "007", "rw": "003", "berat_badan": 63.5})
    cek(p39.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji normalisasi angka")
    cek(p39.angka_dinormalkan >= 1,
        f"uji tidak bermakna: {p39.angka_dinormalkan} kolom angka dinormalkan Dapodik")
    cek(p39.data_bio_tersimpan.get("rt") == "7",
        f"RT tersimpan {p39.data_bio_tersimpan.get('rt')!r} (data «007» seharusnya jadi «7»)")
    cek(p39.data_bio_tersimpan.get("rw") == "3",
        f"RW tersimpan {p39.data_bio_tersimpan.get('rw')!r} (data «003» seharusnya jadi «3»)")
    berat39 = str(p39.data_periodik_tersimpan.get("berat_badan") or "").strip()
    cek(berat39.replace(",", ".") == "63.5",
        f"berat badan tersimpan {berat39!r} — seharusnya 63,5 (gaya Dapodik)")
    cek(not any("belum berisi nilai yang benar" in b for b in j39),
        [b for b in j39 if "belum berisi nilai yang benar" in b][:3])
    cek(any("Dapodik menyimpan kolom ini sebagai angka" in b for b in j39),
        [b for b in j39 if "sebagai angka" in b][:3])
    cek(not any(("«rt»" in b or "«rw»" in b) and "berubah sesudah menggulir" in b for b in j39),
        f"penjaga nilai berkelahi dengan bentuk angka Dapodik: "
        f"{[b for b in j39 if 'penjaga' in b][:3]}")
    cek(not any("kolomnya tidak ketemu" in b for b in j39),
        f"kolom angka ada yang tidak ketemu: {[b for b in j39 if 'tidak ketemu' in b][:3]}")

    # 40) Kolom combo «Desa/Kelurahan» pada versi Dapodik sekolah tidak punya atribut name dan
    #     labelnya bukan elemen <label> — bot sekarang memakai XPath lengkap yang dikirim
    #     sekolah sebagai jalur paling akhir, sesudah kandidat nama/label gagal.
    cek(bot_dapodik.SELECTOR_CADANGAN["bio_kelurahan"][-1]
        == "xpath:" + peramban_palsu.XPATH_DESA_SEKOLAH,
        "XPath lengkap dari sekolah tidak terpasang sebagai kandidat terakhir kolom desa")
    p40, j40 = jalankan("40. kolom desa tanpa name & label → XPath lengkap sekolah dipakai", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "desa_tanpa_nama", True),
                                        setattr(p, "desa_tanpa_label", True),
                                        setattr(p, "desa_jalur_xpath", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p40.xpath_desa_dipakai >= 1, "XPath lengkap dari sekolah tidak pernah dipakai")
    cek(p40.bio_tersimpan, "jendela «Ubah» tidak tersimpan saat kolom desa hanya bisa lewat XPath")
    cek(p40.data_bio_tersimpan.get("kelurahan") == DESA_PILIH_PALSU,
        f"desa tidak tersimpan: {p40.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p40.kode_wilayah() == kode_desa_palsu(DESA_PILIH_PALSU),
        f"kode wilayah sesudah «Simpan»: {p40.kode_wilayah()!r}")
    cek(p40.bio_kode_ditolak == 0, f"Dapodik menolak desanya {p40.bio_kode_ditolak}x")
    cek(any("XPath lengkap yang dikirim sekolah" in b for b in j40),
        [b for b in j40 if "Desa/Kelurahan" in b][:4])

    # 41) Versi Dapodik yang menggambar label kolom desa sebagai div Ext JS
    #     (``.x-fieldlabel``): kolomnya tetap harus ketemu & desanya tersimpan.
    p41, j41 = jalankan("41. label kolom desa berupa div Ext JS (bukan <label>)", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "desa_tanpa_nama", True),
                                        setattr(p, "desa_tanpa_label", True),
                                        setattr(p, "desa_label_div", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p41.label_div_dipakai >= 1,
        "label div (`.x-fieldlabel`) tidak dipakai saat mencari kolom")
    cek(any("labelnya yang berbentuk div" in b for b in j41),
        [b for b in j41 if "Desa/Kelurahan" in b][:4])
    cek(p41.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada versi berlabel div")
    cek(p41.data_bio_tersimpan.get("kelurahan") == DESA_PILIH_PALSU,
        f"desa tidak tersimpan: {p41.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p41.kode_wilayah() == kode_desa_palsu(DESA_PILIH_PALSU),
        f"kode wilayah sesudah «Simpan»: {p41.kode_wilayah()!r}")
    cek(p41.bio_kode_ditolak == 0, f"Dapodik menolak desanya {p41.bio_kode_ditolak}x")

    # 42) Keamanan jalur XPath: bila XPath yang dikirim menunjuk kolom yang BUKAN combo,
    #     bot tidak boleh menuliskan nama desa ke kolom itu — ia melewatinya, melaporkan apa
    #     adanya, dan menyebutkan isian apa saja yang ADA di jendela «Ubah».
    p42, j42 = jalankan("42. XPath sekolah menunjuk kolom BUKAN combo → tidak disalahgunakan", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "desa_tanpa_nama", True),
                                        setattr(p, "desa_tanpa_label", True),
                                        setattr(p, "desa_jalur_xpath", True),
                                        setattr(p, "xpath_desa_salah", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p42.data_bio_tersimpan.get("rt") == "3",
        f"RT terisi nilai lain oleh XPath desa: {p42.data_bio_tersimpan.get('rt')!r}")
    cek(p42.data_bio_tersimpan.get("kelurahan") == DESA_LAMA_PALSU,
        f"desa lama ikut berubah padahal kolomnya tidak ketemu: "
        f"{p42.data_bio_tersimpan.get('kelurahan')!r}")
    cek(any("BUKAN combo" in b for b in j42), [b for b in j42 if "Desa/Kelurahan" in b][:4])
    cek(any("tidak ketemu" in b and "Desa/Kelurahan" in b for b in j42),
        [b for b in j42 if "Desa/Kelurahan" in b][-3:])
    cek(any("isian yang ADA di jendela" in b for b in j42),
        [b for b in j42 if "isian yang ADA" in b][:2])
    cek(p42.bio_kode_ditolak == 0,
        f"«Simpan» Dapodik menolak {p42.bio_kode_ditolak}x padahal kolom desa tidak disentuh")

    # 43) Lingkungan yang dilaporkan sekolah: SEMUA label kolom digambar sebagai div Ext JS
    #     (bukan <label>) — persis keadaan yang membuat RT & RW «gagal diisi» padahal kolom
    #     lain berhasil. Bot harus menemukan kolomnya lewat nama kolom (cara skrip sekolah)
    #     dan lewat label div.
    p43, j43 = jalankan("43. semua label kolom berupa div Ext JS → RT/RW tetap terisi", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "label_div_semua", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p43.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada versi berlabel div")
    salah43 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p43.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah43, f"kolom yang tersimpan tidak sesuai pada versi berlabel div: {salah43}")
    cek(any("RT: terisi" in b for b in j43), [b for b in j43 if "RT" in b][:3])
    cek(any("RW: terisi" in b for b in j43), [b for b in j43 if "RW" in b][:3])
    cek(not any("kolomnya tidak ketemu" in b for b in j43),
        f"masih ada kolom yang tidak ketemu: {[b for b in j43 if 'tidak ketemu' in b][:3]}")
    cek(p43.data_bio_tersimpan.get("kelurahan") == DESA_PILIH_PALSU,
        f"desa tidak tersimpan: {p43.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p43.gulir_kursor_di_kolom == 0,
        f"ada {p43.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom")

    # 44) Jendela «Ubah» versi Dapodik lain bisa TIDAK memuat kolom RT/RW. Dulu catatannya
    #     hanya «kolomnya tidak ketemu — dilewati» tanpa bukti apa pun, sehingga sekolah tidak
    #     bisa mengirim keterangan yang berguna (ronde 48: «untuk log adanya dimana?»).
    #     Sekarang catatannya menyebut kandidat selector yang dicoba + kolom isian yang ADA,
    #     dan kolom lain tetap terisi seperti biasa.
    p44, j44 = jalankan("44. kolom RT/RW tidak ada di jendela → dilaporkan beserta buktinya", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "tanpa_kolom_angka", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p44.bio_tersimpan, "jendela «Ubah» tidak tersimpan saat kolom RT/RW tidak ada")
    cek("rt" not in p44.data_bio_tersimpan and "rw" not in p44.data_bio_tersimpan,
        "kolom RT/RW dilaporkan tersimpan padahal tidak ada di jendela: "
        f"{ {k: v for k, v in p44.data_bio_tersimpan.items() if k in ('rt', 'rw')} }")
    cek(any("RT: kolomnya TIDAK ketemu" in b for b in j44),
        f"«RT tidak ketemu» tidak dilaporkan apa adanya: {[b for b in j44 if 'RT' in b][:4]}")
    cek(any("RW: kolomnya TIDAK ketemu" in b for b in j44),
        f"«RW tidak ketemu» tidak dilaporkan: {[b for b in j44 if 'RW' in b][:4]}")
    cek(any("kandidat yang dicoba" in b and "name:rt=" in b for b in j44),
        f"kandidat selector untuk RT tidak disebut beserta hasilnya: "
        f"{[b for b in j44 if 'kandidat' in b][:3]}")
    cek(any("kolom isian yang ADA di halaman" in b for b in j44),
        f"daftar kolom isian yang ADA tidak dilaporkan: "
        f"{[b for b in j44 if 'ADA di halaman' in b][:3]}")
    salah44 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if nama_kolom not in ("rt", "rw")
               and str(p44.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah44, f"kolom lain ikut tidak terisi saat RT/RW tidak ada: {salah44}")
    cek(p44.data_bio_tersimpan.get("kelurahan") == DESA_PILIH_PALSU,
        "desa tidak tersimpan pada uji kolom RT/RW tidak ada: "
        f"{p44.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p44.gulir_kursor_di_kolom == 0,
        f"ada {p44.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom (RT/RW tidak ada)")

    # 45) Keamanan kandidat XPath lengkap dari sekolah: pada versi Dapodik yang kolom desanya
    #     tidak punya atribut name/label, XPath itu bisa MELESET (mis. menunjuk kolom «RT»).
    #     Bot tidak boleh menyalahgunakannya dengan menulis nama desa ke kolom lain — lebih baik
    #     melaporkan «tidak ketemu» beserta bukti kolom apa yang ADA di jendela «Ubah», dan
    #     membiarkan desa lama Dapodik apa adanya.
    p45, j45 = jalankan("45. XPath desa meleset ke kolom lain → tidak disalahgunakan", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "desa_tanpa_nama", True),
                                        setattr(p, "desa_tanpa_label", True),
                                        setattr(p, "xpath_desa_salah", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p45.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji kandidat XPath meleset")
    cek(str(p45.data_bio_tersimpan.get("rt") or "").strip() == "3",
        "kolom «RT» ditimpa kandidat desa yang meleset: "
        f"{p45.data_bio_tersimpan.get('rt')!r}")
    cek(p45.data_bio_tersimpan.get("kelurahan") == DESA_LAMA_PALSU,
        "desa berubah padahal kandidat desanya meleset: "
        f"{p45.data_bio_tersimpan.get('kelurahan')!r}")
    cek(p45.bio_kode_ditolak == 0,
        f"Dapodik menolak desanya {p45.bio_kode_ditolak}x pada uji kandidat meleset")
    cek(any("BUKAN combo" in b for b in j45),
        f"kandidat yang bukan combo tidak dilaporkan: {[b for b in j45 if 'Desa/Kelurahan' in b][:6]}")
    cek(any("isian yang ADA di jendela «Ubah»" in b for b in j45),
        f"isian yang ADA di jendela tidak dilaporkan: "
        f"{[b for b in j45 if 'Desa/Kelurahan' in b][:6]}")
    cek(p45.gulir_kursor_di_kolom == 0,
        f"ada {p45.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom (XPath meleset)")

    # 46) RT/RW di Dapodik berupa numberfield: yang BENAR-BENAR disimpan saat «Simpan» adalah
    #     nilai MODEL Ext JS-nya, bukan tulisan di kotaknya. Bila gulir mengubah nilainya
    #     menjadi «0» dan yang dikembalikan hanya tulisan di kotak, Dapodik tetap menyimpan
    #     «0» — persis keluhan ronde 48 «masih gagal input rt dan rw». Bot harus memeriksa
    #     modelnya dan memperbaikinya lewat ``Ext.getCmp(...).setValue(...)`` sebelum «Simpan».
    p46, j46 = jalankan("46. RT tersimpan dari model Ext JS: kotak benar, model «0» → diperbaiki",
                        2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "angka_menormalkan", True),
                                        setattr(p, "model_angka_terpisah", True),
                                        setattr(p, "dropdown_band", 5),
                                        setattr(p, "rusak_paksa_kolom", "rt")),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p46.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji model Ext JS kolom angka")
    cek(p46.rusak_paksa_kali >= 1,
        "uji tidak bermakna: nilai «RT» tidak pernah dirusak gulir (DOM + model Ext JS)")
    cek(p46.model_diperbaiki_kali >= 1,
        f"nilai model Ext JS tidak pernah diperbaiki lewat setValue "
        f"({p46.model_diperbaiki_kali}x) — Dapodik akan menyimpan «0»")
    cek(p46.model_dibaca_kali >= 1,
        "bot tidak pernah membaca nilai model Ext JS (getValue) kolom angka")
    cek(str(p46.data_bio_tersimpan.get("rt") or "").strip() == "3",
        f"RT tersimpan {p46.data_bio_tersimpan.get('rt')!r} — model Ext JS-nya tidak ikut "
        "diperbaiki sebelum «Simpan»")
    cek(any("model Ext JS" in b and "ditulis ulang lewat Ext JS (setValue)" in b for b in j46),
        f"perbaikan model Ext JS tidak dilaporkan apa adanya: "
        f"{[b for b in j46 if 'model Ext JS' in b][:4]}")
    salah46 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p46.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah46, f"kolom yang tersimpan tidak sesuai pada uji model Ext JS: {salah46}")
    cek(not any("belum berisi nilai yang benar" in b for b in j46),
        [b for b in j46 if "belum berisi nilai yang benar" in b][:3])
    cek(p46.gulir_kursor_di_kolom == 0,
        f"ada {p46.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom (model Ext JS)")


    # 47) LOG SEKOLAH 29 Sep 2026 («bio-tidak-terisi»): bot mengira hampir SEMUA kolom jendela
    #     «Ubah» adalah dropdown lalu melewatinya — RT, RW, No. KK, NIK, nama ayah, kode pos,
    #     tahun lahir, alamat … Semuanya berbunyi «daftar dropdown TIDAK terbaca … dilewati».
    #     Sebabnya: DOM Dapodik itu tidak memakai kelas ``.x-field``, sehingga wadah yang dibaca
    #     skrip lama memuat kolom TETANGGA beserta tombol putar numberfield (``x-form-trigger``).
    #     Ronde 49: jenis kolom ditentukan dari bukti yang melekat pada kolom itu sendiri —
    #     panah dropdown, role=combobox, atau komponen Ext JS yang benar-benar memuat unsur itu.
    p47, j47 = jalankan("47. DOM sekolah (wadah lebar) → kolom biasa tidak lagi dikira dropdown", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "dom_wadah_lebar", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p47.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji DOM sekolah")
    cek(not any("daftar dropdown TIDAK terbaca" in b for b in j47),
        f"masih ada kolom yang dilewati karena «daftar dropdown TIDAK terbaca»: "
        f"{[b for b in j47 if 'TIDAK terbaca' in b][:4]}")
    cek(not any("bukan dropdown" in b for b in j47),
        f"kolom yang bukan dropdown tetap masuk jalur dropdown: "
        f"{[b for b in j47 if 'bukan dropdown' in b][:3]}")
    cek(any("RT: terisi" in b and "model Ext JS" in b for b in j47),
        f"RT tidak terisi (beserta pemeriksaan model Ext JS-nya): {[b for b in j47 if 'RT:' in b][:3]}")
    salah47 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p47.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah47, f"kolom yang tersimpan tidak sesuai pada DOM sekolah: {salah47}")
    cek(p47.komponen_meleset_kali == 0,
        f"bot memakai komponen Ext JS milik kolom lain {p47.komponen_meleset_kali}x")
    cek(p47.gulir_kursor_di_kolom == 0,
        f"ada {p47.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom")

    # 48) Panah dropdown harus milik KOLOM ITU SENDIRI. Dulu bot memakai
    #     ``following::*[contains(@class, 'x-form-trigger')][1]`` yang menyapu halaman: di
    #     sekolah yang terbuka daftar kolom TETANGGA (log: kolom «Tahun lahir ayah» menampilkan
    #     daftar «Pendidikan ayah», lalu nilainya dilaporkan «TIDAK ADA di daftar»).
    p48, j48 = jalankan("48. panah dropdown milik kolomnya sendiri, bukan milik tetangga", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "dom_wadah_lebar", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p48.panah_sendiri_dipakai >= 1,
        "panah dropdown milik kolom itu sendiri tidak pernah dipakai")
    cek(not any("TIDAK ADA di daftar dropdown" in b for b in j48),
        f"pilihan dilaporkan tidak ada padahal daftarnya milik kolom lain: "
        f"{[b for b in j48 if 'TIDAK ADA' in b][:3]}")
    cek(p48.komponen_meleset_kali == 0,
        f"komponen kolom lain dipakai {p48.komponen_meleset_kali}x (id meleset)")
    for kunci, nama_kolom, nilai in BIO_UJI:
        if nama_kolom not in ("Pendidikan ayah", "Pekerjaan ayah", "Penghasilan ayah",
                              "Pendidikan ibu", "Pekerjaan ibu", "Penghasilan ibu"):
            continue
        cek(str(p48.data_bio_tersimpan.get(nama_kolom) or "").strip() == nilai,
            f"{nama_kolom} tidak tersimpan benar dari daftarnya: "
            f"{p48.data_bio_tersimpan.get(nama_kolom)!r}")
    cek(p48.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji panah milik kolom")

    # 49) Versi Dapodik yang penanda dropdown-nya tidak terbaca (tidak ada panah & role):
    #     kolom combo pun dikira kolom biasa, teksnya diketik — dan Dapodik menyimpan KOSONG,
    #     karena yang tersimpan hanya pilihan dari daftarnya. Bot harus menyadarinya dari
    #     **model Ext JS yang kosong** lalu mencoba daftarnya (ronde 49).
    p49, j49 = jalankan("49. combo tanpa penanda → ketikan tak tersimpan, dicoba lewat daftar", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "kombo_tak_terbaca", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p49.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji combo tanpa penanda")
    cek(any("model Ext JS-nya kosong" in b for b in j49),
        f"model Ext JS yang kosong tidak dilaporkan: "
        f"{[b for b in j49 if 'model Ext JS' in b][:4]}")
    for kunci, nama_kolom, nilai in BIO_UJI:
        if nama_kolom not in ("Pendidikan ayah", "Pekerjaan ayah", "Penghasilan ayah",
                              "Pendidikan ibu", "Pekerjaan ibu", "Penghasilan ibu"):
            continue
        cek(str(p49.data_bio_tersimpan.get(nama_kolom) or "").strip() == nilai,
            f"{nama_kolom} tersimpan kosong/salah pada uji combo tanpa penanda: "
            f"{p49.data_bio_tersimpan.get(nama_kolom)!r}")
    salah49 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if " " not in nama_kolom and str(
                   p49.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah49, f"kolom biasa ikut salah pada uji combo tanpa penanda: {salah49}")
    cek(p49.gulir_kursor_di_kolom == 0,
        f"ada {p49.gulir_kursor_di_kolom}x gulir selagi kursor masih di dalam kolom")

    # 50) Kolom teks yang memakai unsur bergaya panah TANPA bukti combo (role/aria/xtype/
    #     store): di sekolah kolom seperti ini dilaporkan «daftar dropdown TIDAK terbaca —
    #     dilewati». Bot harus mengetik nilainya lebih dulu; panah itu tidak boleh dipakai
    #     membuka daftar, dan bila ternyata kolomnya combo sungguhan (ketikan tidak
    #     tersimpan) barulah daftarnya dicoba.
    p50, j50 = jalankan("50. unsur mirip panah tanpa bukti combo → kolom tetap diketik", 2,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "panah_tanpa_data", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p50.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji panah tanpa data")
    cek(p50.panah_tak_berdata_kali == 0,
        f"panah kolom tanpa data dipakai {p50.panah_tak_berdata_kali}x membuka dropdown")
    cek(any("tidak ada bukti combo" in b for b in j50),
        f"kolom dengan unsur mirip panah tidak dicatat jujur: "
        f"{[b for b in j50 if 'panah' in b][:3]}")
    cek(not any("daftar dropdown TIDAK terbaca" in b or "dilewati — daftar dropdown" in b
                for b in j50),
        f"kolom masih dilewati karena daftar dropdown tak terbaca: "
        f"{[b for b in j50 if 'TIDAK terbaca' in b][:3]}")
    salah50 = [nama_kolom for kunci, nama_kolom, nilai in BIO_UJI
               if str(p50.data_bio_tersimpan.get(nama_kolom) or "").strip() != nilai]
    cek(not salah50, f"kolom yang tersimpan tidak sesuai pada uji panah tanpa data: {salah50}")
    for kunci, nama_kolom, nilai in BIO_UJI:
        if nama_kolom not in ("Pendidikan ayah", "Pekerjaan ayah", "Penghasilan ayah",
                              "Pendidikan ibu", "Pekerjaan ibu", "Penghasilan ibu"):
            continue
        cek(str(p50.data_bio_tersimpan.get(nama_kolom) or "").strip() == nilai,
            f"{nama_kolom} tidak tersimpan dari daftarnya pada uji panah tanpa data: "
            f"{p50.data_bio_tersimpan.get(nama_kolom)!r}")

    # 51) Catatan sekolah 29 September 2026 (bot 4728e77): «Simpan» DITOLAK Dapodik —
    #     «pekerjaan_id_wali: This field is required; inputItem: The minimum value for this
    #     field is 1». Nama kolom itu saja tidak cukup (kolom bernama «inputItem» tidak
    #     muncul di layar), jadi bot ronde 50 harus membaca galatnya bersama LABEL & BAGIAN
    #     kolomnya, mengosongkan «0» bawaan Dapodik, mengisi kolom wali yang wajib dari data
    #     ayah (SM tidak menyimpan wali selama nama ayah terisi), menekan «Simpan» sekali
    #     lagi — dan jendelanya benar-benar TERTUTUP: datanya tersimpan, bukan hanya
    #     dilaporkan.
    p51, j51 = jalankan("51. «Simpan» ditolak Dapodik: kolom wali wajib → diisi dari ayah", 2,
                        bio_wali=True,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "bio_gagal_wali", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p51.bio_tolak_simpan_kali == 1,
        f"Dapodik menolak «Simpan» {p51.bio_tolak_simpan_kali}x — harus 1x sebelum diperbaiki")
    cek(p51.bio_tersimpan, "jendela «Ubah» tidak tersimpan sesudah kolom wali diperbaiki")
    cek(not p51.bio_terbuka, "jendela «Ubah» masih terbuka sesudah perbaikan")
    cek(str(p51.data_bio_tersimpan.get("pekerjaan_id_wali") or "").strip()
        == SISWA["ayah_pekerjaan"],
        f"kolom «Pekerjaan Wali» tidak tersimpan dari data ayah: "
        f"{p51.data_bio_tersimpan.get('pekerjaan_id_wali')!r}")
    cek(str(p51.data_bio_tersimpan.get("inputItem") or "").strip() == "",
        f"kolom «inputItem» yang berisi «0» tidak dikosongkan: "
        f"{p51.data_bio_tersimpan.get('inputItem')!r}")
    cek(any("Pekerjaan Wali" in b and "Data Wali" in b for b in j51),
        f"label & bagian kolom yang ditolak tidak dilaporkan: "
        f"{[b for b in j51 if 'wali' in b.lower()][:4]}")
    cek(any("mengikuti ayah" in b for b in j51),
        f"bot tidak melaporkan bahwa kolom wali diisi mengikuti ayah: "
        f"{[b for b in j51 if 'wali' in b.lower()][:4]}")
    cek(any("penanda kosong dari Dapodik" in b for b in j51),
        f"alasan «0» dikosongkan tidak dilaporkan: "
        f"{[b for b in j51 if 'perbaikan' in b][:4]}")
    cek(any("tertutup SESUDAH perbaikan" in b for b in j51),
        f"keberhasilan sesudah perbaikan tidak dilaporkan jujur: {j51[-5:]}")
    cek(p51.gulir_kursor_di_kolom == 0, "ada gulir selagi kursor masih di dalam kolom")
    salah51 = [kunci for _, kunci, nilai in BIO_UJI
               if str(p51.data_bio_tersimpan.get(kunci) or "").strip() != nilai]
    cek(not salah51, f"kolom lain ikut salah pada uji kolom wali: {salah51}")

    # 52) Pengaturan «Wali mengikuti ayah» DIMATIKAN: bot TIDAK BOLEH mengarang nilai wali.
    #     Yang diharapkan: laporan jujur (kolom wali belum bisa diisi + pengaturannya
    #     dimatikan), jendela «Ubah» DITUTUP supaya Data Periodik & Registrasi tetap jalan —
    #     inilah yang di sekolah masih memunculkan «baris siswa belum terpilih sesudah
    #     menyimpan Data Periodik».
    p52, j52 = jalankan("52. pengaturan «Wali mengikuti ayah» mati → jujur & jendela ditutup",
                        2, bio_wali=True,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "bio_gagal_wali", True)),
                        tampilkan=True,
                        opsi={"bot_isi_bio": "1", "bot_wali_ikuti_ayah": "0"})
    cek(not p52.bio_tersimpan, "BIO dianggap tersimpan padahal Dapodik menolaknya")
    cek(not p52.bio_terbuka, "jendela «Ubah» tidak ditutup bot sesudah Dapodik menolak")
    cek(p52.tutup_jendela_ubah_kali == 1,
        f"jendela «Ubah» ditutup {p52.tutup_jendela_ubah_kali}x (harus tepat 1x)")
    cek(any("dimatikan" in b and "Wali mengikuti ayah" in b for b in j52),
        f"pengaturan yang dimatikan tidak dilaporkan: "
        f"{[b for b in j52 if 'perbaikan' in b][:4]}")
    cek(any("BELUM tersimpan" in b for b in j52),
        f"bot tidak berkata jujur bahwa BIO belum tersimpan: {j52[-5:]}")
    cek(p52.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "2",
        "langkah Data Periodik terganggu oleh jendela «Ubah» yang menolak simpan")
    cek(any(b.startswith("[OK]") for b in j52), f"Registrasi tidak jalan: {j52[-4:]}")

    # 53) Bacaan KEDUA atas galat yang sama: «0» pada kolom «Penghasilan Wali» tidak cukup
    #     dikosongkan — Dapodik menuntut pilihan nyata (nilai model ≥ 1). Bot harus mencoba
    #     cara pertama (kosongkan) DULU, melihat Dapodik masih menolak, lalu mengisi kolom itu
    #     dari data ayah — berurutan, dibatasi jumlah putarannya, dan tiap putaran dilaporkan.
    p53, j53 = jalankan("53. «0» keras: dikosongkan dulu, masih ditolak → diisi dari ayah", 2,
                        bio_wali=True,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "bio_gagal_wali", True),
                                        setattr(p, "bio_min_keras", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p53.bio_tolak_simpan_kali == 2,
        f"Dapodik menolak {p53.bio_tolak_simpan_kali}x (harus 2x: «0» lalu pilihan nyata)")
    cek(p53.bio_tersimpan, "jendela «Ubah» tidak tersimpan pada uji «0» yang keras")
    cek(not p53.bio_terbuka, "jendela «Ubah» masih terbuka pada uji «0» yang keras")
    cek(str(p53.data_bio_tersimpan.get("inputItem") or "").strip()
        == SISWA["ayah_penghasilan"],
        f"kolom wajib itu tidak terisi dari data ayah: "
        f"{p53.data_bio_tersimpan.get('inputItem')!r}")
    cek(any("perbaikan ke-2" in b for b in j53),
        f"putaran perbaikan kedua tidak dilaporkan: {[b for b in j53 if 'perbaikan' in b][:4]}")
    cek(any("Penghasilan Wali" in b and "mengikuti ayah" in b for b in j53),
        f"kolom wajib itu tidak diisi dari data ayah secara terbuka: "
        f"{[b for b in j53 if 'perbaikan' in b][:4]}")

    # 54) Identitas wali (nama/NIK) TIDAK boleh dikarang: kolom wajib «Nama wali» ditolak
    #     Dapodik, sedangkan SM tidak menyimpan data wali sama sekali. Bot tidak boleh mengisi
    #     nama ayah ke kolom nama wali — yang benar: jujur, jendela ditutup, langkah lain
    #     (Data Periodik & Registrasi) tetap jalan.
    p54, j54 = jalankan("54. identitas wali tidak dikarang → jujur & jendela ditutup", 2,
                        bio_wali=True,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "bio_gagal_wali", True),
                                        setattr(p, "bio_wali_nama_wajib", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(not p54.bio_tersimpan, "BIO dianggap tersimpan padahal nama wali ditolak Dapodik")
    cek(not str(p54.data_bio_tersimpan.get("nama_wali") or "").strip(),
        f"nama wali DIISI bot padahal SM tidak punya data wali (mengarang wali): "
        f"{p54.data_bio_tersimpan.get('nama_wali')!r}")
    cek(any("mengarang wali" in b for b in j54),
        f"alasan nama wali tidak diisi tidak dilaporkan: "
        f"{[b for b in j54 if 'perbaikan' in b][:4]}")
    cek(p54.tutup_jendela_ubah_kali == 1,
        f"jendela «Ubah» ditutup {p54.tutup_jendela_ubah_kali}x (harus tepat 1x)")
    cek(p54.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "2",
        "langkah Data Periodik terganggu pada uji identitas wali")
    cek(any(b.startswith("[OK]") for b in j54), f"Registrasi tidak jalan: {j54[-4:]}")

    # 55) Peringatan «baris siswa belum terpilih setelah menyimpan Data Periodik» — ada di
    #     catatan sekolah. Modelnya: jendela «Ubah» yang tertinggal terbuka (karena «Simpan»
    #     ditolak) menutupi tabel sehingga klik pada baris tidak sampai, sementara Dapodik
    #     menyegarkan daftarnya sesudah Data Periodik disimpan. Bot ronde 50 harus MENUTUP
    #     jendela «Ubah» lebih dulu — barisnya bisa dipilih kembali, peringatan itu tidak
    #     muncul, dan Registrasi tetap jalan (di sekolah registrasinya memang tetap berhasil).
    p55, j55 = jalankan("55. jendela «Ubah» menghalangi baris → baris dipilih lagi sesudah periodik",
                        2, bio_wali=True,
                        atur=lambda p: (p.siapkan_bio(), setattr(p, "bio_gagal_wali", True),
                                        setattr(p, "bio_wali_nama_wajib", True),
                                        setattr(p, "jendela_bio_menghalangi", True),
                                        setattr(p, "daftar_tersegar_sesudah_periodik", True)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p55.daftar_tersegar >= 1,
        "uji tidak bermakna: daftar peserta didik tidak pernah tersegar")
    cek(p55.baris_dipilih_ulang_kali >= 1,
        "bot tidak memilih ulang barisnya sesudah daftar peserta didik tersegar "
        f"({p55.baris_dipilih_ulang_kali}x)")
    cek(p55.baris_klik_terhalang == 0,
        f"{p55.baris_klik_terhalang}x klik baris terhalang jendela «Ubah» yang masih terbuka — "
        "jendelanya seharusnya sudah ditutup bot sebelum Data Periodik")
    cek(p55.tutup_jendela_ubah_kali == 1,
        f"jendela «Ubah» ditutup {p55.tutup_jendela_ubah_kali}x (harus tepat 1x)")
    cek(not any("[periodik] peringatan" in b for b in j55),
        f"peringatan «baris siswa belum terpilih» masih muncul: "
        f"{[b for b in j55 if 'peringatan' in b][:3]}")
    cek(p55.baris_terpilih_saat_registrasi is True,
        f"saat «Registrasi» ditekan baris siswa belum terpilih "
        f"({p55.baris_terpilih_saat_registrasi!r})")
    cek(p55.baris_siswa_terpilih(), "baris siswa tidak terpilih lagi sesudah Data Periodik")
    cek(any("MILIK JENDELA REGISTRASI" in b for b in j55),
        "bot tidak melaporkan tombol «Simpan dan Tutup» mana yang dipakai "
        f"(tombol kembar panel Data Periodik): {[b for b in j55 if 'Simpan dan Tutup' in b][:3]}")
    cek(p55.data_periodik_tersimpan.get("jarak_rumah_ke_sekolah_km") == "2",
        f"Data Periodik tidak tersimpan: {p55.data_periodik_tersimpan}")
    cek(any(b.startswith("[OK]") for b in j55),
        f"Registrasi tidak jalan sesudah baris dipilih ulang: {j55[-4:]}")

    # 56) Catatan sekolah 29 Sep 2026: «untuk value tersebut memang harus menunggu agak lama
    #     biar valuenya muncul». Daftar desa di Dapodik baru diambil dari basis data sesudah
    #     kata kunci diketik — di PC sekolah lama. Uji ini menirukan daftar yang baru muncul
    #     sesudah 24 bacaan: bot harus MENUNGGU (bukan menyerah pada bacaan pertama) dan
    #     desanya tetap terisi.
    p56, j56 = jalankan("56. daftar desa baru muncul sesudah ditunggu → tetap terisi", 2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "desa_muat_perlu_default", 24)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(any("daftar desa muncul" in b and "ditunggu" in b for b in j56),
        f"bot tidak melaporkan penantian daftar desa: {[b for b in j56 if 'desa' in b][:4]}")
    angka56 = 0
    for baris in [b for b in j56 if "daftar desa muncul" in b]:
        if "ditunggu " in baris and "x baca" in baris:
            potong = baris.split("ditunggu ", 1)[1].split("x baca", 1)[0].strip()
            angka56 = max(angka56, int(potong) if potong.isdigit() else 0)
    cek(angka56 >= 20,
        f"daftar desa muncul tanpa penantian yang berarti ({angka56}x baca) — uji tidak bermakna: "
        f"{[b for b in j56 if 'daftar desa muncul' in b]}")
    cek(str(p56.data_bio_tersimpan.get("kelurahan") or "").strip() != ""
        and SISWA["kelurahan"].lower() in str(p56.data_bio_tersimpan.get("kelurahan")).lower(),
        f"desa tidak terisi pada uji daftar desa yang lambat: "
        f"{p56.data_bio_tersimpan.get('kelurahan')!r}")
    cek(any(b.startswith("[OK]") for b in j56), f"Registrasi tidak jalan: {j56[-4:]}")

    # 57) Nilai pilihannya pun tidak selalu muncul seketika: sesudah diklik, Dapodik masih
    #     menuliskan nilai desa + ``kode_wilayah_str`` dari basis datanya. Bot harus memeriksa
    #     berulang sampai nilainya muncul — bukan menyimpulkan gagal dari bacaan pertama.
    p57, j57 = jalankan("57. nilai desa baru muncul sesudah ditunggu → tetap terverifikasi", 2,
                        atur=lambda p: (p.siapkan_bio(),
                                        setattr(p, "desa_nilai_muat_perlu_default", 10)),
                        tampilkan=True, opsi={"bot_isi_bio": "1"})
    cek(p57.desa_lambat_kali >= 5,
        f"uji tidak bermakna: nilai desa muncul terlalu cepat ({p57.desa_lambat_kali} bacaan)")
    cek(any("tidak muncul seketika" in b and "ditunggu" in b for b in j57),
        f"bot tidak melaporkan bahwa nilainya ditunggu: "
        f"{[b for b in j57 if 'Desa/Kelurahan' in b][:4]}")
    cek(str(p57.data_bio_tersimpan.get("kelurahan") or "").strip() != ""
        and SISWA["kelurahan"].lower() in str(p57.data_bio_tersimpan.get("kelurahan")).lower(),
        f"desa tidak terisi pada uji nilai desa yang lambat: "
        f"{p57.data_bio_tersimpan.get('kelurahan')!r}")
    cek(any("kode wilayah" in b and "✓" in b for b in j57),
        f"kode wilayah tidak diverifikasi sesudah penantian: "
        f"{[b for b in j57 if 'kode wilayah' in b][:3]}")
    cek(not any("TIDAK jadi terisi" in b for b in j57),
        f"bot menyerah pada bacaan pertama, padahal nilainya baru muncul sesudah ditunggu: "
        f"{[b for b in j57 if 'Desa/Kelurahan' in b][-3:]}")
    cek(any(b.startswith("[OK]") for b in j57), f"Registrasi tidak jalan: {j57[-4:]}")

    print(f"\n[SELESAI] {pemeriksaan} pemeriksaan lolos pada 57 skenario")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
