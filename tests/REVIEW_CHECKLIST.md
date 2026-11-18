# Review checklist (trigger in the diff -> check)

Run `tests/run_blackbox.ps1` for every change. Verifier is separate from the implementer; expected values live in
`tests/golden/expected.yaml` (hand-written, arithmetic in comments) and the fixtures in `data/synthetic/golden_cases/`.

| Trigger seen in the diff | Check |
|---|---|
| upsert / unique keys / `ON CONFLICT` / version rules changed | S4 (replay identical, same data_revision), S5 (older version loses) |
| date, timezone, `tzdata`, `paid_time` handling | S6 (Oct 31 23:30 PT counts in October; golden `O_G2` = 65.00 total glowhaus) |
| money code | Decimal / numeric only, no `float`, API money as strings (`test_s09`) |
| `COALESCE`, `fillna`, `?? 0`, `or 0`, `|| 0` on a metric | S7 (glowhaus null + stale), S8 (verified zero only with full coverage) |
| a metric query touched | value and evidence share one filter set (S9 `test_s9_every_metric_equals_its_evidence`) |
| header mapping / `header_aliases.yaml` / CSV decoding | S11 (aliased W42 header, BOM CSV, missing-field file rejected, exit != 0) |
| route, env var, secret, CORS | S1 (401s, read-only, CORS preflight); grep the frontend bundle for `AUTH_SECRET` / the password |
| `refresh_required` / revision logic | S12 API test; manual: open an evidence drawer, ingest, drawer shows refresh |
| freshness / coverage code | golden glowhaus gap (W41 missing) stays stale; aurelle `cr_0002` stays verified zero |
| `tests/golden/expected.yaml` edited in the same change as `backend/` | REJECT: expected values are never edited together with implementation |
| `scripts/` or `data/` imported from `backend/` (or `backend/app` from tests) | REJECT |

Manual UI steps (also covered by optional `test_ui_playwright.py`): demo login via "Use demo account"; unknown shows
"Unknown" + reason, never `$0`; evidence drawer opens from any metric; a 401 clears `localStorage["darkroom_auth"]`.

## Wave 3 additions
| Trigger seen in the diff | Check |
|---|---|
| `runs()` / `failed_files()` / health cache key or `scope_key` / `brand_id` on issues | `test_w3_health_*`: brand-scoped failed files, shared trackers labelled `Shared Cross-Brand Source`, no cross-brand cache reuse; on seeded synthetic data `pytest -m synth` (verdant 1, threadline 1, others 0) |
| chart classifier / `charts/available` / `new_creators` / chart SQL `COALESCE` | `test_w3_availability_*`, `test_w3_no_literal_zero_*`, `test_w3_new_creators_*`; availability must equal each chart response |
| evidence builder / metric registry text | `test_w3_evidence_explainer_*` (all four explainer fields, every UI metric key) |
| `auth.py` / login page | `test_w3_demo_token_*`, `test_s01_*`; UI: one-click Enter Demo Workspace, Logout in sidebar and header |
| `ChartCard` / EvidenceSheet | Playwright `test_w3_chart_info_*`, `test_w3_evidence_sheet_*` |

Stages in `run_blackbox.ps1`: 1 (batch_1), 2 (+batch_2, batch_bad via S11), 3 (+batch_3: amendment-2 and wave-3 tests),
4 (`late`), `-Ui`, `-Perf`. `-m synth` is run separately against the full synthetic data (not part of the golden run).
