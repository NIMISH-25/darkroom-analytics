import random
from datetime import date, timedelta
from decimal import Decimal as D
from fractions import Fraction

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.api import routes_charts
from app.metrics import charts, diagnostics

SOURCES = ("orders", "affiliate_orders", "returns", "videos_weekly", "samples", "roster")
DAYS = [date(2026, 10, d) for d in range(1, 32)]
# (brand, day, bucket, gmv) order lines; Oct 15 is a coverage gap for glow
LINES = []
for b, base in (("aur", 100), ("glow", 50)):
    for i, d in enumerate(DAYS[:15]):
        LINES.append((b, d, "resolved", D(base + i) + D("0.25")))
        LINES.append((b, d, "creator_unresolved", D("3.10")))
        LINES.append((b, d, "none", D("1.05")))
SAMPLES = [
    dict(brand_id="aur", state=s, delivered_date=None if s in ("pending", "in_transit") else date(2026, 8, 5),
         mature=s in ("matched", "no_video"), delivery_to_video_days=days)
    for s, days in (("matched", 3), ("matched", 10), ("matched", 25), ("no_video", None), ("in_transit", None),
                    ("pending", None), ("unknown", None))]


def lag(d):
    return None if d is None else "0-7" if d <= 7 else "8-14" if d <= 14 else "15-21" if d <= 21 else "22-30"


class Stub:
    def revision(self): return 7
    def revision_key(self): return (7, "t")
    def brands(self): return [{"brand_id": "aur", "name": "Aur"}, {"brand_id": "glow", "name": "Glow"}]

    def freshness(self, brand_id=None):
        return [dict(brand_id=b["brand_id"], source_type=s, state="current", coverage_through=date(2026, 10, 15),
                     n_gaps=0, message=None) for b in self.brands() for s in SOURCES
                if brand_id in (None, b["brand_id"])]

    def goals(self, brand_id, month):
        out = []
        for b in self.brands():
            if brand_id in (None, b["brand_id"]):
                out.append(dict(brand_id=b["brand_id"], metric_key="gmv", scope="shop", basis="gross", goal_id="gmv:shop",
                                target_value=D("10000"), projection=D("8000"), required_pace=D("1"), pace_status="at_risk",
                                status="current", status_reason=None, coverage_through=date(2026, 10, 15)))
        return out

    def daily(self, brand_id, d_from, d_to, cutoff):
        rows = []
        for b in self.brands():
            if brand_id not in (None, b["brand_id"]):
                continue
            for d in DAYS:
                if not d_from <= d <= d_to:
                    continue
                ls = [x for x in LINES if x[0] == b["brand_id"] and x[1] == d]
                gap = b["brand_id"] == "glow" and d == date(2026, 10, 15)
                gm = None if gap or not ls else sum(x[3] for x in ls if x[2] != "none" or True)
                at = None if gap or not ls else sum(x[3] for x in ls if x[2] == "resolved")
                rows.append(dict(brand_id=b["brand_id"], day=d, gross_gmv=gm, creator_attributed_gmv=at,
                                 status="missing" if gap else "current",
                                 rc_n=1 if d.day == 3 else None, rc_k=1, rc_s=D("2.00"), rp_n=None, rp_k=None, rp_s=None))
        return rows

    def video_daily(self, brand_id, d_from, d_to): return []

    def reconciliation(self, brand_id, month, cutoff):
        out = {}
        for b, d, bucket, g in LINES:
            if brand_id in (None, b) and d <= cutoff:
                n, k, s = out.get((b, bucket), (0, 0, D(0)))
                out[(b, bucket)] = (n + 1, k + 1, s + g)
        return [dict(brand_id=b, bucket=bk, order_items=n, known=k, amount=s) for (b, bk), (n, k, s) in out.items()]

    def funnel(self, brand_id):
        rows = []
        for b in ("aur",):
            if brand_id not in (None, b):
                continue
            S = [r for r in SAMPLES]
            st = {"sent": len(S), "delivered": sum(r["delivered_date"] is not None for r in S),
                  "mature": sum(r["mature"] for r in S), "in_transit": 1, "pending": 1, "converted": 3,
                  "no_video_mature": 1, "unknown": 1}
            rows += [dict(brand_id=b, stage=k, lag_bucket=None, count=v) for k, v in st.items()]
            for lb in ("0-7", "8-14", "15-21", "22-30"):
                rows.append(dict(brand_id=b, stage="converted", lag_bucket=lb, count=sum(lag(r["delivery_to_video_days"]) == lb for r in S if r["state"] == "matched")))
        return rows

    def concentration(self, brand_id):
        return [dict(brand_id="aur", creator_id=c, handle="@" + c, gross_gmv=g, unresolved=D("1.00"))
                for c, g in (("c2", D("30.00")), ("c1", D("60.00")), ("c3", D("10.00")))]

    def retainer(self, brand_id, months):
        return [dict(brand_id="aur", creator_id="c1", handle="@c1", month=months[0], expected_posts=D("4.0"), posts=2, n_gaps=0),
                dict(brand_id="glow", creator_id="c9", handle="@c9", month=months[0], expected_posts=D("4.0"), posts=None, n_gaps=2)]

    def diag(self, brand_id):
        def row(p, a, v, lv, m, u, prod):
            return dict(brand_id="aur", period=p, active_creators=a, videos=v, linked_videos=lv, linked_gmv=m,
                        unlinked_older_gmv=u, product_id=prod[0], product_gmv=prod[1], coverage_status="current")
        return self._diag_aur()

    def _diag_aur(self):
        def row(p, a, v, lv, m, u, prod):
            return dict(brand_id="aur", period=p, active_creators=a, videos=v, linked_videos=lv, linked_gmv=m,
                        unlinked_older_gmv=u, product_id=prod[0], product_gmv=prod[1], coverage_status="current")
        return [row("baseline", 10, 40, 30, D("3000.00"), D("100.00"), ("p1", D("2000"))),
                row("baseline", 10, 40, 30, D("3000.00"), D("100.00"), ("p2", D("1000"))),
                row("current", 8, 50, 36, D("2500.01"), D("150.50"), ("p1", D("1500"))),
                row("current", 8, 50, 36, D("2500.01"), D("150.50"), ("p3", D("1000.01")))]

    def distinct_active(self, cur, base): return {"current": 12, "baseline": 15}

    def evidence_sales(self, brand_id, creator_id, d_from, d_to, cutoff):
        return [dict(eligible=True, bucket=bk, gmv=g, refunded=D(0), net=g, creator_id="c1", source_file="orders/a.json",
                     source_locator=f"{b}:{d}:{i}", local_date=d, brand_id=b)
                for i, (b, d, bk, g) in enumerate(LINES)
                if brand_id in (None, b) and d <= cutoff and (d_from is None or d >= d_from) and (d_to is None or d <= d_to)]

    def evidence_refunds(self, *a, **k): return []
    def evidence_videos(self, *a, **k): return []
    def evidence_samples(self, brand_id):
        return [dict(r, sample_id=str(i), source_file="s.xlsx", source_locator=str(i)) for i, r in enumerate(SAMPLES)]
    def as_of(self): return date(2026, 10, 22)


@pytest.fixture
def c():
    app = FastAPI()
    app.include_router(routes_charts.router)
    stub = Stub()
    app.dependency_overrides[auth.current_user] = lambda: "demo"
    app.dependency_overrides[routes_charts.get_charts_repo] = lambda: stub
    return TestClient(app)


def pts(j): return {p["x"]: p for p in j["points"]}


def chart(c, series, brand="aur", **q):
    url = f"/api/v1/brands/{brand}/charts" if brand else "/api/v1/portfolio/charts"
    r = c.get(url, params={"series": series, "month": "2026-10", "cutoff": "2026-10-15", **q})
    assert r.status_code == 200, r.text
    return r.json()


def test_daily_sum_equals_month_actual_and_forecast(c):
    j = chart(c, "daily_gmv_refunds")
    assert len(j["points"]) == 31
    total = sum(D(p["gmv"]) for p in j["points"] if p["gmv"] is not None)
    expect = sum(g for b, d, bk, g in LINES if b == "aur")
    assert total == expect
    assert pts(j)["2026-10-20"]["status"] == "forecast" and pts(j)["2026-10-20"]["gmv"] is None
    assert pts(j)["2026-10-03"]["attributed_refunds_cohort"] == "2.00"
    assert pts(j)["2026-10-04"]["attributed_refunds_cohort"] == "0.00"
    p = pts(j)["2026-10-03"]
    assert D(p["net_attributed_sales"]) == D(p["creator_attributed_gmv"]) - D("2.00")
    assert all(p["evidence_urls"].values())


def test_uncovered_day_null_and_portfolio_guard(c):
    j = chart(c, "daily_gmv_refunds", brand="glow")
    p = pts(j)["2026-10-15"]
    assert p["gmv"] is None and p["status"] == "unavailable" and p["status_reason"]
    pj = chart(c, "daily_gmv_refunds", brand=None)
    assert pts(pj)["2026-10-15"]["gmv"] is None  # any brand unknown -> portfolio unknown, never a partial sum
    assert pts(pj)["2026-10-14"]["gmv"] is not None and pj["brand_id"] is None


def test_reconciliation_sums_and_pct(c):
    j = chart(c, "attribution_reconciliation")
    assert [p["x"] for p in j["points"]] == ["resolved", "creator_unresolved", "none", "conflict"]
    total = sum(D(p["amount"]) for p in j["points"])
    assert total == sum(g for b, d, bk, g in LINES if b == "aur")
    assert sum(D(p["pct"]) for p in j["points"]) == 1
    assert pts(j)["conflict"]["amount"] == "0.00"
    assert D(j["meta"]["eligible_gmv"]["value"]) == total


def test_funnel_matches_samples_counts(c):
    j = chart(c, "sample_funnel_lag")
    st = {p["x"]: p["count"] for p in j["points"] if p["group"] == "stage"}
    lg = {p["x"]: p["count"] for p in j["points"] if p["group"] == "lag"}
    assert st["sent"] == len(SAMPLES) == st["in_transit"] + st["pending"] + st["converted"] + st["no_video_mature"] + st["unknown"]
    assert sum(lg.values()) == st["converted"] == sum(r["state"] == "matched" for r in SAMPLES)
    assert st["converted"] == 3 and st["no_video_mature"] == 1 and st["pending"] + st["in_transit"] == 2
    assert st["delivered"] == sum(r["delivered_date"] is not None for r in SAMPLES)


def test_concentration_and_retainer(c, monkeypatch):
    sales = [("c1", date(2026, 9, 5), D("60.00")), ("c2", date(2026, 10, 2), D("30.00")), ("c3", date(2026, 10, 9), D("10.00")),
             ("c1", date(2026, 10, 20), D("500.00"))]  # after the cutoff: must be ignored
    monkeypatch.setattr(Stub, "evidence_sales", lambda self, b, cr, f, t, cutoff: [
        dict(eligible=True, bucket="resolved", gmv=g, creator_id=c_, brand_id="aur", video_known=(c_ != "c3"), local_date=d,
             source_file="o.json", source_locator=c_) for c_, d, g in sales if d <= cutoff])
    j = chart(c, "creator_concentration")
    assert j["meta"]["basis"].endswith("through 2026-10-15")
    assert j["meta"]["top10_gmv_share"] == "60.0"
    assert [p["creator_id"] for p in j["points"]] == ["c1", "c2", "c3"]
    assert [p["cum_gmv_pct"] for p in j["points"]] == ["60.0", "90.0", "100.0"]
    assert j["points"][-1]["cum_creator_pct"] == "100.0" and j["meta"]["unresolved_gmv"]["value"] == "10.00"
    r = chart(c, "retainer_cadence", brand=None)
    assert [p["x"] for p in r["points"]][0] == "2026-07"
    aur = next(p for p in r["points"] if p["creator_id"] == "c1")
    assert aur["attainment_pct"] == "50.0" and aur["expected_posts"] == "4.00" and aur["brand_id"] == "aur"
    glow = next(p for p in r["points"] if p["creator_id"] == "c9")
    assert glow["posts"] is None and glow["attainment_pct"] is None and glow["status"] == "partial"


def test_pacing(c):
    j = chart(c, "pacing_trajectory")
    p = pts(j)
    assert p["2026-10-15"]["actual"] == p["2026-10-15"]["projection"] == p["2026-10-15"]["required"]
    assert p["2026-10-14"]["projection"] is None and p["2026-10-31"]["projection"] == "8000.00"
    assert p["2026-10-31"]["required"] == "10000.00" and p["2026-10-20"]["status"] == "forecast"
    assert D(p["2026-10-15"]["actual"]) == sum(g for b, d, bk, g in LINES if b == "aur")
    assert set(j["meta"]) >= {"basis", "target", "projection", "required_pace"}
    g = chart(c, "pacing_trajectory", brand="glow")
    assert pts(g)["2026-10-14"]["actual"] is not None and pts(g)["2026-10-15"]["actual"] is None  # null from the first gap


def test_errors(c):
    assert c.get("/api/v1/brands/aur/charts", params={"series": "nope"}).status_code == 422
    assert c.get("/api/v1/brands/zzz/charts", params={"series": "daily_gmv_refunds"}).status_code == 404
    assert c.get("/api/v1/brands/aur/charts", params={"series": "daily_gmv_refunds", "month": "bad"}).status_code == 422


def test_evidence_matches_chart_values(c):
    stub = Stub()
    j = chart(c, "daily_gmv_refunds")
    p = pts(j)["2026-10-04"]
    ev = charts.chart_evidence("gmv", dict(brand_id="aur", month="2026-10", cutoff="2026-10-15", date_from="2026-10-04", date_to="2026-10-04"), stub)
    assert ev["result"]["value"] == p["gmv"] and ev["total_count"] == 3
    assert charts.is_chart_evidence("gmv", {"date_from": "2026-10-04"}) and not charts.is_chart_evidence("gmv", {})
    rec = charts.chart_evidence("gmv", dict(brand_id="aur", month="2026-10", cutoff="2026-10-15", bucket="resolved"), stub)
    rj = pts(chart(c, "attribution_reconciliation"))["resolved"]
    assert rec["result"]["value"] == rj["amount"]
    sf = charts.chart_evidence("sample_conversion_rate", dict(brand_id="aur", stage="converted", bucket="8-14"), stub)
    assert sf["result"]["value"] == "1"
    page = charts.chart_evidence("gmv", dict(brand_id="aur", cutoff="2026-10-15", limit=10, offset=0), stub)
    assert len(page["records"]) == 10 and page["next_offset"] == 10


def test_kpis(c, monkeypatch):
    monkeypatch.setattr(charts, "_actuals_service", lambda repo: FakeActuals())
    Stub.diag = lambda self, b: self._diag_aur() + ([dict(r, brand_id="glow") for r in self._diag_aur()] if b is None else [])
    j = c.get("/api/v1/portfolio/kpis", params={"month": "2026-10", "cutoff": "2026-10-15"}).json()
    k = {x["metric_key"]: x for x in j["kpis"]}
    assert k["active_creators"]["value"]["value"] == "12" and k["active_creators"]["delta"]["value"] == "-3"
    assert k["creator_attributed_gmv"]["value"]["value"] == "300.00" and k["creator_attributed_gmv"]["baseline"]["value"] == "6200.00"
    assert j["pace_counts"] == {"on_track": 0, "at_risk": 2, "off_track": 0, "unknown": 0}
    assert k["creator_attributed_gmv"]["brands_covered"] == 2 and k["creator_attributed_gmv"]["value"]["value"] == "300.00"
    assert k["gmv"]["value"]["value"] == "300.00"  # ruling 5: guarded sum of the brands' actuals


class FakeActuals:
    def compute(self, key, f):
        return {"value": "100.00" if f.brand_id == "aur" else "200.00", "status": "current", "reason": None}


def test_kpis_mixed_bases_only_null_comparisons(c, monkeypatch):
    monkeypatch.setattr(charts, "_actuals_service", lambda repo: FakeActuals())
    orig = Stub.goals

    def goals(self, brand_id, month):
        g = orig(self, brand_id, month)
        return [dict(x, scope="creator_attributed", basis="gross" if x["brand_id"] == "aur" else "net") for x in g]
    monkeypatch.setattr(Stub, "goals", goals)
    j = c.get("/api/v1/portfolio/kpis", params={"month": "2026-10", "cutoff": "2026-10-15"}).json()
    k = next(x for x in j["kpis"] if x["metric_key"] == "creator_attributed_gmv")
    assert k["value"]["value"] == "300.00" and k["brands_covered"] == 2
    for f in ("baseline", "delta", "delta_pct", "progress"):
        assert k[f]["value"] is None and "different ways" in k[f]["status_reason"]


# ---- Shapley
def fr(a, v, g): return (Fraction(a), Fraction(v), Fraction(g))


def test_shapley_exact_and_safe_with_zeros():
    rng = random.Random(1)
    for _ in range(300):
        a0, a1 = rng.randint(1, 30), rng.randint(1, 30)
        v0, v1 = Fraction(rng.randint(0, 90), 7), Fraction(rng.randint(0, 90), 7)
        g0, g1 = Fraction(rng.randint(0, 9999), 100), Fraction(rng.randint(0, 9999), 100)
        f0, f1 = (Fraction(a0), v0, g0), (Fraction(a1), v1, g1)
        assert sum(diagnostics.shapley(f0, f1)) == a1 * v1 * g1 - a0 * v0 * g0
        delta = D(round(float(a1 * v1 * g1 - a0 * v0 * g0), 2)) if False else diagnostics._cents(a1 * v1 * g1 - a0 * v0 * g0)
        eff = diagnostics.effects_cents(f0, f1, delta)
        assert sum(eff) == delta


def test_diagnostics_endpoint(c):
    j = c.get("/api/v1/brands/aur/diagnostics", params={"month": "2026-10", "cutoff": "2026-10-15"}).json()
    sides = {k: v for k, v in j["total"].items() if k != "label"}
    assert {k: v["value"] for k, v in sides.items()} == {"baseline": "3100.00", "current": "2650.51", "delta": "-449.49"}
    assert all(v["unavailable_reason"] is None for v in sides.values())
    assert j["total"]["label"] == "Total sales from linked videos" and j["unlinked_older_gmv"]["label"] == "Sales from older or unlinked videos"
    assert [f["label"] for f in j["factors"]] == ["Active creators", "Videos per active creator", "Sales per video with a link to a creator"]
    assert all(p["label"] == p["name"] for p in j["products"]) and "cause" in j["disclaimer"]
    import re
    for text in [j["total"]["label"], *[f["label"] for f in j["factors"]], *j["notes"], j["disclaimer"], j["method"]]:
        assert not re.search(r"_?[a-z]+_[a-z_]+", text), text  # no key-like words in operator text
    assert j["unlinked_older_gmv"]["delta"]["value"] == "50.50"
    assert sum(D(f["effect"]["value"]) for f in j["factors"]) + D(j["unlinked_older_gmv"]["delta"]["value"]) == D(j["total"]["delta"]["value"])
    assert [f["key"] for f in j["factors"]] == ["active_creators", "videos_per_creator", "gmv_per_video"]
    assert "does not prove the cause" in j["disclaimer"]
    assert j["periods"]["baseline"]["to"] == "2026-09-15"
    assert {p["product_id"] for p in j["products"]} == {"p1", "p2", "p3"}
    assert j["notes"] and all(isinstance(n, str) for n in j["notes"])


def test_diagnostics_nulls():
    s = Stub()
    zero = [dict(r, active_creators=0) if r["period"] == "current" else r for r in s.diag("aur")]
    s.diag = lambda b: zero
    j = diagnostics.build_diagnostics(s, "aur", "2026-10", "2026-10-15")
    assert all(f["effect"]["value"] is None and f["effect"]["unavailable_reason"] for f in j["factors"])
    assert j["total"]["delta"]["value"] is not None and j["status"] == "partial"
    assert any("no active creators" in f["effect"]["unavailable_reason"] for f in j["factors"])
    nul = [dict(r, linked_gmv=None) if r["period"] == "baseline" else r for r in Stub().diag("aur")]
    s.diag = lambda b: nul
    j = diagnostics.build_diagnostics(s, "aur", "2026-10", "2026-10-15")
    assert j["total"]["baseline"]["value"] is None and j["total"]["baseline"]["unavailable_reason"]
    assert j["total"]["delta"]["value"] is None and all(f["effect"]["value"] is None for f in j["factors"])
    assert all(not (f["baseline"]["value"] is None and f["current"]["value"] is None) for f in j["factors"])  # no empty rows


@pytest.fixture(autouse=True)
def _fresh_cache():
    from app.metrics import cache
    cache.clear()
    yield
    cache.clear()


# ---- availability classifier (first match wins)
def env(points, units=("v",), status="current"):
    return {"points": points, "units": {u: "count" for u in units}, "status": status, "status_reason": "why"}


PROFILE_OK = {"creators": 5, "retainers": 2, "affiliates": 3, "samples": 4}


def test_availability_classifier_order():
    cl = charts.classify
    assert cl("retainer_cadence", env([{"v": 1}]), {**PROFILE_OK, "retainers": 0}, "2026-10-15")["status"] == "not_applicable"
    assert cl("creator_concentration", env([{"v": 1}]), {**PROFILE_OK, "creators": 2}, "2026-10-15")["status"] == "not_applicable"
    assert cl("sample_funnel_lag", env([{"v": 1}]), {**PROFILE_OK, "samples": 0}, "2026-10-15")["status"] == "not_applicable"
    assert cl("pacing_trajectory", env([{"v": 1}]), {**PROFILE_OK, "creators": 1}, "2026-10-15")["status"] == "available"  # always shown
    assert cl("creator_concentration", env([]), PROFILE_OK, "2026-10-15")["status"] == "empty"
    assert cl("creator_concentration", env([{"v": None}, {"v": None}]), PROFILE_OK, "2026-10-15")["status"] == "unknown"
    assert cl("creator_concentration", env([{"v": "0.00"}, {"v": None}, {"v": 0}]), PROFILE_OK, "2026-10-15")["status"] == "zero"
    assert cl("creator_concentration", env([{"v": "1"}, {"v": None}], status="stale"), PROFILE_OK, "2026-10-15")["status"] == "stale"
    assert cl("creator_concentration", env([{"v": "1"}]), PROFILE_OK, "2026-10-15")["status"] == "available"
    assert cl("creator_concentration", env([{"v": "1"}]), None, "2026-10-15")["status"] == "available"  # portfolio


def test_every_chart_carries_availability_and_available_route(c, monkeypatch):
    monkeypatch.setattr(charts, "_profile", lambda repo, b, m: PROFILE_OK)
    j = chart(c, "pacing_trajectory")
    assert set(j["availability"]) == {"status", "reason"}
    r = c.get("/api/v1/brands/aur/charts/available", params={"month": "2026-10", "cutoff": "2026-10-15"}).json()
    assert [s["series_id"] for s in r["series"]] == list(charts.SERIES)
    assert all(set(s) == {"series_id", "status", "reason", "as_of", "point_count"} for s in r["series"])
    assert c.get("/api/v1/brands/nope/charts/available").status_code == 404


def test_concentration_share_ratio_and_zero_only_under_full_coverage(c, monkeypatch):
    rows = lambda self, b, cr, f, t, cutoff: [dict(eligible=True, bucket="resolved", gmv=D("50.00"), creator_id="c1", brand_id="aur",
                                                    video_known=True, local_date=date(2026, 10, 2), source_file="o", source_locator="l")]
    monkeypatch.setattr(Stub, "evidence_sales", rows)
    j = chart(c, "creator_concentration")
    p = {x["creator_id"]: x for x in j["points"]}
    assert p["c1"]["share"] == "1.0000" and p["c1"]["share_pct"] == "100.0" and j["units"]["share"] == "ratio"
    assert p["c2"]["gmv"] == "0.00"  # full coverage: verified zero
    orig = Stub.freshness
    monkeypatch.setattr(Stub, "freshness", lambda self, b=None: [dict(r, state="stale" if r["source_type"] == "videos_weekly" else r["state"]) for r in orig(self, b)])
    from app.metrics import cache
    cache.clear()
    p = {x["creator_id"]: x for x in chart(c, "creator_concentration")["points"]}
    assert p["c2"]["gmv"] is None and p["c3"]["gmv"] is None and p["c1"]["gmv"] == "50.00"


def test_kpis_brand_pace(c, monkeypatch):
    monkeypatch.setattr(charts, "_actuals_service", lambda repo: FakeActuals())
    j = c.get("/api/v1/portfolio/kpis", params={"month": "2026-10", "cutoff": "2026-10-15"}).json()
    assert j["brand_pace_counts"] == {"on_track": 0, "behind": 2, "unknown": 0, "total": 2}
    bp = {b["brand_slug"]: b for b in j["brand_pace"]}
    assert bp["aur"]["brand_name"] == "Aur" and bp["aur"]["status_label"] == "Behind pace"
    g = bp["aur"]["goals"][0]
    assert g["goal_name"] == "Total sales" and g["actual_label"] == "$100.00" and g["target_label"] == "$10,000.00"
    assert j["pace_counts"]["at_risk"] == 2  # goal-level counts are kept


def test_brand_pace_unknown_beats_on_track_and_no_target_ignored(c, monkeypatch):
    monkeypatch.setattr(charts, "_actuals_service", lambda repo: FakeActuals())

    def goals(self, brand_id, month):
        base = dict(scope="shop", basis="gross", projection=D("1"), required_pace=D("1"), status="current", status_reason=None,
                    coverage_through=date(2026, 10, 15))
        return [dict(base, brand_id="aur", metric_key="gmv", target_value=D("10"), pace_status="on_track"),
                dict(base, brand_id="aur", metric_key="videos", scope="creator_attributed", target_value=D("10"), pace_status=None),
                dict(base, brand_id="glow", metric_key="gmv", target_value=D("10"), pace_status="on_track"),
                dict(base, brand_id="glow", metric_key="videos", scope="creator_attributed", target_value=None, pace_status="off_track")]
    monkeypatch.setattr(Stub, "goals", goals)
    j = c.get("/api/v1/portfolio/kpis", params={"month": "2026-10", "cutoff": "2026-10-15"}).json()
    bp = {b["brand_slug"]: b["status_label"] for b in j["brand_pace"]}
    assert bp == {"aur": "Not enough data", "glow": "On pace"}  # unknown beats on pace; goal without a target ignored
    assert j["brand_pace_counts"] == {"on_track": 1, "behind": 0, "unknown": 1, "total": 2}


def test_brand_pace_goals_always_have_plain_labels(c, monkeypatch):
    class Unknown:
        def compute(self, key, f):
            return {"value": None, "status": "partial", "reason": "source coverage is partial"}
    monkeypatch.setattr(charts, "_actuals_service", lambda repo: Unknown())
    j = c.get("/api/v1/portfolio/kpis", params={"month": "2026-10", "cutoff": "2026-10-15"}).json()
    for b in j["brand_pace"]:
        assert b["status_label"] in ("On pace", "Behind pace", "Not enough data")
        for g in b["goals"]:
            assert g["actual_label"] == "No data yet" and g["target_label"] and g["status_label"] and g["goal_name"]
            assert g["incomplete_reason"]
