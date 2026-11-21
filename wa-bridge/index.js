/**
 * Jembatan WhatsApp (Baileys) untuk aplikasi SM.
 *
 * Peran: **hanya relay**. Menerima pesan WhatsApp → POST ke bodap (/ollama/chat)
 * → mengirim jawaban kembali. Otak, alat, dan penjaga nilai tetap di Python;
 * bridge ini tidak menjalankan alat dan tidak mengarang jawaban.
 *
 * Diatur lewat variabel lingkungan (diserahkan oleh app/wa_bridge.py):
 *   SM_WA_PORT      port HTTP lokal bridge (bawaan 8799)
 *   SM_WA_DIR       folder session WhatsApp (bawaan ./.session)
 *   SM_BASE_URL     alamat bodap (bawaan http://127.0.0.1:8000)
 *   SM_API_KEY      kunci API bodap (dipakai saat memanggil /ollama/chat)
 *   SM_WA_ENABLED   "1" nyala (bawaan "1")
 *
 * Titik akhir HTTP lokal bridge (hanya dijamin localhost):
 *   GET  /status              status sambungan + nomor
 *   GET  /qr                  PNG kode QR pairing (bila menunggu)
 *   POST /send                { no, teks } — kirim pesan keluar (butuh X-API-Key)
 *   POST /test/inbound        { dari, teks } — simulasi masuk (butuh X-API-Key)
 *   POST /reconnect                       — paksa sambung ulang (butuh X-API-Key)
 *   POST /reset               { no } — kosongkan riwayat nomor (butuh X-API-Key)
 */

"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");

/** Logger untuk Baileys (pino sudah dibawa oleh baileys). */
let log;
try {
  const pino = require("pino");
  log = pino({ level: process.env.SM_WA_LOG || "warn" });
} catch {
  log = { child: () => log, debug() {}, info() {}, warn() {}, error() {}, trace() {}, fatal() {}, level: "warn" };
}

const PORT = parseInt(process.env.SM_WA_PORT || "8799", 10);
const BASE_URL = (process.env.SM_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const API_KEY = process.env.SM_API_KEY || "";
if (!API_KEY) {
  console.warn("[wa-bridge] PERINGATAN: SM_API_KEY kosong — pasang kunci API di pengaturan bodap.");
}
const WA_DIR = process.env.SM_WA_DIR || path.join(__dirname, ".session");
const ENABLED = (process.env.SM_WA_ENABLED || "1") === "1";
const MODE_UJI = (process.env.SM_WA_NO_CONNECT || "") === "1";
// Self-chat: bot membalas pesan yang diketik ke diri sendiri.
// ALLOW_SELF: proses pesan fromMe di self-chat (bawaan "1").
// HANYA_DIRI: hanya balas self-chat, lewati pesan dari nomor lain (bawaan "1").
const ALLOW_SELF = (process.env.SM_WA_ALLOW_SELF || "1") === "1";
const HANYA_DIRI = (process.env.SM_WA_HANYA_DIRI || "1") === "1";

const HISTORY_FILE = path.join(WA_DIR, "riwayat.json");
// Lock satu-instance: hanya SATU proses bridge per session WhatsApp. Dua
// proses akan saling mengeluarkan (loggedOut berulang → harus scan QR lagi).
const LOCK_FILE = path.join(WA_DIR, "bridge.lock");

/** Status sambungan — disimpan di sini agar rute /status bisa baca. */
const status = {
  siap: false,
  terhubung: false,
  menunggu_pairing: false,
  nomor: "",
  pesan: "",
  terakhir: "",
  error: "",
};

let sock = null;
let qrBaru = "";
let history = {};
let ownJid = "";
// LID: WhatsApp versi baru memakai @lid untuk chat ke diri sendiri.
// Simpan LID sendiri agar self-chat via @lid tetap terdeteksi.
let ownLid = "";
// Tanda jawaban bot — anti-echo kokoh: pesan yang diawali tanda ini
// dilewati, dan mudah dibedakan dari ketikan pengguna di layar HP.
const TANDA = "\u{1F916} "; // 🤖
// Penjaga reconnect: hanya satu jadwal sambung ulang, hindari tumpukan
// socket/listener (MaxListenersExceededWarning).
let sedangSambungUlang = false;
let tugasReconnect = null;

/** ID pesan yang baru kita kirim — dipakai anti-echo (jangan membalik balasan kita). */
const _sentIds = new Map();

function catatTerkirim(msg) {
  if (!msg || !msg.key || !msg.key.id) return;
  _sentIds.set(msg.key.id, Date.now());
}

function adalahEcho(id) {
  if (!id) return false;
  const t = _sentIds.get(id);
  if (!t) return false;
  if (Date.now() - t > 60000) { _sentIds.delete(id); return false; }
  return true;
}

/** Kirim pesan dan catat ID-nya supaya echo-nya dilewati. */
async function kirimDanCatat(no, teks) {
  if (!sock) return;
  const terkirim = await sock.sendMessage(no, { text: teks });
  catatTerkirim(terkirim);
}

/** Normalisasi JID: hapus sufiks ":device" (62812xxx:12@... -> 62812xxx@...). */
function normJid(jid) {
  return String(jid || "").replace(/:\d+@/, "@");
}

/**
 * Apakah dua JID menunjuk nomor yang sama?
 * Bandingkan bagian **nomor** (sebelum @), mengabaikan domain
 * (@s.whatsapp.net / @lid) dan sufiks device (:12). Nomor adalah identitas
 * yang sama untuk @s.whatsapp.net dan @lid.
 */
function nomorSama(a, b) {
  const na = String(a || "").replace(/:\d+@/, "@").split("@")[0];
  const nb = String(b || "").replace(/:\d+@/, "@").split("@")[0];
  return na !== "" && na === nb;
}

/**
 * Apakah JID adalah **diri sendiri**? Cek nomor telepon (ownJid) DAN LID
 * (ownLid) — chat ke diri sendiri bisa datang sebagai @s.whatsapp.net atau
 * @lid, keduanya harus terdeteksi.
 */
function adalahDiriSendiri(jid) {
  return nomorSama(jid, ownJid) || (!!ownLid && nomorSama(jid, ownLid));
}

/** Apakah JID adalah nomor pribadi WhatsApp (personal, bukan grup). */
function adalahNomorPribadi(jid) {
  return /@(s\.whatsapp\.net|lid)$/.test(String(jid || ""));
}

/**
 * Apakah pesan ini harus diproses (dijawab)?
 * Kebijakan ketat: **Ollama hanya membalas chat ke diri sendiri** (HANYA_DIRI).
 * - echo balasan kita sendiri (dariMe true, id terkirim): lewati (anti-loop).
 * - pesan keluar ke chat orang lain (dariMe true, bukan ownJid): lewati.
 * - self-chat (dariMe true, remoteJid = ownJid, bukan echo): proses bila ALLOW_SELF.
 * - pesan dari orang lain (dariMe false): **lewati** bila HANYA_DIRI (bawaan).
 */
function bolehProses(msg) {
  if (!msg || !msg.key) return false;
  const dari = msg.key.remoteJid;
  const dariSaya = !!msg.key.fromMe;
  if (dariSaya && adalahEcho(msg.key.id)) return false;
  // Pesan dari luar (bukan kita): tolak bila mode hanya-diri.
  if (!dariSaya) {
    if (HANYA_DIRI) return false;
    return adalahNomorPribadi(dari);
  }
  // Pesan keluar: hanya self-chat (remoteJid = diri sendiri, via nomor atau
  // LID) yang diproses.
  if (!ALLOW_SELF || !ownJid && !ownLid) {
    console.log("[wa-bridge] dilewati (bukan self-chat):", dari, "own:", ownJid, ownLid);
    return false;
  }
  if (!adalahDiriSendiri(dari)) {
    console.log("[wa-bridge] dilewati (bukan self-chat):", dari, "own:", ownJid, ownLid);
    return false;
  }
  return true;
}

function bacaRiwayat() {
  try {
    history = JSON.parse(fs.readFileSync(HISTORY_FILE, "utf8")) || {};
  } catch {
    history = {};
  }
}

function simpanRiwayat() {
  try {
    fs.writeFileSync(HISTORY_FILE, JSON.stringify(history), "utf8");
  } catch (e) {
    console.error("riwayat tidak tersimpan:", e.message);
  }
}

function ambilRiwayat(no) {
  const daftar = history[no] || [];
  return daftar.slice(-20); // BATAS_RIWAYAT sejalan dengan app
}

function catatRiwayat(peran, no, isi) {
  if (!no || !isi) return;
  history[no] = ambilRiwayat(no).concat([{ role: peran, content: String(isi) }]);
  simpanRiwayat();
}

/** Panggil bodap /ollama/chat → jawaban. Riwayat disampaikan agar tidak dobel. */
async function tanyaBodap(teks, no, riwayat) {
  const daftar = Array.isArray(riwayat) ? riwayat : rapihkanRiwayat(no);
  const respons = await fetch(`${BASE_URL}/ollama/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    // Batas waktu: Ollama 3B di CPU bisa lama; jangan biarkan antrean mandek.
    signal: AbortSignal.timeout(600000),
    body: JSON.stringify({ pesan: teks, riwayat: daftar, sumber: "wa" }),
  });
  const isi = await respons.json().catch(() => ({}));
  if (!respons.ok) {
    return { ok: false, jawaban: `Galat dari bodap: ${isi.detail || respons.status}` };
  }
  return {
    ok: true,
    jawaban: String(isi.jawaban || "(bodap tidak memberikan jawaban)"),
  };
}

/** Urutkan riwayat untuk model: hanya user/assistant. */
function rapihkanRiwayat(no) {
  return ambilRiwayat(no)
    .filter((s) => (s.role === "user" || s.role === "assistant") && s.content)
    .map((s) => ({ role: s.role, content: s.content }));
}

/** Pecah teks panjang agar tidak melampaui batas WhatsApp (~4096 karakter). */
function potongPesan(teks, batas = 3800) {
  const s = String(teks || "");
  if (s.length <= batas) return [s];
  const bagian = [];
  // Pecah di batas, usahakan di baris baru.
  let sisa = s;
  while (sisa.length > batas) {
    let potong = sisa.slice(0, batas);
    const idx = potong.lastIndexOf("\n");
    if (idx > batas * 0.5) potong = potong.slice(0, idx);
    bagian.push(potong.trim());
    sisa = sisa.slice(potong.length).replace(/^\n+/, "");
  }  if (sisa.trim()) bagian.push(sisa.trim());
  return bagian;
}

/** Kirim pesan (mungkin beberapa bagian) dan catat ID-nya (anti-echo). */
async function kirimPotong(no, teks) {
  if (!sock) return;
  const potongan = potongPesan(teks);
  for (let i = 0; i < potongan.length; i++) {
    if (i > 0) await sleep(600); // jeda antar bagian agar rapi
    // Prefix TANDA: anti-echo kokoh + mudah dibedakan dari ketikan pengguna.
    const terkirim = await sock.sendMessage(no, { text: TANDA + potongan[i] });
    catatTerkirim(terkirim);
  }
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

/** Menangani satu pesan masuk dari WhatsApp → tanya bodap → balas. */
async function tanganiPesan(dari, teks) {
  if (!ENABLED) {
    return { ok: false, jawaban: "WhatsApp belum siap." };
  }
  // Bila belum terhubung (dan bukan mode uji) — jangan tanya bodap tanpa
  // bisa mengirim balasannya.
  if (!sock && !MODE_UJI) {
    return { ok: false, jawaban: "WhatsApp belum siap." };
  }
  teks = String(teks || "").trim();
  if (!teks) {
    return { ok: false, jawaban: "" };
  }
  status.terakhir = `${dari}: ${teks.slice(0, 40)}`;
  // Perintah reset: kosongkan riwayat nomor (3B cepat kacau bila riwayat panjang).
  if (teks.trim().toLowerCase() === "/reset") {
    history[dari] = [];
    simpanRiwayat();
    const ack = "Riwayat percakapan untuk nomor ini sudah dikosongkan.";
    catatRiwayat("assistant", dari, ack);
    await kirimPotong(dari, ack);
    return { ok: true, jawaban: ack };
  }
  let hasil;
  try {
    // Riwayat DIAMBIL SEBELUM mencatat pesan user — agar tidak dobel.
    const riwayatBersih = rapihkanRiwayat(dari);
    // Indikator «mengetik» yang bertahan: 3B di CPU bisa 20–60 detik,
    // perbarui composing berkala supaya pengguna tahu bot sedang berpikir.
    const pengetik = setInterval(() => {
      if (sock && typeof sock.sendPresenceUpdate === "function") {
        sock.sendPresenceUpdate("composing", dari).catch(() => {});
      }
    }, 8000);
    try {
      hasil = await tanyaBodap(teks, dari, riwayatBersih);
      if (hasil.ok && hasil.jawaban) {
        // Catat hanya setelah berhasil — pesan gagal tidak mengotori riwayat.
        catatRiwayat("user", dari, teks);
        // Simpan jawaban di riwayat TANPA TANDA (agar model tidak melihat
        // prefix 🤖); TANDA hanya untuk tampilan di chat.
        catatRiwayat("assistant", dari, hasil.jawaban.replace(TANDA, "").trim());
        await kirimPotong(dari, hasil.jawaban);
      } else if (hasil.ok) {
        const ganti = "Saya belum bisa menjawab pertanyaan itu. Coba tanyakan hal lain, " +
          "atau ulangi pertanyaannya.";
        catatRiwayat("user", dari, teks);
        catatRiwayat("assistant", dari, ganti);
        await kirimPotong(dari, ganti);
      } else {
        // Galat — jangan masuk riwayat, balas jujur.
        await kirimPotong(dari, hasil.jawaban);
      }
    } finally {
      clearInterval(pengetik);
      if (sock && typeof sock.sendPresenceUpdate === "function") {
        try { await sock.sendPresenceUpdate("paused", dari); } catch {}
      }
    }
  } catch (e) {
    console.error("tanganiPesan gagal:", e);
    status.error = String(e && e.message || e);
    hasil = { ok: false, jawaban: "Ada kesalahan sementara. Coba lagi nanti." };
    await kirimPotong(dari, hasil.jawaban);
  }
  return hasil;
}

// --------------------------------------------------------------------------- //
// HTTP lokal
// --------------------------------------------------------------------------- //
function bacaBadan(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (c) => { data += c; if (data.length > 2_000_000) req.destroy(); });
    req.on("end", () => { try { resolve(JSON.parse(data || "{}")); } catch { resolve({}); } });
    req.on("error", () => resolve({}));
  });
}

function kirim(res, kode, isi, tipe = "application/json") {
  const tubuh = typeof isi === "string" ? isi : JSON.stringify(isi || {});
  res.writeHead(kode, { "Content-Type": tipe, "Content-Length": Buffer.byteLength(tubuh) });
  res.end(tubuh);
}

/** Cek kunci API untuk rute yang mengubah/memancing keluaran. */
function autentikasi(req) {
  const kunci = req.headers["x-api-key"] || "";
  return !!API_KEY && kunci === API_KEY;
}

async function jawabRute(req, res) {
  const url = new URL(req.url, "http://localhost");
  const jalan = url.pathname;
  try {
    if (req.method === "GET" && jalan === "/status") {
      return kirim(res, 200, { ...status, enabled: ENABLED });
    }
    // Akses langsung root: beri info ramah (bukan 404 membingungkan).
    if (req.method === "GET" && jalan === "/") {
      return kirim(res, 200, {
        ok: true,
        bridge: "sm-wa-bridge",
        titik_akhir: ["/status", "/qr", "/reconnect", "/send", "/test/inbound"],
        ...status, enabled: ENABLED,
      });
    }
    if (req.method === "GET" && jalan === "/qr") {
      if (!qrBaru) {
        return kirim(res, 404, { detail: "Tidak ada kode QR saat ini (mungkin sudah terhubung)." });
      }
      const QRCode = require("qrcode");
      const png = await QRCode.toBuffer(qrBaru, { type: "png", width: 320, margin: 1 });
      res.writeHead(200, { "Content-Type": "image/png", "Content-Length": png.length });
      return res.end(png);
    }
    if (req.method === "POST" && jalan === "/reconnect") {
      if (!autentikasi(req)) return kirim(res, 401, { detail: "Kunci API tidak valid." });
      // Paksa sambung ulang: batalkan jadwal, tutup socket, jalankan ulang
      // agar Baileys menghasilkan kode QR pairing yang segar.
      jikaReconnectCancel();
      try {
        if (sock) {
          sock.ev.removeAllListeners();
          if (typeof sock.end === "function") sock.end();
          else if (typeof sock.endSocket === "function") sock.endSocket();
        }
      } catch {} // abaikan kesalahan penutupan
      sock = null;
      qrBaru = "";
      status.terhubung = false;
      status.siap = false;
      status.menunggu_pairing = false;
      status.pesan = "Meminta sambung ulang — kode QR akan muncul sebentar lagi.";
      console.log("[wa-bridge] /reconnect — menyambung ulang untuk QR baru.");
      sambungkan();
      return kirim(res, 200, { ok: true, detail: "Sambung ulang diminta — QR akan muncul." });
    }
    if (req.method === "POST" && jalan === "/send") {
      if (!autentikasi(req)) return kirim(res, 401, { detail: "Kunci API tidak valid." });
      const badan = await bacaBadan(req);
      const no = String(badan.no || "").trim();
      const teks = String(badan.teks || "");
      if (!no || !teks) return kirim(res, 400, { detail: "no dan teks wajib." });
      if (!sock || !status.terhubung) {
        return kirim(res, 503, { detail: "WhatsApp belum terhubung — pasangkan dulu (lihat halaman /wa)." });
      }
      try {
        const terkirim = await sock.sendMessage(no, { text: teks });
        catatTerkirim(terkirim);
        return kirim(res, 200, { ok: true });
      } catch (e) {
        return kirim(res, 503, { detail: "Gagal mengirim: " + (e && e.message || e) });
      }
    }
    if (req.method === "POST" && jalan === "/test/inbound") {
      if (!autentikasi(req)) return kirim(res, 401, { detail: "Kunci API tidak valid." });
      // Uji tanpa WhatsApp sungguhan: simulasi pesan masuk.
      const badan = await bacaBadan(req);
      const dari = String(badan.dari || "uji@s.wa");
      const teks = String(badan.teks || "");
      const hasil = await tanganiPesan(dari, teks);
      return kirim(res, 200, hasil);
    }
    if (req.method === "POST" && jalan === "/reset") {
      if (!autentikasi(req)) return kirim(res, 401, { detail: "Kunci API tidak valid." });
      const badan = await bacaBadan(req);
      const no = String(badan.no || "").trim();
      if (!no) return kirim(res, 400, { detail: "no wajib." });
      history[no] = [];
      simpanRiwayat();
      return kirim(res, 200, { ok: true, detail: `Riwayat ${no} dikosongkan.` });
    }
    return kirim(res, 404, { detail: "Titik akhir tidak ada." });
  } catch (e) {
    console.error("rute HTTP gagal:", e);
    return kirim(res, 500, { detail: String(e && e.message || e) });
  }
}

const server = http.createServer(jawabRute);
if (require.main === module) {
  server.listen(PORT, "127.0.0.1", () => {
    console.log(`[wa-bridge] HTTP lokal: http://127.0.0.1:${PORT}`);
    console.log(`[wa-bridge] bodap: ${BASE_URL} | enabled=${ENABLED}`);
  });
}

// --------------------------------------------------------------------------- //
// Sambungan WhatsApp (Baileys)
// --------------------------------------------------------------------------- //
/** Hapus SEMUA isi WA_DIR kecuali riwayat.json — pairing ulang bersih. */
function hapusSession() {
  try {
    if (!fs.existsSync(WA_DIR)) return;
    for (const f of fs.readdirSync(WA_DIR)) {
      if (f === path.basename(HISTORY_FILE)) continue; // pertahankan riwayat
      try { fs.rmSync(path.join(WA_DIR, f), { recursive: true, force: true }); } catch {}
    }
    console.log("[wa-bridge] Session lama dihapus — butuh QR pairing baru.");
  } catch (e) {
    console.error("[wa-bridge] hapus session gagal:", e && e.message);
  }
}

/**
 * Jadwalkan sambung ulang — hanya SATU yang berjalan, hindari tumpukan
 * socket/listener (MaxListenersExceededWarning).
 * @param {boolean} bersihkanSession benar=hapus kredensial (session loggedOut).
 */
function jadwalkanReconnect(bersihkanSession) {
  if (sedangSambungUlang) return; // sudah ada jadwal — jangan menumpuk
  sedangSambungUlang = true;
  tugasReconnect = setTimeout(async () => {
    tugasReconnect = null;
    sedangSambungUlang = false;
    try {
      if (sock) {
        sock.ev.removeAllListeners();
        if (typeof sock.end === "function") await sock.end();
        else if (typeof sock.endSocket === "function") await sock.endSocket();
      }
    } catch {} // abaikan kesalahan penutupan
    sock = null;
    if (bersihkanSession) hapusSession();
    sambungkan();
  }, 2000);
}

/** Batalkan jadwal sambung ulang yang tertunda (saat sudah terhubung). */
function jikaReconnectCancel() {
  if (tugasReconnect) {
    clearTimeout(tugasReconnect);
    tugasReconnect = null;
  }
  sedangSambungUlang = false;
}

/**
 * Akui lock satu-instance. Bila ada proses lain yang hidup dengan session
 * sama, hentikan diri (agar tidak saling mengeluarkan → loggedOut).
 * @returns {boolean} true bila lock berhasil dikuasai.
 */
function akuiLock() {
  try {
    fs.mkdirSync(WA_DIR, { recursive: true });
    if (fs.existsSync(LOCK_FILE)) {
      let lain = 0;
      try { lain = parseInt(fs.readFileSync(LOCK_FILE, "utf8").trim(), 10) || 0; }
      catch { lain = 0; }
      if (lain > 0 && lain !== process.pid && hidup(lain)) {
        console.error("[wa-bridge] Lock ada — proses lain (PID " + lain +
          ") memakai session ini. Henti diri untuk hindari konflik.");
        process.exit(1);
      }
    }
    fs.writeFileSync(LOCK_FILE, String(process.pid), "utf8");
    return true;
  } catch (e) {
    console.error("[wa-bridge] lock gagal:", e && e.message);
    return false;
  }
}

/** Apakah PID masih hidup? */
function hidup(pid) {
  try {
    process.kill(pid, 0); // sinyal 0 = hanya cek keberadaan
    return true;
  } catch {
    return false;
  }
}

/** Lepas lock saat proses berhenti. */
function lepasLock() {
  try { if (fs.existsSync(LOCK_FILE)) fs.unlinkSync(LOCK_FILE); } catch {}
}

process.on("exit", lepasLock);
process.on("SIGINT", () => { lepasLock(); process.exit(0); });
process.on("SIGTERM", () => { lepasLock(); process.exit(0); });

async function sambungkan() {
  if (!ENABLED) {
    status.siap = false;
    status.pesan = "Dimatikan di pengaturan.";
    return;
  }
  // Mode uji: HTTP jalan tanpa menyambung ke WhatsApp (untuk pengujian offline).
  if (process.env.SM_WA_NO_CONNECT === "1") {
    status.siap = true;
    status.terhubung = false;
    status.menunggu_pairing = false;
    status.pesan = "Mode uji (tanpa sambungan WhatsApp).";
    console.log("[wa-bridge] Mode uji — HTTP jalan, WhatsApp tidak disambung.");
    return;
  }
  // Satu instance per session: bila ada proses lain hidup, henti diri.
  if (!akuiLock()) {
    status.siap = false;
    status.pesan = "Lock session diambil proses lain — henti diri.";
    return;
  }
  let baileys;
  try {
    baileys = require("@whiskeysockets/baileys");
  } catch (e) {
    status.error = "Baileys tidak terpasang (npm install di wa-bridge).";
    console.error("[wa-bridge] " + status.error, e.message);
    return;
  }
  const { makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = baileys;
  fs.mkdirSync(WA_DIR, { recursive: true });
  bacaRiwayat();

  try {
    // fetchLatestBaileysVersion() perlu internet; bila gagal, JANGAN pakai
    // [0,0,0] (versi invalid — Baileys gagal berpasangan, tidak ada QR).
    // Biarkan Baileys memakai versi bawaannya.
    let version;
    try {
      const vs = await fetchLatestBaileysVersion();
      version = vs.version;
      console.log("[wa-bridge] Versi Baileys:", JSON.stringify(version));
    } catch (e) {
      console.warn("[wa-bridge] fetch versi gagal — pakai versi bawaan Baileys:", e.message);
    }
    const { state, saveCreds } = await useMultiFileAuthState(WA_DIR);
    const sockConfig = {
      auth: state,
      logger: log,
      browser: ["SM", "Desktop", "1.0.0"],
    };
    if (version) sockConfig.version = version;
    sock = makeWASocket(sockConfig);

    sock.ev.on("connection.update", (update) => {
      const { connection, qr, lastDisconnect, error } = update;
      if (qr) {
        qrBaru = Array.isArray(qr) ? qr[0] : String(qr);
        status.menunggu_pairing = true;
        status.terhubung = false;
        status.pesan = "Scan kode QR ini dengan WhatsApp di HP (Menu: Perangkat Tertaut).";
        console.log("[wa-bridge] QR pairing tersedia — minta admin scan.");
      }
      if (connection === "open") {
        // Koneksi stabil: hapus jadwal reconnect yang tertunda.
        jikaReconnectCancel();
        qrBaru = "";
        status.terhubung = true;
        status.menunggu_pairing = false;
        status.siap = true;
        ownJid = normJid((sock.user && sock.user.id) || status.nomor || "");
        ownLid = normJid((sock.user && sock.user.lid) || "");
        status.nomor = ownJid;
        console.log("[wa-bridge] ownJid:", ownJid, "| ownLid:", ownLid || "—");
        status.pesan = `Terhubung sebagai ${status.nomor || "—"}.`;
        console.log("[wa-bridge] WhatsApp terhubung:", status.nomor);
      }
      if (connection === "close") {
        status.terhubung = false;
        status.siap = false;
        const code = lastDisconnect && lastDisconnect.error && lastDisconnect.error.output &&
          lastDisconnect.error.output.statusCode;
        if (code === DisconnectReason.loggedOut) {
          status.pesan = "Keluar dari WhatsApp — pasangkan ulang (QR akan muncul).";
          console.log("[wa-bridge] Keluar (loggedOut) — hapus session dan sambung ulang.");
          // Session lama tidak valid: hapus kredensial + session agar pairing
          // ulang bersih, lalu sambung ulang untuk memunculkan QR baru.
          jadwalkanReconnect(true); // hapus session + sambung ulang
        } else {
          status.pesan = "Sambungan terputus — mencoba menyambung lagi.";
          console.log("[wa-bridge] Terputus (code " + (code || "?") + ") — menyambung lagi.");
          // Jangan menumpuk koneksi: satu jadwal sambung ulang saja.
          jadwalkanReconnect(false);
        }
      }
      if (error) {
        console.error("[wa-bridge] connection.update error:", error.message || error);
      }
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("messages.upsert", async ({ messages, type }) => {
      if (type !== "notify") return;
      for (const msg of messages) {
        if (!msg || !bolehProses(msg)) continue;
        const dari = msg.key.remoteJid;
        // Batasan waktu: abaikan pesan lama (>2 menit) — saat reconnect
        // WhatsApp bisa mengirim ulang pesan lama, bot tidak boleh jawab
        // pertanyaan kemarin.
        const ts = Number(msg.messageTimestamp || 0);
        if (ts && Date.now() / 1000 - ts > 120) continue;
        // Ekstrak teks: pesan sementara (ephemeral) membungkus teks di
        // ephemeralMessage.message — ambil dari dalamnya dulu.
        const isi = (msg.message && msg.message.ephemeralMessage &&
                     msg.message.ephemeralMessage.message) || msg.message || {};
        let teks =
          isi.conversation ||
          (isi.extendedTextMessage && isi.extendedTextMessage.text) ||
          "";
        if (!teks) continue; // bukan teks (gambar/suara) — abaikan
        // Anti-echo kokoh: abaikan balasan bot sendiri (diawali TANDA).
        if (teks.startsWith(TANDA)) continue;
        // Jawab secara berurutan agar tidak membebani Ollama.
        queue(() => tanganiPesan(dari, teks));
      }
    });
  } catch (e) {
    status.error = String(e && e.message || e);
    console.error("[wa-bridge] sambungkan gagal:", e);
  }
}

/** Antrean sederhana — satu pesan selesai dulu sebelum berikutnya. */
let antrian = Promise.resolve();
function queue(tugas) {
  const berikut = antrian.then(() => tugas());
  antrian = berikut.catch(() => {});
  return berikut;
}


// Bersihkan _sentIds lama (hindari pertumbuhan tanpa batas).
setInterval(() => {
  const kini = Date.now();
  for (const [id, t] of _sentIds) if (kini - t > 120000) _sentIds.delete(id);
}, 60000);

// Jaga: sambungan WhatsApp yang gagal jangan mematikan HTTP server.
// Catatan: hanya SATU perangkat boleh menjalankan bridge dengan session
// yang sama — dua proses akan saling mengeluarkan (loggedOut berulang).
process.on("uncaughtException", (e) => { console.error("[wa-bridge] uncaught:", e && e.message); });
process.on("unhandledRejection", (e) => { console.error("[wa-bridge] unhandled:", e && e.message); });

if (require.main === module) {
  sambungkan();
}

module.exports = {
  bolehProses, catatTerkirim, adalahEcho, _sentIds,
  normJid, nomorSama, adalahNomorPribadi, potongPesan,
  setOwnJid: (v) => { ownJid = v; },
  setOwnJidRaw: (v) => { ownJid = normJid(v); },
  getOwnJid: () => ownJid,
  ALLOW_SELF, HANYA_DIRI, TANDA,
  getOwnLid: () => ownLid,
  setOwnLid: (v) => { ownLid = normJid(v); },
  adalahDiriSendiri,
};
