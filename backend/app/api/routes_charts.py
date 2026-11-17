"""Chart, portfolio and diagnostics routes (include with app.include_router(routes_charts.router))."""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import auth
from app.metrics import charts, diagnostics
from app.metrics.cache import respond
from app.metrics.charts import ChartsRepo
from app.metrics.conn import read_conn
from app.metrics.service import DEFAULT_CUTOFF, DEFAULT_MONTH

router = APIRouter(prefix="/api/v1", dependencies=[Depends(auth.current_user)])


def get_charts_repo():
    with read_conn() as conn:  # one REPEATABLE READ snapshot per request
        yield ChartsRepo(conn)


def _month(month: str = Query(DEFAULT_MONTH)) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "month must be YYYY-MM")
    return month


def _cutoff(cutoff: str = Query(DEFAULT_CUTOFF)) -> str:
    try:
        date.fromisoformat(cutoff)
    except ValueError:
        raise HTTPException(422, "cutoff must be YYYY-MM-DD")
    return cutoff


def _chart(request, repo, series, brand_id, month, cutoff, metric):
    if series not in charts.SERIES:
        raise HTTPException(422, "series must be one of " + ", ".join(charts.SERIES))
    if metric not in ("gmv", "videos", "active_creators"):
        raise HTTPException(422, "metric must be gmv|videos|active_creators")
    if brand_id is not None and brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise HTTPException(404, "unknown brand")  # errors are never cached
    return respond(request, repo, lambda: charts.build_chart(repo, series, brand_id, month, cutoff, metric))


@router.get("/brands/{brand_id}/charts")
def brand_charts(request: Request, brand_id: str, series: str, month: str = Depends(_month), cutoff: str = Depends(_cutoff),
                 metric: str = "gmv", repo=Depends(get_charts_repo)):
    return _chart(request, repo, series, brand_id, month, cutoff, metric)


@router.get("/brands/{brand_id}/charts/available")
def brand_charts_available(request: Request, brand_id: str, month: str = Depends(_month), cutoff: str = Depends(_cutoff),
                           repo=Depends(get_charts_repo)):
    if brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise HTTPException(404, "unknown brand")
    return respond(request, repo, lambda: charts.build_available(repo, brand_id, month, cutoff))


@router.get("/portfolio/charts")
def portfolio_charts(request: Request, series: str, month: str = Depends(_month), cutoff: str = Depends(_cutoff),
                     metric: str = "gmv", repo=Depends(get_charts_repo)):
    return _chart(request, repo, series, None, month, cutoff, metric)


@router.get("/portfolio/kpis")
def portfolio_kpis(request: Request, month: str = Depends(_month), cutoff: str = Depends(_cutoff), repo=Depends(get_charts_repo)):
    return respond(request, repo, lambda: charts.build_kpis(repo, month, cutoff))


@router.get("/brands/{brand_id}/diagnostics")
def brand_diagnostics(request: Request, brand_id: str, month: str = Depends(_month), cutoff: str = Depends(_cutoff),
                      repo=Depends(get_charts_repo)):
    if brand_id not in {b["brand_id"] for b in repo.brands()}:
        raise HTTPException(404, "unknown brand")
    return respond(request, repo, lambda: diagnostics.build_diagnostics(repo, brand_id, month, cutoff))
