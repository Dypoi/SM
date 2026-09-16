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
from typing import Any, Callable

from . import services

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
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

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
            return webdriver.Chrome(options=opsi)
        except Exception as exc:  # noqa: BLE001 — beri pesan yang bisa ditindaklanjuti
            raise RuntimeError(
                "Google Chrome tidak dapat dibuka. Pastikan Chrome sudah terpasang di PC ini; "
                "bila muncul keluhan driver, sambungkan internet sekali agar Selenium mengunduh "
                f"drivernya otomatis. Rincian: {type(exc).__name__}: {str(exc)[:200]}") from exc

    def _tunggu(self, peramban, detik: float) -> None:
        time.sleep(detik)

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
        url = (self.opsi.get("bot_url") or "").strip()
        if not url:
            raise ValueError("Alamat Dapodik belum diisi pada pengaturan bot.")
        self._catat_kepala(f"Membuka {url} …")
        peramban.get(url)

        peta = peta_selector()
        nama_input = self._tunggu_elemen(peramban, (self._locator("login_username", peta)))
        sandi_input = self._tunggu_elemen(peramban, (self._locator("login_password", peta)))
        nama_input.send_keys(self.opsi.get("bot_username", ""))
        sandi_input.send_keys(self.opsi.get("bot_password", ""))
        self._klik_aman(peramban, self._locator("login_tombol", peta))
        time.sleep(2)

        # menu tujuan (mis. Peserta Didik) lalu dua menu lanjutan seperti skrip asli
        self._klik_aman(peramban, self._locator("menu_tujuan", peta))
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
        self._klik_aman(peramban, self._locator("menu_1", peta))
        self._klik_aman(peramban, self._locator("menu_2", peta))
        time.sleep(2)
        self._catat_kepala("Siap memproses antrean.")

    def _locator(self, kunci: str, peta: dict[str, str]):
        from selenium.webdriver.common.by import By

        nilai = peta.get(kunci, "")
        if not nilai:
            raise ValueError(f"Selector '{kunci}' belum diisi.")
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
            kotak = self._tunggu_elemen(peramban, self._locator("cari_nisn", peta))
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
            self._klik_aman(peramban, self._locator("tombol_registrasi", peta))
            time.sleep(2)

            # 4) isi NIS
            self._isi(peramban, self._locator("input_nis", peta), nis)

            # 5) centang semua pilihan "Ya"
            if self.opsi.get("bot_jawaban_ya", "1") == "1":
                kotak_ya = peramban.find_elements(*self._locator("radio_ya", peta))
                for elemen in kotak_ya:
                    if not elemen.is_selected():
                        peramban.execute_script("arguments[0].click();", elemen)

            # 6) hobi & 7) cita-cita (kolom pilihan Dapodik)
            self._pilih_kolom_pilihan(peramban, self._locator("hobi", peta),
                                      self.opsi.get("bot_hobi", ""))
            time.sleep(1)
            self._pilih_kolom_pilihan(peramban, self._locator("cita", peta),
                                      self.opsi.get("bot_cita", ""))

            # 8) simpan dan tutup
            self._klik_aman(peramban, self._locator("simpan", peta))
            self._tunggu_overlay(peramban)
            time.sleep(2)

            # Dapodik kadang menolak dengan kotak pesan — jangan dianggap berhasil.
            keluhan = self._pesan_dapodik(peramban)
            if keluhan:
                self._selesai_item(item_id, "gagal", f"Ditolak Dapodik: {keluhan}", nisn)
                return
            self._selesai_item(item_id, "sukses", f"Registrasi NIS {nis} berhasil dikirim", nisn)
        except Exception as exc:  # noqa: BLE001 — satu siswa gagal, lanjut ke berikutnya
            self._selesai_item(item_id, "gagal", f"{type(exc).__name__}: {str(exc)[:300]}", nisn)

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


def status_bot() -> dict[str, Any]:
    dengan = bot_berjalan()
    return dengan.kemajuan() if dengan else {}
