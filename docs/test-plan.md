# Blackbox test plan - FROZEN (designed with opus-advisor)

Modelled on Anthropic's article "How the Claude Code team thinks about verification" (https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/, read 2026-11-17): end-to-end first, drive the real running system, a verifier separate from the implementer, checks that changes cannot edit, edge cases not created with the implementer's bias, and a review checklist with diff-readable triggers.

## Harness
`tests/blackbox/` (pytest + httpx + subprocess). Talks ONLY to `BASE_URL` (default http://localhost:8000) and the CLI (`python -m app.cli ...` run via subprocess in `backend/`). No `import app`. Golden expected values live in `tests/golden/expected.yaml`, hand-written with arithmetic in comments; the golden fixture is `data/synthetic/golden_cases/`. A `tests/run_blackbox.ps1` resets the DB, ingests, starts the API, and runs the suite. Freshness is computed against the simulated as-of date, never wall-clock.

## Scenarios (S1-S12)
| id | via | input | expected |
|---|---|---|---|
| S1 | HTTP | no/invalid token; POST/PUT to data routes; login wrong creds | 401/405, no data; login ok for demo user |
| S2 | HTTP | golden batch 1 incl. a duplicated order | Brand A gross=net=100, Brand B=50, video views 140 not 240 |
| S3 | CLI+HTTP | golden batch 2 (late $20 refund) | A net 80, gross 100 |
| S4 | CLI+HTTP | replay batch 1 and 2 | identical API responses, same data_revision |
| S5 | CLI+HTTP | ingest an older version after a newer | newer wins |
| S6 | HTTP | order paid Oct 31 23:30 PT (Nov 1 UTC) | counted in October |
| S7 | HTTP+UI | glowhaus video feed missing weeks | value null, status stale/partial, UI shows "stale"/"Unknown", never $0 |
| S8 | HTTP | roster creator with no activity, full coverage | videos 0 (verified zero) |
| S9 | HTTP | every displayed metric vs its evidence | value equals the evidence calculation for the same filters and revision |
| S10 | HTTP | threadline samples | converted / pending / unresolved states; rate uses mature items only |
| S11 | CLI | header alias + BOM file; file missing a required field | ingests; bad file rejected, exit != 0 for that file, totals unchanged |
| S12 | UI | ingest while an evidence drawer is open | drawer shows refresh, not a mismatch |
Also: CORS preflight from :3000; every endpoint's keys match `docs/api-contract.md`; demo login works end to end in the UI.

## Review checklist (trigger -> check)
- upsert/keys changed -> run S4, S5
- date/timezone code -> S6
- money code -> Decimal/cents, no float
- `COALESCE`, `fillna`, `?? 0`, `or 0` on a metric -> S7, S8
- metric query touched -> value and evidence share one filter, S9
- header mapping -> S11
- route/env/secret -> S1, no secret in the frontend bundle
- `tests/golden/expected.yaml` edited in the same change as `backend/` -> reject

> Amendment 2: see docs/test-plan-amendment-2.md for the 14 essential tests and scenarios S13 to S20.
