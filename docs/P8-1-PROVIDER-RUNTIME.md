# P8.1 — Provider Runtime Observation

**Status: PASS.** P8 observes whether providers answer. It does not decide what they
are, and it does not decide whether they may be used.

## The three questions, three owners

P7.3 froze a boundary between what a provider *is* and what it may do. P8.1 adds a
third question, and the risk was always that it would quietly become a second answer
to one of the first two.

| question | answer | owner |
|---|---|---|
| what is it? | `ProviderProfile` | `hevi/providers/facts.py` |
| may it be used? | `ProviderDecision` | `hevi/provider_policy` |
| is it answering? | `ProviderRuntimeStatus` | `hevi/runtime/provider` |

```
ProviderCatalogue ─▶ ProviderPolicy ─▶ ProviderDecision ─▶ Runtime Probe
   (facts)            (eligibility)        (terms)            (observation)
```

**The probe runs last, on purpose.** There is no value in asking a provider policy
already excluded — it costs a network round trip to learn something already decided,
and a probe of a rejected provider produces an observation that looks like an
endorsement. Only `ProviderDecision.eligible` is probed
(`test_ineligible_provider_is_never_probed`).

## The model

```python
ProviderRuntimeStatus(
    provider_id,
    availability,     # UNKNOWN | AVAILABLE | UNAVAILABLE
    reachable,        # bool
    latency_ms,       # optional
    checked_at,       # datetime
    failure_reason,   # optional
)
```

Six fields, and no others. Specifically **absent**: `locality`, `license_class`,
`capabilities`, `quality`, `ranking`. Locked by
`test_runtime_status_has_exactly_the_permitted_fields`.

That absence is the whole design. A status carrying `locality` would be a second fact
source, and it would fail in a specific, confusing way: a provider that *timed out*
would start looking remote, and `LOCAL_ONLY` would reject it for the wrong reason —
reporting a policy violation when the network merely hiccuped.

### States are not policy vocabulary

```
RuntimeAvailability:  UNKNOWN | AVAILABLE | UNAVAILABLE
```

Deliberately **not** `ELIGIBLE` / `BLOCKED`. Those answer "may this be used", which is
policy's question. A probe emitting `BLOCKED` is second-guessing eligibility it has
no standing to judge — and makes a network outage look like a policy decision
(`test_runtime_states_are_not_policy_vocabulary`).

`reachable != eligible`, and all four combinations stay distinguishable:

| | reachable | not reachable |
|---|---|---|
| **eligible** | `USABLE` | `UNREACHABLE` |
| **not eligible** | `INELIGIBLE` (never probed) | `INELIGIBLE` (never probed) |

## Fail-closed

Default is `UNKNOWN`, and `UNKNOWN` is not usable. Two distinctions are preserved
rather than flattened:

- **`UNKNOWN` ≠ `UNAVAILABLE`.** "We cannot ask" and "we asked and it did not answer"
  are different facts. A provider with no probe configuration is `UNKNOWN`, never
  `UNAVAILABLE`.
- **Every negative carries a reason.** `UNAVAILABLE` without `failure_reason` is
  refused, so a missing credential is distinguishable from a timeout from a 503.

## Reuse, not duplication

There was already a probe. `hevi/provider_policy/runtime.py` owns
`probe_provider`, `PROVIDER_SPECS` and `_probe_url`, including per-provider endpoint
and credential handling. P8.1 **delegates** to it and defines no HTTP client of its
own — enforced by `test_default_probe_delegates_to_the_existing_probe`, which fails
if `httpx`, `aiohttp` or `urllib` appears in the module.

`PROBEABLE` is *derived* from `PROVIDER_SPECS`, not hand-written
(`test_probeable_set_is_derived_not_declared` fails on any hard-coded provider id).

The mapping layer reads exactly **one** key out of the probe result — `reachable`.
The raw result also carries configuration (endpoints, required env var names); none
of it is copied into an observation, verified by
`test_status_never_carries_configuration`.

## Mutation verification

All five required mutations fail the suite:

| mutation | tests failed |
|---|---|
| runtime model gains `locality` | 3 |
| runtime model gains `license_class` | 3 |
| probe registers into `ProviderCatalogue` | 2 |
| runtime state written into `ProviderDecision.capability_states` | 1 |
| `UNAVAILABLE` treated as usable (bypasses execution) | 3 |

## Finding: the video fleet has no probe configuration

**Only 2 of the 16 catalogue providers are probeable.**

```
probeable          2   longcat, voicebox
not probeable     14   wan_local, ltxx2_local, h3_local, manim, wan_cloud,
                       ltx2_cloud, veo3, kling_v2, hailuo, happyhorse_1_1,
                       wan_2_7, and the three MaaS variants
```

`PROVIDER_SPECS` covers 8 *infrastructure* providers (pexels, mpt, joyai, duix,
longcat, voicebox, pocket_tts, voxcpm) — and 6 of those 8 are **not in the
catalogue at all**, while 14 of the catalogue's 16 are absent from the specs. The two
registries overlap by only 2 entries.

This is a pre-existing structural gap, not something P8.1 introduced, and P8.1
handles it correctly: every unprobeable provider reports `UNKNOWN` and is therefore
never usable. Safe, and not yet useful.

**It does mean P8.2 has nothing to acquire against.** Real acquisition qualification
needs at least one provider that can both be probed and produce an artifact. Closing
this requires either extending `PROVIDER_SPECS` with the video generators' health
endpoints, or accepting that P8.2 qualifies the 2 probeable providers first. That is a
decision about which authority owns "how do I health-check a video generator", and it
belongs to whoever owns `PROVIDER_SPECS` — not to P8.1.

## Verification

| check | result |
|---|---|
| P8.1 tests | **31 passed** |
| P7 (unchanged) | 247 passed |
| P6 | 1278 passed |
| P5.1 / P5.3 / P5.4 / P4 | 293 / 298 / 7 / 33 passed |
| provider/nlp | 420 passed, 1 skipped |
| Ruff / Mypy | PASS / 0 errors (15 files) |

Scope: `hevi/providers/facts.py`, `hevi/provider_policy/` and `hevi/production/p7/`
untouched, as required.

## Next

P8.2 Acquisition Evidence. Per the P8 route, do **not** go to render yet — the order
is fact → observation → execution → proof. `AcquiredSource` must carry a checksum and
evidence, and `source string != evidence` has to be representable.

But read the finding above first: with 2 probeable providers, P8.2 qualifies
infrastructure rather than the video fleet. Worth deciding deliberately.
