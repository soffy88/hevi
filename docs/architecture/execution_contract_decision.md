# HEVI-P0-EXECUTION-CONTRACT-001 — reuse decision

Spec §63 orders the work; rule 5 requires extending an existing authority rather
than adding a parallel one. This records what already exists, so every "new" type
below is justified by absence rather than by not having looked.

Surveyed at HEAD `42f2523d`.

## What already exists

| Concern | Existing authority | Fate |
|---------|--------------------|------|
| Execution attempt | `hevi/execution/models.py::ExecutionRun`, `ExecutionState`, `ExecutionFailure` | **extend** |
| Proof of production | `hevi/execution/models.py::ProductionReceipt` | **extend / relate** |
| Artifact record | `hevi/production/artifacts.py::Artifact` (sha256, artifact_id, uri, kind, path) | **reuse** |
| Mission graph | `hevi/missions/p3_types.py::PlanNode` (dependencies, idempotency_key, artifact_ids, max_attempts) | **project from** |
| Mission execution | `hevi/missions/p3_runtime.py::MissionExecutor` | **integrate** |
| Timeline | `hevi/production/timeline_ir.py::TimelineIR` | **canonical, unchanged** |
| Provider capability | `hevi/providers/facts.py::ProviderProfile` | **canonical** (converged in P0-4.2.2) |
| HTML/Gsap | `hevi/renderers/html_gsap.py::HtmlGsapRenderer`, input `RenderPlan` | **canonical, compile into it** |
| Verdict | `hevi/creative/autonomous/verdict.py::ProductionVerdict`, `ProductionVerdictAuthority` | **extend** |
| Artifact validation | `hevi/validation/artifact.py::ValidationResult` | **reuse** |
| Scheduling | `hevi/execution/scheduler.py::Scheduler` | **reuse for ranking only** |

Genuinely absent: `ProductionOperation`, `RenderJob`, `RenderReceipt`,
`VisualSceneIR`, any transaction abstraction, `OperationValidator`.

## Reuse decisions

### ArtifactRef vs Artifact — reference vs record

`Artifact` is the *record*: path, bytes, size, integrity, producer.
`ArtifactRef` is the *reference*: id, hash, uri. An operation needs a reference; a
manifest needs a record.

`ArtifactRef` is constructed only by `ArtifactRef.from_artifact()` and carries no
lifecycle state, because artifact lifecycle lives in `ArtifactManifest` and, at the
mission level, in `ArtifactRecord`. Two types, one direction of construction, tested.

### ProductionOperation vs PlanNode — dialect vs plan

`PlanNode` is the mission planner's node: `kind`, `dependencies`, `payload`,
`idempotency_key`, `attempts`. `ProductionOperation` is the execution dialect:
typed operation kinds, explicit input/output expectations, provider/renderer/encoder
refs.

They are not merged because a plan node is a scheduling concern and an operation is a
contract. They are not duplicated because **`PlanNode` alone decides executability** —
it does not. `ProductionOperation` is derived from a `PlanNode` and is what adapters
receive. A test asserts no executor accepts a bare `PlanNode`.

### ExecutionFailure — enum vs record

`ExecutionFailure` (StrEnum) is the existing vocabulary: SOURCE_MISSING,
EXECUTOR_FAILED, VALIDATION_FAILED, and so on. The spec's `ExecutionFailure` is a
*record* carrying operation_id, retryable, transaction_id.

The enum is kept and referenced. The record is `ExecutionFailureRecord`. Defining a
second class named `ExecutionFailure` in the same package would repeat the
`ExecutionReceipt` collision that `hevi/execution/models.py` documents at length.

### RenderReceipt vs ProductionReceipt

`ProductionReceipt` proves *an artifact was produced and validated*, requiring a
`ValidationResult` that observed the same bytes.

`RenderReceipt` proves *a render ran with these inputs and this renderer version*,
carrying timeline/scene hashes and ffprobe output.

Both are real and neither derives from the other. `hevi/execution/models.py` sets the
precedent for exactly this pair and explains it. `RenderReceipt` does **not** replace
`ProductionReceipt`: a render receipt alone is not production proof, because it does
not require artifact validation to have observed the bytes.

### ProductionVerdict — REPAIR_REQUIRED is additive

Existing `VerdictOutcome` is PASS / FAIL / BLOCKED, where BLOCKED means *insufficient
evidence, never run* — a load-bearing distinction ("证据不足/未跑,不是失败").

The spec asks for REPAIR_REQUIRED, which is a different thing: a *diagnosed
fixable* failure. Both are added/kept. Replacing BLOCKED would destroy the discipline
that an unrun check is not a failure.

## What is genuinely new

| Phase | New | Why |
|-------|-----|-----|
| P0.1 | `ProductionOperation`, `ProductionOperationType`, `ArtifactRef`, `ResourceRef`, `ArtifactExpectation` | no execution dialect exists |
| P0.2 | `ExecutionResult`, `ExecutionFailureRecord` | enum exists, record does not |
| P0.3 | `ProductionExecutionTransaction`, `TransactionSnapshot`, `TransactionReceipt`, `RollbackReceipt` | no transaction anywhere in the repo |
| P0.4 | `RenderJob`, `RenderJobStatus`, `RenderReceipt` | no render-job abstraction |
| P0.5 | `VisualSceneIR` + element/animation/transition specs | no renderer-independent scene |
| P0.8 | `hevi/adapters/openreel/` | OpenReel is not present |

## Non-goals confirmed

- No second Director, Timeline, Provider resolver, Asset selector, Validation engine,
  Repair engine, MissionExecutor or semantic planner.
- No parallel orchestration authority: `MissionExecutor` remains the only executor.
- HTML/Gsap stays in `hevi/renderers/html_gsap.py`. `VisualSceneIR` compiles *into*
  `RenderPlan`; it does not replace the renderer.
- `ProviderProfile` stays the only provider capability authority.

## Gate honesty

`HEVI-P0-EXECUTION-CONTRACT-001` is COMPLETE only at 20/20 (§61). Until the real-media
E2E (§53) produces a real MP4, a real ffprobe and a real validation PASS, the status
is PARTIAL regardless of how many contracts exist.
