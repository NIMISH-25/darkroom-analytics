"""Fixtures: BASE_URL + CLI only. No `import app`."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from helpers import API, GOLDEN_DATA, REPO

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
BACKEND_DIR = Path(os.environ.get("BACKEND_DIR", REPO / "backend"))
BACKEND_PYTHON = os.environ.get("BACKEND_PYTHON", sys.executable)
DEMO_USER = os.environ.get("DEMO_USERNAME", "demo")
DEMO_PASS = os.environ.get("DEMO_PASSWORD", "darkroom-demo")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def frontend_url():
    return FRONTEND_URL


@pytest.fixture(scope="session")
def anon():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        try:
            c.get("/healthz")
        except httpx.HTTPError as e:  # pragma: no cover
            pytest.exit(f"API not reachable at {BASE_URL}: {e}", returncode=2)
        yield c


@pytest.fixture(scope="session")
def token(anon):
    r = anon.post(f"{API}/auth/token", data={"username": DEMO_USER, "password": DEMO_PASS})
    assert r.status_code == 200, f"demo login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def client(token):
    with httpx.Client(base_url=BASE_URL, timeout=60, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


def run_cli(*args, extra_env=None):
    """python -m app.cli <args> from backend/ (DATABASE_URL etc. inherited from the environment)."""
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run([BACKEND_PYTHON, "-m", "app.cli", *map(str, args)], cwd=str(BACKEND_DIR), env=env,
                          capture_output=True, text=True, timeout=600)


@pytest.fixture(scope="session")
def ingest():
    def _ingest(folder: str):
        return run_cli("ingest", str(GOLDEN_DATA / folder))
    return _ingest


@pytest.fixture(scope="session")
def meta(client):
    def _meta():
        r = client.get(f"{API}/meta")
        assert r.status_code == 200
        return r.json()
    return _meta
