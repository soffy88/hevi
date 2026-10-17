# P9 — Real Provider Qualification

**P9.0 harness: PASS. P9.1+ requires credentials and has not run.**

P9 does not change architecture. It verifies the frozen P8 chain against providers that
actually exist.

## P9.0 — what was built

```
hevi/runtime/live/
  credentials.py   Credential, CredentialProvider, redaction
  status.py        LiveRuntimeStatus, LiveOutcome
  drivers.py       HttpLiveDriver, QueueLiveDriver, LocalLiveDriver, DriverRegistry

hevi/qualification/
  live_run.py      LiveQualificationRun, DeclaredVsObserved, QualificationLink, verdict
  live_runner.py   run_live_qualification, qualify_many
```

### Existing-authority scan first

```
hevi/qualification   EXISTED — media.py (MediaValidation), framework.py
hevi/runtime/live    absent -> created
```

`hevi/qualification/` was already an authority. P9.0 is additive: `MediaValidation`,
`validate_media`, `discover_reports` and `write_reports` are untouched and re-exported.

### `LiveRuntimeStatus` is not `ProviderRuntimeStatus`

```
ProviderRuntimeStatus   "we asked, here is the answer"    declared mechanism, P8.1
LiveRuntimeStatus       "we asked a REAL provider"        real answer, P9.0
```

Neither carries `locality`, `license_class` or `capabilities`. A provider that answers
does not thereby become local, licensed or approved.

## The principle: preserve the difference

```
declared:  veo3, QUEUE, requires FAL_API_KEY
observed:  credential_missing
verdict:   QUALIFICATION_FAILED        not UNKNOWN
```

Three verdicts, and the middle one is the point:

| verdict | when |
|---|---|
| `NOT_RUN` | nothing was attempted — no driver, or no command configured |
| `QUALIFICATION_FAILED` | attempted and did not hold, **including `credential_missing`** |
| `QUALIFIED` | all four links proven |

`UNKNOWN` is not an acceptable answer to either of the first two. "We know exactly what
we lack" is not "we don't know", and calling it unknown would hide a fixable
environment condition behind an unfalsifiable state.

### `QUALIFIED` is structurally unreachable without evidence

It requires four `PROVEN` links, each carrying an `evidence_id`; the model refuses to
construct otherwise. There is no `force` / `trust` / `skip_validation` parameter, and a
test asserts none exists.

## Credentials

Redacted in **every** rendering path — `repr`, `str`, `to_dict`, and f-strings — so a
stray log line yields `***`.

`LiveRuntimeStatus.credential_names` records **which names were resolved**, never
values. Recording the *declared requirements* instead is a bug this phase actually
shipped and then fixed: it made the declared-vs-observed diff compare the catalogue to
itself and report `credentials_present: True = True` while the credential was missing.
The regression test is `test_a_missing_credential_shows_as_a_disagreement`.

## Three drivers, one per declared mechanism

| kind | providers | flow |
|---|---|---|
| `HTTP` | WaveSpeed, Alibaba MaaS | request → response → status |
| `QUEUE` | fal.ai video providers | submit → job id → poll → locator |
| `CLI` / `LOCAL_PROCESS` | `wan_local`, `manim` | command → exit code → artifact |

`exit code 0` alone is not success — an artifact must exist too. A queue that returns no
job id, or completes with no locator, is not success either.

## Current result: no credentials configured

```
veo3       qualification_failed   credential_missing: FAL_API_KEY
wan_2_7    qualification_failed   credential_missing: WAVESPEED_API_KEY
manim      not_run                no command configured
wan_local  not_run                no command configured
```

This is the correct output. The harness reports what it does not have rather than a
fleet of green checks.

## Finding: two media-validation contracts now exist

`hevi/qualification/media.py::MediaValidation` (pre-existing, live consumers:
`scripts/real_line_qualification.py`, `tests/qualification/test_framework.py`) overlaps
P8.4's artifact qualification on codec / resolution / duration / fps — and differs in
two ways that matter:

| | pre-existing `MediaValidation` | P8.4 qualification |
|---|---|---|
| input | a **path** | **bytes** |
| `passed` | a plain **field** | **derived** |

So the older gate has precisely the two defects P8.4 was built to remove: a validator
that needs a path can repair what it inspects, and `passed` can be declared without
anything being observed.

**Not merged.** It has live consumers, and consolidating two validation contracts is an
architecture decision for the owner — not something a qualification harness should do
silently. Recorded for decision, not fixed.

## Process change: lint scope is now derived

`scripts/ci/check_lint_scope.py` lints the changed package **plus its transitive
dependency closure**, in both directions.

This exists because P8.4 shipped a duplicate `ValidationCheck` import inside
`hevi/artifact/` that survived every check. Scoping lint to "packages I own" hid a
defect that was *inside* the scoped set — the scope was chosen to exclude the rest of
the repository, including where a change actually propagates.

Running it immediately reported **pre-existing** problems: `hevi/ops/p5_factory.py`,
`hevi/production/gpu_compute.py`, `hevi/layer4_legacy/…`. None are from P9.

**Related finding:** CI runs `mypy --strict hevi`, and that currently reports
**59 errors across 9 files** on the whole tree. The Mypy step is red independently of
this work. Not fixed here — flagging it.

## Acceptance

| check | result |
|---|---|
| `HARNESS_EXISTS` | **PASS** — all four declared kinds have a driver |
| `NO_CREDENTIAL_IN_FACTS` | **PASS** — catalogue unchanged; live modules never import it |
| `NO_CREDENTIAL_IN_RECEIPT` | **PASS** — values absent from every serialised record |
| `DECLARED_VS_OBSERVED_DIFF` | **PASS** — recorded even when it agrees |
| `NO_FAKE_SUCCESS` | **PASS** — four links, each with evidence, no override flag |
| Ruff / Mypy | **PASS** / 0 errors (14 files) |
| tests | **49 passed** |

## Mutation verification

| mutation | result |
|---|---|
| credential gate removed | caught |
| `QUALIFIED` without all four links | caught |
| credential value leaks into `to_dict` | caught |
| nothing-attempted reported as a failure | **initially missed** |
| `credential_names` echoes the declaration | caught |

**M4 initially passed 47/47**, for the same reason the P8.4 T5 did. My not-run test
used a registry with *no* CLI driver, so it took the "no driver" branch and never
exercised a driver that exists, runs, and reports it could not attempt anything — which
is what a missing local command does. Writing the missing case turned the mutation red,
and then exposed a real bug: the `NOT_RUN` branch computed its reason and never recorded
it, so a not-run run could not say why. Both are fixed; `NOT_RUN` now carries a reason
like `QUALIFICATION_FAILED` does.

That is now five instances of the same pattern across P7.3–P9.0. It is the single
highest-yield habit in this codebase: **inject the violation you were told about and
watch it fail.**

## Next: P9.1 — one provider per mechanism

| kind | target | proves |
|---|---|---|
| HTTP | one real provider | request/response chain |
| QUEUE | one video provider | async submit → poll → artifact |
| CLI / LOCAL | `wan_local` or `manim` | local execution |

A provider class passes only with `ProviderDecision` + `LiveRuntimeStatus` +
`AcquiredSource` + `ProductionReceipt` + `QualifiedArtifact`. Missing any one is a FAIL.

`wan_cloud` still has no declared endpoint or credential (GAP-002); it remains
unobservable by design rather than falsely declared.

**GAP-002 and GAP-003 stay open.** P9.0 measured `0 / 16` providers against live
credentials — unchanged from P8.1.5, and correctly so.

---

# P9.0.1 — Media validation consolidation

**Status: PASS.** Two media validation contracts became one.

## What was wrong

```
hevi/qualification/media.py   path in, passed declared    pre-existing
hevi/artifact + validation   bytes in, passed derived     P8.4
```

Both answered "is this media usable", and a caller had no way to know which was
production truth. Same shape as the `ExecutionReceipt` and `AcquisitionState`
collisions: two answers, one question.

Worse, the older gate had the two defects P8.4 exists to remove:

```
nonzero = exists and target.stat().st_size > 0    a directory entry, not content
passed: bool = False                               declarable, not derived
```

## What changed

`media.py` is no longer an authority. It is a **view** over P8.4:

* observation comes from `hevi.artifact.probes.probe_containerised` — no second ffprobe
* `passed` is a **property**; `MediaValidation(passed=True)` now raises `TypeError`
* non-emptiness is proven by **reading and hashing bytes**, never `stat()`
* `to_validation_result()` returns the one canonical `ValidationResult`

`validate_media(path)` keeps its signature and its error vocabulary — `artifact_missing`,
`artifact_empty`, `ffprobe_parse_failed`, `audio_missing` — because
`scripts/real_line_qualification.py` and `tests/qualification/test_framework.py` read
those fields by name. A path is now only a *locator* for reading bytes.

`media.py` was **not** deleted.

## Verification

```
MediaValidation(passed=True)          -> TypeError
real 320x240 h264 mp4                -> passed=True, derived via to_validation_result
same bytes via P8.4 probe            -> agrees with the view
empty file                           -> nonzero=False (bytes read, not stat)
garbage 160 bytes                    -> nonzero=True, passed=False, ffprobe_parse_failed
scripts/real_line_qualification.py   -> parses, compiles, import path resolves
tests/qualification/                 -> 6 passed
P8.4 suite                           -> 120 passed, unchanged
```

22 consolidation tests. Three mutations, all caught:

| mutation | result |
|---|---|
| `passed` declared as a field again | caught |
| non-emptiness proven by `stat()` again | caught — byte-derived checksum disagreed with the real file |
| `media.py` runs its own ffprobe again | caught |

## Recorded, not fixed

**GAP-004** — `mypy --strict hevi` reports 59 errors across 9 files; CI's Mypy step is
red independently of this work. Owner: repository typing maintenance. P9 does not fix it,
because two of the files were already dirty before this work began and rewriting nine
unrelated modules is exactly the scope expansion P9's brief forbids.

## Order for P9.1

Revised as directed — CLI/LOCAL first, because it closes a loop with no external quota:

```
P9.0.1  validation consolidation   done
P9.1    CLI / LOCAL                wan_local or manim
P9.2    HTTP                       WAVESPEED_API_KEY or ALIBABA_MAAS_*
P9.3    QUEUE                      FAL_API_KEY
```

---

# P9.1.a — LOCAL_PROCESS qualification harness

**Status: PASS. P9.1 remains `BLOCKED_BY_RUNTIME`.**

The harness is complete and proves LOCAL_PROCESS semantics end to end. manim itself is
absent (GAP-005) and is reported as blocked, not as a pass.

## The verdict space

```
NOT_RUN                nothing was attempted — no driver, no command configured
BLOCKED_BY_RUNTIME     we know exactly what is missing (binary not on PATH)
QUALIFICATION_FAILED   attempted, and the attempt broke
REJECTED               the runtime ran and declined to produce an artifact
INVALID_ARTIFACT       bytes arrived but are not the artifact they claim to be
QUALIFIED              all four links proven, from real bytes
```

`BLOCKED_BY_RUNTIME` is separate from `NOT_RUN` because "we know what is needed and the
environment lacks it" is a different statement from "we did not try", and names a fixable
cause.

## Required matrix — all five verified

| case | verdict |
|---|---|
| manim executable absent | `BLOCKED_BY_RUNTIME` |
| driver exception | `QUALIFICATION_FAILED` |
| exit 0, no artifact | `REJECTED` |
| artifact invalid (digest mismatch) | `INVALID_ARTIFACT` |
| artifact valid | `QUALIFIED` |

The success path uses a **real subprocess writing a real MP4**, so the loop is proven
with bytes that exist on disk rather than fixtures.

## The loop

```
ProviderCatalogue(manim) -> LocalLiveDriver -> renderer -> artifact bytes
                                                     |
                            AcquiredSource (P8.2) <-+   checksum + evidence
                                    |
                            ProductionReceipt (P8.3)   issued from validated bytes
                                    |
                            ArtifactValidation (P8.4)
                                    |
                                 verdict
```

Layering held, as P8.4 demanded: the renderer returns **bytes**, never a
`ValidationResult`. A renderer that could hand back a validation result would own
artifact truth again.

## Two real bugs found by writing the tests

**Links were never rebuilt.** The live run covers only `observation`; acquisition,
execution and artifact are proven afterwards in `local_process.py`, but the links were
never updated — so a `QUALIFIED` run reported three *pending* links while asserting
qualification. The final run now rebuilds all four.

**`was_attempted` ignored `RUNTIME_UNAVAILABLE`.** The new outcome did not run anything,
but the property said otherwise. Both are now covered by regression tests.

## Two test bugs, same pattern as before

One test read the artifact bytes *before* invoking the renderer. The other banned the
token `ffprobe` from the module — but `validator_name="ffprobe"` only *labels* the
validation step, so the ban flagged a harmless name while a real invocation would have
slipped past. That is the sixth instance of the pattern now recorded in
`docs/TESTING-PRINCIPLES.md`. Rewritten as a capability check over imports and calls.

## Acceptance

| check | result |
|---|---|
| `MANIM_DECLARED_PROVIDER` | **PASS** |
| `LOCAL_PROCESS_DRIVER` | **PASS** |
| `REAL_PROCESS_EXECUTION` | **PASS** — real subprocess, real bytes |
| `ARTIFACT_CREATED_BY_RUN` | **PASS** |
| `PRODUCTION_RECEIPT_CREATED` | **PASS** |
| `P8_4_VALIDATION` | **PASS** |
| `QUALIFIED_REQUIRES_EVIDENCE` | **PASS** — no reader means no receipt |
| Ruff / Mypy | **PASS** / 0 errors |
| tests | **21 passed** |

Mutation verification: dropping the blocked-by-runtime gate, not rebuilding links,
removing the digest check, and reverting `was_attempted` each fail the suite.

## P9.1.b — the remaining step

```bash
sudo apt-get install -y libx11-dev libpango1.0-dev libcairo2-dev pkg-config
uv pip install manim
```

Then re-run the same qualification against the real manim binary. Nothing else changes —
`BLOCKED_BY_RUNTIME` becomes `QUALIFIED`, and GAP-003 moves from `0/16` to `1/16` real
qualifications. That is one of sixteen, and does not close GAP-003.

---

# P9.1.b — Real manim qualification

**Status: PASS.** HEVI's first real provider qualification.

## What was actually run

A real manim scene, rendered by manim 0.21.0 in a subprocess:

```
scene.py  ->  manim render -ql --format mp4
          ->  HeviQualificationScene.mp4   (34198 bytes)
          ->  sha256 3d0a86c6ef5dac44b132efcba55c5ad8…
          ->  AcquiredSource + AcquisitionEvidence   (P8.2)
          ->  ProductionReceipt                      (P8.3)
          ->  ArtifactValidation                     (P8.4)
          ->  QUALIFIED
```

Independently verified by ffprobe before the harness ran:

```
codec=h264  container=isom  resolution=854x480  fps=15  duration=4.2s
```

Nothing simulated: the artifact is the MP4 manim wrote, the checksum is computed from
those bytes, and the receipt is issued from them.

## Verdict

| link | evidence |
|---|---|
| observation | live latency > 0, exit 0 |
| acquisition | `ev-manim`, sha256 over the real bytes |
| execution | `rc-run-manim-hevi-qualification-scene` |
| artifact | `artifact_qualified` |

## All five states still hold, against a real renderer

| case | verdict |
|---|---|
| manim executable absent | `BLOCKED_BY_RUNTIME` |
| driver error | `QUALIFICATION_FAILED` |
| exit 0, no artifact named | `REJECTED` |
| artifact reads as empty | `REJECTED` |
| artifact digest mismatch | `INVALID_ARTIFACT` |
| wrong requirement, real artifact | `REJECTED` (`METADATA_MISMATCH`) |
| real artifact, requirements met | **`QUALIFIED`** |

## Two real bugs the real render exposed

Neither was reachable with an injected runner.

**The locator was discarded.** The qualification passed `request_kind` to
`read_artifact` instead of the locator, so a real filesystem reader had nothing to
open. The first real run failed with `command exited 0 but produced no artifact` —
which was *correct* driver behaviour, and the wiring was wrong. `artifact_locator` is
now threaded through.

**`cwd` was unsupported.** manim must run from its own project directory. The driver
gained a `cwd` parameter; without it no scene could be found.

## A test defect the mutation pass exposed

Removing the empty-bytes guard passed all 14 tests. The verdict was still `REJECTED` —
but for the wrong reason: an empty payload fails validation anyway, so the two
failures looked identical.

This is the mirror of the P8.4 lesson. There, a test named the wrong *thing*; here it
asserted the wrong *level*. Verdict alone is too coarse to distinguish "nothing was
produced" from "what was produced is invalid", so the failure-path tests now assert
`reason` as well as `verdict`, and the empty-bytes case is a separate test from the
no-locator case.

## Dependency policy: still undecided, deliberately

manim was installed into the venv only. `pyproject.toml` and `uv.lock` are unmodified,
so:

* CI's `uv sync --locked` will not reproduce manim, and
* `test_p9_1_b_real_manim.py` self-skips when the runtime is absent.

If manim becomes a supported runtime it belongs in a provider-specific extra; if it
stays a qualification tool it stays out of production dependencies. **That decision is
not made here.**

## Status

```
P9.0      PASS
P9.0.1    PASS
P9.1.a    PASS
P9.1.b    PASS      first real provider qualification
GAP-005   RESOLVED

GAP-002   open      0/16 providers probed against live credentials
GAP-003   open      1/16 real renders (manim)
GAP-004   open      typing debt, CI Mypy red
```

**This proves `manim = qualified`.** It does not close GAP-002 (no provider has been
verified live against a credential) and does not close GAP-003 — fifteen providers remain
unrendered, including every HTTP and QUEUE path.
