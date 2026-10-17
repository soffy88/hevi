# HEVI P6.5.3 — Semantic Match Contract Repair

> **Closes G-13.** P6.6 is unblocked.
> One behavioural line changed in P5.3. Weights, ranking and recipe identities untouched.

---

## 1. The change

`hevi/production/p5_3/retrieval.py::_semantic_match`, one term:

```python
# before
if beat.intent_id and beat.intent_id == recipe.intent:
    score += 0.3

# after
if beat.intent_id and beat.intent_id in recipe.semantic_roles:
    score += 0.3
```

And the other half, in P6.4's `visual_beat_for()`:

```python
intent_id=intent.semantic_role()   # was: intent.qualified_id
```

`beat.intent_id` now carries the P6.5.1 contract's `semantic_id` — a P5.3
`semantic_role`. `recipe.semantic_roles` is a vocabulary P5.3 already used to
score `motion_purpose`, so this reuses an existing surface rather than adding one.

## 2. Why it works

`recipe.intent` is a **recipe instance label**: 77 distinct values across 80
recipes, nearly all singletons. Nothing above P5.3 could name one without naming a
specific recipe, so the term scored 0 for every caller.

`recipe.semantic_roles` is a **layer vocabulary**: 11 values, every recipe carrying
at least one. That is the vocabulary a directing layer can legitimately speak.

## 3. Measured, on the real corpus

| | before | after |
|---|---|---|
| recipes the 0.30 term can reach | **0 / 80** | **1–23 / 80** depending on role |
| `semantic_match` ceiling | 0.70 | **1.00** |
| gain on a matching recipe | — | **+0.30 exactly** |
| `selection_score` gain end-to-end | — | **+0.09 exactly** (0.30 weight × 0.30 term) |

All 11 contract roles now reach the term:

| role | recipes matched |
|---|---|
| `EVIDENCE_DOMINANT` | 23 |
| `EMOTIONAL_PRESENCE` | 20 |
| `REVEAL` | 8 |
| `DIRECT_ADDRESS` / `EXPLAIN` / `DETAIL` | 7 each |
| `COMPARE_CONTRAST` / `FOLLOW` / `ESTABLISH` | 4 each |
| `TRANSITION` | 3 |
| `DEVELOPMENT` | 1 |

## 4. What did not change

| | |
|---|---|
| weights | `semantic` 0.30, `variety` 0.05, and the rest — all pinned by test |
| ranking | still `RecipeLibrary.rank_candidates` in P5.3 |
| recipe ids | none added, renamed or removed; corpus is byte-identical |
| `recipe.intent` values | untouched — still 77, still a label set |
| scoring engines | exactly one `_semantic_match` in the whole repo |
| P6 authority | P6 supplies an input. It selects no recipe, ranks nothing, recommends nothing |

`test_recipe_ids_were_not_modified` and `test_recipe_identities_are_untouched_by_the_repair`
hold the corpus fixed; `test_no_second_scoring_engine` walks all of `hevi/` for a
second implementation.

## 5. Verification before touching the code

I measured the blast radius first rather than assuming it. A hard swap was applied
to a scratch copy and the full P5.3/P5.4 selection run: **exactly one failure**, and
it was my own audit tripwire. Repeating twice confirmed it, and the one unrelated
failure that appeared on the first run (`test_e2e_f_variety`) reproduced on neither
the swapped nor the original code in four subsequent runs — a pre-existing flake on a
`@pytest.mark.slow` test. `EVOKE_EMOTION`, the intent that test supplies, matches
neither a recipe intent nor a semantic role, so the swap is provably score-neutral
for it.

This mattered: several existing P5.3 tests pass `intent_id="ESTABLISH_SUBJECT"`, a
real recipe label. Under a hard swap those beats would lose 0.30 — a silent
behaviour change to callers I was not asked to migrate. I kept the swap because it
is correct, and verified no shipped test depends on the old path.

## 6. A regression I introduced and fixed

Wiring the contract into `beat.intent_id` without a fallback made an unregistered
grammar shape **raise** instead of degrade. `beat_role()`, `motion_purpose()` and
`narrative_phase()` all fall back to the legacy table when the contract has no row;
the new path did not, so `short_form + product_presentation + commercial_clean`
stopped compiling. Caught by `test_integration_binds_every_builtin_grammar_that_fits`
— an existing P6.4 test, not a new one — and fixed by adding
`VisualIntent.semantic_role()` with the same graceful degradation.

## 7. One audit test was deliberately inverted

`test_audit_semantic_match_caps_at_070` asserted the *defect*: that 0.70 was the
ceiling. It was written as a tripwire so that anyone repairing this would trip it
and be forced to update the audit. That is exactly what happened — I flipped it, and
the assertion it replaced is preserved as the negative case
(`test_audit_non_contract_value_cannot_reach_the_intent_term`): a value outside the
shared vocabulary still scores 0, so the term discriminates rather than merely
permits.

## 8. Behaviour change for existing callers

A beat whose `intent_id` names a legacy recipe label (`"ESTABLISH_SUBJECT"`) now
scores 0 on that term instead of 0.30. That is intended — those callers were asking
the label question, and the label is no longer the contract. No shipped test
changes its selected recipe. Any out-of-tree caller doing this should switch to a
`semantic_role`.

## 9. Gate

```
SEMANTIC_SCORE_REACHABLE=PASS        0/80 -> 1-23/80, ceiling 0.70 -> 1.00
NO_SECOND_INTENT_AUTHORITY=PASS      one _semantic_match in the repo
NO_RECIPE_AUTHORITY_IN_P6=PASS       no recipe id appears in any P6 module
NO_PRODUCT_MAPPING=PASS              no product label in matcher, contract or policy
REGRESSION=PASS                      P5.1 293, P5.2 330, P5.3+P5.4 300, P1-P4 330
```

New suite: `tests/test_p6_5_3_semantic_match_contract.py` — 32 tests, including the
four required ones and a check that a hypothetical new role scores nothing until
the contract names it.

P6 total: **1124 passed** (P6.0–P6.5.3).

## 10. P6.6 is unblocked

```
ProductProfile → NarrativeGrammar → PresenterGrammar → VisualGrammar
  → SemanticContract → P5.3 retrieval → RecipeSelectionEvidence
  → ShotPlan (P0/P1 authority) → Render
```

The known semantic scoring gap is closed and measured. P6.6 no longer inherits a
known-broken scoring term.

**Carried forward, unchanged:** P6.5.2's `flexible_channels` advisories are carried
but not yet consumed by any renderer; `EditingLanguage` and `CameraLanguage` remain
the only invented vocabularies; and 4 of the 6 coherent style×grammar pairs are
still unexercised by the ten shipping products, which is a catalogue question
rather than a model defect.
