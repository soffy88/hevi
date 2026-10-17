# P7.0 — The Asset Contract

**Status: FROZEN (P7.3).** Two vocabularies, deliberately separate, and a decision
record that never claims production happened.

> This document was rewritten in P7.3. It previously described `MediaKind` and
> `AssetDecision.selected_asset` — a contract superseded by the P7.0 revision and
> never implemented. The retired names are named here only so a reader who meets
> them elsewhere knows they are dead.

## The two vocabularies

P6 and `hevi.sourcing` could not talk. Sourcing had a **narrative role** taxonomy;
P7 needed a **media representation** taxonomy. Neither was wrong and neither replaces
the other.

| | owns | means | defined in |
|---|---|---|---|
| `MediaType` | representation | what it *is* as delivered | `hevi/production/p7/asset_contract.py` |
| `AssetSemanticRole` | meaning | what it is *for* | derived from `hevi.sourcing` |

### `MediaType` — representation

| member | meaning |
|---|---|
| `IMAGE` | still or moving image, single frame set |
| `VIDEO` | time-ordered frames with audio or without |
| `AUDIO` | sampled sound, speech, music or SFX |
| `MODEL3D` | geometry, meshes, scenes |
| `TEXTURE` | surface maps, normal/roughness/displacement |
| `DOCUMENT` | text, stills of text, diagrams |

New in P7. No representation vocabulary existed anywhere in HEVI before it.

### `AssetSemanticRole` — meaning

| member | meaning |
|---|---|
| `CHARACTER` | a person or being that appears |
| `SCENE` | a place or situation |
| `VOICE` | narration or dialogue as sound |
| `PROP` | a held or featured object |
| `FX` | an effect, transition or overlay |

**Not redefined by P7.** The values are derived from `hevi.sourcing.loader_bridge.ASSET_TYPES`
— the owner. `sourcing_key()` is the only sanctioned route back to the owner's
spelling, so the two cannot drift apart silently.

### Why they must stay apart

A requirement names both, and they never substitute for each other:

```
historical portrait   ->  media_type=IMAGE   semantic_role=CHARACTER
documentary field     ->  media_type=VIDEO   semantic_role=SCENE
narration             ->  media_type=AUDIO   semantic_role=VOICE
```

P6.5.2 collapsed its compatibility matrix to a diagonal because two layers each owned
one vocabulary and demanded identity — a real bug, and the reason this boundary is
now a test (`test_i2_media_type_and_semantic_role_are_disjoint`) rather than a
convention.

## The decision record

### `AssetRequirement` — a declared need

Keyed `media_type` + `semantic_role`, carrying `quantity`, `quality_floor`,
`source_policy` and `constraints`. It states what is needed and never what exists.

### `AssetEvidence` — proof, not assertion

An asset id is a string. Evidence is what makes a claim about it checkable: the
locator, its checksum, and when it was seen. **`source string != evidence`** — a
non-empty URI is a claim, not a proof, and P7 keeps them separate so the difference
is representable.

### `AssetDecision` + `AssetDecisionState` — how a need resolved

```
REQUESTED ──▶ EVALUATED ──▶ ACCEPTED
                          ├▶ BLOCKED     (policy said no, with a reason)
                          └▶ REJECTED
```

The outcome records `selected_source`, the `provider_decision` it was made against,
a `confidence` and the `evidence` relied on. An `ACCEPTED` decision carries both the
source and the evidence that support it; `ACCEPTED` without them is refused.

### Asset lifecycle is not execution lifecycle

`AssetDecisionState` and `RunState` are **disjoint by construction** — verified as set
disjointness, not asserted in a comment. `PRODUCED`, `FAILED`, `EXECUTING`, `QA_PASS`,
`QA_FAIL` and `CANCELLED` exist only in the execution layer.

An `ACCEPTED` asset decision is an **input to production**, never a claim that
production happened. Only an `ExecutionReceipt` can say that. Exactly one code
location constructs `RunState.PRODUCED`, and it requires a real receipt
(`test_i5_produced_has_exactly_one_construction_site`).

## What P7 does not own

P7 adds no second authority for anything:

| concern | owner |
|---|---|
| asset acquisition, validation, matching | `hevi/sourcing` |
| asset semantic role taxonomy | `hevi/sourcing/loader_bridge.py` |
| provider facts | `hevi/providers/facts.py` (`ProviderCatalogue`) |
| provider eligibility | `hevi/provider_policy` |
| production execution and proof | `hevi/production/p6/production_runtime.py` |

No `AssetRegistry`, `AssetRepository`, `AssetProvider` or `AssetValidator` is defined
in P7. `hevi.sourcing.AssetRepository` remains the existing owner.

## The P7 adapter

`hevi/sourcing/p7_adapter.py` is the one place P7 meets sourcing. It is pure
composition — **lookup, mapping, validation** — and nothing else:

```
loops          0      no iteration over candidates, which would be ranking
try/except     0      no failure-handling decision
conditionals   guards only, on lookups
```

It does not rank, score, select, discover or generate. Locked by
`tests/test_p7_architecture_invariants.py` (I6).

## Verification

| check | result |
|---|---|
| P7.0 contract tests | 114 passed |
| invariant tests (I1–I6) | 29 passed |
| contract freeze tests | 30 passed |
| Ruff / Mypy | PASS / 0 errors |

Full P7 baseline: **217 tests** (P7.0 114 · P7.1 49 · P7.2 25 · P7.3 29).
