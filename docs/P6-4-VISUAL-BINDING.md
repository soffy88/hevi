# HEVI P6.4 — Visual Grammar → P5.3 Cinematic Binding

> Status: **P6.4 COMPLETE**
> Baseline: `34df92098b548cfaf20fe74f8f410865f0b61506`
> P5.3 modified: **NO** · P0–P5 modified: **NO**

---

## 1. What this closes

P6.0 declared the grammars. P6.1–P6.3 compiled story, presenter and look. Nothing
connected them to the cinematic engine that actually knows how to shoot. This
phase draws that line:

```
ProductProfile
    ↓ narrative_grammar_id
NarrativeIntent          (P6.1)
    ↓ presenter_grammar_id
PresenterIntent          (P6.2)
    ↓ visual_grammar_id
VisualIntent            (P6.4)   ← five strategies, no shots
    ↓
retrieve_with_evidence() (P5.3)  ← the ONLY way in
    ↓
RecipeSelectionEvidence  (P5.3)
    ↓
ShotPlan → Editable Timeline        (P0/P1 — not P6.4)
```

```
P6.0-P6.3:  Product → Story → Presenter → Visual Intent   (stops here)
P6.4:                                                → P5.3 Cinematic Engine → Renderer
```

## 2. Authority ownership

| Concern | Owner | P6.4 role |
|---|---|---|
| Directive camera / motion / composition / lighting / editing | P6.4 `VisualGrammar` | declares five languages |
| Which concrete recipe to use | **P5.3** `retrieve_with_evidence()` | never names a recipe |
| Rank / score / reject | **P5.3** `RecipeLibrary.rank_candidates()` | never reimplemented |
| `ShotPlan`, `MotionPlan` | P0 / P1 | creates neither, imports neither |
| The `VisualBeat` request | P1 `hevi.production.p1_types` | **consumes** it; never redefines |
| Camera primitives (`dolly`, `pan`, `path`, `focal_behavior`) | P5.3 `CinematicRecipe` | declares coarse directives only |
| Renderer, provider, GPU, CapCut | P0–P5 | names none |

## 3. The one-way door into P5.3

There is exactly one entry, and it is P5.3's own:

```python
candidates, evidence = retrieve_with_evidence(library, beat, profile_id=..., ...)
```

P6.4 does not build a `RecipeLibrary`, does not rank, does not score, does not
name a recipe id. If it chose recipes it would be a second selector sitting
beside P5.3's, and the two would drift — exactly the `recipe_selector` /
`shot_selector` / `motion_selector` recreation the spec forbids.
`test_mutation_bypassing_retrieve_with_evidence_must_fail` and its four siblings
inject each bypass into real source and require it to be caught:

| Bypass mutant | Guard violation |
|---|---|
| removed the call entirely | `bypasses_retrieve_with_evidence` |
| `library.search(...)` | `calls_private_selection:search` |
| `library.rank_candidates(...)` | `calls_private_selection:rank_candidates` |
| `retrieve_recipes(...)` | `calls_private_selection:retrieve_recipes` |
| built `RecipeCandidate(...)` + `selected_recipe_id="CAMERA.SLOW_PUSH_IN"` | `constructs_recipe_candidate`, `hardcoded_recipe_id:CAMERA.SLOW_PUSH_IN` |

## 4. Where the chain stops, and why

The system chain continues to `ShotPlan`, but **`ShotPlan` and `MotionPlan` are
owned by P0/P1**, and P5.3's own module docstring says it does *not* "override
ShotPlan, override MotionPlan". So P6.4's binding deliberately ends at the
evidence.

Constructing a `ShotPlan` here would be a second shot system — forbidden by
`NO_SECOND_SHOT` / `NO_SECOND_MOTION` and by "不要新增 shot system". P6.4 imports
no shot or motion plan type at all, which
`test_integration_module_defines_no_shot_or_motion_type` and
`test_integration_imports_no_shot_plan_or_motion_plan` assert.

## 5. One vocabulary, not two

`VisualGrammar` declares `motion_language`, `composition_language` and
`lighting_language` — concepts P6.3 already models. They are **imported**, not
redefined:

```python
from hevi.production.p6.visual_style.model import (
    CompositionLanguage, LightingLanguage, MotionLanguage,
)
```

Pinned by `test_schema_reuses_p6_3_{motion,composition,lighting}_vocabulary`.
Two enums with one name and different members would be two visual authorities,
and the compiler would spend its life arbitrating between them. P6.4 adds exactly
two vocabularies of its own: `CameraLanguage` and `EditingLanguage`.

### Coherence between the two layers

P6.3 (`documentary_realism`, `educational_clarity`) and P6.4 share grammar ids.
They are two *projections* of one visual tradition, so a disagreement on a shared
language is a real conflict. `VisualCompiler.compile()` takes the optional P6.3
`VisualStyleIntent` and refuses mismatches:

```
P6.3 corporate_clean (motion=restrained) + P6.4 commercial_clean (motion=fluid)
  → VISUAL_GRAMMAR_STYLE_CONFLICT:motion_language:grammar=fluid:style=restrained
```

Pinned by `test_compiler_style_coherence_refuses_disagreeing_layers`. A conflict
is raised, not resolved — silently preferring one layer would make the other
decorative.

### Camera language is coarse on purpose

`CameraLanguage` is `observed / stable / directed / energetic / intimate /
discovering`. It does **not** enumerate `dolly`, `pan`, `zoom`, `crane`,
`orbit`, `truck` — P5.3's `CinematicRecipe` owns those primitives via
`camera_behavior`, `path` and `focal_behavior`. A directive vocabulary that
restated them would be a second camera vocabulary competing with what it feeds.
`test_schema_camera_vocabulary_is_coarse_not_primitives` pins the boundary.

## 6. Strategy derivation — tables, not conditionals

```
camera_language ──→ shot_strategy  ──→ P1 shot_role      (what P5.3 searches on)
motion_language ──→ motion_strategy ──→ P5.3 semantic_role
```

The second hop matters more than it looks. `retrieve_with_evidence` scores
semantic fit partly on `beat.motion_purpose in recipe.semantic_roles`, and the
shipped 80-recipe corpus uses a **closed** set: `EVIDENCE_DOMINANT`,
`EMOTIONAL_PRESENCE`, `REVEAL`, `DIRECT_ADDRESS`, `EXPLAIN`, `DETAIL`,
`COMPARE_CONTRAST`, `FOLLOW`, `ESTABLISH`, `TRANSITION`, `DEVELOPMENT`.

My first pass invented `REVEAL_STRUCTURE` / `FOLLOW_SUBJECT` / `SHOW_SCALE`.
None of them exist in the corpus, so that signal was silently always zero and
ranking degraded to whatever happened to score highest. Switching to P5.3's own
vocabulary changed real outcomes: `dramatic_reconstruction` moved from
`EVIDENCE.MAP_TRACE` to `CAMERA.COMBINED_MOVEMENT`, which is what a directed
dramatic camera should retrieve.

Speaking the target system's vocabulary is not selecting. P5.3 still ranks,
scores and decides.

## 7. Product coverage — general grammars only

Four shipped: `documentary_realism`, `dramatic_reconstruction`,
`educational_clarity`, `commercial_clean`.

Explicitly refused: `history_visual_grammar`, `avatar_visual_grammar`,
`science_visual_grammar` — named in `FORBIDDEN_VISUAL_GRAMMAR_IDS`, and
`registry.validate()` reports one as `PRODUCT_NAMED_VISUAL_GRAMMAR`.

The spec's anti-pattern, `P03 → historical_camera()`, is killed three ways:
product literals are banned by AST (`guard_no_product_literals`), product-named
helpers are banned (`guard_no_product_named_helpers`), and `history_camera()`
injected into real `visual_compiler.py` and `visual_grammar.py` must be caught.

Verified bindings against the real 80-recipe corpus:

| narrative + presenter | grammar | beat role | selected recipe |
|---|---|---|---|
| `documentary` + `documentary_explainer` | `documentary_realism` | FOLLOW | `CAMERA.TRUCK` |
| `story` + `documentary_explainer` | `dramatic_reconstruction` | REVEAL | `CAMERA.COMBINED_MOVEMENT` |
| `explanatory` + `avatar_explainer` | `educational_clarity` | EXPLAIN | `EXPLAINER.CONCEPT_BUILD` |
| `short_form` + `product_presentation` | `commercial_clean` | PAYOFF | `EMOTIONAL.SOLITUDE_HOLD` |

## 8. Fail-closed behaviour

| Condition | Error |
|---|---|
| profile declares no grammar | no visual stage runs (grammar optional) |
| grammar declared with no presenter | `MISSING_PRESENTER_FOR_VISUAL_GRAMMAR` |
| id not registered | `UNKNOWN_VISUAL_GRAMMAR` |
| no id at all | `VISUAL_GRAMMAR_NOT_FOUND` |
| grammar not in the registry at compile time | `VISUAL_GRAMMAR_NOT_FOUND:<id>` |
| narrative/grammar pairing not permitted | `INCOMPATIBLE_VISUAL_PAIRING:narrative=…` |
| presenter cannot be carried by the composition | `INCOMPATIBLE_VISUAL_PAIRING:presenter=…` |
| P6.3/P6.4 shared language disagrees | `VISUAL_GRAMMAR_STYLE_CONFLICT:…` |
| upstream narrative/presenter intent invalid | `NARRATIVE_INTENT_INVALID` / `PRESENTER_INTENT_INVALID` |
| P5.3 returns no candidate | `VISUAL_BINDING_NO_RECIPE` |
| unknown `profile_id` (all candidates violate) | `VISUAL_BINDING_NO_RECIPE` |

No default grammar, and no local recipe fallback. A visual directive with nothing
filmable behind it is a defect to surface.

## 9. Determinism

400 compiles and 400 bindings over the four grammars: exactly one hash and one
evidence fingerprint per grammar.

`RecipeSelectionEvidence` carries a `timestamp`, and P5.3 documents that
identical inputs give identical evidence *except for the timestamp*. Hashing it
would make every decision look non-deterministic when the decision was not, so
`evidence_fingerprint()` excludes it —
`test_integration_evidence_fingerprint_excludes_the_timestamp` proves two
differing timestamps produce the same fingerprint.

`test_integration_binding_is_reproducible_after_intervening_calls` binds a
different grammar in between and requires the original decision to be unchanged,
so retrieval carries no state between calls.

## 10. Migration notes

**Additive.** `visual_grammar.py` and `visual_compiler.py` are new;
`ProductProfile` gains `visual_grammar_id`; `ProductIntent` gains
`visual_intent` and `visual_strategies()`; `compile_product_intent()` gains a
`visual_compiler` parameter. No P0–P5 file touched.

**Backwards compatible.** A profile with no `visual_grammar_id` compiles exactly
as before. P6.0–P6.3 remain 611 tests (157 / 107 / 151 / 196).

**P5.3 read-only.** The only P5.3 imports are `p5_3.library` (type),
`p5_3.schema` (evidence types) and `p5_3.retrieval` (the one call) —
`test_integration_does_not_modify_p5_3` asserts exactly that, including that only
one retrieval line is imported. `git status` confirms `p5_3/` was last modified
at 03:21, ~17 hours before this phase's first write; the dirty `p5_3/retrieval.py`
and `p5_3/metrics.py` are pre-existing P5.4 metrics work.

**One P6.3 rule scoped, deliberately.** P6.3 forbade *every* P6 module from
importing `hevi.production.p1_types`. P6.4 must import P1's `VisualBeat` —
`retrieve_with_evidence` takes that exact type, and consuming an existing request
type is the opposite of a second authority. The blanket ban became two rules:
P6.3's own package may not import `p1_types` at all, and any other P6 phase may
import only the symbol `VisualBeat` from it, with
`test_p1_request_types_allowance_defines_no_beat_type` forbidding any P6 module
from declaring its own `VisualBeat`. The allowance is narrower than the ban it
replaced.

**Rollback:** delete `visual_grammar.py` and `visual_compiler.py`, drop
`visual_grammar_id` from `schema.py`, drop the P6.4 stage from `intent.py`.
P6.0–P6.3 unaffected.

## 11. Acceptance

| Gate | Result |
|---|---|
| `P6.4_ARCHITECTURE` | PASS |
| `VISUAL_SCHEMA` | PASS |
| `VISUAL_REGISTRY` | PASS |
| `VISUAL_COMPILER` | PASS |
| `P5.3_BINDING` | PASS |
| `NO_SECOND_SHOT` | PASS |
| `NO_SECOND_MOTION` | PASS |
| `NO_PRODUCT_BRANCHING` | PASS |
| `DETERMINISM` | PASS (400 compiles, 400 bindings) |
| `P0_P5_REGRESSION` | PASS |
| `RUFF` | PASS |
| `MYPY_NEW_ERRORS` | 0 (20 files) |
| `P5.3_UNMODIFIED` | YES |
| `SOURCE_MUTATION_SCOPE` | `P6.4_ONLY` |
| `UNRELATED_DIRTY_PRESERVED` | YES |

| Section | Required | Actual |
|---|---|---|
| Schema | ≥20 | 33 |
| Registry | ≥20 | 36 |
| Compiler | ≥30 | 42 |
| P5.3 Integration | ≥20 | 32 |
| Mutation | 3 specified | 14 |

`TESTS=157` (P6.4) + `611` (P6.0–P6.3) = **768 passed, 0 failed**

P0–P5: P1 28, P2 11, P3 275, P4 15, P5.1 293, P5.2 330, P5.3 285, P5.4 7 — all
passing.

Explicitly not done: no provider, no render, no GPU, no CapCut, no new renderer,
no new timeline, no new shot system, no P5.3 modification.

## 12. Carried forward

| Gap | Owner |
|---|---|
| `commercial_clean` (PAYOFF) retrieves `EMOTIONAL.SOLITUDE_HOLD` — P5.3 ranks on beat semantics that a strategy-derived beat carries thinly. `intent_id` never matches a `recipe.intent`, so that 0.3 signal is dead | P6.5 / P5.3 |
| Compatibility is one-directional: nothing checks a grammar used across two incompatible arcs in one batch | P6.5 |
| No accessibility or legibility floor on the visual directive (`legibility_first` is a constraint string, not a checked value) | P6.5 |
| Nothing binds `editing_language` downstream; P5.3 selects per-shot, not per-sequence | P6.6 |
| `motion_strategy → semantic_role` is a lossy 5→5 mapping; two strategies collapse onto `REVEAL` | P6.6 |
| P6.3's `narrative_grammar` declaration still uncross-checked against `narrative_grammar_id` (P6.1 gap, narrative half) | P6.5 |
