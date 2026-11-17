"""Metric layer. A metric's value and its evidence are derived from the SAME fetched rows
with the SAME filters, so they cannot disagree (test-plan S9)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

DEFAULT_MONTH = "2026-10"
DEFAULT_CUTOFF = "2026-10-15"
DEFINITION_VERSION = "v1"
DEFAULT_LIMIT = 100
SEVERITY = ["current", "suspect", "stale", "incomplete", "missing"]  # best -> worst
STATE_TO_STATUS = {
    "current": "current", "suspect": "partial", "stale": "stale",
    "incomplete": "partial", "missing": "unavailable",
}
SOURCES = {
    "gmv": ["orders"],
    "creator_attributed_gmv": ["orders", "affiliate_orders"],
    "net_attributed_sales": ["orders", "affiliate_orders", "returns"],
    "creator_net_sales": ["orders", "affiliate_orders", "returns"],
    "videos": ["videos_weekly"],
    "creator_videos": ["videos_weekly"],
    "active_creators": ["videos_weekly"],
    "sample_conversion_rate": ["samples", "videos_weekly"],
    "creator_sales_after_costs": ["orders", "affiliate_orders", "returns", "roster", "samples"],
}
META = {  # key -> (label, definition, unit, kind, formula)
    "gmv": ("GMV (shop, eligible)", "Sum of paid_amount of eligible paid, non-sample, non-cancelled order items in the month (brand local date).", "USD", "sum", "sum(paid_amount) over eligible lines"),
    "creator_attributed_gmv": ("Creator-attributed GMV", "Eligible GMV on lines attributed to a resolved creator.", "USD", "sum", "sum(paid_amount) over eligible lines with resolved creator"),
    "net_attributed_sales": ("Net attributed sales", "Creator-attributed GMV minus completed merchandise refunds of those items (cohort month, refunds completed by the cutoff).", "USD", "sum", "sum(paid_amount - refunded) over eligible resolved lines"),
    "creator_net_sales": ("Creator net sales", "Net attributed sales for one creator.", "USD", "sum", "sum(paid_amount - refunded) over the creator's eligible resolved lines"),
    "videos": ("Videos", "Distinct qualifying videos published in the month (brand local date).", "count", "distinct_count", "count(distinct video_id) where qualifies"),
    "creator_videos": ("Creator videos", "Distinct qualifying videos by one creator in the month.", "count", "distinct_count", "count(distinct video_id) where qualifies and creator"),
    "active_creators": ("Active creators", "Distinct creators with at least one qualifying (non-LIVE) video in the month.", "count", "distinct_count", "count(distinct creator_id) where qualifies"),
    "sample_conversion_rate": ("Sample conversion rate", "Mature delivered sample items (>=30 days) that matched a same-brand/creator/product video within 30x24h of delivery.", "ratio", "ratio", "matched / (matched + no_video) over mature, observable items"),
    "creator_sales_after_costs": ("Creator sales after costs", "Net sales minus retainer (prorated, allocated), commission and sample costs; unknown if any required cost is unknown.", "USD", "sum", "net_sales - retainer - commission - sample_cost"),
    "goal_projection": ("Goal projection", "Month-end projection for a goal versus its target.", "count", "forecast", "actual / elapsed complete days * days in month"),
}


@dataclass(frozen=True)
class Filters:
    brand_id: str | None = None
    creator_id: str | None = None
    month: str = DEFAULT_MONTH
    cutoff: str = DEFAULT_CUTOFF
    goal_id: str | None = None


def jsonable(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def _d(v):
    return None if v is None else Decimal(str(v))


def money(d) -> str:
    d = Decimal(str(d))
    return str(d if d.as_tuple().exponent <= -2 else d.quantize(Decimal("0.01")))


def _s(v):
    return None if v is None else str(v)


def as_of_for(cutoff: str) -> str:
    d = date.fromisoformat(cutoff)
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=ZoneInfo("America/Los_Angeles")).isoformat()


def evidence_url(key: str, f: Filters, revision: int, **extra) -> str:
    q = {"brand_id": f.brand_id, "creator_id": f.creator_id, "month": f.month, "cutoff": f.cutoff,
         "goal_id": f.goal_id, "revision": revision}
    q.update(extra)
    return f"/api/v1/metrics/{key}/evidence?" + urlencode({k: v for k, v in q.items() if v is not None})


def exclusion_items(excl: dict) -> list[dict]:
    """Exclusion list; non-USD lines carry their original currency and amount, labelled (never converted)."""
    out = []
    for e in excl.values():
        amt = str(e["_a"]) if e["_ok"] else None
        item = {"reason": e["reason"], "count": e["count"], "amount": amt}
        if e.get("currency"):
            item["currency"] = e["currency"]
            item["amount_label"] = None if amt is None else f"{e['currency']} {amt} in original currency, not converted to USD"
        out.append(item)
    return out


def _amount(r: dict, net: bool):
    if r.get("gmv") is None or (net and r.get("refunded") is None):
        return None
    return r["gmv"] - r["refunded"] if net else r["gmv"]


def sales_after_costs(net, perf) -> str | None:
    """net (cutoff-aware) minus known costs; None if any required cost or net is unknown."""
    parts = [net, perf.get("retainer_cost"), perf.get("commission_cost"), perf.get("sample_cost")]
    if any(x is None for x in parts):
        return None
    n, *c = (Decimal(str(x)) for x in parts)
    return money(n - sum(c, Decimal(0)))


def goal_id(g: dict) -> str:
    return f"{g['metric_key']}:{g['scope']}"


def actual_key(g: dict) -> str:
    if g["metric_key"] == "gmv":
        if g["scope"] == "shop":
            return "gmv"
        return "net_attributed_sales" if g.get("basis") == "net" else "creator_attributed_gmv"
    return g["metric_key"]  # videos, active_creators


def mv_dict(key, value, unit, f: Filters, status, reason, coverage, revision, **extra) -> dict:
    if status != "current" and not reason:
        reason = "source coverage is " + status
    return {
        "metric_key": key, "value": value, "unit": unit, "as_of": as_of_for(f.cutoff),
        "coverage_through": _s(coverage), "status": status, "status_reason": reason,
        "evidence_url": evidence_url(key, f, revision, **extra),
    }


SAMPLE_COUNTS = {
    "sent": ("sent", lambda r: True),
    "delivered": ("delivered", lambda r: r.get("delivered_date") is not None),
    "matched": ("matched", lambda r: r["state"] == "matched"),
    "pending": ("pending or in transit", lambda r: r["state"] in ("pending", "in_transit")),
    "no_video": ("without a video", lambda r: r["state"] == "no_video"),
    "unknown": ("unknown", lambda r: r["state"] == "unknown"),
}


class MetricService:
    def __init__(self, repo):
        self.repo = repo

    # ---------- status ----------
    def status_for(self, key_or_sources, brand_id: str | None):
        sources = SOURCES[key_or_sources] if isinstance(key_or_sources, str) else key_or_sources
        fresh = self.repo.freshness(brand_id)
        worst, cov, reason = "current", None, None
        brands = {brand_id} if brand_id else {r["brand_id"] for r in fresh}
        for b in brands:
            for s in sources:
                row = next((r for r in fresh if r["brand_id"] == b and r["source_type"] == s), None)
                state = row["state"] if row else "missing"
                if SEVERITY.index(state) > SEVERITY.index(worst):
                    worst, reason = state, (row or {}).get("message") or f"{s} is {state} for {b}"
                if row and row.get("coverage_through") is not None:
                    c = str(row["coverage_through"])
                    cov = c if cov is None or c < cov else cov
        if not brands:
            worst, reason = "missing", "no source coverage recorded"
        return STATE_TO_STATUS[worst], reason, cov

    # ---------- core: rows -> result ----------
    def compute(self, key: str, f: Filters) -> dict:
        memo = self.__dict__.setdefault("_cc", {})
        if (key, f) not in memo:
            memo[(key, f)] = self._compute(key, f)
        return memo[(key, f)]

    def _perf(self, f: Filters):
        cm = getattr(self.repo, "creator_map", None)
        if cm is not None:
            return cm(f.brand_id, f.month).get(f.creator_id)
        return next((c for c in self.repo.creators(f.brand_id, f.month) if c["creator_id"] == f.creator_id), None)

    def _compute(self, key: str, f: Filters) -> dict:
        label, definition, unit, kind, formula = META[key]
        records, included, inputs = [], [], []
        excl: dict[str, dict] = {}
        warnings: list[str] = []
        value = None
        status, reason, cov = self.status_for(key, f.brand_id)

        def exclude(why, amt=None, currency=None):
            k = why if currency is None else why + ":" + str(currency)
            e = excl.setdefault(k, {"reason": why, "count": 0, "_a": Decimal(0), "_ok": True, "currency": currency})
            e["count"] += 1
            if amt is None:
                e["_ok"] = False
            else:
                e["_a"] += _d(amt)

        if key in ("gmv", "creator_attributed_gmv", "net_attributed_sales", "creator_net_sales"):
            rows = self.repo.sales_rows(f.brand_id, f.creator_id, f.month, f.cutoff)
            need_resolved = key != "gmv"
            net_key = key in ("net_attributed_sales", "creator_net_sales")
            for r in rows:
                r = dict(r)
                orig_amount = r.pop("paid_amount", None)
                r["amount"] = _amount(r, net_key)
                non_usd = (not r["eligible"]) and r.get("exclusion_reason") == "non_usd_currency"
                if not r["eligible"]:
                    why = "non_usd_currency" if non_usd else "not_eligible"
                elif need_resolved and r["bucket"] != "resolved":
                    why = "no_creator_attribution" if r["bucket"] == "none" else "creator_" + str(r["bucket"])
                else:
                    why = None
                if why == "non_usd_currency":
                    exclude(why, orig_amount, r.get("currency"))  # original currency amount, labelled
                elif why:
                    exclude(why, r.get("gmv"))
                records.append((r, why is None))
                if why is None:
                    included.append(r)
            net = key in ("net_attributed_sales", "creator_net_sales")
            col_missing = sum(1 for r in included if r.get("gmv") is None or (net and r.get("refunded") is None))
            gmv_sum = sum((_d(r["gmv"]) for r in included if r.get("gmv") is not None), Decimal(0))
            ref_sum = sum((_d(r["refunded"]) for r in included if r.get("refunded") is not None), Decimal(0))
            inputs = [{"label": "Included lines", "value": len(included), "unit": "count"},
                      {"label": "Gross GMV", "value": money(gmv_sum), "unit": "USD"}]
            if net:
                inputs.append({"label": "Completed refunds", "value": money(ref_sum), "unit": "USD"})
            if col_missing:
                warnings.append(f"{col_missing} line(s) have an unknown amount; value is unknown.")
                if status != "unavailable":
                    status = "partial"
                reason = reason or "unsplit or unknown amounts in included lines"
            else:
                value = money(gmv_sum - ref_sum) if net else money(gmv_sum)
        elif key in ("videos", "creator_videos", "active_creators"):
            rows = self.repo.video_rows(f.brand_id, f.creator_id if key == "creator_videos" else None, f.month, f.cutoff)
            seen = set()
            for r in rows:
                ok = bool(r["qualifies"])
                if not ok:
                    exclude("not_qualifying")
                records.append((r, ok))
                if ok:
                    included.append(r)
                    seen.add(r["creator_id"] if key == "active_creators" else (r["brand_id"], r["video_id"]))
            value = len(seen)
            inputs = [{"label": "Qualifying rows", "value": len(included), "unit": "count"}]
        elif key == "sample_conversion_rate":
            rows = self.repo.sample_rows(f.brand_id, f.creator_id)
            for r in rows:
                ok = bool(r.get("mature")) and r["state"] in ("matched", "no_video")
                if not ok:
                    exclude("immature_or_unobservable:" + str(r["state"]))
                records.append((r, ok))
                if ok:
                    included.append(r)
            matched = sum(1 for r in included if r["state"] == "matched")
            inputs = [{"label": "Matched", "value": matched, "unit": "count"},
                      {"label": "Mature observable", "value": len(included), "unit": "count"}]
            incomplete = any(r.get("video_coverage_complete") is False for r in rows)
            if incomplete:
                if status != "unavailable":
                    status = "partial"
                reason = "video coverage is incomplete, so no-video outcomes and the conversion rate are unknown"
                warnings.append(reason)
            elif included:
                value = str((Decimal(matched) / Decimal(len(included))).quantize(Decimal("0.0001")))
            elif status != "unavailable":
                reason = reason or "no mature observable sample items yet"
        elif key == "creator_sales_after_costs":
            net_res = self.compute("creator_net_sales", f)
            perf = self._perf(f)
            records = list(net_res["_records"])
            excl = net_res["_excl"]
            costs = {}
            if perf is None:
                warnings.append("creator not found in creator_performance")
            else:
                costs = {"Retainer cost": perf.get("retainer_cost"), "Commission cost": perf.get("commission_cost"),
                         "Sample cost": perf.get("sample_cost")}
            inputs = [{"label": "Net sales", "value": net_res["value"], "unit": "USD"}] + [
                {"label": k, "value": _s(v), "unit": "USD"} for k, v in costs.items()]
            # Cost components become signed evidence records so that sum(amount) == result.
            comp = [({"component": k, "amount": None if v is None else -Decimal(str(v)),
                      "source_file": "gold.creator_performance", "source_locator": k.lower()}, True)
                    for k, v in costs.items()]
            records = comp + records
            unknown = [k for k, v in costs.items() if v is None]
            if perf and net_res["value"] is not None:
                value = sales_after_costs(net_res["value"], perf)
                if value is None:
                    warnings.append("Unknown cost component(s): " + ", ".join(unknown) + "; sales after costs is unknown.")
                    reason = reason or ("unknown cost: " + ", ".join(unknown))
            warnings += net_res["warnings"]
            if status == "current" and net_res["status"] != "current":
                status, reason = net_res["status"], net_res["reason"]
        else:
            raise KeyError(key)

        out = self._finish(dict(key=key, label=label, definition=definition, unit=unit, kind=kind, formula=formula,
                                value=value, status=status, reason=reason, coverage=cov, inputs=inputs,
                                warnings=warnings, _records=records, _excl=excl))
        return out

    def _finish(self, d: dict) -> dict:
        """Common null/zero/reason rules for every computed result."""
        value, status, reason, unit = d["value"], d["status"], d["reason"], d["unit"]
        # A zero is a verified zero only with full source coverage; otherwise it is unknown.
        if d["kind"] in ("sum", "distinct_count") and value is not None and Decimal(str(value)) == 0 \
                and status != "current":
            value = None
            reason = reason or "zero cannot be verified while source coverage is " + status
        if status == "unavailable":
            value = None
        if value is None and not reason:
            reason = "value unknown"
        if status != "current" and not reason:
            reason = "source coverage is " + status
        if status == "current" and value is not None:
            reason = None
        excl = d["_excl"]
        d = dict(d, value=value, reason=reason)
        d["exclusions"] = exclusion_items(excl)
        return d

    def mv(self, key: str, f: Filters, revision: int, result: dict | None = None, part: str | None = None) -> dict:
        r = result or self.compute_part(key, part, f)
        extra = {"part": part} if part else {}
        return mv_dict(key, r["value"], r["unit"], f, r["status"], r["reason"], r["coverage"], revision, **extra)

    # ---------- component parts of a metric (own value, own evidence) ----------
    PARTS = {
        ("creator_net_sales", "refunds"): ("Creator refunds", "Completed merchandise refunds (by the cutoff) on the creator's eligible resolved lines.", ["orders", "affiliate_orders", "returns"]),
        ("creator_attributed_gmv", "unresolved"): ("Unresolved GMV", "Eligible creator-attributed GMV whose video is not in the video data.", ["orders", "affiliate_orders", "videos_weekly"]),
        ("creator_sales_after_costs", "retainer_cost"): ("Retainer cost", "Retainer prorated by effective days and allocation share.", ["roster"]),
        ("creator_sales_after_costs", "commission_cost"): ("Commission cost", "Sum of commissions on the creator's eligible resolved lines.", ["orders", "affiliate_orders"]),
        ("creator_sales_after_costs", "sample_cost"): ("Sample cost", "Sample item cost plus shipping for the creator's shipments; unknown if any is unknown.", ["samples"]),
    }

    def _sample_count(self, part: str, f: Filters) -> dict:
        label, pred = SAMPLE_COUNTS[part]
        sources = ["samples"] if part in ("sent", "delivered") else ["samples", "videos_weekly"]
        status, reason, cov = self.status_for(sources, f.brand_id)
        rows = self.repo.sample_rows(f.brand_id, f.creator_id)
        records = [(dict(r), bool(pred(r))) for r in rows]
        value = sum(1 for _, inc in records if inc)
        # no-video outcomes cannot be told apart from "not published yet" while video coverage has gaps
        if part == "no_video" and any(r.get("video_coverage_complete") is False for r in rows):
            value = None
            if status != "unavailable":
                status = "partial"
            reason = "video coverage is incomplete; a missing video cannot be told apart from an unpublished one"
        return self._finish(dict(
            key="sample_conversion_rate", label="Samples: " + label, unit="count", kind="distinct_count",
            definition="Number of sample items that are " + label + ".", formula="count(sample items) where " + label,
            value=value, status=status, reason=reason, coverage=cov,
            inputs=[{"label": "Sample items", "value": len(rows), "unit": "count"}],
            warnings=[], _records=records, _excl={}))

    def compute_part(self, key: str, part: str | None, f: Filters) -> dict:
        if not part:
            return self.compute(key, f)
        if key == "sample_conversion_rate" and part in SAMPLE_COUNTS:
            return self._sample_count(part, f)
        if (key, part) not in self.PARTS:
            raise KeyError((key, part))
        label, definition, sources = self.PARTS[(key, part)]
        status, reason, cov = self.status_for(sources, f.brand_id)
        warnings: list[str] = []
        records: list = []
        excl: dict = {}
        inputs: list = []
        formula = definition
        if part in ("refunds", "unresolved"):
            base = self.compute(key, f)
            for rec, inc in base["_records"]:
                rec = dict(rec)
                if part == "refunds":
                    rec["amount"] = rec.get("refunded")
                    use = inc
                else:
                    use = inc and not rec.get("video_known")
                    rec["amount"] = rec.get("gmv")
                    if inc and not use:
                        e = excl.setdefault("video_known", {"reason": "video_known", "count": 0, "_a": Decimal(0), "_ok": True})
                        e["count"] += 1
                        if rec.get("gmv") is None:
                            e["_ok"] = False  # unknown amount stays unknown (null), never zero
                        else:
                            e["_a"] += _d(rec["gmv"])
                records.append((rec, use))
            if part == "refunds":
                excl = base["_excl"]
            used = [r for r, u in records if u]
            vals = [r["amount"] for r in used]
            value = None if any(v is None for v in vals) else money(sum((_d(v) for v in vals), Decimal(0)))
            if value is None:
                warnings.append("some included lines have an unknown amount; value is unknown.")
                if status != "unavailable":
                    status = "partial"
                reason = reason or "amount unknown on some lines"
            if base["status"] != "current" and status == "current":
                status, reason = base["status"], base["reason"]
            inputs = [{"label": "Included lines", "value": len(used), "unit": "count"}]
            formula = "sum(refunded)" if part == "refunds" else "sum(paid_amount) where creator resolved and video unknown"
            warnings += base["warnings"] if part == "refunds" else []
        else:  # cost parts come straight from gold.creator_performance (costs have no per-row source in the views)
            perf = self._perf(f)
            v = None if perf is None else perf.get(part)
            value = None if v is None else money(v)
            inputs = [{"label": label, "value": value, "unit": "USD"}]
            if value is None:
                reason = reason or label + " is unknown (allocation, contract or amount missing)"
                warnings.append(label + " is unknown; sales after costs is unknown.")
        return self._finish(dict(key=key, label=label, definition=definition, unit="USD", kind="sum", formula=formula,
                                 value=value, status=status, reason=reason, coverage=cov, inputs=inputs,
                                 warnings=warnings, _records=records, _excl=excl))

    # ---------- evidence ----------
    def evidence(self, key: str, f: Filters, part: str | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
        self._page = (limit, offset)
        if key == "goal_projection":
            return self._goal_evidence(f, part or "projection")
        if key not in META:
            raise KeyError(key)
        r = self.compute_part(key, part, f)
        if part:
            r = dict(r, label=r["label"])
        return self._evidence_dict(r, f, self.repo.revision(), url_extra={"part": part} if part else None)

    def _evidence_dict(self, r, f, revision, kind=None, formula=None, extra_inputs=None, url_extra=None):
        recs = r["_records"]
        limit, offset = getattr(self, "_page", (DEFAULT_LIMIT, 0))
        cols = sorted({k for rec, _ in recs for k in rec if k not in ("source_file", "source_locator")})
        # stable provenance order: (source_file, row_num); synthetic component rows have no row_num
        ordered = sorted(recs, key=lambda x: (str(x[0].get("source_file") or ""), (x[0].get("row_num") is None, x[0].get("row_num") if x[0].get("row_num") is not None else 0),
                                              str(x[0].get("source_locator") or "")))
        total = len(ordered)
        out = [{"source_file": rec.get("source_file"), "source_locator": rec.get("source_locator"),
                "included": inc, "values": jsonable({c: rec.get(c) for c in cols})}
               for rec, inc in ordered[offset:offset + limit]]
        next_off = offset + limit if offset + limit < total else None
        d = date.fromisoformat(f.month + "-01")
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        return {
            "label": r["label"], "definition": r["definition"], "definition_version": DEFINITION_VERSION,
            "period_start": d.isoformat(),
            "period_end": min(date.fromisoformat(f.cutoff), nxt - timedelta(days=1)).isoformat(),
            "timezone": "America/Los_Angeles",
            "result": mv_dict(r["key"], r["value"], r["unit"], f, r["status"], r["reason"], r["coverage"], revision,
                              **(url_extra or {})),
            "calculation": {"kind": kind or r["kind"], "formula": formula or r["formula"],
                            "inputs": (extra_inputs or []) + r["inputs"]},
            "exclusions": r["exclusions"], "warnings": r["warnings"], "columns": cols,
            "records": out, "records_truncated": next_off is not None,
            "total_count": total, "limit": limit, "offset": offset, "next_offset": next_off,
            "explainer": build_explainer(r["key"], (url_extra or {}).get("part"), r["label"], r["definition"],
                                         formula or r["formula"], (extra_inputs or []) + r["inputs"], r["exclusions"],
                                         sum(1 for _, i in recs if i), total, r["warnings"]),
        }

    def find_goal(self, f: Filters):
        for g in self.repo.goals(f.brand_id, f.month):
            if goal_id(g) == f.goal_id:
                return g
        return None

    def _goal_evidence(self, f: Filters, part: str = "projection") -> dict:
        row = self.find_goal(f)
        if row is None:
            raise KeyError("goal")
        rev = self.repo.revision()
        r = self.compute(actual_key(row), replace(f, creator_id=None))
        unit = "USD" if row["metric_key"] == "gmv" else "count"
        pace_unit = "USD_per_day" if unit == "USD" else "count_per_day"
        target = _s(row.get("target_value"))
        if part == "target":
            value, status, reason, cov, u = target, "current", None, None, unit
            if value is None:
                status, reason = "unavailable", "no target in plan"
        elif part == "progress":
            value, status, reason = progress_ratio(r["value"], row.get("target_value"), r["status"], r["reason"])
            cov, u = r["coverage"], "ratio"
        elif part == "required_pace":
            gs = goal_state(row, r)
            value, status, reason, cov, u = (gs["required_pace"], gs["status"], gs["reason"],
                                             _s(row.get("coverage_through")), pace_unit)
        else:
            part = "projection"
            gs = goal_state(row, r)
            value, status, reason, cov, u = (gs["projection"], gs["status"], gs["reason"],
                                             _s(row.get("coverage_through")) or r["coverage"], unit)
        if value is None and not reason:
            reason = "unavailable (coverage gaps or insufficient history)"
        r2 = dict(r)
        r2.update(key="goal_projection", label=row.get("label") or META["goal_projection"][0],
                  definition=row.get("definition") or META["goal_projection"][1], unit=u, kind="forecast",
                  value=value, status=status, reason=reason, coverage=cov)
        extra = [{"label": "Actual", "value": r["value"], "unit": unit},
                 {"label": "Target", "value": target, "unit": unit},
                 {"label": "Projection", "value": goal_state(row, r)["projection"], "unit": unit},
                 {"label": "Required pace", "value": goal_state(row, r)["required_pace"], "unit": pace_unit}]
        out = self._evidence_dict(r2, f, rev, kind="goal", formula=META["goal_projection"][4], extra_inputs=extra,
                                  url_extra={"part": part})
        if part == "target":
            vals = {"metric_key": row["metric_key"], "scope": row["scope"], "basis": row.get("basis"),
                    "target_value": target}
            out["records"] = [{"source_file": row.get("plan_file"),
                               "source_locator": "goal plan row " + str(row.get("row_num")),
                               "included": True, "values": vals}]
            out["columns"] = sorted(vals)
            out["records_truncated"] = False
            out["calculation"]["formula"] = "target_value from the goal plan"
            out["exclusions"] = []
        if row.get("reasoning"):
            out["warnings"] = out["warnings"] + [str(row["reasoning"])]
        return out


# ---------------------------------------------------------------------------
# Goal projection state: never show a projection built on an unknown or stale actual.
# ---------------------------------------------------------------------------
def goal_state(g: dict, actual: dict) -> dict:
    """Return projection / required_pace values with their status for one goal row."""
    pstatus = g.get("status") or actual["status"]
    reason = g.get("status_reason")
    proj, pace = g.get("projection"), g.get("required_pace")
    block = None
    if actual["value"] is None:
        block = actual["status"] if actual["status"] != "current" else "unavailable"
        why = "actual is unknown (" + (actual["reason"] or "source coverage is " + actual["status"]) + ")"
    elif actual["status"] in ("stale", "unavailable"):
        block = actual["status"]
        why = "source is " + actual["status"] + ": " + (actual["reason"] or "coverage is behind")
    elif pstatus in ("unavailable", "stale"):
        block, why = pstatus, reason or "source coverage is " + pstatus
    if block:
        proj = pace = None
        pstatus = block
        reason = why
    if proj is None and not reason:
        reason = "projection unavailable (coverage gaps or insufficient history)"
    pace_status = g.get("pace_status") or "unknown"
    if block or proj is None:
        pace_status = "unknown"
    if proj is None and pstatus == "current":
        pstatus = "unavailable"
    return {"projection": None if proj is None else str(proj), "required_pace": None if pace is None else str(pace),
            "status": pstatus, "reason": reason, "pace_status": pace_status}


# ---------------------------------------------------------------------------
# Creator decision support
# ---------------------------------------------------------------------------
NUDGE_QUIET_DAYS = 10
UPGRADE_NET_SALES = Decimal("1000.00")
REBOOK_SALES_AFTER_COSTS = Decimal("0.00")
ACTION_RULES = (
    "Rules in order, first match wins: review if net sales, sales after costs, videos or last-post date "
    "is unknown; nudge if retainer and %d or more days since the last post; upgrade if affiliate and net "
    "sales >= $%s; rebook if retainer and sales after costs < $%s; otherwise watch."
    % (NUDGE_QUIET_DAYS, UPGRADE_NET_SALES, REBOOK_SALES_AFTER_COSTS)
)


def suggested_action(item: dict, cutoff: str) -> dict:
    ctype = item.get("contract_type")
    net, sac, vids = item["net_sales"]["value"], item["sales_after_costs"]["value"], item["videos"]["value"]
    last = item.get("last_post_date")
    unknown = [n for n, v in (("net sales", net), ("sales after costs", sac), ("videos", vids)) if v is None]
    if ctype == "retainer" and last is None and item["videos"]["status"] != "current":
        unknown.append("last-post date")
    cut = date.fromisoformat(cutoff)
    quiet = None if last is None else (cut - date.fromisoformat(str(last))).days

    def out(action, rule, status="current", reason=None):
        return {"action": action, "rule": rule, "status": status, "status_reason": reason}

    if unknown:
        return out("review", "Review: " + ", ".join(unknown) + " unknown, so no recommendation is made. " + ACTION_RULES,
                   "partial", "unknown input(s): " + ", ".join(unknown))
    if ctype == "retainer" and (last is None or quiet >= NUDGE_QUIET_DAYS):
        d = "no post on record" if last is None else f"{quiet} days since the last post"
        return out("nudge", f"Nudge: retainer creator with {d} (threshold {NUDGE_QUIET_DAYS}+ days). " + ACTION_RULES)
    if ctype == "affiliate" and Decimal(str(net)) >= UPGRADE_NET_SALES:
        return out("upgrade", f"Upgrade: affiliate creator with net sales ${net} >= ${UPGRADE_NET_SALES}. " + ACTION_RULES)
    if ctype == "retainer" and Decimal(str(sac)) < REBOOK_SALES_AFTER_COSTS:
        return out("rebook", f"Rebook: retainer creator with sales after costs ${sac} < ${REBOOK_SALES_AFTER_COSTS}. " + ACTION_RULES)
    return out("watch", "Watch: no rule triggered. " + ACTION_RULES)


# ---------------------------------------------------------------------------
# Attention impact (USD exposure)
# ---------------------------------------------------------------------------
def _q(d):
    return str(Decimal(str(d)).quantize(Decimal("0.01")))


def attention_impact(r: dict, month: str, cutoff: str, repo) -> tuple[str | None, str]:
    """(impact_score as money string or None, impact_basis)."""
    d0 = date.fromisoformat(month + "-01")
    dim = ((date(d0.year + (d0.month == 12), d0.month % 12 + 1, 1)) - d0).days
    kind, bid = r["kind"], r["brand_id"]
    if kind == "quiet_retainer":
        perf = repo.creator_map(bid, month).get(r.get("creator_id")) if hasattr(repo, "creator_map") else None
        fee = None if perf is None else perf.get("retainer_cost")
        last = None if perf is None else perf.get("last_post_date")
        days = dim if last is None else max(0, (date.fromisoformat(cutoff) - date.fromisoformat(str(last))).days)
        basis = f"retainer fee x quiet-day share ({min(days, dim)}/{dim} days)"
        if fee is None:
            return None, basis + "; retainer fee unknown"
        return _q(Decimal(str(fee)) * min(days, dim) / dim), basis
    if kind == "sample_no_video":
        shipment = str(r["entity_ref"]).rsplit(":", 1)[0]
        cost = repo.sample_costs(bid).get((bid, shipment)) if hasattr(repo, "sample_costs") else None
        basis = "sample cost of the shipment (items + shipping)"
        if cost is None:
            return None, basis + "; cost unknown"
        return _q(cost), basis
    # missing_source: GMV target x blind-day share
    ps, pe = r.get("period_start"), r.get("period_end")
    blind = dim if ps is None or pe is None else max(0, (date.fromisoformat(str(pe)) - date.fromisoformat(str(ps))).days + 1)
    goals = [g for g in repo.goals(bid, month) if g["metric_key"] == "gmv" and g.get("target_value") is not None]
    basis = f"GMV target x blind-day share ({min(blind, dim)}/{dim} days)"
    if not goals:
        return None, basis + "; no GMV target"
    target = max(Decimal(str(g["target_value"])) for g in goals)
    return _q(target * min(blind, dim) / dim), basis


PROGRESS_CAP = Decimal("1.5")


def progress_ratio(actual, target, actual_status: str = "current", actual_reason: str | None = None):
    """actual / target capped at 1.5 -> (value|None, status, reason). Unknown or stale input -> null with status."""
    if target is None:
        return None, "unavailable", "no target in plan"
    if actual is None or actual_status in ("stale", "unavailable"):
        st = actual_status if actual_status != "current" else "unavailable"
        return None, st, "actual is unknown or stale" + (": " + actual_reason if actual_reason else "")
    t = Decimal(str(target))
    if t == 0:
        return None, "unavailable", "target is zero"
    r = min(Decimal(str(actual)) / t, PROGRESS_CAP).quantize(Decimal("0.0001"))
    return str(r), actual_status, actual_reason if actual_status != "current" else None


# ---------------------------------------------------------------------------
# Plain-English explainer for the evidence sheet (built from the registry, definition, exclusions, counts)
# ---------------------------------------------------------------------------
EXPLAIN = {
    "gmv": ("Total value of paid, non-sample orders for the brand in the period, whether or not a creator drove them.",
            "It is the top line the brand's monthly GMV goal is measured against."),
    "creator_attributed_gmv": ("Sales that can be traced to a known creator through the affiliate records.",
                               "It shows how much of the brand's revenue creators actually drive."),
    "net_attributed_sales": ("Creator-attributed sales after the money returned to customers is taken off.",
                             "It is the sales figure that creator pay and ROI should be judged on."),
    "creator_net_sales": ("What this creator's attributed sales are worth after refunds.",
                          "It is the revenue side of the creator's economics."),
    "videos": ("The number of distinct videos that count (a known creator and a publish time) published in the period.",
               "Output volume is the leading indicator for later sales."),
    "creator_videos": ("The number of qualifying videos this creator published in the period.",
                       "It shows whether the creator is delivering the content they were booked for."),
    "active_creators": ("How many different creators posted at least one qualifying video in the period.",
                        "It shows how wide the brand's creator bench is, beyond total video count."),
    "sample_conversion_rate": ("Of the free samples that had enough time to work, the share that turned into a video.",
                               "It shows whether sending product to creators pays back in content."),
    "creator_sales_after_costs": ("The creator's net sales minus what they cost: retainer, commission and samples.",
                                  "It tells you whether the relationship makes money, not just revenue."),
    "goal_projection": ("Where the month is heading if the pace so far continues, compared with the target.",
                        "It tells you early whether a goal will be missed so you can act."),
    "decomposition": ("A split of the change between two periods into more creators, more videos per creator and more sales per video.",
                      "It points to which lever moved the number; it describes the change, it does not prove the cause."),
    "creator_concentration": ("How much of the brand's creator sales come from its few biggest creators.",
                              "A high share means the brand depends on a handful of people."),
    "retainer_cadence": ("How many posts retainer creators delivered against what their contract expects.",
                         "It shows which retainers to chase or renegotiate."),
    "portfolio_pacing": ("The sum of every brand's goal, pace and projection for the month.",
                         "It shows whether the whole portfolio is on track, not just single brands."),
}
EXCL_TEXT = {
    "not_eligible": "{n} order line(s) left out because they were cancelled, unpaid or sample orders",
    "no_creator_attribution": "{n} order line(s) left out because no creator is attributed",
    "creator_creator_unresolved": "{n} order line(s) left out because the creator id could not be matched to the roster",
    "creator_unresolved": "{n} order line(s) left out because the creator id could not be matched to the roster",
    "creator_conflict": "{n} order line(s) left out because two creators claim them",
    "other_bucket": "{n} line(s) left out because they belong to another attribution bucket",
    "not_qualifying": "{n} video(s) left out because they have no known creator or publish time",
    "video_known": "{n} line(s) left out because their video is in the video data",
}


def _exclusion_sentences(exclusions) -> list[str]:
    out = []
    for e in exclusions or []:
        reason, n = e["reason"], e["count"]
        if reason == "non_usd_currency":
            out.append(f"{n} order(s) paid in {e.get('currency') or 'another currency'} were left out"
                       + (f" ({e['amount_label']})" if e.get("amount_label") else "") + "; no conversion is attempted")
        elif reason.startswith("immature_or_unobservable:"):
            state = reason.split(":", 1)[1].replace("_", " ")
            out.append(f"{n} sample(s) are {state} and cannot be judged yet")
        elif reason in EXCL_TEXT:
            out.append(EXCL_TEXT[reason].format(n=n))
        else:
            out.append(f"{n} row(s) left out ({reason.replace('_', ' ')})")
    return out


def build_explainer(key: str, part, label: str, definition: str, formula: str, inputs, exclusions,
                    n_included: int, n_total: int, warnings=None) -> dict:
    means, matters = EXPLAIN.get(key, (definition, "It supports a decision about the brand's creator programme."))
    if part and part != "projection":
        means = f"{label}. " + means
    sent = _exclusion_sentences(exclusions)
    if key in ("net_attributed_sales", "creator_net_sales", "creator_sales_after_costs") or part == "refunds":
        sent.append("refunds completed after the cutoff are not subtracted yet; a late refund restates the original month once it completes")
    calc = definition.rstrip(".") + ". Formula: " + formula + "."
    if inputs:
        calc += " Inputs: " + ", ".join(f"{i['label']} {i['value']}" for i in inputs[:6] if i.get("value") is not None) + "."
    if sent:
        calc += " Not counted: " + "; ".join(sent) + "."
    if n_total == 0:
        rows = "This number is derived and has no individual source rows; the inputs above show its parts."
    else:
        rows = (f"The {n_total} row(s) behind this number: {n_included} counted and {n_total - n_included} excluded "
                f"(marked included = false). Each row names its source file and row, so the original record can be opened and checked.")
    return {"what_it_means": means, "why_it_matters": matters, "how_calculated": calc, "what_rows_prove": rows}
