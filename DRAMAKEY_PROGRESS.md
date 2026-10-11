# DRAMAKEY Progress Tracker

## Task Status: Round-2 fixes in progress (DRAMAKEY_FIX.md)
Worktree: `/data/soffy/projects/hevi-dramakey`
Branch: `feat/dramakey-3o`
Base Commit: `029348cb` (wip snapshot before style switch)

### Round-2 (DRAMAKEY_FIX.md) checklist
- [x] Fix 1: subtitle wrapping (<=14 chars/line, <=2 lines, punctuation-split cues)
- [x] Fix 2: character consistency (character-card tokens injected; protagonist prioritised)
- [x] Fix 3: subject keyword verification (moon/axe/wall/wine/scholar/taoist + CLIP subject score)
- [x] Fix 4: cloud_stub not selected in E2E (asserted); engine written to qa/record
- [x] Fix 5: default style -> `anime_guofeng`; photoreal off by default; style prefix + photo negatives
- [x] Fix 6: style config `anime_guofeng|ink|flat_comic|photoreal`, shared via `hevi/prompt/style_presets.py`
- [x] Subtitle margin gate rewritten as diff-vs-no-subtitle-concat (real subtitle pixels only)
- [x] Style gate `compute_style_alignment` (OpenCLIP anime-vs-photoreal) added to qa.json
- [x] Unit tests: `tests/test_dramakey_pipeline.py` 12 passed in 25.43s
- [x] 3O lint: same 4 pre-existing site-packages failures, 0 new
- [ ] E2E re-render with `style=anime_guofeng` (novel + script paths) — running
- [ ] Contact-sheet / frame eyeball check (subtitles, protagonist, no photoreal faces)
- [ ] DRAMAKEY_DONE.md update + git commit

### Round-1 checklist (completed at 029348cb)
- [x] Initial audit & baseline checks
- [x] Part A: Keyframe Engine oprim & oskill
- [x] Part B: True Quality Selection + Consistency Gate
- [x] Part C: Novel Planning Enhancements (script2video)
- [x] Part D: End-to-End Render Pipeline (omodul)
- [x] Acceptance & QA (round-1)

