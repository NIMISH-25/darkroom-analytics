# Project Explainer (plain-language guide)

All data in this project is invented. The fictional company is "Northlight", an agency that runs creator (influencer) programs for five fictional TikTok Shop brands. The simulated "today" is **2026-10-15, end of day, US Pacific time, in US dollars** (batch 2 is a later delivery whose manifest says as-of 2026-10-22).

## 1. What the tool is and who it is for

**What it is.** A small web app that answers one question for each brand: "Are our creators helping us reach this month's goals, and how sure are we?" It shows, per brand, the goals (for example, sales for October), what has been achieved so far, a projection of where the month will end, and a plain-English explanation.

**Who it is for.** Account managers and brand leads who work with creators (people who post videos promoting products). They are busy and not engineers. They need to:
- see at a glance whether each brand is on track, at risk, or off track;
- see which creators bring in sales after what they cost;
- see which free product samples led to a video;
- know when a number cannot be trusted because data is missing or late, instead of being shown a misleading "0".

**What makes it different.** Every number can be clicked to show exactly which source rows it came from and how it was calculated. If the data needed for a number is missing, the tool says "Unknown" and explains why.

## 2. What we chose, and why (with tradeoffs)

| Choice | Why | Tradeoff |
|---|---|---|
| **One database technology (Postgres) everywhere**: on a laptop, in tests, in the cloud | Same behaviour in every place; no surprises when deploying; SQL is good at this kind of counting and date work | Heavier to start than a simple file database; needs a local Postgres install |
| **Medallion layers: Bronze, Silver, Gold** | Raw files are kept untouched (Bronze), cleaned and typed (Silver), and turned into business-ready views (Gold). When a number looks wrong you can walk back to the exact original row | More tables and more steps than a quick script |
| **Simulated data with planted scenarios** | We have no real brand data. Five scenarios (a late refund, a quiet creator, an affiliate-only star, samples in different states, missing video files) are hidden in the data on purpose so the tool must prove it handles real-world messiness | The data is invented; it shows the tool works, not that real TikTok exports look identical |
| **Evidence for every number** | Trust: a reader can check any figure against its source rows | Extra work to build, and every figure and its evidence must use the identical filters |
| **"Unknown is never zero"** | A missing number shown as 0 looks like "nothing happened" and leads to wrong decisions. Zero is only shown when we know coverage is complete and the true answer is zero | Screens show more "Unknown" labels, which can feel less tidy |
| **FastAPI (backend) + Next.js (frontend)** | FastAPI is a Python web framework that is quick to build and self-documents; Next.js is a popular React-based web framework that deploys easily to Vercel | Two separate programs to run and deploy instead of one |
| **Token login** | Simple demo login (`demo` / `darkroom-demo`) that works the same way real systems do | Not a production-grade user system: one demo account, no password reset, no roles |
| **Per-goal definitions** | Each goal states whether it counts only creator-driven sales or the whole shop, and gross or net of refunds. Two goals with the same name could otherwise mean different things | The reader sees more labels; goals cannot be silently compared |
| **Metrics only calculated in the backend** | One source of truth; the screen only displays what the API returns | The screen cannot "fix" a number by itself |
| **Money as exact decimals, sent as text** | Avoids rounding errors that floating-point numbers cause (for example 0.1 + 0.2) | Slightly more careful code |
| **Business dates use the brand's time zone (Los Angeles)** | An order at 11:30 pm Pacific on 31 October is October for the brand, even though it is already 1 November in UTC | Needs time-zone data on every machine |

## 3. How data flows (in words)

1. A **batch folder** arrives with a `manifest.json` that lists every file and the period it claims to cover.
2. **Ingestion** reads each file, stores the raw rows untouched (Bronze), checks them, and rejects or quarantines bad files without stopping the others.
3. Clean typed tables (Silver) are rebuilt from all accepted raw data in one all-or-nothing step.
4. **Gold views** compute business results (sales, refunds, goal progress, freshness, attention list).
5. The **API** serves only Gold. The **web app** shows the API values.

Rules that make this safe: replaying the same file changes nothing; the newest version of a record wins regardless of arrival order; weekly video files that overlap an accepted file are quarantined; if declared coverage has gaps, projections are "unavailable".

## 4. Glossary

- **API (application programming interface)**: the set of web addresses the app's screen calls to get data. The screen never touches the database directly.
- **Affiliate**: a creator paid a commission when sales come through their content.
- **As-of date**: the simulated "today" (2026-10-15). Freshness is judged against it, never against the real clock.
- **Attribution**: linking an order line to the creator (and video) credited with the sale.
- **Backend**: the server program (FastAPI) that holds the logic and data access.
- **Batch**: one delivery of files (batch 1, batch 2), described by a manifest.
- **Blackbox test**: a test that uses the system only from outside (web requests and command line), without looking at its code, like a user.
- **Bronze layer**: raw, unchanged copy of everything received; add-only.
- **Business date**: the calendar date of an event in the brand's time zone.
- **Cohort (cohort view)**: grouping by the month the original order was placed. A refund that completes later still reduces the original order's month.
- **Commission**: the amount paid to an affiliate creator for a sale.
- **Contract type**: `retainer` (fixed monthly fee) or `affiliate` (commission only).
- **Coverage / coverage_through**: the last date up to which the declared files continuously cover a source. Never the latest event date.
- **CORS**: a browser safety rule; the backend must list the web address allowed to call it (setting `CORS_ORIGINS`).
- **CLI (command line interface)**: typed commands such as `python -m app.cli migrate`.
- **Creator**: a person who posts content; identified by a stable id like `cr_0001`, even if the handle (name) changes.
- **Data revision**: a counter that increases only when the data actually changed. Used to notice that something on screen is out of date.
- **Eligible GMV**: GMV that counts: paid, not a sample, item not fully cancelled.
- **Evidence**: for any number, its definition, formula, inputs, exclusions, warnings and the source rows behind it.
- **Freshness states**: `current` (up to date), `partial` (some data missing), `stale` (behind where it should be), `unavailable` (no data, value unknown). Internally also `suspect` (an unresolved anomaly) and `missing`. The worst state among a metric's sources wins.
- **Frontend**: what the user sees in the browser (Next.js).
- **Gold layer**: business-ready views the API reads.
- **Golden test / golden case**: a tiny hand-made data set whose correct answers were worked out by hand and written down in advance. The system must reproduce them exactly.
- **GMV (gross merchandise value)**: total value of goods sold before refunds.
- **Handback / worker**: internal build terms; not part of the product.
- **Idempotent**: doing it twice has the same result as doing it once. Re-loading a file does not duplicate anything.
- **Increment vs snapshot**: an increment adds new rows for a period (orders, returns, weekly videos) and never deletes. A snapshot is the complete current picture (roster, samples, products, plans); rows missing from a newer snapshot are deactivated.
- **Ingestion**: reading files, checking them and loading them into the database.
- **JWT / token**: a signed text string proving you logged in. The app sends it with each request; it expires after 8 hours. HS256 is the signing method.
- **Manifest**: the list of files in a batch with the period each one covers.
- **Medallion architecture**: the Bronze, Silver, Gold layering.
- **Migration**: a numbered SQL file that creates or changes database structure; applied in order and tracked.
- **Net sales (net attributed sales)**: creator-attributed GMV minus completed merchandise refunds for those items.
- **Normalisation**: standardising raw values (dates, handles, header names).
- **Postgres**: the database.
- **Projection**: where a month will end if the pace so far continues.
- **Quarantine**: a file set aside because it looks wrong (unknown header, overlapping period); the rest of the batch continues.
- **Quality issue**: a recorded problem (orphan record, conflict) kept visible instead of silently dropped.
- **Required pace**: how much per remaining day is needed to hit the target.
- **Retainer**: fixed monthly fee paid to a creator.
- **Sales after costs**: net sales minus retainer, commission and sample costs; unknown if any required cost is unknown.
- **Sample**: a free product sent to a creator hoping for a video.
- **Schema**: (1) the shape of a table, its columns and types; (2) a named folder inside the database (`bronze`, `silver`, `gold`, `meta`).
- **SKU**: stock keeping unit; one specific variant of a product.
- **Source reference**: file and row number kept on every fact row, so any number traces to its origin.
- **Unix seconds**: a time written as seconds since 1 January 1970 UTC.
- **View**: a saved database query that behaves like a table.
- **Verified zero**: a zero that is known true because coverage is complete.

## 5. Field-by-field dictionary of the source files

Types: text, integer, decimal (money, text such as `"24.00"` in JSON so no rounding), boolean, date (`YYYY-MM-DD`), unix seconds (UTC), nullable (may be empty, meaning unknown).

### 5.1 Brands (fixed list)
| Field | Meaning | Example | Use |
|---|---|---|---|
| brand_id | Short id of the brand | `aurelle` | Folder name, every join |
| name | Display name | Aurelle Jewelry | Shown on screens |
| category | Product type | jewelry | Context only |
| shop_id | The brand's shop id | `shop_aurelle` | Links orders and products to the brand |

The five brands: aurelle (jewelry), verdant (skincare), crunchwell (snacks), threadline (apparel), glowhaus (beauty). All use time zone America/Los_Angeles and USD. Creator ids look like `cr_0001`, handles like `@mia.makes`; some creators work for two brands.

### 5.2 Orders: `orders/<brand_id>/<YYYY-MM>.json` (increment)
Top-level key `orders` is a list. Each order:
| Field | Meaning | Type / example | Use |
|---|---|---|---|
| order_id | Unique order id | text `"AU8391939898"` | Key; a duplicate across pages is stored once |
| shop_id | Shop that took the order | `shop_aurelle` | Brand link |
| status | Order state: UNPAID, AWAITING_SHIPMENT, IN_TRANSIT, DELIVERED, COMPLETED, CANCELLED | `COMPLETED` | Decides eligibility (must be paid, not cancelled) |
| create_time | When the order was placed | unix seconds, `1788327242` | Record keeping |
| paid_time | When it was paid; empty if unpaid | unix seconds or null | Sets the business date for GMV (converted to Los Angeles time) |
| update_time | Last change time | unix seconds | The newest version wins |
| is_sample_order | True if a free sample order | boolean | Sample orders are excluded from GMV |
| payment.currency | Currency | `USD` | Sanity check |
| payment.sub_total | Order subtotal | decimal `"123.45"` | Informational; GMV uses line items |
| line_items | One row per unit sold | list | See below |

Line item:
| Field | Meaning | Example | Use |
|---|---|---|---|
| id | Line id | text | Key; links affiliate records and returns |
| product_id | Product bought | text | Links to products |
| sku_id | Variant | text | Product link |
| sale_price | What the buyer paid for the item after discounts | decimal `"24.00"` | The amount summed into GMV |
| original_price | Price before discounts | `"30.00"` | Context |
| seller_discount | Discount funded by the brand | `"6.00"` | Context |
| platform_discount | Discount funded by TikTok | `"0.00"` | Context |
| display_status | Item state (AWAITING_SHIPMENT, DELIVERED, CANCELLED...) | `DELIVERED` | A fully cancelled item is ineligible |

Sample orders have every amount `"0.00"`.

### 5.3 Affiliate orders: `affiliate_orders/<brand_id>/<YYYY-MM>.json` (increment)
Top-level key `records`. At most one record per line item.
| Field | Meaning | Example | Use |
|---|---|---|---|
| affiliate_record_id | Id of the credit record | text | Key |
| order_id | Order credited | text | Link to order |
| line_item_id | Item credited | text | Link to the line |
| creator_user_id | Creator's stable id | `cr_0007` | Credits sales to the creator |
| creator_handle | Handle at that time | `@mia.makes` | Display; handles can change while the id stays |
| content_id | Video that drove the sale, or null | video id / null | Ties sales to a video |
| content_type | `video`, `live` or `showcase` | `video` | LIVE does not count as a video |
| commission_rate | Share paid as commission | decimal `"0.12"` | Explanation |
| commission_amount | Commission in dollars | `"2.88"` | Creator commission cost |
| commission_status | `pending` or `settled` | `pending` | Informational |
| update_time | Last change | unix seconds | Newest wins |

### 5.4 Returns: `returns/<brand_id>/<YYYY-MM>.json` (increment)
Top-level key `returns`. A refund can complete weeks later, in a later file.
| Field | Meaning | Example | Use |
|---|---|---|---|
| return_id | Return id | text | Key |
| order_id | Original order | text | Restates that order's month |
| line_item_id | Item returned | text | Link |
| return_status | REQUESTED, COMPLETED, REJECTED | `COMPLETED` | Only completed refunds reduce net sales |
| refund_subtotal | Merchandise amount refunded; null if not split out (also null on open REQUESTED returns; 330 null rows in batch 1) | decimal `"12.00"` or null | Subtracted from net; null means status partial and the value is flagged |
| refund_tax | Tax refunded | decimal | Not counted in sales |
| create_time | Return request time | unix seconds | Record keeping |
| completed_time | Refund completion time; null if open | unix seconds or null | Must be on or before as-of to count |
| update_time | Last change | unix seconds | Newest wins |

### 5.5 Products: `products/<brand_id>.csv` (snapshot, UTF-8, header row)
| Field | Meaning | Example | Use |
|---|---|---|---|
| shop_id | Shop | `shop_verdant` | Key part |
| product_id | Product | text | Key part |
| sku_id | Variant | text | Link |
| product_name | Name | Glow Serum | Display |
| list_price | Normal price | decimal `"32.00"` | Context |
| unit_cost | What one unit costs the brand | decimal `"9.50"` | Sample cost = qty x unit_cost |
| update_time | Last change | unix seconds, `1759300000` | Snapshot ordering |

### 5.6 Weekly videos: `videos/<brand_id>/<YYYY>-W<WW>.xlsx` (increment)
Sheet "Video performance". Rows 1-2 are title and period text, row 3 is the header, data follows, a final "Total" row is skipped. Numbers are for that week only, not running totals. Batch 2 may rename headers (`Video Id`, `Video Views`, `Gross Merchandise Value`); known aliases are accepted, an unknown header quarantines the file.
| Column | Meaning | Example | Use |
|---|---|---|---|
| Video ID | Video id (batch 2 header: `Video Id`) | text, e.g. `70000031` | Key; the same video across weeks is one video |
| Creator ID | Creator | `cr_0003` | Credits the video |
| Creator Handle | Handle | `@mia.makes` | Display |
| Post Time | Local-time ISO text of publishing | `2026-08-24T20:11:20` | Month and "last post" date |
| Product ID | Product promoted | text | Matches samples to videos |
| Views | Views that week | integer | Summed across weeks |
| GMV | Sales the platform reports for the video that week | number (a number in the xlsx, e.g. `50.4`) | Reported only; our GMV comes from orders |
| Items Sold | Units that week | integer | Informational |

### 5.7 Roster: `roster/roster.xlsx` (snapshot), sheet "Roster"
| Column | Meaning | Example | Use |
|---|---|---|---|
| brand_id | Brand | `verdant` | Link |
| creator_id | Creator | `cr_0003` | Link |
| handle | Handle | `@mia.makes` | Display |
| contract_type | `retainer` or `affiliate` | `retainer` | Decides costs and whether "quiet" alerts apply |
| monthly_retainer | Total monthly fee | decimal `1500.00` | Retainer cost |
| posts_per_month | Expected posts | `8` | Context |
| effective_from / effective_to | Contract dates | `2026-04-01` / blank | Prorates retainer by days |
| status | Active or not | `active` | Whether shown as active |
| allocation_share (optional) | Share of the retainer given to this brand | `0.5` | Two-brand creators have two rows; if missing on a multi-brand retainer the allocation is unknown, not full charge |

### 5.8 Samples: `samples/samples.xlsx` (snapshot), sheet "Samples"
| Column | Meaning | Example | Use |
|---|---|---|---|
| shipment_id | Shipment | text | Key |
| brand_id | Brand | `threadline` | Link |
| creator_id | Recipient | `cr_0011` | Matching |
| product_id | Product sent | text | Matching and cost |
| qty | Units | `2` | Cost |
| shipped_date | Sent date | `2026-08-03` | Timeline (sometimes an Excel serial number, converted) |
| delivered_date | Delivery date | date, Excel serial number (a few rows, converted) or blank | Starts the 30-day conversion window |
| status_text | Sent, Delivered, In transit, Returned | `Delivered` | State |
| shipping_cost | Postage | decimal or blank | Added to sample cost if known, else cost unknown |
| linked_video_id | Video the team recorded as the result | usually blank | Explicit match when present |

### 5.9 Plans: `plans/<brand_id>.json` (snapshot)
| Key | Meaning | Example | Use |
|---|---|---|---|
| brand_id | Brand | `glowhaus` | Link |
| month | Month the plan covers | `2026-10` | Period |
| goals | Three goals per brand | list | Each below |
| goals[].metric_key | What is measured: `gmv`, `videos`, `active_creators` | `gmv` | Selects the calculation |
| goals[].scope | `creator_attributed` or `shop` (whole shop) | `shop` | Whose sales count |
| goals[].basis | `gross` or `net` of refunds | `net` | Refund treatment |
| goals[].definition | Plain-text definition | text | Shown to the reader |
| goals[].target | Target number | `20000` | Compared with actual |

### 5.10 Manifest: `manifest.json` (required)
| Key | Meaning | Example | Use |
|---|---|---|---|
| batch_id | Batch name | `batch_1` | Tracking |
| simulated_received_at | When it arrived | `2026-10-15T23:59:59-07:00` | Record keeping |
| as_of | Data date (batch 1 `2026-10-15`; batch 2 `2026-10-22`; the API cutoff defaults to 2026-10-15) | `2026-10-15` | Freshness yardstick |
| files[].path | File location in the batch | `orders/aurelle/2026-09.json` | Finds the file; missing file means `missing` |
| files[].source_type | orders, affiliate_orders, returns, products, videos_weekly, roster, samples, plans | `orders` | Chooses the reader |
| files[].brand_id | Brand | `aurelle` | Scope |
| files[].period_start / period_end | Declared coverage | `2026-09-01` / `2026-09-30` | The only source of declared coverage |
| files[].kind | `increment` or `snapshot` | `increment` | Merge rule |
| files[].src_updated_at | When the source last updated it | `2026-10-01T02:00:00Z` | Newest version wins |

Files not listed in the manifest are ignored and recorded as a quality issue.

## 6. The planted scenarios (what the tool must find)
1. **aurelle**: a late partial refund (batch 2) lowers an earlier month's net sales.
2. **verdant**: a retainer creator posts nothing for 10+ days while video data is complete; appears in "needs attention".
3. **crunchwell**: an affiliate-only creator with strong output and sales but no retainer.
4. **threadline**: samples that converted, are pending, and one ambiguous match.
5. **glowhaus**: two weekly video files are missing; video numbers are stale or incomplete while orders look normal.

Also: a duplicated order across two pages, a creator whose handle changes under the same id, and an order at 31 October 23:30 Pacific that belongs to October.

## 7. How we check the tool
- **Golden test**: tiny hand-checked data with known answers (for example brand A gross = net = 100; after a late $20 refund, net 80).
- **Blackbox tests** (S1-S12): drive the running system from outside: login rules, duplicates, replay safety, older-after-newer ordering, time-zone boundary, missing video weeks, verified zeros, evidence matching the displayed value, sample states, bad files, and screen refresh when data changes.
- The expected answers are written by hand and are never changed in the same change as the code they test.
