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
 *   SM_API_KEY      kunci API bodap (dipakai saat memanggil balik)
 *   SM_WA_ENABLED   "1" nyala (bawaan "1")
 *
 * Titik akhir HTTP lokal bridge (hanya dijamin localhost):
 *   GET  /status              status sambungan + nomor
 *   GET  /qr                  PNG kode QR pairing (bila menunggu)
 *   POST /send                { no, teks } — kirim pesan keluar
 *   POST /test/inbound        { dari, teks } — simulasi masuk (untuk uji)
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
const WA_DIR = process.env.SM_WA_DIR || path.join(__dirname, ".session");
const ENABLED = (process.env.SM_WA_ENABLED || "1") === "1";
const MODE_UJI = (process.env.SM_WA_NO_CONNECT || "") === "1";

const HISTORY_FILE = path.join(WA_DIR, "riwayat.json");

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

/** Panggil bodap /ollama/chat → jawaban. */
async function tanyaBodap(teks, no) {
  const riwayat = ambilRiwayat(no);
  const respons = await fetch(`${BASE_URL}/ollama/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify({ pesan: teks, riwayat, sumber: "wa" }),
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
  // Pesan teks WhatsApp sering memakai « » atau format lain; ambil teksnya.
  status.terakhir = `${dari}: ${teks.slice(0, 40)}`;
  let hasil;
  try {
    // Catat dulu pertanyaan pengguna untuk riwayat.
    catatRiwayat("user", dari, teks);
    // Gunakan riwayat yang sudah dicatatkan.
    const riwayatBersih = rapihkanRiwayat(dari);
    // Tanya bodap dengan riwayat bersih (tanyaBodap mengambil lagi dari file).
    hasil = await tanyaBodap(teks, dari);
    if (hasil.ok && hasil.jawaban) {
      catatRiwayat("assistant", dari, hasil.jawaban);
      if (sock) await sock.sendMessage(dari, { text: hasil.jawaban });
    } else if (hasil.ok) {
      // Bodap tidak memberi jawaban — balas jujur.
      const ganti = "Saya belum bisa menjawab pertanyaan itu. Coba tanyakan hal lain, " +
        "atau ulangi pertanyaannya.";
      catatRiwayat("assistant", dari, ganti);
      if (sock) await sock.sendMessage(dari, { text: ganti });
    } else {
      if (sock) await sock.sendMessage(dari, { text: hasil.jawaban });
    }
  } catch (e) {
    console.error("tanganiPesan gagal:", e);
    status.error = String(e && e.message || e);
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

async function jawabRute(req, res) {
  const url = new URL(req.url, "http://localhost");
  const jalan = url.pathname;
  try {
    if (req.method === "GET" && jalan === "/status") {
      return kirim(res, 200, { ...status, enabled: ENABLED });
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
    if (req.method === "POST" && jalan === "/send") {
      const badan = await bacaBadan(req);
      const no = String(badan.no || "").trim();
      const teks = String(badan.teks || "");
      if (!no || !teks) return kirim(res, 400, { detail: "no dan teks wajib." });
      if (!sock) return kirim(res, 503, { detail: "WhatsApp belum terhubung." });
      await sock.sendMessage(no, { text: teks });
      return kirim(res, 200, { ok: true });
    }
    if (req.method === "POST" && jalan === "/test/inbound") {
      // Uji tanpa WhatsApp sungguhan: simulasi pesan masuk.
      const badan = await bacaBadan(req);
      const dari = String(badan.dari || "uji@s.wa");
      const teks = String(badan.teks || "");
      const hasil = await tanganiPesan(dari, teks);
      return kirim(res, 200, hasil);
    }
    return kirim(res, 404, { detail: "Titik akhir tidak ada." });
  } catch (e) {
    console.error("rute HTTP gagal:", e);
    return kirim(res, 500, { detail: String(e && e.message || e) });
  }
}

const server = http.createServer(jawabRute);
server.listen(PORT, "127.0.0.1", () => {
  console.log(`[wa-bridge] HTTP lokal: http://127.0.0.1:${PORT}`);
  console.log(`[wa-bridge] bodap: ${BASE_URL} | enabled=${ENABLED}`);
});

// --------------------------------------------------------------------------- //
// Sambungan WhatsApp (Baileys)
// --------------------------------------------------------------------------- //
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
    // fetchLatestBaileysVersion() perlu internet; bila gagal pakai versi bawaan.
    let version = [0, 0, 0];
    try {
      const vs = await fetchLatestBaileysVersion();
      version = vs.version;
    } catch (e) {
      console.warn("[wa-bridge] fetch versi gagal, pakai bawaan:", e.message);
    }
    const { state, saveCreds } = await useMultiFileAuthState(WA_DIR);
    sock = makeWASocket({
      version,
      auth: state,
      logger: log,
      browser: ["SM", "Desktop", "1.0.0"],
    });

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
        qrBaru = "";
        status.terhubung = true;
        status.menunggu_pairing = false;
        status.siap = true;
        status.nomor = (sock.user && sock.user.id) || status.nomor || "";
        status.pesan = `Terhubung sebagai ${status.nomor || "—"}.`;
        console.log("[wa-bridge] WhatsApp terhubung:", status.nomor);
      }
      if (connection === "close") {
        status.terhubung = false;
        status.siap = false;
        const code = lastDisconnect && lastDisconnect.error && lastDisconnect.error.output &&
          lastDisconnect.error.output.statusCode;
        if (code === DisconnectReason.loggedOut) {
          status.pesan = "Keluar dari WhatsApp — pasangkan ulang.";
          console.log("[wa-bridge] Keluar (loggedOut).");
        } else {
          status.pesan = "Sambungan terputus — mencoba menyambung lagi.";
          console.log("[wa-bridge] Terputus (code " + (code || "?") + ") — menyambung lagi.");
          setTimeout(sambungkan, 2000);
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
        if (!msg || msg.key.fromMe) continue;
        const dari = msg.key.remoteJid;
        if (!dari || dari.endsWith("@g.us") || dari.endsWith("@s.whatsapp.net") === false) {
          // hanya grup/personal whatsapp; lewati grup (bisa dibuka nanti)
        }
        const teks =
          (msg.message && msg.message.conversation) ||
          (msg.message && msg.message.extendedTextMessage &&
            msg.message.extendedTextMessage.text) ||
          "";
        if (!teks) continue; // bukan teks (gambar/suara) — abaikan
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

// Simpan session secara berkala.
setInterval(() => { try { if (sock) sock.ev.emit("creds.update"); } catch {} }, 60_000);

// Jaga: sambungan WhatsApp yang gagal jangan mematikan HTTP server.
process.on("uncaughtException", (e) => { console.error("[wa-bridge] uncaught:", e && e.message); });
process.on("unhandledRejection", (e) => { console.error("[wa-bridge] unhandled:", e && e.message); });

sambungkan();
