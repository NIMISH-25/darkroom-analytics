"""S1: auth boundary, read-only API, login, CORS preflight."""
import httpx
import pytest

from conftest import BASE_URL, DEMO_PASS, DEMO_USER
from helpers import API

DATA_ROUTES = [
    f"{API}/meta", f"{API}/overview", f"{API}/brands/aurelle/creators", f"{API}/brands/threadline/samples",
    f"{API}/metrics/gmv/evidence?brand_id=aurelle", f"{API}/data-health", f"{API}/attention", f"{API}/auth/me",
]


def test_healthz_is_open(anon):
    r = anon.get("/healthz")
    assert r.status_code == 200 and "status" in r.json()


@pytest.mark.parametrize("route", DATA_ROUTES)
def test_no_token_is_401_and_leaks_nothing(anon, route):
    r = anon.get(route)
    assert r.status_code == 401
    assert "brands" not in r.text and "items" not in r.text


@pytest.mark.parametrize("bad", ["garbage", "Bearer x", "x.y.z", "a.b"])
def test_invalid_token_is_401(anon, bad):
    r = anon.get(f"{API}/overview", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


def test_missing_or_malformed_authorization_header_is_401(anon):
    assert anon.get(f"{API}/overview").status_code == 401
    assert anon.get(f"{API}/overview", headers={"Authorization": "Basic abc"}).status_code == 401


def test_tampered_signature_is_401(anon, token):
    head, payload, sig = token.split(".")
    forged = ".".join([head, payload, sig[:-2] + ("AA" if not sig.endswith("AA") else "BB")])
    assert anon.get(f"{API}/overview", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("route", [f"{API}/overview", f"{API}/brands/aurelle/creators", f"{API}/data-health"])
def test_data_routes_are_read_only(client, anon, method, route):
    assert client.request(method, route).status_code in (404, 405)       # authenticated
    assert anon.request(method, route).status_code in (401, 404, 405)    # anonymous: never 2xx


def test_login_wrong_credentials(anon):
    for u, p in [(DEMO_USER, "wrong"), ("nobody", DEMO_PASS), ("", "")]:
        r = anon.post(f"{API}/auth/token", data={"username": u, "password": p})
        assert r.status_code in (401, 422)
        assert "access_token" not in r.text


def test_login_ok_and_me(anon):
    r = anon.post(f"{API}/auth/token", data={"username": DEMO_USER, "password": DEMO_PASS})
    assert r.status_code == 200
    body = r.json()
    assert {"access_token", "token_type", "expires_at"} <= set(body) and body["token_type"].lower() == "bearer"
    assert body["access_token"].count(".") == 2          # JWT
    me = anon.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json() == {"username": DEMO_USER}


def test_cors_preflight_from_frontend_origin():
    origin = "http://localhost:3000"
    r = httpx.options(f"{BASE_URL}{API}/overview", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,content-type"})
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == origin
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed or allowed == "*"
    assert r.headers.get("access-control-allow-credentials", "false").lower() != "true"


def test_cors_rejects_unknown_origin():
    r = httpx.options(f"{BASE_URL}{API}/overview", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") not in ("http://evil.example", "*")
