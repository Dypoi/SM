"""Lapisan akses database SQLite (tanpa ORM, tanpa dependensi tambahan).

Dipilih SQLite + SQL langsung agar:
* benar-benar ringan (satu berkas, tidak perlu server database),
* mudah dibackup/dipindah antar sekolah,
* query dataset besar (impor 1000+ siswa) tetap cepat.

Koneksi disimpan per-thread supaya aman dipakai dari threadpool FastAPI.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import config

_local = threading.local()
_write_lock = threading.RLock()


def _connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(
        str(config.DB_PATH),
        timeout=30.0,
        isolation_level=None,  # autocommit; transaksi dikelola manual
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def connection() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _local.conn = _connect()
    return conn


def close_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


# --------------------------------------------------------------------------- #
# Query helper
# --------------------------------------------------------------------------- #
def query_all(sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> list[sqlite3.Row]:
    return list(connection().execute(sql, params))


def query_one(sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> sqlite3.Row | None:
    return connection().execute(sql, params).fetchone()


def query_value(sql: str, params: Sequence[Any] | Mapping[str, Any] = (), default: Any = None) -> Any:
    row = query_one(sql, params)
    if row is None or len(row) == 0:
        return default
    value = row[0]
    return default if value is None else value


def execute(sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> sqlite3.Cursor:
    with _write_lock:
        return connection().execute(sql, params)


def execute_many(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    with _write_lock:
        connection().executemany(sql, list(seq))


def insert_returning_id(sql: str, params: Sequence[Any] = ()) -> int:
    cursor = execute(sql, params)
    return int(cursor.lastrowid or 0)


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Transaksi tulis. ``BEGIN IMMEDIATE`` mengurangi risiko database locked."""
    conn = connection()
    with _write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def table_columns(table: str) -> list[str]:
    rows = query_all(f"PRAGMA table_info({table})")
    return [row["name"] for row in rows]


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Ubah satu baris menjadi dict; ``None`` bila barisnya tidak ada.

    Penting: pemanggil memeriksa hasil ini dengan ``is None`` untuk membedakan
    "data tidak ditemukan" dari "data kosong".
    """
    return None if row is None else dict(row)


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
