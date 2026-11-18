# AI usage log (short, factual)

- Tool: Claude Code, with a main session acting as orchestrator and Haiku, Sonnet and Opus subagents.
- Discovery: Haiku research agents audited files, tests and docs.
- Architecture: an Opus advisor designed the Medallion schema, the API contract and the blackbox test plan (S1-S12). Those contracts were then frozen in `docs/`.
- Implementation: Sonnet workers built ingestion, API, data generator, tests and UI against non-overlapping files.
- Verification: separate agents checked docs, tests and diffs. A human reviews the diffs.
- Independent verifier agent: found real bugs (a slow gold view, the refund cutoff being ignored, and an evidence 422). They were fixed in later retry rounds; the fixes took more than one round.
- Golden value GS4 was re-derived by hand from the raw files after the verifier flagged a mismatch. The golden data was then regenerated (contiguous video coverage, W44 files, video V_A0).
- Numbers: every metric is computed in SQL (Gold views and the metric layer). No LLM produces or edits a displayed number. The golden expected values in `tests/golden/expected.yaml` were written by hand.
- Data: all data is synthetic, produced by a deterministic script, not by an LLM at run time.
