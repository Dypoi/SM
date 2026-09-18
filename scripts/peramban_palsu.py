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


#: Pilihan dropdown «Pendidikan» pada Dapodik — dibuat seperti yang terlihat pada tangkapan
#: layar sekolah (D1…D4, Informal, Lainnya, Non formal, Paket A…). Daftar ini **tidak sama**
#: dengan daftar di aplikasi SM («SMA / sederajat»), persis seperti Dapodik sekolah — jadi
#: bot harus benar-benar mencocokkan pilihannya, bukan sekadar mengetikkan teksnya.
PILIHAN_PENDIDIKAN_PALSU: tuple[str, ...] = (
    "D1", "D2", "D3", "D4", "Informal", "Lainnya", "Non formal", "Paket A", "Paket B",
    "Paket C", "Paud", "Putus SD", "S1", "S2", "S3", "SD", "SLB", "SLTA", "SLTP", "SMK",
    "SMP", "SMA", "Tidak sekolah",
)


def pilihan_dropdown_dapodik(kunci: str) -> tuple[str, ...]:
    """Daftar pilihan sebuah dropdown BIO: ``pendidikan``/``pekerjaan``/``penghasilan``.

    Pekerjaan & penghasilan memakai daftar Dapodik yang sama dengan aplikasi SM
    (``app.dapodik``), pendidikan memakai daftar pada tangkapan layar sekolah.
    """
    if kunci == "pendidikan":
        return PILIHAN_PENDIDIKAN_PALSU
    from app import dapodik

    return {"pekerjaan": dapodik.PEKERJAAN_OPTIONS,
            "penghasilan": dapodik.PENGHASILAN_OPTIONS}.get(kunci, ())


#: Kolom jendela «Ubah» (BIO) — nama kolomnya diambil apa adanya dari skrip sekolah.
#: Elemen ketiga = jenis dropdown ("" = kolom teks biasa). Nama kolomnya diambil dari DOM
#: asli halaman Dapodik yang dikirim sekolah (mis. ``pekerjaan_id_ayah``).
BIO_KOLOM_PALSU: tuple[tuple[str, str, str], ...] = (
    ("no_kk", "No. Kartu Keluarga", ""),
    ("reg_akta_lahir", "No. Registrasi Akta Lahir", ""),
    ("alamat_jalan", "Alamat (Jalan)", ""),
    ("rt", "RT", ""),
    ("rw", "RW", ""),
    ("kode_pos", "Kode Pos", ""),
    ("anak_keberapa", "Anak ke-berapa", ""),
    ("nama_ayah", "Nama ayah", ""),
    ("nik_ayah", "NIK ayah", ""),
    ("tahun_lahir_ayah", "Tahun lahir ayah", ""),
    ("jenjang_pendidikan_ayah", "Pendidikan ayah", "pendidikan"),
    ("pekerjaan_id_ayah", "Pekerjaan ayah", "pekerjaan"),
    ("penghasilan_id_ayah", "Penghasilan ayah", "penghasilan"),
    ("nik_ibu", "NIK ibu", ""),
    ("tahun_lahir_ibu", "Tahun lahir ibu", ""),
    ("jenjang_pendidikan_ibu", "Pendidikan ibu", "pendidikan"),
    ("pekerjaan_id_ibu", "Pekerjaan ibu", "pekerjaan"),
    ("penghasilan_id_ibu", "Penghasilan ibu", "penghasilan"),
)


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
        #: Id komponen Ext JS (``data-componentid`` pada DOM sekolah, mis. radiofield-1112)
        self.componentid = str(sifat.get("componentid", ""))
        #: Unsur induk (untuk XPath leluhur sederhana, mis. mencari pembungkus)
        self.induk: "UnsurPalsu | None" = None
        #: True = tombol «Simpan dan Tutup» milik panel Data Periodik
        self.simpan_periodik = bool(sifat.get("simpan_periodik", False))
        #: Nama kelompok pilihan (mis. "jarak") — mengklik satu anggota melepas yang lain
        self.kelompok = str(sifat.get("kelompok", ""))
        #: XPath absolut skrip sekolah, mis. /html/body/div[5]/div[2]/form/input
        self.jalur = sifat.get("jalur", "")
        #: True = unsur milik jendela «Ubah» (BIO) — hanya hidup saat jendelanya terbuka
        self.bio = bool(sifat.get("bio", False))
        #: True = wadah/jendela «Ubah» (punya area gulir sendiri)
        self.bio_panel = bool(sifat.get("bio_panel", False))
        #: True = tombol «Simpan» jendela «Ubah»
        self.simpan_bio = bool(sifat.get("simpan_bio", False))
        #: Aksi tombol pada halaman sekolah: "ubah" (membuka jendela BIO) / "simpan"
        self.aksi = str(sifat.get("aksi", ""))
        #: True = tombol PALSU (mis. «Ubah»/«Simpan» milik panel «Data Rincian PD» yang
        #: tidak berhubungan dengan jendela «Edit Peserta Didik»)
        self.palsu = bool(sifat.get("palsu", False))
        #: True = tombol palsu itu berada di dalam panel «Data Rincian PD»
        self.rincian = bool(sifat.get("rincian", False))
        #: Pilihan dropdown (combo Ext JS) — kosong berarti kolom teks biasa. Bila terisi,
        #: kolom hanya menyimpan nilai yang persis ada di daftar ini (persis Ext JS/Dapodik).
        self.daftar_pilihan: tuple[str, ...] = tuple(sifat.get("daftar_pilihan", ()))
        #: Nilai MODEL Ext JS (yang benar-benar dikirim saat «Simpan») — beda dari tulisan
        #: di layar bila yang diketik bukan salah satu pilihan daftarnya.
        self.nilai_model = str(sifat.get("nilai_model", ""))
        #: Id pilihan yang tersimpan (di Dapodik: ``getValue()`` combo berisi id, bukan teks).
        self.nilai_id = sifat.get("nilai_id", "")
        #: True = tombol panah dropdown (membuka daftar pilihannya)
        self.trigger_combo = bool(sifat.get("trigger_combo", False))
        #: True = satu pilihan di daftar dropdown yang sedang terbuka
        self.item_dropdown = bool(sifat.get("item_dropdown", False))

    # ------------------------------------------------------------ atribut --- #
    def get_attribute(self, nama: str) -> str | None:
        peta = {"type": self.type, "name": self.name, "id": self.id,
                "placeholder": self.placeholder, "aria-label": self.aria,
                "value": self.nilai, "class": self.kelas, "label": self.label,
                "data-componentid": self.componentid}
        if nama == "checked":
            # Pada mode keadaan_lewat_kelas atribut `checked` memang tidak ada di DOM —
            # persis DOM Dapodik: keadaannya hanya ditandai kelas x-form-cb-checked.
            if self.peramban.keadaan_lewat_kelas and self.type in ("radio", "checkbox"):
                return None
            return "checked" if self.terpilih else None
        if nama == "disabled":
            return None if self.enabled else "true"
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
        """Terpilih — dipakai untuk baris tabel & kotak centang.

        Pada mode ``keadaan_lewat_kelas`` (menirukan DOM Dapodik) keadaan tercentang TIDAK
        terbaca dari sini: yang menandainya kelas ``x-form-cb-checked`` pada pembungkusnya,
        sehingga bot harus memeriksanya lewat skrip.
        """
        if self.peramban.keadaan_lewat_kelas and self.type in ("radio", "checkbox"):
            self.peramban.is_selected_diminta += 1
            return False
        return bool(self.terpilih)

    # ------------------------------------------------------------ aksi ------ #
    def _buka_formulir_bila_pembuka(self) -> None:
        if self.teks.strip().lower() == "masuk" and not self.name and not self.id:
            # Tombol pembuka halaman depan: formulir login baru terlihat sesudah ini.
            self.peramban.buka_formulir = True

    def _klik_paksa(self, script: bool = False) -> None:
        if getattr(self, "trigger_combo", False):
            # Tombol panah dropdown Ext JS: membuka daftar pilihannya.
            self.peramban.buka_dropdown(self.induk)
            return
        if getattr(self, "item_dropdown", False):
            # Memilih satu pilihan di daftar: inilah yang mengisi NILAI MODEL Ext JS.
            self.peramban.pilih_item_dropdown(self, lewat_skrip=script)
            return
        if self.peramban.hanya_ext_yang_menerima and \
                (self.untuk or self.type in ("radio", "checkbox")):
            # Keadaan paling keras: Dapodik mengabaikan SEMUA klik pada pilihan itu —
            # baik pada kotaknya, pembungkusnya, maupun labelnya. Yang menerima hanya
            # Ext.getCmp(...).setValue(true) (lewat data-componentid).
            self.peramban.klik_diabaikan += 1
            return
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
                and (script or self.peramban.hanya_ext_yang_menerima
                     or (self.peramban.hanya_label_yang_menerima and self.periodik)):
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
        if self.aksi == "ubah":
            self.peramban.bio_ubah_dicoba += 1
            if self.palsu:
                # «Ubah» milik panel «Data Rincian PD» (bukan jendela «Edit Peserta Didik»):
                # ditekan pun tidak membuka apa-apa.
                self.peramban.bio_ubah_palsu_diklik += 1
                return
            self.peramban.buka_jendela_bio()
        if self.aksi == "simpan":
            if self.palsu:
                # «Simpan» milik panel «Data Rincian PD»: tidak menyimpan BIO apa pun.
                self.peramban.bio_simpan_palsu_diklik += 1
                return
            self.peramban.simpan_bio()
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
        if not self.enabled:
            # Selenium menolak mengklik/mengetik unsur yang nonaktif — persis kolom km
            # Dapodik sebelum pilihan «lebih dari 1 km» terpasang.
            raise ElementNotInteractableException("unsur nonaktif (disabled)")
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

    def _pilih_kotak(self, dari_ext: bool = False) -> None:
        """Kotak centang/radio terpilih (klik sungguhan / urutan tetikus asli / Ext JS).

        ``dari_ext=True`` = dipilih lewat ``Ext.getCmp(...).setValue(...)`` so model Ext JS-nya
        ikut berubah (penanda ``x-form-cb-checked`` berpindah). Klik biasa bisa jadi hanya
        mengubah DOM tanpa memindahkan penanda — persis keluhan di PC sekolah.
        """
        if self.terpilih and "x-form-cb-checked" in ((self.induk.kelas if self.induk else "")):
            return
        self.terpilih = True
        jarak = self.name.startswith("jarak") or (self.kelompok or "").startswith("jarak")
        if jarak:
            # Hindari hitungan ganda ketika pilihan yang sama disentuh lagi lewat Ext.getCmp.
            self.peramban.jarak_dicentang += 1
            self.peramban.jarak_pilihan = (self.label or self.jalur).strip()
        if self.peramban.kelas_tidak_ikut_pindah and not dari_ext:
            # Model Ext JS tidak ikut: penanda tetap di pilihan lama dan kolom km tetap
            # nonaktif — inilah keadaan yang membuat bot harus naik ke Ext.getCmp.
            self.peramban.perbarui_kolom_km()
            return
        if self.kelompok:              # model Ext JS ikut: penandanya pindah
            for lain in self.peramban.unsur:
                if lain is not self and lain.kelompok == self.kelompok:
                    lain.terpilih = False
                    if lain.induk is not None:
                        lain.induk.kelas = lain.induk.kelas.replace(
                            "x-form-cb-checked", "").strip()
        if self.induk is not None and "x-form-cb-checked" not in (self.induk.kelas or ""):
            self.induk.kelas = (self.induk.kelas + " x-form-cb-checked").strip()
        self.peramban.perbarui_kolom_km()

    def _pilih_baris(self) -> None:
        """Klik sungguhan pada baris tabel / kotak centang = memilihnya (seperti Ext JS)."""
        if self.type in ("radio", "checkbox") and (self.periodik or self.induk is not None):
            if self.peramban.hanya_ext_yang_menerima or self.peramban.klik_kotak_ditelan or \
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
        if not self.enabled:
            raise ElementNotInteractableException("unsur nonaktif (disabled)")
        if self.periodik and (not self.peramban.panel_periodik_terbuka()
                              or not self.peramban.periodik_siap()):
            # Panel masih kelabu, atau kolomnya belum terjangkau karena area gulir panel
            # belum digeser: Dapodik mengabaikan ketikan ini — nilainya tidak tersimpan.
            self.peramban.ketikan_diabaikan += 1
            return
        if self.bio and not (self.peramban.bio_terbuka and self.peramban.bio_siap()):
            # Jendela «Ubah» tertutup, atau kolomnya belum terjangkau karena jendelanya
            # belum digulir: seperti Dapodik, ketikan ini tidak menghasilkan apa-apa.
            self.peramban.ketikan_diabaikan += 1
            return
        if self.bio and (self.peramban.bio_hanya_ext
                         or self.peramban.bio_indeks(self) >= self.peramban.bio_band()):
            # Dapodik menolak ketikan langsung: versi ini hanya menerima nilai lewat model
            # Ext JS, atau kolomnya TIDAK berada di bagian jendela yang terlihat pada posisi
            # gulir saat ini (nilainya tidak jadi tersimpan) — persis dugaan sekolah.
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
        if self.daftar_pilihan:
            # Dropdown Ext JS: mengetik hanya mengubah TULISAN di layar. Nilai MODEL-nya
            # (yang dikirim ke Dapodik saat «Simpan») baru terisi bila tulisan itu persis
            # salah satu pilihan daftarnya — inilah yang membuat kolom terlihat "sudah
            # diisi" padahal tersimpannya kosong.
            pilihan = next((p for p in self.daftar_pilihan
                            if p.strip().lower() == (self.nilai or "").strip().lower()), "")
            self.nilai_model = pilihan
            if not pilihan:
                self.peramban.ketikan_diabaikan += 1

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
        #: True = SEMUA klik pada kotak centang/radio ditelan; hanya
        #: ``Ext.getCmp(...).setValue(...)`` yang bisa memilihnya (keadaan paling keras)
        self.hanya_ext_yang_menerima = False
        #: True = keadaan tercentang TIDAK terbaca dari input (``checked``/``is_selected``),
        #: hanya dari kelas ``x-form-cb-checked`` pada pembungkusnya — persis DOM sekolah
        self.keadaan_lewat_kelas = False
        #: berapa kali Ext.getCmp(...).setValue(...) dipakai
        self.ext_setvalue_dipakai = 0
        #: True = klik mengubah DOM (input ``checked``) TETAPI model Ext JS tidak ikut:
        #: penanda ``x-form-cb-checked`` tetap di pilihan lama dan kolom kilometer tetap
        #: nonaktif. Inilah keadaan yang membuat bot harus naik ke ``Ext.getCmp``.
        self.kelas_tidak_ikut_pindah = False
        #: berapa kali bot naik ke Ext.getCmp karena penandanya tidak pindah
        self.naik_ke_ext_kali = 0
        #: berapa kali bot menanyakan is_selected() pada kotak centang/radio
        self.is_selected_diminta = 0
        #: berapa kali keadaan tercentang terbaca dari kelas x-form-cb-checked
        self.dibaca_lewat_kelas = 0
        #: True = Ext JS tidak tersedia (Ext.getCmp tidak ada) — jalur pamungkas mati
        self.ext_mati = False
        #: berapa klik sungguhan pada kotak centang/radio yang ditelan
        self.klik_kotak_ditelan_kali = 0
        #: True = XPath/CSS untuk baris «Jarak rumah ke sekolah» meleset (tata letak Dapodik
        #: berbeda): bot harus menemukan pilihannya lewat teks labelnya (JavaScript).
        self.jarak_tanpa_xpath = False
        #: berapa kali bot melacak kotak lewat teks labelnya (jalur JavaScript)
        self.kotak_lewat_teks_dipakai = 0
        #: berapa kali bot melacak label pilihannya lewat teksnya (jalur JavaScript)
        self.label_lewat_teks_dipakai = 0
        #: True = halaman ini tidak punya baris «Jarak rumah ke sekolah» (versi Dapodik lain)
        self.tanpa_baris_jarak = False
        #: True = halaman ini punya tombol «Ubah» & jendela BIO (versi Dapodik sekolah)
        self.bio_aktif = False
        #: False = tombol «Ubah» tidak dipasang (versi Dapodik lain) — untuk uji kejujuran bot
        self.bio_ada_tombol = True
        #: True = jendela «Ubah» sedang terbuka
        self.bio_terbuka = False
        #: True = tombol «Simpan» jendela «Ubah» sudah ditekan
        self.bio_tersimpan = False
        #: Berapa kali area gulir harus digeser sebelum kolom BIO terjangkau (persis Dapodik:
        #: jendela «Ubah» panjang, kolomnya harus dibawa ke layar dulu)
        self.bio_perlu_gulir = 2
        #: Berapa kali **isi jendela «Ubah»** digulir (bukan halaman) — inilah yang menolong
        self.gulir_bio = 0
        #: Berapa kali tombol «Ubah» milik panel «Data Rincian PD» (palsu) tertekan
        self.bio_ubah_palsu_diklik = 0
        #: Berapa kali tombol «Simpan» milik panel «Data Rincian PD» (palsu) tertekan
        self.bio_simpan_palsu_diklik = 0
        #: Berapa kali tombol «Ubah» dicoba sampai jendela «Edit Peserta Didik» terbuka
        self.bio_ubah_dicoba = 0
        #: True = halaman ini punya panel «Data Rincian PD» dengan tombol «Ubah»/«Simpan» palsu
        self.bio_panel_rincian = False
        #: True = ada «Ubah» palsu di luar panel «Data Rincian» (petunjuk tampilan tak menolong)
        self.bio_ubah_palsu_luar = False
        #: True = Dapodik menolak SEMUA ketikan ke kolom BIO (hanya jalur Ext JS yang diterima).
        #: Meniru keadaan yang membuat bot harus mundur ke Ext.getCmp(...).setValue(...).
        self.bio_hanya_ext = False
        #: Berapa kolom BIO yang terlihat pada posisi gulir jendela saat ini. Kolom di luar
        #: bagian yang terlihat TIDAK dapat dicari/ditulis — inilah "gulir kebanyakan/kurang".
        self.bio_terlihat_awal = 4
        #: True = wadah jendela «Ubah» TIDAK terbaca oleh bot (mis. formulirnya berupa panel
        #: dengan judul yang tak dikenali). Kolomnya hanya bisa ditemukan lewat NAMANYA di
        #: seluruh halaman — persis cara skrip sekolah (`find_element(By.NAME, …)`).
        self.bio_tanpa_wadah = False
        #: Daftar dropdown (bound list Ext JS) yang sedang terbuka + penghitung untuk uji
        self.dropdown_terbuka: "UnsurPalsu | None" = None
        self.dropdown_dibuka = 0
        self.dropdown_item_diklik = 0
        self.dropdown_item_lewat_skrip = 0
        self.dropdown_ext_dipakai = 0
        self.dropdown_ditutup = 0
        #: True = tombol panah dropdown ditelan Dapodik (hanya Ext.getCmp(...).expand() bisa)
        self.dropdown_panah_ditelan = False
        #: True = jalur Ext.getCmp(...).expand() juga tidak tersedia
        self.dropdown_ext_mati = False
        #: True = daftar dropdown TIDAK mau terbuka (tombol panah, kolom, & Ext.expand gagal)
        self.dropdown_tak_bisa_dibuka = False
        #: True = item daftar bisa diklik tetapi tidak berpengaruh (persis Dapodik di PC)
        self.dropdown_item_ditelan = False
        self.dropdown_item_ditelan_kali = 0
        #: Berapa kali pilihan dipasang lewat model Ext JS (select/setValue)
        self.dropdown_ext_pilih = 0
        #: Berapa kali daftar dropdown DIBACA bot (dipakai menirukan data yang lambat tampil)
        self.dropdown_baca_kali = 0
        #: Berapa bacaan dulu sebelum pilihannya muncul (0 = langsung tampil) — persis Dapodik:
        #: daftar dropdown butuh sesaat untuk terisi setelah dibuka.
        self.dropdown_muat_perlu = 0
        #: Berapa pilihan yang terlihat sekaligus (0 = semua). Daftar dropdown punya area
        #: gulir sendiri: pilihan di bawah baru terlihat setelah daftarnya digeser.
        self.dropdown_band = 0
        #: Berapa kali isi daftar dropdown digeser (setiap geser = 150 px)
        self.gulir_daftar = 0
        #: Jarak gulir daftar dropdown (px) — tinggi satu baris ±30 px, jadi menggulir 150 px
        #: menyingkap ±5 baris berikutnya (persis daftar Ext JS yang panjang).
        self.gulir_daftar_px = 0
        self.dropdown_gulir_kali = 0
        #: Berapa kali bot mencoba mengklik pilihan yang belum terlihat di daftar
        self.dropdown_item_tak_terlihat = 0
        #: Isi kolom BIO yang benar-benar tersimpan (name → nilai saat «Simpan» ditekan)
        self.data_bio_tersimpan: dict[str, str] = {}
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
            # Struktur DOM sekolah: div.x-field (pembungkus) > div.x-form-cb-wrap-inner,
            # dengan label x-form-cb-label SESUDAH input di dalam wadah yang sama.
            pembungkus = UnsurPalsu(self, "div", kelas="x-field x-form-cb-wrap-inner",
                                    untuk=unsur.name, pilihan=unsur.label or "",
                                    periodik=unsur.periodik)
            if unsur.periodik:
                pembungkus.induk = next((u for u in self.unsur if u.panel_periodik), None)
            unsur.induk = pembungkus
            label = UnsurPalsu(self, "label", kelas="x-form-cb-label", teks=unsur.label or "",
                               untuk=unsur.name, pilihan=unsur.label or "",
                               periodik=unsur.periodik)
            label.induk = pembungkus
            posisi = self.unsur.index(unsur) + 1
            self.unsur.insert(posisi, pembungkus)
            self.unsur.insert(posisi + 1, label)
        if getattr(self, "kelas_tidak_ikut_pindah", False):
            # Radio baru saja dibungkus: keadaan awal DOM sekolah = «kurang dari 1 km» tercentang.
            self.pasang_kurang_tercentang()

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
            UnsurPalsu(self, "input", type="radio", name="jarak_rumah_ke_sekolah",
                       componentid="radiofield-1111",
                       label="Kurang dari 1 km", periodik=True, kelompok="jarak",
                       jalur="/html/body/div[2]/div/div/div[2]/div/div/div/div[3]/div[2]/div/div/"
                             "div/div[1]/div/div/div[7]/div/div/table/tbody/tr/td/div[1]/div/div/"
                             "span/input"),
            UnsurPalsu(self, "input", type="radio", name="jarak_rumah_ke_sekolah",
                       componentid="radiofield-1112",
                       label="Lebih dari 1 km", periodik=True, kelompok="jarak",
                       jalur="/html/body/div[2]/div/div/div[2]/div/div/div/div[3]/div[2]/div/div/"
                             "div/div[1]/div/div/div[7]/div/div/table/tbody/tr/td/div[2]/div/div/"
                             "span/input"),
            # Kolom teks di sebelah kotak «Jarak rumah ke sekolah» — persis Dapodik.
            # Kolom km nonaktif (disabled) sampai pilihan «lebih dari 1 km» terpasang —
            # persis DOM sekolah: `x-item-disabled` + `disabled=""` + aria-disabled="true".
            UnsurPalsu(self, "input", type="text", name="jarak_rumah_ke_sekolah_km",
                       componentid="numberfield-1113", label="Sebutkan (dalam kilometer)",
                       periodik=True, enabled=False),
            UnsurPalsu(self, "input", type="text", name="jumlah_saudara_kandung",
                       label="Jumlah Saudara Kandung", periodik=True),
            UnsurPalsu(self, "span", kelas="x-btn-inner-default-small", teks="Simpan dan Tutup",
                       periodik=True, simpan_periodik=True),
        ])
        self._pasang_pembungkus_kotak()
        if getattr(self, "bio_aktif", False):
            if getattr(self, "bio_panel_rincian", False):
                self.tambah_panel_rincian()
            if getattr(self, "bio_ubah_palsu_luar", False):
                # «Ubah» palsu ini dipasang LEBIH DULU (seperti tombol serupa di tempat lain
                # pada halaman): bot harus mencobanya, melihat jendelanya tidak terbuka, lalu
                # mencoba kandidat berikutnya.
                self.tambah_panel_rincian(jadikan_palsu=False, di_luar_panel=True)
            self.tambah_tombol_ubah()
        if getattr(self, "tanpa_baris_jarak", False):
            # Versi Dapodik yang tidak punya baris «Jarak rumah ke sekolah»: radio & labelnya
            # tidak dipasang sama sekali (dipakai uji kejujuran bot).
            self.unsur = [u for u in self.unsur if not self._unsur_baris_jarak(u)]
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

    def pasang_kurang_tercentang(self) -> None:
        """Tandai «kurang dari 1 km» sebagai pilihan yang sedang tercentang (DOM sekolah).

        Dipakai bersama ``kelas_tidak_ikut_pindah``: keadaan awal pada HTML sekolah adalah
        «kurang dari 1 km» yang berpenanda ``x-form-cb-checked``.
        """
        kurang = next((unsur for unsur in self.unsur
                       if unsur.type == "radio"
                       and (unsur.label or "") == "Kurang dari 1 km"), None)
        if kurang is None or kurang.induk is None:
            return
        kurang.terpilih = True
        if "x-form-cb-checked" not in (kurang.induk.kelas or ""):
            kurang.induk.kelas = (kurang.induk.kelas + " x-form-cb-checked").strip()
        self.perbarui_kolom_km()

    def siapkan_bio(self, ada_tombol: bool = True, panel_rincian: bool = False,
                    ubah_palsu_di_luar: bool = False) -> "PerambanPalsu":
        """Pasang tombol «Ubah» & jendela BIO seperti halaman Dapodik sekolah.

        ``ada_tombol=False`` meniru versi Dapodik yang tidak punya tombol «Ubah» — dipakai
        untuk memastikan bot melewati langkah BIO dengan jujur, bukan menebak-nebak.
        ``panel_rincian=True`` menambahkan panel «Data Rincian PD» beserta tombol
        «Ubah»/«Simpan» palsunya (persis tangkapan layar sekolah).
        """
        self.bio_aktif = True
        self.bio_ada_tombol = bool(ada_tombol)
        self.bio_panel_rincian = bool(panel_rincian)
        self.bio_ubah_palsu_luar = bool(ubah_palsu_di_luar)
        if self.sudah_masuk:
            self.tambah_tombol_ubah()
        return self

    def _kolom_bio_semua(self) -> list["UnsurPalsu"]:
        """Kolom teks BIO menurut urutan tampilannya (dari atas ke bawah)."""
        return [unsur for unsur in self.unsur
                if unsur.bio and unsur.type == "text" and unsur.name]

    def bio_band(self) -> int:
        """Berapa kolom BIO yang **terlihat** pada posisi gulir jendela saat ini.

        Meniru Dapodik/Ext JS: hanya kolom yang berada di bagian jendela yang terlihat yang
        bisa dicari & ditulis. Tiap geser 250 px memunculkan dua kolom berikutnya — jadi
        bukan soal "250 px kebanyakan atau kurang banyak", melainkan soal **posisi** gulir.
        """
        return min(self.bio_terlihat_awal + 2 * self.bio_geseran(),
                   len(self._kolom_bio_semua()))

    def bio_indeks(self, unsur: "UnsurPalsu") -> int:
        """Posisi kolom BIO pada urutan tampilan (0 = paling atas)."""
        try:
            return self._kolom_bio_semua().index(unsur)
        except ValueError:
            return -1

    def bio_geseran(self) -> int:
        """Berapa kali bagian BIO sudah digeser — sesuai cara bot menjangkaunya.

        Jendela «Ubah» punya area gulirnya sendiri (``gulir_bio``). Bila wadah jendelanya
        **tidak terbaca** oleh JavaScript (``bio_tanpa_wadah``), bot memakai cara skrip
        sekolah: kolomnya dicari lewat namanya, dan halaman digeser ``window.scrollBy``
        (``gulir``) — Selenium pun menggeser layar saat mengetik.
        """
        if self.bio_tanpa_wadah:
            return len(self.gulir)
        return self.gulir_bio

    def bio_siap(self) -> bool:
        """Apakah bagian BIO sudah digulir cukup jauh untuk dijangkau.

        Penting: jendela «Ubah» punya area gulirnya sendiri — menggulir halaman
        (``window.scrollBy``) TIDAK menolong, persis seperti yang terlihat pada tangkapan
        layar sekolah (jendela tetap memperlihatkan bagian yang sama). Bila wadah jendelanya
        tidak terbaca, yang dipakai bot adalah gulir halaman (lihat ``bio_geseran``).
        """
        return self.bio_geseran() >= self.bio_perlu_gulir

    def tambah_tombol_ubah(self) -> None:
        """Tombol «Ubah» (ungu) pada toolbar — membuka jendela BIO siswa."""
        if not self.bio_ada_tombol:
            return
        # Hanya tombol «Ubah» ASLI yang dihitung: «Ubah» milik panel «Data Rincian PD»
        # (palsu) tidak boleh membuat tombol aslinya tidak dipasang.
        if any(getattr(u, "aksi", "") == "ubah" and not getattr(u, "palsu", False)
               for u in self.unsur):
            return
        self.unsur.append(UnsurPalsu(self, "span", kelas="x-btn-inner-soft-purple-small",
                                     teks="Ubah", aksi="ubah"))

    def tambah_panel_rincian(self, jadikan_palsu: bool = True, di_luar_panel: bool = False) -> None:
        """Panel «Data Rincian PD» dengan toolbar «Ubah» & «Simpan» sendiri.

        Persis halaman sekolah (lihat tangkapan layar): di bawah jendela ada panel
        «Data Rincian PD : <nama siswa>» dengan deretan tombol Tambah / **Ubah** (ungu) /
        **Simpan** / Hapus / Validasi. Tombol «Ubah»/«Simpan» itu **bukan** milik jendela
        «Edit Peserta Didik» — menekannya tidak membuka/menyimpan apa pun. Bot harus
        membedakannya, kalau tidak kliknya "seolah berhasil" tetapi jendelanya tetap terbuka
        (itulah keluhan sekolah).
        """
        rincian = UnsurPalsu(self, "div", kelas="x-panel", teks="Data Rincian PD")
        self.unsur.append(rincian)
        if jadikan_palsu:
            for kelas, teks, aksi in (("x-btn-inner-soft-green-small", "Tambah", ""),
                                      ("x-btn-inner-soft-purple-small", "Ubah", "ubah"),
                                      ("x-btn-inner-default-small", "Simpan", "simpan"),
                                      ("x-btn-inner-soft-red-small", "Hapus", ""),
                                      ("x-btn-inner-soft-blue-small", "Validasi", "")):
                if not aksi:
                    continue
                palsu = UnsurPalsu(self, "span", kelas=kelas, teks=teks, aksi=aksi, palsu=True,
                                   rincian=True)
                palsu.induk = rincian
                self.unsur.append(palsu)
        if di_luar_panel:
            # «Ubah» palsu yang TIDAK berada di panel «Data Rincian» (mis. tombol serupa di
            # tempat lain): petunjuk tampilan tidak menolong, jadi bot harus mencobanya,
            # melihat jendelanya tidak terbuka, lalu mencoba kandidat berikutnya.
            self.unsur.append(UnsurPalsu(self, "span", kelas="x-btn-inner-soft-purple-small",
                                         teks="Ubah", aksi="ubah", palsu=True))

    def buka_jendela_bio(self) -> None:
        """Tombol «Ubah» ditekan → jendela BIO terbuka (butuh baris siswa terpilih)."""
        if not self.baris_siswa_terpilih():
            return
        self.bio_terbuka = True
        if not any(unsur.bio for unsur in self.unsur):
            self.tambah_jendela_bio()

    def tambah_jendela_bio(self) -> None:
        """Jendela «Ubah» beserta kolom-kolomnya (nama kolom dari skrip sekolah).

        Nilai awalnya sengaja diisi "LAMA" (data lama Dapodik): uji bisa memastikan bot
        benar-benar MENIMPA-nya dengan data siswa dari aplikasi SM.
        """
        self.unsur.append(UnsurPalsu(self, "div", kelas="x-window",
                                     teks="Ubah Data Peserta Didik", bio=True, bio_panel=True))
        for nomor, (nama, label, jenis) in enumerate(BIO_KOLOM_PALSU, start=1):
            if jenis:
                # Dropdown (combo Ext JS): kolom + tombol panah + daftar pilihannya.
                # Nilai awalnya KOSONG (bukan "LAMA") — di Dapodik pun combo kosong berarti
                # belum dipilih, berbeda dengan kolom teks yang bisa berisi data lama.
                # Persis DOM sekolah: role combobox, readonly, punya tombol panah, dan
                # nilai modelnya berisi ID pilihan (bukan teksnya).
                combo = UnsurPalsu(self, "input", type="text", name=nama, label=label,
                                   bio=True, nilai="", nilai_model="", nilai_id="",
                                   aria="combobox", role="combobox", readonly="readonly",
                                   daftar_pilihan=pilihan_dropdown_dapodik(jenis),
                                   componentid=f"combobox-{1300 + nomor}")
                self.unsur.append(combo)
                panah = UnsurPalsu(self, "div", kelas="x-form-trigger x-form-arrow-trigger",
                                   trigger_combo=True)
                panah.induk = combo
                self.unsur.append(panah)
                for opsi in combo.daftar_pilihan:
                    item = UnsurPalsu(self, "li", kelas="x-boundlist-item", teks=opsi,
                                      item_dropdown=True)
                    item.induk = combo
                    self.unsur.append(item)
                continue
            self.unsur.append(UnsurPalsu(self, "input", type="text", name=nama, label=label,
                                         bio=True, nilai="LAMA",
                                         componentid=f"textfield-{1200 + nomor}"))
        self.unsur.append(UnsurPalsu(self, "span", kelas="x-btn-inner-default-small",
                                     teks="Simpan", bio=True, simpan_bio=True, aksi="simpan"))

    def simpan_bio(self) -> None:
        """Tombol «Simpan» jendela «Ubah» ditekan: nilai tersimpan, jendelanya tertutup."""
        self.bio_tersimpan = True
        for unsur in self.unsur:
            if unsur.bio and unsur.type == "text" and unsur.name:
                # Dropdown mengirim NILAI MODEL Ext JS; kolom teks mengirim tulisannya.
                self.data_bio_tersimpan[unsur.name] = (unsur.nilai_model if unsur.daftar_pilihan
                                                       else unsur.nilai)
        self.bio_terbuka = False
        self.dropdown_terbuka = None

    # -------------------------------------------------- dropdown (combo) --- #
    def buka_dropdown(self, combo: "UnsurPalsu | None") -> None:
        """Daftar dropdown dibuka (klik tombol panah atau ``Ext.getCmp(...).expand()``)."""
        if combo is None or self.dropdown_tak_bisa_dibuka:
            return          # Dapodik keras: daftarnya tidak mau terbuka sama sekali
        if self.dropdown_terbuka is not combo:
            # Daftar yang baru dibuka selalu mulai dari atas, dan pilihannya butuh sesaat
            # untuk tampil (pengosongan daftar = waktunya kembali dari nol).
            self.gulir_daftar = 0
            self.gulir_daftar_px = 0
            self.dropdown_baca_kali = 0
        self.dropdown_terbuka = combo
        self.dropdown_dibuka += 1

    def item_dropdown_terlihat(self, item: "UnsurPalsu") -> bool:
        """Apakah satu pilihan dropdown benar-benar terlihat & bisa diklik saat ini.

        Tiga syarat, persis picker Ext JS: daftar dropdownnya sedang terbuka, datanya sudah
        selesai tampil (tidak sedang memuat), dan pilihannya berada di bagian daftar yang
        terlihat pada posisi gulir saat ini.
        """
        combo = item.induk
        if combo is None or self.dropdown_terbuka is not combo or self.dropdown_tak_bisa_dibuka:
            return False
        if self.dropdown_muat_perlu and self.dropdown_baca_kali <= self.dropdown_muat_perlu:
            return False                 # datanya belum tampil — masih dimuat
        if not self.dropdown_band:
            return True
        urutan = [u for u in self.unsur
                  if getattr(u, "item_dropdown", False) and u.induk is combo]
        try:
            posisi = urutan.index(item)
        except ValueError:
            return False
        # Setiap 30 px gulir menyingkap satu baris lagi (tinggi baris ±30 px).
        return posisi < self.dropdown_band + (self.gulir_daftar_px // 30)

    def daftar_dropdown_terlihat(self, combo: "UnsurPalsu | None") -> list["UnsurPalsu"]:
        """Pilihan yang terlihat pada daftar dropdown sebuah kolom (urutan tampilannya)."""
        if combo is None:
            return []
        return [u for u in self.unsur
                if getattr(u, "item_dropdown", False) and u.induk is combo
                and self.item_dropdown_terlihat(u)]

    def pilih_item_dropdown(self, item: "UnsurPalsu", lewat_skrip: bool = False) -> None:
        """Satu pilihan di daftar dropdown dipilih: nilai MODEL Ext JS ikut terisi."""
        combo = item.induk
        if combo is None or self.dropdown_terbuka is not combo:
            return
        if not self.item_dropdown_terlihat(item):
            # Pilihan yang belum terlihat tidak bisa diklik (persis Dapodik: tidak ada di
            # layar). Bot harus menggulir daftarnya lebih dulu.
            self.dropdown_item_tak_terlihat += 1
            return
        if self.dropdown_item_ditelan:
            # Klik pada pilihannya ditelan lapisan Dapodik: daftarnya tetap terbuka dan
            # nilai model TIDAK berubah — bot harus naik ke jalur model Ext JS.
            self.dropdown_item_ditelan_kali += 1
            return
        combo.nilai = item.teks            # tulisan di layar
        combo.nilai_model = item.teks      # teks pilihan yang dilihat Dapodik
        combo.nilai_id = combo.daftar_pilihan.index(item.teks) + 1 if item.teks in combo.daftar_pilihan else ""
        self.dropdown_terbuka = None
        self.dropdown_item_diklik += 1
        if lewat_skrip:
            self.dropdown_item_lewat_skrip += 1

    def pilih_dropdown_lewat_ext(self, combo: "UnsurPalsu | None", teks: str) -> bool:
        """Pilih pilihan lewat model Ext JS: ``select(record)`` / ``setValue(id)``.

        Persis komponen combo Ext JS: yang dicari adalah **record** di store komponennya
        (``displayField``), lalu nilainya diambil dari ``valueField`` — bukan teks yang
        diketikkan ke kotaknya.
        """
        if combo is None or not combo.daftar_pilihan:
            return False
        dicari = " ".join(str(teks or "").split()).lower()
        cocok = next((p for p in combo.daftar_pilihan
                      if " ".join(p.split()).lower() == dicari), "")
        if not cocok:
            return False
        combo.nilai = cocok
        combo.nilai_model = cocok
        combo.nilai_id = combo.daftar_pilihan.index(cocok) + 1
        self.dropdown_terbuka = None
        self.dropdown_ext_pilih += 1
        return True

    def tutup_dropdown(self) -> None:
        """Daftar dropdown ditutup tanpa memilih apa pun."""
        self.dropdown_terbuka = None
        self.gulir_daftar = 0
        self.gulir_daftar_px = 0
        self.dropdown_baca_kali = 0
        self.dropdown_ditutup += 1

    def siapkan_jarak_tanpa_xpath(self) -> "PerambanPalsu":
        """XPath/CSS baris «Jarak rumah ke sekolah» meleset (tata letak Dapodik berbeda).

        Persis keadaan pada log sekolah: bot melaporkan «kotak … tidak ada di halaman ini»
        walaupun pilihannya jelas terlihat. Dengan mode ini bot harus menemukan pilihannya
        lewat **teks labelnya** (dibaca JavaScript), lalu mengisi kolom kilometer.
        """
        self.jarak_tanpa_xpath = True
        return self

    def hapus_baris_jarak(self) -> "PerambanPalsu":
        """Versi Dapodik yang TIDAK punya baris «Jarak rumah ke sekolah» sama sekali.

        Baris Data Periodik baru dibuat setelah baris siswa dipilih, jadi tombol ini memasang
        penanda: saat panelnya dibangun, radio «… 1 km» tidak ikut dibuat. Dipakai untuk
        memastikan bot tidak menebak-nebak: pilihannya tidak dipasang, kolom kilometer
        dilewati, dan log menyebutkan apa yang benar-benar terlihat di panel.
        """
        self.tanpa_baris_jarak = True
        self.unsur = [u for u in self.unsur if not self._unsur_baris_jarak(u)]
        return self

    def siapkan_model_ext_tidak_ikut(self) -> "PerambanPalsu":
        """Keadaan pada DOM sekolah: «kurang dari 1 km» sudah tercentang (berpenanda),
        sementara klik berikutnya hanya mengubah DOM tanpa memindahkan penandanya —
        sehingga kolom kilometer tetap nonaktif sampai ``Ext.getCmp`` menyetel nilainya.
        """
        self.kelas_tidak_ikut_pindah = True
        self.pasang_kurang_tercentang()      # radio mungkin belum dibuat: diulang saat dibuat
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

    def perbarui_kolom_km(self) -> None:
        """Dapodik menonaktifkan kolom km sampai pilihan «lebih dari 1 km» terpasang.

        Persis DOM sekolah: ``<div class="x-field ... x-item-disabled">`` dengan
        ``<input ... disabled>`` pada kolom ``jarak_rumah_ke_sekolah_km``.
        """
        km = next((unsur for unsur in self.unsur
                   if unsur.name == "jarak_rumah_ke_sekolah_km"), None)
        if km is None:
            return
        # Dapodik mengaktifkan kolom km hanya setelah MODEL Ext JS-nya berubah — yaitu saat
        # penanda x-form-cb-checked benar-benar pindah ke «lebih dari 1 km» (DOM saja tidak cukup).
        km.enabled = any(unsur.kelompok == "jarak"
                         and (unsur.label or "").strip() == "Lebih dari 1 km"
                         and "x-form-cb-checked" in (unsur.induk.kelas if unsur.induk else "")
                         for unsur in self.unsur)

    def ext_set_value(self, componentid: str, nilai) -> bool:
        """Ext.getCmp(id).setValue(...) — jalur pamungkas Ext JS (data-componentid)."""
        if self.ext_mati:
            return False
        for unsur in self.unsur:
            if unsur.componentid and unsur.componentid == componentid:
                if unsur.type in ("radio", "checkbox"):
                    if bool(nilai) and self.panel_periodik_terbuka():
                        # Ext.getCmp memilih lewat MODEL Ext JS: penandanya ikut pindah dan
                        # kolom kilometer pun jadi aktif.
                        unsur._pilih_kotak(dari_ext=True)
                    return True
                if unsur.daftar_pilihan:
                    # Dropdown: Ext JS hanya mengisi nilai model bila pilihannya ada di daftar.
                    teks = "" if nilai is None else str(nilai)
                    unsur.nilai = teks
                    unsur.nilai_model = next(
                        (p for p in unsur.daftar_pilihan if p.strip().lower() == teks.strip().lower()),
                        "")
                    return True
                unsur.nilai = "" if nilai is None else str(nilai)
                return True
        return False

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
        if getattr(unsur, "item_dropdown", False):
            # Pilihan dropdown hanya terlihat selagi daftar dropdownnya terbuka.
            return self.dropdown_terbuka is unsur.induk
        if getattr(unsur, "trigger_combo", False):
            # Tombol panah dropdown: ikut hidup-matinya jendela «Ubah».
            return self.bio_terbuka
        if unsur.bio:
            # Jendela «Ubah» (BIO) hanya tampil setelah tombol «Ubah» ditekan.
            return self.bio_terbuka
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
        potong = re.search(r"/(?:preceding|following|ancestor)::", bagian)
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
        for awal in ("input", "button", "select", "textarea", "a", "form", "li", "div",
                     "span", "img", "*"):
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
        """Kolom Data Periodik/BIO baru terjangkau setelah panelnya digulir cukup jauh."""
        if getattr(unsur, "item_dropdown", False):
            # Pilihan dropdown hanya bisa dijangkau selagi daftarnya terbuka, datanya sudah
            # tampil, dan pilihannya berada di bagian daftar yang terlihat.
            return self.item_dropdown_terlihat(unsur)
        if unsur.bio:
            # Kolom BIO hanya terjangkau bila jendelanya terbuka DAN kolomnya berada di bagian
            # yang terlihat pada posisi gulir saat ini (bukan sekadar "ada di DOM").
            return (self.bio_terbuka and self.bio_siap()
                    and 0 <= self.bio_indeks(unsur) < self.bio_band())
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
            poros_lelehur = self._bagian_ancestor(nilai)
            for unsur in self.unsur:
                if not self._cocokkan(unsur, nilai, xpath=(by == "xpath")):
                    continue
                tujuan = unsur
                if poros_lelehur:
                    lanjut = self._poros_ancestor(unsur, poros_lelehur)
                    if not lanjut:
                        continue
                    tujuan = lanjut[0]
                elif poros:
                    lanjut = self.poros_input(unsur, poros)
                    if not lanjut:
                        continue
                    tujuan = lanjut[0]
                if tujuan not in hasil:
                    hasil.append(tujuan)
        if getattr(self, "jarak_tanpa_xpath", False) and by != "name":
            hasil = [u for u in hasil if not self._unsur_baris_jarak(u)]
        return [u for u in hasil if self._terjangkau(u)]

    @staticmethod
    def _unsur_baris_jarak(unsur: "UnsurPalsu") -> bool:
        """Unsur milik baris «Jarak rumah ke sekolah» (radio «… 1 km» beserta labelnya)."""
        if unsur.name == "jarak_rumah_ke_sekolah":
            return True
        if unsur.componentid in ("radiofield-1111", "radiofield-1112"):
            return True
        teks = " ".join([unsur.teks or "", unsur.label or "", unsur.pilihan or ""]).lower()
        return "1 km" in teks

    @staticmethod
    def _bagian_ancestor(pola: str) -> str:
        """Ambil bagian poros leluhur, mis. ``ancestor::div[…][1]//input[@type="radio"][1]``."""
        posisi = (pola or "").find("/ancestor::")
        return pola[posisi + 1:] if posisi >= 0 else ""

    def _poros_ancestor(self, unsur: UnsurPalsu, bagian: str) -> list[UnsurPalsu]:
        """Selesaikan poros leluhur: ``ancestor::div[…]`` lalu input di dalamnya.

        Dipakai selector bot untuk melacak radio dari labelnya — pada DOM Dapodik label
        ``x-form-cb-label`` berada SESUDAH input di dalam wadah ``.x-field`` yang sama.
        """
        kelas = re.findall(r'contains\(\s*@class\s*,\s*[\'"]([^\'"]+)[\'"]\s*\)', bagian)
        tag = re.search(r"ancestor::(\w+)", bagian)
        wadah = None
        p = unsur.induk
        while p is not None:
            if (not tag or tag.group(1) == p.tag_name) and \
                    all(k.lower() in (p.kelas or "").lower() for k in kelas):
                wadah = p
                break
            p = p.induk
        if wadah is None:
            return []
        if "//input" in bagian:
            tipe = set(re.findall(r"@type\s*=\s*[\'\"](\w+)[\'\"]", bagian))
            hasil = [u for u in self.unsur
                     if u.tag_name == "input" and (not tipe or u.type in tipe)
                     and u.induk is wadah]
            return hasil[:1] if "[1]" in bagian.split("//input", 1)[1] else hasil
        return [wadah]

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
        # Tag yang diminta, mis. following::div[…] (tombol panah dropdown) — default input.
        tag_poros = re.search(r"(?:preceding|following)::(\w+|\*)", bagian)
        tag_diminta = tag_poros.group(1) if tag_poros else "input"
        kelas_poros = re.findall(r"contains\(@class,\s*['\"]([^'\"]+)['\"]\)", bagian)
        try:
            posisi = self.unsur.index(unsur)
        except ValueError:
            return []
        rentang = self.unsur[:posisi][::-1] if arah == "preceding" else self.unsur[posisi + 1:]
        for kandidat in rentang:
            if tag_diminta != "*" and kandidat.tag_name != tag_diminta:
                continue
            if tipe and kandidat.type != tipe.group(1):
                continue
            if any(k.lower() not in (kandidat.kelas or "").lower() for k in kelas_poros):
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
        if "jendela-edit" in skrip:
            # Bot mencari jendela «Edit Peserta Didik» yang benar-benar terbuka.
            if self.bio_tanpa_wadah:
                return None                     # wadahnya tidak terbaca oleh bot
            wadah = next((u for u in self.unsur if getattr(u, "bio_panel", False)), None)
            return wadah if (self.bio_terbuka and wadah is not None) else None
        if "judul-jendela" in skrip:
            if self.bio_tanpa_wadah:
                return ""                       # judulnya pun tidak terbaca
            return "Edit Peserta Didik : Uji" if self.bio_terbuka else ""
        if "rincian-bio" in skrip:
            # Laporan mandiri bot: ringkasan keadaan jendela «Ubah» (untuk log).
            akar = argumen[0] if argumen else None
            daftar = str(argumen[1] if len(argumen) > 1 else "").split(",")
            isi = []
            for nama_kolom in [n.strip() for n in daftar if n.strip()]:
                ada = sum(1 for u in self.unsur if u.bio and u.name == nama_kolom)
                isi.append(f"{nama_kolom}={ada}")
            gulir = [f"x-panel-body {self.gulir_bio}/{self.bio_terlihat_awal}/"
                     f"{len(self._kolom_bio_semua())}"] if (akar is not None and self.bio_terbuka) else []
            simpan = sum(1 for u in self.unsur
                         if getattr(u, "aksi", "") == "simpan" and not getattr(u, "palsu", False))
            simpan_rincian = sum(1 for u in self.unsur
                                 if getattr(u, "aksi", "") == "simpan" and getattr(u, "palsu", False))
            dropdown = ([f"{u.name}={u.nilai_model or '-'} " for u in self.unsur
                         if u.bio and u.daftar_pilihan] if akar is not None else [])
            return {"kolom": " ".join(isi), "gulir": " | ".join(gulir),
                    "simpan": simpan, "simpan_rincian": simpan_rincian,
                    "dropdown": "".join(dropdown).strip()}
        if "tipe-kolom" in skrip:
            # Bot memeriksa apakah kolomnya kolom teks atau dropdown (combo Ext JS).
            sasaran = argumen[0] if argumen else None
            if sasaran is None:
                return ""
            if sasaran.daftar_pilihan:
                return "combo"
            if "x-form-trigger" in (sasaran.kelas or ""):
                return "tombol"
            return "teks"
        if "dropdown-buka" in skrip:
            # Jalur terakhir bot: Ext.getCmp(id).expand() (bila tombol panahnya ditelan).
            sasaran = argumen[0] if argumen else None
            if sasaran is None or not sasaran.daftar_pilihan or self.dropdown_ext_mati \
                    or self.dropdown_tak_bisa_dibuka:
                return False
            self.dropdown_ext_dipakai += 1
            self.buka_dropdown(sasaran)
            return True
        if "dropdown-daftar" in skrip:
            # Pilihan pada daftar dropdown MILIK KOLOM ITU (bukan daftar dropdown lain yang
            # masih terbuka): persis ``Ext.getCmp(id).getPicker()`` di halaman sungguhan.
            # Tiap pembacaan dihitung: datanya baru "tampil" setelah beberapa bacaan
            # (persis Dapodik: daftar dropdown tidak langsung berisi).
            sasaran = argumen[0] if argumen else None
            combo = self.dropdown_terbuka
            if combo is None or (sasaran is not None and sasaran is not combo):
                return []
            self.dropdown_baca_kali += 1
            return [u.teks for u in self.daftar_dropdown_terlihat(combo)]
        if "dropdown-item" in skrip:
            # Indeks pilihan (pada elemen ``li.x-boundlist-item``) yang teksnya cocok.
            sasaran = argumen[0] if argumen else None
            combo = self.dropdown_terbuka
            if combo is None or (sasaran is not None and sasaran is not combo):
                return -1
            dicari = " ".join(str(argumen[1] if len(argumen) > 1 else "").split()).lower()
            self.dropdown_baca_kali += 1
            for posisi, unsur in enumerate(self.daftar_dropdown_terlihat(combo)):
                if " ".join((unsur.teks or "").split()).lower() == dicari:
                    return posisi
            return -1
        if "dropdown-nilai" in skrip:
            # Tulisan di layar + nilai model Ext JS sebuah dropdown (dua hal yang berbeda!).
            # ``model`` = teks pilihan yang benar-benar tersimpan (seperti ``getRawValue()``);
            # ``id`` = nilainya di model (seperti ``getValue()`` pada combo Dapodik).
            sasaran = argumen[0] if argumen else None
            if sasaran is None:
                return {}
            return {"tampil": sasaran.nilai, "model": sasaran.nilai_model,
                    "id": sasaran.nilai_id}
        if "dropdown-terbuka" in skrip:
            # Keadaan daftar yang sebenarnya (daftar tertutup = pilihannya tidak bisa diklik).
            sasaran = argumen[0] if argumen else None
            return bool(not self.dropdown_tak_bisa_dibuka and sasaran is not None
                        and self.dropdown_terbuka is sasaran)
        if "dropdown-store" in skrip:
            # Pilihan dibaca dari DATA komponen Ext JS (store) — tidak perlu daftarnya
            # terbuka. Inilah cara yang paling andal di Dapodik sungguhan.
            sasaran = argumen[0] if argumen else None
            if sasaran is None or not sasaran.daftar_pilihan:
                return []
            return [{"teks": p, "nilai": i + 1}
                    for i, p in enumerate(sasaran.daftar_pilihan)]
        if "dropdown-pilih" in skrip:
            # Pilih lewat model Ext JS: select(record) / setValue(id).
            sasaran = argumen[0] if argumen else None
            dicari = str(argumen[1] if len(argumen) > 1 else "")
            return self.pilih_dropdown_lewat_ext(sasaran, dicari)
        if "/* gulir-daftar-dropdown */" in skrip:
            # Bot menggeser ISI daftar dropdown (daftarnya punya area gulirnya sendiri):
            # persis ``picker.getEl()`` → ``scrollTop += 150`` di halaman sungguhan.
            if self.dropdown_terbuka is None or self.dropdown_tak_bisa_dibuka:
                return 0
            jauh = int(argumen[1]) if len(argumen) > 1 else 150
            self.gulir_daftar += 1
            self.gulir_daftar_px += jauh
            self.dropdown_gulir_kali += 1
            return self.gulir_daftar_px
        if "dropdown-tutup" in skrip:
            self.tutup_dropdown()
            return True
        if "ubah-kandidat" in skrip:
            # Semua tombol «Ubah» yang terlihat: yang di LUAR panel «Data Rincian» lebih dulu,
            # persis urutan yang diharapkan bot.
            kandidat = [u for u in self.unsur if getattr(u, "aksi", "") == "ubah"]
            return sorted(kandidat, key=lambda u: 1 if getattr(u, "rincian", False) else 0)
        if "simpan-jendela" in skrip:
            # Tombol «Simpan» DI DALAM jendela «Ubah» (bukan milik panel «Data Rincian»).
            # Tanpa jendela (argumen kosong): dicari tombol «Simpan» yang BUKAN milik panel
            # «Data Rincian» — jalur cadangan bila wadah jendelanya tidak terbaca.
            if not self.bio_terbuka:
                return None
            akar = argumen[0] if argumen else None
            kandidat = [u for u in self.unsur
                        if getattr(u, "aksi", "") == "simpan" and not getattr(u, "palsu", False)]
            if akar is None:
                kandidat = [u for u in kandidat if not getattr(u, "rincian", False)]
            return kandidat[0] if kandidat else None
        if "kolom-jendela" in skrip:
            # Kolom BIO dicari DI DALAM jendela: nama kolom (persis skrip sekolah) lebih dulu,
            # lalu lewat teks labelnya. Kolom baru terjangkau setelah isi jendela digulir.
            if self.bio_tanpa_wadah:
                return None             # bot tidak mengenali wadahnya: harus lewat nama
            if not (self.bio_terbuka and self.bio_siap()):
                return None
            batas = self.bio_band()
            posisi = {id(u): i for i, u in enumerate(self._kolom_bio_semua())}
            nama = str(argumen[1] if len(argumen) > 1 else "").strip()
            label = str(argumen[2] if len(argumen) > 2 else "").strip().lower()
            for unsur in self.unsur:
                if not (unsur.bio and unsur.type == "text"):
                    continue
                if posisi.get(id(unsur), 99) >= batas:
                    continue          # kolomnya di luar bagian jendela yang terlihat
                if nama and unsur.name == nama:
                    return unsur
            if label:
                for unsur in self.unsur:
                    if not (unsur.bio and unsur.type == "text"):
                        continue
                    if posisi.get(id(unsur), 99) >= batas:
                        continue
                    teks = (unsur.label or "").strip().lower()
                    if teks and (teks == label or teks.startswith(label)):
                        return unsur
            return None
        if "cari-kotak-teks" in skrip:
            # Bot melacak kotak lewat TEKS pilihannya (bukan XPath): label → kotaknya.
            teks = str(argumen[0] if argumen else "").strip().lower()
            pilihan: list[UnsurPalsu] = []
            for unsur in self.unsur:
                if unsur.type not in ("radio", "checkbox"):
                    continue
                teks_unsur = (unsur.label or unsur.pilihan or unsur.teks or "").strip().lower()
                if not teks_unsur or not teks:
                    continue
                if teks_unsur == teks:
                    self.kotak_lewat_teks_dipakai += 1
                    return unsur
                if teks in teks_unsur or (teks_unsur in teks and len(teks_unsur) > 3):
                    pilihan.append(unsur)
            if pilihan:
                self.kotak_lewat_teks_dipakai += 1
                return pilihan[0]
            return None
        if "label-teks" in skrip:
            # Bot melacak LABEL pilihannya lewat teksnya (klik label = cara skrip sekolah).
            teks = str(argumen[0] if argumen else "").strip().lower()
            for unsur in self.unsur:
                if "x-form-cb-label" not in (unsur.kelas or ""):
                    continue
                teks_unsur = (unsur.teks or unsur.pilihan or "").strip().lower()
                if teks_unsur and (teks_unsur == teks or teks in teks_unsur):
                    self.label_lewat_teks_dipakai += 1
                    return unsur
            return None
        if "ringkas-panel" in skrip:
            # Ringkasan yang benar-benar terlihat di panel Data Periodik (untuk log).
            label = []
            for unsur in self.unsur:
                if unsur.periodik and unsur.label and unsur.label not in label:
                    label.append(unsur.label)
            kolom = [u.name for u in self.unsur if u.periodik and u.name]
            bagian = []
            if label:
                bagian.append("label: " + " | ".join(label[:6]))
            if kolom:
                bagian.append("kolom: " + " | ".join(kolom[:6]))
            return " · ".join(bagian)
        if "ext-cari-pilihan" in skrip:
            # Ext.ComponentQuery: radio dengan getBoxLabel() yang memuat teks pilihannya.
            if self.ext_mati:
                return ""
            teks = str(argumen[0] if argumen else "").strip().lower()
            nama = str(argumen[1] if len(argumen) > 1 else "").strip()
            for unsur in self.unsur:
                if unsur.type != "radio":
                    continue
                if nama and unsur.name != nama:
                    continue
                teks_unsur = (unsur.label or "").strip().lower()
                if not teks_unsur or not (teks_unsur == teks or (teks and teks in teks_unsur)):
                    continue
                if not self.panel_periodik_terbuka():
                    return ""
                unsur._pilih_kotak(dari_ext=True)
                self.ext_setvalue_dipakai += 1
                return f"Ext.ComponentQuery radio {unsur.componentid}.setValue"
            return ""
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
                sasaran = argumen[0]
                if sasaran.periodik and (not self.panel_periodik_terbuka()
                                         or not self.periodik_siap()):
                    self.ketikan_diabaikan += 1      # panel kelabu: isian tidak tersimpan
                    return None
                if sasaran.bio and (self.bio_hanya_ext
                                    or self.bio_indeks(sasaran) >= self.bio_band()):
                    # Kolom BIO: menulis `input.value` langsung TIDAK mengubah model Ext JS
                    # (persis kejadian di Dapodik) — nilainya akan ditimpa saat disimpan.
                    # Hanya Ext.getCmp(...).setValue(...) yang benar-benar mengubahnya.
                    self.ketikan_diabaikan += 1
                    return None
                sasaran.nilai = str(argumen[1])
                sasaran.diketikan.append(str(argumen[1]))
            return None
        if "keadaan-pilihan" in skrip and argumen:
            # Keadaan pilihan: apakah unsurnya sendiri tercentang (properti checked / kelas
            # x-form-cb-checked / aria-checked) dan apakah radio pasangannya masih tercentang.
            sasaran = argumen[0]
            bertanda = lambda u: (u is not None and u.induk is not None
                                  and "x-form-cb-checked" in (u.induk.kelas or ""))
            sendiri = {"checked": bool(sasaran.terpilih),
                       "kelas": bertanda(sasaran),      # HANYA penanda kelas yang dihitung
                       "aria": bertanda(sasaran)}
            pasangan = False
            if sasaran.type == "radio" and sasaran.kelompok:
                for lain in self.unsur:
                    if lain is sasaran or lain.kelompok != sasaran.kelompok:
                        continue
                    if lain.terpilih or bertanda(lain):
                        pasangan = True
                        break
            if self.keadaan_lewat_kelas:
                # Keadaan hanya terbaca dari kelas x-form-cb-checked (persis DOM sekolah).
                sendiri = {"checked": False, "kelas": bertanda(sasaran), "aria": False}
                self.dibaca_lewat_kelas += 1
            return {"sendiri": sendiri, "pasangan": pasangan}
        if "penanda-dipakai" in skrip:
            return any("x-form-cb-checked" in ((unsur.induk.kelas if unsur.induk else ""))
                       for unsur in self.unsur)
        if "komponen-id" in skrip and argumen:
            # Id komponen Ext JS: data-componentid → id wadah .x-field → `for` label.
            sasaran = argumen[0]
            if sasaran.componentid:
                return sasaran.componentid
            if sasaran.induk is not None and sasaran.induk.id:
                return sasaran.induk.id
            return ""
        if "Ext.getCmp" in skrip and len(argumen) >= 2:
            # Ext.getCmp(id).setValue(...) — jalur pamungkas Ext JS.
            berhasil = self.ext_set_value(str(argumen[0]), argumen[1])
            if berhasil:
                self.ext_setvalue_dipakai += 1
            return berhasil
        if "x-form-cb-checked" in skrip and "closest" in skrip and \
                "aria-checked" in skrip and argumen:
            # Pembacaan keadaan tercentang: properti checked → kelas x-form-cb-checked →
            # aria-checked. Pada DOM Dapodik, kelas itulah yang menandai pilihannya.
            sasaran = argumen[0]
            if getattr(sasaran, "terpilih", False):
                if self.keadaan_lewat_kelas:
                    self.dibaca_lewat_kelas += 1
                return True
            return False
        if "x-form-cb-label" in skrip and "closest" in skrip and argumen:
            # Teks label pilihan milik sebuah kotak (dari wadah .x-field-nya).
            sasaran = argumen[0]
            wadah = getattr(sasaran, "induk", None)
            for unsur in self.unsur:
                if getattr(unsur, "induk", None) is wadah and "x-form-cb-label" in \
                        (unsur.kelas or ""):
                    return unsur.teks
            return ""
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
                if self.hanya_ext_yang_menerima:
                    self.klik_diabaikan += 1
                    return None
                self.pilih_lewat_pembungkus(sasaran.untuk, sasaran.pilihan)
            elif getattr(sasaran, "periodik", False) and \
                    getattr(sasaran, "type", "") in ("radio", "checkbox"):
                self.diklik_skrip_diabaikan += 1
            return None
        if "scrollIntoView" in skrip and argumen:
            sasaran = argumen[0]
            if getattr(sasaran, "bio", False) or getattr(sasaran, "bio_panel", False):
                # Kolom/jendela BIO dibawa ke layar: yang bergeser adalah isi jendelanya.
                self.gulir_bio += 1
                return None
            if getattr(sasaran, "periodik", False) or getattr(sasaran, "panel_periodik", False):
                # Inilah yang benar-benar menjangkau area gulir panel Data Periodik.
                self.gulir_panel.append(getattr(sasaran, "name", "")
                                        or getattr(sasaran, "teks", "") or "panel")
            return None
        if "/* gulir-jendela-awal */" in skrip:
            # Bot mengembalikan isi jendela «Ubah» ke atas sebelum mulai mengisi kolomnya.
            if not self.bio_terbuka:
                return 0
            if self.bio_tanpa_wadah:
                return None         # wadah gulirnya pun tidak terbaca oleh bot
            self.gulir_bio = 0
            return 1
        if "/* gulir-jendela */" in skrip:
            # Bot menggulir ISI jendela «Ubah» (bukan halaman): inilah yang benar-benar
            # menjangkau kolom di bagian bawah jendela.
            if not self.bio_terbuka:
                return 0
            self.gulir_bio += 1
            return 250
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
                    if self.hanya_ext_yang_menerima:
                        self.klik_diabaikan += 1
                        return None
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
