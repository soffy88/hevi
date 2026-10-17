# HEVI P6.5 — The Product Compiler

> Status: **P6.5 COMPLETE**
> Baseline: `34df92098b548cfaf20fe74f8f410865f0b61506`
> P0–P5 modified: **NO** · P5.3 modified: **NO**

---

## 1. The phase that turns a platform into a factory

```
"历史现场解说"   ← a brief
      ↓
P02_HISTORY_RECONSTRUCTION   ← a row, not a branch
      ↓
ProductCompiler              ← ONE compiler, ten products, zero branches
      ↓
ProductProductionIntent
      ├── NarrativeIntent          (P6.1)
      ├── PresenterIntent          (P6.2)
      ├── VisualStyleIntent        (P6.3)
      ├── VisualIntent             (P6.4)
      ├── RecipeSelectionEvidence  (P5.3)
      └── constraints
      ↓
P6.6 runtime orchestration → P6.7 commercial validation
```

Not this:

```python
if is_history:
    use_historical_narrative()
```

The compiler has never heard of history, science, marketing, news, brand or
short video. It reads four grammar references off whatever profile it is handed
and asks four existing compilers to do their part. Every per-product decision was
already made — **as data** — in `product_profiles.py`.

## 2. Ten products, four grammar shapes

| product | narrative | presenter | style | visual grammar | duration |
|---|---|---|---|---|---|
| `P01_AVATAR_EXPLAINER` | explanatory | avatar_explainer | educational_clarity | educational_clarity | 180s |
| `P02_HISTORY_RECONSTRUCTION` | story | historical_reconstruction | cinematic_drama | dramatic_reconstruction | 480s |
| `P03_DOCUMENTARY` | documentary | documentary_explainer | documentary_realism | documentary_realism | 900s |
| `P04_SCIENCE_EXPLAINER` | explanatory | avatar_explainer | educational_clarity | educational_clarity | 240s |
| `P05_NEWS_ANALYSIS` | documentary | documentary_explainer | documentary_realism | documentary_realism | 300s |
| `P06_EDUCATIONAL` | explanatory | educational_lecture | educational_clarity | educational_clarity | 420s |
| `P07_MARKETING` | explanatory | product_presentation | educational_clarity | educational_clarity | 45s |
| `P08_BRAND_STORY` | story | documentary_explainer | cinematic_drama | dramatic_reconstruction | 600s |
| `P09_SHORT_VIDEO` | short_form | avatar_explainer | educational_clarity | educational_clarity | 30s |
| `P10_CINEMATIC_STORY` | story | historical_reconstruction | cinematic_drama | dramatic_reconstruction | 720s |

**Ten products resolve to seven distinct four-tuples, and to only four
narrative+visual shapes.** Six products share a shape and differ by purpose,
audience, duration, aspect and — for P09 — a vertical aspect the others do not
share.

`test_matrix_shared_shapes_really_share` proves this is not a claim: P01 and P04
produce byte-identical narrative and visual intents apart from
`product_profile_id`, and select the same recipe.

That is the thesis of P6.5 made measurable. **One product is not one pipeline.**

## 3. The naming collision, and why it is load-bearing

P6.0 already owns a closed `ProductType` enum with `P01_…`–`P10_…` values, and
**nine of its ten slots mean something different** from the brief's labels:

| slot | P6.0 `ProductType` | P6.5 `CommercialProduct` |
|---|---|---|
| P02 | `P02_NARRATED_KNOWLEDGE` | `P02_HISTORY_RECONSTRUCTION` |
| P03 | `P03_HISTORICAL_REENACTMENT` | `P03_DOCUMENTARY` |
| P04 | `P04_CHARACTER_DOCUMENTARY` | `P04_SCIENCE_EXPLAINER` |
| P05 | `P05_DOCUMENTARY` | `P05_NEWS_ANALYSIS` |
| P06 | `P06_NARRATIVE_FILM` | `P06_EDUCATIONAL` |
| P07 | `P07_CINEMATIC_KNOWLEDGE` | `P07_MARKETING` |
| P08 | `P08_COMMERCIAL` | `P08_BRAND_STORY` |
| P09 | `P09_TUTORIAL` | `P09_SHORT_VIDEO` |
| P10 | `P10_SHORT_FORM` | `P10_CINEMATIC_STORY` |

Only `P01_AVATAR_EXPLAINER` agrees. Merging them into one enum would make
`P03_DOCUMENTARY` and `P03_HISTORICAL_REENACTMENT` look like variants of one
thing. They are not — P6.0's taxonomy is the canonical production taxonomy
(a `ProductProfile.product_type` field), while the brief's labels are the
customer-facing catalogue a brief is written in.

So they stay separate, and the asymmetry is exploited as a safety property:

```
CommercialProduct("P03_DOCUMENTARY")           -> OK
ProductType("P03_DOCUMENTARY")                 -> ValueError
ProductType("P03_HISTORICAL_REENACTMENT")      -> OK
CommercialProduct("P03_HISTORICAL_REENACTMENT") -> ValueError
```

A mix-up fails loudly instead of silently compiling the wrong product. Pinned in
both directions by `test_schema_commercial_label_is_not_a_product_type` and
`test_schema_product_type_is_not_a_commercial_label`.

## 4. `PRODUCT_PROFILE_REGISTRY` already existed

The brief asks P6.5 to "create `PRODUCT_PROFILE_REGISTRY`, responsible for
`id → ProductProfile`". **P6.0 already owns exactly that**, keyed `id@version`,
with `register`/`get`/`list_ids`/`validate`/`stats`. Creating a second registry
under the same name would be a duplicate authority.

But the two hold genuinely different subjects, so this is a sibling rather than a
copy — the same pattern as P6.1 and P6.2 adding narrative and presenter grammar
registries beside P6.0's `GRAMMAR_REGISTRY`:

| | P6.0 `PRODUCT_PROFILE_REGISTRY` | P6.5 `COMMERCIAL_PRODUCT_REGISTRY` |
|---|---|---|
| key | `id@version` | `id` |
| profiles carry | *embedded* grammars (P6.0's own model) | grammar **references**, resolved at compile time |
| governs | the canonical production taxonomy | the ten customer-facing rows |

Naming is deliberately distinct so the difference is impossible to miss.
`assert_no_id_collision()` keeps the two namespaces from ever drifting into a
shared id.

The structural proof that they are not interchangeable: P6.0's `register()`
enforces `validate_composition()`, which **rejects** a reference-only profile
(`DECLARED_BUT_ABSENT:G01_NarrativeGrammar`). The commercial profiles could not be
registered there even if we wanted to. That is a good thing — P6.0's contract is
"a profile carries its grammars", and P6.5 deliberately does not.

## 5. P5.3 evidence is mandatory

`ProductProductionIntent.recipe_evidence` is a `RecipeSelectionEvidence`, obtained
by calling P6.4's `VisualCompiler.bind()` — itself a single call to P5.3's
`retrieve_with_evidence()`. Two consequences:

* A production intent **cannot exist** without a recorded selection decision.
  `compile()` raises `INVALID_PRODUCT_PROFILE:recipe_library required` without a
  library, and `P5_3_NO_RECIPE` when retrieval selects nothing (an empty library,
  or an unknown `profile_id` that every candidate violates).
* P6.5 creates no `RecipeSelector`, `ShotSelector` or `MotionSelector`. Five
  bypass mutants confirm it: removing the call, calling `library.search`,
  calling `library.rank_candidates`, calling `retrieve_recipes`, or hardcoding
  `"CAMERA.SLOW_PUSH_IN"`.

## 6. Fail-closed

| Condition | Error |
|---|---|
| unknown or empty product id | `UNKNOWN_PRODUCT_PROFILE` |
| any of the four references missing | `INVALID_PRODUCT_PROFILE:<field>` |
| no `recipe_library` supplied | `INVALID_PRODUCT_PROFILE:recipe_library required` |
| narrative grammar unregistered | `NARRATIVE_INVALID` |
| presenter unregistered or pairing incoherent | `PRESENTER_INVALID` |
| style unregistered or pairing incoherent | `VISUAL_STYLE_INVALID` |
| visual grammar unregistered, pairing incoherent, or style conflict | `VISUAL_GRAMMAR_INVALID` |
| P5.3 selects nothing | `P5_3_NO_RECIPE` |

No default profile, no default grammar, no default recipe. `validate_profile()`
reports **all** missing references at once rather than one per attempt.

## 7. Determinism

* **1000 rotating compile cycles** across all ten products → exactly 10 distinct
  hashes.
* **1000 cycles of one product** → exactly 1 hash.
* Order-independent: compiling forward and backward produces the same sequence.
* `recipe_evidence.timestamp` is excluded from `content_hash()`. P5.3 documents
  identical evidence *except for the timestamp*, so a plan whose hash moved every
  run could not be diffed or cached.

## 8. Mutation tests — and a real guard hole

19 mutation tests, all injecting into the **real shipped modules**:

| Mutation | Caught by |
|---|---|
| `if product_id == "P02_HISTORY_RECONSTRUCTION"` into `product_compiler.py` | `test_mutation_injected_product_id_branch_must_fail` |
| `if profile.product_type.value == "P03_HISTORICAL_REENACTMENT"` | `test_mutation_injected_product_branch_in_compile_with_product_type_must_fail` |
| `history_compiler()` helper | `test_mutation_injected_history_compiler_helper_must_fail` |
| `science_compiler()` helper | `test_mutation_injected_science_compiler_helper_must_fail` |
| compiler constructing `ShotPlan` (aliased) | `test_mutation_compiler_creating_a_shot_plan_must_fail` |
| compiler *defining* `ShotPlan` / `MotionPlan` / `RecipeSelector` | three tests |
| bypassing `NarrativeCompiler`, `PresenterCompiler`, `VisualCompiler` | three tests |
| injected `hevi.renderers` / `hevi.providers` imports | two tests |

**The guard hole.** My `guard_no_shot_or_motion_construction` compared call names
exactly. The mutant

```python
from hevi.production.p0_pipeline import ShotPlan as _ShotPlan
_ShotPlan(shot_id="s1")
```

walked straight past it. Two fixes, because the first was not enough:

1. **Normalise names** — leading underscores stripped, case-folded — so
   `_ShotPlan(...)` and `timeline()` are caught.
2. **Sweep the whole module**, not just `compile()`. An authority type imported
   under an alias and used from *another* function was still invisible.

This is the third time a name-exact or shape-enumerated guard had a hole where
the violation would actually be written (P6.2 nested attributes, P6.3
boolean-return branches, P6.5 import aliasing). The pattern is consistent:
guards that enumerate forms get bypassed; guards that normalise and sweep get
closed.

## 9. Migration notes

**Additive.** `product_compiler.py` and `product_profiles.py` are new. P6.4's
`visual_grammar` / `visual_compiler` exports were added to the package `__init__`
(they had been missed). `__all__` deduped to 129 unique names. No P0–P5 file
touched; P5.3's last edit predates this phase by ~18 hours.

**Backwards compatible.** P6.0–P6.4 unchanged at 768 tests (157 / 107 / 151 /
196 / 157).

**One self-inflicted regression, caught and fixed.** Renaming
`ProductProfileRegistry` → `CommercialProductRegistry` initially clobbered P6.0's
same-named export from `hevi.production.p6`, breaking three P6.0 tests. Restored,
and `__all__` rebuilt by deduplicating rather than by further string replacement.

**Rollback:** delete both new modules and drop their `__init__.py` exports.
P6.0–P6.4 unaffected.

## 10. Acceptance

| Gate | Result |
|---|---|
| `P6.5_ARCHITECTURE` | PASS |
| `PRODUCT_SCHEMA` | PASS |
| `PRODUCT_REGISTRY` | PASS |
| `PRODUCT_COMPILER` | PASS |
| `TEN_PRODUCT_MATRIX` | PASS (100 combinations) |
| `P5.3_BINDING` | PASS |
| `NO_PRODUCT_BRANCHING` | PASS |
| `NO_SECOND_PIPELINE` | PASS |
| `DETERMINISM` | PASS (1000 + 1000 cycles) |
| `P0_P5_REGRESSION` | PASS |
| `RUFF` | PASS |
| `MYPY_NEW_ERRORS` | 0 (22 files) |
| `SOURCE_MUTATION_SCOPE` | `P6.5_ONLY` |
| `UNRELATED_DIRTY_PRESERVED` | YES |

| Section | Required | Actual |
|---|---|---|
| Schema | 30+ | 35 |
| Registry | 30+ | 33 |
| Compiler | 50+ | 74 |
| Compatibility | 30+ | 32 |
| Mutation | 10+ | 19 |
| Product matrix | 100 | 100 |

`TESTS=197` (P6.5) + `768` (P6.0–P6.4) = **965 passed, 0 failed**

P0–P5: P1 28, P2 11, P3 276, P4 15, P5.1 293, P5.2 330, P5.3 287, P5.4 7.

## 11. Carried forward

| Gap | Owner |
|---|---|
| `P07_MARKETING` retrieves `EXPLAINER.CONCEPT_BUILD` — a shape match, not a marketing recipe. Root cause is P6.4's G-13: `beat.intent_id` can never equal `recipe.intent`, so 0.3 of P5.3's semantic score is unreachable | P6.6 / P5.3 |
| `archival_history`, `corporate_clean` and `future_tech` styles are used by **no** product. `corporate_clean` has no coherent P6.4 grammar partner (`commercial_clean` conflicts on motion), so marketing cannot get its own visual treatment | P6.6 |
| Only 4 narrative shapes cover 10 products; the differentiation lives entirely in purpose/audience/duration. Nothing yet varies narrative *density* or beat count per product | P6.7 |
| `ProductProductionIntent` carries no asset, capability or delivery requirement — P5.2's readiness check cannot yet be driven from it | P6.6 |
| Duration/aspect policy is carried but not cross-checked against P5.3's `duration_range` on the selected recipe | P6.6 |
| No commercial validation of the result (the point of P6.7) | P6.7 |
