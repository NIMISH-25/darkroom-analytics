"""S11b: a file whose rows are ALL invalid is rejected (exit 1), its brand turns incomplete, the goal
projection is null and the note names the brand in plain English. Runs LAST (marker late) because it leaves crunchwell
incomplete. Expected values: tests/golden/expected.yaml (ingest.batch_allbad, v2.essential.e12.unavailable)."""
import pytest

from helpers import API, EXPECTED, V2, find_goal, get_json, violations

pytestmark = [pytest.mark.late, pytest.mark.v2, pytest.mark.a4, pytest.mark.after_b3, pytest.mark.mutating]
A = EXPECTED["ingest"]["batch_allbad"]


def test_s11b_all_bad_rows_file_is_rejected(client, ingest):
    r = ingest("batch_allbad")
    assert r.returncode == 1, "a file with no usable rows must exit 1: " + r.stdout[-300:] + r.stderr[-300:]
    assert "Traceback" not in r.stderr
    h = get_json(client, f"{API}/data-health", brand_id=A["brand_id"])
    failed = [f for f in h["failed_files"] if f["scope"] == "brand" and "order" in f["file_name"].lower()]
    assert failed, f"rejected file must be listed as failed: {h['failed_files']}"
    assert h["counts"]["brand_failed"] >= 1
    reason = failed[0].get("plain_reason") or ""
    assert "crunchwell" in reason.lower() or failed[0].get("brand_name", "").lower().startswith("crunchwell"), reason
    assert violations(reason, ["Crunchwell"]) == [], f"developer language in the rejection message: {reason!r}"
    others = get_json(client, f"{API}/data-health", brand_id="glowhaus")
    assert not [f for f in others["failed_files"] if "order" in f["file_name"].lower() and f["scope"] == "brand"]


def test_s11b_brand_is_incomplete_and_projection_is_null_with_a_plain_note(client):
    case = V2["essential"]["e12"]["unavailable"][0]
    ov = get_json(client, f"{API}/overview", month="2026-10", cutoff="2026-10-15")
    g = find_goal(ov, case["brand_id"], case["word"])
    p = g["projection"]
    assert p["value"] is None and p["status"] != "current", p
    reason = ((p["status_reason"] or "") + " " + (p.get("data_note") or "")).lower()
    assert any(w in reason for w in case["reason_any"]), f"the reason must name the brand in words: {p}"
    assert violations(p["status_reason"] or "", ["Crunchwell"]) == []
    health = get_json(client, f"{API}/data-health", brand_id=case["brand_id"])
    assert any(s["status"] != "current" for s in health["sources"] if s["scope"] == "brand"), "brand must be incomplete"
