"""Chart series, portfolio KPIs and chart evidence builders.

Everything is computed here from gold views with ONE query per series (see ChartsRepo).
Tests stub ChartsRepo with the same method names. Money is Decimal -> string; NULL is never 0.

Evidence hooks for the core worker (routes.py evidence route):
    is_chart_evidence(metric_key, params) -> bool
    chart_evidence(repo, metric_key, params) -> dict     (same shape as MetricService.evidence + pagination)
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from app.metrics.service import (
    goal_id as goal_id_,
    as_of_for,
    exclusion_items,
    actual_key,
    DEFINITION_VERSION, STATE_TO_STATUS, Filters, MetricService, evidence_url, progress_ratio, jsonable, money, mv_dict,
)

SERIES = ("pacing_trajectory", "daily_gmv_refunds", "attribution_reconciliation", "sample_funnel_lag",
          "creator_concentration", "retainer_cadence")
BUCKETS = ("resolved", "creator_unresolved", "none", "conflict")
STAGES = ("sent", "delivered", "mature", "in_transit", "pending", "converted", "no_video_mature", "unknown")
LAGS = ("0-7", "8-14", "15-21", "22-30")
CHART_EVIDENCE_KEYS = {"decomposition", "creator_concentration", "retainer_cadence", "portfolio_pacing"}
CHART_EVIDENCE_PARAMS = ("date_from", "date_to", "bucket", "stage")
RANK = {"current": 0, "stale": 1, "partial": 2, "unavailable": 3}
MV_STATUSES = ("current", "stale", "partial", "unavailable")


# ------------------------------------------------------------------ data layer
class ChartsRepo:
    """Read-only gold access. One request = one REPEATABLE READ snapshot on one connection."""

    def __init__(self, conn=None):
        self.conn, self._rk, self._cm = conn, None, None

    def __enter__(self):  # standalone use (scripts): own REPEATABLE READ snapshot
        if self.conn is None:
            from app.metrics.conn import read_conn
            self._cm = read_conn()
            self.conn = self._cm.__enter__()
        return self

    def __exit__(self, *exc):
        if self._cm is not None:
            self._cm.__exit__(*exc)

    def revision_key(self):
        if self._rk is None:
            r = self._q("SELECT revision_id, created_at FROM meta.dataset_revision ORDER BY revision_id DESC LIMIT 1")
            self._rk = (int(r[0]["revision_id"]), r[0]["created_at"].isoformat()) if r else (0, None)
        return self._rk

    def _q(self, sql, params=None):
        return list(self.conn.execute(sql, params or {}).fetchall())

    @staticmethod
    def _b(brand_id, col="brand_id"):
        return f"AND {col} = %(brand)s" if brand_id else ""

    def creator_handles(self) -> dict:
        return {r["creator_id"]: r["handle"] for r in self._q("SELECT creator_id, handle FROM silver.creator")}

    def excluded_notes(self):
        from app.metrics.repo import PgRepo
        return PgRepo(self.conn).excluded_notes()

    def revision(self) -> int:
        r = self._q("SELECT max(revision_id) AS r FROM meta.dataset_revision")[0]["r"]
        return int(r) if r is not None else 0  # 0 = no revision yet (sentinel, not a metric)

    def brands(self):
        return self._q("SELECT brand_id, name FROM silver.brand ORDER BY brand_id")

    def freshness(self, brand_id=None):
        if brand_id:
            return self._q("SELECT * FROM gold.source_freshness WHERE brand_id = %(brand)s ORDER BY 1,2", {"brand": brand_id})
        return self._q("SELECT * FROM gold.source_freshness ORDER BY 1,2")

    def goals(self, brand_id, month):
        return self._q(
            "SELECT * FROM gold.goal_progress WHERE month = %(m)s " + self._b(brand_id) + " ORDER BY brand_id, metric_key, scope",
            {"m": month + "-01", "brand": brand_id})

    def daily(self, brand_id, d_from: date, d_to: date, cutoff: date):
        """chart_daily + refunds restated at the REQUEST cutoff (cohort day and processed day), one query."""
        b = self._b(brand_id)
        return self._q(f"""
            WITH d AS (SELECT brand_id, day, gross_gmv, creator_attributed_gmv, status FROM gold.chart_daily
                       WHERE day BETWEEN %(f)s AND %(t)s {b}),
            rc AS (SELECT brand_id, paid_local_date AS day, count(*) n, count(merch_amount) k, sum(merch_amount) s
                   FROM gold.refund_line WHERE eligible AND bucket = 'resolved' AND status IN ('completed','partial')
                     AND completed_local_date <= %(c)s AND paid_local_date BETWEEN %(f)s AND %(t)s {b} GROUP BY 1,2),
            rp AS (SELECT brand_id, completed_local_date AS day, count(*) n, count(merch_amount) k, sum(merch_amount) s
                   FROM gold.refund_line WHERE eligible AND bucket = 'resolved' AND status IN ('completed','partial')
                     AND completed_local_date BETWEEN %(f)s AND LEAST(%(t)s, %(c)s) {b} GROUP BY 1,2)
            SELECT d.brand_id, d.day, d.gross_gmv, d.creator_attributed_gmv, d.status,
                   rc.n AS rc_n, rc.k AS rc_k, rc.s AS rc_s, rp.n AS rp_n, rp.k AS rp_k, rp.s AS rp_s
            FROM d LEFT JOIN rc USING (brand_id, day) LEFT JOIN rp USING (brand_id, day) ORDER BY d.brand_id, d.day""",
                       {"f": d_from, "t": d_to, "c": cutoff, "brand": brand_id})

    def video_daily(self, brand_id, d_from: date, d_to: date):
        """Per day: qualifying videos and creators whose FIRST qualifying video of the month is that day
        (brand_id None = portfolio, creators deduplicated across brands)."""
        b = self._b(brand_id)
        return self._q(f"""
            WITH v AS (SELECT brand_id, video_id, creator_id, local_date FROM gold.video_activity
                       WHERE qualifies AND local_date BETWEEN %(f)s AND %(t)s {b}),
            fc AS (SELECT creator_id, min(local_date) AS day FROM v GROUP BY 1),
            vd AS (SELECT local_date AS day, count(DISTINCT (brand_id, video_id)) AS videos FROM v GROUP BY 1)
            SELECT vd.day, vd.videos,
                   (SELECT count(*) FROM fc WHERE fc.day = vd.day) AS new_creators  -- creators first seen that day
            FROM vd ORDER BY vd.day""",
                       {"f": d_from, "t": d_to, "brand": brand_id})

    def reconciliation(self, brand_id, month, cutoff: date):
        return self._q(f"""
            SELECT brand_id, bucket, count(*) AS order_items, count(gmv) AS known, sum(gmv) AS amount
            FROM gold.sales_line WHERE eligible AND month = %(m)s AND local_date <= %(c)s {self._b(brand_id)}
            GROUP BY 1,2""", {"m": month + "-01", "c": cutoff, "brand": brand_id})

    def funnel(self, brand_id):
        return self._q(f"SELECT brand_id, stage, lag_bucket, count FROM gold.chart_sample_funnel WHERE true {self._b(brand_id)}",
                       {"brand": brand_id})

    def concentration(self, brand_id):
        return self._q(f"SELECT * FROM gold.creator_concentration WHERE true {self._b(brand_id)} ORDER BY brand_id, rank",
                       {"brand": brand_id})

    def retainer(self, brand_id, months: list[date]):
        return self._q(f"SELECT * FROM gold.retainer_cadence WHERE month = ANY(%(ms)s) {self._b(brand_id)} "
                       "ORDER BY month, brand_id, handle", {"ms": months, "brand": brand_id})

    def diag(self, brand_id):
        return self._q(f"SELECT * FROM gold.diagnostic_period WHERE true {self._b(brand_id)} ORDER BY brand_id, period, product_id",
                       {"brand": brand_id})

    def distinct_active(self, cur: tuple[date, date], base: tuple[date, date]):
        r = self._q("""SELECT (SELECT count(DISTINCT creator_id) FROM gold.video_activity WHERE qualifies AND local_date BETWEEN %(cf)s AND %(ct)s) AS current,
                              (SELECT count(DISTINCT creator_id) FROM gold.video_activity WHERE qualifies AND local_date BETWEEN %(bf)s AND %(bt)s) AS baseline""",
                    {"cf": cur[0], "ct": cur[1], "bf": base[0], "bt": base[1]})
        return r[0]

    # ---- evidence rows
    def evidence_sales(self, brand_id, creator_id, d_from, d_to, cutoff: date):
        w, p = ["sl.local_date <= %(c)s"], {"c": cutoff, "r": cutoff}
        for col, k, v in (("sl.brand_id", "brand", brand_id), ("sl.creator_id", "cr", creator_id)):
            if v:
                w.append(f"{col} = %({k})s"); p[k] = v
        if d_from:
            w.append("sl.local_date >= %(f)s"); p["f"] = d_from
        if d_to:
            w.append("sl.local_date <= %(t)s"); p["t"] = d_to
        rows = self._q(
            "SELECT sl.*, r.n AS _rn, r.n_unknown AS _ru, r.known_sum AS _rs FROM gold.sales_line sl "
            "LEFT JOIN (SELECT shop_id, order_id, line_id, count(*) n, count(*) FILTER (WHERE merch_amount IS NULL) n_unknown, "
            "sum(merch_amount) known_sum FROM gold.refund_line WHERE status IN ('completed','partial') "
            "AND completed_local_date <= %(r)s GROUP BY 1,2,3) r USING (shop_id, order_id, line_id) "
            f"WHERE {' AND '.join(w)} ORDER BY sl.source_file, sl.source_locator", p)
        for r in rows:
            n, nu, ks = r.pop("_rn"), r.pop("_ru"), r.pop("_rs")
            if not r["eligible"]:
                r["refunded"], r["net"] = None, None
            elif n is None:
                r["refunded"], r["net"] = Decimal(0), r["gmv"]
            elif nu:
                r["refunded"], r["net"] = None, None
            else:
                r["refunded"], r["net"] = ks, None if r["gmv"] is None else r["gmv"] - ks
        return rows

    def evidence_refunds(self, brand_id, d_from, d_to, cutoff: date, processed: bool):
        col = "completed_local_date" if processed else "paid_local_date"
        w, p = [f"{col} BETWEEN %(f)s AND %(t)s", "completed_local_date <= %(c)s", "eligible", "bucket = 'resolved'",
                "status IN ('completed','partial')"], {"f": d_from, "t": d_to, "c": cutoff}
        if brand_id:
            w.append("brand_id = %(brand)s"); p["brand"] = brand_id
        return self._q(f"SELECT * FROM gold.refund_line WHERE {' AND '.join(w)} ORDER BY source_file_id, row_num", p)

    def evidence_videos(self, brand_id, d_from, d_to):
        return self._q(f"SELECT * FROM gold.video_activity WHERE local_date BETWEEN %(f)s AND %(t)s {self._b(brand_id)} "
                       "ORDER BY source_file, source_locator", {"f": d_from, "t": d_to, "brand": brand_id})

    def evidence_samples(self, brand_id):
        return self._q(f"SELECT * FROM gold.sample_funnel WHERE true {self._b(brand_id)} ORDER BY sent_date, sample_id",
                       {"brand": brand_id})

    def as_of(self) -> date:
        return self._q("SELECT as_of FROM gold.current_as_of")[0]["as_of"]


# ------------------------------------------------------------------ helpers
def _d(v):
    return None if v is None else Decimal(str(v))


def mv_status(s) -> str:
    if s in MV_STATUSES:
        return s
    return STATE_TO_STATUS.get(s, "partial")


def worst(statuses) -> str:
    return max(statuses, key=lambda s: RANK[s], default="unavailable")


def sum_or_none(vals):
    """Sum with the guard count(*) = count(col)."""
    vals = list(vals)
    if not vals or any(v is None for v in vals):
        return None
    return sum((_d(v) for v in vals), Decimal(0))


def month_days(month: str) -> list[date]:
    y, m = int(month[:4]), int(month[5:7])
    return [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"


def _s(v):
    return None if v is None else str(v)


def _filters(brand_id, month, cutoff, **kw) -> Filters:
    return Filters(brand_id=brand_id, month=month, cutoff=cutoff, **kw)


def _refund_val(n, k, s, day_current: bool):
    """No refund rows = verified zero only on a covered day; an unknown refund amount = NULL."""
    if n is None:
        return Decimal(0) if day_current else None
    return _d(s) if n == k else None


def _envelope(series, brand_id, month, cutoff, rev, svc, sources, units, meta, points, extra_reason=None):
    status, reason, cov = svc.status_for(sources, brand_id)
    return {"series": series, "brand_id": brand_id, "month": month, "cutoff": cutoff, "data_revision": rev,
            "definition_version": DEFINITION_VERSION, "coverage_through": _s(cov), "status": status,
            "status_reason": extra_reason or reason, "units": units, "meta": meta, "points": points}


def _pt(x, fields, status, reason, urls, **extra):
    return {"x": x, **fields, **extra, "status": status,
            "status_reason": reason if status != "current" else None, "evidence_urls": urls}


def _check_brand(repo, brand_id):
    if brand_id is not None and brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise LookupError("unknown brand")


# ------------------------------------------------------------------ series builders
def build_chart(repo, series: str, brand_id: str | None, month: str, cutoff: str, metric: str = "gmv") -> dict:
    if series not in SERIES:
        raise ValueError("unknown series")
    if metric not in ("gmv", "videos", "active_creators"):
        raise ValueError("metric must be gmv|videos|active_creators")
    _check_brand(repo, brand_id)
    fn = {"pacing_trajectory": _pacing, "daily_gmv_refunds": _daily, "attribution_reconciliation": _recon,
          "sample_funnel_lag": _funnel, "creator_concentration": _concentration, "retainer_cadence": _retainer}[series]
    env = fn(repo, brand_id, month, cutoff, metric)
    env["availability"] = classify(series, env, _profile(repo, brand_id, month), cutoff)
    return env


# ------------------------------------------------------------------ availability (one classifier)
ALWAYS_SHOWN = ("pacing_trajectory", "daily_gmv_refunds")


def _profile(repo, brand_id, month):
    """What the brand has (creators by contract type, samples); None = portfolio or unknown (no applicability test)."""
    conn = getattr(repo, "conn", None)
    if brand_id is None or conn is None:
        return None
    from app.metrics.repo import PgRepo
    cs = PgRepo(conn).creators(brand_id, month)
    sent = [r["count"] for r in repo.funnel(brand_id) if r["stage"] == "sent" and r["lag_bucket"] is None]
    return {"creators": len(cs), "retainers": sum(1 for c in cs if c.get("contract_type") == "retainer"),
            "affiliates": sum(1 for c in cs if c.get("contract_type") == "affiliate"),
            "samples": None if not sent or any(x is None for x in sent) else int(sum(sent))}


def classify(series: str, env: dict, profile, cutoff: str) -> dict:
    """First match wins: not_applicable, empty, unknown, zero, stale, available. Null is never read as 0."""
    pts = env["points"]
    status, reason = "available", "The series has values and its sources are current."
    if profile is not None and series not in ALWAYS_SHOWN:
        no_data = profile["retainers"] == 0 and profile["affiliates"] == 0 and not profile["samples"]
        if no_data or profile["creators"] < 3:
            return _avail("not_applicable", "The brand has no retainers, affiliates or samples, or fewer than 3 creators.", env, cutoff)
        if series == "retainer_cadence" and profile["retainers"] == 0:
            return _avail("not_applicable", "The brand has no retainer creators.", env, cutoff)
        if series == "sample_funnel_lag" and profile["samples"] == 0:
            return _avail("not_applicable", "The brand has no samples.", env, cutoff)
    if not pts:
        return _avail("empty", "The series has no points for this period.", env, cutoff)
    fields = list(env.get("units") or {})
    vals = [p.get(k) for p in pts for k in fields]
    known = [v for v in vals if v is not None]
    if not known:
        return _avail("unknown", env.get("status_reason") or "Every value is unknown (no source coverage).", env, cutoff)
    if all(_is_zero(v) for v in known):
        return _avail("zero", "Every known value is zero.", env, cutoff)
    if env.get("status") != "current":
        return _avail("stale", env.get("status_reason") or "A source is behind its expected coverage.", env, cutoff)
    return _avail(status, reason, env, cutoff)


def _is_zero(v) -> bool:
    try:
        return Decimal(str(v)) == 0
    except Exception:
        return False


def _avail(status, reason, env, cutoff):
    return {"status": status, "reason": reason}


def build_available(repo, brand_id: str, month: str, cutoff: str) -> dict:
    _check_brand(repo, brand_id)
    out = []
    for s in SERIES:
        env = build_chart(repo, s, brand_id, month, cutoff, "gmv")
        a = env["availability"]
        out.append({"series_id": s, "status": a["status"], "reason": a["reason"],
                    "as_of": as_of_for(cutoff), "point_count": len(env["points"])})
    return {"data_revision": repo.revision(), "series": out}


def _daily_points(repo, brand_id, month, cutoff):
    """Per day (portfolio-aggregated when brand_id is None): dict of Decimal|None fields + status."""
    days = month_days(month)
    cut = date.fromisoformat(cutoff)
    rows = repo.daily(brand_id, days[0], days[-1], cut)
    by_day: dict[date, list[dict]] = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    nb = len({r["brand_id"] for r in rows}) if brand_id is None else 1
    out = {}
    for d in days:
        rs = by_day.get(d, [])
        if d > cut:
            out[d] = dict(status="forecast", reason="after the cutoff", gmv=None, attr=None, rc=None, rp=None)
            continue
        sts = [mv_status(r["status"]) for r in rs] + (["unavailable"] if len(rs) < nb or not rs else [])
        st = worst(sts)
        ok = st == "current"
        gm = sum_or_none(r["gross_gmv"] for r in rs) if ok else None
        at = sum_or_none(r["creator_attributed_gmv"] for r in rs) if ok else None
        rc = sum_or_none(_refund_val(r["rc_n"], r["rc_k"], r["rc_s"], ok) for r in rs) if ok else None
        rp = sum_or_none(_refund_val(r["rp_n"], r["rp_k"], r["rp_s"], ok) for r in rs) if ok else None
        out[d] = dict(status=st, reason=None if ok else f"source coverage is {st} on {d.isoformat()}",
                      gmv=gm, attr=at, rc=rc, rp=rp)
    return out


def _daily(repo, brand_id, month, cutoff, metric):
    rev, svc = repo.revision(), MetricService(repo)
    pts = []
    for d, v in _daily_points(repo, brand_id, month, cutoff).items():
        net = None if v["attr"] is None or v["rc"] is None else v["attr"] - v["rc"]
        iso = d.isoformat()

        def url(key, part=None, d=d):
            ex = {"date_from": d.isoformat(), "date_to": d.isoformat()}
            if part:
                ex["part"] = part
            return evidence_url(key, _filters(brand_id, month, cutoff), rev, **ex)
        urls = {"gmv": url("gmv"), "creator_attributed_gmv": url("creator_attributed_gmv"),
                "attributed_refunds_cohort": url("net_attributed_sales", "refunds_cohort"),
                "attributed_refunds_processed": url("net_attributed_sales", "refunds_processed"),
                "net_attributed_sales": url("net_attributed_sales")}
        f = {"gmv": _m(v["gmv"]), "creator_attributed_gmv": _m(v["attr"]),
             "attributed_refunds_cohort": _m(v["rc"]), "attributed_refunds_processed": _m(v["rp"]),
             "net_attributed_sales": _m(net)}
        pts.append(_pt(iso, f, v["status"], v["reason"], urls))
    units = {k: "USD" for k in ("gmv", "creator_attributed_gmv", "attributed_refunds_cohort",
                                "attributed_refunds_processed", "net_attributed_sales")}
    return _envelope("daily_gmv_refunds", brand_id, month, cutoff, rev, svc,
                     ["orders", "affiliate_orders", "returns"], units, {}, pts)


def _m(v):
    return None if v is None else money(v)


def _recon(repo, brand_id, month, cutoff, metric):
    rev, svc = repo.revision(), MetricService(repo)
    rows = repo.reconciliation(brand_id, month, date.fromisoformat(cutoff))
    st, reason, _ = svc.status_for(["orders", "affiliate_orders"], brand_id)
    ok = st == "current"
    amt, cnt = {}, {}
    for b in BUCKETS:
        rs = [r for r in rows if r["bucket"] == b]
        cnt[b] = sum(int(r["order_items"]) for r in rs) if rs or ok else None
        # guard: any line with unknown gmv makes the bucket unknown; no rows is a verified zero only when covered
        if rs:
            amt[b] = None if any(r["known"] != r["order_items"] for r in rs) else sum((_d(r["amount"]) for r in rs), Decimal(0))
        else:
            amt[b] = Decimal(0) if ok else None
    pct = _largest_remainder(amt)
    pts = []
    for b in BUCKETS:
        urls = {k: evidence_url("gmv", _filters(brand_id, month, cutoff), rev, bucket=b) for k in ("amount", "order_items", "pct")}
        pts.append(_pt(b, {"amount": _m(amt[b]), "order_items": cnt[b], "pct": pct[b]},
                       st if amt[b] is not None else ("partial" if st == "current" else st),
                       reason or ("amount unknown on some lines" if amt[b] is None else None), urls))
    total = sum_or_none(amt.values())
    meta = {"eligible_gmv": mv_dict("gmv", _m(total), "USD", _filters(brand_id, month, cutoff), st, reason, None, rev)}
    return _envelope("attribution_reconciliation", brand_id, month, cutoff, rev, svc, ["orders", "affiliate_orders"],
                     {"amount": "USD", "order_items": "count", "pct": "ratio"}, meta, pts)


def _largest_remainder(amt: dict, places=4) -> dict:
    total = sum_or_none(amt.values())
    if total is None or total <= 0:
        return {k: None for k in amt}
    unit = Decimal(10) ** places
    raw = {k: (_d(v) / total) * unit for k, v in amt.items()}
    fl = {k: r.to_integral_value(ROUND_FLOOR) for k, r in raw.items()}
    left = int(unit - sum(fl.values()))
    for k in sorted(raw, key=lambda k: (-(raw[k] - fl[k]), list(amt).index(k)))[:left]:
        fl[k] += 1
    return {k: str((v / unit).quantize(Decimal(1) / unit)) for k, v in fl.items()}


def _funnel(repo, brand_id, month, cutoff, metric):
    rev, svc = repo.revision(), MetricService(repo)
    st, reason, _ = svc.status_for(["samples", "videos_weekly"], brand_id)
    rows = repo.funnel(brand_id)
    brands = sorted({r["brand_id"] for r in rows}) if brand_id is None else [brand_id]
    present: dict[tuple, list] = {}
    for r in rows:
        key = (("lag", r["lag_bucket"]) if r["lag_bucket"] else ("stage", r["stage"]))
        present.setdefault(key, []).append(r["count"])
    ok = st == "current"
    pts = []
    for group, xs in (("stage", STAGES), ("lag", LAGS)):
        for x in xs:
            vals = present.get((group, x))
            # a missing row is a verified zero only with full sample + video coverage
            cnt = (lambda s: None if s is None else int(s))(sum_or_none(vals)) if vals is not None and len(vals) >= len(brands) else (0 if ok and vals is None else None)
            stat = st if cnt is not None else (st if st != "current" else "partial")
            f = Filters(brand_id=brand_id, month=month, cutoff=cutoff)
            url = evidence_url("sample_conversion_rate", f, rev, **({"stage": x} if group == "stage" else {"stage": "converted", "bucket": x}))
            pts.append({"x": x, "group": group, "count": cnt, "status": stat,
                        "status_reason": None if stat == "current" else (reason or "count unknown"),
                        "evidence_urls": {"count": url}})
    def pct(n, d):
        return None if n is None or not d else str((Decimal(n) * 100 / Decimal(d)).quantize(Decimal("0.1")))
    cnt_of = {(p_["group"], p_["x"]): p_["count"] for p_ in pts}
    for p_ in pts:
        if p_["group"] == "stage":
            p_["pct_of_sent"] = pct(p_["count"], cnt_of.get(("stage", "sent")))
        else:
            p_["pct_of_converted"] = pct(p_["count"], cnt_of.get(("stage", "converted")))
    return _envelope("sample_funnel_lag", brand_id, month, cutoff, rev, svc, ["samples", "videos_weekly"],
                     {"count": "count", "pct_of_sent": "percent", "pct_of_converted": "percent"}, {}, pts)


def _concentration_rows(repo, brand_id, cut: date, st: str) -> list[dict]:
    """Creator universe from the view; gross GMV / unresolved recomputed from sales lines capped at the cutoff
    (ruling 3: all months through the request cutoff, guarded sums, unknown stays null)."""
    base = list(repo.concentration(brand_id))
    agg: dict = {}
    for r in repo.evidence_sales(brand_id, None, None, None, cut):
        if not (r["eligible"] and r["bucket"] == "resolved" and r.get("creator_id")):
            continue
        a = agg.setdefault((r["brand_id"], r["creator_id"]), {"n": 0, "ng": 0, "sum": Decimal(0), "nu": 0, "ngu": 0, "usum": Decimal(0)})
        a["n"] += 1
        if r.get("gmv") is not None:
            a["ng"] += 1
            a["sum"] += _d(r["gmv"])
        if not r.get("video_known"):
            a["nu"] += 1
            if r.get("gmv") is not None:
                a["ngu"] += 1
                a["usum"] += _d(r["gmv"])
    handles = {}
    out, seen = [], set()
    for b in base:
        k = (b["brand_id"], b["creator_id"])
        seen.add(k)
        a = agg.get(k)
        if a is None:  # no sales through the cutoff: zero only with full coverage
            gross, unres = (Decimal(0), Decimal(0)) if st == "current" else (None, None)
        else:
            gross = a["sum"] if a["n"] == a["ng"] else None
            unres = a["usum"] if a["nu"] == a["ngu"] else None
        out.append(dict(b, gross_gmv=gross, unresolved=unres))
    missing = [k for k in agg if k not in seen]
    if missing:
        handles = {r["creator_id"]: r["handle"] for r in repo._q("SELECT creator_id, handle FROM silver.creator")}
    for k in missing:
        a = agg[k]
        out.append({"brand_id": k[0], "creator_id": k[1], "handle": handles.get(k[1]),
                    "gross_gmv": a["sum"] if a["n"] == a["ng"] else None,
                    "unresolved": a["usum"] if a["nu"] == a["ngu"] else None})
    return out


def _concentration(repo, brand_id, month, cutoff, metric):
    rev, svc = repo.revision(), MetricService(repo)
    st, reason, _ = svc.status_for(["orders", "affiliate_orders"], brand_id)
    cut = date.fromisoformat(cutoff)
    # a verified zero (roster creator with no sales) needs complete sales AND video coverage
    zst, zreason, _ = svc.status_for(["orders", "affiliate_orders", "videos_weekly"], brand_id)
    rows = _concentration_rows(repo, brand_id, cut, zst)
    for r in rows:
        if r["gross_gmv"] is not None and _d(r["gross_gmv"]) == 0 and zst != "current":
            r["gross_gmv"] = None
    rows.sort(key=lambda r: ((1, Decimal(0)) if _d(r["gross_gmv"]) is None else (0, -_d(r["gross_gmv"])), r["creator_id"]))
    n = len(rows)
    gm = [_d(r["gross_gmv"]) for r in rows]
    total = sum_or_none(gm)
    pts, cum = [], Decimal(0)
    hundred = Decimal(100)
    for i, r in enumerate(rows, 1):
        g = gm[i - 1]
        known = g is not None and total is not None and total > 0
        if known:
            cum += g
        f = {"creator_id": r["creator_id"], "handle": r["handle"], "gmv": _m(g),
             "share": str((g / total).quantize(Decimal("0.0001"))) if known else None,  # 0-1 ratio
             "share_pct": str((g / total * hundred).quantize(Decimal("0.1"))) if known else None,
             "cum_creator_pct": str((Decimal(i) / n * hundred).quantize(Decimal("0.1"))),
             "cum_gmv_pct": str((cum / total * hundred).quantize(Decimal("0.1"))) if known else None}
        extra = {"brand_id": r["brand_id"]} if brand_id is None else {}
        fl = Filters(brand_id=r["brand_id"], creator_id=r["creator_id"], month=month, cutoff=cutoff)
        u = evidence_url("creator_concentration", fl, rev)
        pts.append(_pt(i, f, st if known else ("partial" if zst == "current" else zst if zst != "unavailable" else "partial"), reason or zreason or "creator GMV unknown", {k: u for k in ("gmv", "share", "share_pct", "cum_creator_pct", "cum_gmv_pct")}, **extra))
    unres = sum_or_none(r.get("unresolved") for r in rows) if rows else None
    meta = {"unresolved_gmv": mv_dict("creator_concentration", _m(unres), "USD", _filters(brand_id, month, cutoff), st if unres is not None else "partial",
                                      reason, None, rev, part="unresolved"),
            "basis": f"gross attributed GMV, all months through {cutoff}"}

    def top_share(frac):
        if not rows or total is None or total <= 0 or any(g is None for g in gm):
            return None
        k = max(1, -(-n * frac // 100))  # ceil(n * frac%)
        return str((sum(gm[:int(k)], Decimal(0)) * hundred / total).quantize(Decimal("0.1")))
    meta["top10_gmv_share"] = top_share(10)
    meta["top20_gmv_share"] = top_share(20)
    return _envelope("creator_concentration", brand_id, month, cutoff, rev, svc, ["orders", "affiliate_orders"],
                     {"gmv": "USD", "share": "ratio", "share_pct": "percent", "cum_creator_pct": "percent", "cum_gmv_pct": "percent"}, meta, pts)


def trailing_months(month: str, n=3) -> list[str]:
    out, m = [], month
    for _ in range(n):
        m = prev_month(m)
        out.append(m)
    return sorted(out)


def _retainer(repo, brand_id, month, cutoff, metric):
    rev, svc = repo.revision(), MetricService(repo)
    months = trailing_months(month)
    rows = repo.retainer(brand_id, [date.fromisoformat(m + "-01") for m in months])
    pts = []
    for r in sorted(rows, key=lambda r: (r["month"], r["brand_id"], r["handle"] or "", r["creator_id"])):
        exp, posts = _d(r.get("expected_posts")), r.get("posts")
        gap = (r.get("n_gaps") is not None and r["n_gaps"] > 0) or posts is None
        att = None
        if not gap and exp is not None and exp > 0:
            att = str((Decimal(posts) / exp * 100).quantize(Decimal("0.1")))
        x = r["month"].strftime("%Y-%m")
        reason = ("weekly video coverage has gaps" if gap else "no expected posts" if att is None else None)
        extra = {"brand_id": r["brand_id"]} if brand_id is None else {}
        u = evidence_url("retainer_cadence", Filters(brand_id=r["brand_id"], creator_id=r["creator_id"], month=x, cutoff=cutoff), rev)
        pts.append(_pt(x, {"creator_id": r["creator_id"], "handle": r["handle"],
                           "expected_posts": None if exp is None else str(exp.quantize(Decimal("0.01"))),
                           "posts": None if gap else int(posts), "attainment_pct": att},
                       "partial" if gap else "current", reason,
                       {k: u for k in ("expected_posts", "posts", "attainment_pct")}, **extra))
    return _envelope("retainer_cadence", brand_id, month, cutoff, rev, svc, ["videos_weekly", "roster"],
                     {"expected_posts": "count", "posts": "count", "attainment_pct": "percent"},
                     {"months": months}, pts)


# ---- pacing
def _pick_goal(goals, metric):
    gs = [g for g in goals if g["metric_key"] == metric]
    return next((g for g in gs if g["scope"] == "shop"), gs[0] if gs else None)


def _pacing(repo, brand_id, month, cutoff, metric):
    rev, svc = repo.revision(), MetricService(repo)
    days, cut = month_days(month), date.fromisoformat(cutoff)
    goals = repo.goals(brand_id, month)
    if brand_id is None:  # one goal per brand, shop scope for gmv
        picked = [g for b in sorted({g["brand_id"] for g in goals}) if (g := _pick_goal([x for x in goals if x["brand_id"] == b], metric))]
        if metric == "gmv":
            picked = [g for g in picked if g["scope"] == "shop"]
    else:
        g = _pick_goal(goals, metric)
        picked = [g] if g else []
    f0 = _filters(brand_id, month, cutoff)
    key = {"gmv": "gmv", "videos": "videos", "active_creators": "active_creators"}[metric]
    if metric == "gmv" and brand_id and picked and picked[0]["scope"] != "shop":
        key = "net_attributed_sales" if picked[0].get("basis") == "net" else "creator_attributed_gmv"
    unit = "USD" if metric == "gmv" else "count"
    # daily actuals (cumulative)
    cum: dict[date, Decimal | None] = {}
    why: dict[date, str | None] = {}
    if metric == "gmv":
        dp = _daily_points(repo, brand_id, month, cutoff)
        run, broke = Decimal(0), None
        for d in days:
            v = dp[d]
            if d > cut:
                cum[d], why[d] = None, None
                continue
            if key == "gmv":
                x = v["gmv"]
            elif key == "creator_attributed_gmv":
                x = v["attr"]
            else:
                x = None if v["attr"] is None or v["rc"] is None else v["attr"] - v["rc"]
            if broke is None and x is None:
                broke = d
            run = None if broke else run + x
            cum[d] = run
            why[d] = None if run is not None else (v["reason"] or f"unknown from the coverage gap on {broke.isoformat()}")
    else:
        st0, rs0, cov0 = svc.status_for(["videos_weekly"], brand_id)
        gaps = any((r.get("n_gaps") is not None and r["n_gaps"] > 0) for r in repo.freshness(brand_id) if r["source_type"] == "videos_weekly")
        vrows = {r["day"]: r for r in repo.video_daily(brand_id, days[0], days[-1])}
        run = 0
        for d in days:
            if d > cut:
                cum[d], why[d] = None, None
                continue
            if gaps or st0 == "unavailable" or (cov0 and d.isoformat() > str(cov0)):
                cum[d], why[d] = None, rs0 or "weekly video coverage has gaps or has not reached this day"
                continue
            r = vrows.get(d)
            run += int((r["videos"] if metric == "videos" else r["new_creators"]) if r else 0)
            cum[d], why[d] = Decimal(run), None
    a_cut = cum.get(min(cut, days[-1])) if cut >= days[0] else None
    tgt = sum_or_none(g.get("target_value") for g in picked)
    proj = sum_or_none(g.get("projection") for g in picked)
    remaining = max((days[-1] - cut).days, 0)
    pace = None if tgt is None or a_cut is None or remaining == 0 else (tgt - a_cut) / remaining
    gstatus = worst([mv_status(g.get("status") or g.get("state") or "partial") for g in picked]) if picked else "unavailable"
    greason = "; ".join(sorted({g["status_reason"] for g in picked if g.get("status_reason")})) or (None if picked else "no goal in plan")
    cov = max((str(g["coverage_through"]) for g in picked if g.get("coverage_through")), default=None)
    bases = {g.get("basis") for g in picked}
    basis = (bases.pop() if len(bases) == 1 else "mixed") if picked else None

    def ev_actual(d):
        return evidence_url(key, f0, rev, date_from=days[0].isoformat(), date_to=d.isoformat())
    gp = {} if brand_id is None else ({"goal_id": picked[0]["goal_id"]} if picked and picked[0].get("goal_id") else {})
    fg = Filters(brand_id=brand_id, month=month, cutoff=cutoff, goal_id=gp.get("goal_id"))

    def gurl(part):
        if brand_id is None:
            return evidence_url("portfolio_pacing", f0, rev, part=part, metric=metric)
        return evidence_url("goal_projection", fg, rev, part=part) if gp else None
    pts = []
    for d in days:
        a = cum[d]
        if d < cut or d > days[-1]:
            p = r_ = None
        elif d == cut:
            p = r_ = a
        else:
            frac = Decimal((d - cut).days) / Decimal(remaining)
            p = None if a_cut is None or proj is None else a_cut + (proj - a_cut) * frac
            r_ = None if a_cut is None or tgt is None else a_cut + (tgt - a_cut) * frac
        fmt = (lambda v: None if v is None else (money(v) if metric == "gmv" else str(v.quantize(Decimal("0.01")))))
        if d > cut:
            status, reason = "forecast", "after the cutoff"
        elif a is None:
            status, reason = "partial", why[d]
        else:
            status, reason = "current", None
        urls = {"actual": ev_actual(d) if d <= cut else None}
        if d >= cut:
            urls["projection"], urls["required"] = gurl("projection"), gurl("target")
        pts.append(_pt(d.isoformat(), {"actual": fmt(a), "projection": fmt(p), "required": fmt(r_)}, status, reason, urls))
    mixed = " (portfolio mixes goal bases)" if basis == "mixed" else ""
    meta = {
        "basis": mv_dict("goal_projection", basis, "text", f0, gstatus, greason, cov, rev, part="basis"),
        "target": mv_dict("goal_projection", _fmt_meta(tgt, metric), unit, f0, "current" if tgt is not None else "unavailable",
                          None if tgt is not None else "no target in plan", None, rev, part="target"),
        "projection": mv_dict("goal_projection", _fmt_meta(proj, metric), unit, f0, gstatus, greason, cov, rev, part="projection"),
        "required_pace": mv_dict("goal_projection", _fmt_meta(pace, metric), unit + "_per_day", f0,
                                 gstatus if pace is not None else (gstatus if gstatus != "current" else "unavailable"),
                                 greason or (None if pace is not None else "required pace unavailable"), cov, rev, part="required_pace"),
        "metric": metric}
    srcs = ["orders", "affiliate_orders"] if metric == "gmv" else ["videos_weekly"]
    env = _envelope("pacing_trajectory", brand_id, month, cutoff, rev, svc, srcs,
                    {"actual": unit, "projection": unit, "required": unit}, meta, pts)
    if mixed:
        env["status_reason"] = (env["status_reason"] or "") + mixed
    return env


def _fmt_meta(v, metric):
    return None if v is None else (money(v) if metric == "gmv" else str(v.quantize(Decimal("0.01"))))


# ------------------------------------------------------------------ portfolio KPIs
def _period_sum(daily_rows, brand_ids, days):
    """Sum gross_gmv over `days` per brand; None if any brand-day is not current/known."""
    per = {}
    for b in brand_ids:
        rs = {r["day"]: r for r in daily_rows if r["brand_id"] == b}
        vals = [rs[d]["gross_gmv"] if d in rs and mv_status(rs[d]["status"]) == "current" else None for d in days]
        per[b] = sum_or_none(vals)
    return per


def _actuals_service(repo):
    """MetricService on the same snapshot connection; computes each brand's actual (patched in unit tests)."""
    from app.metrics.memo import Memo
    from app.metrics.repo import PgRepo
    return MetricService(Memo(PgRepo(repo.conn)))


def build_kpis(repo, month: str, cutoff: str) -> dict:
    rev, svc = repo.revision(), MetricService(repo)
    cut = date.fromisoformat(cutoff)
    cur_days = [d for d in month_days(month) if d <= cut]
    pm = prev_month(month)
    base_days = [d for d in month_days(pm) if d.day <= cut.day]
    brand_ids = [b["brand_id"] for b in repo.brands()]
    cur_p = (cur_days[0], cur_days[-1])
    base_p = (base_days[0], base_days[-1])
    drows = repo.daily(None, base_days[0], cur_days[-1], cut)
    gmv_cur, gmv_base = _period_sum(drows, brand_ids, cur_days), _period_sum(drows, brand_ids, base_days)
    diag = repo.diag(None)

    def dper(period, col):
        out = {}
        for b in brand_ids:
            rs = [r for r in diag if r["brand_id"] == b and r["period"] == period]
            out[b] = _d(rs[0][col]) if rs else None
        return out
    attr = {p: {b: (None if dper(p, "linked_gmv")[b] is None or dper(p, "unlinked_older_gmv")[b] is None
                    else dper(p, "linked_gmv")[b] + dper(p, "unlinked_older_gmv")[b]) for b in brand_ids} for p in ("current", "baseline")}
    da = repo.distinct_active(cur_p, base_p)
    spec = [("gmv", "USD", gmv_cur, gmv_base, ["orders"]),
            ("creator_attributed_gmv", "USD", attr["current"], attr["baseline"], ["orders", "affiliate_orders"]),
            ("videos", "count", dper("current", "videos"), dper("baseline", "videos"), ["videos_weekly"]),
            ("active_creators", "count", {b: None for b in brand_ids}, {b: None for b in brand_ids}, ["videos_weekly"])]
    kpis = []
    all_goals = repo.goals(None, month)
    psvc = _actuals_service(repo)

    def goals_for(key):
        return [g for g in all_goals if g["metric_key"] == ("gmv" if key in ("gmv", "creator_attributed_gmv") else key)
                and (g["scope"] == ("shop" if key == "gmv" else "creator_attributed")
                     if key in ("gmv", "creator_attributed_gmv") else True)]
    for key, unit, cur, base, srcs in spec:
        mixed_reason = None
        if key == "active_creators":
            v, b0 = _d(da["current"]), _d(da["baseline"])
            covered = len(brand_ids)
        else:
            # ruling 5: value = guarded sum of the brands' actuals (null only if a brand's actual is unknown)
            kg = goals_for(key)
            acts = {}
            for b in brand_ids:
                gb = [g for g in kg if g["brand_id"] == b]
                ak = actual_key(gb[0]) if gb else key
                acts[b] = _d(psvc.compute(ak, Filters(brand_id=b, month=month, cutoff=cutoff))["value"])
            v, b0 = sum_or_none(acts.values()), sum_or_none(base.values())
            covered = sum(1 for b in brand_ids if acts[b] is not None)
            if len({g.get("basis") for g in kg}) > 1:
                b0 = None
                mixed_reason = "goal bases differ (gross and net), so baseline, delta and progress are not comparable"
        st, reason, cov = svc.status_for(srcs, None)
        if v is None:
            st = st if st != "current" else "partial"
            reason = reason or f"{len(brand_ids) - covered} brand(s) have unknown actuals, so the portfolio total is unknown"
        delta = None if v is None or b0 is None else v - b0
        dpct = None if delta is None or b0 == 0 else (delta / b0).quantize(Decimal("0.0001"))
        fmt = (lambda x: None if x is None else (money(x) if unit == "USD" else str(int(x))))
        cs = ""
        f = Filters(month=month, cutoff=cutoff)
        ucur = {"date_from": cur_p[0].isoformat(), "date_to": cur_p[1].isoformat()}
        ubase = {"date_from": base_p[0].isoformat(), "date_to": base_p[1].isoformat()}

        def m(val, u, part, ex):
            r_ = reason
            if val is None and mixed_reason and part == "cmp":
                r_, st_ = mixed_reason, "partial"
            else:
                st_ = st
            return mv_dict(key, val, u, f, st_ if val is not None or r_ else st_, r_, cov, rev, **ex)
        tg = [g for g in repo.goals(None, month) if g["metric_key"] == ("gmv" if key in ("gmv", "creator_attributed_gmv") else key)
              and (g["scope"] == ("shop" if key == "gmv" else "creator_attributed") if key in ("gmv", "creator_attributed_gmv") else True)]
        progress = None
        if tg:
            tvals = [g.get("target_value") for g in tg]
            tsum = None if any(x is None for x in tvals) or len(tg) < len(brand_ids) else sum((Decimal(str(x)) for x in tvals), Decimal(0))
            pv, pst, prs = progress_ratio(v, tsum, st, reason)
            if mixed_reason:
                pv, pst, prs = None, "partial", mixed_reason
            if tsum is None and prs == "no target in plan":
                prs = "a brand has no target, so the portfolio target is unknown"
            progress = dict(mv_dict(key, pv, "ratio", f, pst, prs, cov, rev), evidence_url=evidence_url("portfolio_pacing", f, rev, part="progress", metric=key))
        kpis.append({"metric_key": key, "progress": progress, "value": m(fmt(v), unit, None, ucur), "baseline": m(fmt(b0), unit, "cmp", ubase),
                     "delta": m(fmt(delta), unit, "cmp", ucur), "delta_pct": m(_s(dpct), "ratio", "cmp", ucur),
                     "brands_covered": covered, "brands_total": len(brand_ids)})
    counts = {"on_track": 0, "at_risk": 0, "off_track": 0, "unknown": 0}
    for g in repo.goals(None, month):
        counts[g.get("pace_status") if g.get("pace_status") in counts else "unknown"] += 1
    bp_counts, bp = _brand_pace(repo, psvc, all_goals, month, cutoff)
    return {"data_revision": rev, "kpis": kpis, "pace_counts": counts, "brand_pace_counts": bp_counts, "brand_pace": bp}


def _brand_pace(repo, psvc, all_goals, month, cutoff):
    """Per brand: its worst goal pace (behind > unknown > on pace); goals without a target are ignored."""
    from app.metrics.service import goal_state
    from app.presentation.humanize import count_label, data_note_for, goal_name, money_label, plain_text
    rank = {"behind": 2, "unknown": 1, "on_track": 0}
    label = {"on_track": "On pace", "behind": "Behind pace", "unknown": "Not enough data"}
    out, counts = [], {"on_track": 0, "behind": 0, "unknown": 0}
    for b in repo.brands():
        bid, bname = b["brand_id"], b["name"]
        goals = []
        worst_ = None
        for g in [g for g in all_goals if g["brand_id"] == bid and g.get("target_value") is not None]:
            a = psvc.compute(actual_key(g), Filters(brand_id=bid, month=month, cutoff=cutoff, goal_id=goal_id_(g)))
            ps = goal_state(g, a)["pace_status"]
            st = "behind" if ps in ("at_risk", "off_track") else ("on_track" if ps == "on_track" else "unknown")
            fmt = money_label if g["metric_key"] == "gmv" else count_label
            goals.append({"goal_name": goal_name(g["metric_key"], g.get("scope"), g.get("basis")), "status_label": label[st],
                          "actual_label": fmt(a["value"]) if a["value"] is not None else "No data yet",
                          "target_label": fmt(g["target_value"]) if g.get("target_value") is not None else "No target set",
                          "incomplete_reason": plain_text(a["reason"], {"brand": bname}) if st == "unknown" or a["status"] != "current" else None})
            if worst_ is None or rank[st] > rank[worst_]:
                worst_ = st
        worst_ = worst_ or "unknown"
        counts[worst_] += 1
        out.append({"brand_slug": bid, "brand_name": bname, "status_label": label[worst_],
                    "data_note": data_note_for(repo, bid, None), "goals": goals})
    counts["total"] = len(out)
    return counts, out


# ------------------------------------------------------------------ evidence hooks
def _plain_chart_evidence(repo, metric_key, part, label, brand_id, creator_id, sources, excl, recs_out, status, reason, cols):
    from app.presentation import evidence_text
    from app.presentation.humanize import data_note_for, names_for
    ctx = names_for(repo, brand_id, creator_id)
    return evidence_text.build(metric_key, part, label, ctx["brand"], ctx["creator"], exclusion_items(excl),
                               sum(1 for r in recs_out if r.get("included")), len(recs_out), status, reason,
                               data_note_for(repo, brand_id, sources), cols, ctx)


def is_chart_evidence(metric_key: str, params: dict) -> bool:
    return metric_key in CHART_EVIDENCE_KEYS or any(params.get(p) for p in CHART_EVIDENCE_PARAMS) \
        or params.get("part") in ("refunds_cohort", "refunds_processed", "basis")


STAGE_PRED = {
    "sent": lambda r: True, "delivered": lambda r: r.get("delivered_date") is not None,
    "mature": lambda r: bool(r.get("mature")), "in_transit": lambda r: r["state"] == "in_transit",
    "pending": lambda r: r["state"] == "pending", "converted": lambda r: r["state"] == "matched",
    "no_video_mature": lambda r: r["state"] == "no_video", "unknown": lambda r: r["state"] == "unknown",
}


def lag_bucket(days):
    if days is None:
        return None
    return "0-7" if days <= 7 else "8-14" if days <= 14 else "15-21" if days <= 21 else "22-30" if days <= 30 else None


def chart_evidence(metric_key: str, params: dict, repo) -> dict:
    """params: brand_id, creator_id, month, cutoff, date_from, date_to, bucket, stage, part, metric, goal_id, limit, offset."""
    rev, svc = repo.revision(), MetricService(repo)
    brand_id, creator_id = params.get("brand_id"), params.get("creator_id")
    month, cutoff = params.get("month") or "2026-10", params.get("cutoff") or "2026-10-15"
    cut = date.fromisoformat(cutoff)
    d_from = date.fromisoformat(params["date_from"]) if params.get("date_from") else None
    d_to = date.fromisoformat(params["date_to"]) if params.get("date_to") else None
    part, bucket, stage = params.get("part"), params.get("bucket"), params.get("stage")
    f = Filters(brand_id=brand_id, creator_id=creator_id, month=month, cutoff=cutoff, goal_id=params.get("goal_id"))
    extra = {k: params[k] for k in ("date_from", "date_to", "bucket", "stage", "part", "metric") if params.get(k)}
    warnings: list[str] = []
    excl: dict = {}
    inputs: list = []
    sources = ["orders", "affiliate_orders"]
    unit, kind = "USD", "sum"
    recs: list[tuple[dict, bool]] = []
    label = definition = formula = ""
    value = None

    def _rec(r, inc):
        r = dict(r)
        sf, sl = r.pop("source_file", None), r.pop("source_locator", None)
        if sf is None and r.get("source_file_id") is not None:
            sf, sl = f"bronze.source_file#{r['source_file_id']}", f"row {r.get('row_num')}"
        return {"source_file": sf, "source_locator": sl, "included": inc, "values": jsonable(r)}

    def tally(why, amt=None, currency=None):
        k = why if currency is None else why + ":" + str(currency)
        e = excl.setdefault(k, {"reason": why, "count": 0, "_a": Decimal(0), "_ok": True, "currency": currency})
        e["count"] += 1
        if amt is None:
            e["_ok"] = False
        else:
            e["_a"] += _d(amt)

    if metric_key in ("gmv", "creator_attributed_gmv", "net_attributed_sales", "creator_concentration") and part in (None, "unresolved"):
        if metric_key == "creator_concentration":
            d_from = d_to = None
            f_cut = repo.as_of() if hasattr(repo, "as_of") else cut
            rows = repo.evidence_sales(brand_id, creator_id, None, None, f_cut)
        else:
            rows = repo.evidence_sales(brand_id, creator_id, d_from, d_to, cut)
        net = metric_key == "net_attributed_sales"
        need_resolved = metric_key != "gmv" or False
        label, definition = {"gmv": ("GMV (shop, eligible)", "Eligible GMV on the selected days."),
                             "creator_attributed_gmv": ("Creator-attributed GMV", "Eligible GMV on lines attributed to a resolved creator."),
                             "net_attributed_sales": ("Net attributed sales", "Attributed GMV minus completed refunds (by the cutoff)."),
                             "creator_concentration": ("Creator gross attributed GMV", "Eligible resolved GMV of one creator, all months through the data as-of date.")}[metric_key]
        formula = "sum(paid_amount - refunded) over included lines" if net else "sum(paid_amount) over included lines"
        for r in rows:
            amt = (None if r.get("gmv") is None or (net and r.get("refunded") is None) else (r["gmv"] - r["refunded"] if net else r["gmv"]))
            non_usd = (not r["eligible"]) and r.get("exclusion_reason") == "non_usd_currency"
            if not r["eligible"]:
                why = "non_usd_currency" if non_usd else "not_eligible"
            elif bucket and r["bucket"] != bucket:
                why = "other_bucket"
            elif need_resolved and not bucket and r["bucket"] != "resolved":
                why = "no_creator_attribution" if r["bucket"] == "none" else "creator_" + str(r["bucket"])
            else:
                why = None
            if why == "non_usd_currency":
                tally(why, r.get("paid_amount"), r.get("currency"))
            elif why:
                tally(why, r.get("gmv"))
            r = dict(r, amount=amt)
            r.pop("paid_amount", None)
            recs.append((r, why is None))
        inc = [r for r, i in recs if i]
        unknown = sum(1 for r in inc if r["amount"] is None)
        value = None if unknown else money(sum((_d(r["amount"]) for r in inc), Decimal(0)))
        if unknown:
            warnings.append(f"{unknown} line(s) have an unknown amount; value is unknown.")
        inputs = [{"label": "Included lines", "value": len(inc), "unit": "count"}]
    elif metric_key == "net_attributed_sales" and part in ("refunds_cohort", "refunds_processed") or (
            part in ("refunds_cohort", "refunds_processed")):
        processed = part == "refunds_processed"
        rows = repo.evidence_refunds(brand_id, d_from, d_to, cut, processed)
        label = "Attributed refunds (" + ("processed" if processed else "cohort") + ")"
        definition = ("Completed merchandise refunds on eligible resolved lines, by " +
                      ("completion day" if processed else "the original order day") + ", completed by the cutoff.")
        formula = "sum(merch_amount)"
        recs = [(dict(r, amount=r.get("merch_amount")), True) for r in rows]
        unknown = sum(1 for r, _ in recs if r["amount"] is None)
        value = None if unknown else money(sum((_d(r["amount"]) for r, _ in recs), Decimal(0)))
        if unknown:
            warnings.append(f"{unknown} refund(s) have an unknown amount; value is unknown.")
        sources = ["orders", "affiliate_orders", "returns"]
        inputs = [{"label": "Refund rows", "value": len(recs), "unit": "count"}]
    elif metric_key in ("videos", "active_creators"):
        rows = repo.evidence_videos(brand_id, d_from, d_to)
        recs = [(dict(r), bool(r["qualifies"])) for r in rows]
        seen = {(r["creator_id"] if metric_key == "active_creators" else (r["brand_id"], r["video_id"])) for r, i in recs if i}
        value, unit, kind, sources = str(len(seen)), "count", "distinct_count", ["videos_weekly"]
        label = "Videos" if metric_key == "videos" else "Active creators"
        definition = "Distinct qualifying " + ("videos" if metric_key == "videos" else "creators") + " in the period."
        formula = "count(distinct " + ("video_id" if metric_key == "videos" else "creator_id") + ") where qualifies"
        inputs = [{"label": "Qualifying rows", "value": sum(1 for _, i in recs if i), "unit": "count"}]
    elif metric_key == "sample_conversion_rate":
        rows = repo.evidence_samples(brand_id)
        pred = STAGE_PRED[stage or "sent"]
        recs = [(dict(r), bool(pred(r)) and (not bucket or lag_bucket(r.get("delivery_to_video_days")) == bucket)) for r in rows]
        value, unit, kind, sources = str(sum(1 for _, i in recs if i)), "count", "distinct_count", ["samples", "videos_weekly"]
        label = "Sample items: " + (stage or "sent") + (f" ({bucket} days)" if bucket else "")
        definition = "Sample items in the funnel stage" + (f" with a delivery-to-video lag of {bucket} days" if bucket else "") + "."
        formula = "count(sample items) where stage = " + (stage or "sent")
        inputs = [{"label": "Sample items", "value": len(rows), "unit": "count"}]
    elif metric_key == "retainer_cadence":
        mms = [date.fromisoformat(m + "-01") for m in trailing_months(month)]  # same three complete months the chart plots
        rows = [r for r in repo.retainer(brand_id, mms) if not creator_id or r["creator_id"] == creator_id]
        recs = [(dict(r), True) for r in rows]
        unit, kind, sources = "count", "ratio", ["videos_weekly", "roster"]
        label, definition = "Retainer cadence", "Posts delivered against the prorated contracted posts for the month."
        formula = "posts / expected_posts"
        value = None if not rows or rows[0].get("posts") is None or (rows[0].get("n_gaps") is not None and rows[0]["n_gaps"] > 0) else str(int(rows[0]["posts"]))
        inputs = [{"label": "Expected posts", "value": _s(rows[0].get("expected_posts")) if rows else None, "unit": "count"}]
        if value is None:
            warnings.append("weekly video coverage has gaps, so posts and attainment are unknown")
    elif metric_key == "decomposition":
        rows = repo.diag(brand_id)
        recs = [(dict(r), True) for r in rows]
        unit, kind, sources = "USD", "decomposition", ["orders", "affiliate_orders", "videos_weekly"]
        label, definition = "Where it broke (Shapley decomposition)", "Current period versus the same days of the previous month."
        formula = "linked GMV = A x V x G; Shapley effects + change in unlinked older GMV = change in total"
        from app.metrics.diagnostics import build_diagnostics
        d = build_diagnostics(repo, brand_id, month, cutoff)
        value = d["total"]["delta"]["value"]
        inputs = [{"label": "Baseline total", "value": d["total"]["baseline"]["value"], "unit": "USD"},
                  {"label": "Current total", "value": d["total"]["current"]["value"], "unit": "USD"}]
    elif metric_key == "portfolio_pacing" and part == "progress":
        kp = next(k for k in build_kpis(repo, month, cutoff)["kpis"] if k["metric_key"] == (params.get("metric") or "gmv"))
        value, unit, kind, label = (kp["progress"] or {}).get("value"), "ratio", "goal", "Portfolio progress"
        definition, formula = "Portfolio actual divided by the sum of brand targets, capped at 1.5.", "min(actual / target, 1.5)"
        inputs = [{"label": "Actual", "value": kp["value"]["value"], "unit": kp["value"]["unit"]}]
        if value is None:
            warnings.append((kp["progress"] or {}).get("status_reason") or "progress is unknown")
    elif metric_key == "portfolio_pacing":
        rows = [g for g in repo.goals(None, month) if g["metric_key"] == (params.get("metric") or "gmv")
                and (g["scope"] == "shop" or (params.get("metric") or "gmv") != "gmv")]
        col = {"projection": "projection", "target": "target_value", "required_pace": "required_pace"}.get(part or "projection", "projection")
        recs = [(dict(r), True) for r in rows]
        value = _m(sum_or_none(r.get(col) for r in rows)) if (params.get("metric") or "gmv") == "gmv" else _s(sum_or_none(r.get(col) for r in rows))
        unit = "USD" if (params.get("metric") or "gmv") == "gmv" else "count"
        kind, label = "goal", "Portfolio " + (part or "projection")
        definition, formula = "Sum of the brand goals for the month.", f"sum({col}) over brand goals"
        inputs = [{"label": "Goals", "value": len(rows), "unit": "count"}]
        if value is None:
            warnings.append("a brand goal value is unknown, so the portfolio value is unknown")
    else:
        raise KeyError(metric_key)

    status, reason, cov = svc.status_for(sources, brand_id)
    if value is None and status == "current":
        status, reason = "partial", reason or "value unknown"
    recs_out = sorted((_rec(r, i) for r, i in recs), key=lambda x: (str(x["source_file"]), str(x["source_locator"])))
    limit = max(1, min(int(params.get("limit") or 100), 500))
    offset = max(0, int(params["offset"])) if params.get("offset") not in (None, "") else 0  # paging default
    page = recs_out[offset:offset + limit]
    cols = sorted({k for r in page for k in r["values"]})
    start = date.fromisoformat(month + "-01")
    return {
        "label": label, "definition": definition, "definition_version": DEFINITION_VERSION,
        "period_start": (d_from or start).isoformat(), "period_end": min(d_to or cut, cut).isoformat(),
        "timezone": "America/Los_Angeles",
        "result": mv_dict(metric_key, value, unit, f, status, reason, cov, rev, **extra),
        "calculation": {"kind": kind, "formula": formula, "inputs": inputs},
        "exclusions": exclusion_items(excl),
        "warnings": warnings, "columns": cols, "records": page,
        "total_count": len(recs_out), "limit": limit, "offset": offset,
        "next_offset": offset + limit if offset + limit < len(recs_out) else None,
        "records_truncated": offset + limit < len(recs_out),
        **_plain_chart_evidence(repo, metric_key, part, label, brand_id, creator_id, sources, excl, recs_out, status, reason, cols),
    }
