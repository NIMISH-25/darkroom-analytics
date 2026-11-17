# Decisions assumed in place of customer answers

No customer was available. The contracts (`docs/db-contract.md`, `docs/source-contracts.md`) encode the nine choices below; they do not number them, so this numbering is ours. All are **assumed**, not confirmed.

| # | Assumption (assumed) | Reason | If wrong |
|---|---|---|---|
| 1 | Business dates use the brand `reporting_tz` (America/Los_Angeles); USD only | Orders carry UTC; the brands are US shops | Change the timezone per brand; month totals near boundaries move |
| 2 | GMV = paid, non-sample orders, item not cancelled, sum of buyer-paid item amount after discounts, excluding tax and shipping | Matches how a brand reads "sales" | Change the `paid_amount` rule in the gold view; every GMV figure changes |
| 3 | Refunds restate the ORIGINAL order's month (cohort view) | Keeps past months honest after late refunds | Switch to a refund-date view; past months stop changing but the refund month absorbs them |
| 4 | Net = attributed GMV minus completed merchandise refunds; a refund with unknown amount is flagged partial, not guessed | Unknown must stay visible | If tax-inclusive or estimated refunds are wanted, change the refund view |
| 5 | A video counts once, in the month of its local publish date; LIVE does not count as a video; "quiet" = retainer creator with no video for 10 days and full coverage | Simple, testable rule | Change the qualify rule or the 10-day setting (`followup_days` on `/attention`) |
| 6 | Sample conversion: a video for the same brand, creator and product published after delivery and within 30x24h; only items at least 30 days old are in the rate | Gives each sample a fair window | The window or maturity rule changes and so does the rate |
| 7 | A multi-brand retainer is split by `allocation_share`; no share means unknown cost, not a full charge | Avoids over-charging one brand | If an even split is acceptable, default the share to 1/n |
| 8 | Coverage comes only from the manifest; orders lag 1 day; weekly videos are complete only for finished weeks; gaps make projections unavailable | The latest event date can hide missing files | If files are routinely late, raise `lag_days` in `meta.source_contract` |
| 9 | Newest `src_updated_at` wins over arrival order; weekly video metrics are per-week, not cumulative; an overlapping weekly file is quarantined | Replays and late files must be safe | If video exports were cumulative, summing would double count |

Also assumed: the goal definitions in `plans/*.json` (gross or net, shop-wide or creator-attributed) are the customer's, and the demo uses one shared account.
