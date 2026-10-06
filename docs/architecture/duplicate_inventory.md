# Duplicate Inventory — P0-1 Baseline

**Date**: 2026-10-06 · **Baseline**: `5d8bf783`
Companion to `authority_map.md`. This file is the *countable* register: one row
per duplicate set, with the exact size, so a later phase can assert the count goes
down and cannot silently grow.

Every count here was produced by a `rg`/`python` command, not estimated. Where a
previously reported count was wrong, the corrected number is given.

## Summary

| # | Duplicate set | Reported earlier | **Verified** | Delta |
|---|---|---|---|---|
| 1 | Task/Run state machines | 6 + 2 coordinators | **7 + 3 coordinators** | +1 +1 |
| 2 | Production-truth candidates | 5 | **5** | — |
| 3 | Provider registries | 3 | **5** | **+2** |
| 4 | Admission seams | 7 | **6 gates + 1 observer** | −1 (4 and 5 are one impl) |
| 5 | Timeline representations | ~14 | **20** | **+6** |
| 6 | Render-plan authorities | not enumerated | **5** | new set |
| 7 | Artifact/hash authorities | 5 | **5** | — |
| 8 | Evidence systems | 6 | **6** | — |
| 9 | Final-verdict writers | 5 | **6 + 1 untyped** | **+1** |
| 10 | Failure-taxonomy enums | 3 | **5** | **+2** |
| 11 | Failure mappers | 4 | **10** (5 fail-open) | **+6** |
| 12 | Recipe systems | 3 | **3** | — |
| 13 | ShotSpec definitions | 2 | **2** | — |
| 14 | Revision mechanisms | not enumerated | **4** | new set |
| 15 | StoryBible definitions | 2 | **2** | — |
| 16 | Receipt vocabularies | 3 | **3** | — |
| 17 | Required failure classes present | 3/15 | **5/15 exact** | **+2** |

---

## 1. Task/Run state machines — 7 + 3 coordinators

Corrected: 7 machines, not 6. The addition is
`hevi/production/p6/runtime.py:43` `PipelineStage`, a shadow of
`hevi/production/p6/production_runtime.py:73` `RunState` **inside the same
package**; `hevi/production/p6/__init__.py:103` exports only `runtime`.

| Machine | Location | Store | Reach |
|---|---|---|---|
| `video_tasks` | `hevi/tasks/state_machine.py:18` | PG | **PROD** (canonical) |
| `production_revisions` | `hevi/production_graph/` | PG | **PROD** |
| `automation_runs` | `hevi/runs/models.py:14` | PG | **PROD** |
| `MissionStatus` | `hevi/missions/p3_types.py:21` | FS `mission.json` | TEST-ONLY |
| `UnifiedProductionRuntime` / `RunState` | `hevi/production/p6/production_runtime.py:73,506` | none | TEST-ONLY |
| `ProductionBatch` / `JobStatus` | `hevi/ops/p4_types.py:32,236` | FS `batch.json` | TEST-ONLY |
| `DirectionState` / `Lifecycle` | `hevi/creative/direction_state/state.py:9,21` | FS JSONL | TEST-ONLY |

Additional single-purpose state enums (not full machines, recorded so they are not
rediscovered as novel): `hevi/execution/models.py:59`,
`hevi/distribution/models.py:21`, `hevi/production/shot_readiness.py:38`,
`hevi/production/p7/asset_decision.py:41`,
`hevi/creative/layer4/endpoint_lifecycle.py:84`.

**Coordinators — 3, corrected from 2:** `hevi/tasks/task_service.py` (**PROD**, 24
importers), `hevi/scheduler/` (**PROD**, systemd unit), and
`hevi/creative/autonomous/execution.py:1` (**TEST-ONLY**) which nevertheless
self-declares `MissionExecutor` the "canonical execution substrate".

`GoalRun`: **0 hits in `.py`**. Referenced only in `docs/CURRENT_ARCHITECTURE_MAP.md:38`.

## 2. Production-truth candidates — 5

`hevi/production_graph/` (canonical) · `hevi/canvas/` · `hevi/runs/` ·
`hevi/missions/` · `hevi/production/p6/`.

Note the split: four have durable stores, `hevi/production/p6/` has **none**, yet
its `__init__.py` docstring frames P6 as the product authority. Full table in
`authority_map.md` §2.

## 3. Provider registries — 5, corrected from 3

| Registry | Location | Holds | Reach |
|---|---|---|---|
| `ProviderRegistry` | `hevi/providers/registry.py:24` | **provider objects** | **PROD** (canonical) |
| `PROVIDER_CATALOGUE` | `hevi/providers/facts.py:356` | declared facts | **PROD** |
| `PROVIDER_SPECS` | `hevi/provider_policy/runtime.py:38` | spec/health | **PROD** + HTTP |
| `RUNTIME_SPECS` | `hevi/providers/runtime_specs.py:247` | local render recipes | LIB |
| `PROVIDER_LIMITS` | `hevi/video/capability_guard.py:27` | numeric ceilings | **PROD** |

The two additions (`PROVIDER_LIMITS`, `RUNTIME_SPECS`) matter: `PROVIDER_LIMITS`
shadows `ProviderRegistry` capabilities with a local table
(`capability_guard.py:174` falls back only when the local table is silent), so it
wins by default on a question the registry should own.

`hevi/production/adapters.py:17` `ProductionAdapterRegistry` is **excluded** from
this count: VERIFIED it registers `source → coroutine` and holds no provider
object. Its name is misleading and is itself a duplicate-authority hazard.

## 4. Admission seams — 6 gates + 1 observer

Corrected from 7. `creative/layer4/plan_projection.py:238` imports
`endpoint_lifecycle.py`, so seams 4 and 5 are one implementation; and seam 7
(`runtime/provider/provider_probe.py:67,76`) raises nothing — its docstring at
`:71-73` says "never raises", making it an observer rather than a gate.

**No admission record type exists**: `admission_id` 0 hits, `executor_id` 0 hits.
Three verdict shapes: `AdmissionState` (`generation/evidence.py:34`),
`AdmissionVerdict` (`endpoint_lifecycle.py:415`), `AdmissionVerdict3`
(`plan_projection.py:214`).

## 5. Timeline representations — 20, corrected from ~14

Independent census command:
`rg '^class \w*(Timeline|TimelinePlan|BeatPlan|VisualBeatPlan|StoryboardBundle|ShotIR|TimelineSlot|ClipSpec)\b' hevi/`
returns 14 including legacy. Six further beat/shot/clip carriers carry timeline
semantics without a timeline-shaped name:

| # | Module:line | Name | Unit |
|---|---|---|---|
| 1 | `hevi/studio/timeline.py:61` | `Timeline` | float s (**only HTTP-exposed**) |
| 2 | `hevi/creative/layer4/editable_delivery.py:81` | `EditableTimeline` | int ms |
| 3 | `hevi/tongjian/schemas.py:165` | `Timeline` | int ms |
| 4 | `hevi/digital_human/schemas.py:197` | `TimelinePlan` | float s |
| 5 | `hevi/storygraph/shot_ir.py:64` | `ShotIR` | none |
| 6 | `hevi/production/p1_types.py:111` | `VisualBeatPlan` | float s |
| 7 | `hevi/production/p0_pipeline.py:74` | `TimelineLock` | int ms + sha256 (**canonical**) |
| 8 | `hevi/providers/hyperframes/compiler.py:15` | `HyperComposition` | float s |
| 9 | `hevi/narrative/timeline.py:8` | `NarrativeTimeline` | none (**DEAD**) |
| 10 | `hevi/assembly/music_to_video_workflow.py:48` | `BeatTimeline` | float s |
| 11 | `hevi/layer4_legacy/obase_support/creative.py:198` | `TimelineState` | none |
| 12 | `hevi/layer4_legacy/previs/oprim_impl/contracts.py:28` | `TimelineCue` | float s |
| 13 | `hevi/creative/direction_plan/models.py:131` | `BeatPlan` | Anchor→ms |
| 14 | `hevi/creative/layer4/script.py:57` | `StoryboardBundle` | none |
| 15 | `hevi/voicepro/schemas.py:40` | `TimelineSlot` | int ms |
| 16 | `hevi/openshorts/schemas.py:30` | `ClipSpec` | float s |
| 17 | `hevi/creative/director_contract.py:79` | `BeatSpec` | float s |
| 18 | `hevi/assembly/story_to_animation_workflow.py:61` | `StoryBeat` | float s |
| 19 | `hevi/layer4_legacy/obase_support/creative.py:211,420` | `StoryBeat`/`BranchBeat` | none |
| 20 | `hevi/motion/sequence.py:110`, `hevi/assembly/assembler.py:26`, `hevi/studio/jianying.py:22` | `PlannedShot`/`ShotSegment`/`JianyingClip` | mixed |

**Time-unit split: 8 float-seconds, 5 integer-ms, 7 no time field.** The two
user-facing ones (`studio/timeline.py` float s HTTP-exposed;
`editable_delivery.py` int ms) never import each other.

**Guard coverage: 0 of 20.** `tests/test_p6_0_architecture.py:35-40`
`P6_MODULES` is 4 modules; the banned set at `:596` includes `TimelineLock` and
`BeatPlan` — the two types it names canonical at `:601`.

## 6. Render-plan authorities — 5 (new set)

| Authority | Location | Kind |
|---|---|---|
| `RenderPlan` + `RendererId` | `hevi/renderers/base.py:60` | typed enum (**canonical by test assertion, TEST-ONLY**) |
| `preferred_renderers` / `allowed_renderers` | `hevi/production/p2_types.py:175-176` | **strings** |
| `renderers: list[str]` | `hevi/cinematic/animation_pipeline.py:189-216` | **strings** |
| renderer readiness strings | `hevi/production/shot_readiness.py:289,366` | strings |
| `providers/remotion/` | `hevi/providers/remotion/driver.py:7` | the de-facto path |

String-keyed selection bypasses the `RendererId` enum in at least three places.

## 7. Artifact/hash authorities — 5

`hevi/production/artifacts.py:20` (canonical, `integrity_ok()`) ·
`hevi/artifact_store/repository.py:37` · `hevi/execution/models.py:134` ·
`hevi/artifact/qualify.py` · `hevi/ops/p5_1_evidence.py:473`.

`hevi/artifact/qualify.py` and `hevi/production/artifacts.py` are **disjoint**:
the former never sees an `ArtifactManifest`. Only one projection exists between
any two systems (`production/adapters.py:205-207`).

## 8. Evidence systems — 6

`hevi/evidence/acquisition.py:73` (canonical — only mandatory checksum) ·
`hevi/quality/evidence.py:15` (**only persisted**, but no hash binding) ·
`hevi/ops/p5_1_evidence.py:53` + `p5_1_types.py:628` ·
`hevi/production/p6/schema.py:521` (**DEAD**) ·
`hevi/production/p7/evidence.py:28` ·
receipt `artifact_sha256` (`artifact_verification.py:473`, TEST-ONLY).

**`EvidencePack`: 0 hits repo-wide.** The inverse of the desired state: the
persisted system is unbound, the bound system is unpersisted.

## 9. Final-verdict writers — 6 + 1 untyped

| Writer | Location | Checksum-bound | HTTP |
|---|---|---|---|
| `ReceiptStatus` / `_receipt` | `artifact_verification.py:71,457` | **YES** | no |
| `DirectionVerdict` | `creative/direction_verify/models.py:65` | **YES** | no — **DEAD** |
| `ProductionVerdict` | `creative/autonomous/verdict.py:38` | indirect | no |
| `DeliveryGateResult` | `verdict/delivery_gate.py:52` | no | **YES** |
| `DeliveryVerdict` | `production/delivery_gate.py:39` | no | **YES** |
| `FinalReviewResult` | `verdict/final_review.py:97` | no | **YES** |
| raw dict | `hevi/studio/fulfill.py:386,440` | no type at all | **YES** |

**`REAL_VIDEO_ACCEPTED`: 0 code emitters**, VERIFIED
(`rg -c REAL_VIDEO_ACCEPTED --type py` → 0). Present only in
`artifacts/real_video/20261005T160434Z/RUN_SUMMARY.json`,
`artifacts/real_video/20261005T160122Z/RUN_SUMMARY.json`, `STATUS.md`. The
producing script writes `f"MACHINE_{status.value}"`
(`scripts/qualification/produce_first_real_video.py:806`).

## 10. Failure-taxonomy enums — 5, corrected from 3

`hevi/quality/taxonomy.py:8` `FailureCode` (18 members, canonical) ·
`hevi/acquisition/models.py:48` `AcquisitionFailure` ·
`hevi/generation/errors.py:6` (7 exception classes) ·
`hevi/production/p7/asset_decision.py:41` `AssetDecisionState` (lifecycle, not
failures) · `hevi/creative/layer4/repair_incident.py:57` `RootCauseCategory`.

## 11. Failure mappers — 10, of which 5 fail-open

Fail-open (unknown input becomes a real category):
`quality/taxonomy.py:78` → `DELIVERY_INTEGRITY` ·
`creative/layer4/blender_workflow.py:248` → `RETRY_TARGET` ·
`missions/p3_runtime.py:457` → `VISUAL_QA` ·
`creative/autonomous/repair.py:46` → `RETRY_TARGET` ·
`creative/layer4/plan_projection.py:302` → `PROVIDER_ERROR` (blame-shift).

Fail-closed: `resilience/errors.py:69` · `ops/p4_scheduler.py:178` ·
`production/p6/production_runtime.py:701`.

Partial: `creative/layer4/v2v_workflow.py:133`.

Substring classification present in three mappers, all explicitly forbidden by
convergence spec §13: `plan_projection.py:302-329` (`"TIMEOUT" in text`,
`"HTTP 429" in text`), `blender_workflow.py:248-286` (`combined_lower`),
`resilience/errors.py:68-96` (`_RETRYABLE_KEYS`).

## 12. Recipe systems — 3

| System | Count | Scorer | Constraints evaluated | Cap filter | Flag | Reach |
|---|---|---|---|---|---|---|
| S1 `ShotRecipe` `cinematic/shot_intelligence/` | **6** | no | partial | **no** | `SHOT_INTELLIGENCE_ENABLED` **off** | TEST-ONLY |
| S2 `CinematicRecipe` `production/p5_3/` | **80** | **yes** | **yes** | **yes** | none | LIB |
| S3 `ShotRecipeCard` `motion/recipe_card.py` | **152** | no | **no** | **no** | none | **PROD** (HTTP) |

**Count correction:** S2 is 80, not 63 — `recipes/__init__.py:1` docstring is
stale; VERIFIED by executing `load_all_recipes()`. Family split: CAMERA 23,
COMPOSITION 10, EVIDENCE 9, DATA 8, EMOTIONAL 8, EXPLAINER 8, PRODUCT 8,
PRESENTER 6.

**All 80 S2 recipes are `qualification_state=EXPERIMENTAL`** →
`library.list_qualified()` returns **0**.

**Recipe fixtures: 0.** No recipe-keyed entry in `tests/fixtures/` or `tests/gold/`.

## 13. ShotSpec definitions — 2

`hevi/creative/director_contract.py:142` (float s, **no provenance field**) ·
`hevi/erduo/schemas.py:92` (uses `start_ms`/`end_ms` int — the only spec-compliant
time representation of the two).

Constructed at exactly 3 sites; **no recipe type appears in any signature or body**.

## 14. Revision mechanisms — 4 (new set)

`hevi/production_graph/` `production_revisions` (canonical; `parent_id` is a plain
UUID with **no ForeignKey**) · `hevi/creative/layer4/editable_delivery.py:87,96`
(vestigial counter, 0 persistence) · `hevi/narrative/models.py:330`
(TEST-ONLY) · `hevi/creative/direction_state/` (TEST-ONLY).

**Typed revision linkage absent:** `supersedes_revision_id` 0 hits,
`invalidated_artifact_ids` 0 hits. `changed_fields` has 1 hit
(`creative/direction_verify/impact.py:55`) and is an in-memory `set[str]`.

## 15. StoryBible definitions — 2

`hevi/narrative/models.py:310` (canonical — richest contract in the repo: revision,
source_refs, `NarrativeProvenance:288`) ·
`hevi/layer4_legacy/obase_support/creative.py:295` (legacy flat).

## 16. Receipt vocabularies — 3

`hevi/execution/models.py:134` `ProductionReceipt` (fail-closed, no plan hash) ·
`hevi/production/p6/production_runtime.py:378` `ExecutionReceipt` (TEST-ONLY) ·
`hevi/narrative/models.py:279` `RevisionReceipt` (TEST-ONLY, 0 importers).

## 17. Required failure classes present — 5 of 15 exact

Corrected upward from 3. Exact tokens in code: `GENERATION_FAILED`,
`RENDER_FAILED`, `MEDIA_PROBE_FAILED`, `QUALITY_GATE_FAILED`,
`HUMAN_REVIEW_REQUIRED`.

Partial/near-miss: `PROVIDER_UNAVAILABLE` (raw string only),
`ASSET_NOT_FOUND` (prefix only), `TIMELINE_INVALID` (`TIMELINE_INVALID_JSON`),
`EVIDENCE_MISSING` (**lowercase**, so it cannot join the uppercase vocabulary).

Doc-only: `CAPABILITY_UNSATISFIED`, `PROVENANCE_MISSING`.
**Absent, 0 hits:** `INVALID_INPUT`, `ASSET_LOW_CONFIDENCE`,
`PROVIDER_RATE_LIMIT`, `TRANSCRIPT_FAILED`.

No single module contains more than two of the fifteen.

---

## Repository-state evidence (not implementation defects)

Recorded per instruction so these are never re-litigated as P0-1 findings.

| Fact | Evidence |
|---|---|
| 77 untracked `hevi/*.py` existed at `565a37c5` | git collapses untracked dirs, so the earlier reported "22" under-counted; 3412 untracked files total via `--untracked-files=all` |
| frozen by commit `5d8bf783` | 141 files, 40253 insertions, no refactoring |
| **6 baseline test failures** | identical with and without the WIP's tests, so pre-existing: `test_history_arc_adapter.py` ×2 (real assertion failure at an unmodified file), `test_library.py` ×4 (passes in isolation, fails in full-suite ordering) |
| manim qualification environment mismatch | `test_manim_is_qualified` in `tests/test_p9_1d_real_qualification.py` asserts manim **is** qualified; the code correctly returns `BLOCKED_BY_RUNTIME` because manim is not installed. Recorded as a **P0-4 blocker**, not fixed here. |
| `REAL_VIDEO_PROOF_001` immutable | `0ae70bae1401201bed568427f65941e168d07b4209f632262acd4843d2fc4585`, matches `FREEZE.json` + `FINAL_SHA256` |
| lint not clean at baseline | 112 ruff errors on `hevi/`+`tests/`, of which **98 pre-existing on tracked files**; 14 on newly added files |

## Immutability

`REAL_VIDEO_PROOF_001` was verified byte-identical before and after P0-1. P0-1
created no commits and modified no runtime code; the two files added under
`docs/architecture/` and `tests/architecture/` are documentation and tests only.
