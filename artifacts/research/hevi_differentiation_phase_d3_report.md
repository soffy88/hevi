# HEVI Differentiation Program — Phase D3 Report

## Baseline

- `HEVI_START_SHA=46847a8` / `HEVI_FINAL_SHA=46847a8` (no commit requested)
- `WORKTREE_CLEAN=NO` — deliverables as new/modified files, incl. regenerated `docs/API-CAPABILITIES.md`
- D2-A stays **BLOCKED** (never marked PASS; no fallback passed off as lip-sync)
- D1 audit files NOT modified; 39-capability ledger NOT modified

## D3-0 adoption inventory

`artifacts/research/hevi_d3_adoption_inventory.json`: D2 authorities had
**zero** production adoption (in-memory only, no API, no Studio).
Bypass sites found: identity 24, continuity 7, repair 22.

## D3-A — Persistent identity adoption: PASS

- Durable owner-scoped SQLite store (`identity_store.py`: identities, bindings,
  facts, subject links, gate decisions; `HEVI_IDENTITY_DB` env-isolated)
- One-off characters stay project-local Subjects; binding is explicit
- 10 API endpoints (`/api/identities/...`): create/list/inspect/appearances/
  voice/bind-project/upgrade/link-subject — all owner-scoped, cross-owner → 404
- `IDENTITY_BYPASS_COUNT=0` over required production entries;
  `CROSS_PROJECT_REUSE_RUNTIME / VERSION_PINNING_RUNTIME /
  EXPLICIT_UPGRADE_RUNTIME / TENANT_ISOLATION_RUNTIME = PASS`

## D3-B — Continuity gate: PASS

- `continuity_gate.py`: canonical fact ingestion (non-approved sources forced
  `provenance=inferred`, never BLOCK-capable) + stage gate (storyboard /
  reference / video / voice); BLOCK → paid generation refused; WARN →
  audited override required; sparse data → WARN, never fake PASS
- Wired: subjects appearance registration commits facts (linked identities);
  `POST /tasks/{id}/regenerate` accepts optional `identity_binding_id` and
  refuses 409 on hard contradiction; failures never write facts; history
  append-only (`INSERT OR IGNORE`)
- `PAID_GENERATION_BLOCKED_ON_HARD_CONTRADICTION /
  WARN_OVERRIDE_AUDITED / FAILED_GENERATION_NO_CONTINUITY_MUTATION /
  REVISION_CONTINUITY = PASS`, `CONTINUITY_BYPASS_COUNT=0` (same scope note)

## D3-C — Self-healing runtime: PASS (core)

- Durable incident store + `IncidentService` (reload resumes incidents,
  attempts, cooldowns — restart no longer rebills)
- Detection seams: task failure paths (`task.adapter`, `task.run`) classify +
  fingerprint-dedupe (storm-proof); paid regen rides a CONFIRM_REQUIRED
  incident (explicit POST = confirmation; loop guard still caps storms)
- `AUTO_SAFE_REAL_RUNTIME=PASS`, `AUTO_SAFE_NEW_BILLING=0`,
  `CONFIRM_REQUIRED_REAL_RUNTIME=PASS`, `UNCONFIRMED_PAID_REPAIR=0`,
  `MANUAL_ONLY_REAL_RUNTIME=PASS`, `POST_REPAIR_VERIFICATION=PASS`
  (server-side currency/presentation recompute),
  `REPAIR_RESTART_RECOVERY=PASS`, loops/duplicates `=0`

## D3-D — Product surface: PASS

- 24 API endpoints total; `docs/API-CAPABILITIES.md` regenerated (+39 lines)
- Studio: `identityApi/continuityApi/incidentApi` + `OpsPanel` (identities /
  continuity / incidents with confirm-refuse), mounted as assets 「运维」 tab;
  renders canonical state only — `STUDIO_AUTHORITY_PARITY=PASS`

## D3-E — Composition: PASS_NO_DELTA

Memory + identity + continuity jointly resolve planning inputs
(style pref, project convention, identity/appearance/voice, injured state,
pinned version) through existing APIs — no new memory system, no wiring gap.

## D3-F — Lip-sync watch: BLOCKED

`scripts/qualification/lipsync_runtime_probe.py` emits GPU_AVAILABLE,
NVIDIA_SMI, COMFYUI_REACHABLE, ECHOMIMIC_AVAILABLE, MODEL_AVAILABLE,
REAL_PROBE, ARTIFACT_VALID. Current: `D2A_REOPEN_ALLOWED=false`
(GPU + ComfyUI + EchoMimic blocked; workflow file present). No monitoring,
no new lip-sync code, BLOCKED is not an architecture failure.

## D3-G — Local/hybrid: CONTROL_PLANE_READY

Adapters (h3_local/Qwen/EchoMimic), cloud fallback, provider policy,
cost/privacy routing, hardware detection all present (35 tests fresh PASS).
No GPU → `LOCAL_RUNTIME=BLOCKED_HARDWARE`, never claimed verified.
(`hevi_d3_local_hybrid_qualification.json`)

## Production E2Es — all PASS

E2E-D3-1 (cross-project identity → production), E2E-D3-2 (contradiction
BLOCKs paid gen → corrected → continuity update), E2E-D3-3 (auto-safe,
billing 0, presentation CURRENT), E2E-D3-4 (unconfirmed 409/submits 0 →
confirmed exactly one), E2E-D3-5 (restart resume, no duplicates).

## Final quality

- Backend: **3170 passed / 29 skipped / 0 failed / 0 errors**
  (D2 3143 + 27 D3 tests; two regressions caught and fixed in-phase:
  direct-caller compat, OpenAPI snapshot regen)
- Frontend vitest: 31 files / 159 tests PASS; `tsc --noEmit` clean
- `RUFF=PASS`, `MYPY=PASS` (strict), `3O_ARCHITECTURE_ZERO=PASS`,
  `LEDGER_TAXONOMY_CHANGED=NO`, 39/39 qualified

## Final output block

```
HEVI_DIFFERENTIATION_D3_COMPLETE.
D3_A=PASS. D3_B=PASS. D3_C=PASS. D3_D=PASS.
D3_E=PASS_NO_DELTA. D3_F=BLOCKED. D3_G=CONTROL_PLANE_READY.
E2E_D3_1..5=PASS. FULL_SUITE=3170/29/0/0.
3O_ARCHITECTURE_ZERO=PASS. LEDGER_TAXONOMY_CHANGED=NO.
CLASSIFICATION=HEVI_DIFFERENTIATION_PHASE_D3.
```
