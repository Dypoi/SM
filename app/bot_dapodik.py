"""Bot Dapodik — menjalankan registrasi peserta didik di Dapodik lokal.

Diadaptasi dari skrip Selenium sekolah (``DAFDIR KLS7`` + tombol Registrasi),
dengan empat perbedaan penting:

1. **Antrean dari aplikasi SM, bukan berkas Excel**: NISN & NIS/NIPD diambil
   dari tabel ``students`` (lihat :func:`app.services.bot_antrean`).
2. **Berjalan di belakang layar**: Chrome dijalankan *headless* (tanpa jendela),
   sehingga bot bekerja sambil aplikasi SM tetap dipakai. Bila perlu melihat
   prosesnya (mis. mengisi verifikasi pertama kali), matikan opsi headless di
   halaman Bot Dapodik.
3. **Kemajuannya tampil di aplikasi**: setiap siswa dicatat pada tabel
   ``dapodik_job_items`` sehingga halaman Bot Dapodik bisa menampilkan progres
   secara langsung, dan pekerjaan bisa dilanjutkan tanpa mengulang yang sukses.
4. **Ada mode uji coba** (``bot_simulasi``): antrean, aturan lewati, kemajuan,
   dan log diuji tanpa membuka peramban/Dapodik sama sekali.

Alur tiap siswa (sama dengan skrip asli):

    cari NISN -> pilih baris -> Registrasi -> isi NIS -> centang semua "Ya"
    -> Hobi -> Cita-cita -> "Simpan dan Tutup"
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import config, services

# --------------------------------------------------------------------------- #
# Peta tombol (selector) — bawaan sama dengan skrip bot sekolah.
# Dapat ditimpa dari halaman Bot Dapodik (pengaturan lanjutan, format JSON)
# bila Dapodik berubah versi, tanpa perlu mengubah kode.
# --------------------------------------------------------------------------- #
SELECTOR_BAWAAN: dict[str, str] = {
    "login_username": "/html/body/div[5]/div[2]/form/input",
    "login_password": "/html/body/div[5]/div[2]/form/div[1]/input",
    "login_tombol": '//*[@id="form2"]/button',
    "menu_tujuan": "/html/body/div[1]/ul/li[2]/div/a/button",
    "popup_tutup": "/html/body/div[11]/div[2]/div[2]/div/div/a[1]",
    "menu_1": '//*[@id="ext-element-76"]',
    "menu_2": '//*[@id="ext-element-66"]',
    "cari_nisn": "name:cari_text",
    "tombol_registrasi": '//span[contains(@class, "x-btn-inner-soft-green-small") '
                         'and normalize-space()="Registrasi"]',
    "input_nis": "name:nipd",
    "radio_ya": '//div[contains(@class, "x-form-cb-wrap-inner")]'
                '//label[normalize-space()="Ya"]/preceding-sibling::span/input',
    "hobi": "name:id_hobby",
    "cita": "name:id_cita",
    "simpan": '//span[contains(@class, "x-btn-inner-default-small") '
              'and contains(normalize-space(), "Simpan dan Tutup")]',
}

#: Penanda kelas baris tabel Ext JS tempat hasil pencarian muncul.
BARIS_TABEL = 'x-grid-row'

#: Nama kunci yang boleh ditimpa lewat pengaturan (agar salah ketik terdeteksi).
SELECTOR_DIIZINKAN = tuple(SELECTOR_BAWAAN)

#: Selector cadangan yang dicoba bila selector bawaan tidak menemukan elemen.
#: Penting karena Dapodik sering diperbarui: XPath absolut dan id ``ext-element-*``
#: berubah setiap versi, sedangkan pencarian berbasis teks jauh lebih tahan lama.
SELECTOR_CADANGAN: dict[str, list[str]] = {
    "login_username": [
        "css:input[name=username]",
        "css:input[name=user]",
        "css:input[name=email]",
        "css:input[type=text]",
    ],
    "login_password": [
        "css:input[name=password]",
        "css:input[name=sandi]",
        "css:input[type=password]",
    ],
    "login_tombol": [
        "xpath://button[contains(normalize-space(), 'Masuk') or contains(normalize-space(), 'Login')]",
        "css:button[type=submit]",
        "css:form button",
    ],
    "menu_tujuan": [
        "xpath://*[self::a or self::button or self::li][contains(normalize-space(), 'Peserta Didik')]",
    ],
    "popup_tutup": [
        "css:div.x-window a.x-tool-close",
        "css:div.x-window .x-tool-close",
        "css:a.x-tool-close",
    ],
    "menu_1": [
        "xpath://*[self::a or self::span or self::li][contains(normalize-space(), 'Pendaftaran')]",
        "xpath://*[self::a or self::span or self::li][contains(normalize-space(), 'Registrasi')]",
    ],
    "menu_2": [
        "xpath://*[self::a or self::span or self::li][contains(normalize-space(), 'Peserta Didik')]",
    ],
    "cari_nisn": [
        "css:input[name*=cari]",
        "css:input[name*=search]",
        "css:input[name*=nisn]",
    ],
    "tombol_registrasi": [
        "xpath://*[self::span or self::a or self::button][contains(normalize-space(), 'Registrasi')]",
        "xpath://*[self::span or self::a or self::button][contains(normalize-space(), 'Daftar')]",
    ],
    "input_nis": [
        "css:input[name*=nipd]",
        "css:input[name*=nis]",
    ],
    "radio_ya": [
        'xpath://*[normalize-space()="Ya"]/preceding::input[@type="radio"][1]',
    ],
    "hobi": [
        "css:input[name*=hobby]",
        "css:input[name*=hobi]",
        "css:select[name*=hobby]",
    ],
    "cita": [
        "css:input[name*=cita]",
        "css:select[name*=cita]",
    ],
    "simpan": [
        "xpath://*[self::span or self::a or self::button][contains(normalize-space(), 'Simpan dan Tutup')]",
        "xpath://*[self::span or self::a or self::button][contains(normalize-space(), 'Simpan')]",
    ],
}

#: Batas waktu singkat untuk menguji satu kandidat selector (detik).
SELEKTOR_UJI_DETIK = 6

#: Batas jumlah berkas bukti (screenshot/HTML) yang disimpan agar tidak menumpuk.
BUKTI_MAKSIMAL = 40


def peta_selector() -> dict[str, str]:
    """Gabungkan selector bawaan dengan penimpaan dari pengaturan bot."""
    peta = dict(SELECTOR_BAWAAN)
    mentah = (services.bot_setting().get("bot_selector_json") or "").strip()
    if not mentah:
        return peta
    try:
        ubah = json.loads(mentah)
    except json.JSONDecodeError:
        return peta
    if isinstance(ubah, dict):
        for kunci, nilai in ubah.items():
            if kunci in peta and str(nilai).strip():
                peta[str(kunci)] = str(nilai).strip()
    return peta


def _pesan_galat_selector(mentah: str) -> str:
    """Periksa JSON selector sebelum disimpan (pesan jelas bila salah)."""
    if not (mentah or "").strip():
        return ""
    try:
        ubah = json.loads(mentah)
    except json.JSONDecodeError as exc:
        return f"Peta selector bukan JSON yang sah: {exc.msg} (baris {exc.lineno})."
    if not isinstance(ubah, dict):
        return "Peta selector harus berupa objek JSON, mis. {\"cari_nisn\": \"name:cari_text\"}."
    asing = [kunci for kunci in ubah if kunci not in SELECTOR_DIIZINKAN]
    if asing:
        return ("Nama selector tidak dikenal: " + ", ".join(sorted(asing)) +
                ". Yang boleh: " + ", ".join(SELECTOR_DIIZINKAN) + ".")
    return ""


# --------------------------------------------------------------------------- #
# Penjalan bot (satu pekerjaan sekaligus)
# --------------------------------------------------------------------------- #
class BotBerjalanError(RuntimeError):
    """Dilempar bila bot sudah berjalan atau pengaturannya belum siap."""


class BotDapodik:
    """Satu pekerjaan bot: antrean siswa dijalankan berurutan sampai selesai/dihentikan."""

    def __init__(self, job_id: int, antrean: list[dict[str, Any]], item_ids: list[int],
                 opsi: dict[str, str], kepala: Callable[[str], None] | None = None) -> None:
        self.job_id = job_id
        self.antrean = antrean
        self.item_ids = item_ids
        self.opsi = opsi
        self._kepala = kepala or (lambda baris: None)
        self._stop = threading.Event()
        self._benang: threading.Thread | None = None
        self.mulai_pada = 0.0
        self.selesai_pada = 0.0
        self.diproses = 0
        self.sedang: dict[str, Any] | None = None
        self.peramban_tampak = opsi.get("bot_headless", "1") != "1"
        self.simulasi = opsi.get("bot_simulasi", "0") == "1"

    # ---------------------------------------------------------------- jalan ---
    def jalankan(self) -> None:
        self._benang = threading.Thread(target=self._kerja, name=f"bot-dapodik-{self.job_id}",
                                        daemon=True)
        self._benang.start()

    def hentikan(self) -> None:
        self._stop.set()

    def berjalan(self) -> bool:
        return bool(self._benang and self._benang.is_alive())

    # ------------------------------------------------------------ keadaan --- #
    def kemajuan(self) -> dict[str, Any]:
        detik = max(0.001, (self.selesai_pada or time.time()) - self.mulai_pada)
        kecepatan = self.diproses / detik * 60 if self.diproses else 0.0
        sisa = max(0, len(self.antrean) - self.diproses)
        perkiraan = int(sisa / kecepatan * 60) if kecepatan > 0 else 0
        return {
            "job_id": self.job_id,
            "berjalan": self.berjalan(),
            "simulasi": self.simulasi,
            "tampak": self.peramban_tampak,
            "total": len(self.antrean),
            "diproses": self.diproses,
            "sedang": (self.sedang or {}).get("nama"),
            "sedang_nisn": (self.sedang or {}).get("nisn"),
            "kecepatan": round(kecepatan, 1),
            "perkiraan_detik": perkiraan,
            "dihentikan": self._stop.is_set(),
        }

    # ---------------------------------------------------------------- kerja ---
    def _kerja(self) -> None:
        self.mulai_pada = time.time()
        self._catat_kepala(f"Mulai {len(self.antrean)} siswa "
                           f"({'uji coba' if self.simulasi else 'headless' if not self.peramban_tampak else 'jendela tampak'}).")
        peramban = None
        galat_fatal = ""
        try:
            if not self.simulasi:
                peramban = self._buka_peramban()
                self._login(peramban)
            for posisi, siswa in enumerate(self.antrean):
                if self._stop.is_set():
                    break
                self._proses_satu(peramban, siswa, self.item_ids[posisi] if posisi < len(self.item_ids) else None)
                self.diproses += 1
                jeda = float(self.opsi.get("bot_jeda", "1") or 1)
                if jeda and not self.simulasi:
                    time.sleep(jeda)
        except Exception as exc:  # noqa: BLE001 — apa pun harus tercatat & peramban ditutup
            galat_fatal = f"{type(exc).__name__}: {str(exc)[:300]}"
            services.perbarui_job_bot(self.job_id, status="gagal", baris_log=f"[FATAL] {galat_fatal}")
            self._kepala(f"[FATAL] {galat_fatal}")
        finally:
            self.selesai_pada = time.time()
            if peramban is not None:
                try:
                    peramban.quit()
                except Exception:  # noqa: BLE001
                    pass
            if galat_fatal or self._stop.is_set():
                sisa = services.tandai_sisa_menunggu_bot(
                    self.job_id, "Pekerjaan gagal/dihentikan sebelum siswa ini diproses")
                if sisa:
                    self._catat_kepala(
                        f"{sisa} siswa belum diproses (akan diulang pada pekerjaan berikutnya).")
            if not galat_fatal:
                if self._stop.is_set():
                    services.perbarui_job_bot(self.job_id, status="batal",
                                              baris_log="Dihentikan oleh petugas.")
                else:
                    services.perbarui_job_bot(self.job_id, status="sukses",
                                              baris_log="Pekerjaan selesai.")
            _lupakan(self)

    def _catat_kepala(self, baris: str) -> None:
        services.perbarui_job_bot(self.job_id, baris_log=baris)
        self._kepala(baris)

    # ------------------------------------------------------------- peramban ---
    def _buka_peramban(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:  # noqa: BLE001 — pustaka belum terpasang
            raise RuntimeError(
                "Pustaka selenium belum terpasang pada Python aplikasi ini. Buka halaman "
                "Bot Dapodik lalu tekan «Pasang pustaka bot».") from exc

        opsi = Options()
        opsi.add_experimental_option("prefs", {
            "profile.password_manager_leak_detection": False,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        })
        if self.opsi.get("bot_headless", "1") == "1":
            # --headless=new: Chrome modern berjalan tanpa jendela, tetap bisa
            # menyimpan sesi & menjalankan JavaScript Ext JS.
            opsi.add_argument("--headless=new")
            opsi.add_argument("--disable-gpu")
            opsi.add_argument("--window-size=1600,1000")
        else:
            opsi.add_argument("--start-maximized")
        opsi.add_argument("--log-level=3")
        try:
            peramban = webdriver.Chrome(options=opsi)
            # Dapodik dimuat lambat pada PC sekolah: beri waktu halaman selesai.
            peramban.set_page_load_timeout(max(60.0, float(self.opsi.get("bot_timeout", "30") or 30)))
            return peramban
        except Exception as exc:  # noqa: BLE001 — beri pesan yang bisa ditindaklanjuti
            raise RuntimeError(
                "Google Chrome tidak dapat dibuka. Pastikan Chrome sudah terpasang di PC ini; "
                "bila muncul keluhan driver, sambungkan internet sekali agar Selenium mengunduh "
                f"drivernya otomatis. Rincian: {type(exc).__name__}: {str(exc)[:200]}") from exc

    def _tunggu(self, peramban, detik: float) -> None:
        time.sleep(detik)

    # -------------------------------------------------- tunggu & kenali halaman --- #
    def _tunggu_halaman(self, peramban) -> None:
        """Tunggu halaman benar-benar selesai dimuat, lalu beri jeda tambahan.

        Dapodik memakai Ext JS: DOM baru lengkap beberapa detik sesudah
        ``document.readyState`` selesai. Skrip bot sekolah memakai jeda 15 detik;
        di sini jeda dapat diatur lewat pengaturan ``bot_jeda_muat``.
        """
        batas = float(self.opsi.get("bot_timeout", "30") or 30)
        try:
            from selenium.webdriver.support.ui import WebDriverWait

            WebDriverWait(peramban, batas).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:  # noqa: BLE001 — tetap lanjut, jeda di bawah jadi penyelamat
            pass
        time.sleep(float(self.opsi.get("bot_jeda_muat", "8") or 8))

    def _galat_halaman(self, peramban) -> str:
        """Pesan bantuan bila halaman yang terbuka ternyata halaman galat Chrome."""
        try:
            judul = (peramban.title or "").strip()
            sumber = (peramban.page_source or "")[:4000]
        except Exception:  # noqa: BLE001
            return ""
        tanda = ("ERR_CONNECTION_REFUSED", "ERR_CONNECTION_RESET", "ERR_NAME_NOT_RESOLVED",
                 "ERR_CONNECTION_TIMED_OUT", "ERR_ADDRESS_UNREACHABLE", "ERR_EMPTY_RESPONSE")
        if any(kode in sumber for kode in tanda):
            kode = next(kode for kode in tanda if kode in sumber)
            return (f"Halaman Dapodik tidak dapat dibuka ({kode}). Pastikan aplikasi Dapodik "
                    f"sedang berjalan di PC ini dan alamatnya benar ({self.opsi.get('bot_url', '')}).")
        if "can't be reached" in judul.lower() or "tidak dapat dijangkau" in judul.lower() \
                or "tidak dapat diakses" in judul.lower():
            return (f"Halaman Dapodik tidak dapat dijangkau dari peramban. Periksa apakah aplikasi "
                    f"Dapodik sedang berjalan dan alamat {self.opsi.get('bot_url', '')} sudah benar.")
        return ""

    def _ringkas_halaman(self, peramban) -> dict[str, Any]:
        """Apa yang terlihat pada halaman saat ini (untuk pesan galat & alat uji)."""
        from selenium.webdriver.common.by import By

        def kumpul_teks(css: str, batas: int = 10) -> list[str]:
            hasil: list[str] = []
            try:
                elemen = peramban.find_elements(By.CSS_SELECTOR, css)
            except Exception:  # noqa: BLE001
                return hasil
            for el in elemen:
                try:
                    if not el.is_displayed():
                        continue
                    teks = " ".join((el.text or el.get_attribute("value") or "").split())
                except Exception:  # noqa: BLE001
                    continue
                if teks:
                    hasil.append(teks[:45])
                if len(hasil) >= batas:
                    break
            return hasil

        ringkas: dict[str, Any] = {"judul": "", "url": "", "galat_halaman": ""}
        try:
            ringkas["judul"] = (peramban.title or "").strip()[:120]
            ringkas["url"] = (peramban.current_url or "").strip()[:200]
            ringkas["galat_halaman"] = self._galat_halaman(peramban)
            ringkas["isian_teks"] = kumpul_teks("input[type=text], input[type=email], input:not([type])")
            ringkas["isian_sandi"] = len(peramban.find_elements(By.CSS_SELECTOR, "input[type=password]"))
            ringkas["tombol"] = kumpul_teks("button, input[type=submit], a.x-btn")
            ringkas["menu"] = kumpul_teks("ul li a, ul li button, .x-menu-item-text")
            ringkas["judul_kotak"] = kumpul_teks(".x-window-header-text, .x-panel-header-text, h1, h2")
        except Exception as exc:  # noqa: BLE001
            ringkas["galat_ringkas"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        return ringkas

    def _bukti(self, peramban, label: str) -> str:
        """Simpan tangkapan layar + HTML halaman sebagai bukti pemeriksaan ('' bila gagal)."""
        stempel = time.strftime("%Y%m%d-%H%M%S")
        aman = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]
        folder = config.DATA_DIR / "bot"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            gambar = folder / f"{aman}-{stempel}.png"
            halaman = folder / f"{aman}-{stempel}.html"
            peramban.save_screenshot(str(gambar))
            halaman.write_text(peramban.page_source or "", encoding="utf-8", errors="replace")
            self._bersihkan_bukti(folder)
            return str(gambar)
        except Exception:  # noqa: BLE001 — bukti hanya alat bantu
            return ""

    @staticmethod
    def _bersihkan_bukti(folder: Path) -> None:
        """Sisakan sejumlah berkas bukti terbaru saja."""
        try:
            berkas = sorted(folder.glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
            for usang in berkas[BUKTI_MAKSIMAL:]:
                usang.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    def _tunggu_overlay(self, peramban) -> None:
        """Tunggu mask/overlay loading Ext JS hilang (sama seperti skrip bot)."""
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        batas = float(self.opsi.get("bot_timeout", "15") or 15)
        try:
            WebDriverWait(peramban, batas).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.x-mask")))
        except TimeoutException as exc:
            raise TimeoutException("Overlay loading masih aktif setelah timeout.") from exc

    def _tunggu_elemen(self, peramban, locator):
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        batas = float(self.opsi.get("bot_timeout", "15") or 15)
        return WebDriverWait(peramban, batas).until(EC.visibility_of_element_located(locator))

    def _klik_aman(self, peramban, locator, ulang: int | None = None) -> None:
        """Klik dengan percobaan ulang (elemen tertutup overlay / berubah)."""
        from selenium.common.exceptions import (ElementClickInterceptedException,
                                                StaleElementReferenceException, TimeoutException)
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        ulang = ulang or int(self.opsi.get("bot_max_retries", "3") or 3)
        batas = float(self.opsi.get("bot_timeout", "15") or 15)
        galat = None
        for percobaan in range(1, ulang + 1):
            try:
                self._tunggu_overlay(peramban)
                elemen = WebDriverWait(peramban, batas).until(EC.element_to_be_clickable(locator))
                peramban.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemen)
                elemen.click()
                return
            except (ElementClickInterceptedException, StaleElementReferenceException,
                    TimeoutException) as exc:
                galat = exc
                self._catat_kepala(f"[ULANG {percobaan}/{ulang}] klik gagal: {type(exc).__name__}")
                time.sleep(1)
        raise galat if galat else RuntimeError("Klik gagal.")

    def _isi(self, peramban, locator, nilai: str):
        from selenium.webdriver.common.keys import Keys

        elemen = self._tunggu_elemen(peramban, locator)
        elemen.click()
        elemen.send_keys(Keys.CONTROL, "a")
        elemen.send_keys(str(nilai))
        return elemen

    # ------------------------------------------------------- kolom pilihan --- #
    def _pilih_kolom_pilihan(self, peramban, locator, nilai: str) -> None:
        """Isi kolom pilihan (Hobi / Cita-cita) yang aman untuk Dapodik.

        Dapodik memakai Ext JS sehingga kolom pilihan kadang berupa combo box,
        bukan ``<select>`` biasa. Urutan percobaan:

        1. ``<select>`` biasa → pilih sesuai teks/nilai (termasuk cocok sebagian);
        2. combo box → ketik teks lalu klik pilihan yang muncul di daftar;
        3. bila daftar tidak muncul → Enter (sama seperti skrip bot sekolah).
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import Select, WebDriverWait

        nilai = str(nilai or "").strip()
        if not nilai:
            raise ValueError("Hobi/Cita-cita belum diisi pada pengaturan bot.")
        elemen = self._tunggu_elemen(peramban, locator)

        if (elemen.tag_name or "").lower() == "select":
            pilih = Select(elemen)
            for opsi in pilih.options:
                teks = (opsi.text or "").strip()
                if nilai.lower() == teks.lower() or nilai.lower() in teks.lower() or teks.lower() in nilai.lower():
                    pilih.select_by_index(opsi.index)
                    return
            raise ValueError(f"Pilihan '{nilai}' tidak ada pada daftar Dapodik.")

        # Combo box: buka, ketik, lalu pilih item pada daftar (bound list).
        aman = nilai.replace('"', " ").replace("'", " ").strip()
        kata = aman.split(" ")[0]
        try:
            elemen.click()
        except Exception:  # noqa: BLE001 — input readonly: buka lewat tombol panah combo
            try:
                elemen.find_element(By.XPATH, "following::*[contains(@class, 'x-form-trigger')][1]").click()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Kolom pilihan tidak dapat dibuka: {exc}") from exc
        try:
            elemen.send_keys(Keys.CONTROL, "a")
            elemen.send_keys(nilai)
        except Exception:  # noqa: BLE001 — sebagian combo readonly, cukup daftar dibuka
            pass
        for xpath in (f'//li[contains(@class, "x-boundlist-item") and contains(normalize-space(), "{aman}")]',
                      f'//li[contains(@class, "x-boundlist-item") and starts-with(normalize-space(), "{kata}")]'):
            try:
                item = WebDriverWait(peramban, 4).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                item.click()
                return
            except Exception:  # noqa: BLE001 — coba cara berikutnya
                continue
        elemen.send_keys(Keys.RETURN)  # cara terakhir, sama seperti skrip asli

    def _pesan_dapodik(self, peramban) -> str:
        """Baca kotak pesan Dapodik yang menandakan penolakan/peringatan ('' bila tidak ada)."""
        from selenium.webdriver.common.by import By

        try:
            kotak = peramban.find_elements(By.CSS_SELECTOR, "div.x-message-box, div.x-window")
        except Exception:  # noqa: BLE001
            return ""
        for elemen in kotak:
            try:
                if not elemen.is_displayed():
                    continue
                teks = " ".join((elemen.text or "").split())
            except Exception:  # noqa: BLE001
                continue
            if not teks:
                continue
            rendah = teks.lower()
            if any(kata in rendah for kata in ("harus", "wajib", "tidak boleh", "tidak valid",
                                               "gagal", "error", "salah", "belum diisi",
                                               "periksa kembali")):
                self._tutup_pesan(peramban)
                return teks[:250]
        return ""

    def _tutup_pesan(self, peramban) -> None:
        """Tutup kotak pesan Dapodik supaya antrean berikutnya bisa diproses."""
        from selenium.webdriver.common.by import By

        try:
            tombol = peramban.find_elements(By.CSS_SELECTOR,
                                            "div.x-message-box .x-btn, div.x-message-box button")
        except Exception:  # noqa: BLE001
            return
        for elemen in tombol:
            try:
                if elemen.is_displayed():
                    peramban.execute_script("arguments[0].click();", elemen)
                    time.sleep(1)
                    return
            except Exception:  # noqa: BLE001
                continue

    # ---------------------------------------------------------------- login --- #
    def _login(self, peramban) -> None:
        """Masuk ke Dapodik dan buka daftar peserta didik.

        Dibuat tahan perbedaan versi: menunggu halaman selesai dimuat lebih dulu,
        mengenali halaman galat Chrome, dan memakai selector cadangan bila tombol
        bawaan tidak ketemu — semuanya dilaporkan pada catatan pekerjaan.
        """
        url = (self.opsi.get("bot_url") or "").strip()
        if not url:
            raise ValueError("Alamat Dapodik belum diisi pada pengaturan bot.")
        self._catat_kepala(f"Membuka {url} …")
        try:
            peramban.get(url)
        except Exception as exc:  # noqa: BLE001 — halaman gagal dimuat sama sekali
            raise RuntimeError(
                f"Halaman {url} tidak dapat dibuka dalam batas waktu. Pastikan aplikasi "
                f"Dapodik sedang berjalan (Rincian: {type(exc).__name__}).") from exc
        self._tunggu_halaman(peramban)

        galat_halaman = self._galat_halaman(peramban)
        if galat_halaman:
            raise RuntimeError(galat_halaman)

        peta = peta_selector()
        try:
            loc_nama, nilai_nama, _ = self._cari_dengan_cadangan(peramban, "login_username", peta)
            loc_sandi, _, _ = self._cari_dengan_cadangan(peramban, "login_password", peta)
        except TimeoutError:
            ringkas = self._ringkas_halaman(peramban)
            bukti = self._bukti(peramban, "gagal-login")
            pesan = (f"Formulir masuk tidak ditemukan pada halaman "
                     f"'{ringkas.get('judul') or '(tanpa judul)'}'. ")
            if not ringkas.get("isian_sandi"):
                pesan += ("Halaman tidak memuat kolom kata sandi — kemungkinan masih memuat, "
                          "alamat salah, atau Dapodik belum siap. ")
            pesan += (f"Isian teks terlihat: {ringkas.get('isian_teks') or 'tidak ada'}. "
                      f"Bukti pemeriksaan: {bukti or 'tidak tersimpan'}. "
                      "Bila Dapodik memang sudah tampil, sesuaikan selector lewat "
                      "«Peta tombol Dapodik» (atau pakai tombol Uji koneksi Dapodik).")
            raise RuntimeError(pesan) from None
        nama_input = self._tunggu_elemen(peramban, loc_nama)
        sandi_input = self._tunggu_elemen(peramban, loc_sandi)
        nama_input.send_keys(self.opsi.get("bot_username", ""))
        sandi_input.send_keys(self.opsi.get("bot_password", ""))
        loc_tombol, _, _ = self._cari_dengan_cadangan(peramban, "login_tombol", peta)
        self._klik_aman(peramban, loc_tombol)
        time.sleep(2)
        self._tunggu_halaman(peramban)
        if self._galat_halaman(peramban):
            raise RuntimeError(self._galat_halaman(peramban))

        # menu tujuan (mis. Peserta Didik) lalu dua menu lanjutan seperti skrip asli
        loc_menu, _, _ = self._cari_dengan_cadangan(peramban, "menu_tujuan", peta)
        self._klik_aman(peramban, loc_menu)
        time.sleep(5)
        try:
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait

            tutup = WebDriverWait(peramban, 5).until(
                EC.element_to_be_clickable(self._locator("popup_tutup", peta)))
            tutup.click()
        except Exception:  # noqa: BLE001 — popup memang sering tidak muncul
            self._catat_kepala("Popup tidak muncul, lanjut.")
        time.sleep(2)
        loc_satu, nilai_satu, _ = self._cari_dengan_cadangan(peramban, "menu_1", peta)
        self._klik_aman(peramban, loc_satu)
        loc_dua, nilai_dua, _ = self._cari_dengan_cadangan(peramban, "menu_2", peta)
        self._klik_aman(peramban, loc_dua)
        time.sleep(2)
        self._catat_kepala("Siap memproses antrean.")

    def _cari_dengan_cadangan(self, peramban, kunci: str, peta: dict[str, str],
                              wajib: bool = True, batas: float | None = None) -> tuple[Any, str, bool]:
        """Cari elemen memakai selector terpasang, lalu selector cadangan.

        Kembalikan ``(locator, nilai_selector, memakai_cadangan)``. Dapodik sering
        diperbarui sehingga XPath/id berubah; cadangan berbasis teks membuat bot tetap
        jalan dan pesan pada log memberi tahu selector mana yang benar-benar dipakai
        (agar bisa disalin ke *Peta tombol Dapodik*).
        """
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        terpasang = (peta.get(kunci) or "").strip()
        kandidat: list[str] = []
        for nilai in [terpasang, *SELECTOR_CADANGAN.get(kunci, [])]:
            nilai = (nilai or "").strip()
            if nilai and nilai not in kandidat:
                kandidat.append(nilai)
        if not kandidat:
            raise ValueError(f"Selector '{kunci}' belum diisi.")
        batas = batas or float(self.opsi.get("bot_timeout", "30") or 30)
        galat: Exception | None = None
        for indeks, nilai in enumerate(kandidat):
            try:
                locator = self._locator_nilai(nilai)
                WebDriverWait(peramban, batas if indeks == 0 else SELEKTOR_UJI_DETIK).until(
                    EC.visibility_of_element_located(locator))
                if indeks > 0:
                    self._catat_kepala(f"[selector] '{kunci}' memakai cadangan: {nilai}")
                return locator, nilai, indeks > 0
            except Exception as exc:  # noqa: BLE001 — coba kandidat berikutnya
                galat = exc
        pesan = (f"Tidak menemukan elemen '{kunci}' setelah mencoba "
                 f"{len(kandidat)} selector (terakhir gagal: {type(galat).__name__}).")
        if wajib:
            raise TimeoutError(pesan)
        return None, "", False

    def _locator_nilai(self, nilai: str):
        from selenium.webdriver.common.by import By

        if not nilai:
            raise ValueError("Selector kosong.")
        if nilai.startswith("name:"):
            return (By.NAME, nilai[5:])
        if nilai.startswith("css:"):
            return (By.CSS_SELECTOR, nilai[4:])
        if nilai.startswith("xpath:"):
            return (By.XPATH, nilai[6:])
        if nilai.startswith("//") or nilai.startswith("("):
            return (By.XPATH, nilai)
        if nilai.startswith("[") or nilai.startswith(".") or nilai.startswith("#"):
            return (By.CSS_SELECTOR, nilai)
        return (By.NAME, nilai)

    def _locator(self, kunci: str, peta: dict[str, str]):
        """Selector terpasang untuk sebuah kunci (tanpa cadangan)."""
        nilai = peta.get(kunci, "")
        if not nilai:
            raise ValueError(f"Selector '{kunci}' belum diisi.")
        return self._locator_nilai(nilai)

    # ------------------------------------------------------- satu siswa ----- #
    def _aturan_lewati(self, siswa: dict[str, Any]) -> str:
        """Alasan siswa dilewati sebelum menyentuh Dapodik ('' = lanjut)."""
        nisn = str(siswa.get("nisn") or "").strip()
        if not nisn.isdigit() or len(nisn) != 10:
            return f"NISN '{nisn}' bukan 10 digit angka"
        nis = str(siswa.get("nis") or siswa.get("nipd") or "").strip()
        if not nis and self.opsi.get("bot_pakai_nisn", "0") != "1":
            return "NIPD/NIS belum diisi pada data siswa"
        return ""

    def _proses_satu(self, peramban, siswa: dict[str, Any], item_id: int | None) -> None:
        self.sedang = siswa
        nisn = str(siswa.get("nisn") or "").strip()
        nis = str(siswa.get("nis") or siswa.get("nipd") or "").strip()
        if not nis and self.opsi.get("bot_pakai_nisn", "0") == "1":
            nis = nisn
        if item_id:
            services.catat_item_bot(item_id, "menunggu", "sedang diproses")
        try:
            alasan = self._aturan_lewati(siswa)
            if alasan:
                self._selesai_item(item_id, "dilewati", alasan, nisn)
                return

            if self.simulasi:
                time.sleep(0.05)
                self._selesai_item(item_id, "sukses",
                                   f"Uji coba: NIS {nis} akan didaftarkan lewat "
                                   f"{self.opsi.get('bot_url', 'Dapodik')}", nisn)
                return

            from selenium.common.exceptions import TimeoutException
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait

            peta = peta_selector()

            # 1) cari NISN pada kotak pencarian
            loc_cari, _, _ = self._cari_dengan_cadangan(peramban, "cari_nisn", peta)
            kotak = self._tunggu_elemen(peramban, loc_cari)
            kotak.click()
            kotak.send_keys(Keys.CONTROL, "a")
            kotak.send_keys(nisn)
            kotak.send_keys(Keys.RETURN)
            self._tunggu_overlay(peramban)

            # 2) baris tabel yang memuat NISN
            xpath_baris = (f'//tr[contains(@class, "{BARIS_TABEL}") '
                           f'and .//td[contains(., "{nisn}")]]')
            batas = float(self.opsi.get("bot_timeout", "15") or 15)
            try:
                WebDriverWait(peramban, batas).until(
                    EC.element_to_be_clickable((By.XPATH, xpath_baris)))
            except TimeoutException:
                self._selesai_item(item_id, "dilewati",
                                   "Data NISN tidak ditemukan pada tabel Dapodik", nisn)
                return
            self._klik_aman(peramban, (By.XPATH, xpath_baris))
            time.sleep(2)

            # 3) tombol Registrasi
            loc_daftar, _, _ = self._cari_dengan_cadangan(peramban, "tombol_registrasi", peta)
            self._klik_aman(peramban, loc_daftar)
            time.sleep(2)

            # 4) isi NIS
            loc_nis, _, _ = self._cari_dengan_cadangan(peramban, "input_nis", peta)
            self._isi(peramban, loc_nis, nis)

            # 5) centang semua pilihan "Ya"
            if self.opsi.get("bot_jawaban_ya", "1") == "1":
                loc_ya = self._locator("radio_ya", peta)
                kotak_ya = peramban.find_elements(*loc_ya)
                if not kotak_ya:
                    for kandidat in SELECTOR_CADANGAN.get("radio_ya", []):
                        kotak_ya = peramban.find_elements(*self._locator_nilai(kandidat))
                        if kotak_ya:
                            break
                for elemen in kotak_ya:
                    if not elemen.is_selected():
                        peramban.execute_script("arguments[0].click();", elemen)

            # 6) hobi & 7) cita-cita (kolom pilihan Dapodik)
            loc_hobi, _, _ = self._cari_dengan_cadangan(peramban, "hobi", peta)
            self._pilih_kolom_pilihan(peramban, loc_hobi, self.opsi.get("bot_hobi", ""))
            time.sleep(1)
            loc_cita, _, _ = self._cari_dengan_cadangan(peramban, "cita", peta)
            self._pilih_kolom_pilihan(peramban, loc_cita, self.opsi.get("bot_cita", ""))

            # 8) simpan dan tutup
            loc_simpan, _, _ = self._cari_dengan_cadangan(peramban, "simpan", peta)
            self._klik_aman(peramban, loc_simpan)
            self._tunggu_overlay(peramban)
            time.sleep(2)

            # Dapodik kadang menolak dengan kotak pesan — jangan dianggap berhasil.
            keluhan = self._pesan_dapodik(peramban)
            if keluhan:
                self._selesai_item(item_id, "gagal", f"Ditolak Dapodik: {keluhan}", nisn)
                return
            self._selesai_item(item_id, "sukses", f"Registrasi NIS {nis} berhasil dikirim", nisn)
        except Exception as exc:  # noqa: BLE001 — satu siswa gagal, lanjut ke berikutnya
            pesan = f"{type(exc).__name__}: {str(exc)[:300]}"
            if peramban is not None:
                bukti = self._bukti(peramban, f"gagal-{nisn}")
                if bukti:
                    pesan = f"{pesan} · bukti: {bukti}"
            self._selesai_item(item_id, "gagal", pesan, nisn)

    def _selesai_item(self, item_id: int | None, status: str, pesan: str, nisn: str) -> None:
        if item_id:
            services.catat_item_bot(item_id, status, pesan)
        services.perbarui_job_bot(self.job_id,
                                  tambah_sukses=1 if status == "sukses" else 0,
                                  tambah_gagal=1 if status == "gagal" else 0)
        tanda = {"sukses": "OK", "gagal": "GAGAL", "dilewati": "LEWAT"}.get(status, status.upper())
        self._catat_kepala(f"[{tanda}] {nisn} — {pesan}")
        self.sedang = None


# --------------------------------------------------------------------------- #
# Pengelola pekerjaan yang sedang berjalan (satu saja)
# --------------------------------------------------------------------------- #
_bot: BotDapodik | None = None
_kunci = threading.Lock()


def _lupakan(bot: BotDapodik) -> None:
    global _bot
    with _kunci:
        if _bot is bot:
            _bot = None


def bot_berjalan() -> BotDapodik | None:
    """Bot yang sedang bekerja, atau ``None`` bila tidak ada pekerjaan berjalan."""
    with _kunci:
        return _bot if (_bot is not None and _bot.berjalan()) else None


def mulai_bot(antrean: list[dict[str, Any]], opsi: dict[str, str], actor: str | None = None,
              kepala: Callable[[str], None] | None = None) -> tuple[int, BotDapodik]:
    """Buat pekerjaan baru & mulai bot di belakang layar. Kembalikan (job_id, bot)."""
    global _bot
    with _kunci:
        if _bot is not None and _bot.berjalan():
            raise BotBerjalanError("Bot masih berjalan. Hentikan dulu sebelum memulai lagi.")
        if not antrean:
            raise BotBerjalanError("Antrean kosong — tidak ada siswa yang perlu diproses.")
        mode = "simulasi" if opsi.get("bot_simulasi") == "1" else (
            "headless" if opsi.get("bot_headless") == "1" else "tampak")
        job_id = services.buat_job_bot(len(antrean), {
            "url": opsi.get("bot_url"),
            "hobi": opsi.get("bot_hobi"),
            "cita": opsi.get("bot_cita"),
            "pakai_nisn": opsi.get("bot_pakai_nisn"),
        }, actor=actor, mode=mode)
        item_ids = [services.isi_item_bot(job_id, siswa) for siswa in antrean]
        _bot = BotDapodik(job_id, antrean, item_ids, opsi, kepala=kepala)
        _bot.jalankan()
        return job_id, _bot


def hentikan_bot() -> bool:
    dengan = bot_berjalan()
    if dengan is None or not dengan.berjalan():
        return False
    dengan.hentikan()
    return True


def uji_dapodik(opsi: dict[str, str] | None = None) -> dict[str, Any]:
    """Buka Dapodik sebentar lalu laporkan apa yang terlihat.

    Alat bantu bila bot berhenti dengan TimeoutException: hasilnya menunjukkan
    judul halaman, alamat akhir, kolom/tombol/menu yang tampak, serta selector
    mana yang cocok. Bekerja juga saat selectornya meleset (tidak melempar galat),
    sehingga pengguna bisa menyalin selector yang benar ke «Peta tombol Dapodik».
    """
    opsi = dict(opsi or services.bot_setting())
    bot = BotDapodik(0, [], [], opsi)
    laporan: dict[str, Any] = {
        "waktu": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": (opsi.get("bot_url") or "").strip(),
        "headless": opsi.get("bot_headless", "1") == "1",
        "simulasi": opsi.get("bot_simulasi", "0") == "1",
        "catatan": [],
    }
    if not laporan["url"]:
        laporan["galat"] = "Alamat Dapodik belum diisi pada pengaturan bot."
        return laporan

    peramban = None
    try:
        peramban = bot._buka_peramban()
        peramban.get(laporan["url"])
        bot._tunggu_halaman(peramban)
        laporan.update({k: v for k, v in bot._ringkas_halaman(peramban).items()})
        peta = peta_selector()
        cocok: dict[str, bool] = {}
        for kunci in ("login_username", "login_password", "login_tombol"):
            _, nilai, cadangan = bot._cari_dengan_cadangan(peramban, kunci, peta, wajib=False)
            cocok[kunci] = bool(nilai)
            laporan.setdefault("selector_cocok", {})[kunci] = (
                "bawaan" if nilai and not cadangan else ("cadangan" if nilai else "tidak ketemu"))
        laporan["bukti"] = bot._bukti(peramban, "uji-koneksi-dapodik")
        if not cocok.get("login_username"):
            laporan["catatan"].append(
                "Kolom nama pengguna tidak ditemukan: periksa apakah alamat Dapodik benar dan "
                "aplikasi Dapodik sudah berjalan.")
    except Exception as exc:  # noqa: BLE001 — alat bantu, selalu kembalikan laporan
        laporan["galat"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        if peramban is not None:
            try:
                peramban.quit()
            except Exception:  # noqa: BLE001
                pass
    return laporan


def status_bot() -> dict[str, Any]:
    dengan = bot_berjalan()
    return dengan.kemajuan() if dengan else {}
