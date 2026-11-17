"""Shared writers for the synthetic data generator (no dependency on backend/app)."""
from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from openpyxl import Workbook

PT = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")
FIXED_ZIP_TIME = (2026, 10, 15, 0, 0, 0)

BRANDS = [
    ("aurelle", "Aurelle Jewelry", "jewelry"),
    ("verdant", "Verdant Skincare", "skincare"),
    ("crunchwell", "Crunchwell Snacks", "snacks"),
    ("threadline", "Threadline Apparel", "apparel"),
    ("glowhaus", "Glowhaus Beauty", "beauty"),
]

VIDEO_HEADER_V1 = ["Video ID", "Creator ID", "Creator Handle", "Post Time", "Product ID", "Views", "GMV", "Items Sold"]
VIDEO_HEADER_V2 = ["Video Id", "Creator ID", "Creator Handle", "Post Time", "Product ID", "Video Views",
                   "Gross Merchandise Value", "Items Sold"]


def unix(local_naive: datetime) -> int:
    """Pacific local wall-clock -> unix seconds UTC."""
    return int(local_naive.replace(tzinfo=PT).timestamp())


def iso_z(dt_utc: datetime) -> str:
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def money(x) -> str:
    return str(Decimal(x).quantize(Decimal("0.01")))


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def iso_week_label(monday: date) -> str:
    y, w, _ = monday.isocalendar()
    return f"{y}-W{w:02d}"


def ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def write_json(path: str, obj) -> None:
    ensure_dir(path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1, sort_keys=False)
        f.write("\n")


def write_csv_text(path: str, header: list, rows: list, bom: bool = False) -> None:
    ensure_dir(path)
    lines = [",".join(header)]
    for r in rows:
        cells = []
        for c in r:
            s = "" if c is None else str(c)
            if "," in s or '"' in s:
                s = '"' + s.replace('"', '""') + '"'
            cells.append(s)
        lines.append(",".join(cells))
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n" if bom else "\n".join(lines) + "\n")


def _normalize_zip(path: str) -> None:
    """Rewrite an xlsx with fixed zip timestamps so the bytes are reproducible."""
    with open(path, "rb") as f:
        src = zipfile.ZipFile(io.BytesIO(f.read()))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for name in sorted(src.namelist()):
            zi = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            data = src.read(name)
            if name == "docProps/core.xml":
                import re
                data = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                              rb"\g<1>2026-10-15T00:00:00Z\g<2>", data)
            out.writestr(zi, data)
    with open(path, "wb") as f:
        f.write(buf.getvalue())


def save_wb(wb: Workbook, path: str) -> None:
    ensure_dir(path)
    wb.properties.created = datetime(2026, 10, 15)
    wb.properties.modified = datetime(2026, 10, 15)
    wb.properties.creator = "synthetic"
    wb.save(path)
    _normalize_zip(path)


def write_video_xlsx(path: str, brand_name: str, week_label: str, start: date, end: date,
                     header: list, rows: list) -> None:
    """Rows 1-2 title/period text, row 3 header, data, final Total row (must be skipped by ingestion)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Video performance"
    ws.append([f"Video performance - {brand_name} - {week_label}"])
    ws.append([f"Period: {start.isoformat()} to {end.isoformat()} (metrics for this week only)"])
    ws.append(header)
    tv = tg = ti = 0
    for r in rows:
        ws.append(r)
        tv += r[5]
        tg += Decimal(str(r[6]))
        ti += r[7]
    ws.append(["Total", None, None, None, None, tv, float(tg), ti])
    save_wb(wb, path)


class Manifest:
    def __init__(self, batch_id: str, received_at: str, as_of: str):
        self.d = {"batch_id": batch_id, "simulated_received_at": received_at, "as_of": as_of, "files": []}

    def add(self, path, source_type, brand_id, start, end, kind, src_updated_at):
        self.d["files"].append({
            "path": path.replace("\\", "/"), "source_type": source_type, "brand_id": brand_id,
            "period_start": start, "period_end": end, "kind": kind, "src_updated_at": src_updated_at,
        })

    def write(self, root: str) -> None:
        write_json(os.path.join(root, "manifest.json"), self.d)


def make_line(line_id, product_id, sku_id, sale, original, seller="0.00", platform="0.00", display_status="DELIVERED"):
    return {"id": line_id, "product_id": product_id, "sku_id": sku_id, "sale_price": money(sale),
            "original_price": money(original), "seller_discount": money(seller),
            "platform_discount": money(platform), "display_status": display_status}


def make_order(order_id, shop_id, status, create_local, paid_local, update_local, lines, is_sample=False):
    """All *_local are naive Pacific datetimes (or None for paid_local)."""
    sub = sum((Decimal(l["sale_price"]) for l in lines), Decimal("0"))
    return {
        "order_id": order_id, "shop_id": shop_id, "status": status,
        "create_time": unix(create_local),
        "paid_time": unix(paid_local) if paid_local else None,
        "update_time": unix(update_local),
        "is_sample_order": is_sample,
        "payment": {"currency": "USD", "sub_total": money(sub)},
        "line_items": lines,
    }


def make_aff(rec_id, order_id, line_id, creator_id, handle, content_id, content_type, rate, amount,
             status, update_local):
    return {"affiliate_record_id": rec_id, "order_id": order_id, "line_item_id": line_id,
            "creator_user_id": creator_id, "creator_handle": handle, "content_id": content_id,
            "content_type": content_type, "commission_rate": rate, "commission_amount": money(amount),
            "commission_status": status, "update_time": unix(update_local)}


def make_return(return_id, order_id, line_id, status, refund, create_local, completed_local, update_local):
    return {"return_id": return_id, "order_id": order_id, "line_item_id": line_id, "return_status": status,
            "refund_subtotal": None if refund is None else money(refund),
            "refund_tax": None if refund is None else "0.00",
            "create_time": unix(create_local),
            "completed_time": unix(completed_local) if completed_local else None,
            "update_time": unix(update_local)}


def write_roster_xlsx(path, rows):
    cols = ["brand_id", "creator_id", "handle", "contract_type", "monthly_retainer", "posts_per_month",
            "effective_from", "effective_to", "status", "allocation_share"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Roster"
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    save_wb(wb, path)


def write_samples_xlsx(path, rows):
    cols = ["shipment_id", "brand_id", "creator_id", "product_id", "qty", "shipped_date", "delivered_date",
            "status_text", "shipping_cost", "linked_video_id"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Samples"
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    save_wb(wb, path)


def excel_serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days
