# P7 — Frozen Architecture

**Status: FROZEN as of P7.3.** P7.0–P7.2 established the boundary; P7.3 locks it. The
invariants below are enforced by `tests/test_p7_architecture_invariants.py` (29 tests),
which reads the source tree rather than only imported objects — so a boundary cannot be
crossed without a test failing.

Each invariant was written against a failure that actually occurred or was measured,
not against an abstract concern.

## The chain

```
ProductProfile
      |
      v
Narrative / Presenter / VisualStyle / VisualGrammar        P6.1 - P6.4
      |
      v
SemanticContract                                          P6.5.1 - P6.5.3
      |
      v
Unified Runtime (P6) ── intent ──┐
                                  v
                         AssetRequirement                 hevi/production/p7
                                  |
ProviderCatalogue ─▶ ProviderDecision                     hevi/providers/facts.py
      (declared)        │                                 hevi/provider_policy
                        v
                  ProviderPolicy  ->  eligibility
                        │
                        v
                  AssetDecision     ->  terms   (ACCEPTED / BLOCKED / REJECTED)
                        │
                        v
                  [ acquire ]        ->  hevi/sourcing      ← P8, not P7
                        │
                        v
                  [ execute ]        ->  hevi/production/p6
                        │
                        v
                  ExecutionReceipt   ->  the only proof of production
```

P7 adds the vocabulary and the decision record. It acquires nothing and executes
nothing.

## Single owners

| concern | sole owner | never |
|---|---|---|
| asset acquisition, validation, matching | `hevi/sourcing` | a P7 `AssetRepository` / `AssetRegistry` |
| asset semantic role taxonomy | `hevi/sourcing/loader_bridge.py` | a P7 or provider-policy `asset_type` |
| media representation vocabulary | `MediaType` (P7) | reusing a semantic role as a media type |
| provider facts | `ProviderCatalogue` (`hevi/providers/facts.py`) | parsing a provider id |
| provider eligibility | `ProviderPolicy` | policy inventing a fact |
| production proof | `ExecutionReceipt` (P6) | an asset decision claiming `PRODUCED` |

## I1 — Asset semantic authority

`hevi/sourcing` owns the narrative role taxonomy. P7's `AssetSemanticRole` presents it
and `sourcing_key()` is the only route back to the owner's spelling.

```
AssetSemanticRole  ->  sourcing taxonomy
```

Forbidden: `asset_role.py` in P7, `asset_type.py` in provider policy, or any second
vocabulary that restates the five roles.
Locked by `test_i1_asset_semantic_role_has_exactly_one_definition`.

**Prevented:** two role taxonomies drifting apart, so an asset sourced as `character`
silently fails to match a requirement for `CHARACTER`.

## I2 — Media representation authority

`MediaType` is the only representation vocabulary, and it is **disjoint** from
`AssetSemanticRole`:

```
MediaType.values() ∩ AssetSemanticRole.values() = empty
```

Locked by `test_i2_media_type_and_semantic_role_are_disjoint`.

**Prevented:** the P6.5.2 collapse — two layers each owning one vocabulary and
demanding identity, which flattened a compatibility matrix to a diagonal.

## I3 — Provider fact authority

```
ProviderCatalogue  ->  ProviderDecision
```

Facts are **declared**, never inferred. `provider_id` parsing, vendor-name inference
and string-prefix inference are all forbidden in the evaluator, the catalogue, the P7
adapter and P7's asset policy.

Locked by `test_i3_no_name_based_fact_inference`, which walks the AST of all four
files for `startswith` / `endswith` / `split` / `partition` / regex calls against
locality tokens, and by `test_i3_catalogue_is_the_only_fact_source`.

**Prevented, measurably:** a provider named `local-cache` but running remotely was
**allowed** under `LOCAL_ONLY`. And of the 14 selectable generators, **9 have no
locality hint in their name at all** — so no name rule could have been correct.

## I4 — Policy authority

`ProviderPolicy` computes `facts + requirements = eligibility`. It may not *create* a
fact: `if provider.locality == LOCAL: license = GENERATED` must not exist, and the
policy may not write to the catalogue.

Locked by `test_i4_policy_creates_no_provider_fact` and
`test_i4_policy_cannot_mutate_the_catalogue`.

**Prevented:** the second form of the same leak — locality was being used to infer
licence class, so fixing only locality would have left half the hole open.

## I5 — Execution authority

Only `ExecutionReceipt` establishes that production happened.

```
AssetDecisionState ∩ RunState = empty
```

Asset states: `REQUESTED`, `EVALUATED`, `ACCEPTED`, `BLOCKED`, `REJECTED`.
Execution states: `PRODUCED`, `FAILED`, `EXECUTING`, `CANCELLED`, `QA_PASS`, `QA_FAIL` —
and they appear in no P7 code, only in P7 prose explaining that they are not P7's.

`RunState.PRODUCED` has **exactly one** construction site in the package, and it
requires a real receipt. Locked by
`test_i5_produced_has_exactly_one_construction_site`.

**Prevented:** a decision that never touched a renderer asserting that a generation
outcome occurred.

## I6 — P7 adapter purity

`hevi/sourcing/p7_adapter.py` may only look up, map, compose and validate.

```
loops            0
try/except       0
conditionals     guards on lookups only
```

No ranking, selection, quality scoring, provider decision, discovery or generation.
Locked by `test_i6_adapter_has_no_loop`, `test_i6_adapter_has_no_try`,
`test_i6_adapter_scores_and_ranks_nothing`.

**Prevented:** the adapter quietly becoming a second selection authority.

## These invariants have teeth

Each was verified by mutation — the violation introduced, the suite observed to fail,
the code restored:

| mutation | result |
|---|---|
| reintroduce `provider_id.startswith("local")` in the evaluator | **1 failed** |
| give the adapter a ranking loop | **2 failed** |
| add a second `RunState.PRODUCED` construction site | **1 failed** |

An invariant test that cannot fail documents an intention rather than enforcing a
boundary.

## The boundary P7 does not cross

P7 records decisions. It does not acquire assets, execute providers, or assert that
anything was produced. P8 — real production qualification — verifies that the chain
above works against live providers, without changing any authority established here.
