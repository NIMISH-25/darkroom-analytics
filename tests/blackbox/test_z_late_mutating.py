"""Runs LAST, in its own pytest process (marker `late`): ingests batch_4_revision and batch_overlap.
S17 (a new ingest changes the ETag; a replay does not) and essential test #6 (an overlapping weekly resend is
quarantined and changes no total)."""
import pytest

from helpers import API, EXPECTED, V2, dec, evidence, get_json, metric_result

pytestmark = [pytest.mark.late, pytest.mark.v2, pytest.mark.after_b3, pytest.mark.mutating]


def test_s17_new_ingest_changes_etag_and_replay_does_not(client, ingest):
    route = f"{API}/overview"
    before = client.get(route)
    e0, rev0 = before.headers["etag"], get_json(client, f"{API}/meta")["data_revision"]
    r = ingest("batch_4_revision")
    assert r.returncode == 0, r.stdout[-300:] + r.stderr[-300:]
    after = client.get(route)
    rev1 = get_json(client, f"{API}/meta")["data_revision"]
    assert rev1 != rev0, "an ingest that adds a $1.00 order must create a new data_revision"
    assert after.headers["etag"] != e0, "ETag must change with the revision"
    assert client.get(route, headers={"If-None-Match": e0}).status_code == 200, "old ETag must not 304"
    assert client.get(route, headers={"If-None-Match": after.headers["etag"]}).status_code == 304
    # replay: same revision, same ETag
    assert ingest("batch_4_revision").returncode == 0
    assert get_json(client, f"{API}/meta")["data_revision"] == rev1
    assert client.get(route).headers["etag"] == after.headers["etag"]
    # old-revision evidence is a 409 that is never cached
    stale = client.get(f"{API}/metrics/gmv/evidence", params={"brand_id": "verdant", "revision": rev0})
    assert stale.status_code == 409 and "etag" not in stale.headers
    # the $1.00 verdant September order is visible (hand value: 0.00 -> 1.00)
    mv = metric_result(client, "gmv", {"brand_id": "verdant", "month": "2026-09", "cutoff": "2026-10-15"})
    assert dec(mv["value"]) == dec("1.00")


def test_e06_overlapping_weekly_resend_is_quarantined_and_changes_nothing(client, ingest):
    p = {"brand_id": "aurelle", "creator_id": "cr_0001", "month": "2026-10", "cutoff": "2026-10-15"}
    before = evidence(client, "creator_videos", p)
    v0 = metric_result(client, "videos", {k: p[k] for k in ("brand_id", "month", "cutoff")})
    r = ingest("batch_overlap")                 # W41 re-sent with views 999 / gmv 999.00 / 9 items
    assert "Traceback" not in r.stderr
    after = evidence(client, "creator_videos", p)
    v1 = metric_result(client, "videos", {k: p[k] for k in ("brand_id", "month", "cutoff")})
    assert dec(v1["value"]) == dec(v0["value"]) == 1, "an overlapping resend must not add or replace videos"
    assert after["records"] == before["records"], "quarantined rows leaked into the evidence"
    if "views" in [c.lower() for c in after["columns"]]:
        views = sum(int({k.lower(): x for k, x in r_["values"].items()}["views"]) for r_ in after["records"]
                    if r_.get("included", True))
        assert views == 140, f"per-week 100 + 40 = 140; the 999 resend must not be summed or substituted, got {views}"
    health = get_json(client, f"{API}/data-health", brand_id="aurelle")
    vid = [s for s in health["sources"] if "video" in s["source"]]
    assert vid and vid[0]["status"] != "current" or health["failed_files"] or r.returncode != 0, \
        "the quarantine must be visible (non-current source, failed file or non-zero exit)"


def test_w3_overlap_quarantine_counts_for_aurelle_only(client):
    """Hand-derived: batch_overlap quarantines aurelle's W41 weekly file -> aurelle brand_failed 1 (weekly videos);
    verdant keeps its 1 (batch_bad orders); crunchwell, threadline, glowhaus stay 0 on golden data."""
    want = {"aurelle": 1, "verdant": 1, "crunchwell": 0, "threadline": 0, "glowhaus": 0}
    for brand, n in want.items():
        h = get_json(client, f"{API}/data-health", brand_id=brand)
        assert h["counts"]["brand_failed"] == n, (brand, h["failed_files"])
    a = get_json(client, f"{API}/data-health", brand_id="aurelle")["failed_files"]
    assert any("video" in f["file_name"].lower() for f in a)
