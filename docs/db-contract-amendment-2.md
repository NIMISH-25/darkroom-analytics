# DB contract, Amendment 2 (remediation wave): FROZEN

This amends `docs/db-contract.md`. Where they differ, this file wins.

**Rule 8 amended.** Plain views still use `CREATE OR REPLACE VIEW`. Materialized views cannot; migrations drop and recreate them in dependency order. Public view names never change; the public views wrap the materialized ones.

## Migrations (new; never edit applied ones)
- `007_notes.sql`: `app.creator_note(note_id bigint generated always as identity primary key, brand_id text not null, creator_id text not null, body text not null, author text not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(), deleted_at timestamptz)`. Schema `app`. No foreign keys to Silver. Rerunnable DDL (`if not exists`). Survives every Silver rebuild and `reset`; add `reset --purge-notes` to drop it.
- `008_indexes.sql`: `silver.shop_order(shop_id, paid_local_date)`, `silver.refund(shop_id, completed_local_date)`, `silver.video(brand_id, published_local_date)`, `silver.order_item(shop_id, order_id)`, `silver.attribution(shop_id, order_id, line_id)`, `silver.attribution(creator_id)`, `silver.video(brand_id, creator_id)`, `silver.sample_shipment(brand_id, creator_id)`, and provenance `(source_file_id, row_num)` on every Silver fact table.
- `009_gold_mv.sql`: materialized `gold.mv_sales_line`, `gold.mv_video_activity`, `gold.mv_sample_funnel`, `gold.mv_goal_progress` (they depend on the dataset revision, not on the request). The public views `gold.sales_line`, `gold.video_activity`, `gold.sample_funnel`, `gold.goal_progress` keep their names and columns and read the materialized ones. Cutoff-dependent logic (refunds up to the request cutoff, projections) stays computed per request. Indexes: unique `mv_sales_line(shop_id, order_id, line_id)` and `(brand_id, month, order_id, line_id)`; filter `month = date`, never `month::text LIKE`. Creates SQL function `gold.refresh_materialized()` that refreshes them in dependency order.
- `010_gold_charts.sql`: plain views for the chart series (below), including `gold.creator_concentration` and `gold.retainer_cadence` (drafts in `verification-output/analysis/*.sql`; use `create or replace`, since the drafts may already exist in a dev database).

## Publish transaction (`ingestion/batch.py`)
`rebuild_silver` -> compute digest -> if changed: insert `meta.dataset_revision` -> `select gold.refresh_materialized()` -> commit. The revision insert comes first because the materialized views read `gold.current_as_of`. Run `ANALYZE` (including the materialized views) after commit. A replay creates no revision.

## Bulk ingestion
`bronze.source_file` insert uses `ON CONFLICT DO NOTHING RETURNING` (the unique index is NULLS NOT DISTINCT); no row returned means a replay. `bronze.source_record` is loaded with `COPY`. Silver: `COPY` into a temp table, then `INSERT ... SELECT DISTINCT ON (natural key) ... ORDER BY src_updated_at DESC ... ON CONFLICT`. Alias and identity maps are prefetched once per batch (no per-row SELECT).

## Chart views (migration 010). All are brand_id and cutoff aware, NULL = unknown, no COALESCE to zero
- `gold.chart_daily(brand_id, day, gross_gmv, creator_attributed_gmv, refunds_cohort, refunds_processed, status)`: one row per brand per day of the month; days outside source coverage have NULLs and a status. The API applies the cutoff to refunds per request.
- `gold.chart_reconciliation(brand_id, month, bucket[resolved|creator_unresolved|none|conflict], amount, order_items)`: the four buckets sum to eligible shop GMV.
- `gold.chart_sample_funnel(brand_id, stage, lag_bucket, count)`: stages sent, delivered, mature, in_transit, pending, converted, no_video_mature, unknown (the partition sums to sent); lag buckets 0-7, 8-14, 15-21, 22-30 sum to converted.
- `gold.creator_concentration(brand_id, rank, creator_id, handle, gross_gmv, share, cum_creator_pct, cum_gmv_pct, net_sales, unresolved)`: Lorenz curve of gross attributed GMV per brand; roster creators with no sales appear with zero only when sales coverage is complete.
- `gold.retainer_cadence(brand_id, creator_id, handle, month, expected_posts, posts, attainment_pct, retainer_allocated, n_gaps, coverage_through)`: `posts` and `attainment_pct` are NULL unless the brand's weekly video coverage is gap-free and reaches month end.
- `gold.diagnostic_period(brand_id, period, active_creators, videos, linked_videos, linked_gmv, unlinked_older_gmv, product_id, product_gmv, coverage_status)`: current period (1st to cutoff) and baseline (same days of the previous month). The API does the decomposition arithmetic with Decimal from these numbers.

## Why these two extra charts (data analysis of the full synthetic set, cutoff 2026-10-15)
- **Revenue concentration:** the top 10% of creators bring 64% of Crunchwell's attributed GMV, against 32% at Aurelle, 30% at Glowhaus, 31% at Threadline and 30% at Verdant (values read from the running app at cutoff 2026-10-15; basis: all months through the cutoff). It shows which brands depend on a handful of creators.
- **Retainer delivery vs contract:** across July to September, retainer creators averaged 35 to 43% of their contracted posts (Verdant 42.5%, Crunchwell 36.8%, Aurelle 36.5%, Threadline 34.7%); Glowhaus is unknown because its weekly video coverage has gaps. It shows which retainers to chase or renegotiate. The generator sets the posting rates, so treat the exact percentages as simulated.
