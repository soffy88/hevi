# Authority Map — P0-1 Baseline

**Date**: 2026-10-06 · **Baseline**: `5d8bf783` (parent `565a37c5`)
**Method**: read-only call-graph tracing with `rg`; no module classified from its
name or docstring. Every claim below carries `file:line`. Claims are marked
VERIFIED (directly read or grepped) or INFERRED (conclusion from verified facts).

**Phase status: BLOCKED.** Twelve of thirteen concepts have an identifiable
canonical candidate. **Admission has none.** That is the finding, not a gap in the
mapping.

## How to read the reachability column

| Label | Meaning |
|---|---|
| **PROD** | imported by a module under `hevi/` or `services/` that is itself reachable from an HTTP/MCP/CLI entrypoint |
| **LIB** | imported by production code, but no entrypoint reaches it |
| **TEST-ONLY** | referenced only from `tests/` and `scripts/` |
| **DEAD** | no importer anywhere, including tests |

A `TEST-ONLY` or `DEAD` module may still be the semantically correct owner. It is
**not** the current canonical owner, because canonical selection in this phase is
gated on *actually called in production* (spec §5 Step 3).

---

## 1. Task / Run

**Canonical: `hevi/tasks/`** (`video_tasks` + `state_machine.py`) — **PROD**

VERIFIED: the only candidate with a real Postgres table, a transition validator
enforced inside a `SELECT … FOR UPDATE` transaction (`hevi/tasks/repository.py:117-129`),
and HTTP + MCP + systemd wiring (`hevi/mcp/server.py:21`,
`hevi/queue/worker_entrypoint.py:62`, `hevi/deploy/systemd/hevi-worker.service`).

| Candidate | Store | Writers | Reach | Verdict |
|---|---|---|---|---|
| `hevi/tasks/` | PG `video_tasks` | `repository.py:24,120-129`; `task_service.py:1146` | **PROD** | **CANONICAL** |
| `hevi/production_graph/` | PG `productions` + `production_revisions` | `repository.py:216,240,258` | **PROD** | competing (see §2) |
| `hevi/runs/` | PG `automation_runs` | `runs/repository.py:24,42` | **PROD** | competing |
| `hevi/missions/` | FS `mission.json` | `p3_runtime.py:62` | **TEST-ONLY** | dead authority |
| `hevi/production/p6/` | **none** | never instantiated in prod | **TEST-ONLY** | false canonical claim |
| `hevi/ops/p4_types.py` | FS `batch.json` | `p4_scheduler.py:32` | **TEST-ONLY** (`p5_factory` has 0 importers) | dead |
| `hevi/creative/direction_state/` | FS JSONL | `repository.py:100,122,179,195` | **TEST-ONLY** | dead |
| `hevi/creative/autonomous/execution.py` | — | `execution.py:107` | **TEST-ONLY** (sole importer is one test) | dead |

**`GoalRun` does not exist** — VERIFIED, 0 hits in `.py`; the only mention is
`docs/CURRENT_ARCHITECTURE_MAP.md:38`.

Additional state machines found beyond the six previously audited (VERIFIED by
`rg -n "class \w*(Status|State|Stage)\(StrEnum\)"`): `hevi/execution/models.py:59`
`ExecutionState`, `hevi/distribution/models.py:21`, `hevi/production/shot_readiness.py:38`,
`hevi/production/p7/asset_decision.py:41`, `hevi/creative/layer4/endpoint_lifecycle.py:84`,
and a shadow duplicate *inside one package*: `hevi/production/p6/runtime.py:43`
`PipelineStage` vs `hevi/production/p6/production_runtime.py:73` `RunState` — the
package `__init__.py:103` exports only `runtime`.

**Competing authorities:** `automation_runs` — three routers (`tongjian.py:762,819`,
`shortdrama.py:79`, `explainer.py:44`) write status transitions directly, bypassing
`video_tasks` transitions entirely; bridged only by `hevi/runs/task_projection.py`,
which is itself imported by just two routers.

**Projection status:** `hevi/runs/task_projection.py:1-6` self-documents as
"project adapter runs into the shared `video_tasks` status surface" — an explicit
adapter, correctly scoped.

**Removal condition:** the three routers write through `TaskRepository.update_task`
and stop passing `status` to `AutomationRunRepository.update`; `director_pipeline.py`
serves reads from `video_tasks`.

## 2. Production

**Canonical: `hevi/production_graph/`** — **PROD**

VERIFIED: the only candidate with a normalized revision chain, an
`active_revision_id` FK (`hevi/db/alembic/versions/0a1b2c3d4e5f:67-71`), content
hashing (`director_documents.content_hash`), stage locks, and an HTTP reader at
`hevi/api/routers/director_pipeline.py:209`.

| Candidate | Store | Writers | HTTP-reachable | Verdict |
|---|---|---|---|---|
| `hevi/production_graph/` | PG `productions`, `production_revisions`, `stage_locks` | `repository.py:216,240` | `director_pipeline.py:209,245,279,832` | **CANONICAL** |
| `hevi/canvas/` | PG `canvas_graphs` (JSONB blob) | `graph_repository.py:20,34` | `api/routers/canvas.py`, MCP `canvas_tools.py` | competing |
| `hevi/runs/` | PG `automation_runs` | `runs/repository.py:24,42` | `tongjian.py:762` | competing |
| `hevi/missions/` | FS `mission.json` | `p3_runtime.py:62` | no | dead |
| `hevi/production/p6/` | **none** | none | no | dead |

**VERIFIED bypass:** `hevi/canvas/graph_models.py:14` is registered in
`hevi/db/models/__init__.py:3` but is written only via raw `insert_one`/`update_one`
— the ORM class mirrors a schema it never writes, so `canvas_graphs` and
`productions` are two write paths for one concept with no reconciliation.

**Projection status:** `hevi/api/routers/director_pipeline.py` is a read-through
projection, and `production_graph/__init__.py:1-5` states "a projection is never
the source of truth". Correctly scoped.

**Removal condition:** `canvas_graphs` gains `production_id` + `revision_no` FKs
and writes route through `ProductionGraphRepository.save()`; `tongjian`/`shortdrama`
runs become `productions.type` values rather than separate tables.

## 3. Revision

**Canonical: `production_revisions` in `hevi/production_graph/`** — **PROD**

VERIFIED: durable, ordered (`revision_no` + `UniqueConstraint`), append-only
`snapshot_json`, `parent_id` chaining at `repository.py:238`.

| Candidate | Mechanism | Reach | Verdict |
|---|---|---|---|
| `production_revisions` | PG, `parent_id` (**plain UUID, no ForeignKey** — `0a1b2c3d4e5f:44-65`) | **PROD** | **CANONICAL** |
| `hevi/creative/layer4/editable_delivery.py:87,96` | `revision_id` string + `edit_revision` int, `model_copy(update=…)`, in-memory only | read-only **PROD** (`authorities.py:736`) | vestigial counter |
| `hevi/narrative/models.py:330` | `StoryBible.revision`, caller-set string | **TEST-ONLY** (`narrative/persistence.py` has 0 importers) | dead |
| `hevi/creative/direction_state/` | per-revision directories + JSONL | **TEST-ONLY** | dead |

**Typed revision linkage: VERIFIED ABSENT.** `supersedes_revision_id` → 0 files.
`invalidated_artifact_ids` → 0 files. `changed_fields` → 1 file
(`hevi/creative/direction_verify/impact.py:55,68,72-98`), and that is an in-memory
`set[str]` for DAG propagation, not a revision record.

VERIFIED: `edit_revision` is a pure-function counter — `rg -n edit_revision hevi/`
returns only the four lines inside `editable_delivery.py`; no DB column, no
read-back, and every HTTP call rebuilds it at `default=1`. It is unreferenced state.

**Removal condition:** `production_revisions.parent_id` gains a real ForeignKey;
`edit_revision` is either persisted to a revision table or deleted as vestigial.

## 4. Provider Registry

**Canonical: `ProviderRegistry`** (`hevi/providers/registry.py:24`, re-export of
`obase.provider_registry`) — **PROD**

VERIFIED: the only registry holding live provider *objects/callables*
(`registry.py:213`, `:301`), populated at process boot
(`hevi/queue/worker_entrypoint.py:36`) and read by production code
(`hevi/director/intent.py:38`).

| Candidate | Holds | Writers | Reach | Verdict |
|---|---|---|---|---|
| `ProviderRegistry` | **provider objects** | `registry.py:213,245,284-384` | **PROD** | **CANONICAL** |
| `hevi/providers/facts.py:356` `PROVIDER_CATALOGUE` | declared facts only (`:143-183`) | static `_SEED:197` | **PROD** readers (`policy.py:102,107`; `framework.py:93,123,156`) | competing |
| `hevi/provider_policy/runtime.py:38` `PROVIDER_SPECS` | spec/health | static | **PROD** + HTTP `api/routers/providers.py:9` | competing |
| `hevi/providers/runtime_specs.py:247` `RUNTIME_SPECS` | local render recipes | static | **LIB** | competing |
| `hevi/video/capability_guard.py:27` `PROVIDER_LIMITS` | numeric ceilings | static | **PROD** (`kernel_service.py:82`; `authorities.py:619`) | competing |

That is **five** registries, not three. `PROVIDER_LIMITS` is the sharpest problem:
`capability_guard.py:174` falls back to `ProviderRegistry.get().capabilities()`
when the local table is silent, so one question has two sources with the local
table winning by default.

**`ProductionAdapterRegistry` is NOT a provider registry** — VERIFIED:
`hevi/production/adapters.py:48` registers `source → coroutine`
(`:154`, `:352`), holds no provider object and performs no qualification. It is a
task router over `v2v` / `template_qualification`. Its name invites misreading and
should be renamed in a later phase.

**False disclaimers:** `facts.py:19` and `runtime_specs.py:19-20` each list the
other as a fact source while re-declaring facts; neither disclaimer is implemented.

**Removal condition:** `PROVIDER_CATALOGUE` and `PROVIDER_LIMITS` can be deleted
only once every `provider_id` resolves through `ProviderRegistry.get(...).capabilities(...)`.

## 5. Qualification

**Canonical: NONE EXISTS.** — this concept has no candidate that satisfies the
selection criteria.

VERIFIED: the subsystem is a harness. `hevi/qualification/__init__.py:1-13` calls
itself "machine-readable production qualification contracts", but exactly **one**
production module reaches it, via **one** function: `hevi/creative/autonomous/acquire.py:24`
→ `hevi/qualification/media.py`. The runners
(`framework.py`, `http_runner.py`, `live_run.py`, `live_runner.py`,
`local_process.py`, `providers/*`) have **zero** non-test, non-script importers.

| Module | Reached from | Reach |
|---|---|---|
| `hevi/qualification/media.py` | `creative/autonomous/acquire.py:24` | **PROD** (sole) |
| `framework.py`, `http_runner.py`, `live_run*.py`, `local_process.py`, `providers/*` | intra-package only | **TEST-ONLY** |
| `hevi/providers/facts.py:143` `ProviderProfile` | `policy.py:107`, `framework.py:156` | **PROD** (facts, not verdicts) |
| `hevi/providers/runtime_specs.py:117` | `live_run.py:39`, `runtime/live/drivers.py:39` | **LIB** |
| `hevi/runtime/provider/models.py` `ProviderRuntimeStatus` | `acquire.py:36,101-103` | **PROD** |

**VERIFIED absent:** no provider declares `qualification_status` or
`qualification_evidence` anywhere in the provider model surface. The only
`qualification_status` in the repo is `hevi/video_intelligence/patterns.py:79`
(prompt templates, unrelated) and a DB column in
`hevi/db/alembic/versions/g0b1c2d3e4f5:129` that nothing reads.

**Competing "is this provider usable" vocabularies:** three — VERIFIED:
`PROVIDER_CATALOGUE.capability_state` (`facts.py:155`, values `AVAILABLE`/`UNRESOLVED`),
`generation/evidence.py:34` `AdmissionState`,
`runtime/provider/models.py` `RuntimeAvailability`.

VERIFIED contradiction: `hevi/qualification/__init__.py:9-12` openly documents a
duplicate media gate it declines to merge.

**Removal condition:** `framework.py` / `http_runner.py` / `live_run*.py` /
`local_process.py` are removable today (zero non-test importers). `media.py` and
`hevi/qualification/` are not removable while `acquire.py:24` calls them. Building
the qualification *authority* is P0-4 work, not P0-1.

## 6. Admission

**Canonical: NONE.** — VERIFIED. This is the P0-1 blocker.

Seven seams, of which **six** are independent. `plan_projection.py:238` imports
`endpoint_lifecycle.py`, so seams 4 and 5 are one implementation; the honest count
is six gates plus one observer.

| # | Location | Gates | HTTP-reachable | Admits / denies | Bypass |
|---|---|---|---|---|---|
| 1 | `provider_policy/policy.py:86,234` | provider selection by cost/quality/locality | **YES** `director_pipeline.py:1771`; `task_service.py:225` | denies (`:236`) | **YES** `task_service.py:194` returns early when the pool is not `PgPool`, silently skipping the gate |
| 2 | `generation/evidence.py:84` `try_admit` | LongCat capability admission | no | denies (`:92,96`) | **YES** `longcat_probe.py:160` derives `admitted` from the report it just wrote |
| 3 | `creative/autonomous/selection.py:202` `admit_generation` | asset→generation handoff | indirect via `p0→p1→p2→p3` | denies (`:213,220,229`) | **YES** see below |
| 4 | `creative/layer4/endpoint_lifecycle.py:462` | endpoint capability match | **YES** `authorities.py:224` | both, never raises | **YES** `authorities.py:370` never calls it |
| 5 | `creative/layer4/plan_projection.py:222,252` | pre-submit batch admission | **YES** `authorities.py:807,821` | both | **YES** `admit_single` is never called from `authorities.py`; batch does not gate the run route |
| 6 | `video/capability_guard.py:153` | mode/resolution/fps ceilings | **YES** `kernel_service.py:82` | denies (`:167,180,190`) | **PARTIAL** `mcp/tools/video_tools.py:46-51` rewrites the provider string to a hardcoded default *before* task creation |
| 7 | `runtime/provider/provider_probe.py:67,76` | reachability/latency | no | neither — docstring `:71-73` "never raises" | n/a (observer) |

**The sole-authority claim is false.** VERIFIED:
`hevi/creative/autonomous/selection.py:206` declares itself the only point where
generation may begin. It is contradicted by `hevi/api/routers/authorities.py:370-398`,
which creates and submits a production task with no admission call, and by
`hevi/creative/layer4/v2v_workflow.py:154-162`, which calls `happyhorse_animate` /
`i2v_animate` directly — reachable via `production/adapters.py:154,363`
(`execute_v2v`) → `task_service.py:58`.

**No admission record type exists.** VERIFIED: `admission_id` → 0 files,
`executor_id` → 0 files. `qualification_id` appears once, in
`scripts/build_release_evidence.py:85`, as `qualification_evidence_sha`. Three
unrelated verdict shapes: `AdmissionState` (`generation/evidence.py:34`),
`AdmissionVerdict` (`endpoint_lifecycle.py:415`),
`AdmissionVerdict3` (`plan_projection.py:214` — the suffix suggests a rename
already started).

**Canonical selection: BLOCKED.** Seam 1 is the only deny-capable seam on the HTTP
task path; seam 3 has the strongest claim and the only real implementation, but
reaches HTTP only through the `missions` graph, which is itself TEST-ONLY.
Designating either would violate an existing invariant or require adopting a
test-only module as an authority — the spec §22 stop condition
"current authority is only a dead/unwired module".

**Removal conditions:** seam 7 removable once nothing reads
`acquire.py:101`; seam 2 removable once `longcat_adapter.py:50` stops deriving
capability from a report only the report writes; seam 4 collapsible into seam 5
once `admit_single` is actually called.

## 7. Timeline

**Canonical: `hevi/production/p0_pipeline.py:74` `TimelineLock`** — **PROD**

VERIFIED: the only timeline type with an integrity binding — `audio_sha256:78`,
`subtitle_sha256`, and a fail-closed `verify_against:87`.

**20 representations, not 14.** VERIFIED census of `class *Timeline|*BeatPlan|
*VisualBeatPlan|*StoryboardBundle|*ShotIR|*TimelineSlot|*ClipSpec` gives 14
timeline-named classes including legacy, plus six further beat/shot/clip carriers
the name-based audit missed.

| # | Module:line | Time unit | Reach |
|---|---|---|---|
| 1 | `hevi/studio/timeline.py:41,61` | float **seconds** | **PROD** — only HTTP-exposed: `api/routers/studio.py:224`, `studio/ops.py:789-846` |
| 2 | `hevi/creative/layer4/editable_delivery.py:66,81` | integer **ms** | **PROD** `authorities.py:736` |
| 3 | `hevi/tongjian/schemas.py:165` | integer **ms** | **LIB** |
| 4 | `hevi/digital_human/schemas.py:163,197` | float **seconds** | **LIB** |
| 5 | `hevi/storygraph/shot_ir.py:64` | no time field | **PROD** (one importer) |
| 6 | `hevi/production/p1_types.py:63,111` `VisualBeat` | float **seconds** | **PROD** — but declared canonical by *test only* |
| 6b | `hevi/production/p0_pipeline.py:74` `TimelineLock` | integer **ms** + sha256 | **PROD** — **CANONICAL** |
| 7 | `hevi/providers/hyperframes/compiler.py:15` | float **seconds** | **PROD** |
| 8 | `hevi/narrative/timeline.py:8` | no numeric time | **DEAD** (0 importers) |
| 9 | `hevi/assembly/music_to_video_workflow.py:48` | float **seconds** | **PROD** HTTP `embrace_runtime.py:318` |
| 10 | `hevi/layer4_legacy/obase_support/creative.py:198` | no time field | **LIB** |
| 11 | `hevi/layer4_legacy/previs/oprim_impl/contracts.py:28` | float **seconds** | **LIB** |
| 12 | `hevi/creative/direction_plan/models.py:103,131` | Anchor → resolved ms | **PROD** |
| 13 | `hevi/creative/layer4/script.py:57` `StoryboardBundle` | no time field | **PROD** |
| 14 | `hevi/voicepro/schemas.py:40` | integer **ms** | **LIB** |
| 14b | `hevi/openshorts/schemas.py:30` | float **seconds** | **PROD** |

**The guard does not say what its message says.** VERIFIED:
`tests/test_p6_0_architecture.py:601` states "VisualBeat and TimelineLock are the
canonical timeline authority", but `P6_MODULES` (`:35-40`) is **only four**
modules — `p6.schema`, `p6.registry`, `p6.compiler`, `p6.runtime`. The banned set
(`:596`) includes `TimelineLock` and `BeatPlan`, i.e. it bans the very types it
names canonical, and it covers **none** of the twenty representations above. No
guard prevents `digital_human.schemas.TimelinePlan` and `studio.timeline.Timeline`
from coexisting.

VERIFIED fail-open in the live compile path —
`hevi/providers/hyperframes/compiler.py:72-85`: non-dict cuts dropped, unknown
action treated as "keep", missing `start_s` defaulted to `0.0`/`3.0`, unknown kind
coerced to `"card"`, duration clamped by `max(dur, 0.8)`. **No `raise` in the
module.** `p1_types.py:98` coerces negative duration to `0.0` rather than
rejecting; `p1_types.py:119-121` appends without sorting, so there is no
deterministic ordering.

**Explicit adapters:** only two — `hevi/creative/director_adapter.py:13-22`
(ShotIR + BeatPlan + ShotSpec → one) and `hevi/studio/anchor_resolver.py:43`
(Anchor → ms; docstring `:52` states it does not touch the Timeline model). The
other eighteen have no declared projection path.

**Removal condition:** `narrative/timeline.py:8` + `models.py:114` are deletable
now (zero importers, VERIFIED). The rest each need an adapter first.

## 8. Render Plan

**Canonical: `hevi/renderers/base.py:60` `RenderPlan`** — **PROD: NO. TEST-ONLY.**

VERIFIED: `rg "RenderPlan|renderers.base import" hevi services workflows tools deploy`
returns only docstring text (`hevi/production/p6/schema.py:22,284`). Zero importers
in `hevi/api` or `hevi/mcp`. Sole callers are `tests/test_p5_2_capabilities.py:95`
and `tests/integration/p5_2/*`.

This is the **second false canonical claim**, and the sharper one:
`tests/test_p6_0_architecture.py:583` asserts "hevi.renderers.base is the renderer
authority" for a module no production path reaches. The de-facto render path is
`hevi/providers/remotion/` + `hevi/creative/layer4/v2v_workflow.py:112` /
`blender_workflow.py:231`; `hevi/renderers/remotion.py:143-144` and
`providers/remotion/driver.py:7` say so in their own docstrings.

| Finding | Evidence |
|---|---|
| `RenderResult.content_hash` **never assigned** | declared `base.py:97`; the only other hit is a comment `remotion.py:144` saying it "stays at their default" |
| `ProductionReceipt` has no `plan_hash`/`timeline_hash` | `hevi/execution/models.py:134-148` fields are `receipt_id, run_id, artifact_id, artifact_checksum, producer, completed_at, validation_result` |
| `frame_deterministic` is asserted, never measured | `ffmpeg.py:121` and `html_gsap.py:428` assign literal `True`; `remotion.py:149` literal `False` |
| All three renderers are TEST-ONLY | VERIFIED per §5 table; `remotion.py`'s own docstring redirects to `hevi/providers/remotion/` |

VERIFIED competing selection vocabularies: `production/p2_types.py:175-176`
(`preferred_renderers`/`allowed_renderers` as **strings**),
`cinematic/animation_pipeline.py:189-216` (`renderers: list[str]`),
`production/shot_readiness.py:289,366`. String-keyed selection bypasses the
`RendererId` enum entirely.

VERIFIED tautology: `hevi/renderers/html_gsap.py:434`
`"evidence_present": not plan.required_evidence or True` always satisfies
`base.py:176`, silently defeating the evidence check.

**Projection status:** none. Nothing converts `VisualBeat` or a P6 grammar into a
`RenderPlan`; `hevi/production/p6/schema.py:22` forbids the import.

**Removal condition:** `hevi/renderers/` is deletable with replacement by
`hevi/providers/`, which already has three production callers.

## 9. Artifact

**Canonical: `hevi/production/artifacts.py:20-27` `Artifact.sha256`** — **PROD**

VERIFIED: the only artifact type with both a content-addressed id and an
in-process `integrity_ok()` (`:57-68`), enforced at `:244`, reachable from nine
HTTP routers (`tasks`, `tongjian`, `authorities`, `dashboard`, `history_series`,
`incidents`, `product`, `director_pipeline`, `cinematic`).

| Candidate | Hash binding | Writers | Reach |
|---|---|---|---|
| `hevi/production/artifacts.py` | `integrity_ok()` enforced `:244` | 14 importers | **PROD**, 9 routers |
| `hevi/artifact_store/repository.py:37` | requires `uri`+`sha256`+`byte_size` `:166-169` | 7 sites | **PROD** |
| `hevi/execution/models.py:134` `ProductionReceipt` | checksum-vs-validation enforced `:149-182` | `execute.py:175` | **LIB** (qualification only) |
| `hevi/artifact/qualify.py` | `INVALID_ARTIFACT` on mismatch `:211` | writes nothing (`:19`) | **LIB** |
| `hevi/ops/p5_1_evidence.py:473` `content_hash` | independent computation `:542` | — | **LIB** |

That is **five** independent hash authorities. VERIFIED: `artifact/qualify.py`
never sees an `ArtifactManifest` — the two systems are disjoint, and
`production/adapters.py:205-207` is the only manifest projection between them.

VERIFIED fail-closed strength worth keeping: `ProductionReceipt.__post_init__`
(`:149-182`) rejects empty ids, non-SHA256 checksums (`:163`), missing or failed
validation (`:167,174`), and **checksum mismatch against the validator's own
observation** (`:179`). That is the strongest integrity check in the repository and
should become the model.

**Removal condition:** `artifact/qualify.py` and `execution/models.py` are not
removable — they are the only fail-closed receipt path — but neither is reachable
from any router, which is the actual defect.

## 10. Evidence

**Canonical: `hevi/evidence/acquisition.py:73` `AcquisitionEvidence`** — **LIB**

VERIFIED: the only evidence type where a checksum is structurally mandatory
(`_SHA256_HEX` regex at `:89-96`) and verifiable against bytes (`verify_against:109`).

| Candidate | Binds artifact hash | Persisted | Reach |
|---|---|---|---|
| `hevi/evidence/acquisition.py:73` | **YES** (mandatory sha256) | no disk write | **LIB** — `acquire.py:136`; 0 API/MCP importers |
| `hevi/quality/evidence.py:15` `EvaluationEvidence` | **NO** — `artifact_id` is a free string; `task_service.py:312` writes `artifact_id=""` | **YES** `quality/repository.py:96` | **PROD** HTTP `authorities.py:385` |
| `hevi/ops/p5_1_evidence.py:53` + `p5_1_types.py:628` | no checksum (`asset_fingerprint` over url/title) | no | **LIB** |
| `hevi/production/p6/schema.py:521` `EvidenceClaim` | no — `source_refs` are bare strings | no | **DEAD** — zero construction sites outside tests |
| `hevi/production/p7/evidence.py:28` | no — `fingerprint():65` over own fields | no | **LIB** |
| receipt `artifact_sha256` (`artifact_verification.py:473`) | **YES** | returned dict | **TEST-ONLY** — only caller is `scripts/qualification/produce_first_real_video.py:725` |

**The central evidence finding:** VERIFIED — the *persisted* evidence authority
(`EvaluationEvidence` → Postgres) is the one **least** bound to bytes, while the
checksum-bound one (`AcquisitionEvidence`) is never persisted. The two lineages
are parallel and never joined.

VERIFIED: `EvidencePack` → **0 hits repo-wide**. No such type exists.

**Projection status:** none. No module converts `AcquisitionEvidence` →
`EvaluationEvidence` → receipt.

**Removal condition:** a receipt whose `artifact_sha256` is computed *from* an
`AcquisitionEvidence.checksum`, with `EvaluationEvidence.artifact_id` replaced by
that digest.

## 11. Acceptance

**Canonical: `hevi/production/artifact_verification.py:457` `_receipt`** —
**TEST-ONLY** (reachable only from `scripts/qualification/`).

VERIFIED: the only verdict carrying both `artifact_sha256` and `VERIFIER_VERSION`.

| Verdict type | Location | Checksum-bound | HTTP-reachable |
|---|---|---|---|
| `ReceiptStatus` + `_receipt` | `artifact_verification.py:71,457` | **YES** `:473` | **no** — scripts only |
| `DirectionVerdict` | `creative/direction_verify/models.py:65` | **YES** — raises `VERDICT_UNBOUND` `:80` | **no — DEAD** |
| `ProductionVerdict` | `creative/autonomous/verdict.py:38` | indirect (`artifact_validation.passed` `:68`, stores no hash) | no |
| `DeliveryGateResult` | `verdict/delivery_gate.py:52` | **NO** — ffprobe on path | **YES** `embrace_runtime.py:333` |
| `DeliveryVerdict` | `production/delivery_gate.py:39` | **NO** — size/duration only | **YES** `director_pipeline.py:2427`, `authorities.py:479`, `studio/ops.py:493` |
| `FinalReviewResult` | `verdict/final_review.py:97` | **NO** — booleans from the request body | **YES** `embrace_runtime.py:395` |
| (sixth shape) | `hevi/studio/fulfill.py:386,440` | raw dict `{"error": {"code": "QUALITY_GATE_FAILED"}}`, no type | **YES** |

**Six competing verdict writers; exactly one is checksum-bound and HTTP-reachable —
none.** The one checksum-bound verdict that exists (`DirectionVerdict`) is dead:
VERIFIED, `rg "DirectionVerdict\("` returns only `tests/p10/test_p10d_verify.py:47,51`.

**`FinalReviewResult` is the most severe.** VERIFIED: `run_final_review:122` takes
`inputs_present: dict[str,bool]` and `verdicts: dict[str,bool]` straight from the
HTTP request body and never touches a file. An HTTP client can POST
`{"inputs": {...}, "verdicts": {"D1": true}}` and receive `passed: true` with no
artifact involved.

**`REAL_VIDEO_ACCEPTED` has zero code emitters.** VERIFIED independently:
`rg -c REAL_VIDEO_ACCEPTED --type py` → **0 files**. The string exists only in
`artifacts/real_video/20261005T160434Z/RUN_SUMMARY.json`,
`artifacts/real_video/20261005T160122Z/RUN_SUMMARY.json` and `STATUS.md`. The
producing script writes `f"MACHINE_{status.value}"`
(`scripts/qualification/produce_first_real_video.py:806`), plus
`"REJECTED_BOUNDARY_QA"` (`:687`) and `status` (`:603`) — never this literal.
**The recorded acceptance is hand-written, and it disagrees with the code that
purports to have produced it.**

For contrast, `P11_LAYOUT_ACCEPTED` *is* emitted in code
(`scripts/qualification/run_p11_layout.py:341`) and is correctly gated on a human
review that has not happened, so its current verdict is
`P11_LAYOUT_AWAITING_HUMAN_REVIEW`.

**Removal condition:** every HTTP verdict path returns a receipt containing
`artifact_sha256`; the three path-only verdicts are demoted to pre-flight checks;
`run_final_review` stops accepting verdicts from its own request body.

## 12. Failure Taxonomy

**Canonical: `hevi/quality/taxonomy.py:8` `FailureCode` (18 members)** — **PROD**,
but only because nothing better exists. VERIFIED: it is the only taxonomy imported
by a canonical repair authority (`creative/layer4/repair_incident.py:43`) and by
HTTP-reachable code (`api/routers/director_pipeline.py`).

**Five enum families** (VERIFIED): `quality/taxonomy.py:8`,
`acquisition/models.py:48`, `generation/errors.py:6`,
`production/p7/asset_decision.py:41`, `creative/layer4/repair_incident.py:57`.

**Ten failure mappers, five fail-open:**

| Mapper | Unknown → | Fail-open |
|---|---|---|
| `quality/taxonomy.py:78,88` `normalize_failure` | `DELIVERY_INTEGRITY` at severity 5.0 | **YES** — a `None` becomes a measured integrity failure |
| `creative/layer4/blender_workflow.py:248,286` | `RETRY_TARGET` | **YES** — unknown crash is retryable |
| `missions/p3_runtime.py:457,473` | `VISUAL_QA` | **YES** |
| `creative/autonomous/repair.py:46,47` | `RETRY_TARGET` | **YES** |
| `creative/layer4/plan_projection.py:302,329` | `PROVIDER_ERROR` | partial — blame-shifts outward |
| `resilience/errors.py:69,97` | `UnretryableError` | no |
| `ops/p4_scheduler.py:178,193` | `PERMANENT` | no |
| `production/p6/production_runtime.py:701,721` | `RUNTIME_ERROR` + `FAILED` | no — explicitly no success branch `:706` |
| `creative/layer4/v2v_workflow.py:133,146` | `V2V_PROVIDER_FAILURE` | partial |

Substring classification VERIFIED in `plan_projection.py:302-329`
(`"TIMEOUT" in text`, `"HTTP 429" in text`), `blender_workflow.py:248-286`
(`combined_lower` keyword routing) and `resilience/errors.py:68-96`
(`_RETRYABLE_KEYS`/`_UNRETRYABLE_KEYS`). All three are exactly the forbidden
patterns in convergence spec §13.

**Required-class coverage: 5 of 15 exact.** VERIFIED token census:

| Required token | Status |
|---|---|
| `GENERATION_FAILED` | exact — `generation/errors.py:7` |
| `RENDER_FAILED` | exact — `creative/autonomous/repair.py:31` |
| `MEDIA_PROBE_FAILED` | exact — `artifact_verification.py:201,229,233,237` |
| `QUALITY_GATE_FAILED` | exact string — `distribution/safety.py:25`; `studio/fulfill.py:386` |
| `HUMAN_REVIEW_REQUIRED` | exact — `ops/p5_1_session.py:193,358,360` |
| `PROVIDER_UNAVAILABLE` | partial — raw string at `api/routers/voice_studio.py:264` |
| `ASSET_NOT_FOUND` | partial — `video_intelligence/runtime_adapters.py:71` prefix only |
| `TIMELINE_INVALID` | partial — `ops/p5_1_editable.py:648` `TIMELINE_INVALID_JSON` |
| `EVIDENCE_MISSING` | partial — **lowercase** `"evidence_missing"` at `acquisition/models.py:66`, so it cannot join the uppercase vocabulary |
| `CAPABILITY_UNSATISFIED`, `PROVENANCE_MISSING` | doc-only (`docs/p10/p10c_spec.md:76`, `p10b_spec.md:49`) |
| `INVALID_INPUT`, `ASSET_LOW_CONFIDENCE`, `PROVIDER_RATE_LIMIT`, `TRANSCRIPT_FAILED` | **absent, 0 hits** |

No single module contains more than two of the fifteen.

**Removal condition:** a `FailureClass` enum carrying all fifteen tokens, imported
by every mapper above, with `normalize_failure` returning `None` rather than
`DELIVERY_INTEGRITY` for unrecognized input.

## 13. Shot Recipe Selection

**Canonical: `hevi/production/p5_3/` `CinematicRecipe` (80 recipes)** — **LIB**
(intended authority, not currently canonical).

VERIFIED: the only system with a weighted scorer (`.30 semantic, .20 profile,
.15 asset, .10 capability, .10 duration, .10 historical, .05 variety` at
`library.py:219-247`), hard constraint exclusion (`:181-212`, `:218`),
capability exclusion (`:127`, `:207`), immutable versioning (`schema.py:307`
`qualified_id`), and the strongest adversarial test set
(`test_p5_3_adversarial.py` 30 fns, `test_p5_3_schema.py` 20 fns, +22 files).

| System | Recipes | Scorer | Constraint filter | Cap filter | Flag | Reach |
|---|---|---|---|---|---|---|
| S1 `ShotRecipe` `cinematic/shot_intelligence/` | **6** | **NO** — 2-tuple boolean+id tiebreak `selector.py:47` | partial | **NO** — `renderer_capabilities` never read as a filter | `SHOT_INTELLIGENCE_ENABLED` default `"0"` = **OFF** | **TEST-ONLY**, 0 selectors called in prod |
| S2 `CinematicRecipe` `production/p5_3/` | **80** (docstring `recipes/__init__.py:1` says 63 — **stale**) | **YES** | **YES** | **YES** | none | **LIB** — 3 importers, no entrypoint |
| S3 `ShotRecipeCard` `motion/recipe_card.py:32` | **152** (enforced `recipe_card.py:508-509`) | **NO** | **NO** — `validate_card:50` is static lint | **NO** | none | **PROD** — only HTTP-reachable: `GET /api/studio/motion/shot-cards` |

**No shared vocabulary.** VERIFIED: `rg "p5_3|shot_intelligence|recipe_card"`
inside all three package directories returns only self-references and docstrings.
No cross-imports; no system can read another's output.

**Recipe → ShotSpec: NO SUCH PATH EXISTS.** VERIFIED. Two `ShotSpec` classes
(`hevi/creative/director_contract.py:142`, `hevi/erduo/schemas.py:92`), constructed
at exactly three sites — `hevi/creative/director_adapter.py:81`
(`rg "ShotSpec\("`), `hevi/layer4_legacy/erduo/oprim_impl/__init__.py:110`, and
`tests/test_director_contract.py:39`. **No recipe type appears in the signature or
body of any of them.** The nearest bridges are `ShotPlan` (`models.py:84`),
`VisualBeat` (`p6/visual_compiler.py:536`, whose docstring says "creates no shot"),
and `ShotIR.from_recipe_card` (`storygraph/shot_ir.py:130`, no production caller).

**Two fail-open bugs, both VERIFIED:**

1. S1 `selector.py:45` — `candidates = fitting or candidates`: when no recipe fits
   `target_duration_s`, the duration filter is discarded and a non-fitting recipe is
   returned, with confidence silently dropping 0.9 → 0.65 (`:48-52`). **No test
   covers this branch.**
2. S2 `library.py:158-179` — `filter()` returns `self.search(...) if not recipes
   else [...]`: passing an empty list **searches the whole library** instead of
   returning empty.

**All 80 S2 recipes are `qualification_state=EXPERIMENTAL`** (VERIFIED by
executing `load_all_recipes()`) → `library.list_qualified()` returns **0**. The
strongest recipe system has qualified nothing.

**Production "selection" is a hardcoded dict.** `hevi/assembly/promo_video_workflow.py:150-156`
is a five-entry `role_card` map, reachable via HTTP
(`api/routers/embrace_runtime.py:323-392`). The library's own selector
`choose_motion_cards` is round-robin `cards[index % len(cards)]`
(`layer4_legacy/talkcraft/oskill_impl/compiler.py:24-27`), is legacy **and dead**
(zero production callers; `hevi/talkcraft/*` are 3-line re-export shims).

**Documentation authority without wiring authority.** VERIFIED: S1 is the only
system carrying `canonical: bool = True` on its plan (`models.py:88`) and the only
one with a documented authority boundary (`docs/P6-0-AUTHORITY-BOUNDARY.md:91`),
while having zero production selector callers and a flag that defaults off.

**Visual fixtures: NONE for any system.** VERIFIED: `tests/fixtures/` contains
`audio`, `creative_audit_gold`, `narrative_gold`, `video_quality_gold`,
`video_reel_gold`, `video_retrieval_gold`, `writing_naturalness` — none recipe-keyed.
`tests/gold/` contains only `creative_runtime/`, and
`test_storyboard_gold.py:64` calls `ShotSelector()` with no expected-recipe golden
data.

**Removal conditions:** S1 removable once the flag default flips, a production line
planner calls `plan_for_line`, and `selector.py:45` raises — nothing depends on it
today. S2 not removable (`p6/product_compiler.py:58`, `p6/visual_compiler.py:65`
are hard deps) and can only be *promoted*. S3 not removable (`api/routers/studio.py:147`
+ `embrace_runtime.py:392`); its dead `choose_motion_cards` path is removable now.

---

## False canonical claims to remove (spec §5 Step 4)

| Claim | Location | Reality |
|---|---|---|
| "canonical" ProductProfile/compiler singletons | `hevi/production/p6/` | entire package TEST-ONLY; `production_runtime.py` has 0 production importers |
| "canonical" renderer authority | `tests/test_p6_0_architecture.py:583` | `hevi/renderers/` has 0 production importers; `providers/remotion/` is the real path |
| "canonical timeline authority" | `tests/test_p6_0_architecture.py:601` | guard covers 4 modules and bans 2 of the types it names; 0 of 20 representations covered |
| "唯一允许开始生成的判定点" | `hevi/creative/autonomous/selection.py:206` | 6 admission seams; `authorities.py:370` runs tasks with no admission call |
| "canonical execution substrate" | `hevi/creative/autonomous/execution.py:1` | sole importer is one test file |
| "single authority for cinematic recipes" | `hevi/production/p5_3/library.py:1-8` | LIB, no entrypoint, 0 recipes qualified |

## Every bypass, enumerated

| # | Bypass | Evidence |
|---|---|---|
| B1 | Provider policy gate skipped for non-PgPool pools | `hevi/tasks/task_service.py:194` |
| B2 | `/authorities/endpoints/{name}/run` runs with no admission call | `hevi/api/routers/authorities.py:370-398` |
| B3 | Direct provider calls from creative code | `hevi/creative/layer4/v2v_workflow.py:154-162` via `production/adapters.py:154,363` |
| B4 | MCP rewrites provider id before task creation | `hevi/mcp/tools/video_tools.py:46-51` |
| B5 | `admit_single` never called from its router | `hevi/api/routers/authorities.py:807` |
| B6 | LongCat "admission" derived from its own report | `hevi/generation/longcat_probe.py:160` |
| B7 | `FinalReviewResult` accepts verdicts from its own request body | `hevi/verdict/final_review.py:97-122`, `api/routers/embrace_runtime.py:395` |
| B8 | Path-based verdicts pass on bytes that changed after the check | `verdict/delivery_gate.py`, `production/delivery_gate.py` |
| B9 | `filter([])` searches the whole library | `hevi/production/p5_3/library.py:158-179` |
| B10 | Duration-fit failure silently returns a non-fitting recipe | `hevi/cinematic/shot_intelligence/selector.py:45` |
| B11 | `qc_layout` / `qc_motion` permanently blocked | `hevi/studio/ops.py:503-517` |
| B12 | Caption check fails open when the SRT is unreadable | `hevi/video/quality_check.py:272-276` |
| B13 | `evidence_present` tautology | `hevi/renderers/html_gsap.py:434` |
| B14 | `REAL_VIDEO_ACCEPTED` hand-written into JSON | `RUN_SUMMARY.json`, `STATUS.md`; 0 code emitters |
| B15 | `EvaluationEvidence.artifact_id` written as `""` | `hevi/tasks/task_service.py:312` |

---

## Gate verdict

**AUTHORITIES_UNIQUELY_IDENTIFIED = BLOCKED**

Twelve of thirteen concepts have exactly one designated canonical candidate with
every competing writer classified and every bypass listed above.

**Admission (§6) has no canonical candidate.** Selecting seam 1 would ignore seam
3's stronger claim and its only real implementation; selecting seam 3 would make a
TEST-ONLY module (`hevi/missions/`) part of the authority chain. Both routes hit
spec §22's stop condition "current authority is only a dead/unwired module".

**Qualification (§5) has no canonical candidate either** — the subsystem is a
harness with one production consumer and a zero-import runner layer. This was not
flagged as a blocker because building the qualification authority is P0-4's
deliverable; Admission is different, because P0-4 cannot converge seven seams
without first deciding which seam is canonical.

Also outstanding for P0-2: `RenderPlan` (§8) and `Acceptance` (§11) have canonical
designations that are TEST-ONLY, which the gate permits (a unique designation was
made and every competitor was classified) but which must be recorded as
designation-only, not as working authority.
