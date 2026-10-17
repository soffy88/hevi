# HEVI P6.0 — Migration Map

How P6.0 lands, and what each later phase adds. P6.0 is additive: no P0-P5 file
is modified, moved, or deprecated.

---

## 1. What P6.0 adds

| Path | Lines | Role |
|------|-------|------|
| `hevi/production/p6/__init__.py` | 106 | Public surface |
| `hevi/production/p6/schema.py` | ~830 | `ProductProfile`, G01-G10, enums, value types |
| `hevi/production/p6/registry.py` | ~240 | `PRODUCT_PROFILE_REGISTRY`, `GRAMMAR_REGISTRY` |
| `hevi/production/p6/compiler.py` | ~200 | `ProductProfileCompiler` contract, fail-closed P6.0 compiler |
| `hevi/production/p6/runtime.py` | ~290 | `produce()` boundary, `ProductionRuntimePort` |
| `tests/test_p6_0_architecture.py` | ~600 | 157 architecture assertions |
| `docs/P6-0-*.md` (4 files) | — | spec, gap map, authority boundary, this map |

**Zero modifications to P0-P5.** Proven by
`test_p6_does_not_modify_frozen_p0_to_p5_modules`, which diffs nine modules
against HEAD.

## 2. Placement rationale

`hevi/production/p6/`, not a new top-level package.

`hevi/production/` already holds P0-P2, P5.2 and P5.3. A `hevi/p6/` would be a
parallel tree for the same concern. A `hevi/commercial/` would name a market
segment rather than a production layer, and would sit next to ~90 existing
packages without a clear owner.

Tests are flat in `tests/`, matching `test_p5_1_architecture.py` and
`test_p5_2_architecture.py`. `tests/architecture/` does not exist in this repo.

## 3. Phase sequence

| Phase | Adds | Depends on | Gate |
|-------|------|-----------|------|
| **P6.0** | schemas, registries, contracts | P0-P5 (read-only) | this document |
| P6.1 | `NarrativeGrammar` behaviour; first real compiler | P6.0 | narrative E2E |
| P6.2 | `PresenterGrammar` → P2 profile + P5.1 presentation | P6.1 | P01 profile |
| P6.3 | `CharacterGrammar` → `entities.ProductionEntity` | P6.1 | P04/P06 profiles |
| P6.4 | `WorldGrammar` → constraint derivation | P6.3 | P03/P06 profiles |
| P6.5 | `EvidenceGrammar` → `EvidenceAsset` binding | P6.1 | traceability E2E |
| P6.6 | P03 historical reenactment profile | P6.4, P6.5 | P03 qualification |
| P6.7 | P05 documentary profile | P6.5 | P05 qualification |
| P6.8 | P08 commercial profile; **resolve `PRODUCT_HERO`** | P6.2, P6.5 | P08 qualification |
| P6.9 | P09 tutorial profile | P6.1, P6.2 | P09 qualification |
| P6.10 | P10 short-form profile; P01/P02/P07 | P6.1, P6.2 | remaining profiles |
| P6.11 | P01-P10 qualification | all | `P01–P10_E2E=PASS` |
| P6.FREEZE | regression + boundary freeze | P6.11 | `HEVI_P6=QUALIFIED` |

## 4. Sequencing constraints

**P6.5 before P6.6/P6.7.** Historical and documentary products are evidence-led.
A profile that cannot answer "which claim does this shot serve" is not a
documentary, so evidence binding precedes the products that depend on it.

**P6.2 before P6.8/P6.9/P6.10.** Three of the ten products use a presenter. One
presenter grammar serves all three; building it per-product is the branching
this architecture exists to prevent.

**P6.4 before P6.6.** Historical reenactment needs a world. P06 narrative film
also needs one, so the world grammar is built once.

**P6.8 owns `PRODUCT_HERO`.** It is the only phase with both the commercial
grammar and the standing to register into P2's registry. P6.5 or earlier must
not touch it — that is how a second profile registry gets created by accident.

## 5. First real compiler (P6.1)

`UnimplementedCompiler` is replaced, not extended. The replacement must:

1. subclass `ProductProfileCompiler` (inherits `validate_profile` and the
   capability check),
2. dispatch on `GrammarKind` — never on `ProductType`,
3. read no provider and select no renderer,
4. return `CompiledProductIntent` with a stable `content_hash()`,
5. keep `test_product_branching_absent` green.

Adding a product then means adding a `ProductProfile`, not editing the compiler.
That is the property the whole layer exists to provide, and
`test_product_branching_absent` is what keeps it honest.

## 6. Carried-forward debt

Not P6's to fix in P6.0, recorded so they are not lost:

| Debt | Owner | Note |
|------|-------|------|
| `PRODUCT_HERO` unresolvable via P2 registry | P2 / P6.8 | 11 references, 0 registrations |
| `profile_grammar.py` lacks `PRODUCT_HERO` | P5.3 | raised, not edited |
| Duplicate `ShotPlan` (`hevi/cinematic/`) | P0 owner | unasserted today |
| Duplicate `MotionPlan` (`hevi/production/semantic_motion.py`) | P0 owner | unasserted today |
| Duplicate `ShotPreparation` (`hevi/season_planner/`) | P5.2 owner | unasserted today |
| `ProfileId` non-exhaustive | P2 | runtime-registration precedent exists |
| P5.1 QA guard misses real class names | P5.1 | guards `QualityEvaluator`, real name is `QualityEvaluation` |
| `hevi/pipeline/longvideo_orchestrator.py` (71 KB) ownership unknown | unassigned | not traced |

## 7. Rollback

P6.0 is additive and self-contained. Removing
`hevi/production/p6/`, `tests/test_p6_0_architecture.py` and the four docs
restores the previous state exactly. No migration, no data, no config, and no
P0-P5 edit to undo.

## 8. Dirty-tree discipline

The canonical checkout carries substantial unrelated dirty state by design.
P6.0 adds only its own paths and does not clean, reset, stash, or absorb
anything. `test_unrelated_dirty_is_preserved` asserts that every P6-attributed
change lands under `hevi/production/p6/`, `tests/`, or `docs/`.
