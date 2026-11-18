from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, field_validator

from app import auth
from app.metrics import charts
from app.metrics.cache import respond
from app.metrics.conn import read_conn, write_conn
from app.metrics.memo import Memo
from app.metrics.repo import PgRepo
from app.metrics.service import (
    DEFAULT_CUTOFF, DEFAULT_MONTH, META, Filters, MetricService, actual_key, attention_impact, evidence_url,
    goal_id, goal_state, jsonable, mv_dict, progress_ratio, suggested_action,
)
from app.presentation.humanize import (
    attention_text, count_label, data_note_for, exclusion_file_reason, failed_file_reason, goal_name, money_label,
    names_for, plain_text, SOURCE_NOUN,
)

_gid = goal_id
router = APIRouter()
api = APIRouter(prefix="/api/v1")
SORTS = {"handle", "videos", "gmv", "net_sales", "sales_after_costs", "last_post_date"}


def get_repo():
    """One REPEATABLE READ read-only connection per request (revision + data = one snapshot)."""
    with read_conn() as conn:
        yield Memo(PgRepo(conn))


def _month(month: str = Query(DEFAULT_MONTH)) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Choose a month like 2026-10.")
    return month


def _cutoff(cutoff: str = Query(DEFAULT_CUTOFF)) -> str:
    try:
        date.fromisoformat(cutoff)
    except ValueError:
        raise HTTPException(422, "Choose a cutoff date like 2026-10-15.")
    return cutoff


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@api.post("/auth/token")
def token(form: OAuth2PasswordRequestForm = Depends()):
    if not auth.verify_credentials(form.username, form.password):
        raise HTTPException(401, "Incorrect username or password")
    tok, exp = auth.create_token(form.username)
    return {"access_token": tok, "token_type": "bearer", "expires_at": exp.isoformat()}


@api.get("/auth/me")
def me(user: str = Depends(auth.current_user)):
    return {"username": user}


secured = [Depends(auth.current_user)]


@api.get("/meta", dependencies=secured)
def meta(request: Request, repo=Depends(get_repo)):
    return respond(request, repo, lambda: {
        "default_month": DEFAULT_MONTH, "default_cutoff": DEFAULT_CUTOFF,
        "months": repo.months(), "brands": jsonable(repo.brands()), "data_revision": repo.revision()})


def _goal_item(svc, repo, g, b, month, cutoff, rev):
    f = Filters(brand_id=b["brand_id"], month=month, cutoff=cutoff, goal_id=goal_id(g))
    unit, pace_unit = ("USD", "USD_per_day") if g["metric_key"] == "gmv" else ("count", "count_per_day")
    actual = svc.compute(actual_key(g), f)
    gs = goal_state(g, actual)
    tgt = g.get("target_value")
    name = goal_name(g["metric_key"], g.get("scope"), g.get("basis"))
    fmt = money_label if g["metric_key"] == "gmv" else count_label
    applicable = g["metric_key"] != "active_creators" and tgt is not None
    pace_reason = None if not applicable or gs["required_pace"] is not None else (
        gs["reason"] or "There is not enough data yet to work out a daily pace.")
    if not applicable:
        pace_reason = "A daily pace does not apply to a count of different creators." if g["metric_key"] == "active_creators" else "No target has been set."
    bname = b["name"]
    reasoning = (f"At the current pace {bname} is on course for {fmt(gs['projection'])} by the end of the month, against a target of {fmt(tgt)}."
                 if gs["projection"] is not None and tgt is not None else
                 f"No projection for {bname} yet: " + (plain_text(gs["reason"], {"brand": bname}) or "there is not enough data") )
    if not reasoning.endswith("."):
        reasoning += "."
    cov = g.get("coverage_through") or actual["coverage"]
    pv, pst, prs = progress_ratio(actual["value"], tgt, actual["status"], actual["reason"])
    return {
        "goal_id": goal_id(g), "label": name,
        "definition": plain_text(g.get("definition") or "", {"brand": bname}) or "", "scope": g["scope"], "basis": g.get("basis"),
        "target": mv_dict("goal_projection", None if tgt is None else str(tgt), unit, f,
                          "current" if tgt is not None else "unavailable",
                          None if tgt is not None else "no target in plan", None, rev, part="target"),
        "actual": svc.mv(actual_key(g), f, rev, actual),
        "projection": mv_dict("goal_projection", gs["projection"], unit, f, gs["status"], gs["reason"], cov, rev),
        "required_pace": mv_dict("goal_projection", gs["required_pace"], pace_unit, f, gs["status"], gs["reason"], cov,
                                 rev, part="required_pace"),
        "progress": mv_dict("goal_projection", pv, "ratio", f, pst, prs, actual["coverage"], rev, part="progress"),
        "pace_status": gs["pace_status"],
        "required_pace_applicable": applicable, "required_pace_reason": pace_reason,
        "pace_label": {"on_track": "On pace", "at_risk": "Behind pace", "off_track": "Behind pace"}.get(gs["pace_status"], "Not enough data"),
        "scope_label": "Shop-wide" if g["scope"] == "shop" else "Creator-driven",
        "reasoning": reasoning,
    }


@api.get("/overview", dependencies=secured)
def overview(request: Request, month: str = Depends(_month), cutoff: str = Depends(_cutoff), repo=Depends(get_repo)):
    def build():
        svc, rev = MetricService(repo), repo.revision()
        goals = repo.goals(None, month)
        by_brand = defaultdict(list)
        for g in goals:
            by_brand[g["brand_id"]].append(g)
        return {"data_revision": rev, "brands": [
            {"brand_id": b["brand_id"], "name": b["name"],
             "goals": [_goal_item(svc, repo, g, b, month, cutoff, rev) for g in by_brand[b["brand_id"]]]}
            for b in repo.brands()]}
    return respond(request, repo, build)


def _sort_key(item, sort):
    if sort == "handle":
        return (item["handle"] or "").lower()
    v = item["last_post_date"] if sort == "last_post_date" else item[sort]["value"]
    if v is None:
        return None
    return v if sort == "last_post_date" else Decimal(str(v))


class _Prefetched:
    """Repo wrapper serving rows grouped once per brand (same rows the evidence endpoint would fetch)."""

    def __init__(self, repo, sales, vids):
        self._r, self._s, self._v = repo, sales, vids

    def sales_rows(self, *a, **k):
        return self._s

    def video_rows(self, *a, **k):
        return self._v

    def __getattr__(self, n):
        return getattr(self._r, n)


@api.get("/brands/{brand_id}/creators", dependencies=secured)
def creators(request: Request, brand_id: str, q: str | None = None, contract_type: str | None = None,
             status: str | None = None, sort: str = "handle", order: str = "asc", month: str = Depends(_month),
             cutoff: str = Depends(_cutoff), repo=Depends(get_repo)):
    if sort not in SORTS or order not in ("asc", "desc"):
        raise HTTPException(422, "Choose a valid column to sort by and an order (ascending or descending).")
    if brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise HTTPException(404, "That brand was not found.")

    def build():
        rev = repo.revision()
        perf = repo.creators(brand_id, month)
        types = sorted({p["contract_type"] for p in perf if p.get("contract_type")})
        sales_by, vids_by = defaultdict(list), defaultdict(list)  # group once, no per-creator scans
        for r in repo.sales_rows(brand_id, None, month, cutoff):
            sales_by[r["creator_id"]].append(r)
        for r in repo.video_rows(brand_id, None, month, cutoff):
            vids_by[r["creator_id"]].append(r)
        items = []
        for p in perf:
            if q and q.lower() not in (p["handle"] or "").lower():
                continue
            if contract_type and p.get("contract_type") != contract_type:
                continue
            if status and p.get("coverage_status") != status:
                continue
            cid = p["creator_id"]
            f = Filters(brand_id=brand_id, creator_id=cid, month=month, cutoff=cutoff)
            s2 = MetricService(_Prefetched(repo, sales_by.get(cid, []), vids_by.get(cid, [])))

            def cost(part):
                return s2.mv("creator_sales_after_costs", f, rev, s2.compute_part("creator_sales_after_costs", part, f), part)

            item = {
                "creator_id": cid, "handle": p["handle"], "contract_type": p.get("contract_type"),
                "last_post_date": jsonable(p.get("last_post_date")), "coverage_status": p.get("coverage_status"),
                "videos": s2.mv("creator_videos", f, rev),
                "gmv": s2.mv("creator_attributed_gmv", f, rev),
                "refunds": s2.mv("creator_net_sales", f, rev, part="refunds"),
                "net_sales": s2.mv("creator_net_sales", f, rev),
                "retainer_cost": cost("retainer_cost"),
                "commission_cost": cost("commission_cost"),
                "sample_cost": cost("sample_cost"),
                "sales_after_costs": s2.mv("creator_sales_after_costs", f, rev),
                "unresolved_gmv": s2.mv("creator_attributed_gmv", f, rev, part="unresolved"),
            }
            item["suggested_action"] = suggested_action(item, cutoff)
            items.append(item)
        has = [i for i in items if _sort_key(i, sort) is not None]
        none = [i for i in items if _sort_key(i, sort) is None]  # nulls last in both directions
        has.sort(key=lambda i: _sort_key(i, sort), reverse=order == "desc")
        return {"data_revision": rev, "contract_types": types, "items": has + none}
    return respond(request, repo, build)


@api.get("/brands/{brand_id}/samples", dependencies=secured)
def samples(request: Request, brand_id: str, status: str | None = None, creator_id: str | None = None,
            month: str = Depends(_month), cutoff: str = Depends(_cutoff), repo=Depends(get_repo)):
    def build():
        svc, rev = MetricService(repo), repo.revision()
        f = Filters(brand_id=brand_id, creator_id=creator_id, month=month, cutoff=cutoff)
        allrows = repo.sample_rows(brand_id, creator_id)
        conv = svc.compute("sample_conversion_rate", f)

        def cnt(part):
            return svc.mv("sample_conversion_rate", f, rev, svc.compute_part("sample_conversion_rate", part, f), part)

        counts = {k: cnt(k) for k in ("sent", "delivered", "matched", "pending", "no_video", "unknown")}
        counts["conversion_rate"] = svc.mv("sample_conversion_rate", f, rev, conv)
        items = []
        for r in allrows:
            if status and r["state"] != status:
                continue
            items.append({
                "sample_id": r["sample_id"], "creator_id": r["creator_id"], "handle": r.get("handle"),
                "product_sku": r.get("product_sku"), "sent_date": jsonable(r.get("sent_date")),
                "delivered_date": jsonable(r.get("delivered_date")), "status": r["state"],
                "video_id": r.get("matched_video_id"), "delivery_to_video_days": r.get("delivery_to_video_days"),
                "evidence_url": evidence_url("sample_conversion_rate", Filters(
                    brand_id=brand_id, creator_id=r["creator_id"], month=month, cutoff=cutoff), rev),
            })
        return {"data_revision": rev, "counts": counts, "items": items}
    return respond(request, repo, build)


@api.get("/metrics/{metric_key}/evidence", dependencies=secured)
def evidence(request: Request, metric_key: str, brand_id: str | None = None, creator_id: str | None = None,
             goal_id: str | None = None, part: str | None = None, revision: int | None = None,
             date_from: str | None = None, date_to: str | None = None, bucket: str | None = None,
             stage: str | None = None, metric: str | None = None,
             limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
             month: str = Depends(_month), cutoff: str = Depends(_cutoff), repo=Depends(get_repo)):
    params = {"brand_id": brand_id, "creator_id": creator_id, "month": month, "cutoff": cutoff, "goal_id": goal_id,
              "part": part, "date_from": date_from, "date_to": date_to, "bucket": bucket, "stage": stage,
              "metric": metric, "limit": limit, "offset": offset}
    is_chart = charts.is_chart_evidence(metric_key, params)
    if not is_chart and metric_key not in META:
        raise HTTPException(404, "That figure is not available.")
    current = repo.revision()
    if revision is not None and revision != current:
        return JSONResponse(status_code=409, headers={"Cache-Control": "no-store"},
                            content={"detail": {"code": "refresh_required", "current_revision": current}})
    if is_chart:
        return respond(request, repo, lambda: charts.chart_evidence(
            metric_key, params, charts.ChartsRepo(getattr(repo, "conn", None))))
    if metric_key == "creator_sales_after_costs" and not (brand_id and creator_id):
        raise HTTPException(422, "Choose a brand and a creator to explain.")
    if metric_key == "goal_projection":
        if not goal_id:  # pick the brand's main sales goal, else ask which goal to explain
            gl = [g for g in repo.goals(brand_id, month) if g["metric_key"] == "gmv"] if brand_id else []
            main = next((g for g in gl if g["scope"] == "shop"), gl[0] if gl else None)
            if main is None:
                raise HTTPException(422, "Choose which goal to explain.")
            goal_id = _gid(main)
        if not brand_id:  # locate the brand owning this goal
            brand_id = next((g["brand_id"] for g in repo.goals(None, month) if _gid(g) == goal_id), None)
            if not brand_id:
                raise HTTPException(404, "That goal was not found.")
    f = Filters(brand_id=brand_id, creator_id=creator_id, month=month, cutoff=cutoff, goal_id=goal_id)

    def build():
        try:
            return MetricService(repo).evidence(metric_key, f, part, limit, offset)
        except KeyError:
            raise HTTPException(404, "That goal was not found.")
    return respond(request, repo, build)


SHARED_LABEL = "Shared Cross-Brand Source"


@api.get("/data-health", dependencies=secured)
def data_health(request: Request, brand_id: str | None = None, repo=Depends(get_repo)):
    if brand_id is not None and brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise HTTPException(404, "That brand was not found.")

    def build():
        shared = repo.shared_types()
        sources, seen_shared = [], set()
        for r in repo.freshness(brand_id):
            is_shared = r["source_type"] in shared
            if is_shared:
                if r["source_type"] in seen_shared:  # portfolio form: each shared tracker once
                    continue
                seen_shared.add(r["source_type"])
            sources.append({"brand_id": None if is_shared else r["brand_id"], "source": r["source_type"],
                            "source_name": SOURCE_NOUN.get(r["source_type"], "data"),
                            "brand_name": None if is_shared else names_for(repo, r["brand_id"])["brand"],
                            "status": r["state"], "coverage_through": r.get("coverage_through"),
                            "last_ingested_at": r.get("last_ingested_at"), "message": r.get("message"),
                            "scope": "shared" if is_shared else "brand",
                            "source_label": SHARED_LABEL if is_shared else None})
        bn = {b_["brand_id"]: b_["name"] for b_ in repo.brands()}
        failed = []
        for r_ in repo.failed_files(brand_id):
            is_shared = r_["scope_key"] == "all" or r_["source_type"] in shared
            bid = None if is_shared else r_["scope_key"]
            reason = failed_file_reason(r_.get("status"), r_["source_type"], r_.get("error"), bn.get(bid))
            failed.append({"run_id": str(r_["run_id"]), "file_name": r_["file_name"], "error": reason, "plain_reason": reason,
                           "scope": "shared" if is_shared else "brand", "brand_id": bid,
                           "brand_name": bn.get(bid) if bid else None, "source_label": SHARED_LABEL if is_shared else None})
        excluded = []
        for r_ in repo.files_with_exclusions(brand_id):
            is_shared = r_["scope_key"] == "all" or r_["source_type"] in shared
            bid = None if is_shared else r_["scope_key"]
            excluded.append({"run_id": str(r_["run_id"]), "file_name": r_["file_name"], "rows_excluded": int(r_["rows_excluded"]),
                             "plain_reason": exclusion_file_reason(r_["rows_excluded"], r_["source_type"], bn.get(bid)),
                             "scope": "shared" if is_shared else "brand", "brand_id": bid,
                             "brand_name": bn.get(bid) if bid else None, "source_label": SHARED_LABEL if is_shared else None})
        counts = {"brand_failed": sum(1 for f in failed if f["scope"] == "brand"),
                  "shared_failed": sum(1 for f in failed if f["scope"] == "shared"),
                  "open_issues": repo.open_issue_count(brand_id),
                  "rows_excluded": sum(e["rows_excluded"] for e in excluded)}
        return jsonable({
            "data_revision": repo.revision(), "counts": counts, "sources": sources,
            "runs": [{"run_id": str(r["run_id"]), "started_at": r["started_at"], "status": r["status"],
                      "files_failed": r["files_failed"]} for r in repo.runs(brand_id)],
            "failed_files": failed, "files_with_exclusions": excluded,
            "unresolved_identities": [{"brand_id": r["brand_id"], "source": r["source"],
                                       "raw_identifier": r["raw_identifier"], "occurrences": r["occurrences"]}
                                      for r in repo.unresolved_identities(brand_id)],
        })
    return respond(request, repo, build, extra=("health", brand_id, repo.last_run_id()))


@api.get("/attention", dependencies=secured)
def attention(request: Request, brand_id: str | None = None, kind: str | None = None,
              followup_days: int | None = None, month: str = Depends(_month), cutoff: str = Depends(_cutoff),
              repo=Depends(get_repo)):
    def build():
        rev = repo.revision()
        items = []
        for r in repo.attention(brand_id):
            if kind and r["kind"] != kind:
                continue
            if followup_days is not None and r["kind"] == "sample_no_video" and r.get("days_waiting") is not None \
                    and r["days_waiting"] < followup_days:
                continue
            f = Filters(brand_id=r["brand_id"], creator_id=r.get("creator_id"), month=month, cutoff=cutoff)
            key = {"quiet_retainer": "creator_videos", "sample_no_video": "sample_conversion_rate"}.get(r["kind"], "videos")
            if key == "creator_videos" and not r.get("creator_id"):
                key = "videos"
            score, basis = attention_impact(r, month, cutoff, repo)
            nm = names_for(repo, r["brand_id"], r.get("creator_id"))
            src = "videos_weekly" if r["kind"] != "missing_source" else r["entity_ref"]
            st_, rs_, _ = MetricService(repo).status_for([src], r["brand_id"])
            fr = next((x for x in repo.freshness(r["brand_id"]) if x["source_type"] == src), None)
            title, rule, why, todo = attention_text(
                r["kind"], nm["brand"] or "The brand", nm["creator"], r.get("days_waiting"), None,
                src if r["kind"] == "missing_source" else None, fr["state"] if fr else None,
                rs_ if r["kind"] == "missing_source" else None)
            items.append({
                "item_id": f"{r['kind']}:{r['brand_id']}:{r['entity_ref']}", "kind": r["kind"],
                "brand_id": r["brand_id"], "brand_name": nm["brand"], "creator_name": nm["creator"],
                "title": title, "rule": rule, "why_needs_attention": why, "what_to_do": todo,
                "incomplete_reason": rs_ if st_ != "current" else None,
                "data_note": data_note_for(repo, r["brand_id"], [src]),
                "period_start": jsonable(r.get("period_start")), "period_end": jsonable(r.get("period_end")),
                "impact_score": score, "impact_basis": basis,
                "evidence_url": evidence_url(key, f, rev),
            })
        # rank across brands by USD exposure, unknown impact last
        items.sort(key=lambda i: (i["impact_score"] is None,
                                  -Decimal(i["impact_score"]) if i["impact_score"] is not None else 0,
                                  i["brand_id"], i["item_id"]))
        for n, i in enumerate(items, 1):
            i["rank"] = n
        return {"data_revision": rev, "items": items}
    return respond(request, repo, build)


# ---------------------------------------------------------------- creator notes (never cached)
class NoteIn(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _trim(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 2000:
            raise ValueError("body must be 1 to 2000 characters")
        return v


def _check_creator(repo, brand_id, creator_id):
    if brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise HTTPException(404, "That brand was not found.")
    if creator_id not in repo.creator_handles():
        raise HTTPException(404, "That creator was not found.")


def _note(r: dict) -> dict:
    return jsonable({"note_id": r["note_id"], "brand_id": r["brand_id"], "creator_id": r["creator_id"],
                     "author": r["author"], "body": r["body"], "created_at": r["created_at"]})


@api.get("/brands/{brand_id}/creators/{creator_id}/notes", dependencies=secured)
def list_notes(brand_id: str, creator_id: str, repo=Depends(get_repo)):
    _check_creator(repo, brand_id, creator_id)
    try:
        rows = repo.notes(brand_id, creator_id)
    except psycopg.errors.UndefinedTable:
        raise HTTPException(503, "Notes are not available yet.")
    return JSONResponse({"items": [_note(r) for r in rows], "total_count": len(rows)},
                        headers={"Cache-Control": "no-store"})


@api.post("/brands/{brand_id}/creators/{creator_id}/notes", status_code=201)
def add_note(brand_id: str, creator_id: str, payload: NoteIn, user: str = Depends(auth.current_user),
             repo=Depends(get_repo)):
    _check_creator(repo, brand_id, creator_id)
    try:
        with write_conn() as conn:
            row = conn.execute(
                "INSERT INTO app.creator_note (brand_id, creator_id, body, author) VALUES (%s, %s, %s, %s) "
                "RETURNING note_id, brand_id, creator_id, author, body, created_at",
                (brand_id, creator_id, payload.body, user)).fetchone()
    except psycopg.errors.UndefinedTable:
        raise HTTPException(503, "Notes are not available yet.")
    return JSONResponse(_note(row), status_code=201, headers={"Cache-Control": "no-store"})


router.include_router(api)
