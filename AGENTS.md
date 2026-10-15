# AGENTS.md — aturan kerja di repositori ini

> Berkas ini dibaca otomatis oleh agen/AI di awal sesi. **Baca juga
> [`CATATAN-KESALAHAN.md`](CATATAN-KESALAHAN.md)** — di sana ada 10 kesalahpahaman nyata
> (beserta bukti log & potongan DOM) yang sudah pernah membuat perbaikan bot Dapodik meleset.
> Tujuannya satu: **jangan mengulangi kesalahan yang sama.**

Proyek: **SM** — aplikasi manajemen sekolah (FastAPI + SQLite, tampilan HTML sederhana) dengan
bot Dapodik berbasis Selenium. Pengguna utama: petugas sekolah (Windows, `C:\SM`).

---

## 1. Aturan emas (wajib, terutama saat menangani keluhan bot Dapodik)

1. **Cocokkan kalimat log pengguna ke baris kode yang mencetaknya.** `grep` kalimat itu di
   `app/bot_dapodik.py`, baca fungsi yang mencetaknya, pahami mengapa baris itu bisa tercapai —
   **jangan** mulai dari jalur yang paling mudah diperbaiki. (Pelajaran ronde 15t: bot
   diperbaiki di jalur *klik*, padahal log berbunyi *«kotak … tidak ada di halaman ini»* —
   jalur itu tidak pernah dipakai.)
2. **Reproduksi sampai uji GAGAL lebih dulu**, baru perbaiki. Uji tiruan yang hijau **tidak**
   berarti beres di sekolah: sandbox tidak punya Chrome dan tidak bisa membuka Dapodik.
3. **Tunggu, jangan menyimpulkan "tidak ada".** Ext JS merender bertahap; popup pengumuman &
   lapisan `x-mask` menelan klik berikutnya. Bedakan **"tidak ada"** dari **"belum tampil"**.
4. **Bedakan "perintah dikirim" dari "nilai berubah".** Setiap pemilihan/pengisian diverifikasi
   dari keadaan halaman, dan hasilnya dilaporkan jujur — termasuk kata "gagal"/"dilewati".
5. **Jangan andalkan satu XPath**, dan **jangan pernah menuduh kredensial atau selector
   pengguna**. Skrip Selenium milik pengguna yang sudah bekerja = **spesifikasi alur**.
6. **Pastikan versi kode di PC pengguna** sebelum menganalisis: lencana `Kode SM: <revisi>` di
   halaman Bot Dapodik dan baris `[versi]` pada log. Perbaikan juga wajib terlihat di keduanya.

## 2. Daftar periksa sebelum mengklaim "sudah beres"

1. Reproduksi keluhannya (uji baru di `scripts/uji_bot_dapodik.py` + `scripts/peramban_palsu.py`)
   yang **gagal** tanpa perbaikan.
2. Perbaiki **jalur yang benar-benar gagal** (lihat aturan emas 1), jangan menghapus kejujuran
   log demi uji hijau.
3. Jalankan kedua suite: `scripts/uji_bot_dapodik.py` dan `scripts/cek_sistem.py`
   (`--http` bila menyentuh halaman web).
4. Jawab pengguna dengan: sebab yang terbukti (kutipan log/DOM) · apa yang diubah (nama fungsi)
   · bukti uji (jumlah skenario/pemeriksaan) · **satu langkah konkret** untuk pengguna
   (jalankan `run.bat`, periksa `Kode SM: <revisi>`, kirim blok log tertentu).
5. Bila perbaikan sebelumnya meleset, **akui dulu** dan sebutkan alasannya.

## 3. Batas lingkungan kerja

* Tanpa Chrome & tanpa akses Dapodik → uji memakai peramban palsu; setiap kesimpulan tentang
  Dapodik nyata harus punya bukti dari log/DOM pengguna. Karena itu **log bot harus
  mendiagnosis dirinya sendiri** (cetak label, nama kolom, id komponen, ukuran jendela).
* Ruang kerja **bisa ter-reset** (sudah berkali-kali: `.venv`, `data/`, `node_modules` hilang
  dan HEAD kembali ke commit awal). Maka: pekerjaan selalu **ter-push** ke cabang
  `arena/01a0a87a-sm`; uji harus **permanen di `scripts/`** (bukan `/tmp`).
  Pemulihan: `git fetch origin arena/01a0a87a-sm` → `git reset --hard FETCH_HEAD` → buat
  `.venv` + `pip install -r requirements.txt -r requirements-bot.txt` → `npm install jsdom` →
  `scripts/buat_data_contoh.py` → `run.py --init-db` (**wajib**; kalau tidak:
  `no such table: dapodik_jobs`).
* Cabang kerja **hanya** `arena/01a0a87a-sm` (jangan push ke `main`); PR: #1.
* Angka konfigurasi yang tidak boleh dinaikkan hanya demi uji lewat: `bot_timeout=15`,
  `bot_jeda_muat=5`, `MAX_RETRIES=3`, `GULIR_PERIODIK=250`, `GULIR_PERCOBAAN=4`,
  `BUKTI_MAKSIMAL=40`, `UJI_TUNGGU_PERTAMA=4`, `UJI_TUNGGU_LAIN=2`, `SELEKTOR_UJI_DETIK=6`.

## 4. Peta cepat bot Dapodik

* `app/bot_dapodik.py` — seluruh alur bot (login → menu → cari NISN & pilih baris → Data
  Periodik → Registrasi). **Peta gejala → baris log → fungsi ada di `CATATAN-KESALAHAN.md` §3.**
* `scripts/peramban_palsu.py` — Dapodik tiruan (mode-mode keadaan: popup, mask, klik ditelan,
  `keadaan_lewat_kelas`, `siapkan_model_ext_tidak_ikut`, `siapkan_jarak_tanpa_xpath`, …).
* `scripts/uji_bot_dapodik.py` — uji bot permanen (9 skenario / 29 pemeriksaan).
* `scripts/cek_sistem.py` — suite aplikasi (24 blok; `--http` menambah uji halaman).
* `app/templates/bot_dapodik.html` + `app/routers/bot_routes.py` — halaman & pengaturan bot.

## 5. Gaya kerja yang diharapkan pengguna

* Perbaiki sampai terbukti; jangan menjanjikan "beres" bila hanya teruji di tiruan.
* Jangan membangun fitur yang tidak diminta (mis. "saran selector" pernah dibangun lalu harus
  dihapus permanen atas permintaan pengguna).
* Bahasa jawaban: Indonesia, ringkas, dengan bukti yang bisa diperiksa pengguna.
