"""S19 latency budget: every GET < 2s after warm-up, the first call < 3s. Meaningful on the FULL synthetic data set
(python scripts/generate_synthetic_data.py, ingest batch_1 + batch_2), not on the tiny golden fixture; run with -m perf."""
import time

import pytest

from helpers import API, get_json

pytestmark = [pytest.mark.perf, pytest.mark.v2]
BRANDS = ["aurelle", "verdant", "crunchwell", "threadline", "glowhaus"]
SERIES = ["pacing_trajectory", "daily_gmv_refunds", "attribution_reconciliation", "sample_funnel_lag",
          "creator_concentration", "retainer_cadence"]


def routes():
    out = [f"{API}/meta", f"{API}/overview", f"{API}/data-health", f"{API}/attention", f"{API}/portfolio/kpis"]
    for b in BRANDS:
        out += [f"{API}/brands/{b}/creators", f"{API}/brands/{b}/samples", f"{API}/brands/{b}/diagnostics"]
        out += [f"{API}/brands/{b}/charts?series={s}" for s in SERIES]
    out += [f"{API}/portfolio/charts?series={s}" for s in SERIES]
    out += [f"{API}/metrics/{k}/evidence?brand_id=aurelle" for k in ("gmv", "creator_attributed_gmv", "videos")]
    return out


def timed(client, route):
    t = time.perf_counter()
    r = client.get(route)
    return r.status_code, time.perf_counter() - t


def test_s19_first_call_under_3s_then_under_2s(client):
    slow_first, slow_warm, bad = [], [], []
    for route in routes():
        code, t1 = timed(client, route)
        if code != 200:
            bad.append((route, code))
            continue
        if t1 >= 3.0:
            slow_first.append((route, round(t1, 2)))
    for route in routes():
        code, t2 = timed(client, route)
        if code == 200 and t2 >= 2.0:
            slow_warm.append((route, round(t2, 2)))
    assert not bad, f"non-200 responses: {bad}"
    assert not slow_first, f"first call over 3s: {slow_first}"
    assert not slow_warm, f"warm call over 2s: {slow_warm}"


def test_s19_cached_304_is_fast(client):
    route = f"{API}/overview"
    etag = client.get(route).headers["etag"]
    for _ in range(3):
        t = time.perf_counter()
        r = client.get(route, headers={"If-None-Match": etag})
        assert r.status_code == 304 and time.perf_counter() - t < 1.0
