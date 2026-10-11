# DRAMAKEY Progress Tracker

## Task Status: Completed
Worktree: `/data/soffy/projects/hevi-dramakey`
Branch: `feat/dramakey-3o`
Base Commit: `98e216af`

### Checklist
- [x] Initial audit & baseline checks
  - [x] 3O lint baseline captured (4 failed checks baseline in site-packages)
  - [x] Existing tests verified passing (17 script2video tests, 42 cross-module tests)
  - [x] Models verified: SD-Turbo (`/data/soffy/models/ms/models/AI-ModelScope--sd-turbo`), TAESD (`madebyollin--taesd`), open_clip (`/home/soffy/models/open_clip`), Piper TTS (`/data/soffy/projects/hevi-zero/voices`)
  - [x] Downloaded YuNet & SFace ONNX models to `/data/soffy/models/opencv/`
- [x] Part A: Keyframe Engine oprim & oskill
  - [x] Abstract interface `KeyframeEngine` & `KeyframeResult`
  - [x] Implementation: `sdturbo_cpu` (SD-Turbo + TAESD, flock `/tmp/hevi_cpu_render.lock`)
  - [x] Implementation: `cloud_stub`, `fake`, `sdxlturbo_cpu` slot
  - [x] Registry & resolution: `resolve_keyframe_engine`
  - [x] Write `docs/KEYFRAME-ENGINE.md`
  - [x] Chinese -> English prompt oskill `zh_shot_to_sd_prompt` with rule dictionary & character tokens
- [x] Part B: True Quality Selection + Consistency Gate
  - [x] Pixel-level `image_score`: open_clip ViT-B-32 + Laplacian sharpness + exposure + bad-image detection
  - [x] Dual-candidate generation & scoring
  - [x] Face similarity gate: YuNet + SFace cosine similarity with character reference face
  - [x] Character reference portrait generation (3 seeds best face)
- [x] Part C: Novel Planning Enhancements (script2video)
  - [x] Chapter splitting: `split_chapters` by chapter headings & length subdivision
  - [x] Character fusion & `CharacterCard` schema + `characters.json`
  - [x] Duration to shot budgeting: `shot_budget_for_duration`
- [x] Part D: End-to-End Render Pipeline (omodul)
  - [x] `novel2video_workflow` with `render=True` path
  - [x] Ken Burns camera motion via ffmpeg zoompan
  - [x] Piper TTS voiceover (differentiated character voices)
  - [x] Subtitle generation (.srt) & burn-in
  - [x] Concatenation into final 1080x1920 MP4
  - [x] Checkpoint caching by content hash
- [x] Acceptance & QA
  - [x] E2E script `scripts/e2e/dramakey_e2e.py` on 崂山道士 (73.76s, 14 shots)
  - [x] Real qa.json (ffprobe, volumedetect, 6-frame contact sheet, frame diff, sha256)
  - [x] Script2video 30s sample (31.96s, 6 shots)
  - [x] Unit tests (<30s runtime: 10 tests in 11.09s)
  - [x] 3O lint re-check (0 new violations)
  - [x] DRAMAKEY_DONE.md written
