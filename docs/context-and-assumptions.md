# Context and assumptions (Step 1)

**Read this first.** No customer data or customer answers were supplied. Everything in this project is simulated, including the files, and every customer question below is answered by us, not confirmed. The answers are listed in [decisions.md](decisions.md) with what changes if each is wrong.

## 1. The customer

Northlight is a fictional agency that runs TikTok Shop creator programs for five brands (jewelry, skincare, snacks, apparel, beauty). Creators post short sales videos. A few are on a monthly retainer plus commission; most are affiliates on commission only. The team also ships free samples to get new creators posting.

| Who | Decision | How often | What they need to see |
|---|---|---|---|
| Head of Creator Programs | Which creators to rebook, nudge or drop, across all five brands | Weekly | Each creator's videos, sales driven, refunds and cost, side by side, sortable |
| Creator manager (per brand) | Who needs a nudge today; which samples to chase | Daily | Retainer creators who went quiet, samples delivered with no video |
| Account lead (owns monthly goals) | Are we on track this month, and if not, why | Weekly, and mid-month | Each goal against actuals, a month-end projection, and the reasoning |
| Whoever reports to the brand | Can I trust this number | Monthly | The definition, the date range, the source files, and whether a source is late |

What the team told us, and where the tool answers it:

| The pain | Where it is answered |
|---|---|
| "Every week we argue about who to rebook" | Creators page: output, refunds, cost and sales after costs for every creator |
| "A retainer creator going quiet costs us real money" | Needs-attention list: quiet retainer rule |
| "We send dozens of samples and don't know how many turn into a video" | Samples page: sent, delivered, converted, pending, no video |
| "I find out we're behind for the month when it's too late" | Overview: each goal with a projection and the pace still required |
| "TikTok's numbers don't add up; refunds come in weeks later" | Gross and net shown separately; refunds restate the original month; every number opens its evidence |
| "Where did it break?" | Diagnostics page and each brand's Diagnostics tab: the month so far (Oct 1-15) against the same days of the previous month (Sep 1-15), split into fewer creators posting, weaker videos and product mix, with a stated method and disclaimer. It shows evidence, not proof of cause |
| "Who do we rebook, nudge or drop?" | Each creator row has a suggested action (review, nudge, upgrade, rebook or watch) with the rule shown next to it; first matching rule wins, and any unknown input gives "review" |
| "What do we do today?" | Needs attention page: one ranked list across the five brands, ordered by dollar exposure (nulls last) |
| "What did we decide about this creator?" | Notes on a creator, saved from a form in the creator sheet |

## 2. Definitions the tool depends on

These match the code (`docs/db-contract.md`) and the field list (`docs/PROJECT_EXPLAINER.md`).

- **Business day and month:** the brand's reporting timezone (US Pacific). An order paid late on 31 October Pacific counts in October even if it is already 1 November in UTC.
- **GMV (gross):** the buyer-paid item amount after item discounts, for paid orders only. It excludes tax, shipping, sample orders, and lines that were fully cancelled. A refund does not reduce it.
- **Net sales:** creator-attributed GMV minus completed merchandise refunds. A refund counts against the month of the original order (so a late refund restates that month), but only once it has completed on or before the date you are looking at. If a refund amount cannot be split from tax or shipping, the value is flagged partial; we do not guess.
- **Samples and cancelled orders:** never count as sales.
- **Currency:** USD only. The original amount and currency are stored.
- **Video:** counted once, in the month of its local publish date, however many weekly files it appears in. LIVE sessions are not counted.
- **Active creator:** posted at least one qualifying video for that brand in the month. A creator who posts ten videos counts once.
- **Creator cost:** retainer (prorated by days, split by an allocation share if a retainer covers several brands) plus commission plus the cost of samples. A cost we cannot know stays unknown; it is never treated as zero.
- **Creator value:** net sales, and net sales after known costs. This is not profit: it leaves out product cost, platform fees and fulfilment.
- **Sample conversion:** a sample counts as converted when the same creator posts a video for that brand and product after delivery and within 30 days. The rate only counts samples at least 30 days old; newer ones stay pending.
- **Quiet retainer creator:** a retainer creator with no video in the last 10 days, but only while video coverage is complete. If the video file is missing, the answer is "cannot tell", never "quiet".
- **Freshness, per brand and source:** current, partial, stale, missing or suspect. Coverage comes only from what each file declares in its manifest, never from the latest event date.
- **Projection:** actual to date divided by complete days elapsed, times days in the month. It is unavailable when the data has gaps. The active-creator projection needs at least three complete prior months.

## 3. Assumptions, and what would catch each one if it is wrong

| Assumption | Guard in the system |
|---|---|
| Each source's coverage is what its manifest declares | A file not in the manifest is ignored and logged; a declared file that is absent shows as missing |
| Weekly video exports hold per-week numbers, not running totals | A weekly file whose period overlaps an accepted one is quarantined, never added |
| A newer record of the same order or refund replaces an older one, whatever the arrival order | Newest `src_updated_at` wins; ties that cannot be ordered raise a conflict |
| Files change shape over time | Unknown column headers quarantine that file only; a missing required field rejects that file only; header variants are mapped in one alias file |
| The same file may be sent twice | Files are keyed by their hash, so a replay changes nothing |
| Unknown is different from zero | Missing or partial sources give `null` with a status and a reason, and a test checks it |
| One creator can appear under several handles | Creators are matched by id; look-alike handles are never merged automatically; unmatched identifiers are listed for review |

The full numbered list of assumed customer answers is in [decisions.md](decisions.md).

## 4. Scope

**What it is:** an internal decision tool over five clients' creator programs. It shows goals against actuals with a projection and the reasoning; every creator's output, cost and value; the sample funnel; where every number came from; and whether each data source is fresh, late or missing. It also lists who needs attention in one ranked queue, traces a goal miss to a likely cause, suggests a rebook, nudge or drop action per creator with the visible rule, keeps team notes per creator, and draws charts with an info popover explaining each one. Data Health is brand-scoped, and login is a single "Enter Demo Workspace" button.

**What it is not:** finding or messaging creators, running ads, live calls to TikTok's API, real authentication or production infrastructure, or payout and settlement accounting. It does not forecast beyond month end, and it does not claim to prove why a number moved.

**Built since the first draft:** goal-miss diagnostics (Oct 1-15 against Sep 1-15, on `/diagnostics` and the brand Diagnostics tab); `suggested_action` on creator rows with its rule; creator notes (API and a form in the creator sheet); the ranked Needs-attention queue (`/attention`); charts with info popovers; brand-scoped Data Health; one-click demo login. Non-USD orders are excluded from USD GMV, and unknown creator ids stay in an unresolved bucket (see `docs/rulings-after-verification.md`).

**Not built:**
- Live deployment (a plan exists in `docs/DEPLOYMENT_PLAN.md`).
- Real TikTok API sync (files are loaded by a command).
- Authentication beyond the single demo login.
- Alerting (for example a message when a retainer creator goes quiet).

## 5. Questions we would ask the customer

We could not ask, so each has an assumed answer in [decisions.md](decisions.md):

1. Are the October GMV goals gross or net, and do they cover all shop sales or only creator-driven sales?
2. Does "active creator" mean posted, or sold? Do LIVE sessions count?
3. What are the retainer terms, and is a partial month prorated?
4. What does a sample cost, including shipping?
5. How long can a retainer creator go without posting before the team wants to hear about it?
6. Does any brand sell outside the US or report in another currency?
7. When the roster and TikTok disagree on a handle or status, which wins?
8. What does the weekly rebook meeting look at today, and who is in it?
9. Which timezone defines the month?
