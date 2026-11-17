# Schema and diagram

The diagram below is built from the migrations in `backend/db/migrations/` (`001` to `016`: tables are in `001_bronze_meta`, `002_silver`, `007_notes`; `011` adds `silver.shop_order.currency`; the rest are views, indexes and backfills). The SQL is the source of truth. If this page and the SQL ever disagree, the SQL wins.

Mermaid cannot draw a dot inside a table name, so the diagram writes `silver.order_item` as `silver_order_item`, and so on.

## How the layers fit

- **Bronze** keeps every row of every accepted file exactly as it arrived (`bronze.source_file` is the file, `bronze.source_record` is one row of JSON). Nothing is cleaned here, so any number can be traced back to a file and a row.
- **Silver** is the cleaned, typed version: one table per thing in the business (orders, refunds, videos, samples, goals). Rebuilt from accepted Bronze in one transaction, so a replay changes nothing.
- **Gold** is a set of SQL views over Silver. They hold the metric rules (GMV, net sales, projections, freshness). The API reads only Gold.
- **Meta** holds the control tables: source contracts, ingest runs, dataset revisions and quality issues.

Silver tables use natural keys (the ids the source already has), carry `source_file_id`, `row_num` and `row_hash` for lineage, and link to each other by value, not by database foreign keys. An orphan row (for example an attribution whose order is missing) becomes a `meta.quality_issue`; it is never silently dropped. `NULL` always means unknown, never zero.

## Entity diagram

```mermaid
erDiagram
    bronze_source_file ||--o{ bronze_source_record : "has rows"
    bronze_source_file ||..o{ meta_quality_issue : "may raise"
    meta_ingest_run ||..o{ bronze_source_file : "run_id"

    silver_brand ||..o{ silver_brand_creator : "roster"
    silver_creator ||..o{ silver_brand_creator : "works for"
    silver_creator ||..o{ silver_creator_alias : "known as"
    silver_creator ||..o{ silver_contract : "retainer"
    silver_contract ||..o{ silver_contract_allocation : "split across brands"
    silver_brand ||..o{ silver_contract_allocation : "share"

    silver_brand ||..o{ silver_goal : "monthly goals"
    silver_brand ||..o{ silver_product : "via shop_id"
    silver_brand ||..o{ silver_shop_order : "via shop_id"
    silver_shop_order ||..o{ silver_order_item : "lines"
    silver_product ||..o{ silver_order_item : "sold as"
    silver_order_item ||..o| silver_attribution : "credited to"
    silver_creator ||..o{ silver_attribution : "driver"
    silver_attribution ||..o| silver_commission : "earns"
    silver_order_item ||..o{ silver_refund : "refunded by"

    silver_creator ||..o{ silver_video : "posts"
    silver_video ||..o{ silver_video_snapshot : "weekly metrics"
    silver_video ||..o{ silver_attribution : "content_id"

    silver_creator ||..o{ silver_sample_shipment : "receives"
    silver_sample_shipment ||..o{ silver_sample_item : "contains"
    silver_sample_item }o..o| silver_video : "linked_video_id"

    bronze_source_file {
        bigint source_file_id PK
        text batch_id
        text source_type
        text scope_key
        date coverage_start
        date coverage_end
        text kind "increment or snapshot"
        text sha256 "replay key"
        text parser_version
        text status "accepted, quarantined, rejected"
        timestamptz src_updated_at
    }
    bronze_source_record {
        bigint source_file_id PK
        int row_num PK
        jsonb payload
        text row_hash
    }
    meta_quality_issue {
        bigint issue_id PK
        text code
        text entity_ref
        bigint source_file_id
        int row_num
        text brand_id
        text source_type
        text severity
        text state
        text message
        text origin "file or silver"
    }
    app_creator_note {
        bigint note_id PK
        text brand_id
        text creator_id
        text body
        text author
        timestamptz created_at
        timestamptz deleted_at "soft delete"
    }
    meta_ingest_run {
        bigint run_id PK
        text batch_id
        text status
        int files_failed
    }
    silver_brand {
        text brand_id PK
        text shop_id
        text reporting_tz
        text currency
    }
    silver_creator {
        text creator_id PK
        text handle
    }
    silver_creator_alias {
        text namespace PK
        text alias_norm PK
        date valid_from PK
        text creator_id
        boolean reviewed
    }
    silver_brand_creator {
        text brand_id PK
        text creator_id PK
        text contract_type "retainer or affiliate"
        boolean roster_active
        date effective_from
        date effective_to
    }
    silver_contract {
        text contract_id PK
        text creator_id
        numeric monthly_retainer
        int posts_per_month
        date effective_from
        date effective_to
    }
    silver_contract_allocation {
        text contract_id PK
        text brand_id PK
        numeric share "unknown if missing"
    }
    silver_goal {
        text brand_id PK
        date month PK
        text metric_key PK
        text scope PK
        text basis "gross or net"
        numeric target_value
    }
    silver_product {
        text shop_id PK
        text product_id PK
        numeric list_price
        numeric unit_cost
    }
    silver_shop_order {
        text shop_id PK
        text order_id PK
        timestamptz paid_at
        date paid_local_date
        text status
        boolean is_sample
        timestamptz src_updated_at "newest wins"
        text currency "added in 011; non-USD is excluded from USD GMV"
    }
    silver_order_item {
        text shop_id PK
        text order_id PK
        text line_id PK
        text product_id
        numeric paid_amount
        text item_status
    }
    silver_attribution {
        text shop_id PK
        text affiliate_record_id PK
        text order_id
        text line_id
        text creator_id
        text video_id "null if not linked"
    }
    silver_commission {
        text shop_id PK
        text commission_id PK
        text affiliate_record_id
        numeric amount
        text status "pending or settled"
    }
    silver_refund {
        text shop_id PK
        text refund_id PK
        text line_id PK
        text order_id
        numeric merch_amount "null if unsplit"
        text status
        date completed_local_date
    }
    silver_video {
        text brand_id PK
        text video_id PK
        text creator_id
        text product_id
        date published_local_date
    }
    silver_video_snapshot {
        text brand_id PK
        text video_id PK
        date period_start PK
        date period_end
        bigint views
        int items_sold
    }
    silver_sample_shipment {
        text brand_id PK
        text shipment_id PK
        text creator_id
        date shipped_at
        date delivered_at
        numeric shipping_cost
    }
    silver_sample_item {
        text brand_id PK
        text shipment_id PK
        int line_no PK
        text product_id
        int qty
        text linked_video_id
    }
```

Dotted lines are links by value (no database foreign key). The only real foreign key is the solid line from `bronze.source_record` to `bronze.source_file`.

## Gold views

The Gold views are defined in migrations `003`, `004`, `005`, `006`, `009`, `010`, `011`, `012`, `014`, `015` and `016` (`009` adds the materialized views `gold.mv_sales_line`, `mv_video_activity`, `mv_sample_funnel` and `mv_goal_progress`, which the plain views read; `010` adds the chart views; `011` re-creates several views after the currency and roster rulings; `013` only backfills `brand_id` on quality issues; `007` and `008` add the notes table and indexes). They read Silver (and Meta for freshness). Each one is the single place a metric rule lives:

| View | What it answers |
|---|---|
| `gold.sales_line` | Each order line: is it eligible, its GMV and its refund total. (The API applies the cutoff date when it reads refunds, so a refund only counts once it has completed on or before the date being viewed.) |
| `gold.refund_line`, `gold.commission_line` | Refund and commission rows used as evidence |
| `gold.video_activity` | Each video and whether it qualifies for the month |
| `gold.sample_funnel`, `gold.sample_cost_line` | Each sample item's state, and its cost |
| `gold.creator_performance` | Per creator per month: videos, GMV, refunds, costs |
| `gold.goal_progress` | Per goal: target, actual, projection, required pace and the reasoning text |
| `gold.source_freshness`, `gold.source_coverage` | Current, stale, partial or missing, per brand and source |
| `gold.needs_attention` | Quiet retainer creators, samples with no video, missing sources |
| `gold.unresolved_identity` | Raw creator or product identifiers we could not match |
| `gold.current_as_of` | The simulated "today" |

## App and Meta tables

- `app.creator_note` (migration 007): notes the team saves on a creator (`brand_id`, `creator_id`, `body`, `author`, timestamps, soft delete via `deleted_at`). It lives in its own `app` schema, so a Silver rebuild or `reset` does not erase it (`reset --purge-notes` does).
- `meta.source_contract`: per source type, `kind`, `cadence` and `lag_days`, used for freshness.
- `meta.ingest_run`: one row per ingest (`status`, `files_failed`). `meta.dataset_revision`: a new row only when data changed. `meta.quality_issue`: one row per problem (`code`, `severity`, `state`, `origin` is `file` or `silver`, `brand_id`).

## Keys and replay

- A file is identified by `(source_type, scope_key, coverage_start, coverage_end, sha256, parser_version)`. The same file sent twice is a no-op.
- When two versions of the same order or refund exist, the one with the newest `src_updated_at` wins, whatever order they arrived in.
- Snapshot sources (roster, samples, products, plans) replace the previous snapshot; incremental sources (orders, affiliate orders, returns, weekly videos) only add or update.
