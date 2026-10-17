# HEVI P6.0 — Product Grammar Specification

> Status: **P6.0 ARCHITECTURE ONLY**
> Baseline: `34df92098b548cfaf20fe74f8f410865f0b61506`
> Scope: schemas, registries, compiler contract, runtime boundary
> Explicitly **not** in scope: any grammar behaviour, any product business logic

---

## 1. Objective

Ten commercial video products, one production engine.

```
ProductProfile
  -> Product Grammar (declarative, composable)
  -> Narrative / Performance / Visual Constraints
  -> Unified Production Runtime  (existing P0-P5)
  -> Render / Delivery
```

P6 is a **product-intent layer**. It states what kind of video is being made
and which constraints bound it. It never states how the video is made — that
stays with P0-P5.

---

## 2. Product matrix

| ID | Type | Grammar composition |
|----|------|---------------------|
| P01 | `AVATAR_EXPLAINER` | Presenter + Narrative + Cinematic |
| P02 | `NARRATED_KNOWLEDGE` | Narrator + Narrative + Evidence |
| P03 | `HISTORICAL_REENACTMENT` | Evidence + World + Character + Narrative + Cinematic |
| P04 | `CHARACTER_DOCUMENTARY` | Character + Documentary + Evidence |
| P05 | `DOCUMENTARY` | Documentary + Evidence + Narrative |
| P06 | `NARRATIVE_FILM` | Character + World + Narrative + Cinematic |
| P07 | `CINEMATIC_KNOWLEDGE` | Narrator + Evidence + Cinematic |
| P08 | `COMMERCIAL` | Commercial + Presenter/Character + Cinematic |
| P09 | `TUTORIAL` | Instruction + Presenter + Narrative |
| P10 | `SHORT_FORM` | ShortForm + Narrative + optional Presenter/Character/Evidence |

The matrix is **declarative intent**, not implementation. A row is a list of
`GrammarRef`; it is not a code path. P6.0 ships the ten `ProductType` members
and the `GrammarKind` vocabulary, and **zero** product profiles — populating
the matrix is P6.6-P6.10.

---

## 3. Grammars (G01-G10)

| Kind | Carries | Notable invariant |
|------|---------|-------------------|
| `G01_NarrativeGrammar` | mode, ordered nodes, arc constraints | nodes unique, non-empty |
| `G02_PresenterGrammar` | presenter identity refs, delivery/camera/gesture policy | `presenter_id` required |
| `G03_CharacterGrammar` | character identity, role, dialogue/performance policy | **must** declare ≥1 continuity constraint |
| `G04_WorldGrammar` | era, location, culture, technology, visual constraints | not an asset authority |
| `G05_EvidenceGrammar` | claims, epistemic status, source refs | `FACT` **requires** a source |
| `G06_DocumentaryGrammar` | narrator/interview/archive refs, reconstruction policy | declares 4 required answers per shot |
| `G07_CommercialGrammar` | brand, locked product identity, proof points, forbidden claims | **must** declare ≥1 forbidden claim |
| `G08_InstructionGrammar` | objective, ordered verifiable steps | every step needs action + expected state + verification |
| `G09_ShortFormGrammar` | platform, duration, hook, beat/caption/cut/retention policy | hook required |
| `G10_CinematicGrammar` | `CinematicIntent` in P5.3 vocabulary | **declaration only** — P5.3 resolves all motion |

Every grammar is a frozen dataclass with `to_dict()`. All are declarative,
composable, serialisable, provider-independent and runtime-independent — the
last two are enforced by AST guards, not by convention.

### Epistemic honesty (G05)

`EpistemicStatus` separates `FACT` / `INTERPRETATION` / `RECONSTRUCTION` /
`FICTION`. Two rules are load-bearing:

- `EvidenceClaim` with `FACT` and no `source_refs` raises at construction.
- `disclosure_required` is true for `RECONSTRUCTION` and `FICTION`.

A generated model output is not an evidence authority. It may enter only as
`DERIVED`, `RECONSTRUCTION` or `SYMBOLIC`.

---

## 4. ProductProfile

Declared in `hevi/production/p6/schema.py`. Frozen, versioned, hashable.

Required: `id`, `version`, `product_type`, `purpose`, `audience`, `grammars`.
Optional: `profile_refs`, `duration_policy`, `aspect_policy`, the ten grammar
payloads, five policy tuples, `renderer_constraint`, `constraints`,
`qualification_profile`.

`content_hash()` is SHA-256 over `to_dict()` with sorted keys, so identical
intent always hashes identically across processes.

### Composition validation

`validate_composition()` is fail-closed in both directions:

- `DECLARED_BUT_ABSENT` — a profile references a grammar it does not carry.
- `PRESENT_BUT_UNDECLARED` — a profile carries a grammar it never declared.
- `SHORT_FORM_ASPECT_MISMATCH` — vertical-only grammar with a non-vertical aspect.

### Why `ProductProfile` is not a second profile registry

HEVI already has exactly one creative profile authority:
`hevi.production.p2_types.ProductionProfileRegistry`, reached via
`hevi.production.p2_profiles.get_registry()`.

| | `ProductionProfile` (P2) | `ProductProfile` (P6) |
|---|---|---|
| Owns | creative direction | commercial product intent |
| Carries | shot/motion/edit grammar, asset policy | grammar refs, product constraints |
| Registry | `ProductionProfileRegistry` | `ProductProfileRegistry` |
| Relationship | — | **references** via `profile_refs` |

P6 never defines or registers a `ProductionProfile`. Enforced structurally:
`test_no_second_authority` asserts no P6 module defines
`ProductionProfile` or `ProductionProfileRegistry`, across 23 canonical types.

---

## 5. Registries

| Registry | Holds | Key |
|----------|-------|-----|
| `PRODUCT_PROFILE_REGISTRY` | `ProductProfile` | `id@version` |
| `GRAMMAR_REGISTRY` | grammar kind → contract | `GrammarKind` |

Both fail closed: duplicate qualified id raises, invalid composition is rejected
**at registration** rather than first use, and unknown grammar kinds are refused.
`GrammarRegistry.validate_all()` proves all ten kinds carry a contract.

---

## 6. Compiler contract

`ProductProfileCompiler` (ABC) with four mandatory capabilities, checked in
`__init__` so a subclass cannot drop one:

| Capability | Meaning |
|------------|---------|
| `DETERMINISTIC` | identical profile in, byte-identical intent out |
| `FAIL_CLOSED` | unknown type, unresolvable ref, missing grammar → raise |
| `SCHEMA_VALIDATED` | validated before any intent is produced |
| `PROVIDER_INDEPENDENT` | no provider read, no provider lookup |

`validate_profile()` lives on the base class so no implementation can skip it.
Order matters: validation runs **before** the not-implemented refusal, so a
malformed profile is reported as malformed rather than hidden behind
"not implemented" (`test_compiler_validates_before_reporting_unimplemented`).

`CompiledProductIntent` carries **no** `VisualBeat`, `ShotPlan`, `MotionPlan`
or renderer. Holding those would make P6 a second timeline and shot authority.

**P6.0 ships `UnimplementedCompiler`, which raises.** It exists so the contract
is executable and testable now. A stub returning empty intent would let a caller
believe a product had been compiled when nothing had happened.

---

## 7. Runtime boundary

```python
produce(product_profile, source_material, production_constraints)
```

`PIPELINE_STAGES` names the seven hand-off points in the order the existing
runtime performs them. P6 asserts the list; it does not walk it.

`ProductionRuntimePort` is a `Protocol` describing what P6 needs from a runtime.
**No implementation of it lives in P6** — any such implementation would be the
second pipeline the architecture forbids.

`RuntimeBoundary.produce()` while unbound raises `RuntimeNotBoundError`. P6 will
not fall back to a built-in run, because a built-in run is exactly the thing
being forbidden.

Caller constraints may only **narrow** a product's declared bounds.
`CONSTRAINT_EXCEEDS_PRODUCT_DECLARATION` rejects widening.

---

## 8. P6.0 acceptance

| Gate | Result |
|------|--------|
| `PRODUCT_PROFILE_SCHEMA` | PASS |
| `GRAMMAR_CONTRACT` | PASS |
| `REGISTRY` | PASS |
| `COMPILER_CONTRACT` | PASS |
| `RUNTIME_BOUNDARY` | PASS |
| `AUTHORITY_BOUNDARY` | PASS |
| `MIGRATION_MAP` | PASS (`docs/P6-0-MIGRATION-MAP.md`) |
| `NO_SECOND_PIPELINE` | PASS |
| `NO_SECOND_RENDERER` | PASS |
| `NO_SECOND_TIMELINE` | PASS |
| `NO_SECOND_SHOT` | PASS |
| `NO_SECOND_ASSET` | PASS |
| `NO_SECOND_QA` | PASS |
| `NO_PROVIDER_AUTHORITY` | PASS |
| `NO_HARDCODED_PRODUCT_BRANCHING` | PASS |

Every gate is a test that executes. None is asserted from description text.

---

## 9. Layout decision

`hevi/production/p6/` — inside the canonical `hevi/production/` home where
P0-P2, P5.2 and P5.3 already live.

Not `tests/architecture/`: HEVI has no such directory and architecture suites are
flat (`test_p5_1_architecture.py`, `test_p5_2_architecture.py`). Creating a
parallel directory was the one thing the spec forbids.
