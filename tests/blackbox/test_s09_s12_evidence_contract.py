"""S9 every displayed metric equals its own evidence; S12 stale revision -> refresh_required (API side);
response shapes match docs/api-contract.md."""
import pytest

from helpers import API, abs_url, assert_mv, dec, get_json, walk_mvs

BRANDS = ["aurelle", "verdant", "crunchwell", "threadline", "glowhaus"]
MONEY_COLUMNS = ("paid_amount", "amount", "sale_price", "gmv", "net_amount", "refund_amount")


def all_displayed_mvs(client):
    out = []
    out += [("overview", p, mv) for p, mv in walk_mvs(get_json(client, f"{API}/overview"))]
    for b in BRANDS:
        out += [(f"creators/{b}", p, mv) for p, mv in walk_mvs(get_json(client, f"{API}/brands/{b}/creators"))]
        out += [(f"samples/{b}", p, mv) for p, mv in walk_mvs(get_json(client, f"{API}/brands/{b}/samples"))]
    return out


def test_s9_every_metric_equals_its_evidence(client, base_url):
    mvs = all_displayed_mvs(client)
    assert len(mvs) > 50, "suspiciously few metric values returned"
    checked = 0
    for screen, path, mv in mvs:
        assert_mv(mv, f"{screen}{path}")
        r = client.get(abs_url(base_url, mv["evidence_url"]))
        assert r.status_code == 200, f"{screen}{path}: evidence_url -> {r.status_code}"
        ev = r.json()
        res = ev["result"]
        assert res["value"] == mv["value"] or (res["value"] is not None and mv["value"] is not None
                                               and dec(res["value"]) == dec(mv["value"])), \
            f"{screen}{path} ({mv['metric_key']}): shown {mv['value']!r} but evidence says {res['value']!r}"
        assert res["status"] == mv["status"], f"{screen}{path}: status differs from evidence"
        assert ev["calculation"]["kind"] in ("sum", "distinct_count", "ratio", "forecast", "goal")
        assert ev["label"] and ev["definition"] and ev["definition_version"] is not None
        checked += 1
    assert checked == len(mvs)


def test_s9_sum_evidence_adds_up(client, base_url):
    """Where the evidence rows carry a money column, included rows must add up to the result."""
    verified = 0
    for _, _, mv in all_displayed_mvs(client):
        if mv["unit"] != "USD" or mv["value"] is None:
            continue
        ev = get_json(client, abs_url(base_url, mv["evidence_url"]).replace(base_url, ""))
        if ev["calculation"]["kind"] != "sum" or ev["records_truncated"]:
            continue
        col = next((c for c in MONEY_COLUMNS if ev["records"] and all(c in r["values"] for r in ev["records"])), None)
        if col is None:
            continue
        total = sum((dec(r["values"][col]) for r in ev["records"] if r["included"] and r["values"][col] is not None),
                    start=dec(0))
        assert total == dec(ev["result"]["value"]), f"{mv['metric_key']}: rows sum {total} != result {ev['result']['value']}"
        verified += 1
    if verified == 0:
        pytest.skip("evidence rows expose no recognised money column; sum check not applicable")


def test_s9_evidence_records_keep_source_reference(client):
    ev = get_json(client, f"{API}/metrics/gmv/evidence", brand_id="aurelle", month="2026-10", cutoff="2026-10-15")
    assert ev["records"], "gmv evidence must list records"
    for r in ev["records"]:
        assert r["source_file"] and r["source_locator"] not in (None, ""), "every fact row keeps its source reference"
        assert set(r) >= {"source_file", "source_locator", "included", "values"}


def test_s12_stale_revision_requires_refresh(client):
    meta = get_json(client, f"{API}/meta")
    cur = meta["data_revision"]
    ok = client.get(f"{API}/metrics/gmv/evidence", params={"brand_id": "aurelle", "revision": cur})
    assert ok.status_code == 200
    stale = client.get(f"{API}/metrics/gmv/evidence", params={"brand_id": "aurelle", "revision": cur - 1})
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "refresh_required" and detail["current_revision"] == cur
    assert "records" not in stale.text, "409 must not return a mismatching evidence payload"


# ---------------------------------------------------------------- shapes
def test_shape_meta(client):
    b = get_json(client, f"{API}/meta")
    assert {"default_month", "default_cutoff", "months", "brands", "data_revision"} <= set(b)
    assert b["default_month"] == "2026-10" and b["default_cutoff"] == "2026-10-15"
    assert {x["brand_id"] for x in b["brands"]} == set(BRANDS)
    assert all(x["timezone"] == "America/Los_Angeles" for x in b["brands"])


def test_shape_overview(client):
    b = get_json(client, f"{API}/overview")
    assert {"data_revision", "brands"} <= set(b) and len(b["brands"]) == 5
    for br in b["brands"]:
        assert {"brand_id", "name", "goals"} <= set(br) and len(br["goals"]) == 3
        for g in br["goals"]:
            assert {"goal_id", "label", "definition", "scope", "basis", "target", "actual", "projection",
                    "pace_status", "reasoning"} <= set(g)
            assert g["pace_status"] in ("on_track", "at_risk", "off_track", "unknown")
            for k in ("target", "actual", "projection"):
                assert_mv(g[k], f"{br['brand_id']}.{g['goal_id']}.{k}")
            if g.get("required_pace") is not None:
                assert_mv(g["required_pace"])


def test_shape_creators(client):
    b = get_json(client, f"{API}/brands/aurelle/creators")
    assert {"data_revision", "contract_types", "items"} <= set(b)
    for it in b["items"]:
        assert {"creator_id", "handle", "contract_type", "last_post_date", "coverage_status"} <= set(it)
        for k in ("videos", "gmv", "refunds", "net_sales", "retainer_cost", "commission_cost", "sample_cost",
                  "sales_after_costs", "unresolved_gmv"):
            assert_mv(it[k], f"creator {it['creator_id']}.{k}")


def test_creators_sort_nulls_last_and_filters(client):
    asc = get_json(client, f"{API}/brands/aurelle/creators", sort="last_post_date", order="asc")["items"]
    dates = [i["last_post_date"] for i in asc]
    non_null = [d for d in dates if d is not None]
    assert dates[:len(non_null)] == non_null and non_null == sorted(non_null), "nulls must sort last"
    desc = get_json(client, f"{API}/brands/aurelle/creators", sort="last_post_date", order="desc")["items"]
    d2 = [i["last_post_date"] for i in desc]
    assert d2[:len(non_null)] == sorted(non_null, reverse=True) and all(x is None for x in d2[len(non_null):])
    q = get_json(client, f"{API}/brands/aurelle/creators", q="golden.quiet")["items"]
    assert [i["creator_id"] for i in q] == ["cr_0002"]
    ret = get_json(client, f"{API}/brands/aurelle/creators", contract_type="retainer")["items"]
    assert ret and all(i["contract_type"] == "retainer" for i in ret)


def test_shape_samples(client):
    b = get_json(client, f"{API}/brands/threadline/samples")
    assert {"data_revision", "counts", "items"} <= set(b)
    for k in ("sent", "delivered", "matched", "pending", "no_video", "unknown", "conversion_rate"):
        assert_mv(b["counts"][k], f"counts.{k}")
    for it in b["items"]:
        assert {"sample_id", "creator_id", "handle", "product_sku", "sent_date", "delivered_date", "status",
                "video_id", "delivery_to_video_days", "evidence_url"} <= set(it)
        assert it["status"] in ("in_transit", "pending", "matched", "no_video", "unknown")


def test_shape_data_health(client):
    b = get_json(client, f"{API}/data-health")           # portfolio view: all files, shared trackers once
    assert {"data_revision", "sources", "runs", "failed_files", "unresolved_identities", "counts"} <= set(b)
    for s in b["sources"]:
        assert {"brand_id", "source", "status", "coverage_through", "last_ingested_at", "message", "scope",
                "source_label"} <= set(s)
        assert s["scope"] in ("brand", "shared")
    shared = [s["source"] for s in b["sources"] if s["scope"] == "shared"]
    assert len(shared) == len(set(shared)), "each shared tracker is listed once in the portfolio view"
    glow = [s for s in get_json(client, f"{API}/data-health", brand_id="glowhaus")["sources"]
            if "video" in s["source"] and s["scope"] == "brand"]
    assert glow and all(s["status"] != "current" for s in glow), "glowhaus videos must not look current"


def test_shape_attention(client):
    b = get_json(client, f"{API}/attention")
    assert {"data_revision", "items"} <= set(b)
    for it in b["items"]:
        assert {"item_id", "kind", "brand_id", "title", "rule", "period_start", "period_end", "evidence_url"} <= set(it)
        assert it["kind"] in ("quiet_retainer", "sample_no_video", "missing_source")


def test_data_revision_consistent_across_routes(client):
    rev = get_json(client, f"{API}/meta")["data_revision"]
    for path in (f"{API}/overview", f"{API}/brands/aurelle/creators", f"{API}/brands/threadline/samples",
                 f"{API}/data-health", f"{API}/attention"):
        assert get_json(client, path)["data_revision"] == rev, path
