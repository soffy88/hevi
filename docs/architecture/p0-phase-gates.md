# P0 phase gates

This file records the required evidence at the end of each P0 phase.  A
phase is coherent only when its files, schema, migration, tests and legacy
compatibility status are recorded.

## P0.0

PHASE=P0.0  
FILES_CHANGED=`docs/architecture/production-domain-inventory.md`, `docs/architecture/ADR-canonical-film-production-domain.md`, this file  
NEW_SCHEMA=none  
MIGRATIONS=none  
TESTS_ADDED=none  
TESTS_PASSED=inventory reviewed against RC6 source  
TESTS_FAILED=none  
LEGACY_COMPATIBILITY=baseline unchanged; unrelated dirty worktree excluded in a separate clean worktree  
KNOWN_GAPS=canonical domain not yet implemented  
COMMIT=docs(production-domain): inventory RC6 semantics and freeze ADR

## P0.2

PHASE=P0.2  
FILES_CHANGED=`hevi/production_graph/adapters/` and `tests/test_production_graph_adapters.py`  
NEW_SCHEMA=Tongjian and Script2Video narrative adapter contracts  
MIGRATIONS=none; adapters target the existing immutable revision snapshot  
TESTS_ADDED=source-span preservation, causal edge mapping, cross-event ordering, stable legacy identity mapping  
TESTS_PASSED=8 focused tests including P0.1 and legacy graph contracts  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=Tongjian `ChapterIR` and Script2Video `NovelPlan` remain unchanged and can still be consumed by their old workflows  
KNOWN_GAPS=Cinematic/Studio/Vault/Canvas adapters and dual-read API follow in P0.3/P0.4/P0.13  
COMMIT=feat(narrative-graph): adapt legacy narrative schemas

## P0.1

PHASE=P0.1  
FILES_CHANGED=`hevi/production_graph/ids.py`, `hevi/production_graph/domain.py`, `hevi/production_graph/contracts.py`, `hevi/production_graph/repository.py`, `hevi/production_graph/__init__.py`, `tests/test_production_domain_core.py`  
NEW_SCHEMA=canonical Pydantic graph records and immutable `ProductionGraphSnapshot`; legacy execution-plan imports re-export the canonical plan  
MIGRATIONS=reuses RC6 `productions` and `production_revisions`; canonical snapshots are persisted under the existing immutable revision row  
TESTS_ADDED=stable ID namespace, source span validation, revision isolation/parenting, referential integrity, legacy execution-plan DAG compatibility  
TESTS_PASSED=6 focused tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=existing `tests/test_production_graph_contracts.py` passes; old `ProductionGraphRepository` CRUD and execution-plan persistence API retained  
KNOWN_GAPS=canonical narrative/ontology adapters, readiness, compiler, runtime envelope and API are subsequent P0 phases  
COMMIT=feat(production-domain): add canonical IDs and revision graph core

## P0.3

PHASE=P0.3  
FILES_CHANGED=`hevi/production_graph/domain.py`, `hevi/production_graph/adapters/vault.py`, `hevi/production_graph/adapters/__init__.py`, `tests/test_production_ontology.py`  
NEW_SCHEMA=Character/CharacterState/LookVariant, World/Location/Prop state and Vault reference bindings  
MIGRATIONS=none; existing Vault manifests and ArtifactStore remain the binary authorities  
TESTS_ADDED=published IdentityPack binding, typed identity/motion refs, cross-episode look/state change, prop ownership, repository reopen  
TESTS_PASSED=11 focused tests including P0.1/P0.2 and legacy graph contract tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=Vault `Manifest`/`ManifestFile` and existing identity-pack lifecycle unchanged; no binary storage duplicated  
KNOWN_GAPS=scene/beat/shot adapter, readiness and compiler follow  
COMMIT=feat(production-ontology): converge Vault identity and continuity state

## P0.4

PHASE=P0.4  
FILES_CHANGED=`hevi/production_graph/adapters/cinematic.py`, canonical scene/beat metadata, `tests/test_canonical_shot.py`  
NEW_SCHEMA=canonical `Scene`, `Beat`, `CanonicalShot`, `CameraSpec` projection boundary  
MIGRATIONS=none; existing Cinematic/Director documents remain compatibility DTOs  
TESTS_ADDED=Cinematic/Director projection, provider-field rejection, scene→beat→shot referential integrity  
TESTS_PASSED=11 focused tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=Cinematic shot planning and Director shot DTOs remain unchanged; legacy prompt is not made provider transport state  
KNOWN_GAPS=first-class keyframes, typed reference bundles, continuity/readiness/compiler remain  
COMMIT=feat(shot-domain): converge scene beat and canonical shot

## P0.5

PHASE=P0.5  
FILES_CHANGED=`hevi/production_graph/keyframes.py`, `references.py`, `reference_views.py`, `continuity.py`, exports, `tests/test_keyframe_reference_continuity.py`  
NEW_SCHEMA=first-class Keyframe roles, typed ReferenceBundle operations, camera-view selection and canonical continuity derivation  
MIGRATIONS=none; existing Vault files and ArtifactStore IDs are referenced, never copied  
TESTS_ADDED=START/PEAK/END promotion, lock protection, azimuth/facing view selection and front fallback, typed reference locking, continuity constraints  
TESTS_PASSED=16 focused tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=existing SceneStage camera/view helper and IdentityPack lifecycle remain available; canonical selector uses the same orientation convention  
KNOWN_GAPS=readiness gate, production compiler and runtime/resource contracts remain  
COMMIT=feat(shot-domain): add keyframe reference and continuity contracts

## P0.6

PHASE=P0.6  
FILES_CHANGED=`hevi/production_graph/readiness.py`, canonical shot readiness enum, `tests/test_shot_readiness.py`  
NEW_SCHEMA=explicit 14-state ShotReadiness machine and `ReadinessContext`/`ShotReadinessResult` gate  
MIGRATIONS=none; readiness is evaluated before existing runtime dispatch  
TESTS_ADDED=machine-readable blockers, all-gate readiness, READY-only dispatch, illegal and LOCKED transitions  
TESTS_PASSED=14 focused tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=existing task and Slate state machines are unchanged; this is the canonical pre-dispatch gate  
KNOWN_GAPS=compiler capability contract and resource profile are next  
COMMIT=feat(shot-domain): enforce readiness state machine

## P0.7

PHASE=P0.7  
FILES_CHANGED=`hevi/compiler/`, `tests/test_production_compiler.py`  
NEW_SCHEMA=ProviderCapabilities, ResourceBudget, transport-only ProviderAdapter and immutable canonical compiler ExecutionPlan  
MIGRATIONS=none; compiler output is accepted by existing immutable `ExecutionPlanRepository` through the existing bridge  
TESTS_ADDED=supported/unsupported intents, reference/duration/resolution/prompt/audio/budget limits, deterministic idempotency and provider fallback  
TESTS_PASSED=16 focused tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=existing ProviderRegistry and provider adapters are not replaced or expanded; compiler does not perform HTTP calls  
KNOWN_GAPS=resource discovery/profile and durable TaskEnvelope integration remain
COMMIT=feat(production-compiler): compile canonical shots into immutable plans

## P0.8

PHASE=P0.8  
FILES_CHANGED=`hevi/production_graph/resources.py`, Remotion runtime integration, `tests/test_execution_profile.py`  
NEW_SCHEMA=runtime `ExecutionProfile` with CPU quota, memory, GPU evidence, render/provider/IO caps and admission invariant  
MIGRATIONS=none; existing scheduler and MPT remain in place; Remotion receives an effective concurrency cap  
TESTS_ADDED=cgroup quota parsing, fractional/zero CPU handling, GPU absence, explicit profile wiring and concurrency cap  
TESTS_PASSED=5 focused resource tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=existing Remotion config and scheduler contracts remain valid; default behavior is conservatively capped from runtime evidence  
KNOWN_GAPS=canonical profile still needs propagation into ProductionPlan/TaskEnvelope and Studio API  
COMMIT=feat(runtime): add resource-aware execution profiles

## P0.9

PHASE=P0.9  
FILES_CHANGED=`hevi/production_graph/revisions.py`, `hevi/director/session.py`, `tests/test_director_session_revisions.py`  
NEW_SCHEMA=persistent DirectorSession/Decision boundary and validated RevisionPatch application to immutable child snapshots  
MIGRATIONS=none; current snapshot repository remains the persistence boundary  
TESTS_ADDED=inspectable decision, child revision isolation, stale patch rejection, locked shot protection, closed session rejection  
TESTS_PASSED=3 focused Director/revision tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=existing `run_director_loop()` is retained; no agent receives direct provider or repository mutation access  
KNOWN_GAPS=Director records need DB/API projection and ProductionPlan/Slate bridge follows in P0.10  
COMMIT=feat(director): persist decisions through validated revision patches

## P0.10

PHASE=P0.10  
FILES_CHANGED=`hevi/studio/slate_bridge.py`, Studio exports, `tests/test_slate_bridge.py`  
NEW_SCHEMA=canonical `ProductionPlan` to legacy `Slate` work-order bridge  
MIGRATIONS=none; the existing `run_slate()`/recipe/checkpoint path is retained as the execution boundary  
TESTS_ADDED=canonical IDs/mode/shot IDs survive bridge; empty line rejected  
TESTS_PASSED=2 focused bridge tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=RC6 Slate callers and deterministic recipes are unchanged; Director/compiler remain upstream of Slate  
KNOWN_GAPS=durable canonical TaskEnvelope and API v2 still follow  
COMMIT=feat(studio): bridge ProductionPlan into Slate

## P0.11

PHASE=P0.11  
FILES_CHANGED=`hevi/production_graph/durable_execution.py`, canonical TaskEnvelope fields, exports, `tests/test_durable_execution.py`  
NEW_SCHEMA=durable TaskEnvelope coordinator with intent-before-send, provider-job persistence, resume, retry, cancel and artifact registration semantics  
MIGRATIONS=none; the existing MPT/AttemptRepository remains the runtime persistence authority and can implement the store protocol  
TESTS_ADDED=intent ordering, provider-job persistence, restart resume without duplicate send, idempotency conflict and plan-to-envelope pinning  
TESTS_PASSED=4 focused durable execution tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=existing MPT, task service, queue and provider registry are not replaced; the coordinator is an integration boundary  
KNOWN_GAPS=PostgreSQL TaskEnvelope projection and Studio API are next; the in-memory store is test/local evidence, not production durability  
COMMIT=feat(runtime): add durable TaskEnvelope side-effect semantics

## P0.12

PHASE=P0.12  
FILES_CHANGED=`hevi/api/routers/studio_v2.py`, API registration, `tests/test_studio_v2_api.py`  
NEW_SCHEMA=versioned canonical Studio project/source/narrative/episode/scene/shot/readiness/compiler/director/run API surface  
MIGRATIONS=none in this phase; endpoints use `ProductionGraphRepository` and RevisionPatch, preserving existing `/api/studio` routes  
TESTS_ADDED=route registration and API project/source revision write/read with dependency-isolated repository  
TESTS_PASSED=route smoke plus focused Studio v2 API test  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=RC6 Studio tools, timelines and Slate endpoints remain registered; v2 never calls provider transport directly  
KNOWN_GAPS=task persistence and legacy dual-read/write index are completed in P0.13  
COMMIT=feat(studio): add canonical domain API v2

## P0.13

PHASE=P0.13  
FILES_CHANGED=`hevi/production_graph/adapters/canvas.py`, `studio.py`, `migration.py`, adapter exports, repository canonical indexes, `f7a8b9c0d1e2` migration, `tests/test_legacy_migration_adapters.py`  
NEW_SCHEMA=Canvas projection nodes with explicit production IDs; Studio/Slate compatibility projections; queryable canonical entity/edge/readiness indexes  
MIGRATIONS=dual-read canonical-first and canonical-first/legacy-projection write helpers; reversible Alembic indexes; no legacy table deletion  
TESTS_ADDED=Canvas layout-only vs semantic patch, missing identity rejection, Slate round-trip, canonical-first ordering and projection-failure semantics  
TESTS_PASSED=12 focused canonical/ontology/migration tests; Alembic head resolves to `f7a8b9c0d1e2`  
TESTS_FAILED=0 focused tests; live PostgreSQL upgrade not run because the local PostgreSQL service is unavailable  
LEGACY_COMPATIBILITY=Tongjian, Script2Video, Cinematic, Vault, Studio/Slate and Canvas remain available as adapters/projections; old schemas are not deleted  
KNOWN_GAPS=production TaskEnvelope DB store and permanent Golden E2E evidence remain in P0.14; live DB migration requires PostgreSQL  
COMMIT=feat(migration): add reversible legacy adapters and canonical indexes
