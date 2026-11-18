"""Plain-English operator interface. HTTP only.
The crawl walks every operator-visible string field of the main responses and asserts none matches tests/banned_phrases.json
(after entity names are stripped). Needs the plain-English backend; run after golden batch_3 (stage 3)."""
import pytest

from helpers import API, V2, EXPECTED, dec, get_json, sv, violations

pytestmark = [pytest.mark.v2, pytest.mark.a4, pytest.mark.after_b3]
BRANDS = ["aurelle", "verdant", "crunchwell", "threadline", "glowhaus"]
SERIES = ["pacing_trajectory", "daily_gmv_refunds", "attribution_reconciliation", "sample_funnel_lag",
          "creator_concentration", "retainer_cadence"]
METRIC_KEYS = ["gmv", "creator_attributed_gmv", "net_attributed_sales", "videos", "active_creators", "goal_projection",
               "creator_videos", "creator_net_sales", "sample_conversion_rate", "creator_sales_after_costs"]

# operator-visible string fields plus the older explainer mirror and chart/diagnostic notes
TEXT_KEYS = {"status_reason", "data_note", "what_this_means", "why_it_matters", "what_to_watch", "incomplete_reason",
             "why_needs_attention", "what_to_do", "plain_reason", "unavailable_reason", "required_pace_reason",
             "status_label", "goal_name", "actual_label", "target_label", "what_it_means", "how_calculated",
             "what_rows_prove", "disclaimer", "title", "rule", "label_plain"}


def walk_text(obj, path="$"):
    """Yield (path, text) for every operator-visible string in a response."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if k in TEXT_KEYS and isinstance(v, str):
                yield p, v
            elif k == "notes" and isinstance(v, list):
                for i, n in enumerate(v):
                    if isinstance(n, str):
                        yield f"{p}[{i}]", n
                    elif isinstance(n, dict):
                        yield from walk_text(n, f"{p}[{i}]")
            elif k == "columns_plain" and isinstance(v, list):
                for i, c in enumerate(v):
                    if isinstance(c, dict) and isinstance(c.get("label"), str):
                        yield f"{p}[{i}].label", c["label"]
            else:
                yield from walk_text(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_text(v, f"{path}[{i}]")


def metric_params(client, key):
    base = {"brand_id": "aurelle", "month": "2026-10", "cutoff": "2026-10-15"}
    if key.startswith("creator_"):
        items = get_json(client, f"{API}/brands/aurelle/creators", month="2026-10", cutoff="2026-10-15")["items"]
        return {**base, "creator_id": items[0]["creator_id"]}
    if key == "sample_conversion_rate":
        return {"brand_id": "threadline"}
    if key == "goal_projection":
        ov = get_json(client, f"{API}/overview", month="2026-10", cutoff="2026-10-15")
        goal = next(b for b in ov["brands"] if b["brand_id"] == "aurelle")["goals"][0]
        return {**base, "goal_id": goal["goal_id"]}
    return base


def crawl_responses(client):
    out = {"overview": get_json(client, f"{API}/overview"), "portfolio_kpis": get_json(client, f"{API}/portfolio/kpis"),
           "data_health_portfolio": get_json(client, f"{API}/data-health")}
    for b in BRANDS:
        out[f"creators/{b}"] = get_json(client, f"{API}/brands/{b}/creators")
        out[f"samples/{b}"] = get_json(client, f"{API}/brands/{b}/samples")
        out[f"attention/{b}"] = get_json(client, f"{API}/attention", brand_id=b)
        out[f"diagnostics/{b}"] = get_json(client, f"{API}/brands/{b}/diagnostics", month="2026-10", cutoff="2026-10-15")
        out[f"health/{b}"] = get_json(client, f"{API}/data-health", brand_id=b)
        out[f"available/{b}"] = get_json(client, f"{API}/brands/{b}/charts/available", month="2026-10", cutoff="2026-10-15")
        for s in SERIES:
            kw = {"metric": "gmv"} if s == "pacing_trajectory" else {}
            out[f"chart/{b}/{s}"] = get_json(client, f"{API}/brands/{b}/charts", series=s, month="2026-10",
                                             cutoff="2026-10-15", **kw)
    for k in METRIC_KEYS:
        out[f"evidence/{k}"] = get_json(client, f"{API}/metrics/{k}/evidence", **metric_params(client, k))
    return out


def test_a4_no_developer_language_in_any_operator_visible_string(client):
    meta = get_json(client, f"{API}/meta")
    names = [b["name"] for b in meta["brands"]] + [b["brand_id"] for b in meta["brands"]]
    bad, seen = [], 0
    for where, body in crawl_responses(client).items():
        for path, text in walk_text(body):
            seen += 1
            v = violations(text, names)
            if v:
                bad.append(f"{where} {path}: {v[:3]} in {text[:90]!r}")
    assert seen > 200, f"the crawl only saw {seen} strings; operator text fields are missing"
    assert not bad, "developer language in operator-visible text:\n" + "\n".join(bad[:25])


def test_a4_every_metric_value_has_plain_reason_and_data_note_field(client):
    body = get_json(client, f"{API}/brands/aurelle/creators", month="2026-10", cutoff="2026-10-15")
    mvs = [v for it in body["items"] for v in it.values() if isinstance(v, dict) and "evidence_url" in v]
    assert mvs
    for mv in mvs:
        assert "data_note" in mv, "every metric value carries data_note (null when complete)"
        if mv["status"] != "current":
            assert mv["status_reason"], "a non-complete value needs a plain reason"


def test_a4_422_for_a_missing_parameter_is_a_plain_sentence(client):
    r = client.get(f"{API}/metrics/goal_projection/evidence", params={"brand_id": "aurelle"})
    assert r.status_code in (200, 422), r.text[:200]
    if r.status_code == 422:
        detail = r.json()["detail"]
        assert isinstance(detail, str), f"422 detail must be one plain sentence, got {detail!r}"
        assert violations(detail) == [] and "goal_id" not in detail, detail
    else:
        assert r.json()["result"], "evidence without a goal must pick the brand's main sales goal"


def test_a4_evidence_has_plain_sections_and_plain_columns(client):
    for key in ("gmv", "videos", "creator_net_sales"):
        ev = get_json(client, f"{API}/metrics/{key}/evidence", **metric_params(client, key))
        for f in ("what_this_means", "why_it_matters", "what_to_watch"):
            assert isinstance(ev.get(f), str) and len(ev[f].strip()) >= 20, f"{key}.{f}"
        assert "incomplete_reason" in ev and "data_note" in ev
        cols = ev["columns_plain"]
        assert isinstance(cols, list) and all({"key", "label"} <= set(c) and c["label"] for c in cols)
        if ev["records"]:            # an answer with no supporting rows legitimately has no columns to label
            assert cols, f"{key}: records are listed but columns_plain is empty"


# ------------------------------------------------------------------ goals and brand pace
def test_a4_required_pace_applicable_false_for_active_creator_goals(client):
    ov = get_json(client, f"{API}/overview", month="2026-10", cutoff="2026-10-15")
    seen_false = seen_true = 0
    for b in ov["brands"]:
        for g in b["goals"]:
            assert "required_pace_applicable" in g and "required_pace_reason" in g, g["goal_id"]
            if str(g["goal_id"]).split(":")[0] == "active_creators":
                assert g["required_pace_applicable"] is False, f"{b['brand_id']}: distinct counts have no daily pace"
                seen_false += 1
            elif g["required_pace_applicable"]:
                seen_true += 1
                if g["required_pace"]["value"] is None:
                    assert g["required_pace_reason"], "applicable but empty needs a plain reason"
    assert seen_false == 5 and seen_true >= 5


def test_a4_brand_pace_counts_total_equals_brands_and_labels_are_plain(client):
    k = get_json(client, f"{API}/portfolio/kpis")
    c = k["brand_pace_counts"]
    assert c["total"] == 5 == len(k["brand_pace"])
    assert c["on_track"] + c["behind"] + c["unknown"] == c["total"], c
    assert {b["brand_slug"] for b in k["brand_pace"]} == set(BRANDS)
    for b in k["brand_pace"]:
        assert b["brand_name"] and b["status_label"] and "data_note" in b, b
        assert violations(b["status_label"]) == []
        assert b["goals"], f"{b['brand_slug']} has no goals listed"
        for g in b["goals"]:
            for f in ("goal_name", "status_label", "actual_label", "target_label"):
                assert isinstance(g.get(f), str) and g[f].strip(), f"{b['brand_slug']}: goal has no plain {f}"
            assert "incomplete_reason" in g


# ------------------------------------------------------------------ diagnostics sides
def side(x):
    return x if isinstance(x, dict) and "value" in x else {"value": x, "unavailable_reason": None}


@pytest.mark.parametrize("brand", BRANDS)
def test_a4_diagnostics_sides_have_own_reasons_and_no_empty_rows(client, brand):
    d = get_json(client, f"{API}/brands/{brand}/diagnostics", month="2026-10", cutoff="2026-10-15")
    rows = [("total", d["total"])] + [(f"factor {f.get('key')}", f) for f in d["factors"]]
    reasons = []
    for name, row in rows:
        base, cur = side(row["baseline"]), side(row["current"])
        assert not (base["value"] is None and cur["value"] is None) or name == "total", \
            f"{brand}/{name}: a row with both sides empty must be left out"
        for label, sd in (("baseline", base), ("current", cur)):
            if sd["value"] is None:
                assert sd["unavailable_reason"], f"{brand}/{name}.{label}: an empty side needs its own plain reason"
                reasons.append((name, label, sd["unavailable_reason"]))
    if len({r for _, _, r in reasons}) == 1 and len(reasons) > 2:
        pytest.fail(f"{brand}: one blanket reason repeated for every side: {reasons[0][2]!r}")
    for p in d.get("products", []):
        assert not (side(p.get("gmv_baseline"))["value"] is None and side(p.get("gmv_current"))["value"] is None), p
    assert isinstance(d.get("notes", []), list)
    for n in d.get("notes", []):
        assert violations(n if isinstance(n, str) else n.get("text", "")) == []


def test_a4_golden_diagnostics_values_still_hold_with_side_objects(client):
    e = V2["s14"]
    d = get_json(client, f"{API}/brands/{e['brand_id']}/diagnostics", month=e["month"], cutoff=e["cutoff"])
    for k in ("baseline", "current", "delta"):
        assert dec(side(d["total"][k])["value"]) == dec(e["total"][k]), k
    for want, got in zip(e["factors"], d["factors"]):
        assert abs(dec(side(got["effect"])["value"]) - dec(want["effect"])) < dec("0.01"), got
