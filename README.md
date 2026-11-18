# darkroom-analytics

A creator-analytics tool for "Northlight", a fictional agency that runs TikTok Shop creator programs for five fictional brands.
No dataset was supplied, so **all data is simulated** by a deterministic script (seed 20261015). File formats are modelled on TikTok Shop field names, not a verified TikTok schema.
The simulated "today" is **2026-10-15, end of day, US Pacific, USD**.

## Where to start reading

| Doc | What it is |
|---|---|
| [docs/context-and-assumptions.md](docs/context-and-assumptions.md) | Step 1: the customer, definitions, assumptions, scope |
| [docs/data-model.md](docs/data-model.md) | Step 2: schema and entity diagram |
| [docs/source-contracts.md](docs/source-contracts.md) | The source file formats |
| [docs/data-quality.md](docs/data-quality.md) | Planted data problems and how ingestion handles each |
| [docs/decisions.md](docs/decisions.md) | Nine assumed customer answers (no customer was available) |
| [docs/rulings-after-verification.md](docs/rulings-after-verification.md) | Decisions made after the independent verification run |
| [docs/PROJECT_EXPLAINER.md](docs/PROJECT_EXPLAINER.md) | Plain-English guide, glossary and field dictionary |
| [docs/DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md) | Plan for hosting (not executed) |
| [data/README.md](data/README.md) | Guide to the generated synthetic datasets (what each file is, its fields and planted issues) |
| [docs/Project_Context_and_Overview.docx](docs/Project_Context_and_Overview.docx) | Project purpose, architecture and the end-to-end pipeline |
| [docs/Schema_Ingestion_and_Data_Quality.docx](docs/Schema_Ingestion_and_Data_Quality.docx) | Schema diagram, how ingestion works, and data-quality rules |

## Demo data in 60 seconds

- Two batches of invented files: `data/synthetic/batch_1` (256 data files plus `manifest.json`, as-of 2026-10-15) and `batch_2` (24 data files plus `manifest.json`, as-of 2026-10-22). Tiny hand-checkable fixtures are in `data/synthetic/golden_cases/`.
- Eight file types: orders, affiliate attribution, refunds, weekly video xlsx, product CSVs, roster, samples tracker, October plans. Folder list, field-by-field dictionary and real example values: [docs/source-contracts.md](docs/source-contracts.md) (section "Demo dataset guide").
- Planted problems (duplicate order pages, late refund, renamed headers, BOM, a rejected file, an overlapping week, a missing-week gap, Excel serial dates, unknown creators) with the exact messages ingestion emits and what the UI shows: [docs/data-quality.md](docs/data-quality.md).

## How data gets in

Data comes from generated files in `data/`, listed by a manifest, not from direct database inserts.

1. **Read** each file. Orders, refunds and videos are per brand; the roster and samples are shared.
2. **Check** it: readable, required columns present, and a hash so the same file is never loaded twice. Overlapping weekly video files are set aside.
3. **Clean** it: types, money as exact decimals, business dates in Pacific time, creator and product matching. A faulty row is left out alone with a plain note; an unreadable file is rejected.
4. **Load** it: Bronze keeps the raw copy, Silver (cleaned tables) is rebuilt in one transaction, and Gold views plus a new data revision appear only when something changed.
5. **Show** it: the API reads Gold only and the screens display it. The UI computes no numbers.

Batches: a later batch can add or update records, the newest update wins, and replaying a batch changes nothing. Brands are kept apart by scope.

- Silver is rebuilt on each change, not updated incrementally.
- The dashboard date comes from a cutoff setting that defaults to the dataset date.
- Non-USD orders are excluded from USD sales.
- Creators not on the roster are shown as unresolved, not dropped.

## How to run it (native Windows, PowerShell)

Prerequisites: Python 3.13, Node 24, PostgreSQL 17 listening on port 5432.

**1. One-time database setup (the app does not create the Postgres role or database; run once as the Postgres superuser):**

```powershell
psql -U postgres -c "CREATE ROLE darkroom LOGIN PASSWORD 'darkroom' CREATEDB;"
psql -U postgres -c "CREATE DATABASE darkroom OWNER darkroom;"
```

The default connection string is `postgresql://darkroom:darkroom@localhost:5432/darkroom`. Override it with the `DATABASE_URL` environment variable.

**2. Backend install**

```powershell
cd F:\Interviews\Darkroom\darkroom-analytics\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**3. Create the tables** (applies migrations 001 to 017: bronze_meta, silver, gold_core, gold_metrics, goal_progress_perf, perf_and_sample_coverage, notes, indexes, gold_mv, gold_charts, rulings_currency_roster_cadence, cadence_coverage_start, issue_brand_backfill, goal_progress_cutoff, goal_progress_video_precision, concentration_zero_samples_unresolved, no_unknown_as_zero):

```powershell
python -m app.cli migrate
```

**4. Ingest batch 1** (as-of 2026-10-15):

```powershell
python -m app.cli ingest ../data/synthetic/batch_1
```

**5. Ingest batch 2** (later delivery). One row of `orders/verdant/2026-10-extra.json` has no order number: that row alone is left out (the file loads, totals show a plain note, the command exits 0). Only a file with no usable rows is rejected (exit 1):

```powershell
python -m app.cli ingest ../data/synthetic/batch_2
echo $LASTEXITCODE
```

Replaying either batch changes no data. Replaying batch 2 exits 0 again with the same note. Other CLI commands: `profile <batch_dir>` and `reset`.

**6. Start the API** (port 8000):

```powershell
uvicorn app.main:app --port 8000
```

**7. Start the frontend** (new terminal, port 3000):

```powershell
cd F:\Interviews\Darkroom\darkroom-analytics\frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

`.env.example` sets `NEXT_PUBLIC_USE_MOCKS=false` (real API at `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`). Set it to `true` to render local mock JSON with no backend.

**8. Open http://localhost:3000.** The login page has no inputs: it shows a notice that the workspace runs on pre-loaded synthetic demo data, and one **Enter Demo Workspace** button (it signs in as `demo` / `darkroom-demo` under the hood). A **Logout** button sits in the sidebar footer and the top bar. Details: [docs/api-contract-amendment-3.md](docs/api-contract-amendment-3.md).

### Tests

- Backend unit tests: `cd backend; python -m pytest tests` (parsers, bulk load, API, charts). Run the three suites below; results of the last verification are in [docs/ai-usage.md](docs/ai-usage.md).
- Blackbox suite (the 14 essential tests and scenarios S1-S20, HTTP and CLI only, run against a golden fixture with hand-written answers in `tests/golden/expected.yaml`): from the repo root run `.\tests\run_blackbox.ps1`. It **drops and recreates the DB schemas**, ingests the golden batches and starts its own API on port 8000, so stop your API first and do not point it at data you want to keep.
- UI test (`tests/blackbox/test_ui_playwright.py`): needs Playwright installed (the backend venv has it) and a running API and frontend (`FRONTEND_URL`); skipped otherwise.
- Data checks: `python scripts/verify_synthetic.py`. Regenerate data: `python scripts/generate_synthetic_data.py`.

## What you can click

Seven routes plus login. Each brand page has five tabs.

| Route or tab | What it shows | Assignment item it covers |
|---|---|---|
| `/overview` | Every brand's October goals: actual, month-end projection, reasoning | Minimum bar 1 (goals vs actuals vs projection), charts |
| `/brands/<brand>` tab Overview & Pacing | The same for one brand, with pacing charts | Minimum bar 1, charts |
| `/creators`, tab Creators & Economics | Videos, sales, refunds, costs, sales after costs; search, filter, sort; saved notes per creator | Minimum bar 2 (rebook, nudge or drop), creator notes |
| `/samples`, tab Samples & Funnel | Sent, delivered, matched to a video or not | Minimum bar 3 |
| `/diagnostics`, tab Diagnostics & Insights | Why a goal is missing: fewer creators posting, weaker videos, or product mix | Goal-miss diagnostics |
| `/attention` | Ranked "act on today" list: quiet retainer creators, samples with no video, missing sources | Needs Attention |
| `/health`, tab Data Health | Fresh, stale or missing status per source, failed files, unresolved identities | Minimum bar 5 |
| Any number, then the Evidence sheet | Definition, formula, exclusions and the source rows | Minimum bar 4 |

## Architecture

Raw files are loaded into Postgres in three layers. Bronze keeps the raw rows untouched. Silver holds typed, cleaned tables. Gold is SQL views that compute every business number. The FastAPI backend reads only Gold. The Next.js UI renders what the API returns: **the UI never computes a number**.

```mermaid
flowchart LR
  F[Batch folder + manifest.json] --> I[CLI ingestion]
  I --> B[(Bronze: raw rows, append-only)]
  B -->|rebuilt in one transaction| S[(Silver: typed, cleaned, quality issues)]
  S --> G[(Gold: SQL views for metrics, freshness, attention)]
  G --> A[FastAPI /api/v1]
  A --> U[Next.js UI]
```

Key rules: money is exact decimal and sent as text; unknown is `null`, never 0 (a missing source gives a status and reason, not a zero); declared coverage comes only from the manifest; refunds count only when completed on or before the cutoff and restate the original order's month; replaying a file is a no-op; every fact row keeps its source file and row number.

## Verified

Results of the last full verification (2026-11-18, clean database reset before each data set; run by an independent verifier agent, not by the code authors):

| Suite | Result |
|---|---|
| Backend unit tests (`backend/tests`) | 68 passed |
| Blackbox, golden fixture, stages 1 to 3 plus late (incl. the faulty-rows and all-bad-file cases) | all passed (stage 3: 12 + 25 + 57 + 67 passed, 1 skipped) |
| Blackbox, synthetic data (`-m "synth or perf"`) | 19 passed (17 data checks, 2 speed checks) |
| Browser tests (Playwright, production build, real API), incl. the plain-English check of the six pages | 31 of 31 passed |
| TypeScript check and production build | clean |
| Tests collected in the root `tests/` suite (with the Playwright-capable Python) | 304 |

After the verification the database was left on the clean synthetic data: 280 files, 3,991 orders, 2 revisions. The Verdant extra orders file now loads with its one faulty record left out (see [docs/api-contract-amendment-4.md](docs/api-contract-amendment-4.md)); the only failed file is the quarantined Threadline weekly video file.

## Done and not done

Done: simulated data with planted problems; Bronze/Silver/Gold ingestion with replay, quarantine and rejection; API with login, evidence, freshness, notes and charts; the screens above; golden fixture and blackbox suite.

Not done:
- Live deployment (plan only in [docs/DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md); Neon, Vercel and Render paths not run).
- Real users, roles or password reset (one demo account).
- Real TikTok data and scheduled file pickup (ingestion is a manual command).

## What I would do next

- Deploy: Vercel for the UI, Render for the API, Neon for the database.
- Sync real TikTok Shop data instead of file drops.
- Load Silver incrementally instead of rebuilding it on every publish.
- Add real authentication with users and roles.
- Add alerts (for example a Slack message when a retainer creator goes quiet).

## How I used AI tools

- Claude Code orchestrated Haiku, Sonnet and Opus subagents in waves: audit, design, build, verify.
- An Opus advisor designed the schema, the API and the test plan; Sonnet workers built separate files against frozen contracts.
- Independent verifier agents found real bugs (a slow view, an ignored refund cutoff, an evidence error), and the fixes took several rounds.
- All numbers are computed in SQL and never by an LLM. The golden expected values were written by hand.
- A human reviews the diffs. AI-written code can still contain mistakes.
- A short log is in [docs/ai-usage.md](docs/ai-usage.md).
