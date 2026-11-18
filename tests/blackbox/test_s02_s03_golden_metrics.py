"""S2 (batch_1 incl. duplicate order), S3 (late refund), S5/S6/S8 values driven by tests/golden/expected.yaml.
Every expected number is hand-written there with its arithmetic."""
import pytest

from helpers import API, EXPECTED, dec, evidence, get_json, metric_result, param_cases


@pytest.mark.parametrize("case", param_cases(EXPECTED["metrics"]))
def test_golden_metric_value(client, case):
    mv = metric_result(client, case["metric"], case["params"])
    assert mv["value"] is not None, (
        f"{case['id']}: expected {case['value']}, got null ({mv['status']}: {mv['status_reason']})")
    assert dec(mv["value"]) == dec(case["value"]), f"{case['id']}: {mv['value']} != {case['value']}"
    if "status" in case:
        assert mv["status"] == case["status"]


@pytest.mark.parametrize("case", param_cases(EXPECTED["creator_rows"]))
def test_golden_creator_row(client, case):
    body = get_json(client, f"{API}/brands/{case['brand_id']}/creators", **case["params"])
    rows = [r for r in body["items"] if r["creator_id"] == case["creator_id"]]
    assert len(rows) == 1, f"{case['creator_id']} must appear exactly once in {case['brand_id']}"
    row = rows[0]
    for key, want in case["expect"].items():
        got = row[key]["value"]
        assert got is not None, f"{case['id']}.{key} is null"
        assert dec(got) == dec(want), f"{case['id']}.{key}: {got} != {want}"


def test_video_views_are_per_week_not_cumulative(client):
    """V_A1 sits in two weekly files (views 100 and 40): one video; views, if exposed, total 140 (not 240)."""
    ev = evidence(client, "creator_videos", {"brand_id": "aurelle", "creator_id": "cr_0001", "month": "2026-10",
                                              "cutoff": "2026-10-15"})
    assert dec(ev["result"]["value"]) == 1
    cols = [c.lower() for c in ev["columns"]]
    views = 0
    for rec in ev["records"]:
        vals = {k.lower(): v for k, v in rec["values"].items()}
        assert "total" not in str(vals.get("video_id", "")).lower(), "Total row must not become a record"
        if rec.get("included", True) and vals.get("views") is not None:
            views += int(vals["views"])
    if "views" in cols:
        assert views == 140, f"views over both weekly rows must be 100 + 40 = 140, got {views}"


def test_duplicate_order_page_is_not_double_counted_in_evidence(client):
    ev = evidence(client, "creator_attributed_gmv", {"brand_id": "aurelle", "month": "2026-10", "cutoff": "2026-10-15"})
    included = [r for r in ev["records"] if r.get("included", True)]
    assert len(included) == 1, f"exactly one included record expected (page-2 copy excluded), got {len(included)}"
    for r in included:
        assert r["source_file"] and r["source_locator"] is not None
