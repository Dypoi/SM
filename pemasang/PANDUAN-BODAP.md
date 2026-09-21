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
4. **Menyiapkan basis data** di folder data. **Data lama tidak pernah dihapus** — memasang
   ulang atau memperbarui hanya mengganti program.
5. **Membuat ikon SM** di Desktop & menu Start, peluncur `Jalankan-SM.cmd`, pencabut
   `Hapus-SM.cmd`, dan bacaan singkat `BACA-INI-SM.txt`.

Bila folder tujuan sudah berisi berkas orang lain, pemasang **berhenti** dan meminta folder
lain — tidak ada berkas yang tertimpa.

## 4. Pemakaian tanpa jendela (opsional, untuk skrip)

```bat
bodap.exe --sunyi --tujuan D:\SM --data D:\SM\data --port 8000
bodap.exe --periksa                :: cerita kondisi pemasangan
bodap.exe --hapus --tujuan D:\SM --ya
bodap.exe --uji                    :: uji mandiri: pasang → jalankan → periksa → hapus
```

## 5. Uji otomatis

* `python scripts/uji_bodap.py` — ikon, isi `payload`, `bodap --uji` (memasang, menjalankan
  aplikasi sampai halaman utama menjawab HTTP, memeriksa data di luar folder aplikasi tetap
  ada sesudah pencabutan). Hasil terakhir: **26/26 pemeriksaan**.
* Alur GitHub Actions menjalankan `bodap.exe --uji --laporan hasil-uji.json` **di runner
  Windows** sebelum artifact diunggah — jadi berkas yang diunduh sudah terbukti bisa dipasang.

## 6. Menghapus

* **Windows → Pengaturan → Aplikasi → SM → Hapus** (folder `…\Programs\SM`), atau
* klik dua kali **`Hapus-SM.cmd`** di folder aplikasi.
* Data sekolah tetap tersimpan bila folder datanya berada di luar folder aplikasi
  (mis. `D:\SM-data`); hapus manual hanya bila memang ingin dibuang.
