# Architecture Decision: OpenShorts Integration — Naming Mapping (P2)

Date: 2026-10-05
Status: ACCEPTED
Governing spec: Production Engineering Specification v2.0 (`docs/specs/`), §1.3, §9, §10, §16, §22 Gate A/C, §23, §24

## Context

The spec's authority chain names four HEVI-side types:

```
CreativeIntent → CreativeProgram → ShotIntent → Canonical ShotSpec
→ HyperFrame → Qualified Executor → Execution → Artifact
→ Verification → Evidence → Receipt → Revision/ACCEPT
```

The P0/P1 audit found that **three of those names are not types that exist in HEVI**:

| Spec name | Audit result |
|---|---|
| `ExecutorRegistry` | Zero hits repo-wide. No admission gate for executors or providers exists. |
| `Qualified Executor` | Nearest existing concept: `hevi/qualification/models.py:136 ProviderQualification` (a Protocol whose docstring states "Executes one provider. Judges nothing.") |
| `HyperFrame` | One grep hit: `hevi/qualification/providers/hyperframes.py:53 HyperFramesExecutionConfig` — a timeout/locator config, not a creative intermediate. |
| `Artifact` / `Verification` / `Evidence` / `Receipt` | **Exist.** `hevi/validation/artifact.py`, `hevi/creative/autonomous/verdict.py`, `hevi/evidence/`, `hevi/execution/`. |

Meanwhile §23 forbids `create a second provider registry`, `create a second verification
authority`, and `invent a new RunState`. And §10/§22-Gate-A require enforcing a provider
admission gate that does not exist.

Building the missing types would have violated the spec's own non-goals. So we **map the
spec's abstract names onto the seams HEVI already has**, and add mechanical guards so the
mapping cannot silently rot.

## Decision

### D1 — `ExecutorRegistry` maps to a *composition* of three existing seams

There is no single registry. Provider authority in HEVI is:

```
provider_policy.PolicyEngine.evaluate_provider_policy()   ← policy/cost/quota
        +
generation.evidence.CapabilityEvidence.try_admit()        ← runtime readiness + local verification
        +
qualification.ProviderQualification (Protocol)            ← executes, judges nothing
        +
creative.autonomous.selection.admit_generation()         ← the sole "start generating" seam
```

Two admission seams already exist and are already declared authoritative in code:

- `hevi/creative/autonomous/selection.py:202-211` — *"generation admission seam：唯一允许「开始生成」的判定点"*
- `hevi/creative/autonomous/canonical.py` `KNOWN_SPLITS` — registers the `ProviderPolicy/ProviderDecision`
  split as a *known, registered* split rather than pretending it was unified.

**What we did not do:** we did not build an `ExecutorRegistry` class. Doing so would have
created the second provider registry §23 forbids.

**Known residual (recorded, not fixed here):** `ProviderRegistry.get()` has 60 call sites
across 42 production files and `evaluate_provider_policy` has 3. The policy engine is
advisory. This is pre-existing and unchanged by this decision.

### D2 — `HyperFrame` maps to `HyperComposition`

`hevi/providers/hyperframes/compiler.py:13-36`:

```python
@dataclass
class HyperClip:
    start_s: float
    duration_s: float
    text: str
    kind: str = "title"          # title | card | quote | end

@dataclass
class HyperComposition:
    title: str
    width: int = 1920
    height: int = 1080
    fps: int = 30
    clips: list[HyperClip] = ...
    css_vars: dict[str, str] = ...
    design_md: str = ""
    declared_duration_s: float | None = None
```

This is the ShotSpec→executable-visual-structure translation the spec's Phase C asks for.
**It has no hash function**, so spec §9's `HyperFrame hash` evidence field has no producer
yet. Recorded as open debt; not silently ignored.

The spec's "no provider-specific prompt may become the canonical creative representation"
is satisfied by `canonical.py`'s existing guard.

### D3 — Verification: three levels today, not four

Spec §7 defines V0 (existence), V1 (media validity), V2 (contract compliance), V3 (creative).
HEVI has no `VerificationLevel` enum. What exists:

| Spec level | Existing HEVI seam |
|---|---|
| V0 | `hevi/validation/artifact.py` `ValidationCheck(operator=CheckOperator.NON_EMPTY)` |
| V1 | `hevi/production/delivery_gate.py:50 probe_video()` (ffprobe); `hevi/verdict/case_dimensions.py:48 _probe()` |
| V2 | ShotSpec compliance — **no single owner** (`docs/CURRENT_ARCHITECTURE_MAP.md` §3.3: 6 evaluators + 4 gate modules) |
| V3 | `hevi/creative/autonomous/verdict.py ProductionVerdictAuthority` (aggregator, runs zero evaluators) |

We did not add a fourth vocabulary. The aggregator's existing fail-closed contract is
asserted by `tests/p10/test_s1_canonical_authority.py` and now also by
`tests/test_openshorts_integration_gates.py`.

### D4 — Fail-closed is now mechanical, and it was not

The audit found three live paths where *unknown became PASS*. These were defects against
spec §7/§8 ("Unknown MUST NOT become PASS") and are now closed:

| Path | Before | After |
|---|---|---|
| `hevi/verdict/case_dimensions.py:93` | `"status": "PASS", "passed": True` with **14 of 15** dimensions `NOT_OBSERVED`; persisted to `shot_verdict.passed=True` | `CaseVerdictStatus` derived from dimension statuses; a probe alone yields `NOT_OBSERVED` / `passed=False` |
| `hevi/studio/ops.py:493` (`qc.production`) | `except Exception: return _ok(verdict={"ok": True})` — any exception, including import failure, reported success | `return _blocked("QC_PRODUCTION_NOT_EVALUATED", ...)` |
| `hevi/studio/ops.py:496-508` (`qc.layout`, `qc.motion`, `qc.gate.*`) | 7 tools returned unconditional `ok=True` with zero observation | all return `status="blocked"`, `passed=None` |

`blocked` was chosen over `failed` because it is already in HEVI's live vocabulary
(`ProductionVerdictOutcome.BLOCKED`: *"证据不足/未跑，不是失败"*) and because a missing
evaluator is not a defect in the artifact.

### D5 — The 182-tool studio registry is the canonical semantic surface

`hevi/studio/tools.py` already matches spec §16 exactly (`ToolSpec`/`ToolResult` frozen
dataclasses, `register_tool`, `invoke_tool`). 182 dotted IDs registered at import time.

Per spec §1.4/§23 we did **not** mass-rewrite MCP. MCP has 23 tools; 5 are semantic
duplicates of studio/REST and share the same underlying function; 18 have no studio
counterpart. New capabilities converge on the studio registry (OS-02), existing duplicates
stay until parity tests prove equivalence.

## Consequences

**Accepted:**
- Gate A is now checkable: no second registry can be added without turning a test red.
- Gate C's core invariant ("artifact existence ≠ success", "unknown ≠ PASS") is enforced
  by test, not by convention.
- A real artifact that probes cleanly can no longer be auto-promoted to a creative pass.

**Owed / open debt (recorded in STATUS.md):**
- V2 (ShotSpec contract compliance) has no single owner.
- `HyperComposition` has no content hash, so spec §9's `HyperFrame hash` field has no producer.
- `ProviderRegistry.get()` is called directly in 60 places; provider policy is advisory.
- `qc.layout` / `qc.motion` / `qc.gate.*` now report `blocked` — they have **no evaluator**.
  They are honest, but they are not yet useful. Wiring real evaluators is future work.
- `hevi/services/drama_integration.py:90` calls `invoke_tool("slate_update")`, which is not
  a registered tool; the result is discarded. Pre-existing silent no-op, not touched here.

## Rejected alternatives

1. **Build `ExecutorRegistry` + `HyperFrame`.** Rejected: §23 forbids a second provider
   registry; it would have been the largest architecture change in the repo with no video.
2. **Rename existing types to match the spec's names.** Rejected: churn across 42 files,
   zero semantic gain, and `ProviderRegistry` is owned by `obase` — HEVI cannot rename it.
3. **Leave the fail-open paths and note them.** Rejected: they are live correctness defects
   that make Gate C unprovable. They were cheap to close.