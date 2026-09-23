# Catatan kegagalan & kesalahpahaman — bot Dapodik

> **Berkas ini ditulis untuk dibaca ulang sebelum mengubah bot Dapodik** (oleh agen/AI yang
> melanjutkan pekerjaan ini, atau oleh siapa pun). Isinya bukan daftar `commit`, melainkan
> **cara berpikir yang salah** yang sudah pernah membuat perbaikan meleset — supaya tidak
> diulang.
>
> Ringkasan satu kalimat: **hampir semua kegagalan terjadi karena sebabnya saya simpulkan
> dari teori/kode, bukan dari bukti yang ada di log & DOM yang dikirim pengguna.**

Berkas pendamping: **`AGENTS.md`** (aturan kerja repo yang dibaca otomatis oleh agen/AI —
versi ringkas dari catatan ini), `README.md` (dokumentasi fitur), `scripts/uji_bot_dapodik.py`
(uji bot permanen), `scripts/peramban_palsu.py` (Dapodik tiruan), `scripts/cek_sistem.py`
(suite).

---

## 0a. Aturan emas (baca ini dulu bila sedang buru-buru)

1. **Cocokkan kalimat log pengguna ke baris kode yang mencetaknya** (`grep` kalimat itu di
   `app/bot_dapodik.py`) — jangan mulai dari jalur yang paling mudah diperbaiki.
2. **Reproduksi sampai uji GAGAL lebih dulu**, baru perbaiki; uji hijau **tidak** berarti
   beres di sekolah (uji tiruan ≠ Dapodik).
3. **Tunggu, jangan menyimpulkan "tidak ada"**: Ext JS merender bertahap; popup/mask menelan
   klik berikutnya.
4. **Bedakan "perintah dikirim" dari "nilai berubah"** — selalu verifikasi keadaan halaman dan
   laporkan jujur.
5. **Jangan andalkan satu XPath** dan jangan tuduh kredensial/selector pengguna; skrip
   Selenium yang bekerja = spesifikasi alur.
6. **Pastikan versi kode di PC pengguna** (`Kode SM: …` / `[versi]`) sebelum menganalisis.
7. **Kolom dropdown Dapodik jangan bergantung pada `Ext`**: buka dengan **tombol ↓** pada
   kolomnya, baca daftarnya dari **DOM** (`aria-owns="…-inputEl …-picker-listEl"`), dan
   **gulir daftarnya dari atas sampai bawah** sebelum menyimpulkan sebuah pilihan tidak ada.

---

## 0. Cara memakai catatan ini

1. Nomor 1–10 di bawah adalah kesalahpahaman yang **sudah pernah terjadi**. Baca dulu
   nomor yang gejalanya mirip dengan keluhan yang sedang masuk.
2. Pakai **Daftar periksa** (§2) sebelum mengklaim apa pun "sudah beres".
3. Pakai **Peta gejala → baris log → tempat di kode** (§3) untuk menemukan jalur kode yang
   benar-benar gagal — jangan mulai dari jalur yang paling mudah diperbaiki.
4. Aturan menjawab pengguna ada di §4; batas kemampuan lingkungan kerja ada di §5.

---

## 1. Kesalahpahaman yang sudah pernah terjadi (jangan diulang)

### 1. "Login tidak ditemukan" padahal kredensial benar (ronde 15d–15e)

| | |
|---|---|
| **Gejala asli** | Log sekolah: kolom nama pengguna/kata sandi "tidak ditemukan". |
| **Yang saya pikirkan** | Selector atau kredensialnya yang salah → saya malah menyarankan memperbaiki selector. |
| **Yang sebenarnya** | Dapodik memakai Ext JS: formulir login muncul **beberapa detik sesudah** halaman selesai dimuat. Kolomnya memang belum ada saat bot mencari. |
| **Aturan** | Selalu **tunggu unsur bermunculan** sebelum menyimpulkan "tidak ada". **Jangan pernah** menuduh kredensial/selector pengguna; laporkan keadaan sebenarnya (berapa kolom yang ketemu, judul halaman, isi yang terlihat). |

### 2. Membangun fitur yang tidak diminta: "saran selector" (ronde 15f)

| | |
|---|---|
| **Gejala asli** | Pengguna: *"tidak perlu ada saran, hapus saja itu"* dan *"gunakan code bot dapodik saya … diadopsi"*. |
| **Yang saya pikirkan** | Pengguna butuh bantuan mencari selector baru → saya bangun mekanisme saran otomatis. |
| **Yang sebenarnya** | Pengguna **sudah punya skrip Selenium yang bekerja**; yang diminta adalah bot mengikuti alur skrip itu apa adanya. |
| **Aturan** | Kerjakan yang diminta; jangan menambah mekanisme baru. **Skrip pengguna yang bekerja = spesifikasi**, bukan bahan saran. Fitur saran selector sudah dihapus permanen — jangan dihidupkan lagi. |

### 3. Menganalisis tanpa mereproduksi (ronde 15g)

| | |
|---|---|
| **Gejala asli** | Pengguna: *"audit forensik, apakah anda sudah mencobanya sendiri? liat coba error nya dimana"*. |
| **Yang saya pikirkan** | Cukup membaca kode dan menebak penyebabnya. |
| **Yang sebenarnya** | Harus **dijalankan ulang** sampai galatnya muncul, baru diperbaiki. |
| **Aturan** | Reproduksi dulu (di peramban palsu bila tanpa Chrome). Bila tidak bisa direproduksi, katakan terus terang dan buat uji yang mereproduksinya sebelum mengubah kode. |

### 4. Mengabaikan popup modal (ronde 15h)

| | |
|---|---|
| **Gejala asli** | Langkah setelah menu gagal beruntun; klik tombol tidak berpengaruh. |
| **Yang saya pikirkan** | Popup pengumuman tidak penting. |
| **Yang sebenarnya** | Popup *«Selamat Datang di Aplikasi Dapodik 2027.b»* beserta lapisan modalnya **menutupi halaman**, sehingga klik berikutnya ditelan (`ElementClickInterceptedException`) dan langkah-langkah sesudahnya ikut gagal. |
| **Aturan** | Periksa popup/lapisan modal lebih dulu pada setiap kegagalan "berantai"; tunggu sampai benar-benar hilang, dan tulis di log. |

### 5. Menganggap klik skrip bisa memilih baris tabel (ronde 15i–15j)

| | |
|---|---|
| **Gejala asli** | Tombol Registrasi tidak membuka apa pun. |
| **Yang saya pikirkan** | `arguments[0].click()` cukup untuk memilih baris siswa. |
| **Yang sebenarnya** | Ext JS memilih baris pada **mousedown**; klik lewat skrip hanya mengirim event `click` → baris tidak terpilih → Registrasi memang tidak terbuka. |
| **Aturan** | Tiru cara nyata (klik sungguhan / urutan `mousedown → mouseup → click`) dan **verifikasi** baris benar-benar terpilih sebelum melanjutkan. |

### 6. Menggulir halaman padahal panelnya punya area gulir sendiri (ronde 15o)

| | |
|---|---|
| **Gejala asli** | Pengguna: *"kalo scrool apakah akan ke scroll semua?"*; kolom Data Periodik tidak terjangkau. |
| **Yang saya pikirkan** | `window.scrollBy(0, 250)` sudah cukup. |
| **Yang sebenarnya** | Panel *«Data Periodik Peserta Didik»* berada di dalam wadah bergulir sendiri; menggulir halaman tidak menjangkaunya dan malah menggeser bagian lain. |
| **Aturan** | Bawa unsur ke layar dengan `scrollIntoView` **lalu** betulkan `scrollTop` setiap induk yang memang punya gulir — dan uji bahwa hanya panelnya yang bergeser. |

### 7. Menganggap "perintah berhasil" = "nilai berubah" (ronde 15p–15q)

| | |
|---|---|
| **Gejala asli** | Radio «lebih dari 1 km» seolah diklik, tetapi Dapodik tetap menonaktifkan kolom kilometer. |
| **Yang saya pikirkan** | Klik pada kotak radio = terpilih. |
| **Yang sebenarnya** | Dapodik menerima pemilihan lewat **label** `x-form-cb-label`; dan sesudah mengetik, Ext JS perlu peristiwa `input → change → blur`. Perintah "berhasil" tidak berarti nilainya berubah. |
| **Aturan** | Setiap pemilihan/pengisian **diverifikasi dari keadaan halaman**, dan hasilnya dilaporkan jujur (`… belum menandainya terpilih`) — bukan mengaku berhasil. |

### 8. Lupa memastikan versi kode di PC pengguna (ronde 15q)

| | |
|---|---|
| **Gejala asli** | Pengguna: *"PC masih kode lama"* — log tidak memuat penanda perbaikan terbaru. |
| **Yang saya pikirkan** | Perbaikan sudah jalan; mengapa masih gagal? |
| **Yang sebenarnya** | PC menjalankan kode lama, jadi seluruh analisis atas log itu tidak ada gunanya. |
| **Aturan** | Setiap perbaikan wajib terlihat versinya: baris `[versi] kode SM yang berjalan: …` pada log **dan** lencana `Kode SM: …` di halaman Bot Dapodik. Sebelum menganalisis kegagalan, minta versi itu diperiksa lebih dulu. |

### 9. Memperbaiki jalur yang salah — kesalahpahaman ronde 15s → 15t

| | |
|---|---|
| **Gejala asli (15t)** | Setelah perbaikan penanda `x-form-cb-checked`, pengguna mengirim DOM yang sama + log baru. Log memuat: `[periodik] kotak «Jarak rumah ke sekolah» tidak ada di halaman ini`. |
| **Yang saya pikirkan (15s)** | Masalahnya `input.checked`: DOM berubah tetapi model Ext JS tidak — maka saya menambah `_keadaan_pilihan`/`_terpilih_grup` + eskalasi `Ext.getCmp`. |
| **Yang saya pikirkan (15t)** | "Sudah beres" — karena uji saya hijau. |
| **Yang sebenarnya** | Kotaknya **tidak pernah ketemu**: XPath absolut Dapodik (`…/td/div[2]/…/span/input`) meleset, sehingga pemeriksaan penanda tidak pernah dipakai sama sekali. Uji hijau saya hanya membuktikan peramban palsu saya konsisten — bukan bahwa Dapodik sekolah akan berperilaku sama. |
| **Aturan** | **Cocokkan kalimat log pengguna satu per satu ke baris kode yang mencetaknya** (`grep` kalimat itu di `app/bot_dapodik.py`) sebelum menyimpulkan apa pun. Perbaikan hanya sah bila menyentuh jalur yang benar-benar gagal. "Hijau di uji" ≠ "beres di sekolah". |

### 10. Terlalu bergantung tata letak, dan menganggap "belum tampil" = "tidak ada" (ronde 15u)

| | |
|---|---|
| **Gejala asli** | Sama seperti nomor 9: `kotak … tidak ada di halaman ini`. |
| **Yang saya pikirkan** | Kalau selector tidak ketemu, berarti pilihannya tidak ada di halaman. |
| **Yang sebenarnya** | (a) XPath menyalin tata letak versi Dapodik tertentu dan bisa meleset; (b) Ext JS menggambar baris Data Periodik **bertahap**, sedangkan empat percobaan gulir lama selesai dalam sekejap tanpa jeda; (c) `is_displayed()` saya jadikan syarat mutlak, sehingga kotak yang **ada tetapi belum terlihat** dianggap tidak ada. |
| **Aturan** | Jangan bergantung XPath: lacak pilihan lewat **teksnya** dan JavaScript (label → kotaknya), atau lewat API Ext JS. Buang kandidat yang jelas bertuliskan pilihan lain (jangan sampai memilih yang salah). Beri jeda kecil antar percobaan. Bedakan **"tidak ada"** dari **"belum tampil/terlihat"**, dan pastikan log menyebutkan apa yang benar-benar terlihat di panel. |

### 11. Menganggap satu tombol «Ubah»/«Simpan» = milik jendela yang benar (ronde 15x)

| | |
|---|---|
| **Gejala asli** | Pengguna: *"masih bekerja belum baik terkait ubah … yang pasti itu tampilan setelah klik ubah"* + tangkapan layar. |
| **Yang saya pikirkan** | Tombol «Ubah» yang kelasnya ungu itu satu-satunya; setelah ditekan, jendela «Ubah» pasti terbuka. |
| **Yang sebenarnya** | Tangkapan layar menunjukkan **dua set tombol**: toolbar halaman *dan* panel «Data Rincian PD» di bawahnya (Tambah / **Ubah** ungu / **Simpan** / Hapus / Validasi). Menekan «Ubah»/«Simpan» milik panel itu tidak membuka/menyimpan jendela «Edit Peserta Didik» — persis keluhan "jendela tetap terbuka". Selain itu **jendela «Ubah» punya area gulirnya sendiri**: menggulir halaman (`scrollBy(0,250)`) tidak menolong, dan juga bukan soal "250 px kebanyakan/kurang" — yang benar adalah menggeser isi jendela lalu **mencari kolomnya lagi setiap kali**. |
| **Aturan** | Jangan percaya satu selector untuk tombol yang bisa muncul berkali-kali: **coba tiap kandidat dan VERIFIKASI hasilnya** (mis. jendela «Edit Peserta Didik» benar-benar terbuka). Batasi pencarian kolom & tombol simpan pada **wadah jendelanya** (`.x-window`), bukan seluruh halaman. Untuk area ber-gulir: geser **isi wadah itu** sedikit demi sedikit sambil mencari ulang — jangan mengandalkan gulir halaman dengan angka tetap. |
| **Tambahan (ronde 15y)** | "250 px kebanyakan atau kurang banyak" **bukan** pertanyaan yang benar: yang menentukan adalah **posisi** gulir wadah. Jadi: kembalikan isi wadah ke atas dulu (skrip sekolah mengisi dari atas ke bawah), geser 250 px, **cari ulang setiap kali**, berhenti hanya bila isinya sudah mentok. Selain itu: menulis `input.value` lewat JavaScript **tidak** mengubah model Ext JS — bila ketikan/JS ditolak, nilainya harus disetel lewat `Ext.getCmp(<data-componentid>).setValue(...)` dan **diperiksa ulang**. |

### 12. Membalas keluhan yang sama dengan jawaban yang sama (ronde 15y → 15z)

| | |
|---|---|
| **Gejala asli** | Pengguna mengirim **pesan yang sama tiga kali**: *"masih bekerja belum baik terkait ubah, mungkin karena scroll 250 kebanyakan atau kurang banyak saya ga tau si…"* — tanpa log, tanpa DOM baru. |
| **Yang saya pikirkan** | Setelah 15x (dua set tombol) & 15y (posisi gulir) saya merasa penyebabnya sudah ketemu, lalu jawabannya diulang dengan kata lain. |
| **Yang sebenarnya** | Jawaban yang diulang **tidak menambah informasi apa pun**. Yang dibutuhkan pengguna adalah bukti dari sisi bot: jendela «Ubah» itu terbaca seperti apa, kolomnya ketemu atau tidak, wadah gulirnya yang mana. Dan karena log belum pernah dikirim, bot harus **melaporkan keadaannya sendiri** — bukan menunggu pengguna memotret layar. |
| **Aturan** | (a) Jangan mengulang jawaban yang sama; bila penyebab belum pasti, ubah **cara kerja bot** agar ia melaporkan keadaannya sendiri (`[bio-rincian]`, bukti `.png`/`.html` di `data/bot/`). (b) Selalu sediakan **jalur cadangan yang tidak bergantung pada pembacaan struktur baru**: skrip sekolah memakai `find_element(By.NAME, …)` tanpa mempedulikan jendelanya — jalur itu harus ada, lengkap dengan **gulir 250 px + cari ulang** setiap langkah. (c) Menambah jalur cadangan **tidak boleh** menghilangkan kejujuran log: kolom yang tetap tidak ketemu harus tetap dicatat sebagai dilewati. |

### 13. Menganggap semua kolom jendela «Ubah» = kolom teks (ronde 16)

| | |
|---|---|
| **Gejala asli** | Pengguna mengirim tangkapan layar: kolom **«Pendidikan ayah»** sedang terbuka daftarnya (D1, D2, D3, D4, Informal, Lainnya, Non formal, Paket A…), lalu bertanya *"bot bisa mengatasi ini ga? dropdown dropdown ini"*. |
| **Yang saya pikirkan (15w–15z)** | Keempat belas kolom skrip sekolah diisi dengan **Ctrl+A → ketik** — asumsi saya semuanya kolom teks. |
| **Yang sebenarnya** | Kolom **Pendidikan/Pekerjaan/Penghasilan ayah-ibu** adalah **dropdown (combo Ext JS)**. Mengetikkan teksnya hanya mengubah **tulisan di layar**; **nilai model Ext JS**-nya tetap kosong bila teksnya tidak persis salah satu pilihan daftar — jadi tidak tersimpan, kolom wajib (bertanda bintang merah) tetap kosong, dan penyimpanan bisa ikut ditolak. Daftar Dapodik juga **tidak sama** dengan daftar aplikasi SM: «SMA / sederajat» bisa bernama «SMA» atau «SLTA» di sana. |
| **Aturan** | Sebelum mengisi, **kenali jenis kolomnya** (``role="combobox"``, tombol panah ``.x-form-trigger``, readonly, atau xtype combobox). Untuk dropdown: baca pilihannya dari **data komponen Ext JS** (``store``: ``displayField`` → teks, ``valueField`` → nilai), cocokkan (persis → dirapikan → nama lain → satu-satunya yang sepadan), lalu pilih — klik pilihannya bila daftarnya terbuka, atau ``select(record)``/``setValue(<valueField>)`` lewat model Ext JS. Hasilnya diperiksa dari **``getRawValue()``** (teks), bukan ``getValue()`` — pada combo Dapodik ``getValue()`` berisi **id** angka. Pilihan yang tidak ada di daftar **jangan ditebak**: sebutkan pilihan yang benar-benar terlihat dan lewati dengan jujur. **Daftar harus dibaca dari kolom itu sendiri** — pernah terjadi: daftar «Pekerjaan» dipakai untuk mencocokkan nilai «Penghasilan». |
| **Tambahan (ronde 18 — perilaku picker)** | "Masih gagal" berikutnya bukan soal cara memilih, melainkan **perilaku daftar dropdownnya**: (a) **datanya muncul setelah ditunggu** — daftar Ext JS tidak langsung berisi, jadi membaca sekali lalu menyimpulkan "kosong" itu salah; (b) **daftarnya punya area gulir sendiri** — pilihan di bawah tidak terlihat, dan yang tidak terlihat **tidak bisa diklik**; bot harus menggeser isi daftarnya (150 px sekali geser) lalu mencari ulang tiap langkah. Karena itu `_pilihan_dropdown` hanya mengembalikan pilihan yang **benar-benar terlihat** (bukan seluruh isi `store`), dan pemilihannya berurutan: klik dropdownnya → tunggu → gulir → klik. Jangan pernah mengklik pilihan yang belum terlihat, dan jangan melaporkan "sudah digulir/diklik" kalau langkahnya tidak pernah terjadi. |
### 20. Peringatan memenuhi halaman, tombol «+ Siswa» yang tak mungkin dipakai, ikon terbalik & menggantung (ronde 34)

| | |
|---|---|
| **Gejala asli** | Sekolah: *«notif seperti „Aplikasi sedang dapat dibuka dari internet" hapus dan pindahkan ke samping button berkas sebagai icon notifikasi»*, *«button +siswa hapus saja karena sistem ini tidak bisa +siswa secara manual»*, dan *«ketika login sebagai siswa masih banyak icon yang tidak pada tempatnya»*. |
| **Yang saya pikirkan** | Spanduk kuning itu penting untuk keamanan, jadi harus selalu terlihat; tombol «+ Siswa» warisan template admin biasa. |
| **Yang sebenarnya** | (a) Peringatan keamanan **tidak harus memakan ruang konten** — cukup ikon dengan tanda, karena yang perlu bertindak hanya petugas/pemilik. (b) Tombol «+ Siswa» menawarkan hal yang **tidak pernah** terjadi di sistem ini (data hanya dari impor Dapodik) → menu yang menyesatkan. (c) Ikon: di kartu kegiatan siswa kotak ikon 46 px **menggantung di pojok** kartu yang tinggi, ikon di kartu peran halaman masuk menempel di **atas** baris teksnya, dan tombol **Masuk memakai ikon keluar** (`logout`) — jelas terbalik maksudnya. |
| **Aturan** | (a) Peringatan yang tidak perlu dibaca setiap saat → **ikon lonceng** di bilah atas (angka jumlah, popup saat diklik) — bukan spanduk di dalam konten; hanya muncul bila keadaannya memang berlaku. (b) **Jangan menyediakan tombol untuk alur yang tidak ada** (tambah siswa manual). (c) Ikon yang menempel pada judul/teks harus berada dalam **satu baris flex dengan teksnya** (`align-items: center`) atau dipusatkan pada blok teksnya — jangan `flex-start` untuk kotak ikon besar. (d) Nama ikon harus **sesuai artinya**: `login` untuk tombol Masuk, `logout` untuk Keluar. |
| **Pelajaran uji** | Semua ini bisa diperiksa dari berkas: `cek_sistem` blok 30 memastikan spanduk lama tidak ada lagi, bilah atas memuat lonceng, tombol «+ Siswa» hilang dari bilah atas & halaman Data Siswa, tombol Masuk memakai ikon `login`, dan kartu kegiatan memakai baris kepala (ikon + judul). Ikon baru (`bell`, `login`) otomatis masuk pemeriksaan geometri `scripts/cek_ikon.py`. |

### 19. Ikon «tidak pas» & kartu jumlah di bawah tabel (ronde 33)

| | |
|---|---|
| **Gejala asli** | Sekolah: *«icon-nya seperti tidak pas gitu loh, coba cek setiap yang mengandung icon apakah sudah pas»* dan *«di halaman data siswa kenapa jumlah laki-laki ada di bawah, harusnya di atas»*. |
| **Yang saya pikirkan** | Ikon sudah memakai satu makro, jadi pasti seragam; kartu ringkasan di bawah tabel hanya soal selera. |
| **Yang sebenarnya** | (a) Setiap ikon digambar **satu per satu secara manual** di kanvas 24×24 tanpa aturan bersama: `flag` pusatnya di x=10,5 (miring ke kiri), `warning` melewati tepi (1,8–22,2), `cog` menyentuh tepi (1–23), banyak ikon lain jauh lebih kecil (plus 14, menu 16×10) sehingga bobotnya tidak sama. (b) **Tiga nama ikon yang dipakai template tidak ada di makro** — `folder`, `history`, dan `x` — sehingga yang muncul di halaman adalah **lingkaran polos** (cadangan), bukan ikonnya. (c) Ikon yang menempel pada teks (mis. di `<h3>` atau `<summary>`) memakai perataan bawaan browser (garis dasar teks) sehingga tampak **naik** beberapa piksel. (d) Kartu jumlah memang di bawah tabel: `students/list.html` menaruh blok `grid grid-4` **setelah** tabel. |
| **Aturan** | (a) Semua ikon garis: pusat **(12, 12)**, gambar di dalam **kotak aman 2–22**, sisi terpanjang **≥ 14**; nama ikon yang dipakai template **wajib ada** di makro (kalau tidak, muncul penanda `icon-kosong`). (b) Ikon yang menempel pada teks diberi `vertical-align` pada aturan dasar `.icon`, dan setiap aturan ukuran ikon di CSS harus **persegi** (lebar = tinggi) supaya gambarnya tidak gepeng. (c) Angka penting diletakkan **di atas** daftar: kartu jumlah siswa (laki-laki/perempuan/KIP/PIP) berada di atas tabel. (d) Periksa dengan alat, bukan perasaan: `scripts/cek_ikon.py` mengukur tiap ikon, dan `cek_sistem` blok 29 menjalankannya + menolak halaman yang memuat ikon tak dikenal. |
| **Pelajaran uji** | «Sudah satu makro» **bukan** jaminan seragam. Yang rapi itu isi makronya, bukan cangkangnya. Selain itu, nama ikon yang salah tidak memunculkan galat apa pun — perlu penanda (`icon-kosong`) + pemeriksaan halaman agar ketahuan. |

### 18. Tampilan «rame» karena tata cara ditulis memenuhi halaman (ronde 32)

| | |
|---|---|
| **Gejala asli** | Sekolah: *«banyak orang bilang designnya rame banget, kenapa ga dibikin simple aja»* + permintaan: *«tidak perlu banyak notif/tata cara yang tidak penting — biar ada tanda `!`, kalau diklik muncul popup kecil»*. |
| **Yang saya pikirkan** | Menambahkan kalimat penjelas di setiap kartu = membantu; sapaan + daftar langkah + kotak bantuan = ramah untuk anak. |
| **Yang sebenarnya** | Justru **tulisan itulah keramaiannya**: satu halaman berisi 4–6 blok teks penjelas yang harus dibaca sebelum anak menemukan tombolnya. Yang dibutuhkan guru/sekolah: halaman yang tenang, dan penjelasan tersedia **saat diminta** (diklik), bukan tampil terus. |
| **Aturan** | (a) Tata cara/syarat → **tombol `!`** yang membuka **popup singkat** (`petunjuk()` di `_macros.html`, gaya `.pl-info*` di `portal.css`, pembuka + penutup (klik luar/Esc) di `app.js`); satu popup terbuka sekaligus. (b) Setiap halaman siswa maksimal **satu baris penjelas** di luar popup; kalimat penjelas panjang (`pl-card-ket` > ~90 karakter), kotak bantuan, dan daftar langkah **dihapus** dari badan halaman. (c) Bagian yang jarang dibuka (berkas, riwayat) **dilipat** dengan `<details>`. (d) Halaman petugas tidak diubah. |
| **Pelajaran uji** | Saat sebuah label UI diubah (mis. «Riwayat Pendaftaran» → «Riwayat pendaftaran»), **uji yang menuntut teks itu ikut diperbarui** — dan bila blok kini hanya muncul saat ada data, periksa **setelah** datanya ada (ujian harus mengikuti perilaku baru, bukan sebaliknya). |

### 17. «Dataku» berbentuk tabel lembar kerja (ronde 28 → 31)

| | |
|---|---|
| **Gejala asli** | Sekolah mengirim **tangkapan layar** halaman *Dataku* dan menulis: «bagian jelek». Terlihat satu tabel raksasa: kepala kolom **KOLOM / ISI DATA**, puluhan baris berderet, nilai sejajar kiri dengan banyak ruang kosong di kanan, jenis kelamin tertulis **«L»**, dan NIK/KK berderet angka. |
| **Yang saya pikirkan** | Halaman siswa sudah dipindah ke kerangka ruang siswa (ronde 28), jadi tampilannya sudah «ramah anak». |
| **Yang sebenarnya** | Kerangkanya sudah baru, tetapi **isi halaman Dataku belum disentuh**: masih `<table class="data">` seperti halaman petugas. Tabel dua kolom memang tepat untuk petugas yang membandingkan banyak baris, tetapi untuk anak kelas 7 ia terbaca seperti berkas Excel dan terasa menakutkan. |
| **Aturan** | Untuk halaman **siswa**, data perorangan disajikan sebagai **kartu per kelompok** (judul + ikon + satu kalimat penjelas) dan setiap baris berbentuk «nama data — isi» (label kiri, nilai kanan) — bukan tabel dengan kepala kolom. Tambahkan **pencarian** (anak tidak perlu menggulir 50 baris), tombol **Cetak / simpan PDF**, dan penanda **«Belum diisi»**. Nilai yang berupa **kode** boleh diterjemahkan maknanya (L → Laki-laki, 1 → Ya) tetapi **isi data tidak boleh diubah** (nama tetap apa adanya, angka tetap angka). Label boleh dirapikan untuk anak (`Nama Lengkap` → `Nama lengkap`) dengan **akronim dipertahankan** (NISN, NIK, KK, RT/RW, KM) — lihat `rapikan_label()` di `app/web.py`. Tabel padat TETAP dipakai di halaman petugas. |

### 16. Halaman siswa memakai tampilan petugas (ronde 28)

| | |
|---|---|
| **Gejala asli** | Komplain dari sekolah: *«tampilan seperti ini cocok untuk anak-anak kelas 7 SMP?»* |
| **Yang saya pikirkan** | Portal siswa sudah punya beranda sendiri, kartu sambutan «Halo, …!», dan bahasa Indonesia — dianggap sudah memadai. |
| **Yang sebenarnya** | Yang dilihat anak kelas 7 (12–13 tahun, umumnya dari **HP**) adalah kerangka aplikasi kantor: **sidebar menu petugas** (Impor, Bot Dapodik, Pengaturan, Pembaruan), huruf dasar 14,5 px, tabel padat, tombol kecil, istilah teknis («Data ini berasal dari berkas Dapodik», «Ajukan Perubahan Data», status «—»). Untuk petugas itu memang tepat — memuat banyak data sekaligus. Untuk anak, itu berat dibaca dan **menakutkan**: tidak jelas apa yang harus dilakukan, dan ada menu yang bukan haknya. |
| **Tambahan (ronde 29)** | Halaman **masuk** juga halaman pertama yang dilihat anak, jadi ikut dibenahi: tab peran dibuat besar (min. 66 px) dengan keterangan «Siswa — cukup NISN, tanpa sandi», panel siswa diberi sapaan **«Halo, teman!»**, daftar **langkah 1-2-3**, isian NISN 58 px (huruf 1,4 rem, angka berjarak), tombol masuk 60 px, dan kotak bantuan warna hangat. Tampilan tab petugas **tidak diubah** (hanya tombolnya ikut membesar supaya enak disentuh). Pada layar HP, blok penjelasan di sisi kiri dipersingkat supaya isian langsung terlihat. |
| **Tambahan (ronde 30)** | Komplain yang sama datang **tiga kali**. Sebelum menjawab ulang, periksa dulu kemungkinan paling sepele: **PC sekolah masih menjalankan kode lama**. Hasil pemasangan `bodap.exe` tidak menarik kode sendiri — tampilan baru hanya muncul setelah pemasangan **diperbarui** (jalankan `bodap.exe` terbaru ke folder yang sama, atau `python pemasang/pasang.py perbarui`; folder `data` tidak tersentuh). Karena itu disediakan `scripts/bandingkan_tampilan.py`: template **lama** diambil apa adanya dari riwayat Git (`git archive <revisi> app/templates`) lalu dirender dengan data siswa yang sama, sehingga menjadi bukti «lama ⇄ sekarang» yang bisa dinilai siapa pun. Pelajaran umum: bila pengguna mengulang keluhan yang sama, **jangan mengulang jawaban yang sama** — cari kemungkinan baru (versi kode yang dipakai, tampilan yang benar-benar dilihat) dan sediakan buktinya. |
| **Aturan** | **Pisahkan kerangka halaman menurut pemakainya.** Halaman siswa memakai `portal/_base.html` + `portal.css` (menu bawah seperti aplikasi HP, huruf 16,5–17 px, tombol ≥ 44 px, kalimat sederhana, kartu «Yang perlu kamu lakukan»), dan **tidak memuat satu pun menu petugas**. Kosong ditulis **«Belum diisi»** (bukan «—»), pengajuan disebut **«Minta perbaikan data»**, ekskul disebut **«Kegiatan / klub»**. Data tetap ditampilkan **apa adanya** (isi berkas sekolah) — yang diubah hanya cara menyajikannya. Halaman petugas **tidak diubah**: tabel padat memang yang dibutuhkan di sana. Bukti untuk sekolah: `scripts/pratinjau_tampilan.py` menyalin halaman siswa jadi HTML mandiri (folder `pratinjau/`, diabaikan Git karena berisi data siswa). |

### 15. «Perintah tailscale timed out» — padahal Tailscale sedang menunggu izin (ronde 26 → 27)

| | |
|---|---|
| **Gejala asli** | Jendela `SM-online.bat` di PC sekolah: `[2/3] Menyalakan Tailscale Funnel ...` lalu `Tailscale belum bisa dipakai: gagal menjalankan tailscale: Command [...] 'funnel' '--bg' '--https=443' '8000'] timed out after 90 seconds`. Di Command Prompt, `tailscale status` normal (Connected) dan `tailscale funnel status` menjawab **`No serve config`**. |
| **Yang saya pikirkan** | Perintah funnel menggantung karena masalah jaringan/port, jadi batas 90 detik dianggap cukup untuk menyimpulkan «gagal». |
| **Yang sebenarnya** | Saat Funnel dipakai **pertama kali** di sebuah tailnet, perintah `tailscale funnel` **mencetak tautan persetujuan** (`https://login.tailscale.com/f/funnel?node=…`) lalu **menunggu tanpa batas** sampai halaman itu disetujui (ia juga bisa membuka peramban). Keluaran perintah itu **ditelan** (`capture_output=True`) sehingga tautannya tidak pernah terlihat, dan batas 90 detik mematikan prosesnya di tengah jalan → tidak ada yang tersimpan, karena itu `funnel status` tetap `No serve config`. Jadi bukan jaringan, bukan port, bukan aplikasi SM. |
| **Aturan** | (a) Untuk perintah yang **bisa interaktif/menunggu pengguna**, keluaran **harus ditampilkan langsung** ke layar (bukan `capture_output`) dan dibaca baris demi baris; (b) **kehabisan waktu ≠ gagal** — laporkan sebagai «belum selesai, kemungkinan menunggu persetujuan» dan sertakan tautan yang benar-benar tercetak; (c) beri kesempatan menyetujui: batas tunggu 180 detik dan **diperpanjang otomatis** selama belum ada galat (total ±9 menit) sehingga begitu guru mengklik *Approve*, jendelanya **lanjut sendiri**; (d) sediakan juga jalur yang tidak menunggu sama sekali: admin/dns (MagicDNS + HTTPS) dan admin/acls → *Add Funnel to policy*; (e) bila funnel sudah «on» tetapi alamat publik belum menjawab, ingatkan bug Tailscale di Windows: pengaturan funnel baru dikirim ke servernya setelah aplikasi/daemon dijalankan ulang (`Quit` → buka lagi, atau `sc stop tailscale` + `sc start tailscale`). |

### 14. Berkas pustaka bawaan dibuat dari daftar nama, bukan dari versi yang dipatok aplikasi (ronde 22)

| | |
|---|---|
| **Gejala asli** | Tangkapan layar PC sekolah: «Pemasangan pustaka gagal: ERROR: Could not find a version that satisfies the requirement python-multipart==0.0.20 (from versions: 0.0.32)» — padahal internet ada. |
| **Yang saya pikirkan (ronde 21)** | Pemasang punya berkas pustaka bawaan (``--dengan-bahan``), jadi pemasangan pasti jalan walau tanpa internet. |
| **Yang sebenarnya** | Dua kesalahan bertumpuk: (a) ``buat_payload.py`` mengunduh pustaka dari **daftar nama yang ditulis tangan** (``PUSTAKA = (… "python-multipart" …)``) sehingga yang dibundel versi *terbaru* (0.0.32), sedangkan ``requirements.txt`` memakai **versi yang dipatok** (0.0.20) — berkas bawaan jadi tidak bisa memenuhi permintaan aplikasi; (b) begitu berkas bawaan gagal, pemasang **langsung berhenti** padahal pengguna punya internet. |
| **Aturan** | (a) Bundel pustaka **selalu** dibuat dari berkas permintaan aplikasi (``requirements.txt``/``requirements-bot.txt``) — jangan pernah dari daftar nama yang ditulis tangan; (b) sediakan **jalan keluar**: coba berkas bawaan dulu, lalu lanjut unduh dari internet secara otomatis, karena «tidak punya internet» bukan satu-satunya keadaan pengguna; (c) sebutkan **pustaka dan versi** yang gagal pada pesan, jangan hanya «gagal memasang pustaka»; (d) paket yang hanya ada sebagai kode sumber (``odfpy``) harus dibawa beserta keperluannya (``defusedxml`` — terbaca dari ``setup.py``, bukan dari metadatanya). |

| **Tambahan (ronde 19 — jangan bergantung pada Ext JS & jangan menyimpulkan «tidak ada» sebelum daftarnya disusuri)** | Dua kekeliruan yang terbukti dari uji sendiri: (a) **semua jalur berbasis Ext bisa mati bersama-sama** — di sebagian pemasangan Dapodik, `Ext` tidak terjangkau dari skrip (``Ext.getCmp``/``store``/``select`` semuanya gagal); kalau bot hanya punya jalur itu, dropdownnya tidak bisa dibuka sama sekali. Jalan yang **tidak bergantung Ext** sudah ada dan harus dipakai lebih dulu: menekan **tombol ↓** pada kolomnya (begitulah combo Ext JS dibuka) dan membaca **elemen daftarnya dari DOM** lewat ``aria-owns="…-inputEl …-picker-listEl"``/``…-picker-listEl``/``.x-boundlist``. Keadaan terbuka juga bisa dibaca dari ``aria-expanded`` & elemen daftar yang benar-benar terlihat. (b) **«pilihan tidak ada» itu kesimpulan yang mahal** — pernah dicatat padahal pilihannya hanya belum masuk bagian daftar yang terlihat; yang benar: gulir daftarnya dari ATAS sampai bawah, kumpulkan semua pilihan yang pernah terlihat, baru cocokkan lagi (dan hentikan penyusuran begitu pilihan yang sama namanya ketemu). Selain itu, ``_klik_pilihan_dropdown`` harus **mulai dari atas** setiap kali — pilihan di atas posisi gulir saat ini tidak akan pernah ketemu bila daftarnya hanya digulir ke bawah. Bila sebuah kolom tetap gagal, simpan **bukti layar saat daftarnya terbuka** (``bio-dropdown-<kolom>-*.png``) supaya keadaannya bisa diperiksa tanpa menebak. |
| **Tambahan (ronde 17 — DOM asli dari sekolah)** | Dua sebab ronde 16 belum berhasil di PC sekolah: (a) **nama kolomnya berbeda** — ``name="pekerjaan_id_ayah"`` & ``penghasilan_id_ayah`` (bukan ``pekerjaan_ayah``), ``aria-owns="…-picker-listEl"``, ``data-componentid="pekerjaancombo-2560"``; (b) **daftarnya tidak harus terbuka** — pilihannya ada di ``store`` komponennya, dan di Dapodik sekolah mengklik pilihan **tidak menyimpan apa pun** (klik ditelan lapisan), sehingga jalur yang bekerja adalah ``select(record)``/``setValue(id)``. Pelajaran umum: **jangan menebak nama kolom** — minta/minta-tempel DOM-nya, lalu pakai nama itu sebagai selector utama; dan **"pilihan terbaca" ≠ "daftar terbuka"** (jangan mencatat "sudah diklik" untuk klik yang tidak pernah terjadi). |

---

## 2. Daftar periksa sebelum mengklaim "sudah beres"

1. **Temukan baris lognya.** `grep` kalimat yang dikeluhkan pengguna di `app/bot_dapodik.py`,
   lalu baca fungsi yang mencetaknya — pahami mengapa baris itu bisa tercapai.
2. **Reproduksi dulu.** Tambahkan skenario di `scripts/uji_bot_dapodik.py` +
   `scripts/peramban_palsu.py` yang membuat **uji itu GAGAL lebih dulu**.
3. **Baru perbaiki.** Uji harus hijau **tanpa** menghapus kejujuran log (jangan mengganti
   "dilewati — belum terpasang" menjadi "berhasil" demi uji hijau).
4. **Jalankan seluruh suite:** `scripts/uji_bot_dapodik.py` **dan** `scripts/cek_sistem.py`
   (tambahkan `--http` bila menyentuh halaman web).
5. **Tulis jawaban yang bisa diperiksa pengguna:** baris log mana yang salah, jalur kode mana
   yang diperbaiki, bukti ujinya, dan **satu hal konkret** yang diminta (versi kode + blok log).

---

## 3. Peta gejala → baris log → tempat di kode

Semua di `app/bot_dapodik.py` (nama fungsi, bukan nomor baris — nomornya bergeser).

| Gejala / baris log | Fungsi |
|---|---|
| `[periodik] kotak «Jarak rumah ke sekolah» tidak ada di halaman ini — yang terlihat di panel: …` | `_pilih_jarak` (+ `_ringkas_panel`) |
| `[periodik] kotak «Jarak rumah ke sekolah» ditemukan tetapi belum terlihat …` | `_kotak_jarak` |
| `[periodik] pilihan jarak «…»: kotaknya ditemukan (id komponen …) — dicoba klik labelnya → kotaknya → pembungkusnya → Ext.getCmp.` | `_pilih_satu` |
| `[periodik] …: kotak yang ditemukan bertuliskan «…» (bukan yang diminta) …` | `_pilih_satu` (perbaikan kotak lewat teks) |
| `[periodik] …: label pilihannya ditemukan lewat teksnya (JavaScript) …` | `_pilih_satu` → `_label_lewat_teks` |
| `[periodik] …: tampilan sudah berubah tetapi nilai Ext JS belum …` / `semua klik belum mengubah nilai Ext JS — dipakai Ext.getCmp` | `_pilih_satu` (eskalasi) |
| `[periodik] …: nilai Ext JS belum berubah juga — pilihan ini belum terpasang …` | `_pilih_satu` (kegagalan jujur) |
| `[periodik] …: id komponen Ext JS tidak terbaca (data-componentid kosong) …` | `_set_ext_pilihan` |
| `[periodik] Sebutkan (dalam kilometer): dilewati — pilihan «…» belum terpasang …` | `_isi_data_periodik` |
| `[periodik] memilih «Jarak rumah ke sekolah» — data siswa … km → pilihan «…»` | `_isi_data_periodik` |
| `[periodik] <kolom>: data siswa kosong — dilewati.` | `_isi_data_periodik` |
| `[periodik] <kolom>: kolom masih nonaktif saat akan diisi …` | `_isi_periodik_satu` (`_tunggu_aktif`) |
| `[gulir] panel «Data Periodik Peserta Didik» dibawa ke layar …` / `… tidak ketemu — memakai gulir halaman …` | `_gulir_panel_periodik` |
| `[gulir] halaman digulir 250 px ke bawah (seperti skrip sekolah).` | `_gulir` |
| `[tunggu] lapisan pemuatan Dapodik masih terlihat …` | penantian `div.x-mask` |
| `[login] kolom <label>: terisi (n karakter)` / `tidak ditemukan` | `_login` |
| `[registrasi] baris siswa belum terpilih …` | `_pastikan_baris_terpilih` |
| `[selector] klik lewat skrip untuk …` / `kolom diisi lewat skrip …` | `_klik_aman` / pengisian cadangan |
| `[versi] kode SM yang berjalan: …` | `_versi_kode` (dipakai juga oleh lencana `Kode SM:` di halaman bot) |
| `[layar] jendela Chrome … · area tampil …` | `_buka_peramban` |
| `[bio] jendela «Ubah» tidak terbaca oleh JavaScript — kolomnya dilacak lewat namanya …` | `_cari_kolom_bio` (jalur tanpa wadah jendela) |
| `[bio] <kolom>: kolomnya ditemukan lewat namanya di halaman (cara skrip sekolah) — … digeser 250 px bertahap (Nx).` | `_cari_kolom_bio` → `_kolom_global` |
| `[bio-rincian] <kapan> \| jendela: … \| kolom di dalam jendela: … \| wadah gulir: … \| tombol «Simpan»: N (milik panel «Data Rincian»: M)` | `_rincian_bio` |
| `[bio] bukti layar disimpan: … (.png + .html di folder yang sama)` | `_bukti` (dipanggil dari `_isi_bio`) |
| `[bio] <kolom>: dropdown dibaca lewat data komponen Ext JS [+ daftar dibuka lewat panah/kolom/Ext JS] — N pilihan tersedia.` | `_isi_dropdown_bio` → `_data_dropdown` (+ `_buka_dropdown`) |
| `[bio] <kolom>: daftar dropdownnya tidak terbuka di Dapodik — pilihan «…» dipasang lewat model Ext JS (select/setValue).` | `_isi_dropdown_bio` → `_pilih_dropdown_ext` |
| `[bio] <kolom>: dropdown dibuka lewat panah — N pilihan tampil (menunggu 3x baca).` | `_isi_dropdown_bio` → `_tunggu_daftar_dropdown` |
| `[bio] <kolom>: pilihan «…» belum tampil di daftar — daftarnya digeser Nx ke bawah sampai ketemu.` | `_klik_pilihan_dropdown` → `_gulir_daftar_dropdown` |
| `[bio] <kolom>: pilihan «…» tidak ketemu pada daftar yang terbuka (sudah digeser Nx) — pilihan dipasang lewat model Ext JS (select/setValue).` | `_isi_dropdown_bio` → `_pilih_dropdown_ext` |
| `[bio] <kolom>: pilihan «…» sudah diklik tetapi nilainya belum tersimpan … dipilih lewat model Ext JS` | `_isi_dropdown_bio` → `_pilih_dropdown_ext` |
| `[bio] <kolom>: «SMA / sederajat» dibaca sebagai «SMA».` / `… bernama lain «SLTA» di Dapodik` | `_cocokkan_pilihan` |
| `[bio] <kolom>: terisi (dipilih dari daftar): …` / `terisi lewat Ext JS (dipilih dari daftar): …` | `_isi_dropdown_bio` (`_klik_pilihan_dropdown` / `_set_ext`) |
| `[bio] <kolom>: pilihan «…» TIDAK ADA di daftar dropdown Dapodik — yang terlihat: … (dilewati, tidak ditebak).` | `_isi_dropdown_bio` + `_cocokkan_pilihan` |

---

## 4. Aturan menjawab pengguna

1. **Akui dulu bila perbaikan sebelumnya meleset**, sebutkan alasannya (mis. "saya memperbaiki
   jalur klik, padahal log menunjukkan kotaknya tidak pernah ketemu"). Tanpa ini pengguna
   berhak menganggap jawabannya halusinasi.
2. Setiap jawaban memuat: **sebab yang terbukti** (kutipan log/DOM), **apa yang diubah**
   (nama fungsi), **bukti uji** (jumlah skenario/pemeriksaan), dan **satu langkah konkret**
   untuk pengguna (jalankan `run.bat`, periksa `Kode SM: <revisi>`, kirim blok log tertentu).
3. Jangan menjanjikan "beres" untuk hal yang hanya teruji di peramban palsu. Katakan apa
   adanya: "teruji di uji tiruan; bila di sekolah masih gagal, log akan menunjukkan X — kirim
   baris itu".
4. Bila pengguna mengirim HTML/DOM: **kutip bagian yang relevan** dan jelaskan apa yang
   dibacanya (mis. penanda `x-form-cb-checked`, `disabled` pada kolom km), jangan diam-diam
   menyimpulkan.

---

## 5. Batas lingkungan kerja (dan konsekuensinya)

* Sandbox **tidak punya Chrome dan tidak punya akses ke Dapodik**. Karena itu:
  * uji permanen memakai **peramban palsu** (`scripts/peramban_palsu.py`) — hanya membuktikan
    konsistensi internal, bukan perilaku Dapodik sungguhan;
  * setiap kesimpulan tentang Dapodik nyata **harus** punya bukti dari log/DOM pengguna;
  * log bot harus **mendiagnosis dirinya sendiri** — cetak apa yang terlihat (label, nama
    kolom, id komponen, ukuran jendela), bukan hanya "gagal".
* Ruang kerja bisa **ter-reset** (pernah terjadi dua kali: `.venv`, `data/`, `node_modules`
  hilang, HEAD kembali ke commit awal). Maka:
  * pekerjaan harus selalu **ter-push** ke cabang `arena/01a0a87a-sm`;
  * uji harus **permanen di `scripts/`**, jangan di `/tmp` (file `/tmp` hilang saat reset);
  * pemulihan: `git fetch origin arena/01a0a87a-sm` → `git reset --hard FETCH_HEAD` →
    buat `.venv` + `pip install -r requirements.txt -r requirements-bot.txt` →
    `npm install jsdom` → `scripts/buat_data_contoh.py` → `run.py --init-db` (wajib, kalau
    tidak: `no such table: dapodik_jobs`).
* Angka yang harus dipegang: `bot_timeout=15`, `bot_jeda_muat=5`, `MAX_RETRIES=3`,
  `GULIR_PERIODIK=250`, `GULIR_PERCOBAAN=4`, `BUKTI_MAKSIMAL=40`, `UJI_TUNGGU_PERTAMA=4`,
  `UJI_TUNGGU_LAIN=2`, `SELEKTOR_UJI_DETIK=6` — jangan dinaikkan hanya untuk membuat uji lewat.

---

## 6. Ringkasan riwayat perbaikan bot (untuk konteks cepat)

| Ronde | Commit | Inti |
|---|---|---|
| 15b | `0beee4c` | Bot mengikuti skrip Selenium sekolah; headless; progres di aplikasi SM; antrean dari data siswa aplikasi |
| 15d–15h | `86a8858` … `a8f75c5` | Tunggu formulir login; penantian pemuatan; hapus fitur saran selector; popup pengumuman ditutup lebih dulu |
| 15j | `69f5050` | Pilih baris siswa (mousedown) sebelum Registrasi |
| sekolah_asal | `c139178` | Antrean bot membawa «Sekolah Asal» + pengisiannya |
| 15k–15o | `c509b25` … `146464f` | Urutan Data Periodik; `scrollBy(0,250)`; panel ber-area-gulir dibawa ke layar |
| 15p–15q | `ce8a954`, `3326051`, `508e8b9` | Radio lewat label `x-form-cb-label`; peristiwa input/change/blur; log jarak eksplisit; versi kode di log & halaman |
| 15s | `9b5e368` | DOM sekolah: label sesudah input, keadaan lewat kelas `x-form-cb-checked`, kolom km nonaktif ditunggu |
| 15t | `3b9da31` | Penanda `x-form-cb-checked` menentukan → eskalasi `Ext.getCmp(...).setValue(...)` |
| 15u | `e6c35ca` | Pilihan jarak tidak lagi bergantung XPath (dilacak lewat teksnya), jeda render, log `[layar]`, laporan isi panel |
| 15v | `11671bc` | Aturan kerja repo (`AGENTS.md` + `CLAUDE.md`) supaya catatan ini benar-benar dibaca |
| 15w | `3594a7b` | **BIO lewat tombol «Ubah»** (14 kolom persis skrip sekolah, jendela dibawa ke layar, disimpan dengan «Simpan») dijalankan **sebelum** Data Periodik |
| 15x | `25ef4a8` | BIO diperkuat dari tangkapan layar sekolah: verifikasi jendela «Edit Peserta Didik», kolom & «Simpan» dibatasi pada jendelanya, isi jendela digulir bertahap (bukan `scrollBy` halaman) |
| 15y | `3924e29` | BIO: posisi gulir jendela (mulai dari atas, 250 px sekali geser, dicari ulang tiap langkah) + mundur ke `Ext.getCmp(...).setValue(...)` bila ketikan/JS tidak mengubah model Ext JS |
| 15z | `12a9d70` | BIO: bot **melaporkan sendiri** keadaan jendela (`[bio-rincian]` + bukti `.png`/`.html` di `data/bot/`) dan tetap bekerja walau wadah jendela tak terbaca — kolom dilacak lewat namanya sambil halaman digeser 250 px (cara skrip sekolah) |
| 16 | `b648d1e` | **Kolom dropdown (combo Ext JS)** jendela «Ubah»: pilihannya dipilih dari daftar (panah → kolom → `Ext.expand()`), dicocokkan dengan daftar Dapodik (persis → dirapikan → nama lain), nilai **model** Ext JS diperiksa, pilihan di luar daftar **tidak ditebak**; + Pekerjaan & Penghasilan ayah/ibu |
| 17 | `bce72cd` | Dropdown memakai **nama kolom asli** Dapodik (`pekerjaan_id_ayah`, `penghasilan_id_ayah`, …), pilihannya dibaca dari **data komponen Ext JS** (`store`) sehingga daftar tidak perlu terbuka, hasil diperiksa dari `getRawValue()`, dan pemasangan nilai lewat `select(record)`/`setValue(id)` bila klik ditelan atau daftar tak terbuka |
| 34 | (lihat commit) | **Peringatan → lonceng, tombol «+ Siswa» dihapus, ikon dirapikan.** Spanduk «Aplikasi sedang dapat dibuka dari internet» dihapus dari `base.html`; kini **lonceng notifikasi** di samping tombol «Impor Berkas» (angka jumlah + popup, satu popup terbuka sekaligus, klik luar/Esc menutup; hanya tampil bila aplikasi memang online). Tombol «+ Siswa» dihapus dari bilah atas dan dari halaman Data Siswa (data hanya lewat impor Dapodik). Ikon: kartu kegiatan siswa memakai baris kepala (ikon sebaris dengan nama kegiatan) — tidak lagi menggantung di pojok kartu; kartu peran & kepala halaman masuk memusatkan ikonnya (`align-items: center`); tombol **Masuk** yang keliru memakai ikon **keluar** diganti ikon baru `login`; tombol ikon-saja diberi `aria-label`/`title`. Ikon `bell` & `login` ditambahkan dengan aturan 24×24 yang sama. Pratinjau menambah `notifikasi.html` (lonceng tertutup & terbuka). 30/30 & 57/57 lulus (payload 106 berkas). |
| 33 | (lihat commit) | **Ikon dirapikan & kartu jumlah dipindah ke atas.** 30 ikon digambar ulang dengan aturan bersama (pusat 12,12 · kotak aman 2–22 · ukuran ≥14); ikon `folder`, `history`, `x` yang tadinya tidak ada (muncul lingkaran polos) dibuat; `cog`/`warning`/`flag` tidak lagi miring atau menyentuh tepi; ikon yang menempel pada teks diberi `vertical-align`; penanda `icon-kosong` untuk nama ikon yang salah. Halaman Data Siswa: kartu jumlah (laki-laki/perempuan/KIP/PIP) pindah ke **atas** tabel. Alat baru `scripts/cek_ikon.py` mengukur geometri semua ikon, `cek_sistem` blok 29 menjalankannya, dan pratinjau menambah **galeri ikon** (`pratinjau/ikon.html`) serta halaman petugas (`dasbor.html`, `data-siswa.html`). 29/29 & 57/57 lulus. |
| 32 | (lihat commit) | **«Designnya rame banget» → tombol `!` + popup.** Semua tata cara di halaman siswa dipindah ke tombol `!` kecil yang membuka popup singkat (`petunjuk()` di `_macros.html`, `.pl-info*` di `portal.css`, pembuka/penutup di `app.js`: satu popup sekaligus, klik luar/Esc menutup). Beranda dipangkas jadi empat blok (sapaan · Perlu dilakukan · kelengkapan satu baris · kegiatan), «Dataku» kehilangan kalimat penjelas per kelompok, «Kegiatan» memakai kartu + riwayat terlipat, «Minta perbaikan data» menunjukkan satu baris per bagian (49 isian tetap lengkap, dibuka saat perlu; tabel riwayat → baris ringkas), halaman masuk kehilangan daftar langkah 1-2-3 dan kotak bantuan panjang, dan footer jadi satu baris. Hero tidak lagi memotong popup (`overflow: visible`). `cek_sistem` blok 16 memeriksa makro `petunjuk`, gaya popup, pembuka di `app.js`, dan bahwa halaman siswa memakainya; blok 22 mengikuti label baru. |
| 31 | (lihat commit) | **Tangkapan layar sekolah: «bagian jelek» = tabel Dataku.** Halaman `portal/profile.html` disusun ulang menjadi kartu per kelompok (Tentang saya, Alamat & kontak, Data ayah/ibu/wali, Sekolah, Bantuan, Kesehatan) dengan baris «nama data — isi», **pencarian** penyaring langsung, tombol **Cetak / simpan PDF**, penanda «Belum diisi», dan badge «diatur sekolah» untuk rombel/tingkat. Nilai kode diterjemahkan maknanya (L → Laki-laki, 1 → Ya) tanpa mengubah isi data; label dirapikan lewat `rapikan_label()` dengan daftar akronim agar NISN/NIK/KK/RT/KM tetap benar. `cek_sistem` blok 16 menguji perapian label + memastikan halaman siswa tidak lagi memakai `<table>`. |
| 30 | (lihat commit) | **Bukti «lama ⇄ sekarang» + cara memperbarui PC sekolah.** `scripts/bandingkan_tampilan.py` merender template **lama** (diambil dari Git lewat `git archive <revisi> app/templates`) dengan data siswa yang sama, lalu menyandingkannya dengan halaman sekarang di `pratinjau/bandingkan.html` — supaya penilaian «cocok untuk anak kelas 7?» berdasar tampilan sungguhan, bukan tangkapan layar atau ingatan. README ditambah cara menarik pembaruan di PC sekolah (bodap.exe ke folder yang sama / `pasang.py perbarui` / menu Pembaruan) karena **tampilan baru tidak muncul pada pemasangan yang belum diperbarui**. |
| 29 | (lihat commit) | **Halaman masuk ikut diramah-anakkan** (lanjutan r28): tab «Siswa — cukup NISN, tanpa sandi» berukuran ≥66 px, sapaan «Halo, teman!», langkah **1-2-3** cara masuk, isian NISN 58 px & tombol 60 px, kotak bantuan «belum tahu NISN?» warna hangat — semuanya dibatasi kelas `.login-ramah`/`.pl-masuk-siswa` sehingga tab Admin/Guru & Ekstrakurikuler tampil seperti sebelumnya. Pratinjau (`scripts/pratinjau_tampilan.py`) kini menampilkan tab siswa sebagai `masuk.html`, dan `cek_sistem` memeriksa penanda gaya itu tetap ada. |
| 28 | (lihat commit) | **«Ruang siswa» dipisahkan dari halaman petugas** (komplain sekolah: tampilan tidak cocok untuk anak kelas 7). Siswa tidak lagi melihat sidebar/tabel petugas: kerangka `portal/_base.html` + `app/static/css/portal.css` (menu bawah besar, huruf 16,5–17 px, tombol ≥44 px, warna lembut), beranda dengan kartu **«Yang perlu kamu lakukan»**, penanda **«Belum diisi»**, judul & kalimat disederhanakan (Dataku, Kegiatan/klub, Minta perbaikan data), dan `dokumen_jenis`/`pengajuan_aktif` diteruskan ke beranda. Ditambah `scripts/pratinjau_tampilan.py` untuk melihat tampilan siswa sebagai HTML mandiri (tanpa memasang aplikasi), pemeriksaan `cek_sistem` (blok 16: berkas tema + 4 template memakai kerangka siswa; blok 17: halaman siswa tanpa tautan menu petugas), serta catatan `.gitignore` untuk folder `pratinjau/`. Halaman petugas sengaja **tidak** diubah. |
| 27 | (lihat commit) | **«Tailscale timed out» = Tailscale menunggu izin Funnel, bukan gagal** (laporan PC sekolah: `funnel status` → `No serve config`). `SM-online.py` sekarang menampilkan keluaran `tailscale funnel` **langsung ke layar** (tautan persetujuan `login.tailscale.com/f/funnel` terlihat, bukan tertelan), batas tunggu 180 detik yang **diperpanjang otomatis sampai ±9 menit** selama belum ada galat (jadi begitu disetujui, jendelanya lanjut sendiri), dan pesannya jujur «belum selesai — masih menunggu persetujuan» beserta dua jalan keluar (tautan itu, atau admin/dns + admin/acls → *Add Funnel to policy*). Ditambah peringatan bug Tailscale Windows (funnel «on» tapi alamat belum menjawab → jalankan ulang aplikasi/daemon Tailscale) dan panduan `PANDUAN-ONLINE.md` yang menyebut langkah izin ini lebih dulu. |
| 26 | (lihat commit) | **Tailscale Funnel dipilih sebagai jalur online utama** (data tetap di PC sekolah, bot Dapodik tetap bisa jalan). Pelajaran: ``tailscale funnel`` punya syarat yang mudah terlewat — **MagicDNS**, **HTTPS Certificates**, dan izin Funnel pada tailnet — sehingga pesan galat aslinya tidak berarti apa-apa bagi guru; ``SM-online.py`` sekarang menerjemahkannya menjadi langkah perbaikan konkret (``--cek`` memeriksa tanpa menjalankan server). Port publik Funnel hanya **443/8443/10000** (batas Tailscale) dan divalidasi sebelum perintah dijalankan, plus ``--hentikan`` untuk menutup akses publik tanpa mematikan aplikasi lokal. Alamat publik juga **diuji sungguhan** setelah funnel menyala (permintaan keluar lewat relay lalu kembali) supaya laporan «sudah online» tidak sekadar dugaan. |
| 25 | (lihat commit) | **Bisa dijalankan online gratis lewat Vercel** — dan batasnya dinyatakan terus terang di aplikasi: serverless Vercel hanya bisa menulis di ``/tmp`` (data **tidak permanen**), tidak punya Chrome (bot mustahil) dan tidak punya git (menu Pembaruan mati). Karena itu ``app/config.py`` mendeteksi environment ``VERCEL`` lalu memindahkan folder data ke ``/tmp`` **sebelum** apa pun memakainya, mematikan ``SM_GIT_UPDATE``/``SM_AUTO_SEED``/``SM_EKSKUL_SEKOLAH``, dan halaman Bot Dapodik + daftar periksa keamanan menjelaskan sebabnya. Pelajaran: berkas ``api/index.py`` saja tidak cukup — Vercel bisa memilih ``app/main.py`` sebagai titik masuk, jadi penyesuaian serverless **harus** ada di dalam modul konfigurasi. ``SM_SECRET_KEY`` wajib diisi di Vercel; tanpa itu tiap instans membuat kunci sesi sendiri dan login terputus-putus. |
| 24 | (lihat commit) | **Bisa dicabut dari Control Panel**: entri *Programs and Features* / *Pengaturan → Aplikasi* ditulis lewat `reg` di `HKCU\…\CurrentVersion\Uninstall\SM` (tanpa PowerShell, tanpa hak admin) oleh modul bersama `pemasang/pencabut_sm.py`; `DisplayName` yang membuat entri muncul, `UninstallString` yang membuat tombol **Uninstall** bekerja. Pelajaran penting: berkas pencabut **jangan** hanya diletakkan di dalam folder aplikasi — begitu foldernya dipindahkan (atau gagal menghapus dirinya sendiri), entri Control Panel menjadi tombol mati; karena itu `Hapus-SM.vbs`/`Hapus-SM.cmd` disalin juga ke `%LOCALAPPDATA%\Programs\SM-Pencabut`. Pencabut **tidak pernah** menghapus folder data, mematikan aplikasi lebih dulu (`--hentikan`), dan `--hapus` kini menolak folder yang bukan pemasangan SM kecuali memakai `--paksa` (dulu `--hapus --tujuan <folder apa pun> --ya` bisa menghapus folder orang lain). |
| 23 | (lihat commit) | **Tiga mikro-bug sekaligus**: (1) deret **`SyntaxWarning: invalid escape sequence '\s'`** di `app/bot_dapodik.py` — JS yang ditulis di dalam string Python harus memakai `\\s`; seluruh berkas `.py` kini dipindai otomatis (blok 27 di `scripts/cek_sistem.py`, lewat tokenizer — `compileall` tidak menampilkan peringatan ini); (2) **jendela terminal muncul saat aplikasi dijalankan** → peluncur `SM-latar.py` dijalankan `SM.vbs`/`Hentikan-SM.vbs` lewat **`pythonw.exe`** dengan `CREATE_NO_WINDOW`/`DETACHED_PROCESS`, jadi aplikasi berjalan **di belakang layar**; (3) **hasil pemasangan masih berisi data lama** (daftar ekskul contoh ikut terbawa) → `SM_EKSKUL_SEKOLAH` bawaan **0**, basis data hasil pasang **kosong**, dan 14 ekskul resmi hanya diisi bila diminta (`run.py --isi-ekskul-resmi` atau tombol di halaman Ekstrakurikuler) |
| 22 | (lihat commit) | **Berkas pustaka bawaan diperbaiki**: dibuat dari ``requirements.txt``/``requirements-bot.txt`` (versi pasti sama dengan yang diminta aplikasi), sdist (``odfpy``) dibawa beserta keperluannya, dan setiap pin diperiksa (``payload/wheels-terlewat.txt``); pemasang kini **lanjut unduh dari internet** bila berkas bawaan tidak cocok, dengan log jujur menyebut versi yang gagal; uji regresi: bundel cocok dengan pin + pemasangan tetap sukses saat berkas bawaan sengaja dibuat salah |
| 21 | (lihat commit) | **`bodap.exe` — pemasang satu berkas (Windows)**: wizard Sambutan → Folder & pilihan → Proses → Selesai + ikon Desktop; membawa Python bawaan (komputer tujuan tidak perlu Python), pip bawaan, dan (opsional) seluruh berkas `.whl`; data sekolah tidak pernah ditimpa; pencabut `Hapus-SM.cmd`; pencadangan keamanan: `.venv` pribadi bila memakai Python komputer (PEP 668) |
| 20 | (lihat commit) | **Pemasang (installer)**: `pemasang/pasang.py` + `pemasang/buat_paket.py` — pasang/periksa/perbarui/hapus/dari-zip dan paket ZIP (opsional dengan berkas `.whl` untuk pasang tanpa internet); data sekolah di folder `data` tidak pernah ditimpa; folder berisi berkas orang lain tidak ditimpa tanpa `--paksa` |
| 19 | (lihat commit) | Dropdown **tidak bergantung Ext JS**: dibuka lewat **tombol ↓** pada kolomnya dan daftarnya dicari langsung dari **DOM** (`aria-owns="…-inputEl …-picker-listEl"`); pilihan belum ketemu → daftar **disusuri dari atas sampai bawah** (berhenti begitu pilihan yang sama namanya ketemu, yang **sama persis** didahulukan atas nama lain) sebelum menyimpulkan «tidak ada»; **bukti layar** `bio-dropdown-<kolom>-*.png` disimpan saat sebuah kolom dropdown tetap gagal |
| 18 | (lihat commit) | Dropdown diklik seperti orang memakainya: **tunggu datanya muncul**, lalu **gulir isi daftarnya 150 px sekali geser** sampai pilihan terlihat, baru diklik; pilihan yang belum terlihat tidak pernah diklik |

---

*Terakhir diperbarui: ronde 34. Tambahkan kesalahpahaman baru ke §1 begitu
ditemukan — termasuk kesalahan saya sendiri — supaya tidak terulang.*
