"""Rebuild Silver from accepted Bronze, deterministically, in one transaction (caller owns the transaction).

Rules: newest version wins (row update_time, then file src_updated_at; snapshots by snapshot time), never
arrival order. Unorderable differing ties -> quality_issue 'version_conflict' (deterministic pick by file id).
Snapshots deactivate keys missing from the newest snapshot of their group. Cross-source orphans are
quality issues, never silent drops.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import psycopg

from .entity import CreatorIndex, blank
from .parsers import canonicalize, row_hash

BRANDS = [
    ("aurelle", "shop_aurelle", "Aurelle Jewelry"),
    ("verdant", "shop_verdant", "Verdant Skincare"),
    ("crunchwell", "shop_crunchwell", "Crunchwell Snacks"),
    ("threadline", "shop_threadline", "Threadline Apparel"),
    ("glowhaus", "shop_glowhaus", "Glowhaus Beauty"),
]
TZ = "America/Los_Angeles"
UTC = dt.timezone.utc
MIN_DT = dt.datetime(1970, 1, 1, tzinfo=UTC)
SILVER_TABLES = [
    "brand", "creator", "creator_alias", "brand_creator", "product", "shop_order", "order_item", "attribution",
    "commission", "refund", "video", "video_snapshot", "sample_shipment", "sample_item", "goal", "contract",
    "contract_allocation",
]


# ----------------------------------------------------------------------------- value helpers
def money(v: Any) -> Decimal | None:
    if blank(v):
        return None
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def integer(v: Any) -> int | None:
    d = money(v)
    return int(d) if d is not None and d == d.to_integral_value() else None


def unix_dt(v: Any) -> dt.datetime | None:
    if blank(v):
        return None
    try:
        return dt.datetime.fromtimestamp(float(v), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse_date(v: Any) -> dt.date | None:
    """ISO date/datetime string, datetime, or Excel serial number."""
    if blank(v):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().replace(".", "", 1).isdigit()):
        n = float(v)
        if 20000 <= n <= 80000:
            return dt.date(1899, 12, 30) + dt.timedelta(days=int(n))
        return None
    s = str(v).strip()
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def local_dt(v: Any, tz: str) -> dt.datetime | None:
    """Parse a post-time (ISO string or datetime); naive values are local to the brand timezone."""
    if blank(v):
        return None
    if isinstance(v, str):
        s = v.strip().replace("Z", "+00:00")
        try:
            d = dt.datetime.fromisoformat(s)
        except ValueError:
            pd = parse_date(v)
            if pd is None:
                return None
            d = dt.datetime(pd.year, pd.month, pd.day)
    elif isinstance(v, dt.datetime):
        d = v
    else:
        pd = parse_date(v)
        if pd is None:
            return None
        d = dt.datetime(pd.year, pd.month, pd.day)
    if d.tzinfo is None:
        d = d.replace(tzinfo=ZoneInfo(tz))
    return d.astimezone(UTC)


def local_date(d: dt.datetime | None, tz: str) -> dt.date | None:
    return d.astimezone(ZoneInfo(tz)).date() if d else None


def boolish(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y")
    return bool(v)


# ----------------------------------------------------------------------------- plumbing
@dataclass
class SrcFile:
    source_file_id: int
    source_type: str
    scope_key: str
    coverage_start: dt.date | None
    coverage_end: dt.date | None
    ts: dt.datetime  # version time of the file
    records: list[tuple[int, dict, str]]  # row_num, payload, row_hash

    @property
    def order(self) -> tuple[dt.datetime, int]:
        return (self.ts, self.source_file_id)


class Issues:
    def __init__(self) -> None:
        self.rows: dict[tuple, tuple] = {}

    def add(self, code: str, entity_ref: str, severity: str, message: str, fid: int | None = None,
            row: int | None = None, brand: str | None = None, source_type: str | None = None) -> None:
        k = (code, entity_ref, fid, row)
        self.rows.setdefault(k, (code, entity_ref, fid, row, brand, source_type, severity, message))


def load_files(conn: psycopg.Connection) -> dict[str, list[SrcFile]]:
    out: dict[str, list[SrcFile]] = defaultdict(list)
    files: dict[int, SrcFile] = {}
    for r in conn.execute(
        "select source_file_id, source_type, scope_key, coverage_start, coverage_end, "
        "coalesce(src_updated_at, ingested_at) from bronze.source_file where status = 'accepted' "
        "order by source_file_id"
    ):
        f = SrcFile(r[0], r[1], r[2], r[3], r[4], r[5], [])
        files[f.source_file_id] = f
        out[f.source_type].append(f)
    with conn.cursor(name="rec_cur") as cur:
        cur.execute(
            "select r.source_file_id, r.row_num, r.payload, r.row_hash from bronze.source_record r "
            "join bronze.source_file f using (source_file_id) where f.status = 'accepted' "
            "order by r.source_file_id, r.row_num"
        )
        for fid, rn, payload, h in cur:
            files[fid].records.append((rn, payload, h))
    return out


def merge_increment(items: Iterable[tuple[Any, tuple, str, Any, int, int]], issues: Issues,
                    code: str, brand_of: Any = None, source_type: str | None = None) -> dict:
    """items: (key, version, row_hash, obj, file_id, row_num). Newest version wins; differing ties -> conflict."""
    best: dict[Any, tuple] = {}
    for key, ver, h, obj, fid, rn in items:
        cur = best.get(key)
        if cur is None:
            best[key] = (ver, h, obj, fid, rn)
            continue
        cver, ch, _, cfid, _ = cur
        if ver == cver and h != ch and fid != cfid:
            issues.add("version_conflict", f"{code}:{'/'.join(map(str, key)) if isinstance(key, tuple) else key}",
                       "suspect", "Two versions with identical timestamps but different content; kept the later file.",
                       fid, rn, brand_of(obj) if brand_of else None, source_type)
        if (ver, fid) > (cver, cfid):
            best[key] = (ver, h, obj, fid, rn)
    return best


def merge_snapshots(items: Iterable[tuple[Any, tuple, Any, str, Any, int, int]], issues: Issues,
                    code: str, source_type: str) -> dict:
    """items: (group, order, key, row_hash, obj, file_id, row_num) -> {key: (obj, active, fid, rn, hash)}."""
    newest: dict[Any, tuple] = {}
    best: dict[Any, tuple] = {}
    rows = list(items)
    for group, order, key, h, obj, fid, rn in rows:
        if group not in newest or order > newest[group]:
            newest[group] = order
        cur = best.get(key)
        if cur is not None and cur[0][0] == order[0] and cur[3] != h and cur[1] != fid:
            issues.add("version_conflict", f"{code}:{key}", "suspect",
                       "Two snapshots with the same as-of time but different content.", fid, rn, None, source_type)
        if cur is None or order > cur[0]:
            best[key] = (order, fid, rn, h, obj, group)
    return {k: (v[4], v[0] == newest[v[5]], v[1], v[2], v[3]) for k, v in best.items()}


def copy_rows(conn: psycopg.Connection, table: str, cols: list[str], rows: list[tuple]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        with cur.copy(f"copy {table} ({', '.join(cols)}) from stdin") as cp:
            for r in rows:
                cp.write_row(r)


def primary_keys(conn: psycopg.Connection) -> dict[str, list[str]]:
    """Natural keys of every Silver table, read once per rebuild (no per-row lookups)."""
    rows = conn.execute(
        "select c.relname, a.attname from pg_index i join pg_class c on c.oid = i.indrelid "
        "join pg_namespace n on n.oid = c.relnamespace "
        "join lateral unnest(i.indkey) with ordinality k(attnum, ord) on true "
        "join pg_attribute a on a.attrelid = c.oid and a.attnum = k.attnum "
        "where n.nspname = 'silver' and i.indisprimary order by c.relname, k.ord").fetchall()
    out: dict[str, list[str]] = defaultdict(list)
    for t, col in rows:
        out[t].append(col)
    return out


def load_table(conn: psycopg.Connection, table: str, cols: list[str], rows: list[tuple], pk: list[str]) -> None:
    """COPY into a temp staging table, then INSERT .. SELECT DISTINCT ON (natural key) newest first .. ON CONFLICT."""
    if not rows:
        return
    stg = f"_stg_{table}"
    clist = ", ".join(cols)
    conn.execute(f"create temp table {stg} on commit drop as select {clist} from silver.{table} with no data")
    copy_rows(conn, stg, cols, rows)
    pkl = ", ".join(pk)
    order = [pk_c for pk_c in pk]
    if "src_updated_at" in cols:
        order.append("src_updated_at desc nulls last")
    order += ["source_file_id desc", "row_num desc"]
    rest = [c for c in cols if c not in pk]
    upd = ", ".join(f"{c} = excluded.{c}" for c in rest)
    conn.execute(
        f"insert into silver.{table} ({clist}) select distinct on ({pkl}) {clist} from {stg} "
        f"order by {', '.join(order)} on conflict ({pkl}) do update set {upd}")
    conn.execute(f"drop table {stg}")


# ----------------------------------------------------------------------------- the rebuild
def rebuild_silver(conn: psycopg.Connection) -> dict[str, int]:
    issues = Issues()
    files = load_files(conn)
    brand_tz = {b[0]: TZ for b in BRANDS}
    shop_brand = {b[1]: b[0] for b in BRANDS}
    brand_shop = {b[0]: b[1] for b in BRANDS}

    def tz_for_shop(shop: str) -> str:
        return brand_tz.get(shop_brand.get(shop, ""), TZ)

    def shop_for_scope(scope: str) -> str:
        return brand_shop.get(scope, scope)

    idx = CreatorIndex()

    # ---- observe creator ids/handles from every source
    for f in files.get("roster", []):
        for rn, p, h in f.records:
            c = canonicalize("roster", p)
            idx.see(c.get("creator_id"), c.get("handle"), f.ts)
    for f in files.get("videos_weekly", []):
        for rn, p, h in f.records:
            c = canonicalize("videos_weekly", p)
            idx.see(c.get("creator_id"), c.get("creator_handle"), f.ts)
    for f in files.get("affiliate_orders", []):
        for rn, p, h in f.records:
            idx.see(p.get("creator_user_id"), p.get("creator_handle"), f.ts)
    for f in files.get("samples", []):
        for rn, p, h in f.records:
            c = canonicalize("samples", p)
            idx.see(c.get("creator_id"), c.get("creator_handle"), f.ts)

    def resolve(cid: Any, handle: Any, source_type: str, fid: int, rn: int, brand: str | None) -> str | None:
        r = idx.resolve(cid, handle)
        if r is None:
            ref = str(handle).strip() if not blank(handle) else "(no creator id or handle)"
            code = "creator_ambiguous" if idx.is_ambiguous(handle) else "creator_unresolved"
            issues.add(code, ref, "warn", f"{source_type} row has no resolvable creator id", fid, rn, brand, source_type)
        return r

    out: dict[str, list[tuple]] = {t: [] for t in SILVER_TABLES}

    # ---- brand (reference config)
    for b, shop, name in BRANDS:
        out["brand"].append((b, shop, name, TZ, "USD", None, None, row_hash({"b": b, "s": shop, "n": name})))

    # ---- orders
    order_items = []
    for f in files.get("orders", []):
        for rn, p, h in f.records:
            ver = (unix_dt(p.get("update_time")) or MIN_DT, f.ts)
            order_items.append(((p["shop_id"], str(p["order_id"])), ver, h, p, f.source_file_id, rn))
    orders = merge_increment(order_items, issues, "order", lambda o: shop_brand.get(o["shop_id"]), "orders")
    order_line_keys: set[tuple] = set()
    line_paid: dict[tuple, Decimal | None] = {}
    for (shop, oid), (ver, h, p, fid, rn) in sorted(orders.items()):
        tz = tz_for_shop(shop)
        if shop not in shop_brand:
            issues.add("unknown_shop", shop, "warn", f"order {oid} has unknown shop_id", fid, rn, None, "orders")
        paid = unix_dt(p.get("paid_time"))
        is_sample = boolish(p.get("is_sample_order"))
        cur = (p.get("payment") or {}).get("currency")
        if cur and cur != "USD":
            issues.add("currency_mismatch", f"{shop}:{oid}", "warn", f"currency {cur}", fid, rn, shop_brand.get(shop), "orders")
        out["shop_order"].append((shop, oid, paid, local_date(paid, tz), str(p["status"]).upper(), is_sample,
                                  unix_dt(p.get("update_time")), str(cur).strip().upper() if cur else None, fid, rn, h))
        seen: set[str] = set()
        for li in p["line_items"]:
            lid = str(li["id"])
            if lid in seen:
                issues.add("duplicate_line", f"{shop}:{oid}:{lid}", "warn", "duplicate line id in order", fid, rn,
                           shop_brand.get(shop), "orders")
                continue
            seen.add(lid)
            amt = money(li.get("sale_price"))
            if li.get("sale_price") not in (None, "") and amt is None:
                issues.add("bad_amount", f"{shop}:{oid}:{lid}", "warn", "unparseable sale_price", fid, rn,
                           shop_brand.get(shop), "orders")
            if amt is not None and amt < 0:
                issues.add("negative_amount", f"{shop}:{oid}:{lid}", "suspect", "negative sale_price", fid, rn,
                           shop_brand.get(shop), "orders")
            st = li.get("display_status")
            out["order_item"].append((shop, oid, lid, str(li["product_id"]), amt,
                                      str(st).upper() if st else None, is_sample, fid, rn, h))
            order_line_keys.add((shop, oid, lid))
            line_paid[(shop, oid, lid)] = amt

    # ---- affiliate attribution + commission
    aff_items = []
    for f in files.get("affiliate_orders", []):
        shop = shop_for_scope(f.scope_key)
        for rn, p, h in f.records:
            ver = (unix_dt(p.get("update_time")) or MIN_DT, f.ts)
            aff_items.append(((shop, str(p["affiliate_record_id"])), ver, h, (p, shop), f.source_file_id, rn))
    affs = merge_increment(aff_items, issues, "affiliate", lambda o: shop_brand.get(o[1]), "affiliate_orders")
    for (shop, rid), (ver, h, (p, _), fid, rn) in sorted(affs.items()):
        brand = shop_brand.get(shop)
        creator = resolve(p.get("creator_user_id"), p.get("creator_handle"), "affiliate_orders", fid, rn, brand)
        oid, lid = str(p["order_id"]), str(p["line_item_id"])
        if (shop, oid, lid) not in order_line_keys:
            issues.add("orphan_attribution", f"{shop}:{oid}:{lid}", "warn", "affiliate record has no matching order line",
                       fid, rn, brand, "affiliate_orders")
        vid = None if blank(p.get("content_id")) else str(p["content_id"])
        ctype = None if blank(p.get("content_type")) else str(p["content_type"]).lower()
        out["attribution"].append((shop, rid, oid, lid, creator, None if blank(p.get("creator_handle")) else str(p["creator_handle"]),
                                   vid, ctype, unix_dt(p.get("update_time")), fid, rn, h))
        cs = str(p.get("commission_status") or "").lower()
        if cs in ("pending", "settled"):
            amt = money(p.get("commission_amount"))
            out["commission"].append((shop, rid, rid, money(p.get("commission_rate")), amt, cs, fid, rn, h))
        else:
            issues.add("bad_commission_status", f"{shop}:{rid}", "warn", f"commission_status {cs!r}", fid, rn, brand, "affiliate_orders")

    # ---- returns / refunds
    ret_items = []
    for f in files.get("returns", []):
        shop = shop_for_scope(f.scope_key)
        for rn, p, h in f.records:
            ver = (unix_dt(p.get("update_time")) or MIN_DT, f.ts)
            ret_items.append(((shop, str(p["return_id"]), str(p["line_item_id"])), ver, h, (p, shop), f.source_file_id, rn))
    rets = merge_increment(ret_items, issues, "return", lambda o: shop_brand.get(o[1]), "returns")
    for (shop, rid, lid), (ver, h, (p, _), fid, rn) in sorted(rets.items()):
        brand = shop_brand.get(shop)
        tz = tz_for_shop(shop)
        oid = str(p["order_id"])
        rs = str(p["return_status"]).upper()
        merch = money(p.get("refund_subtotal"))
        completed = unix_dt(p.get("completed_time"))
        if rs == "COMPLETED":
            status = "completed" if merch is not None else "partial"
            if completed is None:
                issues.add("refund_missing_completed_time", f"{shop}:{rid}", "suspect",
                           "completed refund without completed_time", fid, rn, brand, "returns")
        elif rs == "REQUESTED":
            status = "requested"
        elif rs == "REJECTED":
            status = "rejected"
        else:
            issues.add("bad_return_status", f"{shop}:{rid}", "warn", f"return_status {rs!r}", fid, rn, brand, "returns")
            continue
        if (shop, oid, lid) not in order_line_keys:
            issues.add("orphan_refund", f"{shop}:{oid}:{lid}", "warn", "return has no matching order line",
                       fid, rn, brand, "returns")
        paid = line_paid.get((shop, oid, lid))
        if merch is not None and paid is not None and merch > paid and status == "completed":
            issues.add("refund_exceeds_paid", f"{shop}:{rid}", "suspect", f"refund {merch} > paid {paid}", fid, rn, brand, "returns")
        out["refund"].append((shop, rid, lid, oid, merch, money(p.get("refund_tax")), status, completed,
                              local_date(completed, tz), unix_dt(p.get("update_time")), fid, rn, h))

    # ---- products (snapshot per shop)
    items = []
    for f in files.get("products", []):
        shop0 = shop_for_scope(f.scope_key)
        for rn, p, h in f.records:
            c = canonicalize("products", p)
            shop = str(c["shop_id"]).strip() if not blank(c.get("shop_id")) else shop0
            items.append((shop0, f.order, (shop, str(c["product_id"]).strip()), h, c, f.source_file_id, rn))
    for (shop, pid), (c, active, fid, rn, h) in sorted(merge_snapshots(items, issues, "product", "products").items()):
        out["product"].append((shop, pid, None if blank(c.get("sku_id")) else str(c["sku_id"]),
                               None if blank(c.get("product_name")) else str(c["product_name"]),
                               money(c.get("list_price")), money(c.get("unit_cost")), active, fid, rn, h))

    # ---- roster (snapshot) -> brand_creator, contract, allocation
    items = []
    for f in files.get("roster", []):
        for rn, p, h in f.records:
            c = canonicalize("roster", p)
            items.append(("all", f.order, (str(c["brand_id"]).strip(), str(c["creator_id"]).strip()), h, c, f.source_file_id, rn))
    roster = merge_snapshots(items, issues, "roster", "roster")
    groups: dict[tuple, list] = defaultdict(list)
    for (brand, cid), (c, active, fid, rn, h) in sorted(roster.items()):
        ctype = None if blank(c.get("contract_type")) else str(c["contract_type"]).strip().lower()
        eff_from, eff_to = parse_date(c.get("effective_from")), parse_date(c.get("effective_to"))
        retainer = money(c.get("monthly_retainer"))
        out["brand_creator"].append((brand, cid, active, None if blank(c.get("handle")) else str(c["handle"]).strip(),
                                     ctype, None if blank(c.get("status")) else str(c["status"]).strip(),
                                     eff_from, eff_to, fid, rn, h))
        if ctype == "retainer":
            groups[(cid, eff_from)].append((brand, c, retainer, eff_to, fid, rn, h))
    for (cid, eff_from), rows in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or dt.date.min)):
        contract_id = f"{cid}:{eff_from or 'open'}"
        retainers = {r[2] for r in rows if r[2] is not None}
        if len(retainers) > 1:
            issues.add("contract_conflict", contract_id, "suspect", f"different retainers across brands: {sorted(retainers)}",
                       rows[0][4], rows[0][5], rows[0][0], "roster")
        retainer = max(retainers) if retainers else None
        ppm = next((integer(r[1].get("posts_per_month")) for r in rows if integer(r[1].get("posts_per_month")) is not None), None)
        eff_to = next((r[3] for r in rows if r[3] is not None), None)
        first = rows[0]
        out["contract"].append((contract_id, cid, retainer, ppm, eff_from, eff_to, first[4], first[5], first[6]))
        for brand, c, _, _, fid, rn, h in rows:
            share = money(c.get("allocation_share"))
            if share is None and len(rows) == 1:
                share = Decimal(1)
            if share is None:
                issues.add("unknown_allocation", f"{contract_id}:{brand}", "warn",
                           "multi-brand retainer without allocation share", fid, rn, brand, "roster")
            out["contract_allocation"].append((contract_id, brand, share, fid, rn, h))
        shares = [money(r[1].get("allocation_share")) for r in rows]
        if len(rows) > 1 and all(s is not None for s in shares) and sum(shares) != 1:
            issues.add("allocation_sum", contract_id, "warn", f"allocation shares sum to {sum(shares)}", first[4], first[5], None, "roster")  # shared across brands: brand NULL

    # ---- attribution creator ids that are not on the brand roster (ruling 1): one issue per (brand, raw id)
    seen_off_roster: set[tuple] = set()
    for (shop, rid), (ver, h, (p, _), fid, rn) in sorted(affs.items()):
        brand = shop_brand.get(shop)
        cid = None if blank(p.get("creator_user_id")) else str(p["creator_user_id"]).strip()
        if cid and (brand, cid) not in roster and (brand, cid) not in seen_off_roster:
            seen_off_roster.add((brand, cid))
            raw = cid + (f" ({str(p['creator_handle']).strip()})" if not blank(p.get("creator_handle")) else "")
            issues.add("creator_not_on_roster", f"{brand}:{raw}", "warn",
                       "Attribution creator id is not on the brand roster; GMV kept in the creator_unresolved bucket.",
                       fid, rn, brand, "affiliate_orders")

    # ---- videos (weekly increments)
    vid_items = []
    snap_items = []
    for f in files.get("videos_weekly", []):
        brand = f.scope_key
        tz = brand_tz.get(brand, TZ)
        seen_in_file: set[str] = set()
        for rn, p, h in f.records:
            c = canonicalize("videos_weekly", p)
            vid = str(c["video_id"]).strip()
            if vid in seen_in_file:
                issues.add("duplicate_row", f"{brand}:{vid}", "warn", "video repeated within one weekly file", f.source_file_id, rn, brand, "videos_weekly")
                continue
            seen_in_file.add(vid)
            pub = local_dt(c.get("post_time"), tz)
            if pub is None:
                issues.add("bad_post_time", f"{brand}:{vid}", "warn", f"unparseable Post Time {c.get('post_time')!r}", f.source_file_id, rn, brand, "videos_weekly")
            vid_items.append(((brand, vid), f.order, h, (c, pub, tz), f.source_file_id, rn))
            snap_items.append(((brand, vid, f.coverage_start), f.order, h, (c, f), f.source_file_id, rn))
    vids = merge_increment(vid_items, issues, "video", lambda o: None, "videos_weekly")
    for (brand, vid), (ver, h, (c, pub, tz), fid, rn) in sorted(vids.items()):
        creator = resolve(c.get("creator_id"), c.get("creator_handle"), "videos_weekly", fid, rn, brand)
        out["video"].append((brand, vid, creator, None if blank(c.get("creator_handle")) else str(c["creator_handle"]).strip(),
                             None if blank(c.get("product_id")) else str(c["product_id"]).strip(),
                             pub, local_date(pub, tz), fid, rn, h))
    snaps = merge_increment(snap_items, issues, "video_snapshot", lambda o: None, "videos_weekly")
    for (brand, vid, ps), (ver, h, (c, f), fid, rn) in sorted(snaps.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        out["video_snapshot"].append((brand, vid, ps, f.coverage_end, integer(c.get("views")), money(c.get("gmv")),
                                      integer(c.get("items_sold")), f.ts, fid, rn, h))

    # ---- samples (snapshot)
    items = []
    for f in files.get("samples", []):
        line_no: dict[tuple, int] = defaultdict(int)
        for rn, p, h in f.records:
            c = canonicalize("samples", p)
            brand, ship = str(c["brand_id"]).strip(), str(c["shipment_id"]).strip()
            line_no[(brand, ship)] += 1
            items.append(("all", f.order, (brand, ship, line_no[(brand, ship)]), h, c, f.source_file_id, rn))
    samples = merge_snapshots(items, issues, "sample", "samples")
    shipments: dict[tuple, dict] = {}
    for (brand, ship, ln), (c, active, fid, rn, h) in sorted(samples.items()):
        if (brand, ship) not in shipments:
            tz_ = brand_tz.get(brand, TZ)
            creator = resolve(c.get("creator_id"), c.get("creator_handle"), "samples", fid, rn, brand)
            raw_cid = None if blank(c.get("creator_id")) else str(c["creator_id"]).strip()
            if raw_cid and (brand, raw_cid) not in roster:
                issues.add("creator_not_on_roster", f"{brand}:{raw_cid}", "warn",
                           f"Sample shipment {ship} names creator {raw_cid}, who is not on the {brand} roster.",
                           fid, rn, brand, "samples")
            shipments[(brand, ship)] = dict(creator=creator, handle=None if blank(c.get("creator_handle")) else str(c["creator_handle"]).strip(),
                                            shipped=parse_date(c.get("shipped_date")), delivered=parse_date(c.get("delivered_date")),
                                            status=None if blank(c.get("status_text")) else str(c["status_text"]).strip(),
                                            ship_cost=money(c.get("shipping_cost")), active=active, fid=fid, rn=rn, h=h)
            for k in ("shipped_date", "delivered_date"):
                if not blank(c.get(k)) and parse_date(c.get(k)) is None:
                    issues.add("bad_date", f"{brand}:{ship}", "warn", f"unparseable {k} {c.get(k)!r}", fid, rn, brand, "samples")
        else:
            s = shipments[(brand, ship)]
            s["active"] = s["active"] or active
            if s["ship_cost"] is None:
                s["ship_cost"] = money(c.get("shipping_cost"))
        out["sample_item"].append((brand, ship, ln, None if blank(c.get("product_id")) else str(c["product_id"]).strip(),
                                   integer(c.get("qty")), None if blank(c.get("linked_video_id")) else str(c["linked_video_id"]).strip(),
                                   active, fid, rn, h))
    for (brand, ship), s in sorted(shipments.items()):
        out["sample_shipment"].append((brand, ship, s["creator"], s["handle"], s["shipped"], s["delivered"], s["status"],
                                       s["ship_cost"], s["active"], s["fid"], s["rn"], s["h"]))

    # ---- plans (snapshot per brand+month)
    items = []
    for f in files.get("plans", []):
        for rn, p, h in f.records:
            month = parse_date(str(p["month"]) + "-01") if len(str(p["month"])) == 7 else parse_date(p["month"])
            if month is None:
                issues.add("bad_month", str(p["month"]), "warn", "plan month unparseable", f.source_file_id, rn, p["brand_id"], "plans")
                continue
            month = month.replace(day=1)
            key = (str(p["brand_id"]), month, str(p["metric_key"]), str(p["scope"]))
            items.append(((key[0], month), f.order, key, h, p, f.source_file_id, rn))
    for (brand, month, mk, scope), (p, active, fid, rn, h) in sorted(merge_snapshots(items, issues, "goal", "plans").items()):
        out["goal"].append((brand, month, mk, scope, str(p["basis"]).lower(), "v1",
                            None if blank(p.get("definition")) else str(p["definition"]), money(p["target"]), active, fid, rn, h))

    # ---- creators / aliases
    for cid, ts in sorted(idx.ids.items()):
        out["creator"].append((cid, idx.latest_handle(cid), None, None, row_hash({"c": cid})))
    for r in idx.alias_rows():
        out["creator_alias"].append((*r, None, None, row_hash(list(map(str, r)))))

    # ---- write
    conn.execute("truncate " + ", ".join(f"silver.{t}" for t in SILVER_TABLES))
    conn.execute("delete from meta.quality_issue where origin = 'silver'")
    cols = {
        "brand": "brand_id, shop_id, name, reporting_tz, currency, source_file_id, row_num, row_hash",
        "creator": "creator_id, handle, source_file_id, row_num, row_hash",
        "creator_alias": "namespace, alias_norm, valid_from, creator_id, reviewed, n_creators, source_file_id, row_num, row_hash",
        "brand_creator": "brand_id, creator_id, roster_active, handle, contract_type, status, effective_from, effective_to, source_file_id, row_num, row_hash",
        "product": "shop_id, product_id, sku_id, name, list_price, unit_cost, active, source_file_id, row_num, row_hash",
        "shop_order": "shop_id, order_id, paid_at, paid_local_date, status, is_sample, src_updated_at, currency, source_file_id, row_num, row_hash",
        "order_item": "shop_id, order_id, line_id, product_id, paid_amount, item_status, is_sample, source_file_id, row_num, row_hash",
        "attribution": "shop_id, affiliate_record_id, order_id, line_id, creator_id, creator_handle, video_id, content_type, src_updated_at, source_file_id, row_num, row_hash",
        "commission": "shop_id, commission_id, affiliate_record_id, rate, amount, status, source_file_id, row_num, row_hash",
        "refund": "shop_id, refund_id, line_id, order_id, merch_amount, tax_amount, status, completed_at, completed_local_date, src_updated_at, source_file_id, row_num, row_hash",
        "video": "brand_id, video_id, creator_id, creator_handle, product_id, published_at, published_local_date, source_file_id, row_num, row_hash",
        "video_snapshot": "brand_id, video_id, period_start, period_end, views, gmv_reported, items_sold, observed_at, source_file_id, row_num, row_hash",
        "sample_shipment": "brand_id, shipment_id, creator_id, creator_handle, shipped_at, delivered_at, status_text, shipping_cost, active, source_file_id, row_num, row_hash",
        "sample_item": "brand_id, shipment_id, line_no, product_id, qty, linked_video_id, active, source_file_id, row_num, row_hash",
        "goal": "brand_id, month, metric_key, scope, basis, definition_version, definition, target_value, active, source_file_id, row_num, row_hash",
        "contract": "contract_id, creator_id, monthly_retainer, posts_per_month, effective_from, effective_to, source_file_id, row_num, row_hash",
        "contract_allocation": "contract_id, brand_id, share, source_file_id, row_num, row_hash",
    }
    pks = primary_keys(conn)
    for t in SILVER_TABLES:
        load_table(conn, t, [c.strip() for c in cols[t].split(",")], out[t], pks[t])
    copy_rows(conn, "meta.quality_issue",
              ["code", "entity_ref", "source_file_id", "row_num", "brand_id", "source_type", "severity", "message", "origin"],
              [(*v[:6][0:6], v[6], v[7], "silver") for v in issues.rows.values()])
    counts = {t: len(out[t]) for t in SILVER_TABLES}
    counts["quality_issues"] = len(issues.rows)
    return counts
