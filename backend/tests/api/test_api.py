from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes_mod
from app.api.routes import get_repo
from app.main import app
from app.metrics import cache
from app.metrics.service import Filters, MetricService, suggested_action


class FakeRepo:
    rev = 3
    fresh_state = "current"

    def revision(self): return self.rev
    def brands(self): return [{"brand_id": "aurelle", "name": "Aurelle Jewelry", "timezone": "America/Los_Angeles"}]
    def months(self): return ["2026-09", "2026-10"]

    def freshness(self, brand_id=None):
        return [{"brand_id": "aurelle", "source_type": s, "state": self.fresh_state if s != "videos_weekly" else "current",
                 "coverage_through": date(2026, 10, 14), "last_ingested_at": None, "message": None}
                for s in ("orders", "affiliate_orders", "returns", "videos_weekly", "samples", "roster")
                if brand_id in (None, "aurelle")]

    def sales_rows(self, brand_id, creator_id, month, cutoff):
        rows = [
            dict(order_id="o1", line_id="1", creator_id="cr_1", eligible=True, bucket="resolved", gmv=Decimal("10.10"), refunded=Decimal("2.00"), source_file="orders/a.json", source_locator="$.orders[0]"),
            dict(order_id="o2", line_id="1", creator_id="cr_1", eligible=True, bucket="resolved", gmv=Decimal("5.00"), refunded=Decimal("0"), source_file="orders/a.json", source_locator="$.orders[1]"),
            dict(order_id="o3", line_id="1", creator_id=None, eligible=True, bucket="creator_unresolved", gmv=Decimal("7.00"), refunded=Decimal("0"), source_file="orders/a.json", source_locator="$.orders[2]"),
            dict(order_id="o4", line_id="1", creator_id="cr_1", eligible=False, bucket="resolved", gmv=Decimal("99"), refunded=Decimal("0"), source_file="orders/a.json", source_locator="$.orders[3]"),
        ]
        return [r for r in rows if creator_id in (None, r["creator_id"])]

    def video_rows(self, brand_id, creator_id, month, cutoff):
        return [dict(brand_id="aurelle", video_id="v1", creator_id="cr_1", qualifies=True, source_file="videos/w.xlsx", source_locator="Sheet!A4"),
                dict(brand_id="aurelle", video_id="v2", creator_id="cr_1", qualifies=False, source_file="videos/w.xlsx", source_locator="Sheet!A5")]

    def sample_rows(self, brand_id, creator_id, status=None):
        return [dict(sample_id="s1", creator_id="cr_1", handle="@a", product_sku="P1", sent_date=date(2026, 8, 1), delivered_date=date(2026, 8, 5), state="matched", matched_video_id="v1", delivery_to_video_days=3, mature=True, source_file="samples.xlsx", source_locator="Samples!A2"),
                dict(sample_id="s2", creator_id="cr_2", handle="@b", product_sku="P1", sent_date=date(2026, 8, 1), delivered_date=date(2026, 8, 5), state="no_video", matched_video_id=None, delivery_to_video_days=None, mature=True, source_file="samples.xlsx", source_locator="Samples!A3"),
                dict(sample_id="s3", creator_id="cr_2", handle="@b", product_sku="P2", sent_date=date(2026, 10, 9), delivered_date=None, state="in_transit", matched_video_id=None, delivery_to_video_days=None, mature=False, source_file="samples.xlsx", source_locator="Samples!A4")]

    def goals(self, brand_id, month):
        return [dict(brand_id="aurelle", metric_key="gmv", scope="creator_attributed", basis="gross", label="GMV", definition="d", target_value=Decimal("1000"), projection=None, required_pace=None, pace_status=None, reasoning="r", status="unavailable", status_reason="coverage gap", coverage_through=None)]

    def creators(self, brand_id, month):
        return [dict(brand_id="aurelle", creator_id="cr_1", handle="@a", contract_type="retainer", last_post_date=date(2026, 10, 1), coverage_status="current", retainer_cost=Decimal("100"), commission_cost=Decimal("1"), sample_cost=None, sales_after_costs=None),
                dict(brand_id="aurelle", creator_id="cr_2", handle="@b", contract_type="affiliate", last_post_date=None, coverage_status="current", retainer_cost=None, commission_cost=None, sample_cost=None, sales_after_costs=None)]

    def attention(self, brand_id=None):
        return [dict(brand_id="aurelle", kind="quiet_retainer", entity_ref="cr_2", reason="quiet", title="Quiet cr_2", period_start=date(2026, 10, 2), period_end=date(2026, 10, 11), creator_id="cr_2"),
                dict(brand_id="aurelle", kind="sample_no_video", entity_ref="SH1:1", reason="no video", title="Sample", period_start=date(2026, 8, 5), period_end=date(2026, 10, 15), creator_id="cr_1", days_waiting=20),
                dict(brand_id="aurelle", kind="missing_source", entity_ref="videos_weekly", reason="gap", title="Missing", period_start=date(2026, 10, 1), period_end=date(2026, 10, 15))]

    def creator_map(self, brand_id, month): return {c["creator_id"]: c for c in self.creators(brand_id, month)}
    def sample_costs(self, brand_id=None): return {("aurelle", "SH1"): Decimal("12.50")}
    notes_rows = []
    def notes(self, brand_id, creator_id): return self.notes_rows

    def creator_handles(self): return {"cr_1": "@a"}
    def runs(self, brand_id=None): return [dict(run_id=1, started_at=date(2026, 10, 1), status="succeeded", files_failed=0)]
    def shared_types(self): return {"roster", "samples"}
    def last_run_id(self): return 1
    def files_with_exclusions(self, brand_id=None): return []
    def excluded_notes(self): return []
    def open_issue_count(self, brand_id=None): return 2
    FAILED = [dict(run_id=2, file_name="orders/aurelle/2026-10.json", error="bad", scope_key="aurelle", source_type="orders", status="rejected"),
              dict(run_id=2, file_name="roster/roster.xlsx", error="x", scope_key="all", source_type="roster", status="quarantined")]
    def failed_files(self, brand_id=None): return list(self.FAILED)
    def unresolved_identities(self, brand_id=None): return []


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def repo():
    r = FakeRepo()
    app.dependency_overrides[get_repo] = lambda: r
    yield r
    app.dependency_overrides.clear()


@pytest.fixture
def c(repo):
    cl = TestClient(app)
    tok = cl.post("/api/v1/auth/token", data={"username": "demo", "password": "darkroom-demo"}).json()["access_token"]
    cl.headers["Authorization"] = f"Bearer {tok}"
    return cl


def test_health_and_auth():
    cl = TestClient(app)
    assert cl.get("/healthz").json() == {"status": "ok"}
    assert cl.post("/api/v1/auth/token", data={"username": "demo", "password": "x"}).status_code == 401
    assert cl.get("/api/v1/meta").status_code == 401
    r = cl.post("/api/v1/auth/token", data={"username": "demo", "password": "darkroom-demo"}).json()
    assert r["token_type"] == "bearer" and r["expires_at"]
    me = cl.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + r["access_token"]})
    assert me.json() == {"username": "demo"}


def test_meta(c):
    j = c.get("/api/v1/meta").json()
    assert j["default_month"] == "2026-10" and j["data_revision"] == 3 and j["brands"][0]["brand_id"] == "aurelle"


def test_value_equals_evidence(c):
    j = c.get("/api/v1/brands/aurelle/creators").json()
    cr = next(i for i in j["items"] if i["creator_id"] == "cr_1")
    assert cr["gmv"]["value"] == "15.10" and cr["net_sales"]["value"] == "13.10" and cr["refunds"]["value"] == "2.00"
    ev = c.get(cr["net_sales"]["evidence_url"]).json()
    assert ev["result"]["value"] == cr["net_sales"]["value"]
    assert sum(1 for r in ev["records"] if r["included"]) == 2
    assert all(r["source_file"] and r["source_locator"] for r in ev["records"])
    assert cr["sample_cost"]["value"] is None and cr["sales_after_costs"]["value"] is None
    assert cr["videos"]["value"] == 1


def test_creator_without_sales_is_verified_zero_when_current(c):
    j = c.get("/api/v1/brands/aurelle/creators?sort=gmv&order=desc").json()
    assert j["items"][0]["creator_id"] == "cr_1"
    assert j["items"][1]["gmv"]["value"] == "0.00"


def test_stale_empty_is_null_not_zero(c, repo):
    repo.fresh_state = "stale"
    j = c.get("/api/v1/brands/aurelle/creators").json()
    cr2 = next(i for i in j["items"] if i["creator_id"] == "cr_2")
    assert cr2["gmv"]["value"] is None and cr2["gmv"]["status"] == "stale" and cr2["gmv"]["status_reason"]


def test_evidence_revision_409(c):
    r = c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&revision=2")
    assert r.status_code == 409
    assert r.json() == {"detail": {"code": "refresh_required", "current_revision": 3}}
    ok = c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&revision=3").json()
    assert ok["result"]["value"] == "22.10" and ok["exclusions"][0]["reason"] == "not_eligible"
    assert ok["period_end"] == "2026-10-15"


def test_overview_unavailable_projection(c):
    g = c.get("/api/v1/overview").json()["brands"][0]["goals"][0]
    assert g["projection"]["value"] is None and g["projection"]["status"] == "unavailable"
    assert g["actual"]["value"] == "15.10" and g["pace_status"] == "unknown"
    ev = c.get(g["projection"]["evidence_url"]).json()
    assert ev["calculation"]["kind"] == "goal" and ev["result"]["value"] is None


def test_samples(c):
    j = c.get("/api/v1/brands/aurelle/samples").json()
    assert j["counts"]["conversion_rate"]["value"] == "0.5000"
    assert j["counts"]["pending"]["value"] == 1 and len(j["items"]) == 3
    assert len(c.get("/api/v1/brands/aurelle/samples?status=matched").json()["items"]) == 1


def test_active_creators_and_health_attention(c):
    ev = c.get("/api/v1/metrics/active_creators/evidence?brand_id=aurelle").json()
    assert ev["result"]["value"] == 1 and ev["calculation"]["kind"] == "distinct_count"
    h = c.get("/api/v1/data-health").json()
    assert h["sources"][0]["source"] and h["runs"][0]["status"] == "succeeded"
    a = c.get("/api/v1/attention?kind=missing_source").json()
    assert a["items"][0]["evidence_url"].startswith("/api/v1/metrics/")
    assert c.get(a["items"][0]["evidence_url"]).status_code == 200


def test_cors_preflight():
    r = TestClient(app).options("/api/v1/meta", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_samples_video_coverage_gap_is_null_not_zero(c, repo):
    orig = repo.sample_rows
    repo.sample_rows = lambda b, cr, status=None: [dict(r, video_coverage_complete=False) for r in orig(b, cr)]
    j = c.get("/api/v1/brands/aurelle/samples").json()["counts"]
    assert j["no_video"]["value"] is None and j["no_video"]["status"] == "partial" and j["no_video"]["status_reason"]
    assert j["conversion_rate"]["value"] is None and j["conversion_rate"]["status"] == "partial"


def test_attention_ranked_by_impact_nulls_last(c):
    items = c.get("/api/v1/attention").json()["items"]
    assert [i["rank"] for i in items] == [1, 2, 3]
    assert [i["kind"] for i in items] == ["missing_source", "sample_no_video", "quiet_retainer"]
    assert items[0]["impact_score"] == "483.87" and "GMV target" in items[0]["impact_basis"]
    assert items[1]["impact_score"] == "12.50"
    assert items[2]["impact_score"] is None and "unknown" in items[2]["impact_basis"]


def test_etag_and_304(c):
    r = c.get("/api/v1/overview")
    assert r.headers["cache-control"] == "private, no-cache" and r.headers["etag"]
    r2 = c.get("/api/v1/overview", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304 and r2.content == b""
    assert c.get("/api/v1/overview").content == r.content
    assert "etag" not in c.post("/api/v1/auth/token", data={"username": "demo", "password": "x"}).headers


def test_cache_not_used_for_errors_or_409(c):
    assert c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&revision=1").status_code == 409
    assert c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&revision=1").status_code == 409
    assert c.get("/api/v1/metrics/nope/evidence").status_code == 404


def test_evidence_pagination(c):
    full = c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle").json()
    assert full["total_count"] == 4 and full["next_offset"] is None and len(full["records"]) == 4
    p1 = c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&limit=3").json()
    assert len(p1["records"]) == 3 and p1["next_offset"] == 3 and p1["result"]["value"] == full["result"]["value"]
    assert p1["exclusions"] == full["exclusions"]
    p2 = c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&limit=3&offset=3").json()
    assert len(p2["records"]) == 1 and p2["next_offset"] is None and p2["offset"] == 3
    assert c.get("/api/v1/metrics/gmv/evidence?limit=0").status_code == 422
    assert c.get("/api/v1/metrics/gmv/evidence?limit=501").status_code == 422
    assert c.get("/api/v1/metrics/gmv/evidence?offset=-1").status_code == 422


def test_notes(c, repo, monkeypatch):
    import contextlib

    class Conn:
        def execute(self, sql, params):
            self.p = params
            return self

        def fetchone(self):
            return dict(note_id=7, brand_id=self.p[0], creator_id=self.p[1], body=self.p[2], author=self.p[3],
                        created_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc))

    @contextlib.contextmanager
    def fake_write():
        yield Conn()

    monkeypatch.setattr(routes_mod, "write_conn", fake_write)
    url = "/api/v1/brands/aurelle/creators/cr_1/notes"
    r = c.post(url, json={"body": "  call her  "})
    assert r.status_code == 201 and r.json()["body"] == "call her" and r.json()["author"] == "demo"
    assert c.post(url, json={"body": "   "}).status_code == 422
    assert c.post(url, json={"body": "x" * 2001}).status_code == 422
    assert c.post(url, json={}).status_code == 422
    assert TestClient(app).post(url, json={"body": "a"}).status_code == 401
    repo.notes_rows = [dict(note_id=7, brand_id="aurelle", creator_id="cr_1", author="demo", body="call her", created_at=datetime(2026, 10, 15, tzinfo=timezone.utc))]
    g = c.get(url)
    assert g.json()["total_count"] == 1 and g.headers["cache-control"] == "no-store"
    assert c.get("/api/v1/brands/aurelle/creators/nobody/notes").status_code == 404


def test_suggested_action_rules_and_creator_rows(c):
    items = c.get("/api/v1/brands/aurelle/creators").json()["items"]
    sa = items[0]["suggested_action"]
    assert sa["action"] == "review" and sa["status"] == "partial" and "10 or more days" in sa["rule"]

    def mv(v, status="current"):
        return {"value": v, "status": status}

    base = dict(contract_type="retainer", last_post_date="2026-09-20", net_sales=mv("500.00"),
                sales_after_costs=mv("100.00"), videos=mv(2))
    assert suggested_action(base, "2026-10-15")["action"] == "nudge"
    assert suggested_action(dict(base, last_post_date="2026-10-10"), "2026-10-15")["action"] == "watch"
    assert suggested_action(dict(base, last_post_date="2026-10-10", sales_after_costs=mv("-5.00")), "2026-10-15")["action"] == "rebook"
    aff = dict(base, contract_type="affiliate", net_sales=mv("1000.00"))
    assert suggested_action(aff, "2026-10-15")["action"] == "upgrade"
    assert suggested_action(dict(aff, net_sales=mv(None)), "2026-10-15")["action"] == "review"


def test_goal_projection_null_when_actual_unknown_or_stale(c, repo):
    repo.goals = lambda b, m: [dict(brand_id="aurelle", metric_key="gmv", scope="shop", basis="gross", label="GMV", definition="d", target_value=Decimal("1000"), projection=Decimal("50.00"), required_pace=Decimal("3.00"), pace_status="on_track", reasoning="r", status="current", status_reason=None, coverage_through=date(2026, 10, 14))]
    g = c.get("/api/v1/overview").json()["brands"][0]["goals"][0]
    assert g["projection"]["value"] == "50.00" and g["required_pace"]["value"] == "3.00" and g["pace_status"] == "on_track"
    cache.clear()
    repo.fresh_state = "stale"
    g = c.get("/api/v1/overview").json()["brands"][0]["goals"][0]
    assert g["projection"]["value"] is None and g["projection"]["status"] == "stale" and g["projection"]["status_reason"]
    assert g["required_pace"]["value"] is None and g["pace_status"] == "unknown"


def test_unknown_gmv_is_never_zero(repo):
    repo.sales_rows = lambda b, cr, m, cu: [dict(order_id="o9", line_id="1", creator_id="cr_1", eligible=True, bucket="resolved", gmv=None, refunded=Decimal("0"), video_known=False, source_file="f", source_locator="l", row_num=1)]
    r = MetricService(repo).compute_part("creator_attributed_gmv", "unresolved", Filters(brand_id="aurelle", creator_id="cr_1"))
    assert r["value"] is None
    assert all(e["amount"] is None for e in r["exclusions"])


def test_chart_evidence_dispatch(c, monkeypatch):
    import contextlib
    import app.metrics.charts as ch
    seen = {}

    class FakeCharts:
        def __init__(self, conn=None): pass

    def fake_ev(key, params, crepo):
        seen.update(key=key, **params)
        return {"result": {"value": "1"}, "records": [], "total_count": 0}

    monkeypatch.setattr(ch, "ChartsRepo", FakeCharts)
    monkeypatch.setattr(ch, "chart_evidence", fake_ev)
    r = c.get("/api/v1/metrics/decomposition/evidence?brand_id=aurelle&date_from=2026-10-01&date_to=2026-10-15&bucket=resolved&stage=sent&metric=gmv&limit=5&offset=2")
    assert r.status_code == 200 and r.json()["total_count"] == 0
    assert seen["key"] == "decomposition" and seen["date_from"] == "2026-10-01" and seen["bucket"] == "resolved" \
        and seen["limit"] == 5 and seen["offset"] == 2 and seen["metric"] == "gmv"
    # chart filters on an ordinary key also route to the chart hook; stale revision still 409
    assert c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&bucket=resolved").status_code == 200
    r409 = c.get("/api/v1/metrics/portfolio_pacing/evidence?revision=1")
    assert r409.status_code == 409 and r409.json()["detail"]["code"] == "refresh_required"
    assert c.get("/api/v1/metrics/nope/evidence").status_code == 404


def test_overview_progress_ratio(c, repo):
    repo.goals = lambda b, m: [dict(brand_id="aurelle", metric_key="gmv", scope="shop", basis="gross", label="GMV", definition="d", target_value=Decimal("10.00"), projection=Decimal("50.00"), required_pace=Decimal("3.00"), pace_status="on_track", reasoning="r", status="current", status_reason=None, coverage_through=date(2026, 10, 14))]
    g = c.get("/api/v1/overview").json()["brands"][0]["goals"][0]
    # actual 15.10 / target 10.00 = 1.51 -> capped at 1.5
    assert g["progress"]["value"] == "1.5000" and g["progress"]["unit"] == "ratio"
    ev = c.get(g["progress"]["evidence_url"]).json()
    assert ev["result"]["value"] == "1.5000"
    cache.clear()
    repo.fresh_state = "stale"
    g = c.get("/api/v1/overview").json()["brands"][0]["goals"][0]
    assert g["progress"]["value"] is None and g["progress"]["status"] == "stale" and g["progress"]["status_reason"]


def test_progress_ratio_unit():
    from app.metrics.service import progress_ratio
    assert progress_ratio("5", "10")[0] == "0.5000"
    assert progress_ratio(None, "10")[0] is None and progress_ratio("5", None)[1] == "unavailable"
    assert progress_ratio("5", "0")[0] is None and progress_ratio("5", "10", "stale")[0] is None


def test_request_cutoff_is_set_on_every_snapshot(monkeypatch):
    from fastapi import FastAPI
    import app.main as main_mod
    from app.metrics import conn as connmod

    executed = []

    class FakeConn:
        def execute(self, sql, params=None):
            executed.append((sql, params))
            return self

        def rollback(self): pass
        def close(self): pass

    monkeypatch.setattr(connmod, "_read", None)
    monkeypatch.setattr(connmod.psycopg, "connect", lambda *a, **k: FakeConn())
    monkeypatch.setattr(connmod, "_cfg_read", lambda conn: None)
    probe = FastAPI()
    probe.add_middleware(main_mod.CutoffMiddleware)

    @probe.get("/p")
    def p():
        with connmod.read_conn():
            pass
        return {"ok": True}

    cl = TestClient(probe)
    cl.get("/p?cutoff=2026-10-12")
    cl.get("/p")
    cl.get("/p?cutoff=garbage")
    assert [e[1] for e in executed] == [("2026-10-12",), ("2026-10-15",), ("2026-10-15",)]
    assert all("set_config('app.cutoff'" in e[0] and e[0].count("true") == 1 for e in executed)


def test_response_cache_key_includes_cutoff(c, repo):
    built = []
    orig = repo.sales_rows
    repo.sales_rows = lambda b, cr, m, cu: built.append(cu) or orig(b, cr, m, cu)
    c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&cutoff=2026-10-10")
    c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&cutoff=2026-10-12")
    n = len(built)
    c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle&cutoff=2026-10-12")  # cached: no new query
    assert n >= 2 and len(built) == n


def test_non_usd_exclusion_in_evidence(c, repo):
    orig = repo.sales_rows
    repo.sales_rows = lambda b, cr, m, cu: orig(b, cr, m, cu) + [
        dict(order_id="o5", line_id="1", creator_id=None, eligible=False, bucket=None, gmv=None, refunded=None,
             exclusion_reason="non_usd_currency", currency="EUR", paid_amount=Decimal("120.00"), creator_raw="@x",
             source_file="orders/a.json", source_locator="$.orders[4]")]
    ev = c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle").json()
    e = next(x for x in ev["exclusions"] if x["reason"] == "non_usd_currency")
    assert e["count"] == 1 and e["amount"] == "120.00" and e["currency"] == "EUR" and "original currency" in e["amount_label"]
    assert ev["result"]["value"] == "22.10"
    assert "creator_raw" in ev["columns"]


def test_data_health_is_brand_scoped_with_shared_trackers(c):
    h = c.get("/api/v1/data-health?brand_id=aurelle").json()
    assert h["counts"] == {"brand_failed": 1, "shared_failed": 1, "open_issues": 2, "rows_excluded": 0}
    by = {f["file_name"]: f for f in h["failed_files"]}
    assert by["orders/aurelle/2026-10.json"]["scope"] == "brand" and by["orders/aurelle/2026-10.json"]["brand_id"] == "aurelle"
    sh = by["roster/roster.xlsx"]
    assert sh["scope"] == "shared" and sh["brand_id"] is None and sh["source_label"] == "Shared Cross-Brand Source"
    shared_src = [s for s in h["sources"] if s["scope"] == "shared"]
    assert {s["source"] for s in shared_src} == {"roster", "samples"} and all(s["brand_id"] is None for s in shared_src)
    assert all(s["scope"] == "brand" and s["source_label"] is None for s in h["sources"] if s["source"] not in ("roster", "samples"))
    assert c.get("/api/v1/data-health?brand_id=nope").status_code == 404
    p = c.get("/api/v1/data-health").json()
    assert [s["source"] for s in p["sources"] if s["scope"] == "shared"].count("roster") == 1  # listed once


def test_data_health_cache_key_has_brand_and_last_run(c, repo):
    a = c.get("/api/v1/data-health?brand_id=aurelle").json()
    repo.FAILED = repo.FAILED[:1]
    assert c.get("/api/v1/data-health?brand_id=aurelle").json()["counts"]["shared_failed"] == 1  # same run id: cached
    repo.last_run_id = lambda: 2  # a replay adds a run but no revision
    assert c.get("/api/v1/data-health?brand_id=aurelle").json()["counts"]["shared_failed"] == 0


def test_evidence_explainer(c):
    ev = c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle").json()
    ex = ev["explainer"]
    assert set(ex) == {"what_it_means", "why_it_matters", "how_calculated", "what_rows_prove"} and all(ex.values())
    assert "cancelled, unpaid or a free sample" in ex["how_calculated"] and "real record" in ex["what_rows_prove"]
    for k in ("what_this_means", "why_it_matters", "what_to_watch", "data_note", "incomplete_reason"):
        assert k in ev
    assert ev["what_this_means"] == ex["what_it_means"] and "Aurelle Jewelry" in ev["what_this_means"]
    assert {c["key"] for c in ev["columns_plain"]} == set(ev["columns"]) and all(c["label"] for c in ev["columns_plain"])
    assert {"key": "order_id", "label": "Order number"} in ev["columns_plain"]
    for key in ("videos", "active_creators", "sample_conversion_rate", "creator_attributed_gmv", "net_attributed_sales"):
        assert c.get(f"/api/v1/metrics/{key}/evidence?brand_id=aurelle").json()["explainer"]["what_it_means"]
    net = c.get("/api/v1/metrics/net_attributed_sales/evidence?brand_id=aurelle").json()["explainer"]
    assert "late" in ev_watch(c, "net_attributed_sales") or "Refunds that finish after" in ev_watch(c, "net_attributed_sales")


def ev_watch(c, key):
    return c.get(f"/api/v1/metrics/{key}/evidence?brand_id=aurelle").json()["what_to_watch"]


BANNED = [r"\w+\[\d+\]", r"\b_?[a-z]+_[a-z_]+\b", r"\b(count|sum|avg)\s*\(", r"\bdistinct\b", r"UNAVAILABLE", r"\bnull\b",
          r"\bNone\b", r"\bNaN\b", r"\bundefined\b", r"is required", r"[{}]"]
TEXT_KEYS = {"status_reason", "incomplete_reason", "data_note", "plain_reason", "unavailable_reason", "why_needs_attention",
             "what_to_do", "what_this_means", "why_it_matters", "what_to_watch", "required_pace_reason", "reasoning", "title",
             "what_it_means", "how_calculated", "what_rows_prove", "observation", "message", "error"}


def crawl(o, found, path=""):
    import re
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and k in TEXT_KEYS:
                for pat in BANNED:
                    if re.search(pat, v):
                        found.append((path + "." + k, v, pat))
            else:
                crawl(v, found, path + "." + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            crawl(v, found, f"{path}[{i}]")


def test_no_developer_language_in_any_response(c, repo):
    repo.fresh_state = "incomplete"
    urls = ["/api/v1/overview", "/api/v1/brands/aurelle/creators", "/api/v1/brands/aurelle/samples", "/api/v1/attention",
            "/api/v1/data-health?brand_id=aurelle", "/api/v1/metrics/gmv/evidence?brand_id=aurelle",
            "/api/v1/metrics/net_attributed_sales/evidence?brand_id=aurelle", "/api/v1/metrics/sample_conversion_rate/evidence?brand_id=aurelle",
            "/api/v1/metrics/creator_sales_after_costs/evidence?brand_id=aurelle&creator_id=cr_1"]
    found = []
    for u in urls:
        r = c.get(u)
        assert r.status_code == 200, u
        crawl(r.json(), found, u)
    assert found == []


def test_plain_422_and_goal_evidence_without_goal(c):
    r = c.get("/api/v1/metrics/goal_projection/evidence")
    assert r.status_code == 422 and r.json()["detail"] == "Choose which goal to explain."
    assert c.get("/api/v1/metrics/gmv/evidence?limit=0").json()["detail"] == "Choose a page size between 1 and 500."
    assert c.get("/api/v1/overview?month=2026-13").json()["detail"] == "Choose a month like 2026-10."
    ok = c.get("/api/v1/metrics/goal_projection/evidence?brand_id=aurelle")  # picks the brand's main sales goal
    assert ok.status_code == 200 and ok.json()["result"]["metric_key"] == "goal_projection"


def test_humanize_maps_and_unknown_codes(caplog):
    from app.presentation.humanize import GENERIC, humanize, plain_text
    assert humanize("order_id") == "order number" and humanize("videos_weekly") == "weekly video reports"
    assert humanize("zz_unknown_code") == GENERIC and "unknown code" in caplog.text
    t = plain_text("orders: 1 coverage gap(s), 0 quarantined, 1 rejected file(s); last error: orders[1] missing required field order_id", {"brand": "Verdant"})
    assert t.startswith("Verdant") and "[" not in t and "(s)" not in t and "order_id" not in t
    assert plain_text("totally unexpected thing_with_code count(distinct video_id)") and "_" not in plain_text("a thing_with_code")


def test_mv_data_note_from_excluded_rows(c, repo):
    repo.excluded_notes = lambda: [dict(brand_id="aurelle", source_type="orders", message=None, n=1)]
    cr = c.get("/api/v1/brands/aurelle/creators").json()["items"][0]
    note = cr["gmv"]["data_note"]
    assert note and "Aurelle Jewelry" in note and "higher than shown" in note
    assert c.get("/api/v1/overview").json()["brands"][0]["goals"][0]["actual"]["data_note"]
    ev = c.get("/api/v1/metrics/gmv/evidence?brand_id=aurelle").json()
    assert ev["data_note"] and ev["data_note"] in ev["what_to_watch"]


def test_goal_fields_required_pace_applicability(c, repo):
    base = dict(brand_id="aurelle", scope="creator_attributed", basis="gross", definition="d", projection=Decimal("50.00"),
                required_pace=None, pace_status="on_track", reasoning="x", status="current", status_reason=None, coverage_through=date(2026, 10, 14))
    repo.goals = lambda b, m: [dict(base, metric_key="active_creators", target_value=Decimal("5")),
                               dict(base, metric_key="videos", target_value=None),
                               dict(base, metric_key="gmv", scope="shop", target_value=Decimal("100"), required_pace=Decimal("2.00"))]
    gs = {g["goal_id"]: g for g in c.get("/api/v1/overview").json()["brands"][0]["goals"]}
    ac, vd, gm = gs["active_creators:creator_attributed"], gs["videos:creator_attributed"], gs["gmv:shop"]
    assert ac["required_pace_applicable"] is False and ac["required_pace_reason"]
    assert vd["required_pace_applicable"] is False and "target" in vd["required_pace_reason"]
    assert gm["required_pace_applicable"] is True and gm["required_pace_reason"] is None
    assert gm["label"] == "Total sales" and "on course" in gm["reasoning"]


def test_attention_plain_fields(c):
    items = c.get("/api/v1/attention").json()["items"]
    for i in items:
        assert i["brand_name"] == "Aurelle Jewelry" and i["why_needs_attention"] and i["what_to_do"]
        assert {"incomplete_reason", "data_note", "creator_name"} <= set(i)
    q = next(i for i in items if i["kind"] == "quiet_retainer")
    assert "has gone quiet" in q["title"]


def test_data_health_plain_reasons_and_exclusions(c, repo):
    repo.FAILED = [dict(run_id=2, file_name="orders/verdant/x.json", error="orders[1] missing required field 'order_id'",
                        scope_key="aurelle", source_type="orders", status="rejected")]
    repo.files_with_exclusions = lambda b=None: [dict(run_id=3, file_name="orders/aurelle/ok.json", scope_key="aurelle",
                                                      source_type="orders", rows_excluded=2)]
    h = c.get("/api/v1/data-health?brand_id=aurelle").json()
    f = h["failed_files"][0]
    assert f["brand_name"] == "Aurelle Jewelry" and "order number" in f["plain_reason"] and "[" not in f["error"]
    e = h["files_with_exclusions"][0]
    assert e["rows_excluded"] == 2 and "left out" in e["plain_reason"] and e["brand_name"] == "Aurelle Jewelry"
    assert h["counts"]["rows_excluded"] == 2
