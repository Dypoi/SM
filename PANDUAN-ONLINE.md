# SM online lewat Tailscale Funnel — panduan langkah demi langkah

Panduan ini untuk **PC sekolah (Windows)**. Setelah selesai, aplikasi SM milik Anda bisa dibuka
dari rumah/HP lewat alamat **https** tetap — **gratis, tanpa IP publik, tanpa membuka port
router**, dan **data sekolah tetap di komputer sekolah**.

> Singkatnya: aplikasi tetap berjalan seperti biasa di PC sekolah; Tailscale Funnel hanya
> membuatkan “pintu” HTTPS dari internet ke PC itu. Jadi **PC sekolah harus menyala** selama
> aplikasi ingin bisa dibuka dari luar.

---

## 1. Apa yang terjadi (dan kenapa ini yang dipilih)

```
HP/guru di rumah ──HTTPS──► relay Tailscale ──(terowongan terenkripsi)──► PC sekolah
                                       (server SM jalan di sini, data di sini)
```

| Yang Anda dapat | Artinya |
| --- | --- |
| Alamat tetap | `https://<nama-pc>.<tailnet>.ts.net` — tidak berubah tiap kali dijalankan |
| Biaya | Rp0 (paket **Personal** gratis: 6 pengguna, perangkat tak terbatas; Funnel tersedia) |
| Data | **tidak pernah keluar** dari PC sekolah — hanya permintaan halaman yang lewat relay |
| Bot Dapodik | **tetap bisa jalan** (Chrome & Dapodik ada di PC itu) |
| HTTPS | otomatis; sertifikat Let's Encrypt untuk `*.ts.net` diurus Tailscale |
| Port | yang menghadap internet hanya 443/8443/10000 (batas Tailscale); aplikasi tetap di port lokal 8000 |
| Bisa dibatasi? | bila **tidak** ingin publik, ada `tailscale serve` → hanya perangkat di jaringan Tailscale Anda (lihat bagian 9) |

Bandingkan dengan Vercel (lihat `PANDUAN-VERCEL.md`): di sana aplikasi **pindah** ke server
Vercel, datanya sementara, dan bot tidak bisa jalan. Di sini aplikasi tetap milik sekolah.

**Syaratnya:** PC sekolah ber-internet, akun Tailscale gratis, dan Windows 10/11
(Tailscale versi 1.38.3 atau lebih baru).

---

## 2. Persiapan (± 5 menit, sekali saja)

1. **Akun Tailscale gratis** — buka <https://login.tailscale.com/start>, masuk memakai akun
   Google/Microsoft/GitHub. Tidak perlu kartu kredit.
2. **Pasang Tailscale di PC sekolah** — unduh dari <https://tailscale.com/download/windows>,
   klik dua kali hasil unduhnya, lalu **Log in** memakai akun tadi. Setelah masuk, ikon
   Tailscale di sudut kanan bawah akan menampilkan **Connected**.
3. **Nyalakan MagicDNS & HTTPS** di konsol admin:
   buka <https://login.tailscale.com/admin/dns> → aktifkan **MagicDNS** dan
   **HTTPS Certificates** (klik *Enable HTTPS*).
   Ini wajib: tanpa HTTPS, Funnel menolak menyala.
4. **Izin Funnel** — Tailscale CLI menambahkan sendiri izin ini untuk pengguna pemilik/admin
   saat perintah funnel pertama dijalankan. Bila muncul pesan izin, bagian 10 menunjukkan
   yang harus diketuk di <https://login.tailscale.com/admin/acls>.

> Catatan: cukup satu akun Tailscale untuk sekolah ini. Di PC lain (mis. laptop kepala sekolah)
> bisa dipasang Tailscale yang sama bila ingin membuka aplikasi **tanpa** lewat internet —
> cukup buka `http://<ip-pc-sekolah>:8000` setelah keduanya ada di jaringan Tailscale yang sama.

---

## 3. Menjalankannya (langkah utama)

1. Pastikan **Dapodik/Chrome** dan aplikasi SM tidak sedang dipakai hal lain.
2. Buka folder aplikasi SM di PC sekolah, lalu **klik dua kali `SM-online.bat`**.
   *Jendela konsol akan menampilkan langkahnya — biarkan jendela ini terbuka.*
3. Perhatikan tiga baris terpenting:

   ```
   [1/3] Menjalankan server SM ...
         Server siap: http://127.0.0.1:8000
   [2/3] Menyalakan Tailscale Funnel ...
         Uji alamat publik: menjawab (HTTP 303)          ← bukti alamat publik benar-benar hidup
   [3/3] Aplikasi SM sudah online
     Alamat publik : https://sm-sekolah.tautan-anda.ts.net
     Di sekolah    : http://192.168.1.7:8000
   ```

   Bila tertulis **“BELUM menjawab”**, tunggu 10–30 detik lalu cek lagi (DNS/relay Tailscale
   kadang butuh beberapa detik saat pertama kali) — rincian di bagian 10.
4. **Bagikan alamat publik itu** kepada petugas/guru/siswa. Sama seperti biasa:
   petugas masuk dengan akun admin, siswa dengan NISN.
5. Alamat itu juga tersimpan di `data/alamat-publik.txt` dan tampil di
   **Pengaturan → Sistem → Aman Online**, lengkap dengan daftar periksa keamanan.

Ingin memastikan dulu sebelum menjalankan? Pakai **`SM-online.bat --cek`** — ia hanya memeriksa
(terpasang? sudah login? HTTPS & Funnel aktif?) dan langsung memberi tahu bila ada yang kurang.

---

## 4. Sebelum benar-benar dibagikan ke siswa (penting)

Buka **Pengaturan → Sistem → Aman Online** dan benahi yang bertanda *perlu dibenahi*:

1. **Ganti kata sandi admin** dari `admin123` (Pengaturan → Pengguna).
2. **Nyalakan pengaman login siswa** (satu klik di kartu itu). Tanpa ini, siapa pun yang tahu
   NISN bisa melihat data pribadi siswa — dan sekarang aplikasinya terjangkau dari internet.
3. **Cadangkan folder `data/`** secara berkala (salin ke flashdisk/Drive).
4. Bila hanya petugas yang perlu mengakses: **jangan** bagikan tautan ke siswa, cukup ke
   petugas. (Untuk benar-benar menutup akses publik, lihat bagian 9.)

Tailscale hanya membuka pintu; **pintu dalamnya tetap login aplikasi**. Penjaga CSRF, header
keamanan, pembatasan percobaan login, dan sesi `Secure` menyala otomatis saat aplikasi diakses
lewat HTTPS.

---

## 5. Menjaga agar tetap bisa dibuka dari luar

| Hal | Yang dilakukan |
| --- | --- |
| PC sekolah jangan tidur | *Pengaturan → Sistem → Daya & tidur* → **Tidur: Tidak pernah** (paling tidak saat jam sekolah); matikan *Hibernate* |
| Aplikasi ikut nyala saat komputer dinyalakan | saat memasang dengan `bodap.exe`, centang **«Jalankan SM otomatis saat komputer dinyalakan»**; lalu Tailscale juga otomatis nyala |
| Funnel tetap menyala setelah restart | ya — `--bg` membuat pengaturan funnel tersimpan di sisi Tailscale |
| Internet sempat mati | begitu internet kembali, funnel otomatis jalan lagi (aplikasi & tunnel tetap hidup) |
| Listrik/PC mati | aplikasi ikut mati; nyalakan PC, keduanya hidup lagi |

---

## 6. Mematikan akses publik

| Ingin | Caranya |
| --- | --- |
| Menutup akses dari internet, aplikasi tetap jalan di sekolah | `SM-online.bat --hentikan` (atau `tailscale funnel off`) |
| Menghentikan semuanya | tutup jendela `SM-online.bat` dengan `Ctrl+C` |
| Hanya sebentar | buka <https://login.tailscale.com/admin/machines> → perangkat → *Disable* |

Setelah `--hentikan`, penanda “sedang online” di aplikasi juga dibersihkan sehingga spanduk
perhatian di halaman petugas hilang.

---

## 7. Menjalankan ulang dengan cara yang lebih rapi (opsional)

Setelah semuanya terbukti berjalan, jendela konsol `SM-online.bat` tidak perlu terus terlihat:
aplikasi bisa dijalankan **di belakang layar** lewat ikon **SM** di Desktop (peluncur `SM.vbs`),
lalu funnel dinyalakan sekali dengan:

```bat
tailscale funnel --bg 8000
```

Perintah itu mengingat setelannya, jadi setelah reboot pun funnel langsung aktif sementara
aplikasi dijalankan dari ikon **SM** seperti biasa.

---

## 8. Kalau hanya untuk guru (tanpa dibuka ke internet umum)

Tailscale punya dua tingkat:

| Perintah | Siapa yang bisa membuka | Kapan dipakai |
| --- | --- | --- |
| `tailscale serve --bg 8000` | hanya perangkat yang sudah masuk ke **jaringan Tailscale Anda** (laptop/HP guru yang di-invite) | paling aman: guru bisa melihat data dari rumah tanpa aplikasi terbuka untuk publik |
| `tailscale funnel --bg 8000` | **siapa saja** yang punya tautan | siswa/orang tua perlu membuka dari HP tanpa memasang apa pun |

Untuk memakai `serve`, tambahkan akun guru di <https://login.tailscale.com/admin/users>
(kirim undangan), minta mereka memasang Tailscale di laptop/HP, lalu bagikan
`https://<nama-pc>.<tailnet>.ts.net` — hanya mereka yang bisa membukanya.

---

## 9. Pemecahan masalah

| Gejala | Sebab & jalan keluar |
| --- | --- |
| `Funnel is not enabled on your tailnet` | Izin Funnel belum ada. Jalankan perintah funnel **sebagai pemilik/admin tailnet** (CLI menambahkan izinnya sendiri), atau tambahkan `nodeAttrs` berisi `funnel` di <https://login.tailscale.com/admin/acls> |
| `HTTPS is not enabled on your tailnet` | Buka <https://login.tailscale.com/admin/dns> → aktifkan **HTTPS Certificates** |
| `Logged out` / `no state` / `stopped` | Tailscale belum masuk: klik ikonnya di sudut kanan bawah → *Log in*, tunggu **Connected** |
| `MagicDNS` disebut pada galat | Nyalakan **MagicDNS** di halaman DNS yang sama |
| Port 443 sudah dipakai | Jalankan `SM-online.bat --hentikan` dulu, atau `SM-online.bat --https-port 8443` |
| Alamat `ts.net` tidak menjawab dari HP | (1) jendela `SM-online.bat` masih terbuka? (2) Tailscale «Connected»? (3) tunggu 10–30 detik, ulangi; (4) cek dengan `tailscale funnel status` |
| Alamat menjawab tetapi lambat | Funnel punya batas bandwidth (tidak diumumkan, umumnya longgar untuk aplikasi sekolah). Kalau lambat terus, jalankan aplikasi di jam tertentu saja |
| Halaman terbuka tetapi login seperti “lupa” | penyimpanan cookie di HP (mode privat) atau jam HP salah; coba peramban biasa |
| Setelah beberapa hari hilang sendiri | PC tidur/restart dan jendela `SM-online.bat` tertutup — jalankan lagi, atau pakai cara bagian 7 |
| Bot Dapodik gagal dibuka dari jauh | bot memang hanya bisa dijalankan **di PC sekolah** (butuh Dapodik lokal + Chrome); jalankan dari komputer itu atau lewat Tailscale |
| Muncul peringatan “aplikasi sedang dapat dibuka dari internet” | itu pengingat normal; benahi daftar di **Pengaturan → Aman Online** lalu spanduknya hilang |

---

## 10. Tanya jawab singkat

**Apakah alamatnya berubah?** Tidak — `https://<nama-pc>.<tailnet>.ts.net` tetap selama
perangkat itu ada di tailnet Anda. (Beda dengan Cloudflare *quick tunnel* yang berubah tiap
dijalankan.)

**Perlu domain sekolah sendiri?** Funnel tidak mendukung domain sendiri (alamat `*.ts.net`).
Bila perlu domain kustom, itu jalur Vercel/hosting lain.

**Apakah data siswa dikirim ke Tailscale?** Tidak dibaca. Relay hanya meneruskan koneksi
terenkripsi (end-to-end antara relay dan PC sekolah); basis data dan berkas tetap di PC.

**Kuota?** Gratis 6 pengguna & perangkat tak terbatas. Tailscale menyebut ada batas bandwidth
Funnel yang tidak bisa diatur, tetapi untuk aplikasi sekolah (halaman HTML kecil) biasanya
tidak terasa.

**Bisakah dipakai sekolah + internet sekaligus?** Bisa: di sekolah lewat
`http://<ip-pc>:8000`, dari luar lewat alamat `https://…ts.net`.

**Kalau PC sekolah mati?** Aplikasi tidak bisa dibuka dari luar (lokal di sekolah pun tidak).
Untuk itu Vercel bisa dipakai sebagai “etalase” pratinjau — lihat `PANDUAN-VERCEL.md`.

**Berapa biaya totalnya?** Rp0: Tailscale Personal gratis dan aplikasi SM tidak memerlukan
layanan berbayar.

---

## 11. Perintah yang perlu diingat

```bat
SM-online.bat                 :: server + funnel (cara biasa)
SM-online.bat --cek           :: periksa kesiapan Tailscale lebih dulu
SM-online.bat --hentikan      :: matikan akses publik
SM-online.bat --lokal         :: tanpa internet (hanya jaringan sekolah)
SM-online.bat --buka          :: buka alamat publik di peramban PC ini
SM-online.bat --https-port 8443   :: bila port 443 dipakai layanan lain
```

Pemeriksaan otomatisnya ada di `python scripts/cek_sistem.py` (blok 18 & 19) dan diuji tanpa
internet sekalipun.
