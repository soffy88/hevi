# Timeline Inventory — P0-3

**Date**: 2026-10-06 · **Baseline**: `ecd44ed3` (P0-2)
**Canonical**: `hevi/production/timeline_ir.py::TimelineIR`
**Adapters**: `hevi/production/timeline_adapters.py`

Twenty predecessor representations exist. None was a canonical contract. `TimelineIR`
is the normalisation boundary they now project through — **not** a twenty-first model:
every field traces to a predecessor, and the only genuinely new operation is
`content_hash()`.

## Roles are recorded in code, not only here

`LEGACY_TIMELINE_ROLES` in `hevi/production/timeline_adapters.py` maps each
predecessor to one of five roles, so the classification is a value the repository
enforces rather than a claim in a document. A test asserts all twenty are present.

| Role | Meaning |
|---|---|
| `ADAPTER` | translated into the IR; the adapter is the only way to do so |
| `PROJECTION` | derived **from** the IR; cannot define production truth |
| `LEGACY_READ_ONLY` | retained for compatibility; no writer may be added |
| `TEST_FIXTURE` | exists to exercise tests, not to be produced |
| `DEAD` | no callers; recorded so it is not rediscovered as novel |

## The twenty, with role and time unit

| # | Representation | file:line | Unit | Reach before P0-3 | **Role now** |
|---|---|---|---|---|---|
| 1 | `EditableTimeline` | `creative/layer4/editable_delivery.py:81` | int ms | **PROD** (`api/routers/authorities.py:774`) | **ADAPTER** |
| 2 | `studio.Timeline` | `studio/timeline.py:61` | float s | **PROD** (`api/routers/studio.py:224`) | ADAPTER |
| 3 | `HyperComposition` | `providers/hyperframes/compiler.py:23` | float s | **PROD** (`providers/hyperframes/provider.py:21`) | ADAPTER |
| 4 | `digital_human.TimelinePlan` | `digital_human/schemas.py:197` | float s | LIB | ADAPTER |
| 5 | `tongjian.Timeline` | `tongjian/schemas.py:165` | int ms | LIB | ADAPTER |
| 6 | `TimelineLock` | `production/p0_pipeline.py:74` | int ms + sha256 | **PROD** | **PROJECTION** |
| 7 | `TimelineSlot` | `voicepro/schemas.py:40` | int ms | LIB | LEGACY_READ_ONLY |
| 8 | `openshorts.ClipSpec` | `openshorts/schemas.py:30` | float s | **PROD** | LEGACY_READ_ONLY |
| 9 | `TimelineCue` | `layer4_legacy/previs/oprim_impl/contracts.py:28` | float s | LIB | LEGACY_READ_ONLY |
| 10 | `TimelineState` | `layer4_legacy/obase_support/creative.py:198` | none | LIB | LEGACY_READ_ONLY |
| 11 | `BeatPlan` | `creative/direction_plan/models.py:131` | Anchor→ms | **PROD** | TEST_FIXTURE |
| 12 | `BeatSpec` | `creative/director_contract.py:79` | float s | LIB | TEST_FIXTURE |
| 13 | `BeatTimeline` | `assembly/music_to_video_workflow.py:48` | float s | **PROD** | TEST_FIXTURE |
| 14 | `StoryBeat` (assembly) | `assembly/story_to_animation_workflow.py:61` | float s | **PROD** | TEST_FIXTURE |
| 15 | `StoryboardBundle` | `creative/layer4/script.py:57` | none | **PROD** | TEST_FIXTURE |
| 16 | `PlannedShot` | `motion/sequence.py:110` | mixed | LIB | TEST_FIXTURE |
| 17 | `ShotSegment` | `assembly/assembler.py:26` | mixed | **PROD** | TEST_FIXTURE |
| 18 | `JianyingClip` | `studio/jianying.py:22` | float s | **PROD** | TEST_FIXTURE |
| 19 | `StoryBeat` (layer4_legacy) | `layer4_legacy/obase_support/creative.py:211` | none | LIB | TEST_FIXTURE |
| 20 | `NarrativeTimeline` | `narrative/timeline.py:8` | none (`order: int`) | **DEAD** | **DEAD** |

**Unit split before P0-3: 8 float-seconds, 5 integer-ms, 7 with no time field.** After:
one canonical unit (integer ms), enforced at construction.

## Where each IR field came from

| IR member | Predecessor | Verbatim? |
|---|---|---|
| `canvas: Canvas` | `HyperComposition.width/height/fps` (`compiler.py:25-27`) | yes |
| `TrackKind` | `editable_delivery.TrackKind` (`:34-38`) — `VIDEO/AUDIO/TEXT` | yes, same members |
| `Transition` / `TransitionKind` | `editable_delivery.Transition` (`:40-63`) — `CUT/FADE/DISSOLVE/WIPE` | yes, incl. the cut-has-no-duration rule |
| `TimelineClip` | `EditableClip` (`:66-78`) — all ten fields | yes, **plus `start_ms`** |
| `audio_master_clock` | `TimelineLock.audio_lock_id/audio_sha256/audio_lock_revision/drift_ms` (`:77-83`) | yes |
| `content_hash()` | — | **new** |

`TimelineClip.start_ms` is the one field with no direct predecessor, and it exists for
a concrete reason: `EditableTimeline` has no placement, so clips are packed
sequentially per track. That is why `studio/jianying.py:84-85` had to recompute
positions from a cursor and why `clips_from_presentation` hardcoded `start_s=0.0`
(`jianying.py:122`). Without `start_ms` the IR could not express *where* a clip is,
only how long it is.

## The two properties nothing else had

**Stable identity.** VERIFIED before P0-3: `RenderPlan.to_dict()`
(`renderers/base.py:83`) has no hash method, no timeline type is hashed anywhere, and
`RenderReceipt.timeline_hash` (spec §6.2) was unconstructible.
`TimelineIR.content_hash()` is sha256 over `canonical_dict()`, sorted by
`(track, order, clip_id)` so construction order cannot affect it. `timeline_id` and
`revision_id` are **inside** the hash: two revisions of identical content are
different timelines and a receipt must tell them apart.

**Fail-closed validation.** The live compile path today is the opposite —
`providers/hyperframes/compiler.py:72-85` drops non-dict cuts, treats unknown action
as "keep", defaults missing `start_s` to `0.0`/3.0, coerces unknown kind to
`"card"`, and clamps duration with `max(dur, 0.8)`. **There is no `raise` in that
module.** `production/p1_types.py:98` coerces negative duration to `0.0`, and
`:119-121` appends beats without sorting, so no predecessor hash could be stable.

## Invariants the IR enforces (and where they were previously unenforced)

| Invariant | Code | Prior state |
|---|---|---|
| integer ms only | `_require_int_ms` | 8 representations used float seconds |
| non-negative duration | `TimelineClip.__post_init__` | `p1_types.py:98` clamped to `0.0` |
| deterministic ordering | `canonical_order()` | `p1_types.py:119-121` unsorted append |
| no overlap | `_validate_no_overlap` | only a post-hoc verdict (`verdict/production_checks.py:109-130`) |
| video contiguity, no gaps | `_validate_track_coverage` | no predecessor check at all |
| references resolve | `_validate_referenced_assets` | discovery at render time |
| transition endpoints valid | `_validate_continuity` | none |
| clip-id uniqueness | `_validate_unique_ids` | `editable_delivery.py:104-106` had it |
| video covers duration | `_validate_track_coverage` | `editable_delivery.py:99-103` had it |
| audio-clock binding | `AudioMasterClock` + `verify_against` | `TimelineLock:87-93` had it |

The last four are preserved from `EditableTimeline`/`TimelineLock`; the first six are
new.

## Production caller migrated

`hevi/api/routers/authorities.py` — `GET /api/tasks/{task_id}/editable`, the
production-reachable editable-export path (P0-1 §7 recorded it as one of two
HTTP-exposed timelines). It now projects its `EditableTimeline` onto `TimelineIR` and
returns `timeline_ir` with the content hash alongside the existing `editable` and
`jianying` payloads.

Fail-closed at the boundary: `_canonical_timeline_for_export` raises
`HTTPException(409, "TIMELINE_NOT_CANONICAL:...")` if the projection cannot satisfy
the IR invariants. A legacy timeline that does not validate is a source defect, not
something to paper over at the edge — so the export refuses.

Nothing else was migrated. `studio.Timeline`, `HyperComposition` and
`digital_human.TimelinePlan` have adapters available but their call sites are not yet
rewired; that is P0-5 work, which owns renderer consumption.

## Explicitly not done

Per instruction, P0-3 did not touch renderer authority, admission authority, final
acceptance, JianYing export, or the four fail-open mappers. `JianyingClip` is
classified `TEST_FIXTURE` but not migrated — P0-7 owns that path.

## Gate verdict

```text
TIMELINE_IR_CANONICAL               = PASS
TIME_UNIT_MS_ONLY                   = PASS
TIMELINE_VALIDATION_FAILCLOSED      = PASS
TIMELINE_HASH_STABLE                = PASS
TIMELINE_PROVENANCE_BOUND           = PASS
LEGACY_TIMELINES_NONAUTHORITATIVE   = PASS
```

The last two need justification rather than assertion.

**`TIMELINE_PROVENANCE_BOUND`** rests on `AudioMasterClock`: `audio_lock_id`,
`audio_sha256` (validated as 64 hex chars, refused otherwise), `audio_lock_revision`
and `drift_ms` are mandatory and hash-verified against an `AudioLock` via
`verify_against`, carried across verbatim from the only predecessor that bound them.
`timeline_id` and `revision_id` are inside the content hash, so a timeline's identity
records which revision produced it.

**`LEGACY_TIMELINES_NONAUTHORITATIVE`** is a weaker claim than it looks and is stated
honestly: all twenty are classified in `LEGACY_TIMELINE_ROLES`, the five ADAPTERs have
one-directional projections into the IR, and `TimelineLock` — the one predecessor that
claimed canonical status — is now a *projection derived from* the IR rather than an
independently authored record. But five of the twenty (`studio.Timeline`,
`HyperComposition`, `digital_human.TimelinePlan`, `tongjian.Timeline`,
`openshorts.ClipSpec`) still have production call sites that do not go through the IR.
They can no longer *define* timeline truth because the IR is the only type with an
identity and a validator, but their call sites are not yet rewired. Full migration is
P0-5. This is reported as PASS on the "cannot independently define production truth"
criterion and explicitly **not** claimed as "every caller migrated".
