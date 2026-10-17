# HEVI P7.1 — Provider Fact Authority

> Closes the two boundary leaks found in the P7.0 audit.
> `LOCALITY_AUTHORITY=PASS · NO_PROVIDER_ID_PARSING=PASS · ASSET_EXECUTION_BOUNDARY=PASS`

---

## 1. The leak that was found

The P7.0 audit probed the locality rule and found it inferred a fact from a name:

```python
def _is_local(provider_id): return provider_id.startswith("local")
```

| provider id | was it? | P7.0 verdict |
|---|---|---|
| `local.generate` | local | allowed |
| `acme.internal-image` | local (your hardware) | **blocked** |
| `edge.cluster.render` | local | **blocked** |
| `local-voice.run` | remote | allowed |
| `local-cache` | remote | allowed |

Two of those were wrong in both directions, and the direction that *mattered* was
the permissive one: a remote provider named `local-cache` was treated as local and
**allowed** under `LOCAL_ONLY`.

The deeper problem is the one this phase addresses. Prefix parsing makes a naming
convention into an implicit authority. It rots the first time somebody names a
local provider `acme.internal-image`.

## 2. The principle

> An authority provides facts; a consumer must never guess them from a name.

## 3. What changed — facts at the authority

`ProviderDecision` (in `hevi/provider_policy/policy.py`, the sole provider
*policy* authority) gains three
structured, typed facts on `ProviderDecision`:

```python
class ProviderLocality(StrEnum):      LOCAL, REMOTE
class ProviderLicenseClass(StrEnum):  LICENSED, GENERATED, UNKNOWN
class ProviderCapabilityState(StrEnum): AVAILABLE, BLOCKED, FAILED, NOT_ADOPTED

class ProviderDecision(BaseModel):
    ...
    locality:         dict[str, ProviderLocality]        = {}
    license_class:    dict[str, ProviderLicenseClass]    = {}
    capability_states: dict[str, ProviderCapabilityState] = {}
```

All three default to empty, so every existing construction site and every existing
test keeps working — verified: 355 provider/nlp tests still pass.

`ProviderCapabilityState` also fixes a smaller gap: `NOT_ADOPTED` previously
existed only as a key in diagnostic output, so "not used" and "not usable" were
indistinguishable to any consumer that did not parse a report.

## 4. What changed — P7 reads facts

`asset_policy._is_local()` is **deleted**. In its place:

```python
def _locality_of(decision, provider_id) -> str:
    declared = decision.locality.get(provider_id)
    return declared.value if declared is not None else "UNRESOLVED"
```

Same for licence class. The distinction the audit asked for now holds:

| provider id | declared fact | LOCAL_ONLY verdict |
|---|---|---|
| `local.generate` | LOCAL | allowed |
| `acme.internal-image` | LOCAL | **allowed** (was blocked) |
| `edge.cluster.render` | LOCAL | **allowed** (was blocked) |
| `local-voice.run` | REMOTE | **blocked** |
| `local-cache` | REMOTE | **blocked** (was allowed) |
| `mystery.provider` | *undeclared* | **blocked** — `UNRESOLVED` |

An absent fact is genuinely unknown. P7 reports `UNRESOLVED` and fails closed — it
does not fall back to reading the id.

## 5. The same leak existed twice, so both were fixed

`LICENSED_ONLY` inferred licensing from locality: "local ⇒ unlicensed". That is the
same defect — a fact guessed from a name — and fixing only locality would have left
half the leak in place. Licence class is now its own declared fact:

| provider | locality | licence | LICENSED_ONLY |
|---|---|---|---|
| `pexels.stock` | REMOTE | LICENSED | allowed |
| `local.generate` | LOCAL | GENERATED | blocked |
| `acme.internal-image` | LOCAL | **LICENSED** | **allowed** (was blocked) |

A local pipeline can serve licensed material. Only a declared licence class can
answer that.

## 6. Asset lifecycle, and the execution boundary

```
REQUESTED → EVALUATED → ACCEPTED | BLOCKED | REJECTED
```

`AssetDecisionState` gained the two progression states, so a decision records its
own position, not only its outcome. Both refuse to carry a source, a provider
decision or evidence — a provisional decision cannot assert work not done.

**What the asset plane deliberately does not own** — asserted as a set disjointness,
not a comment:

```
AssetDecisionState ∩ RunState = {}          (verified: EMPTY)
```

`PRODUCED`, `FAILED`, `QA_PASSED`, `BLOCKED_BY_PROVIDER`, `EXECUTING`,
`CANCELLED` belong to the execution layer. If the asset plane could say "produced",
a generation outcome would be assertable from a decision that never touched a
renderer — the execution authority would have leaked back in. An `ACCEPTED` asset
decision is an *input* to production; the proof of production is P6.6's
`ExecutionReceipt`.

Statically, exactly **one** site constructs `RunState.PRODUCED`, and it passes a
real receipt.

## 7. Behaviour change — read this if you call `evaluate_policy`

**A `ProviderDecision` that declares no locality now fails closed under
`LOCAL_ONLY`.** Before, it was judged by its id's spelling. Three P7.0 tests encoded
the old behaviour and were updated to declare facts; that is the intended contract,
not a regression. Any caller outside this repo that relied on the inference must
now declare `locality`.

## 8. Guard coverage

| gate | method | result |
|---|---|---|
| `LOCALITY_AUTHORITY` | 6-case name/fact matrix, both directions | PASS |
| locality undeclared | fails closed with `UNRESOLVED` | PASS |
| licence undeclared | fails closed with `UNRESOLVED` | PASS |
| `NO_PROVIDER_ID_PARSING` | AST: no `startswith`/`split`/index on provider ids in P7 policy | PASS |
| `NO_LOCALITY_IN_P7` | no `*Locality` class defined in P7 | PASS |
| `ASSET_EXECUTION_BOUNDARY` | state sets disjoint; no receipt field on a decision | PASS |
| single receipt choke point | AST over `production_runtime.py` | PASS |
| structured facts typed | pydantic field annotations are `dict[str, Enum]` | PASS |
| backward compatible | all facts default empty | PASS |

Nine mutation tests, including reinstating `startswith("local")`, guessing locality
when undeclared, guessing licence from locality, and adding `PRODUCED` to the asset
plane.

## 9. Test counts

| suite | tests |
|---|---|
| `test_p7_0_asset_contract.py` | 114 |
| `test_p7_1_provider_facts.py` | 49 |
| **total P7** | **163** |

## 10. Regression

| suite | result |
|---|---|
| P6.0–P6.8 | 1277 passed |
| P1 / P2 / P4 | 28 / 11 / 15 |
| P5.1 / P5.2 / P5.3 / P5.4 | 293 / 330 / 298 / 7 |
| provider / nlp (incl. provider_policy) | 355 passed, 1 skipped |
| `hevi/sourcing` | 21 passed |
| RUFF / MYPY | PASS / 0 errors |

## 11. Audit outcome — all four properties hold

| property | verdict |
|---|---|
| new asset type touches only taxonomy | PASS — 3 guard tests, no logic |
| new provider touches only the provider layer | PASS — governed by declared terms |
| new generation flow must pass a receipt | PASS — one site, receipt required |
| adapter stays business-logic-free | PASS — 4 lookup guards, 0 loops, no policy |

The one leak the audit found is closed, and the same defect class was fixed in both
places it occurred. HEVI's asset/provider boundary is now long-term evolvable rather
than merely correct today.

## 12. Not done

`evaluate_provider_policy` does not yet *populate* `locality` / `license_class` /
`capability_states`; the facts are declared on the model and read by P7, but the
evaluator that chooses providers still does not fill them in. Until it does, every
real decision will report `UNRESOLVED` and fail closed under `LOCAL_ONLY` and
`LICENSED_ONLY` — safe, but the two policies are unusable in production until the
evaluator emits the facts. That is the P7.2 entry point, and it is the honest next
step rather than P7.2's render qualification.

---

## 13. P7.3 synchronisation

Two facts about this document were stale after P7.2 and are corrected here.

**The fact enums moved.** `ProviderLocality`, `ProviderLicenseClass` and
`ProviderCapabilityState` were defined in `provider_policy/policy.py` when P7.1 added
them. P7.2 needed a producer for them, so the definitions moved to
`hevi/providers/facts.py` — the module that *declares* facts rather than deciding on
them — and `policy.py` **re-exports** them. The import path this document introduced
in §3 is unchanged:

```python
from hevi.provider_policy.policy import ProviderLocality   # still valid
from hevi.providers.facts import ProviderLocality          # the definition site
```

The P7.1 mutation test that pinned the enums to `policy.py` was not merely re-pointed.
It now asserts the **stronger** property: each fact enum is defined in exactly one
file across `hevi/`, and that file is `facts.py`
(`test_mutation_provider_layer_fact_fields_removed_must_fail`).

**The schema had no producer.** §3 introduced the fields and §4 made consumers read
them, but nothing filled them in — so every real decision reported `UNRESOLVED` and
failed closed. Safe, and unusable. P7.2 closed that; see
`docs/P7-2-PROVIDER-CATALOGUE.md`.

Current shape:

```
ProviderCatalogue (hevi/providers/facts.py)
        |  declared facts
        v
evaluate_provider_policy()  ->  ProviderDecision.locality
                                        .license_class
                                        .capability_states
        |
        v
ProviderPolicy  ->  AssetDecision  ->  P7 asset terms
```

All three families still default to empty, so callers that construct a
`ProviderDecision` by hand are unaffected. The lifecycle in §6 is unchanged.
