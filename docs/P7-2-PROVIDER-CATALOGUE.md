# P7.2 — Provider Fact Materialization

**Status: PASS.** The producer side of `ProviderDecision` now exists. P7.1 closed the
consumer's guessing; P7.2 supplies the facts it was refusing to invent.

## The gap P7.2 closed

P7.1 ended with a chain that had a hole in the middle:

```
ProviderDecision schema   ✓  facts declared, typed, fail-closed
        |
        X                  ✗  nothing produced them
        |
Provider evaluator
```

Every real decision therefore reported `UNRESOLVED` and blocked under `LOCAL_ONLY`
and `LICENSED_ONLY`. Safe, and unusable — the definition of a fail-closed system with
no fact producer.

P7.2 closes it:

```
ProviderCatalogue  ──facts──▶  evaluate_provider_policy()  ──▶  ProviderDecision
```

## Why a catalogue had to be built

There was no provider metadata authority. The two registries that existed carry
*limits and configuration*, not *identity*:

| Registry | Count | Carries |
|---|---|---|
| `hevi.video.capability_guard.PROVIDER_LIMITS` | 14 video generators | modes, resolution, duration, fps |
| `hevi.provider_policy.runtime.PROVIDER_SPECS` | 8 infra providers | health path, env, endpoint |

Neither says where anything runs. And provider names are useless as a substitute —
of the 14 generators, **5** carry any locality hint and **9** carry none:

```
name hints locality (5)   wan_local  ltx2_local  h3_local  wan_cloud  ltx2_cloud
name hints nothing (9)    manim  veo3  kling_v2  hailuo  happyhorse_1_1
                          wan_2_7  happyhorse_1_1_maas  …_maas_lock  wan_2_7_maas
```

A name-based rule leaves two thirds of the fleet undecidable. This is the concrete
cost of the inference P7.1 deleted, measured rather than asserted.

## `hevi/providers/facts.py` — the sole fact source

`ProviderProfile` holds declared facts and performs **no derivation**:

```python
ProviderProfile(
    provider_id="wan_local",
    kind=ProviderKind.VIDEO,
    locality=ProviderLocality.LOCAL,          # runs on your hardware
    license_class=ProviderLicenseClass.GENERATED,
    capability_state=ProviderCapabilityState.AVAILABLE,
    capabilities=("t2v", "i2v"),
)
```

`ProviderCatalogue` is lookup only — no scoring, no ranking, no derivation. Those
belong to `hevi.provider_policy`.

### Three enums moved here

`ProviderLocality`, `ProviderLicenseClass` and `ProviderCapabilityState` moved from
`hevi/provider_policy/policy.py` to the module that produces them.
`policy.py` **re-exports** them, so the import path P7.1 introduced is unchanged.

Placement was forced by import direction: the catalogue must not import the policy
that consumes it, so the shared enums had to move to a leaf. `facts.py` imports
nothing from `hevi`.

## Acceptance criteria

### 1. The evaluator does not guess — verified two ways

The spec's worked example, run end to end:

```
catalogue: acme.internal-image  locality=LOCAL  license=LICENSED

evaluate()  ─▶ locality={'acme.internal-image': LOCAL}
               license_class={'acme.internal-image': LICENSED}

LOCAL_ONLY     ─▶ allowed=('acme.internal-image',)
LICENSED_ONLY  ─▶ allowed=('acme.internal-image',)
```

Absence closes the loop:

```
catalogue has no such provider
  ─▶ UNRESOLVED  ─▶ BLOCKED      (and the known LOCAL peer is still allowed)
```

Enforced by AST inspection, not by convention: `test_no_source_under_test_contains_a_name_based_locality_guess`
walks every call to `startswith` / `endswith` / `split` / `partition` in both files and
fails if any argument names a locality token. `test_locality_is_independent_of_the_name`
declares a provider *named* `local-looking-remote-vp` as `REMOTE` and confirms
`LOCAL_ONLY` refuses it.

### 2. The catalogue is the single fact source

`evaluate_provider_policy(..., catalogue=...)` accepts an injected source, and the
module-level `PROVIDER_CATALOGUE` is the default — one authority, one construction
path. `test_evaluator_defines_no_asset_or_execution_state` asserts the policy module
defines no `AssetDecision`, `RunState` or `ExecutionReceipt`.

### 3. Closure tests

`tests/test_p7_2_provider_fact_emission.py` — 25 tests, including the two spec
scenarios above, full-fleet fact coverage, invalid-profile rejection, and the
"absence is observable" property.

### 4. Boundary held

`evaluate_provider_policy` returns a `ProviderDecision` and nothing else. It produces
no `AssetDecision`, no `ACCEPTED` state, no `RunState`, no receipt.

## Two findings made while building this

### A. `PROVIDER_LIMITS` was a de facto fourth provider registry — video-only

Candidate validation read:

```python
if limits is None:
    reasons.append("unknown_provider")
```

so `PROVIDER_LIMITS` — a *limits* table — was deciding which providers *exist*.
Being video-only, it made every non-video provider unselectable: a local stock image
provider could not be evaluated at all. P7 supports `MediaType.IMAGE`, but the
evaluator had no route to it.

Fixed minimally:

```python
if limits is None and not facts_source.has(provider_id):
    reasons.append("unknown_provider")
```

A provider exists if the catalogue declares it **or** the limits table describes it.
Typos are still rejected — a candidate in neither source is unknown. No existing
rejection changed behaviour.

### B. `LOCAL_ONLY` is satisfiable only if a local provider survives provider policy

Worth stating plainly, because it looks like a bug and is not:

```
quality_floor=9  eligible=['veo3']                LOCAL_ONLY allowed=()      ← wan_local rejected: quality_below_floor:9
quality_floor=7  eligible=[ltx2_local,wan_local,veo3]  LOCAL_ONLY allowed=('ltx2_local','wan_local')
```

Provider policy decides *eligibility*; P7 decides *terms*. P7 will not allow a
provider the policy rejected. With the default floor of 9, the local runtimes score
below it, so `LOCAL_ONLY` blocks — correctly. Loosening the floor is a policy
decision, not a fact-plumbing defect.

## Design decision worth flagging

The spec's `catalog missing locality => UNRESOLVED` is implemented as **absence, not a
null field**: `ProviderProfile` requires `locality`, so a half-declared provider cannot
be constructed at all.

```python
ProviderProfile("x", ProviderKind.IMAGE)   # TypeError: locality required
```

Absence of a provider from the catalogue yields empty fact maps, which is what makes
`UNRESOLVED` reachable. This is strictly stronger than a nullable field — you cannot
declare a provider that is half-known — but it does reach the spec's outcome by a
different route, so it is called out rather than assumed.

## Verification

| Check | Result |
|---|---|
| Ruff — `facts.py`, `provider_policy/`, `p7/`, P7 tests | PASS |
| Mypy — 10 source files | PASS, 0 errors |
| P7 total | **188 passed** (P7.0 114 · P7.1 49 · P7.2 25) |
| P6 | 1278 passed |
| P5.1 / P5.3 / P5.4 | 293 / 298 / 7 passed |
| P1 / P2 / P4 | pass |
| P5.2 | 305 passed, 23 skipped, **2 failed — pre-existing** |
| provider/nlp | 380 passed, 1 skipped |

The 2 P5.2 failures are `capcut-cli binary not found`, unrelated to this work.
Confirmed by stashing `policy.py` back to `HEAD` and reproducing both failures
identically. `capcut-cli` is not installed on this machine.

### One strengthened P7.1 test

`test_mutation_provider_layer_fact_fields_removed_must_fail` asserted the enums were
defined in `policy.py`. P7.1's guarantee still holds — the definition moved. Rather
than re-point the path, the test now asserts the **stronger** property: each fact enum
is defined in exactly one file across `hevi/`, and that file is `facts.py`. That
directly encodes "the catalogue is the sole fact source" and fails if a second
definition ever appears.

## The declared fleet

Every entry the catalogue holds. `locality` is asserted from what the provider *is*;
`license_class` from what it yields.

| provider | kind | locality | license_class | capability_state |
|---|---|---|---|---|
| `h3_local` | video | LOCAL | GENERATED | AVAILABLE |
| `hailuo` | video | REMOTE | GENERATED | AVAILABLE |
| `happyhorse_1_1` | video | REMOTE | GENERATED | AVAILABLE |
| `happyhorse_1_1_maas` | video | REMOTE | GENERATED | AVAILABLE |
| `happyhorse_1_1_maas_lock` | video | REMOTE | GENERATED | NOT_ADOPTED |
| `hyperframes` | video | LOCAL | GENERATED | AVAILABLE |
| `kling_v2` | video | REMOTE | GENERATED | AVAILABLE |
| `longcat` | llm | REMOTE | LICENSED | AVAILABLE |
| `ltx2_cloud` | video | REMOTE | GENERATED | AVAILABLE |
| `ltx2_local` | video | LOCAL | GENERATED | AVAILABLE |
| `manim` | video | LOCAL | GENERATED | AVAILABLE |
| `remotion` | video | LOCAL | GENERATED | AVAILABLE |
| `veo3` | video | REMOTE | GENERATED | AVAILABLE |
| `voicebox` | audio | LOCAL | LICENSED | AVAILABLE |
| `wan_2_7` | video | REMOTE | GENERATED | AVAILABLE |
| `wan_2_7_maas` | video | REMOTE | GENERATED | AVAILABLE |
| `wan_cloud` | video | REMOTE | GENERATED | AVAILABLE |
| `wan_local` | video | LOCAL | GENERATED | AVAILABLE |
| `h3_local` | video | LOCAL | GENERATED | AVAILABLE |
| `hailuo` | video | REMOTE | GENERATED | AVAILABLE |
| `happyhorse_1_1` | video | REMOTE | GENERATED | AVAILABLE |
| `happyhorse_1_1_maas` | video | REMOTE | GENERATED | AVAILABLE |
| `happyhorse_1_1_maas_lock` | video | REMOTE | GENERATED | NOT_ADOPTED |
| `kling_v2` | video | REMOTE | GENERATED | AVAILABLE |
| `longcat` | llm | REMOTE | LICENSED | AVAILABLE |
| `ltx2_cloud` | video | REMOTE | GENERATED | AVAILABLE |
| `ltx2_local` | video | LOCAL | GENERATED | AVAILABLE |
| `manim` | video | LOCAL | GENERATED | AVAILABLE |
| `veo3` | video | REMOTE | GENERATED | AVAILABLE |
| `voicebox` | audio | LOCAL | LICENSED | AVAILABLE |
| `wan_2_7` | video | REMOTE | GENERATED | AVAILABLE |
| `wan_2_7_maas` | video | REMOTE | GENERATED | AVAILABLE |
| `wan_cloud` | video | REMOTE | GENERATED | AVAILABLE |
| `wan_local` | video | LOCAL | GENERATED | AVAILABLE |

Local providers: `h3_local`, `hyperframes`, `ltx2_local`, `manim`, `remotion`,
`voicebox`, `wan_local`.
Remote providers: the remaining 11. `happyhorse_1_1_maas_lock` is the single entry
declared `NOT_ADOPTED` — it exists and is reachable, but is not for general routing.
Before P7.2, "we chose not to use this" and "we cannot use this" were indistinguishable
to any consumer that did not parse a report.

## Declared fact is not verified external truth

**This catalogue states what HEVI believes about each provider. It is not a
verification that the belief is true.**

Nothing here was probed. No endpoint was contacted, no licence was read, no
capability was exercised. Each entry is a *declaration* made from knowledge of what the
provider is — a self-hosted diffusion runtime runs locally, a hosted endpoint does not —
and those declarations are the best available input to policy, not proof.

The distinction is load-bearing:

```
declared fact   !=   verified external truth
ProviderProfile      ProviderVerification
```

A declared fact can be wrong and HEVI will act on it confidently. That is acceptable
for routing — a wrong locality costs a policy decision — and **not** acceptable for
compliance. `LICENSED_ONLY` is the policy that would be wrong: a mislabelled
`license_class` silently admits unlicensed material into a licensed-only pipeline.

The future extension is `ProviderVerification` — an external probe that checks a
catalogue entry against the live provider and reports disagreement. It is named here
and **not implemented**; P7.3 documents the contract, P7 does not build it. Two tests
assert it stays unimplemented (`test_verification_is_named_but_not_implemented`).

Until that exists, every entry in the table above deserves confirmation from whoever
owns that integration before it is trusted for a compliance decision.

## Remaining

- Real render qualification remains blocked: no provider credentials, CUDA unavailable.
- `ProviderVerification` is documented, not built (see above).

## Remaining from P7.2, now closed by P7.3

- ~~`docs/P7-0-ASSET-CONTRACT.md` is stale~~ — rewritten in P7.3 against the current
  `MediaType` contract.


---

## Amendment (P9.1.c) — the fleet grew from 16 to 18

The P7.3 contract freeze recorded `assert PROVIDER_CATALOGUE.stats()["providers"] == 16`
and a doc-completeness test requiring every catalogue member to appear here. Both
correctly **failed** when two providers were added, which is the freeze working as
designed: growing the fleet is a contract change, not a no-op.

| provider | added because | declared | qualified |
|---|---|---|---|
| `remotion` | audit R2 — a renderer invocable by ~60 modules with no catalogue identity | LOCAL, GENERATED | **yes**, P9.1.c |
| `hyperframes` | audit R3 — `hevi/qualification/framework.py` named it as a render runtime but it had no identity | LOCAL, GENERATED | **no** |

`hyperframes` is declared but **not qualified**. Its existence in
`hevi/providers/hyperframes/` is verified; its rendering has not been exercised. A
declaration is not a qualification, and the difference is recorded rather than blurred.

`wan_cloud` remains unobserved (GAP-001 residual) and `hypermotion` is **not
registered** — no implementation, package or script exists, so there is nothing to
declare.


---

## Amendment (P9.1.d) — 18 -> 20 providers

| provider | kind | locality | license | runtime_class | qualified |
|---|---|---|---|---|---|
| `ffmpeg` | encoder | LOCAL | LICENSED | cli | no |
| `html_gsap` | renderer | LOCAL | GENERATED | local_process | no |
| `hyperframes` | video | LOCAL | GENERATED | local_process | no |
| `remotion` | video | LOCAL | GENERATED | local_process | **yes**, P9.1.c |

`ffmpeg` is an **ENCODER** over **CLI**, with `text_to_video` and `image_generation`
explicitly excluded so widening it is visible. `html_gsap` and `hyperframes` are
renderers over **LOCAL_PROCESS**, declared but **not qualified**.

`ProviderKind` gained `GENERATOR`, `RENDERER` and `ENCODER`; `ProviderProfile` gained
`runtime_class` and `artifact_contract`, both defaulting so no existing profile needed a
rewrite. An `ArtifactContract` declares output *shape*, never validity.
