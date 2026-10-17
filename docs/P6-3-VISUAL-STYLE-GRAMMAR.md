# HEVI P6.3 — Visual Style Grammar

> Status: **P6.3 COMPLETE**
> Baseline: `34df92098b548cfaf20fe74f8f410865f0b61506`
> No P0–P5 module modified

---

## 1. Authority ownership

```
ProductProfile
    ↓ narrative_grammar_id
NARRATIVE_GRAMMAR_REGISTRY   → NarrativeCompiler   → NarrativeIntent
    ↓ presenter_grammar_id
PRESENTER_GRAMMAR_REGISTRY   → PresenterCompiler   → PresenterIntent
    ↓ visual_style_id
VISUAL_STYLE_REGISTRY        → VisualStyleCompiler → VisualStyleIntent
    ↓
ProductIntent
    ↓
existing runtime boundary (P0–P5)
```

| Concern | Owner | P6.3 role |
|---|---|---|
| What a video looks like | P6.3 `VisualStyleGrammar` | declares mood / palette / composition / texture / motion / lighting |
| Product identity | `ProductProfile` (P6.0) | adds `visual_style_id` **reference** |
| Story structure | P6.1 | consumed, never recomputed |
| Performance shape | P6.2 | consumed, and it constrains composition |
| Camera, shot, motion execution | P1 / P5.3 `CinematicRecipe` | names none |
| Colour grade execution | P5.2 profile policies, P0 pipeline | names none |
| Renderer | `hevi.renderers.base` | names none; constraints are declared, not resolved |
| Image model, asset generation | P5.2 | names none |
| Provider, TTS | `hevi.providers` | names none |

`ProductProfile` gains exactly one field, `visual_style_id`. It is a *reference*:
a product selects a shared style and never defines its own. It carries no
`mood`, `palette`, `composition`, `texture` or `lighting`, and
`test_architecture_product_selects_style_reference_only` enforces it.

## 2. Data flow

```
NarrativeIntent  ─┐
                  ├─→ VisualStyleCompiler ─→ VisualStyleIntent
PresenterIntent  ─┘        ▲
                            │
              VisualStyleGrammar (from VISUAL_STYLE_REGISTRY)
```

Both upstream intents are genuine inputs, not decoration — see §5.

`VisualStyleIntent` carries `style_id`, `mood`, `palette`, `composition`,
`texture`, `motion`, `lighting` and `constraints`, plus the inherited presenter
requirements. `motion` is an addition beyond the Phase 4 field list: the grammar
has six language fields and dropping one would silently discard a declared
quality.

## 3. Supported styles

Six general styles, no product names:

| id | category | mood | palette | composition | texture | motion | lighting |
|---|---|---|---|---|---|---|---|
| `documentary_realism` | documentary | authoritative | natural | documentary | realistic | restrained | natural |
| `archival_history` | archival | nostalgic | warm | observational | archival | deliberate | dramatic |
| `educational_clarity` | editorial | educational | high_contrast | infographic | clean | restrained | studio |
| `cinematic_drama` | cinematic | dramatic | cinematic | cinematic | realistic | deliberate | dramatic |
| `future_tech` | technological | futuristic | cool | cinematic | futuristic | fluid | studio |
| `corporate_clean` | brand_neutral | minimal | natural | presenter_centered | clean | restrained | soft |

Eight commercial video needs are covered by six styles, and the mapping runs
through the narrative compatibility table rather than through product identity:
documentary and historical reconstruction both reach `documentary_realism` /
`archival_history`; education and marketing reach `educational_clarity` /
`corporate_clean`; cinematic story reaches `cinematic_drama`; short form reaches
`educational_clarity`, `corporate_clean` or `future_tech`. Avatar explainer and
science are the same shapes as education — a performed explanation is a
performed explanation, whichever subject it explains.

Forbidden by name and by test: `AVATAR_STYLE`, `TIKTOK_STYLE`,
`COMMERCIAL_STYLE`, `HISTORICAL_STYLE_ONLY` and ten similar tokens
(`test_mutation_historical_style_only_identifier_is_caught`).

### `category` is not a back door

A grouping field is one accidental step from a product taxonomy, so it is a
closed `StyleCategory` enum of *visual traditions* — `DOCUMENTARY`, `ARCHIVAL`,
`EDITORIAL`, `CINEMATIC`, `TECHNOLOGICAL`, `BRAND_NEUTRAL`. An off-vocabulary
category raises `UNKNOWN_STYLE_CATEGORY` rather than filing the style under
"other", and `test_registry_categories_name_visual_traditions_not_products`
checks no category name encodes a product.

### `motion_language` names characteristics, not camera moves

`restrained`, `deliberate`, `fluid`, `energetic`, `still`. P5.3 owns camera
movement; a P6.3 motion language states the *felt quality* of movement and the
existing recipe authority decides what actually moves the camera. No `dolly`,
`pan`, `zoom`, `crane`, `handheld`, `tracking` or `orbit` appears in the enum, and
a test asserts that.

## 4. Compatibility — two dimensions, both data

### Narrative → style

`STYLE_COMPATIBILITY_REGISTRY`, keyed by narrative grammar id:

| narrative | permitted styles |
|---|---|
| `documentary` | `documentary_realism`, `archival_history` |
| `explanatory` | `educational_clarity`, `corporate_clean`, `documentary_realism` |
| `story` | `cinematic_drama`, `documentary_realism`, `archival_history` |
| `short_form` | `educational_clarity`, `corporate_clean`, `future_tech` |

`cinematic_drama` is exclusive to `story`, and `archival_history` serves only
`documentary` and `story` — both asserted directly.

A narrative absent from the table is unrestricted, so a new narrative stays
usable without a compatibility edit. `allow()` **merges**, never replaces, so
adding a pairing cannot silently drop an existing one.

### Presenter → composition

Phase 4 makes `PresenterIntent` an input for a reason. A performance shape
constrains the frame that can carry it: an avatar explainer or a lecture cannot
be framed as an observed documentary. That rule is
`COMPOSITION_COMPATIBILITY`, keyed by presenter grammar id:

| presenter | compositions able to carry it |
|---|---|
| `avatar_explainer` | `presenter_centered`, `infographic` |
| `educational_lecture` | `presenter_centered`, `infographic` |

Presenter shapes that are not performer-dependent (`documentary_explainer`,
`historical_reconstruction`, `product_presentation`) place no constraint and are
absent from the table.

This is a real effect, not a formality: `documentary_realism` is permitted for
`explanatory`, but under an `avatar_explainer` presenter it is refused, because
its `documentary` composition contradicts the performance.
`test_compatibility_presenter_narrows_the_composition` pins exactly that.

Both dimensions raise `INCOMPATIBLE_STYLE_PAIRING`, but the message carries the
side that failed and the permitted set, so the reason is actionable rather than
a bare code.

### Why data

`if narrative == "documentary" and style == "cinematic_drama"` is precisely the
branching the architecture forbids. As a table, adding a pairing is a data change
and the branching guard stays green.

## 5. Fail-closed behaviour

| Condition | Error |
|---|---|
| profile declares no `visual_style_id` | no style stage runs (style optional) |
| `visual_style_id` declared with no presenter | `MISSING_PRESENTER_FOR_VISUAL_STYLE` |
| style id not registered | `UNKNOWN_VISUAL_STYLE` |
| grammar not in the registry at compile time | `VISUAL_STYLE_NOT_FOUND:<ref>` |
| narrative/style pairing not permitted | `INCOMPATIBLE_STYLE_PAIRING:narrative=…` |
| presenter/composition pairing not permitted | `INCOMPATIBLE_STYLE_PAIRING:presenter=…` |
| upstream narrative intent invalid | `NARRATIVE_INTENT_INVALID` |
| upstream presenter intent invalid | `PRESENTER_INTENT_INVALID` |
| upstream grammar id empty | `NARRATIVE_GRAMMAR_ID_MISSING` / `PRESENTER_GRAMMAR_ID_MISSING` |

There is **no default style** and no `try_compile` escape hatch. A partially
styled intent is exactly what a downstream renderer would execute without
question.

The one design decision worth stating: a style needs a performance to be styled
*for*, so `visual_style_id` on a profile with no presenter is refused rather
than silently producing a styled video with nobody presenting it. That is a
declaration-consistency check, not product branching.

## 6. Determinism

**2400 compiles across all 24 usable narrative × presenter × style pairings, and
every hash set is a singleton.** Plus 100 repeated compiles on a fresh
`VisualStyleCompiler` per iteration, and 100 over shared instances.

No clock, no RNG, no environment read. Constraints are merged, deduplicated on
`(key, value, rationale)` and sorted, so declaration order cannot reach the
output.

## 7. Mutation tests — and two guard holes found

22 mutation tests. The important ones inject into **copies of the real shipped
modules**, not into toy snippets, and assert the guard fires on them:

| Mutation injected into real source | Caught by |
|---|---|
| `if product_profile.product_type.value == "P03_HISTORICAL_REENACTMENT"` into `compiler.py` | `test_mutation_injected_product_branch_into_real_compiler_is_caught` |
| `HISTORICAL_STYLE_ONLY` builtin into `registry.py` | `test_mutation_injected_historical_style_only_builtin_is_caught` |
| product-keyed `STYLE_BY_PRODUCT` dict into `compiler.py` | `test_mutation_injected_style_dispatch_dict_is_caught` |
| `from hevi.renderers.base import select_renderer` into `compiler.py` | `test_mutation_injected_renderer_call_into_real_compiler_is_caught` |
| `from hevi.providers.tts import VolcanoTTS` into `registry.py` | `test_mutation_injected_provider_import_into_real_registry_is_caught` |
| `class VisualStylePlan` into `compiler.py` | `test_mutation_injected_second_style_authority_into_real_compiler_is_caught` |
| counter-keyed compile order | `test_mutation_injected_non_deterministic_order_breaks_the_real_compiler` |

**Hole 1 — the shape enumeration was incomplete.** My first branching guard
checked `if` tests, dict keys and subscripts. Writing the exhaustive shape list
against it, one of my own test shapes failed to be caught:

```python
def f(product_type):
    return product_type == "P03_HISTORICAL_REENACTMENT"   # boolean-return branch
```

That is not an `if`, not a dict key, not a subscript. The fix is not another
shape — it is inverting the rule. The P6.3 package has **no** legitimate need for
a product-type literal anywhere, so the guard now flags *any* such literal and
the whole class closes at once. `test_mutation_every_injected_product_branch_shape_is_caught`
pins nine shapes, including nested-attribute, `str()`-wrapped, parenthesised,
`in`-tuple and subscript forms.

**Hole 2 — the exemption was too broad.** Inverting to a blanket rule required an
exemption for `NARRATIVE_REQUIRED_PRODUCT_TYPES` in the shared P6.0 modules, a
membership requirement P6.1 and P6.2 already permit. The first version of that
exemption skipped every `Set` and `Dict` node, which would have let a product
literal hide beside the table.
`test_architecture_requirement_table_cannot_smuggle_a_selection` now proves the
exemption covers the table's own assignment only.

This is the second time, after P6.2, that a guard written to enumerate bad
shapes had a hole where a real branch would actually be written. Enumerating
shapes feels thorough and is not; inverting the rule is.

## 8. Migration notes

**Additive.** `hevi/production/p6/visual_style/` is a new package (`model.py`,
`registry.py`, `compiler.py`). `ProductProfile` gains `visual_style_id`.
`ProductIntent` gains `visual_style_intent` and `visual_languages()`.
`compile_product_intent()` gains a `visual_style_compiler` parameter. No P0–P5
file is touched.

**Backwards compatible.** A profile with no `visual_style_id` compiles exactly as
before, with `visual_style_intent is None`. All 415 P6.0/P6.1/P6.2 tests pass
unchanged — same count as the pre-P6.3 baseline, so no P6.0/1/2 semantics moved.

**One P6.0 defect fixed, deliberately.** `ProductProfile.to_dict()` did not
serialise `narrative_grammar_id` or `presenter_grammar_id`, so two profiles
differing only in which grammars they selected hashed **identically** — which
made `content_hash()` useless as a cache key for precisely the fields P6.1–P6.3
added. All three ids are now serialised.
`test_architecture_profile_content_hash_covers_every_grammar_reference` pins it.
This was a pre-existing P6.1-era omission, not a P6.3 regression, and it was
fixed here because P6.3's product connection depends on the reference being part
of the profile's identity.

**Rollback:** delete `hevi/production/p6/visual_style/`, drop `visual_style_id`
and the three serialised ids from `schema.py`, and drop the style stage from
`intent.py`. P6.0–P6.2 are unaffected.

## 9. Acceptance

| Gate | Result |
|---|---|
| `P6.3_ARCHITECTURE` | PASS |
| `VISUAL_STYLE_SCHEMA` | PASS |
| `STYLE_REGISTRY` | PASS |
| `STYLE_COMPILER` | PASS |
| `PRODUCT_CONNECTION` | PASS |
| `COMPATIBILITY` | PASS |
| `FAIL_CLOSED` | PASS |
| `DETERMINISM` | PASS (2400 compiles, 24 pairings) |
| `NO_SECOND_PIPELINE` | PASS |
| `NO_SECOND_RENDERER` | PASS |
| `NO_SECOND_TIMELINE` | PASS |
| `NO_SECOND_SHOT` | PASS |
| `NO_SECOND_ASSET` | PASS |
| `NO_SECOND_QA` | PASS |
| `NO_PROVIDER_AUTHORITY` | PASS |
| `RUFF` | PASS |
| `MYPY_NEW_ERRORS` | 0 (18 files) |
| `P6.0` / `P6.1` / `P6.2` | PASS (157 / 107 / 151) |
| `P0–P5` | PASS |
| `SOURCE_MUTATION_SCOPE` | `P6.3_ONLY` |
| `UNRELATED_DIRTY_PRESERVED` | YES |

Test minimums, all exceeded:

| Section | Required | Actual |
|---|---|---|
| Schema | ≥20 | 30 |
| Registry | ≥20 | 28 |
| Compiler | ≥30 | 36 |
| Compatibility | ≥20 | 31 |
| Architecture | ≥30 | 46 |
| Mutation | ≥5 | 22 |

`TESTS=193` (P6.3) + `157` + `107` + `151` = **608 passed, 0 failed**

P0–P5: P1 23, P3 274, P4 15, P2 11, P5.1 293, P5.2 330, P5.3 282 — all passing.

## 10. Carried forward

| Gap | Owner |
|---|---|
| Compatibility is one-directional: nothing checks that a style is not simultaneously used by two *incompatible* arcs across a batch, nor that a narrative's styles are internally coherent | P6.4 |
| `category` is declared but never consulted — no lookup uses it yet | P6.4 |
| Nothing cross-checks P6.0's `narrative_grammar` declaration against `narrative_grammar_id` (P6.1 gap, narrative half; presenter half closed in P6.2) | P6.4 |
| Motion language is declared but nothing consumes it downstream; P5.3's `CinematicRecipe` has no binding to it yet | P6.4 / P5.3 |
| `ProductProfile.to_dict()` still omits `profile_refs`-adjacent validation; `profile_refs` unresolved against P2 | P6.4 |
| No per-style accessibility or legibility floor (`style_legibility` is declared as a constraint string, not a checked value) | P6.4 |
