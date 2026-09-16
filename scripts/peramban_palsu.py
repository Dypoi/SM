"""Peramban palsu untuk menguji bot Dapodik tanpa Chrome.

Lingkungan uji (sandbox/CI) tidak punya Google Chrome, padahal perilaku bot perlu
diuji: menunggu formulir login tampil, menembus halaman pembuka (splash), mengisi
kolom yang belum terlihat, dan mengenali selector sendiri.

Kelas di sini meniru bagian API Selenium WebDriver yang dipakai ``app/bot_dapodik``
secukupnya (``find_element``, ``find_elements``, ``execute_script``, ``is_displayed``,
``click``, ``send_keys``) sehingga skenario seperti yang dialami di PC sekolah dapat
direproduksi. **Hanya untuk pengujian** — aplikasi tidak memakainya.
"""

from __future__ import annotations

from typing import Any

from selenium.common.exceptions import (ElementNotInteractableException,
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
        self.diklik += 1
        self._buka_formulir_bila_pembuka()

    def click(self) -> None:
        if not self.is_displayed():
            raise ElementNotInteractableException("unsur tidak terlihat")
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
        elif self.skenario == "xpath_bawaan":
            # Halaman yang cocok dengan skrip bot asli (selector bawaan semuanya tepat).
            self.unsur.append(UnsurPalsu(self, "input", type="text", name="username",
                                         kelas="x-form-text"))
            self.unsur.append(UnsurPalsu(self, "input", type="password", name="password"))
            self.unsur.append(UnsurPalsu(self, "button", teks="Masuk", id="form2"))

    def _terlihat_otomatis(self, unsur: UnsurPalsu) -> bool:
        """Skenario splash: kolom login baru terlihat setelah tombol pembuka diklik."""
        if self.skenario == "splash" and unsur.type in ("text", "password"):
            return self.buka_formulir
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
            if '@id="form2"' in bagian:
                return unsur.id == "form2"
            if "contains(normalize-space()" in bagian or "contains(., '" in bagian:
                # cuplikan teks yang dicari, mis. contains(normalize-space(), 'Masuk')
                for penanda in ("normalize-space(), ", "., "):
                    if penanda in bagian:
                        potongan = bagian.split(penanda, 1)[1]
                        potongan = potongan.split(")")[0].strip().strip("'\"")
                        return potongan.lower() in (unsur.teks or "").lower()
            return False
        if bagian.startswith("/html/") or bagian.startswith("/body"):
            return False
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
        if "document.readyState" in skrip and "return" in skrip and "kolom" not in skrip:
            return "complete"
        if "input[type=password], input[type=email], input[type=text]" in skrip:
            return any(self._terlihat_otomatis(u) and u.tag_name == "input"
                       and u.type in ("password", "email", "text") for u in self.unsur)
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
    def unsur_bernama(self, nama: str) -> UnsurPalsu | None:
        for unsur in self.unsur:
            if unsur.name == nama:
                return unsur
        return None

    def tombol_diklik(self) -> list[str]:
        return [u.teks or u.id for u in self.unsur if u.diklik]


SKENARIO = ("splash", "kolom_tersembunyi", "siap", "xpath_bawaan", "kosong")


def buat(skenario: str = "splash") -> PerambanPalsu:
    return PerambanPalsu(skenario)
