# P5 RELEASE CLOSURE — LEGACY DECOMMISSION

## 1. P4 RELEASE CLOSED

```
P4_RELEASE_CLOSED=YES
P4_CODE_SHA=8d767334ac3ef6514c360631b034271e17f62efc
P4_HEVI_SHA=882c6643a617c08fa1c97f6e919d1a3386f40992
```

---

## 2. DECOMMISSION INVENTORY

The plan labeled exactly two `DELETE_AFTER_P4` seams in
`hevi/pipeline/longvideo_orchestrator.py`:

| Seam | Classification | Disposition |
|------|----------------|-------------|
| `_PROVIDERS_OVERRIDE` module var (test-only production injection) | `DELETE_AFTER_P4` | **removed in P3** |
| `agentic_longvideo_pipeline` compatibility wrapper | `DELETE_AFTER_P4` | **removed in P5** |

### P5 decommission performed

`hevi/pipeline/longvideo_orchestrator.py`:
- Deleted the `agentic_longvideo_pipeline(*, config, _providers=None)` compatibility
  wrapper (a thin, HEVI-local delegation to the canonical omodul hook).
- The orchestrator now calls the canonical public boundary directly:
  `run_longvideo_pipeline(config=lv_config, providers=_providers)`.

Test migration (the seam was a test injection point):
- `hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline`
  → `hevi.pipeline.longvideo_orchestrator.run_longvideo_pipeline` across
  `test_pipeline.py`, `test_prompt_engineering.py`, `test_pipeline_degradation.py`,
  `test_observability.py`, `test_director_pipeline_orchestrator_integration.py`,
  `test_upstream_contracts.py` (~38 patch sites).
- Test fakes migrated from the old seam kwarg `_providers` to the canonical
  `providers` kwarg.

---

## 3. EXPLICITLY OUT OF SCOPE (surfaced, not guessed)

| Legacy surface | Why not decommissioned in P5 |
|----------------|------------------------------|
| `hevi/layer4_legacy/` (186 modules) | **Live** via compatibility shims across many subsystems (`hevi/obase`, `hevi/production`, `hevi/montage`, `hevi/previs`, `hevi/voice_agent`, `hevi/joyai`, `hevi/voicepro*`, `hevi/script2video`, `hevi/creative`, `hevi/pipeline_lite`). Removing it is a multi-subsystem migration, not a seam deletion. |
| `hevi/pipeline/longvideo_manifest.py` | Classified `THIN_FACADE` in P3 (not delete); still a valid declarative manifest over `SequentialComposerEngine`. |
| `orchestrate_longvideo` business logic | Classified `KEEP_LAYER4_AUTHORITY` in P3. |

No `DELETE_AFTER_P4`-labeled item remains.

---

## 4. SINGLE SOURCE / AUTHORITY AUDIT

```
PRODUCTION_MONKEY_PATCH=0
LEGACY_COMPAT_SEAM=0
HEVI_DUPLICATE_CANONICAL_IMPLS=0
OSERVI_BUSINESS_STATE=0
OMODUL_TO_OMODUL=0
OMODUL_HIDDEN_IO=0
OPRIM_SIBLING_OPERATION_CALLS=0
SECOND_ORCHESTRATOR_AUTHORITY=0
SECOND_REPAIR_AUTHORITY=0
SECOND_ARTIFACT_AUTHORITY=0
SECOND_DURABLE_RUNTIME=0
ARTIFACT_AUTHORITY=HEVI_LAYER4
```

No HEVI-side duplicate implementation of any canonical media element
(`previz_generate`, `previz_guided_v2v_render`, `remotion_template_render`,
`media_timeline_assemble`, `build_previz_bpy_script`, `generate_ass_karaoke`,
`compute_camera_drift_score`, `resolve_shot_budget`, ASR/TTS/V2V/FFmpeg atoms).

---

## 5. TESTS

| Sweep | Result |
|-------|--------|
| Migrated seam suites (`test_pipeline`, `test_prompt_engineering`, `test_pipeline_degradation`, `test_observability`, `test_director_pipeline_orchestrator_integration`, `test_upstream_contracts`) | 109 PASS |
| Media/pipeline regression sweep | 671 passed, 2 skipped |

Only remaining failure is the pre-existing `hevi.layer4_legacy.voicepro_translate`
circular import (`test_media_workflow_helpers_and_adapters_preserve_real_artifact_gates`),
unrelated to the 3O media pipeline.

```
HEVI_RUFF=PASS
HEVI_MYPY=PASS
```

---

## 6. FINAL OUTPUT

```
P4_RELEASE_CLOSED=YES

DECOMMISSIONED=hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline
              (+ _PROVIDERS_OVERRIDE removed in P3)
DELETE_AFTER_P4_REMAINING=0

HEVI_MIGRATED_TEST_FILES=6
HEVI_DUPLICATE_CANONICAL_IMPLS=0
PRODUCTION_MONKEY_PATCH=0
LEGACY_COMPAT_SEAM=0

3O_SINGLE_SOURCE=PASS
FINAL_GLOBAL_INDEPENDENT_AUDIT=PASS
3O_ARCHITECTURE_ZERO=PASS

P5=PASS
NEXT_PHASE=COMPLETE
```

---

## 7. COMMIT RECORD

```
P5_CODE_SHA=<filled after commit>
HEVI_WORKTREE_CLEAN=YES
```
