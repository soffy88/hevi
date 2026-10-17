# P8.2 — Acquisition Evidence

**Status: PASS.** A URI is no longer sufficient to become a source. `ACQUIRED` requires
a digest, and a digest cannot be typed.

## The problem this solves

A URI is the cheapest possible fake. It costs nothing to write
`https://cdn.example/video.mp4`, it survives serialisation, and every layer above it
will treat it as an asset. The failure it produces is silent: nothing 404s, nothing
raises, and the pipeline reports a source it never fetched.

So the cheap fake is made insufficient:

```
uri ──fetch──▶ bytes ──sha256──▶ checksum
                                     +
                          the event that fetched them
                                     =
                                evidence
```

Everything else in P8.2 is a claim someone typed. The checksum is a claim the payload
itself makes, which is why `verify_against(payload)` is the one check in this phase
that cannot be satisfied by invention.

## Two models, deliberately apart

```python
AcquiredSource(       source_id, provider_id, uri, checksum,
                     acquired_at, evidence_id, state)

AcquisitionEvidence(  evidence_id, provider_id, source_id, checksum,
                     timestamp, acquisition_method)
```

`AcquiredSource` is a located thing. `AcquisitionEvidence` carries **no URI at all** —
`test_evidence_carries_no_uri` fails if one is added, because if evidence held the
locator then `evidence == uri` would become expressible and the separation would be
unenforceable by construction.

### What evidence proves, and what it does not

It proves: *this source was produced by this provider, by this method, at this time,
and these bytes hash to this value.*

It does **not** prove:

| claim | why not | whose it is |
|---|---|---|
| the content is any good | quality is not evidence | P7 asset policy |
| it is lawful to use | licensing is a declared fact | `ProviderProfile` |
| policy approved it | eligibility | `ProviderDecision` |
| it will still be there | a URI is not a lease | nobody yet |

Overclaiming here is how a provenance system quietly becomes a compliance system.

## Three gates, three distinct reasons

```
ProviderDecision        may this provider be used?   -> POLICY_BLOCKED
ProviderRuntimeStatus   is it answering right now?    -> PROVIDER_UNREACHABLE
payload + digest        did anything arrive intact?   -> DOWNLOAD_FAILED
                                                       CHECKSUM_MISMATCH
```

Each stops acquisition for its own reason, which is the point: collapsing them produces
the P8 failure mode, a source that was never fetched reported as acquired because the
URL was well-formed. `test_policy_and_runtime_failures_are_distinguishable` and
`test_policy_check_precedes_the_fetch` hold both the distinction and the order — a
policy-rejected provider is not contacted at all, verified with a spy fetcher that
records calls.

**Fail-closed carries through.** An absent runtime status is treated as `UNKNOWN`,
which is not usable, so "we never looked" cannot acquire anything
(`test_absent_runtime_status_cannot_acquire`).

## Failure classification

```
POLICY_BLOCKED          authority said no; retrying is pointless
PROVIDER_UNREACHABLE    observation layer already knows; not a bug
DOWNLOAD_FAILED         transport; retrying may work
CHECKSUM_MISMATCH       payload is not what was expected
EVIDENCE_MISSING        no proof accompanies a claim
```

There is deliberately no bare `FAILED`. `test_failure_causes_are_classified_not_collapsed`
fails if one appears. Every failure requires a reason, and an outcome carries exactly
one of `source` or `failure` — never both, or a caller could read whichever it found
convenient.

## Finding: I collided with `RunState` in my own new vocabulary

`AcquisitionState.FAILED` was defined with value `"failed"` — **identical to
`RunState.failed`**. The disjointness invariant P7.3 froze for `AssetDecisionState` was
violated by the very phase meant to extend it, and the collision is invisible in
source review and fatal in a serialised record: "the download failed" and "the render
failed" become the same token.

```python
REQUESTED  = "acquisition_requested"
AVAILABLE  = "acquisition_available"
ACQUIRED   = "acquired"
FAILED     = "acquisition_failed"     # was "failed"
```

`RunState` also contains `validated`, `compiled`, `produced`, `qa_passed` and
`qa_failed` — a namespace already crowded enough that a bare `available` was one
rename away from the same trap. Caught by
`test_acquisition_state_is_disjoint_from_run_state`, which is P7.3's I5 invariant
reused rather than restated.

A second defect in the same area: the "no execution receipt" test scanned raw text and
failed because the module docstrings *name* `ExecutionReceipt` to explain that
production truth is not this package's. Describing a boundary is not crossing it; the
check now reads code identifiers only.

## Acceptance

| check | result |
|---|---|
| `ACQUIRED_REQUIRES_EVIDENCE` | **PASS** — enforced in `__post_init__` |
| `CHECKSUM_REQUIRED` | **PASS** — sha256 hex, 8 placeholders rejected |
| `NO_SOURCE_AS_EVIDENCE` | **PASS** — evidence has no URI field |
| `NO_PROVIDER_FACTS_IN_ACQUIRED_SOURCE` | **PASS** — 9 forbidden names + AST check |
| `NO_PRODUCTION_STATE_LEAK` | **PASS** — states disjoint, identifiers checked |
| Ruff / Mypy | **PASS** / 0 errors (40 files) |
| tests | **56 passed** |

## T1–T5 mutation verification

| mutation | tests failed |
|---|---|
| T1 evidence gains a `uri` field | 2 |
| T2 `checksum` becomes optional | 1 |
| T3 remove the evidence requirement for `ACQUIRED` | 2 |
| T4 `AcquiredSource` gains `locality` + `license_class` | 4 |
| T5 `UNAVAILABLE` provider still acquires | 4 |

T2 is the interesting one. Loosening the checksum guard failed exactly **one** test —
the digest-shape test — and no end-to-end test, because nothing downstream ever
constructed an invalid digest anyway. A narrow guard has narrow coverage; the test
that failed is the one that owned the rule.

## Scope

`hevi/sourcing/`, `hevi/providers/facts.py`, `hevi/provider_policy/` and
`hevi/production/p7/` unmodified. Verified by checksum and by confirming `policy.py`'s
diff is still the P7.2 materialisation and nothing else.

No network client was added. `Fetcher` is a callable seam; `acquire.py` defines no
fetcher and contains no async I/O, so a second transport cannot creep in
(`test_acquisition_module_contains_no_network_client`,
`test_acquisition_module_defines_no_fetcher`).

## Next: P8.3 Execution Receipt Qualification

```
AcquiredSource ──▶ Render ──▶ ExecutionReceipt ──▶ Artifact
```

P8.3 inherits this phase's hardest constraint: `artifact_exists() != production
success`. A file on disk proves bytes were written, not that a render completed as
intended — the same distinction between a location and a proof that P8.2 just drew for
acquisition.
