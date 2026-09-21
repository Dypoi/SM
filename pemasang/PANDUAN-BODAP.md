# bodap.exe — pemasang SM satu berkas

**Tujuan:** cukup membawa **satu berkas `bodap.exe`** ke laptop/PC lain, klik dua kali di sana,
lalu ikuti jendelanya seperti pemasang aplikasi pada umumnya:

```
Sambutan → Lanjut → Folder & pilihan → Lanjut → [pemasangan berjalan] → Selesai
```

Selesai itu: ikon **SM** muncul di Desktop, klik ikon itu → aplikasi sekolah langsung terbuka
di peramban (`http://localhost:8000`). Internet diperlukan **sekali saja**, saat memasang
(untuk pustaka aplikasi).

---

## 1. Cara mendapatkan `bodap.exe`

Pilih salah satu:

| Cara | Perintah | Catatan |
| --- | --- | --- |
| **A. Di PC sendiri (Windows)** | klik dua kali **`pemasang\BUAT-BODAP.bat`** | perlu Python 3.10+ & internet; hasil akhir: **`dist\bodap.exe`** |
| **B. Otomatis di GitHub** | salin templat sekali: `copy pemasang\ci\bodap-windows.yml .github\workflows\` → commit & push → tab **Actions** → «bodap.exe (pemasang Windows)» → **Run workflow** | GitHub membangun di runner Windows; hasilnya artifact **bodap-windows** (berisi `bodap.exe` + laporan uji) |

Cara A juga berjalan otomatis bila Anda mengunggah tanda versi:
`git tag v0.1.0 && git push origin v0.1.0` → `bodap.exe` langsung menempel pada halaman
**Releases** repo.

## 2. Yang dibawa `bodap.exe`

Semuanya ada di dalam satu berkas itu (± 60–80 MB):

| Isi | Guna |
| --- | --- |
| seluruh program SM (folder `app`, template, skrip) | yang dijalankan di komputer tujuan |
| **Python bawaan Windows** (embeddable) | komputer tujuan **tidak perlu** memasang Python |
| pip + daftar pustaka | memasang FastAPI & pembaca Excel **tanpa internet** bila paket dibuat `--dengan-bahan` |
| `pemasang/pasang.py` | mesin pemasangan/pencabutan yang ikut tersalin ke folder aplikasi |
| ikon `SM` | untuk `bodap.exe`, pintasan Desktop, dan jendela pemasang |

## 3. Yang dikerjakan pemasang (di komputer tujuan)

1. **Menyalin program** ke `%LOCALAPPDATA%\Programs\SM` (bisa diganti pada halaman pilihan).
2. **Menyiapkan Python bawaan** di dalam folder aplikasi — Python milik komputer tidak diubah.
   Bila paket tidak membawa Python bawaan, dipakai Python komputer; kalau tidak ada, bisa
   diunduh otomatis (opsi pada wizard).
3. **Memasang pustaka** (butuh internet sekali). Bila paket memuat `payload/wheels`, pemasangan
   berjalan tanpa internet.
4. **Menyiapkan basis data** di folder data — untuk pemasangan **baru** isinya **fresh &
   kosong**: tanpa siswa contoh dan **tanpa daftar ekstrakurikuler bawaan** (14 ekskul resmi
   diisi sendiri dari halaman Ekstrakurikuler bila memang dipakai). **Data lama tidak pernah
   dihapus** — memasang ulang atau memperbarui hanya mengganti program.
5. **Membuat peluncur & pencabut**: `SM.vbs` + `Hentikan-SM.vbs` beserta `SM-latar.py`
   (menjalankan & mematikan aplikasi **di belakang layar tanpa jendela terminal**),
   `Jalankan-SM.cmd`, `Hapus-SM.cmd`/`Hapus-SM.vbs`, ikon **SM** di Desktop & menu Start,
   serta bacaan singkat `BACA-INI-SM.txt`.

Bila folder tujuan sudah berisi berkas orang lain, pemasang **berhenti** dan meminta folder
lain — tidak ada berkas yang tertimpa.

## 4. Setelah terpasang: jalan di belakang layar (tanpa jendela terminal)

Ikon **SM** di Desktop tidak membuka jendela hitam apa pun: ia menjalankan `SM.vbs` yang
memanggil **`pythonw.exe`** → `SM-latar.py` → aplikasi SM. Aplikasi **berjalan di belakang
layar**, peramban terbuka sendiri di `http://localhost:8000`, dan tidak ada jendela konsol
yang perlu dibiarkan terbuka.

| Yang ingin dilakukan | Caranya |
| --- | --- |
| membuka aplikasi | klik ikon **SM** di Desktop (atau `SM.vbs`) — bila sudah jalan, peramban saja yang dibuka |
| mematikan aplikasi | menu Start → **Hentikan SM** (`Hentikan-SM.vbs`), tanpa jendela apa pun |
| melihat keadaan | `python SM-latar.py --status` (tambahkan `--json` untuk skrip) |
| mencari masalah | `python SM-latar.py --tampak` menjalankannya di jendela ini; catatan aplikasi ada di `data\log-server.txt` |
| mencabut aplikasi | Windows → **Pengaturan → Aplikasi → SM → Hapus** (data sekolah tidak disentuh) |

Port bawaan **8000**; bila sedang dipakai program lain, pemasang memilih port bebas berikutnya
dan mencatatnya di `data\server.json` — berkas yang sama dipakai `--status` dan `--hentikan`.

## 5. Pemakaian tanpa jendela (opsional, untuk skrip)

```bat
bodap.exe --sunyi --tujuan D:\SM --data D:\SM\data --port 8000
bodap.exe --periksa                :: cerita kondisi pemasangan
bodap.exe --hapus --tujuan D:\SM --ya
bodap.exe --uji                    :: uji mandiri: pasang → jalankan → periksa → hapus
```

## 6. Uji otomatis

* `python scripts/uji_bodap.py` — ikon, isi `payload`, **kesesuaian berkas pustaka bawaan
  dengan versi yang dipatok aplikasi**, **pemasangan yang tetap berhasil walau berkas bawaan
  tidak cocok (lanjut internet)**, dan `bodap --uji` (memasang, menjalankan aplikasi sampai
  halaman utama menjawab HTTP, menjalankannya lewat peluncur latar sampai bisa dihentikan,
  memastikan basis data hasil pasang **kosong**, serta memeriksa data di luar folder aplikasi
  tetap ada sesudah pencabutan). Hasil terakhir: **38 pemeriksaan**.
* Alur GitHub Actions menjalankan `bodap.exe --uji --laporan hasil-uji.json` **di runner
  Windows** sebelum artifact diunggah — jadi berkas yang diunduh sudah terbukti bisa dipasang.

## 7. Pemecahan masalah

| Gejala | Sebab & jalan keluar |
| --- | --- |
| `ERROR: Could not find a version that satisfies the requirement python-multipart==0.0.20 (from versions: 0.0.32)` lalu «Pemasangan pustaka gagal» | Berkas pustaka bawaan di dalam `bodap.exe` itu **versinya berbeda** dari yang diminta aplikasi (kejadian pada bodap.exe lama: bundel memakai versi terbaru, sedangkan aplikasi memakai versi yang dipatok). **Sejak perbaikan ini pemasang otomatis melanjutkan unduhan dari internet**, jadi pesan itu tidak lagi menghentikan pemasangan. Bila masih muncul: buat ulang `bodap.exe` dengan **`pemasang\BUAT-BODAP.bat`** (bundel pustaka baru dibuat dari `requirements.txt`), lalu jalankan lagi. |
| «Pemasangan pustaka gagal» padahal internet ada | Pastikan unduhan ke `pypi.org` tidak diblokir (jaringan sekolah kadang memakai proxy/filter). Coba setel proxy Windows atau jalankan sekali di jaringan lain; berkas yang sudah tersalin tidak perlu diulang. |
| «Komputer ini belum punya Python 3.10+» | Paket tidak membawa Python bawaan. Centang **«Bila perlu, unduh Python dari python.org»** pada wizard, atau pasang Python manual (<https://www.python.org/downloads/>, centang «Add python.exe to PATH»). |
| Ikon Desktop tidak muncul | Pemasang memberi tahu di catatan bila gagal. Buat manual: klik kanan `Jalankan-SM.cmd` → **Kirim ke → Desktop (buat pintasan)**. |
| «Folder tujuan sudah berisi berkas lain» | Pilih folder lain pada halaman pilihan (pemasang tidak menimpa berkas orang lain). |
| Saat aplikasi dijalankan muncul jendela hitam (terminal) | Jendela itu muncul bila SM dijalankan lewat `Jalankan-SM.cmd`/`SM.cmd`, bukan lewat ikon **SM**. Ikon SM memakai `SM.vbs` → `pythonw.exe` (tanpa konsol). Tutup jendelanya dan pakai ikon **SM**; untuk mencari masalah pakai `python SM-latar.py --tampak`. |
| Ikon **SM** diklik tetapi aplikasi tidak terbuka | Periksa `data\server.json` (port & pid) dan `data\log-server.txt` (pesan terakhir aplikasi); jalankan `python SM-latar.py --status`. Bila perlu, `python SM-latar.py --hentikan` lalu klik ikon SM sekali lagi. |
| Daftar ekstrakurikuler sudah terisi padahal ingin mulai kosong | Pemasangan baru sudah kosong. Daftar 14 ekskul resmi hanya terisi bila diminta (tombol di halaman Ekstrakurikuler atau `python run.py --isi-ekskul-resmi`); `SM_EKSKUL_SEKOLAH=0` (bawaan) memastikan tidak ada pengisian otomatis. |

## 8. Menghapus

* **Windows → Pengaturan → Aplikasi → SM → Hapus** (folder `…\Programs\SM`), atau
* klik dua kali **`Hapus-SM.cmd`** di folder aplikasi.
* Data sekolah tetap tersimpan bila folder datanya berada di luar folder aplikasi
  (mis. `D:\SM-data`); hapus manual hanya bila memang ingin dibuang.
