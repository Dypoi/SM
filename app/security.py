"""Keamanan: hashing kata sandi, sesi berbasis cookie, kunci API.

Sengaja memakai ``hashlib.pbkdf2_hmac`` (pustaka standar) supaya tidak ada
dependensi native yang menyulitkan instalasi di komputer sekolah.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config

_ALGO = "pbkdf2_sha256"


# --------------------------------------------------------------------------- #
# Kata sandi
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, rounds: int | None = None) -> str:
    rounds = rounds or config.PBKDF2_ROUNDS
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds)
    return f"{_ALGO}${rounds}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, rounds_text, salt, expected = stored.split("$", 3)
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(rounds_text)
    )
    return hmac.compare_digest(digest.hex(), expected)


def new_api_key(prefix: str = "smk") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


# --------------------------------------------------------------------------- #
# Sesi (cookie bertanda tangan)
# --------------------------------------------------------------------------- #
_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="sm-session")


def create_session_token(payload: dict[str, Any]) -> str:
    data = dict(payload)
    data.setdefault("iat", int(time.time()))
    return _serializer.dumps(data)


def read_session_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=config.SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


# --------------------------------------------------------------------------- #
# Utilitas umum
# --------------------------------------------------------------------------- #
def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")


def mask_nik(value: str | None) -> str:
    """Sembunyikan sebagian NIK/No. KK untuk tampilan (privasi)."""
    if not value:
        return ""
    text = str(value)
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:6]}{'*' * (len(text) - 10)}{text[-4:]}"
