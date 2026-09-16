# SIMSEK — Sistem Informasi Manajemen Sekolah

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
3. Ekstrak, misalnya ke `C:\SIMSEK`

### Langkah B — jalankan

**Cara termudah di Windows:** klik dua kali berkas **`run.bat`**.
Skrip itu otomatis membuat lingkungan Python, memasang dependensi (sekali saja,
perlu internet), lalu menjalankan server.

**Manual lewat Command Prompt:**

```cmd
cd C:\SIMSEK
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
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

Agar berjalan sendiri, aktifkan di bagian **Pengaturan Pembaruan**: periksa otomatis
tiap N jam, tarik otomatis bila ada versi baru, dan muat ulang otomatis. Bila
pembaruan tersedia, admin juga melihat pemberitahuan di halaman **Dasbor**.

Cara manual (bila aplikasi tidak dipasang lewat `git clone`, atau ingin lewat
Command Prompt):

```cmd
cd /d C:\SIMSEK
git pull origin arena/01a0a87a-sm
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

> Fitur ini perlu Git bila ingin dipakai dari dalam aplikasi. Bila Python/Git belum
> ada di komputer server, halaman Pembaruan tetap menampilkan langkah manualnya.
> Untuk mematikan fitur ini: set `SM_GIT_UPDATE=0`.

### Tanya jawab pembaruan

| Pertanyaan | Jawaban |
| --- | --- |
| Pembaruan dijalankan di komputer mana? | Di **komputer server** tempat aplikasi dijalankan. Bila dibuka dari browser komputer lain, penarikan tetap terjadi di server. |
| Apakah data siswa hilang? | Tidak. `git pull` hanya mengganti berkas program; basis data dan unggahan ada di folder `data/` yang tidak ikut git. |
| Bagaimana kalau ada perubahan kode lokal? | Penarikan otomatis dibatalkan agar tidak ada pekerjaan yang hilang. Jalankan `git status` untuk melihat berkasnya. |
| Cadangan ada di mana? | `data/backup/simsek-YYYYmmdd-HHMMSS.sqlite3`, dibuat otomatis sebelum penarikan (10 terbaru disimpan). |
| Komputer tanpa internet? | Matikan "Periksa pembaruan otomatis" pada halaman Pembaruan; aplikasi tetap berjalan normal. |

### Opsi lain

```cmd
run.bat                              ← Windows: klik dua kali
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

### Ekstrakurikuler
- Kelola kegiatan: kode, kategori, pembina, hari, jam, tempat, kuota, deskripsi, status.
- Anggota dengan jabatan, nilai, predikat, dan status, plus ekspor daftar anggota CSV.
- Statistik sebaran kategori dan jumlah siswa terlibat.

### Portal siswa
- Siswa masuk hanya dengan **NISN** (opsional ditambah tanggal lahir, diatur di Pengaturan).
- Melihat kelengkapan datanya sendiri dan **memperbaiki alamat/kontak** — perubahan
  tercatat di riwayat dengan sumber `portal_siswa`.

### Statistik & kualitas data
- Rekap per tingkat, rombel, agama, kecamatan, transportasi, program bantuan.
- **Kualitas Data**: kelengkapan setiap kolom, 8 temuan bergaya validasi Dapodik
  (NISN bukan 10 digit, NIK bukan 16 digit, NISN ganda, dan lainnya), serta panel
  kesiapan sinkronisasi.

### Pengaturan (khusus admin)
- Identitas sekolah (nama, NPSN, alamat, kepala sekolah, kontak).
- Preferensi: tahun ajaran, semester, aturan login siswa, hak edit siswa, baris per halaman.
- Manajemen pengguna (admin / operator-guru), audit aktivitas, kunci API.

### Pembaruan aplikasi (khusus admin)
- Menu **Pembaruan**: periksa pembaruan di GitHub, tarik pembaruan (`git pull`),
  lihat catatan perubahan, dan muat ulang server tanpa membuka Command Prompt.
- Cadangan basis data otomatis sebelum penarikan (`data/backup/`, 10 berkas terbaru).
- Pemeriksaan berkala di latar belakang, dengan pilihan tarik otomatis dan
  muat ulang otomatis.

---

## 4. Fondasi bot Dapodik (tahap berikutnya)

Aplikasi sudah menyiapkan seluruh kontrak yang dibutuhkan bot agar tahap berikutnya
tinggal menulis logika di sisi Python:

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
├── app/
│   ├── main.py                # rakit FastAPI, penangan kesalahan, /health
│   ├── config.py              # konfigurasi & path (dapat dioverride via env SM_*)
│   ├── db.py                  # koneksi SQLite + helper query/transaksi
│   ├── migrations.py          # skema & seeder (versi 001_skema_awal)
│   ├── security.py            # hash PBKDF2, cookie sesi, kunci API
│   ├── readers.py             # pembaca xlsx/xls/xlsb/ods/csv  ← inti multi-format
│   ├── dapodik.py             # definisi 66 field, deteksi header, validasi
│   ├── services.py            # logika bisnis: impor, siswa, ekskul, statistik, API
│   ├── auth.py                # login petugas (user+sandi) & siswa (NISN)
│   ├── updater.py             # pembaruan aplikasi: git pull, cadangan, muat ulang
│   ├── web.py                 # konfigurasi Jinja2, filter tanggal/angka, paginasi
│   ├── routers/               # rute HTTP dipisah per modul
│   │   ├── auth_routes.py     login/logout
│   │   ├── dashboard_routes.py
│   │   ├── student_routes.py  data siswa, statistik, kualitas data, ekspor
│   │   ├── import_routes.py   unggah → pratinjau → jalankan
│   │   ├── ekskul_routes.py   ekstrakurikuler & anggota
│   │   ├── portal_routes.py   portal siswa
│   │   ├── settings_routes.py pengaturan, pengguna, API key
│   │   ├── update_routes.py   pembaruan aplikasi (khusus admin)
│   │   └── api_routes.py      API JSON untuk bot Dapodik
│   ├── templates/             # Jinja2 (server-side, tanpa CDN)
│   │   ├── _macros.html, base.html, partials/
│   │   └── students/, import/, ekskul/, portal/
│   └── static/css/app.css, static/js/app.js
├── scripts/
│   ├── cek_sistem.py          # pemeriksaan mandiri 14 titik uji
│   └── buat_template.py       # pembuat berkas template impor
├── template-import/           # contoh.xlsx berisi data fiktif (aman dibagikan)
├── sample-data/               # berkas Dapodik asli (tidak di-commit, berisi data pribadi)
└── data/                      # database, unggahan, kunci sesi (tidak di-commit)
```

---

## 6. Data & privasi

- **Pembaruan kode tidak menyentuh data**: `git pull` hanya mengubah berkas program;
  `data/`, pengguna, pengaturan, dan kunci API tetap. Sebelum menarik pembaruan,
  aplikasi membuat cadangan basis data di `data/backup/`.
- **Semua data disimpan lokal** di folder `data/` (`simsek.sqlite3`). Tidak ada
  pengiriman data ke internet. Untuk mencadangkan aplikasi, cukup salin folder `data/`.
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
| `SM_ROWS_PER_PAGE` | `25` | Baris per halaman |
| `SM_AUTO_SEED` | `1` | Impor otomatis berkas contoh saat database kosong |
| `SM_API_PUBLIC` | `0` | `1` = API baca dapat diakses tanpa kunci |
| `SM_GIT_UPDATE` | `1` | `0` = matikan fitur pembaruan `git pull` di aplikasi |
| `SM_GIT_BIN` | otomatis | Path `git` bila tidak terdeteksi otomatis |
| `SM_GIT_TIMEOUT` | `180` | Batas waktu perintah git (detik) |
| `SM_RESTART_CMD` | `run.py` | Perintah untuk memulai ulang server setelah pembaruan |

---

## 8. Rencana pengembangan berikutnya

- [x] Pembaca Excel/CSV multi-format & pemetaan kolom Dapodik otomatis
- [x] Data peserta didik lengkap dengan pencarian, filter, ekspor, dan audit perubahan
- [x] Login admin (`admin`/`admin123`) dan login siswa (NISN)
- [x] Modul ekstrakurikuler (kegiatan, anggota, nilai, predikat)
- [x] Laporan kualitas data & panel kesiapan sinkronisasi
- [x] API JSON + kunci akses sebagai fondasi integrasi
- [x] Fitur pembaruan aplikasi dari dalam web (git pull, cadangan, muat ulang)
- [ ] **Bot Dapodik**: pembaca berkas Dapodik, pembanding data, dan pengirim koreksi otomatis
- [ ] Riwayat kenaikan kelas & mutasi siswa antar tahun ajaran
- [ ] Presensi harian dan rekap per kelas
- [ ] Nilai rapor, legger, dan cetak rapor
- [ ] Notifikasi WhatsApp/e-mail untuk wali murid
- [ ] Multi-sekolah dalam satu pemasangan (multi-tenant)

Silakan ajukan fitur berikutnya — struktur `routers/` + `services.py` sengaja dibuat per modul
agar penambahan fitur tidak mengganggu yang sudah ada.
