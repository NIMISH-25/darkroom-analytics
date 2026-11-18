"""S13 charts, S14 diagnostics, S15 notes, S16 evidence pagination, S17 caching (non-mutating), S18 portfolio KPIs.
Golden expected values: tests/golden/expected.yaml (v2.*). Needs the amendment-2 backend and golden batch_3."""
import json

import httpx
import pytest

from conftest import BASE_URL
from helpers import API, V2, assert_mv, chart, dec, find_goal, get_json, points_by_x, sv

pytestmark = [pytest.mark.v2, pytest.mark.after_b3]
BRANDS = ["aurelle", "verdant", "crunchwell", "threadline", "glowhaus"]
SERIES = ["pacing_trajectory", "daily_gmv_refunds", "attribution_reconciliation", "sample_funnel_lag",
          "creator_concentration", "retainer_cadence"]
ENVELOPE = {"series", "brand_id", "month", "cutoff", "data_revision", "definition_version", "coverage_through",
            "status", "status_reason", "units", "meta", "points"}
POINT_STATUS = {"current", "partial", "stale", "unavailable", "forecast"}


# ------------------------------------------------------------------ S13
@pytest.mark.parametrize("brand", BRANDS)
@pytest.mark.parametrize("series", SERIES)
def test_s13_every_series_returns_the_envelope(client, brand, series):
    kw = {"metric": "gmv"} if series == "pacing_trajectory" else {}
    body = chart(client, series, brand, month="2026-10", cutoff="2026-10-15", **kw)
    assert ENVELOPE <= set(body), f"missing {ENVELOPE - set(body)}"
    assert body["series"] == series and body["brand_id"] == brand
    assert isinstance(body["points"], list)
    for p in body["points"]:
        assert "x" in p and "status" in p and "evidence_urls" in p
        assert p["status"] in POINT_STATUS, p["status"]
        if p["status"] in ("stale", "unavailable", "partial"):
            assert any(v is None for k, v in p.items() if k not in ("x", "status", "status_reason", "evidence_urls",
                                                                   "group", "brand_id", "creator_id", "handle")) \
                or p.get("status_reason"), "a non-current point must carry null values or a reason"


def test_s13_pacing_and_daily_cover_every_day_of_the_month(client):
    for series, kw in (("pacing_trajectory", {"metric": "gmv"}), ("daily_gmv_refunds", {})):
        body = chart(client, series, "aurelle", month="2026-10", cutoff="2026-10-15", **kw)
        xs = [p["x"] for p in body["points"]]
        assert xs == [f"2026-10-{d:02d}" for d in range(1, 32)], series


def test_s13_daily_gmv_values_and_sum_equals_overview_actual(client):
    e = V2["s13"]["daily"]
    body = chart(client, "daily_gmv_refunds", e["brand_id"], month=e["month"], cutoff=e["cutoff"])
    pts = points_by_x(body)
    d5, d20 = e["day_0105"], e["day_1020"]
    for k in ("gmv", "creator_attributed_gmv", "attributed_refunds_cohort", "net_attributed_sales"):
        assert pts[d5["x"]][k] is not None and dec(pts[d5["x"]][k]) == dec(d5[k]), k
    assert dec(pts[d20["x"]]["attributed_refunds_processed"]) == dec(d20["attributed_refunds_processed"])
    x = e["cross_check"]
    assert dec(pts[d20["x"]]["attributed_refunds_cohort"]) == dec(x["cohort_on_completion_day"]), "cohort goes to the ORDER day"
    assert dec(pts[d5["x"]]["attributed_refunds_processed"]) == dec(x["processed_on_order_day"]), "processed goes to the completion day"
    assert dec(pts[d20["x"]]["net_attributed_sales"]) == dec(x["net_on_completion_day"])
    at15 = chart(client, "daily_gmv_refunds", "aurelle", month="2026-10", cutoff="2026-10-15")
    total = sum(dec(p["gmv"]) for p in at15["points"] if p["x"] <= "2026-10-15" and p["gmv"] is not None)
    assert total == dec(e["sum_gmv_to_1015"])
    ov = get_json(client, f"{API}/overview", month="2026-10", cutoff="2026-10-15")
    assert dec(find_goal(ov, "aurelle", "gmv")["actual"]["value"]) == total, "daily GMV must sum to the overview actual"


def test_s13_reconciliation_buckets_sum_to_eligible_gmv(client):
    e = V2["s13"]["reconciliation"]
    body = chart(client, "attribution_reconciliation", e["brand_id"], month=e["month"], cutoff="2026-10-15")
    pts = points_by_x(body)
    assert set(pts) == {"resolved", "creator_unresolved", "none", "conflict"}
    for bucket, want in e["buckets"].items():
        assert dec(pts[bucket]["amount"]) == dec(want["amount"]), bucket
        assert pts[bucket]["order_items"] == want["order_items"], bucket
        assert abs(dec(pts[bucket]["pct"]) - dec(want["pct"])) < dec("0.0002"), bucket
    assert sum(dec(p["amount"]) for p in pts.values()) == dec(e["total"])
    assert sum(dec(p["pct"]) for p in pts.values()) == dec("1"), "largest-remainder pct must sum to exactly 1"
    gm = get_json(client, f"{API}/metrics/gmv/evidence", brand_id="aurelle", month=e["month"], cutoff="2026-10-15")
    assert dec(gm["result"]["value"]) == dec(e["total"])


def test_s13_sample_funnel_matches_samples_counts(client):
    e = V2["s13"]["funnel"]
    body = chart(client, "sample_funnel_lag", e["brand_id"], month="2026-10", cutoff="2026-10-15")
    stage = {p["x"]: p["count"] for p in body["points"] if p.get("group") == "stage"}
    lag = {p["x"]: p["count"] for p in body["points"] if p.get("group") == "lag"}
    for k, v in {**e["stages"], **e["partition"]}.items():
        assert stage[k] == v, f"stage {k}"
    assert sum(stage[k] for k in e["partition"]) == stage["sent"], "partition must sum to sent"
    assert lag == e["lag"] and sum(lag.values()) == stage["converted"]
    counts = get_json(client, f"{API}/brands/{e['brand_id']}/samples")["counts"]
    assert dec(counts["sent"]["value"]) == stage["sent"] and dec(counts["delivered"]["value"]) == stage["delivered"]
    assert dec(counts["matched"]["value"]) == stage["converted"]
    assert dec(counts["no_video"]["value"]) == stage["no_video_mature"]
    assert dec(counts["unknown"]["value"]) == stage["unknown"]
    assert dec(counts["pending"]["value"]) == stage["pending"] + stage["in_transit"]


def test_s13_creator_concentration_lorenz(client):
    e = V2["s13"]["concentration"]
    body = chart(client, "creator_concentration", e["brand_id"], month=e["month"], cutoff=e["cutoff"])
    pts = body["points"]
    assert len(pts) >= len(e["points"])
    basis = str(body["meta"].get("basis", "")).lower()
    assert "all months" in basis and e["cutoff"] in basis, f"meta.basis: {basis!r}"
    for want, got in zip(e["points"], pts):
        assert got["x"] == want["x"] and got["creator_id"] == want["creator_id"]
        assert dec(got["gmv"]) == dec(want["gmv"]), f"{want['creator_id']}.gmv"
        # share is an exact 0-1 ratio (0.7241 +/- 0.00005 after 4-decimal rounding)
        assert abs(dec(got["share"]) - dec(want["share"])) < dec("0.00006"), f"{want['creator_id']}.share (0-1 ratio)"
        # cum_*_pct (and share_pct if present) are PERCENT values 0-100 rounded to ONE decimal: tolerance 0.06
        for k in ("cum_creator_pct", "cum_gmv_pct"):
            assert abs(dec(got[k]) - dec(want[k])) < dec("0.06"), f"{want['creator_id']}.{k}: {got[k]} vs {want[k]}"
        if got.get("share_pct") is not None:
            assert abs(dec(got["share_pct"]) - dec(want["share"]) * 100) < dec("0.06"), f"{want['creator_id']}.share_pct"
    assert "unresolved_gmv" in body["meta"]


def test_s13_retainer_cadence_prorated_and_null_without_coverage(client):
    e = V2["s13"]["cadence"]
    body = chart(client, "retainer_cadence", e["brand_id"], month="2026-10", cutoff="2026-10-15")
    mine = {p["x"]: p for p in body["points"] if p.get("creator_id") == e["creator_id"]}
    sep = mine[e["sep"]["x"]]
    assert dec(sep["expected_posts"]) == dec(e["sep"]["expected_posts"])           # 4 * 15/30
    assert sep["posts"] == e["sep"]["posts"] and dec(sep["attainment_pct"]) == dec(e["sep"]["attainment_pct"])
    for m in e["absent_months"]:
        assert m not in mine, f"{m}: contract not effective, no point expected (ruling 4)"


def test_s13_gap_points_are_null_with_status_never_zero(client):
    e = V2["s13"]["gap"]
    body = chart(client, e["series"], e["brand_id"], month=e["month"], cutoff=e["cutoff"], metric=e["metric"])
    assert body["status"] != "current" and body["status_reason"]
    nulls = [p for p in body["points"] if p["status"] in ("stale", "partial", "unavailable")]
    assert nulls, "a video gap must produce non-current points"
    for p in nulls:
        assert p.get("actual") is None, f"{p['x']}: gap point plotted as {p.get('actual')!r}"


def test_s13_portfolio_charts_cover_all_brands(client):
    body = chart(client, "daily_gmv_refunds", None, month="2026-10", cutoff="2026-10-15")
    assert body["brand_id"] is None and ENVELOPE <= set(body)
    body = chart(client, "creator_concentration", None, month="2026-09", cutoff="2026-10-15")
    assert {p.get("brand_id") for p in body["points"]} <= set(BRANDS) | {None}


def test_s13_every_chart_point_evidence_url_resolves(client, base_url):
    body = chart(client, "daily_gmv_refunds", "aurelle", month="2026-10", cutoff="2026-10-20")
    urls = [u for p in body["points"] for u in p["evidence_urls"].values() if u][:6]
    assert urls, "chart points must link to evidence"
    for u in urls:
        r = client.get(u if u.startswith("http") else base_url + u)
        assert r.status_code == 200, (u, r.status_code)


# ------------------------------------------------------------------ S14
def test_s14_shapley_hand_derived_values(client):
    e = V2["s14"]
    body = get_json(client, f"{API}/brands/{e['brand_id']}/diagnostics", month=e["month"], cutoff=e["cutoff"])
    for k in ("periods", "method", "status", "disclaimer", "total", "factors", "unlinked_older_gmv", "products"):
        assert k in body, k
    d = body["disclaimer"].lower()
    assert any(w in d for w in ("cause", "why", "prove", "proof")), f"disclaimer must say this does not prove why: {d!r}"
    for k in ("baseline", "current", "delta"):
        assert dec(sv(body["total"][k])) == dec(e["total"][k]), f"total.{k}"
        assert dec(sv(body["unlinked_older_gmv"][k])) == dec(e["unlinked_older_gmv"][k]), f"unlinked.{k}"
    assert len(body["factors"]) == 3
    for want, got in zip(e["factors"], body["factors"]):
        assert abs(dec(sv(got["baseline"])) - dec(want["baseline"])) < dec("0.01")
        assert abs(dec(sv(got["current"])) - dec(want["current"])) < dec("0.01")
        assert abs(dec(sv(got["effect"])) - dec(want["effect"])) < dec("0.01"), got


def test_s14_effects_plus_unlinked_change_equal_total_change(client):
    for brand in BRANDS:
        body = get_json(client, f"{API}/brands/{brand}/diagnostics", month="2026-10", cutoff="2026-10-15")
        effects = [sv(f["effect"]) for f in body["factors"]]   # each side is {value, unavailable_reason}; None = unavailable
        unlinked, total = sv(body["unlinked_older_gmv"]["delta"]), sv(body["total"]["delta"])
        if any(x is None for x in effects) or unlinked is None or total is None:
            continue
        # exact to the cent: sum of effects + change in unlinked GMV = change in total
        assert sum(dec(x) for x in effects) + dec(unlinked) == dec(total), brand


def test_s14_incomplete_coverage_gives_null_effects(client):
    body = get_json(client, f"{API}/brands/{V2['s14']['null_brand']}/diagnostics", month="2026-10", cutoff="2026-10-15")
    assert body["status"] != "current"
    assert all(sv(f["effect"]) is None for f in body["factors"]), "null (not 0) when coverage is incomplete"


# ------------------------------------------------------------------ S15
def _notes_url(brand="aurelle", creator="cr_0001"):
    return f"{API}/brands/{brand}/creators/{creator}/notes"


def test_s15_post_get_round_trip_and_validation(client):
    e = V2["s15"]
    url = _notes_url(e["brand_id"], e["creator_id"])
    rev = get_json(client, f"{API}/meta")["data_revision"]
    before = get_json(client, url)["total_count"]
    r = client.post(url, json={"body": e["body_raw"]})
    assert r.status_code == 201, r.text
    n = r.json()
    assert {"note_id", "brand_id", "creator_id", "author", "body", "created_at"} <= set(n)
    assert n["body"] == e["body_stored"] and n["author"] == e["author"]
    assert n["brand_id"] == e["brand_id"] and n["creator_id"] == e["creator_id"]
    got = get_json(client, url)
    assert got["total_count"] == before + 1
    assert got["items"][0]["note_id"] == n["note_id"], "newest first"
    assert get_json(client, f"{API}/meta")["data_revision"] == rev, "notes must not change data_revision"
    assert get_json(client, _notes_url("verdant", "cr_0001"))["total_count"] >= 0     # per-brand scope


def test_s15_validation_rules(client):
    e = V2["s15"]
    url = _notes_url(e["brand_id"], e["creator_id"])
    for bad in ({"body": ""}, {"body": "   \n\t "}, {}, {"body": "x" * (e["max_len"] + 1)}, {"body": None}):
        assert client.post(url, json=bad).status_code == 422, f"invalid body accepted: {str(bad)[:30]}"
    ok = client.post(url, json={"body": "y" * e["max_len"]})
    assert ok.status_code == 201 and len(ok.json()["body"]) == e["max_len"]
    assert client.put(url, json={"body": "x"}).status_code in (404, 405), "append-only"
    assert client.delete(url).status_code in (404, 405)


def test_s15_notes_require_auth(anon):
    assert anon.get(_notes_url()).status_code == 401
    assert anon.post(_notes_url(), json={"body": "x"}).status_code == 401


@pytest.mark.mutating
def test_s15_notes_survive_replay(client, ingest):
    e = V2["s15"]
    url = _notes_url(e["brand_id"], e["creator_id"])
    client.post(url, json={"body": "survives replay"})
    before = get_json(client, url)
    rev = get_json(client, f"{API}/meta")["data_revision"]
    for folder in ("batch_1", "batch_2", "batch_3"):
        assert ingest(folder).returncode == 0
    after = get_json(client, url)
    assert after == before, "notes changed by a replay"
    assert get_json(client, f"{API}/meta")["data_revision"] == rev


# ------------------------------------------------------------------ S16
def test_s16_pages_cover_all_rows_exactly_once(client):
    e = V2["s16"]
    rev = get_json(client, f"{API}/meta")["data_revision"]
    path = f"{API}/metrics/{e['metric']}/evidence"
    first = get_json(client, path, **e["params"], revision=rev, limit=100)
    total = first["total_count"]
    assert total >= e["min_included_rows"] and first["limit"] == 100 and first["offset"] == 0
    seen, summary = [], None
    offset, limit = 0, 1
    while offset is not None:
        pg = get_json(client, path, **e["params"], revision=rev, limit=limit, offset=offset)
        seen += [(r["source_file"], r["source_locator"]) for r in pg["records"]]
        snap = json.dumps([pg["result"], pg["calculation"], pg["exclusions"]], sort_keys=True)
        summary = summary or snap
        assert snap == summary, "result/calculation/exclusions must cover ALL rows on every page"
        offset = pg["next_offset"]
        assert len(seen) <= total
    assert len(seen) == total and len(set(seen)) == total, "each row exactly once"
    assert dec(first["result"]["value"]) == dec(e["result"])


def test_s16_limit_bounds_and_empty_tail(client):
    e = V2["s16"]
    rev = get_json(client, f"{API}/meta")["data_revision"]
    path = f"{API}/metrics/{e['metric']}/evidence"
    for bad in (501, 0, -1, 10000):
        r = client.get(path, params={**e["params"], "revision": rev, "limit": bad})
        assert r.status_code == 422, f"limit={bad} -> {r.status_code}"
    assert client.get(path, params={**e["params"], "revision": rev, "limit": 500}).status_code == 200
    tail = get_json(client, path, **e["params"], revision=rev, limit=10, offset=100000)
    assert tail["records"] == [] and tail["next_offset"] is None


# ------------------------------------------------------------------ S17 (non-mutating part)
CACHED = [f"{API}/overview", f"{API}/brands/aurelle/creators", f"{API}/brands/aurelle/charts?series=daily_gmv_refunds"]


@pytest.mark.parametrize("route", CACHED)
def test_s17_etag_and_304(client, route):
    r1 = client.get(route)
    assert r1.status_code == 200
    etag = r1.headers.get("etag")
    assert etag and etag.startswith('"'), "strong ETag expected"
    cc = r1.headers.get("cache-control", "").lower()
    assert "private" in cc and "no-cache" in cc
    r2 = client.get(route, headers={"If-None-Match": etag})
    assert r2.status_code == 304 and not r2.content
    r3 = client.get(route, headers={"If-None-Match": '"not-the-etag"'})
    assert r3.status_code == 200 and r3.headers["etag"] == etag, "same data, same ETag"


def test_s17_never_304_without_auth_and_401_not_cacheable(anon, client):
    etag = client.get(f"{API}/overview").headers["etag"]
    r = anon.get(f"{API}/overview", headers={"If-None-Match": etag})
    assert r.status_code == 401, "cache lookup must happen after authentication"
    assert "etag" not in r.headers
    assert "max-age" not in r.headers.get("cache-control", "")


def test_s17_409_is_not_cached(client):
    rev = get_json(client, f"{API}/meta")["data_revision"]
    r = client.get(f"{API}/metrics/gmv/evidence", params={"brand_id": "aurelle", "revision": rev - 1})
    assert r.status_code == 409
    assert "etag" not in r.headers
    r2 = client.get(f"{API}/metrics/gmv/evidence", params={"brand_id": "aurelle", "revision": rev - 1},
                    headers={"If-None-Match": '"*"'})
    assert r2.status_code == 409


def test_s17_notes_and_health_are_not_etagged(client):
    assert "etag" not in client.get("/healthz").headers
    assert "etag" not in client.post(_notes_url(), json={"body": "cache probe"}).headers


# ------------------------------------------------------------------ S18
def _brand_values(client, key, month, cutoff):
    return [metric_value(client, key, b, month, cutoff) for b in BRANDS]


def metric_value(client, key, brand, month, cutoff):
    ev = get_json(client, f"{API}/metrics/{key}/evidence", brand_id=brand, month=month, cutoff=cutoff)
    return ev["result"]["value"]


def test_s18_portfolio_kpis_envelope(client):
    body = get_json(client, f"{API}/portfolio/kpis")
    assert {"data_revision", "kpis", "pace_counts"} <= set(body) and body["kpis"]
    assert set(body["pace_counts"]) >= {"on_track", "at_risk", "off_track", "unknown"}
    for k in body["kpis"]:
        assert {"metric_key", "value", "baseline", "delta", "delta_pct", "brands_covered", "brands_total"} <= set(k)
        for f in ("value", "baseline", "delta", "delta_pct"):
            assert_mv(k[f], f"{k['metric_key']}.{f}")
        assert k["brands_total"] == 5 and 0 <= k["brands_covered"] <= 5


def test_s18_gmv_kpi_hand_derived_and_equals_sum_of_brands(client):
    e = V2["s18"]
    body = get_json(client, f"{API}/portfolio/kpis", month=e["month"], cutoff=e["cutoff"])
    k = next(x for x in body["kpis"] if x["metric_key"] == "gmv")
    assert dec(k["value"]["value"]) == dec(e["gmv"])
    vals = _brand_values(client, "gmv", e["month"], e["cutoff"])
    assert all(v is not None for v in vals)
    assert sum(dec(v) for v in vals) == dec(k["value"]["value"]), "KPI must equal the sum of brand values"
    assert k["brands_covered"] == e["brands_total"]


def test_s18_additive_kpis_follow_the_null_guard_and_pace_counts_match_overview(client):
    body = get_json(client, f"{API}/portfolio/kpis")
    ov = get_json(client, f"{API}/overview")
    for k in body["kpis"]:
        if k["metric_key"] in ("gmv", "creator_attributed_gmv", "net_attributed_sales", "videos"):
            vals = _brand_values(client, k["metric_key"], "2026-10", "2026-10-15")
            if any(v is None for v in vals):
                assert k["value"]["value"] is None, f"{k['metric_key']}: a brand is unknown, portfolio must be null"
            else:
                assert dec(k["value"]["value"]) == sum(dec(v) for v in vals), k["metric_key"]
    counts = {}
    for b in ov["brands"]:
        for g in b["goals"]:
            counts[g["pace_status"]] = counts.get(g["pace_status"], 0) + 1
    for state in ("on_track", "at_risk", "off_track", "unknown"):
        assert body["pace_counts"][state] == counts.get(state, 0), state
