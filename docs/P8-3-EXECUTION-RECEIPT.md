# P8.3 — Execution Receipt Qualification

**Status: PASS.** A production receipt is issued from artifact *bytes* a validator has
observed, never from a path.

## Naming: a collision I had to resolve rather than reproduce

**P6 already defines a type called `ExecutionReceipt`.**

```
P6   ExecutionReceipt   runtime_id, entrypoint_ref, produced -> a delegate RAN
P8.3 spec asked for     receipt_id, run_id, artifact_id, artifact_checksum, ... -> an artifact is PROVEN
```

Different subject, different claim. Defining the second would have put two types behind
one name with two meanings — precisely the defect P8.2 found in its own
`AcquisitionState.FAILED` colliding with `RunState.failed` — and would have breached
P8.3's own `NO_SECOND_PRODUCTION_AUTHORITY` acceptance criterion.

So this is **`ProductionReceipt`**, and the two are independent types:

| | P6 `ExecutionReceipt` | P8.3 `ProductionReceipt` |
|---|---|---|
| proves | a delegate ran | an artifact was produced and validated |
| has `artifact_checksum` | no | yes, required |
| has validation | no | yes, required and passing |
| owns | orchestration | execution proof |

`test_the_two_receipts_are_independent_types` asserts neither subclasses the other,
and `test_execution_package_defines_no_execution_receipt` fails if the name is reused.

## `hevi/execution/` already existed

Worth recording, because I got it wrong first: `hevi/execution/` is **P0-E** —
immutable execution plans, DAG repair, `Scheduler`, `ResourceSnapshot`. My first
`__init__.py` overwrote it and broke `hevi.tasks.repository` on import.

It is now additive: all eleven P0-E exports preserved, eight P8.3 exports appended,
`__all__` extended rather than replaced. P0-E's own suites pass unchanged
(473 passed, 4 skipped). The two layers live in separate modules with separate
namespaces — P0-E decides *what should run*, P8.3 decides *what may be claimed*.

## `artifact_exists() != production_success`

A path proves bytes were written. It does not prove they are playable, that they came
from the source we intended, or that a render finished rather than crashed after
flushing a partial file.

So `issue_receipt` takes bytes. There is no variant that takes a location, and the
test asserts it (`test_receipt_is_never_issued_from_a_path`). The checksum is
**recomputed from the payload, never passed in** — no `checksum` parameter exists
(`test_checksum_is_recomputed_not_passed_in`).

## Gates, in order, each refusing for its own reason

```
run not completed        -> EXECUTOR_FAILED
source mismatch          -> SOURCE_MISSING
artifact absent / empty  -> ARTIFACT_MISSING
artifact unreadable      -> ARTIFACT_UNREADABLE
never validated          -> VALIDATION_NOT_RUN
validation failed        -> VALIDATION_FAILED
validation saw other bytes -> PAYLOAD_MISMATCH
already receipted        -> ALREADY_RECEIPTED
```

Ordering is load-bearing: a run that produced no artifact is not "validation failed",
and an existing receipt is not re-issued because the artifact still exists. No bare
`FAILED`, `SUCCESS` or `DONE` — `test_no_bare_success_or_done_states`.

`ValidationResult.passed` is **derived** from the checks, never declared, so a result
cannot claim success while carrying a failed check. And validation must carry a digest
of the payload it observed: a result that never hashed anything says nothing about
anything.

## `COMPLETED` is not `PRODUCED`

```python
ExecutionState.COMPLETED = "execution_completed"
```

Namespaced so it cannot collide with `RunState` on the wire. This package never names
`RunState` at all — checked on code identifiers, not text, because the docstrings
mention `RunState.PRODUCED` to explain that it is *not* this package's. P7.3's I5
invariant is re-verified and still holds: `RunState.PRODUCED` has exactly one
construction site.

## T5 — receipt uniqueness

One receipt per `(run_id, artifact_id)`, enforced by `ReceiptLedger`. The test that
matters is **two distinct receipts for the same run and artifact** — re-recording an
identical object trips the id guard first, which is a weaker statement. Different
artifacts from one run, and the same artifact from different runs, each get their own
receipt.

## Acceptance

| check | result |
|---|---|
| `ARTIFACT_EXISTS_NOT_PROOF` | **PASS** — receipt issued from bytes only |
| `RECEIPT_REQUIRES_VALIDATION` | **PASS** — required, passing, and digest-matched |
| `NO_RUNSTATE_LEAK` | **PASS** — states namespaced; identifiers never reference it |
| `CHECKSUM_PROPAGATED` | **PASS** — computed from payload, propagated to receipt |
| `NO_SECOND_PRODUCTION_AUTHORITY` | **PASS** — `ProductionReceipt`, not a second `ExecutionReceipt` |
| Ruff / Mypy | **PASS** / 0 errors (49 files) |
| tests | **44 passed** |

## T1–T5 mutation verification

| mutation | tests failed |
|---|---|
| T1 empty artifact no longer refused | 1 |
| T2 validation no longer required | 1 |
| T3 `COMPLETED = "produced"` | 1 |
| T4 skip validation, receipt anyway | 3 |
| T5 duplicate identity guard removed | 1 |

T2 is worth noting: removing the *model's* validation guard produced an `AttributeError`
rather than a clean refusal, because a later check dereferences
`validation_result.passed`. The guard fired first, so the failure was an exception
rather than the intended `PRODUCTION_RECEIPT_WITHOUT_VALIDATION` — caught, but noisily.
The gate order is correct; the failure mode is just untidy.

## Defects found in my own work

Three, all recorded because each could have produced a false green:

1. **I overwrote a live package.** See above. Caught by import failure in
   `hevi.tasks.repository`, then fixed and verified.
2. **A whole-tree AST walk made an invariant fragile.** `test_run_state_produced_still_has_one_construction_site`
   parsed every file under `hevi/`, so it became hostage to
   `hevi/prompting/anti_repeat.py` — a pre-existing non-raw regex that raises a
   `SyntaxWarning`, which becomes a `SyntaxError` under `-W error`. Scoped to
   `hevi/production/` and `hevi/execution/`, the two trees where a second construction
   could actually appear.
3. **Three test bugs of my own**: a list passed where the frozen model requires a
   tuple; a helper that made run and supplied source agree, so the mismatch test
   could not fail; and a rename that broke an assertion using the variable it renamed.

## Scope

`hevi/sourcing/`, `hevi/providers/facts.py`, `hevi/provider_policy/`,
`hevi/production/p7/` and `hevi/acquisition/` unmodified — verified by checksum. No
subprocess, no filesystem, no renderer: `execute.py` imports neither `subprocess` nor
`os` and uses no `open`/`Path`, because performing the render is the executor's
business and this module only decides what may be claimed.

## Next: P8.4 Artifact Qualification

```
AcquiredSource -> Execution -> ProductionReceipt -> Artifact qualification
```

`ValidationResult` is now the container P8.4 fills with codec, resolution, duration,
and visual/audio integrity checks. The discipline carries: a check must be *named*,
must be *observed against the bytes*, and `passed` remains derived so it cannot be
asserted rather than computed.
