"""S7 stale feed -> unknown (never 0); S8 verified zero; S10 sample states; attention items."""
import pytest

from helpers import API, EXPECTED, dec, get_json, metric_result, param_cases, marks_for


@pytest.mark.parametrize("case", param_cases(EXPECTED["unknown_metrics"]))
def test_s7_missing_weeks_give_null_and_stale(client, case):
    mv = metric_result(client, case["metric"], case["params"])
    assert mv["value"] is None, f"gap in video feed must be unknown (null), got {mv['value']!r}"
    assert mv["status"] in case["statuses"]
    assert mv["status_reason"], "a null value must say why"


def test_s7_orders_still_normal_while_videos_stale(client):
    mv = metric_result(client, "gmv", {"brand_id": "glowhaus", "month": "2026-10", "cutoff": "2026-10-15"})
    assert dec(mv["value"]) == dec("40.00")


def test_s7_creators_table_never_shows_zero_for_unknown(client):
    body = get_json(client, f"{API}/brands/glowhaus/creators", month="2026-10", cutoff="2026-10-15")
    for row in body["items"]:
        mv = row["videos"]
        assert mv["value"] is None or mv["status"] == "current", f"{row['creator_id']}: value under {mv['status']}"


def test_s8_verified_zero_requires_full_coverage(client):
    body = get_json(client, f"{API}/brands/aurelle/creators", month="2026-10", cutoff="2026-10-15")
    row = next(r for r in body["items"] if r["creator_id"] == "cr_0002")
    assert dec(row["videos"]["value"]) == 0 and row["videos"]["status"] == "current"
    assert row["last_post_date"] == "2026-09-20"  # V_A0, outside October


def _find(items, ship):
    """Locate a golden shipment in the API items without assuming how sample_id is formed."""
    by_date = {"GS1": "2026-08-15", "GS2": "2026-08-20", "GS3": "2026-10-06", "GS4": "2026-08-20",
               "GS5": "2026-10-12"}
    cands = [i for i in items if i["sent_date"] == by_date[ship]]
    if ship == "GS2":
        cands = [i for i in cands if i["creator_id"] == "cr_0003"]
    if ship == "GS4":
        cands = [i for i in cands if i["creator_id"] != "cr_0003"]
    assert len(cands) == 1, f"{ship}: expected exactly one API item, found {len(cands)}"
    return cands[0]


def test_s10_threadline_sample_states(client):
    s = EXPECTED["samples"]
    body = get_json(client, f"{API}/brands/{s['brand_id']}/samples")
    for k, want in s["counts"].items():
        assert dec(body["counts"][k]["value"]) == want, f"counts.{k}"
    rate = body["counts"]["conversion_rate"]["value"]
    assert rate is not None and abs(dec(rate) - dec(s["conversion_rate"])) < dec("0.0005"), "rate = 1 matched / 3 mature items"
    for ship, want in s["statuses"].items():
        assert _find(body["items"], ship)["status"] == want, ship
    gs1 = _find(body["items"], "GS1")
    assert str(gs1["video_id"]).endswith("V_T1")
    assert gs1["delivery_to_video_days"] == s["delivery_to_video_days"]["GS1"]
    assert gs1["evidence_url"]


def test_s10_conversion_rate_evidence_matches(client):
    ev = get_json(client, f"{API}/metrics/sample_conversion_rate/evidence", brand_id="threadline")
    assert abs(dec(ev["result"]["value"]) - dec("0.3333")) < dec("0.0005")
    assert ev["calculation"]["kind"] == "ratio"


@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c['brand_id']}-{c['kind']}", marks=marks_for(c.get("stage", "any"))) for c in EXPECTED["attention"]])
def test_attention_items(client, case):
    body = get_json(client, f"{API}/attention", brand_id=case["brand_id"], kind=case["kind"])
    assert body["items"], f"no {case['kind']} item for {case['brand_id']}"
    for it in body["items"]:
        assert it["kind"] == case["kind"] and it["brand_id"] == case["brand_id"] and it["evidence_url"]
    if "contains" in case:
        assert any(case["contains"] in (it["title"] + it["rule"]) for it in body["items"])
