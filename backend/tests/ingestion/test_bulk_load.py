"""Bulk loader tests. DB tests run inside a transaction that is always rolled back (no persistent writes)."""
import datetime as dt
import os

import psycopg
import pytest

from app import db
from app.ingestion.batch import _State
from app.ingestion.silver import load_table, primary_keys

URL = os.environ.get("DATABASE_URL") or "postgresql://darkroom:darkroom@localhost:5432/darkroom"


@pytest.fixture()
def conn():
    try:
        c = psycopg.connect(URL)
    except Exception:  # noqa: BLE001
        pytest.skip("database not available")
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def test_default_port_is_5432():
    assert ":5432/" in db.DEFAULT_URL


def test_overlap_detection():
    st = _State.__new__(_State)
    st.weekly = {"aurelle": [(7, dt.date(2026, 10, 1), dt.date(2026, 10, 7))]}
    assert st.overlap("aurelle", dt.date(2026, 10, 7), dt.date(2026, 10, 13)) == (7, dt.date(2026, 10, 1), dt.date(2026, 10, 7))
    assert st.overlap("aurelle", dt.date(2026, 10, 8), dt.date(2026, 10, 14)) is None
    assert st.overlap("verdant", dt.date(2026, 10, 1), dt.date(2026, 10, 7)) is None


def test_load_table_newest_src_updated_at_wins(conn):
    cols = ["shop_id", "order_id", "status", "is_sample", "src_updated_at", "source_file_id", "row_num", "row_hash"]
    old, new = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc)
    rows = [("zz_shop", "o1", "OLD", False, old, 1, 1, "h1"), ("zz_shop", "o1", "NEW", False, new, 2, 1, "h2"),
            ("zz_shop", "o2", "ONLY", False, old, 1, 2, "h3")]
    pk = primary_keys(conn)["shop_order"]
    assert pk == ["shop_id", "order_id"]
    load_table(conn, "shop_order", cols, rows, pk)
    got = dict(conn.execute("select order_id, status from silver.shop_order where shop_id='zz_shop'").fetchall())
    assert got == {"o1": "NEW", "o2": "ONLY"}


def test_load_table_empty_is_noop(conn):
    load_table(conn, "shop_order", ["shop_id"], [], ["shop_id"])
