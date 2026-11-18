# Test plan, Amendment 2: the 14 essential tests and new scenarios

This extends `docs/test-plan.md`. Every test is a pytest test in `tests/blackbox/` using HTTP and CLI only.

**The 14 essential correctness tests**
- Already covered: #1 replay (S4), #2 out-of-order update (S5), #7 missing data (S7), #8 sample maturity (S10), #9 timezone (S6), #11 evidence integrity (S9), #13 second batch (S11), #14 revision change (S12).
- To add: #3 partial refund and cancellation (no double deduction); #4 brand isolation and cross-brand cost allocation; #5 identity ambiguity (look-alike names do not merge; a reviewed alias or a stable id works); #6 video snapshots count once and cumulative values are not summed; #10 money, currency, discount and allocation rules; #12 projection edge cases (zero denominator, month end, incomplete coverage, distinct counts never below current).

**New scenarios**
- S13 chart series: every series for every brand returns the envelope; the sum of daily GMV equals the overview actual; reconciliation buckets sum to eligible GMV; the sample funnel equals `/samples`; missing or stale points are null with a status.
- S14 diagnostics: the Shapley effects plus the change in unlinked GMV equal the total change; null for zero denominators and for incomplete coverage.
- S15 notes: POST then GET round trip; validation (empty body, over 2000 characters); survives a re-ingest and a replay; does not change `data_revision`.
- S16 evidence pagination: pages cover all rows exactly once; the summary does not change; `limit` over 500 gives 422.
- S17 caching: a second call with `If-None-Match` returns 304; a new ingest changes the ETag; 401 and 409 are never cached.
- S18 portfolio KPIs equal the sum or pooled value of the brand values.
- S19 latency budget: every GET under 2 seconds on the full synthetic data after warm-up; the first call under 3 seconds.
- S20 UI (Playwright): sidebar routes and brand tabs render; KPI strip values open the evidence sheet; hatched regions appear for the Glowhaus video gap; no `$0` for an unknown value.

`tests/golden/expected.yaml` stays hand-written; add expected values for S13 to S15 on the golden fixture, derived by hand from the raw files. It is never edited in the same change as `backend/`.
