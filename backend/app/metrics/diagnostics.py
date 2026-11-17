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
DISCLAIMER = ("This is a decomposition with context, not proof of cause: it splits the change in GMV into "
              "creator count, videos per creator and GMV per video, and does not show why they changed.")
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


def build_diagnostics(repo, brand_id: str, month: str, cutoff: str) -> dict:
    if brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise LookupError("unknown brand")
    rev, svc = repo.revision(), MetricService(repo)
    rows = repo.diag(brand_id)
    cur, base = _period(rows, "current"), _period(rows, "baseline")
    cut = date.fromisoformat(cutoff)
    pm = prev_month(month)
    periods = {"current": {"from": f"{month}-01", "to": cutoff},
               "baseline": {"from": f"{pm}-01", "to": f"{pm}-{min(cut.day, calendar.monthrange(int(pm[:4]), int(pm[5:]))[1]):02d}"}}
    src_status, src_reason, _ = svc.status_for(["orders", "affiliate_orders", "videos_weekly"], brand_id)
    reasons = []
    if cur is None or base is None:
        status, reasons = "unavailable", ["no diagnostic period data"]
        cur = cur or {k: None for k in ("a", "videos", "lv", "m", "u")} | {"status": "unavailable", "products": {}}
        base = base or {k: None for k in ("a", "videos", "lv", "m", "u")} | {"status": "unavailable", "products": {}}
    else:
        status = worst([cur["status"], base["status"], src_status])
        if status != "current":
            reasons.append(src_reason or f"source coverage is {status}")

    def total(p):
        return None if p["m"] is None or p["u"] is None else p["m"] + p["u"]
    t0, t1 = total(base), total(cur)
    t_delta = None if t0 is None or t1 is None else t1 - t0
    u_delta = None if base["u"] is None or cur["u"] is None else cur["u"] - base["u"]
    f0, f1 = _factors(base["a"], base["lv"], base["m"]), _factors(cur["a"], cur["lv"], cur["m"])
    eff = [None, None, None]
    if f0 and f1 and t_delta is not None:
        linked_delta = cur["m"] - base["m"]
        eff = [str(e) for e in effects_cents(f0, f1, linked_delta)]
    else:
        reasons.append("effects are unknown: an input is missing or there were no active creators in a period")
        if status == "current":
            status = "partial"
    places = {"active_creators": "0.01", "videos_per_creator": "0.0001", "gmv_per_video": "0.01"}
    factors = []
    for i, (key, _label) in enumerate(FACTORS):
        factors.append({"key": key, "baseline": None if not f0 else _dec(f0[i], places[key]),
                        "current": None if not f1 else _dec(f1[i], places[key]), "effect": eff[i]})
    products = []
    for pid in sorted(set(base["products"]) | set(cur["products"])):
        b, c = base["products"].get(pid), cur["products"].get(pid)
        g0 = _d(b["product_gmv"]) if b else Decimal(0)
        g1 = _d(c["product_gmv"]) if c else Decimal(0)
        delta = None if g0 is None or g1 is None else g1 - g0
        name = (c or b).get("product_name") or (c or b).get("name") or pid
        obs = ("GMV unknown for one period" if delta is None else
               f"GMV {'rose' if delta > 0 else 'fell' if delta < 0 else 'was flat'}" +
               ("" if delta == 0 else f" by {money(abs(delta))}") + f" ({money(g0)} to {money(g1)})")
        products.append({"product_id": pid, "name": name, "gmv_baseline": _md(g0), "gmv_current": _md(g1),
                         "delta": _md(delta), "observation": obs})
    products.sort(key=lambda p: ((1, Decimal(0)) if p["delta"] is None else (0, -abs(Decimal(p["delta"]))), p["product_id"]))
    return {
        "data_revision": rev, "definition_version": DEFINITION_VERSION, "brand_id": brand_id, "month": month,
        "cutoff": cutoff, "periods": periods,
        "method": "Shapley decomposition (six-order averaged substitution) of linked GMV = A x V x G, "
                  "with A = active creators, V = linked videos per active creator, G = attributed GMV per linked video.",
        "status": status, "status_reason": "; ".join(dict.fromkeys(reasons)) or None, "disclaimer": DISCLAIMER,
        "total": {"baseline": _md(t0), "current": _md(t1), "delta": _md(t_delta)},
        "factors": factors,
        "unlinked_older_gmv": {"baseline": _md(base["u"]), "current": _md(cur["u"]), "delta": _md(u_delta)},
        "products": products,
    }
