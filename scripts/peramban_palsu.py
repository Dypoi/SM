"""Peramban palsu untuk menguji bot Dapodik tanpa Chrome.

Lingkungan uji (sandbox/CI) tidak punya Google Chrome, padahal perilaku bot perlu
diuji: menunggu formulir login tampil, menembus halaman pembuka (splash), mengisi
kolom yang belum terlihat, dan mengenali selector sendiri.

Skenario yang tersedia: ``splash`` (halaman pembuka), ``kolom_tersembunyi`` (persis
laporan PC sekolah), ``siap``, ``mask`` (masih tertutup lapisan loading Ext JS),
``masuk`` (login berhasil setelah tombol ditekan), ``alur_penuh`` (halaman login,
menu, tabel, dan formulir Registrasi persis skrip sekolah), ``xpath_bawaan``, ``kosong``.
Panel «Data Periodik» berada di dalam **area gulir sendiri** (``div[4]`` pada halaman
Dapodik) sehingga ``window.scrollBy`` TIDAK menjangkaunya; ``siapkan_periodik_perlu_gulir(n)``
membuat kolomnya baru terjangkau setelah panelnya digulir dengan ``scrollIntoView``
(mis. ``siapkan_periodik_perlu_gulir(2)``).
Kotak centang/radio Ext JS juga ditirukan sebenarnya: klik lewat skrip
(``arguments[0].click()``) **tidak** mengubah keadaan terpilih — hanya klik sungguhan,
klik pembungkus/label (``x-form-cb-wrap-inner``), atau urutan tetikus lengkap
(mousedown → mouseup → click) yang mengubahnya.
Formulir Registrasi dapat diberi kolom «Sekolah Asal» (``tambah_formulir_registrasi(nisn,
sekolah_asal="SD NEGERI …", nama_kolom="sekolah_asal")``) — kolom itu dicari bot lewat
labelnya maupun lewat namanya, seperti di Dapodik.
Panggil ``sibukkan()`` untuk menyalakan lapisan pemuatan yang tidak pernah hilang — klik
biasa akan tertelan (``ElementClickInterceptedException``) seperti di PC sekolah.
Popup pengumuman Dapodik ("Selamat Datang di Aplikasi Dapodik 2027.b") juga bisa ditirukan:
``siapkan_popup(detik)`` mengaturnya muncul beberapa detik setelah menu dibuka — selagi popup
itu tampil, aplikasi mengabaikan klik di luarnya (persis laporan PC sekolah yang gagal di
tahap siswa karena popup menutupi halaman).

Kelas di sini meniru bagian API Selenium WebDriver yang dipakai ``app/bot_dapodik``
secukupnya (``find_element``, ``find_elements``, ``execute_script``, ``is_displayed``,
``click``, ``send_keys``) sehingga skenario seperti yang dialami di PC sekolah dapat
direproduksi. **Hanya untuk pengujian** — aplikasi tidak memakainya.
"""

from __future__ import annotations

import re
import time
from typing import Any

from selenium.common.exceptions import (ElementClickInterceptedException,
                                        ElementNotInteractableException,
                                        NoSuchElementException)


class UnsurPalsu:
    """Satu elemen halaman palsu (input/tombol/tautan)."""

    def __init__(self, peramban: "PerambanPalsu", tag: str = "input", **sifat: Any) -> None:
        self.peramban = peramban
        self.tag_name = tag
        self.type = sifat.get("type", "")
        self.name = sifat.get("name", "")
        self.id = sifat.get("id", "")
        self.placeholder = sifat.get("placeholder", "")
        self.aria = sifat.get("aria", "")
        self.teks = sifat.get("teks", "")
        self.terlihat = bool(sifat.get("terlihat", True))
        self.enabled = bool(sifat.get("enabled", True))
        self.lebar = int(sifat.get("lebar", 180 if self.terlihat else 0))
        self.tinggi = int(sifat.get("tinggi", 24 if self.terlihat else 0))
        self.nilai = sifat.get("nilai", "")
        self.diklik = 0
        self.diketik: list[str] = []
        self.kelas = sifat.get("kelas", "")
        #: True = unsur milik popup pengumuman (tombol Tutup & isi jendelanya)
        self.popup = bool(sifat.get("popup", False))
        #: True = baris tabel sudah terpilih (Dapodik: pilihan terjadi saat mousedown)
        self.terpilih = bool(sifat.get("terpilih", False))
        #: Teks label di sebelah kolom (mis. "Sekolah Asal") — dipakai bot mencari lewat label
        self.label = str(sifat.get("label", ""))
        #: True = unsur milik panel «Data Periodik» (hanya hidup setelah baris siswa dipilih)
        self.periodik = bool(sifat.get("periodik", False))
        #: True = wadah/panel «Data Periodik Peserta Didik» (area gulir sendiri)
        self.panel_periodik = bool(sifat.get("panel_periodik", False))
        #: Nama kolom yang dipilih oleh pembungkus ini (kotak centang/radio di dalamnya)
        self.untuk = str(sifat.get("untuk", ""))
        #: Pilihan yang diwakili pembungkus/label ini (mis. "Lebih dari 1 km")
        self.pilihan = str(sifat.get("pilihan", ""))
        #: Unsur induk (untuk XPath leluhur sederhana, mis. mencari pembungkus)
        self.induk: "UnsurPalsu | None" = None
        #: True = tombol «Simpan dan Tutup» milik panel Data Periodik
        self.simpan_periodik = bool(sifat.get("simpan_periodik", False))
        #: Nama kelompok pilihan (mis. "jarak") — mengklik satu anggota melepas yang lain
        self.kelompok = str(sifat.get("kelompok", ""))
        #: XPath absolut skrip sekolah, mis. /html/body/div[5]/div[2]/form/input
        self.jalur = sifat.get("jalur", "")

    # ------------------------------------------------------------ atribut --- #
    def get_attribute(self, nama: str) -> str | None:
        peta = {"type": self.type, "name": self.name, "id": self.id,
                "placeholder": self.placeholder, "aria-label": self.aria,
                "value": self.nilai, "class": self.kelas, "label": self.label}
        return peta.get(nama, self.nilai if nama == "value" else None)

    @property
    def text(self) -> str:
        return self.teks

    @property
    def size(self) -> dict[str, int]:
        return {"width": self.lebar, "height": self.tinggi}

    def is_displayed(self) -> bool:
        # Skenario "splash": kolom login baru terlihat setelah tombol pembuka diklik.
        return bool(self.peramban._terlihat_otomatis(self))

    def is_enabled(self) -> bool:
        return bool(self.enabled)

    def is_selected(self) -> bool:
        """Terpilih — dipakai untuk baris tabel & kotak centang."""
        return bool(self.terpilih)

    # ------------------------------------------------------------ aksi ------ #
    def _buka_formulir_bila_pembuka(self) -> None:
        if self.teks.strip().lower() == "masuk" and not self.name and not self.id:
            # Tombol pembuka halaman depan: formulir login baru terlihat sesudah ini.
            self.peramban.buka_formulir = True

    def _klik_paksa(self, script: bool = False) -> None:
        """Klik seperti lewat skrip: tetap bekerja walau unsur tidak terlihat.

        ``script=True`` = klik dikirim lewat skrip halaman (``arguments[0].click()``).
        Kotak centang/radio Data Periodik **tidak dihiraukan** dalam mode ini (persis
        Ext JS/Dapodik: keadaan centangnya tidak berubah), kecuali pembungkus/labelnya.
        """
        if self.untuk:      # pembungkus/label Ext JS: mengkliknya memilih kotak di dalamnya
            if self.peramban.hanya_label_yang_menerima and self.periodik and \
                    "x-form-cb-label" not in (self.kelas or ""):
                # Hanya labellah yang menerima klik; pembungkusnya ditelan lapisan di atasnya.
                self.peramban.klik_diabaikan += 1
                return
            self.peramban.pilih_lewat_pembungkus(self.untuk, self.pilihan)
            return
        if self.type in ("radio", "checkbox") and (self.periodik or self.induk is not None) \
                and (script or (self.peramban.hanya_label_yang_menerima and self.periodik)):
            self.peramban.diklik_skrip_diabaikan += 1
            return
        if self.periodik and not self.peramban.panel_periodik_terbuka():
            self.peramban.klik_diabaikan += 1      # panel kelabu: Dapodik mengabaikan klik
            return
        if self.peramban.popup_terbuka() and not self.popup:
            # Selagi popup pengumuman tampil, aplikasi mengabaikan klik di luarnya —
            # inilah yang membuat formulir Registrasi tidak pernah terbuka di PC sekolah.
            self.peramban.klik_terblokir += 1
            return
        self.diklik += 1
        # Catatan: di Ext JS pemilihan baris terjadi pada *mousedown*; klik lewat skrip
        # (arguments[0].click()) hanya mengirim event 'click' sehingga baris TIDAK terpilih —
        # inilah sebabnya tombol Registrasi tidak membuka apa pun di PC sekolah.
        if self.popup and (self.teks.strip().lower() == "tutup" or
                           "x-tool-close" in (self.kelas or "")):
            self.peramban.tutup_popup()
            return
        if self.name == "tombol_registrasi" or \
                "x-btn-inner-soft-green-small" in (self.kelas or ""):
            self.peramban.buka_formulir_registrasi()
        if self.simpan_periodik:
            self.peramban.simpan_data_periodik()
        if self.jalur == "/html/body/div[1]/ul/li[2]/div/a/button":
            # Menu Peserta Didik dibuka → Dapodik menampilkan popup pengumuman versi.
            self.peramban._menu_tujuan_diklik()
        self._buka_formulir_bila_pembuka()
        if self.peramban.skenario == "masuk" and self.teks.strip().lower() in ("masuk", "login"):
            # Tombol kirim formulir login: halaman berpindah ke daftar peserta didik.
            self.peramban.sudah_masuk = True
            self.peramban.unsur.append(UnsurPalsu(self.peramban, "a", teks="Peserta Didik"))
        if self.peramban.skenario == "alur_penuh" and self.teks.strip().lower() == "masuk":
            self.peramban.buka_daftar_peserta_didik()

    def click(self) -> None:
        """Klik sungguhan (mouse event asli) — inilah yang memilih baris di Ext JS."""
        if not self.is_displayed():
            raise ElementNotInteractableException("unsur tidak terlihat")
        if self.peramban.popup_terbuka() and not self.popup:
            # Popup pengumuman (beserta lapisan modalnya) menutupi halaman ini.
            raise ElementClickInterceptedException(
                "element click intercepted: popup pengumuman Dapodik menutupi unsur ini")
        if self.peramban.mask_keras:
            # Persis keluhan di PC sekolah: lapisan pemuatan Ext JS menutupi kolom,
            # sehingga klik biasa ditelan (ElementClickInterceptedException).
            raise ElementClickInterceptedException(
                "element click intercepted: lapisan pemuatan menutupi unsur ini")
        self._pilih_baris()          # klik sungguhan memilih baris tabel (mousedown)
        self._klik_paksa()

    def _pilih_kotak(self) -> None:
        """Kotak centang/radio terpilih (klik sungguhan / urutan tetikus asli)."""
        if self.terpilih:
            return
        self.terpilih = True
        if self.kelompok:
            for lain in self.peramban.unsur:
                if lain is not self and lain.kelompok == self.kelompok:
                    lain.terpilih = False
        if self.name == "jarak_rumah" or (self.kelompok or "").startswith("jarak"):
            # Hanya pilihan jarak yang dihitung (pilihan «Ya» tidak ikut tercampur).
            self.peramban.jarak_dicentang += 1
            self.peramban.jarak_pilihan = (self.label or self.jalur).strip()

    def _pilih_baris(self) -> None:
        """Klik sungguhan pada baris tabel / kotak centang = memilihnya (seperti Ext JS)."""
        if self.type in ("radio", "checkbox") and (self.periodik or self.induk is not None):
            if self.peramban.klik_kotak_ditelan or \
                    (self.peramban.hanya_label_yang_menerima and self.periodik):
                # Klik pada kotaknya ditelan lapisan di atasnya; pada baris «Jarak rumah ke
                # sekolah» hanya labelnya yang menerima (pilihan «Ya» tetap bisa lewat wadah).
                self.peramban.klik_kotak_ditelan_kali += 1
            elif self.periodik and not (self.peramban.panel_periodik_terbuka()
                                        and self.peramban.periodik_siap()):
                # Panelnya masih kelabu, atau kotaknya belum terjangkau karena area gulir
                # panel belum digeser: klik ini tidak menghasilkan apa-apa.
                self.peramban.klik_diabaikan += 1
            else:
                self._pilih_kotak()
            return
        if self.tag_name == "tr" and "x-grid-row" in (self.kelas or ""):
            self.terpilih = True
            if "x-grid-row-selected" not in self.kelas:
                self.kelas = (self.kelas + " x-grid-row-selected").strip()
            self.peramban._periodik_tersimpan = False      # panel Data Periodik terbuka lagi

    def send_keys(self, *tombol: Any) -> None:
        """Meniru pengetikan: tombol pengubah (Ctrl+A) ditangani, bukan diketik apa adanya."""
        if not self.is_displayed():
            raise ElementNotInteractableException("unsur tidak terlihat")
        if self.periodik and (not self.peramban.panel_periodik_terbuka()
                              or not self.peramban.periodik_siap()):
            # Panel masih kelabu, atau kolomnya belum terjangkau karena area gulir panel
            # belum digeser: Dapodik mengabaikan ketikan ini — nilainya tidak tersimpan.
            self.peramban.ketikan_diabaikan += 1
            return
        from selenium.webdriver.common.keys import Keys

        pengubah = (Keys.CONTROL, Keys.SHIFT, Keys.ALT, Keys.COMMAND)
        kontrol = False
        for bagian in tombol:
            if not isinstance(bagian, str) or not bagian:
                continue
            if bagian in pengubah:
                kontrol = True
                continue
            if bagian in (Keys.ENTER, Keys.RETURN, Keys.TAB):
                if (bagian in (Keys.ENTER, Keys.RETURN) and self.name == "cari_text"
                        and self.peramban._popup_setelah_cari):
                    self.peramban.munculkan_popup()   # pengumuman muncul saat pencarian
                kontrol = False
                continue
            if kontrol and bagian.lower() in ("a", "x"):
                if bagian.lower() == "a":
                    self.clear()          # Ctrl+A = pilih semua
                kontrol = False
                continue
            self.nilai += bagian
            self.diketik.append(bagian)
            kontrol = False

    def clear(self) -> None:
        self.nilai = ""
        self.diketik.clear()

    def find_elements(self, by: str = "", nilai: str = "") -> list["UnsurPalsu"]:
        """Cari unsur di dalam unsur ini.

        Didukung: XPath leluhur sederhana (``ancestor(-or-self)::…``) dan poros
        ``preceding::``/``following::input[…]`` — dipakai bot untuk melacak kotak
        centang/radio milik sebuah label.
        """
        if by != "xpath":
            return []
        if nilai.startswith("ancestor"):
            return self._leluhur(nilai)
        return self.peramban.poros_input(self, nilai)

    def _leluhur(self, ekspresi: str) -> list["UnsurPalsu"]:
        """Dukung ``ancestor(-or-self)::tag[contains(@class, "…")][1]`` seperti dipakai bot."""
        termasuk_self = ekspresi.startswith("ancestor-or-self")
        kelas = re.findall(r'contains\(@class,\s*[\'"]([^\'"]+)[\'"]\)', ekspresi)
        tag = re.search(r"ancestor(?:-or-self)?::(\w+)", ekspresi)
        kandidat: list["UnsurPalsu"] = [self] if termasuk_self else []
        induk = self.induk
        while induk is not None:
            kandidat.append(induk)
            induk = induk.induk
        hasil: list["UnsurPalsu"] = []
        for unsur in kandidat:
            if tag and tag.group(1) != "*" and unsur.tag_name != tag.group(1):
                continue
            if any(k.lower() not in (unsur.kelas or "").lower() for k in kelas):
                continue
            hasil.append(unsur)
            if "[1]" in ekspresi:
                break
        return hasil

    def find_element(self, by: str = "", nilai: str = "") -> "UnsurPalsu":
        raise NoSuchElementException(f"tidak ada {nilai}")


class PerambanPalsu:
    """Peramban tiruan dengan skenario halaman Dapodik."""

    def __init__(self, skenario: str = "splash") -> None:
        self.skenario = skenario
        self.url = ""
        self.judul = "Dapodik"
        self.buka_formulir = skenario != "splash"
        self.sudah_masuk = False
        self.nisn_dicari = ""
        #: berapa kali lapisan loading (div.x-mask) masih terlihat saat ditanya
        self.mask_sisa = 2 if skenario == "mask" else 0
        #: True = lapisan pemuatan tidak pernah hilang (klik biasa selalu tertelan)
        self.mask_keras = False
        #: detik (jam halaman) setelah menu tujuan diklik sebelum popup pengumuman muncul
        self.popup_detik: float | None = 0.0
        self._popup_muncul = False
        self._popup_mulai = 0.0
        self._popup_tutup = False
        #: berapa klik di luar popup yang diabaikan aplikasi (bukti penutupan salah waktu)
        self.klik_terblokir = 0
        #: berapa kali popup pengumuman berhasil ditutup
        self.ditutup_popup = 0
        #: True = formulir Registrasi baru muncul setelah tombol Registrasi ditekan
        self.registrasi_otomatis = False
        #: berapa klik Registrasi pertama yang diabaikan (meniru klik yang tertelan)
        self.tolak_klik_registrasi = 0
        #: Data Periodik: sudah disimpan (panel tertutup sampai baris dipilih kembali)
        self._periodik_tersimpan = False
        #: nilai yang benar-benar tersimpan dari panel Data Periodik
        self.data_periodik_tersimpan: dict[str, str] = {}
        #: berapa kali kotak «Jarak rumah ke sekolah» dicentang
        self.jarak_dicentang = 0
        #: pilihan jarak yang sedang tercentang (labelnya)
        self.jarak_pilihan = ""
        #: berapa ketikan/klik yang diabaikan karena panel Data Periodik masih kelabu
        self.ketikan_diabaikan = 0
        self.klik_diabaikan = 0
        #: semua jarak gulir halaman (px) — bukti bot memakai window.scrollBy seperti skrip
        self.gulir: list[int] = []
        #: scrollIntoView pada panel/unsur Data Periodik — inilah yang menjangkau area
        #: gulirnya sendiri (window.scrollBy tidak menolong, seperti di Dapodik)
        self.gulir_panel: list[str] = []
        #: kolom Data Periodik baru terjangkau setelah sekian kali scrollIntoView panelnya
        self.periodik_perlu_gulir = 0
        #: berapa klik lewat skrip pada kotak centang/radio yang TIDAK dihiraukan Ext JS
        self.diklik_skrip_diabaikan = 0
        #: True = klik SUNGGUHAN pada kotak centang/radio juga ditelan (hanya pembungkus/
        #: label di sekitarnya yang menerima) — persis bila ada lapisan di atas kotaknya
        self.klik_kotak_ditelan = False
        #: True = HANYA label `x-form-cb-label` yang menerima klik; klik pada kotaknya
        #: (nyata maupun skrip) dan pada pembungkus `x-form-cb-wrap-inner` ditelan —
        #: inilah keadaan yang diatasi skrip sekolah dengan mengklik labelnya
        self.hanya_label_yang_menerima = False
        #: berapa kali kolom isian menerima peristiwa input/change/blur dari bot
        self.peristiwa_dipicu = 0
        #: berapa klik sungguhan pada kotak centang/radio yang ditelan
        self.klik_kotak_ditelan_kali = 0
        #: berapa kali pilihan jarak dipilih lewat pembungkus/labelnya
        self.dipilih_lewat_pembungkus = 0
        #: True = popup pengumuman muncul saat pencarian ditekan; hasilnya tampil setelah ditutup
        self._popup_setelah_cari = False
        self._nisn_tersembunyi = ""
        #: jam halaman — dapat diganti jam palsu saat pengujian agar cepat
        self.jam = time.monotonic
        self.skrip: list[str] = []
        self.unsur: list[UnsurPalsu] = []
        self.ditutup = False
        self.disimpan: list[str] = []
        self._bangun_halaman()

    # ------------------------------------------------------------ halaman --- #
    def _bangun_halaman(self) -> None:
        if self.skenario == "kosong":
            return
        if self.skenario == "splash":
            # Halaman pembuka: hanya tombol "Masuk"; kolom login tersembunyi.
            self.unsur.append(UnsurPalsu(self, "button", teks="Masuk", terlihat=True))
            self.unsur.append(UnsurPalsu(self, "input", type="text", name="email",
                                         placeholder="Email", terlihat=False, lebar=0, tinggi=0))
            self.unsur.append(UnsurPalsu(self, "input", type="password", name="password",
                                         placeholder="Kata sandi", terlihat=False,
                                         lebar=0, tinggi=0))
            self.unsur.append(UnsurPalsu(self, "input", type="submit", name="",
                                         id="form2", nilai="", terlihat=True))
        elif self.skenario == "kolom_tersembunyi":
            # Persis seperti laporan pengguna: kolom ada di DOM tetapi belum terlihat,
            # tombol kirim formulir sudah terlihat.
            self.unsur.append(UnsurPalsu(self, "input", type="email", name="email",
                                         placeholder="Email", terlihat=False, lebar=0, tinggi=0))
            self.unsur.append(UnsurPalsu(self, "input", type="password", name="password",
                                         placeholder="Kata sandi", terlihat=False,
                                         lebar=0, tinggi=0))
            self.unsur.append(UnsurPalsu(self, "button", teks="Masuk", id="tombol-masuk"))
        elif self.skenario == "siap":
            self.unsur.append(UnsurPalsu(self, "input", type="email", name="email",
                                         placeholder="Email"))
            self.unsur.append(UnsurPalsu(self, "input", type="password", name="password",
                                         placeholder="Kata sandi"))
            self.unsur.append(UnsurPalsu(self, "button", teks="Masuk"))
        elif self.skenario == "mask":
            # Ext JS masih menutupi halaman dengan lapisan loading (div.x-mask);
            # skrip asli sekolah selalu menunggu lapisan ini hilang lebih dulu.
            self.unsur.append(UnsurPalsu(self, "input", type="email", name="email",
                                         placeholder="Email"))
            self.unsur.append(UnsurPalsu(self, "input", type="password", name="password",
                                         placeholder="Kata sandi"))
            self.unsur.append(UnsurPalsu(self, "button", teks="Masuk", id="form2"))
        elif self.skenario == "masuk":
            # Halaman siap; setelah tombol Masuk ditekan formulir hilang (login berhasil).
            self.unsur.append(UnsurPalsu(self, "input", type="email", name="email",
                                         placeholder="Email"))
            self.unsur.append(UnsurPalsu(self, "input", type="password", name="password",
                                         placeholder="Kata sandi"))
            self.unsur.append(UnsurPalsu(self, "button", teks="Masuk", id="form2"))
        elif self.skenario == "alur_penuh":
            # Halaman login persis selector bawaan skrip sekolah (XPath absolut).
            self.unsur.append(UnsurPalsu(self, "input", type="text", name="",
                                         jalur="/html/body/div[5]/div[2]/form/input"))
            self.unsur.append(UnsurPalsu(self, "input", type="password", name="",
                                         jalur="/html/body/div[5]/div[2]/form/div[1]/input"))
            self.unsur.append(UnsurPalsu(self, "button", teks="Masuk", id="form2"))
        elif self.skenario == "xpath_bawaan":
            # Halaman yang cocok dengan skrip bot asli (selector bawaan semuanya tepat).
            self.unsur.append(UnsurPalsu(self, "input", type="text", name="username",
                                         kelas="x-form-text"))
            self.unsur.append(UnsurPalsu(self, "input", type="password", name="password"))
            self.unsur.append(UnsurPalsu(self, "button", teks="Masuk", id="form2"))

    def _pasang_pembungkus_kotak(self) -> None:
        """Bungkus setiap kotak centang/radio dengan wadah Ext JS seperti Dapodik.

        Wadahnya berkelas ``x-form-cb-wrap-inner`` dan didampingi label ``x-form-cb-label``
        yang bertuliskan teks pilihannya; wadah diletakkan tepat di sebelah kotaknya (seperti
        DOM sungguhan). Klik lewat skrip pada kotaknya sendiri tidak dihiraukan — mengklik
        label (atau wadah) inilah cara skrip yang terbukti berhasil memilih radio.
        """
        for unsur in list(self.unsur):
            if unsur.type not in ("radio", "checkbox") or not unsur.kelompok:
                continue
            if unsur.induk is not None:
                continue                       # sudah punya wadah, jangan dibungkus dua kali
            pembungkus = UnsurPalsu(self, "div", kelas="x-form-cb-wrap-inner",
                                    untuk=unsur.name, pilihan=unsur.label or "",
                                    periodik=unsur.periodik)
            if unsur.periodik:
                pembungkus.induk = next((u for u in self.unsur if u.panel_periodik), None)
            unsur.induk = pembungkus
            label = UnsurPalsu(self, "label", kelas="x-form-cb-label", teks=unsur.label or "",
                               untuk=unsur.name, pilihan=unsur.label or "",
                               periodik=unsur.periodik)
            posisi = self.unsur.index(unsur) + 1
            self.unsur.insert(posisi, pembungkus)
            self.unsur.insert(posisi + 1, label)

    def _menu_tujuan_diklik(self) -> None:
        """Menu tujuan dibuka: Dapodik menampilkan popup pengumuman versi."""
        if self.popup_detik is not None:
            self.munculkan_popup(self.popup_detik)

    def buka_daftar_peserta_didik(self) -> None:
        """Setelah login (skenario alur_penuh): tampilkan menu, pencarian, dan tabel siswa."""
        if self.sudah_masuk:
            return
        self.sudah_masuk = True
        self.judul = "Dapodik - Peserta Didik"
        for unsur in self.unsur:
            if unsur.jalur.startswith("/html/body/div[5]"):
                unsur.terlihat = False      # formulir login ditinggalkan halaman
        self.unsur.extend([
            UnsurPalsu(self, "button", teks="", jalur="/html/body/div[1]/ul/li[2]/div/a/button"),
            # Popup pengumuman versi Dapodik — sudah ada di DOM, tampil setelah menu dibuka.
            UnsurPalsu(self, "div", kelas="x-window", popup=True,
                       teks="Selamat Datang di Aplikasi Dapodik 2027.b"),
            UnsurPalsu(self, "a", teks="Tutup", popup=True,
                       jalur="/html/body/div[11]/div[2]/div[2]/div/div/a[1]"),
            UnsurPalsu(self, "a", teks="Jangan Tampilkan Log ini", popup=True),
            UnsurPalsu(self, "span", teks="Pendaftaran", id="ext-element-76"),
            UnsurPalsu(self, "span", teks="Peserta Didik", id="ext-element-66"),
            UnsurPalsu(self, "input", type="text", name="cari_text"),
            # Tombol Registrasi pada toolbar — sudah ada sebelum formulirnya dibuka.
            UnsurPalsu(self, "span", kelas="x-btn-inner-soft-green-small", teks="Registrasi"),
            # Panel «Data Periodik Peserta Didik» — punya area gulir SENDIRI (div[4] pada
            # halaman Dapodik), kelabu sampai ada baris siswa dipilih, dan isinya baru
            # terjangkau setelah panelnya digulir (bukan dengan window.scrollBy).
            UnsurPalsu(self, "div", kelas="x-panel x-container",
                       panel_periodik=True,
                       jalur="/html/body/div[2]/div/div/div[2]/div/div/div/div[4]"),
            UnsurPalsu(self, "input", type="text", name="tinggi_badan", label="Tinggi Badan",
                       periodik=True),
            UnsurPalsu(self, "input", type="text", name="berat_badan", label="Berat Badan",
                       periodik=True),
            UnsurPalsu(self, "input", type="text", name="lingkar_kepala",
                       label="Lingkar Kepala", periodik=True),
            # Baris «Jarak rumah ke sekolah» punya DUA pilihan, seperti Dapodik:
            # «kurang dari 1 km» (td/div[1]) dan «lebih dari 1 km» (td/div[2], persis skrip).
            # Keduanya dibungkus `x-form-cb-wrap-inner` — klik pada pembungkusnya mengubah
            # pilihannya, klik lewat skrip pada kotaknya TIDAK.
            UnsurPalsu(self, "input", type="radio", name="jarak_rumah",
                       label="Kurang dari 1 km", periodik=True, kelompok="jarak",
                       jalur="/html/body/div[2]/div/div/div[2]/div/div/div/div[3]/div[2]/div/div/"
                             "div/div[1]/div/div/div[7]/div/div/table/tbody/tr/td/div[1]/div/div/"
                             "span/input"),
            UnsurPalsu(self, "input", type="radio", name="jarak_rumah",
                       label="Lebih dari 1 km", periodik=True, kelompok="jarak",
                       jalur="/html/body/div[2]/div/div/div[2]/div/div/div/div[3]/div[2]/div/div/"
                             "div/div[1]/div/div/div[7]/div/div/table/tbody/tr/td/div[2]/div/div/"
                             "span/input"),
            # Kolom teks di sebelah kotak «Jarak rumah ke sekolah» — persis Dapodik.
            UnsurPalsu(self, "input", type="text", name="jarak_rumah_ke_sekolah_km",
                       label="Sebutkan (dalam kilometer)", periodik=True),
            UnsurPalsu(self, "input", type="text", name="jumlah_saudara_kandung",
                       label="Jumlah Saudara Kandung", periodik=True),
            UnsurPalsu(self, "span", kelas="x-btn-inner-default-small", teks="Simpan dan Tutup",
                       periodik=True, simpan_periodik=True),
        ])
        self._pasang_pembungkus_kotak()
        self.judul = "Dapodik - Peserta Didik"

    def popup_terbuka(self) -> bool:
        """Apakah popup pengumuman sedang tampil (dan belum ditutup)."""
        if not self._popup_muncul or self._popup_tutup:
            return False
        return (self.jam() - self._popup_mulai) >= float(self.popup_detik or 0)

    def munculkan_popup(self, detik: float = 0.0) -> None:
        """Tampilkan popup pengumuman (mis. karena menu tujuan baru saja dibuka)."""
        self._popup_muncul = True
        self._popup_tutup = False
        self._popup_mulai = self.jam()
        self.popup_detik = float(detik)

    def tutup_popup(self) -> None:
        """Tutup popup pengumuman seperti tombol «Tutup» ditekan."""
        self._popup_tutup = True
        self.ditutup_popup += 1
        if self._nisn_tersembunyi:
            # Hasil pencarian yang tertahan popup baru muncul setelah popup ditutup.
            self.nisn_dicari = self._nisn_tersembunyi
            self._nisn_tersembunyi = ""

    def siapkan_popup_setelah_cari(self, nisn: str) -> "PerambanPalsu":
        """Popup pengumuman muncul ketika pencarian ditekan; hasilnya tampil setelah ditutup.

        Meniru Dapodik yang menampilkan pengumuman versi tepat saat daftar peserta didik
        selesai dimuat — hasil pencariannya jadi tidak terlihat sampai popup ditutup.
        """
        self._popup_setelah_cari = True
        self._nisn_tersembunyi = nisn
        self.nisn_dicari = ""
        return self

    def siapkan_periodik_perlu_gulir(self, kali: int = 1) -> "PerambanPalsu":
        """Kolom Data Periodik baru terjangkau setelah panelnya digulir ``kali`` kali.

        Menirukan Dapodik: panel «Data Periodik Peserta Didik» berada di dalam **area gulir
        sendiri**, jadi ``window.scrollBy`` tidak menolong — yang menjangkaunya adalah
        ``scrollIntoView`` pada panel/kolomnya.
        """
        self.periodik_perlu_gulir = int(kali)
        return self

    def periodik_siap(self) -> bool:
        """Apakah area gulir panel Data Periodik sudah dijangkau (bukan gulir halaman)."""
        return len(self.gulir_panel) >= self.periodik_perlu_gulir

    def siapkan_popup(self, detik: float = 0.0) -> "PerambanPalsu":
        """Atur popup pengumuman: muncul ``detik`` setelah menu tujuan dibuka.

        ``detik=0`` (bawaan) = muncul seketika seperti Dapodik; angka lebih besar meniru
        popup yang muncul **belakangan** (persis PC sekolah yang menunggu hanya 5 detik).
        """
        self.popup_detik = float(detik)
        return self

    def pakai_jam(self, jam) -> "PerambanPalsu":
        """Ganti jam halaman (mis. dengan jam palsu pada pengujian agar cepat)."""
        self.jam = jam
        return self

    def buka_formulir_registrasi(self) -> None:
        """Formulir Registrasi terbuka (dipicu tombol Registrasi, seperti Dapodik).

        Seperti Dapodik: tanpa baris siswa yang terpilih, tombol Registrasi tidak
        membuka apa pun.
        """
        if self.tolak_klik_registrasi > 0:
            self.tolak_klik_registrasi -= 1      # klik pertama tertelan lapisan/popup
            return
        if not self.baris_siswa_terpilih():
            return
        if self.registrasi_otomatis and not any(u.name == "nipd" for u in self.unsur):
            self.tambah_formulir_registrasi(self.nisn_dicari)

    def panel_periodik_terbuka(self) -> bool:
        """Panel «Data Periodik» hidup hanya bila ada baris siswa terpilih (seperti Dapodik)."""
        return self.baris_siswa_terpilih() and not self._periodik_tersimpan

    def simpan_data_periodik(self) -> None:
        """Tombol «Simpan dan Tutup» panel Data Periodik ditekan."""
        self._periodik_tersimpan = True
        for unsur in self.unsur:
            if unsur.periodik and unsur.type != "checkbox" and unsur.name:
                self.data_periodik_tersimpan[unsur.name] = unsur.nilai
        self.data_periodik_tersimpan["jarak"] = "1" if self.jarak_dicentang else "0"

    def baris_siswa_terpilih(self) -> bool:
        """Apakah ada baris siswa (x-grid-row) yang sudah terpilih."""
        return any(u.tag_name == "tr" and "x-grid-row" in (u.kelas or "") and u.terpilih
                   for u in self.unsur)

    def tambah_baris_siswa(self, nisn: str) -> None:
        """Tambahkan satu baris tabel Ext JS untuk NISN tertentu (skenario alur_penuh)."""
        self.unsur.append(UnsurPalsu(self, "tr", kelas="x-grid-row", teks=nisn))

    def tambah_formulir_registrasi(self, nisn: str, sekolah_asal: str = "",
                                   nama_kolom: str = "") -> None:
        """Tambahkan unsur formulir Registrasi seperti pada Dapodik (skenario alur_penuh).

        ``sekolah_asal`` mengisi nilai awal kolomnya (kosong = kolom tetap ada, belum diisi).
        ``nama_kolom`` menirukan Dapodik yang menamai kolomnya berbeda-beda
        ('' = hanya berlabel, seperti versi yang tidak memakai atribut ``name``).
        """
        if not any("x-btn-inner-soft-green-small" in (u.kelas or "") for u in self.unsur):
            self.unsur.append(UnsurPalsu(self, "span", kelas="x-btn-inner-soft-green-small",
                                         teks="Registrasi"))
        self.unsur.extend([
            UnsurPalsu(self, "input", type="text", name="nipd"),
            UnsurPalsu(self, "input", type="text", name=nama_kolom, label="Sekolah Asal",
                       nilai=sekolah_asal),
            UnsurPalsu(self, "input", type="text", name="id_hobby"),
            UnsurPalsu(self, "input", type="text", name="id_cita"),
            UnsurPalsu(self, "span", kelas="x-btn-inner-default-small", teks="Simpan dan Tutup"),
        ])
        # Dua pertanyaan «Ya/Tidak» seperti Dapodik: radio «Ya» berkelas Ext JS, satu di
        # antaranya sudah tercentang (persis log sekolah: "pilihan «Ya» dicentang: 0 dari 2").
        for nomor, terpilih_awal in enumerate((True, False), start=1):
            self.unsur.append(UnsurPalsu(self, "input", type="radio", name="jawaban_ya",
                                         label="Ya", kelompok=f"ya{nomor}",
                                         terpilih=terpilih_awal))
            self._pasang_pembungkus_kotak()

    def pilih_lewat_pembungkus(self, nama: str, pilihan: str = "") -> None:
        """Klik pada pembungkus/label Ext JS = memilih kotak centang/radio di dalamnya.

        ``pilihan`` = teks pilihan yang diwakili wadah itu (mis. «Lebih dari 1 km»): hanya
        kotak itulah yang terpilih, seperti di Dapodik (satu wadah = satu radio).
        """
        for unsur in self.unsur:
            if unsur.type not in ("radio", "checkbox"):
                continue
            if nama and unsur.name != nama:
                continue
            if pilihan and (unsur.label or "").strip() != pilihan.strip():
                continue
            unsur._pilih_kotak()
        self.dipilih_lewat_pembungkus += 1

    def _terlihat_otomatis(self, unsur: UnsurPalsu) -> bool:
        """Skenario splash: kolom login baru terlihat setelah tombol pembuka diklik."""
        if unsur.periodik:
            # Panel Data Periodik kelabu sampai baris siswa dipilih (persis screenshot PC).
            return self.panel_periodik_terbuka()
        if unsur.popup:
            # Unsur popup ada di DOM, tetapi baru terlihat saat popupnya benar-benar tampil.
            return self.popup_terbuka()
        if self.skenario == "splash" and unsur.type in ("text", "password"):
            return self.buka_formulir
        if self.skenario == "masuk" and unsur.type in ("text", "password", "email"):
            return not self.sudah_masuk      # setelah login berhasil formulir hilang
        if self.skenario == "alur_penuh" and (unsur.jalur.startswith("/html/body/div[5]") or
                                              unsur.jalur.startswith("/html/body/div[1]") or
                                              unsur.jalur.startswith("/html/body/div[11]")):
            # formulir login hanya sebelum masuk; menu & popup hanya sesudah masuk
            if unsur.jalur.startswith("/html/body/div[5]"):
                return not self.sudah_masuk
            return self.sudah_masuk
        if self.skenario == "alur_penuh" and unsur.tag_name == "tr":
            return self.sudah_masuk and unsur.teks == self.nisn_dicari
        return unsur.terlihat

    # ------------------------------------------------------------ pencarian - #
    def _cocokkan(self, unsur: UnsurPalsu, nilai: str, xpath: bool = False) -> bool:
        # Selector CSS boleh berisi beberapa pilihan dipisah koma; XPath tidak boleh dipecah
        # (komanya termasuk di dalam contains(...)).
        bagian_daftar = [nilai] if xpath else [b.strip() for b in nilai.split(",") if b.strip()]
        for bagian in bagian_daftar:
            if self._cocok_satu(unsur, bagian):
                return True
        return False

    @staticmethod
    def _cocok_satu(unsur: UnsurPalsu, bagian: str) -> bool:
        if bagian.startswith("xpath:"):
            bagian = bagian[6:]
        # Segala sesuatu mulai dari poros (preceding/following) BUKAN saringan unsur ini —
        # poros itu dipakai untuk melacak kotak lain (lihat poros_input), jadi dipotong dulu.
        potong = re.search(r"/(?:preceding|following)::", bagian)
        if potong:
            bagian = bagian[:potong.start()]
        if bagian.startswith("//"):
            # XPath sederhana: seluruh saringan yang dikenali harus cocok, dan pola yang
            # sama sekali tidak dikenali tidak dianggap cocok (supaya uji tidak lolos palsu).
            dikenali = False
            # (a) saringan atribut: @id="…", @type="…", @aria-selected="true", …
            for nama, nilai_atr in re.findall(r'@([\w:-]+)\s*=\s*[\'"]([^\'"]*)[\'"]', bagian):
                if nama == "class":
                    continue                      # class lewat contains(@class, …) di bawah
                dikenali = True
                if nama == "id":
                    if unsur.id != nilai_atr:
                        return False
                elif nama == "type":
                    if unsur.type != nilai_atr:
                        return False
                elif str(unsur.get_attribute(nama) or "") != nilai_atr:
                    return False
            # (b) contains(@class, "…") — semua yang diminta harus ada
            for kelas_dicari in re.findall(
                    r'contains\(\s*@class\s*,\s*[\'"]([^\'"]+)[\'"]\s*\)', bagian):
                dikenali = True
                if kelas_dicari.lower() not in (unsur.kelas or "").lower():
                    return False
            # (c) tag majemuk: [self::a or self::span or self::button]
            tag_majemuk = re.findall(r'self::(\w+)', bagian)
            if tag_majemuk:
                dikenali = True
                if unsur.tag_name not in tag_majemuk:
                    return False
            # (d) teks. Polanya dibaca persis seperti XPath 1.0 — penting supaya uji ini
            #     menangkap selector yang keliru (dulu pola translate/`normalize-space(.)`
            #     salah dibaca sehingga label «Lebih dari 1 km» dan «Kurang dari 1 km»
            #     sama-sama dianggap cocok).
            teks_unsur = " ".join([unsur.teks or "", unsur.nilai or ""]).strip().lower()
            # contains(translate(normalize-space([.]), "X", "y"), "cari")
            for asal, ganti, cari in re.findall(
                    r"contains\(\s*translate\(\s*normalize-space\(\s*\.?\s*\)\s*,\s*"
                    r"['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)\s*,\s*"
                    r"['\"]([^'\"]+)['\"]\s*\)", bagian):
                dikenali = True
                teks_terjemah = teks_unsur
                for asal_abjad, ganti_abjad in zip(asal, ganti):
                    teks_terjemah = teks_terjemah.replace(asal_abjad.lower(),
                                                          ganti_abjad.lower())
                if cari.lower() not in teks_terjemah:
                    return False
            # contains(normalize-space([.]), "…") / contains(text(), "…") / contains(., "…")
            for cari in re.findall(
                    r"contains\(\s*(?:normalize-space\(\s*\.?\s*\)|text\(\)|\.)\s*,"
                    r"\s*['\"]([^'\"]+)['\"]\s*\)", bagian):
                dikenali = True
                if cari.lower() not in teks_unsur:
                    return False
            # normalize-space([.]) = "…"
            for nilai_teks in re.findall(
                    r"normalize-space\(\s*\.?\s*\)\s*=\s*['\"]([^'\"]+)['\"]", bagian):
                dikenali = True
                if teks_unsur != nilai_teks.strip().lower():
                    return False
            return dikenali
        if bagian.startswith("/html/") or bagian.startswith("/body"):
            return bool(unsur.jalur) and (unsur.jalur == bagian or unsur.jalur.startswith(bagian))
        sisa = bagian
        tag = ""
        for awal in ("input", "button", "select", "textarea", "a", "form", "*"):
            if sisa.startswith(awal):
                tag = awal
                sisa = sisa[len(awal):]
                break
        if tag and tag != "*" and unsur.tag_name != tag:
            return False
        while sisa:
            if sisa.startswith("#"):
                nama_id = sisa[1:].split("[")[0].split(".")[0]
                if unsur.id != nama_id:
                    return False
                sisa = sisa[1 + len(nama_id):]
                continue
            if sisa.startswith("."):
                kelas = sisa[1:].split("[")[0].split(".")[0]
                if kelas not in (unsur.kelas or "").split():
                    return False
                sisa = sisa[1 + len(kelas):]
                continue
            if sisa.startswith("["):
                akhir = sisa.index("]")
                isi = sisa[1:akhir]
                sisa = sisa[akhir + 1:]
                if "*=" in isi:
                    nama, nilai_atribut = isi.split("*=", 1)
                    nilai_atribut = nilai_atribut.strip().strip('"\'')
                    if nilai_atribut.lower() not in str(unsur.get_attribute(nama.strip()) or "").lower():
                        return False
                elif "=" in isi:
                    nama, nilai_atribut = isi.split("=", 1)
                    nilai_atribut = nilai_atribut.strip().strip('"\'')
                    if str(unsur.get_attribute(nama.strip()) or "") != nilai_atribut:
                        return False
                else:
                    if not unsur.get_attribute(isi.strip()):
                        return False
                continue
            if sisa in (" ", ">"):
                sisa = sisa[1:]
                continue
            return False
        return True

    def _terjangkau(self, unsur: UnsurPalsu) -> bool:
        """Kolom Data Periodik baru terjangkau setelah halaman digulir cukup jauh."""
        return self.periodik_siap() or not unsur.periodik

    def find_elements(self, by: str, nilai: str) -> list[UnsurPalsu]:
        """Cari unsur; kolom Data Periodik baru ketemu setelah halaman digulir cukup jauh.

        Pola XPath yang berujung ``/preceding::input[…]`` atau ``/following::input[…]``
        (ada pada selector bawaan Dapodik) diselesaikan seperti XPath sungguhan: yang
        dikembalikan bukan unsur teksnya, melainkan kotak input terdekat sebelum/sesudahnya.
        """
        if by == "name":
            hasil = [u for u in self.unsur if u.name == nilai]
        else:
            hasil = []
            poros = self._bagian_poros(nilai)
            for unsur in self.unsur:
                if not self._cocokkan(unsur, nilai, xpath=(by == "xpath")):
                    continue
                tujuan = unsur
                if poros:
                    lanjut = self.poros_input(unsur, poros)
                    if not lanjut:
                        continue
                    tujuan = lanjut[0]
                if tujuan not in hasil:
                    hasil.append(tujuan)
        return [u for u in hasil if self._terjangkau(u)]

    @staticmethod
    def _bagian_poros(pola: str) -> str:
        """Ambil bagian poros input pada pola XPath, mis. ``preceding::input[@type="radio"]``."""
        cocok = re.search(r"((?:preceding|following)::input"
                          r"(?:\[\s*@type\s*=\s*['\"]\w+['\"]\s*\])?)", pola or "")
        return cocok.group(1) if cocok else ""

    def poros_input(self, unsur: UnsurPalsu, ekspresi: str) -> list[UnsurPalsu]:
        """Kotak input terdekat sebelum/sesudah ``unsur`` (poros XPath ``preceding``/``following``)."""
        bagian = ekspresi if ekspresi.startswith(("preceding", "following")) \
            else self._bagian_poros(ekspresi)
        if not bagian:
            return []
        arah = "preceding" if bagian.startswith("preceding") else "following"
        tipe = re.search(r"@type\s*=\s*['\"](\w+)['\"]", bagian)
        try:
            posisi = self.unsur.index(unsur)
        except ValueError:
            return []
        rentang = self.unsur[:posisi][::-1] if arah == "preceding" else self.unsur[posisi + 1:]
        for kandidat in rentang:
            if kandidat.tag_name != "input":
                continue
            if tipe and kandidat.type != tipe.group(1):
                continue
            return [kandidat]           # [1] = yang terdekat saja
        return []

    def find_element(self, by: str, nilai: str) -> UnsurPalsu:
        hasil = self.find_elements(by, nilai)
        if not hasil:
            raise NoSuchElementException(f"tidak ada unsur {nilai}")
        return hasil[0]

    # ------------------------------------------------------------ skrip ----- #
    def execute_script(self, skrip: str, *argumen: Any) -> Any:
        self.skrip.append(skrip)
        if "querySelectorAll('label')" in skrip:
            # Bot mencari kolom isian lewat teks labelnya (mis. «Sekolah Asal»).
            teks = str(argumen[0] if argumen else "").strip().lower()
            for unsur in self.unsur:
                if unsur.label and unsur.label.strip().lower().startswith(teks) \
                        and self._terjangkau(unsur):
                    return unsur
            return None
        if "mousedown" in skrip and "dispatchEvent" in skrip:
            # Bot mengirim urutan tetikus lengkap (mousedown → mouseup → click):
            # inilah yang benar-benar memilih baris tabel Ext JS.
            if argumen:
                argumen[0]._pilih_baris()
            return None
        if ".remove()" in skrip or "removeChild" in skrip:
            # Jalan keluar terakhir bot: membuang jendela popup dari halaman.
            self.tutup_popup()
            return None
        if "x-mask" in skrip and "querySelectorAll" in skrip:
            if self.mask_keras or self.popup_terbuka():
                return 1      # popup modal Ext JS juga memakai lapisan penutup
            if self.mask_sisa > 0:
                self.mask_sisa -= 1
                return 1
            return 0
        if "document.readyState" in skrip and "return" in skrip and "kolom" not in skrip:
            return "complete"
        if "input[type=password]" in skrip:
            # _formulir_terlihat: penanda formulir login = kolom sandi yang terlihat.
            return any(self._terlihat_otomatis(u) and u.tag_name == "input" and u.type == "password"
                       for u in self.unsur)
        if "p.style.display = 'block'" in skrip or "p.style.display" in skrip:
            # _paksa_terlihat: unsur jadi terlihat (dipakai bila kolom tersembunyi).
            if argumen:
                argumen[0].terlihat = True
            return None
        if "el.value = nilai" in skrip:
            if argumen:
                if argumen[0].periodik and (not self.panel_periodik_terbuka()
                                            or not self.periodik_siap()):
                    self.ketikan_diabaikan += 1      # panel kelabu: isian tidak tersimpan
                    return None
                argumen[0].nilai = str(argumen[1])
                argumen[0].diketik.append(str(argumen[1]))
            return None
        if "dispatchEvent" in skrip and argumen and "new Event" in skrip and \
                getattr(argumen[0], "periodik", False) and \
                ("'input'" in skrip or '"input"' in skrip):
            # Peristiwa input/change/blur dari bot sesudah mengetik (cara skrip sekolah).
            self.peristiwa_dipicu += 1
            return None
        if "dispatchEvent" in skrip and argumen:
            sasaran = argumen[0]
            if getattr(sasaran, "untuk", ""):
                # Urutan mousedown → mouseup → click pada pembungkus/label Ext JS.
                self.pilih_lewat_pembungkus(sasaran.untuk, sasaran.pilihan)
            elif getattr(sasaran, "periodik", False) and \
                    getattr(sasaran, "type", "") in ("radio", "checkbox"):
                self.diklik_skrip_diabaikan += 1
            return None
        if "scrollIntoView" in skrip and argumen:
            sasaran = argumen[0]
            if getattr(sasaran, "periodik", False) or getattr(sasaran, "panel_periodik", False):
                # Inilah yang benar-benar menjangkau area gulir panel Data Periodik.
                self.gulir_panel.append(getattr(sasaran, "name", "")
                                        or getattr(sasaran, "teks", "") or "panel")
            return None
        if "window.scrollBy" in skrip:
            # Persis skrip sekolah: driver.execute_script("window.scrollBy(0, 250);")
            jarak = argumen[0] if argumen else None
            if jarak is None:
                import re as _re
                cocok = _re.search(r"scrollBy\(\s*0\s*,\s*(-?\d+)", skrip)
                jarak = cocok.group(1) if cocok else 0
            self.gulir.append(int(jarak))
            return None
        if "arguments[0].click()" in skrip:
            if argumen:
                sasaran = argumen[0]
                if "x-form-cb-label" in (getattr(sasaran, "kelas", "") or ""):
                    # Klik SKRIP pada label Ext JS — inilah yang dipakai skrip sekolah bila
                    # klik sungguhannya tertelan. Kotak radio-nya sendiri tetap menolak.
                    self.pilih_lewat_pembungkus(sasaran.untuk, sasaran.pilihan)
                    return None
                sasaran._klik_paksa(script=True)
            return None
        if "return {" in skrip and "readyState:" in skrip.replace(" ", "") or "readyState" in skrip:
            return {"readyState": "complete", "overlay": 0, "iframe": 0,
                    "judul_dokumen": self.judul, "teks_awal": "Masuk"}
        return None

    # ------------------------------------------------------------ lain-lain - #
    @property
    def title(self) -> str:
        return self.judul

    @property
    def page_source(self) -> str:
        return "<html><body>" + "".join(
            f"<{u.tag_name} type='{u.type}' name='{u.name}'>{u.teks}" for u in self.unsur) + "</body></html>"

    @property
    def current_url(self) -> str:
        return self.url

    def get(self, url: str) -> None:
        self.url = url

    def save_screenshot(self, jalur: str) -> bool:
        self.disimpan.append(jalur)
        with open(jalur, "wb") as berkas:
            berkas.write(b"\x89PNG\r\n\x1a\n")  # penanda berkas gambar
        return True

    def quit(self) -> None:
        self.ditutup = True

    # ------------------------------------------------------------ bantuan --- #
    def sibukkan(self) -> "PerambanPalsu":
        """Nyalakan lapisan pemuatan yang tidak pernah hilang (untuk menguji ketangguhan)."""
        self.mask_keras = True
        return self

    def unsur_bernama(self, nama: str) -> UnsurPalsu | None:
        for unsur in self.unsur:
            if unsur.name == nama:
                return unsur
        return None

    def tombol_diklik(self) -> list[str]:
        return [u.teks or u.id for u in self.unsur if u.diklik]


SKENARIO = ("splash", "kolom_tersembunyi", "siap", "mask", "masuk", "alur_penuh",
            "xpath_bawaan", "kosong")


def buat(skenario: str = "splash") -> PerambanPalsu:
    return PerambanPalsu(skenario)
