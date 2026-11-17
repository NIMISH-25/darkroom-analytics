"""CLI: python -m app.cli migrate | ingest <batch_dir> | profile <batch_dir> | reset"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db


def _warm() -> None:
    """Prime the API cache after a successful ingest, if the API package provides it."""
    try:
        from app.metrics.cache import warm
    except ImportError:
        return
    try:
        warm()
    except Exception as e:  # noqa: BLE001
        print(f"cache warm skipped: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    rp = sub.add_parser("reset")
    rp.add_argument("--purge-notes", action="store_true", help="also drop app.creator_note")
    for c in ("ingest", "profile"):
        sp = sub.add_parser(c)
        sp.add_argument("batch_dir")
    a = ap.parse_args(argv)
    if a.cmd == "profile":
        from .ingestion.profile import profile_batch
        print(profile_batch(Path(a.batch_dir)))
        return 0
    try:
        conn = db.connect()
    except Exception as e:  # noqa: BLE001
        print(f"cannot connect to database ({db.database_url().split('@')[-1]}): {e}", file=sys.stderr)
        return 2
    with conn:
        if a.cmd == "migrate":
            done = db.migrate(conn)
            print("applied: " + (", ".join(done) if done else "nothing (up to date)"))
            return 0
        if a.cmd == "reset":
            db.reset(conn, purge_notes=a.purge_notes)
            print("applied: " + ", ".join(db.migrate(conn)))
            return 0
        db.migrate(conn)
        from .ingestion.batch import ingest_batch
        rep = ingest_batch(conn, Path(a.batch_dir))
        print(rep.render())
        _warm()
        return 1 if rep.rejected else 0


if __name__ == "__main__":
    sys.exit(main())
