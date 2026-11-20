# Menjalankan SM online lewat Vercel (gratis) — langkah demi langkah

Vercel dapat menjalankan aplikasi FastAPI seperti SM **gratis** (paket *Hobby*). Panduan ini
menjelaskan caranya, **apa yang bisa** dan **apa yang tidak bisa** dilakukan di sana, supaya
tidak ada kejutan setelah aplikasi online.

> **Penting dibaca lebih dulu.** Vercel menyalakan aplikasi per permintaan (*serverless*):
> tidak ada diska tetap, tidak ada Chrome, dan setiap permintaan dibatasi ±60 detik. Artinya
> di Vercel **data hanya sementara** (hilang begitu aplikasi “tidur” atau dideploy ulang) dan
> **Bot Dapodik tidak bisa dijalankan**. Untuk data sekolah yang sesungguhnya, jalankan SM di
> **PC sekolah** seperti biasa (lihat README §8) dan pakai Vercel untuk pratinjau/demo online.

---

## 1. Apakah benar gratis?

| | Paket **Hobby** (gratis) | Catatan |
| --- | --- | --- |
| Biaya | **Rp0**, tanpa kartu kredit | — |
| Kuota | 100 GB transfer/bulan · 1 juta pemanggilan fungsi · 1 juta permintaan edge · 4 jam CPU · 1 GB Blob | lebih dari cukup untuk satu sekolah |
| Batas waktu fungsi | **60 detik** per permintaan | impor Excel besar bisa kena batas ini |
| Diska | hanya `/tmp`, **tidak permanen** | bukan tempat menyimpan data sekolah |
| Pengguna komersial | **tidak diizinkan** | Hobby = proyek pribadi/non-komersial. Pemakaian internal sekolah tanpa penjualan/iklan umumnya masuk kategori non-komersial; bila sekolah memungut biaya lewat aplikasi ini, pakai Pro atau server sendiri |
| Jam tidur | fungsi berhenti saat tidak ada permintaan | permintaan berikutnya “dingin” beberapa detik |

Jadi: **gratis, cocok untuk pratinjau online & dicoba dari rumah**, bukan untuk dijadikan
tempat data induk sekolah.

## 2. Yang perlu disiapkan

1. Akun Vercel gratis — <https://vercel.com/signup> (bisa masuk dengan akun GitHub).
2. Repo GitHub SM sudah ada: `github.com/Dypoi/SM` (repo ini).
3. Berkas yang sudah tersedia di repo (tidak perlu dibuat lagi):
   * `api/index.py` — titik masuk yang dipakai Vercel,
   * `vercel.json` — pengaturan fungsi & pengalihan alamat,
   * `.python-version` — memakai Python 3.12,
   * `.vercelignore` — memastikan `data/`, `sample-data/`, berkas `.xlsx`, dan alat pemasang
     **tidak ikut** terunggah.

## 3. Cara A — lewat situs Vercel (paling mudah, tanpa memasang apa pun)

1. Buka <https://vercel.com/new>.
2. **Import Git Repository** → pilih **Dypoi/SM** → **Import**.
   * Bila repo belum muncul, tekan *Adjust GitHub App Permissions* lalu beri akses ke repo SM.
   * Cabang yang dipakai boleh `main` (setelah PR #1 digabung) atau
     `arena/01a0a87a-sm` — pilih pada kotak **Branch**.
3. Pada halaman pengaturan proyek:
   * **Framework Preset**: biarkan **Other** (Vercel mengenali FastAPI dari `api/index.py`).
   * **Root Directory**: biarkan kosong (akar repo).
   * **Build & Output Settings**: biarkan bawaan.
   * Buka **Environment Variables** dan isi minimal dua ini (lihat tabel di bagian 5):
     `SM_SECRET_KEY` dan `SM_ADMIN_PASSWORD`.
4. Tekan **Deploy** dan tunggu 1–2 menit.
5. Selesai: alamat aplikasi muncul, mis. `https://sm-sekolah.vercel.app`.
   Buka alamat itu → login petugas `admin` / kata sandi yang Anda isi.
6. Setiap kali Anda `git push` ke cabang yang dideploy, Vercel otomatis mendeploy ulang.

## 4. Cara B — lewat terminal (Vercel CLI)

```bash
npm i -g vercel        # sekali saja (butuh Node.js)
cd SM
vercel login
vercel                 # deploy pratinjau
vercel --prod          # deploy ke alamat utama
```

Saat pertama kali dijalankan, Vercel menanyakan beberapa hal: pilih **Link to existing
project? No**, **Project name** (mis. `sm-sekolah`), **Directory** (`./`),
**Modify settings? No**. Variabel lingkungan bisa ditambah dengan:

```bash
vercel env add SM_SECRET_KEY production
vercel env add SM_ADMIN_PASSWORD production
vercel --prod          # deploy ulang supaya variabelnya terpakai
```

## 5. Environment variable yang sebaiknya diisi

| Nama | Guna | Contoh |
| --- | --- | --- |
| `SM_SECRET_KEY` | kunci penandatangan cookie sesi. **Wajib diisi di Vercel**: tanpa ini kunci dibuat per instans sehingga login bisa terputus-putus | teks acak panjang (40+ karakter) |
| `SM_ADMIN_PASSWORD` | kata sandi admin yang bukan bawaan | `GantiSegera123!` |
| `SM_ADMIN_USER` | nama pengguna admin (opsional) | `admin` |
| `SM_DATA_DIR` | folder data. Di Vercel otomatis `/tmp/sm-data` (mode Vercel); isi hanya bila ingin menaruhnya di tempat lain di `/tmp` | `/tmp/sm-data` |
| `SM_GIT_UPDATE` | biarkan `0` di Vercel (menu Pembaruan tidak berguna di serverless) | `0` |
| `SM_AUTO_SEED` | `0` = aplikasi mulai kosong | `0` |
| `SM_ROWS_PER_PAGE` | jumlah baris per halaman (opsional) | `25` |

Daftar lengkap ada di README §7.

## 6. Setelah aplikasi online — apa yang bisa dilakukan

| Bisa | Tidak bisa (dan jalan keluarnya) |
| --- | --- |
| Membuka semua halaman, login petugas & siswa | **Bot Dapodik** — butuh Chrome & proses panjang; jalankan di PC sekolah. Aplikasi memberi tahu ini di halaman Bot Dapodik |
| Mengimpor Excel/CSV dari komputer sendiri (unggahan ke `/tmp`) | **Menyimpan data permanen** — data hilang saat fungsi tidur/deploy ulang |
| Mencoba fitur, melatih guru/petugas, demo ke dinas | **Pembaruan lewat menu «Pembaruan»** (tanpa git di serverless) — pakai `git push` ke repo |
| Berbagi tautan ke guru untuk melihat tampilan | **Impor berkas besar** yang makan lebih dari 60 detik |

**Cara pakai yang disarankan:** jadikan Vercel sebagai *ruang latihan/demo*. Kalau ingin data
siswa benar-benar terbaca online, gunakan **PC sekolah + Tailscale Funnel** (README §8,
gratis, data tetap di PC sekolah) atau pindahkan data lewat **Ekspor/Impor** bila berganti
tempat.

## 7. Bila ada masalah

| Gejala | Sebab & jalan keluar |
| --- | --- |
| Halaman 404 di alamat utama | Titik masuk belum terbaca. Pastikan `api/index.py`, `vercel.json`, dan `requirements.txt` ada di akar repo, lalu **Redeploy**. |
| `500 Internal Server Error` | Buka **Deployments → Functions → Logs** di dasbor Vercel. Umumnya berkaitan dengan variabel lingkungan yang belum diisi (`SM_SECRET_KEY`). |
| Login berhasil lalu terlempar kembali ke halaman masuk | `SM_SECRET_KEY` belum diisi sehingga tiap instans memakai kunci berbeda — isi variabel itu lalu deploy ulang. |
| Data hilang setelah beberapa menit | Memang sifat serverless (lihat §6). Untuk data sungguhan jalankan SM di PC sekolah. |
| `Unable to find any supported Python versions` | Berkas `.python-version` terhapus/berubah — kembalikan ke `3.12`, lalu deploy ulang. |
| `FUNCTION_INVOCATION_TIMEOUT` saat impor Excel | Impor berkas lebih kecil, atau jalankan impor di PC sekolah. |
| Halaman Bot Dapodik berkata tidak bisa dijalankan | Benar: di Vercel tidak ada Chrome. Jalankan bot di PC sekolah. |
| Perubahan kode tidak muncul | Pastikan push ke **cabang** yang dideploy; lihat **Deployments** di dasbor dan lakukan *Redeploy* bila perlu. |

## 8. Ringkasan berkas yang dipakai Vercel

```
repo SM
├── api/index.py        # titik masuk: `from app.main import app`
├── vercel.json         # fungsi (memori, batas waktu) + pengalihan semua alamat ke fungsi
├── .python-version     # 3.12
├── .vercelignore       # jangan unggah data/ · sample-data/ · *.xlsx · pemasang/ · scripts/
├── requirements.txt    # pustaka yang dipasang Vercel
└── app/                # seluruh isi aplikasi SM (tidak berubah)
```

Pemeriksaannya otomatis: `python scripts/cek_sistem.py` (blok 28) memastikan berkas di atas
lengkap, `vercel.json` sah, dan mode Vercel benar-benar bekerja (folder data pindah ke `/tmp`,
pembaruan git mati, bot menolak jalan dengan penjelasan).
