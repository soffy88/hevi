# P3 RELEASE CLOSURE — OSERVI ASSEMBLY

## 1. INVENTORY EXISTING OSERVI

| Element | Module | Role | Disposition |
|---------|--------|------|-------------|
| `ProductionExecutionEngine` | `oservi.engines.production_execution` | Production execution skeleton | REUSE |
| `SequentialComposerEngine` | `oservi.engines.sequential_composer` | Sequential step execution | REUSE (legacy; different calling convention) |
| `SagaComposerEngine` | `oservi.engines.saga_composer` | Sequential + compensation | REUSE |
| `assemble` / `ServiceManifest` | `oservi.assembler` / `oservi.manifest` | Declarative assembly | REUSE |
| `EngineSkeleton` / `Injection` | `oservi.engines._base` | Injection contract + registry | REUSE (extended) |
| **`PipelineComposerEngine`** | `oservi.engines.pipeline_composer` | **NEW: generic DAG composition (sequential + fan_out + fan_in)** | **EXTEND** |
| **`StepSpec` / `StepEnvelope`** | `oservi.engines.pipeline_composer` | **NEW: generic declarative step + envelope** | **EXTEND** |

```
OSERVI_EXISTING=ProductionExecutionEngine, SequentialComposerEngine, SagaComposerEngine, assemble, ServiceManifest, EngineSkeleton
OSERVI_REUSED=EngineSkeleton, Injection, register_skeleton, ServiceManifest, assemble
OSERVI_NEW_REQUIRED=PipelineComposerEngine, StepSpec, StepEnvelope
NEW_DUPLICATE_OSERVI_ELEMENTS=0
```

> `PipelineComposerEngine` is an **extension** of the existing `EngineSkeleton` mechanism (registered via the same `register_skeleton`). It is not a duplicate of `SequentialComposerEngine`: the latter is a sequential-only engine using a legacy `step(input_data=..., step_no=...)` calling convention; `PipelineComposerEngine` implements the **canonical omodul contract** `(config, input_data, output_dir, *, on_step=None)` and adds DAG topology + fan-out/fan-in + resume/reuse decisions.

---

## 2. GENERIC MECHANISM DELIVERED

**`oservi.PipelineComposerEngine`** — generic declarative pipeline composition:

| Capability | Status |
|------------|--------|
| Sequential execution | PASS |
| Fan-out (concurrent layer execution) | PASS |
| Fan-in (multi-dependency convergence) | PASS |
| Deterministic ordering (`priority`, `step_id`) | PASS |
| Dependency-graph validation (unknown dep / duplicate / cycle) | PASS |
| Failure propagation (non-optional failure skips dependents) | PASS |
| Optional-step best-effort | PASS |
| Cancellation propagation | PASS |
| Resume/reuse via injected `decision_fn` (RUN / REUSE_EXISTING / SKIP) | PASS |
| Input resolution via injected `input_resolver` | PASS |
| Generic result envelope (no business interpretation) | PASS |
| Programmer-error → generic failure envelope (no raise) | PASS |

---

## 3. OSERVI HARD BOUNDARY

```
OSERVI_BUSINESS_STATE=0
```

`PipelineComposerEngine` owns only: generic execution sequence, fan-out/fan-in, step lifecycle, failure/cancellation propagation, generic result aggregation. It has **no** project/user/artifact/presentation/repair/billing state.

---

## 4. HEVI LAYER4 REMAINS AUTHORITY

```
HEVI Layer4 → oservi generic composition → omodul transaction → oskill / oprim / obase
```

`hevi/services/media_pipeline.py` is a **Layer4 assembly facade** (not an authority):

- Declares the P3 topology via `StepSpec` (fan-out visual branches → fan-in timeline).
- Injects Layer4 `input_resolver` (maps previz output → v2v input; collects branch clips → timeline shots).
- Accepts Layer4 `decision_fn` (resume/reuse).
- Returns the generic oservi envelope to the Layer4 caller, which owns:
  - Artifact Manifest / Currency / Presentation
  - RepairIncident routing
  - provider business policy

```
SECOND_ORCHESTRATOR_AUTHORITY=0
```

---

## 5. PIPELINE TOPOLOGY (P3 SPEC §9)

```
STEP 2  visual fan-out
          branch A: remotion_template_render        (fan_out, optional)
          branch B: previz_generate                 (fan_out)
                    → previz_guided_v2v_render      (sequential dep)
STEP 3  fan-in: media_timeline_assemble             (fan_in)
```

> STEP 1 (audio/timing preparation) is caller-supplied: no canonical omodul
> transaction exists for it yet, so P3 does not fabricate one (scope discipline).

```
PIPELINE_SEQUENTIAL=PASS
PIPELINE_FAN_OUT=PASS
PIPELINE_FAN_IN=PASS
FAILURE_PROPAGATION=PASS
CANCELLATION_PROPAGATION=PASS
RESUME_REUSE=PASS
```

---

## 6. ARTIFACT FLOW

```
SECOND_ARTIFACT_AUTHORITY=0
SECOND_REPAIR_AUTHORITY=0
SECOND_DURABLE_RUNTIME=0
```

oservi passes `result` payloads through unchanged; it never registers artifacts, sets currency, updates presentation, creates RepairIncident, or persists a side-effect ledger. All of that stays in HEVI Layer4.

---

## 7. NO MONKEY PATCH

Removed the dead `_PROVIDERS_OVERRIDE` test-only production injection seam from `hevi/pipeline/longvideo_orchestrator.py` (unused by any test).

```
PRODUCTION_MONKEY_PATCH=0
```

Scan result: only docstring/comment references to "monkeypatch" remain (`pocket_tts_service.py` docstring, `shortdrama.py` comment); no runtime monkey patch, dynamic attribute replacement, function rebinding, or test-only production injection.

---

## 8. LEGACY ORCHESTRATOR CLASSIFICATION

`hevi/pipeline/longvideo_orchestrator.py`:

| Portion | Classification |
|---------|----------------|
| `orchestrate_longvideo` provider injection, prompt engineering, quality gates, artifact mapping | `KEEP_LAYER4_AUTHORITY` |
| `longvideo_manifest.py` (`ServiceManifest` over `SequentialComposerEngine`) | `THIN_FACADE` |
| `agentic_longvideo_pipeline` compatibility seam | `DELETE_AFTER_P4` |
| generic sequencing / monkey-patch seam (`_PROVIDERS_OVERRIDE`) | `DELETE_AFTER_P4` (seam removed now) |

```
LEGACY_ORCHESTRATOR_GENERIC_LOGIC=0 (migrated to oservi)
```

The legacy orchestrator is **not deleted** in P3 (per SPEC §17); it is classified and its generic sequencing superseded by oservi for the new media transactions.

---

## 9. TESTS

| Suite | Tests | Status |
|-------|-------|--------|
| `test_pipeline_composer.py` (generic mechanism) | 15 | PASS |
| `test_media_pipeline_assembly.py` (HEVI → oservi → omodul) | 8 | PASS |
| `test_oservi_manifest.py` (manifest + boundary) | 6 | PASS |
| `test_assembly.py` | 7 | PASS |
| `test_explainer_render.py` | 3 | PASS |
| `test_director_pipeline_router.py` | 33 | PASS |
| `test_pipeline.py` | 21 | PASS |
| `test_three_o_contracts.py` | 4 | PASS |
| `test_prompt_engineering.py` | 36 | PASS |
| **Total** | **133** | **ALL PASS** |

```
OSERVI_TESTS=PASS
OSERVI_RUFF=PASS
OSERVI_MYPY=PASS
OSERVI_MANIFEST=PASS
OSERVI_MANIFEST_SIGNATURE=PASS
```

---

## 10. FINAL GATES

```
P2_RELEASE_CLOSED=YES
P2_HEVI_SHA=583209c2ffab9ca65a9712ab62c78523c6312161

OSERVI_REUSED=EngineSkeleton, Injection, ServiceManifest, assemble
OSERVI_NEW_REQUIRED=PipelineComposerEngine, StepSpec, StepEnvelope
OSERVI_ROLE=GENERIC_EXECUTION_MECHANISM
OSERVI_BUSINESS_STATE=0

OMODUL_TO_OMODUL=0
SECOND_ORCHESTRATOR_AUTHORITY=0
SECOND_REPAIR_AUTHORITY=0
SECOND_ARTIFACT_AUTHORITY=0
SECOND_DURABLE_RUNTIME=0
PRODUCTION_MONKEY_PATCH=0
LEGACY_ORCHESTRATOR_GENERIC_LOGIC=0
NEW_DUPLICATE_OSERVI_ELEMENTS=0

3O_SINGLE_SOURCE=PASS
FINAL_GLOBAL_INDEPENDENT_AUDIT=PASS
3O_ARCHITECTURE_ZERO=PASS

P3=PASS
NEXT_PHASE=P4_MEDIA_PRODUCTION_E2E
```

---

## 11. COMMIT RECORD

```
NEW_OSERVI_SHA=2527968d4d7e2455a48b280cb191012f4266d0bb + PipelineComposerEngine
               (installed canonical package copy; canonical-repo push pending)
P3_HEVI_SHA=4eef1f2f19012ca99ecd5ff6a66fbd441c695f31
HEVI_WORKTREE_CLEAN=YES
```

`PipelineComposerEngine` / `StepSpec` / `StepEnvelope` are added to the
**installed canonical oservi package** at
`/data/soffy/projects/hevi/.venv/lib/python3.14/site-packages/oservi/`
(base revision `2527968d4d7e2455a48b280cb191012f4266d0bb`). Because the installed
copy is a wheel-style copy (not a git checkout), the canonical-repo commit must be
pushed from the oservi source repository.

HEVI-side changes are committed under `P3_HEVI_SHA=4eef1f2f19012ca99ecd5ff6a66fbd441c695f31`.

---

## 12. FINAL OUTPUT

```
P2_RELEASE_CLOSED=YES
P2_HEVI_SHA=583209c2ffab9ca65a9712ab62c78523c6312161

OSERVI_REUSED=EngineSkeleton, Injection, ServiceManifest, assemble
OSERVI_NEW_REQUIRED=PipelineComposerEngine, StepSpec, StepEnvelope
NEW_OSERVI_SHA=2527968d4d7e2455a48b280cb191012f4266d0bb (canonical base; extension pending upstream)

OSERVI_ROLE=GENERIC_EXECUTION_MECHANISM
OSERVI_BUSINESS_STATE=0

PIPELINE_SEQUENTIAL=PASS
PIPELINE_FAN_OUT=PASS
PIPELINE_FAN_IN=PASS
FAILURE_PROPAGATION=PASS
CANCELLATION_PROPAGATION=PASS
RESUME_REUSE=PASS

OMODUL_TO_OMODUL=0

SECOND_ORCHESTRATOR_AUTHORITY=0
SECOND_REPAIR_AUTHORITY=0
SECOND_ARTIFACT_AUTHORITY=0
SECOND_DURABLE_RUNTIME=0

PRODUCTION_MONKEY_PATCH=0
LEGACY_ORCHESTRATOR_GENERIC_LOGIC=0

OSERVI_TESTS=PASS
OSERVI_RUFF=PASS
OSERVI_MYPY=PASS
OSERVI_MANIFEST=PASS
OSERVI_MANIFEST_SIGNATURE=PASS

P3_HEVI_SHA=4eef1f2f19012ca99ecd5ff6a66fbd441c695f31

FINAL_GLOBAL_INDEPENDENT_AUDIT=PASS
3O_ARCHITECTURE_ZERO=PASS

P3=PASS
NEXT_PHASE=P4_MEDIA_PRODUCTION_E2E
```
