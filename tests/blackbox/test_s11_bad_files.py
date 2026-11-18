"""S11: header alias + BOM ingest fine; a file missing a required field is rejected, exit != 0, totals unchanged."""
import pytest

from helpers import API, EXPECTED, dec, get_json, metric_result

pytestmark = [pytest.mark.mutating, pytest.mark.after_b2]


def failed(client, brand=None):
    """Brand-scoped failed files (amendment 3); without a brand: the portfolio view of all files."""
    return get_json(client, f"{API}/data-health", brand_id=brand)["failed_files"]


def _is(f, *words):
    name = f["file_name"].lower()
    return all(w in name for w in words)


def test_s11_alias_header_and_bom_files_were_accepted(client):
    assert not [f for f in failed(client, "aurelle") if _is(f, "video")], "renamed-header weekly file was rejected"
    assert not [f for f in failed(client, "crunchwell") if _is(f, "product")], "UTF-8 BOM CSV was rejected"
    src = get_json(client, f"{API}/data-health", brand_id="aurelle")["sources"]
    vid = [s for s in src if "video" in s["source"]]
    assert vid and vid[0]["coverage_through"] >= "2026-10-18", "W42 (aliased header) coverage not recorded"


def test_s11_bad_file_rejected_totals_unchanged(client, ingest):
    params = {"brand_id": "verdant", "month": "2026-10", "cutoff": "2026-10-15"}
    before = dec(metric_result(client, "gmv", params)["value"])
    assert before == dec(EXPECTED["ingest"]["verdant_gmv_after_bad_batch"])
    r = ingest("batch_bad")
    assert r.returncode != 0, "a batch with a rejected file must exit non-zero"
    assert "Traceback" not in r.stderr, "rejection must be reported, not crash"
    bad = [f for f in failed(client, "verdant") if _is(f, "order")]   # file_name is a label, not a path
    assert all(f["scope"] == "brand" and f["brand_id"] == "verdant" for f in bad)
    assert not [f for f in failed(client, "aurelle") if _is(f, "order")], "verdant failure leaked into aurelle health"
    assert bad, "no failed_files entry for the verdant orders file"
    assert any("order_id" in (f["error"] or "") for f in bad), f"error must name the missing field: {bad}"
    after = dec(metric_result(client, "gmv", params)["value"])
    assert after == before, "rejected file changed totals ($999.00 order leaked in)"
    assert dec(metric_result(client, "gmv", {**params, "cutoff": "2026-11-02"})["value"]) == before


def test_s11_good_file_in_same_batch_is_accepted(client):
    """batch_bad also carries a valid returns file for crunchwell; it must not be rejected with its neighbour."""
    assert not [f for f in failed(client, "crunchwell") if _is(f, "return")]
