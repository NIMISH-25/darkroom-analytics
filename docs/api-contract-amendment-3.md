# API and UI contract, Amendment 3 (health scoping, chart pruning, readability): FROZEN

This amends `docs/api-contract.md` and `docs/api-contract-amendment-2.md`. Where they differ, this file wins. `CLAUDE.md` is not changed by this amendment.

## 1. Brand-scoped Data Health
Problem found: the Data Health tab showed the same failed files on every brand because `runs()` and `failed_files()` took no brand and were cached under one key.
- `GET /api/v1/data-health?brand_id=<id>`: a brand's files are those whose `scope_key` equals the brand id. Files with one shared scope (the roster and the samples tracker: one file for all brands, `scope_key` `all`, `source_type` `roster` or `samples`) are **shared trackers**. Plans are one file per brand (`scope_key` = the brand id), so they are ordinary brand files, not shared. They appear on every brand with `scope: "shared"` and `source_label: "Shared Cross-Brand Source"`, and they do not count toward the brand's own failure counts. Row-level issues in a shared tracker are scoped to the brand whose row caused them (`meta.quality_issue.brand_id`); an issue with a null `brand_id` is shared. Ingestion sets `brand_id` on every issue it can attribute.
- Response additions: `sources[]` and `failed_files[]` items get `scope: "brand"|"shared"`, `brand_id` (null for shared) and `source_label` (null for brand files). New field `counts: {brand_failed, shared_failed, open_issues}` computed on the server. `runs[]` lists only runs that touched this brand's files or shared files.
- Without `brand_id` (portfolio `/health`): all files; each shared tracker is listed once.
- The cache key includes the brand and the latest run id: `(function, brand_id, last_run_id)`.
- Expected on the seeded data: verdant has exactly one brand failure (orders, rejected), threadline has one (weekly videos, quarantined), aurelle, crunchwell and glowhaus have none.

## 2. Brand chart availability
- `GET /api/v1/brands/{brand_id}/charts/available?month&cutoff` -> `{data_revision, series:[{series_id, status, reason, as_of, point_count}]}`. Every chart response also carries `availability: {status, reason}` from the same classifier.
- `status`, first match wins: `not_applicable` (no retainers, affiliates or samples for this brand, or fewer than 3 creators), `empty` (no points), `unknown` (every value null), `zero` (every non-null value is 0), `stale` (source freshness is breached), otherwise `available`. Periods with no source coverage are null, never 0.
- UI: draw the chart for `available` and `stale` (nulls as gaps with the hatch); for `zero` and `unknown` show a one-line note; draw nothing for `empty` and `not_applicable`. The UI never decides this itself.
- Always shown when available: pacing trajectory and daily GMV vs refunds. Shown only when the data supports it (never chosen by brand name): reconciliation, retainer cadence, creator concentration, sample lag, creator economics.
- Fix: `new_creators` in the chart SQL is the count of creators first seen in the period, or null; it must not be a literal 0.

## 3. Evidence explainer
`GET /api/v1/metrics/{key}/evidence` gains `explainer: {what_it_means, why_it_matters, how_calculated, what_rows_prove}`, plain-English strings built on the server from the metric registry, definition, exclusions and counts (for example how many cancelled orders, pending samples or late refunds were excluded). The UI shows them verbatim in a "What this number means" card at the top of the evidence sheet and computes nothing.

## 4. Chart pruning (UI)
Principle: a chart stays only if it shows something the table beside it cannot; brand pages show one brand's data; portfolio pages show cross-brand comparison.
- `/overview`: keep the portfolio KPI strip, the portfolio pacing chart and the ranked attention strip. Remove the reconciliation chart. Brand cards stay as navigation tiles with name, pace status and coverage badge; remove their goal lists (the KPI strip already shows them).
- `/brands/[brandSlug]` tabs: Overview = KPI strip + pacing + daily GMV vs refunds + reconciliation (when available). Creators = the table only (no economics chart; it duplicated the table). Samples = counts strip + the delivery-to-video lag chart (remove the stage bars; they repeated the counts). Diagnostics = the comparison panel + concentration and retainer cadence when available. Health = the brand-scoped health lists only (no chart).
- `/creators`: the portfolio creator economics chart plus the table. `/samples`: portfolio counts + lag chart. `/diagnostics`: brand selector, comparison panel, and the concentration and cadence charts when available. `/health`: the freshness grid and failures (no chart). `/attention`: queue only.
- Any chart whose availability is `not_applicable` or `empty`, or that would be mostly zero or null, is not drawn.

## 5. Readability and login (UI)
- Base body and table text 14px (`text-sm`), small labels 12px minimum (nothing below `text-xs`), KPI headlines `text-3xl` (`text-4xl` for the main number of a portfolio strip), table rows `h-12`, cell padding `px-4 py-3`, buttons `h-9`, sidebar width 250px, content padding `p-8`.
- Login: no username or password inputs. A notice reads: "This environment runs on pre-loaded synthetic demo data for Northlight's 5 TikTok Shop brands. Use the demo session below to explore the workspace." and a primary **Enter Demo Workspace** button that calls `POST /api/v1/auth/token` with `demo` / `darkroom-demo` under the hood. Backend auth is unchanged.
- Logout: visible **Logout** button in the sidebar footer and in the top header bar; it clears the stored token and returns to `/login`.

## 6. Chart colours (contrast of at least 3.4:1 on white and on dark surfaces no lighter than #18181B)
Actual and actual posts `#2563EB` (solid, `strokeWidth` 2.5, visible dots); projection and expected posts `#C2410C` (dashed); target `#71717A` (dotted); gross GMV `#0072B2`; attributed GMV `#009E73`; refunds `#B5578F`; net sales `#8B5CF6`; status ok `#15803D`, warn or stale `#A16207`, error `#DC2626`, unknown `#71717A` with the hatch. All series are visible at rest (no hover needed).

## 7. Chart info (i) button
Every remaining chart header has an info icon opening a popover with three short parts: what the chart shows; how to read the lines, bars and hatched gaps; what business decision it helps with. `ChartCard` takes `info?: {what: string, how: string, decision: string}`; each chart passes its own copy.
