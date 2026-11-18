"""S4 replay is a no-op; S5 an older version after a newer one never wins. Drives the CLI.
Runs only after golden batch_2 is ingested (final state: batch_1 + batch_2)."""
import pytest

from helpers import API, EXPECTED, dec, get_json, metric_result

pytestmark = [pytest.mark.mutating, pytest.mark.after_b2]

SNAPSHOT_ROUTES = [
    (f"{API}/meta", {}), (f"{API}/overview", {}),
    (f"{API}/brands/aurelle/creators", {"cutoff": "2026-10-20"}), (f"{API}/brands/verdant/creators", {}),
    (f"{API}/brands/threadline/samples", {}), (f"{API}/attention", {}),
    (f"{API}/metrics/net_attributed_sales/evidence",
     {"brand_id": "aurelle", "month": "2026-10", "cutoff": "2026-10-20"}),
]


def snapshot(client):
    return {(p, tuple(sorted(q.items()))): get_json(client, p, **q) for p, q in SNAPSHOT_ROUTES}


def test_s4_replay_is_identical(client, ingest):
    before = snapshot(client)
    rev = before[(f"{API}/meta", ())]["data_revision"]
    for folder in ("batch_1", "batch_2", "batch_1", "batch_2"):
        r = ingest(folder)
        assert r.returncode == 0, f"replay of {folder} failed: {r.stdout[-400:]} {r.stderr[-400:]}"
    after = snapshot(client)
    assert after[(f"{API}/meta", ())]["data_revision"] == rev, "replay must not create a new data_revision"
    assert after == before, "replay changed an API response"


def test_s5_older_version_after_newer_loses(client, ingest):
    params = {"brand_id": "crunchwell", "month": "2026-10", "cutoff": "2026-10-15"}
    assert dec(metric_result(client, "gmv", params)["value"]) == dec(
        EXPECTED["ingest"]["batch_older_expected_crunchwell_gmv"])
    r = ingest("batch_older")          # carries the $20.00 version with an older update time
    assert "Traceback" not in r.stderr, "CLI crashed instead of reporting"
    assert dec(metric_result(client, "gmv", params)["value"]) == dec("45.00"), \
        "older $20.00 version overwrote the newer one"
    ingest("batch_2")                  # re-ingesting the newest keeps 45.00
    assert dec(metric_result(client, "gmv", params)["value"]) == dec("45.00")
