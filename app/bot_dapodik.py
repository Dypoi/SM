"""Bot Dapodik — menjalankan registrasi peserta didik di Dapodik lokal.

**Alurnya adalah port skrip Selenium sekolah** (``DAFDIR KLS7`` + tombol Registrasi):
langkah, penantian, dan percobaan ulangnya sama — hanya sumber antrean & cara menampilkan
kemajuannya yang berbeda. Empat perbedaan penting dari skrip aslinya:

1. **Antrean dari aplikasi SM, bukan berkas Excel**: NISN & NIS/NIPD diambil
   dari tabel ``students`` (lihat :func:`app.services.bot_antrean`).
2. **Berjalan di belakang layar**: Chrome dijalankan *headless* (tanpa jendela),
   sehingga bot bekerja sambil aplikasi SM tetap dipakai. Bila perlu melihat
   prosesnya (mis. mengisi verifikasi pertama kali), matikan opsi headless di
   halaman Bot Dapodik.
3. **Kemajuannya tampil di aplikasi**: setiap siswa dicatat pada tabel
   ``dapodik_job_items`` sehingga halaman Bot Dapodik bisa menampilkan progres
   secara langsung, dan pekerjaan bisa dilanjutkan tanpa mengulang yang sukses.
4. **Ada mode uji coba** (``bot_simulasi``): antrean, aturan lewati, kemajuan,
   dan log diuji tanpa membuka peramban/Dapodik sama sekali.

Alur tiap siswa (sama dengan skrip asli):

    cari NISN -> pilih baris -> Registrasi -> isi NIS -> centang semua "Ya"
    -> Hobi -> Cita-cita -> "Simpan dan Tutup"
"""

from __future__ import annotations

import re

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import config, services

# --------------------------------------------------------------------------- #
# Peta tombol (selector) — bawaan sama dengan skrip bot sekolah.
# Dapat ditimpa dari halaman Bot Dapodik (pengaturan lanjutan, format JSON)
# bila Dapodik berubah versi, tanpa perlu mengubah kode.
# --------------------------------------------------------------------------- #
SELECTOR_BAWAAN: dict[str, str] = {
    "login_username": "/html/body/div[5]/div[2]/form/input",
    "login_password": "/html/body/div[5]/div[2]/form/div[1]/input",
    "login_tombol": '//*[@id="form2"]/button',
    "menu_tujuan": "/html/body/div[1]/ul/li[2]/div/a/button",
    "popup_tutup": "/html/body/div[11]/div[2]/div[2]/div/div/a[1]",
    "menu_1": '//*[@id="ext-element-76"]',
    "menu_2": '//*[@id="ext-element-66"]',
    "cari_nisn": "name:cari_text",
    "tombol_registrasi": '//span[contains(@class, "x-btn-inner-soft-green-small") '
                         'and normalize-space()="Registrasi"]',
    "input_nis": "name:nipd",
    "radio_ya": '//div[contains(@class, "x-form-cb-wrap-inner")]'
                '//label[normalize-space()="Ya"]/preceding-sibling::span/input',
    # Dapodik menamai kolom ini berbeda-beda antar versi, jadi dicari lewat labelnya
    # («Sekolah Asal») — lihat _cari_lewat_label. Bisa diganti di «Peta tombol Dapodik».
    "sekolah_asal": "label:Sekolah Asal",
    # --- Data Periodik: panel di halaman Peserta Didik, persis potongan skrip sekolah.
    #     Dijalankan SEBELUM tombol Registrasi ditekan. XPath kotak «Jarak rumah ke
    #     sekolah» diambil apa adanya dari skrip itu, dengan cadangan berbasis label
    #     supaya tetap jalan bila Dapodik mengubah tata letaknya.
    "periodik_tinggi": "name:tinggi_badan",
    "periodik_berat": "name:berat_badan",
    "periodik_lingkar": "name:lingkar_kepala",
    "periodik_saudara": "name:jumlah_saudara_kandung",
    # Baris «Jarak rumah ke sekolah» di Dapodik punya DUA pilihan:
    #   «kurang dari 1 km» (td/div[1]) dan «lebih dari 1 km» (td/div[2]).
    # XPath div[2] di bawah diambil apa adanya dari skrip sekolah (= lebih dari 1 km).
    # Bot memilih salah satunya sesuai kolom «Jarak Rumah ke Sekolah (KM)» milik siswa.
    "periodik_jarak_lebih": "/html/body/div[2]/div/div/div[2]/div/div/div/div[3]/div[2]/div/div/"
                            "div/div[1]/div/div/div[7]/div/div/table/tbody/tr/td/div[2]/div/div/"
                            "span/input",
    "periodik_jarak_kurang": "/html/body/div[2]/div/div/div[2]/div/div/div/div[3]/div[2]/div/div/"
                             "div/div[1]/div/div/div[7]/div/div/table/tbody/tr/td/div[1]/div/div/"
                             "span/input",
    # Dipakai bila pilihan yang sesuai tidak ada (bawaan = skrip sekolah: lebih dari 1 km).
    "periodik_jarak": "/html/body/div[2]/div/div/div[2]/div/div/div/div[3]/div[2]/div/div/div/"
                      "div[1]/div/div/div[7]/div/div/table/tbody/tr/td/div[2]/div/div/span/input",
    # Wadah/panel «Data Periodik Peserta Didik». Panel ini punya **area gulir sendiri**,
    # jadi `window.scrollBy` tidak menjangkaunya — bot membawa panelnya ke layar dengan
    # scrollIntoView (hanya panelnya yang bergeser, halaman lain tidak ikut).
    "periodik_panel": "/html/body/div[2]/div/div/div[2]/div/div/div/div[4]",
    # Kolom teks di sebelah kotak «Jarak rumah ke sekolah»: «Sebutkan (dalam kilometer):»
    # namanya ``jarak_rumah_ke_sekolah_km``. Isinya jarak (km) dari data siswa SM.
    "periodik_jarak_km": "name:jarak_rumah_ke_sekolah_km",
    # --- Jendela «Ubah» (BIO) pada halaman Peserta Didik — persis skrip sekolah.
    #     Tombol «Ubah» (ungu) dibuka SESUDAH baris siswa dipilih & SEBELUM Data Periodik;
    #     nama kolom di bawah diambil apa adanya dari skrip sekolah (By.NAME).
    "bio_ubah": '//span[contains(@class, "x-btn-inner-soft-purple-small") and '
                'normalize-space()="Ubah"]',
    "bio_jendela": "css:div.x-window",
    "bio_no_kk": "name:no_kk",
    "bio_reg_akta": "name:reg_akta_lahir",
    "bio_alamat": "name:alamat_jalan",
    "bio_rt": "name:rt",
    "bio_rw": "name:rw",
    "bio_kode_pos": "name:kode_pos",
    # Kolom «Desa/Kelurahan» bukan kolom biasa: satu kolom combo yang isinya
    # «Desa/Kel. <desa> - Kec. <kecamatan> - Kota <kota>» sekaligus, dan daftarnya diambil
    # Dapodik dari basis data setelah pengguna mengetik nama kecamatan. Nama kolomnya bisa
    # berbeda antar versi Dapodik, jadi dicari lewat labelnya lebih dulu (bisa ditimpa di
    # «Peta tombol Dapodik»).
    "bio_kelurahan": "label:Desa/Kelurahan",
    "bio_anak_ke": "name:anak_keberapa",
    "bio_ayah_nama": "name:nama_ayah",
    "bio_ayah_nik": "name:nik_ayah",
    "bio_ayah_tahun": "name:tahun_lahir_ayah",
    "bio_ayah_pendidikan": "name:jenjang_pendidikan_ayah",
    "bio_ibu_nik": "name:nik_ibu",
    "bio_ibu_tahun": "name:tahun_lahir_ibu",
    "bio_ibu_pendidikan": "name:jenjang_pendidikan_ibu",
    # Kolom dropdown (combo) — nama kolomnya diambil dari DOM asli halaman Dapodik sekolah
    # (ronde 17): «pekerjaan_id_ayah» & «penghasilan_id_ayah» (data-componentid
    # «pekerjaancombo-2560», role combobox, readonly). Bila di versi lain namanya berbeda,
    # kolomnya masih dicari lewat labelnya, dan kunci ini bisa ditimpa di «Peta tombol Dapodik».
    "bio_ayah_pekerjaan": "name:pekerjaan_id_ayah",
    "bio_ayah_penghasilan": "name:penghasilan_id_ayah",
    "bio_ibu_pekerjaan": "name:pekerjaan_id_ibu",
    "bio_ibu_penghasilan": "name:penghasilan_id_ibu",
    "bio_simpan": '//span[contains(@class, "x-btn-inner-default-small") and '
                  'normalize-space()="Simpan"]',
    "simpan_periodik": '//span[contains(@class, "x-btn-inner-default-small") '
                       'and contains(text(), "Simpan dan Tutup")]',
    "hobi": "name:id_hobby",
    "cita": "name:id_cita",
    "simpan": '//span[contains(@class, "x-btn-inner-default-small") '
              'and contains(normalize-space(), "Simpan dan Tutup")]',
}

#: Jarak gulir tiap langkah (px) — sama seperti skrip sekolah:
#: ``driver.execute_script("window.scrollBy(0, 250);")`` sebelum mengisi Data Periodik.
#: Panel «Data Periodik Peserta Didik» ada di bagian bawah halaman, jadi tanpa digulir
#: kolom-kolomnya bisa tidak terjangkau/tertimpa bagian lain halaman.
GULIR_PERIODIK = 250

#: Berapa kali gulir tambahan dicoba bila kolom yang dicari belum ketemu.
GULIR_PERCOBAAN = 4

#: Penanda kelas baris tabel Ext JS tempat hasil pencarian muncul.
BARIS_TABEL = 'x-grid-row'

#: Jendela popup Dapodik yang harus ditutup sebelum langkah berikutnya. Dapodik
#: menampilkan pengumuman versi ("Selamat Datang di Aplikasi Dapodik 2027.b") sebagai
#: jendela Ext JS; selama jendela itu (beserta lapisan modalnya) tampil, semua klik di
#: luarnya diabaikan aplikasi — persis penyebab kegagalan "input_nis tidak ditemukan".
XPATH_POPUP: tuple[str, ...] = (
    '//div[contains(@class, "x-window") or contains(@class, "x-message-box")]'
    '[contains(., "Selamat Datang") or contains(., "Jangan Tampilkan") '
    'or contains(., "Riwayat Versi")]',
    '//div[contains(@class, "x-window") or contains(@class, "x-message-box")]'
    '[.//*[self::a or self::span or self::button][normalize-space()="Tutup"]]',
)

#: Nama kunci yang boleh ditimpa lewat pengaturan (agar salah ketik terdeteksi).
SELECTOR_DIIZINKAN = tuple(SELECTOR_BAWAAN)

#: Selector cadangan yang dicoba bila selector bawaan tidak menemukan elemen.
#: Penting karena Dapodik sering diperbarui: XPath absolut dan id ``ext-element-*``
#: berubah setiap versi, sedangkan pencarian berbasis teks jauh lebih tahan lama.
SELECTOR_CADANGAN: dict[str, list[str]] = {
    "login_username": [
        "css:input[name=username]",
        "css:input[name=user]",
        "css:input[name=email]",
        "css:input[type=text]",
    ],
    "login_password": [
        "css:input[name=password]",
        "css:input[name=sandi]",
        "css:input[type=password]",
    ],
    "login_tombol": [
        "xpath://button[contains(normalize-space(), 'Masuk') or contains(normalize-space(), 'Login')]",
        "css:button[type=submit]",
        "css:form button",
    ],
    "menu_tujuan": [
        "xpath://*[self::a or self::button or self::li][contains(normalize-space(), 'Peserta Didik')]",
    ],
    "popup_tutup": [
        'xpath://*[self::a or self::span or self::button][normalize-space()="Tutup"]',
        "css:div.x-window a.x-tool-close",
        "css:div.x-window .x-tool-close",
        "css:a.x-tool-close",
    ],
    "menu_1": [
        "xpath://*[self::a or self::span or self::li][contains(normalize-space(), 'Pendaftaran')]",
        "xpath://*[self::a or self::span or self::li][contains(normalize-space(), 'Registrasi')]",
    ],
    "menu_2": [
        "xpath://*[self::a or self::span or self::li][contains(normalize-space(), 'Peserta Didik')]",
    ],
    "cari_nisn": [
        "css:input[name*=cari]",
        "css:input[name*=search]",
        "css:input[name*=nisn]",
    ],
    "tombol_registrasi": [
        "xpath://*[self::span or self::a or self::button][contains(normalize-space(), 'Registrasi')]",
        "xpath://*[self::span or self::a or self::button][contains(normalize-space(), 'Daftar')]",
    ],
    "input_nis": [
        "css:input[name*=nipd]",
        "css:input[name*=nis]",
    ],
    "radio_ya": [
        'xpath://*[normalize-space()="Ya"]/preceding::input[@type="radio"][1]',
    ],
    "sekolah_asal": [
        "css:input[name*=sekolah_asal]",
        "css:input[name*=sekolahasal]",
        "css:input[name*=asal]",
    ],
    "periodik_panel": [
        'xpath://div[contains(@class, "x-panel") or contains(@class, "x-container")]'
        '[.//*[contains(normalize-space(), "Data Periodik")]][1]',
        'xpath://*[contains(normalize-space(), "Data Periodik Peserta Didik")]'
        '/ancestor::div[contains(@class, "x-panel") or contains(@class, "x-container")][1]',
    ],
    "periodik_tinggi": [
        "label:Tinggi Badan",
        "css:input[name*=tinggi]",
    ],
    "periodik_berat": [
        "label:Berat Badan",
        "css:input[name*=berat]",
    ],
    "periodik_lingkar": [
        "label:Lingkar Kepala",
        "css:input[name*=lingkar]",
    ],
    "periodik_saudara": [
        "label:Jumlah Saudara Kandung",
        "css:input[name*=saudara]",
    ],
    # Struktur DOM Dapodik (Ext JS modern) yang sebenarnya, dari sekolah:
    #   <div class="x-field x-form-type-radio" id="radiofield-1112">
    #     <div class="x-form-cb-wrap-inner">
    #       <span class="x-form-cb"><input type="radio" name="jarak_rumah_ke_sekolah"
    #                                      data-componentid="radiofield-1112"></span>
    #       <label class="x-form-cb-label" for="radiofield-1112-inputEl">lebih dari 1 km</label>
    # Labelnya berada SESUDAH input, dan yang tercentang ditandai kelas `x-form-cb-checked`
    # pada pembungkusnya. Karena itu kotaknya dilacak dari labelnya lewat wadah `.x-field`
    # atau poros `preceding::` — bukan `following::` yang justru menunjuk radio berikutnya.
    "periodik_jarak_lebih": [
        'xpath://label[contains(translate(normalize-space(.), "KM", "km"), "lebih dari 1")]'
        '/ancestor::div[contains(@class, "x-field")][1]//input[@type="radio" or '
        '@type="checkbox"][1]',
        'xpath://label[contains(translate(normalize-space(.), "KM", "km"), "lebih dari 1")]'
        '/preceding::input[@type="radio"][1]',
    ],
    "periodik_jarak_kurang": [
        'xpath://label[contains(translate(normalize-space(.), "KM", "km"), "kurang dari 1")]'
        '/ancestor::div[contains(@class, "x-field")][1]//input[@type="radio" or '
        '@type="checkbox"][1]',
        'xpath://label[contains(translate(normalize-space(.), "KM", "km"), "kurang dari 1")]'
        '/preceding::input[@type="radio"][1]',
    ],
    # Jendela «Ubah» (BIO): tombol ungu bisa berubah kelasnya antar versi Dapodik — teks
    # «Ubah» pada tombolnya yang paling tetap. Kolomnya dicari lewat nama (persis skrip
    # sekolah), dengan cadangan lewat labelnya untuk kolom yang labelnya khas.
    "bio_ubah": [
        'xpath://*[self::span or self::a or self::button][normalize-space()="Ubah"]',
        'xpath://span[contains(@class, "x-btn-inner-soft-purple-small")]',
    ],
    #: Kolom-kolom di atas dicari lewat **nama kolomnya lebih dulu** (persis
    #: ``find_element(By.NAME, …)`` skrip sekolah yang terbukti berhasil), baru lewat
    #: labelnya. Sebabnya dari laporan ronde 47: yang gagal diisi justru kolom-kolom yang
    #: HANYA punya jalur label (RT, RW, alamat, No. KK, kode pos) — di versi Dapodik sekolah
    #: labelnya tidak digambar sebagai elemen ``<label>``.
    "bio_no_kk": ["name:no_kk", "label:No. Kartu Keluarga", "css:input[name*=no_kk]"],
    "bio_reg_akta": ["name:reg_akta_lahir", "name:no_registrasi_akta_lahir",
                     "label:No. Registrasi Akta Lahir", "css:input[name*=akta]"],
    "bio_alamat": ["name:alamat_jalan", "label:Alamat (Jalan)", "label:Alamat",
                   "css:input[name*=alamat_jalan]", "css:input[name*=alamat]"],
    "bio_rt": ["name:rt", "label:RT", "css:input[name=rt]"],
    "bio_rw": ["name:rw", "label:RW", "css:input[name=rw]"],
    "bio_kode_pos": ["name:kode_pos", "label:Kode Pos", "css:input[name*=kode_pos]"],
    #: Kolom combo «Desa/Kelurahan». Dapodik menyimpan **kode wilayah**-nya (mis.
    #: ``kode_wilayah``/``kode_wilayah_str``), sedangkan teks di kotaknya hanya tampilan.
    #: Di sebagian versi Dapodik (laporan sekolah ronde 47) kolom itu **tidak terjangkau
    #: lewat name maupun label** — karena itu kandidat terakhirnya adalah **XPath lengkap
    #: yang dikirim sekolah**, dan unsur yang didapat dari kandidat itu wajib diperiksa
    #: dulu bahwa ia memang kolom combo (jangan sampai nilai desa ditulis ke kolom lain).
    "bio_kelurahan": ["label:Desa/Kelurahan", "label:Desa", "label:Kelurahan",
                      "name:kode_wilayah", "css:input[name=kode_wilayah]",
                      "css:input[name*=kelurahan]", "css:input[name*=desa]",
                      "css:input[name*=wilayah]",
                      "xpath:/html/body/div[10]/div[2]/div/div[1]/div/div[1]/div/div"
                      "/fieldset[1]/div/div/div/div[18]/div/div/div[1]/input"],
    "bio_anak_ke": ["label:Anak ke-berapa", "label:Anak ke", "css:input[name*=anak]"],
    "bio_ayah_nama": ["css:input[name*=nama_ayah]"],
    "bio_ayah_nik": ["css:input[name*=nik_ayah]"],
    "bio_ayah_tahun": ["css:input[name*=tahun_lahir_ayah]"],
    "bio_ayah_pendidikan": ["name:jenjang_pendidikan_ayah", "label:Pendidikan ayah",
                            "css:input[name*=pendidikan][name*=ayah]"],
    "bio_ibu_nik": ["css:input[name*=nik_ibu]"],
    "bio_ibu_tahun": ["css:input[name*=tahun_lahir_ibu]"],
    "bio_ibu_pendidikan": ["name:jenjang_pendidikan_ibu", "label:Pendidikan ibu",
                           "css:input[name*=pendidikan][name*=ibu]"],
    # Kolom dropdown (combo Ext JS). Nama aslinya dari DOM sekolah: «pekerjaan_id_ayah»,
    # «penghasilan_id_ayah» (dan pasangan ibu). Versi Dapodik lain bisa menamainya tanpa
    # «_id_» atau dibalik («pekerjaan_ayah», «ayah_pekerjaan») — semuanya dicoba, lalu lewat
    # labelnya; nama apa pun yang mengandung «pekerjaan»+«ayah» juga cocok.
    "bio_ayah_pekerjaan": ["name:pekerjaan_id_ayah", "label:Pekerjaan ayah",
                           "css:input[name*=pekerjaan][name*=ayah]"],
    "bio_ayah_penghasilan": ["name:penghasilan_id_ayah", "label:Penghasilan ayah",
                             "css:input[name*=penghasilan][name*=ayah]"],
    "bio_ibu_pekerjaan": ["name:pekerjaan_id_ibu", "label:Pekerjaan ibu",
                          "css:input[name*=pekerjaan][name*=ibu]"],
    "bio_ibu_penghasilan": ["name:penghasilan_id_ibu", "label:Penghasilan ibu",
                            "css:input[name*=penghasilan][name*=ibu]"],
    "bio_simpan": [
        'xpath://span[contains(@class, "x-btn-inner") and normalize-space()="Simpan"]',
        'xpath://*[self::a or self::button][normalize-space()="Simpan"]',
    ],
    "periodik_jarak": [
        "css:input[type=radio][name=jarak_rumah_ke_sekolah]",   # nama kolom pada DOM sekolah
        "css:input[type=radio][name*=jarak]",
        'xpath://*[contains(normalize-space(), "Jarak rumah ke sekolah")]'
        '/ancestor::div[contains(@class, "x-field")][1]//input[@type="radio" or '
        '@type="checkbox"][1]',
        "css:input[type=checkbox][name*=jarak]",
    ],
    "periodik_jarak_km": [
        "label:Sebutkan",                       # labelnya «Sebutkan (dalam kilometer):»
        "css:input[name=jarak_rumah_ke_sekolah_km]",
        "css:input[name*=sekolah_km]",
        "css:input[type=text][name*=jarak]",
    ],
    "simpan_periodik": [
        'xpath://span[contains(@class, "x-btn-inner-default-small") '
        'and contains(normalize-space(), "Simpan dan Tutup")]',
        'xpath://span[contains(@class, "x-btn-inner-default-small") '
        'and normalize-space()="Simpan"]',
    ],
    "hobi": [
        "css:input[name*=hobby]",
        "css:input[name*=hobi]",
        "css:select[name*=hobby]",
    ],
    "cita": [
        "css:input[name*=cita]",
        "css:select[name*=cita]",
    ],
    "simpan": [
        "xpath://*[self::span or self::a or self::button][contains(normalize-space(), 'Simpan dan Tutup')]",
        "xpath://*[self::span or self::a or self::button][contains(normalize-space(), 'Simpan')]",
    ],
}

#: Batas waktu singkat untuk menguji satu kandidat selector (detik).
SELEKTOR_UJI_DETIK = 6

#: Batas waktu menunggu daftar pilihan (Hobi/Cita-cita) muncul pada combo box Ext JS.
PILIHAN_TUNGGU_DETIK = 4

#: Berapa lama menunggu lapisan pemuatan Ext JS (``div.x-mask``) hilang sebelum
#: mengisi kolom / menekan tombol (skrip asli sekolah menunggu hal yang sama).
LAPISAN_TUNGGU_DETIK = 10

#: Batas waktu pemeriksaan selector pada laporan «Uji koneksi Dapodik» (detik).
UJI_TUNGGU_PERTAMA = 4
UJI_TUNGGU_LAIN = 2

#: Batas jumlah berkas bukti (screenshot/HTML) yang disimpan agar tidak menumpuk.
BUKTI_MAKSIMAL = 40

#: Batas waktu menunggu daftar hasil pencarian combo «Desa/Kelurahan» (detik).
#: Dapodik tidak menyimpan daftar desa di komponen combo-nya: daftarnya baru diambil dari
#: basis data **sesudah** pengguna mengetik (di Dapodik terbaru: nama KECAMATAN dulu, lalu
#: pilihan desa di bawah kecamatan itu muncul). Jadi daftarnya harus ditunggu seperti daftar
#: dropdown lain — bukan dibaca sekali lalu disimpulkan kosong.
#:
#: Ronde 51 (catatan sekolah 29 Sep 2026): «untuk value tersebut memang harus menunggu agak
#: lama biar valuenya muncul» — di PC sekolah daftar/nilai desa kadang baru muncul sesudah
#: lebih dari 6 detik, dan nilainya (termasuk ``kode_wilayah_str``) tidak selalu terisi tepat
#: sesudah pilihan diklik. Batasnya dinaikkan dan dipakai untuk DUA penantian: daftarnya
#: maupun nilai pilihannya (lihat ``_batas_tunggu_desa``).
DESA_TUNGGU_DETIK = 12.0

#: Paling banyak berapa halaman daftar desa yang disusuri.
#: Picker combo Dapodik memakai bilah halaman («Page 1 of 2» pada tangkapan layar sekolah):
#: pilihan yang berada di halaman berikutnya tidak akan pernah terlihat — dan karena itu
#: tidak bisa diklik — sebelum tombol halaman berikutnya ditekan.
DESA_HALAMAN_MAKSIMAL = 12

#: Jaring pengaman: berhenti menyusuri daftar sesudah sekian pilihan desa terkumpul.
DESA_PILIHAN_MAKSIMAL = 400

# --------------------------------------------------------------------------- #
# Alat bersama untuk mengenali kolom Dapodik (ronde 49).
#
# Pelajaran dari log sekolah («bio-tidak-terisi», 29 Sep 2026): bot mengira **hampir semua**
# kolom jendela «Ubah» adalah dropdown, lalu melewatinya — termasuk RT & RW. Penyebabnya satu
# asumsi yang salah: kolom dianggap dropdown bila **wadah lebar** di atasnya memuat unsur
# ``x-form-trigger``. Wadah itu ternyata memuat kolom TETANGGA (Dapodik menyusun dua kolom per
# baris), dan ``x-form-trigger`` juga dipakai tombol putar **numberfield** — jadi kolom angka
# seperti RT/RW/KK/NIK ikut dikira dropdown, dan bot melaporkannya
# «daftar dropdown TIDAK terbaca … dilewati».
#
# Aturannya sekarang:
#   1. **Bidang kolom** = wadah terdekat yang hanya memuat satu kolom isian (naik dari unsur
#      itu sendiri) — bukan wadah lebar yang berisi kolom tetangga.
#   2. Yang menandai dropdown hanyalah **panah** dropdown (``…arrow…``), ``role=combobox``/
#      ``aria-owns``, atau **komponen Ext JS-nya sendiri** (combo/ber-store) — dan komponen itu
#      wajib **memuat unsur yang sedang diperiksa** (``dom.contains(el)``); kalau tidak, ia
#      komponen milik kolom lain (di sekolah: kolom «Tahun lahir ayah» terbaca memakai daftar
#      «Pendidikan ayah» gara-gara id-nya meleset).
#   3. Tombol putar (spinner) numberfield **bukan** dropdown, dan ``readonly`` sendirian
#      **bukan** alasan menyebut sebuah kolom dropdown (combo Dapodik memang readonly).
# --------------------------------------------------------------------------- #
JS_ALAT = r"""
/* ---- alat ronde 49: bidang kolom + komponen Ext JS (dipakai banyak skrip bot) ---- */
const bidangKolom = (el) => {
    let p = el ? el.parentElement : null;
    while (p) {
        const isian = p.querySelectorAll('input:not([type=hidden]), textarea, select');
        if (isian.length <= 1) return p;
        const naik = p.parentElement;
        if (!naik || naik === document.body || naik === document.documentElement) return p;
        p = naik;
    }
    return el ? el.parentElement : null;
};
const panahKolom = (el) => {
    const b = bidangKolom(el);
    if (!b || !b.querySelectorAll) return null;
    const kandidat = b.querySelectorAll(
        '.x-form-arrow-trigger, .x-form-trigger-arrow, [class*="arrow-trigger"],' +
        ' .x-form-trigger[class*="arrow"], img.x-form-trigger[src*="arrow"]');
    return kandidat.length ? kandidat[kandidat.length - 1] : null;
};
const putarKolom = (el) => {
    const b = bidangKolom(el);
    if (!b || !b.querySelectorAll) return 0;
    return b.querySelectorAll('[class*="spinner"], .x-form-trigger-up, .x-form-trigger-down')
        .length;
};
const komponenKolom = (el) => {
    if (!el || typeof Ext === 'undefined' || !Ext.getCmp) return null;
    const id = String((el.getAttribute && (el.getAttribute('data-componentid') || el.id)) || '');
    const kandidat = [];
    if (id) {
        kandidat.push(id);
        const bersih = id.replace(/-inputEl$/, '');
        kandidat.push(bersih);
        kandidat.push(bersih.replace(/-(trigger|picker|bodyEl|listEl|aria).*$/, ''));
    }
    for (const k of kandidat) {
        if (!k) continue;
        let c = null;
        try { c = Ext.getCmp(k); } catch (e) { c = null; }
        if (!c) continue;
        if (c.inputEl && c.inputEl.dom === el) return c;
        const dom = (c.el && c.el.dom) || (c.inputEl && c.inputEl.dom) || null;
        if (dom && (dom === el || dom.contains(el))) return c;
    }
    try {
        const nama = el.getAttribute && el.getAttribute('name');
        if (nama && Ext.ComponentQuery && Ext.ComponentQuery.query) {
            for (const c of Ext.ComponentQuery.query('[name="' + nama + '"]')) {
                const dom = (c.el && c.el.dom) || null;
                if (dom && dom.contains(el)) return c;
            }
        }
    } catch (e) { /* tanpa ComponentQuery: cukup jalur di atas */ }
    return null;
};
const xtypeKolom = (c) => (c && c.getXType) ? String(c.getXType() || '') : '';
const jumlahStore = (c) => {
    if (!c || !c.getStore) return -1;
    try {
        const s = c.getStore();
        if (!s || !s.getCount) return -1;
        return s.getCount();
    } catch (e) { return -1; }
};
const komboKolom = (c) => /combo|picklist|tag|multiselect/i.test(xtypeKolom(c))
    || jumlahStore(c) > 0;
"""


def peta_selector() -> dict[str, str]:
    """Gabungkan selector bawaan dengan penimpaan dari pengaturan bot."""
    peta = dict(SELECTOR_BAWAAN)
    mentah = (services.bot_setting().get("bot_selector_json") or "").strip()
    if not mentah:
        return peta
    try:
        ubah = json.loads(mentah)
    except json.JSONDecodeError:
        return peta
    if isinstance(ubah, dict):
        for kunci, nilai in ubah.items():
            if kunci in peta and str(nilai).strip():
                peta[str(kunci)] = str(nilai).strip()
    return peta


def _pesan_galat_selector(mentah: str) -> str:
    """Periksa JSON selector sebelum disimpan (pesan jelas bila salah)."""
    if not (mentah or "").strip():
        return ""
    try:
        ubah = json.loads(mentah)
    except json.JSONDecodeError as exc:
        return f"Peta selector bukan JSON yang sah: {exc.msg} (baris {exc.lineno})."
    if not isinstance(ubah, dict):
        return "Peta selector harus berupa objek JSON, mis. {\"cari_nisn\": \"name:cari_text\"}."
    asing = [kunci for kunci in ubah if kunci not in SELECTOR_DIIZINKAN]
    if asing:
        return ("Nama selector tidak dikenal: " + ", ".join(sorted(asing)) +
                ". Yang boleh: " + ", ".join(SELECTOR_DIIZINKAN) + ".")
    return ""


# --------------------------------------------------------------------------- #
# Penjalan bot (satu pekerjaan sekaligus)
# --------------------------------------------------------------------------- #
class BotBerjalanError(RuntimeError):
    """Dilempar bila bot sudah berjalan atau pengaturannya belum siap."""


class BotDapodik:
    """Satu pekerjaan bot: antrean siswa dijalankan berurutan sampai selesai/dihentikan."""

    def __init__(self, job_id: int, antrean: list[dict[str, Any]], item_ids: list[int],
                 opsi: dict[str, str], kepala: Callable[[str], None] | None = None) -> None:
        self.job_id = job_id
        self.antrean = antrean
        self.item_ids = item_ids
        self.opsi = opsi
        self._kepala = kepala or (lambda baris: None)
        self._stop = threading.Event()
        self._benang: threading.Thread | None = None
        self.mulai_pada = 0.0
        self.selesai_pada = 0.0
        self.diproses = 0
        self.sedang: dict[str, Any] | None = None
        self.peramban_tampak = opsi.get("bot_headless", "1") != "1"
        #: True bila lapisan pemuatan Dapodik pernah tidak hilang — penantian berikutnya
        #: dipersingkat supaya pekerjaan tidak lambat, langkah tetap memakai cara paksa.
        self._lapisan_lengket = False
        #: Berapa kali kursor dipindahkan keluar dari kolom isian sebelum menggulir
        #: (ronde 45: menggulir selagi kursor di dalam kolom bisa mengubah nilainya).
        self.kursor_dipindah = 0
        #: Nilai kolom BIO yang sudah ditulis bot → diperiksa lagi setiap kali menggulir.
        self._penjaga_nilai: dict[str, str] = {}
        #: Ronde 50 — cara perbaikan yang sudah dicoba untuk kolom yang ditolak Dapodik
        #: (``{"inputItem": {"kosongkan"}}``): kolom yang sama tidak dikosongkan berulang kali,
        #: dan bot tahu kapan harus mencoba mengisinya dari data siswa.
        self._bio_perbaikan_cara: dict[str, set[str]] = {}
        #: Unsurnya sendiri per kolom — dipakai saat memperbaiki/membaca ulang nilainya
        #: (jangan bergantung pada unsur pertama yang namanya sama di seluruh halaman).
        self._penjaga_unsur: dict[str, Any] = {}
        #: Berapa kali nilai MODEL Ext JS sebuah kolom angka diperiksa (``getValue()``).
        self.model_diperiksa = 0
        #: Berapa kali nilai model itu harus ditulis ulang supaya Dapodik menyimpan angka
        #: yang benar (kotaknya sudah benar, modelnya masih «0» — ronde 48).
        self.model_diperbaiki = 0
        #: Berapa kali nilai model tidak terbaca (Ext JS tidak tersedia) — bot tidak mengaku.
        self.model_tak_terbaca = 0
        #: Berapa kali penjaga nilai menemukan nilai kolom yang berubah & mengembalikannya.
        self.penjaga_dipulihkan = 0
        #: Keadaan desa/kelurahan yang sudah terverifikasi — diperiksa lagi sebelum «Simpan»,
        #: karena nilainya bisa berubah lagi sesudah dipilih (mis. tergulir di jendela «Ubah»).
        self._desa_terverifikasi: dict[str, Any] | None = None
        #: Berapa kali pilihan desa dipasang ulang tepat sebelum «Simpan».
        self.desa_dipulihkan_kali = 0
        self.simulasi = opsi.get("bot_simulasi", "0") == "1"

    # ---------------------------------------------------------------- jalan ---
    def jalankan(self) -> None:
        self._benang = threading.Thread(target=self._kerja, name=f"bot-dapodik-{self.job_id}",
                                        daemon=True)
        self._benang.start()

    def hentikan(self) -> None:
        self._stop.set()

    def berjalan(self) -> bool:
        return bool(self._benang and self._benang.is_alive())

    # ------------------------------------------------------------ keadaan --- #
    def kemajuan(self) -> dict[str, Any]:
        detik = max(0.001, (self.selesai_pada or time.time()) - self.mulai_pada)
        kecepatan = self.diproses / detik * 60 if self.diproses else 0.0
        sisa = max(0, len(self.antrean) - self.diproses)
        perkiraan = int(sisa / kecepatan * 60) if kecepatan > 0 else 0
        return {
            "job_id": self.job_id,
            "berjalan": self.berjalan(),
            "simulasi": self.simulasi,
            "tampak": self.peramban_tampak,
            "total": len(self.antrean),
            "diproses": self.diproses,
            "sedang": (self.sedang or {}).get("nama"),
            "sedang_nisn": (self.sedang or {}).get("nisn"),
            "kecepatan": round(kecepatan, 1),
            "perkiraan_detik": perkiraan,
            "dihentikan": self._stop.is_set(),
        }

    # ---------------------------------------------------------------- kerja ---
    def _kerja(self) -> None:
        self.mulai_pada = time.time()
        self._catat_kepala(f"Mulai {len(self.antrean)} siswa "
                           f"({'uji coba' if self.simulasi else 'headless' if not self.peramban_tampak else 'jendela tampak'}).")
        peramban = None
        galat_fatal = ""
        try:
            if not self.simulasi:
                peramban = self._buka_peramban()
                self._login(peramban)
            for posisi, siswa in enumerate(self.antrean):
                if self._stop.is_set():
                    break
                self._proses_satu(peramban, siswa, self.item_ids[posisi] if posisi < len(self.item_ids) else None)
                self.diproses += 1
                jeda = float(self.opsi.get("bot_jeda", "1") or 1)
                if jeda and not self.simulasi:
                    time.sleep(jeda)
        except Exception as exc:  # noqa: BLE001 — apa pun harus tercatat & peramban ditutup
            galat_fatal = f"{type(exc).__name__}: {str(exc)[:300]}"
            services.perbarui_job_bot(self.job_id, status="gagal", baris_log=f"[FATAL] {galat_fatal}")
            self._kepala(f"[FATAL] {galat_fatal}")
        finally:
            self.selesai_pada = time.time()
            if peramban is not None:
                try:
                    peramban.quit()
                except Exception:  # noqa: BLE001
                    pass
            if galat_fatal or self._stop.is_set():
                sisa = services.tandai_sisa_menunggu_bot(
                    self.job_id, "Pekerjaan gagal/dihentikan sebelum siswa ini diproses")
                if sisa:
                    self._catat_kepala(
                        f"{sisa} siswa belum diproses (akan diulang pada pekerjaan berikutnya).")
            if not galat_fatal:
                if self._stop.is_set():
                    services.perbarui_job_bot(self.job_id, status="batal",
                                              baris_log="Dihentikan oleh petugas.")
                else:
                    services.perbarui_job_bot(self.job_id, status="sukses",
                                              baris_log="Pekerjaan selesai.")
            _lupakan(self)

    def _catat_kepala(self, baris: str) -> None:
        services.perbarui_job_bot(self.job_id, baris_log=baris)
        self._kepala(baris)

    # ------------------------------------------------------------- peramban ---
    def _buka_peramban(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:  # noqa: BLE001 — pustaka belum terpasang
            raise RuntimeError(
                "Pustaka selenium belum terpasang pada Python aplikasi ini. Buka halaman "
                "Bot Dapodik lalu tekan «Pasang pustaka bot».") from exc

        opsi = Options()
        opsi.add_experimental_option("prefs", {
            "profile.password_manager_leak_detection": False,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        })
        if self.opsi.get("bot_headless", "1") == "1":
            # --headless=new: Chrome modern berjalan tanpa jendela, tetap bisa
            # menyimpan sesi & menjalankan JavaScript Ext JS.
            opsi.add_argument("--headless=new")
            opsi.add_argument("--disable-gpu")
            opsi.add_argument("--window-size=1600,1000")
        else:
            opsi.add_argument("--start-maximized")
        opsi.add_argument("--log-level=3")
        try:
            peramban = webdriver.Chrome(options=opsi)
            # Ukuran jendela ikut ditulis pada log: tata letak Ext JS Dapodik (dan baris
            # «Jarak rumah ke sekolah») bisa berbeda pada jendela yang sempit, sehingga
            # keterangan ini penting saat memeriksa kegagalan dari jarak jauh.
            try:
                peramban.set_window_size(1600, 1000)
                ukuran = peramban.get_window_size()
                pandangan = peramban.execute_script(
                    "return window.innerWidth + 'x' + window.innerHeight;")
                self._catat_kepala(f"[layar] jendela Chrome {ukuran.get('width')}x"
                                   f"{ukuran.get('height')} · area tampil {pandangan}")
            except Exception:  # noqa: BLE001 — keterangan tambahan saja
                pass
            # Dapodik dimuat lambat pada PC sekolah: beri waktu halaman selesai.
            peramban.set_page_load_timeout(max(60.0, float(self.opsi.get("bot_timeout", "15") or 15)))
            return peramban
        except Exception as exc:  # noqa: BLE001 — beri pesan yang bisa ditindaklanjuti
            raise RuntimeError(
                "Google Chrome tidak dapat dibuka. Pastikan Chrome sudah terpasang di PC ini; "
                "bila muncul keluhan driver, sambungkan internet sekali agar Selenium mengunduh "
                f"drivernya otomatis. Rincian: {type(exc).__name__}: {str(exc)[:200]}") from exc

    def _tunggu(self, peramban, detik: float) -> None:
        time.sleep(detik)

    # -------------------------------------------------- tunggu & kenali halaman --- #
    def _tunggu_halaman(self, peramban) -> None:
        """Tunggu halaman benar-benar selesai dimuat, lalu beri jeda tambahan.

        Dapodik memakai Ext JS: DOM baru lengkap beberapa detik sesudah
        ``document.readyState`` selesai. Skrip bot sekolah memakai jeda 15 detik;
        di sini jeda dapat diatur lewat pengaturan ``bot_jeda_muat``.
        """
        batas = float(self.opsi.get("bot_timeout", "15") or 15)
        try:
            from selenium.webdriver.support.ui import WebDriverWait

            WebDriverWait(peramban, batas).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:  # noqa: BLE001 — tetap lanjut, jeda di bawah jadi penyelamat
            pass
        time.sleep(float(self.opsi.get("bot_jeda_muat", "8") or 8))

    def _galat_halaman(self, peramban) -> str:
        """Pesan bantuan bila halaman yang terbuka ternyata halaman galat Chrome."""
        try:
            judul = (peramban.title or "").strip()
            sumber = (peramban.page_source or "")[:4000]
        except Exception:  # noqa: BLE001
            return ""
        tanda = ("ERR_CONNECTION_REFUSED", "ERR_CONNECTION_RESET", "ERR_NAME_NOT_RESOLVED",
                 "ERR_CONNECTION_TIMED_OUT", "ERR_ADDRESS_UNREACHABLE", "ERR_EMPTY_RESPONSE")
        if any(kode in sumber for kode in tanda):
            kode = next(kode for kode in tanda if kode in sumber)
            return (f"Halaman Dapodik tidak dapat dibuka ({kode}). Pastikan aplikasi Dapodik "
                    f"sedang berjalan di PC ini dan alamatnya benar ({self.opsi.get('bot_url', '')}).")
        if "can't be reached" in judul.lower() or "tidak dapat dijangkau" in judul.lower() \
                or "tidak dapat diakses" in judul.lower():
            return (f"Halaman Dapodik tidak dapat dijangkau dari peramban. Periksa apakah aplikasi "
                    f"Dapodik sedang berjalan dan alamat {self.opsi.get('bot_url', '')} sudah benar.")
        return ""

    def _ringkas_halaman(self, peramban) -> dict[str, Any]:
        """Apa yang terlihat pada halaman saat ini (untuk pesan galat & alat uji)."""
        from selenium.webdriver.common.by import By

        def kumpul_teks(css: str, batas: int = 10) -> list[str]:
            hasil: list[str] = []
            try:
                elemen = peramban.find_elements(By.CSS_SELECTOR, css)
            except Exception:  # noqa: BLE001
                return hasil
            for el in elemen:
                try:
                    if not el.is_displayed():
                        continue
                    teks = " ".join((el.text or el.get_attribute("value") or "").split())
                except Exception:  # noqa: BLE001
                    continue
                if teks:
                    hasil.append(teks[:45])
                if len(hasil) >= batas:
                    break
            return hasil

        ringkas: dict[str, Any] = {"judul": "", "url": "", "galat_halaman": ""}
        try:
            ringkas["judul"] = (peramban.title or "").strip()[:120]
            ringkas["url"] = (peramban.current_url or "").strip()[:200]
            ringkas["galat_halaman"] = self._galat_halaman(peramban)
            ringkas["isian_teks"] = kumpul_teks("input[type=text], input[type=email], input:not([type])")
            ringkas["isian_sandi"] = len(peramban.find_elements(By.CSS_SELECTOR, "input[type=password]"))
            ringkas["tombol"] = kumpul_teks("button, input[type=submit], a.x-btn")
            ringkas["menu"] = kumpul_teks("ul li a, ul li button, .x-menu-item-text")
            ringkas["judul_kotak"] = kumpul_teks(".x-window-header-text, .x-panel-header-text, h1, h2")
        except Exception as exc:  # noqa: BLE001
            ringkas["galat_ringkas"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        return ringkas

    def _bukti(self, peramban, label: str) -> str:
        """Simpan tangkapan layar + HTML halaman sebagai bukti pemeriksaan ('' bila gagal)."""
        stempel = time.strftime("%Y%m%d-%H%M%S")
        aman = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]
        folder = config.DATA_DIR / "bot"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            gambar = folder / f"{aman}-{stempel}.png"
            halaman = folder / f"{aman}-{stempel}.html"
            peramban.save_screenshot(str(gambar))
            halaman.write_text(peramban.page_source or "", encoding="utf-8", errors="replace")
            self._bersihkan_bukti(folder)
            return str(gambar)
        except Exception:  # noqa: BLE001 — bukti hanya alat bantu
            return ""

    @staticmethod
    def _bersihkan_bukti(folder: Path) -> None:
        """Sisakan sejumlah berkas bukti terbaru saja."""
        try:
            berkas = sorted(folder.glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
            for usang in berkas[BUKTI_MAKSIMAL:]:
                usang.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    def _tunggu_lapisan(self, peramban, detik: float | None = None) -> bool:
        """Tunggu lapisan pemuatan Ext JS (``div.x-mask``) hilang.

        Skrip asli sekolah selalu menunggu ini sebelum mengisi/menekan tombol. Pada
        beberapa versi Dapodik lapisan itu menutupi formulir login sehingga klik
        biasa tertelan. Kembalikan ``True`` bila layar sudah bersih.
        """
        batas = float(detik if detik is not None else LAPISAN_TUNGGU_DETIK)
        mulai = time.time()
        while True:
            try:
                sisa = int(peramban.execute_script(
                    """
                    const tampak = (el) => {
                        const kotak = el.getBoundingClientRect();
                        const gaya = window.getComputedStyle(el);
                        return kotak.width > 1 && kotak.height > 1 &&
                               gaya.display !== 'none' && gaya.visibility !== 'hidden';
                    };
                    return [...document.querySelectorAll(
                        'div.x-mask, .loading-mask, #loading')].filter(tampak).length;
                    """) or 0)
            except Exception:  # noqa: BLE001 — tidak bisa diperiksa: anggap bersih
                return True
            if sisa <= 0:
                return True
            if time.time() - mulai >= batas:
                return False
            time.sleep(0.4)

    def _lapisan_hilang(self, peramban, batas: float | None = None) -> bool:
        """Apakah lapisan pemuatan sudah hilang (penantian menyesuaikan keadaan sebelumnya)."""
        if batas is None:
            batas = 1.0 if self._lapisan_lengket else LAPISAN_TUNGGU_DETIK
        return self._tunggu_lapisan(peramban, batas)

    def _siap_melanjutkan(self, peramban, label: str = "") -> bool:
        """Tunggu Dapodik selesai memuat sebelum langkah berikutnya (tidak pernah melempar).

        Sama seperti ``wait_for_loading_to_finish()`` pada skrip sekolah, tetapi bila
        lapisan pemuatan tetap ada, pekerjaan diteruskan dengan catatan — langkah
        berikutnya akan memakai cara paksa/skrip.

        Popup pengumuman Dapodik (mis. "Selamat Datang di Aplikasi Dapodik 2027.b") juga
        diperiksa lebih dulu: selama popup itu tampil, klik di luarnya diabaikan Dapodik.
        """
        self._singkirkan_popup(peramban)
        selesai = self._lapisan_hilang(peramban)
        if not selesai:
            if not self._lapisan_lengket:
                self._catat_kepala("[tunggu] lapisan pemuatan Dapodik masih terlihat" +
                                   (f" sebelum {label}" if label else "") +
                                   " — langkah dilanjutkan dengan cara paksa (klik lewat skrip).")
            self._lapisan_lengket = True
        else:
            self._lapisan_lengket = False
        return selesai

    def _kirim_enter(self, peramban, locator) -> None:
        """Tekan Enter pada sebuah kolom; bila tertelan lapisan pemuatan, kirim lewat skrip."""
        from selenium.webdriver.common.keys import Keys

        try:
            peramban.find_element(*locator).send_keys(Keys.RETURN)
            return
        except Exception:  # noqa: BLE001 — lanjut ke cara skrip
            pass
        try:
            peramban.execute_script(
                """
                const el = arguments[0];
                for (const tipe of ['keydown', 'keypress', 'keyup']) {
                    el.dispatchEvent(new KeyboardEvent(tipe, {key: 'Enter', code: 'Enter',
                                                              keyCode: 13, which: 13,
                                                              bubbles: true}));
                }
                """, peramban.find_element(*locator))
            self._catat_kepala("[selector] tombol Enter dikirim lewat skrip")
        except Exception:  # noqa: BLE001 — upaya terbaik
            pass

    def _nilai_kolom(self, peramban, locator) -> str:
        """Isi kolom saat ini (dibaca ulang dari halaman) — '' bila tidak terbaca."""
        try:
            return str(peramban.find_element(*locator).get_attribute("value") or "")
        except Exception:  # noqa: BLE001
            return ""

    def _isi_dan_periksa(self, peramban, locator, nilai: str, label: str) -> dict[str, Any]:
        """Isi kolom lalu pastikan isinya benar-benar masuk (dibaca ulang).

        Menangkap kejadian "kolom ketemu & diketik, tetapi halaman tidak menerimanya"
        (mis. kolom readonly/tertutup lapisan) — penyebab login gagal yang sulit dilihat.
        Nilai sandi tidak pernah dicatat, hanya panjangnya.
        """
        self._lapisan_hilang(peramban)
        self._isi(peramban, locator, nilai)
        isi = self._nilai_kolom(peramban, locator)
        if str(nilai).strip() and str(nilai).strip() not in isi:
            try:  # percobaan kedua: tampilkan lalu isi lewat skrip
                elemen = peramban.find_element(*locator)
                self._paksa_terlihat(peramban, elemen)
                self._isi_lewat_js(peramban, elemen, nilai)
                isi = self._nilai_kolom(peramban, locator)
            except Exception:  # noqa: BLE001 — tetap laporkan hasil terakhir
                pass
        hasil = {"terisi": bool(isi) and str(nilai).strip() in isi, "panjang": len(isi)}
        self._catat_kepala(f"[login] kolom {label}: " +
                           ("terisi" if hasil["terisi"] else "GAGAL terisi") +
                           f" ({hasil['panjang']} karakter)")
        return hasil

    def _tunggu_elemen(self, peramban, locator):
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        batas = float(self.opsi.get("bot_timeout", "15") or 15)
        return WebDriverWait(peramban, batas).until(EC.visibility_of_element_located(locator))

    def _pertama_terlihat(self, peramban, locator, aktif: bool = False):
        """Elemen pertama yang benar-benar **terlihat** (bukan yang tersembunyi).

        Penting: Ext JS sering menyisakan elemen kembar yang tersembunyi di halaman —
        mis. tombol «Simpan dan Tutup» panel Data Periodik setelah panelnya ditutup, yang
        kelasnya sama dengan tombol «Simpan dan Tutup» formulir Registrasi. Pencarian yang
        mengambil elemen pertama di DOM bisa memilih yang tersembunyi (klik tidak terjadi).
        """
        try:
            for unsur in peramban.find_elements(*locator):
                try:
                    if not unsur.is_displayed():
                        continue
                    if aktif and not unsur.is_enabled():
                        continue
                    return unsur
                except Exception:  # noqa: BLE001 — periksa unsur berikutnya
                    continue
        except Exception:  # noqa: BLE001 — tidak dapat mencari: anggap tidak ada
            return None
        return None

    def _elemen_ada(self, peramban, locator):
        """Elemen yang ada di halaman, terlihat atau belum (mis. formulir masih memuat)."""
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        batas = float(self.opsi.get("bot_timeout", "15") or 15)
        return WebDriverWait(peramban, batas).until(EC.presence_of_element_located(locator))

    # ------------------------------------------------- popup pengumuman --- #
    def _boleh_ditutup(self, peramban, unsur) -> bool:
        """Apakah unsur ini benar-benar popup pengumuman — bukan jendela formulir Registrasi.

        Pengaman penting: kalau jendela itu (atau jendela induknya) memuat kolom NIS
        ``input[name=nipd]``, bot tidak boleh menutupnya — itu formulir yang sedang diisi.
        """
        from selenium.webdriver.common.by import By

        try:
            if unsur.find_elements(By.NAME, "nipd"):
                return False
            return not unsur.find_elements(
                By.XPATH, "ancestor-or-self::div[contains(@class, 'x-window') "
                          "or contains(@class, 'x-message-box')][.//input[@name='nipd']]")
        except Exception:  # noqa: BLE001 — tidak dapat diperiksa: aman untuk ditutup
            return True

    def _unsur_popup(self, peramban, peta: dict[str, str] | None = None):
        """Jendela popup pengumuman Dapodik yang sedang tampil (``None`` bila tidak ada)."""
        from selenium.webdriver.common.by import By

        peta = peta or peta_selector()
        cara = [(By.XPATH, nilai) for nilai in XPATH_POPUP]
        cara.extend(self._locator_nilai(nilai)
                    for nilai in self._kandidat_selector("popup_tutup", peta))
        for by, nilai in cara:
            try:
                for unsur in peramban.find_elements(by, nilai):
                    if not unsur.is_displayed():
                        continue
                    if not self._boleh_ditutup(peramban, unsur):
                        continue
                    return unsur
            except Exception:  # noqa: BLE001 — coba cara berikutnya
                continue
        return None

    def _tunggu_popup_hilang(self, peramban, peta: dict[str, str] | None = None,
                             batas: float = 3.0) -> bool:
        """Tunggu popup yang sudah ditutup benar-benar hilang dari halaman."""
        akhir = time.time() + batas
        while self._unsur_popup(peramban, peta) is not None:
            if time.time() >= akhir:
                return False
            time.sleep(0.4)
        return True

    def _tutup_popup(self, peramban, unsur_popup, peta: dict[str, str] | None = None) -> bool:
        """Tutup popup pengumuman: tombol «Tutup» (beberapa cara), lalu buang dari halaman."""
        peta = peta or peta_selector()
        for nilai in (self._kandidat_selector("popup_tutup", peta) + [
                'xpath://*[self::a or self::span or self::button][normalize-space()="Tutup"]']):
            try:
                for tombol in peramban.find_elements(*self._locator_nilai(nilai)):
                    if not tombol.is_displayed() or not self._boleh_ditutup(peramban, tombol):
                        continue
                    try:
                        tombol.click()
                    except Exception:  # noqa: BLE001 — tertelan lapisan modal: klik lewat skrip
                        peramban.execute_script("arguments[0].click();", tombol)
                    if self._tunggu_popup_hilang(peramban, peta, 3):
                        return True
                    self._catat_kepala("[popup] tombol «Tutup» sudah diklik, popup masih "
                                       "tampil — mencoba cara lain.")
            except Exception:  # noqa: BLE001 — coba kandidat berikutnya
                continue
        try:  # jalan keluar terakhir: Dapodik tidak menanggapi klik pada popupnya
            peramban.execute_script(
                """
                arguments[0].remove();
                document.querySelectorAll('div.x-mask').forEach((lapisan) => lapisan.remove());
                """, unsur_popup)
            if self._tunggu_popup_hilang(peramban, peta, 2):
                self._catat_kepala("[popup] popup pengumuman Dapodik dibuang dari halaman "
                                   "(tombolnya tidak menanggapi klik).")
                return True
        except Exception:  # noqa: BLE001 — upaya terbaik
            pass
        return False

    def _singkirkan_popup(self, peramban, peta: dict[str, str] | None = None,
                          batas: float = 0.0) -> bool:
        """Tutup popup pengumuman bila tampil; ``batas`` menunggunya muncul lebih dulu.

        Dipakai sebelum langkah penting. Bila tidak ada popup, pemeriksaan ini singkat.
        """
        peta = peta or peta_selector()
        unsur = self._unsur_popup(peramban, peta)
        akhir = time.time() + max(0.0, batas)
        while unsur is None and time.time() < akhir:
            time.sleep(0.5)
            unsur = self._unsur_popup(peramban, peta)
        if unsur is None:
            return False
        self._catat_kepala("Popup pengumuman Dapodik tampil — menutupnya …")
        if self._tutup_popup(peramban, unsur, peta):
            self._lapisan_hilang(peramban, 3)
            return True
        self._catat_kepala("Popup pengumuman Dapodik belum dapat ditutup — langkah "
                           "diteruskan dengan cara paksa.")
        return False

    def _baris_terpilih(self, peramban, xpath_baris: str) -> bool:
        """Apakah baris siswa sudah terpilih (wajib sebelum menekan tombol Registrasi)."""
        from selenium.webdriver.common.by import By

        try:
            if peramban.find_elements(
                    By.XPATH, f'{xpath_baris}[contains(@class, "x-grid-row-selected")]'):
                return True
        except Exception:  # noqa: BLE001 — lanjut ke pemeriksaan berikutnya
            pass
        try:
            baris = peramban.find_element(By.XPATH, xpath_baris)
            if baris.is_selected():
                return True
            if str(baris.get_attribute("aria-selected") or "").strip().lower() == "true":
                return True
            if "selected" in str(baris.get_attribute("class") or "").lower():
                return True
        except Exception:  # noqa: BLE001 — tidak dapat diperiksa
            pass
        return False

    def _pastikan_baris_terpilih(self, peramban, xpath_baris: str, nisn: str) -> bool:
        """Pilih baris siswa sampai benar-benar terpilih.

        Penting: di Ext JS baris terpilih saat **mousedown**. Klik lewat skrip
        (``arguments[0].click()``) hanya mengirim event *click*, sehingga barisnya tidak
        pernah terpilih — akibatnya tombol Registrasi tidak membuka apa pun (gejala di
        screenshot PC sekolah: kotak centang baris kosong, panel Data Periodik kelabu).
        """
        from selenium.webdriver.common.by import By

        if self._baris_terpilih(peramban, xpath_baris):
            return True
        # 1) klik sungguhan: sel NISN lebih dulu, lalu barisnya.
        for locator in ((By.XPATH, f'{xpath_baris}//td[contains(., "{nisn}")]'),
                        (By.XPATH, xpath_baris)):
            try:
                self._klik_aman(peramban, locator, ulang=2)
            except Exception:  # noqa: BLE001 — coba cara berikutnya
                continue
            if self._baris_terpilih(peramban, xpath_baris):
                return True
        # 2) urutan tetikus lengkap lewat skrip (mousedown → mouseup → click) pada sel/baris.
        for locator in ((By.XPATH, f'{xpath_baris}//td[contains(., "{nisn}")]'),
                        (By.XPATH, xpath_baris)):
            try:
                peramban.execute_script(
                    """
                    const el = arguments[0];
                    for (const tipe of ['mousedown', 'mouseup', 'click']) {
                        el.dispatchEvent(new MouseEvent(tipe, {bubbles: true, cancelable: true,
                                                              view: window}));
                    }
                    """, peramban.find_element(*locator))
            except Exception:  # noqa: BLE001 — coba sasaran berikutnya
                continue
            if self._baris_terpilih(peramban, xpath_baris):
                self._catat_kepala("[registrasi] baris siswa dipilih lewat skrip "
                                   "(klik sungguhan tertelan lapisan pemuatan).")
                return True
        return False

    def _formulir_registrasi_terbuka(self, peramban, peta: dict[str, str] | None = None) -> bool:
        """Apakah formulir Registrasi sudah terbuka (kolom NIS atau Hobi sudah terlihat)."""
        peta = peta or peta_selector()
        for kunci in ("input_nis", "hobi"):
            for nilai in self._kandidat_selector(kunci, peta):
                try:
                    for unsur in peramban.find_elements(*self._locator_nilai(nilai)):
                        if unsur.is_displayed():
                            return True
                except Exception:  # noqa: BLE001 — coba kandidat berikutnya
                    continue
        return False

    def _paksa_terlihat(self, peramban, elemen) -> None:
        """Tampilkan elemen & pembungkus yang menyembunyikannya (mis. formulir belum dibuka)."""
        try:
            # Ronde 45: jangan menggulir selagi kursor masih di dalam kolom isian.
            self._kursor_aman(peramban, awalan="[unsur]")
            peramban.execute_script(
                """
                let el = arguments[0];
                let p = el;
                while (p && p.style) {
                    const gaya = window.getComputedStyle(p);
                    if (gaya.display === 'none') p.style.display = 'block';
                    if (gaya.visibility === 'hidden') p.style.visibility = 'visible';
                    if (parseFloat(gaya.opacity || '1') === 0) p.style.opacity = '1';
                    if (p === document.body) break;
                    p = p.parentElement;
                }
                el.removeAttribute('disabled');
                el.removeAttribute('readonly');
                el.scrollIntoView({block: 'center'});
                el.focus();
                """, elemen)
            self._periksa_nilai_bio(peramban, "[unsur]")
        except Exception:  # noqa: BLE001 — upaya terbaik
            pass

    def _picu_peristiwa(self, peramban, elemen) -> None:
        """Beri tahu Ext JS bahwa isi kolom berubah (input → change → blur).

        Skrip yang terbukti berhasil selalu menjalankan ketiga peristiwa ini sesudah
        mengetik; tanpa itu Dapodik bisa menganggap kolomnya masih kosong.
        """
        try:
            peramban.execute_script(
                """
                const el = arguments[0];
                for (const nama of ['input', 'change', 'blur']) {
                    el.dispatchEvent(new Event(nama, {bubbles: true}));
                }
                """, elemen)
        except Exception:  # noqa: BLE001 — upaya terbaik
            pass

    def _isi_lewat_js(self, peramban, elemen, nilai: str) -> None:
        """Isi kolom lewat skrip (dipakai bila kolom tidak dapat diketik langsung)."""
        peramban.execute_script(
            """
            const el = arguments[0], nilai = arguments[1];
            el.removeAttribute('disabled');
            el.removeAttribute('readonly');
            el.focus();
            el.value = nilai;
            for (const nama of ['input', 'change', 'keyup', 'keydown', 'blur']) {
                el.dispatchEvent(new Event(nama, {bubbles: true}));
            }
            """, elemen, str(nilai))

    def _klik_aman(self, peramban, locator, ulang: int | None = None, elemen=None) -> None:
        """Klik dengan percobaan ulang: overlay, elemen berubah, atau belum terlihat.

        ``elemen`` (opsional) = unsur yang sudah dipilih pemanggil — mis. tombol «Simpan dan
        Tutup» milik JENDELA REGISTRASI, bukan tombol kembarnya di panel Data Periodik (nama,
        kelas, dan tulisan tombol itu sama). Kalau diisi, pencarian lewat locator dilewati;
        pengaman sebelum klik (lapisan pemuatan, kursor keluar dari kolom, gulir ke tengah)
        tetap dijalankan.
        """
        from selenium.common.exceptions import (ElementClickInterceptedException,
                                                ElementNotInteractableException,
                                                StaleElementReferenceException, TimeoutException)
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        ulang = ulang or int(self.opsi.get("bot_max_retries", "3") or 3)
        batas = float(self.opsi.get("bot_timeout", "15") or 15)
        galat = None
        for percobaan in range(1, ulang + 1):
            try:
                # Skrip sekolah selalu menunggu lapisan pemuatan hilang sebelum mengklik;
                # bila lapisan itu belum hilang juga, klik dilanjutkan lewat skrip (di bawah)
                # supaya tidak menggantung — penyebab "element click intercepted" di PC sekolah.
                if not self._lapisan_hilang(peramban, min(LAPISAN_TUNGGU_DETIK, batas)):
                    raise TimeoutError("lapisan pemuatan Dapodik belum hilang")
                if elemen is None or not self._terlihat(peramban, elemen):
                    elemen = WebDriverWait(peramban, batas).until(
                        lambda p: self._pertama_terlihat(p, locator, aktif=True))
                # Ronde 45: kursor dikeluarkan dulu dari kolom isian mana pun. Menggulir
                # selagi kursor ada di dalam kolom angka (mis. «RT») mengubah nilainya
                # menjadi «0» di Dapodik — jadi jangan pernah menggulir selagi mengetik.
                self._kursor_aman(peramban, awalan="[klik]")
                peramban.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemen)
                self._periksa_nilai_bio(peramban, "[klik]")
                elemen.click()
                return
            except (ElementClickInterceptedException, StaleElementReferenceException,
                    TimeoutException, TimeoutError, ElementNotInteractableException) as exc:
                galat = exc
                # Klik bisa tertelan popup pengumuman yang muncul belakangan: tutup dulu
                # popupnya, lalu ulangi percobaan ini (elemen yang sama, klik sungguhan).
                if self._singkirkan_popup(peramban):
                    time.sleep(1)
                    continue
                # Upaya terakhir pada percobaan ini: tampilkan elemen lalu klik lewat skrip.
                try:
                    elemen = (self._pertama_terlihat(peramban, locator)
                              or peramban.find_element(*locator))
                    self._paksa_terlihat(peramban, elemen)
                    peramban.execute_script("arguments[0].click();", elemen)
                    self._catat_kepala(f"[selector] klik lewat skrip untuk {locator}")
                    return
                except Exception:  # noqa: BLE001 — benar-benar gagal, ulangi
                    pass
                self._catat_kepala(f"[klik {percobaan}/{ulang}] belum berhasil ({type(exc).__name__}) — "
                                   "mencoba lagi.")
                time.sleep(1)
        raise galat if galat else RuntimeError("Klik gagal.")

    def _isi(self, peramban, locator, nilai: str):
        """Isi kolom: mengetik seperti manusia, dengan cadangan lewat skrip."""
        from selenium.webdriver.common.keys import Keys

        elemen = None
        for cara in ("ketik", "paksa", "skrip"):
            try:
                elemen = self._elemen_ada(peramban, locator)
                if cara == "ketik":
                    elemen.click()
                    elemen.send_keys(Keys.CONTROL, "a")
                    elemen.send_keys(str(nilai))
                elif cara == "paksa":
                    self._paksa_terlihat(peramban, elemen)
                    elemen.send_keys(Keys.CONTROL, "a")
                    elemen.send_keys(str(nilai))
                else:
                    self._paksa_terlihat(peramban, elemen)
                    self._isi_lewat_js(peramban, elemen, nilai)
                    self._catat_kepala(f"[selector] kolom diisi lewat skrip ({locator})")
                return elemen
            except Exception as exc:  # noqa: BLE001 — coba cara berikutnya
                if cara == "skrip":
                    raise
                self._catat_kepala(f"[isi kolom] cara '{cara}' gagal ({type(exc).__name__}) — "
                                   "mencoba cara lain.")
                time.sleep(0.5)
        return elemen

    # ------------------------------------------------------- kolom pilihan --- #
    def _cari_lewat_label(self, peramban, teks: str):
        """Cari kolom isian lewat **label** yang tertera di formulir Dapodik.

        Dapodik menamai kolomnya berbeda-beda antar versi (mis. ``sekolah_asal`` atau
        ``id_sekolah_asal``), sedangkan labelnya tetap «Sekolah Asal». Skrip ini mencari teks
        label, lalu mengambil kolom isian **yang berada di bidang yang sama** dengan label itu
        (lewat ``for`` atau wadah ``.x-field``/``.x-form-item``-nya) — jadi label «RT» tidak
        akan mengambil kotak «RW» bila keduanya berada di satu baris.

        Sejak ronde 47 label juga dilacak pada **div Ext JS** (``.x-fieldlabel`` /
        ``.x-form-item-label``): di sebagian versi Dapodik label kolom (RT, RW, Desa/Kelurahan,
        No. KK, Kode Pos) tidak digambar sebagai elemen ``<label>``, sehingga pencarian label
        biasa tidak menemukannya.
        """
        try:
            return peramban.execute_script(
                """
                /* cari-label-halaman */
                const cari = String(arguments[0] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                if (!cari) return null;
                const rapi = (t) => String(t || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const bersih = (t) => rapi(t).replace(/[*:\\u00a0]+$/g, '').trim();
                const tampil = (el) => !!(el && el.getClientRects && el.getClientRects().length);
                const isianDalam = (bidang) => {
                    if (!bidang) return null;
                    for (const k of bidang.querySelectorAll('input, textarea, select')) {
                        const jenis = String(k.getAttribute('type') || '').toLowerCase();
                        if (jenis === 'hidden' || jenis === 'button' || jenis === 'submit') continue;
                        if (tampil(k)) return k;
                    }
                    return null;
                };
                const kotakDariLabel = (etiket) => {
                    const id = etiket.htmlFor || etiket.getAttribute('for');
                    if (id) {
                        const lewatId = document.getElementById(id);
                        if (lewatId && tampil(lewatId)) return lewatId;
                    }
                    const bidang = etiket.closest('.x-field, .x-form-item, .form-group');
                    return isianDalam(bidang) || isianDalam(etiket.parentElement);
                };
                const kandidatLabel = [
                    ...document.querySelectorAll('label'),
                    ...document.querySelectorAll(
                        '.x-fieldlabel, .x-form-item-label, .x-form-item-label-default'),
                ];
                for (const etiket of kandidatLabel) {
                    const teksLabel = bersih(etiket.textContent);
                    if (!teksLabel || (teksLabel !== cari && !teksLabel.startsWith(cari))) continue;
                    const kotak = kotakDariLabel(etiket);
                    if (kotak) return kotak;
                }
                // Sebagian formulir Ext JS tidak memakai <label>: teks polos di sebelah kolom.
                const semua = [...document.querySelectorAll('div, span, td')];
                const pemilik = semua.find((d) => bersih(d.textContent) === cari);
                if (pemilik) {
                    const bidang = pemilik.closest('.x-field, .x-form-item, .form-group')
                        || pemilik.parentElement;
                    return isianDalam(bidang);
                }
                return null;
                """, str(teks))
        except Exception:  # noqa: BLE001 — halaman belum siap: anggap tidak ada
            return None

    def _cari_kolom_dengan_label(self, peramban, kunci: str, peta: dict[str, str]):
        """Cari satu kolom isian mengikuti urutan kandidat selector milik ``kunci``.

        Nilai yang diawali ``label:`` dicari lewat **teks labelnya** (paling tahan
        perbedaan versi Dapodik, mis. «Sekolah Asal», «Tinggi Badan»); nilai lain dicari
        seperti biasa. Kembalikan elemen, atau ``None`` bila tidak ada.
        """
        for nilai in self._kandidat_selector(kunci, peta):
            if nilai.lower().startswith("label:"):
                unsur = self._cari_lewat_label(peramban, nilai.split(":", 1)[1])
                if unsur is not None:
                    return unsur
                continue
            try:
                for unsur in peramban.find_elements(*self._locator_nilai(nilai)):
                    return unsur
            except Exception:  # noqa: BLE001 — coba kandidat berikutnya
                continue
        return None

    def _kolom_sekolah_asal(self, peramban, peta: dict[str, str]):
        """Kolom «Sekolah Asal» pada formulir Registrasi (``None`` bila tidak ada)."""
        return self._cari_kolom_dengan_label(peramban, "sekolah_asal", peta)

    #: Kolom Data Periodik: (kunci data siswa, label, kunci selector). Urutan mengikuti
    #: potongan skrip sekolah: tinggi badan → berat badan → lingkar kepala → (jarak) →
    #: jumlah saudara kandung → Simpan dan Tutup.
    PERIODIK_AWAL: tuple[tuple[str, str, str], ...] = (
        ("tinggi_badan", "Tinggi badan", "periodik_tinggi"),
        ("berat_badan", "Berat badan", "periodik_berat"),
        ("lingkar_kepala", "Lingkar kepala", "periodik_lingkar"),
    )
    #: Kolom yang diisi SESUDAH baris «Jarak rumah ke sekolah» (urutan sama seperti skrip
    #: sekolah: centang jarak & kolom kilometernya lebih dulu, baru jumlah saudara kandung).
    PERIODIK_AKHIR: tuple[tuple[str, str, str], ...] = (
        ("jml_saudara", "Jumlah saudara kandung", "periodik_saudara"),
    )

    #: Kolom jendela «Ubah» (BIO) yang diisi bot — persis potongan skrip sekolah, termasuk
    #: urutannya: No. KK → No. Registrasi Akta Lahir → alamat/RT/RW/kode pos → anak ke-berapa
    #: → data ayah (nama, NIK, tahun lahir, pendidikan) → data ibu (NIK, tahun lahir,
    #: pendidikan). «Nama Ibu» tidak diisi karena skrip sekolah pun tidak mengisinya.
    BIO_KOLOM: tuple[tuple[str, str, str], ...] = (
        ("no_kk", "No. Kartu Keluarga", "bio_no_kk"),
        ("no_registrasi_akta", "No. Registrasi Akta Lahir", "bio_reg_akta"),
        ("alamat", "Alamat (Jalan)", "bio_alamat"),
        ("rt", "RT", "bio_rt"),
        ("rw", "RW", "bio_rw"),
        # Kolom combo «Desa/Kelurahan» (satu kolom memuat desa + kecamatan + kota). Diisi
        # dengan cara tersendiri: mengetik nama kecamatan → menunggu daftar desa dari
        # Dapodik → menggulir & memindah halaman daftarnya → memilih desa yang cocok.
        ("kelurahan", "Desa/Kelurahan", "bio_kelurahan"),
        ("kode_pos", "Kode Pos", "bio_kode_pos"),
        ("anak_ke", "Anak ke-berapa", "bio_anak_ke"),
        ("ayah_nama", "Nama ayah", "bio_ayah_nama"),
        ("ayah_nik", "NIK ayah", "bio_ayah_nik"),
        ("ayah_tahun_lahir", "Tahun lahir ayah", "bio_ayah_tahun"),
        ("ayah_pendidikan", "Pendidikan ayah", "bio_ayah_pendidikan"),
        ("ayah_pekerjaan", "Pekerjaan ayah", "bio_ayah_pekerjaan"),
        ("ayah_penghasilan", "Penghasilan ayah", "bio_ayah_penghasilan"),
        ("ibu_nik", "NIK ibu", "bio_ibu_nik"),
        ("ibu_tahun_lahir", "Tahun lahir ibu", "bio_ibu_tahun"),
        ("ibu_pendidikan", "Pendidikan ibu", "bio_ibu_pendidikan"),
        ("ibu_pekerjaan", "Pekerjaan ibu", "bio_ibu_pekerjaan"),
        ("ibu_penghasilan", "Penghasilan ibu", "bio_ibu_penghasilan"),
    )

    #: Berapa kali bot boleh MENGISI ULANG kolom yang ditolak Dapodik sebelum menyerah
    #: (ronde 50). Tiap putaran dicatat, dan nilai yang tidak ada datanya tidak dikarang.
    BATAS_PERBAIKAN_BIO = 3

    #: Atribut data keluarga (ayah/ibu/wali) → kunci data siswa di SM (``wali_pekerjaan``, …).
    #: Dipakai saat memperbaiki kolom yang ditolak Dapodik (ronde 50): potongan nama/label
    #: kolom dirapikan lebih dulu (spasi → garis bawah) sebelum dicocokkan.
    ATRIBUT_KELUARGA: dict[str, str] = {
        "jenjang_pendidikan": "pendidikan",
        "pendidikan": "pendidikan",
        "pekerjaan": "pekerjaan",
        "penghasilan": "penghasilan",
        "tahun_lahir": "tahun_lahir",
        "tanggal_lahir": "tahun_lahir",
        "nik": "nik",
        "nama": "nama",
    }

    @property
    def PERIODIK(self) -> tuple[tuple[str, str, str], ...]:
        """Semua kolom Data Periodik (untuk pemeriksaan keberadaan panel)."""
        return self.PERIODIK_AWAL + self.PERIODIK_AKHIR

    @staticmethod
    def _nilai_teks(nilai: Any) -> str:
        """Nilai angka jadi teks rapi seperti skrip sekolah: 55.0 → '55', 63.5 → '63.5'."""
        teks = str(nilai if nilai is not None else "").strip()
        if not teks:
            return ""
        try:
            angka = float(teks.replace(",", "."))
        except ValueError:
            return teks
        return str(int(angka)) if angka == int(angka) else str(angka)

    def _kursor_aman(self, peramban, tumpuan=None, awalan: str = "[kursor]") -> dict:
        """Pindahkan kursor keluar dari kolom isian **sebelum** menggulir.

        Laporan sekolah (ronde 45): menggulir halaman/jendela selagi kursor masih berada di
        dalam kolom isian bisa mengubah nilai kolom itu — «RT» berubah menjadi «0» setelah
        digulir. Karena itu setiap kali bot akan menggulir, fokus dipindah lebih dulu ke
        tempat yang aman: ``tumpuan`` bila ada (mis. isi jendela «Ubah» atau daftar pilihan
        yang sedang terbuka supaya daftarnya tidak menutup), atau dilepas sama sekali.

        Kembalikan keterangan apa yang dipindahkan (untuk dilaporkan apa adanya).
        """
        try:
            hasil = peramban.execute_script(
                """
                /* kursor-aman */
                const tumpuan = arguments[0] || null;
                const aktif = document.activeElement;
                const info = {aktif: '', tumpuan: '', dipindah: false};
                if (!aktif || aktif === document.body || aktif === document.documentElement) {
                    return info;
                }
                const tag = String(aktif.tagName || '').toUpperCase();
                const teks = (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT')
                    && !['radio', 'checkbox', 'button', 'submit', 'hidden']
                        .includes(String(aktif.type || '').toLowerCase());
                if (!teks) return info;
                info.aktif = aktif.getAttribute('name') || aktif.id || tag;
                if (tumpuan && typeof tumpuan.focus === 'function') {
                    tumpuan.focus();
                    info.tumpuan = (tumpuan.getAttribute
                        && (tumpuan.getAttribute('name') || tumpuan.id))
                        || (tumpuan.className ? String(tumpuan.className).slice(0, 40)
                                              : 'tumpuan');
                } else if (aktif.blur) {
                    aktif.blur();
                }
                info.dipindah = true;
                return info;
                """, tumpuan)
        except Exception:  # noqa: BLE001 — memindahkan kursor hanya upaya terbaik
            return {}
        if isinstance(hasil, dict) and hasil.get("dipindah"):
            self.kursor_dipindah += 1
            nama = str(hasil.get("aktif") or "?")
            tempat = str(hasil.get("tumpuan") or "badan halaman")
            self._catat_kepala(f"{awalan} kursor dikeluarkan dari kolom «{nama}» (dipindah ke "
                               f"{tempat}) sebelum menggulir — menggulir selagi kursor ada di "
                               "dalam kolom bisa mengubah nilainya (mis. «RT» menjadi «0»).")
        return hasil if isinstance(hasil, dict) else {}

    def _tumpuan_dropdown(self, peramban, unsur):
        """Elemen daftar pilihan milik sebuah combo — tempat kursor yang aman & tetap terbuka.

        Melepas fokus dari kotak combo membuat daftarnya menutup (Ext JS ``completeEdit``),
        jadi saat menggulir/mengklik pilihannya kursor ditaruh pada **daftar pilihannya**
        — bukan di kolom isian mana pun — supaya daftarnya tetap terbuka.
        """
        try:
            return peramban.execute_script(
                """
                /* dropdown-aria */
                const el = arguments[0];
                if (!el) return null;
                const id = (el.getAttribute && el.getAttribute('id')) || '';
                const milik = el.getAttribute ? el.getAttribute('aria-owns') : '';
                if (!milik) return null;
                const bagian = String(milik).split(/\\s+/).filter((s) => s.indexOf('list') >= 0);
                for (const nama of bagian) {
                    const kandidat = document.getElementById(nama);
                    if (kandidat) return kandidat;
                }
                return null;
                """, unsur)
        except Exception:  # noqa: BLE001 — tanpa daftar, kursor cukup dilepas
            return None

    # --- Penjaga nilai: jangan biarkan gulir mengubah kolom yang sudah diisi --- #
    @staticmethod
    def _angka_sama(kiri: Any, kanan: Any) -> bool:
        """Apakah dua isian **sama sebagai angka** (mis. «007» ≡ «7»)?

        Dapodik menyimpan RT/RW (dan beberapa kolom lain) sebagai **angka**: nilai data
        sekolah «007» tampil & tersimpan sebagai «7». Bentuk yang berbeda seperti itu
        **bukan** kegagalan pengisian, dan **bukan** perubahan nilai yang perlu dikembalikan
        penjaga — laporan ronde 47: «masih gagal input rt dan rw».
        """
        def angka(nilai: Any) -> float | None:
            teks = str(nilai if nilai is not None else "").strip().replace(" ", "")
            if not teks or not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", teks):
                return None
            try:
                return float(teks.replace(",", "."))
            except ValueError:
                return None

        kiri_angka, kanan_angka = angka(kiri), angka(kanan)
        return kiri_angka is not None and kanan_angka is not None and kiri_angka == kanan_angka

    def _isi_sesuai(self, diminta: str, isi: str) -> tuple[bool, bool]:
        """Sudah berisikah kolomnya dengan nilai yang diminta? → ``(sesuai, angka_dinormalkan)``.

        ``angka_dinormalkan`` = nilai cocok **sebagai angka** walau tulisannya berbeda
        («007» → «7»), supaya lognya jujur menjelaskan apa yang dilakukan Dapodik.
        """
        if not isi:
            return False, False
        if isi == diminta:
            return True, False
        if self._angka_sama(diminta, isi):
            # Tulisan berbeda, nilainya sama sebagai angka («007» ≡ «7», «63.5» ≡ «63,5»).
            return True, True
        if self._keduanya_angka(diminta, isi):
            # Dua-duanya angka tetapi nilainya BEDA: jangan diterima hanya karena bentuk
            # teksnya mirip (mis. data «3» tidak boleh dianggap cocok dengan kolom «13»).
            return False, False
        return (diminta in isi), False

    @staticmethod
    def _angka_lah(nilai: Any) -> bool:
        """Apakah isian ini berbentuk angka (kolom angka seperti RT/RW)?"""
        teks = str(nilai if nilai is not None else "").strip().replace(" ", "")
        return bool(re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", teks))

    @staticmethod
    def _keduanya_angka(kiri: Any, kanan: Any) -> bool:
        """Apakah dua isian itu sama-sama berbentuk angka (tanpa perlu nilainya sama)?"""
        return BotDapodik._angka_lah(kiri) and BotDapodik._angka_lah(kanan)

    @staticmethod
    def _catatan_angka(diminta: str, isi: str, dinormalkan: bool) -> str:
        """Keterangan tambahan bila Dapodik menyimpan nilainya sebagai angka."""
        if not dinormalkan:
            return ""
        return (f" (data «{diminta}» — Dapodik menyimpan kolom ini sebagai angka, "
                f"jadi «{isi}» sudah benar)")

    def _nilai_model(self, peramban, unsur) -> str | None:
        """Nilai yang tersimpan di **model Ext JS** kolom ini (bukan hanya tulisan di kotaknya).

        Dapodik menyimpan isian dari model Ext JS-nya. Untuk kolom angka seperti RT/RW
        (``numberfield``), tulisan yang sudah benar di kotaknya belum tentu nilai yang
        tersimpan: gulir dapat mengubah nilainya menjadi «0», dan bila yang diperbaiki hanya
        tulisannya, Dapodik tetap menyimpan «0» — sisa sebab keluhan «masih gagal input rt dan
        rw» (ronde 48). Kembalian ``None`` = tidak terbaca (Ext JS tidak ada): bot tidak
        mengaku apa-apa, keterbatasan itu dicatat.
        """
        komponen = self._komponen_id(peramban, unsur)
        if not komponen:
            return None
        try:
            nilai = peramban.execute_script(
                """
                /* nilai-model-unsur */
                if (typeof Ext === 'undefined' || !Ext.getCmp) return null;
                const c = Ext.getCmp(arguments[0]);
                if (!c) return null;
                if (typeof c.getValue === 'function') {
                    const v = c.getValue();
                    return (v === null || v === undefined) ? '' : String(v);
                }
                if (typeof c.getRawValue === 'function') {
                    const v = c.getRawValue();
                    return (v === null || v === undefined) ? '' : String(v);
                }
                return null;
                """, komponen)
        except Exception:  # noqa: BLE001 — pembacaan tambahan saja
            return None
        if nilai is None:
            return None
        return str(nilai).strip()

    def _pastikan_model_angka(self, peramban, unsur, diharapkan: str) -> str:
        """Kolom ANGKA: pastikan nilai MODEL Ext JS-nya juga benar, bukan hanya kotaknya.

        Bila modelnya tertinggal (mis. masih «0» sesudah tulisan di kotak dikembalikan
        penjaga nilai), nilainya ditulis ulang lewat ``Ext.getCmp(...).setValue(...)`` memakai
        bentuk yang sudah benar di kotaknya — supaya yang diketik tidak berbeda dari yang
        ditampilkan Dapodik. Keterangan kembalian: ``""`` = tidak ada yang perlu dikatakan
        (bukan kolom angka / model tak terbaca), ``"cocok («…»)"``, ``"diperbaiki …"``, atau
        peringatan jujur bila perbaikannya tidak berhasil.
        """
        if not self._angka_lah(diharapkan):
            return ""                       # bukan kolom angka: model tidak perlu diurus
        nama = str(getattr(unsur, "name", "") or "").strip() or "kolom angka"
        model = self._nilai_model(peramban, unsur)
        if model is None:
            self.model_tak_terbaca += 1
            return ""                       # tak terbaca: jangan mengaku sudah diperiksa
        self.model_diperiksa += 1
        if model != "" and self._isi_sesuai(diharapkan, model)[0]:
            return f"cocok («{model}»)"
        try:
            isi_kotak = str(unsur.get_attribute("value") or "").strip()
        except Exception:  # noqa: BLE001 — pembacaan tulisan di kotak hanya upaya terbaik
            isi_kotak = ""
        nilai_tulis = isi_kotak if self._isi_sesuai(diharapkan, isi_kotak)[0] else diharapkan
        if not self._set_ext(peramban, unsur, nilai=nilai_tulis):
            return (f"model Ext JS «{nama}» masih «{model or 'kosong'}» dan tidak bisa ditulis "
                    "lewat Ext JS — nilainya perlu diperiksa di Dapodik.")
        time.sleep(0.3)
        sesudah = self._nilai_model(peramban, unsur)
        if sesudah is not None and self._isi_sesuai(diharapkan, sesudah)[0]:
            self.model_diperbaiki += 1
            return (f"model Ext JS «{nama}» masih «{model or 'kosong'}» walau kotaknya sudah "
                    f"benar — ditulis ulang lewat Ext JS (setValue) menjadi «{sesudah}» supaya "
                    "Dapodik menyimpan angka itu.")
        return (f"model Ext JS «{nama}» belum benar sesudah ditulis ulang "
                f"(«{sesudah or 'kosong'}», seharusnya «{diharapkan}») — periksa kolom ini "
                "di Dapodik.")

    def _rekam_nilai_bio(self, unsur, nilai: str) -> None:
        """Catat nilai kolom BIO yang sudah ditulis bot (untuk diperiksa sesudah menggulir)."""
        nama = str(getattr(unsur, "name", "") or "")
        if nama:
            self._penjaga_nilai[nama] = self._nilai_teks(nilai)
            self._penjaga_unsur[nama] = unsur    # dipakai untuk memeriksa model Ext JS-nya

    def _periksa_nilai_bio(self, peramban, awalan: str = "[penjaga]") -> list[str]:
        """Periksa lagi nilai kolom BIO yang sudah ditulis; kembalikan yang berubah.

        Menanggulangi keadaan nyata di sekolah: menggulir selagi kursor berada di kolom
        isian (atau gulir oleh pengguna yang sedang menonton) mengubah nilai kolom — «RT»
        menjadi «0». Nilai yang berubah **dikembalikan** dan dilaporkan apa adanya, supaya
        data Dapodik tidak ikut salah.
        """
        if not self._penjaga_nilai:
            return []
        try:
            sekarang = peramban.execute_script(
                """
                /* nilai-kolom-bio */
                const nama = arguments[0] || [];
                const hasil = {};
                for (const satu of nama) {
                    const el = document.querySelector('input[name="' + satu + '"]');
                    if (el) hasil[satu] = String(el.value === undefined ? '' : el.value);
                }
                return hasil;
                """, list(self._penjaga_nilai))
        except Exception:  # noqa: BLE001 — tidak terbaca: tidak ada yang diklaim
            return []
        if not isinstance(sekarang, dict):
            return []
        berubah: list[str] = []
        for nama, diharapkan in list(self._penjaga_nilai.items()):
            dapat = self._nilai_teks(sekarang.get(nama))
            # «Sama» juga berarti sama SEBAGAI ANGKA: Dapodik menyimpan kolom angka seperti
            # RT/RW sebagai numberfield, jadi «007» di data sekolah memang tampil «7» —
            # itu bukan perubahan yang perlu dikembalikan (ronde 47).
            if dapat == "" or dapat == diharapkan or self._angka_sama(diharapkan, dapat):
                continue                 # tidak terbaca / masih sama
            berubah.append(nama)
            self._catat_kepala(f"{awalan} nilai kolom «{nama}» berubah sesudah menggulir "
                               f"(«{dapat}») — dikembalikan menjadi «{diharapkan}» supaya "
                               "data Dapodik tidak ikut salah.")
            try:
                pulih = peramban.execute_script(
                    """
                    /* pulihkan-kolom-bio */
                    const nama = arguments[0], nilai = arguments[1];
                    const el = document.querySelector('input[name="' + nama + '"]');
                    if (!el) return false;
                    el.removeAttribute('readonly');
                    el.value = nilai;
                    for (const jenis of ['input', 'change', 'blur']) {
                        el.dispatchEvent(new Event(jenis, {bubbles: true}));
                    }
                    return true;
                    """, nama, diharapkan)
            except Exception:  # noqa: BLE001 — pencatatan pemulihan di bawah
                pulih = False
            if pulih:
                self.penjaga_dipulihkan += 1
            else:
                self._penjaga_nilai.pop(nama, None)
                self._catat_kepala(f"{awalan} kolom «{nama}» tidak bisa dikembalikan lewat "
                                   "skrip — nilainya perlu diperiksa di Dapodik.")
        # Kolom ANGKA diperiksa sampai ke MODEL Ext JS-nya: Dapodik menyimpan dari model itu,
        # jadi kotak yang sudah benar saja belum menjamin (mis. «RT» tersimpan «0» — ronde 48).
        for nama, diharapkan in list(self._penjaga_nilai.items()):
            if not self._angka_lah(diharapkan):
                continue
            unsur = self._penjaga_unsur.get(nama)
            if unsur is None:
                continue
            catatan = self._pastikan_model_angka(peramban, unsur, diharapkan)
            if catatan and not catatan.startswith("cocok"):
                self._catat_kepala(f"{awalan} kolom «{nama}»: {catatan}")
        return berubah

    def _gulir(self, peramban, jarak: int = GULIR_PERIODIK, catat: bool = True) -> None:
        """Gulir halaman ke bawah — sama seperti ``window.scrollBy(0, 250)`` skrip sekolah.

        Dipakai sebelum mengisi Data Periodik supaya kolom yang letaknya di bawah layar
        benar-benar tampil (klik pada elemen di luar layar sering tidak diproses Dapodik).
        """
        self._kursor_aman(peramban, awalan="[gulir]")
        try:
            peramban.execute_script("window.scrollBy(0, arguments[0]);", int(jarak))
        except Exception:  # noqa: BLE001 — sebagian cara menolak argumen
            try:
                peramban.execute_script(f"window.scrollBy(0, {int(jarak)});")
            except Exception:  # noqa: BLE001 — gulir hanya upaya terbaik
                if catat:
                    self._catat_kepala("[gulir] halaman tidak dapat digulir lewat skrip.")
                return
        if catat:
            self._catat_kepala(f"[gulir] halaman digulir {int(jarak)} px ke bawah "
                               "(seperti skrip sekolah).")

    def _bawa_ke_layar(self, peramban, unsur, tumpuan=None) -> None:
        """Bawa satu unsur ke layar dengan menggulir **hanya wadah yang perlu**.

        ``window.scrollBy`` menggulir seluruh halaman; panel seperti «Data Periodik
        Peserta Didik» justru berada di dalam wadah bergulir sendiri, sehingga gulir
        halaman tidak menolong (dan bisa menggeser bagian lain yang tidak perlu).
        Yang benar: ``scrollIntoView`` pada unsurnya, lalu ``scrollTop`` setiap induk
        yang memiliki gulir dibetulkan — halaman lain tidak ikut bergeser.

        Sebelum menggulir, **kursor dikeluarkan dulu dari kolom isian** (ronde 45):
        menggulir selagi kursor berada di dalam kolom bisa mengubah nilai kolom itu
        (mis. «RT» menjadi «0»). ``tumpuan`` dipakai bila fokusnya harus ditaruh pada
        elemen tertentu (mis. daftar pilihan yang sedang terbuka).
        """
        hasil_kursor = self._kursor_aman(peramban, tumpuan, awalan="[gulir]")
        if isinstance(hasil_kursor, dict) and hasil_kursor.get("dipindah"):
            self._periksa_nilai_bio(peramban)
        try:
            peramban.execute_script(
                """
                const el = arguments[0];
                el.scrollIntoView({block: 'center', inline: 'nearest'});
                let p = el.parentElement;
                while (p && p !== document.body) {
                    const gaya = getComputedStyle(p);
                    if ((gaya.overflowY === 'auto' || gaya.overflowY === 'scroll') &&
                        p.scrollHeight > p.clientHeight + 4) {
                        const kotakEl = el.getBoundingClientRect();
                        const kotakP = p.getBoundingClientRect();
                        if (kotakEl.top < kotakP.top || kotakEl.bottom > kotakP.bottom) {
                            p.scrollTop += (kotakEl.top - kotakP.top)
                                - (kotakP.height - kotakEl.height) / 2;
                        }
                    }
                    p = p.parentElement;
                }
                """, unsur)
        except Exception:  # noqa: BLE001 — gulir hanya upaya terbaik
            pass

    def _panel_periodik(self, peramban, peta: dict[str, str]):
        """Wadah «Data Periodik Peserta Didik» (``None`` bila tidak ada di halaman)."""
        for nilai in self._kandidat_selector("periodik_panel", peta):
            try:
                for unsur in peramban.find_elements(*self._locator_nilai(nilai)):
                    return unsur
            except Exception:  # noqa: BLE001 — coba kandidat berikutnya
                continue
        return None

    def _gulir_panel_periodik(self, peramban, peta: dict[str, str], catat: bool = True) -> bool:
        """Bawa panel Data Periodik ke layar — hanya panelnya, bukan seluruh halaman."""
        panel = self._panel_periodik(peramban, peta)
        if panel is None:
            return False
        self._bawa_ke_layar(peramban, panel)
        if catat:
            self._catat_kepala("[gulir] panel «Data Periodik Peserta Didik» dibawa ke layar "
                               "(hanya panelnya yang digulir, halaman lain tidak ikut).")
        return True

    def _cari_kolom_dengan_gulir(self, peramban, kunci: str, peta: dict[str, str]):
        """Cari kolom Data Periodik; bila belum ketemu, gulir 250 px lalu coba lagi.

        Kolom bisa belum tampil karena halaman belum digulir ke bagian Data Periodik —
        persis kekhawatiran pada skrip sekolah, karena itu gulirannya diulang beberapa kali
        sebelum bot memutuskan kolomnya memang tidak ada.
        """
        unsur = self._cari_kolom_dengan_label(peramban, kunci, peta)
        for _ in range(GULIR_PERCOBAAN):
            if unsur is not None:
                return unsur
            # Panelnya yang digulir dulu (area gulir sendiri), baru halaman sebagai pelengkap.
            self._gulir_panel_periodik(peramban, peta, catat=False)
            self._gulir(peramban, catat=False)
            # Beri waktu Ext JS menggambar barisnya sebelum dicari lagi: tanpa jeda, empat
            # percobaan gulir selesai dalam sekejap sementara barisnya belum dirender — dulu
            # itulah yang membuat bot melaporkan «kolom tidak ada» pada PC sekolah.
            self._tunggu(peramban, 1.2)
            unsur = self._cari_kolom_dengan_label(peramban, kunci, peta)
        return unsur

    def _kotak_jarak_dengan_gulir(self, peramban, peta: dict[str, str]) -> list[Any]:
        """Kotak «Jarak rumah ke sekolah»; bila belum terlihat, gulir dulu lalu cari lagi."""
        kotak = self._kandidat_kotak_jarak(peramban, peta)
        for _ in range(GULIR_PERCOBAAN):
            if kotak:
                return kotak
            self._gulir_panel_periodik(peramban, peta, catat=False)
            self._gulir(peramban, catat=False)
            self._tunggu(peramban, 1.2)      # beri waktu Ext JS menggambar baris «Jarak …»
            kotak = self._kandidat_kotak_jarak(peramban, peta)
        if not kotak:
            # Percobaan terakhir: satu kali lagi setelah menunggu — baris yang lambat dirender
            # sering baru muncul setelah panelnya benar-benar diam sejenak.
            self._tunggu(peramban, 2.0)
            kotak = self._kandidat_kotak_jarak(peramban, peta)
        return kotak

    def _rincian_unsur(self, peramban, unsur) -> str:
        """Keadaan satu kolom isian apa adanya (dipakai saat kolomnya gagal diisi).

        Inilah bukti yang dulu tidak ada di catatan sekolah: nama kolom, jenisnya, apakah
        ia read-only/nonaktif, dan nilai yang benar-benar ada di kolom itu. Dengan satu
        baris ini sebab kegagalan («RT belum berisi nilai yang benar») bisa ditelusuri
        tanpa menebak dan tanpa memotret layar.
        """
        if unsur is None:
            return "kolomnya tidak ketemu sama sekali di halaman ini"

        def atr(nama: str) -> str:
            try:
                return str(unsur.get_attribute(nama) or "")
            except Exception:  # noqa: BLE001 — keterangan tambahan saja
                return ""

        terlihat = "ya"
        try:
            terlihat = "ya" if self._terlihat(peramban, unsur) else "tidak"
        except Exception:  # noqa: BLE001
            terlihat = "?"
        return ("name=" + (atr("name") or "(tanpa nama)")
                + " · id=" + (atr("id") or "-")
                + " · type=" + (atr("type") or "-")
                + " · komponen=" + (atr("data-componentid") or "-")
                + " · nilai di kolom=" + repr(atr("value"))
                + " · readonly=" + ("ya" if atr("readonly") else "tidak")
                + " · nonaktif=" + ("ya" if atr("disabled") else "tidak")
                + " · terlihat=" + terlihat
                # Ronde 49: sertakan jenis kolom & nilai MODEL Ext JS-nya — inilah yang
                # disimpan Dapodik, jadi sebab «kotaknya benar, hasilnya «0»» terbaca.
                + " · " + self._rincian_jenis_kolom(peramban, unsur))

    def _rincian_kandidat_kolom(self, peramban, kunci: str, peta: dict[str, str]) -> str:
        """Berapa unsur yang ditemukan oleh TIAP kandidat selector kolom ini.

        Dipakai saat kolomnya tidak ketemu: dari sini terbaca kandidat mana yang meleset
        dan selector mana yang harus ditambahkan (mis. nama kolom yang berbeda di versi
        Dapodik sekolah) — bukan dengan menebak dari kode.
        """
        bagian: list[str] = []
        for nilai in self._kandidat_selector(kunci, peta):
            jumlah = 0
            try:
                if nilai.lower().startswith("label:"):
                    jumlah = 1 if self._cari_lewat_label(peramban, nilai.split(":", 1)[1]) else 0
                else:
                    jumlah = len(list(peramban.find_elements(*self._locator_nilai(nilai))))
            except Exception:  # noqa: BLE001 — kandidat berikutnya
                jumlah = -1
            tanda = {0: "0", -1: "galat"}.get(jumlah, str(jumlah))
            bagian.append(f"{nilai}={tanda}")
        return ", ".join(bagian)

    def _rincian_kolom_halaman(self, peramban, batas: int = 20) -> str:
        """Sebutkan kolom isian yang ADA di halaman (nama/keadaan) — bukti saat tak ketemu."""
        potong: list[str] = []
        try:
            from selenium.webdriver.common.by import By

            for elemen in peramban.find_elements(By.CSS_SELECTOR, "input, textarea, select"):
                jenis = ""
                nama = ""
                try:
                    jenis = str(elemen.get_attribute("type") or "").lower()
                except Exception:  # noqa: BLE001
                    jenis = ""
                if jenis in ("hidden", "button", "submit", "radio", "checkbox", "file", "image"):
                    continue
                try:
                    nama = str(elemen.get_attribute("name") or "").strip() or "(tanpa nama)"
                except Exception:  # noqa: BLE001
                    nama = "(tanpa nama)"
                potong.append(nama)
                if len(potong) >= batas:
                    break
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            return ""
        return ", ".join(potong)

    def _isi_periodik_satu(self, peramban, peta: dict[str, str], kunci: str, label: str,
                           nilai: str, unsur=None, awalan: str = "[periodik]") -> str:
        """Isi satu kolom isian (Ctrl+A lalu ketik, seperti potongan skrip sekolah).

        Dipakai untuk panel Data Periodik **dan** jendela «Ubah» (BIO): langkahnya sama —
        bawa kolom ke layar, tunggu aktif, Ctrl+A, ketik, lalu beri peristiwa
        input → change → blur, dengan cadangan lewat JavaScript dan Ext JS.
        """
        from selenium.webdriver.common.keys import Keys

        unsur = (unsur if unsur is not None
                 else self._cari_kolom_dengan_gulir(peramban, kunci, peta))
        if unsur is None:
            # Jujur + memberi bukti: kandidat apa saja yang dicoba, dan kolom apa yang ADA.
            self._catat_kepala(
                f"{awalan} {label}: kolomnya TIDAK ketemu di halaman ini — kandidat yang "
                f"dicoba: {self._rincian_kandidat_kolom(peramban, kunci, peta)}.")
            daftar = self._rincian_kolom_halaman(peramban)
            if daftar:
                self._catat_kepala(
                    f"{awalan} {label}: kolom isian yang ADA di halaman (nama): {daftar}")
            return "kolomnya tidak ada di halaman ini"
        # Kolom di bawah layar sering tidak menerima ketikan: bawa dulu ke layar
        # (menggulir wadahnya sendiri). Dapodik juga bisa MENONAKTIFKAN kolomnya sampai
        # langkah sebelumnya benar (mis. kolom km menunggu pilihan «lebih dari 1 km»), jadi
        # bot menunggu kolomnya aktif lebih dulu.
        self._bawa_ke_layar(peramban, unsur)
        if not self._tunggu_aktif(peramban, unsur):
            self._catat_kepala(f"{awalan} {label}: kolom masih nonaktif saat akan diisi — "
                               "dicoba apa adanya (Dapodik bisa mengabaikannya).")
        self._paksa_terlihat(peramban, unsur)
        try:                       # fokuskan dulu (klik sungguhan, bila tertelan → klik skrip)
            unsur.click()
        except Exception:  # noqa: BLE001 — lapisan pemuatan/popup bisa menelan klik
            try:
                peramban.execute_script("arguments[0].click();", unsur)
            except Exception:  # noqa: BLE001
                pass
        try:
            unsur.send_keys(Keys.CONTROL, "a")
            unsur.send_keys(nilai)
            # Persis skrip yang terbukti berhasil: setelah mengetik, Ext JS diberi tahu
            # lewat peristiwa input → change → blur. Tanpa ini nilainya bisa tidak "terbaca"
            # oleh Dapodik walaupun kotaknya sudah bertuliskan angka.
            self._picu_peristiwa(peramban, unsur)
        except Exception:  # noqa: BLE001 — lanjut ke pemeriksaan hasil
            pass
        isi = ""
        try:
            isi = str(unsur.get_attribute("value") or "").strip()
        except Exception:  # noqa: BLE001
            isi = ""
        # Penilaian memakai pembanding ANGKA juga: Dapodik menyimpan kolom seperti RT/RW
        # sebagai numberfield, jadi «007» dari data SM sah tersimpan sebagai «7» — dulu
        # perbandingan teks membuat kolom ini dilaporkan «belum berisi nilai yang benar»
        # (keluhan ronde 47: «masih gagal input rt dan rw»).
        sesuai, dinormalkan = self._isi_sesuai(nilai, isi)
        if not sesuai:      # sebagian kolom menolak ketikan langsung: isi lewat skrip
            try:
                self._isi_lewat_js(peramban, unsur, nilai)
                isi = str(unsur.get_attribute("value") or "").strip()
            except Exception:  # noqa: BLE001
                isi = ""
            sesuai, dinormalkan = self._isi_sesuai(nilai, isi)
        if not sesuai:
            # Jalur pamungkas Ext JS: nilainya dimasukkan ke model Ext JS lewat komponennya
            # sendiri (data-componentid → Ext.getCmp(...)), bukan hanya ke DOM.
            if self._set_ext(peramban, unsur, nilai=nilai):
                time.sleep(0.3)
                try:
                    isi = str(unsur.get_attribute("value") or "").strip()
                except Exception:  # noqa: BLE001
                    isi = ""
                sesuai, dinormalkan = self._isi_sesuai(nilai, isi)
                if sesuai:
                    # Ronde 45: nilai SETIAP kolom yang ditulis bot dicatat — kolom mana pun
                    # (bukan hanya kolom angka) bisa berubah bila digulir selagi kursornya
                    # ada di dalamnya.
                    self._rekam_nilai_bio(unsur, isi)
                    return f"terisi lewat Ext JS: {isi}{self._catatan_angka(nilai, isi, dinormalkan)}"
        if sesuai:
            # Nilai kolom dicatat: sesudah setiap gulir diperiksa lagi, karena gulir bisa
            # mengubah nilai kolom isian mana pun (mis. «RT» menjadi «0» — ronde 45).
            self._rekam_nilai_bio(unsur, isi)
            # Kolom angka: jangan berhenti di tulisan di kotaknya — Dapodik menyimpan dari
            # model Ext JS, jadi modelnya diperiksa (dan diperbaiki) sekarang juga (ronde 48).
            catatan_model = self._pastikan_model_angka(peramban, unsur, isi)
            imbuh = f" · model Ext JS {catatan_model}" if catatan_model else ""
            return (f"terisi: {isi}{self._catatan_angka(nilai, isi, dinormalkan)}{imbuh}")
        # Gagal mengisi: sebutkan keadaan kolomnya apa adanya (bukti, bukan tebakan).
        self._catat_kepala(
            f"{awalan} {label}: kolom belum berisi nilai yang benar — nilai diminta "
            f"{nilai!r}, keadaan kolom: {self._rincian_unsur(peramban, unsur)}")
        return "kolom belum berisi nilai yang benar"

    def _kotak_jarak(self, peramban, kunci: str, peta: dict[str, str]) -> list[Any]:
        """Kotak pilihan jarak untuk satu kunci selector.

        Yang dicari lebih dulu adalah yang **terlihat**, karena Dapodik menolak klik pada
        kolom yang belum tampil. Bila tidak satu pun terlihat, kandidat yang ada tetap
        dipakai (nanti dibawa ke layar lebih dulu) — daripada melaporkan «tidak ada di
        halaman ini» padahal kotaknya ada. Ini juga yang membuat log sekolah dulu berbunyi
        «kotak … tidak ada di halaman ini» padahal pilihannya terlihat oleh guru.
        """
        semua: list[Any] = []
        for nilai in self._kandidat_selector(kunci, peta):
            try:
                kotak = list(peramban.find_elements(*self._locator_nilai(nilai)))
            except Exception:  # noqa: BLE001 — coba kandidat berikutnya
                kotak = []
            for unsur in kotak:
                if unsur not in semua:
                    semua.append(unsur)
            terlihat = [unsur for unsur in kotak if self._terlihat(peramban, unsur)]
            if terlihat:
                return terlihat
        if semua:
            self._catat_kepala("[periodik] kotak «Jarak rumah ke sekolah» ditemukan tetapi "
                               "belum terlihat — dibawa ke layar dulu.")
        return semua

    def _kandidat_kotak_jarak(self, peramban, peta: dict[str, str]) -> list[Any]:
        """Kotak «Jarak rumah ke sekolah» — salah satu dari dua pilihan (kurang/lebih)."""
        for kunci in ("periodik_jarak_lebih", "periodik_jarak_kurang", "periodik_jarak"):
            kotak = self._kotak_jarak(peramban, kunci, peta)
            if kotak:
                return kotak
        return []

    def _terpilih(self, peramban, unsur) -> bool:
        """Apakah kotak centang/radio ini **benar-benar** terpilih (dibaca dari halaman).

        Tiga sumber dibaca karena Ext JS menyimpan keadaannya di beberapa tempat: properti
        ``checked`` milik input, kelas ``x-form-cb-checked`` pada pembungkusnya (inilah
        penanda yang terlihat pada DOM Dapodik: ``<div class="x-field ... x-form-cb-checked">``),
        dan atribut ``aria-checked``. Tanpa memeriksa ketiganya, bot bisa mengira pemilihannya
        gagal (atau sebaliknya) padahal keadaan sebenarnya berbeda.
        """
        try:
            if unsur.is_selected():
                return True
        except Exception:  # noqa: BLE001 — lanjut ke pemeriksaan berikutnya
            pass
        try:
            if bool(peramban.execute_script(
                    """
                    const el = arguments[0];
                    if (el.checked === true) return true;
                    const wadah = el.closest ? el.closest('.x-form-cb-checked') : null;
                    if (wadah) return true;
                    if (el.getAttribute && el.getAttribute('aria-checked') === 'true') return true;
                    return false;
                    """, unsur)):
                return True
        except Exception:  # noqa: BLE001 — lanjut ke pemeriksaan berikutnya
            pass
        try:
            return str(unsur.get_attribute("checked") or "").lower() in ("true", "checked", "1")
        except Exception:  # noqa: BLE001
            return False

    def _komponen_id(self, peramban, unsur) -> str:
        """Id komponen Ext JS untuk ``Ext.getCmp(...)``.

        Dicari berurutan: ``data-componentid`` milik unsurnya sendiri (itulah yang tertulis
        pada DOM sekolah: ``radiofield-1112``, ``numberfield-1113``) → ``id`` wadah
        ``.x-field`` terdekat → atribut ``for`` label di dekatnya (mis.
        ``for="radiofield-1112-inputEl"`` → ``radiofield-1112``).
        """
        try:
            nilai = peramban.execute_script(
                """
                /* komponen-id */
                const el = arguments[0];
                const bersih = (t) => (t || '').trim();
                const dari = el.getAttribute && el.getAttribute('data-componentid');
                if (bersih(dari)) return bersih(dari);
                const bidang = el.closest ? el.closest('.x-field[id]') : null;
                if (bidang && bersih(bidang.id)) return bersih(bidang.id);
                const label = (el.tagName === 'LABEL' && el.getAttribute('for'))
                    ? el
                    : (el.querySelector ? el.querySelector('label[for]') : null);
                if (label) {
                    const target = bersih(label.getAttribute('for')).replace(/-inputEl$/, '');
                    if (target) return target;
                }
                return '';
                """, unsur)
            return str(nilai or "").strip()
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            return ""

    def _keadaan_pilihan(self, peramban, unsur) -> dict[str, Any]:
        """Keadaan pilihan menurut DOM: sendiri tercentang? pasangan masih tercentang?

        Pada DOM sekolah, penanda tercentang adalah kelas ``x-form-cb-checked`` pada
        pembungkus ``div.x-field`` (input-nya tidak membawa atribut ``checked``). Untuk radio,
        pilihan dianggap benar hanya bila **penandanya sudah pindah** ke radio yang diminta
        dan radio pasangannya tidak lagi bertanda. Bila DOM berubah tetapi penandanya tidak
        pindah, nilai Ext JS-nya belum berubah — di situlah jalur ``Ext.getCmp`` diperlukan,
        sebab Dapodik baru mengaktifkan kolom kilometer setelah nilai Ext JS-nya berubah.
        """
        try:
            return dict(peramban.execute_script(
                """
                /* keadaan-pilihan */
                const el = arguments[0];
                const bertanda = (x) => !!(x && x.closest && x.closest('.x-form-cb-checked'));
                const sendiri = {
                    checked: el.checked === true,
                    kelas: bertanda(el),
                    aria: !!(el.getAttribute && el.getAttribute('aria-checked') === 'true'),
                };
                let pasangan = false;
                if (el.type === 'radio' && el.name) {
                    const daftar = document.querySelectorAll(
                        'input[type=radio][name="' + el.name + '"]');
                    for (const lain of daftar) {
                        if (lain === el) continue;
                        if (lain.checked === true || bertanda(lain) ||
                                (lain.getAttribute &&
                                 lain.getAttribute('aria-checked') === 'true')) {
                            pasangan = true;
                            break;
                        }
                    }
                }
                return {sendiri: sendiri, pasangan: pasangan};
                """, unsur) or {})
        except Exception:  # noqa: BLE001 — kembali ke pemeriksaan sederhana
            return {}

    def _penanda_dipakai(self, peramban) -> bool:
        """Apakah halaman ini memakai penanda ``x-form-cb-checked`` (ciri DOM Dapodik).

        Bila dipakai, **radio** dinilai dari penanda itu: kelas itulah tanda bahwa nilai Ext JS
        benar-benar berubah, dan Dapodik baru mengaktifkan kolom kilometer setelah itu. Versi
        Dapodik yang tidak memakai penanda tetap dinilai dari keadaan biasa.
        """
        try:
            return bool(peramban.execute_script(
                "/* penanda-dipakai */ return !!document.querySelector('.x-form-cb-checked');"))
        except Exception:  # noqa: BLE001 — anggap tidak dipakai
            return False

    def _terpilih_grup(self, peramban, unsur) -> bool:
        """Terpilih menurut penanda Ext JS (radio) dan bukan hanya perubahan tampilan.

        Pada DOM Dapodik, ``radiofield-1111`` yang terpilih ditandai kelas
        ``x-form-cb-checked`` pada pembungkus ``div.x-field``-nya. Klik yang hanya mengubah
        input (tanpa memindahkan penanda itu) berarti **model Ext JS belum berubah** — dan
        Dapodik tetap menonaktifkan kolom kilometer sampai modelnya benar.
        """
        keadaan = self._keadaan_pilihan(peramban, unsur)
        sendiri = (keadaan or {}).get("sendiri") or {}
        if not sendiri:
            return self._terpilih(peramban, unsur)
        radio = self._jenis_kotak(peramban, unsur) == "radio"
        if radio and self._penanda_dipakai(peramban):
            if not sendiri.get("kelas"):
                return False
            if (keadaan or {}).get("pasangan"):
                return False          # penandanya masih di pilihan lain
            return True
        if not (sendiri.get("checked") or sendiri.get("kelas") or sendiri.get("aria")):
            return False
        if radio and (keadaan or {}).get("pasangan"):
            return False
        return True

    def _set_ext(self, peramban, unsur, nilai=None, terpilih: bool = True) -> bool:
        """Pilih/isi lewat Ext JS sendiri: ``Ext.getCmp(id).setValue(...)``.

        Jalur pamungkas bila semua cara klik ditelan Dapodik: setiap unsur Ext JS punya
        ``data-componentid``, dan ``Ext.getCmp`` memberi komponennya langsung — jadi
        nilainya masuk ke model Ext JS (bukan hanya ke DOM).
        """
        komponen = self._komponen_id(peramban, unsur)
        if not komponen:
            return False
        try:
            return bool(peramban.execute_script(
                """
                if (typeof Ext === 'undefined' || !Ext.getCmp) return false;
                const c = Ext.getCmp(arguments[0]);
                if (!c) return false;
                c.setValue(arguments[1]);
                return true;
                """, komponen, nilai if nilai is not None else terpilih))
        except Exception:  # noqa: BLE001 — jalur ini hanya upaya tambahan
            return False

    def _kotak_lewat_teks(self, peramban, teks: str):
        """Kotak radio/centang yang dilacak lewat **teks pilihannya**, dibaca JavaScript.

        XPath bergantung pada tata letak Dapodik (``div[1]``, ``div[2]``, ``span/input``) yang
        bisa berbeda antar versi — dan bila XPath-nya meleset, bot lama berhenti dengan
        «kotak … tidak ada di halaman ini» padahal pilihannya jelas terlihat sekolah.
        Cara ini menelusuri label pilihannya langsung di DOM (``for`` → input, atau input di
        dalam ``.x-field`` yang sama), jadi tetap ketemu pada tata letak mana pun.
        """
        if not (teks or "").strip():
            return None
        try:
            return peramban.execute_script(
                """
                /* cari-kotak-teks */
                const cari = (arguments[0] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                if (!cari) return null;
                const normal = (t) => (t || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const kotakDari = (label) => {
                    const forId = label.getAttribute && label.getAttribute('for');
                    if (forId) {
                        let k = document.getElementById(forId);
                        if (!k && forId.endsWith('-inputEl')) {
                            k = document.getElementById(forId.slice(0, -8));
                        }
                        if (k) return k;
                    }
                    const wadah = (label.closest && label.closest('.x-field')) || label.parentElement;
                    if (wadah && wadah.querySelector) {
                        const k = wadah.querySelector('input[type=radio], input[type=checkbox]');
                        if (k) return k;
                    }
                    return null;
                };
                const labelSemua = document.querySelectorAll("label");
                let cadangan = null;
                for (const label of labelSemua) {
                    const t = normal(label.textContent);
                    if (!t) continue;
                    const pas = (t === cari) || t.includes(cari) || (cari.includes(t) && t.length > 3);
                    if (!pas) continue;
                    const k = kotakDari(label);
                    if (!k) continue;
                    if (t === cari) return k;          // yang persis lebih diutamakan
                    if (!cadangan) cadangan = k;
                }
                if (cadangan) return cadangan;
                for (const inp of document.querySelectorAll('input[type=radio], input[type=checkbox]')) {
                    const wadah = (inp.closest && inp.closest('.x-field')) || inp.parentElement;
                    const t = normal(wadah ? wadah.textContent : '');
                    if (t && t.includes(cari)) return inp;
                }
                return null;
                """, teks)
        except Exception:  # noqa: BLE001 — jalur tambahan saja
            return None

    def _label_lewat_teks(self, peramban, teks: str):
        """Label pilihan (``x-form-cb-label``) yang dilacak lewat teksnya, dibaca JavaScript."""
        if not (teks or "").strip():
            return None
        try:
            return peramban.execute_script(
                """
                /* label-teks */
                const cari = (arguments[0] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                if (!cari) return null;
                const normal = (t) => (t || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                let cadangan = null;
                for (const label of document.querySelectorAll("label")) {
                    const t = normal(label.textContent);
                    if (!t) continue;
                    let pas = (t === cari) || t.includes(cari);
                    if (!pas) continue;
                    if (label.offsetParent === null && label.getClientRects().length === 0) continue;
                    if (t === cari) return label;
                    if (!cadangan) cadangan = label;
                }
                return cadangan;
                """, teks)
        except Exception:  # noqa: BLE001 — jalur tambahan saja
            return None

    def _ringkas_panel(self, peramban, peta: dict[str, str]) -> str:
        """Ringkasan apa yang **benar-benar terlihat** di panel Data Periodik (untuk log).

        Dipakai saat pilihan jarak tidak ketemu: lebih berguna daripada diam-diam gagal,
        karena daftar ini menunjukkan apakah tata letak Dapodik sekolah memang berbeda.
        """
        try:
            panel = (peta.get("periodik_panel") or "").strip()
            return str(peramban.execute_script(
                """
                /* ringkas-panel */
                let wadah = null;
                if (arguments[0]) { try { wadah = document.evaluate(arguments[0], document,
                    null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; }
                    catch (e) { wadah = null; } }
                if (!wadah) wadah = document.body;
                const label = [];
                for (const l of wadah.querySelectorAll('label, .x-form-cb-label')) {
                    const t = (l.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (t && !label.includes(t)) label.push(t);
                    if (label.length >= 6) break;
                }
                const kolom = [];
                for (const i of wadah.querySelectorAll('input')) {
                    const n = i.getAttribute('name') || i.getAttribute('data-componentid') || i.type;
                    if (n && !kolom.includes(n)) kolom.push(n);
                    if (kolom.length >= 6) break;
                }
                const bagian = [];
                if (label.length) bagian.push('label: ' + label.join(' | '));
                if (kolom.length) bagian.push('kolom: ' + kolom.join(' | '));
                return bagian.join(' · ');
                """, panel) or "")
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            return ""

    def _set_ext_pilihan(self, peramban, unsur, nama: str = "", teks: str = "") -> str:
        """Setel pilihan lewat **model Ext JS** — bertingkat sampai nilainya benar berubah.

        1. ``Ext.getCmp(id).setValue(true)`` — id dari ``data-componentid``/``.x-field[id]``/
           label ``for="…-inputEl"``;
        2. bila komponen itu tidak ada: komponen radio ber-``name`` sama yang ``getBoxLabel()``
           memuat teks pilihannya (Dapodik kadang memindahkan komponennya);
        3. bila masih tidak ada: komponen radio mana pun yang teksnya memuat pilihan itu.

        Kembalikan keterangan singkat jalur yang dipakai ('' bila tidak ada yang berhasil).
        """
        komponen = self._komponen_id(peramban, unsur)
        nama_kolom = ""
        try:
            nama_kolom = str(unsur.get_attribute("name") or "").strip()
        except Exception:  # noqa: BLE001 — hanya untuk pencarian komponen
            nama_kolom = ""
        if komponen:
            try:
                if bool(peramban.execute_script(
                        """
                        if (typeof Ext === 'undefined' || !Ext.getCmp) return false;
                        const c = Ext.getCmp(arguments[0]);
                        if (!c || !c.setValue) return false;
                        c.setValue(arguments[1]);
                        return true;
                        """, komponen, True)):
                    keterangan = f"Ext.getCmp({komponen!r}).setValue"
                    if nama:
                        self._catat_kepala(f"[periodik] {nama}: dipilih lewat Ext JS sendiri "
                                           f"({keterangan}).")
                    return keterangan
            except Exception:  # noqa: BLE001 — lanjut ke pencarian komponen
                pass
        if not komponen and (teks or "").strip():
            # Tanpa id komponen, Ext.getCmp tidak bisa dipakai; jalur berikutnya masih ada
            # (pencarian komponen radio lewat Ext.ComponentQuery) — jadi tidak langsung gagal.
            if nama:
                self._catat_kepala(f"[periodik] {nama}: id komponen Ext JS tidak terbaca "
                                   "(data-componentid kosong) — dicari lewat Ext.ComponentQuery.")
        if (teks or "").strip():
            try:
                keterangan = str(peramban.execute_script(
                    """
                    /* ext-cari-pilihan */
                    if (typeof Ext === 'undefined' || !Ext.ComponentQuery) return '';
                    const teks = (arguments[0] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    const nama = arguments[1] || '';
                    const daftar = Ext.ComponentQuery.query(nama ? 'radio[name=' + nama + ']'
                                                                 : 'radio');
                    const kotak = (c) => (c.getBoxLabel ? String(c.getBoxLabel()) : '')
                        .replace(/\\s+/g, ' ').trim().toLowerCase();
                    let pakai = daftar.find((c) => kotak(c) === teks);
                    if (!pakai) pakai = daftar.find((c) => kotak(c).includes(teks));
                    if (!pakai) return '';
                    pakai.setValue(true);
                    return 'Ext.ComponentQuery radio' + (pakai.id ? ' ' + pakai.id : '') + '.setValue';
                    """, teks, nama_kolom) or "")
            except Exception:  # noqa: BLE001 — jalur tambahan saja
                keterangan = ""
            if keterangan:
                if nama:
                    self._catat_kepala(f"[periodik] {nama}: dipilih lewat Ext JS sendiri "
                                       f"({keterangan}).")
                return keterangan
        return ""

    def _teks_kotak(self, peramban, unsur) -> str:
        """Teks label pilihan milik sebuah kotak centang/radio (``x-form-cb-label`` Ext JS)."""
        try:
            teks = peramban.execute_script(
                """
                const el = arguments[0];
                const field = el.closest ? el.closest('.x-field') : null;
                const isi = field || el;
                const label = isi.querySelector ? isi.querySelector('.x-form-cb-label') : null;
                return label ? (label.textContent || '').trim() : '';
                """, unsur)
            return str(teks or "").strip()
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            return ""

    @staticmethod
    def _terlihat(peramban, unsur) -> bool:
        """Apakah unsurnya benar-benar tampil (keterangan tambahan, bukan penentu)."""
        try:
            return bool(unsur.is_displayed())
        except Exception:  # noqa: BLE001 — anggap tidak terbaca
            return False

    def _tunggu_aktif(self, peramban, unsur, detik: float = 6.0) -> bool:
        """Tunggu sampai kolomnya benar-benar aktif.

        Penting pada baris «Jarak rumah ke sekolah»: Dapodik **menonaktifkan** kolom
        «Sebutkan (dalam kilometer)» (``disabled``) sampai pilihan «lebih dari 1 km»
        terpasang, jadi mengetik sebelum itu tidak akan tersimpan.
        """
        akhir = time.time() + detik
        while True:
            try:
                if unsur.is_enabled():
                    return True
            except Exception:  # noqa: BLE001 — anggap belum aktif
                return False
            if time.time() >= akhir:
                return False
            time.sleep(0.3)

    @staticmethod
    def _label_unik(teks: str) -> bool:
        """Apakah teks pilihan ini cukup khas untuk diklik lewat labelnya.

        «lebih dari 1 km» hanya ada satu pada halaman sehingga aman diklik lewat labelnya
        (persis skrip yang terbukti berhasil). Sebaliknya «Ya» bisa muncul berkali-kali
        (tiap pertanyaan punya pasangan Ya/Tidak), jadi jalurnya lewat wadah
        ``x-form-cb-wrap-inner`` milik kotaknya sendiri agar tidak salah pilih.
        """
        bersih = " ".join((teks or "").split())
        if len(bersih.split()) >= 2:
            return True
        return bersih.lower() not in ("ya", "tidak", "iya")

    def _kandidat_label_pilihan(self, teks: str) -> list[str]:
        """XPath label pilihan — persis kandidat pada skrip yang terbukti berhasil.

        Skrip itu **tidak** mengklik kotak radio-nya, melainkan labelnya
        (``x-form-cb-label`` / ``<label>`` yang bertuliskan teks pilihannya), dan huruf
        besar/kecil disamakan lewat ``translate(..., "ABCDEFGHIJKLM", "abcdefghijklm")``.
        """
        bersih = " ".join((teks or "").split())
        if not bersih:
            return []
        aman = bersih.replace('"', "'")
        rendah = aman.lower()
        kandidat = [
            f'xpath://label[normalize-space()="{aman}"]',
            f'xpath://*[contains(@class, "x-form-cb-label") and normalize-space()="{aman}"]',
            f'xpath://label[contains(normalize-space(.), "{aman}")]',
            f'xpath://*[contains(@class, "x-form-cb-label") and '
            f'contains(normalize-space(.), "{aman}")]',
        ]
        if rendah != aman:
            kandidat += [
                'xpath://label[contains(translate(normalize-space(.), '
                f'"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{rendah}")]',
                'xpath://*[contains(@class, "x-form-cb-label") and contains(translate('
                'normalize-space(.), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", '
                f'"abcdefghijklmnopqrstuvwxyz"), "{rendah}")]',
            ]
        return kandidat

    def _label_pilihan(self, peramban, teks: str) -> list[Any]:
        """Label pilihan yang terlihat di halaman (cara skrip yang terbukti berhasil)."""
        label: list[Any] = []
        for nilai in self._kandidat_label_pilihan(teks):
            try:
                for unsur in peramban.find_elements(*self._locator_nilai(nilai)):
                    try:
                        if not unsur.is_displayed() or unsur in label:
                            continue
                    except Exception:  # noqa: BLE001 — periksa unsur berikutnya
                        continue
                    label.append(unsur)
            except Exception:  # noqa: BLE001 — coba kandidat berikutnya
                continue
        return label

    def _pembungkus_pilihan(self, peramban, unsur) -> list[Any]:
        """Pembungkus/label Ext JS di sekitar kotak centang/radio (bila ada)."""
        from selenium.webdriver.common.by import By

        pembungkus: list[Any] = []
        for xpath in ("ancestor-or-self::*[contains(@class, 'x-form-cb-wrap-inner')][1]",
                      "ancestor-or-self::*[contains(@class, 'x-form-cb-wrap')][1]",
                      "ancestor::label[1]"):
            try:
                pembungkus.extend(unsur.find_elements(By.XPATH, xpath))
            except Exception:  # noqa: BLE001 — coba cara berikutnya
                continue
        return pembungkus

    def _unsur_kotak(self, peramban, unsur):
        """Kotak centang/radio dari unsur yang ditemukan.

        Selector Dapodik kadang mengembalikan label atau wadahnya, bukan kotaknya
        (mis. ``//*[normalize-space()="Ya"]/preceding::input[@type="radio"][1]``). Supaya
        pemeriksaan "sudah terpilih belum" membaca unsur yang benar, kotaknya dilacak dulu.
        """
        from selenium.webdriver.common.by import By

        def jenis(nilai) -> str:
            try:
                return str(nilai.get_attribute("type") or "").lower()
            except Exception:  # noqa: BLE001
                return ""

        if jenis(unsur) in ("checkbox", "radio"):
            return unsur
        for xpath in ('preceding::input[@type="radio"][1]',
                      'preceding::input[@type="checkbox"][1]',
                      'following::input[@type="radio"][1]',
                      'following::input[@type="checkbox"][1]',
                      './/input[@type="radio" or @type="checkbox"][1]'):
            try:
                for kandidat in unsur.find_elements(By.XPATH, xpath):
                    if jenis(kandidat) in ("checkbox", "radio"):
                        return kandidat
            except Exception:  # noqa: BLE001 — coba cara berikutnya
                continue
        return unsur

    def _kotak_ya(self, peramban, peta: dict[str, str]) -> list[Any]:
        """Kotak pilihan «Ya» pada formulir Registrasi (semuanya, bila ada beberapa).

        Bila selector mengembalikan label/wadahnya, kotaknya dilacak dulu lewat
        ``_unsur_kotak`` supaya pemeriksaan terpilihnya membaca unsur yang benar.
        """
        nilai_daftar = [nilai for nilai in [(peta.get("radio_ya") or "").strip(),
                                            *SELECTOR_CADANGAN.get("radio_ya", [])] if nilai]
        for nilai in nilai_daftar:
            ditemukan: list[Any] = []
            try:
                for unsur in peramban.find_elements(*self._locator_nilai(nilai)):
                    kotak = self._unsur_kotak(peramban, unsur)
                    try:
                        if str(kotak.get_attribute("type") or "").lower() not in ("radio",
                                                                                  "checkbox"):
                            continue
                    except Exception:  # noqa: BLE001 — bukan kotak: lewati
                        continue
                    if kotak not in ditemukan:
                        ditemukan.append(kotak)
            except Exception:  # noqa: BLE001 — coba selector berikutnya
                continue
            if ditemukan:
                return ditemukan
        return []

    def _pilih_satu(self, peramban, unsur, nama: str, teks_label: str = "") -> bool:
        """Pilih satu kotak centang/radio sampai **benar-benar** terpilih.

        Penting: Ext JS/Dapodik sering **tidak menghiraukan** klik yang dikirim lewat skrip
        (``arguments[0].click()``) pada kotak centang/radio — perintahnya "berhasil" tetapi
        keadaan centangnya tidak berubah (inilah keluhan "bot masih gagal memilih radio").
        Karena itu setiap percobaan diperiksa ulang, lalu dicoba: klik sungguhan pada
        kotaknya → klik pembungkus/labelnya → urutan tetikus lengkap lewat skrip.
        """
        unsur = self._unsur_kotak(peramban, unsur)
        # Selector bisa mengembalikan kotak yang BUKAN kotak yang diminta (mis. cadangan
        # `input[name*=jarak]` mengembalikan «kurang dari 1 km» padahal yang diminta «lebih
        # dari 1 km»). Kotak yang jelas-jelas bertuliskan pilihan lain dilacak ulang lewat
        # teks labelnya — dibaca langsung oleh JavaScript, bukan XPath yang bisa meleset.
        if teks_label:
            teks_unsur = (self._teks_kotak(peramban, unsur) or "").lower()
            if teks_unsur and teks_label.lower() not in teks_unsur:
                kotak_benar = self._kotak_lewat_teks(peramban, teks_label)
                if kotak_benar is not None:
                    self._catat_kepala(f"[periodik] {nama}: kotak yang ditemukan bertuliskan "
                                       f"«{teks_unsur}» (bukan yang diminta) — kotak yang benar "
                                       "dilacak lewat teks labelnya.")
                    unsur = self._unsur_kotak(peramban, kotak_benar)
        if self._terpilih_grup(peramban, unsur):
            return True
        self._bawa_ke_layar(peramban, unsur)
        if teks_label:
            # Satu baris jelas: kotaknya ketemu, id komponennya terbaca atau tidak, dan urutan
            # percobaan yang akan dijalankan — supaya log bisa dibaca tanpa menebak.
            komponen_log = self._komponen_id(peramban, unsur)
            rincian = (f" (id komponen {komponen_log})" if komponen_log
                       else " (id komponen Ext JS tidak terbaca)")
            self._catat_kepala(f"[periodik] {nama}: kotaknya ditemukan{rincian} — dicoba klik "
                               "labelnya → kotaknya → pembungkusnya → Ext.getCmp.")
        # 1) Cara skrip yang terbukti berhasil: klik **labelnya** (bukan kotak radio-nya).
        #    Klik sungguhan dulu, bila tertelan baru klik lewat skrip — urutan persis itu.
        #    Hanya untuk teks yang khas (lihat _label_unik): «Ya» dicari lewat wadahnya.
        label_kandidat: list[Any] = []
        if self._label_unik(teks_label):
            label_kandidat = self._label_pilihan(peramban, teks_label)
            if not label_kandidat and (teks_label or "").strip():
                # XPath label bisa tidak cocok pada tata letak Dapodik yang berbeda:
                # labelnya dicari langsung oleh JavaScript (teks pilihan → label → kotaknya).
                label_js = self._label_lewat_teks(peramban, teks_label)
                if label_js is not None:
                    self._catat_kepala(f"[periodik] {nama}: label pilihannya ditemukan lewat "
                                       "teksnya (JavaScript) — XPath label tidak cocok.")
                    label_kandidat = [label_js]
        for label in label_kandidat:
            self._bawa_ke_layar(peramban, label)
            time.sleep(0.3)
            try:
                label.click()
            except Exception:  # noqa: BLE001 — coba klik lewat skrip
                pass
            time.sleep(0.3)
            if self._terpilih_grup(peramban, unsur):
                self._catat_kepala(f"[periodik] {nama}: dipilih lewat labelnya "
                                   "(x-form-cb-label) — sama seperti skrip yang berhasil.")
                return True
            try:
                peramban.execute_script("arguments[0].click();", label)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
            if self._terpilih_grup(peramban, unsur):
                self._catat_kepala(f"[periodik] {nama}: dipilih lewat labelnya "
                                   "(klik skrip) — sama seperti skrip yang berhasil.")
                return True
        pembungkus = self._pembungkus_pilihan(peramban, unsur)
        try:                       # 2) klik sungguhan pada kotaknya
            unsur.click()
        except Exception:  # noqa: BLE001 — coba cara berikutnya
            pass
        time.sleep(0.3)
        if self._terpilih_grup(peramban, unsur):
            return True
        for calon in pembungkus:   # 2) klik pembungkus/labelnya (cara Ext JS)
            try:
                calon.click()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
            if self._terpilih_grup(peramban, unsur):
                self._catat_kepala(f"[periodik] {nama}: dipilih lewat pembungkus/label "
                                   "kolomnya (klik pada kotaknya sendiri tidak diterima).")
                return True
        for calon in [unsur, *pembungkus]:   # 3) klik lewat skrip (input-nya sendiri)
            try:
                peramban.execute_script("arguments[0].click();", calon)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
            if self._terpilih_grup(peramban, unsur):
                self._catat_kepala(f"[periodik] {nama}: dipilih lewat klik skrip pada "
                                   f"{'kotaknya' if calon is unsur else 'pembungkusnya'}.")
                return True
        for calon in [unsur, *pembungkus]:   # 4) urutan tetikus lengkap lewat skrip
            try:
                peramban.execute_script(
                    """
                    const el = arguments[0];
                    for (const tipe of ['mousedown', 'mouseup', 'click']) {
                        el.dispatchEvent(new MouseEvent(tipe, {bubbles: true, cancelable: true,
                                                              view: window}));
                    }
                    """, calon)
            except Exception:  # noqa: BLE001
                continue
            time.sleep(0.3)
            if self._terpilih_grup(peramban, unsur):
                self._catat_kepala(f"[periodik] {nama}: dipilih lewat urutan tetikus skrip.")
                return True
        # 5) Semua klik belum berhasil — dan pada DOM Dapodik inilah yang sering terjadi:
        #    tampilannya berubah (input.checked) tetapi penanda `x-form-cb-checked` tetap di
        #    pilihan lama, jadi **model Ext JS** belum berubah dan Dapodik masih menonaktifkan
        #    kolom kilometer. Karena itu jalur Ext JS dipakai SEKARANG, dengan keterangan
        #    yang jelas — bukan sebagai pilihan terakhir tanpa penjelasan.
        keadaan = self._keadaan_pilihan(peramban, unsur)
        sendiri = (keadaan or {}).get("sendiri") or {}
        if sendiri and (sendiri.get("checked") or sendiri.get("aria")):
            self._catat_kepala(f"[periodik] {nama}: tampilan sudah berubah tetapi nilai Ext JS "
                               "belum (penanda x-form-cb-checked masih di pilihan lain) — "
                               "dipakai Ext.getCmp.")
        else:
            self._catat_kepala(f"[periodik] {nama}: semua klik belum mengubah nilai Ext JS — "
                               "dipakai Ext.getCmp (jalur pamungkas).")
        if self._set_ext_pilihan(peramban, unsur, nama, teks_label):
            time.sleep(0.3)
            # Setelah Ext JS menyetel nilainya, DOM yang benar-benar berubah sudah cukup
            # sebagai bukti — walau versi Dapodik tertentu tidak memakai penanda kelas.
            if self._terpilih_grup(peramban, unsur) or self._terpilih(peramban, unsur):
                return True
        self._catat_kepala(f"[periodik] {nama}: nilai Ext JS belum berubah juga — pilihan ini "
                           "belum terpasang (mungkin perlu diklik manual sekali).")
        return self._terpilih_grup(peramban, unsur)

    def _pilih_jarak(self, peramban, peta: dict[str, str], jarak_km: str) -> tuple[str, bool]:
        """Pilih «kurang dari 1 km» / «lebih dari 1 km» sesuai data jarak siswa.

        Dapodik menyediakan **dua** pilihan pada baris «Jarak rumah ke sekolah»; skrip
        sekolah selalu memakai pilihan **lebih dari 1 km** (``td/div[2]``). Bot memilih
        yang sesuai: jarak ≤ 1 km → «kurang dari 1 km» (``td/div[1]``), lebih dari itu →
        «lebih dari 1 km». Bila yang sesuai tidak ada di halaman, dipakai selector bawaan
        skrip sekolah (``periodik_jarak``).
        """
        if not str(jarak_km or "").strip():
            # Tidak ada data jarak: jangan menebak pilihan apa pun.
            return ("kotak «Jarak rumah ke sekolah» tidak dicentang — data jarak siswa kosong",
                    False)
        try:
            angka = float(str(jarak_km).replace(",", "."))
        except (TypeError, ValueError):
            angka = 0.0
        lebih_dari = angka > 1.0
        kunci = "periodik_jarak_lebih" if lebih_dari else "periodik_jarak_kurang"
        nama_pilihan = "lebih dari 1 km" if lebih_dari else "kurang dari 1 km"

        teks_pilihan = "lebih dari 1 km" if lebih_dari else "kurang dari 1 km"
        kotak = self._kotak_jarak(peramban, kunci, peta)
        if not kotak:
            kotak = self._kotak_jarak(peramban, "periodik_jarak", peta)
            nama_pilihan += " (memakai selector bawaan skrip sekolah)"
        # Selector bisa mengembalikan satu radio yang SALAH (mis. cadangan `name*=jarak`
        # mengembalikan «kurang dari 1 km» padahal datanya lebih dari 1 km). Kandidat yang
        # teksnya terbaca dan tidak cocok dibuang — jangan sampai bot memilih yang keliru.
        teks_kandidat = [(unsur, self._teks_kotak(peramban, unsur) or "") for unsur in kotak]
        cocok = [unsur for unsur, teks in teks_kandidat if teks_pilihan in teks.lower()]
        if cocok:
            if len(cocok) < len(kotak):
                nama_pilihan += f" [disaring dari {len(kotak)} kandidat lewat teks labelnya]"
            kotak = cocok
        elif kotak and any(teks.strip() for _, teks in teks_kandidat):
            kotak = []          # semua kandidat bertuliskan pilihan yang lain
        if not kotak:
            # XPath bisa meleset (Dapodik mengubah tata letak): kotaknya dilacak lewat teks
            # pilihannya — dibaca langsung oleh JavaScript, tidak bergantung XPath.
            kotak_js = self._kotak_lewat_teks(peramban, teks_pilihan)
            if kotak_js is not None:
                kotak = [kotak_js]
                nama_pilihan += " [kotaknya dilacak lewat teks labelnya]"
        if not kotak:
            # Tidak ada pilihan yang bisa dipakai — laporkan apa yang benar-benar terlihat di
            # panel (bukan menebak), supaya jelas bila tata letak Dapodik sekolah berbeda.
            rincian = self._ringkas_panel(peramban, peta)
            pesan = "kotak «Jarak rumah ke sekolah» tidak ada di halaman ini"
            if rincian:
                pesan += f" — yang terlihat di panel: {rincian}"
            return (pesan, False)

        dicentang = 0
        for unsur in kotak:
            if self._pilih_satu(peramban, unsur, f"pilihan jarak «{nama_pilihan}»",
                                teks_pilihan):
                dicentang += 1
        # Jangan sampai kedua pilihan tercentang: pilihan lain dikosongkan lagi — **hanya
        # untuk kotak centang**. Pada radio, mengklik pilihan lain justru membatalkan pilihan
        # yang baru saja dipasang.
        for kunci_lain in ("periodik_jarak_kurang", "periodik_jarak_lebih"):
            if kunci_lain == kunci:
                continue
            for unsur in self._kotak_jarak(peramban, kunci_lain, peta):
                if self._jenis_kotak(peramban, unsur) == "radio":
                    continue
                if self._terpilih(peramban, unsur):
                    try:
                        unsur.click()
                    except Exception:  # noqa: BLE001 — biarkan
                        pass
                    time.sleep(0.3)
        berhasil = bool(kotak) and dicentang == len(kotak)
        pesan = (f"kotak «Jarak rumah ke sekolah» ({nama_pilihan}) dicentang: "
                 f"{dicentang} dari {len(kotak)}")
        if not berhasil:
            pesan += (" — peringatan: Dapodik belum menandainya terpilih "
                      "(mungkin perlu diklik manual sekali).")
        return pesan, berhasil

    @staticmethod
    def _jenis_kotak(peramban, unsur) -> str:
        """Jenis kotak: ``radio``/``checkbox`` (dari atribut type)."""
        try:
            return str(unsur.get_attribute("type") or "").lower()
        except Exception:  # noqa: BLE001
            return ""

    def _isi_jarak_km(self, peramban, peta: dict[str, str], nilai: str) -> str:
        """Isi kolom «Sebutkan (dalam kilometer):» di baris «Jarak rumah ke sekolah».

        Namanya di Dapodik: ``jarak_rumah_ke_sekolah_km``. Nilainya jarak (km) dari data
        siswa SM. Nama kolom ikut dicatat pada log supaya mudah diperiksa.
        """
        unsur = self._cari_kolom_dengan_gulir(peramban, "periodik_jarak_km", peta)
        if unsur is not None:
            try:      # kotak centang/radio bukan kolom isian kilometer
                if str(unsur.get_attribute("type") or "").lower() in ("checkbox", "radio"):
                    unsur = None
            except Exception:  # noqa: BLE001 — tidak terbaca: biarkan
                pass
        if unsur is None:
            return "kolom «Sebutkan (dalam kilometer)» tidak ada di halaman ini"
        nama = ""
        try:
            nama = str(unsur.get_attribute("name") or "").strip()
        except Exception:  # noqa: BLE001 — nama kolom hanya untuk log
            nama = ""
        tanda = f" [{nama}]" if nama else ""
        keterangan = self._isi_periodik_satu(peramban, peta, "periodik_jarak_km",
                                             "Sebutkan (dalam kilometer)", nilai, unsur)
        return f"{tanda}: {keterangan}" if keterangan.startswith("terisi") else keterangan

    # ------------------------------------------------------ jendela «Ubah» (BIO) --- #
    def _jendela_edit(self, peramban, peta: dict[str, str] | None = None):
        """Jendela «Edit Peserta Didik» yang **sedang terbuka** (None bila belum ada).

        Pada halaman sekolah ada lebih dari satu tombol «Ubah» (toolbar halaman *dan* panel
        «Data Rincian PD» di bawahnya — lihat tangkapan layar sekolah). Karena itu bot tidak
        menganggap tombol «Ubah» mana pun benar: setelah menekannya, bot memastikan
        jendela inilah yang benar-benar tampil.
        """
        nama_kolom = ",".join(self._nama_kolom_bio_semua(peta or {}))
        hasil = None
        try:
            hasil = peramban.execute_script(
                """
                /* jendela-edit */
                const tampil = (w) => !!(w && w.getClientRects && w.getClientRects().length);
                const naik = (el) => {
                    let p = el, n = 0;
                    while (p && n < 12) {
                        if (p.matches && (p.matches('.x-window') || p.matches('.x-panel') ||
                                          p.matches('.x-container'))) return p;
                        p = p.parentElement; n += 1;
                    }
                    return el;
                };
                // (a) jendela Ext JS dengan judul «Edit Peserta Didik»
                for (const w of document.querySelectorAll('div.x-window')) {
                    if (!tampil(w)) continue;
                    const judul = w.querySelector('.x-title-text');
                    const teks = ((judul ? judul.textContent : '') + ' ' +
                                  (w.textContent || '')).replace(/\\s+/g, ' ').trim();
                    if (/Edit Peserta Didik/i.test(teks)) return w;
                }
                // (b) judulnya ada di tempat lain (mis. formulirnya berupa PANEL, bukan jendela
                //     melayang): judul dilacak ke wadah yang benar-benar memuat kolom isian.
                for (const j of document.querySelectorAll(
                        '.x-title-text, .x-title, .x-panel-header-title, .x-header-text')) {
                    const t = (j.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!/Edit Peserta Didik/i.test(t)) continue;
                    const wadah = naik(j);
                    if (wadah && wadah.querySelector && wadah.querySelector('input')) return wadah;
                }
                // (c) kolom BIO-nya sendiri (nama kolom dari skrip sekolah): wadahnya dipakai
                //     sebagai batas pencarian — tetap bekerja walau judulnya tidak terbaca.
                const daftar = (arguments[0] || '').split(',').map((x) => x.trim()).filter(Boolean);
                for (const n of daftar) {
                    const k = document.querySelector('input[name="' + n + '"]');
                    if (k && tampil(k)) return naik(k);
                }
                return null;
                """, nama_kolom)
        except Exception:  # noqa: BLE001 — dianggap belum ada
            hasil = None
        if hasil is not None:
            return hasil
        # Cadangan: selector «bio_jendela» (dapat diubah sekolah di «Peta tombol Dapodik»).
        if peta:
            for nilai in self._kandidat_selector("bio_jendela", peta):
                try:
                    for unsur in peramban.find_elements(*self._locator_nilai(nilai)):
                        if not self._terlihat(peramban, unsur):
                            continue
                        judul = (self._judul_jendela(peramban, unsur) or "").lower()
                        if "edit peserta didik" in judul:
                            return unsur
                except Exception:  # noqa: BLE001 — coba kandidat berikutnya
                    continue
        return None

    def _judul_jendela(self, peramban, jendela) -> str:
        """Judul jendela (untuk log) — mis. «Edit Peserta Didik : AALI …»."""
        try:
            teks = peramban.execute_script(
                """
                /* judul-jendela */
                const w = arguments[0];
                if (!w) return '';
                const j = w.querySelector('.x-title-text');
                return ((j ? j.textContent : w.textContent) || '')
                    .replace(/\\s+/g, ' ').trim().slice(0, 80);
                """, jendela)
            return str(teks or "")
        except Exception:  # noqa: BLE001 — judul hanya untuk log
            return ""

    def _tombol_ubah_semua(self, peramban, peta: dict[str, str]) -> list[Any]:
        """Semua tombol «Ubah» yang terlihat, **yang di luar panel «Data Rincian» lebih dulu**.

        Tombol «Ubah» milik panel «Data Rincian PD» tidak membuka jendela «Edit Peserta
        Didik»; menekannya dahulu membuat bot melaporkan gagal walaupun tombol yang benar ada.
        Urutan ini hanya dugaan terbaik — bot tetap **memverifikasi** tiap kandidat.
        """
        kandidat: list[Any] = []
        try:
            hasil = peramban.execute_script(
                """
                /* ubah-kandidat */
                const tampil = (el) => !!(el && el.getClientRects && el.getClientRects().length);
                const dalamRincian = (el) => {
                    let p = el, naik = 0;
                    while (p && naik < 8) {
                        if (p.classList && (p.classList.contains('x-panel') ||
                                            p.classList.contains('x-toolbar'))) {
                            if (/Data Rincian/i.test(p.textContent || '')) return true;
                        }
                        p = p.parentElement; naik += 1;
                    }
                    return false;
                };
                const kumpul = [];
                const dilihat = new Set();
                for (const el of document.querySelectorAll('span, a, button')) {
                    const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (t !== 'Ubah') continue;
                    if (!tampil(el)) continue;
                    const inti = (el.closest && el.closest('.x-btn')) || el;
                    if (dilihat.has(inti)) continue;
                    dilihat.add(inti);
                    kumpul.push({ el: inti, rincian: dalamRincian(inti) });
                }
                kumpul.sort((a, b) => (a.rincian ? 1 : 0) - (b.rincian ? 1 : 0));
                return kumpul.map((k) => k.el);
                """) or []
            kandidat.extend(hasil)
        except Exception:  # noqa: BLE001 — pakai cadangan selector di bawah
            kandidat = []
        if not kandidat:          # versi Dapodik lain: pakai selector seperti biasa
            for nilai in self._kandidat_selector("bio_ubah", peta):
                try:
                    for unsur in peramban.find_elements(*self._locator_nilai(nilai)):
                        if self._terlihat(peramban, unsur) and unsur not in kandidat:
                            kandidat.append(unsur)
                except Exception:  # noqa: BLE001 — coba kandidat berikutnya
                    continue
        return kandidat

    def _nama_kolom_bio_semua(self, peta: dict[str, str]) -> list[str]:
        """Semua nama kolom Dapodik untuk BIO (dari selector; mis. «name:no_kk» → «no_kk»)."""
        nama: list[str] = []
        for _, _, kunci in self.BIO_KOLOM:
            nilai = self._nama_kolom_selector(kunci, peta)
            if nilai and nilai not in nama:
                nama.append(nilai)
        return nama

    def _nama_kolom_selector(self, kunci: str, peta: dict[str, str]) -> str:
        """Nama kolom Dapodik dari kandidat selector (mis. «name:no_kk» → «no_kk»)."""
        for nilai in self._kandidat_selector(kunci, peta):
            if nilai.lower().startswith("name:"):
                return nilai[5:].strip()
        return ""

    def _kolom_dalam_jendela(self, peramban, jendela, nama_kolom: str, teks_label: str):
        """Cari kolom **di dalam jendela** (bukan di halaman) lewat nama & labelnya.

        Penting supaya bot tidak mengisi kolom lain yang kebetulan bernama sama di halaman,
        dan supaya pencariannya mengikuti isi jendelanya (yang punya area gulir sendiri).
        """
        if jendela is None:
            return None
        try:
            hasil = peramban.execute_script(
                """
                /* kolom-jendela */
                const root = arguments[0];
                const nama = (arguments[1] || '').trim();
                const cari = (arguments[2] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                if (!root) return null;
                const tampil = (el) => !!(el && el.getClientRects && el.getClientRects().length);
                const rapi = (t) => String(t || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const bersih = (t) => rapi(t).replace(/[*:\\u00a0]+$/, '').trim();
                const isianDalam = (bidang) => {
                    // Kolom di dalam SATU bidang (.x-field) — supaya label RT tidak
                    // mengambil kotak RW bila keduanya berada di baris yang sama.
                    if (!bidang) return null;
                    for (const k of bidang.querySelectorAll('input, textarea, select')) {
                        const jenis = String(k.getAttribute('type') || '').toLowerCase();
                        if (jenis === 'hidden' || jenis === 'button' || jenis === 'submit') continue;
                        if (tampil(k)) return k;
                    }
                    return null;
                };
                if (nama) {
                    for (const k of root.querySelectorAll('input[name="' + nama + '"]')) {
                        if (tampil(k)) return {el: k, lewat: 'nama'};
                    }
                }
                if (cari) {
                    // Labelnya bisa berupa <label> ATAU digambar sebagai div Ext JS
                    // (`.x-fieldlabel` / `.x-form-item-label`) — di sebagian versi Dapodik
                    // hanya cara kedua yang ada (laporan ronde 47).
                    const labelnya = root.querySelectorAll(
                        'label, .x-fieldlabel, .x-form-item-label, .x-form-item-label-default');
                    for (const l of labelnya) {
                        const t = bersih(l.textContent);
                        if (!t || (t !== cari && !t.startsWith(cari))) continue;
                        // Label yang digambar sebagai DIV Ext JS (bukan elemen <label>) —
                        // keadaan yang dilaporkan sekolah ronde 47 (RT, RW, Desa/Kelurahan).
                        const labelDiv = !(l.tagName || '').toUpperCase().startsWith('LABEL');
                        const forId = l.getAttribute('for');
                        const lewatId = forId ? document.getElementById(forId) : null;
                        if (lewatId && tampil(lewatId)) {
                            return {el: lewatId, lewat: labelDiv ? 'label-div' : 'label'};
                        }
                        const bidang = l.closest('.x-field, .x-form-item');
                        const k = isianDalam(bidang) || isianDalam(l.parentElement);
                        if (k) return {el: k, lewat: labelDiv ? 'label-div' : 'label'};
                    }
                }
                return null;
                """, jendela, nama_kolom, teks_label)
        except Exception:  # noqa: BLE001 — pemanggil memakai pencarian cadangan
            return None
        if isinstance(hasil, dict):
            lewat = str(hasil.get("lewat") or "")
            if lewat == "label-div":
                # Jujur soal jalurnya: labelnya bukan elemen <label> melainkan div Ext JS —
                # inilah yang bikin kolom (RT, RW, Desa/Kelurahan, …) dulu «tidak ketemu».
                self._catat_kepala(
                    f"[bio] {teks_label or nama_kolom}: kolomnya ditemukan lewat labelnya yang "
                    "berbentuk div Ext JS (`.x-fieldlabel`) — bukan elemen <label>; versi "
                    "Dapodik seperti ini tidak terjangkau pencarian label biasa.")
            return hasil.get("el")
        return hasil

    def _atur_gulir_jendela(self, peramban, jendela, ke: int = 0) -> int:
        """Kembalikan **isi jendela** ke posisi gulir tertentu (bawaan: paling atas).

        Skrip sekolah mengisi kolom BIO dari atas ke bawah, jadi bot mulai dari atas pula:
        tiap kolom dicari sambil isi jendela digeser bertahap. Ini juga menanggulangi
        "gulir kebanyakan/kurang banyak" — posisinya selalu diatur ulang di awal.
        """
        self._kursor_aman(peramban, jendela, awalan="[bio]")
        try:
            return int(peramban.execute_script(
                """
                /* gulir-jendela-awal */
                const akar = arguments[0];
                const tujuan = arguments[1] || 0;
                if (!akar) return 0;
                let jumlah = 0;
                const atur = (el) => {
                    if (!el || !el.scrollHeight) return;
                    const gaya = getComputedStyle(el);
                    if ((gaya.overflowY === 'auto' || gaya.overflowY === 'scroll') &&
                            el.scrollHeight > el.clientHeight + 4) {
                        el.scrollTop = tujuan;
                        jumlah += 1;
                    }
                };
                atur(akar);
                for (const el of akar.querySelectorAll('div')) atur(el);
                return jumlah;
                """, jendela, int(ke)) or 0)
        except Exception:  # noqa: BLE001 — pengaturan gulir hanya upaya terbaik
            return 0

    def _gulir_dalam_jendela(self, peramban, jendela, langkah: int = GULIR_PERIODIK) -> int:
        """Geser **isi jendela** sebesar ``langkah`` piksel; kembalikan berapa yang bergeser.

        Menggulir halaman (``window.scrollBy``) tidak menolong untuk jendela yang punya area
        gulir sendiri — persis yang terlihat pada tangkapan layar sekolah. Karena itu bot
        menggeser wadah bergulir di dalam jendelanya, sedikit demi sedikit, dan **setiap kali**
        mencoba mencari kolomnya lagi (tidak menebak-nebak "250 px cukup atau tidak").

        Kursornya ditaruh pada wadah jendelanya lebih dulu (bukan di dalam kolom isian),
        lalu nilai kolom yang sudah ditulis diperiksa lagi — gulir jangan sampai mengubahnya.
        """
        self._kursor_aman(peramban, jendela, awalan="[bio]")
        bergeser = 0
        try:
            bergeser = int(peramban.execute_script(
                """
                /* gulir-jendela */
                const akar = arguments[0];
                const langkah = arguments[1] || 250;
                if (!akar) return 0;
                const kandidat = [];
                const periksa = (el) => {
                    if (!el || !el.scrollHeight) return;
                    const gaya = getComputedStyle(el);
                    if ((gaya.overflowY === 'auto' || gaya.overflowY === 'scroll') &&
                            el.scrollHeight > el.clientHeight + 4) kandidat.push(el);
                };
                periksa(akar);
                for (const el of akar.querySelectorAll('div')) periksa(el);
                if (!kandidat.length) return 0;
                // Utamakan wadah yang benar-benar memuat kolom isian (bukan bilah bantu):
                // kalau ada beberapa, geser semuanya supaya tidak ada bagian yang terlewat.
                const berisi = kandidat.filter((el) => el.querySelector && el.querySelector('input'));
                const daftar = berisi.length ? berisi : kandidat;
                let bergeser = 0;
                for (const isi of daftar) {
                    const sebelum = isi.scrollTop;
                    isi.scrollTop = Math.min(isi.scrollTop + langkah, isi.scrollHeight);
                    bergeser += isi.scrollTop - sebelum;
                }
                return bergeser;
                """, jendela, int(langkah)) or 0)
        except Exception:  # noqa: BLE001 — 0 = tidak bergeser
            bergeser = 0
        if bergeser:
            self._periksa_nilai_bio(peramban)
        return bergeser

    def _cari_kolom_bio(self, peramban, peta: dict[str, str], kunci: str, jendela,
                        teks_label: str = ""):
        """Kolom jendela «Ubah»: dicari di dalam jendela, sambil isi jendela digulir bertahap.

        Isi jendela digeser sedikit demi sedikit dan **setiap kali** dicoba dicari lagi —
        jadi tidak ada tebakan "gulir 250 px cukup atau tidak". Bila isi jendelanya sudah
        mentok (tidak bergeser lagi), halaman ikut digulir sebagai pelengkap, lalu kolomnya
        dicari sekali lagi; sesudah itu barulah bot menyimpulkan kolomnya tidak ada.
        """
        nama_kolom = self._nama_kolom_selector(kunci, peta)
        mentok = 0
        geser_halaman = 0
        for _ in range(GULIR_PERCOBAAN + 8):
            if jendela is not None:
                unsur = self._kolom_dalam_jendela(peramban, jendela, nama_kolom, teks_label)
                if unsur is not None:
                    return unsur
                bergeser = self._gulir_dalam_jendela(peramban, jendela)
            else:
                # Wadah jendela tidak terbaca oleh JavaScript: kolomnya dicari lewat namanya
                # — persis ``find_element(By.NAME, …)`` skrip sekolah — lalu halaman digeser
                # 250 px dan kolomnya dicari lagi, seperti Selenium yang menggeser layar saat
                # mengetik. Jadi jalur ini tidak bergantung pada wadah jendelanya.
                unsur = self._kolom_global(peramban, nama_kolom, teks_label)
                if unsur is not None:
                    if not getattr(self, "_bio_global_dilaporkan", False):
                        self._bio_global_dilaporkan = True
                        self._catat_kepala(
                            f"[bio] {teks_label or nama_kolom}: kolomnya ditemukan lewat "
                            "namanya di halaman (cara skrip sekolah) — jendela «Ubah» tidak "
                            f"terbaca, halaman digeser 250 px bertahap ({geser_halaman}x).")
                    return unsur
                if geser_halaman >= GULIR_PERCOBAAN:
                    return None
                geser_halaman += 1
                if not getattr(self, "_bio_gulir_dilaporkan", False):
                    self._bio_gulir_dilaporkan = True
                    self._catat_kepala(
                        "[bio] jendela «Ubah» tidak terbaca oleh JavaScript — kolomnya "
                        "dilacak lewat namanya di seluruh halaman, dan tiap kali belum tampil "
                        "halaman digeser 250 px lalu dicari lagi (cara skrip sekolah memakai "
                        "Selenium).")
                self._gulir(peramban, catat=False)
                self._tunggu(peramban, 0.6)
                continue
            if bergeser:
                # Beri waktu Ext JS menggambar baris berikutnya sebelum kolomnya dicari lagi.
                self._tunggu(peramban, 0.6)
                continue
            mentok += 1
            # Isi jendela sudah mentok (atau jendelanya tidak bisa dikenali). Sekarang kolomnya
            # dicari dengan **CARA SKRIP SEKOLAH**: `find_element(By.NAME, …)` di seluruh
            # halaman — inilah yang selama ini terbukti berhasil di PC sekolah, jadi dipakai
            # sebagai cadangan, bukan ditinggalkan.
            global_unsur = self._kolom_global(peramban, nama_kolom, teks_label)
            if global_unsur is not None:
                self._catat_kepala(f"[bio] {teks_label or nama_kolom}: kolomnya ditemukan lewat "
                                   "namanya di halaman (cara skrip sekolah) — jendelanya "
                                   "dipakai sebagai batas bila terbaca.")
                return global_unsur
            # Halaman digulir sebagai pelengkap (Selenium pun menggeser layar saat mengetik) —
            # sekali saja, supaya bot tidak menggantung pada kolom yang memang tidak ada.
            if mentok == 1:
                self._gulir(peramban, catat=False)
                self._tunggu(peramban, 0.6)
                continue
            break
        # Jalur terakhir sebelum menyerah: kandidat selector yang hanya bisa diselesaikan
        # sendiri (mis. XPath lengkap yang dikirim sekolah untuk kolom combo «Desa/Kelurahan»)
        # dan pelacakan combo lewat label yang bukan elemen <label> (div ``.x-fieldlabel``).
        unsur = self._cari_kolom_kandidat_lain(peramban, peta, kunci, teks_label, jendela)
        if unsur is not None:
            return unsur
        if jendela is not None:
            return self._kolom_dalam_jendela(peramban, jendela, nama_kolom, teks_label)
        return self._kolom_global(peramban, nama_kolom, teks_label)

    def _layak_combo(self, peramban, unsur) -> bool:
        """Benarkah unsur ini kolom **combo** (bukan kolom teks biasa)?

        Dipakai untuk kandidat yang bisa meleset (mis. XPath tata letak): bot tidak boleh
        menuliskan nama desa ke kolom lain yang kebetulan sejalur — itu justru merusak data.
        """
        if unsur is None:
            return False
        try:
            return bool(peramban.execute_script(
                JS_ALAT + """
                /* layak-combo */
                const el = arguments[0];
                if (!el) return false;
                const jenis = String(el.getAttribute('type') || 'text').toLowerCase();
                if (jenis && !['text', 'search'].includes(jenis)) return false;
                const aria = String(el.getAttribute('aria-owns') || '');
                const peran = String(el.getAttribute('role') || '');
                const kelas = String(el.getAttribute('class') || '');
                // Ronde 49: yang dihitung **panah dropdown** atau komponen combo — bukan
                // sembarang ``x-form-trigger``. Tombol putar numberfield memakai kelas itu
                // juga, sehingga kolom angka (RT/RW) dulu dikira combo.
                const panah = !!panahKolom(el);
                return /list/i.test(aria) || peran === 'combobox'
                    || /arrow/.test(kelas) || panah || komboKolom(komponenKolom(el));
                """, unsur))
        except Exception:  # noqa: BLE001 — tidak terbaca: jangan dipakai
            return False

    def _cari_combo_desa(self, peramban, jendela):
        """Cari kolom combo «Desa/Kelurahan» yang labelnya BUKAN elemen ``<label>``.

        Sebagian Dapodik menggambar label kolom sebagai div Ext JS (``.x-fieldlabel``),
        sehingga pencarian lewat ``<label>`` tidak menemukannya — itulah yang membuat bot
        melaporkan «kolomnya tidak ketemu» (laporan ronde 47). Yang dicari: kolom yang
        benar-benar combo dan labelnya (``<label>`` atau div) menyebut desa/kelurahan/wilayah.
        """
        try:
            return peramban.execute_script(
                JS_ALAT + """
                /* cari-combo-desa */
                const root = arguments[0] || document;
                const tampil = (el) => !!(el && el.getClientRects && el.getClientRects().length);
                const labelDari = (el) => {
                    const wadah = (el.closest && el.closest('.x-field, .x-form-item')) || null;
                    if (!wadah) return '';
                    const l = wadah.querySelector(
                        'label, .x-fieldlabel, .x-form-item-label, .x-form-item-label-default');
                    return (l && l.textContent ? l.textContent : '')
                        .replace(/\\s+/g, ' ').trim().toLowerCase();
                };
                const hasil = [];
                for (const el of root.querySelectorAll('input')) {
                    if (!tampil(el)) continue;
                    const jenis = String(el.getAttribute('type') || 'text').toLowerCase();
                    if (!['text', 'search', ''].includes(jenis)) continue;
                    const aria = String(el.getAttribute('aria-owns') || '');
                    const peran = String(el.getAttribute('role') || '');
                    const kelas = String(el.getAttribute('class') || '');
                    const panah = !!panahKolom(el);
                    const combo = /list/i.test(aria) || peran === 'combobox'
                        || /arrow/.test(kelas) || panah || komboKolom(komponenKolom(el));
                    if (!combo) continue;
                    if (/(desa|kelurahan|wilayah)/.test(labelDari(el))) {
                        hasil.push(el);
                    }
                }
                return hasil.length ? hasil[0] : null;
                """, jendela)
        except Exception:  # noqa: BLE001 — pemanggil memakai kandidat lain
            return None

    def _rincian_isian_bio(self, peramban, jendela) -> str:
        """Sebutkan isian apa saja yang ADA di jendela «Ubah» — laporan mandiri saat gagal.

        Dipakai hanya bila kolom combo «Desa/Kelurahan» tidak ketemu: satu baris log ini
        membuat sebabnya langsung terbaca (nama kolom apa, combo atau bukan) tanpa perlu
        memotret layar sekolah.
        """
        try:
            daftar = peramban.execute_script(
                JS_ALAT + """
                /* rincian-isian-bio */
                const root = arguments[0] || document;
                const hasil = [];
                for (const el of root.querySelectorAll('input')) {
                    if (!(el.getClientRects && el.getClientRects().length)) continue;
                    const jenis = String(el.getAttribute('type') || 'text').toLowerCase();
                    if (jenis === 'hidden') continue;
                    const nama = el.getAttribute('name') || '(tanpa nama)';
                    const aria = String(el.getAttribute('aria-owns') || '');
                    const peran = String(el.getAttribute('role') || '');
                    const kelas = String(el.getAttribute('class') || '');
                    const panah = !!panahKolom(el);
                    const combo = /list/i.test(aria) || peran === 'combobox'
                        || /arrow/.test(kelas) || panah || komboKolom(komponenKolom(el));
                    const xt = xtypeKolom(komponenKolom(el));
                    hasil.push(nama + '/' + (combo ? 'combo' : 'teks')
                        + (xt ? '(' + xt + ')' : ''));
                    if (hasil.length >= 20) break;
                }
                return hasil;
                """, jendela)
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            return ""
        if not isinstance(daftar, list) or not daftar:
            return ""
        return ", ".join(str(satu) for satu in daftar if str(satu).strip())

    def _cari_kolom_kandidat_lain(self, peramban, peta: dict[str, str], kunci: str,
                                  teks_label: str = "", jendela=None):
        """Coba kandidat selector yang tersisa — termasuk XPath lengkap dari sekolah.

        Khusus kolom combo «Desa/Kelurahan», kandidat XPath **wajib** menghasilkan unsur yang
        benar-benar kolom combo; kalau tidak, kandidat itu dilewati dan dicatat apa adanya
        (lebih baik jujur «tidak ketemu» daripada menulis nama desa ke kolom lain).
        """
        combo_desa = kunci in ("bio_kelurahan",)
        dicoba: list[str] = []
        for nilai in self._kandidat_selector(kunci, peta):
            if nilai.lower().startswith("label:"):
                continue              # sudah dicoba lewat pencarian nama/label di atas
            dicoba.append(nilai)
        for nilai in dicoba:
            try:
                locator = self._locator_nilai(nilai)
            except Exception:  # noqa: BLE001 — kandidat berikutnya
                continue
            try:
                for unsur in peramban.find_elements(*locator):
                    if not self._terlihat(peramban, unsur):
                        continue
                    jenis = ""
                    try:
                        jenis = str(unsur.get_attribute("type") or "").lower()
                    except Exception:  # noqa: BLE001 — tanpa atribut type
                        jenis = ""
                    if jenis not in ("", "text", "search"):
                        continue      # kolom tersembunyi/tombol bukan sasaran pengisian
                    if combo_desa and not self._layak_combo(peramban, unsur):
                        self._catat_kepala(
                            f"[bio] {teks_label or 'Desa/Kelurahan'}: kandidat «{nilai}» "
                            "menemukan kolom yang BUKAN combo — dilewati (nilai desa tidak "
                            "boleh ditulis ke kolom lain).")
                        continue
                    if nilai.startswith("xpath:/html/"):
                        self._catat_kepala(
                            f"[bio] {teks_label or 'Desa/Kelurahan'}: kolomnya ditemukan lewat "
                            "XPath lengkap yang dikirim sekolah — kandidat paling akhir, "
                            "sesudah pencarian nama/label tidak menemukannya; kolomnya sudah "
                            "diperiksa memang combo.")
                    return unsur
            except Exception:  # noqa: BLE001 — kandidat berikutnya
                continue
        if combo_desa:
            # Pelacakan combo lewat label yang digambar div Ext JS (bukan <label>).
            lewat_div = self._cari_combo_desa(peramban, jendela)
            if lewat_div is None and jendela is not None:
                # Cara terakhir: combo itu juga bisa berada di luar batas tampilan jendela
                # yang sedang terlihat — sekali lagi di seluruh halaman.
                lewat_div = self._cari_combo_desa(peramban, None)
            if lewat_div is not None:
                self._catat_kepala(
                    f"[bio] {teks_label or 'Desa/Kelurahan'}: kolom combo-nya ditemukan lewat "
                    "labelnya yang berbentuk div (bukan elemen <label>) — versi Dapodik yang "
                    "tidak terjangkau oleh pencarian label biasa.")
                return lewat_div
        return None

    def _kolom_global(self, peramban, nama_kolom: str, teks_label: str = ""):
        """Cari kolom **di seluruh halaman** lewat namanya (persis `By.NAME` skrip sekolah).

        Dipakai sebagai cadangan ketika wadah jendelanya tidak terbaca atau kolomnya tidak
        ketemu di dalamnya. Hanya kolom yang benar-benar terlihat yang diterima, supaya bot
        tidak menulis ke kolom tersembunyi milik panel lain.
        """
        if nama_kolom:
            try:
                from selenium.webdriver.common.by import By

                for unsur in peramban.find_elements(By.NAME, nama_kolom):
                    if self._terlihat(peramban, unsur):
                        return unsur
            except Exception:  # noqa: BLE001 — coba pencarian lewat labelnya
                pass
        if teks_label:
            lewat_label = self._cari_lewat_label(peramban, teks_label)
            if lewat_label is not None and self._terlihat(peramban, lewat_label):
                return lewat_label
        return None

    def _simpan_dalam_jendela(self, peramban, jendela):
        """Tombol «Simpan» **milik jendela** «Ubah» (bukan milik panel «Data Rincian PD»).

        ``jendela=None`` dipakai sebagai jalur cadangan: tombolnya dicari di halaman, tetapi
        yang **BUKAN** milik panel «Data Rincian PD» — supaya bot tidak menekan tombol
        «Simpan» yang salah (itulah yang membuat jendela «Ubah» tetap terbuka di sekolah).
        """
        try:
            return peramban.execute_script(
                """
                /* simpan-jendela */
                const root = arguments[0];
                const dalamRincian = (el) => {
                    let p = el, naik = 0;
                    while (p && naik < 8) {
                        if (p.classList && (p.classList.contains('x-panel') ||
                                            p.classList.contains('x-toolbar'))) {
                            if (/Data Rincian/i.test(p.textContent || '')) return true;
                        }
                        p = p.parentElement; naik += 1;
                    }
                    return false;
                };
                const sumber = root ? root.querySelectorAll('span, a, button, div.x-btn')
                                    : document.querySelectorAll('span, a, button');
                for (const el of sumber) {
                    const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (t !== 'Simpan') continue;
                    if (!el.getClientRects().length) continue;
                    if (!root && dalamRincian(el)) continue;   // tombol panel Data Rincian
                    return el;
                }
                return null;
                """, jendela)
        except Exception:  # noqa: BLE001 — pemanggil mencatat kegagalan jujur
            return None

    def _rincian_bio(self, peramban, jendela, peta: dict[str, str], label: str = "") -> str:
        """Ringkas keadaan jendela «Ubah» — supaya log bisa dibaca tanpa bertanya ke sekolah.

        Berisi: judul jendela, berapa kolom BIO yang terlihat **di dalam jendela** dan **di
        seluruh halaman**, wadah bergulir yang ditemukan beserta ukurannya, dan berapa tombol
        «Simpan» yang terlihat. Inilah alat diagnosis untuk kasus «masih belum baik terkait
        ubah»: dari satu baris ini jelas apakah masalahnya di jendela, di gulir, atau di kolom.
        """
        nama_kolom = self._nama_kolom_bio_semua(peta)
        try:
            rincian = peramban.execute_script(
                JS_ALAT + """
                /* rincian-bio */
                const akar = arguments[0];
                const daftar = (arguments[1] || '').split(',').map((x) => x.trim()).filter(Boolean);
                const tampil = (el) => !!(el && el.getClientRects && el.getClientRects().length);
                const isi = [];
                for (const n of daftar) {
                    const global = document.querySelectorAll('input[name="' + n + '"]').length;
                    const dalam = akar ? akar.querySelectorAll('input[name="' + n + '"]').length
                                       : 0;
                    isi.push(n + '=' + (akar ? dalam : global));
                }
                const gulir = [];
                const sumber = akar || document;
                if (akar) {
                    const periksa = (el) => {
                        if (!el || !el.scrollHeight) return;
                        const g = getComputedStyle(el);
                        if ((g.overflowY === 'auto' || g.overflowY === 'scroll') &&
                                el.scrollHeight > el.clientHeight + 4) {
                            gulir.push(((el.className || 'div') + '').slice(0, 28) + ' ' +
                                       el.scrollTop + '/' + el.clientHeight + '/' + el.scrollHeight);
                        }
                    };
                    periksa(akar);
                    for (const el of akar.querySelectorAll('div')) periksa(el);
                }
                let simpanJendela = 0, simpanRincian = 0;
                const dalamRincian = (el) => {
                    let p = el, n = 0;
                    while (p && n < 8) {
                        if (p.classList && (p.classList.contains('x-panel') ||
                                            p.classList.contains('x-toolbar'))) {
                            if (/Data Rincian/i.test(p.textContent || '')) return true;
                        }
                        p = p.parentElement; n += 1;
                    }
                    return false;
                };
                for (const el of document.querySelectorAll('span, a, button')) {
                    const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (t !== 'Simpan' || !tampil(el)) continue;
                    if (dalamRincian(el)) simpanRincian += 1; else simpanJendela += 1;
                }
                // Ronde 49: daftar kolom yang BENAR-BENAR dropdown — dulu kuncinya tidak
                // pernah diisi sehingga catatan selalu berbunyi «kolom dropdown: -».
                const dropdown = [];
                for (const el of (akar || document).querySelectorAll('input')) {
                    if (!tampil(el)) continue;
                    const jenis = String(el.getAttribute('type') || 'text').toLowerCase();
                    if (jenis !== 'text' && jenis !== 'search' && jenis !== '') continue;
                    const peran = String(el.getAttribute('role') || '');
                    const aria = String(el.getAttribute('aria-owns') || '');
                    const panah = !!panahKolom(el);
                    if (!(panah || peran === 'combobox' || /list/i.test(aria)
                            || komboKolom(komponenKolom(el)))) continue;
                    dropdown.push(String(el.getAttribute('name') || el.id || '?'));
                    if (dropdown.length >= 12) break;
                }
                return {kolom: isi.join(' '), gulir: gulir.slice(0, 3).join(' | '),
                        simpan: simpanJendela, simpan_rincian: simpanRincian,
                        dropdown: dropdown.join(', ')};
                """, jendela, ",".join(nama_kolom))
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            rincian = {}
        if not isinstance(rincian, dict):
            rincian = {}
        judul = self._judul_jendela(peramban, jendela) if jendela is not None else ""
        potongan = [f"jendela: {judul or 'tidak terbaca'}"]
        potongan.append(f"kolom di dalam jendela: {rincian.get('kolom') or '-'}")
        potongan.append(f"wadah gulir: {rincian.get('gulir') or '-'}")
        potongan.append(f"tombol «Simpan»: {rincian.get('simpan', 0)} "
                        f"(milik panel «Data Rincian»: {rincian.get('simpan_rincian', 0)})")
        potongan.append(f"kolom dropdown: {rincian.get('dropdown') or '-'}")
        if label:
            potongan.insert(0, label)
        return "[bio-rincian] " + " | ".join(potongan)

    #: Nama lain sebuah pilihan di daftar Dapodik (daftar sekolah kadang berbeda dengan
    #: daftar di aplikasi SM, mis. «SMA / sederajat» di Dapodik bernama «SLTA»).
    PADANAN_PILIHAN: dict[str, tuple[str, ...]] = {
        "sma": ("slta", "smu"),
        "smp": ("sltp",),
        "sd": ("sekolah dasar",),
        "tidak sekolah": ("tidak tamat sd", "belum sekolah"),
    }

    @staticmethod
    def _norm_pilihan(teks: Any) -> str:
        """Bentuk pembanding pilihan: huruf kecil, spasi rapi, tanpa tanda & «sederajat».

        «SMA / sederajat» → «sma»; «Rp. 500,000 - Rp. 999,999» → «rp 500000 rp 999999».
        """
        hasil = " ".join(str(teks or "").split()).lower()
        hasil = re.sub(r"[.,;]", "", hasil)
        hasil = hasil.replace(" / ", "/").replace("sederajat", "")
        hasil = hasil.replace("/", " ").replace("-", " ")
        return " ".join(hasil.split())

    def _cocokkan_pilihan(self, nilai: str, pilihan: list[str]) -> tuple[str, str]:
        """Pilihan dropdown yang paling cocok untuk sebuah nilai + keterangan pencocokannya.

        Urutannya: (1) sama persis, (2) sama setelah dirapikan & kata «sederajat» dibuang,
        (3) nama lain yang lazim dipakai Dapodik (SLTA/SMU ↔ SMA, SLTP ↔ SMP), (4) satunya
        pilihan yang sepadan. Bila tidak ada yang cocok, kembalikan kosong — bot **tidak**
        menebak pilihan yang tidak ada di daftar.
        """
        cari = self._norm_pilihan(nilai)
        if not cari or not pilihan:
            return "", ""
        for opsi in pilihan:
            if opsi.strip() == str(nilai).strip():
                return opsi, "sama persis"
        for opsi in pilihan:
            if self._norm_pilihan(opsi) == cari:
                return opsi, f"«{nilai}» dibaca sebagai «{opsi}»"
        for nama_lain in self.PADANAN_PILIHAN.get(cari, ()):
            for opsi in pilihan:
                if self._norm_pilihan(opsi) == nama_lain:
                    return opsi, f"«{nilai}» bernama lain «{opsi}» di Dapodik"
        kandidat = [opsi for opsi in pilihan
                    if cari and (cari in self._norm_pilihan(opsi)
                                 or self._norm_pilihan(opsi) in cari)]
        if len(kandidat) == 1:
            return kandidat[0], f"«{nilai}» dicocokkan dengan «{kandidat[0]}»"
        return "", ""

    def _info_kolom(self, peramban, unsur) -> dict[str, Any]:
        """Keadaan satu kolom isian Dapodik — apa adanya (bukan tebakan).

        Yang dibaca: jenis DOM (``type``/``role``/``aria-owns``/``readonly``), **bidang**
        kolom (wadah yang hanya memuat kolom ini — lihat :data:`JS_ALAT`), apakah ada
        **panah dropdown** di bidang itu, apakah ada **tombol putar** numberfield, dan
        komponen Ext JS-nya: ``xtype``, jumlah isi ``store``, nilai ``getValue()``/
        ``getRawValue()``. Komponen yang tidak benar-benar memuat unsur ini **dibuang**
        (``komponen=False``) — inilah yang mencegah daftar milik kolom tetangga terpakai
        (di sekolah: «Tahun lahir ayah» membaca daftar «Pendidikan ayah»).
        """
        try:
            hasil = peramban.execute_script(
                JS_ALAT + """
                /* jenis-kolom */
                const el = arguments[0];
                if (!el) return {};
                const c = komponenKolom(el);
                const peran = String((el.getAttribute && el.getAttribute('role')) || '');
                const aria = String((el.getAttribute && el.getAttribute('aria-owns')) || '');
                const jenis = String((el.getAttribute && el.getAttribute('type')) || 'text')
                    .toLowerCase();
                const panah = !!panahKolom(el);
                const putar = putarKolom(el);
                const komponen = !!c;
                const xt = xtypeKolom(c);
                const store = jumlahStore(c);
                const readonly = c ? !!(c.readOnly || c.editable === false)
                                   : !!el.readOnly;
                const kuat = komboKolom(c) || peran === 'combobox' || /list/i.test(aria);
                const kombo = kuat || panah;
                let nilai = String(el.value == null ? '' : el.value).trim();
                let raw = '';
                try {
                    if (c && c.getValue) {
                        const v = c.getValue();
                        nilai = (v === null || v === undefined) ? '' : String(v);
                    }
                    if (c && c.getRawValue) raw = String(c.getRawValue() || '');
                } catch (e) { /* nilai hanya keterangan */ }
                return {jenis: jenis, peran: peran, aria: aria, komponen: komponen,
                        xtype: xt, store: store, panah: panah, putar: putar,
                        readonly: readonly, kombo: kombo, kombo_kuat: kuat,
                        nilai: nilai, raw: raw,
                        id: String(el.id || ''),
                        componentid: String((el.getAttribute
                                             && el.getAttribute('data-componentid')) || ''),
                        terlihat: !!(el.getClientRects && el.getClientRects().length)};
                """, unsur)
        except Exception:  # noqa: BLE001 — tidak terbaca: diperlakukan sebagai kolom teks
            hasil = {}
        return hasil if isinstance(hasil, dict) else {}

    def _tipe_kolom(self, peramban, unsur) -> str:
        """Jenis kolom: ``combo`` (dropdown Ext JS) atau ``teks``.

        Aturan ronde 49 (lihat :data:`JS_ALAT`): dropdown hanya bila ada **bukti yang
        melekat pada kolom itu sendiri** — panah dropdown di bidangnya, ``role=combobox``/
        ``aria-owns``, atau komponen Ext JS-nya benar-benar combo/ber-store **dan** memuat
        unsur ini. Tombol putar numberfield (RT/RW/KK/NIK tahun) dan ``readonly``
        sendirian **tidak** lagi dianggap dropdown: dulu keduanya membuat bot melewati
        kolom-kolom itu di sekolah.

        Buktinya dibedakan **kuat** dan **lemah**: ``role=combobox``/``aria-owns``/xtype
        combo/store berisi = kuat (langsung jalur daftar); hanya ada unsur mirip panah =
        lemah — kolomnya dicoba **diketik lebih dulu**, dan barulah daftarnya dicoba bila
        ketikannya tidak tersimpan (model Ext JS kosong). Dengan urutan itu, kolom biasa
        yang kebetulan memakai unsur bergaya panah tidak lagi «dilewati».
        """
        return "combo" if self._info_kolom(peramban, unsur).get("kombo") else "teks"

    def _rincian_jenis_kolom(self, peramban, unsur) -> str:
        """Satu baris bukti tentang kolom: dipakai saat kolom gagal diisi/dilewati."""
        info = self._info_kolom(peramban, unsur)
        if not info:
            return "(keadaan kolom tidak terbaca)"
        combo = ("kuat" if info.get("kombo_kuat")
                 else "panah saja" if info.get("panah") else "tidak")
        return (f"jenis={info.get('jenis') or '-'} · role={info.get('peran') or '-'} · "
                f"combo={combo} · "
                f"komponen={'ada' if info.get('komponen') else 'tidak ada'}"
                f"{' (' + str(info.get('xtype')) + ')' if info.get('xtype') else ''} · "
                f"store={info.get('store')} · panah={'ya' if info.get('panah') else 'tidak'} · "
                f"tombol putar={info.get('putar')} · readonly="
                f"{'ya' if info.get('readonly') else 'tidak'} · nilai di kolom="
                f"{(info.get('nilai') or '')!r} · raw={info.get('raw')!r} · "
                f"id={info.get('id') or '-'}")

    def _daftar_aria(self, peramban, unsur):
        """Elemen daftar dropdown milik kolom ini — dibaca dari **DOM**, tanpa ``Ext``.

        DOM Dapodik membawa ``aria-owns="…-inputEl …-picker-listEl"``: dari situ (atau dari
        ``…-picker-listEl``/``.x-boundlist`` di sekitar kolomnya) elemen daftar dropdownnya
        bisa ditemukan langsung. Inilah jalan yang tetap bekerja walaupun ``Ext`` tidak bisa
        dipanggil dari skrip — keadaan yang membuat semua jalur Ext JS gagal di sekolah.
        """
        try:
            return peramban.execute_script(
                JS_ALAT + """
                /* dropdown-aria */
                const el = arguments[0];
                if (!el) return null;
                const kandidat = [];
                const tambah = (n) => { if (n && kandidat.indexOf(n) < 0) kandidat.push(n); };
                const id = (el.getAttribute && (el.getAttribute('data-componentid') || el.id)) || '';
                const bersih = String(id).replace(/-inputEl$/, '');
                const owns = String((el.getAttribute && el.getAttribute('aria-owns')) || '')
                    .split(/\\s+/).filter(Boolean);
                for (const o of owns) tambah(document.getElementById(o));
                if (bersih) {
                    tambah(document.getElementById(bersih + '-picker-listEl'));
                    tambah(document.getElementById(bersih + '-picker'));
                    // Ronde 49: daftar hanya boleh dibaca dari BIDANG kolom ini (wadah yang
                    // hanya memuat kolom ini). ``closest('.x-field') || parentElement`` dulu
                    // bisa memuat kolom tetangga, sehingga daftar milik kolom lain ikut
                    // terbaca — di sekolah: kolom «Tahun lahir ayah» memakai daftar
                    // «Pendidikan ayah».
                    const bidang = bidangKolom(el);
                    if (bidang && bidang.querySelector) tambah(bidang.querySelector('.x-boundlist'));
                }
                for (const n of kandidat) {
                    if ((n.textContent || '').trim()) return n;      # yang ada isinya
                }
                return kandidat.length ? kandidat[0] : null;
                """, unsur)
        except Exception:  # noqa: BLE001 — hanya jalur tambahan
            return None

    def _pilihan_dari_daftar_dom(self, peramban, unsur) -> list[str]:
        """Pilihan yang terbaca langsung dari elemen daftar dropdown (tanpa Ext)."""
        daftar = self._daftar_aria(peramban, unsur)
        if daftar is None:
            return []
        from selenium.webdriver.common.by import By

        try:
            item = daftar.find_elements(
                By.CSS_SELECTOR,
                "li.x-boundlist-item, div.x-boundlist-item, .x-combo-list-item") or []
        except Exception:  # noqa: BLE001
            return []
        hasil: list[str] = []
        for k in item:
            try:
                if not k.is_displayed():
                    continue
                teks = " ".join(str(k.text or "").split())
            except Exception:  # noqa: BLE001
                continue
            if teks and teks not in hasil:
                hasil.append(teks)
        return hasil

    def _data_dropdown(self, peramban, unsur) -> list[tuple[str, Any]]:
        """(teks pilihan, nilainya) tiap pilihan dropdown — dibaca dari **data komponen** Ext JS.

        Inilah cara paling andal di Dapodik dan tidak bergantung tata letak: komponen combo
        Ext JS menyimpan seluruh pilihannya di ``store``-nya (``displayField`` untuk teks,
        ``valueField`` untuk nilainya). Jadi pilihannya bisa dibaca **tanpa membuka daftar
        dropdown sama sekali** — dan nilai untuk ``setValue`` sekaligus diketahui. Berguna
        ketika tombol panahnya ditelan lapisan pemuatan (daftar tidak mau terbuka).
        """
        try:
            hasil = peramban.execute_script(
                JS_ALAT + """
                /* dropdown-store */
                const el = arguments[0];
                if (!el) return [];
                const c = komponenKolom(el);
                if (!c || !c.getStore) return [];
                const store = c.getStore();
                if (!store || !store.getRange) return [];
                const kunci = c.displayField || 'nama', nilai = c.valueField || 'id';
                const keluar = [];
                for (const r of store.getRange()) {
                    const t = r.get(kunci);
                    if (t === undefined || t === null) continue;
                    keluar.push({teks: String(t), nilai: r.get(nilai)});
                }
                return keluar;
                """, unsur)
        except Exception:  # noqa: BLE001 — tanpa Ext/stor: pakai daftar yang terbuka
            return []
        data: list[tuple[str, Any]] = []
        for baris in (hasil or []):
            if not isinstance(baris, dict):
                continue
            teks = str(baris.get("teks") or "").strip()
            if teks:
                data.append((teks, baris.get("nilai")))
        return data

    def _pilih_dropdown_ext(self, peramban, unsur, teks: str) -> bool:
        """Pilih satu pilihan dropdown lewat **model Ext JS** (``select``/``setValue``).

        Dipakai bila mengklik pilihannya tidak menyimpan apa pun (klik ditelan lapisan
        Dapodik, atau daftarnya tidak mau terbuka). Cara ini bekerja langsung pada komponen
        combo-nya: record yang teksnya cocok dicari di ``store``, lalu dipilih — sehingga
        ``getRawValue()`` **dan** nilai modelnya ikut berubah, persis seperti dipilih manual.
        """
        try:
            berhasil = peramban.execute_script(
                JS_ALAT + """
                /* dropdown-pilih */
                const el = arguments[0];
                const cari = String(arguments[1] || '')
                    .replace(/\\s+/g, ' ').trim().toLowerCase();
                if (!el || !cari) return false;
                const c = komponenKolom(el);
                if (!c || !c.getStore) return false;
                const store = c.getStore();
                const kunci = c.displayField || 'nama', nilai = c.valueField || 'id';
                let rec = null;
                if (store && store.getRange) {
                    for (const r of store.getRange()) {
                        const t = r.get(kunci);
                        if (t === undefined || t === null) continue;
                        if (String(t).replace(/\\s+/g, ' ').trim().toLowerCase() === cari) {
                            rec = r;
                            break;
                        }
                    }
                }
                if (!rec) return false;
                if (c.select) { try { c.select(rec); } catch (e) {} }
                if (c.setValue && !(c.getRawValue && c.getRawValue())) {
                    c.setValue(rec.get(nilai));
                }
                if (c.collapse) { try { c.collapse(); } catch (e) {} }
                if (c.fireEvent) { try { c.fireEvent('select', c, rec); } catch (e) {} }
                return true;
                """, unsur, teks)
        except Exception:  # noqa: BLE001 — jalur ini upaya tambahan
            return False
        return bool(berhasil)

    def _pilihan_dropdown(self, peramban, unsur) -> list[str]:
        """Pilihan yang **terlihat** pada daftar dropdown kolom ini (kosong = belum tampil).

        Penting: daftarnya dibaca dari komponen Ext JS-nya sendiri (``getPicker()``) dan
        hanya bila komponen itu memang sedang terbuka — tanpa itu, daftar milik dropdown lain
        yang masih terbuka bisa terbaca sebagai daftar kolom ini (pernah terjadi pada uji:
        daftar «Pekerjaan» dipakai mencocokkan nilai «Penghasilan»). Yang dikembalikan hanyalah
        pilihan yang benar-benar terlihat, karena hanya itu yang bisa diklik; daftar lengkap
        untuk mencocokkan dibaca dari data komponen (``_data_dropdown``).
        """
        lewat_dom = self._pilihan_dari_daftar_dom(peramban, unsur)
        if lewat_dom:
            return lewat_dom
        try:
            hasil = peramban.execute_script(
                JS_ALAT + """
                /* dropdown-daftar */
                const el = arguments[0];
                if (!el) return [];
                const c = komponenKolom(el);
                if (c && c.isExpanded && !c.isExpanded()) return [];
                let akar = null;
                // Tanpa komponen: HANYA daftar di bidang kolom ini yang boleh dibaca —
                // dulu seluruh halaman disapu, sehingga daftar milik dropdown lain
                // terbaca sebagai daftar kolom ini (uji ronde 13).
                const picker = (c && (c.getPicker ? c.getPicker() : c.picker)) || null;
                if (picker && picker.getEl && picker.getEl()) akar = picker.getEl().dom;
                if (!akar) akar = bidangKolom(el);
                if (!akar) return [];
                const lihat = (el2) => !!(el2 && el2.getClientRects && el2.getClientRects().length);
                const daftar = [];
                for (const el2 of akar.querySelectorAll(
                        'li.x-boundlist-item, div.x-boundlist-item, .x-combo-list-item')) {
                    if (!lihat(el2)) continue;
                    const t = (el2.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (t && daftar.indexOf(t) < 0) daftar.push(t);
                }
                return daftar;
                """, unsur)
        except Exception:  # noqa: BLE001 — daftar hanya keterangan tambahan
            return []
        return [str(x) for x in (hasil or []) if str(x).strip()]

    def _dropdown_terbuka(self, peramban, unsur) -> bool:
        """Apakah daftar dropdown **benar-benar terbuka** di layar (bukan sekadar terbaca).

        Dipakai supaya bot tidak mencatat "pilihan sudah diklik" untuk klik yang tidak pernah
        terjadi: pilihannya bisa terbaca dari data komponen Ext JS walaupun daftarnya tertutup.
        """
        try:
            return bool(peramban.execute_script(
                JS_ALAT + r"""
                /* dropdown-terbuka */
                const el = arguments[0];
                if (!el) return false;
                const c = komponenKolom(el);
                if (c && c.isExpanded) return !!c.isExpanded();
                // Tanpa komponen: keadaan daftarnya dibaca dari DOM **di bidang kolom ini
                // sendiri** — dulu seluruh halaman disapu, sehingga daftar milik dropdown
                // lain yang masih terbuka terbaca sebagai daftar kolom ini (uji ronde 13)
                // dan bot menyangka dropdown kolomnya sudah terbuka.
                const lihat = (el2) => !!(el2 && el2.getClientRects && el2.getClientRects().length);
                const bidang = bidangKolom(el);
                if (bidang && bidang.querySelectorAll) {
                    for (const n of bidang.querySelectorAll(
                            'li.x-boundlist-item, div.x-boundlist-item, .x-combo-list-item')) {
                        if (lihat(n)) return true;
                    }
                }
                if (el.getAttribute && el.getAttribute('aria-expanded') === 'true') return true;
                const owns = String((el.getAttribute && el.getAttribute('aria-owns')) || '')
                    .split(/\s+/).filter(Boolean);
                for (const o of owns) {
                    const n = document.getElementById(o);
                    if (n && lihat(n)) return true;
                }
                return false;
                """, unsur))
        except Exception:  # noqa: BLE001 — tidak terbaca: anggap tertutup
            return False

    def _panah_kolom(self, peramban, unsur):
        """Tombol panah dropdown milik kolom ini — dicari **di bidang kolomnya sendiri**.

        Ronde 49: dulu tombolnya dicari dengan XPath **following** yang menyapu seluruh
        halaman, sehingga klik mendarat pada panah kolom tetangga dan yang terbuka
        daftar kolom lain (log sekolah: kolom «Tahun lahir ayah» menampilkan daftar
        «Pendidikan ayah»). Yang dicari sekarang hanya panah di dalam bidang kolom ini,
        dan tombol putar numberfield (bukan panah dropdown) tidak pernah dikembalikan.
        """
        try:
            panah = peramban.execute_script(
                JS_ALAT + """
                /* panah-kolom */
                const el = arguments[0];
                if (!el) return null;
                const p = panahKolom(el);
                if (!p) return null;
                const kelas = String((p.getAttribute && p.getAttribute('class')) || '');
                if (!/arrow/.test(kelas)) return null;   // jangan pernah klik tombol putar
                return p;
                """, unsur)
        except Exception:  # noqa: BLE001 — tanpa panah: coba cara berikutnya
            return None
        return panah

    def _buka_dropdown(self, peramban, unsur, cara: str) -> bool:
        """Buka daftar sebuah dropdown: lewat tombol panah, kolomnya, atau Ext ``expand()``."""
        from selenium.webdriver.common.by import By

        if cara == "panah-bawah":
            # Combo Ext JS juga dibuka dengan menekan tombol ↓ pada kolomnya — cara ini tidak
            # membutuhkan Ext sama sekali, jadi tetap bekerja walau ``Ext.getCmp`` tidak bisa
            # dipanggil dari skrip (dugaan terkuat mengapa dropdown sekolah belum berhasil).
            from selenium.webdriver.common.keys import Keys

            self._paksa_terlihat(peramban, unsur)
            for tombol in ((Keys.ARROW_DOWN,), (Keys.ALT, Keys.ARROW_DOWN)):
                try:
                    unsur.click()
                except Exception:  # noqa: BLE001 — klik bisa tertelan lapisan pemuatan
                    pass
                try:
                    unsur.send_keys(*tombol)
                except Exception:  # noqa: BLE001 — kolom readonly bisa menolaknya
                    continue
                self._tunggu(peramban, 0.4)
                if self._dropdown_terbuka(peramban, unsur):
                    return True
            return False
        if cara == "panah":
            # Ronde 49: panahnya dicari **di bidang kolom itu sendiri** (JavaScript), bukan
            # XPath **following** yang menyapu halaman. Di sekolah, cara itu mengambil
            # panah milik kolom TETANGGA sehingga yang terbuka daftar kolom lain (log:
            # kolom «Tahun lahir ayah» menampilkan daftar «Pendidikan ayah»).
            panah = self._panah_kolom(peramban, unsur)
            if panah is None:
                return False
            self._bawa_ke_layar(peramban, panah)
            try:
                panah.click()
            except Exception:  # noqa: BLE001 — lapisan pemuatan bisa menelan klik
                peramban.execute_script("arguments[0].click();", panah)
            return self._dropdown_terbuka(peramban, unsur)
        if cara == "kolom":
            try:
                self._paksa_terlihat(peramban, unsur)
                try:
                    unsur.click()
                except Exception:  # noqa: BLE001 — klik bisa tertelan lapisan pemuatan
                    peramban.execute_script("arguments[0].click();", unsur)
                return self._dropdown_terbuka(peramban, unsur)
            except Exception:  # noqa: BLE001
                return False
        try:      # jalur pamungkas: komponen Ext JS-nya sendiri
            berhasil = peramban.execute_script(
                JS_ALAT + """
                /* dropdown-buka */
                if (typeof Ext === 'undefined' || !Ext.getCmp) return false;
                const el = arguments[0];
                const c = komponenKolom(el);
                if (!c) return false;
                if (c.expand) { c.expand(); return true; }
                if (c.onTriggerClick) { c.onTriggerClick(); return true; }
                return false;
                """, unsur)
        except Exception:  # noqa: BLE001
            return False
        return bool(berhasil) and self._dropdown_terbuka(peramban, unsur)

    def _tunggu_daftar_dropdown(self, peramban, unsur, percobaan: int = 8) -> list[str]:
        """Tunggu daftar dropdown **terisi** — datanya tidak langsung tampil di Dapodik.

        Daftar Ext JS dibangun sesaat setelah dibuka (kadang perlu satu–dua detik, apalagi di
        PC sekolah yang lambat). Bot membacanya berulang sampai ada isinya, bukan menyerah
        pada bacaan pertama yang kosong. Berapa kali harus menunggu dicatat pada
        ``self._baca_daftar_terakhir`` supaya bisa dilaporkan jujur di log.
        """
        self._baca_daftar_terakhir = 0
        for _ in range(max(1, percobaan)):
            self._baca_daftar_terakhir += 1
            pilihan = self._pilihan_dropdown(peramban, unsur)
            if pilihan:
                return pilihan
            self._tunggu(peramban, 0.5)
        return []

    def _gulir_daftar_dropdown(self, peramban, unsur, jauh: int = 150) -> int:
        """Geser **isi daftar dropdown** (positif = ke bawah, negatif = kembali ke atas).

        Kembalikan posisi gulir barunya (0 = mentok/tidak bisa digulir). Dipakai untuk mencari
        pilihan yang letaknya di luar bagian daftar yang terlihat — pilihan yang belum terlihat
        memang tidak bisa diklik (persis Dapodik).
        """
        self._aman_daftar_dropdown(peramban, unsur)
        try:
            hasil = peramban.execute_script(
                """
                /* gulir-daftar-dropdown */
                const el = arguments[0];
                const jauh = Number(arguments[1] || 150);
                if (!el) return 0;
                const id = (el.getAttribute && (el.getAttribute('data-componentid') || el.id)) || '';
                const lihat = (el2) => !!(el2 && el2.getClientRects && el2.getClientRects().length);
                const c = (typeof Ext !== 'undefined' && Ext.getCmp && id)
                    ? Ext.getCmp(String(id).replace(/-inputEl$/, '')) : null;
                let akar = null;
                const picker = (c && (c.getPicker ? c.getPicker() : c.picker)) || null;
                if (picker && picker.getEl && picker.getEl()) akar = picker.getEl().dom;
                if (!akar) {
                    // Tanpa Ext: elemen daftarnya dicari dari DOM (aria-owns / id picker).
                    const bersih = String(id).replace(/-inputEl$/, '');
                    const owns = String((el.getAttribute && el.getAttribute('aria-owns')) || '')
                        .split(/\\s+/).filter(Boolean);
                    for (const o of owns) {
                        if (akar) break;
                        const n = document.getElementById(o);
                        if (n && lihat(n)) akar = n;
                    }
                    if (!akar && bersih) {
                        const n = document.getElementById(bersih + '-picker-listEl')
                            || document.getElementById(bersih + '-picker');
                        if (n && lihat(n)) akar = n;
                    }
                }
                if (!akar) {
                    for (const el2 of document.querySelectorAll('.x-boundlist')) {
                        if (lihat(el2)) { akar = el2; break; }
                    }
                }
                if (!akar) return 0;
                const kontainer = akar.querySelector('.x-boundlist-list-ct')
                    || akar.querySelector('ul.x-boundlist-list') || akar;
                kontainer.scrollTop = (kontainer.scrollTop || 0) + jauh;
                return kontainer.scrollTop || 0;
                """, unsur, int(jauh))
        except Exception:  # noqa: BLE001 — gulir hanya upaya terbaik
            return 0
        try:
            return int(hasil or 0)
        except (TypeError, ValueError):
            return 0

    def _aman_daftar_dropdown(self, peramban, unsur) -> None:
        """Kursor keluar dari kotak combo, tetapi daftar pilihannya tetap terbuka (ronde 45).

        Melepas fokus dari kotak combo membuat daftarnya menutup (Ext JS ``completeEdit``);
        karena itu fokus ditaruh pada **daftar pilihannya** — bukan di kolom isian mana pun —
        sebelum bot menggulir atau mengklik pilihannya.
        """
        self._kursor_aman(peramban, self._tumpuan_dropdown(peramban, unsur), awalan="[desa]")

    def _klik_pilihan_dropdown(self, peramban, unsur, teks: str, percobaan: int = 12) -> tuple:
        """Klik pilihan pada daftar dropdown — **digulir dulu** bila pilihannya belum tampil.

        Kembalikan ``(berhasil_klik, berapa_kali_digulir)``. Setiap langkah: cari pilihan yang
        terlihat → bila belum ada, geser isi daftar 150 px → cari lagi. Jadi pilihan yang
        berada jauh di bawah (daftar pekerjaan/penghasilan bisa panjang) tetap terjangkau,
        tanpa bergantung pada "berapa kali harus digulir".
        """
        from selenium.webdriver.common.by import By

        geser = 0
        # Kursornya ditaruh pada daftarnya lebih dulu: menggulir/mengklik jangan sampai
        # menyentuh kolom isian mana pun (mis. «RT» yang bisa berubah menjadi «0»).
        self._aman_daftar_dropdown(peramban, unsur)
        # Selalu mulai dari ATAS: pilihan yang berada di atas posisi gulir saat ini tidak akan
        # pernah ketemu bila daftarnya hanya digulir ke bawah.
        self._gulir_daftar_dropdown(peramban, unsur, jauh=-100000)
        for _ in range(max(1, percobaan)):
            posisi = self._posisi_pilihan_dropdown(peramban, unsur, teks)
            if posisi >= 0:
                try:
                    kotak = [k for k in (peramban.find_elements(
                        By.CSS_SELECTOR,
                        "li.x-boundlist-item, div.x-boundlist-item, .x-combo-list-item") or [])
                        if k.is_displayed()]
                    if posisi >= len(kotak):
                        return False, geser
                    item = kotak[posisi]
                    self._bawa_ke_layar(peramban, item,
                                        tumpuan=self._tumpuan_dropdown(peramban, unsur))
                    try:
                        item.click()
                    except Exception:  # noqa: BLE001 — klik bisa tertelan lapisan pemuatan
                        peramban.execute_script("arguments[0].click();", item)
                    return True, geser
                except Exception:  # noqa: BLE001
                    return False, geser
            if not self._gulir_daftar_dropdown(peramban, unsur):
                return False, geser      # daftarnya tidak bisa digulir lagi
            geser += 1
            self._tunggu(peramban, 0.3)
        return False, geser

    def _posisi_pilihan_dropdown(self, peramban, unsur, teks: str) -> int:
        """Posisi pilihan (di antara yang TERLIHAT) pada daftar dropdown kolom ini; -1 = tidak ada."""
        try:
            return int(peramban.execute_script(
                """
                /* dropdown-item */
                const el = arguments[0];
                const cari = (arguments[1] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                if (!el) return -1;
                const id = (el.getAttribute && (el.getAttribute('data-componentid') || el.id)) || '';
                const c = (typeof Ext !== 'undefined' && Ext.getCmp && id)
                    ? Ext.getCmp(String(id).replace(/-inputEl$/, '')) : null;
                if (c && c.isExpanded && !c.isExpanded()) return -1;
                let akar = document;
                const picker = (c && (c.getPicker ? c.getPicker() : c.picker)) || null;
                if (picker && picker.getEl && picker.getEl()) akar = picker.getEl().dom;
                const tampil = (el2) => !!(el2 && el2.getClientRects && el2.getClientRects().length);
                const item = [];
                for (const el2 of akar.querySelectorAll(
                        'li.x-boundlist-item, div.x-boundlist-item, .x-combo-list-item')) {
                    if (tampil(el2)) item.push(el2);
                }
                for (let i = 0; i < item.length; i += 1) {
                    const t = (item[i].textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    if (t === cari) {
                        item[i].scrollIntoView({block: 'center'});
                        return i;
                    }
                }
                return -1;
                """, unsur, teks))
        except Exception:  # noqa: BLE001
            return -1

    def _nilai_dropdown(self, peramban, unsur) -> tuple[str, str]:
        """(tulisan di layar, teks pilihan yang tersimpan) sebuah dropdown.

        Penting di Dapodik: ``getValue()`` sebuah combo berisi **id** (mis. ``2560``), bukan
        teksnya — jadi yang dipakai untuk memeriksa hasil adalah ``getRawValue()``
        (teks pilihan yang benar-benar dilihat pengguna & dikirim Dapodik).
        """
        try:
            hasil = peramban.execute_script(
                """
                /* dropdown-nilai */
                const el = arguments[0];
                if (!el) return {};
                const id = (el.getAttribute && (el.getAttribute('data-componentid') || el.id)) || '';
                const c = (typeof Ext !== 'undefined' && Ext.getCmp && id)
                    ? Ext.getCmp(String(id).replace(/-inputEl$/, '')) : null;
                const raw = (c && c.getRawValue) ? String(c.getRawValue() || '') : '';
                const isi = (c && c.getValue) ? c.getValue() : '';
                return {tampil: (raw || el.value || ''),
                        model: (raw || (typeof isi === 'string' ? isi : '')),
                        id: isi};
                """, unsur)
        except Exception:  # noqa: BLE001
            hasil = {}
        if not isinstance(hasil, dict):
            hasil = {}
        return str(hasil.get("tampil") or ""), str(hasil.get("model") or "")

    def _tutup_dropdown(self, peramban, unsur=None) -> None:
        """Tutup daftar dropdown supaya tidak menutupi kolom berikutnya."""
        if unsur is None:
            return
        try:
            peramban.execute_script(
                JS_ALAT + """
                /* dropdown-tutup */
                if (typeof Ext === 'undefined' || !Ext.getCmp) return false;
                const el = arguments[0];
                const c = komponenKolom(el);
                if (!c || !c.collapse) return false;
                c.collapse();
                return true;
                """, unsur)
        except Exception:  # noqa: BLE001 — daftar yang menutupi akan menutup sendiri
            pass

    def _bukti_dropdown(self, peramban, label: str) -> None:
        """Simpan tangkapan layar **saat daftar dropdown terbuka** (bukti untuk sekolah).

        Kalau sebuah kolom dropdown tetap tidak berhasil, gambar ini menunjukkan apa yang
        benar-benar tampil di layar (daftar terbuka? pilihannya apa saja?) — jadi keadaannya
        bisa diperiksa tanpa perlu menebak atau meminta pengguna memotret ulang.
        """
        if getattr(self, "_bukti_dropdown_diambil", False):
            return                      # cukup sekali per siswa supaya berkas tidak menumpuk
        self._bukti_dropdown_diambil = True
        nama_berkas = re.sub(r"[^A-Za-z0-9]+", "-", str(label or "kolom")).strip("-").lower()
        bukti = self._bukti(peramban, f"bio-dropdown-{nama_berkas or 'kolom'}")
        if bukti:
            self._catat_kepala(f"[bio] bukti layar daftar dropdown disimpan: {bukti} "
                               "(beserta berkas .html di folder yang sama).")

    def _isi_dropdown_bio(self, peramban, peta: dict[str, str], label: str, nilai: str,
                          unsur, awalan: str = "[bio]") -> str:
        """Isi satu kolom **dropdown** jendela «Ubah» — pilihannya diambil dari daftarnya.

        Kolom seperti «Pendidikan ayah», «Pekerjaan ayah», dan «Penghasilan ayah» adalah
        combo Ext JS: mengetikkan teksnya **tidak** menyimpan apa pun bila teks itu tidak
        ada di daftar. Jadi bot membuka daftarnya (panah → kolomnya → ``Ext.expand()``),
        membaca pilihannya, mencocokkan nilainya, mengklik pilihan itu, lalu memeriksa
        **nilai model Ext JS**-nya — bukan hanya tulisan di layar. Bila pilihannya tidak
        ada di daftar, bot mencatat pilihan yang terlihat dan **tidak menebak**.
        """
        self._bawa_ke_layar(peramban, unsur)
        if not self._tunggu_aktif(peramban, unsur):
            self._catat_kepala(f"{awalan} {label}: kolom dropdown masih nonaktif saat akan "
                               "diisi — dicoba apa adanya.")
        # 1) Klik dropdownnya (persis orang memakai Dapodik: tombol panahnya).
        terbuka = False
        cara_dipakai = ""
        for cara in ("panah", "panah-bawah", "kolom", "Ext JS"):
            if self._buka_dropdown(peramban, unsur, cara):
                terbuka = True
                cara_dipakai = cara
                break
            self._tunggu(peramban, 0.6 if cara != "Ext JS" else 0.4)
        # 2) Tunggu datanya muncul — daftar dropdown tidak langsung berisi di Dapodik.
        tampil = self._tunggu_daftar_dropdown(peramban, unsur) if terbuka else []
        # 3) Daftar lengkap untuk mencocokkan: dari data komponen Ext JS (store) — inilah yang
        #    tetap terbaca walau daftarnya tidak mau terbuka.
        data = self._data_dropdown(peramban, unsur)
        pilihan: list[str] = [teks for teks, _ in data] or list(tampil)
        if not pilihan and not tampil:
            # Jalur terakhir untuk mengenali pilihan: baca langsung elemen daftarnya (DOM).
            dari_dom = self._pilihan_dari_daftar_dom(peramban, unsur)
            if dari_dom:
                pilihan = dari_dom
                tampil = dari_dom
                cara_dipakai = (cara_dipakai or "elemen daftar") + " + daftar dibaca dari DOM"
        nama_cara = {"panah": "tombol panahnya",
                     "panah-bawah": "tombol ↓ pada kolomnya (tanpa Ext)",
                     "kolom": "kolomnya sendiri",
                     "Ext JS": "Ext JS (expand)",
                     "": "elemen daftarnya"}.get(cara_dipakai, cara_dipakai)
        if terbuka and tampil:
            tunggu = (f" (menunggu {self._baca_daftar_terakhir}x baca)"
                      if getattr(self, "_baca_daftar_terakhir", 1) > 1 else "")
            self._catat_kepala(f"{awalan} {label}: dropdown dibuka lewat {nama_cara} — "
                               f"{len(tampil)} pilihan tampil{tunggu}.")
        elif terbuka and pilihan:
            self._catat_kepala(f"{awalan} {label}: dropdown dibuka lewat {nama_cara}, "
                               "tetapi pilihannya belum tampil — dibaca dari data komponen "
                               f"Ext JS ({len(pilihan)} pilihan).")
        elif pilihan:
            self._catat_kepala(f"{awalan} {label}: daftar dropdownnya tidak mau terbuka "
                               "(panah → kolom → Ext sudah dicoba) — pilihan dibaca dari data "
                               f"komponen Ext JS ({len(pilihan)} pilihan).")
        else:
            # Ronde 49: daftar yang tidak terbaca **bukan** alasan melewati kolom begitu
            # saja. Kalau kolomnya ternyata bukan dropdown (mis. numberfield RT/RW yang
            # memakai tombol putar ``x-form-trigger`` — di sekolah dulu SEMUA kolom
            # seperti ini dilaporkan «daftar dropdown TIDAK terbaca — dilewati»), nilainya
            # diketik seperti kolom biasa. Dropdown sungguhan tetap tidak ditebak.
            info = self._info_kolom(peramban, unsur)
            if not info.get("kombo_kuat"):
                self._catat_kepala(f"{awalan} {label}: bukan combo sungguhan (tidak ada "
                                   "role=combobox/aria-owns/xtype combo/data pilihan pada "
                                   "kolom ini) — nilainya diketik seperti kolom biasa. "
                                   "Keadaan kolom: "
                                   + self._rincian_jenis_kolom(peramban, unsur))
                return self._isi_periodik_satu(peramban, peta, "", label, nilai, unsur,
                                               awalan=awalan)
            self._catat_kepala(f"{awalan} {label}: daftar dropdown TIDAK terbaca (data "
                               "komponen, tombol panah, kolomnya, dan Ext.getCmp sudah "
                               "dicoba) — dilewati. Keadaan kolom: "
                               + self._rincian_jenis_kolom(peramban, unsur))
            return ("dilewati — daftar dropdown tidak terbaca (nilainya tidak diketik paksa, "
                    "karena Dapodik hanya menyimpan pilihan yang ada di daftar).")
        cocok, catatan = self._cocokkan_pilihan(nilai, pilihan)
        geser_cari = 0
        if not cocok and terbuka:
            # Pilihan belum ketemu di bagian yang TERLIHAT. Jangan langsung menyimpulkan
            # "tidak ada": daftarnya bisa panjang — susuri dari atas ke bawah sambil
            # mengumpulkan semua pilihan yang pernah terlihat, lalu cocokkan lagi.
            semua = list(pilihan)
            cari_norm = self._norm_pilihan(nilai)
            self._gulir_daftar_dropdown(peramban, unsur, jauh=-100000)
            for _ in range(14):
                posisi_gulir = self._gulir_daftar_dropdown(peramban, unsur)
                if not posisi_gulir:
                    break
                geser_cari += 1
                baru = (self._pilihan_dropdown(peramban, unsur)
                        or self._pilihan_dari_daftar_dom(peramban, unsur))
                for teks_baru in baru:
                    if teks_baru not in semua:
                        semua.append(teks_baru)
                if cari_norm and any(self._norm_pilihan(t) == cari_norm for t in semua):
                    break        # pilihannya sudah ketemu: tidak perlu disusuri sampai mentok
            pilihan = semua
            # Daftarnya sudah disusuri; pencocokan dilakukan SEKALI atas seluruh pilihan yang
            # terlihat. Dengan begitu pilihan yang sama persis didahulukan atas nama lain
            # («SMA» dipilih, bukan «SLTA» yang kebetulan muncul lebih dulu).
            cocok, catatan = self._cocokkan_pilihan(nilai, semua)
            if cocok:
                catatan = (f"{catatan} (ketemu setelah daftarnya disusuri {geser_cari}x "
                           f"ke bawah)" if geser_cari else catatan)
            elif geser_cari:
                self._catat_kepala(f"{awalan} {label}: daftar dropdown sudah disusuri "
                                   f"{geser_cari}x ke bawah ({len(semua)} pilihan terlihat) — "
                                   f"«{nilai}» tetap tidak ada.")
        if not cocok:
            ringkas = ", ".join(pilihan[:10]) + (" …" if len(pilihan) > 10 else "")
            self._catat_kepala(f"{awalan} {label}: pilihan «{nilai}» TIDAK ADA di daftar "
                               f"dropdown Dapodik — yang terlihat: {ringkas} "
                               "(dilewati, tidak ditebak).")
            self._bukti_dropdown(peramban, label)
            self._tutup_dropdown(peramban, unsur)
            return (f"dilewati — «{nilai}» tidak ada di daftar dropdown Dapodik "
                    f"({len(pilihan)} pilihan terbaca).")
        if catatan and catatan != "sama persis":
            self._catat_kepala(f"{awalan} {label}: {catatan}.")
        # 4) Klik pilihannya — kalau pilihannya belum tampil di daftar, daftarnya DIGULIR
        #    150 px sekali geser sampai ketemu (daftar dropdown punya area gulir sendiri).
        diklik, geser = (self._klik_pilihan_dropdown(peramban, unsur, cocok) if terbuka
                         else (False, 0))
        if geser:
            self._catat_kepala(f"{awalan} {label}: pilihan «{cocok}» belum tampil di daftar — "
                               f"daftarnya digeser {geser}x ke bawah sampai ketemu.")
        self._tunggu(peramban, 0.5)
        nilai_tampil, model = self._nilai_dropdown(peramban, unsur)
        if diklik and self._norm_pilihan(model or nilai_tampil) == self._norm_pilihan(cocok):
            keterangan = f"terisi (dipilih dari daftar): {nilai_tampil or model}"
            return keterangan if catatan == "sama persis" else f"{keterangan} — {catatan}"
        if diklik:
            self._catat_kepala(f"{awalan} {label}: pilihan «{cocok}» sudah diklik tetapi "
                               f"nilainya belum tersimpan (tampil: «{nilai_tampil}») — dipilih "
                               "lewat model Ext JS (select/setValue).")
        elif terbuka:
            self._catat_kepala(f"{awalan} {label}: pilihan «{cocok}» tidak ketemu pada daftar "
                               f"yang terbuka (sudah digeser {geser}x) — pilihan dipasang lewat "
                               "model Ext JS (select/setValue).")
        else:
            self._catat_kepala(f"{awalan} {label}: daftar dropdownnya tidak terbuka di Dapodik "
                               f"— pilihan «{cocok}» dipasang lewat model Ext JS "
                               "(select/setValue).")
        # Pilih lewat MODEL Ext JS (select(record) → nilai & teks ikut berubah) — inilah yang
        # bekerja di Dapodik sekolah: mengklik pilihannya tidak menyimpan apa pun.
        if self._pilih_dropdown_ext(peramban, unsur, cocok):
            self._tunggu(peramban, 0.5)
            nilai_tampil, model = self._nilai_dropdown(peramban, unsur)
            if self._norm_pilihan(model or nilai_tampil) == self._norm_pilihan(cocok):
                return (f"terisi lewat Ext JS (dipilih dari daftar): "
                        f"{nilai_tampil or model}")
        if self._set_ext(peramban, unsur, nilai=cocok):
            self._tunggu(peramban, 0.4)
            nilai_tampil, model = self._nilai_dropdown(peramban, unsur)
            if self._norm_pilihan(model or nilai_tampil) == self._norm_pilihan(cocok):
                return (f"terisi lewat Ext JS (dipilih dari daftar): "
                        f"{nilai_tampil or model}")
        self._bukti_dropdown(peramban, label)
        self._tutup_dropdown(peramban, unsur)
        return (f"gagal terisi — pilihan «{cocok}» tidak masuk ke nilai kolomnya "
                f"(tampil: «{nilai_tampil}», model: «{model}»).")

    # ------------------------------------------- Desa/Kelurahan (combo wilayah) --- #
    @staticmethod
    def _kata_wilayah(teks: Any) -> str:
        """Bentuk pembanding nama wilayah: huruf kecil, tanpa tanda, tanpa kata baku.

        «Desa/Kel. Karawaci Baru» → «karawaci baru»; «Kec. Karawaci» → «karawaci»;
        «Kota Tangerang» → «tangerang». Kata «desa/kel/kecamatan/kota/kabupaten» dibuang
        supaya teks pilihan Dapodik bisa dibandingkan dengan data SM apa adanya.
        """
        hasil = " ".join(str(teks or "").split()).lower()
        hasil = re.sub(r"[.,;:()/\\-]+", " ", hasil)
        buang = {"desa", "kel", "kelurahan", "kec", "kecamatan", "kota", "kab",
                 "kabupaten", "prov", "provinsi"}
        return " ".join(k for k in hasil.split() if k not in buang)

    @staticmethod
    def _tampil_desa(teks: Any) -> str:
        """Nama desa dari teks pilihan Dapodik, ditulis apa adanya (untuk pesan laporan)."""
        bagian = [b.strip() for b in re.split(r"\s+-\s+", " ".join(str(teks or "").split()))
                  if b.strip()]
        if not bagian:
            return ""
        return re.sub(r"^(desa\s*/\s*kel\.?|desa|kel\.?|kelurahan)\s*", "", bagian[0],
                      flags=re.IGNORECASE).strip()

    @staticmethod
    def _tampil_kecamatan(teks: Any) -> str:
        """Bagian kecamatan dari teks pilihan Dapodik, ditulis apa adanya."""
        for bagian in re.split(r"\s+-\s+", " ".join(str(teks or "").split())):
            if bagian.strip().lower().startswith(("kec", "kecamatan")):
                return bagian.strip()
        return ""

    @classmethod
    def _kata_rapat(cls, teks: Any) -> str:
        """Nama wilayah tanpa spasi — untuk menangani ejaan yang beda pemisahan kata.

        Sekolah sering menemui nama desa yang di SM ditulis «Karang Sari» tetapi di basis
        data Dapodik tertulis «Karangsari» (atau sebaliknya). Karena itu, selain bentuk
        biasa, nama wilayah juga dibandingkan dalam bentuk rapat (tanpa spasi/tanda).
        """
        return cls._kata_wilayah(teks).replace(" ", "")

    @classmethod
    def _bagian_wilayah(cls, teks: Any) -> tuple[str, str, str]:
        """Pisahkan satu pilihan combo menjadi (desa, kecamatan, kota).

        Bentuk pilihan pada tangkapan layar sekolah:

            «Desa/Kel. Karawaci Baru - Kec. Karawaci - Kota Tangerang»

        Sebagian pemasangan Dapodik menuliskan satu baris polos tanpa pemisah «-»; dalam
        hal itu seluruh teks dianggap nama desa. Pemisahan ini dipakai **hanya** untuk
        mencocokkan dengan data SM — bot tidak menebak desa dari awal teks.
        """
        rapi = " ".join(str(teks or "").split())
        if not rapi:
            return "", "", ""
        bagian = [b.strip() for b in re.split(r"\s+-\s+", rapi) if b.strip()]
        if len(bagian) <= 1:
            return cls._kata_wilayah(rapi), "", ""
        desa = bagian[0]
        kecamatan = ""
        kota = ""
        for tambahan in bagian[1:]:
            rendah = tambahan.lower()
            if not kecamatan and rendah.startswith(("kec", "kecamatan")):
                kecamatan = tambahan
            elif not kota and rendah.startswith(("kab", "kota", "kabupaten")):
                kota = tambahan
        return cls._kata_wilayah(desa), cls._kata_wilayah(kecamatan), cls._kata_wilayah(kota)

    def _cocokkan_desa(self, desa: str, kecamatan: str, pilihan: list[str]) -> tuple[str, str]:
        """Pilihan «Desa/Kelurahan» yang paling cocok + keterangan pencocokannya.

        Berjenjang, dan **tidak menebak**:

        1. desa **dan** kecamatan sama persis;
        2. desa sama persis;
        3. desa sama dalam bentuk rapat — ejaan yang beda pemisahan kata ditulis apa adanya
           («Karang Sari» ↔ «Karangsari»), tentu saja tetap dengan kecamatan sebagai
           penentu bila nama itu ada di beberapa kecamatan;
        4. hanya satu pilihan yang memuat nama desanya;
        5. bila ada beberapa pilihan bernama sama, kecamatan SM dipakai untuk memilih yang
           tepat — kalau tetap ambigu, bot mengembalikan kosong (dilaporkan, bukan ditebak).
        """
        desa_kata = self._kata_wilayah(desa)
        kec_kata = self._kata_wilayah(kecamatan)
        desa_rapat = self._kata_rapat(desa)
        if not desa_kata or not pilihan:
            return "", ""
        rinci = [(opsi, *self._bagian_wilayah(opsi)) for opsi in pilihan]
        for opsi, d, k, _ in rinci:
            if d == desa_kata and kec_kata and k == kec_kata:
                return opsi, "sama persis (desa + kecamatan)"
        sama_desa = [(opsi, k) for opsi, d, k, _ in rinci if d == desa_kata]
        if len(sama_desa) == 1:
            opsi, k = sama_desa[0]
            if kec_kata and k and k != kec_kata:
                # Kecamatan di SM berbeda dari kecamatan pilihan Dapodik. Kecamatan itu TIDAK
                # punya kolom sendiri di Dapodik (ikut di kolom desa ini), jadi desanya tetap
                # dipilih sesuai daftar Dapodik — tetapi perbedaannya dilaporkan apa adanya
                # supaya data SM-nya bisa ikut diperiksa.
                return opsi, (f"nama desanya sama persis, tetapi kecamatan pada pilihan "
                              f"Dapodik «{self._tampil_kecamatan(opsi)}» berbeda dari data "
                              f"SM «{kecamatan}»")
            return opsi, "nama desanya sama persis"
        if len(sama_desa) > 1 and kec_kata:
            tepat = [o for o, k in sama_desa if k == kec_kata]
            if len(tepat) == 1:
                return tepat[0], ("desa & kecamatan yang sama dipilih — nama desa itu ada di "
                                  "lebih dari satu kecamatan")
        # Ejaan beda pemisahan kata: «Karang Sari» ↔ «Karangsari».
        if len(desa_rapat) >= 4:
            rapat_pilihan = [(opsi, self._kata_rapat(d), k) for opsi, d, k, _ in rinci]
            if kec_kata:
                tepat_rapat = [o for o, r, k in rapat_pilihan
                               if r == desa_rapat and k == kec_kata]
                if len(tepat_rapat) == 1:
                    return tepat_rapat[0], (f"ejaan berbeda (spasi): «{desa}» ↔ "
                                            f"«{self._tampil_desa(tepat_rapat[0])}» — "
                                            "dipilih lewat kecamatan yang sama")
            sama_rapat = [o for o, r, _ in rapat_pilihan if r == desa_rapat]
            if len(sama_rapat) == 1:
                opsi = sama_rapat[0]
                k = next(k for o, _, k in rapat_pilihan if o == opsi)
                if kec_kata and k and k != kec_kata:
                    return "", ""
                return opsi, (f"ejaan berbeda (spasi): «{desa}» ↔ "
                              f"«{self._tampil_desa(opsi)}»")
        if len(sama_desa) > 1:
            return "", ""            # nama sama di beberapa kecamatan tanpa penentu: jangan tebak
        memuat = [(opsi, k) for opsi, d, k, _ in rinci
                  if desa_kata in d or (len(d) >= 4 and d in desa_kata)]
        if len(memuat) == 1:
            return memuat[0][0], f"«{desa}» dicocokkan dengan «{memuat[0][0]}»"
        if len(memuat) > 1 and kec_kata:
            tepat = [o for o, k in memuat if k == kec_kata]
            if len(tepat) == 1:
                return tepat[0], ("dicocokkan lewat kecamatan — nama desanya muncul di "
                                  "beberapa pilihan")
        return "", ""

    def _ketik_pencarian_desa(self, peramban, unsur, kueri: str) -> str:
        """Ketik kueri pencarian ke dalam kolom «Desa/Kelurahan» — persis cara pengguna.

        Skrip sekolah memakai ``Ctrl+A`` lalu mengetik; begitu pula di sini. Mengetik bukan
        untuk mengisi nilainya (Dapodik hanya menyimpan pilihan yang ada di daftarnya),
        melainkan untuk memicu Dapodik mengambil daftar desa untuk kecamatan itu.
        """
        from selenium.webdriver.common.keys import Keys

        try:
            self._paksa_terlihat(peramban, unsur)
            try:
                unsur.click()
            except Exception:  # noqa: BLE001 — fokus bisa ditelan lapisan pemuatan
                pass
            unsur.send_keys(Keys.CONTROL, "a")
            unsur.send_keys(str(kueri))
            return "diketik"
        except Exception as exc:  # noqa: BLE001 — kolom readonly/kunci: daftar dibaca apa adanya
            self._catat_kepala(f"[desa] kueri «{kueri}» tidak bisa diketik ke kolomnya "
                               f"({type(exc).__name__}) — daftar dibaca apa adanya.")
            return "gagal"

    def _halaman_daftar_dropdown(self, peramban, unsur) -> tuple[int, int]:
        """(halaman sekarang, jumlah halaman) bilah halaman picker — (0, 0) bila tidak ada."""
        try:
            hasil = peramban.execute_script(
                """
                /* halaman-dropdown */
                const el = arguments[0];
                if (!el) return {};
                const lihat = (n) => !!(n && n.getClientRects && n.getClientRects().length);
                let akar = null;
                for (const n of document.querySelectorAll('.x-boundlist, .x-picker, .x-list-paging')) {
                    if (lihat(n)) { akar = n; break; }
                }
                if (!akar) {
                    const id = (el.getAttribute && el.getAttribute('aria-owns') || '').split(/\\s+/)[0];
                    const n = id ? document.getElementById(id) : null;
                    if (n) akar = n.closest ? (n.closest('.x-boundlist') || n) : n;
                }
                if (!akar) return {};
                const semua = [...akar.querySelectorAll('*')];
                for (const n of semua) {
                    const t = (n.textContent || '').replace(/\\s+/g, ' ').trim();
                    const m = /^Page\\s+(\\d+)\\s+of\\s+(\\d+)$/i.exec(t);
                    if (m) return {halaman: parseInt(m[1], 10), total: parseInt(m[2], 10)};
                }
                return {};
                """, unsur)
        except Exception:  # noqa: BLE001 — bilah halaman hanya keterangan tambahan
            return 0, 0
        if not isinstance(hasil, dict):
            return 0, 0
        try:
            return int(hasil.get("halaman") or 0), int(hasil.get("total") or 0)
        except (TypeError, ValueError):
            return 0, 0

    def _halaman_berikutnya_dropdown(self, peramban, unsur) -> bool:
        """Tekan tombol «halaman berikutnya» pada bilah halaman picker (bila ada & aktif)."""
        halaman_awal, total = self._halaman_daftar_dropdown(peramban, unsur)
        if not (0 < halaman_awal < total):
            return False
        try:
            berhasil = peramban.execute_script(
                """
                /* halaman-dropdown-lanjut */
                const el = arguments[0];
                if (!el) return false;
                const lihat = (n) => !!(n && n.getClientRects && n.getClientRects().length);
                let akar = null;
                for (const n of document.querySelectorAll('.x-boundlist, .x-picker')) {
                    if (lihat(n)) { akar = n; break; }
                }
                if (!akar) return false;
                const tombol = [...akar.querySelectorAll(
                        '.x-tbar-page-next, .x-tbar-page-last, a[title*="Next"], a[title*="Berikut"]')]
                    .find(lihat);
                if (!tombol) return false;
                tombol.click();
                return true;
                """, unsur)
        except Exception:  # noqa: BLE001 — bilah halaman mungkin tidak bisa dipakai
            return False
        return bool(berhasil)

    def _kumpulkan_pilihan_desa(self, peramban, unsur, desa: str, kecamatan: str,
                                awalan: str = "[bio]", label: str = "") -> tuple:
        """Susuri daftar hasil pencarian «Desa/Kelurahan» sampai desa yang dicari ketemu.

        Tiga hal yang dijaga (semuanya dari tangkapan layar sekolah): daftarnya **punya area
        gulir sendiri**, **berhalaman** («Page 1 of 2» pada bilah halaman picker), dan
        **tidak langsung terisi** sesudah kecamatan diketik (Dapodik mengambilnya dari basis
        data). Jadi pilihannya dikumpulkan berulang: baca → gulir → baca lagi → buka halaman
        berikutnya → baca lagi, dan berhenti begitu desa yang dicari terlihat.

        Kembalikan ``(pilihan_cocok, catatan, semua_pilihan, info)``.
        """
        semua: list[str] = []
        geser = 0
        halaman_dilewati = 0

        def serap() -> int:
            baru = 0
            sumber = list(self._pilihan_dropdown(peramban, unsur) or [])
            sumber += [teks for teks, _ in self._data_dropdown(peramban, unsur)]
            for teks in sumber:
                if teks and teks not in semua:
                    semua.append(teks)
                    baru += 1
            return baru

        serap()
        langkah = 0
        sepi = 0
        while langkah < 80 and len(semua) < DESA_PILIHAN_MAKSIMAL:
            langkah += 1
            cocok, catatan = self._cocokkan_desa(desa, kecamatan, semua)
            if cocok:
                return cocok, catatan, semua, {"geser": geser, "halaman": halaman_dilewati}
            jumlah_awal = len(semua)
            if self._gulir_daftar_dropdown(peramban, unsur):
                geser += 1                       # masih ada bagian daftar yang belum terlihat
            else:
                halaman, total = self._halaman_daftar_dropdown(peramban, unsur)
                if (0 < halaman < total) and halaman_dilewati < DESA_HALAMAN_MAKSIMAL - 1 \
                        and self._halaman_berikutnya_dropdown(peramban, unsur):
                    halaman_dilewati += 1
                    self._catat_kepala(
                        f"{awalan} {label}: pilihan belum ketemu pada halaman itu — membuka "
                        "halaman berikutnya pada bilah halaman daftarnya («Page x of y»).")
                    self._tunggu(peramban, 1.0)  # halaman baru masih diambil dari basis data
                    self._gulir_daftar_dropdown(peramban, unsur, jauh=-100000)
            self._tunggu(peramban, 0.4)
            serap()
            if len(semua) > jumlah_awal:
                sepi = 0
            else:
                # Belum ada tambahan: datanya (halaman baru) memang butuh beberapa bacaan.
                # Baru sesudah beberapa putaran tanpa tambahan, daftarnya dianggap mentok.
                sepi += 1
                if sepi >= 6:
                    break
        cocok, catatan = self._cocokkan_desa(desa, kecamatan, semua)
        return cocok, catatan, semua, {"geser": geser, "halaman": halaman_dilewati}

    def _isi_desa_kelurahan(self, peramban, peta: dict[str, str], label: str, unsur,
                            siswa: dict[str, Any], awalan: str = "[bio]") -> str:
        """Isi kolom combo «Desa/Kelurahan» dari data SM (desa + kecamatan).

        Alur Dapodik terbaru (dari sekolah): pengguna **mengetik nama kecamatan** lebih dulu,
        lalu Dapodik menampilkan daftar desa/kelurahan di bawah kecamatan itu; daftarnya
        bisa digulir dan berhalaman. Satu kolom itu sekaligus memuat desa + kecamatan + kota,
        jadi yang dicocokkan adalah **desa**-nya, dan kecamatan dipakai untuk memastikan
        pilihannya benar (nama desa bisa sama di kecamatan berbeda).

        Bot **tidak pernah** hanya mengetikkan nilainya: yang diketik adalah kata kunci
        pencarian, dan nilai kolomnya diambil dengan memilih dari daftar Dapodik — lalu
        diperiksa kembali dari nilai kolomnya.
        """
        desa = self._nilai_teks(siswa.get("kelurahan"))
        kecamatan = self._nilai_teks(siswa.get("kecamatan"))
        if not desa:
            # Jangan sekadar «dilewati»: sebut APA yang kosong, di mana memperbaikinya, dan
            # bahwa kolom Dapodik dibiarkan apa adanya (ronde 51 — dari catatan sekolah, baris
            # ini muncul padahal data siswa di aplikasi SM ada; sebabnya ada di ANTREAN bot).
            self._catat_kepala(
                f"{awalan} {label}: data «{label}» siswa KOSONG pada data yang dikirim ke bot "
                "(aplikasi SM) — kolom Dapodik dibiarkan apa adanya, tidak dikosongkan. Isi "
                "kolomnya di menu Data Siswa (atau impor ulang Excel dari Dapodik) lalu "
                "jalankan bot lagi supaya desa ini ikut terisi.")
            return "dilewati — kolom «Desa/Kelurahan» siswa kosong di SM"
        self._catat_kepala(f"{awalan} {label}: data SM — desa «{desa}»"
                           + (f", kecamatan «{kecamatan}»." if kecamatan else
                              " (kecamatan kosong di SM)."))
        if not self._tunggu_aktif(peramban, unsur):
            self._catat_kepala(f"{awalan} {label}: kolomnya masih nonaktif saat akan diisi — "
                               "dicoba apa adanya.")
        # Isi kolom SEBELUM bot menyentuhnya: kalau desa yang diminta tidak ada di daftar
        # Dapodik, isi lama ini dikembalikan supaya data Dapodik tidak ikut berubah karena
        # kata kunci pencarian yang tertinggal di kotaknya.
        nilai_awal = self._nilai_teks(self._nilai_dropdown(peramban, unsur)[0])
        # Kode wilayah desa yang sedang tersimpan (``kode_wilayah_str``). Dipakai untuk
        # memastikan desa yang dipilih benar-benar PINDAH — bukan sekadar teksnya berubah.
        kode_terbaca, kode_awal = self._kode_wilayah(peramban, unsur)
        if kode_terbaca:
            pesan_kode = f", kode wilayah «{kode_awal or '(kosong)'}»."
        else:
            nama_kolom = self._nama_kolom_wilayah(peramban)
            pesan_kode = ("; kolom kode wilayah (kode_wilayah_str) tidak ada di halaman ini — "
                          "hasil pemilihan dinilai dari nilai model combo-nya"
                          + (f" (kolom tersembunyi yang ada: {nama_kolom})" if nama_kolom else ""))
        self._catat_kepala(f"{awalan} {label}: isi sebelum disentuh — «{nilai_awal or '(kosong)'}»"
                           + pesan_kode)
        kueri: list[str] = []
        for calon in (kecamatan, desa, self._kata_rapat(desa)):
            if calon and calon.lower() not in {k.lower() for k in kueri}:
                kueri.append(calon)
        cocok = ""
        catatan = ""
        semua: list[str] = []
        info: dict[str, Any] = {}
        for nomor, cari in enumerate(kueri, start=1):
            if cari == kecamatan:
                cara_cari = "kecamatan"
            elif self._kata_wilayah(cari) == self._kata_wilayah(desa):
                cara_cari = "nama desa"
            else:
                cara_cari = "nama desa yang ditulis rapat (tanpa spasi)"
            self._catat_kepala(
                f"{awalan} {label}: mengetik «{cari}» pada kolomnya (Dapodik mencari desa lewat "
                f"{cara_cari}) — daftarnya diambil Dapodik dari basis datanya, jadi ditunggu "
                "lebih dulu.")
            self._ketik_pencarian_desa(peramban, unsur, cari)
            self._tunggu(peramban, 0.8)
            if not self._dropdown_terbuka(peramban, unsur):
                for cara in ("panah", "panah-bawah", "kolom", "Ext JS"):
                    if self._buka_dropdown(peramban, unsur, cara):
                        break
                    self._tunggu(peramban, 0.4)
            tampil = self._tunggu_daftar_dropdown(
                peramban, unsur, percobaan=max(4, int(self._batas_tunggu_desa() / 0.5)))
            jumlah_baca = getattr(self, "_baca_daftar_terakhir", 1)
            if tampil:
                self._catat_kepala(f"{awalan} {label}: daftar desa muncul — {len(tampil)} "
                                   f"pilihan terlihat (ditunggu {jumlah_baca}x baca).")
            else:
                self._catat_kepala(f"{awalan} {label}: daftar desa belum terlihat sesudah "
                                   f"{jumlah_baca}x baca — pilihannya dibaca dari data "
                                   "komponen/DOM apa adanya.")
            cocok, catatan, semua, info = self._kumpulkan_pilihan_desa(
                peramban, unsur, desa, kecamatan, awalan, label)
            if cocok:
                break
            self._catat_kepala(
                f"{awalan} {label}: «{desa}» tidak ada pada hasil pencarian «{cari}» "
                f"({len(semua)} pilihan dibaca, daftar digeser {info.get('geser', 0)}x, "
                f"{info.get('halaman', 0)} halaman berikutnya dibuka).")
            if nomor < len(kueri):
                self._catat_kepala(f"{awalan} {label}: kueri berikutnya dicoba dengan nama "
                                   "desanya.")
        if not cocok:
            ringkas = ", ".join(semua[:8]) + (" …" if len(semua) > 8 else "")
            self._catat_kepala(
                f"{awalan} {label}: desa «{desa}» TIDAK ADA pada daftar Dapodik (kueri "
                f"{' & '.join(repr(k) for k in kueri)} sudah dicoba, {len(semua)} pilihan "
                f"dibaca) — yang terlihat: {ringkas or '(daftar kosong)'} (dilewati, tidak "
                "ditebak).")
            self._bukti_dropdown(peramban, label)
            self._tutup_dropdown(peramban, unsur)
            if self._pulihkan_desa(peramban, unsur, nilai_awal, awalan, label):
                return (f"dilewati — «{desa}» tidak ada pada daftar Desa/Kelurahan Dapodik "
                        f"({len(semua)} pilihan terbaca); isi kolom dikembalikan seperti semula.")
            return (f"dilewati — «{desa}» tidak ada pada daftar Desa/Kelurahan Dapodik "
                    f"({len(semua)} pilihan terbaca).")
        if catatan and catatan != "sama persis (desa + kecamatan)":
            self._catat_kepala(f"{awalan} {label}: {catatan}.")
        diklik, geser = self._klik_pilihan_dropdown(peramban, unsur, cocok)
        if geser:
            self._catat_kepala(f"{awalan} {label}: pilihan «{cocok}» baru terlihat setelah "
                               f"daftarnya digeser {geser}x.")
        tersimpan, alasan, tampil_nilai, kode_info, tunggu_info = self._periksa_desa_sampai_siap(
            peramban, unsur, desa, cocok, nilai_awal, kode_awal)
        if "ditunggu 1x" not in tunggu_info:
            self._catat_kepala(f"{awalan} {label}: nilainya tidak muncul seketika — {tunggu_info} "
                               "(Dapodik menuliskan nilainya dari basis datanya; bot menunggu, "
                               "tidak menilai gagal dari bacaan pertama).")
        if tersimpan:
            self._catat_kecamatan_berbeda(label, kecamatan, tampil_nilai or model)
            if kode_info:
                self._catat_kepala(f"{awalan} {label}: {kode_info}.")
            self._catat_desa_terverifikasi(peramban, unsur, desa, cocok, nilai_awal, kode_awal)
            self._tutup_dropdown(peramban, unsur)
            return (f"terisi (dipilih dari daftar Dapodik): {tampil_nilai or model}"
                    + ("" if catatan == "sama persis (desa + kecamatan)" else f" — {catatan}"))
        if diklik:
            self._catat_kepala(f"{awalan} {label}: pilihan «{cocok}» sudah diklik tetapi "
                               f"nilainya belum tersimpan — {alasan} (tampil: "
                               f"«{tampil_nilai}») — dipilih lewat model Ext JS "
                               "(select/setValue).")
        else:
            self._catat_kepala(f"{awalan} {label}: pilihan «{cocok}» tidak bisa diklik pada "
                               "daftarnya (sudah digulir & halaman dibuka) — dipilih lewat "
                               "model Ext JS (select/setValue).")
        if self._pilih_dropdown_ext(peramban, unsur, cocok):
            tersimpan, alasan, tampil_nilai, kode_info, tunggu_info = \
                self._periksa_desa_sampai_siap(peramban, unsur, desa, cocok, nilai_awal, kode_awal)
            if "ditunggu 1x" not in tunggu_info:
                self._catat_kepala(f"{awalan} {label}: nilai lewat model Ext JS juga tidak muncul "
                                   f"seketika — {tunggu_info}.")
            if tersimpan:
                self._catat_kecamatan_berbeda(label, kecamatan, tampil_nilai or model)
                if kode_info:
                    self._catat_kepala(f"{awalan} {label}: {kode_info}.")
                self._catat_desa_terverifikasi(peramban, unsur, desa, cocok, nilai_awal, kode_awal)
                self._tutup_dropdown(peramban, unsur)
                return (f"terisi lewat model Ext JS (pilihan «{cocok}» dari daftar Dapodik): "
                        f"{tampil_nilai or model}")
            self._catat_kepala(f"{awalan} {label}: pilihan «{cocok}» dipasang lewat model "
                               f"Ext JS tetapi belum terverifikasi — {alasan}.")
        self._bukti_dropdown(peramban, label)
        self._tutup_dropdown(peramban, unsur)
        self._catat_kepala(f"{awalan} {label}: kolom «Desa/Kelurahan» TIDAK jadi terisi — "
                           f"{alasan}. Ini yang perlu dikirim ke kami bila berulang: baris "
                           "«kode wilayah (kode_wilayah_str)» di atas, dan bukti layar "
                           "yang disimpan bot di folder data/bot.")
        if self._pulihkan_desa(peramban, unsur, nilai_awal, awalan, label):
            return (f"gagal terisi — pilihan «{cocok}» tidak masuk ke kolomnya "
                    f"(tampil: «{tampil_nilai}»; {alasan}); isi kolom dikembalikan seperti "
                    "semula (data lama Dapodik tidak ikut berubah).")
        return (f"gagal terisi — pilihan «{cocok}» tidak masuk ke kolomnya "
                f"(tampil: «{tampil_nilai}»; {alasan}).")

    def _batas_tunggu_desa(self) -> float:
        """Berapa detik bot menunggu daftar & nilai desa sebelum menyimpulkan gagal.

        Dapodik mengambil daftar desa (data Kemendagri) dari basis datanya, dan nilainya
        (termasuk ``kode_wilayah_str``) baru dituliskan sesudahnya — di PC sekolah proses itu
        bisa lama (ronde 51: «harus menunggu agak lama biar valuenya muncul»). Batasnya
        dinaikkan, dan pengaturan «bot_timeout» (bawaan 15 detik) boleh memperpanjangnya
        sampai paling lama 30 detik supaya pekerjaan tidak menggantung.
        """
        try:
            batas_opsi = float(self.opsi.get("bot_timeout", "15") or 15)
        except (TypeError, ValueError):
            batas_opsi = 15.0
        return max(DESA_TUNGGU_DETIK, min(30.0, batas_opsi))

    def _periksa_desa_sampai_siap(self, peramban, unsur, desa: str, cocok: str,
                                  nilai_awal: str, kode_awal: str) -> tuple[bool, str, str, str, str]:
        """Tunggu sampai pilihan desa benar-benar masuk ke kolomnya.

        Sesudah pilihan diklik (atau dipasang lewat model Ext JS), Dapodik masih menuliskan
        nilai desa beserta ``kode_wilayah_str`` dari basis datanya — kadang tidak seketika.
        Bot memeriksa berulang sampai batas waktu, bukan menilai gagal dari bacaan pertama,
        dan mencatat berapa kali ia memeriksa (bukti jujur bahwa bot memang menunggu).

        Kembalikan ``(tersimpan, alasan, tampil, keterangan_kode, keterangan_tunggu)``.
        """
        batas = self._batas_tunggu_desa()
        akhir = time.time() + batas
        periksa = 0
        tampil = ""
        alasan = "pilihan belum diklik"
        keterangan_kode = ""
        tersimpan = False
        while True:
            periksa += 1
            tampil_nilai, model = self._nilai_dropdown(peramban, unsur)
            tampil = tampil_nilai or model
            tersimpan, alasan, keterangan_kode = self._desa_dan_kode_terverifikasi(
                peramban, unsur, desa, cocok, tampil, nilai_awal, kode_awal)
            if tersimpan or time.time() >= akhir:
                break
            self._tunggu(peramban, 0.5)
        return (tersimpan, alasan, tampil, keterangan_kode,
                f"ditunggu {periksa}x periksa (batas {batas:.0f} detik)")

    def _pulihkan_desa(self, peramban, unsur, nilai_awal: str,
                       awalan: str, label: str) -> bool:
        """Kembalikan isi kolom «Desa/Kelurahan» seperti sebelum bot menyentuhnya.

        Bot mengetik kata kunci pencarian ke kotak itu; kalau desanya tidak ketemu, kata
        kunci itu tidak boleh tertinggal di kolom data Dapodik. Isinya dikembalikan ke
        tulisan semula (atau dikosongkan bila memang kosong sejak awal).
        """
        sekarang = self._nilai_teks(self._nilai_dropdown(peramban, unsur)[0])
        if self._norm_pilihan(sekarang) == self._norm_pilihan(nilai_awal):
            return False                      # sudah sama: tidak ada yang perlu dipulihkan
        if not self._ketik_pencarian_desa(peramban, unsur, nilai_awal):
            self._catat_kepala(f"{awalan} {label}: peringatan — kata kunci pencarian masih "
                               "tertinggal di kolomnya (isi semula tidak bisa dikembalikan).")
            return False
        self._tunggu(peramban, 0.6)
        self._catat_kepala(f"{awalan} {label}: isi kolom dikembalikan seperti semula "
                           f"(«{nilai_awal}») supaya data lama Dapodik tidak ikut berubah.")
        return True

    def _desa_tersimpan(self, desa: str, teks: str) -> bool:
        """Periksa hasil pemilihan: teks kolomnya benar-benar memuat **nama desa** yang diminta.

        Kecamatan di dalam teks Dapodik **tidak** dijadikan syarat: data kecamatan di SM bisa
        berbeda/keliru, dan yang menentukan pilihan di Dapodik adalah daftar desanya. Bila
        kecamatannya berbeda, itu dilaporkan terpisah supaya bisa dicek — bukan dijadikan
        alasan menggagalkan pemilihan yang sudah benar.
        """
        d, _, _ = self._bagian_wilayah(teks)
        desa_kata = self._kata_wilayah(desa)
        if not desa_kata:
            return False
        if d == desa_kata or (len(desa_kata) >= 4 and desa_kata in d):
            return True
        rapat_desa = self._kata_rapat(desa)      # «Karang Sari» ↔ «Karangsari»
        rapat_teks = self._kata_rapat(d)
        return bool(rapat_desa) and (
            rapat_desa == rapat_teks
            or (len(rapat_desa) >= 5 and rapat_desa in rapat_teks))

    def _pilihan_tersimpan(self, peramban, unsur) -> tuple[bool, str]:
        """Apakah combo menyimpan sebuah PILIHAN — bukan sekadar teks yang diketik.

        Di Dapodik, mengetik hanya mengisi ``getRawValue()`` (tulisan di kotaknya), sedangkan
        ``getValue()`` — nilai model yang benar-benar dikirim saat «Simpan» — tetap kosong
        sampai sebuah pilihan diambil dari daftarnya. Karena itu hasil pemilihan diperiksa
        dari ``getValue()``. Kembalikan ``(Ext_terbaca, nilai_id)``.
        """
        try:
            hasil = peramban.execute_script(
                """
                /* dropdown-id */
                const el = arguments[0];
                if (!el) return {};
                const id = (el.getAttribute && (el.getAttribute('data-componentid') || el.id)) || '';
                const c = (typeof Ext !== 'undefined' && Ext.getCmp && id)
                    ? Ext.getCmp(String(id).replace(/-inputEl$/, '')) : null;
                if (!c || !c.getValue) return {ext: false, nilai: ''};
                const isi = c.getValue();
                return {ext: true, nilai: (isi === undefined || isi === null) ? '' : String(isi)};
                """, unsur)
        except Exception:  # noqa: BLE001 — tidak terbaca: dinilai dari teksnya
            return False, ""
        if not isinstance(hasil, dict):
            return False, ""
        return bool(hasil.get("ext")), str(hasil.get("nilai") or "")

    def _kode_wilayah(self, peramban, unsur) -> tuple[bool, str]:
        """Baca KODE WILAYAH desa yang benar-benar tersimpan (``kode_wilayah_str``).

        Di Dapodik kolom «Desa/Kelurahan» punya kolom tersembunyi bernama
        ``kode_wilayah_str``; itulah yang menentukan desa mana yang tersimpan saat «Simpan»
        ditekan. Teks di kotaknya bisa sudah berubah sementara kodenya masih menunjuk desa
        yang lama — kejadian yang dilaporkan sekolah (ronde 45). Bot membacanya langsung dari
        DOM, jadi tidak bergantung pada Ext JS.

        Kembalikan ``(terbaca, kode)``.
        """
        try:
            hasil = peramban.execute_script(
                """
                /* kode-wilayah */
                const el = arguments[0] || null;
                const akar = (el && el.closest && el.closest('.x-window')) || document;
                const tepat = (a) => a.querySelector('input[name="kode_wilayah_str"]');
                const mirip = (a) => a.querySelector('input[name^="kode_wilayah"]');
                const cari = tepat(akar) || mirip(akar) || tepat(document) || mirip(document);
                if (!cari) return null;
                return String(cari.value === undefined ? '' : cari.value);
                """, unsur)
        except Exception:  # noqa: BLE001 — tidak terbaca: dinilai dari nilai modelnya
            return False, ""
        if hasil is None:
            return False, ""
        return True, self._nilai_teks(hasil)

    def _nama_kolom_wilayah(self, peramban) -> str:
        """Sebutkan kolom tersembunyi yang ada di halaman — untuk laporan bila kolomnya hilang.

        Dipakai hanya ketika ``kode_wilayah_str`` tidak ditemukan: log menyebut nama-nama kolom
        tersembunyi yang **ada** (mis. versi Dapodik yang menamainya lain), supaya sekolah
        cukup mengirim satu baris log dan penyebabnya bisa langsung diketahui.
        """
        try:
            nama = peramban.execute_script(
                """
                /* nama-kolom-wilayah */
                const hasil = [];
                for (const el of document.querySelectorAll('input[type="hidden"]')) {
                    const nama = String(el.getAttribute('name') || '');
                    if (nama && (nama.indexOf('wilayah') >= 0 || nama.indexOf('kode') >= 0)) {
                        hasil.push(nama);
                    }
                }
                return hasil.slice(0, 6);
                """)
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            return ""
        if not isinstance(nama, list) or not nama:
            return ""
        return ", ".join(str(satu) for satu in nama if str(satu).strip())

    def _catat_desa_terverifikasi(self, peramban, unsur, desa: str, cocok: str,
                                  nilai_awal: str, kode_awal: str) -> None:
        """Simpan keadaan desa yang sudah terverifikasi — untuk diperiksa lagi sebelum «Simpan».

        Pemilihan yang sudah benar masih bisa berubah sesudahnya (mis. nilai kolom berubah
        karena tergulir di dalam jendela «Ubah» — ronde 45). Yang dicatat: kode wilayahnya
        (``kode_wilayah_str``) dan, bila kolom itu tidak ada, nilai model combo-nya.
        """
        terbaca, kode = self._kode_wilayah(peramban, unsur)
        ext_terbaca, nilai_id = self._pilihan_tersimpan(peramban, unsur)
        self._desa_terverifikasi = {
            "unsur": unsur,
            "desa": desa,
            "cocok": cocok,
            "nilai_awal": nilai_awal,
            "kode_awal": kode_awal,
            "kode": kode if terbaca else "",
            "nilai_model": nilai_id if ext_terbaca else "",
        }

    def _pastikan_desa_sebelum_simpan(self, peramban) -> str:
        """Periksa lagi desa/kelurahan tepat sebelum «Simpan»; pasang ulang bila berubah.

        Kembalikan satu kalimat untuk log (kosong = tidak ada yang perlu dikatakan). Bila
        nilainya berubah sesudah diverifikasi, pilihannya dipasang ulang lewat model Ext JS;
        bila itu pun gagal, keadaannya dilaporkan apa adanya supaya tidak ada klaim palsu.
        """
        info = self._desa_terverifikasi
        if not info:
            return ""
        unsur = info["unsur"]
        terbaca, kode = self._kode_wilayah(peramban, unsur)
        if terbaca:
            satuan, sekarang, diharapkan = "kode wilayah", kode, info.get("kode", "")
        else:
            _, nilai_id = self._pilihan_tersimpan(peramban, unsur)
            satuan, sekarang, diharapkan = "nilai pilihan", nilai_id, info.get("nilai_model", "")
        if not diharapkan:
            return ""          # tidak ada yang bisa diperiksa: jangan mengklaim apa pun
        if sekarang == diharapkan:
            return f"[bio] Desa/Kelurahan: {satuan} «{sekarang}» masih utuh sebelum «Simpan» ✓."
        self._catat_kepala(
            f"[bio] Desa/Kelurahan: {satuan} berubah sesudah dipilih — "
            f"«{sekarang or '(kosong)'}» padahal sudah terverifikasi «{diharapkan}»; pilihannya "
            "dipasang ulang lewat model Ext JS supaya Dapodik tidak menyimpan desa yang lama.")
        if not self._pilih_dropdown_ext(peramban, unsur, info["cocok"]):
            return ("[bio] Desa/Kelurahan: peringatan — pilihan tidak bisa dipasang ulang; "
                    "desanya mungkin tetap desa yang lama (kolom lain tetap disimpan, periksa "
                    "hasilnya di Dapodik).")
        self._tunggu(peramban, 0.5)
        tampil_nilai, model = self._nilai_dropdown(peramban, unsur)
        tersimpan, alasan, kode_info = self._desa_dan_kode_terverifikasi(
            peramban, unsur, info["desa"], info["cocok"], tampil_nilai or model,
            info["nilai_awal"], info["kode_awal"])
        if not tersimpan:
            return (f"[bio] Desa/Kelurahan: peringatan — {alasan} (periksa hasilnya di Dapodik "
                    "sesudah disimpan).")
        self.desa_dipulihkan_kali += 1
        return (f"[bio] Desa/Kelurahan: pilihan dipasang ulang sebelum «Simpan» — "
                f"{kode_info or 'nilai pilihannya kembali benar'}.")

    def _desa_dan_kode_terverifikasi(self, peramban, unsur, desa: str, cocok: str, teks: str,
                                     nilai_awal: str, kode_awal: str) -> tuple[bool, str, str]:
        """Tersimpan? — teks desa benar, nilai model terisi, **dan kode wilayahnya ikut pindah**.

        Kembalikan ``(tersimpan, alasan, keterangan_kode)``. Pemeriksaan kode wilayah inilah
        yang menangkap keadaan «teks sudah berubah, kodenya masih desa lama» (``kode_wilayah_str``
        tidak ikut pindah) — kalau itu dibiarkan, Dapodik menyimpan desa yang lama.
        """
        tersimpan, alasan = self._pilihan_desa_terpilih(peramban, unsur, desa, cocok, teks)
        if not tersimpan:
            return False, alasan, ""
        terbaca, kode = self._kode_wilayah(peramban, unsur)
        if not terbaca:
            return True, "", ("kode wilayah (kode_wilayah_str) tidak terbaca dari halaman — "
                              "hasil pemilihan dinilai dari nilai model Ext JS")
        teks_berubah = self._norm_pilihan(teks) != self._norm_pilihan(nilai_awal)
        if teks_berubah and kode == self._nilai_teks(kode_awal):
            return False, ("kode wilayah (kode_wilayah_str) masih «"
                           f"{kode or '(kosong)'}» — belum ikut pindah ke desa yang baru "
                           f"dipilih («{cocok}»), jadi Dapodik akan tetap menyimpan desa "
                           "yang lama"), ""
        return True, "", (f"kode wilayah {self._nilai_teks(kode_awal) or '(kosong)'} → "
                          f"{kode or '(kosong)'} ✓")

    def _pilihan_desa_terpilih(self, peramban, unsur, desa: str, cocok: str,
                               teks: str) -> tuple[bool, str]:
        """Periksa bahwa kolom «Desa/Kelurahan» benar-benar berisi pilihan dari daftar.

        Bukan sekadar tulisannya mirip: **teks yang diketik untuk mencari** juga memuat nama
        desa, jadi pemeriksaan itu saja bisa menyimpulkan "berhasil" padahal Dapodik belum
        menyimpan pilihan apa pun. Karena itu nilai modelnya (``getValue``) diperiksa; bila
        Ext tidak terjangkau, teksnya harus benar-benar teks pilihan dari daftar — bukan kata
        kunci pencarian.
        """
        if not self._desa_tersimpan(desa, teks):
            return False, "teks kolomnya belum memuat nama desa yang diminta"
        ext_terbaca, nilai_id = self._pilihan_tersimpan(peramban, unsur)
        if ext_terbaca:
            if not nilai_id:
                return False, ("model Dapodik masih kosong (getValue kosong) — teks di kotaknya "
                               "baru ketikan pencarian, belum ada pilihan yang tersimpan")
            return True, ""
        if self._norm_pilihan(teks) == self._norm_pilihan(cocok):
            return True, ""                  # teksnya persis pilihan dari daftar
        _, kec_teks, kota_teks = self._bagian_wilayah(teks)
        if kec_teks or kota_teks:
            return True, ""                  # teks pilihan lengkap (desa + kecamatan/kota)
        return False, (f"teks kolomnya «{teks[:60]}» masih berupa kata kunci pencarian — "
                       "pilihan yang tersimpan selalu berupa teks pilihan dari daftar Dapodik")

    def _catat_kecamatan_berbeda(self, label: str, kecamatan: str, teks: str,
                                 awalan: str = "[bio]") -> None:
        """Beri tahu bila kecamatan pada pilihan Dapodik berbeda dari data SM (untuk dicek)."""
        _, k, _ = self._bagian_wilayah(teks)
        kec_kata = self._kata_wilayah(kecamatan)
        if kec_kata and k and k != kec_kata:
            self._catat_kepala(f"{awalan} {label}: peringatan — kecamatan pada pilihan Dapodik "
                               f"«{k}» berbeda dari data SM «{kec_kata}»; desanya tetap yang "
                               "dipilih sesuai daftar Dapodik.")

    def _isi_bio(self, peramban, peta: dict[str, str], siswa: dict[str, Any]) -> bool:
        """Buka jendela «Ubah» lalu isi BIO siswa — persis potongan skrip sekolah.

        Urutan skrip sekolah: tombol «Ubah» ditekan sesudah baris siswa dipilih, tunggu tiga
        detik, lalu tiap kolom diisi dengan Ctrl+A → ketik, dan disimpan dengan tombol
        «Simpan». Tiga hal yang dijaga di sini (dari tangkapan layar sekolah):

        * halaman sekolah punya **dua** set tombol «Ubah»/«Simpan» (toolbar halaman & panel
          «Data Rincian PD») — bot memakai tombol yang benar-benar membuka/menyimpan jendela
          «Edit Peserta Didik»;
        * jendela «Ubah» punya **area gulirnya sendiri** — yang digulir isi jendelanya;
        * kolom yang datanya kosong di SM **tidak** dikosongkan, hanya dilewati & dicatat.
        """
        # Laporan mandiri: dua kalimat keadaan jendela cukup dicatat sekali per siswa.
        self._bio_global_dilaporkan = False
        self._bio_gulir_dilaporkan = False
        self._bukti_dropdown_diambil = False
        self._desa_terverifikasi = None      # keadaan desa milik siswa sebelumnya dibuang
        self._penjaga_nilai.clear()          # nilai kolom milik siswa sebelumnya dibuang
        # Cara perbaikan yang sudah dicoba untuk tiap kolom yang ditolak Dapodik (ronde 50):
        # supaya bot tidak mengosongkan kolom yang sama berulang-ulang, lalu tahu kapan harus
        # beralih mengisi nilainya dari data siswa.
        self._bio_perbaikan_cara.clear()
        kandidat = self._tombol_ubah_semua(peramban, peta)
        if not kandidat:
            self._catat_kepala("[bio] tombol «Ubah» tidak ada di halaman ini — langkah BIO "
                               "dilewati (versi Dapodik sekolah mungkin berbeda).")
            return False
        self._catat_kepala(f"[bio] tombol «Ubah» terlihat: {len(kandidat)} kandidat — dicoba "
                           "satu per satu sampai jendela «Edit Peserta Didik» terbuka.")
        jendela = None
        for nomor, tombol in enumerate(kandidat, start=1):
            self._bawa_ke_layar(peramban, tombol)
            try:
                tombol.click()
            except Exception:  # noqa: BLE001 — klik sungguhan bisa tertelan; lanjut lewat skrip
                try:
                    peramban.execute_script("arguments[0].click();", tombol)
                except Exception:  # noqa: BLE001 — diperiksa dari jendelanya
                    pass
            self._tunggu(peramban, 3)          # skrip sekolah menunggu 3 detik
            jendela = self._jendela_edit(peramban, peta)
            if jendela is not None:
                self._catat_kepala(f"[bio] jendela «Edit Peserta Didik» terbuka "
                                   f"({self._judul_jendela(peramban, jendela)}) — kandidat ke-"
                                   f"{nomor} dari {len(kandidat)}.")
                break
            self._catat_kepala(f"[bio] kandidat «Ubah» ke-{nomor} tidak membuka jendela "
                               "«Edit Peserta Didik» — dicoba kandidat berikutnya.")
        if jendela is None:
            # Jendelanya tidak bisa dikenali. JANGAN menyerah: skrip sekolah mengisi kolomnya
            # lewat `find_element(By.NAME, …)` tanpa mempedulikan jendelanya — jadi cara itu
            # dipakai sebagai cadangan, dan kolomnya dicari sambil halaman digulir.
            self._catat_kepala("[bio] jendela «Edit Peserta Didik» belum terbaca (judulnya tidak "
                               "ketemu) — kolomnya dilacak lewat namanya seperti skrip sekolah, "
                               "halaman digulir bila kolomnya belum tampil.")
            self._catat_kepala(self._rincian_bio(peramban, None, peta, "sebelum mengisi"))
        self._catat_kepala(self._rincian_bio(peramban, jendela, peta, "keadaan jendela"))
        jumlah_wadah = self._atur_gulir_jendela(peramban, jendela, 0)
        self._catat_kepala(f"[bio] isi jendela «Ubah» dikembalikan ke atas "
                           f"({jumlah_wadah} area gulir) — kolomnya dicari sambil jendelanya "
                           "digeser 250 px bertahap, jadi tidak bergantung pada "
                           "«gulir kebanyakan atau kurang banyak».")
        self._catat_kepala(f"[bio] mengisi BIO ({len(self.BIO_KOLOM)} kolom seperti skrip "
                           "sekolah): No. KK, akta, alamat/RT/RW, desa/kelurahan, kode pos, "
                           "anak ke-berapa, data ayah & ibu — tiap kolom dibawa ke layar "
                           "lebih dulu, dan bila ketikan ditolak Dapodik nilainya dicoba "
                           "lewat Ext JS.")
        terisi = 0
        kosong: list[str] = []
        for kunci_data, label, kunci_sel in self.BIO_KOLOM:
            nilai = self._nilai_teks(siswa.get(kunci_data))
            if not nilai:
                kosong.append(label)
                self._catat_kepala(f"[bio] {label}: data siswa kosong — dilewati "
                                   "(kolom Dapodik tidak dikosongkan).")
                continue
            unsur = self._cari_kolom_bio(peramban, peta, kunci_sel, jendela, label)
            if unsur is None:
                # Jujur + memberi bukti (ronde 48: «untuk log adanya dimana?»): sebut kolom apa
                # yang tidak ketemu, kandidat selector yang dicoba beserta jumlah unsurnya, dan
                # kolom isian apa yang BENAR-BENAR ADA di halaman. Dulu catatannya hanya
                # «dilewati» tanpa bukti, sehingga sebabnya harus ditebak.
                self._catat_kepala(
                    f"[bio] {label}: kolomnya TIDAK ketemu di jendela «Ubah» — kandidat yang "
                    f"dicoba beserta jumlah unsur yang ditemukan: "
                    f"{self._rincian_kandidat_kolom(peramban, kunci_sel, peta)}.")
                daftar_isian = self._rincian_kolom_halaman(peramban)
                if daftar_isian:
                    self._catat_kepala(f"[bio] {label}: kolom isian yang ADA di halaman (nama): "
                                       f"{daftar_isian}")
                if kunci_sel == "bio_kelurahan":
                    # Kolom combo «Desa/Kelurahan» adalah kolom yang paling sering dilaporkan
                    # «tidak ditemukan» (ronde 47) — sebutkan isian apa saja yang ADA di jendela
                    # «Ubah», supaya sebabnya terbaca dari catatan itu.
                    isian = self._rincian_isian_bio(peramban, jendela)
                    self._catat_kepala(
                        "[bio] Desa/Kelurahan: isian yang ADA di jendela «Ubah» (nama/jenis): "
                        + (isian or "(tidak terbaca)") +
                        " — kandidat yang dicoba: label «Desa/Kelurahan», name «kode_wilayah», "
                        "input[name*=wilayah], lalu XPath lengkap dari sekolah.")
                self._catat_kepala(self._rincian_bio(peramban, jendela, peta,
                                                     f"saat kolom «{label}» tidak ketemu"))
                bukti = self._bukti(peramban, "bio-kolom-tidak-ketemu")
                if bukti:
                    self._catat_kepala(f"[bio] bukti layar disimpan: {bukti} "
                                       "(beserta berkas .html di folder yang sama).")
                continue
            # Kolom «Desa/Kelurahan» punya cara sendiri: satu combo memuat desa + kecamatan
            # + kota, dan daftarnya baru diambil Dapodik sesudah nama kecamatan diketik.
            if kunci_sel == "bio_kelurahan":
                keterangan = self._isi_desa_kelurahan(peramban, peta, label, unsur, siswa)
            # Dropdown (combo Ext JS) diisi lain: pilihannya harus benar-benar dipilih dari
            # daftarnya — mengetikkan teksnya saja tidak menyimpan apa pun ke Dapodik.
            # Ronde 49: jalur daftar hanya dipakai bila buktinya KUAT (role=combobox,
            # aria-owns daftar, xtype combo, atau store berisi). Kolom yang hanya punya unsur
            # mirip panah dicoba **diketik lebih dulu**; bila ketikannya tidak tersimpan
            # (model Ext JS kosong) barulah daftarnya dicoba — sehingga kolom biasa tidak
            # pernah lagi «dilewati» hanya karena ada unsur bergaya panah di kotaknya.
            # ``elif`` — penting: kolom «Desa/Kelurahan» sudah diisi oleh jalurnya sendiri di
            # atas, dan keterangan desa (termasuk «dipilih dari daftar Dapodik» + kode
            # wilayah) TIDAK boleh ditimpa jalur dropdown biasa (kalau ditimpa, kolomnya
            # dikerjakan dua kali dan catatannya kehilangan bukti kode wilayahnya).
            elif self._info_kolom(peramban, unsur).get("kombo_kuat"):
                keterangan = self._isi_dropdown_bio(peramban, peta, label, nilai, unsur)
            else:
                info_kolom = self._info_kolom(peramban, unsur)
                if info_kolom.get("panah"):
                    self._catat_kepala(
                        f"[bio] {label}: ada unsur mirip panah di kotaknya, tetapi tidak ada bukti combo "
                        "(role=combobox / aria-owns / xtype combo / store) — "
                        "nilainya dicoba diketik lebih dulu seperti kolom biasa. Keadaan "
                        "kolom: " + self._rincian_jenis_kolom(peramban, unsur))
                keterangan = self._isi_periodik_satu(peramban, peta, kunci_sel, label, nilai,
                                                     unsur, awalan="[bio]")
                if not keterangan.startswith("terisi"):
                    # Ronde 49: kolom yang tampak kolom biasa tetapi menolak ketikan —
                    # mis. combo yang panahnya tidak terbaca — dicoba lewat jalur dropdown.
                    # Nilai combo hanya tersimpan bila pilihannya diambil dari daftar.
                    info = self._info_kolom(peramban, unsur)
                    if (info.get("komponen") or info.get("panah")
                            or int(info.get("store") or -1) > 0):
                        self._catat_kepala(f"[bio] {label}: ketikan tidak tersimpan — "
                                           "kolomnya punya komponen Ext JS/data pilihan, "
                                           "jadi dicoba lewat daftar dropdown. Keadaan "
                                           "kolom: "
                                           + self._rincian_jenis_kolom(peramban, unsur))
                        keterangan = self._isi_dropdown_bio(peramban, peta, label, nilai,
                                                            unsur)
                else:
                    # Kotaknya sudah berisi, tetapi **model Ext JS**-nya kosong: itulah tanda
                    # combo Dapodik yang menolak ketikan (yang tersimpan hanya pilihan dari
                    # daftarnya) — kolom seperti ini tampak «sudah diisi» padahal Dapodik
                    # tidak menyimpan apa pun. Karena itu dicoba lewat daftar dropdown.
                    model = self._nilai_model(peramban, unsur)
                    if model == "":
                        self._catat_kepala(f"[bio] {label}: kotaknya sudah berisi «{nilai}» "
                                           "tetapi model Ext JS-nya kosong — combo Dapodik "
                                           "hanya menyimpan pilihan dari daftarnya, jadi "
                                           "dicoba lewat daftar dropdown. Keadaan kolom: "
                                           + self._rincian_jenis_kolom(peramban, unsur))
                        keterangan = self._isi_dropdown_bio(peramban, peta, label, nilai,
                                                            unsur)
            self._catat_kepala(f"[bio] {label}: {keterangan}")
            if keterangan.startswith("terisi"):
                terisi += 1
                # Kolom yang sudah benar dicatat nilainya; sesudah setiap gulir, nilainya
                # diperiksa lagi (gulir pernah mengubah «RT» menjadi «0» — ronde 45).
                try:
                    nilai_sekarang = str(unsur.get_attribute("value") or "").strip()
                except Exception:  # noqa: BLE001 — pembacaan nilai hanya upaya terbaik
                    nilai_sekarang = ""
                if nilai_sekarang:
                    self._rekam_nilai_bio(unsur, nilai_sekarang)
                self._periksa_nilai_bio(peramban, awalan="[bio]")
            else:
                # Nilai tidak masuk ke kolomnya: inilah saat paling penting untuk merekam
                # keadaan halaman — screenshot + HTML, supaya sebabnya bisa dilihat langsung.
                self._catat_kepala(self._rincian_bio(peramban, jendela, peta,
                                                     f"saat kolom «{label}» tidak terisi"))
                bukti = self._bukti(peramban, "bio-tidak-terisi")
                if bukti:
                    self._catat_kepala(f"[bio] bukti layar disimpan: {bukti} "
                                       "(beserta berkas .html di folder yang sama).")
            time.sleep(0.5)          # jeda antar kolom supaya Ext JS selesai memproses
        # Ronde 45: SEMUA kolom diperiksa lagi tepat sebelum «Simpan» — nilai kolom mana pun
        # bisa berubah sesudah diisi (mis. tergulir di dalam jendela «Ubah»).
        kembali = self._periksa_nilai_bio(peramban, "[bio]")
        if kembali:
            self._catat_kepala(f"[bio] {len(kembali)} kolom dikembalikan ke nilai yang benar "
                               "sebelum «Simpan».")
        # Desa/kelurahan diperiksa tersendiri: kode wilayahnya belum tentu ikut pada nilai teks.
        catatan_desa = self._pastikan_desa_sebelum_simpan(peramban)
        if catatan_desa:
            self._catat_kepala(catatan_desa)
        # Simpan: tombol «Simpan» DI DALAM jendela «Ubah» (bukan milik panel Data Rincian).
        simpan = self._simpan_dalam_jendela(peramban, jendela)
        if simpan is None:
            # Wadah jendelanya tidak terbaca oleh JavaScript (versi Dapodik lain): tombolnya
            # dicari di halaman dengan menyaring tombol milik panel «Data Rincian PD».
            self._catat_kepala("[bio] tombol «Simpan» di dalam jendela tidak terbaca — "
                               "mencari di halaman (tombol panel «Data Rincian PD» disaring).")
            simpan = self._simpan_dalam_jendela(peramban, None)
        if simpan is None:
            self._catat_kepala("[bio] tombol «Simpan» di dalam jendela «Ubah» tidak ketemu — "
                               f"kolom yang sudah terisi ({terisi}) dicatat, tetapi belum bisa "
                               "dipastikan tersimpan.")
            return False
        self._catat_kepala("[bio] menyimpan lewat tombol «Simpan» di dalam jendela «Ubah» "
                           "(tombol «Simpan» milik panel «Data Rincian PD» tidak dipakai).")
        try:
            simpan.click()
        except Exception:  # noqa: BLE001 — klik sungguhan bisa tertelan; lanjut lewat skrip
            try:
                peramban.execute_script("arguments[0].click();", simpan)
            except Exception:  # noqa: BLE001 — keadaan jendelanya diperiksa di bawah
                pass
        self._tunggu(peramban, 2)
        if self._jendela_edit(peramban, peta) is not None:
            self._catat_kepala("[bio] peringatan: tombol «Simpan» sudah ditekan tetapi jendela "
                               "«Edit Peserta Didik» masih terlihat — Dapodik MENOLAK simpan "
                               "(datanya belum masuk).")
            daftar_galat = self._galat_validasi_bio(peramban, jendela)
            if daftar_galat:
                self._catat_kepala("[bio] galat validasi di jendela «Ubah» (dari Dapodik): "
                                   + self._galat_validasi_teks(daftar_galat))
            wajib = self._kolom_wajib_kosong_bio(peramban, jendela)
            if wajib:
                self._catat_kepala("[bio] kolom WAJIB yang masih kosong di jendela «Ubah» "
                                   "(dari Dapodik): " + wajib)
            bukti_tidak_tutup = self._bukti(peramban, "bio-simpan-tidak-menutup")
            if bukti_tidak_tutup:
                self._catat_kepala(f"[bio] bukti layar disimpan: {bukti_tidak_tutup} "
                                   "(beserta berkas .html di folder yang sama).")
            # Ronde 50: kolom yang ditolak Dapodik diisi ulang dari data SM (kolom wali
            # mengikuti ayah bila siswa memang tidak punya wali), lalu «Simpan» ditekan lagi.
            # Dua cara dipakai BERURUTAN karena bacaan atas galatnya ada dua: kolom angka «0»
            # yang ditolak «minimum value … is 1» dikosongkan lebih dulu (Dapodik memakai «0»
            # sebagai penanda kosong), dan bila Dapodik masih menolak kolom yang sama, kolom
            # itu memang harus berisi nilai — diambil dari data siswa bila ada. Tiap putaran
            # dicatat; yang tidak ada datanya tidak dikarang dan tidak diaku berhasil.
            putaran = 0
            galat_kini = daftar_galat
            while galat_kini and putaran < self.BATAS_PERBAIKAN_BIO:
                diperbaiki = self._perbaiki_galat_validasi_bio(peramban, peta, siswa, jendela,
                                                               galat_kini)
                if not diperbaiki:
                    break
                putaran += 1
                self._catat_kepala(f"[bio] perbaikan ke-{putaran}: {diperbaiki} kolom yang "
                                   "ditolak Dapodik dicoba dibetulkan dari data SM — «Simpan» "
                                   "ditekan lagi.")
                self._tekan_simpan_bio(peramban, jendela, peta)
                if self._jendela_edit(peramban, peta) is None:
                    rincian_ulang = (f", {len(kosong)} kolom dilewati (data kosong)"
                                     if kosong else "")
                    self._catat_kepala("[bio] jendela «Ubah» tertutup SESUDAH perbaikan — data "
                                       f"BIO dikirim ({terisi} kolom terisi{rincian_ulang}).")
                    return True
                galat_kini = self._galat_validasi_bio(peramban, jendela)
                if galat_kini:
                    self._catat_kepala("[bio] galat yang MASIH tersisa sesudah perbaikan: "
                                       + self._galat_validasi_teks(galat_kini))
                else:
                    self._catat_kepala("[bio] jendela «Ubah» masih terbuka sesudah perbaikan, "
                                       "tetapi Dapodik tidak menampilkan pesan galat apa pun.")
            if galat_kini and putaran >= self.BATAS_PERBAIKAN_BIO:
                self._catat_kepala(f"[bio] batas {self.BATAS_PERBAIKAN_BIO} putaran perbaikan "
                                   "tercapai tetapi Dapodik masih menolak — kolom yang tersisa "
                                   "perlu dibetulkan manual sekali di Dapodik (bot tidak "
                                   "mengarang nilainya).")

            if self._tutup_jendela_ubah(peramban, jendela, peta):
                self._catat_kepala("[bio] jendela «Ubah» ditutup bot supaya langkah Data "
                                   "Periodik & Registrasi tidak terganggu (baris siswa "
                                   "diperiksa & dicari ulang sesudahnya) — data BIO siswa ini "
                                   "BELUM tersimpan.")
            else:
                self._catat_kepala("[bio] peringatan: jendela «Ubah» tidak bisa ditutup bot — "
                                   "langkah Data Periodik & Registrasi bisa terganggu "
                                   "(Dapodik masih menampilkan jendela itu).")
            return False
        rincian = f", {len(kosong)} kolom dilewati (data kosong)" if kosong else ""
        self._catat_kepala(f"[bio] jendela «Ubah» tertutup — data BIO dikirim "
                           f"({terisi} kolom terisi{rincian}).")
        return True

    def _galat_validasi_bio(self, peramban, jendela) -> list[dict[str, Any]]:
        """Galat validasi Dapodik di jendela «Ubah» — lengkap dengan label & bagiannya.

        Ronde 49 hanya mencatat «nama: pesan», dan di sekolah dua kolom yang ditolak berbunyi
        «pekerjaan_id_wali: This field is required» serta «inputItem: The minimum value for
        this field is 1» — nama kolomnya saja tidak cukup untuk tahu kolom MANA yang harus
        dibetulkan. Sejak ronde 50 setiap galat dibaca bersama **label kolomnya** (dari DOM
        maupun ``fieldLabel`` komponennya), **bagian** formulirnya (fieldset «Data Ayah/Ibu/
        Wali»), jenis komponen, nilai yang ada sekarang, dan id komponennya — dan daftar itu
        dipakai :meth:`_perbaiki_galat_validasi_bio` untuk membetulkan kolomnya.
        """
        try:
            galat = peramban.execute_script(
                JS_ALAT + r"""
                /* galat-validasi */
                const root = arguments[0] || document;
                const hasil = [];
                const rapi = (t) => String(t || '').replace(/\s+/g, ' ').trim();
                const wadahLabel = (el) => {
                    let p = el, naik = 0;
                    while (p && p !== document.body && naik < 8) {
                        const banyak = p.querySelectorAll
                            ? p.querySelectorAll('input, textarea, select').length : 99;
                        const l = p.querySelector
                            ? p.querySelector('label, .x-fieldlabel, .x-form-item-label') : null;
                        if (l && banyak <= 3) return l;
                        p = p.parentElement; naik += 1;
                    }
                    return null;
                };
                const label = (el) => {
                    const l = wadahLabel(el);
                    const dariDom = l && l.textContent ? rapi(l.textContent) : '';
                    if (dariDom) return dariDom;
                    const c = komponenKolom(el);
                    return rapi(c && c.fieldLabel ? c.fieldLabel : '');
                };
                const bagian = (el) => {
                    let p = el, naik = 0;
                    while (p && naik < 14) {
                        const h = p.querySelector
                            ? p.querySelector('.x-fieldset-header-text, legend, '
                                              + '.x-panel-header-text')
                            : null;
                        const t = h && h.textContent ? rapi(h.textContent) : '';
                        if (t) return t;
                        p = p.parentElement; naik += 1;
                    }
                    return '';
                };
                for (const el of root.querySelectorAll('input, textarea, select')) {
                    const c = komponenKolom(el);
                    let pesan = '';
                    try {
                        if (c && c.getErrors) {
                            const g = c.getErrors();
                            pesan = Array.isArray(g) ? g.join('; ') : String(g || '');
                        }
                        if (!pesan && c && c.hasActiveError && c.hasActiveError()) {
                            const g = c.getActiveError ? c.getActiveError() : '';
                            pesan = String((g && (g.title || g.text)) || '');
                        }
                    } catch (e) { pesan = ''; }
                    if (!pesan) {
                        const bidang = bidangKolom(el);
                        if (bidang && bidang.querySelector) {
                            const t = bidang.querySelector('.x-form-invalid-under, '
                                + '.x-form-error-msg, .x-form-invalid-icon');
                            if (t) {
                                pesan = String((t.textContent
                                    || t.getAttribute('data-errorqtip')) || '');
                            }
                        }
                    }
                    pesan = rapi(pesan);
                    if (!pesan) continue;
                    const nama = String(el.getAttribute('name') || el.id || '?');
                    if (hasil.some((g) => g.nama === nama && g.pesan === pesan)) continue;
                    hasil.push({nama: nama, pesan: pesan, label: label(el),
                                bagian: bagian(el),
                                xtype: xtypeKolom(c) || String(el.getAttribute('type') || ''),
                                nilai: (c && c.getValue) ? String(c.getValue() || '')
                                                         : String(el.value || ''),
                                id: String(el.id || ''),
                                terlihat: !!(el.getClientRects && el.getClientRects().length)});
                    if (hasil.length >= 14) break;
                }
                if (hasil.length) return hasil;
                const umum = [];
                for (const t of root.querySelectorAll('.x-form-invalid-under, .x-form-error-msg')) {
                    const teks = rapi(t.textContent);
                    if (teks && !umum.some((p) => p.pesan === teks)) {
                        umum.push({nama: '', pesan: teks, label: '', bagian: '', xtype: '',
                                   nilai: '', id: '', terlihat: true});
                    }
                }
                return umum.slice(0, 8);
                """, jendela)
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            return []
        if not isinstance(galat, list):
            return []
        return [satu for satu in galat
                if isinstance(satu, dict) and str(satu.get("pesan") or "").strip()]

    def _galat_validasi_teks(self, daftar) -> str:
        """Satu baris galat validasi: «nama (label «…», bagian «…»): pesan»."""
        baris: list[str] = []
        for satu in daftar or []:
            nama = str(satu.get("nama") or "?").strip() or "?"
            label = str(satu.get("label") or "").strip()
            bagian = str(satu.get("bagian") or "").strip()
            petunjuk: list[str] = []
            if label:
                petunjuk.append(f"label «{label}»")
            if bagian:
                petunjuk.append(f"bagian «{bagian}»")
            tambahan = f" ({', '.join(petunjuk)})" if petunjuk else ""
            baris.append(f"{nama}{tambahan}: {satu.get('pesan')}")
        return "; ".join(baris)

    def _nilai_kolom_bernama(self, peramban, jendela, kandidat) -> str:
        """Nilai sebuah kolom Dapodik yang dicari lewat namanya (mis. nama wali).

        Dipakai untuk tahu apakah siswa ini **punya wali di Dapodik**: bila nama walinya
        memang kosong, kolom wali yang ditolak Dapodik boleh diisi mengikuti data ayah
        (lihat :meth:`_perbaiki_galat_validasi_bio`).
        """
        nama_kandidat = [str(k) for k in (kandidat if isinstance(kandidat, (list, tuple))
                                          else (kandidat,)) if str(k).strip()]
        if not nama_kandidat:
            return ""
        try:
            nilai = peramban.execute_script(
                JS_ALAT + r"""
                /* nilai-kolom-bernama */
                const root = arguments[0] || document;
                const nama = arguments[1] || [];
                for (const el of root.querySelectorAll('input, textarea')) {
                    if (nama.indexOf(String(el.getAttribute('name') || '')) < 0) continue;
                    const c = komponenKolom(el);
                    const nilai = (c && c.getValue) ? c.getValue() : el.value;
                    return String(nilai == null ? '' : nilai).trim();
                }
                return '';
                """, jendela, nama_kandidat)
        except Exception:  # noqa: BLE001 — hanya keterangan tambahan
            return ""
        return str(nilai or "").strip()

    def _unsur_kolom_bernama(self, peramban, jendela, nama: str):
        """Kotak isian milik sebuah NAMA kolom Dapodik — dipakai saat memperbaiki galat.

        Kolom yang ditolak Dapodik sering hanya muncul sebagai **input tersembunyi** (lazim
        pada combo Ext JS: ``<input type="hidden" name="pekerjaan_id_wali">``). Yang
        dikembalikan adalah kotak yang benar-benar perlu diisi: ``inputEl`` komponennya atau
        unsur terlihat paling dekat di wadah kolomnya.
        """
        if not str(nama or "").strip():
            return None
        try:
            return peramban.execute_script(
                JS_ALAT + r"""
                /* unsur-kolom-bernama */
                const root = arguments[0] || document;
                const nama = String(arguments[1] || '');
                if (!nama) return null;
                const tampil = (el) => !!el
                    && !!(el.getClientRects && el.getClientRects().length)
                    && String((el.getAttribute && el.getAttribute('type')) || '')
                        .toLowerCase() !== 'hidden';
                const cocok = (el) => {
                    const n = String((el.getAttribute && el.getAttribute('name')) || '');
                    const id = String(el.id || '');
                    return n === nama || id === nama || id.indexOf(nama + '-') === 0;
                };
                for (const el of root.querySelectorAll('input, textarea')) {
                    if (cocok(el) && tampil(el)) return el;
                }
                for (const el of root.querySelectorAll('input, textarea')) {
                    if (!cocok(el)) continue;
                    const c = komponenKolom(el);
                    if (c && c.inputEl && c.inputEl.dom) return c.inputEl.dom;
                    const bidang = el.parentElement;
                    if (bidang && bidang.querySelectorAll) {
                        for (const lain of bidang.querySelectorAll('input, textarea')) {
                            if (tampil(lain)) return lain;
                        }
                    }
                    return el;
                }
                return null;
                """, jendela, nama)
        except Exception:  # noqa: BLE001 — pemanggil mencatatnya jujur
            return None

    def _keluarga_dari_nama(self, nama: str, label: str, bagian: str) -> tuple[str, str]:
        """Orang (ayah/ibu/wali) + atribut (pekerjaan, penghasilan, …) dari nama/label kolom."""
        teks = " ".join((str(nama or ""), str(label or ""), str(bagian or "")))
        teks = teks.lower().replace(" ", "_")
        orang = ""
        for calon, pola in (("wali", ("wali",)), ("ayah", ("ayah", "bapak")), ("ibu", ("ibu",))):
            if any(p in teks for p in pola):
                orang = calon
                break
        if not orang:
            return "", ""
        atribut = ""
        for pola, kunci in self.ATRIBUT_KELUARGA.items():
            if pola in teks:
                atribut = kunci
                break
        return orang, atribut

    def _perbaiki_galat_validasi_bio(self, peramban, peta: dict[str, str],
                                     siswa: dict[str, Any], jendela, daftar_galat) -> int:
        """Isi kolom yang DITOLAK Dapodik memakai data yang memang ada di SM (ronde 50).

        Sebab «Simpan» ditolak di sekolah (catatan 29 Sep 2026) terbaca dari galatnya:
        «pekerjaan_id_wali: This field is required» dan «inputItem: The minimum value for this
        field is 1». Data siswa SM tidak menyimpan wali (aturan aplikasi: wali hanya bila nama
        ayah kosong), sedangkan Dapodik tetap mewajibkan kolom wali. Yang dilakukan bot:

        * kolom angka yang ditolak dengan «minimum value … is 1» dan **berisi «0»**
          dikosongkan — Dapodik mengisi sendiri kolom seperti itu dengan «0» sebagai penanda
          kosong, dan nilai itulah yang membuat penyimpanan gagal (bukan data siswa);
        * kolom wali yang ditolak diisi dari data wali SM bila ada; bila SM tidak punya wali
          **dan** Dapodik juga belum punya nama wali, kolomnya diisi mengikuti data ayah
          (bawaan; dapat dimatikan lewat pengaturan «Wali mengikuti ayah»);
        * kolom ayah/ibu yang ditolak diisi dari data ayah/ibu SM.

        Tidak ada nilai yang dikarang: yang tidak ada datanya dilaporkan apa adanya (dan bot
        tidak mengaku berhasil). Kembalikan banyaknya kolom yang berhasil diisi ulang.
        """
        ikut_ayah = str(self.opsi.get("bot_wali_ikuti_ayah", "1")) == "1"
        nama_wali = self._nilai_kolom_bernama(peramban, jendela, ("nama_wali", "wali_nama"))
        dipakai = 0
        for satu in daftar_galat or []:
            nama = str(satu.get("nama") or "").strip()
            label = str(satu.get("label") or "").strip() or nama or "?"
            bagian = str(satu.get("bagian") or "").strip()
            pesan = str(satu.get("pesan") or "").strip()
            nilai_kini = str(satu.get("nilai") or "").strip()
            tempat = f"{nama}{', bagian «' + bagian + '»' if bagian else ''}"
            dicoba = self._bio_perbaikan_cara.setdefault(nama or label, set())
            if ("minimum value" in pesan.lower() and nilai_kini in ("0", "0.0", "-0")
                    and "kosongkan" not in dicoba):
                # Bacaan pertama: «0» adalah penanda KOSONG bawaan Dapodik (rujukan
                # panduandapik.id) — kolomnya dikosongkan, data siswa tidak diubah.
                unsur_nol = self._unsur_kolom_bernama(peramban, jendela, nama) if nama else None
                if unsur_nol is not None and self._set_ext(peramban, unsur_nol, ""):
                    dicoba.add("kosongkan")
                    self._catat_kepala(
                        f"[bio-perbaikan] kolom «{label}» ({tempat}) berisi «0» dan ditolak "
                        f"Dapodik («{pesan}») — nilai «0» itu penanda kosong dari Dapodik, "
                        "jadi kolomnya dikosongkan (data siswa tidak diubah).")
                    dipakai += 1
                else:
                    self._catat_kepala(
                        f"[bio-perbaikan] kolom «{label}» ({tempat}) berisi «0» dan ditolak "
                        f"Dapodik («{pesan}»), tetapi bot tidak bisa mengosongkannya — mohon "
                        "dikosongkan manual sekali di Dapodik.")
                continue
            unsur = self._unsur_kolom_bernama(peramban, jendela, nama) if nama else None
            if unsur is None:
                self._catat_kepala(f"[bio-perbaikan] kolom «{label}» ({tempat}) ditolak Dapodik "
                                   f"(«{pesan}») tetapi kotaknya tidak ketemu — dilewati.")
                continue
            orang, atribut = self._keluarga_dari_nama(nama, label, bagian)
            nilai = self._nilai_teks(siswa.get(f"{orang}_{atribut}")) if (orang and atribut) else ""
            sumber = f"data {orang}" if nilai else ""
            if (not nilai and orang == "wali" and ikut_ayah and not nama_wali
                    and atribut in ("pendidikan", "pekerjaan", "penghasilan")):
                # HANYA pendidikan/pekerjaan/penghasilan wali yang boleh mengikuti ayah —
                # kolom wajib bagian «Wali» di Dapodik. Nama & NIK wali TIDAK PERNAH diisi
                # dari data ayah: itu akan mengarang wali yang tidak ada.
                nilai = self._nilai_teks(siswa.get(f"ayah_{atribut}"))
                if nilai:
                    sumber = ("data ayah (siswa ini tidak punya wali di data SM dan Dapodik "
                              "juga belum punya nama wali — kolom wali diisi mengikuti ayah)")
            if not nilai:
                tambahan = ""
                if orang == "wali" and atribut and not ikut_ayah:
                    tambahan = (", dan pengaturan «Wali mengikuti ayah» sedang dimatikan"
                                " (Pengaturan bot)")
                elif orang == "wali" and atribut in ("nama", "nik"):
                    tambahan = (", dan kolom identitas wali (nama/NIK) memang TIDAK pernah "
                                "diisi dari data ayah oleh bot — itu akan mengarang wali yang "
                                "tidak ada")
                elif "kosongkan" in dicoba:
                    tambahan = (", dan kolomnya sudah dikosongkan sekali — Dapodik tetap "
                                "menolaknya, jadi kolom itu memang harus berisi nilai")
                self._catat_kepala(f"[bio-perbaikan] kolom «{label}» ({tempat}) ditolak Dapodik "
                                   f"(«{pesan}») — data yang cocok tidak ada di SM{tambahan} — "
                                   "tidak diisi asal-asalan.")
                continue
            info = self._info_kolom(peramban, unsur)
            if info.get("kombo_kuat"):
                keterangan = self._isi_dropdown_bio(peramban, peta, label, nilai, unsur,
                                                    awalan="[bio-perbaikan]")
            else:
                keterangan = self._isi_periodik_satu(peramban, peta, "", label, nilai, unsur,
                                                     awalan="[bio-perbaikan]")
                if not keterangan.startswith("terisi") and (info.get("panah")
                        or int(info.get("store") or -1) > 0):
                    keterangan = self._isi_dropdown_bio(peramban, peta, label, nilai, unsur,
                                                        awalan="[bio-perbaikan]")
            if keterangan.startswith("terisi"):
                dipakai += 1
                self._catat_kepala(f"[bio-perbaikan] kolom «{label}» ({tempat}) diisi dari "
                                   f"{sumber}: {keterangan}")
            else:
                self._catat_kepala(f"[bio-perbaikan] kolom «{label}» ({tempat}) belum berhasil "
                                   f"diisi dari {sumber}: {keterangan}")
        return dipakai

    def _kolom_wajib_kosong_bio(self, peramban, jendela) -> str:
        """Kolom WAJIB (``allowBlank: false``) yang masih kosong di jendela «Ubah».

        Dapodik menandai kolom wajibnya di **komponen Ext JS**, bukan di DOM — jadi daftar ini
        dibaca dari komponennya. Satu baris catatan ini membuat sebab penolakan «Simpan»
        terbaca langsung (mis. «Pekerjaan Wali», «Tahun Lahir Wali») tanpa memotret layar.
        """
        try:
            wajib = peramban.execute_script(
                JS_ALAT + r"""
                /* kolom-wajib-kosong */
                const root = arguments[0] || document;
                const rapi = (t) => String(t || '').replace(/\s+/g, ' ').trim();
                const hasil = [];
                for (const el of root.querySelectorAll('input, textarea, select')) {
                    const c = komponenKolom(el);
                    if (!c || c.allowBlank !== false) continue;
                    let nilai = el.value;
                    try { if (c.getValue) nilai = c.getValue(); } catch (e) { /* el.value */ }
                    if (String(nilai == null ? '' : nilai).trim()) continue;
                    const bidang = bidangKolom(el);
                    const l = bidang && bidang.querySelector
                        ? bidang.querySelector('label, .x-fieldlabel, .x-form-item-label') : null;
                    let teks = rapi((l && l.textContent) || (c.fieldLabel || ''));
                    const nama = String(el.getAttribute('name') || el.id || '?');
                    if (!teks) teks = nama;
                    const baris = teks + ' (' + nama + ')';
                    if (hasil.indexOf(baris) < 0) hasil.push(baris);
                    if (hasil.length >= 12) break;
                }
                return hasil;
                """, jendela)
        except Exception:  # noqa: BLE001 — keterangan tambahan saja
            return ""
        if not isinstance(wajib, list) or not wajib:
            return ""
        return ", ".join(str(satu) for satu in wajib if str(satu).strip())

    def _tutup_jendela_ubah(self, peramban, jendela, peta: dict[str, str]) -> bool:
        """Tutup jendela «Ubah» yang tetap terbuka sesudah «Simpan» ditolak Dapodik.

        Jendela yang dibiarkan terbuka menutupi halaman Peserta Didik — di sekolah akibatnya
        baris siswa tidak lagi terpilih sesudah Data Periodik disimpan. Bot menutupnya (tombol
        silang ``x-tool-close``, lalu tombol Esc) dan memastikan jendelanya benar-benar hilang.
        """
        if jendela is None:
            jendela = self._jendela_edit(peramban, peta)
        if jendela is None:
            return True
        try:
            peramban.execute_script(
                r"""
                /* tutup-jendela-ubah */
                const root = arguments[0] || document;
                const dekat = (akar) => (akar && akar.querySelector)
                    ? akar.querySelector('.x-tool-close, .x-tool.x-tool-close, a.x-tool-close')
                    : null;
                const tombol = dekat(root) || dekat(document) || dekat(document.body);
                if (tombol) { tombol.click(); return true; }
                return false;
                """, jendela)
        except Exception:  # noqa: BLE001 — masih ada jalur Esc di bawah
            pass
        self._tunggu(peramban, 1)
        if self._jendela_edit(peramban, peta) is not None:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys

            try:
                peramban.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:  # noqa: BLE001 — keadaan jendelanya diperiksa sesudahnya
                pass
            self._tunggu(peramban, 1)
        return self._jendela_edit(peramban, peta) is None
    def _tekan_simpan_bio(self, peramban, jendela, peta: dict[str, str]) -> None:
        """Tekan «Simpan» milik jendela «Ubah» SEKALI LAGI sesudah kolomnya diperbaiki.

        Dipakai ronde 50: sesudah kolom yang ditolak Dapodik diisi ulang, penyimpanan dicoba
        lagi — dan hasilnya diperiksa dari keadaan jendelanya (tertutup = data benar-benar
        dikirim), bukan dari kliknya.
        """
        tombol = self._simpan_dalam_jendela(peramban, jendela)
        if tombol is None:
            tombol = self._simpan_dalam_jendela(peramban, None)
        if tombol is None:
            self._catat_kepala("[bio] tombol «Simpan» jendela «Ubah» tidak ketemu saat akan "
                               "menekan ulang — kolom yang ditolak sudah dibetulkan, tekan "
                               "«Simpan» sekali lagi di Dapodik.")
            return
        try:
            tombol.click()
        except Exception:  # noqa: BLE001 — klik sungguhan bisa tertelan: dicoba lewat skrip
            try:
                peramban.execute_script("arguments[0].click();", tombol)
            except Exception:  # noqa: BLE001 — hasilnya diperiksa dari keadaan jendelanya
                return
        self._tunggu(peramban, 2)

    def _pastikan_baris_setelah_bio(self, peramban, xpath_baris: str, nisn: str, loc_cari) -> None:
        """Setelah jendela «Ubah» disimpan, daftar peserta didik kadang tersegar.

        Jangan menyerah: cari NISN-nya sekali lagi lalu pastikan barisnya tetap terpilih —
        langkah Data Periodik & Registrasi sesudahnya membutuhkan baris yang terpilih.
        """
        if not self._ada_baris(peramban, xpath_baris):
            self._catat_kepala("[bio] daftar peserta didik tersegarkan — mencari NISN sekali lagi.")
            self._kirim_enter(peramban, loc_cari)
            self._siap_melanjutkan(peramban, "hasil pencarian NISN")
            for _ in range(20):
                if self._ada_baris(peramban, xpath_baris):
                    break
                time.sleep(0.5)
        if not self._pastikan_baris_terpilih(peramban, xpath_baris, nisn):
            self._catat_kepala("[bio] peringatan: baris siswa belum terpilih setelah menyimpan "
                               "BIO — langkah berikutnya mungkin perlu baris itu terpilih.")

    def _isi_data_periodik(self, peramban, peta: dict[str, str],
                           siswa: dict[str, Any]) -> bool:
        """Isi panel Data Periodik lalu simpan — **sebelum** tombol Registrasi ditekan.

        Persis potongan skrip sekolah: tinggi badan → berat badan → lingkar kepala →
        centang «Jarak rumah ke sekolah» → jumlah saudara kandung → «Simpan dan Tutup».
        Nilai diambil dari data siswa di aplikasi SM. Kolom yang tidak ada atau data yang
        kosong hanya dicatat pada log — pekerjaan siswa diteruskan.
        """
        # Panel Data Periodik letaknya di bawah halaman DAN punya area gulir sendiri.
        # Karena itu panelnya dibawa ke layar lebih dulu (hanya panel itu yang bergeser),
        # lalu halaman digulir 250 px seperti skrip sekolah sebagai pelengkap.
        if self._gulir_panel_periodik(peramban, peta):
            self._catat_kepala("[gulir] panel Data Periodik siap — lanjut seperti skrip sekolah.")
        else:
            self._catat_kepala("[gulir] panel «Data Periodik Peserta Didik» tidak ketemu — "
                               "memakai gulir halaman seperti skrip sekolah.")
        self._gulir(peramban)

        # Dapodik versi lain bisa tidak punya panel ini sama sekali: jangan digagalkan,
        # cukup dicatat (seperti kolom «Sekolah Asal» yang tidak ada).
        ada_kolom = [self._cari_kolom_dengan_gulir(peramban, kunci_sel, peta)
                     for _, _, kunci_sel in self.PERIODIK]
        ada_jarak = bool(self._kotak_jarak_dengan_gulir(peramban, peta)) \
            if self.opsi.get("bot_periodik_jarak", "1") == "1" else False
        if not any(ada_kolom) and not ada_jarak:
            self._catat_kepala("[periodik] halaman ini tidak punya panel Data Periodik "
                               "(tinggi/berat/lingkar/jarak) — langkah dilewati.")
            return False

        self._catat_kepala("[periodik] mengisi Data Periodik (tinggi, berat, lingkar kepala, "
                           "jarak + kilometer, jumlah saudara kandung) — urutan skrip sekolah.")
        self._penjaga_nilai.clear()          # penjaga nilai mulai dari keadaan panel ini
        terisi = 0

        def isi(kunci: str, label: str, kunci_sel: str, unsur) -> None:
            nonlocal terisi
            nilai = self._nilai_teks(siswa.get(kunci))
            if not nilai:
                self._catat_kepala(f"[periodik] {label}: data siswa kosong — dilewati.")
                return
            keterangan = self._isi_periodik_satu(peramban, peta, kunci_sel, label, nilai, unsur)
            self._catat_kepala(f"[periodik] {label}: {keterangan}")
            if keterangan.startswith("terisi"):
                terisi += 1
            time.sleep(2)          # jeda antar kolom, sama seperti skrip sekolah

        # 1) kolom sebelum baris «Jarak rumah ke sekolah» (tinggi, berat, lingkar kepala)
        for (kunci, label, kunci_sel), unsur in zip(self.PERIODIK_AWAL, ada_kolom):
            isi(kunci, label, kunci_sel, unsur)
        # 2) baris «Jarak rumah ke sekolah»: kotak centang + kolom «Sebutkan (dalam kilometer)».
        #    Bila data jaraknya kosong, keduanya dilewati — Dapodik biasanya menolak
        #    «jarak rumah ke sekolah» yang dicentang tanpa menyebutkan kilometernya.
        jarak_km = self._nilai_teks(siswa.get("jarak_rumah")) \
            if self.opsi.get("bot_periodik_jarak", "1") == "1" else ""
        if jarak_km:
            # Dapodik punya dua pilihan: «kurang dari 1 km» & «lebih dari 1 km» — dipilih
            # sesuai jarak siswa (> 1 km memakai pilihan div[2] seperti skrip sekolah).
            # Langkah ini dicatat lebih dulu supaya jelas terlihat pada log.
            try:
                lebih_dari_satu = float(jarak_km.replace(",", ".")) > 1.0
            except ValueError:
                lebih_dari_satu = True
            self._catat_kepala("[periodik] memilih «Jarak rumah ke sekolah» — data siswa "
                               f"{jarak_km} km → pilihan «"
                               + ("lebih dari 1 km" if lebih_dari_satu else "kurang dari 1 km")
                               + "».")
            pesan_jarak, jarak_terpasang = self._pilih_jarak(peramban, peta, jarak_km)
            self._catat_kepala(f"[periodik] {pesan_jarak}")
            time.sleep(2)
            if lebih_dari_satu and not jarak_terpasang:
                # Dapodik MENONAKTIFKAN kolom «Sebutkan (dalam kilometer)» sampai pilihan
                # «lebih dari 1 km» benar-benar terpasang — jadi kolomnya dilewati dengan
                # jujur, bukan diisi paksa lalu dianggap berhasil.
                self._catat_kepala("[periodik] Sebutkan (dalam kilometer): dilewati — "
                                   "pilihan «lebih dari 1 km» belum terpasang (Dapodik "
                                   "menonaktifkan kolom ini sampai pilihannya benar).")
            elif lebih_dari_satu:
                # Kolom «Sebutkan (dalam kilometer)» diisi bila pilihannya «lebih dari 1 km»
                # (Dapodik meminta keterangan kilometernya).
                keterangan_km = self._isi_jarak_km(peramban, peta, jarak_km)
                self._catat_kepala("[periodik] Sebutkan (dalam kilometer)"
                                   + (keterangan_km if keterangan_km.startswith(" [")
                                      else ": " + keterangan_km))
                if "terisi" in keterangan_km:
                    terisi += 1
                time.sleep(2)
            else:
                self._catat_kepala("[periodik] Sebutkan (dalam kilometer): tidak perlu diisi "
                                   "(jarak siswa ≤ 1 km — pilihannya «kurang dari 1 km»).")
        elif self.opsi.get("bot_periodik_jarak", "1") != "1":
            self._catat_kepala("[periodik] kotak «Jarak rumah ke sekolah» dan kolom "
                               "kilometernya tidak diisi (sesuai pengaturan).")
        else:
            self._catat_kepala("[periodik] kotak «Jarak rumah ke sekolah» tidak dicentang — "
                               "data siswa (Jarak Rumah ke Sekolah) kosong.")
        # 3) kolom sesudahnya (jumlah saudara kandung)
        for (kunci, label, kunci_sel), unsur in zip(self.PERIODIK_AKHIR,
                                                    ada_kolom[len(self.PERIODIK_AWAL):]):
            isi(kunci, label, kunci_sel, unsur)

        # Simpan panel Data Periodik (persis: tombol «Simpan dan Tutup»).
        loc_simpan, _, _ = self._cari_dengan_cadangan(peramban, "simpan_periodik", peta,
                                                     wajib=False)
        if loc_simpan is None:
            self._catat_kepala("[periodik] tombol «Simpan dan Tutup» panel Data Periodik "
                               "tidak ada — penyimpanan dilewati.")
            return terisi > 0
        # Ronde 45: nilai kolom diperiksa lagi TEPAT sebelum disimpan — menggulir (termasuk
        # gulir oleh orang di depan layar) bisa mengubah nilai kolom mana pun, bukan hanya
        # kolom angka. Yang berubah dikembalikan ke nilai yang benar.
        kembali = self._periksa_nilai_bio(peramban, "[periodik]")
        if kembali:
            self._catat_kepala(f"[periodik] {len(kembali)} kolom dikembalikan ke nilai yang "
                               "benar sebelum disimpan.")
        try:
            self._klik_aman(peramban, loc_simpan)
        except Exception as exc:  # noqa: BLE001 — jangan gagalkan siswa karena panel ini
            self._catat_kepala("[periodik] tombol «Simpan dan Tutup» tidak dapat ditekan "
                               f"({type(exc).__name__}) — dilanjutkan ke Registrasi.")
            return terisi > 0
        time.sleep(3)              # skrip sekolah menunggu 3 detik setelah menyimpan
        self._siap_melanjutkan(peramban, "penyimpanan Data Periodik")
        self._catat_kepala(f"[periodik] Data Periodik disimpan ({terisi} kolom terisi).")
        return terisi > 0

    def _tombol_simpan_registrasi(self, peramban, peta: dict[str, str], loc_simpan):
        """Tombol «Simpan dan Tutup» milik jendela Registrasi (bukan panel Data Periodik).

        Tulisan & kelas tombolnya sama di dua tempat: panel «Data Periodik Peserta Didik» dan
        formulir Registrasi. Menekan tombol panel Data Periodik setelah formulir Registrasi
        terbuka membuat Data Periodik **disimpan ulang** — Dapodik lalu menyegarkan daftar
        peserta didik dan baris siswa kehilangan pilihannya (gejala «[periodik] baris siswa
        belum terpilih» di sekolah, 29 Sep 2026).

        Selagi jendela Registrasi terbuka, tombol yang benar adalah yang **terakhir terlihat**:
        jendela modal Ext JS selalu ditambahkan paling akhir di halaman. Bila hanya ada satu
        tombol yang terlihat, atau jendela Registrasi belum terbuka, ``None`` dikembalikan —
        bot memakai jalur biasa (tidak ada yang berubah).
        """
        try:
            if not self._formulir_registrasi_terbuka(peramban, peta):
                return None
            terlihat = [unsur for unsur in peramban.find_elements(*loc_simpan)
                        if self._terlihat(peramban, unsur)]
        except Exception:  # noqa: BLE001 — kembali ke jalur biasa
            return None
        if len(terlihat) < 2:
            return None
        self._catat_kepala(f"[registrasi] ada {len(terlihat)} tombol «Simpan dan Tutup» — dipakai "
                           "tombol MILIK JENDELA REGISTRASI (yang terakhir), bukan tombol panel "
                           "Data Periodik: menekan tombol panel itu menyimpan ulang Data Periodik "
                           "dan daftar peserta didik tersegar (baris siswa kehilangan pilihannya).")
        return terlihat[-1]

    def _ada_baris(self, peramban, xpath_baris: str) -> bool:
        """Apakah baris siswa masih tampil pada tabel Dapodik."""
        from selenium.webdriver.common.by import By

        try:
            return any(unsur.is_displayed()
                       for unsur in peramban.find_elements(By.XPATH, xpath_baris))
        except Exception:  # noqa: BLE001
            return False

    def _isi_sekolah_asal(self, peramban, peta: dict[str, str], nilai: str) -> bool:
        """Isi kolom «Sekolah Asal» dengan data siswa SM — bila formulirnya punya kolom itu.

        Aman dipakai: kolom yang tidak ada atau data yang kosong hanya dicatat pada log,
        pekerjaan siswa tetap diteruskan (seperti pilihan lain pada bot ini).
        """
        from selenium.webdriver.common.keys import Keys

        nilai = str(nilai or "").strip()
        if not nilai:
            self._catat_kepala("[sekolah asal] data siswa belum memuat sekolah asal — dilewati.")
            return False
        unsur = self._kolom_sekolah_asal(peramban, peta)
        if unsur is None:
            self._catat_kepala("[sekolah asal] formulir Registrasi ini tidak punya kolom "
                               "«Sekolah Asal» — dilewati.")
            return False
        try:
            readonly = bool(unsur.get_attribute("readonly"))
        except Exception:  # noqa: BLE001 — tidak terbaca: anggap dapat diketik
            readonly = False
        combo = (unsur.tag_name or "").lower() == "select" or readonly or self._ada_trigger(peramban, unsur)
        try:
            if combo:      # combo box Dapodik: klik → tulis → pilih dari daftar
                self._pilih_kolom_pilihan(peramban, unsur, nilai)
            else:          # kolom teks biasa
                self._paksa_terlihat(peramban, unsur)
                try:
                    unsur.click()
                except Exception:  # noqa: BLE001 — lapisan pemuatan bisa menelan klik
                    pass
                unsur.send_keys(Keys.CONTROL, "a")
                unsur.send_keys(nilai)
        except Exception as exc:  # noqa: BLE001 — jangan gagalkan siswa hanya karena kolom ini
            self._catat_kepala(f"[sekolah asal] kolom tidak dapat diisi ({type(exc).__name__}) — "
                               "dilanjutkan dengan cara skrip.")
        isi = ""
        try:
            isi = str(unsur.get_attribute("value") or "")
        except Exception:  # noqa: BLE001
            isi = ""
        if nilai.lower() not in isi.lower():
            try:               # upaya terakhir: isi lewat skrip
                self._isi_lewat_js(peramban, unsur, nilai)
                isi = str(unsur.get_attribute("value") or "")
            except Exception:  # noqa: BLE001
                isi = ""
        terisi = nilai.lower() in isi.lower()
        if terisi:
            self._catat_kepala(f"[sekolah asal] terisi: {isi}")
        else:
            self._catat_kepala("[sekolah asal] kolom belum berisi nilai yang benar — "
                               "Dapodik bisa meminta kolom ini diisi manual.")
        return terisi

    def _ada_trigger(self, peramban, unsur) -> bool:
        """Apakah unsur punya tombol combo Ext JS di sebelahnya (penanda combo box)."""
        from selenium.webdriver.common.by import By

        try:
            return bool(unsur.find_elements(
                By.XPATH, "following::*[contains(@class, 'x-form-trigger')][1]"))
        except Exception:  # noqa: BLE001
            return False

    def _pilih_kolom_pilihan(self, peramban, locator, nilai: str) -> None:
        """Isi kolom pilihan (Hobi / Cita-cita) yang aman untuk Dapodik.

        Dapodik memakai Ext JS sehingga kolom pilihan kadang berupa combo box,
        bukan ``<select>`` biasa. Urutan percobaan:

        1. ``<select>`` biasa → pilih sesuai teks/nilai (termasuk cocok sebagian);
        2. combo box → ketik teks lalu klik pilihan yang muncul di daftar;
        3. bila daftar tidak muncul → Enter (sama seperti skrip bot sekolah).
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import Select, WebDriverWait

        nilai = str(nilai or "").strip()
        if not nilai:
            raise ValueError("Hobi/Cita-cita belum diisi pada pengaturan bot.")
        self._siap_melanjutkan(peramban, "kolom pilihan")
        elemen = locator if not isinstance(locator, tuple) else self._tunggu_elemen(peramban, locator)

        if (elemen.tag_name or "").lower() == "select":
            pilih = Select(elemen)
            for opsi in pilih.options:
                teks = (opsi.text or "").strip()
                if nilai.lower() == teks.lower() or nilai.lower() in teks.lower() or teks.lower() in nilai.lower():
                    pilih.select_by_index(opsi.index)
                    return
            raise ValueError(f"Pilihan '{nilai}' tidak ada pada daftar Dapodik.")

        # Combo box: buka, ketik, lalu pilih item pada daftar (bound list).
        aman = nilai.replace('"', " ").replace("'", " ").strip()
        kata = aman.split(" ")[0]
        try:
            elemen.click()
        except Exception:  # noqa: BLE001 — lapisan pemuatan bisa menelan klik
            opened = False
            try:     # buka lewat skrip (tahan lapisan pemuatan)
                peramban.execute_script("arguments[0].click();", elemen)
                opened = True
            except Exception:  # noqa: BLE001
                opened = False
            if not opened:
                try:  # input readonly: buka lewat tombol panah combo
                    elemen.find_element(
                        By.XPATH, "following::*[contains(@class, 'x-form-trigger')][1]").click()
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"Kolom pilihan tidak dapat dibuka: {exc}") from exc
        try:
            elemen.send_keys(Keys.CONTROL, "a")
            elemen.send_keys(nilai)
        except Exception:  # noqa: BLE001 — sebagian combo readonly, cukup daftar dibuka
            pass
        # Sama seperti skrip sekolah: beri waktu 2 detik supaya daftar pilihan muncul
        # sebelum memilih/Enter — Dapodik kadang masih memuat daftarnya.
        time.sleep(2)
        for xpath in (f'//li[contains(@class, "x-boundlist-item") and contains(normalize-space(), "{aman}")]',
                      f'//li[contains(@class, "x-boundlist-item") and starts-with(normalize-space(), "{kata}")]'):
            try:
                item = WebDriverWait(peramban, PILIHAN_TUNGGU_DETIK).until(
                    EC.element_to_be_clickable((By.XPATH, xpath)))
                try:
                    item.click()
                except Exception:  # noqa: BLE001 — pilihan bisa tertutup lapisan pemuatan
                    peramban.execute_script("arguments[0].click();", item)
                return
            except Exception:  # noqa: BLE001 — coba cara berikutnya
                continue
        self._kirim_enter(peramban, locator)  # cara terakhir, sama seperti skrip asli

    def _pesan_dapodik(self, peramban) -> str:
        """Baca kotak pesan Dapodik yang menandakan penolakan/peringatan ('' bila tidak ada)."""
        from selenium.webdriver.common.by import By

        try:
            kotak = peramban.find_elements(By.CSS_SELECTOR, "div.x-message-box, div.x-window")
        except Exception:  # noqa: BLE001
            return ""
        for elemen in kotak:
            try:
                if not elemen.is_displayed():
                    continue
                teks = " ".join((elemen.text or "").split())
            except Exception:  # noqa: BLE001
                continue
            if not teks:
                continue
            rendah = teks.lower()
            if any(kata in rendah for kata in ("harus", "wajib", "tidak boleh", "tidak valid",
                                               "gagal", "error", "salah", "belum diisi",
                                               "periksa kembali")):
                self._tutup_pesan(peramban)
                return teks[:250]
        return ""

    def _tutup_pesan(self, peramban) -> None:
        """Tutup kotak pesan Dapodik supaya antrean berikutnya bisa diproses."""
        from selenium.webdriver.common.by import By

        try:
            tombol = peramban.find_elements(By.CSS_SELECTOR,
                                            "div.x-message-box .x-btn, div.x-message-box button")
        except Exception:  # noqa: BLE001
            return
        for elemen in tombol:
            try:
                if elemen.is_displayed():
                    peramban.execute_script("arguments[0].click();", elemen)
                    time.sleep(1)
                    return
            except Exception:  # noqa: BLE001
                continue

    # ---------------------------------------------------------------- login --- #
    def _formulir_terlihat(self, peramban) -> bool:
        """Apakah ada kolom isian login yang benar-benar tampil (bukan hanya ada di DOM)."""
        try:
            return bool(peramban.execute_script(
                """
                const tampak = (el) => {
                    const kotak = el.getBoundingClientRect();
                    const gaya = window.getComputedStyle(el);
                    return kotak.width > 1 && kotak.height > 1 &&
                           gaya.display !== 'none' && gaya.visibility !== 'hidden';
                };
                // Hanya kolom sandi yang menandakan formulir login; kotak pencarian di
                // halaman daftar peserta didik tidak boleh dianggap formulir login.
                const kolom = [...document.querySelectorAll('input[type=password]')];
                return kolom.some(tampak);
                """))
        except Exception:  # noqa: BLE001
            return False

    def _tunggu_formulir_hilang(self, peramban, detik: float | None = None) -> bool:
        """Tunggu formulir login hilang sebagai penanda sudah berhasil masuk."""
        batas = float(detik if detik is not None else self.opsi.get("bot_timeout", "15") or 15)
        mulai = time.time()
        while time.time() - mulai < batas:
            if not self._formulir_terlihat(peramban):
                return True
            time.sleep(1)
        return not self._formulir_terlihat(peramban)

    def _coba_login(self, peramban, peta: dict[str, str]) -> dict[str, Any]:
        """Uji sungguhan: isi kolom login & tekan tombolnya, lalu laporkan hasilnya.

        Dipakai «Uji koneksi Dapodik» supaya jawabannya pasti: bukan hanya "selector
        ketemu", tetapi "berhasil masuk" atau pesan Dapodik yang menolak. Tidak pernah
        melempar galat.
        """
        mulai = time.time()
        batas = float(self.opsi.get("bot_timeout", "15") or 15)
        hasil: dict[str, Any] = {"dicoba": True, "berhasil": False, "detik": 0.0,
                                 "pesan": "", "terisi": {}, "judul_setelah": "", "bukti": ""}
        try:
            if not (self.opsi.get("bot_username", "").strip() and
                    self.opsi.get("bot_password", "")):
                hasil["pesan"] = ("Nama pengguna/kata sandi Dapodik belum diisi pada «Pengaturan» — "
                                  "isi dulu keduanya, lalu uji lagi supaya percobaan masuk benar-benar "
                                  "dijalankan.")
                hasil["detik"] = round(time.time() - mulai, 1)
                return hasil

            loc: dict[str, Any] = {}
            for kunci in ("login_username", "login_password"):
                locator, _, _ = self._cari_dengan_cadangan(peramban, kunci, peta, wajib=False,
                                                           boleh_tak_terlihat=True)
                if locator is not None:
                    loc[kunci] = locator
            if len(loc) < 2:
                hasil["pesan"] = ("Kolom nama pengguna/kata sandi belum dapat dipakai pada halaman "
                                  "ini — lihat tabel status selector di atas.")
                hasil["detik"] = round(time.time() - mulai, 1)
                return hasil

            if not self._tunggu_lapisan(peramban, batas):
                self._catat_kepala("[uji] lapisan pemuatan Dapodik masih terlihat.")
            for kunci, label, nilai in (("login_username", "nama pengguna",
                                         self.opsi.get("bot_username", "")),
                                        ("login_password", "kata sandi",
                                         self.opsi.get("bot_password", ""))):
                hasil["terisi"][kunci] = self._isi_dan_periksa(peramban, loc[kunci], nilai, label)
            belum = [kunci for kunci, info in hasil["terisi"].items() if not info.get("terisi")]
            if belum:
                hasil["pesan"] = ("Kolom " + ", ".join(belum) + " tidak mau diisi oleh peramban — "
                                  "coba lagi, atau jalankan uji dengan pilihan «Tampilkan jendela "
                                  "Chrome».")
                hasil["detik"] = round(time.time() - mulai, 1)
                return hasil

            loc_tombol, _, _ = self._cari_dengan_cadangan(peramban, "login_tombol", peta,
                                                          wajib=False, boleh_tak_terlihat=True)
            if loc_tombol is not None:
                self._klik_aman(peramban, loc_tombol)
            else:
                from selenium.webdriver.common.keys import Keys

                self._catat_kepala("[uji] tombol masuk tidak dikenali — formulir dikirim dengan Enter.")
                self._kirim_enter(peramban, loc["login_password"])

            berhasil = self._tunggu_formulir_hilang(peramban, batas)
            pesan_dapodik = "" if berhasil else self._pesan_dapodik(peramban)
            hasil["detik"] = round(time.time() - mulai, 1)
            try:
                hasil["judul_setelah"] = (peramban.title or "").strip()[:120]
            except Exception:  # noqa: BLE001
                hasil["judul_setelah"] = ""
            hasil["bukti"] = self._bukti(peramban, "uji-masuk")
            if berhasil:
                hasil["berhasil"] = True
                hasil["pesan"] = (f"Login berhasil — halaman Dapodik berpindah dari formulir login "
                                  f"dalam {hasil['detik']} detik (judul sekarang: "
                                  f"'{hasil['judul_setelah'] or '(tanpa judul)'}'). Bot siap dijalankan.")
            elif pesan_dapodik:
                hasil["pesan"] = "Dapodik menolak login: " + pesan_dapodik
            else:
                hasil["pesan"] = ("Formulir login masih tampil setelah tombol masuk ditekan — "
                                  "halaman belum berpindah. Coba jalankan uji dengan pilihan "
                                  "«Tampilkan jendela Chrome» atau naikkan «Batas tunggu elemen».")
        except Exception as exc:  # noqa: BLE001 — alat bantu, selalu laporkan
            hasil["detik"] = round(time.time() - mulai, 1)
            hasil["pesan"] = f"{type(exc).__name__}: {str(exc)[:250]}"
        return hasil

    def _login(self, peramban) -> None:
        """Masuk ke Dapodik & buka daftar peserta didik — urutan sama dengan skrip sekolah.

        Persis skrip asli: buka alamat → tunggu kolom nama pengguna tampil → isi nama
        pengguna & kata sandi → tekan tombol masuk → tunggu 2 detik → klik menu tujuan
        (mis. Peserta Didik) → tunggu 5 detik → tutup popup bila muncul → tunggu 2 detik
        → klik dua menu lanjutan → tunggu 2 detik.
        """
        url = (self.opsi.get("bot_url") or "").strip()
        if not url:
            raise ValueError("Alamat Dapodik belum diisi pada pengaturan bot.")
        self._catat_kepala(f"Membuka {url} …")
        try:
            peramban.get(url)
        except Exception as exc:  # noqa: BLE001 — halaman gagal dimuat sama sekali
            raise RuntimeError(
                f"Halaman {url} tidak dapat dibuka dalam batas waktu. Pastikan aplikasi "
                f"Dapodik sedang berjalan (Rincian: {type(exc).__name__}).") from exc
        self._tunggu_halaman(peramban)

        galat_halaman = self._galat_halaman(peramban)
        if galat_halaman:
            raise RuntimeError(galat_halaman)

        peta = peta_selector()

        # Skrip asli menunggu kolom nama pengguna benar-benar tampil sebelum mengetik.
        loc_user, _, _ = self._cari_dengan_cadangan(peramban, "login_username", peta,
                                                    boleh_tak_terlihat=True)
        loc_sandi, _, _ = self._cari_dengan_cadangan(peramban, "login_password", peta,
                                                     boleh_tak_terlihat=True)

        # Lapisan pemuatan Ext JS (div.x-mask) ditunggu hilang dulu, seperti skrip asli.
        if not self._tunggu_lapisan(peramban):
            self._catat_kepala("[login] lapisan pemuatan Dapodik masih terlihat — mengisi kolom "
                               "dengan cara paksa.")
        terisi = {
            "nama pengguna": self._isi_dan_periksa(peramban, loc_user,
                                                   self.opsi.get("bot_username", ""), "nama pengguna"),
            "kata sandi": self._isi_dan_periksa(peramban, loc_sandi,
                                                self.opsi.get("bot_password", ""), "kata sandi"),
        }
        kurang = [nama for nama, info in terisi.items() if not info["terisi"]]
        if kurang:
            self._catat_kepala("[login] peringatan: kolom " + ", ".join(kurang) +
                               " belum berisi nilai yang benar — Dapodik bisa menolak login.")

        loc_tombol, _, _ = self._cari_dengan_cadangan(peramban, "login_tombol", peta)
        self._klik_aman(peramban, loc_tombol)
        time.sleep(2)

        # Pengaman tambahan: halaman harus benar-benar berpindah dari formulir login.
        if self._formulir_terlihat(peramban) and not self._tunggu_formulir_hilang(peramban, 10):
            pesan_dapodik = self._pesan_dapodik(peramban)
            bukti = self._bukti(peramban, "gagal-login")
            raise RuntimeError(
                "Formulir login masih tampil setelah tombol masuk ditekan — Dapodik belum "
                "mengizinkan masuk. " +
                (f"Pesan Dapodik: {pesan_dapodik} " if pesan_dapodik else
                 "Periksa nama pengguna & kata sandi pada pengaturan bot. ") +
                f"(bukti: {bukti or 'tidak tersimpan'}). Gunakan «Uji koneksi Dapodik» untuk "
                "mencoba masuk sekaligus melihat rinciannya.")

        # Menu tujuan (mis. Peserta Didik), lalu dua menu lanjutan — sama seperti skrip asli.
        loc_menu, _, _ = self._cari_dengan_cadangan(peramban, "menu_tujuan", peta)
        self._klik_aman(peramban, loc_menu)
        time.sleep(5)

        # Tutup popup informasi bila muncul — sama seperti skrip sekolah (menunggu 5 detik
        # lalu lanjut). Bedanya, di PC sekolah popup «Selamat Datang di Aplikasi Dapodik
        # 2027.b» muncul **lebih lambat** daripada 5 detik itu, lalu menutupi halaman dan
        # menelan klik berikutnya (akibatnya formulir Registrasi tidak pernah terbuka).
        # Karena itu popup ditunggu selama jeda muat, dan tetap diperiksa lagi sebelum
        # setiap langkah berikutnya.
        if self._singkirkan_popup(peramban, peta,
                                  batas=float(self.opsi.get("bot_jeda_muat", "5") or 5)):
            self._catat_kepala("Popup Dapodik ditutup.")
        else:
            self._catat_kepala("Popup tidak muncul, lanjut.")
        time.sleep(2)
        self._singkirkan_popup(peramban, peta)
        loc_satu, _, _ = self._cari_dengan_cadangan(peramban, "menu_1", peta)
        self._klik_aman(peramban, loc_satu)
        self._singkirkan_popup(peramban, peta)
        loc_dua, _, _ = self._cari_dengan_cadangan(peramban, "menu_2", peta)
        self._klik_aman(peramban, loc_dua)
        time.sleep(2)
        self._siap_melanjutkan(peramban, "daftar peserta didik")
        self._singkirkan_popup(peramban, peta)
        self._catat_kepala(f"[versi] kode SM yang berjalan: {self._versi_kode()} — langkah "
                           "tiap siswa: 1) cari NISN & pilih barisnya → 2) BIO lewat «Ubah» "
                           "(No. KK, akta, alamat/RT/RW, desa/kelurahan dari daftar Dapodik, "
                           "kode pos, ayah & ibu → Simpan) → 3) Data Periodik "
                           "(gulir panel → tinggi/berat/lingkar → pilih radio jarak → km → "
                           "saudara → Simpan dan Tutup) → 4) Registrasi (NIS → Sekolah Asal → "
                           "«Ya» → Hobi → Cita-cita → Simpan dan Tutup).")
        if self._versi_kode() == "tidak diketahui":
            self._catat_kepala("[versi] aplikasi ini bukan salinan git — pastikan berkas "
                               "sudah diperbarui secara manual sebelum menjalankan bot.")
        self._catat_kepala("Siap memproses antrean.")

    @staticmethod
    def _versi_kode() -> str:
        """Revisi pendek kode yang sedang berjalan (untuk log & halaman bot)."""
        try:
            from app import updater

            return updater.versi_kerja() or "tidak diketahui"
        except Exception:  # noqa: BLE001 — versi hanya keterangan
            return "tidak diketahui"

    def _kandidat_selector(self, kunci: str, peta: dict[str, str]) -> list[str]:
        """Daftar selector yang akan dicoba: terpasang dulu, lalu cadangan berbasis teks."""
        terpasang = (peta.get(kunci) or "").strip()
        kandidat: list[str] = []
        for nilai in [terpasang, *SELECTOR_CADANGAN.get(kunci, [])]:
            nilai = (nilai or "").strip()
            if nilai and nilai not in kandidat:
                kandidat.append(nilai)
        return kandidat

    def _cari_dengan_cadangan(self, peramban, kunci: str, peta: dict[str, str],
                              wajib: bool = True, batas: float | None = None,
                              boleh_tak_terlihat: bool = False) -> tuple[Any, str, bool]:
        """Cari elemen memakai selector terpasang, lalu selector cadangan.

        Kembalikan ``(locator, nilai_selector, memakai_cadangan)``. Dapodik sering
        diperbarui sehingga XPath/id berubah; cadangan berbasis teks membuat bot tetap
        jalan dan pesan pada log memberi tahu selector mana yang benar-benar dipakai
        (agar bisa disalin ke *Peta tombol Dapodik*).

        ``boleh_tak_terlihat`` dipakai pada formulir login: Dapodik kadang menampilkan
        DOM lebih dulu (kolom ada, tetapi belum terlihat karena masih memuat).
        """
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        kandidat = self._kandidat_selector(kunci, peta)
        if not kandidat:
            raise ValueError(f"Selector '{kunci}' belum diisi.")
        batas = batas or float(self.opsi.get("bot_timeout", "15") or 15)
        galat: Exception | None = None
        for indeks, nilai in enumerate(kandidat):
            try:
                locator = self._locator_nilai(nilai)
                WebDriverWait(peramban, batas if indeks == 0 else SELEKTOR_UJI_DETIK).until(
                    lambda p: self._pertama_terlihat(p, locator) is not None)
                if indeks > 0:
                    self._catat_kepala(f"[selector] '{kunci}' memakai cadangan: {nilai}")
                return locator, nilai, indeks > 0
            except Exception as exc:  # noqa: BLE001 — coba kandidat berikutnya
                galat = exc
        if boleh_tak_terlihat:
            for indeks, nilai in enumerate(kandidat):
                try:
                    locator = self._locator_nilai(nilai)
                    if peramban.find_elements(*locator):
                        self._catat_kepala(
                            f"[selector] '{kunci}' ada di halaman tetapi belum terlihat "
                            f"(halaman mungkin masih memuat): {nilai}")
                        return locator, nilai, indeks > 0
                except Exception:  # noqa: BLE001
                    continue
        pesan = (f"Tidak menemukan elemen '{kunci}' setelah mencoba "
                 f"{len(kandidat)} selector (terakhir gagal: {type(galat).__name__}).")
        if wajib:
            raise TimeoutError(pesan)
        return None, "", False

    def _keadaan_selector(self, peramban, kunci: str, peta: dict[str, str]) -> dict[str, Any]:
        """Untuk laporan uji: selector cocok / ada tetapi belum terlihat / tidak ada."""
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        for indeks, nilai in enumerate(self._kandidat_selector(kunci, peta)):
            try:
                locator = self._locator_nilai(nilai)
            except Exception:  # noqa: BLE001
                continue
            try:
                WebDriverWait(peramban, UJI_TUNGGU_PERTAMA if indeks == 0 else UJI_TUNGGU_LAIN).until(
                    EC.visibility_of_element_located(locator))
                return {"keadaan": "terlihat", "nilai": nilai, "cadangan": indeks > 0}
            except Exception:  # noqa: BLE001
                pass
            try:
                if peramban.find_elements(*locator):
                    return {"keadaan": "ada_tak_terlihat", "nilai": nilai, "cadangan": indeks > 0}
            except Exception:  # noqa: BLE001
                pass
        return {"keadaan": "tidak_ada", "nilai": "", "cadangan": False}

    def _deskripsi_unsur(self, peramban) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Daftar kolom & tombol yang ada di halaman (bahan pengenalan selector)."""
        from selenium.webdriver.common.by import By

        def atribut(elemen, nama: str) -> str:
            try:
                return (elemen.get_attribute(nama) or "").strip()
            except Exception:  # noqa: BLE001
                return ""

        def dasar(elemen) -> dict[str, Any]:
            try:
                ukuran = elemen.size or {}
            except Exception:  # noqa: BLE001
                ukuran = {}
            try:
                terlihat = bool(elemen.is_displayed())
            except Exception:  # noqa: BLE001
                terlihat = False
            try:
                aktif = bool(elemen.is_enabled())
            except Exception:  # noqa: BLE001
                aktif = True
            return {
                "tag": (elemen.tag_name or "").lower(),
                "type": atribut(elemen, "type"),
                "name": atribut(elemen, "name"),
                "id": atribut(elemen, "id"),
                "placeholder": atribut(elemen, "placeholder"),
                "aria": atribut(elemen, "aria-label"),
                "terlihat": terlihat,
                "enabled": aktif,
                "ukuran": f"{int(ukuran.get('width', 0))}x{int(ukuran.get('height', 0))}",
            }

        kolom: list[dict[str, Any]] = []
        try:
            for elemen in peramban.find_elements(By.CSS_SELECTOR, "input, select, textarea")[:25]:
                kolom.append(dasar(elemen))
        except Exception:  # noqa: BLE001
            pass
        tombol: list[dict[str, Any]] = []
        try:
            for elemen in peramban.find_elements(
                    By.CSS_SELECTOR, "button, input[type=submit], input[type=button], a")[:40]:
                info = dasar(elemen)
                try:
                    teks = " ".join((elemen.text or atribut(elemen, "value") or "").split())
                except Exception:  # noqa: BLE001
                    teks = ""
                info["teks"] = teks[:45]
                if info["teks"]:
                    tombol.append(info)
        except Exception:  # noqa: BLE001
            pass
        return kolom, tombol

    def _locator_nilai(self, nilai: str):
        from selenium.webdriver.common.by import By

        if not nilai:
            raise ValueError("Selector kosong.")
        if nilai.startswith("name:"):
            return (By.NAME, nilai[5:])
        if nilai.startswith("css:"):
            return (By.CSS_SELECTOR, nilai[4:])
        if nilai.startswith("xpath:"):
            return (By.XPATH, nilai[6:])
        # XPath boleh diawali "//" maupun satu garis miring ("/html/body/...", seperti pada
        # skrip bot sekolah). Sebelumnya nilai seperti itu keliru dibaca sebagai nama elemen
        # sehingga selector bawaan tidak pernah ketemu.
        if nilai.startswith("//") or nilai.startswith("/") or nilai.startswith("("):
            return (By.XPATH, nilai)
        if nilai.startswith("[") or nilai.startswith(".") or nilai.startswith("#"):
            return (By.CSS_SELECTOR, nilai)
        return (By.NAME, nilai)

    def _locator(self, kunci: str, peta: dict[str, str]):
        """Selector terpasang untuk sebuah kunci (tanpa cadangan)."""
        nilai = peta.get(kunci, "")
        if not nilai:
            raise ValueError(f"Selector '{kunci}' belum diisi.")
        return self._locator_nilai(nilai)

    # ------------------------------------------------------- satu siswa ----- #
    def _aturan_lewati(self, siswa: dict[str, Any]) -> str:
        """Alasan siswa dilewati sebelum menyentuh Dapodik ('' = lanjut)."""
        nisn = str(siswa.get("nisn") or "").strip()
        if not nisn.isdigit() or len(nisn) != 10:
            return f"NISN '{nisn}' bukan 10 digit angka"
        nis = str(siswa.get("nis") or siswa.get("nipd") or "").strip()
        if not nis and self.opsi.get("bot_pakai_nisn", "0") != "1":
            return "NIPD/NIS belum diisi pada data siswa"
        return ""

    def _proses_satu(self, peramban, siswa: dict[str, Any], item_id: int | None) -> None:
        self.sedang = siswa
        nisn = str(siswa.get("nisn") or "").strip()
        nis = str(siswa.get("nis") or siswa.get("nipd") or "").strip()
        if not nis and self.opsi.get("bot_pakai_nisn", "0") == "1":
            nis = nisn
        if item_id:
            services.catat_item_bot(item_id, "menunggu", "sedang diproses")
        try:
            alasan = self._aturan_lewati(siswa)
            if alasan:
                self._selesai_item(item_id, "dilewati", alasan, nisn)
                return

            if self.simulasi:
                time.sleep(0.05)
                self._selesai_item(item_id, "sukses",
                                   f"Uji coba: NIS {nis} akan didaftarkan lewat "
                                   f"{self.opsi.get('bot_url', 'Dapodik')}", nisn)
                return

            from selenium.common.exceptions import TimeoutException
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait

            peta = peta_selector()
            # Popup pengumuman bisa muncul kapan saja (mis. saat antrean sudah berjalan);
            # selama popup itu tampil, klik di halaman diabaikan Dapodik.
            self._singkirkan_popup(peramban, peta)

            # 1) cari NISN pada kotak pencarian.
            #    Panel daftar peserta didik harus selesai memuat lebih dulu: kalau belum,
            #    klik pada kolomnya tertelan lapisan pemuatan Ext JS (klik lewat skrip
            #    dipakai sebagai jalan keluar, sama seperti perilaku skrip sekolah).
            self._siap_melanjutkan(peramban, "kotak pencarian peserta didik")
            loc_cari, _, _ = self._cari_dengan_cadangan(peramban, "cari_nisn", peta)
            isi_cari = self._isi_dan_periksa(peramban, loc_cari, nisn, "kotak pencarian NISN")
            if not isi_cari["terisi"]:
                self._catat_kepala("[cari] kotak pencarian belum berisi NISN — mengisi lewat skrip.")
                elemen_cari = peramban.find_element(*loc_cari)
                self._paksa_terlihat(peramban, elemen_cari)
                self._isi_lewat_js(peramban, elemen_cari, nisn)
            self._kirim_enter(peramban, loc_cari)
            self._siap_melanjutkan(peramban, "hasil pencarian NISN")

            # 2) baris tabel yang memuat NISN
            xpath_baris = (f'//tr[contains(@class, "{BARIS_TABEL}") '
                           f'and .//td[contains(., "{nisn}")]]')
            batas = float(self.opsi.get("bot_timeout", "15") or 15)
            # Popup pengumuman bisa muncul tepat saat Dapodik menampilkan hasil pencarian;
            # kalau begitu hasilnya tidak jadi muncul. Jangan langsung menyimpulkan "data
            # tidak ditemukan": tutup popupnya, ulangi pencarian sekali, lalu tunggu lagi.
            terlihat = False
            akhir = time.time() + batas
            dicari_ulang = False
            while not terlihat:
                try:
                    terlihat = any(unsur.is_displayed()
                                   for unsur in peramban.find_elements(By.XPATH, xpath_baris))
                except Exception:  # noqa: BLE001 — coba lagi sampai batas waktu
                    terlihat = False
                if terlihat or time.time() >= akhir:
                    break
                if self._singkirkan_popup(peramban, peta):
                    self._siap_melanjutkan(peramban, "hasil pencarian NISN")
                    if not dicari_ulang:
                        self._kirim_enter(peramban, loc_cari)
                        dicari_ulang = True
                    akhir = time.time() + batas
                time.sleep(0.5)
            if not terlihat:
                self._selesai_item(item_id, "dilewati",
                                   "Data NISN tidak ditemukan pada tabel Dapodik", nisn)
                return
            self._klik_aman(peramban, (By.XPATH, xpath_baris))
            time.sleep(1)
            # Dapodik hanya membuka Registrasi untuk siswa yang barisnya terpilih.
            if not self._pastikan_baris_terpilih(peramban, xpath_baris, nisn):
                self._catat_kepala("[registrasi] peringatan: baris siswa belum terpilih — "
                                   "Dapodik biasanya perlu baris terpilih untuk Registrasi.")
            time.sleep(1)

            # 2a) BIO lewat tombol «Ubah» — persis potongan skrip sekolah (No. KK, akta,
            #     alamat/RT/RW/kode pos, anak ke-berapa, data ayah & ibu) dan dijalankan
            #     SESUDAH baris siswa dipilih, **sebelum** Data Periodik & Registrasi.
            if self.opsi.get("bot_isi_bio", "1") == "1":
                self._isi_bio(peramban, peta, siswa)
                self._pastikan_baris_setelah_bio(peramban, xpath_baris, nisn, loc_cari)

            # 2b) Data Periodik — persis potongan skrip sekolah, dan **sebelum** tombol
            #     Registrasi ditekan: tinggi badan, berat badan, lingkar kepala, centang
            #     «Jarak rumah ke sekolah», jumlah saudara kandung, lalu «Simpan dan Tutup».
            if self.opsi.get("bot_data_periodik", "1") == "1":
                self._isi_data_periodik(peramban, peta, siswa)
                # Setelah disimpan, daftar peserta didik kadang tersegarkan (baris hilang).
                # Jangan menyerah: cari NISN-nya sekali lagi, lalu pastikan tetap terpilih.
                if not self._ada_baris(peramban, xpath_baris):
                    self._catat_kepala("[periodik] daftar peserta didik tersegarkan — "
                                       "mencari NISN sekali lagi.")
                    self._kirim_enter(peramban, loc_cari)
                    self._siap_melanjutkan(peramban, "hasil pencarian NISN")
                    for _ in range(20):
                        if self._ada_baris(peramban, xpath_baris):
                            break
                        time.sleep(0.5)
                if not self._pastikan_baris_terpilih(peramban, xpath_baris, nisn):
                    self._catat_kepala("[periodik] peringatan: baris siswa belum terpilih "
                                       "setelah menyimpan Data Periodik.")

            # 3) tombol Registrasi → formulir Registrasi. Formulir baru terbuka setelah
            #    tombolnya benar-benar diproses Dapodik; kalau kliknya tertelan (popup
            #    pengumuman / lapisan modal), tombol diklik ulang — bot tidak langsung
            #    menyerah dengan "input_nis tidak ditemukan".
            loc_daftar, _, _ = self._cari_dengan_cadangan(peramban, "tombol_registrasi", peta)
            ulang_form = int(self.opsi.get("bot_max_retries", "3") or 3)
            terbuka = False
            for percobaan in range(1, ulang_form + 1):
                self._singkirkan_popup(peramban, peta)
                self._pastikan_baris_terpilih(peramban, xpath_baris, nisn)
                self._klik_aman(peramban, loc_daftar)
                time.sleep(2)
                self._siap_melanjutkan(peramban, "formulir Registrasi")
                terbuka = self._formulir_registrasi_terbuka(peramban, peta)
                if terbuka:
                    break
                self._catat_kepala(f"[registrasi] formulir Registrasi belum terbuka (percobaan "
                                   f"{percobaan}/{ulang_form}) — memeriksa popup & mengklik tombol "
                                   "Registrasi sekali lagi.")
            if not terbuka:
                raise RuntimeError(
                    "Formulir Registrasi Dapodik tidak terbuka setelah tombol Registrasi "
                    f"ditekan {ulang_form} kali. Dapodik biasanya menampilkan popup "
                    "(mis. «Selamat Datang di Aplikasi Dapodik») yang menutupi halaman — "
                    "tutup popup itu dengan tombol «Tutup», lalu jalankan bot sekali lagi.")

            # 4) isi NIS
            loc_nis, _, _ = self._cari_dengan_cadangan(peramban, "input_nis", peta)
            self._isi_dan_periksa(peramban, loc_nis, nis, "NIS")

            # 4b) Sekolah Asal — diambil dari data siswa di aplikasi SM (kolom
            #     «Sekolah Asal»). Bila Dapodik sekolah tidak punya kolomnya atau
            #     datanya kosong, langkah ini dilewati tanpa menggagalkan siswa.
            if self.opsi.get("bot_sekolah_asal", "1") == "1":
                self._siap_melanjutkan(peramban, "kolom Sekolah Asal")
                self._isi_sekolah_asal(peramban, peta, siswa.get("sekolah_asal") or "")

            # 5) centang semua pilihan «Ya» — sama seperti radio jarak: hasilnya diperiksa
            #    ulang, sebab Ext JS bisa menelan klik yang dikirim lewat skrip (inilah yang
            #    dulu membuat log berkata "0 dari 2" padahal tidak ada yang tercentang).
            if self.opsi.get("bot_jawaban_ya", "1") == "1":
                kotak_ya = self._kotak_ya(peramban, peta)
                dicentang = sum(1 for elemen in kotak_ya
                                if self._pilih_satu(peramban, elemen, "pilihan «Ya»", "Ya"))
                pesan = (f"[registrasi] pilihan «Ya» dicentang: {dicentang} dari "
                         f"{len(kotak_ya)}")
                if kotak_ya and dicentang < len(kotak_ya):
                    pesan += (" — peringatan: Dapodik belum menandai semuanya terpilih "
                              "(periksa kotak «Ya» pada formulir).")
                self._catat_kepala(pesan)

            # 6) hobi & 7) cita-cita (kolom pilihan Dapodik) — sama seperti skrip sekolah:
            #    klik → Ctrl+A → tulis → tunggu → Enter
            self._siap_melanjutkan(peramban, "kolom Hobi & Cita-cita")
            loc_hobi, _, _ = self._cari_dengan_cadangan(peramban, "hobi", peta)
            self._pilih_kolom_pilihan(peramban, loc_hobi, self.opsi.get("bot_hobi", ""))
            time.sleep(1)
            loc_cita, _, _ = self._cari_dengan_cadangan(peramban, "cita", peta)
            self._pilih_kolom_pilihan(peramban, loc_cita, self.opsi.get("bot_cita", ""))

            # 8) simpan dan tutup
            #    Ronde 50 (susulan): tombol «Simpan dan Tutup» ada LEBIH DARI SATU di halaman
            #    (panel Data Periodik + formulir Registrasi). Kalau kliknya jatuh ke tombol
            #    panel Data Periodik, Data Periodik disimpan ULANG dan daftar peserta didik
            #    tersegar — baris siswa kehilangan pilihannya. Jadi selagi jendela Registrasi
            #    terbuka, tombolnya dipilih dari unsur terakhir (milik jendela itu).
            loc_simpan, _, _ = self._cari_dengan_cadangan(peramban, "simpan", peta)
            tombol_simpan = self._tombol_simpan_registrasi(peramban, peta, loc_simpan)
            self._klik_aman(peramban, loc_simpan, elemen=tombol_simpan)
            self._siap_melanjutkan(peramban, "penyimpanan Dapodik")
            time.sleep(2)

            # Dapodik kadang menolak dengan kotak pesan — jangan dianggap berhasil.
            keluhan = self._pesan_dapodik(peramban)
            if keluhan:
                self._selesai_item(item_id, "gagal", f"Ditolak Dapodik: {keluhan}", nisn)
                return
            self._selesai_item(item_id, "sukses", f"Registrasi NIS {nis} berhasil dikirim", nisn)
        except Exception as exc:  # noqa: BLE001 — satu siswa gagal, lanjut ke berikutnya
            pesan = f"{type(exc).__name__}: {str(exc)[:300]}"
            if peramban is not None:
                bukti = self._bukti(peramban, f"gagal-{nisn}")
                if bukti:
                    pesan = f"{pesan} · bukti: {bukti}"
            self._selesai_item(item_id, "gagal", pesan, nisn)

    def _selesai_item(self, item_id: int | None, status: str, pesan: str, nisn: str) -> None:
        if item_id:
            services.catat_item_bot(item_id, status, pesan)
        services.perbarui_job_bot(self.job_id,
                                  tambah_sukses=1 if status == "sukses" else 0,
                                  tambah_gagal=1 if status == "gagal" else 0)
        tanda = {"sukses": "OK", "gagal": "GAGAL", "dilewati": "LEWAT"}.get(status, status.upper())
        self._catat_kepala(f"[{tanda}] {nisn} — {pesan}")
        self.sedang = None


# --------------------------------------------------------------------------- #
# Pengelola pekerjaan yang sedang berjalan (satu saja)
# --------------------------------------------------------------------------- #
_bot: BotDapodik | None = None
_kunci = threading.Lock()


def _lupakan(bot: BotDapodik) -> None:
    global _bot
    with _kunci:
        if _bot is bot:
            _bot = None


def bot_berjalan() -> BotDapodik | None:
    """Bot yang sedang bekerja, atau ``None`` bila tidak ada pekerjaan berjalan."""
    with _kunci:
        return _bot if (_bot is not None and _bot.berjalan()) else None


def mulai_bot(antrean: list[dict[str, Any]], opsi: dict[str, str], actor: str | None = None,
              kepala: Callable[[str], None] | None = None) -> tuple[int, BotDapodik]:
    """Buat pekerjaan baru & mulai bot di belakang layar. Kembalikan (job_id, bot)."""
    global _bot
    with _kunci:
        if _bot is not None and _bot.berjalan():
            raise BotBerjalanError("Bot masih berjalan. Hentikan dulu sebelum memulai lagi.")
        if not antrean:
            raise BotBerjalanError("Antrean kosong — tidak ada siswa yang perlu diproses.")
        mode = "simulasi" if opsi.get("bot_simulasi") == "1" else (
            "headless" if opsi.get("bot_headless") == "1" else "tampak")
        job_id = services.buat_job_bot(len(antrean), {
            "url": opsi.get("bot_url"),
            "hobi": opsi.get("bot_hobi"),
            "cita": opsi.get("bot_cita"),
            "pakai_nisn": opsi.get("bot_pakai_nisn"),
        }, actor=actor, mode=mode)
        item_ids = [services.isi_item_bot(job_id, siswa) for siswa in antrean]
        _bot = BotDapodik(job_id, antrean, item_ids, opsi, kepala=kepala)
        _bot.jalankan()
        return job_id, _bot


def hentikan_bot() -> bool:
    dengan = bot_berjalan()
    if dengan is None or not dengan.berjalan():
        return False
    dengan.hentikan()
    return True


def _keadaan_halaman(peramban) -> dict[str, Any]:
    """Kesiapan halaman: already dimuat, masih ada mask/loading, jumlah iframe."""
    try:
        return dict(peramban.execute_script(
            """
            const terlihat = (el) => {
                const kotak = el.getBoundingClientRect();
                const gaya = window.getComputedStyle(el);
                return kotak.width > 1 && kotak.height > 1 &&
                       gaya.display !== 'none' && gaya.visibility !== 'hidden';
            };
            const mask = [...document.querySelectorAll('div.x-mask, .loading, .loading-mask, #loading')]
                .filter(terlihat).length;
            return {
                readyState: document.readyState,
                overlay: mask,
                iframe: document.querySelectorAll('iframe').length,
                judul_dokumen: document.title || '',
                teks_awal: (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 300),
            };
            """))
    except Exception as exc:  # noqa: BLE001
        return {"galat": f"{type(exc).__name__}: {str(exc)[:120]}"}


def uji_dapodik(opsi: dict[str, str] | None = None,
                coba_login: bool = False) -> dict[str, Any]:
    """Buka Dapodik sebentar lalu laporkan apa yang benar-benar terlihat.

    Alat bantu bila bot berhenti dengan TimeoutException. Laporan memuat: judul &
    alamat halaman, kesiapan halaman (readyState/overlay), daftar kolom isian dan
    tombol beserta status terlihat, dan status tiap selector login (cocok / ada tetapi
    belum terlihat / tidak ditemukan). Tidak pernah melempar galat ke pemanggil.

    Bila ``coba_login`` benar, kolom login sekalian diisi, tombol masuk ditekan, dan
    hasilnya dilaporkan pada kunci ``masuk`` (pasti: berhasil masuk atau pesan Dapodik).
    """
    opsi = dict(opsi or services.bot_setting())
    bot = BotDapodik(0, [], [], opsi)
    laporan: dict[str, Any] = {
        "waktu": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": (opsi.get("bot_url") or "").strip(),
        "headless": opsi.get("bot_headless", "1") == "1",
        "simulasi": opsi.get("bot_simulasi", "0") == "1",
        "catatan": [],
        "selector_status": {},
        "kolom": [],
        "tombol": [],
        "formulir_tampil": False,
    }
    if not laporan["url"]:
        laporan["galat"] = "Alamat Dapodik belum diisi pada pengaturan bot."
        return laporan

    peramban = None
    try:
        peramban = bot._buka_peramban()
        peramban.get(laporan["url"])
        bot._tunggu_halaman(peramban)
        laporan.update({k: v for k, v in bot._ringkas_halaman(peramban).items()
                        if k not in ("galat_ringkas",)})
        laporan["halaman"] = _keadaan_halaman(peramban)
        laporan["lapisan_bersih"] = bot._tunggu_lapisan(peramban)
        laporan["formulir_tampil"] = bot._formulir_terlihat(peramban)

        kolom, tombol = bot._deskripsi_unsur(peramban)
        laporan["kolom"] = kolom[:15]
        laporan["tombol"] = tombol[:12]

        peta = peta_selector()
        for kunci in ("login_username", "login_password", "login_tombol"):
            laporan["selector_status"][kunci] = bot._keadaan_selector(peramban, kunci, peta)

        # Nama lama (dipakai pesan ringkas & pemeriksaan mandiri) tetap diisi.
        laporan["selector_cocok"] = {
            kunci: ("bawaan" if info.get("keadaan") == "terlihat" and not info.get("cadangan")
                    else "cadangan" if info.get("keadaan") == "terlihat"
                    else info.get("keadaan") or "tidak_ada")
            for kunci, info in laporan["selector_status"].items()}
        belum_terlihat = [kunci for kunci, keadaan in laporan["selector_status"].items()
                          if keadaan["keadaan"] == "ada_tak_terlihat"]
        tidak_ada = [kunci for kunci, keadaan in laporan["selector_status"].items()
                     if keadaan["keadaan"] == "tidak_ada"]
        if belum_terlihat:
            laporan["catatan"].append(
                "Ada di halaman tetapi belum terlihat: " + ", ".join(belum_terlihat) + ". "
                "Artinya halaman Dapodik kemungkinan belum selesai dimuat. Naikkan «Jeda muat "
                "halaman Dapodik» (mis. 15–20 detik) dan «Batas tunggu elemen» (mis. 60), lalu "
                "uji lagi — bot juga sudah otomatis menunggu lebih lama dan mengisi kolom yang "
                "belum terlihat.")
        if tidak_ada:
            laporan["catatan"].append(
                "Tidak ditemukan: " + ", ".join(tidak_ada) + ". Cocokkan dengan unsur yang "
                "terbaca di bawah, lalu sesuaikan nilainya pada «Peta tombol Dapodik» "
                "(Pengaturan Bot) atau kirimkan tangkapan layar ini.")
        if not laporan["kolom"]:
            laporan["catatan"].append(
                "Tidak ada kolom isian sama sekali: aplikasi Dapodik kemungkinan belum selesai "
                "membuka halaman, atau alamat/port yang dituju salah.")
        if not laporan["lapisan_bersih"]:
            laporan["catatan"].append(
                "Lapisan pemuatan Dapodik (mask/overlay) masih terlihat setelah ditunggu — "
                "halaman memang belum siap. Bot akan mengisi kolom lewat jalur paksa; bila masih "
                "gagal, naikkan «Jeda muat halaman Dapodik».")
        if coba_login:
            laporan["masuk"] = bot._coba_login(peramban, peta)
            laporan["catatan"].append(
                ("Percobaan masuk: " if laporan["masuk"]["berhasil"] else
                 "Percobaan masuk belum berhasil: ") +
                (laporan["masuk"]["pesan"] or "tanpa keterangan"))
        laporan["bukti"] = bot._bukti(peramban, "uji-koneksi-dapodik")
    except Exception as exc:  # noqa: BLE001 — alat bantu, selalu kembalikan laporan
        laporan["galat"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        if peramban is not None:
            try:
                peramban.quit()
            except Exception:  # noqa: BLE001
                pass
    return laporan


def status_bot() -> dict[str, Any]:
    dengan = bot_berjalan()
    return dengan.kemajuan() if dengan else {}
