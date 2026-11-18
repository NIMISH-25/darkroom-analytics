"""Parse source files (JSON / CSV / XLSX) into bronze records, one record per source row.

Outcome of parsing a file: accepted | quarantined (unknown header) | rejected (invalid / missing required field).
Bronze keeps original values (unparsed) plus unknown extra columns.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PARSER_VERSION = "p1"
ALIASES_PATH = Path(__file__).with_name("header_aliases.yaml")

TABULAR = {"videos_weekly", "products", "roster", "samples"}
SHEETS = {"videos_weekly": "Video performance", "roster": "Roster", "samples": "Samples"}
HEADER_ROW = {"videos_weekly": 3, "roster": 1, "samples": 1}
REQUIRED_COLS = {
    "videos_weekly": ["video_id", "creator_id", "post_time", "product_id", "views", "gmv", "items_sold"],
    "products": ["shop_id", "product_id", "product_name"],
    "roster": ["brand_id", "creator_id", "contract_type"],
    "samples": ["shipment_id", "brand_id", "creator_id", "product_id"],
}
# row-level required (non-blank) canonical values for tabular sources
REQUIRED_VALUES = {
    "videos_weekly": ["video_id"],
    "products": ["shop_id", "product_id"],
    "roster": ["brand_id", "creator_id"],
    "samples": ["shipment_id", "brand_id", "product_id"],
}
JSON_COLLECTION = {"orders": "orders", "affiliate_orders": "records", "returns": "returns"}
JSON_REQUIRED = {
    "orders": ["order_id", "shop_id", "status", "create_time", "update_time", "line_items"],
    "affiliate_orders": ["affiliate_record_id", "order_id", "line_item_id", "content_type",
                         "commission_status", "update_time"],
    "returns": ["return_id", "order_id", "line_item_id", "return_status", "update_time"],
}
LINE_REQUIRED = ["id", "product_id"]
MONEY_KEYS = {
    "orders": [],
    "affiliate_orders": ["commission_amount", "commission_rate"],
    "returns": ["refund_subtotal", "refund_tax"],
}
TIME_KEYS = {
    "orders": ["create_time", "paid_time", "update_time"],
    "affiliate_orders": ["update_time"],
    "returns": ["create_time", "completed_time", "update_time"],
}


@dataclass
class Parsed:
    status: str = "accepted"  # accepted | quarantined | rejected
    error: str | None = None
    records: list[tuple[int, dict]] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)
    unknown_headers: list[str] = field(default_factory=list)
    # rows left out on their own: (row_num, reason_code, detail); the file stays accepted
    excluded: list[tuple[int, str, str]] = field(default_factory=list)
    rows_total: int = 0


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def row_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def norm_header(h: Any) -> str:
    s = str(h if h is not None else "").replace("﻿", "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


@lru_cache(maxsize=1)
def load_aliases() -> dict[str, dict[str, str]]:
    """source_type -> {normalized alias -> canonical column}."""
    raw = yaml.safe_load(ALIASES_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for st, cols in raw.items():
        m: dict[str, str] = {}
        for canon, aliases in cols.items():
            m[norm_header(canon)] = canon
            for a in aliases:
                m[norm_header(a)] = canon
        out[st] = m
    return out


def map_headers(source_type: str, headers: list[str]) -> tuple[dict[str, str], list[str], list[str]]:
    """Returns (raw header -> canonical, unknown raw headers, missing required canonical columns)."""
    amap = load_aliases()[source_type]
    mapping: dict[str, str] = {}
    unknown: list[str] = []
    for h in headers:
        c = amap.get(norm_header(h))
        if c is None:
            unknown.append(h)
        else:
            mapping[h] = c
    missing = [c for c in REQUIRED_COLS[source_type] if c not in mapping.values()]
    return mapping, unknown, missing


def canonicalize(source_type: str, payload: dict) -> dict:
    """Map a tabular bronze payload to canonical column names (unknown columns dropped)."""
    amap = load_aliases()[source_type]
    out: dict = {}
    for k, v in payload.items():
        c = amap.get(norm_header(k))
        if c is not None and c not in out:
            out[c] = v
    return out


def _jsonable(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _check_money(v: Any) -> bool:
    if _blank(v):
        return True
    try:
        return Decimal(str(v).strip()).is_finite()
    except InvalidOperation:
        return False


def _check_time(v: Any) -> bool:
    if v is None:
        return True
    try:
        float(v)
        return not isinstance(v, bool)
    except (TypeError, ValueError):
        return False


def _parse_json(source_type: str, data: bytes) -> Parsed:
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return Parsed("rejected", f"invalid JSON: {e}")
    if source_type == "plans":
        return _parse_plans(doc)
    key = JSON_COLLECTION[source_type]
    rows = doc.get(key) if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return Parsed("rejected", f"missing top-level list '{key}'")
    out = Parsed()
    out.rows_total = len(rows)
    for i, rec in enumerate(rows, start=1):
        bad = _json_row_problem(source_type, key, i, rec)
        if bad:
            out.excluded.append((i, bad[0], bad[1]))
            continue
        out.records.append((i, rec))
    if rows and not out.records:
        return Parsed("rejected", f"no usable rows: all {len(rows)} rows have problems (first: {out.excluded[0][2]})",
                      excluded=out.excluded, rows_total=len(rows))
    return out


def _json_row_problem(source_type: str, key: str, i: int, rec: Any) -> tuple[str, str] | None:
    """Reason (code, detail) why one JSON row must be left out, or None when it is usable."""
    if not isinstance(rec, dict):
        return ("not_an_object", f"{key}[{i}] is not an object")
    for k in JSON_REQUIRED[source_type]:
        if k not in rec or rec[k] is None or (isinstance(rec[k], str) and not rec[k].strip()):
            return ("missing_identifier", f"{key}[{i}] missing required field '{k}'")
    for k in MONEY_KEYS[source_type]:
        if not _check_money(rec.get(k)):
            return ("invalid_amount", f"{key}[{i}] invalid amount in '{k}': {rec.get(k)!r}")
    for k in TIME_KEYS[source_type]:
        if not _check_time(rec.get(k)):
            return ("invalid_timestamp", f"{key}[{i}] invalid timestamp in '{k}': {rec.get(k)!r}")
    if source_type == "orders":
        if not isinstance(rec["line_items"], list):
            return ("bad_line_item", f"{key}[{i}] line_items is not a list")
        for j, li in enumerate(rec["line_items"], start=1):
            for k in LINE_REQUIRED:
                if not isinstance(li, dict) or li.get(k) in (None, ""):
                    return ("bad_line_item", f"{key}[{i}].line_items[{j}] missing required field '{k}'")
            if not _check_money(li.get("sale_price")):
                return ("invalid_amount", f"{key}[{i}].line_items[{j}] invalid sale_price {li.get('sale_price')!r}")
    return None


def _parse_plans(doc: Any) -> Parsed:
    if not isinstance(doc, dict) or not doc.get("brand_id") or not doc.get("month") \
            or not isinstance(doc.get("goals"), list):
        return Parsed("rejected", "plans file needs brand_id, month and goals[]")
    out = Parsed()
    for i, g in enumerate(doc["goals"], start=1):
        for k in ("metric_key", "scope", "basis", "target"):
            if not isinstance(g, dict) or g.get(k) is None:
                return Parsed("rejected", f"goals[{i}] missing required field '{k}'")
        if not _check_money(g["target"]):
            return Parsed("rejected", f"goals[{i}] invalid target {g['target']!r}")
        out.records.append((i, {"brand_id": doc["brand_id"], "month": doc["month"], **g}))
    return out


def _finish_tabular(source_type: str, headers: list[str], rows: list[tuple[int, list]]) -> Parsed:
    clean = [h for h in headers]
    if len(set(norm_header(h) for h in clean if not _blank(h))) != len([h for h in clean if not _blank(h)]):
        return Parsed("rejected", "duplicate column headers", headers=headers)
    hdrs = [str(h) if h is not None else "" for h in headers]
    mapping, unknown, missing = map_headers(source_type, [h for h in hdrs if h])
    if missing and unknown:
        return Parsed("quarantined", f"unknown header(s) {unknown}; required column(s) {missing} not found",
                      headers=hdrs, mapping=mapping, unknown_headers=unknown)
    if missing:
        return Parsed("rejected", f"missing required column(s) {missing}", headers=hdrs, mapping=mapping)
    out = Parsed(headers=hdrs, mapping=mapping, unknown_headers=unknown)
    for rn, vals in rows:
        payload = {h: _jsonable(vals[i]) if i < len(vals) else None for i, h in enumerate(hdrs) if h}
        if all(_blank(v) for v in payload.values()):
            continue
        canon = canonicalize(source_type, payload)
        if source_type == "videos_weekly" and any(
                isinstance(v, str) and v.strip().lower() == "total" for v in list(payload.values())[:2]):
            continue
        problem = None
        for k in REQUIRED_VALUES[source_type]:
            if _blank(canon.get(k)):
                problem = ("missing_identifier", f"row {rn} missing required value '{k}'")
                break
        if problem is None:
            for k in ("views", "gmv", "items_sold", "list_price", "unit_cost", "shipping_cost", "qty",
                      "monthly_retainer", "posts_per_month", "allocation_share"):
                if k in canon and not _check_money(canon[k]):
                    problem = ("invalid_amount", f"row {rn} invalid number in '{k}': {canon[k]!r}")
                    break
        out.rows_total += 1
        if problem:
            out.excluded.append((rn, problem[0], problem[1]))
            continue
        out.records.append((rn, payload))
    if out.rows_total and not out.records:
        return Parsed("rejected", f"no usable rows: all {out.rows_total} rows have problems (first: {out.excluded[0][2]})",
                      headers=hdrs, mapping=mapping, excluded=out.excluded, rows_total=out.rows_total)
    return out


def _parse_csv(source_type: str, data: bytes) -> Parsed:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        return Parsed("rejected", f"not UTF-8: {e}")
    rd = csv.reader(io.StringIO(text, newline=""))
    allrows = list(rd)
    if not allrows:
        return Parsed("rejected", "empty file")
    headers = [h.replace("﻿", "") for h in allrows[0]]
    rows = [(i, r) for i, r in enumerate(allrows[1:], start=2)]
    return _finish_tabular(source_type, headers, rows)


def _parse_xlsx(source_type: str, data: bytes) -> Parsed:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - any corrupt workbook is a rejection
        return Parsed("rejected", f"unreadable workbook: {e}")
    sheet = SHEETS[source_type]
    if sheet not in wb.sheetnames:
        return Parsed("rejected", f"missing sheet '{sheet}'")
    ws = wb[sheet]
    hr = HEADER_ROW[source_type]
    headers: list = []
    rows: list[tuple[int, list]] = []
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i < hr:
            continue
        if i == hr:
            headers = list(row)
            while headers and _blank(headers[-1]):
                headers.pop()
            continue
        rows.append((i, list(row)))
    if not headers:
        return Parsed("rejected", "header row not found")
    return _finish_tabular(source_type, headers, rows)


def parse_file(source_type: str, path: Path, data: bytes) -> Parsed:
    """Parse bytes of a file for a source type. Never raises for bad content."""
    try:
        ext = path.suffix.lower()
        if source_type in ("orders", "affiliate_orders", "returns", "plans"):
            return _parse_json(source_type, data) if ext == ".json" else Parsed("rejected", f"expected .json, got {ext}")
        if source_type == "products":
            return _parse_csv(source_type, data) if ext == ".csv" else Parsed("rejected", f"expected .csv, got {ext}")
        if ext == ".csv":
            return _parse_csv(source_type, data)
        if ext == ".xlsx":
            return _parse_xlsx(source_type, data)
        return Parsed("rejected", f"unsupported file type {ext}")
    except Exception as e:  # noqa: BLE001
        return Parsed("rejected", f"parse error: {type(e).__name__}: {e}")
