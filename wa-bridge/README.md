# Jembatan WhatsApp (Baileys)

Sidecar Node.js yang menghubungkan **WhatsApp** ke aplikasi SM. Peran utamanya
adalah **relay pesan**: menerima pesan WA → memanggil balik `/ollama/chat` di
SM → mengirim jawaban kembali. **Otak, alat, dan penjaga nilai tetap di Python**
— bridge ini tidak menjalankan alat dan tidak mengarang jawaban.

## Cara kerja

```
HP WhatsApp ─┐
             ▼
     Baileys (Node, lokal PC sekolah)
             │  HTTP localhost (cepat, tanpa internet)
             ▼
     FastAPI /ollama/chat ──► Ollama.bicara() ──► alat bodap (server-side)
             ▲
     penjaga nilai + num_ctx + pilih-alat + system prompt ala Meta AI
```

## Prasyarat

- **Node.js** terpasang di komputer (saran: LTS). Cek dengan `node --version`.
- Pasang pustaka bridge:

  ```bat
  cd wa-bridge
  npm install
  ```

> **Catatan:** Node.js belum dibundel di `bodap.exe`. Pasang Node.js di PC
> sekolah, lalu jalankan `npm install` di folder `wa-bridge` (sekali). Bila
> belum terpasang, aplikasi tetap jalan — halaman «WhatsApp» melaporkan
> «tidak siap» dengan petunjuk yang jelas.

## Pengaturan (di aplikasi)

1. Buka menu **WhatsApp** di bodap.
2. Aktifkan jembatan dan atur port lokal (bawaan `8799`).
3. Di HP WhatsApp: **Perangkat Tertaut → Tautkan Perangkat → Scan Kode QR**.
   Kode QR tampil di halaman «WhatsApp» (tombol **Muat ulang QR**).
4. Setelah terhubung, nomor WA tersimpan dan status berubah jadi **Terhubung**.
5. Uji dengan kotak **Uji masuk** (simulasi, tanpa WhatsApp sungguhan).

## Variabel lingkungan (dipasang otomatis oleh aplikasi)

| Variabel | Fungsi |
|----------|--------|
| `SM_WA_PORT` | Port HTTP lokal bridge (bawaan 8799) |
| `SM_WA_DIR` | Folder session WhatsApp (di `data/wa`) |
| `SM_BASE_URL` | Alamat bodap untuk memanggil balik |
| `SM_API_KEY` | Kunci API bodap |
| `SM_WA_ENABLED` | "1" nyala / "0" mati |
| `SM_WA_NO_CONNECT` | "1" mode uji (HTTP jalan, tanpa sambungan WA) |
| `SM_WA_ALLOW_SELF` | "1" proses chat ke diri sendiri (bawaan "1") |
| `SM_WA_HANYA_DIRI` | "1" hanya balas self-chat, lewati pesan dari nomor lain (bawaan "1") |

## Chat ke diri sendiri (self-chat)

Bot dapat dihubungi **tanpa meminta orang lain**: ketik pesan ke **chat diri
sendiri** di nomor WA pribadi Anda. Bot menjawabnya seperti biasa.

- Self-chat diproses lewat handler yang sama; **anti-echo** memastikan balasan
  bot sendiri **tidak dibalas ulang** (mencegah loop).
- Bawaan `SM_WA_HANYA_DIRI=1` → hanya self-chat yang dibalas; ubah ke `0` jika
  ingin bot juga menjawab pesan dari nomor lain.
- Bawaan `SM_WA_ALLOW_SELF=1` → self-chat diproses; set ke `0` kembali ke sikap
  lama (semua pesan `fromMe` dilewati, anti-loop).

## Titik akhir HTTP lokal

| Metode | Jalur | Keterangan |
|--------|-------|------------|
| `GET` | `/status` | Status sambungan |
| `GET` | `/qr` | PNG kode QR pairing |
| `POST` | `/send` | `{no, teks}` — kirim keluar |
| `POST` | `/test/inbound` | `{dari, teks}` — simulasi masuk (uji) |

## Catatan efisiensi

- **Bridge tipis** — hanya relay teks; tidak ada logika alat di Node.
- **Riwayat per nomor** disimpan di `data/wa/riwayat.json` (terakhir 20 pesan).
- **Antrean** — satu pesan selesai dulu sebelum berikutnya (anti beban Ollama).
- **Balasan ringkas** — WA bukan tempat tabel besar; sistem prompt mengarah ke
  ringkasan + tautan ke halaman aplikasi.
