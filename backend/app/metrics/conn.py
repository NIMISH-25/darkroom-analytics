"""Connection pools for the API (db.py belongs to the ingestion worker).

* read pool: every connection is REPEATABLE READ + read-only; one request = one transaction, so the
  dataset revision and all the data in a response come from the same snapshot.
* write pool: autocommit, used only for notes.
"""
from __future__ import annotations

import contextlib
import contextvars
import re

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.settings import get_settings

DEFAULT_CUTOFF = "2026-10-15"
_cutoff_var: contextvars.ContextVar = contextvars.ContextVar("request_cutoff", default=DEFAULT_CUTOFF)
_read: ConnectionPool | None = None
_write: ConnectionPool | None = None


def _cfg_read(conn) -> None:
    conn.isolation_level = IsolationLevel.REPEATABLE_READ
    conn.read_only = True


def open_pool() -> None:
    global _read, _write
    url = get_settings().DATABASE_URL
    if _read is None:
        _read = ConnectionPool(url, min_size=2, max_size=10, open=False, configure=_cfg_read,
                               kwargs={"row_factory": dict_row, "autocommit": False})
        _read.open()
    if _write is None:
        _write = ConnectionPool(url, min_size=1, max_size=3, open=False,
                                kwargs={"row_factory": dict_row, "autocommit": True})
        _write.open()


def close_pool() -> None:
    global _read, _write
    for p in (_read, _write):
        if p is not None:
            p.close()
    _read = _write = None


def current_cutoff() -> str:
    return _cutoff_var.get()


def set_request_cutoff(value):
    """Remember the request cutoff (query param) for the snapshot opened later in this request."""
    ok = isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    return _cutoff_var.set(value if ok else DEFAULT_CUTOFF)


def _apply_cutoff(conn) -> None:
    # gold views read app.cutoff (transaction-local); must run before any gold query in the snapshot
    conn.execute("SELECT set_config('app.cutoff', %s, true)", (current_cutoff(),))


@contextlib.contextmanager
def read_conn():
    """One REPEATABLE READ read-only connection for the duration of a request."""
    if _read is not None:
        with _read.connection() as conn:
            _apply_cutoff(conn)
            yield conn
        return
    conn = psycopg.connect(get_settings().DATABASE_URL, row_factory=dict_row, autocommit=False)
    try:
        _cfg_read(conn)
        _apply_cutoff(conn)
        yield conn
    finally:
        conn.rollback()
        conn.close()


@contextlib.contextmanager
def write_conn():
    if _write is not None:
        with _write.connection() as conn:
            yield conn
        return
    with psycopg.connect(get_settings().DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def connect():
    """Context manager yielding a REPEATABLE READ read-only connection (used by charts.py)."""
    return read_conn()
