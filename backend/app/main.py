import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
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
