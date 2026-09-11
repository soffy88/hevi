# HEVI P0 Final Acceptance Evidence

AUDIT_RESULT=FAIL
PUSH_AUTHORIZED=NO

This is an evidence index for candidate `fe22f662cf1d5216a15219c01fb8991d843e3631`,
audited on 2026-09-11. It records executable evidence and does not promote
source existence, model declarations, or unit-only mocks to runtime PASS.
P1_STARTED=NO and P2_STARTED=NO.

## Commit chain

BASE_SHA=`0fcb65333ac5f6cd0860012fa569b6b050e22c6b`
BRANCH=`architecture/production-graph-vnext`
BASE_ANCESTRY=PASS
PHASE_COMMIT_COUNT=15
UNRELATED_COMMITS=0

The candidate is a clean descendant of the requested RC6 base. The 15 phase
commits, in order, are:

| SHA | Subject | P0 phase | Files changed |
|---|---|---|---|
| `49aa26699c0e054709bb0a3e5555590ceb9ed37c` | `docs(production-domain): inventory RC6 semantics and freeze ADR` | P0.0 | `docs/architecture/ADR-canonical-film-production-domain.md`, `docs/architecture/p0-phase-gates.md`, `docs/architecture/production-domain-inventory.md` |
| `42b97fb25db4816900d381f59bc0643b2175b13a` | `feat(production-domain): add canonical IDs and revision graph core` | P0.1 | `hevi/production_graph/{__init__.py,contracts.py,domain.py,ids.py,repository.py}`, `tests/test_production_domain_core.py`, phase-gate doc |
| `3cd2846a400e851152741cc1baee2bd6711b23c9` | `feat(narrative-graph): adapt Tongjian and Script2Video events` | P0.2 | `hevi/production_graph/adapters/{__init__.py,script2video.py,tongjian.py}`, adapter tests, phase-gate doc |
| `901a506a1ebb6188e39562cc386d0e2fd866eb36` | `feat(production-ontology): converge Vault identity and continuity state` | P0.3 | Vault adapter, domain, ontology tests, phase-gate doc |
| `0bd75042145f0f2180bb7cb9874f56bc9a0af235` | `feat(shot-domain): converge scene beat and canonical shot` | P0.4 | Cinematic adapter, domain, canonical-shot tests, phase-gate doc |
| `bd7b70d1334017c0aab4ba3db9fcedac99e81734` | `feat(shot-domain): add keyframe reference and continuity contracts` | P0.5 | keyframes, references, reference views, continuity, tests, phase-gate doc |
| `2e42e6e44c2d25140eb4889d3ab7977aa601f957` | `feat(shot-domain): enforce readiness state machine` | P0.6 | readiness, domain exports, tests, phase-gate doc |
| `72ba015632ba96a0bad28404e882b22e977b26b1` | `feat(production-compiler): compile canonical shots into immutable plans` | P0.7 | `hevi/compiler/{__init__.py,adapters.py,base.py,capabilities.py}`, compiler tests, phase-gate doc |
| `4215854e03580fc4796b43822b580c466a6f7e1f` | `feat(runtime): add resource-aware execution profiles` | P0.8 | Remotion workflow, resources, tests |
| `87234d7a7cbe8e62788c150dfbed21e4b8bfb278` | `feat(director): persist decisions through validated revision patches` | P0.9 | Director session, revisions, tests, phase-gate doc |
| `343a33f07b1774ec44f26aab268a291f3547945b` | `feat(studio): bridge ProductionPlan into Slate` | P0.10 | Slate bridge, exports, tests, phase-gate doc |
| `7857ced86b1a8f49a96baf647ac3e34ae8656170` | `feat(runtime): add durable TaskEnvelope side-effect semantics` | P0.11 | durable execution, domain/revision integration, tests, phase-gate doc |
| `0c631df8b915360d8552f971151bad557a6a97d0` | `feat(studio): add canonical domain API v2` | P0.12 | API router, domain/repository/revisions, API tests, phase-gate doc |
| `b881a125b5d473be68ff88aacc010de6d53f045c` | `feat(migration): add reversible legacy adapters and canonical indexes` | P0.13 | migration `f7a8b9c0d1e2`, adapters, migration tests, phase-gate doc |
| `fe22f662cf1d5216a15219c01fb8991d843e3631` | `test(production): add P0 golden E2E and provenance evidence` | P0.14 | golden fixtures/tests, provenance, updated domain/compiler/runtime/API tests, phase-gate doc |

The final row is related P0 evidence work, not a new P1/P2 phase. The audit
record itself may be committed as a docs-only follow-up; that does not alter
the 15 phase-commit count.

Exact changed-path index for the phase commits:

```text
P0.0 49aa26699c0e054709bb0a3e5555590ceb9ed37c
  docs/architecture/ADR-canonical-film-production-domain.md
  docs/architecture/p0-phase-gates.md
  docs/architecture/production-domain-inventory.md
P0.1 42b97fb25db4816900d381f59bc0643b2175b13a
  docs/architecture/p0-phase-gates.md
  hevi/production_graph/__init__.py
  hevi/production_graph/contracts.py
  hevi/production_graph/domain.py
  hevi/production_graph/ids.py
  hevi/production_graph/repository.py
  tests/test_production_domain_core.py
P0.2 3cd2846a400e851152741cc1baee2bd6711b23c9
  docs/architecture/p0-phase-gates.md
  hevi/production_graph/adapters/__init__.py
  hevi/production_graph/adapters/script2video.py
  hevi/production_graph/adapters/tongjian.py
  tests/test_production_graph_adapters.py
P0.3 901a506a1ebb6188e39562cc386d0e2fd866eb36
  docs/architecture/p0-phase-gates.md
  hevi/production_graph/adapters/__init__.py
  hevi/production_graph/adapters/vault.py
  hevi/production_graph/domain.py
  tests/test_production_ontology.py
P0.4 0bd75042145f0f2180bb7cb9874f56bc9a0af235
  docs/architecture/p0-phase-gates.md
  hevi/production_graph/adapters/__init__.py
  hevi/production_graph/adapters/cinematic.py
  hevi/production_graph/domain.py
  tests/test_canonical_shot.py
P0.5 bd7b70d1334017c0aab4ba3db9fcedac99e81734
  docs/architecture/p0-phase-gates.md
  hevi/production_graph/__init__.py
  hevi/production_graph/continuity.py
  hevi/production_graph/keyframes.py
  hevi/production_graph/reference_views.py
  hevi/production_graph/references.py
  tests/test_keyframe_reference_continuity.py
P0.6 2e42e6e44c2d25140eb4889d3ab7977aa601f957
  docs/architecture/p0-phase-gates.md
  hevi/production_graph/__init__.py
  hevi/production_graph/domain.py
  hevi/production_graph/readiness.py
  tests/test_shot_readiness.py
P0.7 72ba015632ba96a0bad28404e882b22e977b26b1
  docs/architecture/p0-phase-gates.md
  hevi/compiler/__init__.py
  hevi/compiler/adapters.py
  hevi/compiler/base.py
  hevi/compiler/capabilities.py
  tests/test_production_compiler.py
P0.8 4215854e03580fc4796b43822b580c466a6f7e1f
  hevi/assembly/remotion_render_workflow.py
  hevi/production_graph/__init__.py
  hevi/production_graph/resources.py
  tests/test_execution_profile.py
P0.9 87234d7a7cbe8e62788c150dfbed21e4b8bfb278
  docs/architecture/p0-phase-gates.md
  hevi/director/session.py
  hevi/production_graph/__init__.py
  hevi/production_graph/revisions.py
  tests/test_director_session_revisions.py
P0.10 343a33f07b1774ec44f26aab268a291f3547945b
  docs/architecture/p0-phase-gates.md
  hevi/studio/__init__.py
  hevi/studio/slate_bridge.py
  tests/test_slate_bridge.py
P0.11 7857ced86b1a8f49a96baf647ac3e34ae8656170
  docs/architecture/p0-phase-gates.md
  hevi/production_graph/__init__.py
  hevi/production_graph/domain.py
  hevi/production_graph/durable_execution.py
  hevi/production_graph/revisions.py
  tests/test_durable_execution.py
P0.12 0c631df8b915360d8552f971151bad557a6a97d0
  docs/architecture/p0-phase-gates.md
  hevi/api/main.py
  hevi/api/routers/studio_v2.py
  hevi/production_graph/__init__.py
  hevi/production_graph/domain.py
  hevi/production_graph/repository.py
  hevi/production_graph/revisions.py
  tests/test_studio_v2_api.py
P0.13 b881a125b5d473be68ff88aacc010de6d53f045c
  docs/architecture/p0-phase-gates.md
  hevi/db/alembic/versions/f7a8b9c0d1e2_create_canonical_production_indexes.py
  hevi/production_graph/adapters/__init__.py
  hevi/production_graph/adapters/canvas.py
  hevi/production_graph/adapters/studio.py
  hevi/production_graph/domain.py
  hevi/production_graph/migration.py
  hevi/production_graph/repository.py
  tests/test_legacy_migration_adapters.py
P0.14 fe22f662cf1d5216a15219c01fb8991d843e3631
  docs/API-CAPABILITIES.md
  docs/architecture/p0-phase-gates.md
  docs/openapi.json
  hevi/api/routers/studio_v2.py
  hevi/compiler/base.py
  hevi/compiler/capabilities.py
  hevi/db/alembic/versions/f7a8b9c0d1e2_create_canonical_production_indexes.py
  hevi/production_graph/__init__.py
  hevi/production_graph/adapters/cinematic.py
  hevi/production_graph/adapters/script2video.py
  hevi/production_graph/adapters/studio.py
  hevi/production_graph/adapters/tongjian.py
  hevi/production_graph/adapters/vault.py
  hevi/production_graph/domain.py
  hevi/production_graph/durable_execution.py
  hevi/production_graph/ids.py
  hevi/production_graph/keyframes.py
  hevi/production_graph/migration.py
  hevi/production_graph/provenance.py
  hevi/production_graph/readiness.py
  hevi/production_graph/references.py
  hevi/production_graph/repository.py
  hevi/production_graph/resources.py
  hevi/production_graph/revisions.py
  tests/golden/README.md
  tests/golden/gold_a_historical.json
  tests/golden/gold_b_novel.json
  tests/golden/gold_c_one_prompt.json
  tests/integration/test_canonical_production_p0.py
  tests/test_canonical_shot.py
  tests/test_director_session_revisions.py
  tests/test_keyframe_reference_continuity.py
  tests/test_production_compiler.py
  tests/test_production_domain_core.py
  tests/test_production_golden_e2e.py
  tests/test_studio_v2_api.py
```

## P0.0 inventory and ADR

PRODUCTION_DOMAIN_INVENTORY=`docs/architecture/production-domain-inventory.md`
CANONICAL_DOMAIN_ADR=`docs/architecture/ADR-canonical-film-production-domain.md`
SEMANTIC_INVENTORY_COMPLETE=PASS
ARCHITECTURE_INVARIANTS_DOCUMENTED=PASS

The inventory has rows for Tongjian, Cinematic, Script2Video, Director, Vault,
Canvas, Studio, Slate, and Artifact/runtime, with module, type, purpose,
persistence, authority, consumers, overlap, target canonical type, and one of
the required migration actions. The ADR freezes canonical ownership,
legacy-adapter strategy, Director/Slate boundary, Canvas projection,
compiler/adapter separation, revisions, readiness, provenance, resources, and
backward compatibility as explicit invariants.

## Canonical authority

The authoritative semantic definitions are in `hevi/production_graph/domain.py`
and persistence is in `hevi/production_graph/repository.py`. The definitions
are:

| Canonical object | Authoritative definition |
|---|---|
| ProductionProject, ProductionRevision | `hevi.production_graph.domain` |
| SourceDocument, SourceChunk | `hevi.production_graph.domain` |
| NarrativeGraph, NarrativeEvent, NarrativeEdge, PlotThread | `hevi.production_graph.domain` |
| Character, CharacterState, LookVariant | `hevi.production_graph.domain` |
| World, WorldRule, Location, LocationState, Prop, PropState | `hevi.production_graph.domain` |
| Season, Episode, Scene, Beat, CanonicalShot/Shot | `hevi.production_graph.domain` |
| CameraSpec, Keyframe | `hevi.production_graph.domain` |
| ReferenceBundle, ReferenceItem | `hevi.production_graph.domain` |
| ContinuityConstraint, ShotReadinessResult | `hevi.production_graph.domain` |
| DirectorSession, DirectorDecision, RevisionPatch | `hevi.production_graph.domain` and `hevi/production_graph/revisions.py` |
| ProductionPlan, ExecutionPlan, ExecutionAttempt | `hevi.production_graph.domain` |

Legacy convergence is implemented as follows:

| Legacy domain | Classification | Evidence |
|---|---|---|
| Tongjian | ADAPTER | `hevi/production_graph/adapters/tongjian.py` |
| Cinematic | ADAPTER | `hevi/production_graph/adapters/cinematic.py` |
| Script2Video/Novel2Video | ADAPTER | `hevi/production_graph/adapters/script2video.py` |
| Vault | ADAPTER over existing asset lifecycle | `hevi/production_graph/adapters/vault.py` |
| Canvas | PROJECTION | `hevi/production_graph/adapters/canvas.py` |
| Studio | PROJECTION/compatibility bridge | `hevi/production_graph/adapters/studio.py`, `hevi/studio/slate_bridge.py` |
| Slate/runtime | COMPATIBILITY execution boundary | `hevi/studio/slate.py`, existing MPT/provider runtime |

Legacy schemas remain DTOs or projections. They are not canonical semantic
authorities. Vault and ArtifactStore remain authoritative for binary/asset
lifecycle, as permitted by the architecture; no second artifact store was
introduced.

CANONICAL_AUTHORITY=PASS
LEGACY_AUTHORITIES_REMAINING_FOR_CANONICAL_OBJECTS=0

## Database authority and integrity

New migration:

`hevi/db/alembic/versions/f7a8b9c0d1e2_create_canonical_production_indexes.py`

New tables:

`production_graph_entities`, `production_graph_edges`,
`production_graph_readiness`.

Live catalog evidence against the disposable PostgreSQL test database at
`127.0.0.1:55432/hevi` reported:

```text
TABLES=production_graph_edges,production_graph_entities,production_graph_readiness
FKS=production_graph_edges.project_id->productions.id;
production_graph_edges.revision_id->production_revisions.id;
production_graph_entities.project_id->productions.id;
production_graph_entities.revision_id->production_revisions.id;
production_graph_readiness.project_id->productions.id;
production_graph_readiness.revision_id->production_revisions.id
ENTITY_INDEXES=ix_production_graph_entities_project_type,
production_graph_entities_pkey,uq_production_graph_task_idempotency
```

The migration pins project and revision ownership through foreign keys and
uses project/revision scoping plus a unique task idempotency index. Existing
artifact tables, MPT/task runtime, queue, checkpoint, and provider registry
are reused.

CANONICAL_DB_INTEGRITY=PASS
DUPLICATE_ARTIFACT_STORE=NO
DUPLICATE_TASK_RUNTIME=NO

## Adapter and boundary evidence

The following executable tests passed:

| Requirement | Test |
|---|---|
| TONGJIAN_ADAPTER=PASS | `tests/test_production_graph_adapters.py::test_tongjian_adapter_preserves_source_span_and_causal_edges` |
| CINEMATIC_ADAPTER=PASS | `tests/test_canonical_shot.py::test_cinematic_projection_drops_provider_transport_fields` |
| SCRIPT2VIDEO_ADAPTER=PASS | `tests/test_production_graph_adapters.py::test_novel_adapter_preserves_cross_event_order_and_source_binding` |
| VAULT_ADAPTER=PASS | `tests/test_production_ontology.py::test_vault_identity_pack_binds_identity_look_and_typed_refs` |
| STUDIO_ADAPTER=PASS | `tests/test_legacy_migration_adapters.py::test_studio_slate_round_trip_preserves_canonical_ids_as_projection_metadata` |
| CANVAS_PROJECTION=PASS | `tests/test_legacy_migration_adapters.py::test_canvas_is_a_projection_and_semantic_edits_require_canonical_identity` |
| DIRECTOR_DECIDES=PASS | `tests/test_director_session_revisions.py::test_director_decision_is_inspectable_and_patch_creates_child_revision` |
| SLATE_EXECUTES=PASS | `tests/test_slate_bridge.py::test_production_plan_becomes_a_deterministic_slate_work_order` |
| DIRECTOR_PROVIDER_BYPASS=NO | source audit of `hevi/director/session.py`, `hevi/production_graph/revisions.py`, and `hevi/studio/slate_bridge.py`; no provider HTTP dispatch from Director |
| CANVAS_AUTHORITY=PASS | Canvas adapter only projects canonical IDs/layout; semantic edits require validated canonical identity |

The existing `run_slate()` remains the deterministic work-order executor. The
new bridge is `hevi/studio/slate_bridge.py`; it does not move creative
reasoning into Slate.

## Compiler evidence

Interface: `hevi/compiler/base.py::ProductionCompiler.compile` and
`compile_with_fallback`.

Capability contract: `hevi/compiler/capabilities.py::ProviderCapabilities`.
Transport contract: `hevi/compiler/adapters.py::ProviderAdapter` with
send/poll/cancel/download/error transport responsibilities.

`CanonicalShot` uses a forbidden-extra-field model and
`tests/test_canonical_shot.py::test_canonical_shot_rejects_provider_specific_fields`
proves that provider request payload fields do not enter the canonical shot.
The compiler performs capability, reference, duration, resolution, prompt, and
resource checks; the adapter performs transport.

CANONICAL_SHOT_PROVIDER_INDEPENDENT=YES
COMPILER_ADAPTER_SEPARATION=PASS
PROVIDER_COMPILERS=generic `ProductionCompiler` capability compiler only; provider-specific Seedance/Veo/H3/Wan compiler implementations are NONE

## Readiness evidence

Implementation: `hevi/production_graph/readiness.py`.

Executable evidence includes:

- `tests/test_shot_readiness.py::test_ready_is_only_dispatchable_state`
- `tests/test_shot_readiness.py::test_illegal_readiness_transitions_and_locked_shots_are_rejected`
- `tests/test_production_compiler.py::test_compiler_rejects_unsupported_capabilities_and_limits`
- `tests/test_production_compiler.py::test_compiler_rejects_unready_shot_and_unavailable_resources`

These prove illegal state rejection and compiler rejection of non-ready,
unsupported, and unavailable-resource inputs. They do not provide independent
runtime readiness-context assertions for every required blocker (missing
reference, continuity, provider capability, and resource) or a dispatching
provider integration. Therefore:

SHOT_READINESS_RUNTIME_ENFORCED=PARTIAL

## Revision, locking, and camera evidence

Revision implementation: `hevi/production_graph/revisions.py`.

Passing evidence:

- `tests/test_production_domain_core.py::test_revisions_are_isolated_and_parented`
- `tests/test_director_session_revisions.py::test_stale_patch_and_locked_shot_are_rejected`
- `tests/test_production_compiler.py::test_compiler_emits_immutable_plan_with_pins_and_deterministic_idempotency`
- `tests/test_director_session_revisions.py::test_director_decision_is_inspectable_and_patch_creates_child_revision`

These prove old revisions remain readable, edits create child revisions,
plans pin project/shot/reference revisions, locks reject replacement, and
Director changes require validated `RevisionPatch` application.

REVISION_ISOLATION=PASS
LOCK_PROTECTION=PASS
EXECUTION_REVISION_PINNING=PASS
DIRECTOR_PATCH_VALIDATION=PASS

Camera selection implementation: `hevi/production_graph/reference_views.py`.
Passing tests are:

- `tests/test_keyframe_reference_continuity.py::test_camera_orientation_selects_right_view_deterministically`
- `tests/test_keyframe_reference_continuity.py::test_missing_orientation_falls_back_to_front_without_fabricating_view`

The implementation has front/profile/back support, but the candidate evidence
does not execute a front/left/profile/right/back matrix. Accordingly, static
orientation fields are not counted as acceptance proof.

CAMERA_REFERENCE_SELECTION=PARTIAL

## Resource and durable execution evidence

Resource implementation: `hevi/production_graph/resources.py`, with profile-aware
assembly support in `hevi/assembly/remotion_render_workflow.py`.
`tests/test_execution_profile.py` covers CPU limits 1 and 2, configured
concurrency above quota, effective-concurrency arithmetic, and graceful GPU
absence in planning/admission.

However, the real explainer path
`hevi/explainer/render.py::_run_remotion_render` still emits hard-coded
`--concurrency=4` and does not consume `ExecutionProfile`. This is a real
regression risk for the specified Remotion container mismatch.

RESOURCE_CONCURRENCY_CAP=FAIL
GPU_ABSENCE_GRACEFUL=PASS (planning/admission only; no GPU capability is claimed)

Durable implementation: `hevi/production_graph/durable_execution.py`.
The unit tests
`tests/test_durable_execution.py::test_intent_is_persisted_before_send_and_job_before_poll`,
`::test_restart_resumes_persisted_provider_job_without_duplicate_send`, and
`::test_idempotency_conflict_is_rejected` prove ordering, restart resume, and
idempotency using a controlled in-memory provider. The PostgreSQL integration
test `tests/integration/test_canonical_production_p0.py::test_canonical_snapshot_and_task_envelope_survive_restart`
proves TaskEnvelope persistence/reopen, but does not run the coordinator with
a real database-backed provider-job restart.

DURABLE_EXECUTION_RUNTIME_PROOF=PARTIAL
DUPLICATE_EXTERNAL_SIDE_EFFECTS=0 (controlled in-memory proof only; not a full external-provider acceptance proof)

An independent CPU runtime smoke did execute the existing
`run_production_plan` → `run_slate` path with the HyperFrames/FFmpeg fallback:

```text
PLAN=audit-cpu-production-plan
SLATE=audit-cpu-slate
ARTIFACT=/tmp/hevi-p0-runtime-audit.uZ7lgF/output/kinetic_promo.mp4
SHA256=4c63791ad5922abe7ae9f19bfee705646cbb11203b9858e05dbdd9a3a61bdf73
SIZE=29174
```

This is runtime smoke evidence, not a substitute for a permanent Golden
project with live provenance.

## Golden project audit

The three nominal Golden tests are in `tests/test_production_golden_e2e.py`,
but source inspection and execution classification show that they are not
end-to-end production lines.

### Gold A — historical

Fixture: `tests/golden/gold_a_historical.json`
Fixture SHA256: `6e89b4da13ac060a7f12c7996d634d3fd10ba924df5ee1ceead5d4b5cda2eb20`
Project ID: `gold-a`
Events: 2 (`gather`, `letter`)
Scenes: 1 (`gold-a-scene`)
Shots: 1 (`gold-a-shot`)
Source span: fixture `source_span` is carried into the adapted event and shot.
Nominal manifest: `/tmp` test output `gold-a-final-manifest.json` with SHA256
`44f40c77b693b029743d11ef54a4f23484f38e2cf31b6424396cbdc9a93d0405`.

The test manually constructs `ExecutionAttempt`, writes a JSON manifest, and
calls `production_plan_to_slate`; it does not call `run_slate`, a provider
adapter, or a media renderer. It therefore proves a graph/provenance-shaped
fixture only.

GOLD_A_SOURCE_PROVENANCE=PARTIAL
GOLD_A_FINAL_ARTIFACT=NOT_PRODUCED
GOLD_A_FINAL_SHA256=NOT_PRODUCED

### Gold B — long-form / novel

Fixture: `tests/golden/gold_b_novel.json`
Fixture SHA256: `863755858f49bdbb7c0b7109be1dd66470aa6a21bc75ae6ebac0357fc4d6c3d8`
Chapters: 2
Project ID: `gold-b`
Episodes: 2
Events: 2 (`arrive`, `return`)
Scenes: 2
Character states: 2
Look variants: 2
Plot threads: 1

The fixture demonstrates basic cross-chapter/event and state-shaped data, but
does not run a long-form production path and contains no completed Shot →
Keyframe → ReferenceBundle → Readiness → ExecutionPlan → Slate/runtime →
Artifact trace. No artifact was produced.

GOLD_B_LONG_FORM_SEMANTICS=FAIL
GOLD_B_FINAL_ARTIFACT=NOT_PRODUCED
GOLD_B_FINAL_SHA256=NOT_PRODUCED

### Gold C — one prompt

Fixture: `tests/golden/gold_c_one_prompt.json`
Fixture SHA256: `701af9367c93d5dd89f053f8f9263e9e92d186181f3423b108b5dd3d0b5ec141`
Input: `Make a tense 12-second vertical scene of an envoy crossing an old gate at dawn.`
Input SHA256 (without trailing newline): `7176e2a229ef27630189eea30400ef4de4afc41f5e9640e7595d08072a218149`
Project ID: `gold-c`

The test manually constructs Episode, Scene, Beat, CanonicalShot, and
ReferenceBundle and compiles them. It does not invoke a Director, create a
ProductionPlan from the sentence, run Slate/runtime, or produce an artifact.

GOLD_C_REAL_PRODUCT_PATH=FAIL
GOLD_C_FINAL_ARTIFACT=NOT_PRODUCED
GOLD_C_FINAL_SHA256=NOT_PRODUCED

Consequently, the required permanent Golden gates are not met:

GOLD_A=PARTIAL
GOLD_B=FAIL
GOLD_C=FAIL

## Provenance audit

`hevi/production_graph/provenance.py::provenance_chain` exists and the Gold A
test manually assembles a chain ending at `Artifact(gold-a-artifact)`. The
candidate does not produce a live final artifact through the complete chain,
and the tested chain lacks live DirectorDecision and prompt/skill-version
production evidence.

CREATIVE_PROVENANCE_COMPLETE=NO

Required missing runtime proof is:

`Source → NarrativeEvent → AdaptationDecision → Scene → Shot →
DirectorDecision → Prompt/Skill version → ReferenceBundle → ExecutionPlan →
ExecutionAttempt → Artifact SHA`.

## Test classification

RC6 baseline collection: 2735 tests. Candidate collection: 2787 tests. Net
increase: +52.

The +52 added tests classify as:

```text
UNIT=33
INTEGRATION=9
DATABASE=1
RUNTIME=9
GOLDEN_E2E=0
```

The three tests named as Golden are included in UNIT=33 because they construct
objects directly or write a manifest and do not execute a production line.
Thus the candidate has no accepted Golden E2E test evidence.

## Full regression evidence

The full gate was executed at exactly candidate SHA
`fe22f662cf1d5216a15219c01fb8991d843e3631`:

```text
FULL_PYTEST_PASSED=2758
FULL_PYTEST_SKIPPED=29
FULL_PYTEST_FAILED=0
FULL_PYTEST_ERRORS=0
COVERAGE=80.24%
CHECK_PASSED=PASS
RUFF_FORMAT=PASS
RUFF_LINT=PASS
FRONTEND_BUILD=PASS
PACKAGE_BUILD=PASS
```

The 29 skips are existing conditional/out-of-scope skips; no blanket skips
were added. Frontend evidence was 30 Vitest files / 156 tests plus typecheck
and Next build. Package evidence was `dist/hevi-6.0.0.tar.gz` and
`dist/hevi-6.0.0-py3-none-any.whl`.

## Secret and generated-file audit

Candidate diff audit found no committed `.env`, credentials, tokens, generated
media, MinIO data, logs, temporary benchmark files, or runtime database. The
pre-existing tracked `data/memory/studio.db` is baseline content, not a new
runtime artifact. Runtime smoke output remained under `/tmp` and was not
staged.

SECRET_SCAN=PASS
ACCIDENTAL_RUNTIME_ARTIFACTS=0

## Acceptance result

Passing areas: ancestry/phase chain, inventory/ADR, canonical authority,
database integrity, all six legacy adapters/projections, Director/Slate
boundary, provider-independent canonical shot, revision/lock semantics, GPU
absence planning, and the reported full regression gate.

Blocking gaps found by evidence audit:

1. Wire `ExecutionProfile` into the real explainer Remotion invocation; the
   hard-coded `--concurrency=4` currently allows the specified quota mismatch.
2. Add executable readiness-context/dispatch tests for each required blocker.
3. Add front/left/profile/right/back plus ambiguous camera reference-selection
   matrix tests.
4. Exercise durable coordinator restart with the database-backed envelope and
   provider-job persistence, not only in-memory ordering.
5. Replace the nominal Gold A/B/C fixtures with permanent production-line
   E2E runs that create actual artifacts and SHA256 evidence. Gold B must be a
   genuinely multi-chapter long-form continuity run; Gold C must begin at the
   sentence and pass through Director/ProductionPlan/Slate/runtime.
6. Produce the complete live creative provenance chain including
   AdaptationDecision, DirectorDecision, prompt/skill versions, and artifact
   SHA.

P0_IMPLEMENTATION_COMPLETE=NO
P0_FINAL_ACCEPTANCE=NO
REMAINING_P0_GAPS=resource cap integration; readiness runtime coverage; camera matrix; database-backed durable restart; real Gold A/B/C E2E artifacts; complete live provenance

No push was performed because the mandatory acceptance gate failed. The
requested command `git push -u origin architecture/production-graph-vnext`
was therefore not authorized.

FINAL_SHA=`fe22f662cf1d5216a15219c01fb8991d843e3631` before this audit record
PUSHED=NO
REMOTE_SHA=NOT_CHECKED
SHA_MATCH=NOT_APPLICABLE
WORKTREE=clean before adding this audit record
