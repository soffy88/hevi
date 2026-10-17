# P8.1.5 — Provider Runtime Coverage

**Status: PASS.** Observation coverage extended from 2 of 16 catalogue providers to
15 of 16, without creating a second provider identity or a second probe.

## Scope discipline

This phase adds coverage, not authority. It is easy to fill a coverage table and end
up restating what providers *are* — the table already lists every provider id, so a
`locality` column beside it feels harmless. That would be a second fact source, which
is the fork P7.3 closed and P8.1 was built to avoid.

```
hevi/providers/facts.py        ProviderProfile    what a provider IS      (untouched)
hevi/providers/runtime_specs.py ProviderRuntimeSpec how to OBSERVE it      (new)
hevi/provider_policy/runtime.py PROVIDER_SPECS     how infrastructure is observed (untouched)
hevi/runtime/provider/         observation         what happened          (untouched)
```

`hevi/providers/facts.py`, `hevi/provider_policy/policy.py`, `hevi/production/p7/`
and `hevi/sourcing/` were not modified.

## R1 — identity still comes from the catalogue

```python
ProviderRuntimeSpec(
    provider_id,
    health_check,       # HealthCheckKind
    auth_requirements,  # env var NAMES only
    target,
    notes,
)
```

No `locality`, no `license_class`, no `capabilities`, no `quality`, no `kind`, no
`status` — enforced by `test_runtime_spec_declares_no_provider_fact` across twelve
forbidden names, plus an AST check that the module declares no fact-typed field or
`ProviderProfile` subclass.

Local providers are declared `LOCAL_PROCESS`/`CLI` **because that is how they are
observed**, not because of what they are. Encoding the second would let an observation
override identity — the precise defect `test_local_providers_are_declared_as_local_mechanisms`
guards.

## R2 — coverage is reported, and every gap is explicable

```
TOTAL_CATALOGUE_PROVIDER : 16
OBSERVED                : 15
UNOBSERVED              :  1   ['wan_cloud']
FULL_COVERAGE           : False
```

Coverage is computed across **both** authorities — `PROVIDER_SPECS` and
`RUNTIME_SPECS` — because the P8.1 gap was invisible precisely because nobody added
them up. Unobserved providers are named, never counted away
(`test_every_gap_is_named_and_explained`).

### wan_cloud is left unobserved on purpose

`wan_cloud` has no endpoint and no credential anywhere in the codebase — only a price.
Declaring one would have reached 16/16 and been a lie: the report would claim a
provider is observable when nothing can check it. It stays a gap, and
`test_wan_cloud_gap_is_documented_not_invented` fails if anyone invents it.

## R3 — no provider-id branching

`if provider_id == "veo3"` is forbidden; `RUNTIME_SPECS["veo3"]` is the point. The spec
table *is* data listing providers — that is what a registry is — but control flow may
not branch on an id. Two AST tests enforce this, the stronger one catching any
provider-id string literal inside a `Compare`, `If` or `IfExp`.

`test_spec_ids_come_from_the_catalogue` runs the other direction too: every declared
provider must be a real catalogue member, so the table cannot invent one either.

## R4 — health checks are not unified behind HTTP

```
HealthCheckKind = HTTP | CLI | LOCAL_PROCESS | QUEUE
```

Grounded in how each provider is actually invoked:

| provider | mechanism | kind |
|---|---|---|
| `wan_local` | Wan2GP + CausVid via subprocess | `CLI` |
| `ltx2_local` | no local LTX-2 exists; routes to `wan_local` | `CLI` |
| `h3_local` | loopback service on `127.0.0.1` | `LOCAL_PROCESS` |
| `manim` | in-process library render | `LOCAL_PROCESS` |
| `veo3`, `kling_v2`, `hailuo` | fal.ai queue submission | `QUEUE` |
| `ltx2_cloud` | endpoint from `LTX2_ENDPOINTS` | `QUEUE` |
| `happyhorse_1_1`, `wan_2_7` | WaveSpeed HTTP | `HTTP` |
| `*_maas` | Alibaba Bailian HTTP | `HTTP` |

Forcing these into one HTTP shape would mean probing a subprocess with an HTTP request
and declaring victory based on the wrong mechanism. `test_the_video_fleet_uses_more_than_one_kind`
fails if fewer than three kinds are in use — coverage that looks nominal rather than
real is the failure this prevents.

## R5 — auth stays out of runtime status

`auth_requirements` holds environment variable **names** only, matching
`ProviderSpec.required_env`. Names are configuration; values are secrets.
`__post_init__` refuses any entry that is not an uppercase name, so `"HF_TOKEN=hf_abc123"`
cannot be constructed.

`ProviderRuntimeStatus` still carries no `token`, `endpoint`, `env`, `credential` or
`auth` field, re-asserted against the new registry by
`test_runtime_status_carries_no_auth_material` — which also confirms a declared
credential requirement never reaches a status.

## Acceptance

| check | result |
|---|---|
| `CATALOGUE_COVERAGE_REPORT` | **PASS** — 15/16, gap named and explained |
| `NO_PROVIDER_ID_DUPLICATION` | **PASS** — no branching on ids, all ids are real catalogue members |
| `NO_PROVIDER_FACTS_IN_RUNTIME` | **PASS** — 12 forbidden field names, AST-checked |
| `NO_SECRET_LEAK` | **PASS** — names only; a value fails at construction |
| `NO_SECOND_PROBE_CLIENT` | **PASS** — no HTTP/process client, no probe-like methods |
| Ruff / Mypy | **PASS** / 0 errors |
| tests | **44 passed** |

## Mutation verification

| mutation | outcome |
|---|---|
| spec gains a `locality` field | 3 tests failed |
| branch on `provider_id == "wan_local"` | 2 tests failed |
| import `httpx` | 1 test failed |
| invent a `wan_cloud` spec to fake 16/16 | 1 test failed |
| hardcode `"HF_TOKEN=hf_abc123"` | refused at **import**, `ValueError` |

The last is stronger than a failing assertion: the guard is in `__post_init__`, so a
secret cannot enter the table even transiently.

## Two test defects found while building this

Recorded because both would have produced a false green:

1. **Test pollution.** A mutation test registered a provider into the module-level
   `RUNTIME_SPECS`, so a later test saw a `transient.probe` that did not exist and
   failed. A local registry is used now. This is the same class of bug as P7.3's
   I4 name-matching blind spot: a test that passes for the wrong reason.
2. **Text scan vs AST.** The first "no client" test failed because the module
   docstring says "driven through subprocess" — describing *why* the kind is `CLI`.
   A text scan cannot distinguish describing a mechanism from invoking one, so the
   check is now AST-based over imports and calls.

## Next

P8.2 Asset Acquisition Evidence. `AcquiredSource` must carry a checksum and evidence,
and `source string != evidence` must be representable.

One caveat to carry forward: 15/16 providers are now *declared* observable, but that
is a declaration, not a verification — the same distinction P7.2 recorded for
locality and licence class. Nothing has been probed. `wan_cloud` aside, P8.2 can now
exercise the video fleet structurally, but any claim that a provider actually answers
still requires P8's runtime observation against live credentials.
