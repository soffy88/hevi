# HEVI P6.5.1 — Semantic Contract Repair

> Closes the **G-13** structural blocker. P6.6 remains closed.
> Full audit: `docs/SEMANTIC-AUTHORITY-MAP.md`

---

## 1. What was wrong

`beat.intent_id` could never equal `recipe.intent`. Measured, not assumed:

* `recipe.intent` holds **77 distinct values across 80 recipes** — a per-recipe
  description, not a vocabulary.
* P6.4 sets `beat.intent_id` to `"documentary_realism@v1.0.0"`.

So P5.3's 0.30-weight intent term is **structurally unreachable** and
`semantic_match` caps at **0.70** — a permanent ~9% of `selection_score`.

Three vocabularies *are* genuinely shared, and the contract is built on exactly
those: `semantic_roles` (11, the layer vocabulary), `RecipeFamily` (8) and
`beat_roles` (10). `recipe.intent` is excluded by construction.

## 2. What shipped

`hevi/production/semantic_contract.py` — `ProductionSemanticIntent` over the 11
existing roles, plus a `SemanticDirective` bridge, wired into P6.4's
`visual_beat_for()`.

| rule | enforced by |
|---|---|
| invents no new intent vocabulary | module-level names pinned; vocabulary set-equality with the live corpus |
| `recipe.intent` is not a contract surface | absent from the contract; a test excludes all 77 labels |
| no product-specific mapping | directives keyed by `(narrative, presenter, visual)` — 9 rows, 10 products |
| P5.3 scoring untouched | no edit to `p5_3/`; weights asserted unchanged |
| no score inflation | contract contains no reference to `semantic_match` or `selection_score` in code |

### What it fixed

| before | after |
|---|---|
| `narrative_phase` arrived as P1's `DEVELOPMENT` default — by accident | chosen deliberately per grammar shape |
| motion strategy → role was a hard 5→5 table | the contract carries a *set* per shape, resolved deterministically |
| `RESTRAINED_PUSH` and `DELIBERATE_MOVE` both collapsed to `REVEAL` | the collapse is recorded and inspectable |

Real outcome changes: `P07_MARKETING` moved from `EXPLAINER.CONCEPT_BUILD` to
`CAMERA.DETAIL_TO_CONTEXT`; `P09_SHORT_VIDEO` to `CAMERA.STATIC_HOLD`.

### Honest measurement

| | before | after | delta |
|---|---|---|---|
| mean max `semantic_match` | 0.56 | 0.58 | **+0.02** |
| `selection_score` contribution | — | — | **+0.006** |

**This is a small gain and it is capped by the unreachable term.** The contract's
value is structural — explicit shared vocabulary, deliberate phase selection, a
recorded collapse — not numeric. Claiming a large score win here would be false.

## 3. Still open — and it needs your decision

The 0.30 term stays unreachable. Both available routes are forbidden:

* editing P5.3 scoring (out of scope, P5.3 read-only throughout), or
* setting `beat.intent_id` to a recipe intent — recipe selection by label, i.e. a
  second selector, and with 77 singleton intents it would select exactly one.

The fix belongs to P5.3 and is one line in `_semantic_match`:

```python
if beat.intent_id and beat.intent_id in recipe.semantic_roles:
    score += 0.30
```

with P6 setting `beat.intent_id` to a contract `semantic_id`. No new vocabulary,
ranking stays in P5.3. **Not done unilaterally.** Until it lands every plan
carries a known ~9% semantic deficit — now documented rather than silently
absorbed.

## 4. One subtlety worth knowing

`PRESENTER.PRESENTER_PRIMARY` has `intent="DIRECT_ADDRESS"`, which *is* a
`semantic_role`. That label is therefore admissible as a `semantic_id` by
coincidence. The exclusion of `recipe.intent` is a property of the contract's
construction (intents are never consulted), not of the vocabulary — and a test
excludes that one recipe explicitly so the coincidence cannot look like an
admission.

## 5. Gate

```
SEMANTIC_CONTRACT=PASS          NO_SECOND_INTENT_AUTHORITY=PASS
P5_3_SCORE_REACHABLE=PARTIAL    NO_PRODUCT_MAPPING=PASS
REGRESSION=PASS                 (P5.3 292+7, P6.0–P6.5 1032, unchanged)
```

`P5_3_SCORE_REACHABLE` is **PARTIAL** and deliberately reported that way: the
score *path* is verified end to end and 0.70 of 1.00 is reachable, but the 0.30
term needs the P5.3 change above.
