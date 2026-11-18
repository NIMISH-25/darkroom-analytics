"""In-process caches keyed by dataset revision.

* response cache: (revision_id, revision created_at, route, params) -> (ETag, body)
* revision-level data cache: results of repo calls that depend only on the revision
A new revision clears both. Errors, 401/409, notes and health are never stored (callers only use
`respond` for successful GET data routes).
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Callable

from fastapi import Request, Response

_lock = threading.RLock()
_rk = None
_responses: dict = {}
_data: dict = {}
MAX_ENTRIES = 4000


def _roll(rk) -> None:
    global _rk
    with _lock:
        if rk != _rk:
            _rk = rk
            _responses.clear()
            _data.clear()


def rev_cached(rk, key, fn: Callable):
    _roll(rk)
    with _lock:
        if key in _data:
            return _data[key]
    val = fn()
    with _lock:
        if rk == _rk:
            _data[key] = val
    return val


def clear() -> None:
    with _lock:
        _responses.clear()
        _data.clear()


def _dumps(data) -> bytes:
    from app.metrics.service import jsonable
    return json.dumps(jsonable(data), separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def respond(request: Request, repo, build: Callable[[], dict], extra=None) -> Response:
    """Serve a successful GET data response from cache (or build it), with ETag and 304 support."""
    rk = repo.revision_key() if hasattr(repo, "revision_key") else (repo.revision(), None)
    _roll(rk)
    key = (rk, request.url.path, tuple(sorted(request.query_params.multi_items())), extra)
    with _lock:
        hit = _responses.get(key)
    if hit is None:
        from app.presentation.humanize import apply as _plain
        body = _dumps(_plain(build(), repo))
        hit = ('"' + hashlib.sha1(body).hexdigest() + '"', body)
        with _lock:
            if rk == _rk:
                if len(_responses) >= MAX_ENTRIES:
                    _responses.clear()
                _responses[key] = hit
    etag, body = hit
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "X-Data-Revision": str(rk[0])}
    inm = request.headers.get("if-none-match")
    if inm and etag in [t.strip().removeprefix("W/") for t in inm.split(",")]:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


def warm() -> dict:
    """Pre-populate the response cache for the default month/cutoff (overview, creators, samples,
    attention, health and every chart series). Safe to call at startup or after an ingest."""
    from fastapi.testclient import TestClient

    from app import auth
    from app.main import app

    tok, _ = auth.create_token("warm")
    c = TestClient(app, headers={"Authorization": "Bearer " + tok})
    done, failed = 0, 0

    def hit(path, **params):
        nonlocal done, failed
        try:
            r = c.get(path, params=params)
            if r.status_code == 200:
                done += 1
            elif r.status_code != 404:
                failed += 1
        except Exception:
            failed += 1

    hit("/api/v1/meta")
    hit("/api/v1/overview")
    hit("/api/v1/attention")
    hit("/api/v1/data-health")
    series = ["pacing_trajectory", "daily_gmv_refunds", "attribution_reconciliation", "sample_funnel_lag",
              "creator_concentration", "retainer_cadence"]
    brands = c.get("/api/v1/meta").json().get("brands", [])
    for b in brands:
        bid = b["brand_id"]
        hit(f"/api/v1/brands/{bid}/creators")
        hit(f"/api/v1/brands/{bid}/samples")
        for s in series:
            hit(f"/api/v1/brands/{bid}/charts", series=s)
    for s in series:
        hit("/api/v1/portfolio/charts", series=s)
    hit("/api/v1/portfolio/kpis")
    return {"warmed": done, "failed": failed}
