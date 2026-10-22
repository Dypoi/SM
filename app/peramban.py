#!/usr/bin/env python3
"""Buka aplikasi SM di peramban — utamakan **Chrome yang sedang terbuka**.

Masukan sekolah (ronde 42): «ketika bodap icon dijalankan maka akan langsung membuka
chrome yang sedang saat ini dibuka». Sebelumnya aplikasi memakai ``webbrowser.open()``
yang menyerahkan urusan ke peramban bawaan Windows (sering Edge) atau — kalau Windows
belum punya pilihan — menampilkan kotak «Buka dengan…».

Cara kerja
----------
* ``chrome.exe`` dicari lewat registry ``App Paths`` (HKCU lalu HKLM), folder pemasangan
  umum (Program Files, Program Files (x86), LocalAppData), lalu ``PATH``. Bisa dipaksa
  lewat variabel lingkungan ``SM_CHROME`` (dipakai juga oleh uji otomatis).
* Perintahnya hanya ``chrome.exe <alamat>`` — **tanpa** ``--user-data-dir`` dan **tanpa**
  ``--new-window``. Justru karena itu Chrome yang sudah berjalan dengan profil yang sama
  akan membuka **tab baru di jendela yang sedang terbuka**, bukan jendela dengan profil
  baru. Kalau Chrome belum jalan, perintah yang sama menyalakan Chrome dengan profil
  bawaannya.
* Chrome dijalankan lewat ``Popen`` dengan ``CREATE_NO_WINDOW`` (tidak ada jendela konsol
  sekejap pun) dan tidak ditunggu, jadi pemanggil langsung selesai.
* Bila Chrome tidak terpasang, kembali ke peramban bawaan (``webbrowser``) supaya
  aplikasi tetap bisa dibuka. ``SM_PERAMBAN=bawaan`` memaksa jalur cadangan itu
  (mis. pada komputer yang memang memakai peramban lain).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

#: Urutan folder tempat chrome.exe biasanya dipasang, relatif terhadap folder induknya.
FOLDER_CHROME = (
    "Google/Chrome/Application",
    "Google/Chrome Beta/Application",
    "Google/Chrome SxS/Application",      # Chrome Canary
)

#: Variabel lingkungan yang menandai folder pemasangan khas Windows.
AKAR_INSTALASI = ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432")


def tanpa_jendela() -> int:
    """Bendera agar proses anak tidak memunculkan jendela konsol (0 di luar Windows)."""
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def kandidat_chrome() -> list[Path]:
    """Tempat-tempat ``chrome.exe`` biasanya berada (urut dari yang paling mungkin)."""
    kandidat: list[Path] = []
    for variabel in AKAR_INSTALASI:
        dasar = (os.environ.get(variabel) or "").strip()
        if not dasar:
            continue
        for folder in FOLDER_CHROME:
            kandidat.append(Path(dasar) / folder / "chrome.exe")
    kandidat.append(Path("C:/Program Files/Google/Chrome/Application/chrome.exe"))
    kandidat.append(Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"))
    return kandidat


def _chrome_dari_registry() -> Path | None:
    """Chrome yang terdaftar di Windows (``App Paths``) — cara paling akurat."""
    if os.name != "nt":
        return None
    try:
        import winreg      # hanya ada di Windows
    except ImportError:    # pragma: no cover - lingkungan tanpa registry
        return None
    kunci = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
    for akar in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for tambahan in (0, int(getattr(winreg, "KEY_WOW64_32KEY", 0)),
                         int(getattr(winreg, "KEY_WOW64_64KEY", 0))):
            try:
                with winreg.OpenKey(akar, kunci, 0, winreg.KEY_READ | tambahan) as k:
                    nilai = winreg.QueryValue(k, None)
            except OSError:
                continue
            if not nilai:
                continue
            jalur = Path(str(nilai).strip().strip('"'))
            if jalur.is_file():
                return jalur
    return None


def _chrome_dari_path() -> Path | None:
    """Chrome yang bisa ditemukan lewat ``PATH`` (termasuk pemasangan portabel/Linux)."""
    for nama in ("chrome", "chrome.exe", "google-chrome", "google-chrome-stable",
                 "chromium", "chromium-browser"):
        temuan = shutil.which(nama)
        if temuan:
            return Path(temuan)
    return None


def cari_chrome() -> Path | None:
    """Lokasi ``chrome.exe`` bila ada, ``None`` bila tidak ditemukan."""
    paksa_bawaan = (os.environ.get("SM_PERAMBAN") or "").strip().lower()
    if paksa_bawaan in {"bawaan", "default", "webbrowser"}:
        return None
    paksa = (os.environ.get("SM_CHROME") or "").strip()
    if paksa:
        jalur = Path(paksa).expanduser()
        if jalur.is_file():
            return jalur
    for pencari in (_chrome_dari_registry, _chrome_dari_path):
        temuan = pencari()
        if temuan is not None:
            return temuan
    for jalur in kandidat_chrome():
        if jalur.is_file():
            return jalur
    return None


def perintah_chrome(chrome: Path, alamat: str) -> list[str]:
    """Perintah untuk membuka ``alamat`` di Chrome yang sudah berjalan.

    Hanya ``chrome.exe <alamat>``. **Jangan** menambahkan ``--user-data-dir`` — Chrome
    akan menganggap dirinya program lain lalu membuka jendela dengan profil baru — dan
    jangan menambahkan ``--new-window`` yang memaksa jendela baru.
    """
    return [str(chrome), str(alamat)]


def buka(alamat: str) -> str:
    """Buka ``alamat`` di Chrome yang sedang terbuka; kembalikan cara yang dipakai.

    Nilai balik: ``"chrome"`` (lewat Chrome), ``"peramban-bawaan"`` (cadangan), atau
    ``"gagal"`` (dua-duanya tidak bisa dipakai).
    """
    chrome = cari_chrome()
    if chrome is not None:
        try:
            subprocess.Popen(
                perintah_chrome(chrome, alamat),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=tanpa_jendela() | int(getattr(subprocess, "DETACHED_PROCESS", 0)),
            )
            return "chrome"
        except OSError:
            pass       # Chrome ada tetapi gagal dijalankan → pakai peramban bawaan
    try:
        import webbrowser

        webbrowser.open(alamat)
        return "peramban-bawaan"
    except Exception:      # noqa: BLE001 - jangan sampai menggagalkan peluncuran aplikasi
        return "gagal"


def buka_port(port: int, host: str = "localhost") -> str:
    """Buka aplikasi di ``http://<host>:<port>`` (Chrome lebih dulu)."""
    return buka(f"http://{host}:{int(port)}")


def keterangan(cara: str) -> str:
    """Kalimat singkat untuk log/pesan (jujur menyebut peramban mana yang dipakai)."""
    if cara == "chrome":
        return "dibuka di Chrome (tab baru pada jendela Chrome yang sedang terbuka)"
    if cara == "peramban-bawaan":
        return "Chrome tidak ditemukan — dibuka di peramban bawaan"
    return "peramban tidak bisa dibuka otomatis — buka alamatnya dari peramban"


__all__ = ["AKAR_INSTALASI", "FOLDER_CHROME", "buka", "buka_port", "cari_chrome",
           "kandidat_chrome", "keterangan", "perintah_chrome", "tanpa_jendela"]
