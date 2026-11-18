"""Wording layer: internal codes, field names and status text -> plain business English.

Everything operators read (status reasons, notes, evidence text, column labels) passes through here.
`humanize(code, ctx)` maps one internal code; `plain_text(text, ctx)` rewrites a generated sentence;
`apply(data, repo)` is the API boundary: it rewrites every reason-like field of a response in place.
An unknown code gets a generic sentence and a log entry (never the raw code).
"""
from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("darkroom.presentation")

GENERIC = "Some details are not available for this item yet."

# ---------------------------------------------------------------- nouns
SOURCE_NOUN = {
    "orders": "orders", "affiliate_orders": "creator-attributed orders", "returns": "returns",
    "videos_weekly": "weekly video reports", "samples": "sample shipments", "roster": "creator roster",
    "plans": "goal plan", "products": "product list",
}
SOURCE_TITLE = {k: v[:1].upper() + v[1:] for k, v in SOURCE_NOUN.items()}
WEEKLY = {"videos_weekly"}

FIELD_NOUN = {  # field / column name -> plain noun
    "order_id": "order number", "line_id": "order line", "line_item_id": "order line", "shop_id": "shop",
    "creator_id": "creator", "creator_user_id": "creator", "creator_handle": "creator", "creator_raw": "creator as written in the order",
    "video_id": "video", "content_id": "video", "shipment_id": "shipment", "sample_id": "sample", "brand_id": "brand",
    "product_id": "product", "affiliate_record_id": "affiliate record", "refund_id": "refund", "return_id": "return",
    "goal_id": "goal", "paid_amount": "amount paid", "paid_at": "payment time", "created_at": "created time",
    "gmv": "sales", "net": "net sales", "refunded": "refunded amount", "amount": "amount", "currency": "currency",
    "source_file": "source file", "source_locator": "place in the file", "row_num": "row number",
    "order_status": "order status", "item_status": "item status", "is_sample": "free sample", "eligible": "counted",
    "bucket": "attribution group", "month": "month", "local_date": "date", "paid_local_date": "payment date",
    "published_at": "publish time", "published_local_date": "publish date", "qualifies": "counts as a video",
    "views_total": "views", "state": "status", "status": "status", "handle": "creator", "product_sku": "product",
    "sent_date": "sent date", "delivered_date": "delivered date", "matched_video_id": "matched video",
    "delivery_to_video_days": "days from delivery to video", "mature": "old enough to judge", "qty": "quantity",
    "monthly_retainer": "monthly retainer", "posts_per_month": "posts per month", "content_type": "content type",
    "video_known": "video found", "refund_state": "refund status", "exclusion_reason": "why it was left out",
    "disqualify_reason": "why it does not count", "creator_resolved": "creator on the roster",
    "component": "cost item", "n_snapshots": "weekly reports", "gmv_reported_total": "reported sales",
    "affiliate_orders": "creator-attributed orders", "videos_weekly": "weekly video reports",
}
COLUMN_LABEL = {  # evidence table column labels (title case)
    "order_id": "Order number", "line_id": "Order line", "shop_id": "Shop", "product_id": "Product", "creator_id": "Creator",
    "video_id": "Video", "brand_id": "Brand", "paid_amount": "Amount paid", "gmv": "Sales (USD)", "net": "Net sales (USD)",
    "refunded": "Refunded (USD)", "amount": "Amount (USD)", "currency": "Currency", "creator_raw": "Creator as written",
    "bucket": "Attribution", "eligible": "Counted", "local_date": "Date", "paid_local_date": "Payment date",
    "month": "Month", "order_status": "Order status", "item_status": "Item status", "is_sample": "Free sample",
    "exclusion_reason": "Why left out", "refund_state": "Refund status", "video_known": "Video found",
    "content_type": "Content type", "affiliate_record_id": "Affiliate record", "paid_at": "Paid at",
    "published_at": "Published at", "published_local_date": "Publish date", "creator_handle": "Creator",
    "qualifies": "Counts as a video", "disqualify_reason": "Why it does not count", "views_total": "Views",
    "gmv_reported_total": "Reported sales (USD)", "n_snapshots": "Weekly reports", "handle": "Creator",
    "sample_id": "Sample", "shipment_id": "Shipment", "product_sku": "Product", "product_name": "Product",
    "qty": "Quantity", "sent_date": "Sent", "delivered_date": "Delivered", "status_text": "Shipping status",
    "state": "Status", "state_reason": "Why", "matched_video_id": "Matched video", "delivery_to_video_days": "Days to video",
    "mature": "Old enough to judge", "days_since_delivery": "Days since delivery", "converted": "Led to a video",
    "in_rate_denominator": "Counted in rate", "as_of": "As of", "component": "Cost item", "row_num": "Row",
    "video_coverage_state": "Video data", "video_coverage_complete": "Video data complete", "line_no": "Line",
    "attribution_row_num": "Attribution row", "attribution_source_file_id": "Attribution file", "source_file_id": "File",
    "creator_id_resolved": "Creator", "status": "Status", "merch_amount": "Refund amount (USD)",
    "completed_at": "Completed", "completed_local_date": "Completed date", "refund_id": "Refund",
}
STATUS_WORD = {"current": "complete", "stale": "stale", "partial": "incomplete", "unavailable": "not available",
               "forecast": "forecast", "missing": "not loaded yet", "incomplete": "incomplete", "suspect": "needs a check"}
STATUS_LABEL = {"current": "Complete", "partial": "Incomplete", "stale": "Stale", "unavailable": "Incomplete",
                "forecast": "Forecast"}
EXCLUSION_NOUN = {
    "not_eligible": "order lines that were cancelled, unpaid or free samples",
    "non_usd_currency": "orders paid in another currency",
    "no_creator_attribution": "order lines with no creator attached",
    "creator_creator_unresolved": "order lines whose creator is not on the roster",
    "creator_unresolved": "order lines whose creator is not on the roster",
    "creator_conflict": "order lines claimed by two creators",
    "other_bucket": "lines in another attribution group", "not_qualifying": "videos with no known creator or publish time",
    "video_known": "lines whose video is already in the video data",
}
ISSUE_SENTENCE = {
    "creator_not_on_roster": "{brand} has orders credited to a creator who is not on its roster; the sales are kept but not attributed to anyone.",
    "file_rejected": "A {source} file for {brand} could not be used, so those figures may be incomplete.",
    "file_quarantined": "A {source} file for {brand} overlaps one already loaded and was set aside to avoid double counting.",
    "rows_excluded": "Some records for {brand} were left out because they could not be identified, so totals may be higher than shown.",
    "currency_mismatch": "{brand} has orders paid in a currency other than US dollars; they are left out of the dollar totals.",
    "conflict": "Two records for {brand} disagree and could not be ordered, so one was left out.",
}
PARSER_REASON = {
    "missing_order_id": "had no order number", "missing_required_field": "were missing a required detail",
    "missing_creator_id": "had no creator", "missing_video_id": "had no video id", "bad_amount": "had an unreadable amount",
    "bad_date": "had an unreadable date",
}
METRIC_NAME = {
    "gmv": "sales", "creator_attributed_gmv": "creator-driven sales", "net_attributed_sales": "creator net sales",
    "creator_net_sales": "creator net sales", "videos": "videos", "creator_videos": "videos", "active_creators": "active creators",
    "sample_conversion_rate": "sample conversion", "creator_sales_after_costs": "sales after costs",
    "goal_projection": "goal projection", "decomposition": "what changed", "creator_concentration": "creator concentration",
    "retainer_cadence": "retainer posting", "portfolio_pacing": "portfolio pace",
}


def humanize(code, ctx: dict | None = None) -> str:
    """Map one internal code to a plain noun or sentence. Unknown codes are logged, never shown raw."""
    ctx = ctx or {}
    c = str(code)
    brand = ctx.get("brand") or "This brand"
    if c in FIELD_NOUN:
        return FIELD_NOUN[c]
    if c in SOURCE_NOUN:
        return SOURCE_NOUN[c]
    if c in STATUS_WORD:
        return STATUS_WORD[c]
    if c in EXCLUSION_NOUN:
        return EXCLUSION_NOUN[c]
    if c in METRIC_NAME:
        return METRIC_NAME[c]
    if c in PARSER_REASON:
        return PARSER_REASON[c]
    if c in ISSUE_SENTENCE:
        return ISSUE_SENTENCE[c].format(brand=brand, source=SOURCE_NOUN.get(ctx.get("source"), "data"))
    log.warning("humanize: unknown code %r", c)
    return GENERIC


def column_label(key: str) -> str:
    if key in COLUMN_LABEL:
        return COLUMN_LABEL[key]
    if key in FIELD_NOUN:
        n = FIELD_NOUN[key]
        return n[:1].upper() + n[1:]
    log.warning("humanize: unknown column %r", key)
    return " ".join(w for w in key.split("_") if w not in ("id", "n", "num")).capitalize() or "Detail"


# ---------------------------------------------------------------- formatting
def fmt_date(v) -> str:
    try:
        d = v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
        return f"{d.strftime('%b')} {d.day}"
    except Exception:
        return "the expected date"


def money_label(v) -> str | None:
    if v is None:
        return None
    return "${:,.2f}".format(Decimal(str(v)))


def count_label(v, unit="") -> str | None:
    if v is None:
        return None
    n = int(Decimal(str(v)))
    return f"{n:,}" + (f" {unit}" if unit else "")


def _state_phrase(state: str) -> str:
    return {"stale": "behind", "partial": "incomplete", "unavailable": "not loaded yet", "incomplete": "incomplete",
            "missing": "not loaded yet", "suspect": "in need of a check"}.get(state, state)


def freshness_reason(brand: str | None, source: str, state: str, n_gaps=0, n_quarantined=0, n_rejected=0,
                     coverage_through=None, expected_through=None) -> str | None:
    """Plain sentence for one brand/source freshness state (None when current)."""
    b = brand or "This brand"
    noun = SOURCE_NOUN.get(source, "data")
    if state == "current":
        return None
    if state == "missing":
        return f"{b} has no {noun} loaded yet."
    if state == "incomplete":
        unit = "weeks" if source in WEEKLY else "days"
        bits = []
        if n_gaps:
            bits.append(f"{n_gaps} {unit[:-1] if n_gaps == 1 else unit} of {noun} {'is' if n_gaps == 1 else 'are'} missing")
        if n_quarantined:
            bits.append(f"{n_quarantined} overlapping {'file was' if n_quarantined == 1 else 'files were'} set aside to avoid double counting")
        if n_rejected:
            bits.append(f"{n_rejected} {'file' if n_rejected == 1 else 'files'} could not be used")
        return f"{b}'s {noun} are incomplete: " + "; ".join(bits) + "." if bits else f"{b}'s {noun} are incomplete."
    if state == "stale":
        if coverage_through and expected_through:
            return f"{b}'s {noun} only go through {fmt_date(coverage_through)}; data through {fmt_date(expected_through)} is expected."
        return f"{b}'s {noun} are behind where they should be."
    if state == "suspect":
        return f"{b}'s {noun} contain an unusual value that needs a check."
    return f"{b}'s {noun} are {_state_phrase(state)}."


# ---------------------------------------------------------------- sentence rewriting
def _items(s: str) -> str:
    out = []
    for part in [p.strip() for p in s.split(",") if p.strip()]:
        out.append({"Retainer cost": "the retainer terms are missing", "Commission cost": "commission records are missing",
                    "Sample cost": "the sample cost is missing"}.get(part, part.lower()))
    return " and ".join(out)


def _rules(ctx):
    b = ctx.get("brand") or "This brand"
    cr = ctx.get("creator") or "This creator"
    return [
        (r"^No accepted (\w+) files$", lambda m: f"{b} has no {SOURCE_NOUN.get(m[1], 'data')} loaded yet."),
        (r"^(\w+): (\d+) coverage gap\(s\), (\d+) quarantined, (\d+) rejected file\(s\)(?:; last error: .*)?$",
         lambda m: freshness_reason(b, m[1], "incomplete", int(m[2]), int(m[3]), int(m[4]))),
        (r"^(\w+) covered through ([\d-]+), expected through ([\d-]+)$",
         lambda m: freshness_reason(b, m[1], "stale", coverage_through=m[2], expected_through=m[3])),
        (r"^(\d+) open anomaly\(ies\) on (\w+)$", lambda m: freshness_reason(b, m[2], "suspect")),
        (r"^(\w+) is (missing|stale|incomplete|suspect) for (\w+)$",
         lambda m: freshness_reason(ctx.get("brand_names", {}).get(m[3]) or b, m[1], m[2])),
        (r"^No covered days in this month$", lambda m: f"{b} has no data for this month yet."),
        (r"^Source coverage has gaps or rejected/quarantined files$", lambda m: f"{b}'s data has gaps or files that could not be used."),
        (r"^no source coverage recorded$", lambda m: "No data has been loaded yet."),
        (r"^unsplit or unknown amounts in included lines$",
         lambda m: f"Some order or refund amounts for {b} are missing, so this total cannot be shown."),
        (r"^no mature observable sample items yet$", lambda m: f"No {b} sample is old enough yet to judge whether it led to a video."),
        (r"^video coverage is incomplete.*$", lambda m: f"{b}'s weekly video reports have gaps, so a sample with no video cannot be told apart from one that has not posted yet."),
        (r"^unknown cost: (.*)$", lambda m: f"{cr}: {_items(m[1])}, so sales after costs cannot be shown."),
        (r"^zero cannot be verified while source coverage is (\w+)$",
         lambda m: f"{b}'s data is {_state_phrase(m[1])}, so a zero cannot be confirmed yet."),
        (r"^value unknown$", lambda m: "This value is not known yet."),
        (r"^source coverage is (\w+)$", lambda m: f"{b}'s data is {_state_phrase(m[1])}."),
        (r"^no target in plan$", lambda m: "No target has been set for this goal."),
        (r"^actual is unknown or stale(?:: (.*))?$", lambda m: f"The figure so far is unknown or out of date for {b}." ),
        (r"^actual is unknown \(.*\)$", lambda m: f"The figure so far for {b} is not known yet."),
        (r"^source is (\w+): .*$", lambda m: f"{b}'s data is {_state_phrase(m[1])}, so no projection is shown."),
        (r"^target is zero$", lambda m: "The target is zero, so progress cannot be worked out."),
        (r"^(?:projection )?unavailable \(coverage gaps or insufficient history\)$",
         lambda m: f"No projection yet: {b} has gaps in its data or too little history."),
        (r"^amount unknown on some lines$", lambda m: f"Some {b} order lines have no amount, so this total cannot be shown."),
        (r"^(.+?) is unknown \(allocation, contract or amount missing\)$",
         lambda m: f"{cr}: the {m[1].lower()} is unknown because the contract, allocation or amount is missing."),
        (r"^goal bases differ.*$", lambda m: "Brands measure this goal in different ways (some before refunds, some after), so the comparison is not shown."),
        (r"^(\d+) brand\(s\) have unknown actuals.*$", lambda m: f"{m[1]} brand{'s' if m[1] != '1' else ''} cannot report this figure yet, so the portfolio total is not shown."),
        (r"^unknown input\(s\): (.*)$", lambda m: f"No recommendation yet because {m[1]} could not be worked out."),
        (r"^unknown from the coverage gap on ([\d-]+)$", lambda m: f"{b}'s data has a gap starting {fmt_date(m[1])}, so figures after it are unknown."),
        (r"^weekly video coverage has gaps or has not reached this day$", lambda m: f"{b}'s weekly video reports have gaps or do not reach this day yet."),
        (r"^creator GMV unknown$", lambda m: f"{b}'s sales for this creator are not known yet."),
        (r"^count unknown$", lambda m: "This count is not known yet."),
        (r"^a brand goal value is unknown.*$", lambda m: "At least one brand's goal figure is unknown, so the portfolio figure is not shown."),
        (r"^a brand has no target.*$", lambda m: "At least one brand has no target, so the portfolio target is not shown."),
        (r"^progress is unknown$", lambda m: "Progress cannot be worked out yet."),
        (r"^no goal in plan$", lambda m: f"{b} has no goal set for this."),
        (r"^no diagnostic period data$", lambda m: f"{b} has no data for one of the two periods being compared."),
        (r"^effects are unknown.*$", lambda m: f"The split into creators, videos and sales per video cannot be worked out for {b}: a figure is missing or there were no active creators in one period."),
        (r"^(\d+) line\(s\) have an unknown amount; value is unknown\.$", lambda m: f"{m[1]} order {'line has' if m[1] == '1' else 'lines have'} no amount, so the total is not shown."),
        (r"^some included lines have an unknown amount.*$", lambda m: "Some lines have no amount, so the total is not shown."),
        (r"^Unknown cost component\(s\): (.*); sales after costs is unknown\.$", lambda m: f"{cr}: {_items(m[1])}, so sales after costs cannot be shown."),
        (r"^(.+?) is unknown; sales after costs is unknown\.$", lambda m: f"{cr}: the {m[1].lower()} is unknown, so sales after costs cannot be shown."),
        (r"^creator not found in creator_performance$", lambda m: "This creator has no record for the month."),
        (r"^zero cannot be.*$", lambda m: "A zero cannot be confirmed while data is incomplete."),
        (r"^At least one required cost is unknown.*$", lambda m: f"{cr}: a cost is unknown, so sales after costs cannot be shown."),
        (r"^no mature.*$", lambda m: "Nothing is old enough to judge yet."),
    ]


_SNAKE = re.compile(r"\b[A-Za-z]+(?:_[A-Za-z0-9]+)+\b")
_BANNED_AFTER = [re.compile(p) for p in (r"\w+\[\d+\]", r"\b(count|sum|avg)\s*\(", r"\bdistinct\b", r"\bUNAVAILABLE\b",
                                          r"\bnull\b", r"\bNone\b", r"\bNaN\b", r"\bundefined\b", r"is required", r"[{}]")]


def _scrub(t: str) -> str:
    t = re.sub(r"; last error:.*$", "", t)
    t = re.sub(r"\b\w+\[\d+\]\s*", "a record ", t)
    t = re.sub(r"\(ies\)", "ies", t)
    t = re.sub(r"\((s|es)\)", r"\1", t)
    t = re.sub(r"\bdistinct\b", "different", t)
    t = re.sub(r"\b(UNAVAILABLE|NaN|undefined|null|None)\b", "not available", t)
    t = t.replace("{", "").replace("}", "")
    t = re.sub(r"\b(count|sum|avg)\s*\(", r"\1 of (", t)
    t = _SNAKE.sub(lambda m: FIELD_NOUN.get(m[0]) or SOURCE_NOUN.get(m[0]) or m[0].replace("_", " "), t)
    return re.sub(r"\s{2,}", " ", t).strip()


def plain_text(text, ctx: dict | None = None) -> str | None:
    """Rewrite one generated sentence into plain English. Unknown shapes are scrubbed, then checked."""
    if text is None:
        return None
    ctx = ctx or {}
    t = str(text).strip()
    if not t:
        return None
    for pat, fn in _rules(ctx):
        m = re.match(pat, t, re.S)
        if m:
            try:
                return fn(m)
            except Exception:
                break
    out = _scrub(t)
    if any(p.search(out) for p in _BANNED_AFTER):
        log.warning("humanize: could not make plain: %r", t)
        return GENERIC
    return out


# ---------------------------------------------------------------- data notes (rows left out)
def note_from_issue(row: dict, brand: str) -> str:
    msg = row.get("message") or ""
    noun = SOURCE_NOUN.get(row.get("source_type"), "records")
    m = re.search(r"(\d+) of (\d+) rows?", msg)
    if m:
        x, y = int(m[1]), int(m[2])
        return (f"{brand}: {x} of {y} {noun if y != 1 else noun.rstrip('s')} in a loaded file {'was' if x == 1 else 'were'} left out because "
                f"{'it' if x == 1 else 'they'} could not be identified, so the real totals may be higher than shown.")
    if msg and "/" not in msg:
        p = plain_text(msg, {"brand": brand})
        if p and p != GENERIC:
            return p
    n = row.get("count") or row.get("n")
    noun = SOURCE_NOUN.get(row.get("source_type"), "records")
    if n:
        return f"{brand}: {n} {noun if n != 1 else noun.rstrip('s')} in loaded files {'was' if n == 1 else 'were'} left out because they could not be identified, so the real totals may be higher than shown."
    return ISSUE_SENTENCE["rows_excluded"].format(brand=brand)


def data_note_for(repo, brand_id, sources) -> str | None:
    """Note when figures are floors because rows were left out; None otherwise."""
    fn = getattr(repo, "excluded_notes", None)
    if fn is None:
        return None
    names = {b["brand_id"]: b["name"] for b in repo.brands()}
    notes = []
    for r in fn():
        if brand_id and r["brand_id"] != brand_id:
            continue
        if sources and r.get("source_type") and r["source_type"] not in sources:
            continue
        notes.append(note_from_issue(r, names.get(r["brand_id"], "This brand")))
    return " ".join(dict.fromkeys(notes)) or None


def names_for(repo, brand_id=None, creator_id=None) -> dict:
    """{'brand': display name, 'creator': handle, 'brand_names': {id: name}} for plain sentences."""
    try:
        bn = {b["brand_id"]: b["name"] for b in repo.brands()}
    except Exception:
        bn = {}
    handle = None
    if creator_id:
        try:
            handle = repo.creator_handles().get(creator_id)
        except Exception:
            handle = None
    return {"brand": bn.get(brand_id), "creator": handle, "brand_names": bn}


# ---------------------------------------------------------------- API boundary
REASON_KEYS = {"status_reason", "incomplete_reason", "unavailable_reason", "plain_reason", "message", "error", "reason_plain"}
LIST_KEYS = {"warnings", "notes"}
OPAQUE_PREFIX = "_"


class Ctx:
    def __init__(self, repo):
        self.repo = repo
        try:
            self.brand_names = {b["brand_id"]: b["name"] for b in repo.brands()}
        except Exception:
            self.brand_names = {}
        try:
            self.handles = repo.creator_handles()
        except Exception:
            self.handles = {}


def _url_params(url) -> dict:
    try:
        return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    except Exception:
        return {}


def _walk(o, cx: Ctx, brand_id=None, creator_id=None):
    from app.metrics.service import SOURCES
    if isinstance(o, list):
        for x in o:
            _walk(x, cx, brand_id, creator_id)
        return
    if not isinstance(o, dict):
        return
    for k in [k for k in o if isinstance(k, str) and k.startswith(OPAQUE_PREFIX)]:
        del o[k]  # internal helper values never leave the API
    bid = o.get("brand_id") if isinstance(o.get("brand_id"), str) else brand_id
    cid = o.get("creator_id") if isinstance(o.get("creator_id"), str) else creator_id
    is_mv = "metric_key" in o and "evidence_url" in o and "status" in o
    if is_mv:
        p = _url_params(o["evidence_url"])
        bid = p.get("brand_id") or bid
        cid = p.get("creator_id") or cid
    ctx = {"brand": cx.brand_names.get(bid), "creator": cx.handles.get(cid), "brand_names": cx.brand_names}
    for k, v in list(o.items()):
        if k in REASON_KEYS and isinstance(v, str):
            o[k] = plain_text(v, ctx)
        elif k in LIST_KEYS and isinstance(v, list):
            o[k] = [plain_text(x, ctx) if isinstance(x, str) else x for x in v]
    if is_mv and "data_note" not in o:
        from app.metrics.service import SOURCES
        srcs = SOURCES.get(o["metric_key"]) or ["orders", "affiliate_orders", "videos_weekly"]
        o["data_note"] = data_note_for(cx.repo, bid, srcs)
    for k, v in o.items():
        if isinstance(v, (dict, list)):
            _walk(v, cx, bid, cid)


def apply(data, repo):
    """Rewrite every operator-visible reason in a response (in place) and add MV data notes."""
    _walk(data, Ctx(repo))
    return data


# ---------------------------------------------------------------- health / goals / attention wording
GOAL_NAME = {("gmv", "shop"): "Total sales", ("gmv", "creator_attributed"): "Creator-driven sales",
             ("videos", None): "Videos", ("active_creators", None): "Active creators"}


def goal_name(metric_key, scope=None, basis=None) -> str:
    n = GOAL_NAME.get((metric_key, scope)) or GOAL_NAME.get((metric_key, None))
    if n is None:
        log.warning("humanize: unknown goal %r", metric_key)
        return "Goal"
    return n + (" (after refunds)" if basis == "net" and metric_key == "gmv" else "")


def failed_file_reason(status, source_type, error, brand=None) -> str:
    noun = SOURCE_NOUN.get(source_type, "data")
    b = f"{brand}'s " if brand else ""
    err = str(error or "")
    m = re.search(r"period ([\d-]+)\.\.([\d-]+) overlaps", err)
    if status == "quarantined" or m:
        span = f" for {fmt_date(m[1])} to {fmt_date(m[2])}" if m else ""
        return f"{b}{noun}{span} overlap data that is already loaded, so the file was set aside to avoid double counting."
    m = re.search(r"missing required field '?(\w+)'?", err)
    if m:
        return f"A {b}{noun} file could not be used because a record had no {FIELD_NOUN.get(m[1], 'required detail')}."
    return f"A {b}{noun} file could not be read, so its data is not included."


def exclusion_file_reason(n, source_type, brand=None) -> str:
    noun = SOURCE_NOUN.get(source_type, "data")
    n = int(n)
    return (f"{n} {'record was' if n == 1 else 'records were'} left out of this {noun} file because "
            f"{'it' if n == 1 else 'they'} could not be identified; the rest of the file was loaded.")


def attention_text(kind, brand, creator, days_waiting=None, since=None, source_type=None, state=None, reason=None):
    """(title, rule, why_needs_attention, what_to_do)."""
    c = creator or "A creator"
    if kind == "quiet_retainer":
        return (f"{c} has gone quiet at {brand}",
                f"A retainer creator with no qualifying video in the last 10 days of complete video data.",
                f"{c} is on a retainer at {brand} but has not posted a qualifying video in the last 10 days.",
                f"Contact {c} to confirm the next post date; if they cannot deliver, raise it with {brand} before the retainer month ends.")
    if kind == "sample_no_video":
        d = f" {days_waiting} days ago" if days_waiting is not None else ""
        return (f"{c}'s sample from {brand} has no video yet",
                "A delivered sample with no video from the creator after two weeks.",
                f"{brand} sent {c} a sample, delivered{d}, and no video for that product has appeared.",
                f"Message {c} about the sample. If no video is planned, mark it as not converted and decide whether to send more product.")
    noun = SOURCE_NOUN.get(source_type, "data")
    st = _state_phrase(state or "incomplete")
    return (f"{brand}'s {noun} are {st}",
            f"A source whose data is {st} for the period.",
            reason or f"{brand}'s {noun} are {st}, so pacing and creator figures for {brand} may be incomplete.",
            f"Ask {brand} to send the missing {noun} so its goal pace and creator figures can be completed.")
