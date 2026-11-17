# DB contract (Medallion) - FROZEN

Postgres 17 everywhere. Schemas: `bronze`, `silver`, `gold`, `meta`. Migrations are plain SQL files in `backend/db/migrations/NNN_name.sql`, applied in order by `python -m app.cli migrate` (tracked in `meta.schema_migration`). No ORM required (psycopg 3 + SQL).

## Bronze (raw, append-only)
- `bronze.source_file(source_file_id pk, batch_id, source_type, scope_key, coverage_start, coverage_end, kind[increment|snapshot], sha256, parser_version, status[accepted|quarantined|rejected], error, ingested_at, src_updated_at)` with `UNIQUE(source_type, scope_key, coverage_start, coverage_end, sha256, parser_version)` so replay is a no-op. `scope_key` = brand_id or shop_id.
- `bronze.source_record(source_file_id, row_num, payload jsonb, row_hash)` pk(source_file_id,row_num). Original cell/JSON values, unparsed, plus unknown extra columns.

## Silver (typed, normalized; natural-key PKs, no serials)
Every row has `source_file_id`, `row_num`, `row_hash`. NULL = unknown. Cross-source links are soft: orphans become `meta.quality_issue`, never silently dropped.
- `silver.brand(brand_id)`: shop_id, name, reporting_tz, currency
- `silver.creator(creator_id)` (creator_id = TikTok user id); `silver.creator_alias(namespace, alias_norm, valid_from)`: creator_id, reviewed
- `silver.brand_creator(brand_id, creator_id)`: roster_active
- `silver.product(shop_id, product_id)`: name, list_price, unit_cost
- `silver.shop_order(shop_id, order_id)`: paid_at (timestamptz), paid_local_date, status, is_sample, src_updated_at
- `silver.order_item(shop_id, order_id, line_id)`: product_id, paid_amount (numeric, after item discounts, excl tax/shipping), item_status, is_sample
- `silver.attribution(shop_id, affiliate_record_id)`: order_id, line_id, creator_id, video_id?, content_type
- `silver.commission(shop_id, commission_id)`: affiliate_record_id, amount, status[pending|settled]
- `silver.refund(shop_id, refund_id, line_id)`: order_id, merch_amount?, status, completed_at, completed_local_date
- `silver.video(brand_id, video_id)`: creator_id, product_id, published_at
- `silver.video_snapshot(brand_id, video_id, period_start)`: period_end, views, gmv_reported, items_sold, observed_at
- `silver.sample_shipment(brand_id, shipment_id)`: creator_id, delivered_at?, shipped_at, shipping_cost?
- `silver.sample_item(brand_id, shipment_id, line_no)`: product_id, linked_video_id?
- `silver.goal(brand_id, month, metric_key, scope)`: basis[gross|net], definition_version, target_value
- `silver.contract(contract_id)`: creator_id, monthly_retainer, posts_per_month, effective_from, effective_to
- `silver.contract_allocation(contract_id, brand_id)`: share (retainer shared across brands; no allocation => unknown, not full charge)
- `meta.source_contract(source_type)`: kind, cadence, lag_days
- `meta.quality_issue(code, entity_ref, source_file_id)`: severity, state, message
- `meta.dataset_revision(revision_id)`: as_of, created_at, summary
- `meta.ingest_run(run_id)`: started_at, status[succeeded|partial|failed], files_failed

## Gold (SQL views built from row-level views; the only thing the API reads)
`gold.sales_line` (eligible, bucket[resolved|creator_unresolved|none|conflict], gmv, refunded) -> `gold.creator_performance(brand_id, creator_id, month)` -> `gold.goal_progress(brand_id, month, metric_key, scope)` (actual, projection, required_pace, reasoning inputs); `gold.video_activity(qualifies)`, `gold.sample_funnel(matched_video_id, state)`, `gold.source_freshness(brand_id, source_type)(state, coverage_through)`, `gold.needs_attention(brand_id, kind, entity_ref, reason)`. Evidence rows come from the same row-level views as the value, filtered identically.

## Rules
1. Idempotency: replaying a file changes nothing (unique key above). Each publish rebuilds Silver from accepted Bronze in ONE transaction; a new `meta.dataset_revision` is created only if something changed.
2. Version wins by newest `src_updated_at` (snapshots: snapshot_as_of), never by arrival order. Ties that cannot be ordered -> quality_issue `conflict`.
3. Snapshots (roster, samples) deactivate rows missing from the newest snapshot; increments never delete. A weekly video file whose period overlaps an accepted one -> quarantine.
4. Eligible GMV: paid, not sample, item not fully cancelled; sum of `paid_amount`. Refunds with completed_at <= as_of restate the ORIGINAL order's month (cohort view). Cancelled lines are ineligible so nothing is subtracted twice. An unsplit refund (merch amount unknown) -> status partial, value flagged.
5. Business date = event time converted to the brand `reporting_tz` (America/Los_Angeles). Oct 31 23:30 PT counts in October even if UTC is Nov 1. Python on Windows needs `tzdata`.
6. Freshness per (brand, source): `expected_through` = last `period_end` where period_end + lag_days <= as_of. `coverage_through` = contiguous manifest-declared coverage (never the latest event date). Precedence: missing > incomplete (partial/gap/quarantined) > stale (coverage < expected) > suspect (open anomaly) > current. A metric takes the worst state of its sources and the earliest coverage; missing -> value NULL.
7. Unknown stays NULL; aggregates guard with `count(*) = count(col)`. A verified zero requires full coverage.
8. Gold views must not be rebuilt by swapping schemas; migrations use CREATE OR REPLACE VIEW.

## Metric definitions (v1)
- GMV (eligible paid-item) and creator-attributed GMV: see plan sec 5.1. Net = attributed GMV - completed merchandise refunds for those items (cohort).
- Videos: distinct qualifying (brand_id, video_id) published in month (local date). Active creators: distinct creators with >=1 qualifying video in the month; LIVE excluded.
- Projection (GMV, videos): actual through last complete day / elapsed complete days * days in month. Required pace = max(0, target-actual)/remaining days. Unavailable if coverage has gaps. Active creators: median historical completion-curve share (>=3 complete prior months), never below current; else unavailable.
- Sample conversion: unit = delivered sample item; matched when same brand+creator+product video published after delivery and < 30x24h; rate counts mature (>=30 days since delivery), observable items only; recent = pending.
- Creator costs: retainer prorated by effective days / days in month * allocation share; commission from `silver.commission`; sample cost = qty*unit_cost + shipping if known else NULL. `sales_after_costs` = net - known costs, NULL if any required cost is unknown.
- Quiet retainer creator: retainer contract, brand video coverage complete, no video in the last 10 days.

> Amendment 2 (remediation wave): see docs/db-contract-amendment-2.md. It wins where it differs.
