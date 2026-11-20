"""Titik masuk **Vercel** untuk aplikasi SM.

Vercel mencari *instance* FastAPI bernama ``app`` di salah satu titik masuk yang dikenali
(``api/index.py`` termasuk di dalamnya). Berkas ini disengaja **sangat tipis**: seluruh isi
aplikasi tetap berada di ``app/``, sedangkan pengaturan khusus serverless dilakukan di
``app/config.py`` (mode Vercel) supaya tetap berlaku walau Vercel memilih ``app/main.py``
sebagai titik masuk.

Yang berubah di mode Vercel (lihat juga ``PANDUAN-VERCEL.md``):

* **folder data** dipindah ke ``/tmp`` — di Vercel hanya ``/tmp`` yang bisa ditulis, dan
  isinya **tidak permanen**;
* **pembaruan lewat git** dimatikan (di serverless tidak ada repo/git);
* **data contoh & 14 ekskul resmi** tidak diisi otomatis — aplikasi mulai kosong;
* **Bot Dapodik** tidak bisa dijalankan (butuh Chrome & proses panjang) dan aplikasinya
  menjelaskannya di halaman Bot Dapodik.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Akar proyek ada satu tingkat di atas folder ``api/``.
AKAR = Path(__file__).resolve().parent.parent
if str(AKAR) not in sys.path:
    sys.path.insert(0, str(AKAR))

# Serverless: jangan impor berkas contoh, jangan isi ekskul, jangan sentuh git.
os.environ.setdefault("SM_AUTO_SEED", "0")
os.environ.setdefault("SM_EKSKUL_SEKOLAH", "0")
os.environ.setdefault("SM_GIT_UPDATE", "0")

from app.main import app  # noqa: E402,F401  (Vercel membaca variabel bernama `app`)
