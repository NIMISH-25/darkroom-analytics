"""Sanity-check generator output against docs/source-contracts.md (no backend needed).
Run: python scripts/verify_synthetic.py   (exit 1 on any failure)
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta

from openpyxl import load_workbook

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "synthetic")
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("FAIL:", msg)


def load(p):
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


REQ = {
    "orders": ("order_id", "shop_id", "status", "create_time", "paid_time", "update_time", "is_sample_order", "payment",
               "line_items"),
    "affiliate_orders": ("affiliate_record_id", "order_id", "line_item_id", "creator_user_id", "creator_handle",
                         "content_id", "content_type", "commission_rate", "commission_amount", "commission_status",
                         "update_time"),
    "returns": ("return_id", "order_id", "line_item_id", "return_status", "refund_subtotal", "refund_tax",
                "create_time", "completed_time", "update_time"),
}
LIST_KEY = {"orders": "orders", "affiliate_orders": "records", "returns": "returns"}


def verify_batch(path, expect_bad=()):
    name = os.path.basename(path)
    man = load(os.path.join(path, "manifest.json"))
    check(set(man) >= {"batch_id", "simulated_received_at", "as_of", "files"}, f"{name}: manifest keys")
    stats = Counter()
    for f in man["files"]:
        check(set(f) >= {"path", "source_type", "brand_id", "period_start", "period_end", "kind", "src_updated_at"},
              f"{name}: manifest entry keys {f.get('path')}")
        fp = os.path.join(path, f["path"])
        check(os.path.isfile(fp), f"{name}: missing file {f['path']}")
        if not os.path.isfile(fp):
            continue
        st = f["source_type"]
        stats[st] += 1
        if st in REQ:
            rows = load(fp)[LIST_KEY[st]]
            for r in rows:
                miss = [k for k in REQ[st] if k not in r]
                if miss and f["path"] not in expect_bad:
                    check(False, f"{name}: {f['path']} missing {miss}")
                stats[st + "_rows"] += 1
        elif st == "products":
            with open(fp, encoding="utf-8-sig", newline="") as fh:
                hdr = next(csv.reader(fh))
            check(hdr == ["shop_id", "product_id", "sku_id", "product_name", "list_price", "unit_cost", "update_time"],
                  f"{name}: products header {f['path']}")
        elif st == "videos_weekly":
            wb = load_workbook(fp)
            ws = wb["Video performance"]
            vals = list(ws.iter_rows(values_only=True))
            check(len(vals) >= 4 and vals[-1][0] == "Total", f"{name}: video file Total row {f['path']}")
            check(vals[2][0] in ("Video ID", "Video Id") and "Creator ID" in vals[2], f"{name}: video header {f['path']}")
            stats["videos_weekly_rows"] += len(vals) - 4
        elif st == "roster":
            ws = load_workbook(fp)["Roster"]
            stats["roster_rows"] = ws.max_row - 1
        elif st == "samples":
            ws = load_workbook(fp)["Samples"]
            stats["samples_rows"] = ws.max_row - 1
        elif st == "plans":
            p = load(fp)
            check(len(p["goals"]) == 3, f"{name}: plans 3 goals {f['path']}")
    on_disk = sum(len(fs) for _, _, fs in os.walk(path))
    check(on_disk == len(man["files"]) + 1, f"{name}: files on disk ({on_disk}) vs manifest ({len(man['files'])}+1)")
    print(name, dict(stats), "files on disk:", on_disk)
    return man, stats


def main():
    m1, s1 = verify_batch(os.path.join(ROOT, "batch_1"))
    m2, s2 = verify_batch(os.path.join(ROOT, "batch_2"), expect_bad=("orders/verdant/2026-10-extra.json",))
    total = sum(len(fs) for _, _, fs in os.walk(ROOT))
    synth = sum(len(fs) for d in ("batch_1", "batch_2") for _, _, fs in os.walk(os.path.join(ROOT, d)))
    check(100 <= synth <= 300, f"batch_1+batch_2 file count {synth} within 100-300")
    check(2000 <= s1["orders_rows"] + s2["orders_rows"] <= 6000, "a few thousand orders")
    vids = set()
    for f in m1["files"]:
        if f["source_type"] == "videos_weekly":
            ws = load_workbook(os.path.join(ROOT, "batch_1", f["path"]))["Video performance"]
            for r in list(ws.iter_rows(values_only=True))[3:-1]:
                vids.add((f["brand_id"], r[0]))
    check(150 <= len(vids) <= 1000, f"a few hundred videos (got {len(vids)})")
    check(120 <= s2["samples_rows"] <= 200, f"~150 samples (got {s2['samples_rows']})")
    ros = load_workbook(os.path.join(ROOT, "batch_1/roster/roster.xlsx"))["Roster"]
    ids = {r[1] for r in ros.iter_rows(min_row=2, values_only=True)}
    check(60 <= len(ids) <= 100, f"60-100 creators (got {len(ids)})")
    brands = {f["brand_id"] for f in m1["files"] if f["source_type"] == "orders"}
    check(brands == {"aurelle", "verdant", "crunchwell", "threadline", "glowhaus"}, "five brands")
    # glowhaus gap: two missing weekly files
    gw = sorted(f["period_start"] for f in m1["files"] if f["source_type"] == "videos_weekly" and f["brand_id"] == "glowhaus")
    full = sorted(f["period_start"] for f in m1["files"] if f["source_type"] == "videos_weekly" and f["brand_id"] == "aurelle")
    check(len(full) - len(gw) == 2, f"glowhaus missing exactly 2 weekly files ({len(full)} vs {len(gw)})")
    # verdant quiet retainer: no video posted after Oct 2 in any file, coverage through Oct 11
    check(max(f["period_end"] for f in m1["files"] if f["source_type"] == "videos_weekly") == "2026-10-11",
          "weekly video coverage ends 2026-10-11")
    # aurelle late refund: REQUESTED in batch 1, COMPLETED in batch 2
    r1 = [r for f in m1["files"] if f["source_type"] == "returns" and f["brand_id"] == "aurelle"
          for r in load(os.path.join(ROOT, "batch_1", f["path"]))["returns"] if r["return_id"] == "RET-AU-LATE"]
    r2 = [r for f in m2["files"] if f["source_type"] == "returns" and f["brand_id"] == "aurelle"
          for r in load(os.path.join(ROOT, "batch_2", f["path"]))["returns"] if r["return_id"] == "RET-AU-LATE"]
    check([r["return_status"] for r in r1] == ["REQUESTED"] and [r["return_status"] for r in r2] == ["COMPLETED"],
          "aurelle late refund planted across batches")
    # duplicated order across two pages
    p1 = {o["order_id"] for o in load(os.path.join(ROOT, "batch_1/orders/aurelle/2026-08.json"))["orders"]}
    p2 = {o["order_id"] for o in load(os.path.join(ROOT, "batch_1/orders/aurelle/2026-08-page2.json"))["orders"]}
    check(len(p1 & p2) >= 10, "duplicate orders across pages")
    # handle change
    hs = set()
    for f in m1["files"]:
        if f["source_type"] == "affiliate_orders":
            for r in load(os.path.join(ROOT, "batch_1", f["path"]))["records"]:
                if r["creator_user_id"] == "cr_0007":
                    hs.add(r["creator_handle"])
    check(len(hs) == 2, f"creator handle change cr_0007 {hs}")
    # threadline sample states exist in raw data
    sm = load_workbook(os.path.join(ROOT, "batch_1/samples/samples.xlsx"))["Samples"]
    th = [r for r in sm.iter_rows(min_row=2, values_only=True) if r[1] == "threadline"]
    check(len(th) >= 20, "threadline samples")
    ser = [r for r in sm.iter_rows(min_row=2, values_only=True) if isinstance(r[6], int)]
    check(len(ser) >= 1, "some Excel-serial delivered dates")
    # batch 2 specifics
    check(any(f["path"] == "orders/verdant/2026-10-extra.json" for f in m2["files"]), "bad file listed in batch 2")
    hdr = load_workbook(os.path.join(ROOT, "batch_2/videos/aurelle/2026-W42.xlsx"))["Video performance"]
    check("Video Views" in [c.value for c in hdr[3]], "batch 2 renamed header")
    with open(os.path.join(ROOT, "batch_2/products/verdant.csv"), "rb") as fh:
        check(fh.read(3) == b"\xef\xbb\xbf", "batch 2 products CSV has BOM")
    # golden
    for b in ("batch_1", "batch_2", "batch_3", "batch_4_revision", "batch_overlap", "batch_allbad", "batch_older", "batch_bad"):
        verify_batch(os.path.join(ROOT, "golden_cases", b),
                     expect_bad=("orders/verdant/2026-10-extra.json", "orders/crunchwell/2026-10-allbad.json") if b in ("batch_bad", "batch_allbad") else ())
    print("total files under data/synthetic:", total, "| batch_1+batch_2:", synth)
    print("FAILURES:", len(fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
