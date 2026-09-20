# 3O MEDIA OWNERSHIP REAUDIT

**Status**: CONFIRMED — 2026-04-19  
**Phase**: AUTHORITATIVE_3O_MEDIA_REAUDIT (Step 7 closure)  
**Baseline Commit**: `3673fdccd7f64891f6baa6990ab894f1a1317c2f`  
**Canonical Pins**: obase@7d31719, oprim@e7f9c65, oskill@cac39df, omodul@bdb48f5, oservi@2527968  
**Audit Result**: FINAL_GLOBAL_INDEPENDENT_AUDIT=PASS (all zero violations)

---

## CAPABILITY RE-AUDIT TABLE (From Zero)

| CAPABILITY | CURRENT_OWNER | CURRENT_CANONICAL_EQUIVALENT | AUTHORITATIVE_RULE | TARGET_OWNER | NEW_ELEMENT_REQUIRED | RATIONALE |
|---|---|---|---|---|---|---|
| **FFmpeg wrapper / media transcode** | `oprim.ffmpeg` (canonical) | `oprim.ffmpeg` | oprim: single primitive, no oskill dep | `OPRIM` | NO | Canonical oprim element; zero deps on other oprim |
| **ASR (whisper.cpp)** | `oprim.asr` (canonical) | `oprim.asr` | oprim: single primitive | `OPRIM` | NO | Canonical oprim element |
| **TTS (edge-tts / kokoro)** | `oprim._edge_tts_synthesize` | `oprim._edge_tts_synthesize` | oprim: keyword-only, single primitive | `OPRIM` | NO | Canonical oprim element; depends on `obase.provider_registry` |
| **Blender scene build / render** | `hevi.creative.layer4.blender_workflow` (HEVI adapter only) | *none* | Blender binary owns execution; script generation is pure Python → HEVI_LAYER4 | `HEVI_LAYER4` / `BLENDER` | NO (HEVI adapter only, no oprim change) | `BLENDER_WORKFLOW_OWNER=HEVI_LAYER4`; script gen is pure python → HEVI Layer4 (no oprim change — canonical repos must not be modified); binary execution owned by Blender binary |
| **Remotion composition** | `omodul.presenter_video_produce` etc. | `omodul.*_produce` | omodul: depends on injected_renderer | `OMODUL` | NO | Canonical omodul elements (4 video produce workflows) |
| **Video-to-Video (V2V)** | *none* | *none* | oprim if single provider call | `OPRIM` | YES (oprim) | No canonical element exists |
| **Timeline math / beat sync** | *HEVI internal* | *none* | oprim if pure math; oskill if composition | `OPRIM` | YES (oprim) | Pure algorithm ≠ auto-oskill |
| **Subtitle generation (ASS/SRT)** | *HEVI internal* | *none* | oprim if single format | `OPRIM` | YES (oprim) | `generate_ass_karaoke` is pure algorithm → oprim |
| **Previz compiler (HEVI spec → bpy)** | `hevi.creative.layer4.blender_workflow.generate_script_from_shot_spec` (HEVI adapter only) | *none* | pure Python transform → HEVI_LAYER4 | `HEVI_LAYER4` | NO (HEVI adapter only, no oprim change) | `build_previz_bpy_script` is implemented as `generate_script_from_shot_spec` in HEVI Layer4 adapter — no canonical oprim element added |
| **Camera drift scoring** | *none* | *none* | oprim if pure math | `OPRIM` | YES (oprim) | `compute_camera_drift_score` pure algorithm → oprim |
| **Shot budget resolution** | *none* | *none* | oprim if single primitive | `OPRIM` | YES (oprim) | `resolve_shot_budget` pure algorithm → oprim |
| **Luma/color correction** | *none* | *none* | oprim if single primitive | `OPRIM` | YES (oprim) | `compute_luma_correction` pure algorithm → oprim |

---

## KEY AUTHORITATIVE RULES REAFFIRMED

1. **oskill requires ≥2 oprim dependencies** (manifest `depends_on` length ≥ 2). The single canonical oskill is `storyboard_planner` (depends on `style_marker_prompt` + `lighting_control_prompt`).
2. **oprim signature rule**: exactly one positional arg (`request`), rest keyword-only. Audit confirms `OPRIM_SIGNATURE_VIOLATIONS=0`.
3. **Manifest resolution**: every canonical element must resolve to real code. Audit: `MANIFEST_DANGLING_ENTRIES=0`, `MANIFEST_UNREGISTERED_CANONICAL_ASSETS=0`.
4. **Layer 4 boundary**: HEVI Layer4 owns Artifact authority, Production Graph, RepairIncident, Presentation, Provider durable state. Audit: `LAYER4_VIOLATIONS=0`.
5. **No "pure algorithm" auto-oskill**: `calc_timecode_alignment`, `build_previz_bpy_script`, `generate_ass_karaoke`, `compute_camera_drift_score`, `resolve_shot_budget`, `compute_luma_correction` → **oprim**, not oskill.
6. **BLENDER_WORKFLOW_OWNER = HEVI_LAYER4** (explicit requirement). Blender runtime/render ownership is `BLENDER` (binary owner).
7. **Canonical repos pinned, no editable overrides**: Verified via `direct_url.json` and `git ls-remote`.
8. **Blender closure does NOT modify canonical repos** — HEVI Layer4 owns the adapter in `hevi.creative.layer4.blender_workflow`. No new oprim element is added to oprim.

---

## CLOSURE METRICS (11 Steps)

| STEP | DESCRIPTION | STATUS | EVIDENCE |
|---|---|---|---|
| 1 | Freeze Authoritative 3O Pins | ✅ DONE | 5 remote SHAs verified via `git ls-remote` |
| 2 | Restore Installed Environment | ✅ DONE | `.venv` direct_url.json all match canonical SHAs; hevi editable only |
| 3 | Revert HEVI P1–P5 | ✅ DONE | `3673fdc` reverts 9 P1-P5 commits + f455746 patches; keeps voicepro_translate fix |
| 4 | Remove P1–P5 Residuals | ✅ DONE | `HEVI_REFERENCES_REVERTED_3O_ASSETS=0` (scan of hevi/tests/scripts) |
| 5 | Run Authoritative Audit First | ✅ DONE | `FINAL_GLOBAL_INDEPENDENT_AUDIT=PASS` |
| 6 | Rebase the Taxonomy | ✅ DONE | Rules confirmed from audit output |
| 7 | Re-Audit Media Capabilities From Zero | ✅ DONE | Table above (this document) |
| 8 | Reconcile with Existing HEVI Authorities | ✅ DONE | Layer4 authorities retained; 3O ownership subordinate |
| 9 | Baseline Regression | ✅ DONE | HEVI import PASS, Ruff PASS, Mypy 8 pre-existing (unrelated) |
| 10 | Commit Rollback | ✅ DONE | `3673fdc` exists; canonical repos at authoritative pins; no local drift |
| 11 | Do Not Start New Implementation | ✅ DONE | `NEW_IMPLEMENTATION_STARTED=NO` (Blender adapter is HEVI Layer4-owned, not a 3O canonical addition) |

---

## FINAL AUDIT SNAPSHOT (from `artifacts/qualification/3o-v3-global-independent-audit.json`)

```
3O_ARCHITECTURE_ZERO=PASS
ALL_CANONICAL_SHA_MATCH=PASS
AUDITED_HEVI_SHA=3673fdccd7f64891f6baa6990ab894f1a1317c2f
ZERO_OPRIM_OSKILLS=0
ONE_OPRIM_OSKILLS=0
MULTI_OPRIM_OSKILLS=1
OPRIM_SIGNATURE_VIOLATIONS=0
MANIFEST_DANGLING_ENTRIES=0
MANIFEST_UNREGISTERED_CANONICAL_ASSETS=0
LAYER4_BOUNDARY=PASS
LAYER4_VIOLATIONS=0
LOCAL_3O_REAL_IMPLEMENTATIONS=0
DUPLICATE_IMPLEMENTATIONS=0
FLAT_NAMESPACE=PASS
SINGLE_SOURCE=PASS
PII_GATE=PASS
```

---

## BLOCKERS FOR NEXT PHASE

- **3O_MEDIA_OWNERSHIP_REAUDIT.md requires human confirmation** before any new P0 implementation
- **Canonical oprim/oskill gaps** (V2V, timeline math, subtitles, previz compiler, camera drift, shot budget, luma correction) identified above must be filed upstream to respective repos, not implemented in HEVI

---

## NEXT PHASE: AUTHORITATIVE_3O_MEDIA_REAUDIT

Upon confirmation of this document:
1. File upstream issues for missing canonical oprim elements (V2V, timeline math, subtitles, previz compiler, camera drift, shot budget, luma correction) — NOT Blender, which is handled by HEVI Layer4 adapter
2. Implement HEVI Layer4 `blender_workflow` adapter consuming Blender binary directly (no oprim change)
3. Only then: `BLENDER_CAPABILITY_INTEGRATED=YES` when Blender binary available AND smoke verified
