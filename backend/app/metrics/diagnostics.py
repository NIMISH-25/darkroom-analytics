"""Where-it-broke diagnostics: Shapley decomposition of linked GMV = A x V x G.

A = active creators, V = linked videos per active creator, G = attributed GMV per linked video.
Inputs come from gold.diagnostic_period (via the repo); arithmetic is exact (rational numbers, then
Decimal cents), so sum(effects) + change in unlinked older GMV == change in total to the cent.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction

from app.metrics.charts import _d, mv_status, prev_month, worst
from app.metrics.service import DEFINITION_VERSION, MetricService, money

CENT = Decimal("0.01")
DISCLAIMER = "This shows where the change came from. It does not prove the cause."
FACTORS = (("active_creators", "Active creators"), ("videos_per_creator", "Linked videos per active creator"),
           ("gmv_per_video", "Attributed GMV per linked video"))


def _frac(d: Decimal) -> Fraction:
    return Fraction(d)


def _cents(fr: Fraction) -> Decimal:
    with localcontext() as c:
        c.prec = 60
        return (Decimal(fr.numerator) / Decimal(fr.denominator)).quantize(CENT, rounding=ROUND_HALF_EVEN)


def _dec(fr: Fraction, places: str) -> str:
    with localcontext() as c:
        c.prec = 60
        return str((Decimal(fr.numerator) / Decimal(fr.denominator)).quantize(Decimal(places), rounding=ROUND_HALF_EVEN))


def _factors(a, linked_videos, linked_gmv):
    """(A, V, G) as Fractions, or None when undefined. G is 0 only when both videos and GMV are 0."""
    if a is None or linked_videos is None or linked_gmv is None or a == 0:
        return None
    a, lv, m = Fraction(a), Fraction(linked_videos), _frac(linked_gmv)
    if lv == 0:
        return None if m != 0 else (a, Fraction(0), Fraction(0))
    return a, lv / a, m / lv


def shapley(f0, f1):
    """Exact six-order averaged substitution. f0, f1 = (A, V, G) Fractions. Returns 3 effects (Fractions)."""
    (a0, v0, g0), (a1, v1, g1) = f0, f1
    ea = (a1 - a0) * ((v0 * g0 + v1 * g1) / 3 + (v0 * g1 + v1 * g0) / 6)
    ev = (v1 - v0) * ((a0 * g0 + a1 * g1) / 3 + (a0 * g1 + a1 * g0) / 6)
    eg = (g1 - g0) * ((a0 * v0 + a1 * v1) / 3 + (a0 * v1 + a1 * v0) / 6)
    return ea, ev, eg


def effects_cents(f0, f1, linked_delta: Decimal):
    """Effects rounded to cents; the cent residual goes to the largest effect so the sum is exact."""
    eff = [_cents(e) for e in shapley(f0, f1)]
    resid = linked_delta - sum(eff, Decimal(0))
    if resid:
        i = max(range(3), key=lambda k: (abs(eff[k]), -k))
        eff[i] += resid
    return eff


def _period(rows, period):
    rs = [r for r in rows if r["period"] == period]
    if not rs:
        return None
    r = next((x for x in rs if x.get("product_id") is None), rs[0])  # aggregate row has product_id NULL
    return {"a": _d(r.get("active_creators")), "videos": _d(r.get("videos")), "lv": _d(r.get("linked_videos")),
            "m": _d(r.get("linked_gmv")), "u": _d(r.get("unlinked_older_gmv")),
            "status": worst([mv_status(x.get("coverage_status") or "partial") for x in rs]),
            "products": {x["product_id"]: x for x in rs if x.get("product_id") is not None}}


def _md(v):
    return None if v is None else money(v)


def _side(value, reason=None):
    """{value, unavailable_reason}: exactly one of them is set (a real zero keeps its value)."""
    return {"value": value, "unavailable_reason": None if value is not None else (reason or "No data yet for this period.")}


def _span(p):
    from app.presentation.humanize import fmt_date
    return f"{fmt_date(p['from'])} to {fmt_date(p['to'])}"


def build_diagnostics(repo, brand_id: str, month: str, cutoff: str) -> dict:
    from app.presentation.humanize import names_for
    if brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise LookupError("unknown brand")
    rev, svc = repo.revision(), MetricService(repo)
    bname = names_for(repo, brand_id)["brand"] or "This brand"
    rows = repo.diag(brand_id)
    cur, base = _period(rows, "current"), _period(rows, "baseline")
    cut = date.fromisoformat(cutoff)
    pm = prev_month(month)
    periods = {"current": {"from": f"{month}-01", "to": cutoff},
               "baseline": {"from": f"{pm}-01", "to": f"{pm}-{min(cut.day, calendar.monthrange(int(pm[:4]), int(pm[5:]))[1]):02d}"}}
    notes: list[str] = []
    why = {}  # period -> plain reason it is not complete (None when complete)
    for name, p_ in (("current", cur), ("baseline", base)):
        span = _span(periods[name])
        if p_ is None:
            why[name] = f"{bname} has no data loaded for {span}."
        elif p_["status"] != "current":
            why[name] = f"{bname}'s data for {span} is incomplete."
        else:
            why[name] = None
    empty = {k: None for k in ("a", "videos", "lv", "m", "u")} | {"status": "unavailable", "products": {}}
    cur, base = cur or dict(empty), base or dict(empty)
    for w in why.values():
        if w:
            notes.append(w)
    src_status, src_reason, _ = svc.status_for(["orders", "affiliate_orders", "videos_weekly"], brand_id)
    status = worst([cur["status"], base["status"], src_status])
    if src_status != "current" and src_reason and src_reason not in notes:
        notes.append(src_reason)

    def total(p):
        return None if p["m"] is None or p["u"] is None else p["m"] + p["u"]
    t0, t1 = total(base), total(cur)
    t_delta = None if t0 is None or t1 is None else t1 - t0
    u_delta = None if base["u"] is None or cur["u"] is None else cur["u"] - base["u"]
    f0, f1 = _factors(base["a"], base["lv"], base["m"]), _factors(cur["a"], cur["lv"], cur["m"])
    eff = [None, None, None]
    effect_reason = None
    if f0 and f1 and t_delta is not None:
        eff = [str(e) for e in effects_cents(f0, f1, cur["m"] - base["m"])]
    else:
        if why["baseline"] or why["current"]:
            effect_reason = "The split needs complete data for both periods."
        elif base["a"] == 0 or cur["a"] == 0:
            effect_reason = f"{bname} had no active creators in one of the periods, so the split cannot be worked out."
        else:
            effect_reason = "A figure needed for the split is missing for one of the periods."
        notes.append(effect_reason)
        if status == "current":
            status = "partial"

    def side_reason(period_key, what):
        return why[period_key] or f"{what} cannot be worked out for {_span(periods[period_key])}."
    places = {"active_creators": "0.01", "videos_per_creator": "0.0001", "gmv_per_video": "0.01"}
    labels = {"active_creators": "Active creators", "videos_per_creator": "Videos per active creator",
              "gmv_per_video": "Sales per video with a link to a creator"}
    factors = []
    for i, (key, _l) in enumerate(FACTORS):
        row = {"key": key, "label": labels[key],
               "baseline": _side(None if not f0 else _dec(f0[i], places[key]), side_reason("baseline", labels[key])),
               "current": _side(None if not f1 else _dec(f1[i], places[key]), side_reason("current", labels[key])),
               "effect": _side(eff[i], effect_reason)}
        if row["baseline"]["value"] is None and row["current"]["value"] is None:
            continue  # both sides empty: no placeholder row
        factors.append(row)
    products = []
    for pid in sorted(set(base["products"]) | set(cur["products"])):
        b, c = base["products"].get(pid), cur["products"].get(pid)
        # a missing product row is a real zero only when that period's coverage is complete
        g0 = _d(b["product_gmv"]) if b else (Decimal(0) if base["status"] == "current" else None)
        g1 = _d(c["product_gmv"]) if c else (Decimal(0) if cur["status"] == "current" else None)
        if g0 is None and g1 is None:
            continue
        delta = None if g0 is None or g1 is None else g1 - g0
        name = (c or b).get("product_name") or (c or b).get("name") or "Unnamed product"
        obs = ("Sales are not known for one of the periods." if delta is None else
               f"Sales {'rose' if delta > 0 else 'fell' if delta < 0 else 'were flat'}" +
               ("" if delta == 0 else f" by {money(abs(delta))}") + f" ({money(g0)} to {money(g1)}).")
        products.append({"product_id": pid, "name": name,
                         "label": name, "gmv_baseline": _side(_md(g0), side_reason("baseline", "Product sales")),
                         "gmv_current": _side(_md(g1), side_reason("current", "Product sales")),
                         "delta": _side(_md(delta), "Sales are not known for one of the periods."), "observation": obs})
    products.sort(key=lambda p: ((1, Decimal(0)) if p["delta"]["value"] is None else (0, -abs(Decimal(p["delta"]["value"]))), p["product_id"]))
    notes.append("Sales from older videos are shown on their own line because they cannot be tied to videos from this month.")
    return {
        "data_revision": rev, "definition_version": DEFINITION_VERSION, "brand_id": brand_id, "brand_name": bname,
        "month": month, "cutoff": cutoff, "periods": periods,
        "method": "The change is split fairly between three drivers: how many creators posted, how many videos each posted, and how much each video sold.",
        "status": status, "status_reason": " ".join(dict.fromkeys(n for n in notes if n[:5] != "Sales")) or None,
        "disclaimer": DISCLAIMER, "notes": list(dict.fromkeys(notes)),
        "total": {"label": "Total sales from linked videos", "baseline": _side(_md(t0), why["baseline"] or "Total sales are not known for the earlier period."),
                  "current": _side(_md(t1), why["current"] or "Total sales are not known for this period."),
                  "delta": _side(_md(t_delta), "The change needs complete data for both periods.")},
        "factors": factors,
        "unlinked_older_gmv": {"label": "Sales from older or unlinked videos", "baseline": _side(_md(base["u"]), side_reason("baseline", "Sales from older videos")),
                               "current": _side(_md(cur["u"]), side_reason("current", "Sales from older videos")),
                               "delta": _side(_md(u_delta), "The change needs complete data for both periods.")},
        "products": products,
    }
