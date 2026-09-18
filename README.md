# SM — Sistem Informasi Manajemen Sekolah

Aplikasi manajemen sekolah yang **ringan**, **tanpa build step**, dan **siap dikembangkan**:
membaca berkas Excel/CSV dalam banyak format, menampilkan data peserta didik lengkap
seperti pada ekspor Dapodik, dilengkapi modul ekstrakurikuler, portal siswa, dan fondasi
API untuk **bot Dapodik** pada tahap berikutnya.

```
Python 3.10+  ·  FastAPI  ·  Jinja2  ·  SQLite  ·  openpyxl/xlrd/pyxlsb/odfpy
Tanpa Node.js, tanpa bundler, tanpa CDN — satu proses, satu berkas database.
```

---

## 1. Mengambil & menjalankan aplikasi

### Langkah A — ambil kodenya (sekali saja)

Lewat **Command Prompt** (Windows) / Terminal:

```cmd
git clone https://github.com/Dypoi/SM.git
cd SM
git checkout arena/01a0a87a-sm
```

> Kode saat ini berada di cabang `arena/01a0a87a-sm`. Setelah pull request
> [#1](https://github.com/Dypoi/SM/pull/1) digabung ke `main`, baris
> `git checkout` tidak lagi diperlukan.

**Tidak punya Git?** Unduh sebagai ZIP:

1. Buka <https://github.com/Dypoi/SM/tree/arena/01a0a87a-sm>
2. Klik tombol hijau **Code → Download ZIP**
3. Ekstrak, misalnya ke `C:\SM`

### Langkah B — jalankan

**Cara termudah di Windows:** klik dua kali berkas **`run.bat`**.
Skrip itu mencari Python sendiri (folder `.venv` aplikasi diperiksa lebih dulu),
membuat lingkungan Python, memasang dependensi (sekali saja, perlu internet), lalu
menjalankan server. Jendela `.venv` tidak perlu diaktifkan lebih dulu.

**Manual lewat Command Prompt:**

```cmd
cd C:\SM
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-bot.txt   :: opsional, hanya bila memakai Bot Dapodik
python run.py
```

**Linux / macOS:**

```bash
./run.sh                  # atau: python3 -m venv .venv && ...
```

Buka **http://localhost:8000** di peramban.

### Langkah C — masukkan data siswa

Dua pilihan:

1. **Otomatis** — salin berkas Excel Anda (mis. `daftar_pd-SMP NEGERI 2 TANGERANG.xlsx`)
   ke folder `sample-data\`. Saat aplikasi dijalankan dan database masih kosong,
   berkas pertama di folder itu akan diimpor sendiri (816 siswa ±5 detik).
2. **Manual** — masuk sebagai admin, buka menu **Impor Excel/CSV**, unggah berkas,
   periksa pratinjau, lalu klik **Jalankan Impor**.

> Folder `sample-data/` sengaja tidak ikut ter-commit karena berisi data pribadi
> siswa (NIK, NISN, alamat). Berkas contoh fiktif tersedia di
> `template-import/contoh-template-import.xlsx` untuk uji coba.

| Peran | Cara masuk |
| --- | --- |
| **Admin** | username `admin`, kata sandi `admin123` |
| **Siswa** | cukup masukkan **NISN** (mis. `0113374384`) |

> ⚠️ Segera ubah kata sandi `admin` melalui **Pengaturan → Pengguna** setelah aplikasi dipakai.

### Langkah D — mengambil fitur baru (pembaruan)

Setelah aplikasi ini dikembangkan lebih lanjut, Anda tidak perlu mengulang dari awal.
Login sebagai **admin**, lalu buka menu **Pembaruan** di bilah samping (atau
**Pengaturan → Sistem → Pembaruan aplikasi**):

1. Klik **Periksa pembaruan** — aplikasi menanyakan GitHub (butuh internet) dan
   menampilkan berapa komit baru yang tersedia beserta catatan perubahannya.
2. Klik **Tarik pembaruan (git pull)** — kode terbaru masuk ke komputer Anda,
   dependensi baru dipasang otomatis bila `requirements.txt` berubah, dan satu
   **cadangan basis data** dibuat lebih dulu di `data/backup/`.
3. Server dimuat ulang sendiri memakai kode baru (beberapa detik; halaman akan
   terputus sesaat lalu bisa dibuka kembali). Data siswa, pengguna, dan pengaturan
   **tidak berubah**.

> Saat dimuat ulang di Windows, sebuah **jendela konsol baru** terbuka untuk menjalankan
> server — jendela lama (yang berisi `pause` dari `run.bat`) boleh ditutup. Di Linux/macOS
> prosesnya diganti di tempat, tanpa jendela tambahan.

Agar berjalan sendiri, aktifkan di bagian **Pengaturan Pembaruan**: periksa otomatis
tiap N jam, tarik otomatis bila ada versi baru, dan muat ulang otomatis. Bila
pembaruan tersedia, admin juga melihat pemberitahuan di halaman **Dasbor**.

Cara manual (bila aplikasi tidak dipasang lewat `git clone`, atau ingin lewat
Command Prompt):

```cmd
cd /d C:\SM
git pull origin arena/01a0a87a-sm
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

> Fitur ini perlu Git bila ingin dipakai dari dalam aplikasi. Bila Python/Git belum
> ada di komputer server, halaman Pembaruan tetap menampilkan langkah manualnya.
> Untuk mematikan fitur ini: set `SM_GIT_UPDATE=0`.

### Mode otomatis (bawaan)

Sejak fitur pembaruan, aplikasi memeriksa GitHub **setiap 6 jam** dan — bila ada versi
baru, tidak ada perubahan kode lokal, dan kode barunya lolos pemeriksaan — langsung
menariknya lalu memuat ulang server sendiri. Seluruh proses itu disetel di halaman
**Pembaruan → Pengaturan Pembaruan**:

| Opsi | Bawaan | Guna |
| --- | --- | --- |
| Periksa pembaruan otomatis | aktif | Menghubungi GitHub berkala; matikan bila server tanpa internet |
| Tarik otomatis | aktif | `git pull` sendiri tanpa klik |
| Muat ulang otomatis | aktif | Server memakai kode baru tanpa ditutup manual |

**Pengaman sebelum kode baru dipakai:** berkas di-`fetch` + `pull --ff-only`, basis data
dicadangkan ke `data/backup/`, lalu kode diperiksa (`compileall` seluruh modul dan uji
impor `app.main`). Bila kode barunya rusak, perubahan **dikembalikan otomatis**
(`git reset --hard` ke revisi sebelumnya) sehingga aplikasi tetap berjalan, dan
kejadiannya tercatat di **Pengaturan → Audit** serta halaman Pembaruan.

### Tanya jawab pembaruan

| Pertanyaan | Jawaban |
| --- | --- |
| Pembaruan dijalankan di komputer mana? | Di **komputer server** tempat aplikasi dijalankan. Bila dibuka dari browser komputer lain, penarikan tetap terjadi di server. |
| Apakah data siswa hilang? | Tidak. `git pull` hanya mengganti berkas program; basis data dan unggahan ada di folder `data/` yang tidak ikut git. |
| Bagaimana kalau ada perubahan kode lokal? | Penarikan otomatis dibatalkan agar tidak ada pekerjaan yang hilang. Jalankan `git status` untuk melihat berkasnya. |
| Cadangan ada di mana? | `data/backup/sm-YYYYmmdd-HHMMSS.sqlite3`, dibuat otomatis sebelum penarikan (10 terbaru disimpan). |
| Komputer tanpa internet? | Matikan "Periksa pembaruan otomatis" pada halaman Pembaruan; aplikasi tetap berjalan normal. |
| Di Windows, apa yang terjadi saat "Muat ulang server sekarang"? | Aplikasi menulis berkas `data/jalankan-ulang.bat`, lalu membuka **jendela konsol baru** yang menjalankannya. Jendela lama (server sebelum pembaruan) otomatis berhenti dan boleh ditutup. Tunggu 5–10 detik, lalu muat ulang halaman di browser. |
| Ada peluncur lain selain `run.bat`? | Ya, `SM.cmd` — sama seperti `run.bat` tetapi tanpa memasang dependensi (lebih cepat dipakai sehari-hari bila `.venv` sudah ada). |
| Muncul pesan `[!] Python 3.10 atau lebih baru tidak ditemukan` padahal Python sudah dipasang? | Perbarui `run.bat` (tarik pembaruan), lalu jalankan lagi. Versi baru mencari Python di `.venv` aplikasi, peluncur `py`, PATH, dan folder pemasangan umum — tanpa bergantung pada perintah `where` yang bisa gagal bila `PATH` berubah. Bila masih gagal, jalankan **`SM-diagnosa.bat`** (membuat `laporan-python.txt`) dan kirim isinya. |
| Bagaimana kalau server belum sempat menyala padahal `run.bat` gagal? | Jalankan langsung dengan Python yang sudah ada, mis. dari jendela `.venv`: `python run.py`. Aplikasi menyala seperti biasa. |
| Sesaat setelah menekan **Tarik pembaruan** muncul galat `500` / `static_url is undefined`? | Itu keadaan peralihan: berkas tampilan sudah baru, tetapi server masih menjalankan kode lama. Sejak versi ini aplikasi menampilkan halaman **"Pembaruan berhasil dipasang — menunggu server siap"** yang membuka kembali halaman Pembaruan sendiri, dan template tetap dapat dirender oleh kode lama. Bila masih muncul, tunggu 5–10 detik lalu muat ulang halaman; kode & data tidak rusak. |
| Setelah muat ulang halaman malah "tidak dapat diakses"? | Berarti server sedang tidak berjalan. Buka folder aplikasi dan klik dua kali **`run.bat`**. Data siswa tidak terpengaruh. Bila jendela konsol baru memang tidak muncul, jalankan `run.bat` secara manual sekali, lalu coba lagi. |

### Opsi lain

```cmd
run.bat                              ← Windows: klik dua kali
SM.cmd                               ← Windows: mulai cepat (tanpa pasang dependensi)
SM-online.bat                        ← Windows: jalankan + akses internet (bagian 8)
SM-diagnosa.bat                      ← Windows: laporan kondisi bila ada masalah
python run.py --port 9000            # ganti port
python run.py --reload               # mode pengembangan (auto-restart)
python run.py --init-db              # siapkan database lalu keluar
python run.py --seed-ekskul          # isi contoh data ekstrakurikuler
python scripts/cek_sistem.py --http  # pemeriksaan mandiri seluruh fitur
python scripts/buat_template.py      # buat berkas template impor di template-import/
```

---

## 2. Membaca berkas Excel & CSV

Berkas diunggah lewat menu **Impor Excel/CSV**, dibaca, ditampilkan sebagai pratinjau,
baru kemudian disimpan. Tidak ada data yang langsung masuk tanpa persetujuan Anda.

### Format yang didukung

| Ekstensi | Keterangan | Pustaka |
| --- | --- | --- |
| `.xlsx`, `.xlsm`, `.xltx`, `.xltm` | Excel 2007 ke atas | openpyxl |
| `.xls` | Excel 97–2003 | xlrd |
| `.xlsb` | Excel Binary Workbook | pyxlsb |
| `.ods` | LibreOffice / OpenOffice | odfpy |
| `.csv`, `.txt`, `.tsv` | Teks berpemisah | `csv` bawaan Python |

Pemisah CSV (`,` `;` tab `|`), BOM, dan encoding (UTF-8 / Windows-1252 / Latin-1)
dideteksi otomatis — berkas hasil ekspor Excel Indonesia yang memakai titik-koma
tetap terbaca benar.

### Yang dilakukan saat membaca berkas

1. **Deteksi format** dari ekstensi (atau isi berkas bila ekstensi tidak ada).
2. **Mencari baris header** dengan memberi skor setiap baris (dipindai 40 baris pertama).
   Baris judul, nama sekolah, wilayah, tanggal unduh, dan nama pengunduh pada ekspor
   Dapodik otomatis terlewati.
3. **Menyambung sub-header** untuk kolom bergabung `Data Ayah`, `Data Ibu`, dan
   `Data Wali`, sehingga terbentuk kolom seperti `Data Ayah - Pekerjaan`.
4. **Memetakan kolom** ke field aplikasi memakai daftar alias — misalnya `JK`,
   `Jenis Kelamin`, `L/P`, dan `Jenkel` semuanya menuju field yang sama.
5. **Menormalkan nilai**: tanggal (`2011-08-22`, `22/08/2011`, `22 Agustus 2011`,
   serial angka Excel, `20110822`) dan angka desimal gaya Indonesia (`1.234,5`).
6. **Memvalidasi ala Dapodik**: NISN harus angka & 10 digit, NIK 16 digit, kelengkapan
   data orang tua, No. KK, rombel, dan pendeteksian NISN ganda.

### Mode penyimpanan

| Mode | Perilaku |
| --- | --- |
| **Perbarui (upsert)** | Menambah siswa baru, mengisi kolom yang masih kosong. Nama, NIK, dan No. KK yang sudah terisi **tidak** ditimpa. Disarankan. |
| **Hanya tambah** | Melewati NISN yang sudah ada. |
| **Timpa** | Seluruh kolom dari berkas menimpa data aplikasi. |
| **Uji coba (dry)** | Hanya validasi, tidak menulis apa pun. |

### Susunan berkas Dapodik yang dikenali

```
Baris 1 : Daftar Peserta Didik
Baris 2 : SMP NEGERI 2 TANGERANG
Baris 3 : Kecamatan …, Kabupaten …, Provinsi …
Baris 4 : Tanggal Unduh: 2026-09-16 10:52:47
Baris 5 : No | Nama | NIPD | JK | NISN | … (66 kolom)
Baris 6 : (sub-header Data Ayah / Ibu / Wali)
Baris 7+: data siswa
```

Seluruh **66 kolom** ekspor Dapodik dipetakan: identitas, alamat & kontak, data
ayah/ibu/wali (masing-masing 6 sub-kolom), rombel, bantuan (KIP/KPS/PIP), bank,
akta lahir, kesehatan, sampai koordinat rumah.

---

## 3. Fitur yang sudah tersedia

### Data peserta didik
- Daftar siswa dengan pencarian, filter (rombel, tingkat, JK, agama, kelurahan,
  status, kelengkapan data), pengurutan, paginasi, dan 4 preset kolom
  (ringkas / kontak / orang tua / bantuan).
- Halaman detail berisi seluruh kolom, riwayat perubahan per kolom,
  dan daftar ekstrakurikuler siswa.
- Tambah, ubah, dan hapus data (hapus khusus admin).
- Ekspor hasil filter ke **CSV** (siap dibuka Excel, pemisah `;`) dan **Excel `.xlsx`**
  dengan kop sekolah.

### Impor
- Unggah berkas, pratinjau 25 baris pertama, daftar pemetaan kolom, dan daftar temuan.
- Laporan masalah per baris dapat diunduh sebagai CSV.
- Riwayat setiap impor tersimpan (berkas, worksheet, baris header, hasil, status).
- 14 kolom Dapodik lama (dusun, jenis tinggal, alat transportasi, telepon, e-mail, SKHUN,
  no. peserta UN, no. KKS, bank, no. rekening, rekening atas nama, lintang, bujur,
  kebutuhan khusus)
  **tidak lagi dipakai**; berkas lama tetap bisa diunggah dan kolom tersebut ditampilkan
  sebagai "tidak lagi dipakai" pada halaman pratinjau impor.

### Ekstrakurikuler
- Kelola kegiatan: **nama, pembina, pelatih**, hari & jam, deskripsi, dan status.
  (Kolom kode, kategori, tempat, dan kuota sudah dihapus sesuai permintaan sekolah.)
- Anggota dengan jabatan, **nilai A/B/C/D**, **catatan per siswa**, dan status.
- Pembina/pelatih dapat **memasukkan & mengeluarkan siswa** (dengan NISN atau nama siswa),
  lalu menyimpan nilai + catatan langsung dari tabel anggota. Ada juga **Cari cepat siswa**
  (pilih kelas atau tulis nama) dengan tombol *Masukkan* per siswa.
- **Hari & jam kegiatan diisi sendiri oleh pembina/pelatih** dari halaman ekskulnya.
- **Siswa dapat mendaftar sendiri** dari portalnya; permintaan masuk sebagai *menunggu* dan
  **disetujui/ditolak pembina atau pelatih** ekskul tersebut. Persetujuan langsung menjadikan
  siswa anggota; penolakan boleh disertai catatan dan siswa dapat mendaftar lagi.
- **Ekspor daftar anggota: Excel (.xlsx), CSV, dan PDF** — lengkap dengan nama sekolah,
  pembina, pelatih, tahun ajaran, dan kolom tanda tangan pada berkas PDF.
- Statistik: jumlah kegiatan, keanggotaan, siswa terlibat, dan ekskul yang belum berpendamping.

### Portal siswa
- Siswa masuk hanya dengan **NISN** (opsional ditambah tanggal lahir, diatur di Pengaturan).
- Beranda, data lengkap miliknya, kelengkapan data, dan status berkas (akta kelahiran,
  kartu keluarga, ijazah).
- **Ajukan perubahan data**: memperbaiki setiap kolom datanya (kecuali NISN), melampirkan
  foto ketiga berkas, dan menunggu keputusan admin. Riwayat pengajuan terlihat di portal.
- **Mendaftar ekstrakurikuler**: siswa memilih kegiatan yang ingin diikuti dari halaman
  **Ekstrakurikuler**, memantau keadaannya (*menunggu / disetujui / ditolak*), dapat membatalkan
  selama masih menunggu, dan melihat nilai + catatan setelah disetujui pembina/pelatih.
- Kolom **Rombel Saat Ini** dan **Tingkat** tidak dapat diajukan siswa maupun diubah dari
  formulir petugas — perubahannya hanya lewat **impor Excel**.

### Formulir data keluarga (ayah / ibu / wali)
- **Pekerjaan** (ayah, ibu, wali) dipilih dari daftar 17 pilihan Dapodik:
  Tidak Bekerja, Nelayan, Petani, Peternak, PNS/TNI/Polri, Karyawan Swasta,
  Pedagang Kecil, Pedagang Besar, Wiraswasta, Wirausaha, Buruh, Pensiunan,
  Tenaga Kerja Indonesia, Karyawan BUMN, Tidak Dapat Diterapkan, Sudah Meninggal,
  dan Lainnya.
- **Penghasilan** (ayah, ibu, wali) dipilih dari daftar rentang: Kurang dari
  Rp. 500,000 · Rp. 500,000 - Rp. 999,999 · Rp. 1,000,000 - Rp. 1,999,999 ·
  Rp. 2,000,000 - Rp. 4,999,999 · Rp. 5,000,000 - Rp. 20,000,000 ·
  Lebih dari Rp. 20,000,000 · Tidak Berpenghasilan.
- **Jenjang pendidikan** (ayah, ibu, wali) dipilih dari daftar: Tidak Sekolah ·
  Putus SD · SD / sederajat · SMP / sederajat · SMA / sederajat · Paket A ·
  Paket B · Paket C · TK / sederajat · Paud · D1 · D2 · D3 · D4 · S1 · S2 · S3.
- Nilai lama dari berkas impor yang tidak ada di daftar tetap ditampilkan
  (ditandai *data lama*) supaya tidak ada data yang berubah tanpa disengaja;
  nilai yang hanya berbeda huruf besar/kecil otomatis memakai pilihan baku.
- **Data wali hanya ditampilkan bila nama ayah kosong.** Di blok wali ada
  pertanyaan **"Apakah siswa mempunyai wali?"** (Ya / Tidak) serta tombol
  **Hapus data wali**.
- **Data wali dihapus otomatis oleh sistem — tanpa persetujuan siapa pun.**
  Sistem menganggap siswa tidak memiliki wali (dan mengosongkan seluruh kolom
  wali) bila salah satu kondisi ini terpenuhi:
  1. **nama ayah sudah diisi** → siswa dianggap tidak punya wali;
  2. **nama wali sama dengan nama ayah/ibu** → itu sebenarnya data ayah/ibu;
  3. **kolom wali terisi tetapi nama wali kosong**.
  Penghapusan ini berlaku di formulir petugas, di pengajuan siswa (langsung
  selesai tanpa masuk antrean admin dan tanpa perlu unggah berkas), maupun
  lewat API bot; setiap penghapusan tercatat di riwayat data & audit.
- Di formulir, isian wali yang tidak sesuai **tidak ditolak dan tidak memblokir
  penyimpanan**: sistem mengosongkannya lalu menampilkan pesan hasil di halaman
  siswa ("data wali dikosongkan otomatis oleh sistem"). Blok wali juga menampilkan
  catatan lebih dulu bila nama wali sama dengan ayah/ibu.
- Satu-satunya aturan yang **menolak** penyimpanan: **nama ayah tidak boleh
  sama dengan nama ibu** — pesannya meminta kedua nama diperiksa.
- **Rapikan data lama**: bila masih ada data wali dari berkas impor yang tidak
  sesuai aturan, halaman **Kualitas Data** menampilkan daftar siswanya beserta
  alasan dan tombol **"Rapikan data wali"** untuk membersihkannya sekaligus.
  Impor berkas sendiri tetap menampilkan isi berkas apa adanya (tidak dipangkas
  saat diunggah).

### Masuk sebagai pembina / pelatih ekstrakurikuler

Ekstrakurikuler dikelola oleh **pembina** (guru pendamping) dan **pelatih** kegiatan, dan keduanya
masuk ke aplikasi memakai **NIK 16 angka** — tanpa kata sandi.

1. Buka halaman **login**, pilih kartu **Ekstrakurikuler**.
2. Pilih peran (**Pembina** atau **Pelatih**) dan nama ekstrakurikuler.
3. Masukkan **NIK 16 angka** (angka saja; spasi/tanda hubung diabaikan).
4. **Nama Bapak/Ibu** (opsional) dipakai sebagai nama tampilan saat NIK itu pertama kali masuk.

Aturan yang berlaku:

* Satu ekskul hanya punya **satu pembina** dan **satu pelatih**.
* NIK yang masuk **pertama kali** untuk sebuah posisi langsung **terdaftar (dikunci)** pada posisi itu —
  jadi tinggal dipakai masuk berikutnya.
* Posisi yang sudah terisi **tidak bisa diklaim** orang lain; pesannya menyebutkan NIK yang terdaftar.
* Salah orang atau salah pilih peran/ekskul? Admin membukanya di
  **Pengaturan → Pengguna → Akun Ekstrakurikuler** lalu menekan **Lepaskan**; posisi itu bisa diisi lagi
  oleh NIK berikutnya.
* Akun ekskul hanya dapat membuka ekskulnya sendiri: **memasukkan & mengeluarkan siswa**,
  mengisi **hari & jam kegiatan**, **jabatan**, **nilai A/B/C/D**, **catatan**, dan status anggota,
  memutuskan **pendaftaran siswa**, serta mengunduh daftar anggota dalam **Excel, CSV, atau PDF**.
  Halaman data siswa, impor, statistik, dan pengaturan tetap khusus petugas sekolah.
* Nama pembina/pelatih otomatis terisi pada data ekskul begitu yang bersangkutan masuk memakai NIK.

Daftar ekstrakurikuler yang disiapkan aplikasi: OSIS, BASKET, FUTSAL, HADROH, MADING, PADUAN SUARA,
PASKIBRA, PENCAK SILAT, PMR, PRAMUKA, ROHIS, TARI, VOLLY, dan WUSHU. Ekskul lain tetap bisa
ditambahkan lewat menu **Ekstrakurikuler**.

### Persetujuan data siswa (khusus admin)
- Menu **Persetujuan Data** menampilkan antrean pengajuan siswa (yang menunggu di atas)
  beserta jumlah berkas dan statistiknya.
- Halaman periksa menampilkan perbandingan *data sekarang -> usulan siswa* per kolom,
  pratinjau berkas bukti, dan riwayat perubahan siswa tersebut.
- **Setujui** langsung menerapkan nilai baru (tercatat sebagai sumber `pengajuan_siswa`)
  dan menandai berkas sebagai diterima; **Tolak** menyertakan catatan untuk siswa.
- NISN tidak pernah dapat diubah lewat pengajuan; siswa boleh membatalkan pengajuannya
  sendiri selama masih menunggu. Atur lewat `pengajuan_aktif` dan
  `pengajuan_wajib_dokumen` di Pengaturan.

### Statistik & kualitas data
- Rekap per tingkat, rombel, agama, kecamatan, sekolah asal, program bantuan.
- **Kualitas Data**: kelengkapan setiap kolom, 14 temuan bergaya validasi Dapodik
  (NISN bukan 10 digit, NIK bukan 16 digit, NISN ganda, **nama ayah sama dengan
  nama ibu**, **nama wali sama dengan nama ayah/ibu**, **data wali yang akan
  dibersihkan otomatis**, **pendidikan/pekerjaan/penghasilan di luar daftar
  pilihan**, dan lainnya), serta panel kesiapan sinkronisasi.
- **Dua tombol di halaman itu dan gunanya:**
  * **Daftar siswa bermasalah (N)** — membuka Data Siswa berisi siswa yang masih ada
    kolom wajib kosong (`?lengkap=0`), yaitu yang menghambat sinkron Dapodik.
  * **Perbaiki** pada tiap baris temuan — membuka Data Siswa yang **hanya memuat siswa
    terkena temuan itu** (`?masalah=KODE`), plus banner penjelasan, saran perbaikan, dan
    penandaan baris serta sel yang harus dibetulkan. Angka pada halaman Kualitas Data dan
    daftar siswa yang terbuka dihitung dari satu sumber yang sama (`TEMUAN_DAFTAR`),
    jadi tidak mungkin berbeda.
  * Pada tabel **Kelengkapan per Kolom**, angka **Kosong** dan tombol **Perbaiki**
    membuka siswa yang kolom tersebut masih kosong (`?kosong=nama_kolom`); kolom
    bermasalah otomatis ikut ditampilkan walau preset tabel tidak memuatnya.
  * NISN ganda dihitung sebagai **jumlah siswa** (bukan jumlah nilai NISN) dan barisnya
    bisa diklik untuk melihat siswa pemakai NISN tersebut.

### Bot Dapodik (khusus admin)
- Menu **Bot Dapodik** memperbarui data Dapodik **berdasarkan data aplikasi SM**:
  bot mengambil antrean siswa dari aplikasi ini, lalu menyelaraskannya ke Dapodik
  lewat peramban. Tahap yang sudah dikerjakan sekarang: pendaftaran (**Registrasi**)
  bagi siswa yang belum ada di Dapodik berikut pengisian **NIS** (dari kolom NIPD),
  jawaban «Ya» (diperiksa ulang seperti radio jarak: bila Dapodik belum menandainya, lognya
  memberi peringatan — dulu bot mengklaim berhasil padahal kliknya ditelan Ext JS), **Hobi**,
  dan **Cita-cita** — alurnya: cari NISN → pilih baris →
  **Registrasi** → isi **NIS** → centang semua jawaban «Ya» → **Hobi** → **Cita-cita**
  → **Simpan dan Tutup**. Kolom lain (NIK, alamat, ayah/ibu, dst.) ditambahkan dengan
  pola yang sama begitu alur Dapodik untuk kolom tersebut diketahui.
- **Versi kode dicantumkan pada log & halaman bot.** Setiap kali bot mulai bekerja, lognya
  diawali baris `[versi] kode SM yang berjalan: <nomor revisi> — langkah tiap siswa: 1) cari
  NISN & pilih barisnya → 2) Data Periodik (gulir panel → tinggi/berat/lingkar → pilih radio
  jarak → km → saudara → Simpan dan Tutup) → 3) Registrasi (NIS → Sekolah Asal → «Ya» → Hobi →
  Cita-cita → Simpan dan Tutup)`, dan halaman Bot Dapodik menampilkan lencana **Kode SM:
  `<nomor revisi>`**. Jadi bila log PC sekolah belum memuat baris itu (atau nomornya belum
  berubah setelah pembaruan), berarti kode barunya belum terpakai — **tutup `run.bat` lalu
  jalankan ulang** (server tidak memuat ulang sendiri), dan perbarui lewat menu **Pembaruan
  aplikasi** bila folder itu salinan git.
- Siswa yang NISN-nya tidak ada di Dapodik dicatat *“tidak ditemukan”* sehingga mudah
  ditindaklanjuti (mis. NISN salah pada data SM).
- **Antrean diambil dari data siswa aplikasi SM**, bukan dari berkas Excel:
  pilih kelas/rombel, batasi jumlah siswa, atau tempel daftar NISN (bila ingin
  meniru daftar Excel). Siswa berstatus *Lulus/Mutasi/Keluar/Non-aktif* tidak diikutkan.
- Bot bekerja **di belakang layar** (Chrome tanpa jendela) sehingga aplikasi SM tetap
  bisa dipakai petugas. Matikan pilihan itu bila ingin melihat prosesnya.
- **Kemajuan tampil di aplikasi**: jumlah siswa, yang sudah diproses, berhasil, gagal,
  siswa yang sedang diproses, kecepatan, dan perkiraan sisa waktu — diperbarui
  otomatis setiap 2 detik. Rincian per siswa dapat diunduh sebagai **CSV/Excel**.
- **Lanjut tanpa mengulang**: siswa yang sudah berhasil dilewati pada pekerjaan
  berikutnya; tersedia juga pilihan «diproses ulang semua».
- **Mode uji coba** (simulasi) mencatat antrean & kemajuan tanpa membuka peramban —
  pakai ini untuk mencoba alur sebelum benar-benar mendaftar ke Dapodik.
- Bila Dapodik berganti versi, tombol/lokasi kolom dapat disesuaikan lewat
  *Peta tombol Dapodik (JSON)* pada halaman bot, tanpa mengubah program.

### Pengaturan (khusus admin)
- Identitas sekolah (nama, NPSN, alamat, kepala sekolah, kontak).
- Preferensi: tahun ajaran, semester, aturan login siswa, pengajuan perubahan data
  (aktif & wajib berkas), baris per halaman.
- Manajemen pengguna (admin / operator-guru), audit aktivitas, kunci API.

### Pembaruan aplikasi (khusus admin)
- Menu **Pembaruan**: periksa pembaruan di GitHub, tarik pembaruan (`git pull`),
  lihat catatan perubahan, dan muat ulang server tanpa membuka Command Prompt.
- Cadangan basis data otomatis sebelum penarikan (`data/backup/`, 10 berkas terbaru).
- Pemeriksaan berkala di latar belakang, dengan pilihan tarik otomatis dan
  muat ulang otomatis.

---

## 4. Bot Dapodik

> **Sebelum mengubah bot ini, baca `AGENTS.md` (aturan kerja) dan `CATATAN-KESALAHAN.md`.** Berkas itu memuat 10
> kesalahpahaman yang pernah membuat perbaikan meleset (mis. memperbaiki jalur klik padahal
> kotaknya tidak pernah ketemu), daftar periksa sebelum mengklaim "sudah beres", dan peta
> *gejala → baris log → fungsi*. Ringkasan pelajarannya: **cocokkan kalimat log pengguna ke
> baris kode yang mencetaknya sebelum menyimpulkan apa pun**, dan jangan pernah menganggap
> "hijau di uji tiruan" berarti "beres di sekolah".

Bot Dapodik **sudah aktif** di menu **Bot Dapodik** (khusus admin). Ringkasnya:

1. **Pasang Chrome** di PC sekolah (bot memakai Chrome yang sudah terpasang).
2. **Pasang pustaka bot sekali saja.** Cara termudah: buka menu **Bot Dapodik** lalu
   tekan tombol **«Pasang pustaka bot»** (butuh internet, sekitar 1 menit); status
   pustaka terlihat pada kartu *Pengaturan Bot*. Bisa juga lewat Command Prompt:

   ```bat
   cd C:\SM
   .venv\Scripts\python -m pip install -r requirements-bot.txt
   ```

   > **Penting:** pemasangan harus memakai Python milik aplikasi (folder `.venv`).
   > Perintah `pip install ...` biasa bisa masuk ke Python lain di komputer sehingga
   > aplikasi tetap mengatakan *"Pustaka selenium belum terpasang"*. Bila memakai
   > `run.bat`, pustaka bot juga dicoba dipasang otomatis saat belum ada.

3. **Isi pengaturan bot**: alamat Dapodik (bawaan `http://localhost:5774/`), surel/NIK
   akun Dapodik, kata sandi, Hobi, dan Cita-cita. Pilihan *Bekerja di belakang layar*
   dibiarkan tercentang. Untuk percobaan pertama, centang **Mode uji coba (simulasi)**.
4. **Susun antrean** dari data siswa SM: pilih kelas dan/atau batasi jumlah siswa,
   lalu tekan *Tampilkan antrean* → *Mulai bot*.
5. **Pantau kemajuan** pada kartu di atas — bot boleh ditinggal, halaman ini diperbarui
   sendiri. Bila perlu berhenti, tekan *Hentikan bot* (siswa yang sedang diproses
   diselesaikan lebih dulu).

**Alur bot = alur skrip Selenium sekolah**, langkah demi langkah: buka alamat → tunggu
kolom nama pengguna tampil → isi nama pengguna & kata sandi → tekan tombol masuk → tunggu
2 detik → klik menu tujuan (mis. *Peserta Didik*) → tunggu 5 detik → tutup popup bila
muncul → tunggu 2 detik → klik dua menu lanjutan → tunggu 2 detik.

**Popup pengumuman Dapodik** (mis. «Selamat Datang di Aplikasi Dapodik 2027.b») ditunggu
sampai benar-benar tampil, lalu ditutup lewat tombol **Tutup** — kalau perlu lewat klik
skrip atau membuang jendelanya dari halaman. Ini penting karena Dapodik di PC sekolah
menampilkan popup itu **lebih lambat daripada 5 detik** yang ditunggu skrip asli; selama
popup tampil, Dapodik mengabaikan klik di luarnya (akibatnya tombol *Registrasi* seolah
tidak berpengaruh). Karena itu popup juga diperiksa lagi **sebelum setiap langkah**
berikutnya. Per siswa: cari NISN →
klik baris hasilnya → **Data Periodik** (halaman digulir 250 px dulu — `window.scrollBy(0, 250)`
seperti skrip sekolah, lalu tinggi badan, berat badan, lingkar kepala, pilihan «Jarak rumah ke
sekolah» («kurang dari 1 km» / «lebih dari 1 km» sesuai data) + kolom «Sebutkan (dalam
kilometer):», jumlah saudara kandung → *Simpan dan Tutup*)
→ *Registrasi* → isi NIS
→ isi **Sekolah Asal** (dari kolom Sekolah Asal pada data siswa SM) → centang semua «Ya» →
Hobi → Cita-cita → *Simpan dan Tutup*. Yang berbeda hanya sumber antreannya (data siswa SM, bukan Excel) dan
cara menampilkan kemajuannya (di halaman Bot Dapodik). Bawaan **Batas tunggu elemen 15
detik** & **3 percobaan ulang** juga sama seperti skrip itu.

**Data Periodik** dikenali lewat nama kolomnya (`tinggi_badan`, `berat_badan`,
`lingkar_kepala`, `jumlah_saudara_kandung`, `jarak_rumah_ke_sekolah_km`) maupun lewat
**label**nya, dan pilihan «Jarak rumah ke sekolah» memakai XPath dari skrip sekolah
(`periodik_jarak_lebih` = div[2], `periodik_jarak_kurang` = div[1]) dengan cadangan berbasis label.
Bila Dapodik sekolah menamainya lain, ubah pada *Peta tombol Dapodik*, mis.
`{"periodik_saudara": "name:jml_saudara"}`.

**Bila formulir Registrasi tidak terbuka**, bot **mengklik tombol Registrasi ulang**
(3× seperti batas percobaan ulang) sambil memeriksa popup yang mungkin menutupi halaman —
jadi pekerjaan tidak berhenti hanya karena satu klik tertelan. Bot juga **memastikan baris
siswanya benar-benar terpilih** sebelum menekan Registrasi: Dapodik hanya membuka Registrasi
untuk siswa yang terpilih, sedangkan di Ext JS pemilihan terjadi saat *mousedown* sehingga
klik lewat skrip saja tidak cukup — bila perlu, bot mengirim urutan tetikus lengkap
(*mousedown → mouseup → click*) ke sel NISN.

**Bila bot berhenti dengan pesan waktu habis / elemen tidak ditemukan** — tekan tombol
**«Uji koneksi Dapodik»**. Bot membuka Dapodik sebentar lalu menampilkan apa yang
sebenarnya terlihat: judul halaman, kesiapan halaman (readyState & overlay/lapisan
pemuatan), daftar kolom isian dan tombol beserta status *terlihat/belum*, status tiap
selector login (cocok bawaan / cocok cadangan / **ada tetapi belum terlihat** /
tidak ditemukan), plus **tangkapan layar** tersimpan di `data/bot/`.

Ada dua pilihan pada tombol itu (boleh dipakai bersamaan):

| Pilihan | Gunanya |
| --- | --- |
| **Coba masuk** | Bot benar-benar mengisi kolom login & menekan tombol masuk (seperti skrip manual), lalu melaporkan hasilnya: **BERHASIL** atau pesan Dapodik yang menolak. Jadi tidak perlu menebak lagi. Bisa memakan waktu sampai ±1 menit. |
| **Isi Data Periodik sebelum Registrasi** (centang pada Pengaturan Bot) | Persis skrip sekolah: bot **membawa panel «Data Periodik Peserta Didik» ke layar** lebih dulu dengan `scrollIntoView` — panel ini berada di area gulir sendiri (`/html/body/div[2]/div/div/div[2]/div/div/div/div[4]`), sehingga `window.scrollBy` saja tidak menjangkaunya dan malah menggeser bagian halaman yang tidak perlu; sesudah itu halaman tetap digulir **250 px** (`window.scrollBy(0, 250)`) seperti skrip sekolah, dan bila kolomnya belum ketemu semuanya diulang sampai 4× sebelum bot menyimpulkan kolom itu memang tidak ada. Setelah itu bot mengisi **tinggi badan, berat badan, lingkar kepala**, memilih **«Jarak rumah ke sekolah»** — **≤ 1 km → «kurang dari 1 km»**, **> 1 km → «lebih dari 1 km»** (pilihan div[2], sama seperti skrip sekolah) — dan untuk yang lebih dari 1 km sekaligus mengisi kolom **«Sebutkan (dalam kilometer):»** (`jarak_rumah_ke_sekolah_km`), lalu mengisi **jumlah saudara kandung** pada panel *Data Periodik Peserta Didik* — nilainya dari kolom Tinggi Badan / Berat Badan / Lingkar Kepala / Jumlah Saudara Kandung milik siswa di aplikasi SM — lalu menekan *Simpan dan Tutup*. Langkah ini dijalankan sesudah baris siswa dipilih dan **sebelum** tombol *Registrasi* ditekan. Uji khusus bot (tanpa Chrome) ada di `scripts/uji_bot_dapodik.py` — **9 skenario, 29 pemeriksaan**: DOM sekolah (label sesudah input, kelas `x-form-cb-checked`, kolom km nonaktif→aktif), keadaan hanya-terbaca-lewat-kelas, semua klik ditelan → `Ext.getCmp`, kegagalan total → peringatan jujur, model Ext JS tidak ikut (penanda tak pindah → naik `Ext.getCmp` → km aktif & terisi), XPath meleset → kotak dilacak lewat teks labelnya, baris jarak tidak ada → dilewati jujur + isi panel dilaporkan, jarak ≤ 1 km, dan jarak kosong. Kolom yang tidak ada pada versi Dapodik sekolah, atau data siswa yang kosong, hanya dicatat pada log — siswa tetap didaftarkan. Centang «Isi baris Jarak rumah ke sekolah» dapat dimatikan tersendiri bila sekolah tidak memakainya. Tag `periodik_jarak_kurang`/`periodik_jarak_lebih` dapat ditimpa di «Peta tombol Dapodik» bila tata letak Dapodik berbeda. Bila kolom **Jarak Rumah ke Sekolah (KM)** siswa kosong, tidak ada pilihan yang dicentang — Dapodik menolak centang jarak tanpa keterangan kilometernya. **Langkah ini selalu tercatat** — log memuat baris `[periodik] memilih «Jarak rumah ke sekolah» — data siswa 2 km → pilihan «lebih dari 1 km».` sebelum pemilihannya, lalu hasilnya (`… dicentang: 1 dari 1`). **Struktur DOM Dapodik (terperiksa dari halaman sekolah):** radio jaraknya adalah `input[type=radio][name=jarak_rumah_ke_sekolah]` di dalam `div.x-field`, dengan label `label.x-form-cb-label` (**sesudah** input) dan penanda tercentang berupa kelas `x-form-cb-checked` pada pembungkusnya — input-nya sendiri tidak membawa atribut `checked`. Karena itu kotaknya dilacak dari labelnya lewat wadah `.x-field` / poros `preceding::` (bukan `following::`), keadaan tercentangnya dibaca dari ketiga sumber (properti `checked`, kelas `x-form-cb-checked`, `aria-checked`), dan setiap unsur Ext JS membawa `data-componentid` (atau `for="radiofield-1112-inputEl"` pada labelnya) sehingga `Ext.getCmp(...).setValue(...)` adalah **jalur pamungkas**: inilah yang benar-benar mengubah model Ext JS, bukan hanya tampilan. Bot memeriksa **penanda** itu setiap kali memilih — bila tampilan sudah berubah tetapi penanda `x-form-cb-checked` masih di pilihan lain, artinya nilai Ext JS belum berubah (dan kolom kilometer tetap nonaktif), sehingga bot langsung naik ke `Ext.getCmp`. **Jangan bergantung pada satu XPath.** XPath Dapodik (mis. `td/div[2]/…/span/input`) berbeda antar versi dan bisa meleset; dulu bila itu terjadi bot berhenti dengan «kotak … tidak ada di halaman ini» walaupun pilihannya jelas terlihat guru. Sekarang, bila selector tidak menemukan pilihan yang diminta, **kotaknya dilacak lewat teks pilihannya** — dibaca langsung oleh JavaScript (label `for="…-inputEl"` → kotaknya, atau input di dalam `.x-field` yang sama) — lalu labelnya diklik seperti skrip sekolah. Kandidat yang teksnya terbaca tetapi bertuliskan pilihan lain **dibuang** (jangan sampai bot memilih «kurang dari 1 km» hanya karena selectornya mengembalikan satu radio). Setiap pemilihan juga mencatat satu baris jelas: `[periodik] pilihan jarak «lebih dari 1 km»: kotaknya ditemukan (id komponen radiofield-1112) — dicoba klik labelnya → kotaknya → pembungkusnya → Ext.getCmp.`, dan bila jalur Ext JS juga tidak bisa dipakai bot mencatat alasannya (*id komponen tidak terbaca*). Bila pilihan itu memang tidak ada di halaman, log menyebutkan **apa yang benar-benar terlihat di panel** (label & nama kolomnya), bukan sekadar gagal diam-diam. **Kolom «Sebutkan (dalam kilometer)» nonaktif (`disabled`) sampai pilihan «lebih dari 1 km» benar-benar terpasang** — bot menunggu kolomnya aktif lebih dulu, dan bila pilihannya gagal, kolom itu **dilewati dengan jujur** (bukan diisi paksa lalu dianggap berhasil). **Pilihan radio diperiksa ulang:** Ext JS/Dapodik kadang menelan klik yang dikirim lewat skrip (`arguments[0].click()`) — perintahnya seolah berhasil padahal centangnya tidak berubah. Karena itu bot mengecek keadaan terpilih dari halaman, lalu mencoba berurutan: klik **labelnya** (`label` / `x-form-cb-label` yang bertuliskan «lebih dari 1 km» — **persis cara skrip sekolah yang terbukti berhasil**) → klik sungguhan pada kotaknya → klik **pembungkus** kolomnya (`x-form-cb-wrap-inner`) → urutan tetikus lengkap (mousedown → mouseup → click) lewat skrip. Begitu pula setiap kolom isian (berat badan, kilometer, jumlah saudara kandung): setelah diketik, Ext JS diberi tahu lewat peristiwa **input → change → blur** seperti pada skrip itu, supaya nilainya benar-benar terbaca Dapodik. Bila semuanya belum berhasil, log berkata jujur: *“peringatan: Dapodik belum menandainya terpilih (mungkin perlu diklik manual sekali)”* — bot **tidak** lagi mengaku berhasil seperti sebelumnya. Tag `periodik_panel` (wadah panelnya) dapat ditimpa di «Peta tombol Dapodik» bila tata letak Dapodik berbeda.
| **Isi kolom «Sekolah Asal»** (centang pada Pengaturan Bot) | Bot mengisi *Sekolah Asal* pada formulir Registrasi Dapodik dengan kolom **Sekolah Asal** milik siswa di aplikasi SM. Kolom itu dicari lewat namanya maupun lewat labelnya, jadi tetap jalan walau Dapodik menamai kolom berbeda antar versi. Bila Dapodik sekolah tidak punya kolom itu atau data siswanya kosong, langkah ini **dilewati dengan catatan pada log** — siswa tetap didaftarkan. |
| **Jendela tampak** | Uji sekali ini dijalankan dengan jendela Chrome terlihat — berguna untuk membandingkan bila mode *di belakang layar* gagal. Pekerjaan bot yang sesungguhnya tetap di belakang layar. |

Arti hasil yang paling sering muncul:

| Hasil | Artinya | Tindakan |
| --- | --- | --- |
| Kolom login **“ada, belum terlihat”** | Halaman Dapodik belum selesai dimuat (atau memakai halaman pembuka) | Bot sekarang menunggu sendiri sampai kolom terlihat; kalau masih sering, naikkan *Jeda muat halaman Dapodik* ke 15–20 dan *Batas tunggu elemen* ke 60 |
| **“tidak ditemukan”** pada satu selector | Tombol/kolom berganti nama pada versi Dapodik ini | Bandingkan dengan daftar *unsur yang terbaca pada halaman* di kartu yang sama, lalu sesuaikan nilainya di **«Peta tombol Dapodik»** (Pengaturan Bot) — cukup sekali, dan bot memakainya untuk semua pekerjaan berikutnya |
| **Percobaan masuk belum berhasil** | Halaman belum berpindah setelah tombol masuk ditekan | Lihat pesan di bawahnya (mis. pesan penolakan Dapodik), lalu ulangi uji dengan centang **Jendela tampak** untuk melihat langsung apa yang terjadi |
| **Tidak ada kolom sama sekali** | Alamat/port salah atau Dapodik belum berjalan | Buka `http://localhost:5774/` di Chrome biasa untuk memastikan |

Catatan penting:

- Bot memproses **satu pekerjaan sekaligus**; pekerjaan kedua ditolak selama bot bekerja.
- Bila Dapodik sekolah lambat terbuka, naikkan **Jeda muat halaman Dapodik** (bawaan
  5 detik) dan **Batas tunggu elemen** (bawaan 15 detik, sama seperti skrip sekolah).
- Bila Dapodik berganti versi, bot masih mencoba **selector cadangan** (mis. mencari
  tombol lewat tulisannya) dan menuliskan selector mana yang benar-benar dipakai pada
  catatan pekerjaan, supaya bisa disalin ke *Peta tombol Dapodik*.
- Bila kolom login sudah ada di halaman tetapi belum terlihat (Dapodik masih memuat),
  bot menunggu lebih dulu, dan sebagai jalan terakhir mengisi kolom lewat skrip supaya
  pekerjaan tidak langsung gagal.
- Bot juga **menunggu lapisan pemuatan Ext JS** (`div.x-mask`) hilang sebelum mengisi &
  menekan tombol — sama seperti skrip manual — karena lapisan itu sering menelan klik.
  Bila lapisan itu **tidak kunjung hilang** (Dapodik lambat/macet), langkah tetap
  dilanjutkan dengan cara paksa: klik & pengetikan lewat skrip, lalu dicatat pada log
  (`[tunggu] lapisan pemuatan Dapodik masih terlihat …`). Jadi keluhan
  *“element click intercepted”* pada kolom pencarian NISN tidak lagi membuat siswa
  itu gagal — dan pekerjaan tidak menunggu 10 detik di setiap langkah.
- Setelah menekan tombol masuk, bot **memastikan halaman benar-benar berpindah**; bila
  masih di formulir login, pekerjaan dihentikan dengan pesan yang jelas (termasuk pesan
  penolakan dari Dapodik bila ada), bukan dibiarkan menggantung. Nilai kolom juga dibaca
  ulang supaya ketahuan bila ketikan tidak diterima halaman.
- Bila PC mati atau bot dihentikan di tengah jalan, jalankan lagi dengan pilihan
  *«Dilewati (lanjutkan pekerjaan)»* — siswa yang sudah berhasil tidak didaftarkan dua kali.
- Siswa tanpa NIPD/NIS dilewati (atau memakai NISN bila pilihan itu dicentang).
- Bila Dapodik meminta verifikasi tambahan saat login, matikan *Bekerja di belakang
  layar* supaya jendela Chrome terlihat dan dapat dibantu manual.
- Bila muncul pesan *Google Chrome tidak dapat dibuka*, pasang Google Chrome di PC itu.
  Selenium perlu mengunduh **driver** sekali saja, jadi sambungkan internet saat
  percobaan pertama (pada PC tanpa internet, letakkan `chromedriver.exe` di folder
  aplikasi lalu hubungi pengembang).
- Kata sandi Dapodik hanya tersimpan di database lokal (`data/sm.sqlite3`) dan tidak
  pernah dikirim ke internet.

Selain menu tersebut, aplikasi tetap menyediakan **kontrak API** yang dipakai bot antar
sistem (perubahan lewat `PATCH /api/siswa/{nisn}` tercatat sebagai `api_bot`):

| Persiapan | Keterangan |
| --- | --- |
| **Jejak perubahan** | Tabel `data_changes` menyimpan nilai lama & baru untuk setiap kolom, lengkap dengan sumber (`impor`, `manual`, `api_bot`, `portal_siswa`) dan aktornya. |
| **Antrean pekerjaan** | Tabel `dapodik_jobs` untuk mencatat pekerjaan sinkronisasi (jenis, mode uji coba, status, log). |
| **API tulis** | `PATCH /api/siswa/{nisn}` menerima JSON dan hanya mengizinkan kolom pada `services.STUDENT_WRITABLE`. |
| **API baca** | `/api/siswa`, `/api/siswa/{nisn}`, `/api/kualitas-data`, `/api/field`, `/api/perubahan`, `/api/ekskul`, `/api/audit`. |
| **API impor** | `POST /api/impor` untuk mengunggah & mengimpor berkas secara otomatis, mendukung `dry_run`. |
| **Rencana alur bot** | 1) baca data aplikasi, 2) bandingkan dengan Dapodik berdasarkan NISN, 3) terapkan aturan validasi, 4) kirim perbaikan, 5) audit hasilnya. |

Contoh pemakaian:

```bash
KUNCI="<kunci dari Pengaturan → Integrasi & API>"

# Daftar siswa kelas 9D
curl -H "X-API-Key: $KUNCI" "http://localhost:8000/api/siswa?rombel=9D&per_page=5"

# Perbaiki satu kolom (tercatat sebagai api_bot)
curl -X PATCH -H "X-API-Key: $KUNCI" -H "Content-Type: application/json" \
     -d '{"nik":"3671101605170001","_actor":"bot-dapodik"}' \
     "http://localhost:8000/api/siswa/0113374384"

# Uji coba impor tanpa menyimpan
curl -X POST -H "X-API-Key: $KUNCI" -F "berkas=@daftar_pd.xlsx" \
     "http://localhost:8000/api/impor?mode=upsert&dry_run=true"
```

Dokumentasi interaktif: <http://localhost:8000/api/docs>

---

## 5. Struktur proyek

```
.
├── run.py                     # peluncur: python run.py
├── requirements.txt
├── requirements-bot.txt      # selenium (hanya untuk bot Dapodik, opsional)
├── AGENTS.md                 # aturan kerja repo (dibaca otomatis oleh agen/AI)
├── CATATAN-KESALAHAN.md      # kesalahpahaman yang pernah terjadi pada bot — WAJIB DIBACA
│                             # sebelum mengubah bot Dapodik (lihat §4)
├── app/
│   ├── main.py                # rakit FastAPI, penangan kesalahan, /health
│   ├── config.py              # konfigurasi & path (dapat dioverride via env SM_*)
│   ├── db.py                  # koneksi SQLite + helper query/transaksi
│   ├── migrations.py          # skema & seeder (001_skema_awal, 002_pengajuan_perubahan)
│   ├── security.py            # hash PBKDF2, cookie sesi, kunci API
│   ├── readers.py             # pembaca xlsx/xls/xlsb/ods/csv  ← inti multi-format
│   ├── dapodik.py             # definisi 53 field, deteksi header, validasi
│   ├── services.py            # logika bisnis: impor, siswa, ekskul, statistik, API
│   ├── auth.py                # login petugas (user+sandi) & siswa (NISN)
│   ├── updater.py             # pembaruan aplikasi: git pull, cadangan, muat ulang
│   ├── bot_dapodik.py         # bot Dapodik: alur Selenium, headless, kemajuan
│   ├── web.py                 # konfigurasi Jinja2, filter tanggal/angka, paginasi
│   ├── routers/               # rute HTTP dipisah per modul
│   │   ├── auth_routes.py     login/logout
│   │   ├── dashboard_routes.py
│   │   ├── student_routes.py  data siswa, statistik, kualitas data, ekspor
│   │   ├── import_routes.py   unggah → pratinjau → jalankan
│   │   ├── ekskul_routes.py   ekstrakurikuler & anggota
│   │   ├── portal_routes.py   portal siswa & pengajuan perubahan data
│   │   ├── approval_routes.py persetujuan pengajuan (khusus admin)
│   │   ├── settings_routes.py pengaturan, pengguna, API key
│   │   ├── update_routes.py   pembaruan aplikasi (khusus admin)
│   │   ├── bot_routes.py      bot Dapodik: jalankan, hentikan, kemajuan, log
│   │   └── api_routes.py      API JSON untuk bot Dapodik
│   ├── templates/             # Jinja2 (server-side, tanpa CDN)
│   │   ├── _macros.html, base.html, partials/
│   │   └── students/, import/, ekskul/, portal/, approval/
│   └── static/css/app.css, static/js/app.js
├── scripts/
│   ├── cek_sistem.py          # pemeriksaan mandiri 24 titik uji
│   ├── peramban_palsu.py      # peramban tiruan (alur penuh bot) untuk uji tanpa Chrome
│   └── buat_template.py       # pembuat berkas template impor
├── template-import/           # contoh.xlsx berisi data fiktif (aman dibagikan)
├── sample-data/               # berkas Dapodik asli (tidak di-commit, berisi data pribadi)
└── data/                      # database, unggahan, kunci sesi, bukti bot (tidak di-commit)
    ├── sm.sqlite3             # seluruh data aplikasi
    ├── uploads/dokumen/       # berkas bukti pengajuan siswa
    └── bot/                   # tangkapan layar & HTML saat bot/uji koneksi gagal
```

---

## 6. Data & privasi

- **Pembaruan kode tidak menyentuh data**: `git pull` hanya mengubah berkas program;
  `data/`, pengguna, pengaturan, dan kunci API tetap. Sebelum menarik pembaruan,
  aplikasi membuat cadangan basis data di `data/backup/`.
- **Semua data disimpan lokal** di folder `data/` (`sm.sqlite3`). Tidak ada
  pengiriman data ke internet. Untuk mencadangkan aplikasi, cukup salin folder `data/`.
- Pemasangan lama yang masih memakai `simsek.sqlite3` dipindahkan otomatis ke
  `sm.sqlite3` saat aplikasi dijalankan. Bila berkasnya sedang dipakai program lain
  (mis. jendela server SM lain masih terbuka), pemindahan dicoba beberapa kali lalu
  **dilewati** — aplikasi tetap berjalan dan data tetap aman, dan keterangannya hanya
  muncul sekali. Ingin namanya berganti? Tutup semua jendela SM lalu jalankan `run.bat`.
- **Berkas bukti pengajuan** (akta kelahiran, KK, ijazah) tersimpan di
  `data/uploads/dokumen/<id siswa>/` dan hanya dapat dibuka siswa pemiliknya serta petugas.
  Hapus folder siswa saat lulus bila tidak diperlukan lagi.
- Folder `sample-data/` berisi data siswa sungguhan (NIK, NISN, alamat) dan
  **sengaja diabaikan Git** (lihat `.gitignore`). Berkas contoh di `template-import/`
  memakai data fiktif sehingga aman dibagikan.
- Saat aplikasi pertama dijalankan dan database masih kosong, berkas pertama pada
  `sample-data/` otomatis diimpor sebagai data awal (dapat dimatikan dengan
  `SM_AUTO_SEED=0`).

## 7. Konfigurasi (environment variable)

| Variabel | Bawaan | Kegunaan |
| --- | --- | --- |
| `SM_SECRET_KEY` | dibuat otomatis | Kunci penandatangan cookie sesi |
| `SM_ADMIN_USER` / `SM_ADMIN_PASSWORD` | `admin` / `admin123` | Akun admin pertama |
| `SM_DATA_DIR` | `./data` | Lokasi database, unggahan, kunci |
| `SM_MAX_UPLOAD_MB` | `64` | Batas ukuran berkas unggahan |
| `SM_DOKUMEN_MAX_MB` | `8` | Batas ukuran berkas bukti pengajuan (akta/KK/ijazah) |
| `SM_ROWS_PER_PAGE` | `25` | Baris per halaman |
| `SM_AUTO_SEED` | `1` | Impor otomatis berkas contoh saat database kosong |
| `SM_API_PUBLIC` | `0` | `1` = API baca dapat diakses tanpa kunci |
| `SM_GIT_UPDATE` | `1` | `0` = matikan fitur pembaruan `git pull` di aplikasi |
| `SM_GIT_BIN` | otomatis | Path `git` bila tidak terdeteksi otomatis |
| `SM_GIT_TIMEOUT` | `180` | Batas waktu perintah git (detik) |
| `SM_RESTART_CMD` | `run.py` | Perintah untuk memulai ulang server setelah pembaruan |

---

## 8. Menjalankan online (gratis)

Aplikasi ini bisa dibuka dari internet **tanpa biaya, tanpa IP publik, dan tanpa membuka port
router**. Caranya: server tetap berjalan di komputer sekolah seperti biasa, lalu sebuah
*terowongan* gratis membuatkan alamat publik ber-HTTPS yang menuju komputer itu.

### Cara tercepat (Windows)

1. Klik dua kali **`SM-online.bat`**.
2. Jendela konsol menampilkan alamat publik yang bisa dibagikan ke petugas/siswa.
3. Alamat itu juga tersimpan di `data/alamat-publik.txt` dan tampil di
   **Pengaturan → Sistem → Aman Online**, lengkap dengan daftar periksa keamanan.

Bila Tailscale/cloudflared belum terpasang, aplikasi **tetap berjalan untuk jaringan sekolah**
dan petunjuk pemasangannya ditampilkan di jendela konsol.

### Pilihan terowongan

| Cara | Perlu akun? | Alamat | Catatan |
| --- | --- | --- | --- |
| **Tailscale Funnel** (disarankan) | akun Tailscale gratis | tetap: `https://<nama>.<tautan>.ts.net` | HTTPS otomatis, tanpa kartu kredit, tanpa buka port router |
| **Cloudflare quick tunnel** | tidak | berubah setiap dijalankan: `https://xxxx.trycloudflare.com` | praktis untuk uji coba atau berbagi sesaat |

Langkah **Tailscale**: unduh dari <https://tailscale.com/download>, pasang, lalu masuk; aktifkan
**HTTPS** dan **Funnel** untuk perangkat itu di konsol admin Tailscale, kemudian jalankan
`SM-online.bat` sekali lagi.
Langkah **cloudflared**: unduh `cloudflared-windows-amd64.exe` dari halaman rilis Cloudflare,
simpan sebagai `C:\cloudflared\cloudflared.exe`, lalu jalankan `SM-online.bat` lagi.

### Yang dinyalakan otomatis saat online

Begitu ada permintaan dari alamat IP publik (atau bila `SM_PUBLIK=1`), aplikasi memasang sendiri:

* **Header keamanan**: `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, dan `Content-Security-Policy` dasar.
* **HSTS** dan **cookie sesi `Secure`** bila permintaan lewat HTTPS. Di jaringan sekolah (HTTP)
  cookie tetap tanpa `Secure` supaya login tidak gagal.
* **Penjaga CSRF**: permintaan tulis (POST) yang datang dari situs lain ditolak.
* **Pembatasan percobaan login**: 8 percobaan gagal per akun/NISN dan 40 per alamat IP
  (dapat diubah lewat `SM_LOGIN_MAKS_GAGAL_AKUN`, `SM_LOGIN_MAKS_GAGAL_IP_PUBLIK`,
  `SM_LOGIN_JEDA_DETIK`).
* **Dokumentasi API** (`/api/docs`) hanya terbuka setelah login.
* Halaman **login** dan **portal** tidak disimpan di cache peramban.

### Sebelum dibuka luas

Buka **Pengaturan → Sistem → Aman Online**, lalu benahi yang bertanda *perlu dibenahi*:

1. Ganti kata sandi admin bawaan `admin123` (tab **Pengguna**).
2. Nyalakan **pengaman login siswa** (tersedia tombol satu klik di kartu itu). Dengan NISN saja,
   siapa pun yang tahu NISN seorang siswa dapat melihat data pribadinya (NIK, No. KK, alamat,
   nama orang tua).
3. Salin folder `data/` sebagai cadangan berkala.

### Tanya jawab online

| Pertanyaan | Jawaban |
| --- | --- |
| Bisa dipakai di sekolah dan internet sekaligus? | Bisa. Di sekolah lewat `http://<ip-komputer>:8000`; dari luar lewat alamat `https://…` dari terowongan. |
| Apakah data siswa dikirim ke pihak ketiga? | Tidak. Terowongan hanya meneruskan koneksi; basis data dan berkas tetap di komputer sekolah. |
| Ke mana alamat publik dibagikan? | Cukup kepada petugas dan siswa. Pembatasan percobaan login serta audit login tetap berjalan. |
| Bagaimana mematikan mode online? | Tekan `Ctrl+C` di jendela `SM-online.bat`, atau matikan Funnel di konsol admin Tailscale; penanda di aplikasi dibersihkan lewat tombol **Lupakan penanda online**. |
| Parameter lain? | `python SM-online.py --port 9000`, `--lokal` (tanpa terowongan), `--tanpa-server` (server sudah jalan), `--buka` (buka peramban). |

---

## 9. Rencana pengembangan berikutnya

- [x] Pembaca Excel/CSV multi-format & pemetaan kolom Dapodik otomatis
- [x] Data peserta didik lengkap dengan pencarian, filter, ekspor, dan audit perubahan
- [x] Login admin (`admin`/`admin123`) dan login siswa (NISN)
- [x] Modul ekstrakurikuler (kegiatan, anggota, nilai, predikat)
- [x] Akun ekstrakurikuler: pembina & pelatih masuk dengan NIK 16 angka
      (satu ekskul = satu pembina + satu pelatih, terisi saat login pertama)
- [x] Laporan kualitas data & panel kesiapan sinkronisasi
- [x] API JSON + kunci akses sebagai fondasi integrasi
- [x] Fitur pembaruan aplikasi dari dalam web (git pull, cadangan, muat ulang)
- [x] Pengajuan perubahan data oleh siswa + persetujuan admin + berkas bukti
- [x] Perampingan kolom: 14 kolom Dapodik yang tidak dipakai dihapus
- [x] Dropdown pekerjaan, penghasilan, & pendidikan serta aturan data ayah/ibu/wali
      (data wali dihapus otomatis oleh sistem)
- [x] **Bot Dapodik**: memperbarui data Dapodik dari data siswa SM
      (alur Selenium: registrasi + NIS, bekerja di belakang layar, kemajuan tampil di aplikasi)
- [ ] Bot Dapodik: pengisian kolom lain (NIK, alamat, ayah/ibu, tanggal lahir, dst.)
      begitu alur Dapodik untuk kolom tersebut diketahui
- [ ] Bot Dapodik: pembanding data (SM ↔ Dapodik) & pengirim koreksi lewat API
- [ ] Bot Dapodik: unggah berkas sebagai lampiran registrasi (bila Dapodik mewajibkan)
- [ ] Riwayat kenaikan kelas & mutasi siswa antar tahun ajaran
- [ ] Presensi harian dan rekap per kelas
- [ ] Nilai rapor, legger, dan cetak rapor
- [ ] Notifikasi WhatsApp/e-mail untuk wali murid
- [ ] Multi-sekolah dalam satu pemasangan (multi-tenant)

Silakan ajukan fitur berikutnya — struktur `routers/` + `services.py` sengaja dibuat per modul
agar penambahan fitur tidak mengganggu yang sudah ada.
