import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import router
from app.metrics.conn import close_pool, open_pool, set_request_cutoff
from app.settings import get_settings


def _warm_bg() -> None:
    try:
        from app.metrics.cache import warm
        warm()
    except Exception:  # warming is best effort; never block or fail startup
        pass


@asynccontextmanager
async def lifespan(_app):
    open_pool()
    threading.Thread(target=_warm_bg, daemon=True).start()
    yield
    close_pool()


class CutoffMiddleware:
    """Pure ASGI: expose the request's `cutoff` query param to read_conn() (sets app.cutoff per snapshot)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            from urllib.parse import parse_qs
            q = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("cutoff", [None])[0]
            set_request_cutoff(q)
        await self.app(scope, receive, send)


app = FastAPI(title="Darkroom Analytics API", lifespan=lifespan)
app.add_middleware(CutoffMiddleware)

PLAIN_422 = {
    "goal_id": "Choose which goal to explain.", "month": "Choose a month like 2026-10.",
    "cutoff": "Choose a cutoff date like 2026-10-15.", "limit": "Choose a page size between 1 and 500.",
    "offset": "The starting position cannot be negative.", "series": "Choose which chart to show.",
    "metric": "Choose sales, videos or active creators.", "body": "Write a note of 1 to 2000 characters.",
    "brand_id": "Choose a brand.", "creator_id": "Choose a creator.", "revision": "The version number must be a whole number.",
    "username": "Enter the demo account name.", "password": "Enter the demo account password.",
}


@app.exception_handler(RequestValidationError)
async def plain_validation_error(_request, exc: RequestValidationError):
    """422 details are one plain sentence, never a field name or a validator message."""
    text = "Some of the information sent could not be used. Please check it and try again."
    for e in exc.errors():
        name = next((x for x in reversed(e.get("loc", ())) if isinstance(x, str)), None)
        if name in PLAIN_422:
            text = PLAIN_422[name]
            break
    return JSONResponse(status_code=422, content={"detail": text})
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "If-None-Match"],
    expose_headers=["ETag", "X-Data-Revision"],
)
app.include_router(router)

# --- charts / portfolio / diagnostics router (owned by the charts API worker) ---
try:
    from app.api.routes_charts import router as charts_router

    app.include_router(charts_router)
except ModuleNotFoundError as e:  # module not present yet
    if e.name != "app.api.routes_charts":
        raise
