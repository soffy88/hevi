# HEVI — Architecture Gaps

Gaps are recorded here when an implementation is *correct but insufficient*. A bug is
a defect in what was promised; a gap is a limit of what was built. They are tracked
separately so neither is mistaken for the other.

Each entry names an owner outside the phase that discovered it. A gap found by P7 or
P8 is not automatically a P7 or P8 defect.

---

## GAP-001 — Runtime observation coverage

| | |
|---|---|
| **status** | resolved for the video fleet by P8.1.5; one provider remains unobserved |
| **discovered** | P8.1 |
| **owner** | provider runtime specification owner (`PROVIDER_SPECS` / `RUNTIME_SPECS`) |
| **severity** | medium |
| **failure direction** | safe fail-close |

### What was observed

P8.1 correctly modelled runtime observation as a question separate from provider
identity and from policy eligibility. Measurement then showed the model had almost
nothing to describe:

```
catalogue providers                16
observable via PROVIDER_SPECS       2   longcat, voicebox
unobserved                         14   every video generator
```

`PROVIDER_SPECS` covered 8 infrastructure providers, of which **6 were not in the
catalogue at all**, while 14 of the catalogue's 16 were absent from the specs. The two
registries overlapped by 2 entries — and nobody had added them up.

### Why it is not a P8.1 bug

P8.1's contract was observation *without* facts, and it held: no runtime model carried
`locality`, `license_class` or `capabilities`; the probe never wrote to
`ProviderCatalogue`; and `UNKNOWN` failed closed. Every video provider correctly
reported `UNKNOWN`.

The defect was coverage, which P8.1 did not claim to provide. Falsely reporting a
provider as observable would have been a bug; honestly reporting `UNKNOWN` was correct
behaviour on incomplete inputs.

### Why the failure direction is safe

An unobserved provider is `UNKNOWN`, and `UNKNOWN` is never usable. So the gap could
only ever *prevent* production, never authorise anything unfounded. It made P8.2
untestable against the video fleet — an inconvenience, not a hazard.

### Resolution

P8.1.5 declared observation coverage for the video fleet in
`hevi/providers/runtime_specs.py`, grounded in how each provider is actually invoked:

```
observed   15 / 16
unobserved  1 / 16   wan_cloud
```

Four health-check kinds are used, because the mechanisms genuinely differ:
`wan_local`/`ltx2_local` are subprocess (`CLI`), `h3_local`/`manim` are in-process
(`LOCAL_PROCESS`), `veo3`/`kling_v2`/`hailuo`/`ltx2_cloud` are fal.ai queue
submissions (`QUEUE`), and the WaveSpeed and Alibaba providers are plain `HTTP`.

### Residual: wan_cloud

`wan_cloud` has **no endpoint and no credential declared anywhere in the codebase** —
only a price in `hevi/cost/pricing_table.py`. It could have been given a
plausible-looking fal endpoint to reach 16/16. It was not, because a declared
observation that was never grounded is worse than an honest gap: it would report a
provider as observable when nothing can actually check it. Locked by
`test_wan_cloud_gap_is_documented_not_invented`.

**To close:** whoever owns Wave generation declares `wan_cloud`'s endpoint and
credential. Until then it stays `UNKNOWN` and is never routed.

---

## GAP-002 — Provider runtime verification

| | |
|---|---|
| **status** | open — architecture for it exists, nothing has been exercised |
| **discovered** | P8.1.5 |
| **owner** | provider runtime specification owner, plus whoever holds the credentials |
| **severity** | medium |
| **failure direction** | safe fail-close |

### What P8 proved, and what it did not

```
ProviderCatalogue ─▶ RuntimeSpec ─▶ ProviderRuntimeStatus
     declared          declared          observation
```

All three are **declarations and a model**. 15 of 16 catalogue providers have a declared
way to be observed. **Zero have been observed**, because no credentials are configured.

So P8 establishes:

> if a provider works, then the result can be proven

It does **not** establish:

> that any provider works

That distinction is the same `declared != verified` boundary P7.2 drew for locality and
licence class, one layer further from the code. `ProviderRuntimeStatus` can only report
what a probe returned, and no probe has been given anything real to talk to.

### Why the future fix is not a fact source

The obvious extension is a live probe that produces a durable record. It must remain an
*observation*, never a fact:

```
ProviderFact   "what it is"          hevi/providers/facts.py
LiveProbe      "is it responding now"  runtime
```

A probe that wrote locality, licence class or capability state back into the catalogue
would reopen exactly the fork P7.3 closed. P9 must add verification *beside* the
catalogue, never into it.

### To close

Credentials for at least one provider per `HealthCheckKind` — one HTTP, one QUEUE, one
CLI or LOCAL_PROCESS. Then probe each and record what disagreed with the declaration.
Disagreement is the finding; a probe that agrees proves nothing on its own.

---

## GAP-003 — Real render qualification

| | |
|---|---|
| **status** | open — blocked on external resources |
| **discovered** | P6, restated by P8.4 |
| **owner** | whoever holds provider credentials and GPU access |
| **severity** | high for product, none for architecture |
| **failure direction** | safe fail-close |

### What is proven and what is not

P8.4 proves the last link works. Given real bytes, it measures codec, resolution,
duration and container, compares them against requirements, and refuses when they do
not hold — against a real h264 MP4 read through a pipe, with no file written.

It has never run against bytes a provider produced. The full chain
`live provider -> render -> qualified artifact` has zero executions.

### Why this is not a P8 defect

Every gate in P8 fails closed on absent inputs: no credential means `UNKNOWN`, which is
not usable; no probe means `UNVERIFIED`; no artifact means no receipt. The architecture
is doing exactly what it was built to do — refusing to claim what it cannot prove. A
pipeline that reported success here would be the bug.

### To close

One real render per provider class, end to end, with the receipt chain and P8.4
qualification attached. Requires credentials and, for the local runtimes, a CUDA device.

---

## GAP-004 — Repository typing debt

| | |
|---|---|
| **status** | open — pre-existing, deliberately not fixed in P9 |
| **discovered** | P9.0, via the new `scripts/ci/check_lint_scope.py` gate |
| **owner** | repository typing maintenance |
| **severity** | medium |
| **failure direction** | development quality — no runtime effect |

### What was found

CI runs `mypy --strict hevi` over the whole tree. That currently reports:

```
59 errors in 9 files
```

Known locations:

```
hevi/ops/p5_factory.py                              (also dirty before P7)
hevi/production/gpu_compute.py
hevi/layer4_legacy/voicepro_translate/oprim_impl/
… and 6 further files
```

The **Mypy step of `.github/workflows/ci.yml` is therefore red** independently of any
P7, P8 or P9 work.

### Why P9 did not fix it

Three reasons, and the third is the one that matters:

1. It is not a P9 defect. Nothing in P7–P9 introduced these errors.
2. `hevi/ops/p5_factory.py` and `hevi/ops/p5_volcano_tts.py` were already modified in
   the working tree before this work began, and are not mine to rewrite.
3. Fixing typing errors across nine unrelated modules is exactly the kind of scope
   expansion that turns a bounded phase into an unreviewable diff — and P9's brief is
   explicitly *"not to change architecture"*.

### Why it is recorded rather than ignored

Because the new lint-scope gate reports it on every run, which makes it visible without
making it P9's problem. The gate computes its scope from the changed package **plus its
dependency closure**, so it will keep surfacing this until it is addressed — without
failing any P9 phase on it.

### To close

Either fix the nine files, or baseline them the way `scripts/ci/build_ruff_baseline.py`
already does for Ruff, so the step is green and the debt is tracked rather than
accumulating silently.

---

## GAP-005 — LOCAL_PROCESS runtime availability

| | |
|---|---|
| **status** | **RESOLVED** — manim 0.21.0 installed and qualified (P9.1.b) |
| **discovered** | P9.1.a |
| **owner** | environment / runtime |
| **severity** | medium |
| **failure direction** | external blocker |

### What was found

`manim` is a declared `ProviderCatalogue` provider with
`HealthCheckKind.LOCAL_PROCESS` and no credential requirement — the ideal first real
qualification path. It cannot be installed on this machine.

```
manimpango      0.7.0    no linux wheels  -> source build; needs pango headers  (absent)
pycairo         1.29.1   no linux wheels  -> source build; needs cairo headers  (absent)
moderngl        5.12.0   cp312/cp313 only  -> no cp314; this venv is 3.14
skia-pathops    0.9.2    no linux wheels  -> source build
uid 1000, no passwordless sudo -> system headers cannot be installed
CUDA devices: 0
```

### Why this is not a P9 failure

```
P9 harness works, runtime absent      <- the situation
P9 harness broken                     <- not the situation
```

P9.1.a's harness qualifies a real subprocess end to end — real bytes, real checksum,
real receipt, real P8.4 validation — and reports `BLOCKED_BY_RUNTIME` for manim rather
than a pass. A working harness and a missing runtime are separate problems, and only one
of them is P9's.

### Resolution

`libx11-dev`, `libpango1.0-dev`, `libcairo2-dev` and `pkg-config` were installed, after
which `uv pip install manim` succeeded and **manim 0.21.0 rendered a real scene to a real
MP4**, which P9.1.b qualified end to end: 34198 bytes, `h264 / isom / 854x480 / 4.2s`,
checksum computed from those bytes, receipt issued from them, P8.4 validation passing.

`pyproject.toml` and `uv.lock` were **not** modified. So the dependency-policy question
is still open and still undecided — see below.

`pango`, `cairo` and `X11` are system libraries; `manimpango` and `pycairo` publish no
Linux wheels on any Python, so headers are unavoidable. A Python 3.12/3.13 interpreter
would solve `moderngl` only — not the two source builds.

Note for reproducibility: manim lives only in the venv, so CI's `uv sync --locked` will
not reproduce it and `test_p9_1_b_real_manim.py` self-skips when the runtime is absent
(`pytestmark`, GAP-005 reference). If manim becomes a supported runtime it belongs in
the declared dependencies — a provider-specific extra, or an external qualification
tool kept out of production dependencies. **Still undecided, deliberately.**

## GAP-006 - HTTP fleet unverified (P9.2, open)

The HTTP qualification harness is complete: state machine, credential resolver, adapter,
failure matrix, 80 tests, 5/5 mutations. **Zero HTTP providers have produced a real
artifact.** All four are BLOCKED_BY_CREDENTIAL, so GAP-002's remote coverage is unchanged
by P9.2.

Blocked on a human decision, not on code: the live variable ALIYUN_MAAS_API_KEY holds a
WaveSpeed-shaped (sk-ws-) value while WAVESPEED_API_KEY is unset and ALIBABA_MAAS_HOST is
absent. Reinterpreting it would misroute a secret and yield a 401 that reads like a
finding but is a misrouted credential.

Two defects were found and fixed on the way: an empty `checks` tuple let 1408 bytes of
ASCII qualify as video (P8.4 treats "no checks" as "nothing to disprove"), and a provider
requiring no credential could never run.
