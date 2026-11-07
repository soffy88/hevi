# LangAlpha vs. Helios / 3O — capability gap and adoption result

Audit date: 2026-10-22 UTC. LangAlpha clone at `29baaf16ef348427e646f785e0a156ad8e399343`, reviewed read-only; the repository declares Apache-2.0. The new implementation does not copy or adapt LangAlpha source files, so no upstream copyright header was removed and no LangAlpha-derived source dependency was added. No `THIRD_PARTY_NOTICES.md` entry is required for reused code because no code was reused.

## Ranked gaps

1. **Claim-to-source provenance** (highest value): research claims need stable evidence IDs, source URI/provider, observation time, content hash and explicit unresolved state. Landed in `obase` (persistence/hash), `oprim` (pure validation and conflicts), `oskill` (composition and source-link checking), and `omodul` (fingerprint, decision trail and report). Helios is only the read-only adapter/UI boundary.
2. **Strict market-data boundary**: malformed dates/ranges, unbounded records, non-finite prices, invalid OHLC and contradictory timestamps should fail closed. Implemented in `oprim` date primitives and Helios's public OKX candle normalizer.
3. **Deterministic freshness/authority/conflict review**: an explainable quality index—not a probability—flags stale, unsafe, conflicting or unverified sources. Implemented in `oprim` and `oskill`.
4. **Auditable deliverable workflow**: source records, claims and review status are linked to an existing 3O fingerprint and decision trail. Implemented in `omodul`, using current 3O infrastructure rather than adding another agent runtime.
5. **Chart evidence annotations/workspace monitoring**: worthwhile follow-up after provenance stabilizes; not part of this change.

## Capability comparison

| Capability | LangAlpha pattern reviewed | Helios / 3O status | Decision / layer |
|---|---|---|---|
| Agent/subagent composition | README and `src/src/ptc_agent/agent/graph.py`, `insight_graph.py` | `oservi` agentic loop/MCP graft and `oskill` research workflows already exist | Reuse current 3O composition; no parallel graph runtime. |
| Market-data schema/bounds | `src/mcp_servers/AGENT_CONTRACT.md`, date/envelope/schema modules | `obase` Parquet IO, `oprim` market primitives, Helios APIs | Strict range/data contracts in `oprim` and Helios. |
| Source/tool provenance | LangAlpha observability modules and source-panel workflow | Existing 3O fingerprint/decision trail/report exists, but claim-specific linkage needed strengthening | Content-addressed ledger + claim audits in `obase`/`oskill`/`omodul`. |
| Research/report delivery | LangAlpha research teams and deliverable concepts | Existing `oskill` and `omodul` workflows | Use current orchestration and reporting pillars. |
| Persistent workspace/monitoring | LangAlpha workspace and monitoring | Existing sessions, services and memory | Defer; high overlap with existing systems. |
| Trading/order execution | LangAlpha documents governed trading concepts | Not allowed in this task | Explicitly excluded: no broker, order, account mutation or autonomous trading interface. |

## Implemented code and focused tests

| Repo | Implementation | Focused test result |
|---|---|---|
| obase | `obase/obase/evidence_ledger.py` — canonical JSON/hash, UTC timestamps, URI checks, bounded payloads, idempotent JSONL and integrity checks | `17 passed, 1 warning in 0.05s` |
| oprim | `oprim/oprim/market_evidence_quality.py` — bounded historical windows, explainable freshness/authority, conflict detection | `29 passed in 0.55s` |
| oskill | `oskill/oskill/market_evidence_review.py` — dedupe, claim/source linkage, explicit conflict/unverified results | `19 passed in 1.17s` |
| omodul | `omodul/omodul/market_evidence_report.py` — fingerprinted 3O evidence report, source ledger, claim audit and explicit failure state | `12 passed in 2.48s` |
| Helios | `helios/api/app/services/market_evidence_adapter.py` — read-only OKX response normalization, UTC order, OHLC/volume invariants and content hash | `17 passed in 0.02s` |

All **94 focused tests passed**. Raw output: `evidence/focused_final_*.log`. These focused tests do not replace the full-suite gate.

## Real-data runtime evidence

A direct, read-only GET to the public OKX market candles endpoint returned five daily candle rows each for BTC-USDT and ETH-USDT. The adapter validated and normalized both responses; the workflow persisted two evidence records and linked two latest-returned-candle close claims to the corresponding sources. Review result: `reviewed`, 2 current sources, 0 conflicts. Candle close is not represented as a live spot quote. Evidence:

- Raw response: `evidence/live_okx_btc_eth_responses_20261022.json`
- Runtime summary: `evidence/live_market_evidence_run_20261022.json`
- Report and ledger: `evidence/live_market_evidence_report/`
- Re-runnable script: `evidence/run_real_market_evidence.py`

## Layer ownership and safety

- `obase`: source record persistence, canonical hashes and bounded evidence IO.
- `oprim`: pure date/schema/freshness/conflict primitives.
- `oskill`: evidence-review composition and claim/source validation.
- `omodul`: workflow fingerprint, existing decision-trail/cost/report pillars and explicit status.
- `oservi`: retained existing service and lifecycle boundaries; no new source feature was justified by this report.
- Helios: read-only public-market adapter; no order submit/modify/cancel interface, no paid dependency, no production restart.

## Full-suite gate remains blocked

The full tests were run against the six sibling worktrees before pushing; raw baseline/final logs are preserved. Baseline vs final summaries:

| Repo | Before changes | Final run | Result |
|---|---|---|---|
| obase | `1 skipped, 1 warning, 1 error in 2.03s` | `1 skipped, 1 warning, 1 error in 1.30s` | Existing collection blocker: missing `docker`. |
| oprim | `177 failed, 5379 passed, 18 skipped, 3 xfailed, 31 warnings, 17 errors in 92.77s` | `177 failed, 5408 passed, 18 skipped, 3 xfailed, 31 warnings, 17 errors in 97.76s` | Legacy failures/errors unchanged; +29 passing tests. |
| oskill | `272 failed, 3898 passed, 3 skipped, 183 warnings in 131.80s` | `272 failed, 3917 passed, 3 skipped, 183 warnings in 140.33s` | Legacy failures unchanged; +19 passing tests. |
| omodul | `1 warning, 2 errors in 13.16s` | `1 warning, 2 errors in 8.84s` | Existing collection blockers: missing `croniter` and missing `_current_trail` import. |
| oservi | `433 passed, 1 skipped in 1.85s` | `433 passed, 1 skipped in 1.41s` | Full suite passes; baseline run modified tracked bytecode, preserved unstaged. |
| Helios | `1 warning, 10 errors in 5.75s` | `1 warning, 10 errors in 4.51s` | Existing collection blockers including missing `chardet` and test-package import paths. |

Evidence summary: `evidence/pytest_final_20261022T022218Z.txt`; raw logs: `evidence/baseline_*.log`, `evidence/final_*_20261022.log`.

## Branch publication

Each repository's `feat/langalpha-3o` ref was pushed with a normal, non-forced push to `origin`, and then checked using `git ls-remote`. Full output is `evidence/push_feat_langalpha_3o_20261022T022502Z.log`.

- obase: `efa0c013b8dc2f7d5ae7ba3d2eba78688a6f7fc0` — https://github.com/helios-plat/obase/tree/feat/langalpha-3o
- oprim: `34b28e6452f98d59476a1b72741e0f28217fe58f` — https://github.com/helios-plat/oprim/tree/feat/langalpha-3o
- oskill: `a1248485fe301a6863207c1db7c3b92a0e86a377` — https://github.com/helios-plat/oskill/tree/feat/langalpha-3o
- omodul: `5b432095eada3ed126871c328c3c77a4046c3559` — https://github.com/helios-plat/omodul/tree/feat/langalpha-3o
- oservi: `dbcc5d13d71cbfeef7e86878981ebd2ada2f4538` — https://github.com/helios-plat/oservi/tree/feat/langalpha-3o (no source diff; branch records the task base)
- Helios: `2b4a4842442bed315ec557944003eb110bee224a` — https://github.com/soffy88/kanpan/tree/feat/langalpha-3o

No main branch was pushed or merged. No service was restarted or worktree cleaned. R1 execution is complete under the task’s baseline-comparison criterion: pre-existing full-suite failures are explicitly listed, no existing failure/collection-error counts increased, and no tests were removed or skipped to mask a regression.
