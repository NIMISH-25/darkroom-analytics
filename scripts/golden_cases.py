"""Tiny hand-checkable fixture: data/synthetic/golden_cases/{batch_1,batch_2,batch_older,batch_bad}.

Expected values are hand-written in tests/golden/expected.yaml (never produced by this script).
Layout notes (see data/README.md):
  * batch_1  as_of 2026-10-15 (coverage through Oct 14 for orders; weekly videos through Oct 11)
  * batch_2  as_of 2026-11-02 (increments Oct 15 .. Nov 1; weekly videos W42, W43)
  * batch_older  an OLDER version of one crunchwell order (src_updated_at earlier than batch_1)
  * batch_bad    one good file + one file missing the required field order_id
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from synth_common import (
    Manifest, VIDEO_HEADER_V1, VIDEO_HEADER_V2, excel_serial, iso_week_label, make_aff, make_line,
    make_order, make_return, write_csv_text, write_json, write_roster_xlsx, write_samples_xlsx,
    write_video_xlsx,
)

SHOP = {b: f"shop_{b}" for b in ("aurelle", "verdant", "crunchwell", "threadline", "glowhaus")}
NAMES = {"aurelle": "Aurelle Jewelry", "verdant": "Verdant Skincare", "crunchwell": "Crunchwell Snacks",
         "threadline": "Threadline Apparel", "glowhaus": "Glowhaus Beauty"}
PRODUCTS = {"aurelle": [("P_A1", "S_A1", "Gold Hoop Earrings", "100.00", "30.00")],
            "verdant": [("P_V1", "S_V1", "Vitamin C Serum", "50.00", "12.00")],
            "crunchwell": [("P_C1", "S_C1", "Crunch Box", "45.00", "15.00")],
            "threadline": [("P_T1", "S_T1", "Linen Shirt", "60.00", "20.00"),
                           ("P_T2", "S_T2", "Denim Jacket", "90.00", "30.00")],
            "glowhaus": [("P_G1", "S_G1", "Glow Palette", "40.00", "10.00")]}
D = datetime


def _order(brand, oid, paid, amount, update, product="P_{}1", status="DELIVERED"):
    pid = PRODUCTS[brand][0][0]
    sku = PRODUCTS[brand][0][1]
    line = make_line(f"L_{oid[2:]}_1", pid, sku, amount, amount, display_status=status)
    return make_order(oid, SHOP[brand], status, paid - timedelta(minutes=5), paid, update, [line])


def _weeks(start: date, end: date):
    d = start
    while d <= end:
        yield d, d + timedelta(days=6)
        d += timedelta(days=7)


def build(root: str) -> None:
    gc = os.path.join(root, "golden_cases")

    # ---------------------------------------------------------------- batch_1
    b1 = os.path.join(gc, "batch_1")
    m = Manifest("batch_1", "2026-10-15T23:59:59-07:00", "2026-10-15")
    SRC1 = "2026-10-15T07:00:00Z"
    P1 = ("2026-10-01", "2026-10-14")

    def inc(man, base, path, st, brand, period, payload, src):
        write_json(os.path.join(base, path), payload)
        man.add(path, st, brand, period[0], period[1], "increment", src)

    # Brand A (aurelle): one $100 attributed item, duplicate copy on "page 2".
    oa1 = _order("aurelle", "O_A1", D(2026, 10, 5, 12, 0), "100.00", D(2026, 10, 8, 9, 0))
    sample_line = make_line("L_AS_1", "P_A1", "S_A1", "0.00", "0.00", display_status="DELIVERED")
    osamp = make_order("O_ASAMPLE", SHOP["aurelle"], "DELIVERED", D(2026, 10, 3, 9, 55), D(2026, 10, 3, 10, 0),
                       D(2026, 10, 6, 9, 0), [sample_line], is_sample=True)
    inc(m, b1, "orders/aurelle/2026-10.json", "orders", "aurelle", P1, {"orders": [oa1, osamp]}, SRC1)
    inc(m, b1, "orders/aurelle/2026-10-page2.json", "orders", "aurelle", P1, {"orders": [oa1]}, SRC1)
    a1 = make_aff("AR_A1", "O_A1", "L_O_A1_1".replace("L_O_A1_1", "L_A1_1"), "cr_0001", "@golden.mia", "V_A1",
                  "video", "0.12", "12.00", "pending", D(2026, 10, 8, 9, 0))
    inc(m, b1, "affiliate_orders/aurelle/2026-10.json", "affiliate_orders", "aurelle", P1, {"records": [a1]}, SRC1)
    inc(m, b1, "affiliate_orders/aurelle/2026-10-page2.json", "affiliate_orders", "aurelle", P1,
        {"records": [a1]}, SRC1)
    inc(m, b1, "returns/aurelle/2026-10.json", "returns", "aurelle", P1, {"returns": []}, SRC1)

    # Brand B (verdant): $50 item for the same creator cr_0001.
    ob1 = _order("verdant", "O_B1", D(2026, 10, 7, 15, 0), "50.00", D(2026, 10, 9, 9, 0))
    b_aff = make_aff("AR_B1", "O_B1", "L_B1_1", "cr_0001", "@golden.mia", "V_V1", "video", "0.12", "6.00",
                     "pending", D(2026, 10, 9, 9, 0))
    inc(m, b1, "orders/verdant/2026-10.json", "orders", "verdant", P1, {"orders": [ob1]}, SRC1)
    inc(m, b1, "affiliate_orders/verdant/2026-10.json", "affiliate_orders", "verdant", P1, {"records": [b_aff]}, SRC1)
    inc(m, b1, "returns/verdant/2026-10.json", "returns", "verdant", P1, {"returns": []}, SRC1)

    # crunchwell: $30 order, corrected to $45 in batch_2, an older $20 version lives in batch_older.
    oc1 = _order("crunchwell", "O_C1", D(2026, 10, 8, 10, 0), "30.00", D(2026, 10, 9, 10, 0))
    inc(m, b1, "orders/crunchwell/2026-10.json", "orders", "crunchwell", P1, {"orders": [oc1]}, SRC1)
    inc(m, b1, "affiliate_orders/crunchwell/2026-10.json", "affiliate_orders", "crunchwell", P1, {"records": []}, SRC1)
    inc(m, b1, "returns/crunchwell/2026-10.json", "returns", "crunchwell", P1, {"returns": []}, SRC1)

    # glowhaus: normal $40 order; weekly video gap (W41 never delivered).
    og1 = _order("glowhaus", "O_G1", D(2026, 10, 3, 11, 0), "40.00", D(2026, 10, 5, 9, 0))
    inc(m, b1, "orders/glowhaus/2026-10.json", "orders", "glowhaus", P1, {"orders": [og1]}, SRC1)
    inc(m, b1, "affiliate_orders/glowhaus/2026-10.json", "affiliate_orders", "glowhaus", P1, {"records": []}, SRC1)
    inc(m, b1, "returns/glowhaus/2026-10.json", "returns", "glowhaus", P1, {"returns": []}, SRC1)

    # products
    for brand, prods in PRODUCTS.items():
        rel = f"products/{brand}.csv"
        write_csv_text(os.path.join(b1, rel), ["shop_id", "product_id", "sku_id", "product_name", "list_price",
                                                "unit_cost", "update_time"],
                       [[SHOP[brand], p, s, n, lp, uc, "1760500000"] for p, s, n, lp, uc in prods])
        m.add(rel, "products", brand, "2026-10-01", "2026-10-15", "snapshot", SRC1)

    # weekly videos (per-week metrics, NOT cumulative)
    # V_A1: week W40 views 100 / gmv 60.00 / 3 items; week W41 views 40 / gmv 40.00 / 2 items -> total views 140.
    va1 = ["V_A1", "cr_0001", "@golden.mia", "2026-10-01T09:00:00", "P_A1"]
    vv1 = ["V_V1", "cr_0001", "@golden.mia", "2026-10-06T10:00:00", "P_V1"]
    vt1 = ["V_T1", "cr_0003", "@golden.thread", "2026-09-05T11:00:00", "P_T1"]
    w40 = date(2026, 9, 28)
    w41 = date(2026, 10, 5)
    # V_A0: cr_0002's only video, posted 2026-09-20 (before October) so the retainer creator has a last_post_date
    # 25 days before the as-of while aurelle coverage is complete (quiet_retainer attention item).
    va0 = ["V_A0", "cr_0002", "@golden.quiet", "2026-09-20T10:00:00", "P_A1"]
    rows = {
        ("aurelle", date(2026, 9, 14)): [va0 + [300, 0.00, 0]],
        ("aurelle", date(2026, 9, 21)): [],
        ("aurelle", w40): [va1 + [100, 60.00, 3]],
        ("aurelle", w41): [va1 + [40, 40.00, 2]],
        ("verdant", w40): [],
        ("verdant", w41): [vv1 + [80, 50.00, 1]],
        ("glowhaus", w40): [],
    }
    for ws_, we in _weeks(date(2026, 8, 10), date(2026, 10, 5)):
        rows[("threadline", ws_)] = [vt1 + [500, 0.00, 0]] if ws_ == date(2026, 8, 31) else []
    for (brand, ws_), r in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        we = ws_ + timedelta(days=6)
        lab = iso_week_label(ws_)
        rel = f"videos/{brand}/{lab}.xlsx"
        write_video_xlsx(os.path.join(b1, rel), NAMES[brand], lab, ws_, we, VIDEO_HEADER_V1, r)
        m.add(rel, "videos_weekly", brand, ws_.isoformat(), we.isoformat(), "increment", SRC1)

    # roster
    roster = [
        {"brand_id": "aurelle", "creator_id": "cr_0001", "handle": "@golden.mia", "contract_type": "affiliate",
         "effective_from": "2026-01-01", "status": "active"},
        {"brand_id": "verdant", "creator_id": "cr_0001", "handle": "@golden.mia", "contract_type": "affiliate",
         "effective_from": "2026-01-01", "status": "active"},
        {"brand_id": "aurelle", "creator_id": "cr_0002", "handle": "@golden.quiet", "contract_type": "retainer",
         "monthly_retainer": "1000.00", "posts_per_month": 4, "effective_from": "2026-01-01", "status": "active",
         "allocation_share": 1.0},
        {"brand_id": "threadline", "creator_id": "cr_0003", "handle": "@golden.thread",
         "contract_type": "affiliate", "effective_from": "2026-01-01", "status": "active"},
        {"brand_id": "glowhaus", "creator_id": "cr_0004", "handle": "@golden.glow", "contract_type": "affiliate",
         "effective_from": "2026-01-01", "status": "active"},
        {"brand_id": "crunchwell", "creator_id": "cr_0005", "handle": "@golden.crunch", "contract_type": "affiliate",
         "effective_from": "2026-01-01", "status": "active"},
    ]
    write_roster_xlsx(os.path.join(b1, "roster/roster.xlsx"), roster)
    m.add("roster/roster.xlsx", "roster", "all", "2026-10-01", "2026-10-15", "snapshot", SRC1)

    # samples (threadline). GS2 delivered date is an Excel serial (2026-08-25) on purpose.
    samples = [
        dict(shipment_id="GS1", brand_id="threadline", creator_id="cr_0003", product_id="P_T1", qty=1,
             shipped_date="2026-08-15", delivered_date="2026-08-20", status_text="Delivered", shipping_cost="8.00"),
        dict(shipment_id="GS2", brand_id="threadline", creator_id="cr_0003", product_id="P_T2", qty=1,
             shipped_date="2026-08-20", delivered_date=excel_serial(date(2026, 8, 25)), status_text="Delivered",
             shipping_cost="8.00"),
        dict(shipment_id="GS3", brand_id="threadline", creator_id="cr_0003", product_id="P_T1", qty=1,
             shipped_date="2026-10-06", delivered_date="2026-10-08", status_text="Delivered", shipping_cost="8.00"),
        dict(shipment_id="GS4", brand_id="threadline", creator_id="cr_9999", product_id="P_T2", qty=1,
             shipped_date="2026-08-20", delivered_date="2026-08-24", status_text="Delivered", shipping_cost="8.00"),
        dict(shipment_id="GS5", brand_id="threadline", creator_id="cr_0003", product_id="P_T2", qty=1,
             shipped_date="2026-10-12", delivered_date=None, status_text="In transit", shipping_cost="8.00"),
    ]
    write_samples_xlsx(os.path.join(b1, "samples/samples.xlsx"), samples)
    m.add("samples/samples.xlsx", "samples", "threadline", "2026-08-01", "2026-10-15", "snapshot", SRC1)

    # plans
    for brand in SHOP:
        goals = [
            {"metric_key": "gmv", "scope": "shop" if brand == "aurelle" else "creator_attributed",
             "basis": "gross" if brand == "aurelle" else "net", "definition": "Golden GMV goal", "target": 1000},
            {"metric_key": "videos", "scope": "creator_attributed", "basis": "gross",
             "definition": "Qualifying videos published", "target": 5},
            {"metric_key": "active_creators", "scope": "creator_attributed", "basis": "gross",
             "definition": "Creators with a video", "target": 2},
        ]
        write_json(os.path.join(b1, f"plans/{brand}.json"), {"brand_id": brand, "month": "2026-10", "goals": goals})
        m.add(f"plans/{brand}.json", "plans", brand, "2026-10-01", "2026-10-31", "snapshot", SRC1)
    m.write(b1)

    # ---------------------------------------------------------------- batch_2
    b2 = os.path.join(gc, "batch_2")
    m2 = Manifest("batch_2", "2026-11-02T23:59:59-08:00", "2026-11-02")
    SRC2 = "2026-11-02T07:00:00Z"
    P2 = ("2026-10-15", "2026-11-01")

    # aurelle: order re-sent with newer update_time (status only), refund of $20 completing Oct 20 12:00 PT
    oa1_v2 = _order("aurelle", "O_A1", D(2026, 10, 5, 12, 0), "100.00", D(2026, 10, 20, 9, 0), status="COMPLETED")
    inc(m2, b2, "orders/aurelle/2026-10.json", "orders", "aurelle", P2, {"orders": [oa1_v2]}, SRC2)
    a1_v2 = make_aff("AR_A1", "O_A1", "L_A1_1", "cr_0001", "@golden.mia", "V_A1", "video", "0.12", "12.00",
                     "settled", D(2026, 10, 20, 9, 0))
    inc(m2, b2, "affiliate_orders/aurelle/2026-10.json", "affiliate_orders", "aurelle", P2, {"records": [a1_v2]}, SRC2)
    r1 = make_return("R_A1", "O_A1", "L_A1_1", "COMPLETED", "20.00", D(2026, 10, 17, 9, 0), D(2026, 10, 20, 12, 0),
                     D(2026, 10, 20, 12, 0))
    inc(m2, b2, "returns/aurelle/2026-10.json", "returns", "aurelle", P2, {"returns": [r1]}, SRC2)

    # verdant: nothing new, coverage extended
    inc(m2, b2, "orders/verdant/2026-10.json", "orders", "verdant", P2, {"orders": []}, SRC2)
    inc(m2, b2, "affiliate_orders/verdant/2026-10.json", "affiliate_orders", "verdant", P2, {"records": []}, SRC2)
    inc(m2, b2, "returns/verdant/2026-10.json", "returns", "verdant", P2, {"returns": []}, SRC2)

    # crunchwell: corrected to $45 (newer update_time Oct 16)
    oc1_v2 = _order("crunchwell", "O_C1", D(2026, 10, 8, 10, 0), "45.00", D(2026, 10, 16, 10, 0))
    inc(m2, b2, "orders/crunchwell/2026-10.json", "orders", "crunchwell", P2, {"orders": [oc1_v2]}, SRC2)
    inc(m2, b2, "affiliate_orders/crunchwell/2026-10.json", "affiliate_orders", "crunchwell", P2, {"records": []}, SRC2)
    inc(m2, b2, "returns/crunchwell/2026-10.json", "returns", "crunchwell", P2, {"returns": []}, SRC2)

    # glowhaus: order paid 2026-10-31 23:30 PT (= 2026-11-01 06:30 UTC) -> counts in OCTOBER
    og2 = _order("glowhaus", "O_G2", D(2026, 10, 31, 23, 30), "25.00", D(2026, 11, 1, 9, 0), status="AWAITING_SHIPMENT")
    inc(m2, b2, "orders/glowhaus/2026-10.json", "orders", "glowhaus", P2, {"orders": [og2]}, SRC2)
    inc(m2, b2, "affiliate_orders/glowhaus/2026-10.json", "affiliate_orders", "glowhaus", P2, {"records": []}, SRC2)
    inc(m2, b2, "returns/glowhaus/2026-10.json", "returns", "glowhaus", P2, {"returns": []}, SRC2)

    # crunchwell products: UTF-8 BOM
    write_csv_text(os.path.join(b2, "products/crunchwell.csv"),
                   ["shop_id", "product_id", "sku_id", "product_name", "list_price", "unit_cost", "update_time"],
                   [[SHOP["crunchwell"], "P_C1", "S_C1", "Crunch Box", "45.00", "16.00", "1760700000"]], bom=True)
    m2.add("products/crunchwell.csv", "products", "crunchwell", "2026-10-01", "2026-11-02", "snapshot", SRC2)

    # weekly videos W42 (renamed header), W43, W44 (through 2026-11-01 = the batch as-of week, contiguous); no new videos
    for brand in ("aurelle", "verdant", "threadline", "glowhaus"):
        for ws_, hdr in ((date(2026, 10, 12), VIDEO_HEADER_V2), (date(2026, 10, 19), VIDEO_HEADER_V1),
                        (date(2026, 10, 26), VIDEO_HEADER_V1)):
            we = ws_ + timedelta(days=6)
            lab = iso_week_label(ws_)
            rel = f"videos/{brand}/{lab}.xlsx"
            write_video_xlsx(os.path.join(b2, rel), NAMES[brand], lab, ws_, we, hdr, [])
            m2.add(rel, "videos_weekly", brand, ws_.isoformat(), we.isoformat(), "increment", SRC2)
    m2.write(b2)

    # ---------------------------------------------------------------- batch_older
    bo = os.path.join(gc, "batch_older")
    mo = Manifest("batch_older", "2026-10-15T23:59:59-07:00", "2026-10-15")
    oc1_old = _order("crunchwell", "O_C1", D(2026, 10, 8, 10, 0), "20.00", D(2026, 10, 8, 13, 0))
    inc(mo, bo, "orders/crunchwell/2026-10.json", "orders", "crunchwell", P1, {"orders": [oc1_old]},
        "2026-10-08T20:00:00Z")
    mo.write(bo)

    # ---------------------------------------------------------------- batch_bad
    bb = os.path.join(gc, "batch_bad")
    mb = Manifest("batch_bad", "2026-11-02T23:59:59-08:00", "2026-11-02")
    rej = make_return("R_C_REJ", "O_C1", "L_C1_1", "REJECTED", None, D(2026, 10, 17, 9, 0), None,
                      D(2026, 10, 18, 9, 0))
    inc(mb, bb, "returns/crunchwell/2026-10.json", "returns", "crunchwell", P2, {"returns": [rej]}, SRC2)
    bad = _order("verdant", "O_BAD", D(2026, 10, 8, 9, 0), "999.00", D(2026, 10, 9, 9, 0))
    del bad["order_id"]  # required field missing
    inc(mb, bb, "orders/verdant/2026-10-extra.json", "orders", "verdant", P2, {"orders": [bad]}, SRC2)
    mb.write(bb)

    from golden_v2 import build_v2
    build_v2(gc)
