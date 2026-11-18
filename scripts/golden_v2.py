"""Amendment-2 golden fixture additions (called from golden_cases.build).

batch_3 (as_of 2026-11-02, ingested AFTER batch_2) adds September data and new creators. It never changes an October
value that tests/golden/expected.yaml already asserts for batch_1/batch_2.
  * aurelle Sep: partial refunds, a cancelled line with a refund, a look-alike creator handle, a stable-id handle change
  * crunchwell Sep + Oct attribution + weekly videos W35..W44: video snapshots counted once, diagnostics Oct vs Sep
  * threadline Sep: discounts, float-trap cents, a EUR order; retainer starting mid-month
  * roster snapshot v2: dual-brand retainers (60/40 split, missing split), a mid-month retainer
batch_4_revision: one $1.00 verdant order (changes data_revision only; used by the ETag test)
batch_overlap: aurelle W41 re-sent with different numbers (must be quarantined)
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from synth_common import (
    Manifest, VIDEO_HEADER_V1, iso_week_label, make_aff, make_line, make_order, make_return, write_json,
    write_roster_xlsx, write_video_xlsx,
)

D = datetime
SHOP = {b: f"shop_{b}" for b in ("aurelle", "verdant", "crunchwell", "threadline", "glowhaus")}
NAME_CW = "Crunchwell Snacks"


def _line(lid, product, sku, sale, original=None, seller="0.00", platform="0.00", status="DELIVERED"):
    return make_line(lid, product, sku, sale, original if original is not None else sale, seller, platform, status)


def _ord(brand, oid, paid, lines, status="DELIVERED", currency="USD"):
    o = make_order(oid, SHOP[brand], status, paid - timedelta(minutes=5), paid, paid + timedelta(days=1), lines)
    o["payment"]["currency"] = currency
    return o


def _vrow(vid, cid, handle, post, product, views, gmv, items):
    return [vid, cid, handle, post, product, views, gmv, items]


def build_v2(gc: str) -> None:
    SRC3 = "2026-11-02T20:00:00Z"
    SEP = ("2026-09-01", "2026-09-30")
    OCT = ("2026-10-01", "2026-11-01")
    b3 = os.path.join(gc, "batch_3")
    m = Manifest("batch_3", "2026-11-02T23:59:59-08:00", "2026-11-02")
    key = {"orders": "orders", "affiliate_orders": "records", "returns": "returns"}

    def inc(brand, st, name, period, payload):
        rel = f"{st}/{brand}/{name}"
        write_json(os.path.join(b3, rel), payload)
        m.add(rel, st, brand, period[0], period[1], "increment", SRC3)

    def empty(brand, st, period, name):
        inc(brand, st, name, period, {key[st]: []})

    # ---- aurelle September
    o3 = _ord("aurelle", "O_A3", D(2026, 9, 3, 11, 0), [
        _line("L_A3_1", "P_A1", "S_A1", "60.00", "75.00", "10.00", "5.00"),
        _line("L_A3_2", "P_A1", "S_A1", "40.00", "40.00", status="CANCELLED")])
    o4 = _ord("aurelle", "O_A4", D(2026, 9, 12, 14, 0), [_line("L_A4_1", "P_A1", "S_A1", "50.00")])
    o5 = _ord("aurelle", "O_A5", D(2026, 9, 14, 16, 30), [_line("L_A5_1", "P_A1", "S_A1", "30.00")])
    inc("aurelle", "orders", "2026-09.json", SEP, {"orders": [o3, o4, o5]})
    inc("aurelle", "affiliate_orders", "2026-09.json", SEP, {"records": [
        # stable id cr_0001 with a NEW handle -> resolves to cr_0001
        make_aff("AR_A3", "O_A3", "L_A3_1", "cr_0001", "@golden.mia.new", None, "showcase", "0.12", "7.20",
                 "settled", D(2026, 9, 4, 9, 0)),
        # unknown id + look-alike handle of @golden.mia -> must NOT merge into cr_0001
        make_aff("AR_A4", "O_A4", "L_A4_1", "u_9001", "@golden.m1a", None, "showcase", "0.12", "6.00",
                 "settled", D(2026, 9, 13, 9, 0))]})
    inc("aurelle", "returns", "2026-09.json", SEP, {"returns": [
        make_return("R_A3a", "O_A3", "L_A3_1", "COMPLETED", "15.00", D(2026, 9, 15, 9, 0), D(2026, 9, 20, 10, 0),
                    D(2026, 9, 20, 10, 0)),
        make_return("R_A3b", "O_A3", "L_A3_1", "COMPLETED", "10.00", D(2026, 9, 21, 9, 0), D(2026, 9, 25, 10, 0),
                    D(2026, 9, 25, 10, 0)),
        # refund recorded against the CANCELLED line: must not be subtracted again
        make_return("R_A3c", "O_A3", "L_A3_2", "COMPLETED", "40.00", D(2026, 9, 22, 9, 0), D(2026, 9, 26, 10, 0),
                    D(2026, 9, 26, 10, 0))]})

    # ---- verdant September coverage (empty; the $1.00 order lives in batch_4_revision)
    for st in ("orders", "affiliate_orders", "returns"):
        empty("verdant", st, SEP, "2026-09.json")

    # ---- crunchwell September
    def cs(oid, d, amt):
        return _ord("crunchwell", oid, d, [_line(f"L_{oid[2:]}_1", "P_C1", "S_C1", amt, "45.00")])

    inc("crunchwell", "orders", "2026-09.json", SEP, {"orders": [
        cs("O_C2", D(2026, 9, 3, 10, 0), "40.00"), cs("O_C3", D(2026, 9, 9, 12, 0), "20.00"),
        cs("O_C4", D(2026, 9, 6, 13, 0), "30.00"), cs("O_C5", D(2026, 9, 10, 15, 0), "10.00")]})

    def aff(rid, oid, cid, h, vid, amt):
        return make_aff(rid, oid, f"L_{oid[2:]}_1", cid, h, vid, "video", "0.10", amt, "settled",
                        D(2026, 9, 12, 9, 0))

    inc("crunchwell", "affiliate_orders", "2026-09.json", SEP, {"records": [
        aff("AR_C2", "O_C2", "cr_0005", "@golden.crunch", "V_C2", "4.00"),
        aff("AR_C3", "O_C3", "cr_0005", "@golden.crunch", "V_C3", "2.00"),
        aff("AR_C4", "O_C4", "cr_0007", "@golden.crunch2", "V_C4", "3.00"),
        aff("AR_C5", "O_C5", "cr_0007", "@golden.crunch2", "V_C0", "1.00")]})   # V_C0 is an OLDER video (Aug 25)
    empty("crunchwell", "returns", SEP, "2026-09.json")
    # October: attribute the existing $45.00 order O_C1 to the new video V_C5 (shop GMV stays 45.00)
    inc("crunchwell", "affiliate_orders", "2026-10.json", OCT, {"records": [
        make_aff("AR_C1", "O_C1", "L_C1_1", "cr_0005", "@golden.crunch", "V_C5", "video", "0.12", "5.40", "pending",
                 D(2026, 10, 9, 9, 0))]})

    # ---- crunchwell weekly videos W35..W44 (per-week values; V_C2 appears in W36 and W37)
    h5, h7 = "@golden.crunch", "@golden.crunch2"
    vr = {
        date(2026, 8, 24): [_vrow("V_C0", "cr_0007", h7, "2026-08-25T10:00:00", "P_C1", 120, 0.00, 0)],
        date(2026, 8, 31): [_vrow("V_C2", "cr_0005", h5, "2026-09-02T09:00:00", "P_C1", 200, 40.00, 1),
                            _vrow("V_C4", "cr_0007", h7, "2026-09-05T10:00:00", "P_C1", 90, 30.00, 1)],
        date(2026, 9, 7): [_vrow("V_C2", "cr_0005", h5, "2026-09-02T09:00:00", "P_C1", 50, 0.00, 0),
                           _vrow("V_C3", "cr_0005", h5, "2026-09-08T11:00:00", "P_C1", 80, 20.00, 1),
                           _vrow("V_C0", "cr_0007", h7, "2026-08-25T10:00:00", "P_C1", 15, 10.00, 1)],
        date(2026, 9, 28): [_vrow("V_C5", "cr_0005", h5, "2026-10-03T12:00:00", "P_C1", 60, 0.00, 0)],
        date(2026, 10, 5): [_vrow("V_C5", "cr_0005", h5, "2026-10-03T12:00:00", "P_C1", 40, 45.00, 1)],
    }
    for ws_ in (date(2026, 8, 24) + timedelta(days=7 * i) for i in range(10)):
        we = ws_ + timedelta(days=6)
        lab = iso_week_label(ws_)
        rel = f"videos/crunchwell/{lab}.xlsx"
        write_video_xlsx(os.path.join(b3, rel), NAME_CW, lab, ws_, we, VIDEO_HEADER_V1, vr.get(ws_, []))
        m.add(rel, "videos_weekly", "crunchwell", ws_.isoformat(), we.isoformat(), "increment", SRC3)

    # ---- threadline: discounts, float-trap cents, EUR order; coverage Sep 1 .. Nov 1
    t1 = _ord("threadline", "O_T1", D(2026, 9, 10, 10, 0), [
        _line("L_T1_1", "P_T1", "S_T1", "10.00", "20.00", "5.00", "5.00"),
        _line("L_T1_2", "P_T1", "S_T1", "9.99", "12.49", "0.00", "2.50"),
        _line("L_T1_3", "P_T1", "S_T1", "0.10"), _line("L_T1_4", "P_T1", "S_T1", "0.20")])
    t2 = _ord("threadline", "O_T2", D(2026, 9, 11, 10, 0), [_line("L_T2_1", "P_T1", "S_T1", "100.00")],
              currency="EUR")
    inc("threadline", "orders", "2026-09.json", SEP, {"orders": [t1, t2]})
    inc("threadline", "orders", "2026-10.json", OCT, {"orders": []})
    for st in ("affiliate_orders", "returns"):
        empty("threadline", st, SEP, "2026-09.json")
        empty("threadline", st, OCT, "2026-10.json")

    # ---- roster snapshot v2 (full snapshot: batch_1 rows + new rows)
    def row(brand, cid, handle, ctype="affiliate", **kw):
        r = {"brand_id": brand, "creator_id": cid, "handle": handle, "contract_type": ctype,
             "effective_from": "2026-01-01", "status": "active"}
        r.update(kw)
        return r

    rows = [row("aurelle", "cr_0001", "@golden.mia"), row("verdant", "cr_0001", "@golden.mia"),
            row("aurelle", "cr_0002", "@golden.quiet", "retainer", monthly_retainer="1000.00", posts_per_month=4,
                allocation_share=1.0),
            row("threadline", "cr_0003", "@golden.thread"), row("glowhaus", "cr_0004", "@golden.glow"),
            row("crunchwell", "cr_0005", "@golden.crunch"), row("crunchwell", "cr_0007", "@golden.crunch2")]
    for brand, share in (("aurelle", 0.6), ("verdant", 0.4)):          # dual-brand retainer 3000.00, split 60/40
        rows.append(row(brand, "cr_0010", "@golden.dual", "retainer", monthly_retainer="3000.00",
                        posts_per_month=4, allocation_share=share))
    for brand in ("aurelle", "verdant"):                                 # dual-brand retainer, split MISSING
        rows.append(row(brand, "cr_0011", "@golden.noshare", "retainer", monthly_retainer="2000.00",
                        posts_per_month=4))
    rows.append(row("threadline", "cr_0012", "@golden.mid", "retainer", monthly_retainer="900.00",
                    posts_per_month=4, effective_from="2026-09-16"))
    write_roster_xlsx(os.path.join(b3, "roster/roster.xlsx"), rows)
    m.add("roster/roster.xlsx", "roster", "all", "2026-10-01", "2026-11-02", "snapshot", SRC3)
    m.write(b3)

    # ---- batch_4_revision: one more $1.00 verdant order (September), nothing else
    b4 = os.path.join(gc, "batch_4_revision")
    m4 = Manifest("batch_4_revision", "2026-11-03T23:59:59-08:00", "2026-11-02")
    v1 = _ord("verdant", "O_V9", D(2026, 9, 20, 10, 0), [_line("L_V9_1", "P_V1", "S_V1", "1.00")])
    write_json(os.path.join(b4, "orders/verdant/2026-09.json"), {"orders": [v1]})
    m4.add("orders/verdant/2026-09.json", "orders", "verdant", SEP[0], SEP[1], "increment", "2026-11-03T20:00:00Z")
    m4.write(b4)

    # ---- batch_overlap: aurelle W41 re-sent with different numbers -> quarantined
    bo = os.path.join(gc, "batch_overlap")
    mo = Manifest("batch_overlap", "2026-11-03T23:59:59-08:00", "2026-11-02")
    w41 = date(2026, 10, 5)
    lab = iso_week_label(w41)
    rel = f"videos/aurelle/{lab}.xlsx"
    write_video_xlsx(os.path.join(bo, rel), "Aurelle Jewelry", lab, w41, w41 + timedelta(days=6), VIDEO_HEADER_V1,
                     [["V_A1", "cr_0001", "@golden.mia", "2026-10-01T09:00:00", "P_A1", 999, 999.00, 9]])
    mo.add(rel, "videos_weekly", "aurelle", w41.isoformat(), (w41 + timedelta(days=6)).isoformat(), "increment",
           "2026-11-03T20:00:00Z")
    mo.write(bo)


    # ---- batch_allbad: a crunchwell orders file whose rows ALL lack order_id -> no usable rows -> rejected (S11b)
    ba = os.path.join(gc, "batch_allbad")
    mba = Manifest("batch_allbad", "2026-11-03T23:59:59-08:00", "2026-11-02")
    rows = []
    for i, amt in ((1, "12.00"), (2, "8.00")):
        o = _ord("crunchwell", f"O_ALLBAD{i}", D(2026, 10, 9 + i, 10, 0), [_line(f"L_ALLBAD{i}_1", "P_C1", "S_C1", amt)])
        del o["order_id"]
        rows.append(o)
    write_json(os.path.join(ba, "orders/crunchwell/2026-10-allbad.json"), {"orders": rows})
    mba.add("orders/crunchwell/2026-10-allbad.json", "orders", "crunchwell", "2026-10-15", "2026-11-01", "increment",
            "2026-11-03T20:00:00Z")
    mba.write(ba)
