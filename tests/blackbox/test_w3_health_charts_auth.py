"""Wave 3 (docs/api-contract-amendment-3.md): brand-scoped Data Health, chart availability, evidence explainer, demo auth.
Most tests are data-agnostic invariants (any ingested data). Tests marked `synth` assert the seeded FULL synthetic data
(run `pytest -m synth` against a DB holding generated batch_1 + batch_2); `golden_bad` tests assume the golden stage order
of run_blackbox.ps1 (batch_bad ingested in stage 2, before stage 3)."""
import re

import httpx
import pytest

from conftest import BASE_URL
from helpers import API, V2, EXPECTED, assert_left_out_note, dec, get_json

pytestmark = pytest.mark.v2
BRANDS = ["aurelle", "verdant", "crunchwell", "threadline", "glowhaus"]
SERIES = ["pacing_trajectory", "daily_gmv_refunds", "attribution_reconciliation", "sample_funnel_lag",
          "creator_concentration", "retainer_cadence"]
SHARED_LABEL = "Shared Cross-Brand Source"
AVAIL = {"available", "stale", "zero", "unknown", "empty", "not_applicable"}
W3 = EXPECTED.get("w3", {})


def health(client, brand=None):
    return get_json(client, f"{API}/data-health", brand_id=brand)


def brand_files(items, brand):
    return [i for i in items if i.get("scope") == "brand" and i.get("brand_id") == brand]


# ------------------------------------------------------------------ (1) brand-scoped health: invariants
@pytest.mark.parametrize("brand", BRANDS)
def test_w3_health_shape_scope_labels_and_counts(client, brand):
    h = health(client, brand)
    assert {"sources", "failed_files", "runs", "unresolved_identities", "counts"} <= set(h)
    assert {"brand_failed", "shared_failed", "open_issues"} <= set(h["counts"])
    for item in h["sources"] + h["failed_files"]:
        assert item["scope"] in ("brand", "shared"), item
        if item["scope"] == "shared":
            assert item["brand_id"] is None and item["source_label"] == SHARED_LABEL, item
        else:
            assert item["brand_id"] == brand, f"{brand} health lists another brand's item: {item}"
            assert item.get("source_label") is None
    shared = [s for s in h["sources"] if s["scope"] == "shared"]
    assert shared, "shared trackers (roster and samples only; plans are per-brand files) must appear on every brand"
    failed_brand = [f for f in h["failed_files"] if f["scope"] == "brand"]
    failed_shared = [f for f in h["failed_files"] if f["scope"] == "shared"]
    assert h["counts"]["brand_failed"] == len(failed_brand)
    assert h["counts"]["shared_failed"] == len(failed_shared), "shared failures must not count as brand failures"
    assert isinstance(h["counts"]["open_issues"], int)


def test_w3_health_is_not_cached_across_brands(client):
    """Cache-bug guard: sequential calls for different brands must not return each other's files."""
    first = {b: health(client, b) for b in BRANDS}
    again = {b: health(client, b) for b in reversed(BRANDS)}
    for b in BRANDS:
        assert first[b]["failed_files"] == again[b]["failed_files"], f"{b} changed between calls"
        for f in first[b]["failed_files"]:
            assert f["scope"] == "shared" or f["brand_id"] == b
    union = [f["file_name"] for b in BRANDS for f in first[b]["failed_files"] if f["scope"] == "brand"]
    assert len(union) == len(set(union)), "a brand failure appears under more than one brand"


def test_w3_portfolio_lists_each_shared_tracker_once(client):
    port = health(client)
    shared = [s["source"] for s in port["sources"] if s["scope"] == "shared"]
    assert shared and len(shared) == len(set(shared)), f"shared trackers must be listed once: {shared}"
    for b in BRANDS:
        mine = [s["source"] for s in health(client, b)["sources"] if s["scope"] == "shared"]
        assert sorted(mine) == sorted(shared), f"{b} shared trackers differ from the portfolio list"
    pf = [f["file_name"] for f in port["failed_files"]]
    assert len(pf) == len(set(pf)), "portfolio failed_files must not duplicate files"


# ------------------------------------------------------------------ (1) seeded synthetic data
@pytest.mark.synth
@pytest.mark.parametrize("brand,want", [("verdant", 0), ("threadline", 1), ("aurelle", 0), ("crunchwell", 0),
                                         ("glowhaus", 0)])
def test_w3_synthetic_brand_failure_counts(client, brand, want):
    h = health(client, brand)
    assert h["counts"]["brand_failed"] == want, h["failed_files"]
    assert len(brand_files(h["failed_files"], brand)) == want


@pytest.mark.synth
def test_w3_synthetic_failure_kinds(client):
    t = brand_files(health(client, "threadline")["failed_files"], "threadline")[0]
    text = f"{t['file_name']} {t.get('plain_reason') or t.get('error')}".lower()
    assert "video" in text and ("quarantine" in text or "overlap" in text or "already" in text)   # weekly videos set aside


@pytest.mark.synth
@pytest.mark.parametrize("brand,want", sorted(W3["synthetic_rows_excluded"].items()))
def test_w3_synthetic_rows_excluded_are_not_failures(client, brand, want):
    """Amendment 4: verdant's extra orders file loads with 1 of 4 rows left out; it is listed as loaded with exclusions."""
    h = health(client, brand)
    assert h["counts"]["rows_excluded"] == want, h["counts"]
    ex = h["files_with_exclusions"]
    assert (len(ex) == 1) == (want > 0), ex
    if want:
        assert_left_out_note(ex[0]["plain_reason"], 1, "verdant", brand_name=ex[0]["brand_name"])
        assert ex[0]["brand_name"].lower().startswith("verdant")
        assert not [f for f in h["failed_files"] if "order" in f["file_name"].lower()], "left-out rows must not fail the file"


# ------------------------------------------------------------------ (1) golden fixture
@pytest.mark.golden_bad
@pytest.mark.after_b3
def test_w3_golden_bad_batch_leaves_rows_out_without_failing_a_file(client):
    """After golden batch_bad (amendment 4, hand-derived in expected.yaml): verdant's extra file loads with 2 of 5 rows
    left out, so no brand has a failed file and only verdant has excluded rows."""
    for brand, want in W3["golden_failed_after_bad"].items():
        h = health(client, brand)
        assert h["counts"]["brand_failed"] == want, (brand, h["failed_files"])
    for brand, want in W3["golden_rows_excluded_after_bad"].items():
        h = health(client, brand)
        assert h["counts"]["rows_excluded"] == want, (brand, h["counts"])
        assert len(h["files_with_exclusions"]) == (1 if want else 0)
    f = health(client, "verdant")["files_with_exclusions"][0]
    assert_left_out_note(f["plain_reason"], EXPECTED["ingest"]["rows_excluded"]["bad"], "verdant", brand_name=f["brand_name"])
    assert f["brand_name"].lower().startswith("verdant")
    assert not health(client, "aurelle")["files_with_exclusions"], "verdant exclusions leaked into aurelle health"


@pytest.mark.after_b3
def test_w3_shared_tracker_issue_is_scoped_to_its_brand(client):
    """GS4 (samples tracker, shared file) names creator cr_9999 for threadline only: hand-derived in expected.yaml."""
    e = W3["shared_row_issue"]
    seen = {}
    for b in BRANDS:
        ids = [u["raw_identifier"] for u in health(client, b)["unresolved_identities"]]
        seen[b] = any(e["raw_identifier"] in i for i in ids)
    assert seen[e["brand_id"]], f"{e['raw_identifier']} missing for {e['brand_id']}"
    assert not any(v for b, v in seen.items() if b != e["brand_id"]), f"issue leaked to other brands: {seen}"
    port = [u for u in health(client)["unresolved_identities"] if e["raw_identifier"] in u["raw_identifier"]]
    assert len(port) == 1 and port[0]["brand_id"] == e["brand_id"], "portfolio view lists the issue once, brand-tagged"


# ------------------------------------------------------------------ (2) chart availability
def available(client, brand, **kw):
    return get_json(client, f"{API}/brands/{brand}/charts/available", month="2026-10", cutoff="2026-10-15", **kw)


@pytest.mark.parametrize("brand", BRANDS)
def test_w3_availability_equals_each_chart_response(client, brand):
    body = available(client, brand)
    assert "data_revision" in body and body["series"]
    ids = {s["series_id"] for s in body["series"]}
    assert ids <= set(SERIES) and ids, ids
    for s in body["series"]:
        assert {"series_id", "status", "reason", "as_of", "point_count"} <= set(s)
        assert s["status"] in AVAIL, s
        kw = {"metric": "gmv"} if s["series_id"] == "pacing_trajectory" else {}
        chart = get_json(client, f"{API}/brands/{brand}/charts", series=s["series_id"], month="2026-10",
                         cutoff="2026-10-15", **kw)
        assert chart["availability"]["status"] == s["status"], (brand, s["series_id"], chart["availability"], s)
        assert chart["availability"]["reason"] == s["reason"]
        if s["status"] == "empty":
            assert chart["points"] == [] and s["point_count"] == 0
        if s["status"] == "available":
            assert s["point_count"] > 0 and chart["points"], f"{brand}/{s['series_id']} marked available but has no points"


@pytest.mark.parametrize("brand", BRANDS)
def test_w3_available_series_are_not_empty_zero_or_all_null(client, brand):
    for s in available(client, brand)["series"]:
        if s["status"] not in ("available", "stale"):
            continue
        kw = {"metric": "gmv"} if s["series_id"] == "pacing_trajectory" else {}
        chart = get_json(client, f"{API}/brands/{brand}/charts", series=s["series_id"], month="2026-10",
                         cutoff="2026-10-15", **kw)
        skip = {"x", "status", "status_reason", "evidence_urls", "group", "brand_id", "creator_id", "handle"}
        vals = [v for p in chart["points"] for k, v in p.items() if k not in skip]
        assert any(v is not None for v in vals), f"{brand}/{s['series_id']}: available but every value is null"
        nums = []
        for v in vals:
            try:
                nums.append(dec(v))
            except Exception:
                pass
        assert any(n != 0 for n in nums) or not nums, f"{brand}/{s['series_id']}: available but every value is 0"


@pytest.mark.parametrize("brand", BRANDS)
@pytest.mark.parametrize("series", SERIES)
def test_w3_no_literal_zero_where_coverage_is_missing(client, brand, series):
    kw = {"metric": "videos"} if series == "pacing_trajectory" else {}
    chart = get_json(client, f"{API}/brands/{brand}/charts", series=series, month="2026-10", cutoff="2026-10-15", **kw)
    skip = {"x", "status", "status_reason", "evidence_urls", "group", "brand_id", "creator_id", "handle", "count"}
    for p in chart["points"]:
        if p["status"] in ("stale", "unavailable", "partial"):
            for k, v in p.items():
                if k in skip:
                    continue
                assert not (v == 0 or str(v) in ("0", "0.0", "0.00")), \
                    f"{brand}/{series} {p['x']}.{k} = {v!r} under status {p['status']} (must be null)"


def _find_key(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _find_key(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find_key(v, key)


@pytest.mark.parametrize("brand", BRANDS)
def test_w3_new_creators_is_null_or_a_count(client, brand):
    for series in SERIES:
        kw = {"metric": "active_creators"} if series == "pacing_trajectory" else {}
        chart = get_json(client, f"{API}/brands/{brand}/charts", series=series, month="2026-10", cutoff="2026-10-15", **kw)
        for v in _find_key(chart, "new_creators"):
            assert v is None or (isinstance(v, int) and not isinstance(v, bool) and v >= 0), (series, v)


def test_w3_aurelle_daily_gmv_is_available(client):
    """Derived: aurelle has non-zero shop GMV on its order days (golden O_A1 100.00; synthetic ~3 orders/day)."""
    s = {x["series_id"]: x for x in available(client, "aurelle")["series"]}
    assert s["daily_gmv_refunds"]["status"] in ("available", "stale"), s["daily_gmv_refunds"]
    assert s["pacing_trajectory"]["status"] != "not_applicable"


@pytest.mark.synth
def test_w3_synthetic_cadence_verdant_available_glowhaus_stale_or_unknown(client):
    """Derived: verdant has retainer creators and gap-free weekly video coverage for Jul-Sep -> cadence available.
    glowhaus weekly files W36 (Aug 31) and W37 (Sep 7) are missing -> Aug/Sep posts null and its video source is stale."""
    v = {x["series_id"]: x for x in available(client, "verdant")["series"]}
    g = {x["series_id"]: x for x in available(client, "glowhaus")["series"]}
    assert v["retainer_cadence"]["status"] == "available", v["retainer_cadence"]
    assert g["retainer_cadence"]["status"] in ("stale", "unknown", "not_applicable"), g["retainer_cadence"]
    assert g["retainer_cadence"]["status"] != "available"


def test_w3_not_applicable_series_is_not_offered_as_available(client):
    """Golden/any data: glowhaus has 1 creator (< 3) -> a series classified not_applicable/empty is never 'available'."""
    for brand in BRANDS:
        for s in available(client, brand)["series"]:
            if s["status"] in ("empty", "not_applicable"):
                chart = get_json(client, f"{API}/brands/{brand}/charts", series=s["series_id"], month="2026-10",
                                 cutoff="2026-10-15", **({"metric": "gmv"} if s["series_id"] == "pacing_trajectory" else {}))
                assert chart["availability"]["status"] == s["status"] != "available"


# ------------------------------------------------------------------ (3) evidence explainer
EXPLAINER = ("what_it_means", "why_it_matters", "how_calculated", "what_rows_prove")
UI_METRICS = ["gmv", "creator_attributed_gmv", "net_attributed_sales", "videos", "active_creators", "goal_projection",
              "creator_videos", "creator_net_sales", "sample_conversion_rate", "creator_sales_after_costs"]


def _params(client, key):
    base = {"brand_id": "aurelle", "month": "2026-10", "cutoff": "2026-10-15"}
    if key.startswith("creator_"):
        items = get_json(client, f"{API}/brands/aurelle/creators", month="2026-10", cutoff="2026-10-15")["items"]
        return {**base, "creator_id": items[0]["creator_id"]}
    if key == "sample_conversion_rate":
        return {"brand_id": "threadline"}
    if key == "goal_projection":
        ov = get_json(client, f"{API}/overview", month="2026-10", cutoff="2026-10-15")
        goal = next(b for b in ov["brands"] if b["brand_id"] == "aurelle")["goals"][0]
        return {**base, "goal_id": goal["goal_id"]}
    return base


@pytest.mark.parametrize("key", UI_METRICS)
def test_w3_evidence_explainer_present_and_non_empty(client, key):
    ev = get_json(client, f"{API}/metrics/{key}/evidence", **_params(client, key))
    ex = ev.get("explainer")
    assert isinstance(ex, dict) and set(EXPLAINER) <= set(ex), f"{key}: explainer missing {ex!r}"
    for f in EXPLAINER:
        assert isinstance(ex[f], str) and len(ex[f].strip()) >= 15, f"{key}.{f} is empty or trivial: {ex[f]!r}"


# ------------------------------------------------------------------ (4) demo auth
def test_w3_demo_token_opens_auth_me_and_wrong_password_is_401(anon):
    r = anon.post(f"{API}/auth/token", data={"username": "demo", "password": "darkroom-demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"].lower() == "bearer" and body["access_token"].count(".") == 2
    me = httpx.get(f"{BASE_URL}{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == "demo"
    bad = anon.post(f"{API}/auth/token", data={"username": "demo", "password": "not-the-password"})
    assert bad.status_code == 401 and "access_token" not in bad.text


@pytest.mark.synth
@pytest.mark.parametrize("brand", BRANDS)
def test_w3_synthetic_open_issues_match_brand_scoped_quality_rows(client, brand):
    """quality_issue rows after batch_1 + batch_2 (creator_not_on_roster + file_rejected / file_quarantined)."""
    h = health(client, brand)
    assert h["counts"]["open_issues"] == W3["synthetic_open_issues"][brand], h["counts"]
    assert not [s for s in h["sources"] if s["scope"] == "shared" and "plan" in s["source"].lower()], "plans are brand files"
