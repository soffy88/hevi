# Canonical Contract Inventory — P0-2

**Date**: 2026-10-06 · **Baseline**: `d9ed31fd` (P0-1) · **Gate**: `CONTRACTS_CANONICAL`

Eleven canonical contracts plus three supporting objects. Every claim carries
`file:line`; VERIFIED means directly read or grepped, INFERRED means a conclusion
from verified facts.

## Gate status: `CONTRACTS_CANONICAL = PARTIAL`

Fourteen of fourteen concepts have exactly one designated owner and a recorded
migration target. Two of the three "must be created new" contracts are **defined
but not implemented** (`TimelineIR`, `RenderReceipt`, `VideoAcceptance`,
`EvidencePack`, `FailureClass`, `HumanDecision` — six in total), because P0-2's
scope is inventory and type-semantics selection, not consolidation. The gate as
specified asks for field semantics and time units to be *fixed*; that is done here
and encoded in `tests/architecture/test_contract_convergence.py`.

**Not advanced to P0-3.** Six canonical types are unwritten, and `VideoAcceptance`
cannot be written before P0-5 fixes the renderer authority it must reference.

---

## Summary table

| # | Contract | Canonical owner | Action | Reach today | Gate |
|---|---|---|---|---|---|
| 1 | `CreativeBrief` | `creative/direction_content/models.py:47` | ADOPT + fix | TEST-ONLY | ok |
| 2 | `StoryBible` | `narrative/models.py:310` | ADOPT + wire | LIB | ok |
| 3 | `AssetCandidate` | `production/shot_readiness.py:66` | ADOPT + freeze | **PROD** | ok |
| 4 | `ShotRecipe` | `production/p5_3/schema.py:295` | ADOPT, S1/S3 project | LIB | partial |
| 5 | `ShotSpec` | `creative/director_contract.py:142` | ADOPT + ms | LIB | partial |
| 6 | `GenerationRequest` | `generation/models.py:114` | **ADOPT AS-IS** | LIB | ok |
| 7 | `GenerationReceipt` | `generation/backend.py:96` | ADOPT + type gates | LIB | partial |
| 8 | `TimelineIR` | **none — create new** | NEW | n/a | blocked |
| 9 | `RenderReceipt` | **none — create new** | NEW, unbound | n/a | blocked |
| 10 | `EvidencePack` | **none — create new** | NEW | n/a | blocked |
| 11 | `VideoAcceptance` | **none — create new** | NEW | n/a | blocked |
| S1 | `RevisionLink` | `production_graph/production_revisions` | EXTEND | **PROD** | partial |
| S2 | `FailureClass` | **none — create new** | NEW | n/a | blocked |
| S3 | `HumanDecision` | **none — create new** | NEW | n/a | blocked |

ADOPT = existing implementation becomes canonical. NEW = must be created.
EXTEND = existing storage gains columns. PROJECT = demoted to adapter.

---

# 1. `CreativeBrief`

**Current implementation** — `hevi/creative/direction_content/models.py:47`,
`@dataclass(frozen=True)`, no base. Fields (15): `subject`, `objective`,
`audience`, `duration_target: str=""`, `duration_target_ms: int=0`,
`desired_effect`, `emotional_target`, `platform_constraints: tuple[str,...]`,
`brand_constraints`, `factual_constraints`, `hard_requirements:
tuple[HardRequirement,...]`, `creative_preferences`, `forbidden_elements`,
`source_type: str="user"`, `source_reference: str=""`.
Sibling `HardRequirement:36`.

**Canonical: this one. No competitor exists** (VERIFIED `rg "class .*Brief"`).

**Production writers: 0. Readers: 0.** VERIFIED: the only external references are
`tests/p10/test_open_questions_resolution.py:7,146,151` and
`tests/p10/test_p10b_content.py:12,30`. **Reach: TEST-ONLY.**

**Time semantics — defective.** `duration_target_ms: int` is compliant but
`duration_target: str` is a second, unit-less duration channel. Nothing reads
either; `validate():65` never inspects duration.

**Provenance — weak.** `source_type`/`source_reference` only. No `revision_id`, no
`id`, no `created_at`. The module has `content_hash():15` but it is a function, not
a field.

**Validation — opt-in, fail-closed when called.** `validate():65` raises
`ContentValidationError` for empty subject/objective/audience
(`BRIEF_INCOMPLETE`), bad `check_class` (`BRIEF_BAD_CLASS`), unasserted non-H
requirement (`HARDREQ_UNASSERTED`). No `__post_init__`: bare construction accepts
junk.

**Duplicates** — none.

**Canonical type semantics (fixed here):**

| Field | Type | Rule |
|---|---|---|
| `id` | `str` | **required**, non-empty. Absent today |
| `revision_id` | `str` | **required**, non-empty. Absent today |
| `objective` | `str` | non-empty |
| `subject` | `str` | non-empty |
| `audience` | `str \| None` | may be None (spec allows) |
| `format` | `str` | **required**. Absent today — there is no `format` field at all |
| `aspect_ratio` | `str` | **required**. Absent today |
| `language` | `str` | **required**. Absent today |
| `duration_target_ms` | `int \| None` | **the only duration channel**; `duration_target: str` deleted |
| `constraints` | `tuple[Constraint,...]` | renamed from the 4 separate tuples |
| `source_refs` | `tuple[str,...]` | replaces `source_type`/`source_reference` |

**Migration target.** Add `id`/`revision_id`/`format`/`aspect_ratio`/`language`;
delete `duration_target: str`; fold `platform_constraints`/`brand_constraints`/
`factual_constraints`/`hard_requirements` into one `constraints` tuple; move
`validate()` into `__post_init__`. Earn canonical status with a production writer —
none exists.

---

# 2. `StoryBible`

**Canonical: `hevi/narrative/models.py:310`** — frozen dataclass, 22 fields
including `schema_version`, `premise: StoryPremise|None`, `theme: Theme|None`,
`dramatic_question`, `characters`, `relationships`, `world_rules`, `locations`,
`timeline: tuple[TimelineEvent,...]`, `established_facts`,
`continuity_constraints`, `episodes`, `sequences`, `style_profile`,
`narrative_voice`, `unresolved_threads`, `resolved_threads`, `source_refs`,
`revision: str="0"`, `updated_at: Timestamp`.

**Duplicate disqualified** — `hevi/layer4_legacy/obase_support/creative.py:295`,
pydantic `StoryBible(CreativeObject)`: flat `str` for premise/theme where canonical
needs typed objects; UUID-only references with no embedded content; nested in a
`layer4_legacy` package.

**Writers:** `hevi/narrative/bible.py:20` `create_bible()`, `:24` `restore_bible()`,
`:72` `update_bible()` — called only from `narrative/persistence.py:11,31`, and
persistence has **0 importers**. **Readers: 12 production modules**, all inside
`hevi/narrative/` plus `narrative/adapters/shot_intelligence.py`.
**Reach: LIB** — no entrypoint constructs one.

**Time semantics — clean.** VERIFIED `rg "_sec|_s\b|seconds" hevi/narrative/models.py`
→ 0 hits. Time is stringly (`TimelineEvent.time: str` at `models.py:114,231`), which
is narrative ordering, not media time. **This is the only creative contract with no
float-second leak.**

**Provenance — rich but unwired.** `NarrativeProvenance` exists at `models.py:288`
(`project_revision`, `story_bible_revision`, `episode_revision`, `scene_revision`,
`llm_provider`, `llm_model`, `source_refs`, `evidence_refs`,
`continuity_report_id`, `review_report_id`, `shot_plan_id`) and is **not a
StoryBible field**. VERIFIED gap.

**Validation — fail-closed but bypassable.** `validate_bible():32-70` enforces
project_id, no duplicate ids across 10 collections, no dangling relationship refs,
`SOURCE_FACT`/`DERIVED_CLAIL` require `evidence_refs`, sequence id required. But
`create_bible()` **skips validation entirely** — fail-open.

**Canonical type semantics:** keep all 22 fields; **add `provenance:
NarrativeProvenance` as a field**; make `create_bible()` call `validate_bible()`.

---

# 3. `AssetCandidate`

**Canonical: `hevi/production/shot_readiness.py:66`** — the only definition.
**`@dataclass` — MUTABLE.** Fields: `candidate_id`, `requirement_id`, `asset_ref`,
`state: AssetCandidateState= CANDIDATE`, `confidence: float=0.0`, `verified: bool`,
`reason: str`, `selected_by: str`, `lineage: list[str]`, `scored_by: str`.

**Not duplicates.** VERIFIED: `hevi/production/p7/asset_contract.py` defines
`AssetReference:98` (a *pointer* with `asset_id, media_type, semantic_role, origin,
status, uri, provider_id, license`) and `asset_intelligence.py:59` defines
`AssetResolution:59` (an envelope). Different concepts; no competing candidate type.

**Writers: 2 production.** `hevi/creative/autonomous/acquire.py:95` (canonical
producer, deliberately leaves `confidence=0.0`/`scored_by=""` so S3 owns scoring) and
`hevi/production/p0_pipeline.py:604` (hardcodes `confidence=0.0, verified=True`).
**Readers: 5+ production**, incl. `creative/autonomous/selection.py:145,204,205`
and `api/routers/director_pipeline.py`. **Reach: PROD** — the only contract here with
real production wiring.

**Time semantics — no time field.** Sibling leak in the same module:
`ShotPreparation.audio_range: tuple[float,float]` at `shot_readiness.py:101` is
float seconds.

**Provenance — strongest in the repo.** `reason`, `selected_by`, `lineage`,
`scored_by`, `verified`, `confidence`; the `:68-77` docstring documents the
two-scorer discipline (empty `scored_by` = not auto-selectable).

**Validation — accepts junk.** No `__post_init__`. Mutability is deliberate
(`tests/p10/test_s3_scoring_reconciliation.py:121` mutates `.state`), which means a
`SELECTED` candidate can be flipped to `REJECTED` with no audit trail.

**Canonical type semantics:** keep fields; `lineage` becomes `tuple[str,...]` (or
append-only with a recorded transition); add a `state` transition guard. Missing
versus spec §4.3: `duration_ms`, `width`, `height`, `fps`, `transcript_ref`,
`regions`, `license` — the candidate cannot express media facts, only a ref.

**Migration target.** Freeze, or add a transition validator; single construction
factory.

---

# 4. `ShotRecipe` — 3 systems

| | S1 `ShotRecipe` | S2 `CinematicRecipe` | S3 `ShotRecipeCard` |
|---|---|---|---|
| Location | `cinematic/shot_intelligence/models.py:50` | `production/p5_3/schema.py:295` | `motion/recipe_card.py:32` |
| Count | **6** | **80** | **152** |
| Scorer | none (2-tuple tiebreak `selector.py:47`) | **yes** `.30/.20/.15/.10/.10/.10/.05` `library.py:219-247` | none |
| Constraint filter | partial | **yes** hard-exclude `:181-212,:218` | none |
| Capability filter | **no** — `renderer_capabilities` never read as a filter | **yes** `:127,:207` | none |
| Frozen | yes | **no — mutable** | yes |
| `__post_init__` | **no** | **yes, strongest in repo** `:408`, `_validate_primitives():421` (14 vocabularies) | name-only `:46` |
| Time | `duration_range_s: tuple[float,float]` **float s** | `duration_range: tuple[float,float]` **float s** (name avoids the `_s` scan) | `suggested_duration_s: float` + `params` mixing `hold_s`/`rest_s` with `blur_frames` |
| Provenance | `dict[str,str]` untyped | **typed** `SourceProvenance:183` + `LicenseProvenance:195` | `demo_ref: str` only |
| Flag | `SHOT_INTELLIGENCE_ENABLED` **default off** | none | none |
| Reach | **TEST-ONLY**, 0 selector calls in prod | LIB, 6 readers | **PROD** HTTP `GET /api/studio/motion/shot-cards` |
| Tests | 1 file | **10 files** | 0 direct |
| Fail-open | `selector.py:45` `candidates = fitting or candidates` | `library.py:158-179` `filter([])` searches whole library | `validate_card:50` static lint, never enforced |

**Canonical: S2 `CinematicRecipe`.** It is the only system with a scorer, hard
constraint + capability exclusion, typed provenance, immutable versioning
(`qualified_id:307`), 14 validated vocabularies, and 10 test files.

**Disqualified:** S1 — behind a default-off env flag, 6 recipes, no scorer, no
vocabularies, fail-open selector. S3 — wrong abstraction level (a *style/motion
reference card*: energy, pitfalls, demo TSX path), no provenance, `params` mixes
float seconds with frame counts, 0 direct tests.

**Blocker:** all 80 recipes are `qualification_state=EXPERIMENTAL`, so
`library.list_qualified()` returns **0**. The canonical system authorizes nothing yet.

**Canonical type semantics:** `duration_range` → `duration_range_ms:
tuple[int,int]`; frozen dataclass; `source_provenance`/`license_provenance` become
the required provenance fields; `constraints: dict` → typed predicates (P0-6).

---

# 5. `ShotSpec` — 2 definitions, no overlap

| | `creative/director_contract.py:142` | `erduo/schemas.py:92` |
|---|---|---|
| Base | frozen dataclass | pydantic v2, **mutable** |
| Fields | `shot_id`, **`duration_sec: float`**, `narrative_function`, `beats: tuple[BeatSpec,...]`, `composition`, `camera_intent`, `audio_intent`, `semantic_refs`, `continuity`, `renderer_constraints` | `shot_id`, `chapter_id`, `sequence`, **`start_ms: int`**, **`end_ms: int`**, `visual_concept`, `composition`, `animation_beats: list[dict]`, `material_routes`, `status`, `canary_passed`, `rendered_path` |
| Time | **3 float-second fields** (`duration_sec`, `BeatSpec.start_sec`, `end_sec`) | **integer ms — the only compliant one** |
| Provenance | **none** | **none** |
| Validation | **strictest of all contracts**: `.validate(known_claims):153` raises `DIRECTOR_SHOT_ID`, `DIRECTOR_SHOT_DURATION`, `DIRECTOR_BEAT_COUNT` (`<3`), `DIRECTOR_BEAT_COVERAGE` (with `1e-6` float tolerance), `DIRECTOR_SHOT_DANGLING_CLAIM`, + recursive continuity checks | **fail-open**: every field defaults; `ShotSpec()` validates clean |
| Writers | `creative/director_adapter.py:81` (only real one) | **0 production** — only `layer4_legacy/erduo/oprim_impl/__init__.py:110` |
| Reach | LIB | **DEAD** |
| Tests | 2 files | **0** |

VERIFIED: zero field overlap except `shot_id` and `composition`. `rg "erduo"
hevi/creative/director_contract.py` → 0 hits and vice versa. **Do not merge.**

**Canonical: `director_contract.py:142`** on three grounds — it holds the only real
validation contract, the only production writer, and the beat-coverage semantic model
that a shot actually needs. The erduo variant holds the correct *time* convention
but is dead, uses a chapter/sequence/status model that cannot express a canonical
shot, and validates nothing; adopting its convention must not import its
fail-open construction.

**Canonical type semantics:** `duration_sec: float` → `duration_ms: int`;
`BeatSpec.start_sec/end_sec` → `start_ms/end_ms: int`, replacing the `1e-6`
tolerances with exact integer arithmetic; **add `provenance`**; **add `recipe_id`**.
`start_anchor` is not adopted — the existing `start_ms` is sufficient.

---

# 6. `GenerationRequest` — ADOPT AS-IS

**Canonical: `hevi/generation/models.py:114` `VideoGenerationRequest`, unchanged.**
Per instruction, not rewritten.

VERIFIED strength: `@dataclass(frozen=True)`; `required_capabilities():128` maps
`mode` → `continuation|i2v|t2v` (capability, **not** provider); `request_hash():135`
is sha256 over `json.dumps(sort_keys=True, ensure_ascii=False, separators,
default=str)` — deterministic across processes; `OutputSpec.duration_ms:103` and
`fps:102` are **integer ms**; `ConditioningWindow:150-176` carries frame indices +
`timestamp_*_ms` and has a fail-closed `validate():163`.

`FORBIDDEN_CANONICAL_FIELDS` at `models.py:46-49` (8 names) is locked by
`tests/p10/test_generation_contract.py:83-94`, which asserts no banned name among
top-level fields `:85-87` nor in the 5 nested dataclasses' fields `:89-94`.

**Reach: LIB.** VERIFIED: `rg "VideoGenerationRequest\(" -g '!tests/*'` → **0 hits**.
The only constructor is the test double at `test_generation_contract.py:69`. Readers
are `generation/backend.py:45,48,57,107,131` and `longcat_adapter.py:52` (which
unconditionally raises `ProviderNotInstalled` at `:54`). Zero routers, zero MCP.

**Name-collision duplicates (different domains, no conflict):**
`services/voicebox/backend/models.py:79`, `api/routers/tasks.py:39`,
`api/routers/mpt.py:28,74`, `services/mpt/app/models/schema.py:217`,
`layer4_legacy/longvideo/oprim_impl/contracts.py:10`. None reference
`VideoGenerationRequest`.

**Weaknesses recorded, not fixed now:** no `__post_init__` (so `fps=0` is
constructible, and `stage` can contradict `mode`); no `created_at`/`actor`/
`attempt_id`; the neutrality lock is a fixed literal list, so a new provider flag
under a new name passes; `default=str` will `repr()` an exotic value.

---

# 7. `GenerationReceipt`

**Canonical: `hevi/generation/backend.py:96` `GenerationResult`.** Frozen.
Fields: `request: VideoGenerationRequest`, `clip: GeneratedClip`, `state:
ContinuationState|None`, **`gates: dict[str,str]`**, `fallback: FallbackRecord|None`.
`GeneratedClip` at `models.py:207-232` carries `artifact_hash:211`, `generation_id`,
`source_shot_id`, `continuation_state_id`, `generation_stage`, `backend`,
`backend_version`, `width/height/fps/frame_count/duration_ms`.

**Writer: 1** — `backend.py:128` inside `run_generation:107`. **Reach: LIB**, never
persisted.

**Provenance — partial.** `provenance():103-104` returns `clip.provenance()` +
`request_hash`, but that is a **method return, not a stored field**, so nothing
serialised carries the fingerprint.

**`artifact_hash` is unverified.** VERIFIED: free string, no `_SHA256_HEX` regex and
no `verify_against` (contrast `AcquisitionEvidence:95,113`); the test passes the
literal `"h"` (`test_generation_contract.py:55`).

**`gates` is untyped.** `dict[str,str]`, keys fixed by `VALIDATION_GATES
backend.py:33-34`, values bare literals from `_gate_results:131-150` including
`"NOT_EVALUABLE"` at `:145`. No enum, no per-gate evidence, no timestamp, and the
dict is mutable inside a frozen dataclass.

**`failure_class` does not exist.** VERIFIED `rg "failure_class" hevi/generation/`
→ 0 hits. Failure is exceptions only (`CapabilityUnsupported:53`,
`MediaIntegrityError:65`, `SilentFallbackDetected:82`,
`ValidationArtifactMissing:149`, `ContinuationStateMissing:116`).

**Name-collision duplicate:** `hevi/narrative/generation.py:17` `GenerationResult`
— a different concept, same name.

**Canonical type semantics:** rename to `GenerationReceipt`; add `receipt_id`,
`attempt_id`, `created_at`, `cost`; **store `request_hash` as a field**; make
`artifact_hash` regex-validated *and* byte-verifiable; replace `gates: dict[str,str]`
with `tuple[GateVerdict,...]` carrying a status enum + `evidence_ref`; add
`failure_class: FailureClass`.

---

# 8. `TimelineIR` — must be created new

No existing representation satisfies the canonical contract. Per instruction this is
permitted, provided the 20 existing representations become adapters/projections and
do not become a 21st authority.

**Union of semantics the 20 types already support** — none of this would be new
(VERIFIED): canvas (`compiler.py:25-27`, `studio/timeline.py:66`,
`editable_delivery.py:93`); typed tracks (`TrackKind VIDEO/AUDIO/TEXT:34-38`);
clips with source in/out (`EditableClip:66-78`); captions as text-track clips
(`EditableClip.text:75`); audio gain (`EditableClip.gain:76`); typed transitions
(`TransitionKind CUT/FADE/DISSOLVE/WIPE:40-56`); revision metadata
(`editable_delivery.py:84-97`).

**Closest existing: `EditableTimeline` (`creative/layer4/editable_delivery.py:81`).**
The only type with typed tracks + typed transitions + audio gain + per-clip text +
full revision metadata, and `extra="forbid", frozen=True` with a real fail-closed
`_clips_cover_effective_duration():99-107` (video-ms coverage, clip-id uniqueness).
Gaps: no width/height/fps, no canvas, no `content_hash()`, bound to
`presentation_snapshot_id`.

**Canonical type semantics — zero new semantics:**

| Field | Type | Source of truth |
|---|---|---|
| `canvas` | `width:int, height:int, fps:int, aspect_ratio:str` | `compiler.py:25-27` / `base.py:77-79` |
| `tracks` | `tuple[Track,...]` where `Track.kind ∈ {VIDEO,AUDIO,TEXT}` | `editable_delivery.py:34-38` |
| `clips` | `tuple[Clip,...]` with `clip_id, track, source_path, source_in_ms:int, duration_ms:int, text, gain, transition_in, transition_out, order:int` | `EditableClip:66-78` verbatim |
| `metadata` | `project_id, revision_id, created_at` | `editable_delivery.py:84-97` |
| `audio_lock_id` + `audio_sha256` | `str` | **`TimelineLock:77-79` verbatim** — the only integrity binding in any of the 20 |
| `content_hash()` | `sha256` over canonical serialisation | **new, and the one thing nothing has** |

**Invariants (all currently violated somewhere):** integer ms enforced and float
seconds **rejected not coerced**; monotonic ordering (fixes `p1_types.py:119-121`
append-without-sort); non-negative duration (fixes `p1_types.py:98` coercing
negative → `0.0`); clip-id uniqueness; video coverage of the effective duration;
track consistency; reference existence.

**Without `content_hash()` no `RenderReceipt` can cite a `timeline_hash`** — this is
the dependency that makes TimelineIR the first contract to implement in P0-3.

**Immediate deletable:** `hevi/narrative/timeline.py:8` + `models.py:114` — zero
importers, VERIFIED.

---

# 9. `RenderReceipt` — must be created new, unbound from `hevi/renderers/`

Per instruction, the receipt contract is defined here but **must not bind to
`hevi/renderers/`**, which P0-1 established is an orphan (§8 of the authority map):
zero production importers, `content_hash` never assigned, `frame_deterministic` a
literal. `RenderResult` is marked **orphan/legacy candidate**; the real renderer
authority is P0-5's decision.

**Existing types and why neither qualifies:**
`RenderResult` (`renderers/base.py:88`) — 14 fields but `duration_s: float`,
`latency_s: float`, no `renderer_version`, `content_hash` never assigned, not
frozen, not persisted. `ProductionReceipt` (`execution/models.py:134`) — frozen and
**the strongest integrity check in the repo** (`:150-182` rejects empty ids,
non-`_SHA256_HEX` `:162`, missing/failed validation `:167,172`, and
observed-checksum mismatch `:179`), but carries **no render fields at all**.

**§6.2 field coverage today:**

| Field | Carried anywhere? |
|---|---|
| `attempt_id` | partial — `EvaluationEvidence.attempt_id` (`quality/evidence.py:24`); `RenderResult.attempts` is an int count |
| `render_plan_hash` | **NO** — `RenderPlan.to_dict:83` has no hash method |
| `timeline_hash` | **NO** — no timeline type has a hash |
| `renderer_id` | yes — `RenderResult.renderer:92` (str) |
| `renderer_version` | **NO** |
| `artifact_id` | partial — `ProductionReceipt.artifact_id` |
| `artifact_hash` | partial — `ProductionReceipt.artifact_checksum` (enforced); `RenderResult.content_hash` never assigned |
| `media_probe` | partial — `VideoProbe` (`production/delivery_gate.py:29-35`) exists but is **constructed and discarded**, never attached to a receipt |
| `status` | yes — `RenderOutcome` / `ReceiptStatus` |
| `evidence_ref` | **NO** — `RenderPlan.required_evidence:75` is a bare `list[str]` of names |

Six of ten fields exist nowhere. Two of the missing ones (`timeline_hash`,
`render_plan_hash`) depend on P0-3.

**Canonical type semantics:** frozen; `ProductionReceipt.__post_init__:150-182`
transplanted as the integrity core; `renderer_id`/`renderer_version` as plain
strings so P0-5 can bind whichever renderer wins; `media_probe: MediaProbe` as a
new type carrying a **real sha256** plus the `VideoProbe` fields; `evidence_ref`
pointing at an `EvidencePack.evidence_id`. `RenderResult` is retained as a
backend-local struct, not referenced by the receipt contract.

---

# 10. `EvidencePack` — must be created new

**Existing types, and the inversion that makes a pack necessary:**
`AcquisitionEvidence` (`evidence/acquisition.py:73`, frozen) has
`evidence_id, provider_id, source_id, checksum, timestamp, acquisition_method`;
`__post_init__:88-103` enforces non-empty ids + `_SHA256_HEX` + method isinstance;
`verify_against(payload):113` re-hashes bytes. It is **never written to disk**.
`EvaluationEvidence` (`quality/evidence.py:15`, pydantic, **not frozen, no
`__post_init__`, no hash**) has `id, attempt_id, artifact_id` (free string),
`constraint_id, evaluator_id, evaluator_version, metric, score, threshold,
passed: bool|None` (`None` = UNKNOWN, per the comment at `:32`), `evidence_artifact_ids,
details`. It **is** persisted (`quality/repository.py:94-105`).

VERIFIED: `task_service.py:309` writes `artifact_id=""`. So the byte-bound lineage
is unpersisted and the persisted lineage is unbound — the two are never joined.

**Only aggregation type today:** `QualityEvaluation` (`quality/evaluation.py:35-49`)
— `passed: bool, score, residual_severity, residual_count, evidence:
list[EvaluationEvidence], violations: list[ConstraintEvaluation]`. It is a **verdict,
not a pack**: no `artifact_hash`, no `revision_id`, no probes, no screenshots, no
decisions, no `created_at`. VERIFIED `EvidencePack` → **0 hits repo-wide**.

**§6.2 field coverage today:** `evidence_id` yes; `artifact_id` partial (unverified);
`artifact_hash` **no**; `revision_id` **no in any evidence type**; `evaluations[]`
partial (`QualityEvaluation.evidence`); `probes[]` **no** (`VideoProbe` discarded);
`screenshots/contact_sheets` **no typed** (only `contact_sheet_path: Path|None` at
`verdict/delivery_gate.py:57`); `human_decisions[]` **no typed** (nearest
`VerdictInput(source, passed: bool, detail)` at `creative/autonomous/verdict.py:30-34`
— a bool with no actor, time or artifact binding); `created_at` partial.

**Canonical type semantics:** frozen; `__post_init__` modelled on
`AcquisitionEvidence:88-103` requiring `_SHA256_HEX` on `artifact_hash` and a
non-empty `revision_id`; `evaluations: tuple[EvaluationEvidence,...]` reusing
`QualityEvaluation.evidence:48`; `probes: tuple[MediaProbe,...]` where `MediaProbe`
wraps `VideoProbe` **plus a real digest** (closes the "ffprobe on a path" hole);
`human_decisions: tuple[HumanDecision,...]`; `created_at`. Removal condition already
recorded at `authority_map.md:399-401`: the receipt's `artifact_sha256` must be
**computed from** `EvidencePack.artifact_hash`.

---

# 11. `VideoAcceptance` — must be created new

**Verdict type × acceptance source × currently allowed (VERIFIED):**

| Verdict type | (a) request body | (b) filesystem probe | (c) script status string | (d) mere existence |
|---|---|---|---|---|
| `FinalReviewResult` `final_review.py:96` | **YES — worst** `:122-126`, `inputs_present`/`verdicts` are caller bools via `embrace_runtime.py:394-399` | no | no | no (never opens a file; `passed:106-110` is arithmetic over caller bools) |
| `DeliveryGateResult` `verdict/delivery_gate.py:52` | no | **YES** ffprobe/ffmpeg `:68-92,:94` | no | **partial** — path+duration+stream, **no sha256 field at all** |
| `DeliveryVerdict` `production/delivery_gate.py:39` | **YES** `evaluate_director_delivery(shots: list[dict])` reads caller JSON `:173-178` | **YES** `probe_video:50-52` | no | **YES** empty file → `VideoProbe(…,0,False,False,0)` `:53-54`, gated only on ok/size/duration |
| `ReceiptStatus`+`_receipt` `artifact_verification.py:71,457` | no | **YES** `sha256_file:82` → `artifact_sha256:473` | no | no — real bytes, fail-closed `_status_for:448-454` |
| `DirectionVerdict` `direction_verify/models.py:65` | no | yes | no | no — `validate():76-78` raises `VERDICT_UNBOUND`. **DEAD** |
| `ProductionVerdict` `creative/autonomous/verdict.py:38` | **partial** caller `(source, passed)` bools `:57-59` | no | no | no — fail-closed (empty→BLOCKED `:62`, unvalidated→BLOCKED `:64`). **stores no hash** |

**The three HTTP-reachable verdicts carry zero hash binding.** And `REAL_VIDEO_ACCEPTED`
has **0 code emitters** (VERIFIED) — the token exists only in two `RUN_SUMMARY.json`
files and `STATUS.md`, while `produce_first_real_video.py:806` writes
`f"MACHINE_{status.value}"`.

**Canonical type semantics — forbid (a)–(d) by construction:**

| Rule | Mechanism |
|---|---|
| no `verdicts: dict[str,bool]` field | absence of field — a verdict cannot be *passed in* |
| no `status: str` | absence of field — no script-written status can be forwarded |
| `artifact_sha256: str` must match `_SHA256_HEX` | copy `execution/models.py:162`; a caller cannot synthesize it from a path |
| `verifier_id` + `verifier_version` required | names who/what decided |
| `evidence_ref: str` must resolve to an `EvidencePack.evidence_id` | no pack, no verdict |
| `levels: tuple[LevelOutcome,...]` with **zero `UNKNOWN`** | reuse `_SETTLED` `artifact_verification.py:68` and `_status_for:448-454` |
| `UNVERIFIED` as a first-class non-terminal verdict | makes "could not check" unrepresentable as `passed` |
| artifact existence alone insufficient | `artifact_sha256` is mandatory and independent of any probe |

Recorded for **P0-8**, not fixed in P0-2: `FinalReviewResult` accepting verdicts from
a request body; the three path-only verdicts; the hand-written
`REAL_VIDEO_ACCEPTED`.

---

# S1. `RevisionLink`

**Canonical: `production_revisions` (`hevi/production_graph/`), EXTENDED — not a new
table.** Alembic `0a1b2c3d4e5f_create_production_graph.py:44-65`: `id UUID PK`;
`production_id UUID NOT NULL FK→productions.id ON DELETE CASCADE` `:48-51`;
**`parent_id UUID NULL` — no ForeignKey** `:52`; `revision_no Integer NOT NULL`
`:53`; `status String(32) NOT NULL default 'draft'` `:54`; `reason Text` `:55`;
`created_by String(255)` `:56`; `snapshot_json JSONB NOT NULL` `:57`;
`created_at timestamptz` `:58-62`; `UniqueConstraint(production_id, revision_no)`
`:63`.

It is the only mechanism that is durable, immutable (ADR-005
`docs/adr/ADR-005-immutable-revision.md`, CI-enforced
`scripts/ci/check_architecture_invariants.py:32`), and transactional with a
`domain_events` row (`repository.py:296`).

**VERIFIED: `supersedes_revision_id` → 0 production files. `invalidated_artifact_ids`
→ 0 production files.** `changed_fields` → only
`hevi/creative/direction_verify/impact.py:55,68,72-98`, an in-memory `set[str]`.

**Nothing invalidates artifacts.** VERIFIED `rg "invalidate|revoke|purge|superseded"`
over `production_graph/`, `artifact_store/`, `direction_state/` → **0 hits**.
ADR-005:10-11 states the intent; nothing implements the step. Only time-based
expiry exists (`artifacts.expires_at`, `e1f2a3b4c5d6_add_artifact_expires_at.py:15-17`).
One real invalidation, approval staleness
(`hevi/ops/p5_approval.py:162-175` cancels approvals where `approval.revision <
current_revision`) — but it records no artifact ids.

**Other mechanisms (all weaker):** `EditableTimeline.revision_id/edit_revision`
(`editable_delivery.py:87,96`) — vestigial counter, no persistence;
`StoryBible.revision` (`narrative/models.py:330`, TEST-ONLY);
`NarrativeRevision`/`RevisionStore` (`narrative/models.py:268-275`,
`narrative/revision.py:16-29`) — has `base_revision`, `author`, `reason`,
`created_at`, raises `StaleRevisionError`, but **in-memory dict only**;
`direction_state` revisions (`repository.py:195-222`, `_rev_dir:59`) — richest shape
(`revision, actor, reason, command_id, created_at, from_state/action/to_state`,
FS `rev_N/`), TEST-ONLY.

**Canonical type semantics:** add `supersedes_revision_id UUID REFERENCES
production_revisions(id)` replacing bare `parent_id`; add
`invalidated_artifact_ids UUID[]` plus a real invalidation step in
`ensure_execution_context` (`repository.py:120+`); add `changed_fields TEXT[]` from
the snapshot diff (reusing `impact.py:55-99` logic, which returns `tuple[str,...]`
today and is never persisted). `direction_state` stays a consumer and is the design
reference for actor/reason shape.

---

# S2. `FailureClass` — must be created new

`FailureCode` (`quality/taxonomy.py:8-30`, 18 members) **cannot** be promoted: all 18
are creative *defect* semantics (`IDENTITY_MISMATCH`, `WARDROBE_MISMATCH`,
`SCENE_CONTINUITY`, `EYELINE_VIOLATION`, `LIPSYNC_DRIFT`, `STYLE_DRIFT`, …) and
**none of the 15 required tokens appears**. It is already exported through
`quality/__init__.py:14`, so promoting it would either rename 18 members or coerce
infrastructure failures into creative language.

**VERIFIED token census — 4 of 15 first-class, 6 absent, 5 substring-only:**

| Token | Status |
|---|---|
| `GENERATION_FAILED` | canonical `generation/errors.py:7` |
| `PROVIDER_UNAVAILABLE` | canonical `ops/p5_1_types.py:454` (+7 sites) |
| `EVIDENCE_MISSING` | canonical `acquisition/models.py:66` |
| `HUMAN_REVIEW_REQUIRED` | canonical `ops/p5_1_types.py:455` |
| `ASSET_NOT_FOUND` | substring only — `CASE_SOURCE_ASSET_NOT_FOUND_OR_NOT_OWNED` (`video_intelligence/runtime_adapters.py:71`) |
| `TIMELINE_INVALID` | substring only — `TIMELINE_INVALID_JSON:` (`ops/p5_1_editable.py:648`) |
| `RENDER_FAILED` | substring only (4 sites, incl. `production/layout_plan.py:485`) |
| `MEDIA_PROBE_FAILED` | `LevelOutcome` strings `artifact_verification.py:201,229,233,237`, never an enum member |
| `QUALITY_GATE_FAILED` | ad-hoc strings `studio/fulfill.py:386,440`; `distribution/safety.py:25` |
| `INVALID_INPUT`, `CAPABILITY_UNSATISFIED`, `ASSET_LOW_CONFIDENCE`, `PROVIDER_RATE_LIMIT`, `TRANSCRIPT_FAILED`, `PROVENANCE_MISSING` | **absent entirely** |

Near-misses: `CAPABILITY_UNSUPPORTED` (`generation/errors.py:16`),
`CAPABILITY_BLOCKED` (`plan_projection.py:326`), `RATE_LIMITED`
(`providers/reliability.py:54`), `SOURCE_EVIDENCE_MISSING` (`narrative/errors.py:15`).

**The five fail-open mappers, with the unknown-input branch quoted:**

1. `quality/taxonomy.py:78-87` `normalize_failure` — `:85-87`:
   ```python
   except ValueError:
       for alias, code in _ALIASES.items():
           if alias in raw:
               return code
   return FailureCode.DELIVERY_INTEGRITY
   ```
   Also `severity_for:57-62` returns a default `3.0` for unknown.
2. `creative/layer4/blender_workflow.py:248-287` — `:286-287`
   `return f"BLENDER_EXIT_{exit_code}", "RETRY_TARGET"`, then re-fed to
   `normalize_failure` at `repair_incident.py:123`, collapsing to DELIVERY_INTEGRITY.
3. `missions/p3_runtime.py:457-473` — `:473` `return "VISUAL_QA"`.
4. `creative/autonomous/repair.py:46-48` — `:48`
   `return FAILURE_TO_KIND.get(failure_code, RepairKind.RETRY_TARGET)`.
   **An unknown failure is treated as safely retryable — the safety bug.**
5. `creative/layer4/plan_projection.py:302-331` — `:330-331` `return "PROVIDER_ERROR"`.

Also funnelling through `normalize_failure`: `quality/repair_controller.py:149`,
`tasks/task_service.py:315`.

**Single shared enum?** VERIFIED **no.** `FailureCode` has 8 importers but its spread
is only quality + task service + layer4. `AcquisitionFailure`,
`ProviderErrorClass`, `ExecutionFailure`, `RootCauseCategory`, `GenerationError` are
each single-domain.

**Canonical type semantics:** new 15-member StrEnum **plus a 16th `UNKNOWN`** for the
fail-closed branch; keep `FailureCode` as the creative sub-taxonomy with
`FailureClass.defect_code: FailureCode | None` cross-reference so quality analytics
keep their 18 codes. Convert the five mappers: `normalize_failure` returns `None`/`
UNKNOWN` for unrecognized input; `blender_workflow:286` → `UNKNOWN`; `p3_runtime:473`
→ `UNKNOWN`; `repair.py:48` must stop defaulting unknown → `RETRY_TARGET`;
`plan_projection:330` → `PROVIDER_UNAVAILABLE`/`UNKNOWN` instead of bare
`PROVIDER_ERROR`.

---

# S3. `HumanDecision` — must be created new

**Every human-decision entry point today:**

| Entry point | file:line | Type | Persisted | artifact_hash | WHO | WHEN | WHY |
|---|---|---|---|---|---|---|---|
| `verify_v3(human_review=)` | `artifact_verification.py:345`, validated `:348-351` | `str \| None` | only into `evidence["human_review"]` dict `:368-369`; no table | **NO** | no | no | no |
| `verify_artifact` → `verify_v3` | `:397,429`; else-branch `:431-439` | `str \| None` | into receipt levels | **NO** | no | no | no |
| `VerdictInput` | `creative/autonomous/verdict.py:30-34` | `(source:str, passed:bool, detail:str)` | in-memory | **NO** | free-text `source` | no | `detail` |
| `HumanDecision` enum + `apply_human_decision` | `ops/p5_1_types.py:460-464` (KEEP_V0, KEEP_V1, REJECT_ALL, REQUEST_CHANGE); `ops/p5_1_session.py:516-545` | StrEnum | in-memory only (`session.human_decision` `:526`) | **NO** — picks by index (`candidates[0]`/`[-1]` `:521-522`) | no | no | synthesized string `:544` |
| `decide_promotion(human_override=)` | `ops/p5_1_pairwise.py:535,550-576` | `Any` | into `PromotionDecision` `p5_1_types.py:922,929` | **NO** | no | no | `f"HUMAN_OVERRIDE:{...}"` `:572` |
| `apply_approval_decision` | `ops/p5_approval.py:146-160` | `decided_by, reason` | **YES** `approvals.json` via `ApprovalStore:46-52` | **partial** — `ApprovalRequest.revision:int` `p5_types.py:147` + `artifact_refs:148`, **no content hash** | **YES** `:155` | **YES** `:154` | **YES** `:156` |
| `SessionStopReason.HUMAN_REVIEW_REQUIRED` | `ops/p5_1_session.py:193,358-360,544`; enum `p5_1_types.py:455` | StrEnum | in-memory | **NO** | no | no | `plan.reason` `:362` |
| `run_final_review` | `api/routers/embrace_runtime.py:393-400` | `inputs_present: dict[str,bool]`, `verdicts`, `conflicts` | returned to HTTP caller only | **NO** | no | no | no |
| CLI `--human-review` | `scripts/qualification/run_p11_layout.py:323,332,336,340,171` | free `str` | JSON `_human_review` `:310-314` | **NO** | no | no | `basis` string |
| `CREATIVE_REVIEW.json` | `artifacts/real_video/2026100*Z/verification/` | hand-written JSON | file | **NO** — prose `"reviewer": "human-equivalent agent review (...)"`, **not a human** | prose | prose `method` | prose |

VERIFIED: no `HUMAN_ACCEPTED` token; **no `CREATIVE_REVIEW` writer in `hevi/` or
`scripts/`** — both files are hand-authored; `produce_first_real_video.py:807`
writes the literal `"human_review": "PENDING"`.

**`verify_v3` behaviour when the machine aggregate has not settled**
(`artifact_verification.py:375-382`) — quoted:

> `# The machine aggregate has not settled. §20: human acceptance records a`
> `decision, it does not manufacture evidence. A reviewer approving an`
> `unvalidated artifact is not a creative pass, it is an unverified one.`
> `return LevelResult(Level.V3, LevelOutcome.UNKNOWN,`
> `"HUMAN_REVIEW_OVER_INSUFFICIENT_EVIDENCE", evidence)`

**This is the correct path** and must be preserved by the canonical type.

**Can a human decision override a machine FAIL? The two subsystems disagree.**
`verify_v3`: **no** — `:371` REJECT→FAIL and `:372-373` machine FAIL are checked
before `:383` ACCEPT, so ACCEPT can only reach an already-PASS aggregate.
`decide_promotion`: **YES** — `ops/p5_1_pairwise.py:550-576` returns immediately on
`human_override is not None` **before** the `new_blockers > 0` hard-gate check at
`:578`. The docstring at `:538` says "a human decision overrides everything" and
`hard_gates_pass` is recorded but never consulted on that branch.
`apply_approval_decision` sets any status with no policy consultation, although
`ApprovalRuntime` policies exist (`ops/p5_types.py:166-171`).

**Canonical type semantics — modelled on `ApprovalRequest` (`ops/p5_types.py:142-156`,
the only record with WHO/WHEN/WHY) but in Postgres, not `approvals.json`:**
`decision_id, artifact_id, artifact_sha256 (mandatory `_SHA256_HEX`), reviewer_id,
decision ∈ {ACCEPT, REJECT, REQUEST_REVISION}, reason, created_at`, plus
`machine_gate_outcome` so an override is *recorded against* the gate it contradicts
rather than bypassing it. The `HumanDecision` enum at `p5_1_types.py:460-464` is
reduced to a mapper onto this enum, since KEEP_V0/KEEP_V1 are promotion choices,
not review verdicts.

**Recorded for a later phase, not fixed in P0-2:** the `p5_1_pairwise.py:550-576`
override ordering.

---

## Migration order

1. **P0-2 (now):** type semantics frozen above; tests assert them.
2. **P0-3:** `TimelineIR` first — `content_hash()` unblocks `RenderReceipt`.
3. **P0-4:** `FailureClass` + admission decision (open blocker).
4. **P0-5:** `RenderReceipt` + `MediaProbe` + renderer authority; then
   `VideoAcceptance`, since it must cite whichever renderer won.
5. **P0-6:** `ShotRecipe` time units and constraint predicates.
6. **P0-7:** `RevisionLink` columns; `EvidencePack` persistence.
7. **P0-8:** `HumanDecision` + `REAL_VIDEO_ACCEPTED` emitted by code.

## Deliberately out of scope for P0-2

Not touched, per instruction: provider admission; executor routing; renderer
consolidation; FFmpeg centralization; `REAL_VIDEO_ACCEPTED`; JianYing migration. Not
touched because found here and not mine to fix in this phase: the
`FinalReviewResult` request-body defect (P0-8 acceptance blocker); the three
path-only verdicts (P0-5); `p5_1_pairwise.py:550-576` override ordering (P0-8);
`blender_workflow:286` / `p3_runtime:473` / `repair.py:48` fail-open mappers (P0-4).
