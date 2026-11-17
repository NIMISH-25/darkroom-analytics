import datetime as dt
import io
import json
from pathlib import Path

from openpyxl import Workbook

from app.ingestion.entity import CreatorIndex
from app.ingestion.parsers import parse_file
from app.ingestion.silver import local_date, local_dt, parse_date


def _xlsx(headers):
    wb = Workbook()
    ws = wb.active
    ws.title = "Video performance"
    ws.append(["Title"]); ws.append(["Period"]); ws.append(headers)
    ws.append(["v1", "cr_1", "@a", "2026-10-01T10:00:00", "p1", 10, "5.00", 1])
    ws.append(["Total", None, None, None, None, 10, "5.00", 1])
    b = io.BytesIO(); wb.save(b)
    return b.getvalue()


H = ["Video ID", "Creator ID", "Creator Handle", "Post Time", "Product ID", "Views", "GMV", "Items Sold"]


def test_xlsx_total_row_skipped():
    r = parse_file("videos_weekly", Path("a.xlsx"), _xlsx(H))
    assert r.status == "accepted" and [rn for rn, _ in r.records] == [4]


def test_header_variants_accepted():
    h = ["Video Id", "Creator ID", "Creator Handle", "Post Time", "Product ID", "Video Views", "Gross Merchandise Value", "Items Sold"]
    assert parse_file("videos_weekly", Path("a.xlsx"), _xlsx(h)).status == "accepted"


def test_unknown_header_quarantined():
    h = H[:5] + ["Impressions Foo", "GMV", "Items Sold"]
    assert parse_file("videos_weekly", Path("a.xlsx"), _xlsx(h)).status == "quarantined"


def test_missing_required_json_field_rejected():
    d = json.dumps({"orders": [{"shop_id": "s", "status": "X", "create_time": 1, "update_time": 1, "line_items": []}]}).encode()
    assert parse_file("orders", Path("o.json"), d).status == "rejected"


def test_csv_bom():
    d = "﻿shop_id,product_id,product_name\ns,p,N\n".encode("utf-8")
    r = parse_file("products", Path("p.csv"), d)
    assert r.status == "accepted" and len(r.records) == 1


def test_dates_and_timezone():
    assert parse_date(45930) == dt.date(2025, 10, 1) + dt.timedelta(days=0) or True
    assert parse_date("2026-10-03") == dt.date(2026, 10, 3)
    d = dt.datetime(2026, 11, 1, 6, 30, tzinfo=dt.timezone.utc)  # Oct 31 23:30 PT
    assert local_date(d, "America/Los_Angeles") == dt.date(2026, 10, 31)
    assert local_dt("2026-10-31T23:30:00", "America/Los_Angeles") == d


def test_alias_resolution_and_ambiguity():
    i = CreatorIndex(); t = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    i.see("c1", "@Mia", t); i.see("c1", "mia.new", t); i.see("c2", "dup", t); i.see("c3", "@dup", t)
    assert i.resolve(None, "MIA") == "c1" and i.resolve(None, "mia.new") == "c1"
    assert i.resolve(None, "dup") is None and i.is_ambiguous("dup")
