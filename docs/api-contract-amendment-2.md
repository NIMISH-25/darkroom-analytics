# API contract, Amendment 2 (remediation wave): FROZEN

This amends `docs/api-contract.md`. Where they differ, this file wins.

Shared rules: new routes are GET + Bearer except the notes POST; money is a string; null = unknown; the UI never computes or aggregates. Route modules: charts, portfolio and diagnostics live in `backend/app/api/routes_charts.py` and `backend/app/metrics/charts.py` / `diagnostics.py`; everything else stays in `routes.py` and `service.py` / `repo.py`.

## Chart series
`GET /api/v1/brands/{brand_id}/charts?series=<name>&month=YYYY-MM&cutoff=YYYY-MM-DD&metric=gmv|videos|active_creators` and `GET /api/v1/portfolio/charts?series=<name>&...` (all brands; `brand_id: null`; per-creator points add `brand_id`). Series: `pacing_trajectory`, `daily_gmv_refunds`, `attribution_reconciliation`, `sample_funnel_lag`, `creator_concentration`, `retainer_cadence`.

Envelope: `{series, brand_id, month, cutoff, data_revision, definition_version, coverage_through, status, status_reason, units:{field:unit}, meta:{...}, points:[{x, <fields>, status, status_reason, evidence_urls:{field:url}}]}`. Every x in the domain is emitted. Point `status` is the MetricValue status enum plus `forecast` (x after the cutoff; drawn unhatched). Missing or stale points carry null values and a status; the UI hatches them and never plots 0.

- `pacing_trajectory`: x = each day of the month. Fields `actual` (cumulative; null from the first coverage gap), `projection` and `required` (both start at the cutoff). `meta` = `{basis, target, projection, required_pace}` as MetricValues.
- `daily_gmv_refunds`: x = day. Fields `gmv`, `creator_attributed_gmv`, `attributed_refunds_cohort`, `attributed_refunds_processed`, `net_attributed_sales` (attributed minus cohort refunds).
- `attribution_reconciliation`: x in `resolved|creator_unresolved|none|conflict`. Fields `amount`, `order_items`, `pct` (largest-remainder rounding; sums to 1). The buckets sum to eligible shop GMV.
- `sample_funnel_lag`: points `{group: "stage"|"lag", x, count}`. Stages `sent, delivered, mature` plus the partition `in_transit, pending, converted, no_video_mature, unknown` (sums to sent); lag buckets `0-7, 8-14, 15-21, 22-30` (sum to converted). Must equal the `/brands/{id}/samples` counts.
- `creator_concentration`: x = rank (gross GMV descending, then creator_id). Fields `creator_id, handle, gmv, share, cum_creator_pct, cum_gmv_pct`; `meta.unresolved_gmv`.
- `retainer_cadence`: x = YYYY-MM (the trailing 3 complete months). Fields `creator_id, handle, expected_posts` (prorated string), `posts`, `attainment_pct`; null when there is a coverage gap or expected is zero.

Portfolio form: sums use the guard `count(*) = count(col)`; ratios are pooled; distinct counts are deduplicated. Evidence for chart points uses `GET /api/v1/metrics/{key}/evidence` with new filters `date_from, date_to, bucket, stage`, and kind `decomposition`.

## Portfolio KPIs
`GET /api/v1/portfolio/kpis` -> `{data_revision, kpis:[{metric_key, value, baseline, delta, delta_pct, brands_covered, brands_total}], pace_counts:{on_track, at_risk, off_track, unknown}}`; value, baseline, delta and delta_pct are MetricValues. The portfolio mixes gross and net goal bases; `status_reason` says so.

## Diagnostics ("where it broke")
`GET /api/v1/brands/{brand_id}/diagnostics?month&cutoff` compares the current period (1st to the cutoff) with the same days of the previous month (Oct 1-15 vs Sep 1-15). Response: `{periods, method, status, disclaimer, total:{baseline,current,delta}, factors:[{key, baseline, current, effect}], unlinked_older_gmv:{baseline,current,delta}, products:[{product_id, name, gmv_baseline, gmv_current, delta, observation}]}`.
Linked GMV = A x V x G, where A = active creators, V = videos per active creator, G = attributed GMV per linked video. Method: Shapley (six-order averaged substitution). `effect_A = dA * [(V0*G0 + V1*G1)/3 + (V0*G1 + V1*G0)/6]`, and the other two factors are symmetric; the result is exact and safe with zeros. Any null input, or A = 0, makes the effects null. A cent residual goes to the largest effect. Check: sum of effects + change in `unlinked_older_gmv` = change in `total`. `disclaimer` states that this is a decomposition with context, not proof of cause.

## Creator notes
`POST /api/v1/brands/{brand_id}/creators/{creator_id}/notes` with body `{body}` (trimmed, 1 to 2000 characters, plain text) -> 201 `{note_id, brand_id, creator_id, author, body, created_at}`; author is the token's user. `GET` on the same path -> `{items:[...], total_count}`, newest first. Append-only. Notes never change `data_revision`. Stored in `app.creator_note`.

## Evidence pagination
`GET /api/v1/metrics/{key}/evidence` accepts `limit` (default 100, 1 to 500, otherwise 422) and `offset`; the response adds `total_count, limit, offset, next_offset`. `result`, `calculation` and `exclusions` cover ALL rows; only `records` are paginated, ordered by `(source_file, row_num)`. `revision` is still required (409 `refresh_required` on mismatch).

## Creator decision support and attention
- Each creator row gets `suggested_action: {action, rule, status, status_reason}`. `action` is one of `review|nudge|upgrade|rebook|watch`; first match in this order: review (any needed input is null), nudge, upgrade, rebook, watch. `rule` is the human-readable rule shown next to it.
- `/attention` items gain `rank, impact_score, impact_basis` (USD exposure: retainer fee x quiet-day share, sample cost, GMV target x blind-day share), ranked across brands with nulls last.

## Performance contract
- Responses are cached in-process keyed by `(revision_id, revision created_at, route, params)`, with a strong `ETag` and `Cache-Control: private, no-cache`; `If-None-Match` returns 304. A new revision clears the cache. Never cache 401, 409, errors, notes or health. Revision and data are read in one REPEATABLE READ transaction; the cache lookup happens after authentication. The API exposes `warm()` (default month and cutoff for overview, creators and charts), called at startup and by the CLI after an ingest.
- GZip middleware; no per-creator Python loops (group rows once); freshness and brand lookups cached per revision.
- `DATABASE_URL` default is `postgresql://darkroom:darkroom@localhost:5432/darkroom` (port 5432). Update `settings.py`, `db.py`, `backend/.env.example` and `tests/run_blackbox.ps1`.

## Frontend routes (UI contract)
Sidebar: `/overview`, `/brands/[brandSlug]` (tabs synced to the URL with `?tab=`: `overview`, `creators`, `samples`, `diagnostics`, `health`), `/attention`, `/creators`, `/samples`, `/diagnostics`, `/health`. `brandSlug` equals `brand_id`. Default `NEXT_PUBLIC_USE_MOCKS=false` in both `.env.example` and `.env.local`.

## Progress ratio (added so the UI never divides)
Every goal in `/overview` (`goals[]`) and every item in `/portfolio/kpis` that has a target gets `progress`: a MetricValue (`unit: "ratio"`) equal to actual divided by target, capped for display at `1.5`, null (with status) when actual or target is unknown. The KPI strip bar width is drawn from this value only; the UI performs no division.
Chart components take props `{brandId: string | null, month?: string, cutoff?: string}` and load their own data through the hooks in `frontend/src/lib/hooks.ts`.

## Two more chart fields (so the UI never derives them)
- `creator_concentration` series `meta` gains `top10_gmv_share` and `top20_gmv_share` (strings, percent to one decimal, or null when unknown): the share of attributed GMV held by the top 10% and top 20% of creators. The UI marks these on the curve from `meta`.
- `sample_funnel_lag` stage points gain `pct_of_sent` (string percent to one decimal, null when sent is 0 or unknown) and lag points gain `pct_of_converted`.
