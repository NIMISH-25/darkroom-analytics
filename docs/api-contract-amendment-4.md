# API and UI contract, Amendment 4 (plain-English operator interface, faulty-row handling): FROZEN

This amends the earlier contracts. Where they differ, this file wins. `CLAUDE.md` is not changed by this amendment.

## 0. Rule: no developer language in the operator interface
Operators never see: array positions like `orders[1]`, field or column names (`order_id`, `goal_id`, `source_file`, `_scale`), formula or query text (`count(distinct video_id)`), internal status codes, the bare word UNAVAILABLE as a placeholder, or "X vs X" placeholder rows. Every message is a plain sentence that names the brand (and the creator where known). The status badge labels **Complete / Incomplete / Stale** stay; every Incomplete or Stale badge has a tooltip carrying a plain reason.
Where something genuinely has no data, say it in words ("No data yet for this period") or hide the row when it has no meaning for that item. All user-facing strings come from the server's wording layer; the frontend never builds sentences from codes.

## 1. Faulty rows are left out, not the whole file (ruling)
A row missing a required identifier (for example an order without an order number) is excluded **on its own**. Its file stays loaded (status `accepted`), its brand stays `current`, and totals are shown as **floors** (they may be slightly low) with a plain note naming the brand: "Verdant: 1 of 24 orders in a file was left out because it had no order number, so the real totals may be higher than shown." Only a file that cannot be read, or has no usable rows at all, is rejected (unchanged: exit code 1, brand `incomplete`). Quarantined (overlapping) files are unchanged.
- Parser: skips each bad row into `Parsed.excluded` and counts **all** bad rows (not just the first). New table `bronze.excluded_row(source_file_id, row_num, reason_code, detail)` for developers only; new migration `018_excluded_rows.sql`; `bronze.source_file` gains `excluded_rows int`. `meta.quality_issue` gains code `rows_excluded` (brand, count, plain message) replacing `file_rejected` for this case.
- Ingest exit code is 0 when only rows were excluded.
- Existing expectations that change (the tests worker re-derives them by hand from the fixture): golden verdant E12 projection is no longer null because of the extra file (it is a value, with a note); S11 bad-file test expects exit 0, no failed file, `excluded_rows` = the real count; add S11b: a file with only bad rows is rejected, exit 1, brand incomplete, projection null. Data Health: such a file shows as loaded with "N records left out", not as failed; `counts` gains `rows_excluded`.

## 2. Presentation layer (server)
New module `backend/app/presentation/humanize.py`: `humanize(code, ctx)` with complete maps from internal codes and field names to plain nouns ("order number", "video", "creator") and from status codes to sentences. An unknown code gets a generic sentence and a log entry. It is applied at the API boundary: every `status_reason` in every response is plain English (field kept, text changed). The old internal text is not exposed. 422 errors for missing parameters return a plain sentence in `detail` ("Choose which goal to explain."), not a field name.
Response fields (existing technical fields such as `calculation`, `definition`, `result`, `records[].values` stay for API clients and tests; the UI never renders them):
- Every metric value (MV): `status_reason` plain; new `data_note` (plain note when figures are floors because rows were left out; else null).
- Evidence: `what_this_means`, `why_it_matters`, `what_to_watch` (plain, business-focused, name the brand/creator and mention what was included or excluded in plain words), `incomplete_reason` (null when complete), `data_note`, and `columns_plain: [{key, label}]` giving plain column labels; the UI renders records only through `columns_plain`. The earlier `explainer` object is kept and mirrors these.
- Attention items: `why_needs_attention`, `what_to_do` (a specific action), `incomplete_reason`, `data_note`, `brand_name`, `creator_name` (when known).
- Data health: `failed_files[]` and `files_with_exclusions[]` items get `brand_name` and `plain_reason`; `counts.rows_excluded`.
- Goals (overview and brand): `required_pace_applicable` (false for distinct-count goals such as active creators and for goals with no target: the UI hides the row), `required_pace_reason` (plain reason when applicable but null).
- Portfolio KPIs: `brand_pace_counts: {on_track, behind, unknown, total}` and `brand_pace: [{brand_slug, brand_name, status_label, data_note, goals:[{goal_name, status_label, actual_label, target_label, incomplete_reason}]}]`. A brand's status is its worst goal pace; a goal with unknown data beats on-track; goals that do not apply are ignored. The UI label reads "Brands on pace: N of M". The older goal-level `pace_counts` stays for tests but is not displayed.
- Diagnostics: each factor and total side is `{value, unavailable_reason}` with its own plain reason (never one blanket reason). A row whose both sides are empty is left out of the response; a side with complete coverage and no rows is a true zero. `notes[]` explains in plain English what is missing and why.
- Evidence for the goal projection works without a goal: if `goal_id` is missing the server picks the brand's main sales goal or returns the plain 422 above; the frontend always passes the goal.
- Charts: the hidden `_scale` helper is removed; the y-axis minimum is pinned to 0.

## 3. Operator-facing screens (UI)
- Header text "as of … · rev …" becomes "Darkroom analytics" (top bar); revision numbers and the raw as-of date no longer appear in the operator interface (data revision stays in network calls only).
- Every Incomplete or Stale badge (KPI strips, charts, tables) shows its plain reason in a hover and keyboard-focus tooltip.
- The pace widget reads "Brands on pace: N of M" (never mixed goal counts); each status is clickable and opens a panel listing the brands in that state with their goals and plain reasons.
- The evidence sheet shows, in this order: What this number means, Why it matters, What to watch, any note about incomplete or left-out data, then the supporting rows with plain column labels. No formulas, no definitions in code form, no "N of N rows" boilerplate.
- Needs attention: clicking anywhere on an item (not only a View button) opens a panel with why it needs attention and what to do.
- Brands: required daily pace shows only when applicable; the evidence drawer follows the same plain rules; no placeholder rows.
- Creators: the economics chart uses high-contrast fills on the dark theme (hover highlight, readable axis and legend); the "Cost unknown" list shows only each creator's own plain reason (for example missing retainer terms or an unlinked creator), never a file or row error.
- Samples: a repaired layout: each brand is a card with a responsive grid of figures that wrap (no horizontal overflow), a badge and its reason sit under the figure inside its own cell (never over a neighbouring cell), long reasons wrap or move into the tooltip, and nothing overflows the card on desktop.
- Diagnostics (brand tab and /diagnostics): show only rows that have data; per-side plain reasons; no placeholder-versus-placeholder rows.

## 4. Test contract
`tests/banned_phrases.json` holds the ban list as regular expressions, shared by API and UI tests: array positions (`\w+\[\d+\]`), snake_case field names (`\b_?[a-z]+_[a-z_]+\b`, after stripping entity names such as creator handles), function syntax (`\b(count|sum|avg)\s*\(`), the word `distinct`, `UNAVAILABLE`, `null`, `None`, `NaN`, `undefined`, `is required`, braces. The words Incomplete, Stale and Complete are allowed (badge labels). An API crawl test walks every operator-visible string field of overview, brand, creators, samples, attention, diagnostics, health and evidence responses and asserts none matches; a browser test asserts the rendered text of all six pages.
