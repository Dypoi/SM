#!/usr/bin/env python3
"""Melihat & mengukur tampilan lewat peramban sungguhan (Chromium headless).

Skrip ini menghubungi peramban yang sudah dibuka dengan pengawas jarak jauh
(DevTools Protocol), lalu:

* ``--potret``  memotret satu halaman jadi berkas PNG (seluruh halaman), dan
* ``--ukur``    mengukur **letak setiap ikon**: apakah tepat di tengah kotaknya,
                sejajar dengan teks di sebelahnya, dan ukurannya masuk akal.

Kenapa perlu?  Pemeriksaan HTML (`cek_tampilan.py`) hanya membaca susunan tag.
Pertanyaan «ikonnya sudah pas atau belum» baru bisa dijawab dengan mengukur
kotak nyata di peramban.

Menyalakan peramban lebih dulu (sekali saja)::

    npm i @sparticuz/chromium          # sekali, di folder mana pun
    node -e "import('@sparticuz/chromium').then(async m=>console.log(await m.default.executablePath()))"
    LD_LIBRARY_PATH=/tmp/al2023/lib /tmp/chromium --headless --no-sandbox \\
        --disable-gpu --disable-dev-shm-usage --hide-scrollbars \\
        --remote-debugging-port=9222 --user-data-dir=/tmp/cdp-profile about:blank

Contoh pemakaian::

    .venv/bin/python scripts/lihat_tampilan.py --potret /login?mode=siswa
    .venv/bin/python scripts/lihat_tampilan.py --ukur /login?mode=siswa --halaman /portal/ekstrakurikuler
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

BASE = Path(__file__).resolve().parent.parent

# Ukuran kotak ikon yang dipakai makro `icon()` (lihat _macros.html).
UKURAN_IKON = 18  # px, bawaan `.icon`
TOLERANSI = 1.5  # px, beda pusat yang masih dianggap pas


class GalatPeramban(RuntimeError):
    """Peramban pengawas tidak bisa dipakai."""


class Sesi:
    """Percakapan sederhana dengan satu tab peramban (DevTools Protocol)."""

    def __init__(self, alamat_ws: str) -> None:
        import websocket  # websocket-client

        try:
            self.ws = websocket.create_connection(
                alamat_ws, suppress_origin=True, timeout=60, max_size=256 * 1024 * 1024)
        except OSError as galat:  # pragma: no cover - tergantung lingkungan
            raise GalatPeramban(f"Tidak bisa menyambung ke peramban: {galat}") from galat
        self.nomor = 0

    def panggil(self, metode: str, **param):
        self.nomor += 1
        self.ws.send(json.dumps({"id": self.nomor, "method": metode, "params": param}))
        while True:
            pesan = json.loads(self.ws.recv())
            if pesan.get("id") == self.nomor:
                if "error" in pesan:
                    raise GalatPeramban(f"{metode}: {pesan['error'].get('message')}")
                return pesan.get("result", {})

    def nilai(self, skrip: str, tunggu: bool = True):
        """Jalankan JavaScript dan kembalikan nilainya (dari `return skrip`)."""
        hasil = self.panggil("Runtime.evaluate", expression=skrip,
                             returnByValue=True, awaitPromise=tunggu)
        if hasil.get("exceptionDetails"):
            pesan = hasil["exceptionDetails"].get("exception", {}).get("description")
            raise GalatPeramban(f"JavaScript gagal: {pesan}")
        return hasil.get("result", {}).get("value")

    def tutup(self) -> None:
        try:
            self.ws.close()
        except Exception:  # pragma: no cover - pembereskan
            pass


def tab_baru(port: int, url: str) -> str:
    """Minta peramban membuka tab baru, kembalikan alamat websocket-nya."""
    alamat = f"http://127.0.0.1:{port}/json/new?{url}"
    try:
        with urlopen(alamat, timeout=30) as jawaban:  # butuh metode PUT di Chromium baru
            data = json.load(jawaban)
    except (URLError, OSError):
        from urllib.request import Request

        try:
            with urlopen(Request(alamat, method="PUT"), timeout=30) as jawaban:
                data = json.load(jawaban)
        except (URLError, OSError) as galat:
            raise GalatPeramban(f"Tidak bisa membuka tab peramban: {galat}") from galat
    return data["webSocketDebuggerUrl"]


def tunggu_muat(sesi: Sesi, batas: float = 30.0) -> None:
    import time

    mulai = time.time()
    while time.time() - mulai < batas:
        if sesi.nilai("document.readyState") == "complete":
            time.sleep(0.25)  # beri kesempatan JS halaman berjalan
            return
        time.sleep(0.15)
    raise GalatPeramban("Halaman tidak selesai dimuat.")


def buka(sesi: Sesi, url: str, lebar: int, tinggi: int) -> None:
    sesi.panggil("Page.enable")
    sesi.panggil("Emulation.setDeviceMetricsOverride", width=lebar, height=tinggi,
                 deviceScaleFactor=1, mobile=False)
    sesi.panggil("Page.navigate", url=url)
    tunggu_muat(sesi)


def potret(sesi: Sesi, tujuan: Path, skala: float = 1.0) -> tuple[int, int]:
    """Potret seluruh halaman (bukan hanya yang terlihat di layar)."""
    ukuran = sesi.nilai(
        "({w: document.documentElement.scrollWidth,"
        "  h: document.documentElement.scrollHeight})")
    lebar, tinggi = int(ukuran["w"]), int(ukuran["h"])
    hasil = sesi.panggil(
        "Page.captureScreenshot", format="png", captureBeyondViewport=True,
        clip={"x": 0, "y": 0, "width": lebar, "height": tinggi, "scale": skala})
    tujuan.parent.mkdir(parents=True, exist_ok=True)
    tujuan.write_bytes(base64.b64decode(hasil["data"]))
    return int(lebar * skala), int(tinggi * skala)


SKRIP_UKUR = r"""
(() => {
  const hasil = {halaman: location.pathname + location.search, ikon: []};
  const semua = document.querySelectorAll('svg.icon, .ikon svg, .petunjuk svg, .pl-sapa-emoji');
  const label = (el) => {
    const kelas = [...el.classList].filter((k) => k !== 'icon');
    const induk = el.parentElement ? [...el.parentElement.classList] : [];
    return {nama: el.tagName.toLowerCase(), data: el.getAttribute('data-ikon') || '',
            kelas: kelas.join('.'), induk: induk.join('.'),
            jalur: (() => {
              let naik = [], kini = el;
              for (let i = 0; i < 4 && kini && kini.parentElement; i++) {
                naik.push(kini.tagName.toLowerCase() +
                          ([...kini.classList].length ? '.' + [...kini.classList].join('.') : ''));
                kini = kini.parentElement;
              }
              return naik.join(' < ');
            })()};
  };
  for (const el of semua) {
    const kotak = el.getBoundingClientRect();
    const indukKotak = el.parentElement ? el.parentElement.getBoundingClientRect() : null;
    const gaya = getComputedStyle(el);
    const gayaInduk = getComputedStyle(el.parentElement || el);
    // Cari teks yang benar-benar bersebelahan: bisa berupa elemen (<span>, <strong>)
    // maupun simpul teks langsung di dalam induk (mis. «Cetak» di dalam <button>).
    let teks = null;
    if (el.parentElement) {
      const kandidat = [];
      for (const anak of el.parentElement.childNodes) {
        if (anak === el) continue;
        if (anak.nodeType === 3) {
          const isi = (anak.textContent || '').trim();
          if (!isi) continue;
          const jarak = document.createRange();
          jarak.selectNodeContents(anak);
          const kk = jarak.getBoundingClientRect();
          if (kk.width < 1 || kk.height < 1) continue;
          kandidat.push({tag: 'teks', kelas: '', isi: isi.slice(0, 40),
                         atas: kk.top, tengah: kk.top + kk.height / 2, tinggi: kk.height});
        } else if (anak.nodeType === 1) {
          const isi = (anak.textContent || '').trim();
          if (!isi) continue;
          const kk = anak.getBoundingClientRect();
          if (kk.width < 1 || kk.height < 1) continue;
          kandidat.push({tag: anak.tagName.toLowerCase(), kelas: [...anak.classList].join('.'),
                         isi: isi.slice(0, 40), atas: kk.top,
                         tengah: kk.top + kk.height / 2, tinggi: kk.height});
        }
      }
      // Ambil yang paling dekat secara tegak dengan ikon.
      kandidat.sort((a, b) =>
        Math.abs(a.tengah - (kotak.top + kotak.height / 2)) -
        Math.abs(b.tengah - (kotak.top + kotak.height / 2)));
      teks = kandidat.length ? kandidat[0] : null;
    }

    const saudara = el.parentElement ? [...el.parentElement.children]
      .filter((a) => a !== el && a.checkVisibility())
      .map((a) => {
        const kk = a.getBoundingClientRect();
        return {tag: a.tagName.toLowerCase(), kelas: [...a.classList].join('.'),
                x: +kk.x.toFixed(2), y: +kk.y.toFixed(2),
                lebar: +kk.width.toFixed(2), tinggi: +kk.height.toFixed(2),
                pusatX: +(kk.x + kk.width / 2).toFixed(2),
                pusatY: +(kk.y + kk.height / 2).toFixed(2)};
      }) : [];

    hasil.ikon.push({
      ...label(el),
      saudara,
      x: +kotak.x.toFixed(2), y: +kotak.y.toFixed(2),
      lebar: +kotak.width.toFixed(2), tinggi: +kotak.height.toFixed(2),
      pusatX: +(kotak.x + kotak.width / 2).toFixed(2),
      pusatY: +(kotak.y + kotak.height / 2).toFixed(2),
      display: gaya.display, verticalAlign: gaya.verticalAlign,
      induk: indukKotak ? {lebar: +indukKotak.width.toFixed(2), tinggi: +indukKotak.height.toFixed(2),
                           x: +indukKotak.x.toFixed(2), y: +indukKotak.y.toFixed(2),
                           pusatX: +(indukKotak.x + indukKotak.width / 2).toFixed(2),
                           pusatY: +(indukKotak.y + indukKotak.height / 2).toFixed(2),
                           display: gayaInduk.display, alignItems: gayaInduk.alignItems,
                           kelurus: gayaInduk.flexDirection, perataanTeks: gayaInduk.textAlign,
                           // berapa anak elemen yang benar-benar terlihat (selain ikon)
                           anakTerlihat: [...el.parentElement.children].filter(
                             (a) => a !== el && a.checkVisibility()).length,
                           // true bila induk menulis teksnya sendiri (mis. tombol «Cetak»)
                           adaTeks: [...el.parentElement.childNodes].some(
                             (n) => n.nodeType === 3 && (n.textContent || '').trim()),
                           lineHeight: gayaInduk.lineHeight, fontSize: gayaInduk.fontSize,
                           padding: gayaInduk.paddingTop + ' ' + gayaInduk.paddingRight + ' ' +
                                    gayaInduk.paddingBottom + ' ' + gayaInduk.paddingLeft} : null,
      teks: teks,
      ukuran: {lebar: +kotak.width.toFixed(2), tinggi: +kotak.height.toFixed(2)},
      warna: gaya.color, opacity: gaya.opacity,
      // checkVisibility() sekaligus memperhitungkan leluhur yang display:none
      // (mis. panel tab yang tidak aktif) — kalau tidak, ikon tersembunyi
      // akan dilaporkan "lebar 0 px" seolah-olah rusak.
      terlihat: el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}),
    });
  }
  return hasil;
})()
"""


def periksa(hasil: dict) -> list[str]:
    """Ubah hasil ukur jadi daftar temuan yang bisa dibaca manusia.

    Yang diperiksa (semuanya berasal dari kesalahan nyata, bukan dugaan):

    1. ikon tidak boleh berukuran nol (tidak tampil);
    2. ikon di dalam **lencana** (kotak lebih besar darinya) harus tepat di tengah;
    3. ikon yang mendampingi teks **sebaris** harus sejajar dengan teks itu;
    4. ikon di dalam wadah yang menengahkan isinya harus ikut di tengah mendatar.

    Ikon di atas label (menu bawah, kolom) **tidak** disalahkan: susunan
    bertumpuk memang disengaja.
    """
    temuan: list[str] = []
    for ikon in hasil["ikon"]:
        if not ikon["terlihat"]:
            continue
        nama = ikon["data"] or ikon["kelas"] or ikon["nama"]
        tempat = f"{nama} ({ikon['jalur']})"
        induk = ikon["induk"]

        # (1) ikon tanpa ukuran: CSS belum memuat atau ikon tidak tampil.
        if ikon["lebar"] < 1 or ikon["tinggi"] < 1:
            temuan.append(f"{tempat}: ikon tidak terlihat (lebar {ikon['lebar']} px)")
            continue

        # Bila induk hanya berisi ikon ini (tanpa teks sendiri, tanpa anak lain),
        # ia adalah "lencana": ikon harus tepat di tengahnya.
        murni = bool(induk) and not induk["adaTeks"] and induk["anakTerlihat"] == 0
        if murni:
            selisih_x = abs(ikon["pusatX"] - induk["pusatX"])
            selisih_y = abs(ikon["pusatY"] - induk["pusatY"])
            lebih_besar = (induk["lebar"] - ikon["lebar"] >= 6
                           and induk["tinggi"] - ikon["tinggi"] >= 6)
            if lebih_besar and (selisih_x > 1.5 or selisih_y > 1.5):
                arah = []
                if selisih_y > 1.5:
                    arah.append("naik" if ikon["pusatY"] < induk["pusatY"] else "turun")
                if selisih_x > 1.5:
                    arah.append("ke kiri" if ikon["pusatX"] < induk["pusatX"] else "ke kanan")
                temuan.append(
                    f"{tempat}: tidak di tengah lencananya — {selisih_x:.1f} px mendatar, "
                    f"{selisih_y:.1f} px tegak ({' dan '.join(arah)})")
                continue

        if not induk:
            continue

        # Ikon di atas label (menu bawah, susunan bertumpuk) memang sengaja.
        bertumpuk = induk["display"] == "flex" and "column" in induk["kelurus"]

        # (3) sejajar dengan teks di sebelahnya.
        if not bertumpuk and ikon["teks"]:
            beda = ikon["pusatY"] - ikon["teks"]["tengah"]
            if abs(beda) > 2.5:
                temuan.append(f"{tempat}: titik tengah ikon {beda:+.1f} px dari tengah teks "
                              f"«{ikon['teks']['isi']}» → tidak sejajar")

        # (4) wadah bertumpuk yang menengahkan isinya: ikon ikut di tengah mendatar.
        #     Pada wadah sebaris ikon boleh berada di awal (mis. kaca pembesar di
        #     kotak pencarian), jadi aturan ini tidak berlaku di sana.
        if induk["display"] in ("flex", "grid") and induk["alignItems"] == "center" \
                and (bertumpuk or murni):
            beda_x = abs(ikon["pusatX"] - induk["pusatX"])
            if beda_x > 1.5:
                temuan.append(f"{tempat}: tidak di tengah mendatar wadahnya "
                              f"({beda_x:.1f} px dari sumbu tengah)")

        # (4b) ikon di samping kolom isian (tanpa teks): harus sebaris tegak
        #      dengan kolomnya, bukan menggantung di atas atau di bawah.
        if not bertumpuk and not ikon["teks"] and ikon["saudara"]:
            dekat = min(ikon["saudara"],
                        key=lambda s: abs(s["pusatY"] - ikon["pusatY"]))
            beda_y = ikon["pusatY"] - dekat["pusatY"]
            if abs(beda_y) > 2.5:
                temuan.append(f"{tempat}: titik tengah ikon {beda_y:+.1f} px dari tengah "
                              f"<{dekat['tag']}.{dekat['kelas']}> di sebelahnya")

        # (5) wadah rapih yang tidak diatur penengahannya sama sekali.
        if induk["display"] in ("flex", "grid") and induk["alignItems"] not in ("center", "baseline") \
                and not ikon["teks"] and not murni:
            temuan.append(f"{tempat}: wadah {induk['display']} tanpa penengahan "
                          f"(align-items: {induk['alignItems']})")
    return temuan


def _lihat(sesi: Sesi, args, jalur: str, tujuan: Path) -> list[str]:
    """Ukur dan/atau potret satu halaman (sesuai yang diminta)."""
    masalah: list[str] = []
    buka(sesi, f"{args.basis}{jalur}", args.lebar, args.tinggi)
    nama = _nama_berkas(jalur, args)
    if jalur in args.ukur:
        hasil = sesi.nilai(SKRIP_UKUR)
        berkas = tujuan / f"{nama}.json"
        berkas.parent.mkdir(parents=True, exist_ok=True)
        berkas.write_text(json.dumps(hasil, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {jalur}: {len(hasil['ikon'])} ikon diukur → {berkas.relative_to(BASE)}")
        masalah += periksa(hasil)
        masalah += periksa_tumpang_tindih(sesi, jalur)
        masalah += periksa_luapan(sesi, jalur)
    if jalur in args.potret:
        if jalur not in args.ukur:
            buka(sesi, f"{args.basis}{jalur}", args.lebar, args.tinggi)
        berkas = tujuan / f"{nama}.png"
        lebar, tinggi = potret(sesi, berkas, args.skala)
        print(f"  {jalur}: potret {lebar}×{tinggi} px → {berkas.relative_to(BASE)}")
        _potong(berkas, tujuan, nama, args)
    return masalah


SKRIP_TUMPANG = r"""
(() => {
  // Bilah menu bawah pada ponsel dipasang `position: fixed`; periksa apakah ada
  // isi halaman yang tertutup karenanya saat halaman digulir ke paling bawah.
  const nav = document.querySelector('.pl-nav');
  if (!nav) return {ada: false};
  const tinggiDokumen = document.documentElement.scrollHeight;
  window.scrollTo(0, tinggiDokumen);
  const nk = nav.getBoundingClientRect();
  const tertutup = [];
  for (const el of document.querySelectorAll('main *')) {
    if (el.children.length || !el.checkVisibility()) continue;
    if ((el.textContent || '').trim().length < 2) continue;
    const r = el.getBoundingClientRect();
    if (r.height < 4) continue;
    if (r.bottom > nk.top + 1 && r.top < nk.bottom - 1) {
      tertutup.push({tag: el.tagName.toLowerCase(), kelas: [...el.classList].join('.'),
                     isi: (el.textContent || '').trim().slice(0, 40),
                     atas: +r.top.toFixed(1), bawah: +r.bottom.toFixed(1)});
    }
  }
  window.scrollTo(0, 0);
  return {ada: true, tinggiBilah: +nk.height.toFixed(1), atas: +nk.top.toFixed(1),
          tertutup: tertutup.slice(0, 6), jumlah: tertutup.length};
})()
"""


def periksa_tumpang_tindih(sesi: Sesi, jalur: str) -> list[str]:
    """Laporkan isi yang tertutup bilah menu bawah (khas tampilan ponsel)."""
    hasil = sesi.nilai(SKRIP_TUMPANG)
    if not hasil or not hasil.get("ada") or not hasil.get("jumlah"):
        return []
    rinci = ", ".join(f"«{x['isi']}»" for x in hasil["tertutup"])
    return [f"{jalur}: {hasil['jumlah']} bagian isi tertutup bilah menu bawah "
            f"(tinggi {hasil['tinggiBilah']} px): {rinci}"]


SKRIP_LUAPAN = r"""
(() => {
  // Isi yang lebih lebar dari layar memaksa siswa menggulir ke samping —
  // persis keluhan «meluber» yang dilaporkan sekolah.
  const lebar = window.innerWidth;
  const lebih = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!el.checkVisibility()) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const gaya = getComputedStyle(el);
    // Tautan «Lompat ke isi» memang sengaja ditaruh di luar layar sampai difokus
    // (pola aksesibilitas) — bukan luapan yang perlu dibetulkan.
    if (gaya.position === 'absolute' && r.left <= -900) continue;
    const kanan = r.right - lebar;
    const kiri = -r.left;
    // Hanya laporkan yang benar-benar melewati tepi layar (bukan bilah gulir).
    if (kanan > 2 || kiri > 2) {
      // Lewati elemen yang memang melebar karena keturunan yang sudah dilaporkan.
      lebih.push({tag: el.tagName.toLowerCase(), kelas: [...el.classList].join('.'),
                  teks: (el.textContent || '').trim().slice(0, 40),
                  kiri: +r.left.toFixed(1), kanan: +r.right.toFixed(1),
                  lebar: +r.width.toFixed(1), posisi: gaya.position,
                  luber: +(kanan > 2 ? kanan : kiri).toFixed(1)});
    }
  }
  // Yang penting: apakah HALAMAN perlu digulir ke samping. Elemen yang mencuat
  // di dalam wadah ber-`overflow: hidden` atau laci tersembunyi (bilah samping
  // petugas yang diparkir di luar layar) bukan masalah — halamannya tetap rapi.
  const lebarDokumen = document.documentElement.scrollWidth;
  if (lebarDokumen <= lebar + 1) {
    return {lebarLayar: lebar, lebarDokumen, jumlah: 0, pelanggar: []};
  }
  // Urutkan dari yang paling kecil lebihnya (paling dekat ke biang kerok).
  const urut = lebih.slice().sort((a, b) => a.luber - b.luber);
  return {lebarLayar: lebar, lebarDokumen, jumlah: urut.length,
          pelanggar: urut.slice(0, 8)};
})()
"""


def periksa_luapan(sesi: Sesi, jalur: str) -> list[str]:
    """Laporkan isi yang melewati tepi layar (harus digulir ke samping)."""
    hasil = sesi.nilai(SKRIP_LUAPAN)
    if not hasil or not hasil.get("jumlah"):
        return []
    paling = ", ".join(f"<{x['tag']}.{x['kelas']}> «{x['teks']}» (+{x['luber']} px)"
                       for x in hasil["pelanggar"][:3])
    return [f"{jalur}: {hasil['jumlah']} bagian melewati tepi layar "
            f"(dokumen {hasil['lebarDokumen']} px vs layar {hasil['lebarLayar']} px): {paling}"]


def _nama_berkas(jalur: str, args) -> str:
    """Nama berkas yang membedakan halaman sekaligus ukuran layar."""
    inti = jalur.strip("/").replace("/", "-").replace("?", "-").replace("=", "-") or "beranda"
    return f"{inti}-{args.lebar}x{args.tinggi}"


def _potong(berkas: Path, tujuan: Path, nama: str, args) -> None:
    """Simpan potongan gambar (dan perbesar) supaya bagian kecil bisa diperiksa."""
    if not args.potong:
        return
    try:
        from PIL import Image
    except ImportError:
        print("    (lewati --potong: butuh Pillow)")
        return
    bagian = [int(n) for n in args.potong.split(",")]
    if len(bagian) != 4:
        print("    (--potong butuh 4 angka: X,Y,LEBAR,TINGGI)")
        return
    gambar = Image.open(berkas).crop((bagian[0], bagian[1],
                                      bagian[0] + bagian[2], bagian[1] + bagian[3]))
    if args.perbesar and args.perbesar != 1:
        gambar = gambar.resize((int(gambar.width * args.perbesar),
                                int(gambar.height * args.perbesar)), Image.LANCZOS)
    keluar = tujuan / f"{nama}-potong{'-x%s' % args.perbesar if args.perbesar != 1 else ''}.png"
    gambar.save(keluar)
    print(f"    potongan {bagian[2]}×{bagian[3]} px"
          f"{f' diperbesar {args.perbesar}×' if args.perbesar != 1 else ''}"
          f" → {keluar.relative_to(BASE)} ({gambar.width}×{gambar.height} px)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Potret & ukur tampilan lewat peramban sungguhan")
    p.add_argument("--basis", default="http://127.0.0.1:8080", help="Alamat aplikasi SM")
    p.add_argument("--jam", type=int, default=9222, help="Port pengawas peramban (DevTools)")
    p.add_argument("--potret", action="append", default=[], metavar="JALUR",
                   help="Jalur halaman yang dipotret (boleh berulang)")
    p.add_argument("--ukur", action="append", default=[], metavar="JALUR",
                   help="Jalur halaman yang ikonnya diukur (boleh berulang)")
    p.add_argument("--halaman", action="append", default=[], metavar="JALUR",
                   help="Halaman tambahan yang dibuka lebih dulu (mis. setelah login)")
    p.add_argument("--keluar", default="pratinjau/lihat", help="Folder berkas PNG")
    p.add_argument("--lebar", type=int, default=1280)
    p.add_argument("--tinggi", type=int, default=900)
    p.add_argument("--skala", type=float, default=1.0, help="Perbesaran potret")
    p.add_argument("--potong", metavar="X,Y,LEBAR,TINGGI",
                   help="Potong bagian tertentu dari setiap potret (mis. 430,540,540,460)")
    p.add_argument("--perbesar", type=float, default=1.0,
                   help="Perbesar hasil potongan (mis. 2.5) agar ikon bisa diperiksa mata")
    p.add_argument("--masuk-siswa", metavar="NISN",
                   help="Masuk sebagai siswa lebih dulu (mis. 3900000009)")
    p.add_argument("--masuk-petugas", action="store_true",
                   help="Masuk sebagai admin (admin/admin123) lalu periksa halaman petugas")
    args = p.parse_args(argv)

    if not args.potret and not args.ukur:
        args.ukur = ["/login?mode=siswa"]
        args.potret = ["/login?mode=siswa"]

    tujuan = (BASE / args.keluar).resolve()
    try:
        sesi = Sesi(tab_baru(args.jam, "about:blank"))
    except GalatPeramban as galat:
        print(f"[X] {galat}")
        print("    Nyalakan peramban lebih dulu (lihat petunjuk di kepala berkas ini).")
        return 2

    # Halaman yang diminta *sebelum* masuk dipisah supaya tidak teralihkan ke
    # ruang siswa (dulu urutannya salah sehingga potret /login berisi /portal).
    ukur_masuk = [j for j in args.ukur if j.startswith("/login")]
    ukur_dalam = [j for j in args.ukur if not j.startswith("/login")]
    potret_masuk = [j for j in args.potret if j.startswith("/login")]
    potret_dalam = [j for j in args.potret if not j.startswith("/login")]

    masalah: list[str] = []
    try:
        # Selalu mulai dari keadaan tamu: tanpa ini, sisa sesi sekolah bisa
        # membuat halaman masuk teralihkan ke ruang siswa dan potretnya salah.
        sesi.panggil("Network.enable")
        sesi.panggil("Network.clearBrowserCookies")

        for jalur in (ukur_masuk + potret_masuk):
            masalah += _lihat(sesi, args, jalur, tujuan)

        if args.masuk_petugas:
            buka(sesi, f"{args.basis}/login", args.lebar, args.tinggi)
            sesi.nilai(
                "(() => {const f = document.querySelector(\"form[data-panel='staff']\");"
                "f.querySelector(\"input[name='username']\").value = 'admin';"
                "f.querySelector(\"input[name='password']\").value = 'admin123';"
                "f.submit(); return true;})()")
            tunggu_muat(sesi)
            print(f"  masuk sebagai admin: {sesi.nilai('location.pathname')}")

        if args.masuk_siswa:
            buka(sesi, f"{args.basis}/login", args.lebar, args.tinggi)
            ada = sesi.nilai("!!document.querySelector(\"form[data-panel='siswa']\")")
            if not ada:
                raise GalatPeramban("Form masuk siswa tidak ditemukan di /login "
                                    "(mungkin masih ada sesi lama).")
            sesi.nilai(
                "(() => {const f = document.querySelector(\"form[data-panel='siswa']\");"
                f"f.querySelector(\"input[name='nisn']\").value = '{args.masuk_siswa}';"
                "f.submit(); return true;})()")
            tunggu_muat(sesi)
            print(f"  masuk sebagai siswa {args.masuk_siswa}: {sesi.nilai('location.pathname')}")

        for jalur in args.halaman:
            buka(sesi, f"{args.basis}{jalur}", args.lebar, args.tinggi)

        for jalur in (ukur_dalam + potret_dalam):
            masalah += _lihat(sesi, args, jalur, tujuan)

    finally:
        sesi.tutup()

    if masalah:
        print("\n  Tampilan yang perlu dibenahi:")
        for satu in masalah:
            print(f"    - {satu}")
        return 1
    print("\n  Letak ikon pas: sejajar dengan teks dan di tengah wadahnya.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
