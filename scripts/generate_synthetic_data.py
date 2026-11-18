"""Deterministic synthetic data generator (fixed seed). Run:  python scripts/generate_synthetic_data.py

Writes data/synthetic/batch_1, batch_2 and golden_cases per docs/source-contracts.md.
Never imports backend/app. All data is invented.
"""
from __future__ import annotations

import math
import os
import random
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import golden_cases  # noqa: E402
from synth_common import (  # noqa: E402
    BRANDS, PT, Manifest, VIDEO_HEADER_V1, VIDEO_HEADER_V2, excel_serial, iso_week_label, make_aff, make_line,
    make_order, make_return, money, monday_of, write_csv_text, write_json, write_roster_xlsx,
    write_samples_xlsx, write_video_xlsx,
)

SEED = 20261015
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "synthetic")
START = date(2026, 4, 1)
B1_END = date(2026, 10, 14)       # batch 1 orders/returns complete through here
B2_END = date(2026, 10, 21)       # batch 2 orders/returns complete through here
POST_END = date(2026, 10, 18)     # last post date generated
D = datetime
rng = random.Random(SEED)
Q = Decimal("0.01")

BRAND_IDS = [b[0] for b in BRANDS]
BRAND_NAME = {b[0]: b[1] for b in BRANDS}
SHOP = {b: f"shop_{b}" for b in BRAND_IDS}
PRODUCT_NAMES = {
    "aurelle": [("Gold Hoop Earrings", 48), ("Layered Necklace", 62), ("Pearl Studs", 35), ("Charm Bracelet", 54),
                ("Signet Ring", 70), ("Anklet Set", 28)],
    "verdant": [("Vitamin C Serum", 38), ("Hydra Gel Cream", 32), ("Gentle Cleanser", 18), ("SPF 50 Fluid", 26),
                ("Retinol Night Oil", 44), ("Clay Mask", 22)],
    "crunchwell": [("Crunch Box Original", 24), ("Spicy Chickpea Bites", 16), ("Protein Clusters", 29),
                   ("Seaweed Chips", 14), ("Trail Mix Pack", 21), ("Honey Granola", 19)],
    "threadline": [("Linen Shirt", 59), ("Denim Jacket", 94), ("Wide Leg Trousers", 72), ("Knit Cardigan", 66),
                   ("Cotton Tee 3-Pack", 39), ("Canvas Tote", 25)],
    "glowhaus": [("Glow Palette", 36), ("Dewy Tint", 24), ("Lash Serum", 31), ("Lip Oil Duo", 22),
                 ("Setting Spray", 20), ("Brush Set", 42)],
}
PRODUCTS = {b: [(f"P_{b[:3].upper()}_{i + 1}", f"SKU_{b[:3].upper()}_{i + 1}", n, Decimal(p))
                for i, (n, p) in enumerate(PRODUCT_NAMES[b])] for b in BRAND_IDS}
ORDER_RATE = {"aurelle": 3.2, "verdant": 3.5, "crunchwell": 5.0, "threadline": 3.8, "glowhaus": 3.2}
ATTR_RATE = {"aurelle": 0.45, "verdant": 0.45, "crunchwell": 0.6, "threadline": 0.45, "glowhaus": 0.45}


def q(x) -> Decimal:
    return Decimal(x).quantize(Q, rounding=ROUND_HALF_UP)


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def local_dt(d: date, hour=None, minute=None) -> datetime:
    h = rng.randint(7, 22) if hour is None else hour
    m = rng.randint(0, 59) if minute is None else minute
    return datetime(d.year, d.month, d.day, h, m, rng.randint(0, 59))


# ------------------------------------------------------------------ creators / roster
FIRST = ["mia", "noah", "ava", "liam", "zoe", "kai", "ivy", "leo", "nia", "eli", "ruby", "omar", "tess", "jude",
         "lena", "ravi", "cora", "milo", "sana", "theo", "wren", "dev", "pia", "ezra", "lola", "hugo", "isla",
         "finn", "yara", "cal"]
SUFFIX = ["makes", "finds", "daily", "loves", "edit", "vibes", "picks", "studio", "table", "haul", "reviews", "lab"]


def build_creators():
    handles = set()
    creators = []
    for i in range(1, 77):
        cid = f"cr_{i:04d}"
        while True:
            h = f"@{rng.choice(FIRST)}.{rng.choice(SUFFIX)}"
            if h not in handles and h != "@mia.makes":
                break
        handles.add(h)
        creators.append({"id": cid, "handle": h, "old_handle": None})
    creators[0]["handle"] = "@snack.shack.sam"           # cr_0001: crunchwell affiliate star
    creators[1]["handle"] = "@dewy.dana"                 # cr_0002: verdant quiet retainer
    creators[6]["old_handle"] = "@mia.makes"             # cr_0007: handle change mid-year, same id
    creators[6]["handle"] = "@mia.makes.studio"
    return creators


def build_slots(creators):
    """Creator-brand slots (roster rows)."""
    slots = []
    brand_cycle = BRAND_IDS
    for idx, c in enumerate(creators):
        c["brands"] = [brand_cycle[idx % 5]]
    creators[0]["brands"] = ["crunchwell"]
    creators[1]["brands"] = ["verdant"]
    for c in creators[10:20]:                         # 10 creators work for two brands
        other = rng.choice([b for b in BRAND_IDS if b not in c["brands"]])
        c["brands"].append(other)
    for idx, c in enumerate(creators):
        retainer = rng.random() < 0.30
        if idx == 0:
            retainer = False
        if idx == 1:
            retainer = True
        total = rng.choice([800, 1200, 1500, 2000, 2500, 3000]) if retainer else None
        posts = rng.choice([4, 6, 8]) if retainer else None
        n = len(c["brands"])
        missing_share = retainer and n == 2 and idx == 12   # one multi-brand retainer with unknown allocation
        if idx == 12:
            retainer, total, posts, missing_share = True, 1800, 6, True
        for b in c["brands"]:
            eff_from = date(2026, 1, 1) + timedelta(days=rng.randint(0, 100))
            if idx in (30, 31, 32):
                eff_from = date(2026, 7, 1) + timedelta(days=rng.randint(0, 30))
            status, eff_to = "active", None
            if idx == 41 and retainer:
                status, eff_to = "ended", date(2026, 9, 30)
            if idx == 45:
                status = "paused"
            slots.append({
                "brand": b, "creator": c, "retainer": retainer, "monthly": total, "posts_pm": posts,
                "eff_from": eff_from, "eff_to": eff_to, "status": status,
                "share": None if (not retainer or n == 1 or missing_share) else round(1 / n, 2),
                "multi": n > 1,
            })
    return slots


def poisson_floor(rate):
    return int(math.floor(rate + rng.random()))


def build_videos(slots):
    videos = []
    seq = defaultdict(int)

    def add(slot, d, product=None):
        b = slot["brand"]
        seq[b] += 1
        prod = product or rng.choice(PRODUCTS[b])[0]
        c = slot["creator"]
        handle = c["handle"]
        if c["old_handle"] and d < date(2026, 7, 1):
            handle = c["old_handle"]
        videos.append({"id": f"7{BRAND_IDS.index(b)}{seq[b]:06d}", "brand": b, "cid": c["id"], "handle": handle,
                       "post": local_dt(d), "product": prod, "views": int(rng.lognormvariate(8.6, 1.0)),
                       "slot": slot})
        return videos[-1]

    for s in slots:
        c = s["creator"]
        if s["retainer"]:
            rate = max(1.0, s["posts_pm"] / 3.5)
        else:
            rate = 0.3
        if c["id"] == "cr_0001":
            rate = 6.0
        if c["id"] == "cr_0002":
            rate = 3.0
        start = max(START, s["eff_from"])
        end = min(POST_END, s["eff_to"] or POST_END)
        if s["status"] == "paused":
            end = min(end, date(2026, 8, 31))
        if c["id"] == "cr_0002":
            end = date(2026, 10, 2)                   # verdant retainer creator goes quiet after Oct 2
        for month in range(4, 11):
            m_start = date(2026, month, 1)
            m_end = (date(2026, month + 1, 1) - timedelta(days=1)) if month < 12 else date(2026, 12, 31)
            lo, hi = max(m_start, start), min(m_end, end)
            if lo > hi:
                continue
            frac = ((hi - lo).days + 1) / ((m_end - m_start).days + 1)
            n = poisson_floor(rate * frac)
            for _ in range(n):
                add(s, lo + timedelta(days=rng.randint(0, (hi - lo).days)))
    return videos, add


# ------------------------------------------------------------------ samples
def build_samples(slots, videos, add_video):
    rows = []
    n_by_brand = defaultdict(int)

    def slots_for(brand, exclude=("cr_0002",)):
        return [s for s in slots if s["brand"] == brand and s["creator"]["id"] not in exclude
                and s["status"] == "active"]

    def new(brand, slot_or_cid, product, ship, delivered, outcome="none", serial=False, status=None,
            linked=False, unit_cost_known=True):
        n_by_brand[brand] += 1
        cid = slot_or_cid if isinstance(slot_or_cid, str) else slot_or_cid["creator"]["id"]
        row = {"shipment_id": f"SHP-{brand[:3].upper()}-{n_by_brand[brand]:03d}", "brand": brand, "cid": cid,
               "product": product, "qty": rng.choice([1, 1, 1, 2]), "ship": ship, "delivered": delivered,
               "serial": serial, "force_status": status,
               "cost": None if (rng.random() < 0.10 or not unit_cost_known) else Decimal(rng.randint(600, 1200)) / 100,
               "linked": None}
        if outcome == "converted" and not isinstance(slot_or_cid, str):
            vd = delivered + timedelta(days=rng.randint(3, 25))
            if vd <= POST_END:
                v = add_video(slot_or_cid, vd, product)
                v["post"] = datetime(vd.year, vd.month, vd.day, rng.randint(9, 20), rng.randint(0, 59), 0)
                if linked:
                    row["linked"] = v["id"]
        rows.append(row)
        return row

    for brand in BRAND_IDS:
        if brand == "threadline":
            continue
        for _ in range(30):
            s = rng.choice(slots_for(brand))
            ship = date(2026, 4, 15) + timedelta(days=rng.randint(0, 175))
            deliv = ship + timedelta(days=rng.randint(2, 6))
            prod = rng.choice(PRODUCTS[brand])[0]
            kind = rng.random()
            if kind < 0.05:
                new(brand, s, prod, ship, None, status="Returned")
            elif kind < 0.09:
                new(brand, s, prod, ship, None, status="Sent")
            else:
                new(brand, s, prod, ship, deliv, "converted" if rng.random() < 0.4 else "none",
                    serial=rng.random() < 0.03, linked=rng.random() < 0.3)
    # threadline: converted, pending, no_video, ambiguous, unresolved
    tl = slots_for("threadline")
    tprods = [p[0] for p in PRODUCTS["threadline"]]
    for i in range(10):    # converted (mature)
        s = tl[i % len(tl)]
        ship = date(2026, 5, 1) + timedelta(days=i * 12)
        new("threadline", s, rng.choice(tprods), ship, ship + timedelta(days=3), "converted",
            serial=(i == 2), linked=(i % 3 == 0))
    for i in range(8):     # no video, mature
        s = tl[(i + 3) % len(tl)]
        ship = date(2026, 5, 8) + timedelta(days=i * 15)
        new("threadline", s, rng.choice(tprods), ship, ship + timedelta(days=4), "none")
    for i in range(6):     # pending: delivered within 30 days of 2026-10-15
        s = tl[(i + 5) % len(tl)]
        ship = date(2026, 10, 1) + timedelta(days=i)
        new("threadline", s, rng.choice(tprods), ship, ship + timedelta(days=2), "none")
    amb = tl[7 % len(tl)]  # ambiguous: two identical items delivered the same day, only one video follows
    prod = tprods[0]
    r1 = new("threadline", amb, prod, date(2026, 8, 3), date(2026, 8, 6), "converted")
    r2 = new("threadline", amb, prod, date(2026, 8, 3), date(2026, 8, 6), "none")
    r2["qty"], r1["qty"] = 1, 1
    new("threadline", "cr_0999", tprods[1], date(2026, 8, 10), date(2026, 8, 13), "none")  # unresolved creator
    new("threadline", tl[1], tprods[2], date(2026, 10, 12), date(2026, 10, 17), "none")    # delivered only in batch 2
    # a few new shipments between the batches
    for brand in ("aurelle", "glowhaus"):
        s = rng.choice(slots_for(brand))
        new(brand, s, rng.choice(PRODUCTS[brand])[0], date(2026, 10, 16), date(2026, 10, 19), "none")
    return rows


def render_samples(rows, as_of: date):
    out = []
    for r in rows:
        if r["ship"] > as_of:
            continue
        deliv = r["delivered"]
        if r["force_status"] == "Returned":
            text, dd = "Returned", None
        elif r["force_status"] == "Sent":
            text, dd = "Sent", None
        elif deliv and deliv <= as_of:
            text, dd = "Delivered", (excel_serial(deliv) if r["serial"] else deliv.isoformat())
        else:
            text, dd = "In transit", None
        out.append({"shipment_id": r["shipment_id"], "brand_id": r["brand"], "creator_id": r["cid"],
                    "product_id": r["product"], "qty": r["qty"], "shipped_date": r["ship"].isoformat(),
                    "delivered_date": dd, "status_text": text,
                    "shipping_cost": None if r["cost"] is None else money(r["cost"]),
                    "linked_video_id": r["linked"]})
    return out


# ------------------------------------------------------------------ orders / affiliate / returns
def generate_orders(slots, videos, samples):
    videos_by_brand = defaultdict(list)
    for v in videos:
        videos_by_brand[v["brand"]].append(v)
    slots_by_brand = defaultdict(list)
    for s in slots:
        slots_by_brand[s["brand"]].append(s)
    rate_by_creator = {}
    orders = defaultdict(list)       # brand -> [(local_create_dt, order_dict)]
    affs = defaultdict(list)         # brand -> [(update_dt, rec)]
    returns = defaultdict(list)      # brand -> [(event_dt, rec)]
    oseq = defaultdict(int)
    aseq = defaultdict(int)
    rseq = defaultdict(int)
    lines_by_order = {}

    def as_of_for(d: date):
        return date(2026, 10, 15) if d <= B1_END else date(2026, 10, 22)

    def pick_attribution(brand, d):
        r = rng.random()
        if r < 0.01:
            return ("u_9%04d" % rng.randint(1, 30), "@ghost.shop", None, "showcase")
        pool = [v for v in videos_by_brand[brand] if v["post"].date() <= d <= v["post"].date() + timedelta(days=40)]
        ctype = rng.choices(["video", "live", "showcase"], [0.8, 0.1, 0.1])[0]
        if ctype == "video" and pool:
            weights = [6.0 if v["cid"] == "cr_0001" else 1.0 for v in pool]
            v = rng.choices(pool, weights)[0]
            return (v["cid"], v["handle"] if d >= v["post"].date() else v["handle"], v["id"], "video")
        cand = [s for s in slots_by_brand[brand] if s["status"] == "active" and s["eff_from"] <= d]
        if not cand:
            return None
        s = rng.choice(cand)
        c = s["creator"]
        h = c["old_handle"] if (c["old_handle"] and d < date(2026, 7, 1)) else c["handle"]
        return (c["id"], h, None, "live" if ctype != "showcase" else "showcase")

    def add_return_events(brand, oid, lid, sale, paid_dt):
        if rng.random() >= 0.05 or sale <= 0:
            return
        rseq[brand] += 1
        rid = f"RET-{brand[:3].upper()}-{rseq[brand]:04d}"
        req = paid_dt + timedelta(days=rng.randint(2, 12), hours=rng.randint(0, 8))
        outcome = rng.choices(["done", "rej", "open"], [0.7, 0.15, 0.15])[0]
        returns[brand].append((req, make_return(rid, oid, lid, "REQUESTED", None, req, None, req)))
        if outcome == "open":
            return
        end = req + timedelta(days=rng.randint(3, 25), hours=rng.randint(0, 8))
        if outcome == "rej":
            returns[brand].append((end, make_return(rid, oid, lid, "REJECTED", None, req, None, end)))
            return
        refund = q(sale * rng.choice([Decimal("1"), Decimal("1"), Decimal("0.5"), Decimal("0.25")]))
        if rng.random() < 0.03:
            refund = None              # unsplit refund: merchandise amount unknown
        returns[brand].append((end, make_return(rid, oid, lid, "COMPLETED", refund, req, end, end)))

    def build_order(brand, d, hour=None, minute=None, force_sale=None, force_attr=None, oid=None, sample=None):
        oseq[brand] += 1
        oid = oid or f"{brand[:2].upper()}{rng.randint(10**9, 10**10 - 1)}"
        create = local_dt(d, hour, minute)
        paid = create + timedelta(minutes=rng.randint(1, 12)) if hour is None else create
        asof = as_of_for(d)
        age = (asof - d).days
        shop = SHOP[brand]
        pr = rng.choice(PRODUCTS[brand])
        lines = []
        if sample is not None:
            pr = next(p for p in PRODUCTS[brand] if p[0] == sample["product"])
            for k in range(sample["qty"]):
                lines.append(make_line(f"{oid}-{k + 1}", pr[0], pr[1], "0.00", "0.00", display_status="DELIVERED"))
            status = "DELIVERED" if age > 3 else "IN_TRANSIT"
            o = make_order(oid, shop, status, create, paid, min(create + timedelta(days=3), D(asof.year, asof.month, asof.day)), lines, True)
            return o
        roll = rng.random()
        n_units = rng.choice([1, 1, 1, 2, 2, 3])
        if force_sale is not None:
            n_units = 1
        for k in range(n_units):
            lp = pr[3] if force_sale is None else q(force_sale[0])
            seller = q(lp * rng.choice([Decimal("0"), Decimal("0"), Decimal("0.1"), Decimal("0.2")]))
            platform = q(lp * rng.choice([Decimal("0"), Decimal("0"), Decimal("0.05")]))
            if force_sale is not None:
                seller, platform = q(force_sale[1]), Decimal("0.00")
            sale_p = lp - seller - platform
            lines.append(make_line(f"{oid}-{k + 1}", pr[0], pr[1], sale_p, lp, seller, platform))
        if force_sale is None and roll < 0.03:
            status, paid_t = "UNPAID", None
        elif force_sale is None and roll < 0.07:
            status, paid_t = "CANCELLED", paid if rng.random() < 0.5 else None
        elif age <= 2:
            status, paid_t = "AWAITING_SHIPMENT", paid
        elif age <= 6:
            status, paid_t = "IN_TRANSIT", paid
        elif age <= 14:
            status, paid_t = "DELIVERED", paid
        else:
            status, paid_t = "COMPLETED", paid
        for l in lines:
            l["display_status"] = {"UNPAID": "AWAITING_SHIPMENT", "CANCELLED": "CANCELLED"}.get(status, status)
        upd = create + timedelta(days=min(age, rng.randint(1, 10)), hours=rng.randint(0, 5))
        cap = D(asof.year, asof.month, asof.day) - timedelta(minutes=1)
        upd = min(max(upd, create + timedelta(minutes=15)), cap)
        o = make_order(oid, shop, status, create, paid_t, upd, lines)
        attr = force_attr
        if attr is None and paid_t is not None and rng.random() < ATTR_RATE[brand]:
            attr = pick_attribution(brand, d)
        if attr is not None and status != "UNPAID":
            cid, handle, content, ctype = attr
            rate = rate_by_creator.setdefault(cid, rng.choice(["0.10", "0.12", "0.15"]))
            for l in lines:
                aseq[brand] += 1
                amt = q(Decimal(l["sale_price"]) * Decimal(rate))
                st = "settled" if d < date(2026, 9, 15) else "pending"
                affs[brand].append((upd, make_aff(f"AFF-{brand[:3].upper()}-{aseq[brand]:05d}", oid, l["id"], cid,
                                                  handle, content, ctype, rate, amt, st, upd)))
        if paid_t is not None and status != "CANCELLED":
            for l in lines:
                add_return_events(brand, oid, l["id"], Decimal(l["sale_price"]), paid)
        lines_by_order[oid] = o
        return o

    # regular orders
    for brand in BRAND_IDS:
        for d in daterange(START, B2_END):
            season = 1 + 0.25 * math.sin((d - START).days / 28.0)
            rate = ORDER_RATE[brand] * season
            n = max(0, round(rng.gauss(rate, math.sqrt(rate))))
            for _ in range(n):
                orders[brand].append((d, build_order(brand, d)))
    # sample orders (all amounts 0.00)
    for s in samples:
        if s["ship"] <= B2_END and s["cid"] != "cr_0999":
            orders[s["brand"]].append((s["ship"], build_order(s["brand"], s["ship"], sample=s)))

    # planted: aurelle late partial refund (restates September net in batch 2)
    brand = "aurelle"
    atrib = pick_attribution(brand, date(2026, 9, 18))
    while atrib is None or atrib[2] is None or atrib[0].startswith("u_"):
        atrib = pick_attribution(brand, date(2026, 9, 18))
    o = build_order(brand, date(2026, 9, 18), hour=14, minute=0, force_sale=(Decimal("300.00"), Decimal("60.00")),
                    force_attr=atrib, oid="AUPLANT0918001")
    orders[brand].append((date(2026, 9, 18), o))
    lid = o["line_items"][0]["id"]
    returns[brand].append((D(2026, 9, 25, 10, 0), make_return("RET-AU-LATE", o["order_id"], lid, "REQUESTED", None,
                                                              D(2026, 9, 25, 10, 0), None, D(2026, 9, 25, 10, 0))))
    returns[brand].append((D(2026, 10, 17, 11, 0), make_return("RET-AU-LATE", o["order_id"], lid, "COMPLETED", "60.00",
                                                               D(2026, 9, 25, 10, 0), D(2026, 10, 17, 11, 0),
                                                               D(2026, 10, 17, 11, 0))))
    # planted: Sep 30 23:30 PT (= Oct 1 06:30 UTC) belongs to September
    o = build_order(brand, date(2026, 9, 30), hour=23, minute=30, force_sale=(Decimal("85.00"), Decimal("0.00")),
                    oid="AUTZ0930233001")
    orders[brand].append((date(2026, 9, 30), o))
    return orders, affs, returns


# ------------------------------------------------------------------ writers
def month_file_key(d: date):
    return f"{d.year}-{d.month:02d}"


def month_src_updated(month_key: str, batch: int) -> str:
    y, m = int(month_key[:4]), int(month_key[5:])
    if (y, m) == (2026, 10):
        return "2026-10-15T07:00:00Z" if batch == 1 else "2026-10-22T07:00:00Z"
    ny, nm = (y, m + 1) if m < 12 else (y + 1, 1)
    return f"{ny}-{nm:02d}-01T02:00:00Z"


def month_bounds(key: str, batch: int):
    y, m = int(key[:4]), int(key[5:])
    start = date(y, m, 1)
    end = (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))
    if (y, m) == (2026, 10):
        if batch == 1:
            return start, B1_END
        return B1_END + timedelta(days=1), B2_END
    return start, end


def write_batches(creators, slots, videos, samples, orders, affs, returns):
    b1 = os.path.join(ROOT, "batch_1")
    b2 = os.path.join(ROOT, "batch_2")
    m1 = Manifest("batch_1", "2026-10-15T23:59:59-07:00", "2026-10-15")
    m2 = Manifest("batch_2", "2026-10-22T23:59:59-07:00", "2026-10-22")

    def batch_of(d: date):
        return 1 if d <= B1_END else 2

    # ---- orders / affiliate_orders / returns (monthly files; October split by batch)
    for brand in BRAND_IDS:
        by = defaultdict(list)
        for d, o in orders[brand]:
            by[(month_file_key(d), batch_of(d))].append(o)
        # changed order in batch 2 (threadline): newer update_time, extra platform discount
        changed = None
        if brand == "threadline":
            cand = [o for d, o in orders[brand] if date(2026, 10, 1) <= d <= B1_END and not o["is_sample_order"]
                    and o["paid_time"] and o["status"] not in ("CANCELLED", "UNPAID")
                    and Decimal(o["line_items"][0]["sale_price"]) > 5]
            old = cand[0]
            import copy
            changed = copy.deepcopy(old)
            ln = changed["line_items"][0]
            ln["platform_discount"] = money(Decimal(ln["platform_discount"]) + Decimal("2.00"))
            ln["sale_price"] = money(Decimal(ln["sale_price"]) - Decimal("2.00"))
            changed["payment"]["sub_total"] = money(sum(Decimal(l["sale_price"]) for l in changed["line_items"]))
            changed["update_time"] = int(D(2026, 10, 18, 10, 0).replace(tzinfo=PT).timestamp())
            by[("2026-10", 2)].append(changed)
            print(f"  changed order (batch 2): {changed['order_id']}")
        keys = sorted(set(k for k in by) | {(month_file_key(date(2026, m, 1)), 1) for m in range(4, 11)}
                      | {("2026-10", 2)})
        for (mk, bt) in keys:
            start, end = month_bounds(mk, bt)
            root, man = (b1, m1) if bt == 1 else (b2, m2)
            src = month_src_updated(mk, bt)
            rel = f"orders/{brand}/{mk}.json"
            lst = sorted(by.get((mk, bt), []), key=lambda o: (o["create_time"], o["order_id"]))
            if brand == "aurelle" and mk == "2026-08" and bt == 1:
                dup = lst[40:52]                    # 12 orders also appear on a second "page"
                write_json(os.path.join(root, rel), {"orders": lst})
                man.add(rel, "orders", brand, start.isoformat(), end.isoformat(), "increment", src)
                rel2 = f"orders/{brand}/{mk}-page2.json"
                write_json(os.path.join(root, rel2), {"orders": dup})
                man.add(rel2, "orders", brand, start.isoformat(), end.isoformat(), "increment", src)
            else:
                write_json(os.path.join(root, rel), {"orders": lst})
                man.add(rel, "orders", brand, start.isoformat(), end.isoformat(), "increment", src)
            # affiliate
            recs = [r for (u, r) in affs[brand] if (month_file_key(u.date()), batch_of(u.date())) == (mk, bt)
                    and u.date() <= B2_END]
            rel = f"affiliate_orders/{brand}/{mk}.json"
            write_json(os.path.join(root, rel), {"records": sorted(recs, key=lambda r: r["affiliate_record_id"])})
            man.add(rel, "affiliate_orders", brand, start.isoformat(), end.isoformat(), "increment", src)
            # returns
            rets = [r for (u, r) in returns[brand] if (month_file_key(u.date()), batch_of(u.date())) == (mk, bt)
                    and u.date() <= B2_END]
            rel = f"returns/{brand}/{mk}.json"
            write_json(os.path.join(root, rel), {"returns": sorted(rets, key=lambda r: (r["update_time"], r["return_id"]))})
            man.add(rel, "returns", brand, start.isoformat(), end.isoformat(), "increment", src)

    # ---- affiliate records of batch-1 orders whose order update falls in batch 2 are placed by update month above.

    # ---- products
    for brand in BRAND_IDS:
        rel = f"products/{brand}.csv"
        rows = [[SHOP[brand], pid, sku, name, f"{price:.2f}", f"{(price * Decimal('0.35')).quantize(Q)}", "1759300000"]
                for pid, sku, name, price in PRODUCTS[brand]]
        write_csv_text(os.path.join(b1, rel), ["shop_id", "product_id", "sku_id", "product_name", "list_price",
                                                "unit_cost", "update_time"], rows)
        m1.add(rel, "products", brand, "2026-04-01", "2026-10-15", "snapshot", "2026-10-15T07:00:00Z")
    # batch 2: verdant products re-sent with a UTF-8 BOM and one unit_cost change
    rel = "products/verdant.csv"
    rows = [[SHOP["verdant"], pid, sku, name, f"{price:.2f}",
             f"{(price * Decimal('0.35')).quantize(Q) + (Decimal('1.00') if i == 0 else 0)}", "1760900000"]
            for i, (pid, sku, name, price) in enumerate(PRODUCTS["verdant"])]
    write_csv_text(os.path.join(b2, rel), ["shop_id", "product_id", "sku_id", "product_name", "list_price",
                                            "unit_cost", "update_time"], rows, bom=True)
    m2.add(rel, "products", "verdant", "2026-04-01", "2026-10-22", "snapshot", "2026-10-22T07:00:00Z")

    # ---- weekly videos
    attributed = defaultdict(lambda: [Decimal("0"), 0])   # (brand, video_id, week_monday) -> [gmv, items]
    sale_by_line = {}
    for brand in BRAND_IDS:
        for d, o in orders[brand]:
            for l in o["line_items"]:
                sale_by_line[(brand, o["order_id"], l["id"])] = (d, o, l)
    for brand in BRAND_IDS:
        for u, r in affs[brand]:
            if not r["content_id"]:
                continue
            d, o, l = sale_by_line[(brand, r["order_id"], r["line_item_id"])]
            if o["paid_time"] is None or o["status"] == "CANCELLED":
                continue
            k = (brand, r["content_id"], monday_of(d))
            attributed[k][0] += Decimal(l["sale_price"])
            attributed[k][1] += 1
    shares = [0.5, 0.25, 0.12, 0.07, 0.04, 0.02]
    vids_by_brand = defaultdict(list)
    for v in videos:
        vids_by_brand[v["brand"]].append(v)
    glow_missing = {date(2026, 8, 31), date(2026, 9, 7)}
    week_rows = {}
    wk = date(2026, 3, 30)
    last_week = date(2026, 10, 12)     # W42 goes to batch 2
    while wk <= last_week:
        for brand in BRAND_IDS:
            rows = []
            for v in sorted(vids_by_brand[brand], key=lambda x: (x["post"], x["id"])):
                k = (wk - monday_of(v["post"].date())).days // 7
                gmv, items = attributed.get((brand, v["id"], wk), [Decimal("0"), 0])
                if not (0 <= k < len(shares)) and items == 0:
                    continue
                views = int(v["views"] * shares[k]) if 0 <= k < len(shares) else 0
                rows.append([v["id"], v["cid"], v["handle"], v["post"].strftime("%Y-%m-%dT%H:%M:%S"), v["product"],
                             views, float(gmv), items])
            week_rows[(brand, wk)] = rows
        wk += timedelta(days=7)
    for (brand, wk), rows in sorted(week_rows.items()):
        if brand == "glowhaus" and wk in glow_missing:
            continue                                   # planted gap: two weekly files never delivered
        we = wk + timedelta(days=6)
        lab = iso_week_label(wk)
        rel = f"videos/{brand}/{lab}.xlsx"
        if wk == last_week:
            write_video_xlsx(os.path.join(b2, rel), BRAND_NAME[brand], lab, wk, we, VIDEO_HEADER_V2, rows)
            m2.add(rel, "videos_weekly", brand, wk.isoformat(), we.isoformat(), "increment", "2026-10-19T03:00:00Z")
        else:
            write_video_xlsx(os.path.join(b1, rel), BRAND_NAME[brand], lab, wk, we, VIDEO_HEADER_V1, rows)
            src = (we + timedelta(days=1)).isoformat() + "T03:00:00Z"
            m1.add(rel, "videos_weekly", brand, wk.isoformat(), we.isoformat(), "increment", src)
    # batch 2: overlapping resend of threadline W41 (different numbers) -> must be quarantined
    wk41 = date(2026, 10, 5)
    rows = [r[:5] + [r[5] + 7] + r[6:] for r in week_rows[("threadline", wk41)]]
    lab = iso_week_label(wk41)
    rel = f"videos/threadline/{lab}.xlsx"
    write_video_xlsx(os.path.join(b2, rel), BRAND_NAME["threadline"], lab, wk41, wk41 + timedelta(days=6),
                     VIDEO_HEADER_V2, rows)
    m2.add(rel, "videos_weekly", "threadline", wk41.isoformat(), (wk41 + timedelta(days=6)).isoformat(),
           "increment", "2026-10-19T03:00:00Z")

    # batch 2: orders file for verdant with 4 orders, ONE without order_id: that row is left out, the file loads (amendment 4)
    pv = PRODUCTS["verdant"][0]
    extra = [make_order(f"VX-{i}", SHOP["verdant"], "DELIVERED", D(2026, 10, 16 + i, 10, 0), D(2026, 10, 16 + i, 10, 5),
                        D(2026, 10, 18 + i, 9, 0), [make_line(f"VX-{i}-1", pv[0], pv[1], amt, amt)])
             for i, amt in ((0, "38.00"), (1, "22.50"), (2, "41.00"))]
    bad = make_order("X", SHOP["verdant"], "DELIVERED", D(2026, 10, 16, 10, 0), D(2026, 10, 16, 10, 5),
                     D(2026, 10, 17, 9, 0), [make_line("X-1", pv[0], pv[1], "38.00", "38.00")])
    del bad["order_id"]
    extra.insert(1, bad)
    write_json(os.path.join(b2, "orders/verdant/2026-10-extra.json"), {"orders": extra})
    m2.add("orders/verdant/2026-10-extra.json", "orders", "verdant", "2026-10-15", "2026-10-21", "increment",
           "2026-10-22T07:00:00Z")

    # ---- roster
    rrows = []
    for s in slots:
        c = s["creator"]
        rrows.append({"brand_id": s["brand"], "creator_id": c["id"], "handle": c["handle"],
                      "contract_type": "retainer" if s["retainer"] else "affiliate",
                      "monthly_retainer": s["monthly"] if s["retainer"] else None,
                      "posts_per_month": s["posts_pm"], "effective_from": s["eff_from"].isoformat(),
                      "effective_to": s["eff_to"].isoformat() if s["eff_to"] else None, "status": s["status"],
                      "allocation_share": s["share"]})
    write_roster_xlsx(os.path.join(b1, "roster/roster.xlsx"), rrows)
    m1.add("roster/roster.xlsx", "roster", "all", "2026-04-01", "2026-10-15", "snapshot", "2026-10-15T07:00:00Z")

    # ---- samples (snapshots; batch 2 is a newer full snapshot)
    write_samples_xlsx(os.path.join(b1, "samples/samples.xlsx"), render_samples(samples, date(2026, 10, 15)))
    m1.add("samples/samples.xlsx", "samples", "all", "2026-04-01", "2026-10-15", "snapshot", "2026-10-15T07:00:00Z")
    write_samples_xlsx(os.path.join(b2, "samples/samples.xlsx"), render_samples(samples, date(2026, 10, 22)))
    m2.add("samples/samples.xlsx", "samples", "all", "2026-04-01", "2026-10-22", "snapshot", "2026-10-22T07:00:00Z")

    # ---- plans (October 2026)
    targets = {"aurelle": (14000, 14, 7), "verdant": (11000, 18, 8), "crunchwell": (16000, 30, 9),
               "threadline": (13000, 14, 7), "glowhaus": (10000, 12, 6)}
    for brand in BRAND_IDS:
        g, v, a = targets[brand]
        goals = [
            {"metric_key": "gmv", "scope": "shop" if brand in ("aurelle", "glowhaus") else "creator_attributed",
             "basis": "gross" if brand in ("aurelle", "glowhaus") else "net",
             "definition": "Shop-wide paid-item GMV for the month" if brand in ("aurelle", "glowhaus")
             else "Creator-attributed GMV net of completed refunds", "target": g},
            {"metric_key": "videos", "scope": "creator_attributed", "basis": "gross",
             "definition": "Qualifying videos published in the month", "target": v},
            {"metric_key": "active_creators", "scope": "creator_attributed", "basis": "gross",
             "definition": "Creators with at least one qualifying video in the month", "target": a},
        ]
        write_json(os.path.join(b1, f"plans/{brand}.json"), {"brand_id": brand, "month": "2026-10", "goals": goals})
        m1.add(f"plans/{brand}.json", "plans", brand, "2026-10-01", "2026-10-31", "snapshot", "2026-10-15T07:00:00Z")

    m1.write(b1)
    m2.write(b2)


def main():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)
    os.makedirs(ROOT)
    creators = build_creators()
    slots = build_slots(creators)
    videos, add_video = build_videos(slots)
    samples = build_samples(slots, videos, add_video)
    orders, affs, returns = generate_orders(slots, videos, samples)
    write_batches(creators, slots, videos, samples, orders, affs, returns)
    golden_cases.build(ROOT)
    n_orders = sum(len(v) for v in orders.values())
    print(f"creators={len(creators)} roster_rows={len(slots)} videos={len(videos)} samples={len(samples)} orders={n_orders}")
    files = sum(len(fs) for _, _, fs in os.walk(ROOT))
    print(f"files written under {ROOT}: {files}")


if __name__ == "__main__":
    main()
