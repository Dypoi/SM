"""Autentikasi & otorisasi.

Aturan login sesuai permintaan:

* **Admin/Operator**  : username + password (akun awal ``admin`` / ``admin123``).
* **Siswa**           : cukup memasukkan NISN. Zona nyaman untuk sekolah, dengan
  opsi pengaman tambahan (tanggal lahir) yang bisa dinyalakan di Pengaturan.

Sesi disimpan pada cookie bertanda tangan (itsdangerous) sehingga tidak perlu
penyimpanan sesi di server.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, Response, status

from . import config, db, services
from .security import create_session_token, read_session_token, verify_password

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_SISWA = "siswa"
ROLE_EKSKUL = "ekskul"

ROLE_LABELS = {
    ROLE_ADMIN: "Administrator",
    ROLE_OPERATOR: "Operator/Guru",
    ROLE_SISWA: "Siswa",
    ROLE_EKSKUL: "Pembina/Pelatih Ekstrakurikuler",
}

#: NIK harus tepat 16 angka (aturan Dukcapil, sesuai permintaan sekolah).
PANJANG_NIK = 16

# Path yang bisa diakses tanpa login
PUBLIC_PATHS = ("/login", "/logout", "/static", "/health", "/api/health")


@dataclass
class SessionUser:
    id: int | None
    username: str
    nama: str
    role: str
    student_id: int | None = None
    nisn: str | None = None
    rombel: str | None = None
    # Akun ekstrakurikuler (pembina/pelatih)
    ekskul_id: int | None = None
    ekskul_nama: str | None = None
    ekskul_peran: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_ekskul(self) -> bool:
        return self.role == ROLE_EKSKUL

    @property
    def halaman_ekskul(self) -> str:
        """Halaman yang boleh dibuka akun ekstrakurikuler."""
        return f"/ekstrakurikuler/{self.ekskul_id}" if self.ekskul_id else "/login"

    @property
    def is_staff(self) -> bool:
        return self.role in {ROLE_ADMIN, ROLE_OPERATOR}

    @property
    def role_label(self) -> str:
        if self.role == ROLE_EKSKUL and self.ekskul_nama:
            peran = services.PERAN_LABEL.get(self.ekskul_peran or "", "Pengurus")
            return f"{peran} {self.ekskul_nama}"
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def inisial(self) -> str:
        parts = [part for part in (self.nama or self.username).split() if part]
        return "".join(part[0].upper() for part in parts[:2]) or "?"


# --------------------------------------------------------------------------- #
# Sesi
# --------------------------------------------------------------------------- #
def _lewat_https(request: Request | None) -> bool:
    """True bila permintaan sampai ke aplikasi lewat HTTPS.

    Terowongan (Tailscale Funnel / Cloudflare) meneruskan keterangan ini pada
    header ``X-Forwarded-Proto``. Di jaringan sekolah nilainya ``http``,
    sehingga cookie sesi tidak diberi tanda ``Secure`` dan login tetap bisa.
    """
    if request is None:
        return False
    if request.url.scheme == "https":
        return True
    diteruskan = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return diteruskan == "https"


def start_session(response: Response, user: SessionUser, request: Request | None = None) -> None:
    token = create_session_token(
        {
            "uid": user.id,
            "username": user.username,
            "nama": user.nama,
            "role": user.role,
            "student_id": user.student_id,
            "nisn": user.nisn,
            "rombel": user.rombel,
            "ekskul_id": user.ekskul_id,
            "ekskul_nama": user.ekskul_nama,
            "ekskul_peran": user.ekskul_peran,
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    response.set_cookie(
        key=config.SESSION_COOKIE,
        value=token,
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_lewat_https(request),
        path="/",
    )


def end_session(response: Response) -> None:
    response.delete_cookie(config.SESSION_COOKIE, path="/")


def current_user(request: Request) -> SessionUser | None:
    token = request.cookies.get(config.SESSION_COOKIE)
    data = read_session_token(token)
    if not data:
        return None
    return SessionUser(
        id=data.get("uid"),
        username=data.get("username") or "",
        nama=data.get("nama") or data.get("username") or "",
        role=data.get("role") or ROLE_SISWA,
        student_id=data.get("student_id"),
        nisn=data.get("nisn"),
        rombel=data.get("rombel"),
        ekskul_id=data.get("ekskul_id"),
        ekskul_nama=data.get("ekskul_nama"),
        ekskul_peran=data.get("ekskul_peran"),
    )


def require_user(request: Request) -> SessionUser:
    user = current_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={request.url.path}"},
            detail="Silakan login terlebih dahulu.",
        )
    return user


def _arahkan_siswa_ke_portal() -> HTTPException:
    """Siswa yang membuka halaman petugas diarahkan ke portalnya sendiri."""
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/portal?level=info&msg=Halaman+tersebut+khusus+petugas+sekolah."},
        detail="Halaman khusus petugas sekolah.",
    )


def _arahkan_ekskul_ke_halamannya(user: SessionUser, pesan: str) -> HTTPException:
    """Akun pembina/pelatih hanya memegang ekskulnya sendiri."""
    from urllib.parse import quote_plus

    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": f"{user.halaman_ekskul}?level=info&msg={quote_plus(pesan)}"},
        detail=pesan,
    )


def require_staff(request: Request) -> SessionUser:
    user = require_user(request)
    if user.role == ROLE_SISWA:
        raise _arahkan_siswa_ke_portal()
    if user.role == ROLE_EKSKUL:
        raise _arahkan_ekskul_ke_halamannya(user, "Halaman tersebut khusus petugas sekolah.")
    if not user.is_staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak.")
    return user


def require_admin(request: Request) -> SessionUser:
    user = require_user(request)
    if user.role == ROLE_SISWA:
        raise _arahkan_siswa_ke_portal()
    if user.role == ROLE_EKSKUL:
        raise _arahkan_ekskul_ke_halamannya(user, "Halaman tersebut khusus administrator sekolah.")
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator yang boleh membuka halaman Pengaturan.",
        )
    return user


# --------------------------------------------------------------------------- #
# Pembatasan percobaan login (anti tebak NISN / kata sandi)
# --------------------------------------------------------------------------- #
@dataclass
class _CatatanPercobaan:
    gagal: int = 0
    sampai: float = 0.0


_percobaan: dict[str, _CatatanPercobaan] = {}
_percobaan_lock = threading.Lock()


def _kunci_percobaan(mode: str, identitas: str | None, ip: str | None) -> tuple[str, str]:
    akun = f"{mode}:{(identitas or '').strip().lower() or '-'}"
    return akun, f"ip:{ip or '-'}"


def _batas_ip(ip: str | None) -> int:
    from .online import dari_luar

    return config.LOGIN_MAKS_GAGAL_IP_PUBLIK if dari_luar(ip) else config.LOGIN_MAKS_GAGAL_IP_LOKAL


def _catatan_percobaan(kunci: str, sekarang: float) -> _CatatanPercobaan:
    data = _percobaan.get(kunci)
    if data is None:
        data = _CatatanPercobaan()
        _percobaan[kunci] = data
    if data.sampai and data.sampai <= sekarang:  # masa penangguhan sudah lewat
        data.gagal = 0
        data.sampai = 0.0
    return data


def tunggu_sebelum_login(mode: str, identitas: str | None, ip: str | None) -> int:
    """Sisa detik penangguhan login (0 = boleh mencoba sekarang)."""
    akun, jaringan = _kunci_percobaan(mode, identitas, ip)
    sekarang = time.monotonic()
    with _percobaan_lock:
        for kunci, batas in ((akun, config.LOGIN_MAKS_GAGAL_AKUN), (jaringan, _batas_ip(ip))):
            data = _catatan_percobaan(kunci, sekarang)
            if data.sampai > sekarang:
                return max(1, int(data.sampai - sekarang) + 1)
    return 0


def catat_login_gagal(mode: str, identitas: str | None, ip: str | None) -> None:
    """Tambah hitungan gagal; begitu melewati batas, tahan sementara."""
    akun, jaringan = _kunci_percobaan(mode, identitas, ip)
    sekarang = time.monotonic()
    with _percobaan_lock:
        for kunci, batas in ((akun, config.LOGIN_MAKS_GAGAL_AKUN), (jaringan, _batas_ip(ip))):
            data = _catatan_percobaan(kunci, sekarang)
            data.gagal += 1
            if data.gagal >= batas:
                data.sampai = sekarang + config.LOGIN_JEDA_DETIK
                data.gagal = 0


def catat_login_berhasil(mode: str, identitas: str | None, ip: str | None) -> None:
    """Bersihkan hitungan gagal setelah login berhasil."""
    akun, jaringan = _kunci_percobaan(mode, identitas, ip)
    with _percobaan_lock:
        _percobaan.pop(akun, None)
        data = _percobaan.get(jaringan)
        if data is not None:
            data.gagal = max(0, data.gagal - 1)


def ringkasan_penangguhan() -> list[dict[str, Any]]:
    """Kunci yang sedang ditangguhkan (dipakai halaman Pengaturan)."""
    sekarang = time.monotonic()
    with _percobaan_lock:
        return [
            {"kunci": kunci, "sisa_detik": int(data.sampai - sekarang) + 1}
            for kunci, data in _percobaan.items()
            if data.sampai > sekarang
        ]


def bersihkan_penangguhan() -> None:
    with _percobaan_lock:
        _percobaan.clear()


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def authenticate_staff(username: str, password: str) -> tuple[SessionUser | None, str]:
    """Login admin/operator. Mengembalikan (user, pesan_error)."""
    username = (username or "").strip()
    if not username or not password:
        return None, "Username dan kata sandi wajib diisi."

    row = db.query_one("SELECT * FROM users WHERE username = ?", (username,))
    if row is None or not verify_password(password, row["password_hash"]):
        return None, "Username atau kata sandi salah."
    if not row["aktif"]:
        return None, "Akun dinonaktifkan. Hubungi administrator."

    db.execute("UPDATE users SET last_login = datetime('now','localtime') WHERE id = ?", (row["id"],))
    user = SessionUser(
        id=row["id"], username=row["username"], nama=row["nama"] or row["username"],
        role=row["role"], student_id=row["student_id"],
    )
    services.log_audit(user.username, user.role, "login_staff", "users", row["id"])
    return user, ""


def authenticate_student(nisn: str) -> tuple[SessionUser | None, str]:
    """Login siswa dengan NISN saja."""
    nisn = (nisn or "").strip()
    if not nisn:
        return None, "NISN wajib diisi."
    if not nisn.isdigit():
        return None, "NISN hanya berisi angka."

    student = services.get_student_by_nisn(nisn)
    if student is None:
        return None, "NISN tidak terdaftar di sekolah ini."

    if student.get("status") and str(student["status"]).lower() not in {"aktif", "lulus"}:
        return None, f"Status siswa '{student['status']}' — silakan hubungi tata usaha."

    # Akun siswa otomatis tercatat di tabel users (tanpa kata sandi) agar
    # riwayat login dan pemberian hak ekstrakurikuler mudah dilacak.
    user = SessionUser(
        id=student["id"], username=nisn, nama=student["nama"], role=ROLE_SISWA,
        student_id=student["id"], nisn=nisn, rombel=student.get("rombel"),
    )
    db.execute(
        "INSERT INTO users(username, password_hash, nama, role, student_id, last_login) "
        "VALUES(?,?,?,?,?, datetime('now','localtime')) "
        "ON CONFLICT(username) DO UPDATE SET last_login = datetime('now','localtime')",
        (f"siswa:{nisn}", "", student["nama"], ROLE_SISWA, student["id"]),
    )
    services.log_audit(nisn, ROLE_SISWA, "login_siswa", "students", student["id"])
    return user, ""


# --------------------------------------------------------------------------- #
# Login ekstrakurikuler (NIK 16 digit + pilih peran & ekskul)
# --------------------------------------------------------------------------- #
def bersihkan_nik(teks: str | None) -> str:
    """Ambil angka saja dari NIK (spasi, titik, dan tanda hubung diabaikan)."""
    return "".join(karakter for karakter in (teks or "") if karakter.isdigit())


def validasi_nik(teks: str | None) -> tuple[str, str]:
    """Kembalikan (NIK bersih, pesan galat) — pesan kosong berarti sah."""
    nik = bersihkan_nik(teks)
    if not nik:
        return "", "NIK wajib diisi (16 angka sesuai KTP/KK)."
    if len(nik) != PANJANG_NIK:
        return nik, f"NIK harus tepat {PANJANG_NIK} angka — yang dimasukkan {len(nik)} angka."
    return nik, ""


def authenticate_ekskul(
    nik: str, peran: str, ekskul_id: int, nama: str = ""
) -> tuple[SessionUser | None, str, str]:
    """Masuk sebagai pembina/pelatih ekskul.

    Mengembalikan (pengguna, pesan_galat, pesan_info). Aturannya:

    * satu ekskul hanya boleh punya satu pembina dan satu pelatih;
    * posisi yang masih kosong langsung dikunci oleh NIK yang masuk pertama kali;
    * NIK yang sudah terdaftar pada posisi itu cukup masuk seperti biasa.
    """
    peran = (peran or "").strip().lower()
    if peran not in services.EKSKUL_PERAN:
        return None, "Pilih dulu apakah Anda Pembina atau Pelatih.", ""

    nik_bersih, galat = validasi_nik(nik)
    if galat:
        return None, galat, ""

    ekskul = services.get_ekskul(int(ekskul_id)) if int(ekskul_id or 0) else None
    if ekskul is None:
        return None, "Pilih ekstrakurikuler yang Anda dampingi.", ""
    if not ekskul.get("aktif"):
        return None, f"Ekstrakurikuler {ekskul['nama']} sedang nonaktif — hubungi admin sekolah.", ""

    posisi = services.akun_ekskul_posisi(int(ekskul_id), peran)
    info = ""
    if posisi is not None and posisi["nik"] != nik_bersih:
        lain = services.PERAN_LABEL.get(peran, peran)
        return (None,
                f"{lain} {ekskul['nama']} sudah terdaftar oleh NIK {posisi['nik']}. "
                "Hubungi admin sekolah bila memang perlu diganti.", "")

    if posisi is None:
        akun_id = services.klaim_akun_ekskul(int(ekskul_id), peran, nik_bersih, nama, actor=nik_bersih)
        peran_label = services.PERAN_LABEL.get(peran, peran)
        info = (f"Selamat datang! NIK Anda terdaftar sebagai {peran_label} {ekskul['nama']}. "
                "Bila ini keliru, hubungi admin sekolah untuk melepaskannya.")
    else:
        akun_id = int(posisi["id"])
        if nama:
            services.perbarui_nama_akun_ekskul(akun_id, nama)
        peran_label = services.PERAN_LABEL.get(peran, peran)
        info = f"Anda masuk sebagai {peran_label} {ekskul['nama']}."

    services.catat_login_akun_ekskul(akun_id)
    akun = services.akun_ekskul_posisi(int(ekskul_id), peran) or {}
    user = SessionUser(
        id=akun_id,
        username=f"ekskul:{akun.get('nik', nik_bersih)}",
        nama=(nama or akun.get("nama") or f"{peran_label} {ekskul['nama']}").strip(),
        role=ROLE_EKSKUL,
        ekskul_id=int(ekskul["id"]),
        ekskul_nama=ekskul["nama"],
        ekskul_peran=peran,
    )
    services.log_audit(user.username, ROLE_EKSKUL, "login_ekskul", "ekskul_akun", akun_id,
                       f"{peran_label} {ekskul['nama']}")
    return user, "", info


def student_requires_birthdate() -> bool:
    return services.get_setting("login_siswa_pakai_tanggal_lahir", "0") == "1"


def verify_student_birthdate(student: dict[str, Any], tanggal_lahir: str | None) -> bool:
    expected = (student.get("tanggal_lahir") or "").strip()
    if not expected:
        return True
    return (tanggal_lahir or "").strip() == expected


# --------------------------------------------------------------------------- #
# Manajemen pengguna
# --------------------------------------------------------------------------- #
def list_users() -> list[dict[str, Any]]:
    return db.rows_to_dicts(
        db.query_all(
            """
            SELECT u.id, u.username, u.nama, u.role, u.aktif, u.last_login, u.created_at,
                   s.nama AS siswa_nama, s.nisn AS siswa_nisn, s.rombel AS siswa_rombel
              FROM users u LEFT JOIN students s ON s.id = u.student_id
             WHERE u.role <> 'siswa'
             ORDER BY u.role, u.username COLLATE NOCASE
            """
        )
    )


def create_user(username: str, password: str, nama: str, role: str = ROLE_OPERATOR) -> int:
    from .security import hash_password

    username = (username or "").strip()
    if not username:
        raise ValueError("Username wajib diisi.")
    if len(password or "") < 5:
        raise ValueError("Kata sandi minimal 5 karakter.")
    if role not in {ROLE_ADMIN, ROLE_OPERATOR}:
        raise ValueError("Role tidak valid.")
    if db.query_one("SELECT id FROM users WHERE username = ?", (username,)):
        raise ValueError(f"Username '{username}' sudah dipakai.")
    return db.insert_returning_id(
        "INSERT INTO users(username, password_hash, nama, role) VALUES(?,?,?,?)",
        (username, hash_password(password), nama or username, role),
    )


def update_user(user_id: int, *, nama: str | None = None, role: str | None = None,
                aktif: bool | None = None, password: str | None = None) -> None:
    from .security import hash_password

    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise ValueError("Pengguna tidak ditemukan.")
    updates: dict[str, Any] = {}
    if nama is not None:
        updates["nama"] = nama
    if role in {ROLE_ADMIN, ROLE_OPERATOR}:
        updates["role"] = role
    if aktif is not None:
        if not aktif and row["role"] == ROLE_ADMIN:
            remaining = int(db.query_value("SELECT COUNT(*) FROM users WHERE role='admin' AND aktif=1 AND id<>?", (user_id,)) or 0)
            if remaining == 0:
                raise ValueError("Minimal harus ada satu admin aktif.")
        updates["aktif"] = 1 if aktif else 0
    if password:
        if len(password) < 5:
            raise ValueError("Kata sandi minimal 5 karakter.")
        updates["password_hash"] = hash_password(password)
    if not updates:
        return
    set_clause = ", ".join(f"{key} = ?" for key in updates)
    db.execute(
        f"UPDATE users SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ?",
        [*updates.values(), user_id],
    )


def delete_user(user_id: int, actor: str | None = None) -> None:
    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        return
    if row["role"] == ROLE_ADMIN:
        remaining = int(db.query_value("SELECT COUNT(*) FROM users WHERE role='admin' AND id<>?", (user_id,)) or 0)
        if remaining == 0:
            raise ValueError("Tidak bisa menghapus admin terakhir.")
    db.execute("DELETE FROM users WHERE id = ? AND role <> 'siswa'", (user_id,))
    services.log_audit(actor, None, "hapus_pengguna", "users", user_id, row["username"])


def change_password(user_id: int, old_password: str, new_password: str) -> None:
    from .security import hash_password

    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None or not verify_password(old_password, row["password_hash"]):
        raise ValueError("Kata sandi lama salah.")
    if len(new_password or "") < 5:
        raise ValueError("Kata sandi baru minimal 5 karakter.")
    db.execute(
        "UPDATE users SET password_hash = ?, updated_at = datetime('now','localtime') WHERE id = ?",
        (hash_password(new_password), user_id),
    )
