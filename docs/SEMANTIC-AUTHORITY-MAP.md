# HEVI P6.5.1 — Semantic Authority Map

> Deliverable of Phase 1. Audit of `recipe.intent`, `semantic_roles` and retrieval
> scoring in P5.3 against `beat.intent_id`, `NarrativeIntent` and `VisualIntent`
> in P6.
>
> Companion to `docs/P6-4-VISUAL-BINDING.md` §12 and `docs/P6-0-GAP-MAP.md` G-13.

---

## 1. The finding

**`recipe.intent` is not a vocabulary.** It is a per-recipe description.

Measured across the 80 shipped recipes:

```
77 distinct intent values / 80 recipes
```

Almost every value is a singleton:

| intent | recipes |
|---|---|
| `SHOW_PROCESS` | 1 |
| `ZOOM_TO_DETAIL` | 1 |
| `EVOKE_SOLITUDE` | 1 |
| `BUILD_UNDERSTANDING` | 2 |
| `SHOW_DETAIL` | 2 |
| `COMPARE_STATES` | 2 |
| the other 72 intents | 1 each |

`CinematicRecipe.intent` is declared as `str` in `hevi/production/p5_3/schema.py`
with no enum, no registry and no validation. It is a human-readable label
describing what one recipe does.

## 2. Why that breaks the bridge

`retrieve_with_evidence` scores semantic fit as:

```python
def _semantic_match(recipe, beat) -> float:
    if beat.shot_role      and beat.shot_role      in recipe.beat_roles:      score += 0.4
    if beat.intent_id      and beat.intent_id      == recipe.intent:         score += 0.3   # ← unreachable
    if beat.motion_purpose and beat.motion_purpose in recipe.semantic_roles:  score += 0.2
    if beat.narrative_phase and beat.narrative_phase in recipe.beat_roles:    score += 0.1
```

P6.4 sets `beat.intent_id = intent.qualified_id`, i.e.
`"documentary_realism@v1.0.0"`. No recipe intent is ever that string. The term is
**structurally unreachable** — not misconfigured, unreachable.

Measured ceiling:

| term | weight | reachable from P6? |
|---|---|---|
| `shot_role` | 0.40 | yes — strategy-derived, real vocabulary |
| `intent_id` | 0.30 | **never** |
| `motion_purpose` | 0.20 | yes, after P6.4's vocabulary fix |
| `narrative_phase` | 0.10 | only by accident (P1's default) |

```
semantic_match  ≤ 0.70
selection_score loses up to 0.30 × 0.30 = 0.09 of 1.00   (9%)
```

## 3. What *is* genuinely shared

Three vocabularies survive the audit as real, cross-layer contracts:

| vocabulary | size | owner | shared with |
|---|---|---|---|
| `semantic_roles` | **11** | P5.3 | *nothing yet — this is the gap* |
| `RecipeFamily` | 8 | P5.3 (`StrEnum`) | — |
| `beat_roles` | 10 | P5.3 | P1 `VisualBeat.shot_role` |

`semantic_roles` is the one that matters: 11 values, every recipe carries at
least one, and it is the vocabulary a *layer* has a job for:

```
EVIDENCE_DOMINANT   x23   (29%)
EMOTIONAL_PRESENCE  x20   (25%)
REVEAL               x8   (10%)
DIRECT_ADDRESS       x7    (9%)
EXPLAIN              x7    (9%)
DETAIL               x7    (9%)
COMPARE_CONTRAST     x4    (5%)
FOLLOW               x4    (5%)
ESTABLISH            x4    (5%)
TRANSITION           x3    (4%)
DEVELOPMENT          x1    (1%)
```

`recipe.intent` is excluded from the contract by design. It is a recipe's own
description, and a layer-level contract has no business matching on it.

## 4. Who owns what

| concern | owner | why |
|---|---|---|
| **story intent** — the arc, node order, `narrative_phase` | **P6.1** `NarrativeGrammar` / `NarrativeIntent` | P5.3 has no concept of an arc. It sees one beat at a time. |
| **shot intent** — `camera_language`, the strategy that becomes a beat role, the semantic role the beat serves | **P6.4** `VisualGrammar` / `VisualIntent` | this is the directive layer that feeds P5.3 |
| **recipe intent** — a label describing one recipe | **P5.3** `CinematicRecipe.intent` | per-recipe free text. Not a contract surface. Never matched. Never edited. |
| **ranking / weighting** | **P5.3** `rank_candidates` | P6 supplies inputs only; it never weighs them |

## 5. The repair

`hevi/production/semantic_contract.py` — `ProductionSemanticIntent` over the 11
existing roles, plus a `SemanticDirective` that tells P6 what to put on a beat.

**No new intent strings.** Every `semantic_id` is an existing P5.3
`semantic_role`; a test asserts the set matches the shipped corpus exactly, so if
P5.3 gains a role the contract fails loudly rather than drifting.

### What it fixed

| before | after |
|---|---|
| `narrative_phase` arrived as P1's `DEVELOPMENT` default — by accident | chosen deliberately per grammar shape |
| motion strategy → role was a hard 5→5 table | contract carries a *set* per shape, resolved deterministically |
| `RESTRAINED_PUSH` and `DELIBERATE_MOVE` both collapsed to `REVEAL` | the set-to-single collapse is recorded and inspectable |

Real outcome changes:

| product | before | after |
|---|---|---|
| `P07_MARKETING` | `EXPLAINER.CONCEPT_BUILD` | `CAMERA.DETAIL_TO_CONTEXT` |
| `P09_SHORT_VIDEO` | `EMOTIONAL.SOLITUDE_HOLD` | `CAMERA.STATIC_HOLD` |

### Honest measurement of the score gain

| | before | after | delta |
|---|---|---|---|
| mean max `semantic_match` over the corpus | 0.56 | 0.58 | **+0.02** |
| `selection_score` contribution | — | — | **+0.006** |

**This is a small gain, and it is capped by the unreachable term.** The contract's
value is structural, not numeric: it makes the shared vocabulary explicit, makes
phase selection deliberate instead of accidental, and turns a silent information
loss into a recorded decision. Claiming a large score improvement here would be
false.

## 6. What is still broken, and the one-line fix

The 0.30 term remains unreachable. Both available routes are forbidden:

* **Editing P5.3 scoring** — out of scope, and P5.3 has been read-only throughout.
* **Setting `beat.intent_id` to a recipe intent** — that is recipe selection by
  label, i.e. a second selector beside P5.3's, and with 77 singleton intents it
  would select exactly one recipe. This is the `RecipeSelector` the P6.5
  architecture forbids.

The correct fix belongs to P5.3 and is a one-line change to `_semantic_match`:

```python
# instead of:  beat.intent_id == recipe.intent        (0.30, unreachable)
if beat.intent_id and beat.intent_id in recipe.semantic_roles:
    score += 0.30
```

with P6 setting `beat.intent_id` to a contract `semantic_id`. That makes the
existing weight reachable against the vocabulary that was always meant to carry it,
adds **no** new vocabulary, and keeps ranking inside P5.3.

**This is a decision for the owner, not something to do unilaterally.** Until it
lands, every production plan carries a known, quantified ~9% semantic deficit. It
is documented rather than silently absorbed, which is the point.

## 7. Guard rails

| rule | enforcement |
|---|---|
| no new intent vocabulary in P6 | `SHARED_SEMANTIC_ROLES` transcribed from the corpus; a test asserts set equality with the shipped recipes |
| `recipe.intent` not a contract surface | absent from the contract by construction; `test_recipe_intent_is_not_a_contract_surface` |
| no product-specific mapping | directives keyed by `(narrative, presenter, visual)` grammar ids — 9 rows cover all 10 products |
| P5.3 scoring untouched | no edit to `p5_3/`; `git status` confirms |
| no hardcoded score inflation | the contract supplies inputs only; weights unchanged in `library.rank_candidates` |
