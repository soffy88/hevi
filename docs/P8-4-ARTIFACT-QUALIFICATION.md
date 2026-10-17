# P8.4 — Artifact Qualification

**Status: PASS.** Existence yields `FOUND`. Validity is strictly stronger, and an
unobserved requirement cannot pass.

```
ProductionReceipt ──▶ ArtifactDescriptor ──▶ ValidationResult ──▶ ArtifactState
```

## Existing-authority scan first

P8.3's lesson applied before anything was written:

```
hevi/artifact      absent                     -> safe to create
hevi/validation    exists (P8.3, mine)        -> extend, do not replace
hevi/execution     P0-E + P8.3                -> interface only, no rewrite
ArtifactDescriptor / ArtifactCheck elsewhere  -> none found
```

A second scan then found an authority I had not planned for:
**`hevi/video/quality_check.py::probe_stats`** already probes media with ffprobe. It is
not duplicated. What P8.4 adds is a *byte-oriented seam*, because `probe_stats` takes
a `Path` — and a probe that needs a path can also repair the file it inspects, which
rule 4 forbids.

## Two duplications resolved rather than reproduced

**One check type.** P8.3 had `ValidationCheck(name, passed)`; P8.4 asked for
`ArtifactCheck(name, observed, expected, passed)`. Two names for one idea is the same
collision P8.2 hit with `AcquisitionState.FAILED` and P8.3 with `ExecutionReceipt`.

Worse, P8.3's `passed` was a **plain field** — a caller could declare a verdict without
anything having been observed. So rather than add a second type, P8.4 extended the
first:

```python
ValidationCheck(name, observed, expected, operator=CheckOperator.EQ)
@property
def passed(self) -> bool: ...        # derived, and not a field
```

`ArtifactCheck` is now an **alias**, asserted identical by
`test_artifact_check_is_the_validation_check`. The seven P8.3 call sites were updated to
the explicit form; P8.3's 44 tests still pass.

The comparison is a named `CheckOperator` rather than an injected predicate, because
`lambda observed, expected: True` is expressible and passes everything, while no
operator in a closed set can — and the failing comparison stays nameable.

## The four rules

**Rule 1 — existence is `FOUND`, never valid.** `ArtifactDescriptor` has **no** `state`
field at all; `state` is a property that can only ever return `FOUND`. Qualification is
a separate call, so locating bytes cannot produce a verdict.

**Rule 2 — checksum mismatch is `INVALID_ARTIFACT`.** The digest is recomputed from the
payload rather than trusted from the descriptor, which is what makes the rule
enforceable. Distinct from `METADATA_MISMATCH`: the first means the bytes are not the
ones the receipt covers, the second that the bytes are right and the content is not
acceptable.

**Rule 3 — metadata mismatch is not a pass.** 1280x720 does not satisfy 1920x1080.
`test_wrong_resolution_does_not_pass` also asserts `was_observed is True` — measured and
wrong is not the same as never measured.

**Rule 4 — validation never repairs.** The probe reads, `qualify` compares. Verified by
asserting no write-capable module is imported and no write-shaped call appears.

## The property that makes it safe

**An unobserved requirement cannot pass.** If ffprobe is missing, or a stream is absent,
the check reports *not-observed* and the artifact is `UNVERIFIED` — not qualified on
defaults.

```
never observed   -> UNVERIFIED
measured, wrong  -> METADATA_MISMATCH
measured, right  -> QUALIFIED
bytes differ     -> INVALID_ARTIFACT
```

A validator that filled in defaults would convert a missing probe into a silent pass.

## Real observation, from bytes

Probes take **bytes** and ffprobe reads `pipe:0`, so a real MP4 is qualified without any
file being written:

```
codec=h264  resolution=(320,240)  duration=1.0  fps=24.0  container=isom
```

Images are identified by magic number rather than by ffprobe or by filename extension.
Unreadable input yields absent fields, which is *not-observed*, not *wrong* — the
distinction that keeps "no ffprobe" from reading as "invalid media".

## Finding: my own T5 test was decorative

The first version of `test_probe_module_cannot_write` checked identifiers against a
token list containing `write`. I injected a repair helper:

```python
def _repair(path):
    import shutil
    shutil.copy(path, path + ".fixed")
```

**All 47 tests passed.** `copy` was never on the list, and `shutil` was never banned as
a module — so a validator that could rewrite the artifact slipped through a test
specifically written to prevent exactly that.

The check now has two halves: no write-capable module may be *imported*
(`shutil`, `os`, `tempfile`, `pathlib`, `io`, …) and no write-shaped *call* may appear
(`copy`, `unlink`, `replace`, `dump`, …). Re-injecting the same repair now fails.

This is the third time this pattern appeared — P7.3's `I4` name-matching blind spot,
P8.2's text-scan, P8.3's whole-tree AST walk. A test that names the wrong thing passes
just as confidently as one that does not. The habit that catches it is always the same:
**inject the violation you were told about and watch it fail.**

## Acceptance

| check | result |
|---|---|
| `VALIDATION_DERIVED_PASS` | **PASS** — `passed` is a property, not a field |
| `NO_ARTIFACT_REPAIR` | **PASS** — modules and calls both barred |
| `CHECKSUM_VERIFIED` | **PASS** — recomputed from payload every time |
| `METADATA_OBSERVED` | **PASS** — probed from bytes; descriptor cannot assert a codec |
| `NO_PRODUCTION_AUTHORITY_DUPLICATE` | **PASS** — no `RunState`, no receipt, no `PRODUCED` |
| `P0-E unchanged` | **PASS** — 475 passed, 4 skipped; all 10 exports present |
| Ruff / Mypy | **PASS** / 0 errors (53 files) |
| tests | **47 passed**, 0 skipped (real ffprobe exercised) |

## T1–T5 mutation verification

| mutation | tests failed |
|---|---|
| T1 `passed` declared as a field | caught |
| T2 probe reports the requirement instead of the observation | caught |
| T3 checksum trusted from descriptor, not recomputed | 2 |
| T4 unobserved check no longer blocks qualification | 4 |
| T5 validator gains `shutil.copy` repair | 1 (after the fix) |

## Scope

`hevi/sourcing/`, `hevi/providers/facts.py`, `hevi/provider_policy/`,
`hevi/production/p7/` and `hevi/acquisition/` unmodified — verified by checksum.
`hevi/execution/` received only the interface addition from P8.3; P0-E is untouched and
its exports all resolve.

## The chain is closed

```
Intent
  -> ProviderFacts (declared, catalogue)
  -> ProviderPolicy (eligibility)
  -> RuntimeObservation (is it answering)
  -> AcquisitionEvidence (bytes, digest, event)
  -> ExecutionRun
  -> ProductionReceipt (artifact proven, validated)
  -> ArtifactValidation (requirements observed and met)
  -> Qualified Artifact
```

Every arrow is a gate that can refuse, and each layer's states are disjoint from every
other's on the wire. What remains unproven is the part P8 cannot prove without
credentials: that a declared provider is reachable, and that a real render against it
produces a qualifying artifact. `wan_cloud` still has no declared observation, and 15/16
coverage is a declaration rather than a measurement.
