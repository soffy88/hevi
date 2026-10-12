# DRAMAKEY Progress Tracker

## Task Status: All DRAMAKEY_FIX.md items resolved ✅
Worktree: `/data/soffy/projects/hevi-dramakey`
Branch: `feat/dramakey-3o`
Current HEAD: `4451082d` fix(dramakey): subtitle margin gate uses morphological close + connected components

### Round-3 (DRAMAKEY_FIX.md) checklist — ALL PASSED
- [x] Fix 1: subtitle wrapping (<=14 chars/line, <=2 lines, punctuation-split cues) + safe margin gate with morphological filtering
- [x] Fix 2: character consistency (王生 sim 0.565-0.683, 老道长 sim 0.301-0.415, all >=0.30 threshold)
- [x] Fix 3: subject keyword verification (scholar/taoist/moon/wine/axe/wall) + CLIP subject score
- [x] Fix 4: cloud_stub not selected in E2E (asserted); engine=sdturbo_cpu written to qa/record
- [x] Fix 5: default style -> anime_guofeng; photoreal off by default; style prefix + photo negatives
- [x] Fix 6: style config anime_guofeng|ink|flat_comic|photoreal, shared via hevi/prompt/style_presets.py
- [x] Fix 7: re-rendered with style=anime_guofeng; all 14 shots stylized_pass=True (anime 0.36-0.61 >> photo 0.05-0.11)
- [x] Subtitle margin gate rewritten as diff>100 + morphological close + connected components (area>=80 filter)
- [x] Style gate compute_style_alignment added to qa.json
- [x] Unit tests: tests/test_dramakey_pipeline.py 12 passed in 94.51s
- [x] 3O lint: same 4 pre-existing site-packages failures, 0 new
- [x] Novel2Video E2E: output/dramakey_e2e/novel_20261012_004958/final.mp4 (74.24s, 14 shots, QA passed)
- [x] Script2Video E2E: output/script2video_e2e/script_20261012_042000/final.mp4 (32.37s, 6 shots, QA passed)
- [x] DRAMAKEY_DONE.md updated with new SHA256 and full per-shot metrics

### Round-1 baseline (completed at abd91fe6)
- [x] Initial audit & baseline checks
- [x] Part A: Keyframe Engine oprim & oskill
- [x] Part B: True Quality Selection + Consistency Gate
- [x] Part C: Novel Planning Enhancements (script2video)
- [x] Part D: End-to-End Render Pipeline (omodul)
- [x] Acceptance & QA (round-1)
