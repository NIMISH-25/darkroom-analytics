"""UI checks (optional): one-click demo login (Enter Demo Workspace, no credential inputs), Logout, chart (i) popovers, evidence explainer card, Unknown never $0 (S7), evidence drawer refresh on 409 (S12).
Needs `pip install playwright && playwright install chromium` and a running frontend on FRONTEND_URL.
Skipped (not failed) otherwise; REVIEW_CHECKLIST.md lists the manual equivalent."""
import os
import re

import httpx
import pytest

from conftest import run_cli
from helpers import API, GOLDEN_DATA, REPO

SHOTS = REPO / "verification-output" / "ui"
# MetricValue / KpiStrip render every clickable number as <button title="Show evidence">
EVIDENCE_BTN = "button[title='Show evidence']"

pw = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def page(frontend_url):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browsers not installed
            pytest.skip(f"chromium unavailable: {e}")
        pg = browser.new_page()
        try:
            pg.goto(frontend_url, timeout=60000)  # first dev-server compile can take >15s
        except Exception as e:
            pytest.skip(f"frontend not reachable at {frontend_url}: {e}")
        yield pg
        browser.close()


def login(page, frontend_url):
    page.goto(frontend_url + "/login")
    if SHOTS.exists() or SHOTS.mkdir(parents=True, exist_ok=True) is None:
        page.screenshot(path=str(SHOTS / "login.png"))
    page.get_by_role("button", name=re.compile("enter demo workspace", re.I)).click()
    page.wait_for_url(re.compile(r"^(?!.*/login).*$"), timeout=15000)


def test_demo_login_end_to_end(page, frontend_url):
    login(page, frontend_url)
    token = page.evaluate("localStorage.getItem('darkroom_auth')")
    assert token, "token must be stored in localStorage['darkroom_auth']"
    # wait for client-side render; an immediate is_visible() raced the data load
    page.get_by_text(re.compile("aurelle", re.I)).first.wait_for(state="visible", timeout=15000)
    page.wait_for_selector(EVIDENCE_BTN, timeout=20000)
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "overview.png"), full_page=True)


def test_unauthenticated_user_is_sent_to_login(page, frontend_url):
    page.evaluate("localStorage.removeItem('darkroom_auth')")
    page.goto(frontend_url + "/")
    page.wait_for_url(re.compile("/login"), timeout=10000)


def test_s7_unknown_is_shown_never_zero_dollars(page, frontend_url):
    login(page, frontend_url)
    page.goto(frontend_url + "/brands/glowhaus?tab=creators")
    page.wait_for_selector("table tbody tr", timeout=15000)
    page.wait_for_load_state("networkidle")
    body = page.inner_text("body")
    assert re.search("unavailable|incomplete|partial|stale|unknown", body, re.I),         "glowhaus video metrics must show an UNAVAILABLE / INCOMPLETE / PARTIAL / STALE badge"
    # A genuine API zero (status current) legitimately renders as $0.00. The rule is that a NULL API value never
    # renders as $0: the number of "$0.00" in the UI must equal the number of API values that are exactly "0.00".
    raw = page.evaluate("localStorage.getItem('darkroom_auth')")
    tok = raw
    if raw.startswith("{"):
        import json
        d = json.loads(raw)
        tok = d.get("access_token") or d.get("token")
    r = httpx.get(os.environ.get("BASE_URL", "http://localhost:8000") + API + "/brands/glowhaus/creators",
                  headers={"Authorization": f"Bearer {tok.strip(chr(34))}"}, timeout=30)
    assert r.status_code == 200
    # Only fields that have a COLUMN in the creators table (frontend/src/app/_components/creators.tsx): net_sales and
    # unresolved_gmv are returned by the API but not displayed, so they are not counted.
    shown = {"videos": "videos", "gmv": "gmv", "refunds": "refunds", "retainer": "retainer_cost",
             "commission": "commission_cost", "sample cost": "sample_cost", "sales after costs": "sales_after_costs"}
    items = {it["handle"]: it for it in r.json()["items"]}
    zeros = nulls = 0
    for it in items.values():
        for field in shown.values():
            v = it[field]["value"]
            zeros += v == "0.00"
            nulls += v is None
    assert nulls > 0, "fixture should contain unknown values"
    assert len(re.findall(r"\$0\.00", body)) == zeros, "a displayed $0.00 must correspond to an API 0.00 (null never renders as $0.00)"
    # per cell: every null API value renders UNAVAILABLE and nothing else does; every non-null value is not UNAVAILABLE
    heads = [h.strip().lower() for h in page.locator("table thead th").all_inner_texts()]
    cols = {i: shown[h] for i, h in enumerate(heads) if h in shown}
    assert len(cols) == len(shown), f"creators table columns not found: {heads}"
    checked_null = 0
    for row in page.locator("table tbody tr").all():
        cells = [c.strip() for c in row.locator("td").all_inner_texts()]
        it = items.get(cells[0])
        if it is None:
            continue
        for i, field in cols.items():
            v = it[field]["value"]
            if v is None:
                assert re.search("unavailable", cells[i], re.I), f"{cells[0]}.{field}: API null shown as {cells[i]!r}"
                assert "$0" not in cells[i]
                checked_null += 1
            else:
                assert not re.search("unavailable", cells[i], re.I), f"{cells[0]}.{field}: value {v!r} shown as {cells[i]!r}"
    assert checked_null == nulls, f"checked {checked_null} unknown cells but the API has {nulls}"


def current_revision():
    """Real current revision: the mocked 409 must point the drawer at a revision the API serves
    (a made-up 999 makes the real API answer 409 again, which is not what is being tested)."""
    base = os.environ.get("BASE_URL", "http://localhost:8000")
    t = httpx.post(base + API + "/auth/token", data={"username": "demo", "password": "darkroom-demo"}).json()["access_token"]
    return httpx.get(base + API + "/meta", headers={"Authorization": f"Bearer {t}"}).json()["data_revision"]


def test_s12_drawer_refreshes_on_409_instead_of_mismatch(page, frontend_url):
    login(page, frontend_url)
    state = {"n": 0}

    def handler(route):
        if state["n"] == 0:
            state["n"] += 1
            route.fulfill(status=409, content_type="application/json",
                          body='{"detail":{"code":"refresh_required","current_revision":%d}}' % current_revision())
        else:
            route.continue_()

    page.route(re.compile(r".*/metrics/.+/evidence.*"), handler)
    page.goto(frontend_url + "/")
    trigger = page.locator(EVIDENCE_BTN).first
    trigger.wait_for(state="visible", timeout=20000)  # count() right after goto raced the client render
    trigger.click()
    page.get_by_role("dialog").get_by_text(re.compile("definition", re.I)).first.wait_for(timeout=15000)
    page.wait_for_load_state("networkidle")
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "evidence_drawer.png"), full_page=True)
    body = page.inner_text("body")
    assert state["n"] == 1 and not re.search("mismatch", body, re.I), "drawer must refetch, not show a mismatch"
    assert re.search("definition|formula|inputs", body, re.I), "drawer must show refreshed evidence"


def test_s12_real_ingest_batch2_while_drawer_page_open(page, frontend_url):
    """Real (unmocked) S12: load overview at revision N, ingest golden batch_2 mid-session (revision N+1),
    then open an evidence drawer from the stale page: the stale evidence_url must 409 and the drawer must refresh."""
    page.unroute_all()
    login(page, frontend_url)
    page.goto(frontend_url + "/overview")
    page.wait_for_selector(EVIDENCE_BTN, timeout=20000)
    seen = []
    page.on("response", lambda r: seen.append((r.status, r.url)) if "/evidence" in r.url else None)
    res = run_cli("ingest", GOLDEN_DATA / "batch_2")
    assert res.returncode == 0, res.stdout + res.stderr
    page.locator(EVIDENCE_BTN).first.click()  # no reload: URL still carries the old revision
    page.get_by_role("dialog").get_by_text(re.compile("definition", re.I)).first.wait_for(timeout=15000)
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "evidence_drawer_after_ingest.png"), full_page=True)
    codes = [c for c, _ in seen]
    assert 409 in codes and codes[-1] == 200, f"expected 409 then 200 refetch, got {codes}"
    assert not re.search("mismatch", page.inner_text("body"), re.I)


# ---------------------------------------------------------------- S20 (amendment 2)
# Selectors follow frontend/src/components/midday: numbers are button[title='Show evidence'] (EVIDENCE_BTN), the evidence sheet is a
# radix dialog (headings Definition / Formula), tabs are role=tab, sidebar entries are links. Routes and tabs come from docs/api-contract-amendment-2.md.
SIDEBAR = [("/overview", "overview"), ("/attention", "attention"), ("/creators", "creators"),
           ("/samples", "samples"), ("/diagnostics", "diagnostics"), ("/health", "health")]
TABS = [("overview", r"overview"), ("creators", r"creators"), ("samples", r"samples"),
        ("diagnostics", r"diagnostics"), ("health", r"data health|health")]
BROKEN = re.compile(r"application error|404|this page could not be found|unhandled runtime error", re.I)


@pytest.mark.parametrize("route,label", SIDEBAR)
def test_s20_sidebar_routes_render(page, frontend_url, route, label):
    login(page, frontend_url)
    page.goto(frontend_url + route)
    page.wait_for_load_state("networkidle")
    assert not BROKEN.search(page.inner_text("body")), f"{route} did not render"
    assert page.get_by_role("link", name=re.compile(label, re.I)).first.is_visible(), f"sidebar link {label}"


def test_s20_brand_tabs_sync_to_url(page, frontend_url):
    login(page, frontend_url)
    page.goto(frontend_url + "/brands/aurelle")
    page.wait_for_load_state("networkidle")
    for tab, label in TABS:
        page.get_by_role("tab", name=re.compile(label, re.I)).first.click()
        if tab != "overview":
            page.wait_for_url(re.compile(f"tab={tab}"), timeout=10000)
        page.get_by_role("tab", name=re.compile(label, re.I)).first.wait_for(state="visible")
        page.wait_for_load_state("networkidle")
        assert not BROKEN.search(page.inner_text("body"))
    page.goto(frontend_url + "/brands/aurelle?tab=samples")
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("tab", name=re.compile("samples", re.I)).first.get_attribute("aria-selected") == "true"


def test_s20_kpi_value_opens_evidence_sheet_pinned_to_revision(page, frontend_url):
    login(page, frontend_url)
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/evidence" in r.url else None)
    page.goto(frontend_url + "/overview")
    kpi = page.locator(EVIDENCE_BTN).first
    kpi.wait_for(state="visible", timeout=20000)     # client render finishes after load
    kpi.click()
    sheet = page.get_by_role("dialog").first
    sheet.wait_for(state="visible", timeout=10000)
    sheet.get_by_text(re.compile("definition", re.I)).first.wait_for(timeout=15000)   # evidence has loaded
    assert re.search("definition|formula|inputs", sheet.inner_text(), re.I)
    assert any("revision=" in u for u in seen), "evidence request must be pinned to a data_revision"


def test_s20_hatched_region_for_glowhaus_video_gap(page, frontend_url):
    login(page, frontend_url)
    page.goto(frontend_url + "/brands/glowhaus")
    page.wait_for_load_state("networkidle")
    # the default pacing tab (Sales GMV) has nothing missing; the gap is on the Videos Posted tab
    page.get_by_role("tab", name=re.compile("videos posted", re.I)).first.click()
    page.wait_for_load_state("networkidle")
    hatch = page.locator("[data-testid='missing-hatch'], [aria-label^='Missing data']").first
    try:
        hatch.wait_for(state="visible", timeout=20000)
    except Exception:
        pass        # the assertions below report what is missing
    assert page.locator("#missing-data-hatch").count() > 0, "hatch pattern definition missing"
    hatch.wait_for(state="attached", timeout=5000)
    assert hatch.is_visible(), "no visible hatched overlay (data-testid=missing-hatch / aria-label 'Missing data: ...') for the glowhaus video gap"


def test_s20_no_dollar_zero_for_unknown_values(page, frontend_url):
    """glowhaus orders/returns coverage is complete (refunds, commission may be a verified $0.00); VIDEO-dependent cells
    (Videos, Last post; Sales after costs can be a genuine 0.00) are unknown while weekly video coverage is incomplete and must never show 0."""
    login(page, frontend_url)
    page.goto(frontend_url + "/brands/glowhaus?tab=creators")
    page.wait_for_selector("table tbody tr", timeout=20000)
    page.wait_for_load_state("networkidle")
    heads = [h.strip().lower() for h in page.locator("table thead th").all_inner_texts()]
    video_cols = [i for i, h in enumerate(heads) if re.search(r"^videos|last post", h)]
    assert video_cols, f"no video-dependent columns found in {heads}"
    saw_unknown = False
    for row in page.locator("table tbody tr").all():
        cells = row.locator("td").all_inner_texts()
        for i in video_cols:
            if i >= len(cells):
                continue
            txt = cells[i].strip()
            assert not re.fullmatch(r"\$?\s?0(\.00)?", txt), f"video-dependent cell '{heads[i]}' shows {txt!r} under a coverage gap"
            saw_unknown = saw_unknown or bool(re.search("unknown|unavailable|stale|—|-", txt, re.I))
    assert saw_unknown, "video-dependent cells must say Unknown/unavailable while coverage is incomplete"
    page.goto(frontend_url + "/brands/glowhaus?tab=diagnostics")
    page.wait_for_load_state("networkidle")
    assert re.search("unknown|stale|incomplete|unavailable", page.inner_text("body"), re.I)


# ---------------------------------------------------------------- wave 3 (docs/api-contract-amendment-3.md sections 5 and 7)
def test_w3_login_is_one_click_without_credential_inputs(page, frontend_url):
    page.evaluate("localStorage.removeItem('darkroom_auth')")
    page.goto(frontend_url + "/login")
    page.wait_for_load_state("networkidle")
    assert page.locator("input[type=password]").count() == 0, "no password input on the login page"
    assert page.locator("input[type=text], input[type=email], input:not([type])").count() == 0, "no username input"
    assert re.search("pre-loaded synthetic demo data", page.inner_text("body"), re.I), "demo notice missing"
    page.get_by_role("button", name=re.compile("enter demo workspace", re.I)).click()
    page.wait_for_url(re.compile(r"^(?!.*/login).*$"), timeout=15000)
    assert page.evaluate("localStorage.getItem('darkroom_auth')"), "token not stored after entering the workspace"


def test_w3_logout_in_sidebar_footer_and_header_clears_token(page, frontend_url):
    login(page, frontend_url)
    page.goto(frontend_url + "/overview")
    page.wait_for_load_state("networkidle")
    buttons = page.get_by_role("button", name=re.compile("^logout$", re.I))
    assert buttons.count() >= 2, f"Logout expected in the sidebar footer AND the top header, found {buttons.count()}"
    assert page.locator("aside >> text=/logout/i").count() >= 1, "Logout missing in the sidebar"
    assert page.locator("header >> text=/logout/i").count() >= 1, "Logout missing in the header bar"
    buttons.first.click()
    page.wait_for_url(re.compile("/login"), timeout=10000)
    assert not page.evaluate("localStorage.getItem('darkroom_auth')"), "Logout must clear the stored token"
    login(page, frontend_url)
    page.get_by_role("button", name=re.compile("^logout$", re.I)).last.click()      # header copy works too
    page.wait_for_url(re.compile("/login"), timeout=10000)


def test_w3_chart_info_popover_has_three_parts(page, frontend_url):
    login(page, frontend_url)
    page.goto(frontend_url + "/brands/aurelle")
    info = page.get_by_role("button", name=re.compile("^about ", re.I))
    try:
        info.first.wait_for(state="visible", timeout=20000)     # charts render after the data loads
    except Exception:
        pass
    assert info.count() >= 1, "every chart header needs an (i) info button (aria-label 'About <title>')"
    info.first.click()
    pop = page.locator("[role=dialog]").last
    pop.wait_for(state="visible", timeout=5000)
    text = pop.inner_text()
    for part in ("what it shows", "how to read", "decision"):
        assert re.search(part, text, re.I), f"info popover lacks '{part}'"


def test_w3_evidence_sheet_has_what_this_number_means_card(page, frontend_url):
    login(page, frontend_url)
    page.goto(frontend_url + "/overview")
    kpi = page.locator(EVIDENCE_BTN).first
    kpi.wait_for(state="visible", timeout=20000)
    kpi.click()
    sheet = page.get_by_role("dialog").first
    sheet.wait_for(state="visible", timeout=10000)
    # wait for the evidence payload (card + definition) before reading the text
    sheet.get_by_text(re.compile("what this number means", re.I)).first.wait_for(timeout=15000)
    sheet.get_by_text(re.compile("definition", re.I)).first.wait_for(timeout=15000)
    text = sheet.inner_text()
    assert re.search("what this number means", text, re.I), "explainer card missing from the evidence sheet"
    for part in ("why it matters", "how it is calculated", "what the rows prove"):
        assert re.search(part, text, re.I), f"explainer part '{part}' missing"
