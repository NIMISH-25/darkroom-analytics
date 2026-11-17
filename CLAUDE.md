# Repo conventions (read before editing)

Fictional TikTok Shop creator-analytics prototype for "Northlight". All data is invented. Simulated as-of: **2026-10-15 end of day, US Pacific, USD**. Dev machine: native Windows (PowerShell), Python 3.13, Node 24, Postgres 17.

## Hard rules
- Metrics and chart series are computed ONLY in the backend (SQL gold views + metric layer). The UI never computes, aggregates, or forecasts a number; it renders API values.
- Money is `numeric`/`Decimal`, never float. API sends money as strings.
- Unknown is `NULL`, never zero. Guard SQL `SUM` with `count(*) = count(col)`. Never `COALESCE(x,0)`, `fillna(0)` or `?? 0` on a metric or chart point.
- Ingestion NEVER imports the generator (`scripts/`, `data/`). Tests NEVER import `backend/app`; they use HTTP + CLI only.
- Every fact row keeps its source reference (bronze `source_file_id` + `row_num`).
- Expected values in `tests/golden/expected.yaml` are written by hand and are never edited together with implementation code.
- `notes/` is private and gitignored. Never commit it.

## Ownership (no two workers edit the same file)
| Path | Owner |
|---|---|
| `backend/db/` (migrations 007+, views) | ingestion worker A (SQL) |
| `backend/app/ingestion/`, `backend/app/cli.py`, `backend/app/db.py` | ingestion worker B (bulk load, publish order) |
| `backend/app/api/routes.py`, `backend/app/metrics/{repo,service,memo,conn,cache}.py`, `backend/app/main.py`, `backend/app/settings.py`, `backend/requirements.txt`, `backend/.env.example` | API worker (core: perf, cache, evidence pagination, notes, suggested_action, attention, fixes) |
| `backend/app/api/routes_charts.py`, `backend/app/metrics/charts.py`, `backend/app/metrics/diagnostics.py` | API worker (charts, portfolio, diagnostics) |
| `data/`, `scripts/`, `tests/` | data+tests worker |
| `frontend/` foundation (`src/lib`, `src/components/ui`, `src/components/midday`, layout, shell, routes) | ui worker A |
| `frontend/src/components/charts/` | ui worker B |
| `frontend/src/app/**/page.tsx` for the routes and brand tabs | ui worker C |
| `docs/`, `README.md`, `CLAUDE.md`, `.gitignore` | orchestrator / docs worker |

Contracts (frozen for this build): `docs/db-contract.md` + `docs/db-contract-amendment-2.md`, `docs/source-contracts.md`, `docs/api-contract.md` + `docs/api-contract-amendment-2.md`, `docs/test-plan.md` + `docs/test-plan-amendment-2.md`. If a contract needs an addition for charts, diagnostics, or performance fixes, the orchestrator updates the contract first before workers edit code.

## UI theme, routes, tabs & chart rules (`midday-ai/midday` style)
- Model layout density, typography, and borders after `https://github.com/midday-ai/midday` (`apps/dashboard`):
  - Fonts: `Geist Sans` for prose/labels and `Geist Mono` (`font-mono tabular-nums tracking-tight`) for all currency, counts, percentages, dates, and `data_revision` IDs.
  - Surfaces: monochrome canvas (`#0C0C0C` dark / `#FBFBFB` light), `1px` hairline borders (`border-border`, `divide-x`, `divide-y`), `shadow-none`, sharp geometry (`rounded-none` / `rounded-sm`).
  - Status badges: reserve color strictly for coverage and sample states (`current`/`converted` = emerald, `stale`/`pending` = amber, `incomplete`/`suspect` = orange, `missing`/`failed` = rose, `unknown`/`unassigned` = zinc).
- Separate routes and tabs:
  - Sidebar routes: `/overview`, `/brands/[brandSlug]`, `/attention`, `/creators`, `/samples`, `/diagnostics`, and `/health`.
  - Brand detail tabs (`/brands/[brandSlug]`): `Overview & Pacing`, `Creators & Economics`, `Samples & Funnel`, `Diagnostics & Insights`, and `Data Health`.
- Charts (`shadcn/ui` + Recharts):
  - Plot missing/stale periods as `null` with a hatched SVG overlay (`#missing-data-hatch`) and explicit tooltip status—never plot missing data as `0`.
  - Clicking any KPI value, chart point/bar, or table metric opens the right-hand `EvidenceSheet` pinned to that metric's `data_revision`.

## Performance & coverage invariants
- Zero N+1 queries in metrics, charts, tables, or evidence endpoints; use single-pass SQL CTEs, gold views, and composite indexes.
- Use batched bulk operations during ingestion rather than row-by-row queries.
- All findings from `"independent performance analysis"` and `"independent coverage review vs assignment"` must be resolved and verified via HTTP + CLI tests.

## Run (native Windows)
- DB: native PostgreSQL 17 (no Docker); one-time role/database setup is in `README.md`. Override the port or host with `DATABASE_URL`.
- Default `DATABASE_URL=postgresql://darkroom:darkroom@localhost:5432/darkroom`.
- Backend (from `backend/`): `python -m app.cli migrate`, `python -m app.cli ingest ../data/synthetic/batch_1`, `uvicorn app.main:app --port 8000`.
- Frontend (from `frontend/`): `npm install`, `npm run dev` (port 3000).
- Demo login: `demo` / `darkroom-demo`.