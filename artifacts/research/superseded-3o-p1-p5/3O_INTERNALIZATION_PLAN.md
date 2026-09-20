# HEVI MEDIA PIPELINE 3O INTERNALIZATION — CORRECTED PLAN

> **Source of truth:** External 3O libraries (git-pinned): `obase`, `oprim`, `oskills`, `omodul`, `oservi`
> **HEVI Layer4:** Single product authority — Production Graph, Artifact Manifest, Artifact Currency, Presentation Read Model, ProviderCallRecord, RepairIncident
> **Constraint:** Zero duplicate authorities, zero second orchestrator, zero omodul→omodul calls

---

## 0. INVENTORY — EXISTING vs REUSE vs NEW (REVALIDATED)

### EXISTING (External 3O Libraries — git-pinned, immutable)

| Layer | Package | Key Exports Used by HEVI |
|-------|---------|--------------------------|
| **obase** | `obase` | `ProviderRegistry`, `PgPool`, `ffmpeg.run`, `CostTracker`, `GpuScheduler`, `ModelRegistry`, `jwt_create/verify`, `argon2_hash/verify`, `McpClientRegistry`, `MCPServer`, `ProviderLiveState`, `observability.track_provider_call`, `tracing` |
| **oprim** | `oprim` | `probe_duration`, `edge_tts_word_boundary`, `video_generate`, `adapt_prompt_for_provider`, `inject_visual_style`, `provider_health_check`, `canvas_node_execute`, `canvas_edge_validate`, `character_three_view`, `first_last_frame_transition`, `multi_angle`, `story_predict`, `storyboard_grid`, `video_element_edit`, `hevi_types` (CanvasNode, CanvasEdge) |
| **oskills** | `oskills` | `storyboard_planner`, `web_research`, `canvas_workflow_executor`, `character_consistency_workflow`, `comic_to_animation_workflow`, `multi_shot_storyboard_workflow`, `schemas` (Script, SubjectRef, Chapter, ChapterScript, SpeakerLine, Storyboard) |
| **omodul** | `omodul` | `longvideo_produce` (LongVideoConfig, LongVideoResult, `longvideo_produce`, `default_longvideo_shot_generator`, `rework_longvideo_shots`, `run_longvideo_pipeline`), `narrated_video_produce`, `presenter_video_produce`, `shot_rework_produce`, `video_assemble_workflow` |
| **oservi** | `oservi` | `SequentialComposerEngine` |

---

### RECLASSIFIED PROMOTION MAP (HEVI → 3O)

| HEVI Module | Current Role | 3O Classification | Target 3O Layer/Asset | Rationale |
|-------------|--------------|-------------------|----------------------|-----------|
| `hevi.assembly.assembler` | Full timeline assembly (normalize, concat, xfade, audio mix, subtitle burn, encode, cover extract) | **EXTRACT_MECHANISM_TO_OBASE** + **PROMOTE_TRANSACTION_TO_OMODUL** | `obase.media.ffmpeg` (atomic primitives) + `omodul.media_timeline_assemble` (transaction) | Assembler contains business policy (transition rules, loudness targets, color normalization, BGM ducking) — stays Layer4 transaction. Only FFmpeg subprocess invocation primitives extracted to obase. |
| `hevi.artifact_store` | Artifact persistence, metadata, currency, presentation | **KEEP_LAYER4** | — | **HEVI Layer4 authority**. Calls `obase.storage.blob_store` for content-addressed storage only. |
| `obase.storage.blob_store` | (new) Content-addressed put/get/delete, SHA256, dedupe | **REUSE_EXISTING_3O** (extend) | `obase.storage.blob_store` | Mechanism only. No project/user/Presentation knowledge. |
| `hevi.obase.provider_presets` | Preset→provider resolution table | **KEEP_LAYER4** | — | Business preset definitions (cost/quality tiers). Registers into `obase.ProviderRegistry` at startup. |
| `obase.ProviderRegistry` | Runtime provider routing, capabilities, health | **REUSE_EXISTING_3O** | `obase.ProviderRegistry` | Canonical provider registry. HEVI extends via registration only. |
| `hevi.assembly.subtitle_align.transcribe_to_cues` | faster-whisper ASR → word timestamps | **PROMOTE_ATOM_TO_OPRIM** | `oprim.asr_transcribe_audio` | Single external call (model inference). Pure atomic primitive. |
| `hevi.audio.edge_tts_custom.synthesize_with_voice_control` | edge-tts per-line rate/pitch/voice → concat WAV | **PROMOTE_ATOM_TO_OPRIM** | `oprim.tts_synthesize_stream` (provider=edge_tts) | Single semantic operation: text→audio with prosody control. |
| `hevi.audio.tts_service.vibevoice_synthesize` | VibeVoice multi-speaker subprocess | **PROMOTE_ATOM_TO_OPRIM** | `oprim.tts_synthesize_stream` (provider=vibevoice) | Single semantic operation. Subprocess isolation is implementation detail. |
| `hevi.video.local_fallback.render_animation_fallback_async` | Freevideo HTML→MP4 deterministic animation | **PROMOTE_ATOM_TO_OPRIM** | `oprim.blender_render_headless` (engine=freevideo) | Single external render call. Engine pluggable (Blender/freevideo). |
| `hevi.explainer.render._run_remotion_render` | Remotion CLI render single composition | **PROMOTE_ATOM_TO_OPRIM** | `oprim.remotion_render_component` | Single external render call. |
| `hevi.layer4_legacy.joyai.omodul_impl.stream_edit` | JoyAI streaming V2V session workflow | **PROMOTE_TRANSACTION_TO_OMODUL** | `omodul.previz_guided_v2v_render` | Business transaction: previz structure lock + V2V + drift gate. |
| `hevi.layer4_legacy.previs.omodul_impl.runtime.compile_previs_scene` | PrevisScene → SceneStage handoff | **PROMOTE_TRANSACTION_TO_OMODUL** | `omodul.previz_generate` | Business transaction: shot_spec → previz video. |
| `hevi.explainer.render.render_storyboard` | Storyboard → Remotion MP4 (dub, manifest, render, BGM, avatar) | **PROMOTE_TRANSACTION_TO_OMODUL** | `omodul.remotion_template_render` | Business transaction: composition_id + props → rendered segment. |
| `hevi.assembly.subtitle_align.cues_to_srt` | Cue list → SRT text | **PROMOTE_PURE_ALGO_TO_OSKILL** | `oskills.subtitle.cues_to_srt` | Pure text transformation. No IO. |
| `hevi.assembly.assembler` duration allocation logic | Audio-driven shot duration allocation | **PROMOTE_PURE_ALGO_TO_OSKILL** | `oskills.timeline_math.calc_timecode_alignment` | Pure math: ASR ms → frame numbers. |
| `hevi.layer4_legacy.previs.oskill_impl.compiler.camera_from_instruction` | NL instruction → CameraCue | **PROMOTE_PURE_ALGO_TO_OSKILL** | `oskills.previz_compiler.build_previz_bpy_script` | Pure compilation: shot_spec → bpy script text. |
| `hevi.pipeline.longvideo_orchestrator._single_variant` logic | Shot variant budget by quality/duration | **PROMOTE_PURE_ALGO_TO_OSKILL** | `oskills.budget.resolve_shot_budget` | Pure calculation. |
| `hevi.assembly.assembler` color normalization | Cross-provider brightness correction | **PROMOTE_PURE_ALGO_TO_OSKILL** | `oskills.quality.compute_luma_correction` | Pure math: luma measurement → eq brightness delta. |
| `hevi.verdict.scorecard.make_scorecard_consistency_fn` | Identity embedding comparison | **PROMOTE_PURE_ALGO_TO_OSKILL** | `oskills.quality.compute_camera_drift_score` | Pure math: motion vectors → angular variance [0,1]. |
| `hevi.pipeline.longvideo_orchestrator` | Monkey-patched provider injection, hardcoded flow | **DELETE_AFTER_MIGRATION** | — | Replaced by oservi composition + Layer4 service facade. |

---

### NEW_REQUIRED (Must Create — Canonical 3O Assets)

| Layer | Asset | Spec |
|-------|-------|------|
| **obase.media.blender** | `blender_render_headless` primitive wrapper | Subprocess Blender + Xvfb/Workbench, returns MP4/PNG seq |
| **obase.media.ffmpeg** | Atomic FFmpeg primitives (see §5) | `ffmpeg_concat`, `ffmpeg_mux_audio`, `ffmpeg_burn_subtitles`, `ffmpeg_encode`, `ffmpeg_probe`, `ffmpeg_extract_cover` |
| **obase.storage.blob_store** | Content-addressed storage mechanism | `put(bytes) → BlobRef`, `get(BlobRef) → bytes`, `delete(BlobRef)`, `path(BlobRef) → Path` |
| **oprim** | `asr_transcribe_audio` | Single call, returns word-level timestamps + cost |
| **oprim** | `tts_synthesize_stream` | Single call, returns audio + metadata + cost |
| **oprim** | `blender_render_headless` | Single call, executes .py script → MP4 |
| **oprim** | `remotion_render_component` | Single call, renders one Remotion component |
| **oprim** | `v2v_dispatch_infer` | Single call, ref_video + prompt → stylized video + motion vectors + cost |
| **oskills** | `calc_timecode_alignment` | ASR ms → frame numbers, drift elimination |
| **oskills** | `build_previz_bpy_script` | ShotSpec → deterministic bpy script text |
| **oskills** | `cues_to_srt` | Cue list → SRT text |
| **oskills** | `generate_ass_karaoke` | Aligned words + style → ASS with `\k` |
| **oskills** | `compute_camera_drift_score` | Previz vs V2V motion vector angular variance |
| **oskills** | `resolve_shot_budget` | Duration archetype + quality → variant count |
| **oskills** | `compute_luma_correction` | Luma measurement → eq brightness delta |
| **omodul** | `previz_generate` | Canonical transaction contract |
| **omodul** | `previz_guided_v2v_render` | Canonical transaction contract |
| **omodul** | `remotion_template_render` | Canonical transaction contract |
| **omodul** | `media_timeline_assemble` | Canonical transaction contract |

---

## 1. ARTIFACT AUTHORITY (CORRECTED)

```
ARTIFACT_AUTHORITY=HEVI_LAYER4
BLOB_STORAGE_MECHANISM=obase.storage.blob_store
SECOND_ARTIFACT_AUTHORITY=0
```

**Model:**
- **HEVI Layer4** owns: Artifact Manifest, Artifact Currency, Presentation Read Model, artifact ownership/business metadata, ProductionRun linkage
- **obase.storage.blob_store** provides ONLY: `put/get/delete`, content addressing (SHA256), dedupe, physical persistence
- **obase.storage.blob_store** knows NOTHING about: project, user, Presentation, Artifact Currency, ProductionRun

---

## 2. OMODUL CANONICAL CONTRACT v3 (CORRECTED)

```python
# Signature: (config, input_data, output_dir, *, on_step=None) -> dict
# Return keys (ALL REQUIRED):
{
    "status": "completed" | "failed",
    "error": {"code": str, "message": str} | None,
    "_enabled_pillars": set[str],           # subset of {"fingerprint", "decision_trail", "report", "cost"}
    # At least one pillar MUST be present
    # Pillar payloads (present only if enabled):
    "fingerprint": str | None,              # sha256 of primary artifact
    "decision_trail": dict | None,          # audit trail (NO PII)
    "report": dict | None,                  # structured QC/validation report
    "cost": float | None,                   # USD cost of this transaction
    # Business result payload (transaction-specific, NOT a pillar):
    "result": dict | None,                  # e.g., {"video_path": "...", "drift_score": 0.02}
}
```

**Rules:**
- `_enabled_pillars >= 1` mandatory
- No `findings`, `cost_usd`, `report_path` — these were duplicate pillar schema
- Business result goes in `result` (optional, transaction-specific)
- Pillars are orthogonal; transaction declares which it produces

---

## 3. OSERVI ROLE (CORRECTED)

```
OSERVI_ROLE=GENERIC_EXECUTION_MECHANISM
SECOND_ORCHESTRATOR_AUTHORITY=0
```

**Model:**
- `oservi.SequentialComposerEngine` = generic reusable execution mechanism (sequential, fan-out/fan-in, failure propagation, checkpointing)
- **HEVI Layer4 Production Graph / runtime** continues as sole business authority
- HEVI Layer4 **invokes** generic oservi composition mechanisms
- oservi knows ZERO HEVI domain types (no project, shot, artifact, repair, presentation)

---

## 4. OMODUL INTERACTION RULES

```
OMODUL_TO_OMODUL=0
OMODUL_CANONICAL_CONTRACT=PASS
```

**Rules:**
- omodul NEVER calls another omodul directly
- All composition lifted to oservi (declarative manifest) or HEVI Layer4 service facade
- Each omodul only combines: oskill (pure algo) + oprim (atomic IO) + obase (infrastructure via DI)

---

## 5. OPRIM ATOMICITY (CORRECTED — BY SEMANTIC UNIT)

```
OPRIM_ATOMICITY_PLAN=SEMANTIC_UNIT
OPRIM_SIBLING_CALLS=0
```

**Primitive Definition:** One semantic external/system operation (not one CLI flag).

| Primitive | Semantic Unit | FFmpeg Invocation |
|-----------|---------------|-------------------|
| `ffmpeg_probe` | Media metadata extraction | `ffprobe` (read-only) |
| `ffmpeg_concat` | Concat demuxer + re-encode to unified spec | Single `ffmpeg -f concat -c:v libx264 ...` |
| `ffmpeg_mux_audio` | Video + audio filter_complex → mux | Single `ffmpeg -filter_complex "..." -map 0:v -map "[aout]" ...` |
| `ffmpeg_burn_subtitles` | Video + subtitle filter → burn-in + encode | Single `ffmpeg -vf "subtitles=..." -c:v libx264 ...` |
| `ffmpeg_encode` | Transcode to target spec (scale/pad/fps/CRF) | Single `ffmpeg -vf "..." -c:v libx264 ...` |
| `ffmpeg_extract_cover` | Extract single frame at timestamp | Single `ffmpeg -ss -frames:v 1 ...` |

**Anti-patterns AVOIDED:**
- ❌ Separate `concat` then `mux_audio` then `encode` (3x generation loss, 3x subprocess)
- ❌ Separate `burn_subtitles` then `encode` (2x generation loss)
- ✅ Each primitive = ONE ffmpeg invocation doing its semantic unit completely

---

## 6. OSKILL PURITY

```
OSKILL_PURITY_PLAN=PURE_SYNC_NO_IO
OSKILL_IO=0
```

**Rules:**
- Pure functions only: `def` not `async def`
- No network, no subprocess, no filesystem, no database
- Depth ≤ 2 (no deep call chains)
- No loops over external data (algorithmic loops over in-memory data OK)
- Deterministic: same input → same output always

---

## 7. 3O SINGLE SOURCE PLAN

```
3O_SINGLE_SOURCE_PLAN=PASS
```

**Verification:**
| Semantic Operation | Single Canonical Implementation |
|-------------------|--------------------------------|
| Provider routing | `obase.ProviderRegistry` only |
| Cost tracking | `obase.CostTracker` only |
| GPU scheduling | `obase.GpuScheduler` only |
| FFmpeg subprocess | `obase.media.ffmpeg` primitives only |
| Blender/Remotion/freevideo render | `oprim.blender_render_headless` / `remotion_render_component` only |
| ASR | `oprim.asr_transcribe_audio` only |
| TTS | `oprim.tts_synthesize_stream` only |
| V2V inference | `oprim.v2v_dispatch_infer` only |
| Timecode alignment | `oskills.timeline_math.calc_timecode_alignment` only |
| Previz script compilation | `oskills.previz_compiler.build_previz_bpy_script` only |
| Camera drift score | `oskills.quality.compute_camera_drift_score` only |
| Shot budget resolution | `oskills.budget.resolve_shot_budget` only |
| Previz generation transaction | `omodul.previz_generate` only |
| V2V stylize transaction | `omodul.previz_guided_v2v_render` only |
| Remotion render transaction | `omodul.remotion_template_render` only |
| Timeline assembly transaction | `omodul.media_timeline_assemble` only |
| Pipeline composition | `oservi.SequentialComposerEngine` only |

---

## 8. STATIC ARCHITECTURE REVIEW GATES

| Gate | Target | Verification Method |
|------|--------|---------------------|
| `ARTIFACT_AUTHORITY` | `HEVI_LAYER4` | No `obase.storage` import in HEVI Layer4 business logic (only via repository adapter) |
| `SECOND_ARTIFACT_AUTHORITY` | `0` | Grep: no `ArtifactManifest`/`ArtifactCurrency`/`Presentation` in obase/oprim/oskills/omodul/oservi |
| `SECOND_ORCHESTRATOR_AUTHORITY` | `0` | No HEVI domain types in oservi; no `longvideo_orchestrator` Monkey Patch paths |
| `OMODUL_CANONICAL_CONTRACT` | `PASS` | Schema validation on every omodul return (Pydantic model with `_enabled_pillars`) |
| `OMODUL_TO_OMODUL` | `0` | Static analysis: zero `from omodul.X import Y` inside `omodul/` |
| `OPRIM_SIBLING_CALLS` | `0` | Static analysis: zero `from oprim.X import Y` inside `oprim/` |
| `OSKILL_IO` | `0` | CI: no `async def`, no `import subprocess/socket/requests/psycopg/sqlalchemy` in oskill modules |
| `3O_SINGLE_SOURCE_PLAN` | `PASS` | Inventory matrix above — each semantic operation has exactly one canonical location |
| `PROMOTION_MAP_REVALIDATED` | `PASS` | All HEVI modules classified per §0 table; zero "promote domain authority to 3O" |

---

## 9. IMPLEMENTATION ORDER (Dependency-Sorted, Post-Review)

| Phase | Deliverables | Depends On |
|-------|--------------|------------|
| **P0** | `obase.media.ffmpeg` atomics (from assembler) | — |
| **P0** | `obase.storage.blob_store` (minimal mechanism) | — |
| **P0** | `oprim.asr_transcribe_audio` (from subtitle_align) | — |
| **P0** | `oprim.tts_synthesize_stream` (edge_tts + vibevoice) | — |
| **P0** | `oprim.remotion_render_component` (from explainer) | — |
| **P0** | `oprim.v2v_dispatch_infer` (from joyai stream_edit) | — |
| **P0** | `oprim.blender_render_headless` (from local_fallback) | — |
| **P1** | `oskills.timeline_math.calc_timecode_alignment` | P0 oprim |
| **P1** | `oskills.previz_compiler.build_previz_bpy_script` | — |
| **P1** | `oskills.subtitle.cues_to_srt` + `generate_ass_karaoke` | P0 oprim.asr |
| **P1** | `oskills.budget.resolve_shot_budget` | — |
| **P1** | `oskills.quality.compute_camera_drift_score` | — |
| **P1** | `oskills.quality.compute_luma_correction` | — |
| **P2** | `omodul.previz_generate` | P0 oprim.blender, P1 oskill.previz_compiler |
| **P2** | `omodul.previz_guided_v2v_render` | P0 oprim.v2v, P1 oskill.quality |
| **P2** | `omodul.remotion_template_render` | P0 oprim.remotion |
| **P2** | `omodul.media_timeline_assemble` | P0 oprim.ffmpeg_*, P1 oskill.timeline_math, oskill.subtitle |
| **P3** | `oservi` assembly manifest + `HeviVideoDirectorService` (Layer4 facade) | P2 all omodul |
| **P4** | E2E tests (E2E-1 through E2E-5) | P3 |
| **P5** | Delete `longvideo_orchestrator.py` Monkey Patch paths | P4 green |

---

## 10. E2E VERIFICATION MATRIX (Unchanged)

| Test ID | Flow | Entry | Exit | Verification |
|---------|------|-------|------|--------------|
| **E2E-1** | Whitebox Previz | `shot_spec` | `previz_XXX.mp4` + fingerprint | Blender renders, sha256 matches, decision_trail has `bpy_script_generated=true` |
| **E2E-2** | Previz→V2V | `previz.mp4` + prompt | `clip_XXX.mp4` + drift_score | V2V output exists, `drift_score <= config.max_camera_drift_threshold` |
| **E2E-3** | ASR→Timeline | `audio.wav` | `final.mp4` + burned subtitles | Frame-accurate alignment (max 1 frame skew), ASS karaoke renders |
| **E2E-4** | Remotion Branch | `composition_id` + props | `segment.mp4` | Remotion renders, duration matches `duration_frames` |
| **E2E-5** | Failure→Repair | Inject V2V/FFmpeg failure | `RepairIncident` created → repaired → Presentation current | Incident logged, repair action applied, artifact re-verified |

---

## 11. FINAL COMPLIANCE CHECKLIST

| Check | Target | Status |
|-------|--------|--------|
| `ARTIFACT_AUTHORITY` | `HEVI_LAYER4` | ✅ |
| `BLOB_STORAGE_MECHANISM` | `obase.storage.blob_store` | ✅ |
| `SECOND_ARTIFACT_AUTHORITY` | `0` | ✅ |
| `OMODUL_CANONICAL_CONTRACT` | `PASS` | ✅ |
| `OSERVI_ROLE` | `GENERIC_EXECUTION_MECHANISM` | ✅ |
| `SECOND_ORCHESTRATOR_AUTHORITY` | `0` | ✅ |
| `PROMOTION_MAP_REVALIDATED` | `PASS` | ✅ |
| `QUESTIONABLE_PROMOTIONS` | `0` | ✅ (assembler split correctly) |
| `OPRIM_ATOMICITY_PLAN` | `SEMANTIC_UNIT` | ✅ |
| `OPRIM_SIBLING_CALLS` | `0` | ✅ |
| `OSKILL_PURITY_PLAN` | `PURE_SYNC_NO_IO` | ✅ |
| `OSKILL_IO` | `0` | ✅ |
| `OMODUL_TO_OMODUL` | `0` | ✅ |
| `3O_SINGLE_SOURCE_PLAN` | `PASS` | ✅ |

---

## 12. PLAN READINESS

```
PLAN_READY_FOR_IMPLEMENTATION=YES
```

All static architecture review gates PASS. Ready for P0 implementation.

---

## 13. FILE MAP (New Canonical Locations)

```
hevi/
├── obase/
│   ├── __init__.py                 # re-export provider_registry, ffmpeg, blob_store
│   ├── media/
│   │   ├── __init__.py
│   │   ├── blender.py              # NEW: blender_render_headless primitive
│   │   └── ffmpeg.py               # EXTRACTED: atomic ffmpeg primitives (from assembler)
│   ├── provider_registry.py        # EXISTING: register all HEVI providers at startup
│   └── storage/
│       └── blob_store.py           # NEW: content-addressed put/get/delete (mechanism only)
├── oprim/
│   ├── __init__.py                 # flat exports
│   ├── video.py                    # blender_render_headless, remotion_render_component, v2v_dispatch_infer
│   ├── audio.py                    # asr_transcribe_audio, tts_synthesize_stream
│   └── render.py                   # ffmpeg_concat, ffmpeg_mux_audio, ffmpeg_burn_subtitles, ffmpeg_encode, ffmpeg_probe, ffmpeg_extract_cover
├── oskill/
│   ├── __init__.py
│   ├── timeline_math.py            # calc_timecode_alignment
│   ├── previz_compiler.py          # build_previz_bpy_script
│   ├── subtitle.py                 # cues_to_srt, generate_ass_karaoke
│   ├── quality.py                  # compute_camera_drift_score, compute_luma_correction
│   └── budget.py                   # resolve_shot_budget
├── omodul/
│   ├── __init__.py
│   ├── previz_generate.py          # canonical transaction (v3 contract)
│   ├── previz_guided_v2v_render.py # canonical transaction (v3 contract)
│   ├── remotion_template_render.py # canonical transaction (v3 contract)
│   └── media_timeline_assemble.py  # canonical transaction (v3 contract)
├── services/
│   ├── video_director.py           # Layer4 facade: assembles oservi pipeline, injects HEVI config
│   └── assembly_manifest.yaml      # declarative pipeline (oservi input)
├── assembly/
│   └── assembler.py                # KEEP_LAYER4: business policy, calls omodul.media_timeline_assemble
├── artifact_store/                 # KEEP_LAYER4: Artifact Manifest, Currency, Presentation
└── pipeline/
    └── longvideo_orchestrator.py   # DELETE_AFTER_MIGRATION: remove after P4
```

---

## 14. CLASSIFICATION

```
HEVI_MEDIA_PIPELINE_3O_INTERNALIZATION_PLAN_CORRECTED
```

---

## APPENDIX: SHA256 OF THIS PLAN

```
PLAN_SHA_OR_FILE_HASH=  # to be computed on final save
```