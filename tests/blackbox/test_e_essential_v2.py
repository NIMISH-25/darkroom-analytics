"""Essential tests #3 #4 #5 #6 #10 #12 (amendment 2). Golden batch_3 data; expected values in
tests/golden/expected.yaml (v2.essential), hand-derived with arithmetic. HTTP only."""
import pytest

from helpers import (API, V2, assert_mv, chart, creator_row, dec, evidence, find_goal, get_json, metric_result,
                     money_ok, points_by_x)

pytestmark = pytest.mark.after_b3
E = V2["essential"]


# ------------------------------------------------------------------ #3 partial refund + cancellation
def test_e03_partial_refunds_and_cancelled_line_no_double_deduction(client):
    e = E["e03"]
    base = {"month": e["month"]}
    row = creator_row(client, e["brand_id"], e["cutoff_1015"]["creator_id"], cutoff="2026-10-15", **base)
    for k in ("gmv", "refunds", "net_sales", "commission_cost"):
        assert dec(row[k]["value"]) == dec(e["cutoff_1015"][k]), f"{k}: {row[k]['value']} != {e['cutoff_1015'][k]}"
    early = creator_row(client, e["brand_id"], "cr_0001", cutoff="2026-09-22", **base)
    for k in ("gmv", "refunds", "net_sales"):
        assert dec(early[k]["value"]) == dec(e["cutoff_0922"][k]), f"cutoff 09-22 {k}"


def test_e03_shop_gmv_excludes_cancelled_line_and_evidence_agrees(client):
    e = E["e03"]
    p = {"brand_id": e["brand_id"], "month": e["month"], "cutoff": "2026-10-15"}
    ev = evidence(client, "gmv", p)
    assert dec(ev["result"]["value"]) == dec(e["shop_gmv"])
    included = [r for r in ev["records"] if r.get("included", True)]
    assert not any(e["cancelled_line_id"] in str(r["values"]) for r in included), "cancelled line was counted"
    net = evidence(client, "creator_net_sales", {**p, "creator_id": "cr_0001"})
    assert dec(net["result"]["value"]) == dec("35.00")
    assert not any("R_A3c" in str(r["values"]) for r in net["records"] if r.get("included", True)), \
        "refund on a cancelled line must not be deducted"


# ------------------------------------------------------------------ #4 brand isolation + allocation
def test_e04_creator_lists_are_brand_scoped(client):
    for brand, ids in E["e04"]["roster"].items():
        got = {r["creator_id"] for r in get_json(client, f"{API}/brands/{brand}/creators",
                                                   month="2026-10")["items"]}
        assert set(ids) <= got, f"{brand}: roster creators missing {set(ids) - got}"
        others = {c for b, cs in E["e04"]["roster"].items() if b != brand for c in cs} - set(ids)
        assert not (got & others), f"{brand} leaks creators of other brands: {got & others}"


def test_e04_dual_brand_creator_sales_do_not_leak_across_brands(client):
    for brand, want in E["e04"]["oct_cr0001"].items():
        row = creator_row(client, brand, "cr_0001", month="2026-10", cutoff="2026-10-15")
        assert dec(row["gmv"]["value"]) == dec(want), f"{brand}: cr_0001 gmv {row['gmv']['value']} != {want}"
    ev = evidence(client, "gmv", {"brand_id": "aurelle", "month": "2026-10", "cutoff": "2026-10-15"})
    assert not any("O_B1" in str(r["values"]) for r in ev["records"]), "verdant order in aurelle evidence"


@pytest.mark.parametrize("case", E["e04"]["allocation"], ids=lambda c: f"{c['brand_id']}-{c['creator_id']}")
def test_e04_cross_brand_retainer_allocation(client, case):
    row = creator_row(client, case["brand_id"], case["creator_id"], month=E["e04"]["month"], cutoff="2026-10-15")
    rc = row["retainer_cost"]
    if case["retainer_cost"] is None:
        assert rc["value"] is None and rc["status_reason"], "missing share must be unknown, never the full fee or 0"
        assert row["sales_after_costs"]["value"] is None
    else:
        assert dec(rc["value"]) == dec(case["retainer_cost"])


def test_e04_allocations_sum_to_contract_total(client):
    total = sum(dec(creator_row(client, b, "cr_0010", month="2026-09", cutoff="2026-10-15")["retainer_cost"]["value"])
                for b in ("aurelle", "verdant"))
    assert total == dec("3000.00")


# ------------------------------------------------------------------ #5 identity ambiguity
def test_e05_lookalike_handle_is_not_merged_and_stable_id_works(client):
    e = E["e05"]
    row = creator_row(client, e["brand_id"], "cr_0001", month=e["month"], cutoff="2026-10-15")
    assert dec(row["gmv"]["value"]) == dec(e["cr0001_gmv"]), "stable id with new handle must still count (60.00)"
    assert dec(row["gmv"]["value"]) != dec(e["not_merged_gmv"]), "look-alike @golden.m1a was merged into cr_0001"
    items = get_json(client, f"{API}/brands/{e['brand_id']}/creators", month=e["month"])["items"]
    assert not any("m1a" in r["handle"] for r in items), "look-alike handle became a creator row"


def test_e05_unresolved_identity_is_reported(client):
    e = E["e05"]
    body = get_json(client, f"{API}/data-health", brand_id=e["brand_id"])
    raw = " ".join(u["raw_identifier"].lower() for u in body["unresolved_identities"])
    assert any(w.lower() in raw for w in e["unresolved_raw_contains"]), f"unresolved identities: {raw!r}"


# ------------------------------------------------------------------ #6 video snapshots
def test_e06_video_in_two_weekly_files_counts_once(client):
    e = E["e06"]
    p = {"brand_id": e["brand_id"], "month": "2026-09", "cutoff": "2026-10-15"}
    assert dec(metric_result(client, "videos", p)["value"]) == dec(e["sep"]["videos"])
    assert dec(metric_result(client, "active_creators", p)["value"]) == dec(e["sep"]["active_creators"])
    o = {**p, "month": "2026-10"}
    assert dec(metric_result(client, "videos", o)["value"]) == dec(e["oct"]["videos"])
    assert dec(metric_result(client, "active_creators", o)["value"]) == dec(e["oct"]["active_creators"])


def test_e06_views_are_summed_per_week_never_cumulative(client):
    e = E["e06"]
    ev = evidence(client, "creator_videos", {"brand_id": e["brand_id"], "creator_id": "cr_0005", "month": "2026-09",
                                              "cutoff": "2026-10-15"})
    assert dec(ev["result"]["value"]) == dec(e["sep"]["cr_0005_videos"])
    if "views" not in [c.lower() for c in ev["columns"]]:
        pytest.skip("evidence does not expose a views column")
    per_video = {}
    for r in ev["records"]:
        v = {k.lower(): x for k, x in r["values"].items()}
        if r.get("included", True) and v.get("views") is not None:
            per_video[v.get("video_id")] = per_video.get(v.get("video_id"), 0) + int(v["views"])
    assert sum(per_video.values()) == e["sep"]["cr_0005_views"]
    assert per_video.get("V_C2") == e["sep"]["v_c2_views"], "V_C2 = 200 + 50 per-week rows"


# ------------------------------------------------------------------ #10 money, currency, discount, allocation
def test_e10_discounted_cents_sum_exactly(client):
    e = E["e10"]
    mv = metric_result(client, "gmv", {"brand_id": "threadline", "month": "2026-09", "cutoff": "2026-10-15"})
    assert isinstance(mv["value"], str), "money must be a string"
    assert dec(mv["value"]) == dec(e["threadline_sept_gmv"]), "10.00 + 9.99 + 0.10 + 0.20 must be exactly 20.29"
    assert money_ok(mv["value"])


def test_e10_non_usd_order_is_not_added_to_usd_gmv(client):
    e = E["e10"]
    ev = evidence(client, "gmv", {"brand_id": "threadline", "month": "2026-09", "cutoff": "2026-10-15"})
    assert not any("O_T2" in str(r["values"]) for r in ev["records"] if r.get("included", True)), \
        "EUR order counted as USD (would make 120.29)"
    assert dec(ev["result"]["value"]) != dec(e["threadline_sept_gmv"]) + dec(e["eur_order_amount"])
    ex = [x for x in ev["exclusions"] if x["reason"] == e["exclusion"]["reason"]]
    assert ex, f"exclusions must list non_usd_currency: {ev['exclusions']}"
    assert ex[0]["count"] == e["exclusion"]["count"] and dec(ex[0]["amount"]) == dec(e["exclusion"]["amount"])


def test_e10_mid_month_retainer_is_prorated_by_effective_days(client):
    row = creator_row(client, "threadline", "cr_0012", month="2026-09", cutoff="2026-10-15")
    assert dec(row["retainer_cost"]["value"]) == dec(E["e10"]["cr_0012_retainer_cost"])   # 15/30 * 900.00


def test_e10_all_money_values_are_strings_with_cent_precision(client):
    for brand in ("aurelle", "crunchwell", "threadline"):
        for month in ("2026-09", "2026-10"):
            for row in get_json(client, f"{API}/brands/{brand}/creators", month=month)["items"]:
                for k in ("gmv", "refunds", "net_sales", "retainer_cost", "commission_cost", "sample_cost",
                          "sales_after_costs"):
                    mv = row[k]
                    assert_mv(mv, f"{brand}.{row['creator_id']}.{k}")
                    if mv["value"] is not None:
                        assert isinstance(mv["value"], str) and money_ok(mv["value"]), (brand, k, mv["value"])


# ------------------------------------------------------------------ #12 projection edge cases
def test_e12_month_end_projection_equals_actual(client):
    e = E["e12"]["aurelle_gmv_month_end"]
    ov = get_json(client, f"{API}/overview", month="2026-10", cutoff=e["cutoff"])
    g = find_goal(ov, "aurelle", "gmv")
    assert dec(g["actual"]["value"]) == dec(e["actual"])
    assert g["projection"]["value"] is not None, f"month end projection unavailable: {g['projection']['status_reason']}"
    assert dec(g["projection"]["value"]) == dec(e["projection"])


def test_e12_zero_elapsed_days_does_not_error_or_invent_a_number(client):
    ov = get_json(client, f"{API}/overview", month="2026-10", cutoff="2026-10-01")
    for br in ov["brands"]:
        for g in br["goals"]:
            p = g["projection"]
            if p["value"] is None:
                assert p["status_reason"], f"{br['brand_id']}.{g['goal_id']}: null projection needs a reason"
                assert g["pace_status"] in ("unknown", "on_track", "at_risk", "off_track")
            else:
                assert dec(p["value"]) >= 0


def test_e12_projection_never_below_actual_and_distinct_counts_never_below_current(client):
    ov = get_json(client, f"{API}/overview")
    for br in ov["brands"]:
        for g in br["goals"]:
            a, p = g["actual"]["value"], g["projection"]["value"]
            if a is not None and p is not None:
                assert dec(p) >= dec(a), f"{br['brand_id']}.{g['goal_id']}: projection {p} < actual {a}"
    ac = find_goal(ov, "aurelle", "active")
    assert dec(ac["actual"]["value"]) == dec(E["e12"]["active_creators_actual"])
    assert ac["projection"]["value"] is None or dec(ac["projection"]["value"]) >= dec(ac["actual"]["value"])


def test_e12_incomplete_coverage_gives_null_projection(client):
    ov = get_json(client, f"{API}/overview")
    g = find_goal(ov, "glowhaus", "video")
    assert g["projection"]["value"] is None and g["projection"]["status"] != "current"
    assert g["projection"]["status_reason"]


@pytest.mark.parametrize("case", E["e12"]["mid_month"], ids=lambda c: f"{c['brand_id']}-{c['word']}")
def test_e12_mid_month_projection_uses_elapsed_complete_days(client, case):
    ov = get_json(client, f"{API}/overview", month="2026-10", cutoff="2026-10-15")
    g = find_goal(ov, case["brand_id"], case["word"])
    assert dec(g["actual"]["value"]) == dec(case["actual"])
    assert g["projection"]["value"] is not None, g["projection"]["status_reason"]
    assert abs(dec(g["projection"]["value"]) - dec(case["projection"])) < dec("0.01"), \
        f"actual / 15 * 31 expected {case['projection']}, got {g['projection']['value']}"


def test_e05_creator_unresolved_lines_carry_the_raw_creator_id(client):
    e = E["e05"]
    ev = evidence(client, "gmv", {"brand_id": e["brand_id"], "month": e["month"], "cutoff": "2026-10-15",
                                  "bucket": "creator_unresolved"})
    included = [r for r in ev["records"] if r.get("included", True)]
    assert included, "creator_unresolved bucket must list its lines"
    assert any("u_9001" in str(r["values"]) for r in included), "raw creator id must be visible on the line"
    assert dec(ev["result"]["value"]) == dec(e["unresolved_gmv"])


@pytest.mark.golden_bad     # only valid once golden batch_bad (verdant rejected orders file) is loaded
@pytest.mark.parametrize("case", E["e12"]["unavailable"], ids=lambda c: f"{c['brand_id']}-{c['word']}")
def test_e12_rejected_file_makes_projection_unavailable(client, case):
    """Rejected file => incomplete coverage => projection null with a reason (expected.yaml: e12.unavailable)."""
    ov = get_json(client, f"{API}/overview", month="2026-10", cutoff="2026-10-15")
    p = find_goal(ov, case["brand_id"], case["word"])["projection"]
    assert p["value"] is None, f"projection must be unavailable, got {p['value']}"
    assert p["status"] != "current"
    reason = (p["status_reason"] or "").lower()
    assert any(w in reason for w in case["reason_any"]), f"reason does not explain the gap: {p['status_reason']!r}"
