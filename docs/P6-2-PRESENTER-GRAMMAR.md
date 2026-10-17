# HEVI P6.2 — Presenter Grammar

> Status: **P6.2 COMPLETE**
> Baseline: `34df92098b548cfaf20fe74f8f410865f0b61506`
> No P0-P5 module modified

---

## 1. Authority ownership

```
ProductProfile
    ↓ narrative_grammar_id
NARRATIVE_GRAMMAR_REGISTRY  → NarrativeCompiler  → NarrativeIntent
    ↓ presenter_grammar_id                            ↓
PRESENTER_GRAMMAR_REGISTRY   → PresenterCompiler     → PresenterIntent
    ↓                                                        ↓
GRAMMAR_COMPATIBILITY_REGISTRY (pairing)                    ↓
                                                    ProductIntent
                                                         ↓
                                          existing runtime boundary (P0–P5)
```

| Concern | Owner | P6.2 role |
|---|---|---|
| Product identity | `ProductProfile` (P6.0) | adds `presenter_grammar_id` reference |
| Who is presented / casting | P5.1 presenter types, P2 profiles | declares *performance shape* only |
| Voice, TTS, provider | `hevi.providers` | names none |
| Camera, shot, motion | P0 / P1 | names none |
| Renderer | `hevi.renderers.base` | names none; requirements are declared as constraints |
| Story structure | P6.1 `NARRATIVE_GRAMMAR_REGISTRY` | **consumes** `NarrativeIntent`, does not recompute |
| Assets, evidence | P5.2 `shot_readiness` | names none |
| QA, verdict | `hevi.verdict`, `hevi.quality` | names none |

`ProductProfile` gains one field — `presenter_grammar_id` — and nothing else. It
selects a presenter shape. It does **not** define node order, presenter logic,
camera logic, render logic or audio logic;
`test_product_selects_presenter_grammar` asserts the profile carries no
`presenter_nodes`, `presenter_logic`, `camera_logic`, `render_logic` or
`audio_logic` attribute.

## 2. Data flow

```
ProductProfile
  .narrative_grammar_id ──→ NARRATIVE_GRAMMAR_REGISTRY ──→ NarrativeCompiler
                                                              ↓
                                                        NarrativeIntent
                                                              ↓
ProductProfile
  .presenter_grammar_id ──→ PRESENTER_GRAMMAR_REGISTRY
                                                              ↓
                                          PresenterCompiler.compile(profile, narrative_intent)
                                                              ↓
                          compatibility check against the narrative it performs
                                                              ↓
                                                        PresenterIntent
```

The narrative is an **input**, not something recomputed. The presenter performs
the narrative that already exists; that ordering is what makes the two grammars
composable instead of competing.

`PresenterIntent` carries `grammar_id`, `ordered_nodes`, `presentation_style`,
and channel-separated `speaker_requirements` / `visual_requirements` /
`audio_requirements`. Requirements are `ProductConstraint` records — declared
needs, never provider or model names.

## 3. Supported grammars

| id | sequence | min nodes | distinctive constraint |
|---|---|---|---|
| `avatar_explainer` | HOOK, IDENTITY, EXPLANATION, DEMONSTRATION, CONCLUSION, CTA | 6 | `identity_required` |
| `documentary_explainer` | HOOK, CONTEXT, EVIDENCE, EXPLANATION, INTERPRETATION, CONCLUSION | 6 | `evidence_before_interpretation` |
| `historical_reconstruction` | HOOK, CONTEXT, CHARACTER, EVENT, EVIDENCE, INTERPRETATION, CONCLUSION | 7 | `reconstruction_disclosure_required` |
| `educational_lecture` | HOOK, AUTHORITY, EXPLANATION, DEMONSTRATION, CONCLUSION, CTA | 6 | `authority_required` |
| `product_presentation` | INTRO, EXPLANATION, EVIDENCE, DEMONSTRATION, CONCLUSION, CTA | 6 | `claim_grounding_required` |

All five are general. No product-named grammar: a product *selects* a presenter,
it does not own one. That covers the ten target forms without ten presenters —
`avatar_explainer` serves avatar explainer, educational video, science explainer,
news analysis, marketing video and short video; `documentary_explainer` serves
documentary explanation and news analysis; `historical_reconstruction` serves
historical reenactment and narrative storytelling.

### Vocabulary note

The spec's Phase 1 node list has 11 types. Its Phase 2/3 grammars also require
`CONTEXT`, `CHARACTER`, `EVENT` and `INTERPRETATION`, which are absent from that
list. Rather than fail those grammars, the enum carries those four as well —
15 types, all general. `CHARACTER` and `EVENT` name *presentation functions* (a
performer becoming a figure; a performer narrating what happened), not products.

`PresenterNodeType` is deliberately **disjoint from `NarrativeNodeType`**: a
narrative node says what the story is doing, a presenter node says what the
presenter is doing while it happens. They overlap only where the function
genuinely coincides (`HOOK`, `EXPLANATION`, `CTA`, `CONCLUSION`).

## 4. Compatibility — the P6.1 gap, closed as data

P6.1 recorded this gap: *"a profile can declare `narrative_grammar` as one shape
and `narrative_grammar_id` as another, and nothing cross-checks them."* P6.2
closes the **presenter** half of it.

`GRAMMAR_COMPATIBILITY_REGISTRY` is a declarative table keyed by narrative
grammar id:

| narrative | permitted presenters |
|---|---|
| `documentary` | `documentary_explainer`, `historical_reconstruction` |
| `explanatory` | `avatar_explainer`, `educational_lecture`, `product_presentation` |
| `story` | `documentary_explainer`, `historical_reconstruction` |
| `short_form` | `avatar_explainer`, `educational_lecture`, `product_presentation` |

So `narrative=documentary` + `presenter=avatar_explainer` raises
`INCOMPATIBLE_GRAMMAR_PAIRING`. The spec's example pairing is permitted; the
incoherent one is refused.

A narrative **absent** from the table permits any registered presenter. That
keeps a newly added narrative usable without a compatibility edit, while the
pairings that actually matter stay constrained.

Why a table and not a check: `if narrative == "documentary" and presenter ==
"avatar"` is precisely the per-product branching the architecture forbids. As
data, adding a pairing is a data change and `test_no_product_presenter_branching`
stays green.

## 5. Forbidden patterns

| Forbidden | Enforced by |
|---|---|
| `if product_type == "P08_COMMERCIAL"` selecting a presenter | `test_no_product_presenter_branching` |
| `{"P08_COMMERCIAL": presenter}` dispatch table | same |
| `COMMERCIAL_HOOK` / `P08_CTA` node types | `test_no_product_specific_presenter_node_type` |
| importing `hevi.renderers` / `hevi.editable` | `test_no_renderer_import`, `test_no_forbidden_import` |
| importing P0–P5 timeline, shot, asset, QA, provider modules | `test_no_forbidden_import` (19 prefixes) |
| redefining `PresenterEntity`, `PresenterPlan`, `AudioLock`, `ProductionProfile`, … | `test_no_second_presenter_authority` (18 types) |
| module-level presenter dict outside the registry | `test_presenter_registry_only_source` |
| returning `[]` for a missing presenter | `test_presenter_never_returns_empty_nodes` |
| falling back to a default presenter | `test_no_fallback_default_presenter` |

## 6. Fail-closed behaviour

| Condition | Error |
|---|---|
| profile declares no presenter | `PRESENTER_GRAMMAR_NOT_FOUND` |
| presenter id not registered | `UNKNOWN_PRESENTER_GRAMMAR` |
| narrative/presenter pairing not permitted | `INCOMPATIBLE_GRAMMAR_PAIRING` |
| required presenter node excluded | `PRESENTER_IDENTITY_REQUIRED_BUT_ABSENT` (etc.) |
| narrative intent did not validate | `NARRATIVE_INTENT_INVALID` |
| grammar has no nodes | `PRESENTER_GRAMMAR_WITHOUT_NODES` |
| two nodes share an `order` | `AMBIGUOUS_PRESENTER_NODE_ORDER` |
| grammar opens on CTA/CONCLUSION/TRANSITION | `INVALID_PRESENTER_OPENING_NODE` |
| every node optional | `PRESENTER_GRAMMAR_WITHOUT_REQUIRED_NODE` |
| node has no `purpose` | `PRESENTER_NODE_WITHOUT_PURPOSE` |
| node type outside the vocabulary | `UNKNOWN_PRESENTER_NODE_TYPE` |

A compiled presenter is **never** an empty list. `test_presenter_never_returns_empty_nodes`
sweeps all 20 narrative×presenter combinations and asserts each either refuses
or returns a non-empty sequence.

## 7. Determinism

Identical input yields a byte-identical `content_hash()` — proven across five
repeated compilations *and* across fresh `PresenterCompiler` instances. Node order
comes from the grammar's declared `order`, which is required to be unique, so
nothing sorts ambiguously. No clock, RNG or environment read.

## 8. Mutation tests

Four defects injected, each caught:

| # | Mutation | Caught by |
|---|---|---|
| 1 | `if product_type.value == "P08_COMMERCIAL"` | `test_no_product_presenter_branching` |
| 2 | `COMMERCIAL_HOOK` added to the enum | `test_no_product_specific_presenter_node_type` |
| 3 | order derived from a call counter | `test_presenter_compiler_deterministic` |
| 4 | `product_presentation` dropped from registration | `test_presenter_registry_holds_required_builtins` |

**Mutation 1 found a real bug in the guard.** The first version inspected only
the top-level operands of a comparison, so `profile.product_type == "P08"` was
caught but `profile.product_type.value == "P08"` — where the product attribute
is nested one level deeper — was not. The guard now walks the full operand
expression trees. This is the reason mutation tests exist: the guard that was
supposed to prevent ten pipelines had a hole in exactly the most natural way to
write one.

## 9. Migration notes

**Additive.** `hevi/production/p6/presenter.py`,
`presenter_registry.py`, `presenter_compiler.py` are new.
`ProductProfile` gains one optional field. `intent.py` gains the presenter stage.
No P0-P5 file is touched; `test_p6_2_does_not_modify_frozen_p0_to_p5_modules`
diffs nine frozen modules.

**Backwards compatible.** `compile_product_intent()` tolerates a profile with no
`presenter_grammar_id`: it compiles narrative only and leaves
`presenter_intent` as `None`. All 157 P6.0 and 107 P6.1 tests pass unchanged.

**Two `PresenterGrammar` types, both legitimate:**

| | P6.0 `schema.PresenterGrammar` | P6.2 `presenter.PresenterGrammar` |
|---|---|---|
| Role | profile-side declaration | registry-side definition |
| Says | "this product uses an avatar presenter" | "here is what an avatar explainer performance is" |
| Cardinality | one per profile | one per grammar, shared |

Merging them would give every product a private presenter engine.
`test_p6_0_presenter_declaration_still_intact` asserts both survive and stay
distinct — the same pattern P6.1 established for narrative.

**Rollback:** remove the three new modules, drop `presenter_grammar_id` from
`schema.py`, and drop the presenter stage from `intent.py`. P6.0 and P6.1 are
unaffected.

## 10. Acceptance

| Gate | Result |
|---|---|
| `P6.2_ARCHITECTURE` | PASS |
| `PRESENTER_SCHEMA` | PASS |
| `PRESENTER_REGISTRY` | PASS |
| `PRESENTER_COMPILER` | PASS |
| `PRODUCT_CONNECTION` | PASS |
| `COMPATIBILITY_CHECK` | PASS |
| `FAIL_CLOSED` | PASS |
| `DETERMINISM` | PASS |
| `NO_SECOND_PIPELINE` | PASS |
| `NO_SECOND_RENDERER` | PASS |
| `NO_SECOND_TIMELINE` | PASS |
| `NO_SECOND_SHOT` | PASS |
| `NO_SECOND_ASSET` | PASS |
| `NO_SECOND_QA` | PASS |
| `NO_PROVIDER_AUTHORITY` | PASS |
| `RUFF` | PASS |
| `MYPY_NEW_ERRORS` | 0 |
| `P6.0` / `P6.1` / `P0–P5` | PASS |
| `SOURCE_MUTATION_SCOPE` | `P6.2_ONLY` |
| `UNRELATED_DIRTY_PRESERVED` | YES |

`TESTS=151` (P6.2) + `157` (P6.0) + `107` (P6.1) = **415 passed, 0 failed**

## 11. Carried forward

| Gap | Owner |
|---|---|
| P6.0's `narrative_grammar` declaration still is not cross-checked against `narrative_grammar_id` — the *narrative* half of the P6.1 gap | P6.3 |
| `P6_0_COMPILER` still raises `COMPILER_NOT_IMPLEMENTED` | P6.3 |
| `profile_refs` unresolved against P2 | P6.3 |
| Compatibility table is keyed by narrative id only; nothing checks the reverse direction (a presenter used under two narratives) | P6.3 |
| `PRODUCT_HERO` unresolvable via P2 registry | P6.8 |
| `P6_0_COMPILER`/`compile_product_intent` remain two compile entry points | P6.3 |
