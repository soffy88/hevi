# HEVI P9 — Local Render Provider Authority Audit

**TASK** `HEVI_LOCAL_RENDER_PROVIDER_AUTHORITY_AUDIT`
**MODE** read-only · no production change · no provider registration · no execution
driver · no dependency install
**Targets** `remotion`, `hypermotion`

---

## Verdict

**Both targets are disqualified for P9.1.c / P9.1.d — for different reasons.**

| | verdict | reason |
|---|---|---|
| `remotion` | **NOT READY** | runtime missing; and its existing renderer mixes render with verification |
| `hypermotion` | **NOT FOUND** | zero occurrences anywhere in the repository |

Neither may be registered. Registration would create authority that does not exist
yet, which is the P6.5 / P7 drift this audit was commissioned to prevent.

---

## 1. Provider inventory

| | remotion | hypermotion |
|---|---|---|
| exists | **yes** — P5.2-era renderer backend | **no** |
| where | `hevi/renderers/remotion.py` (182 lines) | — |
| other references | `hevi/assembly/remotion_render_workflow.py`, `hevi/assembly/remotion_render.py`, ~60 HEVI modules | — |
| npm package | `remotion@4.0.261`, **only** under `outputs/jingke-remotion/node_modules/` (untracked output artifact) | n/a |
| reference material | `docs/ref-repos/claude-code-video-toolkit/**/remotion.config.ts` | n/a |
| in `ProviderCatalogue` | **no** (catalogue holds 16 providers) | **no** |
| in `RUNTIME_SPECS` | **no** | **no** |

### The 623 `find` hits were mostly noise

`find . -iname "*remotion*"` returns 623 paths. The large majority are output MP4s named
`local_media_**remotion**.mp4` — the substring `remotion` appears inside
`*_media_remotion*`, matching "mo**tion**"-adjacent text, not the library. Filtering to
real Remotion artefacts: `node_modules/remotion`, `node_modules/@remotion/*`, and
`remotion.config.ts` files under a reference repo.

**No `hevi/` source imports the `remotion` package.** The 60 modules that mention
"remotion" reference HEVI's own `RemotionRenderer`, not the npm library.

---

## 2. Authority map

| question | owner | file |
|---|---|---|
| **Provider identity owner?** | `ProviderCatalogue` | `hevi/providers/facts.py` |
| **Provider capability owner?** | `ProviderProfile.kind` + `PROVIDER_LIMITS` | `hevi/providers/facts.py`, `hevi/video/capability_guard.py` |
| **Provider facts owner?** | `ProviderProfile` (locality, licence class) | `hevi/providers/facts.py` |
| **Runtime driver owner?** | `DriverRegistry` + `LocalLiveDriver` | `hevi/runtime/live/drivers.py` |
| **Artifact validation owner?** | `qualify()` + `ValidationCheck` | `hevi/artifact/qualify.py`, `hevi/validation/artifact.py` |
| execution proof | `ProductionReceipt` | `hevi/execution/models.py` |
| observation coverage | `RUNTIME_SPECS` | `hevi/providers/runtime_specs.py` |

Full map: `docs/LOCAL_RENDER_AUTHORITY_MAP.md`.

**Neither target has an entry in any of these.** Remotion exists *outside* the authority
system entirely — it is a renderer, not a provider.

---

## 3. Runtime classification

Classified from the **actual execution mechanism**, not from the name.

### remotion → `LOCAL_PROCESS`

Evidence, not inference:

```python
# hevi/renderers/remotion.py:143
proc = subprocess.run(["npx", "--no-install", "remotion", "render",
                       composition, str(target), "--props=...", ...],
                      cwd=str(self.project))
```

It is a **node process driven as a subprocess** — not a CLI binary on PATH, not an HTTP
API, not a queue. `LOCAL_PROCESS` is the correct classification; `CLI` would be wrong
because `npx` is a node runner, not a purpose-built renderer binary.

Readiness is declared, not guessed:

```python
self.available = (shutil.which("npx") is not None
                  and (self.project / "package.json").is_file()
                  and (self.project / "node_modules").is_dir())
```

### hypermotion → **cannot classify**

Nothing to classify. No implementation, no reference, no package declaration, no script.
Recording a classification here would be inventing one.

---

## 4. Missing dependencies

```
node                       v26.4.0     PRESENT
npx                        12.0.1      PRESENT
npm                        12.0.1      PRESENT
remotion (resolvable from HEVI root)     MISSING
  -> node -e "require.resolve('remotion')" fails
remotion@4.0.261 present only under
  outputs/jingke-remotion/node_modules/   UNTRACKED output artifact
HEVI_REMOTION_PROJECT env var            not set
remotion project dir in HEVI tree         absent (no package.json + node_modules)
```

`RUNTIME_STATUS`:

| provider | status |
|---|---|
| remotion | **MISSING** — toolchain present, package absent |
| hypermotion | **UNKNOWN** — nothing installed, nothing declared |

Remotion would be a *declaration* away from being observable, but declaring a runtime
spec for an absent package would produce `BLOCKED_BY_RUNTIME` forever and add an
unfalsifiable catalogue entry. That is the "declared capability ≠ verified" gap P8
closed.

---

## 5. Artifact chain compatibility

### remotion

Output format is **MP4**:

```python
target = output_dir / f"{plan.shot_id}_remotion.mp4"
proc = subprocess.run(["npx", "--no-install", "remotion", "render",
                       composition, str(target), ...])
```

So its artifact type is directly compatible with the chain:
`ArtifactDescriptor → AcquiredSource → ProductionReceipt → ArtifactValidation`.
MP4 is exactly what P8.4's `probe_containerised` observes from bytes, and what P9.1.b
already qualified.

### hypermotion

**Unknown.** No output format is declared anywhere, because nothing exists. `webm`,
image sequences and audio are equally plausible — which is precisely why no artifact
contract can be recorded.

---

## 6. Architecture risks

### R1 — CRITICAL: the existing Remotion renderer owns artifact truth

`hevi/renderers/remotion.py` mixes rendering with verification:

```python
def _hash_file(path: Path) -> str: ...        # line 37  — checksum inside the renderer
def _probe_duration(path: Path) -> float:      # line 45  — ffprobe inside the renderer
```

It calls `subprocess.run(["ffprobe", ...])` to read duration, and hashes the output
file itself. **This is precisely the boundary P8.4 established.** P8.4's rule:

> The probe reads, `qualify` compares, and nothing in the package can write, repair or
> transcode what it inspects.

Registering `remotion` as a provider *as it stands* would give the renderer its own
artifact proof — a second artifact authority, and a validator that can also be
influenced by the thing it validates.

**Remediation required before any registration:** the renderer must return a locator and
stop proving. `LocalLiveDriver` → `read_artifact` → `checksum_bytes` → `issue_receipt` →
`qualify` already implements the correct split, and P9.1.b proved it end to end.

### R2 — MEDIUM: two disjoint registries again

The same structural gap P8.1.5 found: `PROVIDER_SPECS` (8 infrastructure providers)
versus `RUNTIME_SPECS` (13 video/local providers) overlap by **2**. Remotion sits in
neither. A renderer existing in `hevi/renderers/` is currently invisible to provider
policy, so it can be invoked by ~60 modules without ever appearing in a decision record.
That is the pre-P7 condition, not a new risk — but Remotion is a live example of it.

### R3 — MEDIUM: a qualification module that selects providers

`hevi/qualification/framework.py:99`:

```python
def _provider_needs(recipe: dict[str, Any]) -> list[str]:
    ... return ["h3_local"]
```

A module inside `hevi/qualification/` names a provider in code. Provider selection is
`ProviderPolicy`'s job; a qualification helper that hard-codes one is a miniature second
selection authority. Pre-existing, and outside P9's scope to fix — recorded here because
P9.1.c/d would extend that same package.

### R4 — LOW: vendor branching in probe configuration

`hevi/provider_policy/runtime.py` contains 16 provider-id comparisons
(`pexels`, `mpt`, `joyai`, `pocket_tts`, `longcat`, `voicebox`…) for auth headers and
special-cased handshakes.

This is **not** fact inference and does not breach the P7.1 boundary — locality
inference is clean (verified: zero `startswith`/`split`/`regex` against locality tokens
across `hevi/providers/`, `hevi/provider_policy/`, `hevi/production/p7/`,
`hevi/runtime/live/`, `hevi/qualification/`). It is *how to reach* a provider, not
*what it is*, and P8.1 documented `PROVIDER_SPECS` as the probe-config authority.
Recorded so it is not mistaken for a clean bill of health on vendor branching generally.

---

## 7. Qualification readiness

```
Provider      Identity  Policy  Runtime  Driver  Artifact  Ready
manim         PASS      PASS    PASS     PASS    PASS      QUALIFIED
remotion      ABSENT    ABSENT  MISSING  NONE    PASS*     NOT READY
hypermotion   ABSENT    ABSENT  UNKNOWN  NONE    UNKNOWN   NOT FOUND
```

\* remotion's MP4 output *format* is compatible; that is the only row it passes.

Neither target is ready, and neither is close:

- **remotion** needs a real package in a real project directory, **and** the
  render/verify separation in R1 fixed, before registration would be honest.
- **hypermotion** needs to exist.

---

## Mutation checks

Verified against the guards already shipped, not by re-mutating (this audit is read-only).

| | check | evidence |
|---|---|---|
| **M1** | adding a provider need not change policy | `test_catalogue_is_the_only_fact_source`, `test_i4_policy_cannot_mutate_the_catalogue`; remotion/hypermotion **were** added to nothing and policy is byte-identical |
| **M2** | missing runtime → `BLOCKED_BY_RUNTIME` | `test_matrix_executable_absent_is_blocked_by_runtime`, `test_missing_command_is_blocked_by_runtime` — both green |
| **M3** | exit 0 + no bytes → `REJECTED` | `test_exit_zero_without_an_artifact_is_rejected`, `test_an_artifact_that_reads_as_empty_is_rejected` — both green |
| **M4** | path exists without validation → not qualified | `test_a_locator_alone_is_still_not_proof`, `test_no_reader_means_no_qualification` — both green |

M3/M4 were both strengthened during P9.1.b after a mutation showed verdict alone was too
coarse to distinguish "nothing was produced" from "what was produced is invalid".

---

## Acceptance gate

| gate | result |
|---|---|
| `NO_SECOND_PROVIDER_AUTHORITY` | **PASS** — neither target registered; catalogue unchanged at 16 |
| `NO_PROVIDER_ID_HEURISTIC` | **PASS** — zero locality inference; see R4 for probe-config branching |
| `NO_SECOND_ARTIFACT_PROOF` | **PASS with exception** — the P9 chain is clean; **R1 is a pre-existing breach in `hevi/renderers/remotion.py`**, not in P9 |
| `DRIVER_VALIDATOR_SEPARATION` | **PASS** — `hevi/runtime/live/drivers.py` imports no ffprobe, no hashlib, no validator, no policy |
| `REMOTION_CLASSIFIED` | **PASS** — `LOCAL_PROCESS`, from `npx` subprocess evidence |
| `HYPERMOTION_CLASSIFIED` | **PASS** — classified as *absent*, which is the only honest classification |

The gate passes for the audit's own scope. R1 is reported, not silently absorbed: it is a
real breach in a pre-P7 module, and it is the one thing that must be fixed before
P9.1.c could ever be attempted.

---

## Recommendation

**Do not proceed to P9.1.c or P9.1.d.**

1. **remotion** — install `remotion` into a real HEVI-owned project directory (not an
   untracked `outputs/` artifact), then fix R1 so the renderer returns a locator instead
   of proving its own output. Only then does an identity/policy/runtime row mean
   anything. The dependency-policy question from P9.1.b (declared extra vs external tool)
   is still undecided and applies here too.
2. **hypermotion** — nothing to qualify. If it is a real dependency, it has to be
   declared before it can be audited; if it is a typo or a speculative name, it should
   be dropped from the target list rather than carried as `UNKNOWN`.
3. **R2 and R3** — worth scheduling regardless of Remotion. A renderer invocable by 60
   modules while invisible to provider policy is the P6.5 condition reappearing in a new
   place.
