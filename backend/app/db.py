"""Database helpers for the ingestion side (psycopg 3, plain SQL)."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg

DEFAULT_URL = "postgresql://darkroom:darkroom@localhost:5432/darkroom"
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"


def _dotenv_url() -> str | None:
    for p in (Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"):
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or _dotenv_url() or DEFAULT_URL


def connect(autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(database_url(), autocommit=autocommit)


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply pending SQL migrations in order. Returns the names applied."""
    applied: list[str] = []
    with conn.transaction():
        conn.execute("create schema if not exists meta")
        conn.execute(
            "create table if not exists meta.schema_migration "
            "(name text primary key, applied_at timestamptz not null default now())"
        )
    done = {r[0] for r in conn.execute("select name from meta.schema_migration")}
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if f.name in done:
            continue
        with conn.transaction():
            conn.execute(f.read_text(encoding="utf-8"))
            conn.execute("insert into meta.schema_migration(name) values (%s)", (f.name,))
        applied.append(f.name)
    return applied


def reset(conn: psycopg.Connection, purge_notes: bool = False) -> None:
    """Drop the pipeline schemas. app.creator_note survives unless purge_notes is set."""
    with conn.transaction():
        for s in ("gold", "silver", "bronze", "meta"):
            conn.execute(f"drop schema if exists {s} cascade")
        if purge_notes:
            conn.execute("drop table if exists app.creator_note cascade")
