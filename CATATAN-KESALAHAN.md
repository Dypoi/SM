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
| 17 | (lihat commit) | Dropdown memakai **nama kolom asli** Dapodik (`pekerjaan_id_ayah`, `penghasilan_id_ayah`, …), pilihannya dibaca dari **data komponen Ext JS** (`store`) sehingga daftar tidak perlu terbuka, hasil diperiksa dari `getRawValue()`, dan pemasangan nilai lewat `select(record)`/`setValue(id)` bila klik ditelan atau daftar tak terbuka |

---

*Terakhir diperbarui: ronde 17. Tambahkan kesalahpahaman baru ke §1 begitu
ditemukan — termasuk kesalahan saya sendiri — supaya tidak terulang.*
