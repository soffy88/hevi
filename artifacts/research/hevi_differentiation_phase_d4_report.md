# HEVI Differentiation Program — Phase D4 Report (Long-Horizon Moat Qualification)

## Baseline

- `HEVI_START_SHA=46847a8` / `HEVI_FINAL_SHA=46847a8` (no commit requested)
- `WORKTREE_CLEAN=NO` — deliverables as new/modified files
- No new large capability, no second authority, no taxonomy change
- D2-A lip-sync and local GPU stay **BLOCKED** (honestly)

## D4-0 — Legacy internal path accounting

`hevi_d4_legacy_path_inventory.json`: 47 sites classified
(SAFE_COMPAT_DELEGATE 12, INTERNAL_NON_AUTHORITY 34, DEAD_CODE 1,
MIGRATE_REQUIRED 0, UNKNOWN 0).
**`PRODUCTION_AUTHORITY_LEGACY_BYPASS=0`** — no legacy path can change
canonical authority truth (identity registry / continuity ledger /
incident store) except through the service layer. Project-local stores
(subjects, task rows, config_json) are their own authority by design.

## D4-A — Long-horizon persistent identity: PASS

- 1 owner / 3 projects / 3+ revisions / 2 appearances / 1 voice; pinned
  vs explicit-upgrade; historical artifacts resolve original appearance
  and voice snapshots; durable round-trip preserves all history.
- New alias lifecycle (`rename_identity` preserves old canonical name as
  alias, `add_alias`, `remove_alias` with canonical immutability) and
  appearance/voice version history (`appearance_at_version`,
  `voice_at_version`, `resolve_pinned_*`).
- `HISTORICAL_IDENTITY_DRIFT=0`.

## D4-B — Long-horizon continuity: PASS

- 72 facts across 3 episodes × 4 scenes × 3 shots; fact supersession
  (`supersedes` + `active_facts`) preserves history; append-only durable
  store.
- Validation deterministic; `FALSE_BLOCKS=0`; inferred facts never
  upgrade to hard canon; `HISTORICAL_FACT_DRIFT=0`.
- BLOCK decisions now persisted (non-override) so metrics can count
  refusals without changing the paid-generation refusal.

## D4-C — Self-healing soak/chaos: PASS

- 20-failure storm collapses to 1 incident (fingerprint dedupe, persisted
  `dedupe_hits`); mixed failure families stay distinct; restart at every
  lifecycle stage resumes same incident/action/attempts/cooldown;
  exhaustion at max attempts; cost ceiling (AUTO_SAFE=0, paid requires
  confirmation, budget-bound policy honored).
- `DUPLICATE_REPAIR_SIDE_EFFECTS=0`, `DUPLICATE_REPAIR_BILLING=0`,
  `INFINITE_REPAIR_LOOPS=0`.

## D4-D — Concurrency / multi-user: PASS

- Incident owner-scoping added (model `owner_id`, store column+index,
  service param, router enforcement → cross-owner read/write refused).
- Atomic transitions: service re-reads fresh row under a process lock and
  persists with a compare-and-swap on prior status
  (`REPAIR_CONCURRENT_MODIFICATION` on conflict).
- 3-owner threaded E2E; `LOST_UPDATES=0`; `CROSS_TENANT_*_LEAKS=0`.

## D4-E — Persistence / corruption safety: PASS

- Schema versioning (`schema_version` table; too-new schema fails closed
  with no destructive rebuild; forward ALTER for `owner_id`).
- Crash-mid-transaction leaves no partial state; failed validation never
  reaches the store.
- Backup/restore (SQLite online-backup) fully consistent; restart on the
  restored copy resumes with no duplicate side effects.

## D4-F — Product metrics: PASS

`differentiation_metrics.py` reads only canonical stores (no second
analytics truth): IDENTITY_REUSE_RATE, CONTINUITY_BLOCKS_CAUGHT,
CONTINUITY_WARNINGS_OVERRIDDEN, AUTO_SAFE_REPAIRS, PAID_REPAIRS_CONFIRMED,
FAILED_REPAIRS, REPAIR_MEAN_ATTEMPTS, DUPLICATE_BILLING_PREVENTED,
ARTIFACTS_PRESERVED_BY_REPAIR.

## D4-G — Lip-sync / local runtime: BLOCKED (correct)

Probe re-run: `GPU_AVAILABLE=NO` → stopped immediately. No model download,
no runtime start. `LIPSYNC_RUNTIME=BLOCKED`, `LOCAL_RUNTIME=BLOCKED`.

## D4-H — Claim matrix

`hevi_differentiation_claim_matrix.json`:
Persistent identity, Continuity-aware production, Self-healing
production, Multi-user isolation = **VERIFIED**; Creative memory =
**PARTIAL** (backend/API, no Studio surface, unscoped endpoints);
Local/hybrid and Lip-sync = **BLOCKED**. Explicit over-claim prohibitions
recorded.

## E2E-D4-1..6: all PASS

Three-project pinning; multi-episode continuity; 20-failure storm;
repair + 3 restarts; 3-owner concurrency; durable backup/restore.

## Final quality

- Backend **3199 passed / 29 skipped / 0 failed / 0 errors** (D3 3170 + 29 D4)
- Frontend vitest 31 files / 159 tests PASS; `tsc --noEmit` clean
- `RUFF=PASS`, `MYPY=PASS` (strict), `3O_ARCHITECTURE_ZERO=PASS`,
  `LEDGER_TAXONOMY_CHANGED=NO`, 39/39 qualified

## Final output block

```
HEVI_DIFFERENTIATION_LONG_HORIZON_QUALIFIED.
D4_A=PASS. D4_B=PASS. D4_C=PASS. D4_D=PASS. D4_E=PASS. D4_F=PASS.
D4_G_LIPSYNC=BLOCKED. D4_G_LOCAL=BLOCKED. D4_H=CLAIM_MATRIX_WRITTEN.
E2E_D4_1..6=PASS. FULL_SUITE=3199/29/0/0.
PRODUCTION_AUTHORITY_LEGACY_BYPASS=0.
3O_ARCHITECTURE_ZERO=PASS. LEDGER_TAXONOMY_CHANGED=NO.
CLASSIFICATION=HEVI_DIFFERENTIATION_LONG_HORIZON_QUALIFIED.
```
