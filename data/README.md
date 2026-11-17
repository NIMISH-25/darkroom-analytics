# Synthetic data (fictional "Northlight" brands, all invented)

Regenerate (deterministic, fixed seed 20261015): `python scripts/generate_synthetic_data.py`
Check against the contract: `python scripts/verify_synthetic.py`. Formats follow `docs/source-contracts.md`
(fictional, modelled on TikTok Shop field names; not a verified TikTok schema).

```
data/synthetic/
  batch_1/            as_of 2026-10-15 (orders/affiliate/returns through 2026-10-14, videos through 2026-10-11)
  batch_2/            as_of 2026-10-22 (increments 2026-10-15..21, W42 videos, planted changes)
  golden_cases/       tiny hand-checkable fixture (see below)
```

Every batch folder has `manifest.json`: `{batch_id, simulated_received_at, as_of, files[{path, source_type, brand_id,
period_start, period_end, kind(increment|snapshot), src_updated_at}]}`. Coverage is declared ONLY there.

## File types and columns
| type | path | columns / keys |
|---|---|---|
| orders | `orders/<brand>/<YYYY-MM>.json` | `{"orders":[{order_id, shop_id, status(UNPAID/AWAITING_SHIPMENT/IN_TRANSIT/DELIVERED/COMPLETED/CANCELLED), create_time, paid_time(null if unpaid), update_time (unix s UTC), is_sample_order, payment{currency,sub_total}, line_items[{id, product_id, sku_id, sale_price, original_price, seller_discount, platform_discount, display_status}]}]}`; money = decimal strings, one line per unit, sample orders all `"0.00"` |
| affiliate_orders | `affiliate_orders/<brand>/<YYYY-MM>.json` | `{"records":[{affiliate_record_id, order_id, line_item_id, creator_user_id, creator_handle, content_id(video id or null), content_type(video/live/showcase), commission_rate, commission_amount, commission_status(pending/settled), update_time}]}` |
| returns | `returns/<brand>/<YYYY-MM>.json` | `{"returns":[{return_id, order_id, line_item_id, return_status(REQUESTED/COMPLETED/REJECTED), refund_subtotal(null=unknown), refund_tax, create_time, completed_time, update_time}]}`; the same `return_id` can appear in a later file with a newer status |
| products | `products/<brand>.csv` | `shop_id,product_id,sku_id,product_name,list_price,unit_cost,update_time` (batch_2 copy has a UTF-8 BOM) |
| videos_weekly | `videos/<brand>/<YYYY>-W<WW>.xlsx` | sheet `Video performance`; rows 1-2 title/period, row 3 header, data, final `Total` row. Header `Video ID, Creator ID, Creator Handle, Post Time, Product ID, Views, GMV, Items Sold` (W42 files use `Video Id`, `Video Views`, `Gross Merchandise Value`). Metrics are for THAT WEEK only, never cumulative |
| roster | `roster/roster.xlsx` | sheet `Roster`: `brand_id, creator_id, handle, contract_type, monthly_retainer, posts_per_month, effective_from, effective_to, status, allocation_share` |
| samples | `samples/samples.xlsx` | sheet `Samples`: `shipment_id, brand_id, creator_id, product_id, qty, shipped_date, delivered_date, status_text(Sent/Delivered/In transit/Returned), shipping_cost, linked_video_id`; a few delivered dates are Excel serial numbers on purpose |
| plans | `plans/<brand>.json` | `{brand_id, month:"2026-10", goals[{metric_key, scope, basis, definition, target}]}` (3 goals) |

## Main dataset scale
76 creators / 86 roster rows (10 creators work for two brands), ~4,000 orders, ~2,800 weekly video rows (~525 videos), 150
sample items, Apr 2026 - Oct 15 2026 (batch_2 to Oct 21). 282 files in batch_1+batch_2.

## Planted scenarios
1. aurelle: order `AUPLANT0918001` ($240 net of discount) has a REQUESTED return in batch_1 (Sep 25) and a COMPLETED $60.00 partial refund (`RET-AU-LATE`) in batch_2 (Oct 17): restates September.
2. verdant: retainer creator `cr_0002` posts nothing after 2026-10-02 while video coverage is complete.
3. crunchwell: `cr_0001` (`@snack.shack.sam`) is affiliate-only, high output and sales, no retainer.
4. threadline: samples converted / pending (recent) / no video (mature) / ambiguous (two identical items, one video) / unresolved creator `cr_0999`.
5. glowhaus: weekly videos for weeks starting 2026-08-31 and 2026-09-07 are never delivered (gap); orders are normal.
Also: duplicated orders across two pages (aurelle 2026-08 and `-page2`), `cr_0007` handle `@mia.makes` -> `@mia.makes.studio` mid-year (same id), an order paid Sep 30 23:30 PT (Oct 1 UTC), unpaid/cancelled orders, a few unresolved affiliate creators (`u_9xxxx`), refunds with null `refund_subtotal`.
Batch 2 changes: threadline order re-sent with newer `update_time` and lower price; aurelle late refund; W42 renamed headers; verdant products CSV with BOM; threadline W41 re-sent with different numbers (overlap, must be quarantined); `orders/verdant/2026-10-extra.json` lacks `order_id` (must be rejected, other files accepted); samples re-sent as a newer snapshot.

## golden_cases (hand-checkable; expected values in `tests/golden/expected.yaml`)
Folders `batch_1` (as_of 2026-10-15), `batch_2` (as_of 2026-11-02), plus `batch_older` (an older version of one order) and
`batch_bad` (one good file + one file missing `order_id`). Same formats as above, so the same columns apply. Note: golden
batch_2 files use one period 2026-10-15..2026-11-01 per source (not strictly monthly).
- aurelle: one $100 order `O_A1` paid 2026-10-05, attributed to `cr_0001` / video `V_A1`; a duplicate copy of order and affiliate record on a "page 2" file; a sample order (all 0.00). Batch 2: $20 merchandise refund completing 2026-10-20 12:00 PT.
- verdant: $50 order `O_B1` paid 2026-10-07, same creator `cr_0001`, video `V_V1`.
- Video `V_A1` appears in two weekly files with per-week values: W40 views 100 / gmv 60.00 / items 3, W41 views 40 / gmv 40.00 / items 2 (total views 100 + 40 = 140; treating a later file as cumulative would give a different total, e.g. 240 by summing 100 and 140). A `Total` row sits in each file and must be skipped.
- crunchwell: order `O_C1` $30.00 (update Oct 9) in batch_1, corrected to $45.00 (update Oct 16) in batch_2; `batch_older` carries a $20.00 version (older update, older `src_updated_at`).
- glowhaus: $40 order Oct 3 in batch_1; order `O_G2` $25 paid 2026-10-31 23:30 PT (= Nov 1 06:30 UTC) in batch_2; weekly video W41 missing (gap).
- threadline: samples GS1-GS5 and videos W33-W43 (one video `V_T1`, creator `cr_0003`, posted 2026-09-05); GS4 uses unknown creator `cr_9999`; GS2 delivered date is an Excel serial.
- aurelle `cr_0002` is a retainer creator whose only video `V_A0` was posted 2026-09-20 (W38 file): zero videos in October (verified zero), last post 25 days before as-of.
- threadline expected sample states: GS1 matched, GS2 no_video, GS3 pending, GS4 no_video (unresolved creator `cr_9999`), GS5 in transit; conversion 1/3.

## golden_cases, amendment 2 (batch_3, batch_4_revision, batch_overlap)
Ingest order: batch_1, batch_2, batch_3. `batch_3` (as_of 2026-11-02) adds September data and new creators without changing
any October value asserted for batch_1/batch_2:
- aurelle Sep: order `O_A3` (line `L_A3_1` $60.00 after discounts, cancelled line `L_A3_2` $40.00), partial refunds $15.00 + $10.00 on
  `L_A3_1` and a $40.00 refund on the cancelled line (must not be deducted), `O_A4` $50.00 attributed to unknown id `u_9001` with look-alike
  handle `@golden.m1a`, `AR_A3` stable id `cr_0001` with new handle `@golden.mia.new`, `O_A5` $30.00 unattributed.
- crunchwell: Sep orders `O_C2..O_C5` ($40/$20/$30/$10), videos `V_C0..V_C5` in weekly files W35-W44 (`V_C2` in two weeks), attribution of `O_C1` to `V_C5`.
- threadline: Sep order `O_T1` (discounts, cents 10.00 + 9.99 + 0.10 + 0.20), EUR order `O_T2`, empty Oct files so Oct is covered.
- roster snapshot v2: `cr_0007`; `cr_0010` dual-brand retainer 3000.00 (aurelle 0.6 / verdant 0.4); `cr_0011` dual-brand retainer 2000.00 without
  `allocation_share`; `cr_0012` threadline retainer 900.00 effective 2026-09-16.
- `batch_4_revision`: one $1.00 verdant order (new `data_revision`; ETag test). `batch_overlap`: aurelle W41 re-sent with different numbers (quarantine).
Expected values with arithmetic: `tests/golden/expected.yaml` (`v2:`).
