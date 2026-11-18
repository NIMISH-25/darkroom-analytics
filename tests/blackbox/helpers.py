"""Helpers for the blackbox suite. HTTP + CLI only: this package never imports backend/app."""
from __future__ import annotations

import os
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
GOLDEN_DATA = REPO / "data" / "synthetic" / "golden_cases"
EXPECTED = yaml.safe_load((REPO / "tests" / "golden" / "expected.yaml").read_text(encoding="utf-8"))
API = "/api/v1"


def marks_for(stage: str):
    return {"b1_only": [pytest.mark.b1_only], "after_b2": [pytest.mark.after_b2]}.get(stage, [])


def param_cases(cases):
    return [pytest.param(c, id=c["id"], marks=marks_for(c.get("stage", "any"))) for c in cases]


def dec(v):
    """Decimal from an API value (string or number); None stays None. Never float arithmetic."""
    return None if v is None else Decimal(str(v))


def get_json(client, path, expect=200, **params):
    # httpx REPLACES any query string in `path` when params is passed, so merge them explicitly.
    parts = urlsplit(path)
    merged = dict(parse_qsl(parts.query, keep_blank_values=True))
    merged.update({k: v for k, v in params.items() if v is not None})
    url = urlunsplit(("", "", parts.path, "", "")) if not parts.scheme else urlunsplit(parts[:3] + ("", ""))
    r = client.get(url, params=merged or None)
    assert r.status_code == expect, f"GET {path} {params} -> {r.status_code} {r.text[:300]}"
    return r.json()


def evidence(client, metric, params, **extra):
    return get_json(client, f"{API}/metrics/{metric}/evidence", **{**params, **extra})


def metric_result(client, metric, params):
    """The MV under `result` of the evidence response for the same filters."""
    return evidence(client, metric, params)["result"]


def abs_url(base_url: str, evidence_url: str) -> str:
    if evidence_url.startswith("http"):
        return evidence_url
    if evidence_url.startswith("/"):
        return base_url.rstrip("/") + evidence_url
    return base_url.rstrip("/") + API + "/" + evidence_url


MV_KEYS = {"metric_key", "value", "unit", "as_of", "coverage_through", "status", "status_reason", "evidence_url"}
STATUSES = {"current", "partial", "stale", "unavailable"}


def assert_mv(mv, where=""):
    assert isinstance(mv, dict), f"{where}: MV must be an object, got {mv!r}"
    assert MV_KEYS <= set(mv), f"{where}: MV missing {MV_KEYS - set(mv)}"
    assert mv["status"] in STATUSES, f"{where}: bad status {mv['status']}"
    assert isinstance(mv["evidence_url"], str) and mv["evidence_url"], f"{where}: evidence_url"
    if mv["value"] is not None and mv["unit"] == "USD":
        assert isinstance(mv["value"], str), f"{where}: money must be a string"


def walk_mvs(obj, path="$"):
    """Yield (path, mv) for every MetricValue-shaped dict inside an API response."""
    if isinstance(obj, dict):
        if MV_KEYS <= set(obj):
            yield path, obj
            return
        for k, v in obj.items():
            yield from walk_mvs(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_mvs(v, f"{path}[{i}]")


# ---------------------------------------------------------------- amendment 2 helpers
V2 = EXPECTED.get("v2", {})


def chart(client, series, brand_id=None, **params):
    path = f"{API}/brands/{brand_id}/charts" if brand_id else f"{API}/portfolio/charts"
    return get_json(client, path, series=series, **params)


def points_by_x(body):
    return {p["x"]: p for p in body["points"]}


_GOAL_KEYS = {"gmv": "gmv", "video": "videos", "videos": "videos", "active": "active_creators",
              "active_creators": "active_creators"}


def find_goal(overview, brand_id, word):
    """Goal of a brand matched by METRIC KEY (the part of goal_id before ':', e.g. 'videos:creator_attributed'),
    never by words in the definition text (the active_creators definition mentions 'video')."""
    key = _GOAL_KEYS.get(word, word)
    br = next(b for b in overview["brands"] if b["brand_id"] == brand_id)
    hits = [g for g in br["goals"] if str(g["goal_id"]).split(":")[0] == key]
    assert len(hits) >= 1, f"no {key} goal for {brand_id}: {[g['goal_id'] for g in br['goals']]}"
    return hits[0]


def creator_row(client, brand_id, creator_id, **params):
    body = get_json(client, f"{API}/brands/{brand_id}/creators", **params)
    rows = [r for r in body["items"] if r["creator_id"] == creator_id]
    assert len(rows) == 1, f"{creator_id} should appear once in {brand_id} (found {len(rows)})"
    return rows[0]


def money_ok(v):
    """Money strings carry cent precision: no float noise such as 20.290000000000003."""
    d = dec(v)
    return d == d.quantize(Decimal("0.01"))


# ---------------------------------------------------------------- amendment 4: plain-language ban list
import json as _json
import re as _re

BAN = _json.loads((REPO / "tests" / "banned_phrases.json").read_text(encoding="utf-8"))
_STRIP = [_re.compile(r) for r in BAN["strip"]["regex"]]
_NAMES = sorted(BAN["strip"]["brand_names"], key=len, reverse=True)
_BAN = [(b["id"], _re.compile(b["regex"])) for b in BAN["ban"]]
_ALLOW = _re.compile(r"\b(?:" + "|".join(_re.escape(a) for a in BAN["allow"]) + r")\b")


def strip_entities(text: str, extra_names=()) -> str:
    """Remove creator handles, ids, brand names and the allowed badge words before matching the ban list."""
    for r in _STRIP:
        text = r.sub(" ", text)
    for n in sorted(list(_NAMES) + list(extra_names), key=len, reverse=True):
        text = _re.sub(_re.escape(n), " ", text, flags=_re.I)
    return _ALLOW.sub(" ", text)


def violations(text, extra_names=()):
    """[(ban_id, matched_text)] for operator-visible text; empty list means plain English."""
    if not isinstance(text, str):
        return []
    clean = strip_entities(text, extra_names)
    return [(bid, m.group(0)) for bid, rx in _BAN for m in rx.finditer(clean)]


def sv(x):
    """Value of a diagnostics side: amendment 4 sends {value, unavailable_reason}; older shape was a bare value."""
    return x["value"] if isinstance(x, dict) and "value" in x else x


def assert_left_out_note(text, bad, brand_word=None, brand_name=None):
    """A plain note about rows left out: carries the true count and 'left out', and names the brand (in the text or brand_name)."""
    t = text or ""
    assert re.search(r"left\s+out", t, re.I), f"note must say rows were left out: {t!r}"
    assert re.search(rf"\b{bad}\b", t), f"note must carry the true count {bad}: {t!r}"
    if brand_word:
        assert brand_word.lower() in (t + " " + (brand_name or "")).lower(), f"note must name the brand: {t!r} / {brand_name!r}"
