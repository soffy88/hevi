# HEVI Differentiation Program — Phase D2 Report

## Baseline

- `HEVI_START_SHA=46847a8` (= tag `hevi-arcreel-p0-p1-production-closure-2026-09-19`)
- `HEVI_FINAL_SHA=46847a8` (no commit requested; work delivered in worktree)
- `WORKTREE_CLEAN=NO` — phase deliverables present as new files plus one
  exports-only edit; pre-existing runtime modifications
  (`data/memory/studio.db`, 3O audit SHA re-point) left untouched.
- D1 audit files (`hevi_differentiation_audit_v1.json/md`) NOT modified.

## Canonical TOP 3 (from audit JSON, not from abbreviations)

- **D1-A** — "Verified lip-sync talking head (digital human)"
- **D-C** — "Verified character/story continuity (multi-character)"
- **D1-D** — "Verified production graph + auto-repair (pipeline robustness)"

## D2-0 fresh qualification

| Domain | Fresh status | Consequence |
|--------|--------------|-------------|
| D1-A lip-sync | **BLOCKED** — `generate_talking_face` routes correctly to EchoMimic/ComfyUI `127.0.0.1:8188`, which is unreachable; `nvidia-smi`: No devices were found; 8188/8383/gen-engine all down | D2-A STOPPED, definition not downgraded, no fallback marked verified |
| D-C character | **VERIFIED_PROJECT_SCOPED** — 51 tests fresh PASS; canon/continuity real but strictly project-scoped; cross-project persistent identity missing | D2-B APPROVED |
| D1-D repair | **VERIFIED_SUBSTRATE_WITH_GAPS** — 14 tests fresh PASS; detect/diagnose/plan/partial-execute present; unified incident + policy gates + enforced verification missing | D2-C APPROVED |

Full pre-qualification: `artifacts/research/hevi_d2_preimplementation_qualification.json`.

## D2-A — SKIPPED_BLOCKED

`REAL_LIPSYNC_RUNTIME=BLOCKED`, `LIPSYNC_FALSE_SUCCESS=0`. No code written
against a fake engine. E2E-DIFF-1 = SKIPPED_BLOCKED.

## D2-B — Persistent character & story continuity (IMPLEMENTED)

`hevi/creative/layer4/persistent_identity.py` (Layer 4, reuses
`Appearance`/`VoiceIdentity` — no second character/memory authority):

- `GlobalCreativeIdentity` (owner-scoped, private by default) vs
  `ProjectCharacterBinding` (per-project pinned versions + allow-listed overrides)
- Owner mismatch / anonymous owner fail closed — no cross-user leak
- `ContinuityLedger`: structured facts (character/appearance/location/prop/relationship/story) with episode/scene/shot/revision + source provenance
- `validate_pre_production`: PASS/WARN/BLOCK; BLOCK only for hard constraints (unknown identity, owner mismatch, unknown appearance, canon contradiction)
- Global mutation bumps version; bindings stay pinned; upgrade is explicit

Tests: `tests/creative_runtime/test_persistent_identity.py`, 8 passed.

## D2-C — Self-healing creative production (IMPLEMENTED)

`hevi/creative/layer4/repair_incident.py` (Layer 4, reuses `RepairKind`,
`normalize_failure`, currency primitives — no second orchestrator/graph):

- Canonical `RepairIncident` binding run + node + artifact + cause + evidence + actions + execution + verification
- Deterministic-first classification (known signatures never touch the agent); `UNKNOWN_NEEDS_AGENT` → agent PROPOSES into the graph only
- Policy gates `AUTO_SAFE` / `CONFIRM_REQUIRED` / `MANUAL_ONLY`; paid work can never ride the auto path (forced confirmation unless project policy allows budget-bound auto repair)
- Enforced post-repair verification (task + artifact + currency + presentation evidence; preserved artifacts must survive) — else `REPAIR_FAILED`
- Loop protection: max attempts (3), fingerprint dedupe, cooldown; duplicate execution refused (`DUPLICATE_SIDE_EFFECTS=0`, `HIDDEN_REBILLING=0`, `INFINITE_REPAIR_LOOPS=0`)

Tests: `tests/creative_runtime/test_repair_incident.py`, 16 passed
(7 C8 failure scenarios + cost/duplicate/loop/cooldown/agent-proposal + E2E-DIFF-3 with REAL currency re-evaluation).

## Next candidate (TOP 5 #4): D1-G — VERIFIED_SUBSTRATE, no delta

Creative memory/personalization freshly qualified (29 passed); namespaced
scope + project isolation + recall all present. No genuine missing link —
no speculative code added.

## Final quality

- `RUFF=PASS` (repo-wide), `MYPY=PASS` (strict, new modules)
- `FULL_SUITE`: **3143 passed / 29 skipped / 0 failed / 0 errors**
  (baseline 3119 + 24 new D2 tests)
- `3O_ARCHITECTURE_ZERO=PASS` (no new OBASE/OPRIM/OSKILL/OMODUL/OSERVI)
- `CAPABILITY_TOTAL=39`, `QUALIFIED=39`, `LEDGER_TAXONOMY_CHANGED=NO`
- Fault injection PASS (unit-level); security adversarial PARTIAL
  (isolation refusals tested); Studio E2E NOT_RUN (needs browser/GPU).

## Final output block

```
HEVI_DIFFERENTIATION_D2_COMPLETE.
D2_A_LIPSYNC_PRESENTER=SKIPPED_BLOCKED.
D2_B_PERSISTENT_CHARACTER=IMPLEMENTED.
D2_C_SELF_HEALING_PRODUCTION=IMPLEMENTED.
E2E_DIFF_1=SKIPPED_BLOCKED. E2E_DIFF_2=PASS. E2E_DIFF_3=PASS.
FULL_SUITE=3143 passed / 29 skipped / 0 failed / 0 errors.
3O_ARCHITECTURE_ZERO=PASS. LEDGER_TAXONOMY_CHANGED=NO.
CLASSIFICATION=HEVI_DIFFERENTIATION_PHASE_D2.
```
