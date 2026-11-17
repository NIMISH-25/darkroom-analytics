# Source file contracts - FROZEN (the generator writes these; ingestion reads these)

Fictional, invented formats modelled on TikTok Shop field names. Not a verified TikTok schema. Batches live in `data/synthetic/batch_1/` and `batch_2/`; a tiny hand-checked fixture lives in `data/synthetic/golden_cases/`.

## Brands (fixed)
| brand_id | name | category | shop_id |
|---|---|---|---|
| aurelle | Aurelle Jewelry | jewelry | shop_aurelle |
| verdant | Verdant Skincare | skincare | shop_verdant |
| crunchwell | Crunchwell Snacks | snacks | shop_crunchwell |
| threadline | Threadline Apparel | apparel | shop_threadline |
| glowhaus | Glowhaus Beauty | beauty | shop_glowhaus |
All: `America/Los_Angeles`, USD. Creators: 60-100 total, ids `cr_0001...`, handles like `@mia.makes`; some work for two brands.

## Batch folder
`manifest.json` (required): `{"batch_id":"batch_1","simulated_received_at":"2026-10-15T23:59:59-07:00","as_of":"2026-10-15","files":[{"path":"orders/aurelle/2026-09.json","source_type":"orders","brand_id":"aurelle","period_start":"2026-09-01","period_end":"2026-09-30","kind":"increment","src_updated_at":"2026-10-01T02:00:00Z"}, ...]}`. Declared coverage comes ONLY from the manifest. Files missing from the manifest are ignored with a quality issue; manifest files that don't exist -> `missing`.

source_types and `kind`: `orders`(increment), `affiliate_orders`(increment), `returns`(increment), `products`(snapshot), `videos_weekly`(increment, disjoint weeks, per-week metrics, NOT cumulative), `roster`(snapshot), `samples`(snapshot), `plans`(snapshot).

## Files
- **orders** `orders/<brand_id>/<YYYY-MM>.json`: `{"orders":[{"order_id","shop_id","status"(UNPAID|AWAITING_SHIPMENT|IN_TRANSIT|DELIVERED|COMPLETED|CANCELLED),"create_time":<unix seconds UTC>,"paid_time":<unix|null>,"update_time":<unix>,"is_sample_order":bool,"payment":{"currency":"USD","sub_total":"123.45"},"line_items":[{"id","product_id","sku_id","sale_price":"24.00","original_price":"30.00","seller_discount":"6.00","platform_discount":"0.00","display_status"(AWAITING_SHIPMENT|DELIVERED|CANCELLED...)}]}]}`. `sale_price` is the buyer-paid item amount after discounts (one row per unit). Money = decimal strings. Sample orders have all amounts `"0.00"`.
- **affiliate_orders** `affiliate_orders/<brand_id>/<YYYY-MM>.json`: `{"records":[{"affiliate_record_id","order_id","line_item_id","creator_user_id","creator_handle","content_id"(video_id|null),"content_type"(video|live|showcase),"commission_rate":"0.12","commission_amount":"2.88","commission_status"(pending|settled),"update_time"}]}`. At most one record per line item.
- **returns** `returns/<brand_id>/<YYYY-MM>.json`: `{"returns":[{"return_id","order_id","line_item_id","return_status"(REQUESTED|COMPLETED|REJECTED),"refund_subtotal":"12.00"|null,"refund_tax","create_time","completed_time"|null,"update_time"}]}`. A refund can complete weeks after the order, in a later file.
- **products** `products/<brand_id>.csv` (UTF-8, header): `shop_id,product_id,sku_id,product_name,list_price,unit_cost,update_time`.
- **videos_weekly** `videos/<brand_id>/<YYYY>-W<WW>.xlsx`: sheet `Video performance`; rows 1-2 are title/period text, row 3 is the header, data follows, a final `Total` row must be skipped. Header (batch 1): `Video ID, Creator ID, Creator Handle, Post Time, Product ID, Views, GMV, Items Sold`. Metrics are for that week only. `Post Time` is an ISO local-time string. Batch 2 uses header variants (`Video Id`, `Video Views`, `Gross Merchandise Value`) and a UTF-8 BOM in any CSV; the backend keeps header aliases in `backend/app/ingestion/header_aliases.yaml`. An unknown header -> quarantine the file, continue the batch.
- **roster** `roster/roster.xlsx`: sheet `Roster`: `brand_id, creator_id, handle, contract_type (retainer|affiliate), monthly_retainer, posts_per_month, effective_from, effective_to, status`. A creator with two brands has two rows; `monthly_retainer` is the total and `allocation_share` (optional column) splits it; missing share on a multi-brand retainer = unknown allocation.
- **samples** `samples/samples.xlsx`: sheet `Samples`: `shipment_id, brand_id, creator_id, product_id, qty, shipped_date, delivered_date, status_text (Sent|Delivered|In transit|Returned), shipping_cost, linked_video_id`. Dates are ISO `YYYY-MM-DD` or (in a few rows, on purpose) Excel serial numbers. `linked_video_id` is mostly blank.
- **plans** `plans/<brand_id>.json`: `{"brand_id","month":"2026-10","goals":[{"metric_key":"gmv|videos|active_creators","scope":"creator_attributed|shop","basis":"gross|net","definition":"text","target":number}]}`. 3 goals per brand; at least one brand has a shop-wide GMV goal.

## Time and coverage
- Orders/affiliate/returns: monthly files Apr-Sep 2026 plus October covering 2026-10-01..2026-10-14 (complete through the 14th; lag 1 day).
- Weekly video files: Monday-start ISO weeks Apr 2026..week containing Oct 12 (Oct 12-18 NOT yet complete); coverage ends 2026-10-11.
- History: April to September 2026 plus October to the 15th. A few thousand orders, a few hundred videos, ~150 sample items, 100-300 files in total.

## Planted scenarios (must be computable from the files, never hardcoded in the UI)
1. aurelle (jewelry): a late partial refund (in batch 2) restates an earlier month's net.
2. verdant (skincare): a retainer creator posts nothing for 10+ days while video coverage is complete.
3. crunchwell (snacks): an affiliate-only creator has strong output and sales, no retainer.
4. threadline (apparel): samples include converted, pending, and an ambiguous match.
5. glowhaus (beauty): two weekly video files are missing (gap) so video metrics are stale/incomplete, orders look normal.
Plus: a duplicated order across two pages; creator handle changes mid-year with the same creator id; the Oct 31 23:30 PT timezone boundary order (in a September-to-October golden case only if dates allow; otherwise in the golden fixture).

## Batch 2 (must NOT silently match batch 1)
A changed order (newer `update_time`), a late refund completing after batch 1, a renamed header, a missing required field in one file (must be rejected/reported, others accepted), and an overlapping weekly file (quarantined).

---

# Demo dataset guide (inventory and field dictionary)

Added after the data was generated. Checked against the real files in `data/synthetic/`. Everything is invented. Regenerate with `python scripts/generate_synthetic_data.py` (fixed seed 20261015); `scripts/golden_cases.py` and `scripts/golden_v2.py` build `golden_cases/`. Planted problems and how ingestion treats them are in `docs/data-quality.md`.

## 1. File inventory

Brands: `aurelle`, `verdant`, `crunchwell`, `threadline`, `glowhaus`. Counts are files listed in each manifest.

### `data/synthetic/batch_1` (as_of 2026-10-15, received 2026-10-15T23:59:59-07:00, 256 files)
| Source | Folder and pattern | Files | Period | Kind | Brands |
|---|---|---|---|---|---|
| Orders | `orders/<brand>/<YYYY-MM>.json` (aurelle also `2026-08-page2.json`) | 36 | 2026-04-01 to 2026-10-14 | increment | all 5 |
| Affiliate attribution | `affiliate_orders/<brand>/<YYYY-MM>.json` | 35 | 2026-04-01 to 2026-10-14 | increment | all 5 |
| Refunds (returns) | `returns/<brand>/<YYYY-MM>.json` | 35 | 2026-04-01 to 2026-10-14 | increment | all 5 |
| Weekly video performance | `videos/<brand>/<YYYY>-W<WW>.xlsx` | 138 (28 per brand, glowhaus 26) | 2026-03-30 to 2026-10-11 | increment | all 5 |
| Product catalogs | `products/<brand>.csv` | 5 | 2026-04-01 to 2026-10-15 | snapshot | all 5 |
| Creator roster and contracts | `roster/roster.xlsx` | 1 | 2026-04-01 to 2026-10-15 | snapshot | all (shared file) |
| Samples tracker | `samples/samples.xlsx` | 1 | 2026-04-01 to 2026-10-15 | snapshot | all (shared file) |
| October plans | `plans/<brand>.json` | 5 | 2026-10-01 to 2026-10-31 | snapshot | all 5 |

### `data/synthetic/batch_2` (as_of 2026-10-22, received 2026-10-22T23:59:59-07:00, 24 files)
| Source | Folder and pattern | Files | Period | Kind | Brands |
|---|---|---|---|---|---|
| Orders | `orders/<brand>/2026-10.json` plus `orders/verdant/2026-10-extra.json` | 6 | 2026-10-15 to 2026-10-21 | increment | all 5 |
| Affiliate attribution | `affiliate_orders/<brand>/2026-10.json` | 5 | 2026-10-15 to 2026-10-21 | increment | all 5 |
| Refunds | `returns/<brand>/2026-10.json` | 5 | 2026-10-15 to 2026-10-21 | increment | all 5 |
| Weekly videos | `videos/<brand>/2026-W42.xlsx` plus `videos/threadline/2026-W41.xlsx` | 6 | 2026-10-05 to 2026-10-18 | increment | all 5 |
| Product catalog | `products/verdant.csv` | 1 | 2026-04-01 to 2026-10-22 | snapshot | verdant |
| Samples tracker | `samples/samples.xlsx` (newer snapshot, 150 items) | 1 | 2026-04-01 to 2026-10-22 | snapshot | all |

Batch 2 has no roster and no plans.

### `data/synthetic/golden_cases` (small, hand-checkable; answers in `tests/golden/expected.yaml`)
| Folder | as_of | Files | Contents |
|---|---|---|---|
| `batch_1` | 2026-10-15 | 42 | orders (5, with a page 2), affiliate (5), returns (4), products (5), weekly videos (16), roster, samples (threadline), plans (5) |
| `batch_2` | 2026-11-02 | 25 | orders (4), affiliate (4), returns (4), products (crunchwell), weekly videos (12) |
| `batch_3` | 2026-11-02 | 27 | September-to-November orders (5), affiliate (6), returns (5), crunchwell weekly videos (10), roster v2 |
| `batch_4_revision` | 2026-11-02 | 1 | one $1.00 verdant order |
| `batch_older` | 2026-10-15 | 1 | an older version of crunchwell order `O_C1` |
| `batch_bad` | 2026-11-02 | 2 | a good returns file and a verdant order file missing `order_id` |
| `batch_overlap` | 2026-11-02 | 1 | aurelle W41 resent |

## 2. Manifest (`manifest.json`, one per batch)

Top level: `batch_id` (text, `batch_1`), `simulated_received_at` (ISO datetime with offset, `2026-10-15T23:59:59-07:00`), `as_of` (date, the freshness yardstick, `2026-10-15`), `files` (list). Grain: one entry per file. Declared coverage comes only from here.

| Field | Type | Meaning | Example |
|---|---|---|---|
| `path` | text | file path relative to the batch folder | `orders/aurelle/2026-04.json` |
| `source_type` | text | `orders`, `affiliate_orders`, `returns`, `products`, `videos_weekly`, `roster`, `samples`, `plans` | `orders` |
| `brand_id` | text | brand, or `all` for the shared roster and samples | `aurelle` |
| `period_start`, `period_end` | date | coverage the file declares (inclusive) | `2026-04-01`, `2026-04-30` |
| `kind` | text | `increment` adds rows for a period; `snapshot` is the full current picture | `increment` |
| `src_updated_at` | ISO datetime (UTC) | when the source last changed the file; newest wins | `2026-05-01T02:00:00Z` |

## 3. Field dictionary

Types: text, integer, decimal string (money, exact), number, boolean, date, unix seconds (UTC), nullable (null or blank means unknown). Examples are from real rows.

### 3.1 Orders: `{"orders":[...]}`, grain one order; `line_items` is one row per unit
| Field | Type | Meaning | Example |
|---|---|---|---|
| `order_id` | text | order key | `AU8391939898` |
| `shop_id` | text | the brand's shop | `shop_aurelle` |
| `status` | text | UNPAID, AWAITING_SHIPMENT, IN_TRANSIT, DELIVERED, COMPLETED, CANCELLED | `COMPLETED` |
| `create_time` | unix seconds | order placed | `1788327242` |
| `paid_time` | unix seconds, nullable | paid; null if unpaid. Sets the business date (Los Angeles) | `1788327362` |
| `update_time` | unix seconds | last change; newest version wins | `1789209242` |
| `is_sample_order` | boolean | free sample order; excluded from GMV | `false` |
| `payment.currency` | text | `USD` (one `EUR` order exists in golden batch_3) | `USD` |
| `payment.sub_total` | decimal string | order subtotal, informational | `"48.00"` |
| `line_items[].id` | text | line key | `AU8391939898-1` |
| `line_items[].product_id` | text | product | `P_AUR_1` |
| `line_items[].sku_id` | text | variant | `SKU_AUR_1` |
| `line_items[].sale_price` | decimal string | buyer-paid amount after discounts; summed into GMV | `"48.00"` |
| `line_items[].original_price` | decimal string | price before discounts | `"48.00"` |
| `line_items[].seller_discount` | decimal string | brand-funded discount | `"0.00"` |
| `line_items[].platform_discount` | decimal string | platform-funded discount | `"0.00"` |
| `line_items[].display_status` | text | item state; CANCELLED is ineligible | `COMPLETED` |

### 3.2 Affiliate attribution: `{"records":[...]}`, grain one order line (at most one record per line)
| Field | Type | Meaning | Example |
|---|---|---|---|
| `affiliate_record_id` | text | key | `AFF-AUR-00315` |
| `order_id` | text | order credited | `AU5631277470` |
| `line_item_id` | text | line credited | `AU5631277470-1` |
| `creator_user_id` | text | creator id (`cr_0001`...; `u_9xxxx` is an unknown creator) | `u_90015` |
| `creator_handle` | text | handle at that time | `@ghost.shop` |
| `content_id` | text, nullable | video that drove the sale | `null` |
| `content_type` | text | `video`, `live` or `showcase` | `showcase` |
| `commission_rate` | decimal string | share paid | `"0.10"` |
| `commission_amount` | decimal string | commission in USD | `"7.00"` |
| `commission_status` | text | `pending` or `settled` | `settled` |
| `update_time` | unix seconds | last change | `1788831181` |

### 3.3 Refunds: `{"returns":[...]}`, grain one return per order line
| Field | Type | Meaning | Example |
|---|---|---|---|
| `return_id` | text | key; the same id can reappear in a later file with a newer status | `RET-AU-LATE` |
| `order_id`, `line_item_id` | text | original order and line | `AUPLANT0918001`, `AUPLANT0918001-1` |
| `return_status` | text | REQUESTED, COMPLETED, REJECTED | `COMPLETED` |
| `refund_subtotal` | decimal string, nullable | merchandise refunded; null means not split out | `"60.00"` |
| `refund_tax` | decimal string, nullable | tax refunded, not counted | `null` |
| `create_time` | unix seconds | request time | `1790355600` |
| `completed_time` | unix seconds, nullable | completion; must be on or before the cutoff to count | `1792260000` |
| `update_time` | unix seconds | last change | `1790355600` |

### 3.4 Weekly video performance: `videos/<brand>/<YYYY>-W<WW>.xlsx`, sheet `Video performance`
Rows 1-2 are title and period text, row 3 is the header, then data, then a final `Total` row (skipped). Grain: one video per week. Numbers are for that week only, never running totals. Row 1 example: `Video performance - Aurelle Jewelry - 2026-W40`; row 2: `Period: 2026-09-28 to 2026-10-04 (metrics for this week only)`.

| Column | Type | Meaning | Example |
|---|---|---|---|
| `Video ID` (drift: `Video Id`) | text | video key | `70000031` |
| `Creator ID` | text | creator | `cr_0018` |
| `Creator Handle` | text | handle | `@ava.vibes` |
| `Post Time` | ISO local-time text | publish time | `2026-08-24T20:11:20` |
| `Product ID` | text | product promoted | `P_AUR_3` |
| `Views` (drift: `Video Views`) | integer | views that week | `135` |
| `GMV` (drift: `Gross Merchandise Value`) | number | platform-reported sales that week; reported only | `50.4` |
| `Items Sold` | integer | units that week | `2` |

### 3.5 Product catalog: `products/<brand>.csv` (UTF-8, header row), grain one SKU
| Column | Type | Meaning | Example |
|---|---|---|---|
| `shop_id` | text | shop | `shop_aurelle` |
| `product_id` | text | product | `P_AUR_1` |
| `sku_id` | text | variant | `SKU_AUR_1` |
| `product_name` | text | name | `Gold Hoop Earrings` |
| `list_price` | decimal string | normal price | `48.00` |
| `unit_cost` | decimal string | cost of one unit; sample cost is qty x unit_cost | `16.80` |
| `update_time` | unix seconds | snapshot ordering | `1759300000` |

### 3.6 Creator roster and contracts: `roster/roster.xlsx`, sheet `Roster`, grain one creator per brand
Batch 1 has 86 rows.

| Column | Type | Meaning | Example |
|---|---|---|---|
| `brand_id` | text | brand | `verdant` |
| `creator_id` | text | creator | `cr_0002` |
| `handle` | text | handle | `@dewy.dana` |
| `contract_type` | text | `retainer` or `affiliate` | `retainer` |
| `monthly_retainer` | number, nullable | total monthly fee across brands | `800` |
| `posts_per_month` | integer, nullable | expected posts | `4` |
| `effective_from`, `effective_to` | date text; `effective_to` nullable | contract dates | `2026-01-19`, blank |
| `status` | text | `active` or `paused` | `active` |
| `allocation_share` | number, nullable | brand's share of a shared retainer; blank on a multi-brand retainer means unknown | `0.5` |

### 3.7 Samples tracker: `samples/samples.xlsx`, sheet `Samples`, grain one shipment line
Batch 1 has 148 rows, batch 2 has 150.

| Column | Type | Meaning | Example |
|---|---|---|---|
| `shipment_id` | text | key | `SHP-AUR-001` |
| `brand_id` | text | brand | `aurelle` |
| `creator_id` | text | recipient | `cr_0006` |
| `product_id` | text | product sent | `P_AUR_3` |
| `qty` | integer | units | `1` |
| `shipped_date` | date text | sent | `2026-06-01` |
| `delivered_date` | date text, Excel serial number or blank | delivered; starts the 30-day window | `2026-06-04`, or `46221` |
| `status_text` | text | Sent, Delivered, In transit, Returned | `Delivered` |
| `shipping_cost` | decimal text, nullable | postage | `8.43` |
| `linked_video_id` | text, nullable | video the team recorded; mostly blank | `70000101` |

### 3.8 October plans: `plans/<brand>.json`, grain one brand-month with three goals
| Key | Type | Meaning | Example |
|---|---|---|---|
| `brand_id` | text | brand | `aurelle` |
| `month` | text `YYYY-MM` | plan month | `2026-10` |
| `goals[].metric_key` | text | `gmv`, `videos`, `active_creators` | `gmv` |
| `goals[].scope` | text | `creator_attributed` or `shop` | `shop` |
| `goals[].basis` | text | `gross` or `net` | `gross` |
| `goals[].definition` | text | plain-text definition | `Shop-wide paid-item GMV for the month` |
| `goals[].target` | number | target | `14000` |
