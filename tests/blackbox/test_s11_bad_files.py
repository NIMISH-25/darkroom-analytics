"""S11: header alias + BOM ingest fine; faulty rows are left out alone (exit 0, file loads). S11b (all rows bad -> rejected) lives in test_zz_allbad.py."""
import re

import pytest

from helpers import API, EXPECTED, assert_left_out_note, dec, get_json, metric_result

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


def test_s11_faulty_rows_are_left_out_file_still_loads(client, ingest):
    """Amendment 4: 2 of 5 orders in verdant's extra file have no order number; they are left out alone.
    exit 0, no failed file, brand current, a plain note naming Verdant, totals are floors (leaked $1,499.00 would show)."""
    e = EXPECTED["ingest"]
    params = {"brand_id": "verdant", "month": "2026-10", "cutoff": "2026-10-15"}
    assert dec(metric_result(client, "gmv", params)["value"]) == dec(e["verdant_gmv_after_bad_batch"])
    r = ingest("batch_bad")
    assert r.returncode == 0, "only rows were left out: exit code must be 0: " + r.stdout[-300:] + r.stderr[-300:]
    assert "Traceback" not in r.stderr
    assert not [f for f in failed(client, "verdant") if _is(f, "order")], "file must load, not fail"
    h = get_json(client, f"{API}/data-health", brand_id="verdant")
    assert h["counts"]["rows_excluded"] == e["rows_excluded"]["bad"]
    ex = h["files_with_exclusions"]
    assert len(ex) == 1 and ex[0]["brand_name"].lower().startswith("verdant"), ex
    assert_left_out_note(ex[0]["plain_reason"], e["rows_excluded"]["bad"], "verdant", brand_name=ex[0]["brand_name"])
    assert dec(metric_result(client, "gmv", params)["value"]) == dec("50.00"), "left-out $999.00 / $500.00 rows leaked in"
    assert dec(metric_result(client, "gmv", {**params, "cutoff": "2026-11-02"})["value"]) ==         dec(e["verdant_gmv_after_bad_batch_1102"]), "50.00 + the three good rows 10.00 + 20.00 + 5.00"
    assert not [f for f in failed(client, "aurelle") if _is(f, "order")], "verdant data leaked into aurelle health"


def test_s11_good_file_in_same_batch_is_accepted(client):
    """batch_bad also carries a valid returns file for crunchwell; it must not be rejected with its neighbour."""
    assert not [f for f in failed(client, "crunchwell") if _is(f, "return")]
