# P9.2 — HTTP Provider Qualification

```
credential check -> policy -> runtime -> submit -> poll -> download
                                                   |
                             P8.2 acquisition -> P8.3 receipt -> P8.4 validation
                                                   |
                                               QUALIFIED
```

## Provider matrix

| provider | runtime | credential | attempted | result | evidence_id |
|---|---|---|---|---|---|
| `wan_2_7` (WaveSpeed) | HTTP | `WAVESPEED_API_KEY` | no | `BLOCKED_BY_CREDENTIAL` | — |
| `happyhorse_1_1` (WaveSpeed) | HTTP | `WAVESPEED_API_KEY` | no | `BLOCKED_BY_CREDENTIAL` | — |
| `wan_2_7_maas` (Alibaba) | HTTP | `ALIBABA_MAAS_API_KEY` | no | `BLOCKED_BY_CREDENTIAL` | — |
| `happyhorse_1_1_maas` (Alibaba) | HTTP | `ALIBABA_MAAS_API_KEY` | no | `BLOCKED_BY_CREDENTIAL` | — |

**Zero HTTP attempts were made, so zero artifacts exist.** The `attempted` column is `no`
for all four and every `evidence_id` is empty. Nothing here may be read as a provider
failing — the runner never left the building.

### A credential-collision hazard found while doing this

`hevi/video/alibaba_maas_service.py:28` already warns that Alibaba keys have been
confused with WaveSpeed keys. That is not hypothetical on this machine: the variable
`ALIYUN_MAAS_API_KEY` holds a value with the prefix `sk-ws-`, i.e. WaveSpeed-shaped,
while `WAVESPEED_API_KEY` is unset. `ALIBABA_MAAS_HOST` is absent.

Two names, one ambiguous key, two different hosts. Silently reinterpreting it as a
WaveSpeed credential would send a key to whichever host it does not belong to and then
report the resulting 401 as "invalid credential" — a conclusion that looks like a finding
and is really a misrouted secret. **Unresolved: needs a human to say which provider that
key is for.** Until then nothing attempts it.

The live tests in `tests/test_p9_2_live_http.py` are gated behind `HEVI_HTTP_LIVE=1`
because they call paid APIs. A default `pytest` run must never bill a provider.

## Two real defects this phase found

**1. An empty check tuple validates nothing.** `qualify_local_provider` forwards
`checks` to P8.4's `qualify()`, which treats an empty tuple as "nothing to disprove".
The HTTP runner initially forwarded `()`, so a download of `b"this is not a video" * 64`
— 1408 bytes of ASCII — came back **QUALIFIED**. It is now impossible to reproduce:
`HTTP_VIDEO_CHECKS` is the runner's default and requires `container=isom` and
`duration >= 0.5s`, and `test_junk_bytes_are_never_qualified_over_http` asserts it.

This is the same class of defect as P9.1.d's renderer self-validation: validation that
looks like it is running and is not.

**2. A provider requiring no credential could never run.** `CredentialResolution.complete`
is `False` when nothing was required, so the guard `if not credentials.complete` blocked
such a provider forever with the meaningless reason `credentials_missing:`. The guard now
tests `credentials.required and not credentials.complete`.

## Failure matrix, as implemented

| scenario | verdict | source of the decision |
|---|---|---|
| missing API key | `BLOCKED_BY_CREDENTIAL` | `HTTPQualificationState.CREDENTIAL_MISSING` |
| invalid key (401/403) | `QUALIFICATION_FAILED` | `error_type=credential_rejected` |
| HTTP 4xx | `QUALIFICATION_FAILED` | `error_type=request_rejected` |
| HTTP 5xx | `PROVIDER_UNREACHABLE` | `error_type=provider_unreachable` |
| timeout | `TIMEOUT` state, `QUALIFICATION_FAILED` verdict | `JobTimeout` |
| job success, no artifact | `REJECTED` | `error_type=no_artifact` |
| download corrupted | `INVALID_ARTIFACT` / `REJECTED` | P8.4 |
| valid mp4 | `QUALIFIED` | P8.4 + receipt |

A timeout is a distinct *state* but not a distinct *verdict*: the verdict enum has no
`TIMEOUT` member because a timeout is a way of not having an outcome, not an outcome.

**Mapping is by typed metadata, never by substring.** `AdapterFailure` carries
`error_type` and `http_status`; `_verdict_for` looks them up in a table. A provider whose
error message happens to contain the word "timeout" cannot reclassify its own failure.

## Authority boundaries

| | may | may not |
|---|---|---|
| `providers/facts.py` | id, kind, runtime, capabilities, locality | health, latency, quality |
| credential resolver | report *presence* | return a value |
| HTTP adapter | submit, poll, download, return a locator | hash, probe, validate, judge |
| `http_runner` | orchestrate, map typed failures | measure the artifact |
| P8.4 | ffprobe, decide validity | — |

`CredentialResolution` has no `value` field. `ExecutionResult` has no `checksum`,
`duration`, `codec`, `passed` or `qualified` field. The adapter imports no `hashlib`,
`subprocess` or `shutil`, and spawns nothing — asserted behaviourally by patching
`subprocess.run` and requiring zero calls.

## Resellers are not providers

`wavespeed` and `alibaba_maas` are **not** registered as provider ids. WaveSpeed is a
reseller serving `wan_2_7` and `happyhorse_1_1`; Alibaba Bailian serves `wan_2_7_maas`
and `happyhorse_1_1_maas`. Registering vendor ids as well would be two identities for one
reseller — the collision P7.3 refused for `ExecutionReceipt` and P8.2 refused for
`ValidationCheck`. The vendor is recorded on `HTTPProviderProfile.vendor`.

## Verification

```
80 passed, 6 skipped · ruff PASS · mypy PASS (18 files)
mutations: M1-M5 all caught
```

| mutation | caught by |
|---|---|
| M1 adapter computes a checksum | `test_the_adapter_mentions_no_probe_or_digest_call` |
| M2 adapter imports/spawns `subprocess` | import scan + `test_no_subprocess_is_spawned_by_the_adapter` |
| M3 missing credential treated usable | 5 tests |
| M4 poll result becomes `QUALIFIED` | `test_job_status_completed_alone_never_yields_qualified` |
| M5 adapter fabricates the artifact | `test_the_validated_bytes_are_exactly_what_the_provider_returned` |

## Not done

**The acceptance gate's real-artifact requirement is not met.** Zero HTTP providers have
produced a real artifact; all four are `BLOCKED_BY_CREDENTIAL`. The harness is complete
and the blocker is a credential decision, not code. Until it is resolved, P9.2 cannot be
called complete and P9.3 should not open.
