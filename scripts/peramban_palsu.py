"""Peramban palsu untuk menguji bot Dapodik tanpa Chrome.

Lingkungan uji (sandbox/CI) tidak punya Google Chrome, padahal perilaku bot perlu
diuji: menunggu formulir login tampil, menembus halaman pembuka (splash), mengisi
kolom yang belum terlihat, dan mengenali selector sendiri.

Skenario yang tersedia: ``splash`` (halaman pembuka), ``kolom_tersembunyi`` (persis
laporan PC sekolah), ``siap``, ``mask`` (masih tertutup lapisan loading Ext JS),
``masuk`` (login berhasil setelah tombol ditekan), ``alur_penuh`` (halaman login,
menu, tabel, dan formulir Registrasi persis skrip sekolah), ``xpath_bawaan``, ``kosong``.
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
        #: XPath absolut skrip sekolah, mis. /html/body/div[5]/div[2]/form/input
        self.jalur = sifat.get("jalur", "")

    # ------------------------------------------------------------ atribut --- #
    def get_attribute(self, nama: str) -> str | None:
        peta = {"type": self.type, "name": self.name, "id": self.id,
                "placeholder": self.placeholder, "aria-label": self.aria,
                "value": self.nilai, "class": self.kelas}
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

    # ------------------------------------------------------------ aksi ------ #
    def _buka_formulir_bila_pembuka(self) -> None:
        if self.teks.strip().lower() == "masuk" and not self.name and not self.id:
            # Tombol pembuka halaman depan: formulir login baru terlihat sesudah ini.
            self.peramban.buka_formulir = True

    def _klik_paksa(self) -> None:
        """Klik seperti lewat skrip: tetap bekerja walau unsur tidak terlihat."""
        if self.peramban.popup_terbuka() and not self.popup:
            # Selagi popup pengumuman tampil, aplikasi mengabaikan klik di luarnya —
            # inilah yang membuat formulir Registrasi tidak pernah terbuka di PC sekolah.
            self.peramban.klik_terblokir += 1
            return
        self.diklik += 1
        if self.popup and (self.teks.strip().lower() == "tutup" or
                           "x-tool-close" in (self.kelas or "")):
            self.peramban.tutup_popup()
            return
        if self.name == "tombol_registrasi" or \
                "x-btn-inner-soft-green-small" in (self.kelas or ""):
            self.peramban.buka_formulir_registrasi()
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
        self._klik_paksa()

    def send_keys(self, *tombol: Any) -> None:
        """Meniru pengetikan: tombol pengubah (Ctrl+A) ditangani, bukan diketik apa adanya."""
        if not self.is_displayed():
            raise ElementNotInteractableException("unsur tidak terlihat")
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
        return []

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
        ])
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
        """Formulir Registrasi terbuka (dipicu tombol Registrasi, seperti Dapodik)."""
        if self.tolak_klik_registrasi > 0:
            self.tolak_klik_registrasi -= 1      # klik pertama tertelan lapisan/popup
            return
        if self.registrasi_otomatis and not any(u.name == "nipd" for u in self.unsur):
            self.tambah_formulir_registrasi(self.nisn_dicari)

    def tambah_baris_siswa(self, nisn: str) -> None:
        """Tambahkan satu baris tabel Ext JS untuk NISN tertentu (skenario alur_penuh)."""
        self.unsur.append(UnsurPalsu(self, "tr", kelas="x-grid-row", teks=nisn))

    def tambah_formulir_registrasi(self, nisn: str) -> None:
        """Tambahkan unsur formulir Registrasi seperti pada Dapodik (skenario alur_penuh)."""
        if not any("x-btn-inner-soft-green-small" in (u.kelas or "") for u in self.unsur):
            self.unsur.append(UnsurPalsu(self, "span", kelas="x-btn-inner-soft-green-small",
                                         teks="Registrasi"))
        self.unsur.extend([
            UnsurPalsu(self, "input", type="text", name="nipd"),
            UnsurPalsu(self, "input", type="text", name="id_hobby"),
            UnsurPalsu(self, "input", type="text", name="id_cita"),
            UnsurPalsu(self, "span", kelas="x-btn-inner-default-small", teks="Simpan dan Tutup"),
        ])

    def _terlihat_otomatis(self, unsur: UnsurPalsu) -> bool:
        """Skenario splash: kolom login baru terlihat setelah tombol pembuka diklik."""
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
        if bagian.startswith("//"):
            # Saringan berdasarkan @id (mis. //*[@id="ext-element-76"])
            id_dicari = re.findall(r'@id\s*=\s*"([^"]+)"', bagian) + \
                        re.findall(r"@id\s*=\s*'([^']+)'", bagian)
            if id_dicari:
                return all(unsur.id == satu for satu in id_dicari)
            teks_unsur = " ".join([unsur.teks or "", unsur.nilai or ""]).lower()
            for penanda in ("normalize-space(), ", "., "):
                if penanda in bagian:
                    # ambil teks di dalam tanda kutip pertama setelah penanda,
                    # mis. contains(normalize-space(), "Simpan dan Tutup")
                    sisa = bagian.split(penanda, 1)[1]
                    cocok = re.search(r"['\"]([^'\"]+)['\"]", sisa)
                    if not cocok:
                        return False
                    return cocok.group(1).lower() in teks_unsur
            if "contains(@class" in bagian:
                kelas = bagian.split("contains(@class", 1)[1]
                kelas = kelas.split(",")[1].split(")")[0].strip().strip("'\"")
                return kelas.lower() in (unsur.kelas or "").lower()
            return False
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

    def find_elements(self, by: str, nilai: str) -> list[UnsurPalsu]:
        if by == "name":
            return [u for u in self.unsur if u.name == nilai]
        if by == "xpath":
            return [u for u in self.unsur if self._cocokkan(u, nilai, xpath=True)]
        return [u for u in self.unsur if self._cocokkan(u, nilai)]

    def find_element(self, by: str, nilai: str) -> UnsurPalsu:
        hasil = self.find_elements(by, nilai)
        if not hasil:
            raise NoSuchElementException(f"tidak ada unsur {nilai}")
        return hasil[0]

    # ------------------------------------------------------------ skrip ----- #
    def execute_script(self, skrip: str, *argumen: Any) -> Any:
        self.skrip.append(skrip)
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
                argumen[0].nilai = str(argumen[1])
                argumen[0].diketik.append(str(argumen[1]))
            return None
        if "arguments[0].scrollIntoView" in skrip:
            return None
        if "arguments[0].click()" in skrip:
            if argumen:
                argumen[0]._klik_paksa()
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
