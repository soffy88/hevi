# stickdir — merge attempts (step 0)

Per STICKDIR_TASK.md §(c)/§(b):

- `git merge --no-commit --no-ff feat/sfx-badclips` -> **clean merge, aborted**.
  The merge auto-modified `hevi/studio/fulfill.py` (protected: `hevi/studio/*`
  read-only) and dragged in ~150 unrelated files from the branch's divergent
  history (including `hevi/prompt/style_presets.py`, protected). The global
  no-touch rule ("禁止改动 hevi/studio/*, hevi/prompt/style_presets.py") wins
  over the merge permission, so the merge was aborted and the task's documented
  read-only fallback was used instead: needed SFX WAVs were copied out with
  `git show feat/sfx-badclips:<path>` into this branch's own
  `assets/audio/sfx/library/`.
- `git merge --no-commit --no-ff feat/fx-registry` -> **clean merge, aborted**.
  499 files, including `hevi/prompt/style_presets.py`, `hevi/studio/*`,
  `hevi/layer4_legacy/keyframe/oprim_impl/style_presets.py` (all protected).
  Same fallback: the 5 stickman styles are registered via a new
  `hevi/fx/sources/stickdir.py` matching the fx-registry convention, plus a
  `# TODO(stickdir): register styles in fx registry after feat/fx-registry
  merges` note, and the registry wiring is exercised by a self-contained test
  that stubs the registry contract when `hevi.fx` is absent.

Baseline lint (`scripts/ci/run_3o_v3_lint.py`): 4 failures
(check_no_sibling_call, check_omodul_signature, check_enabled_pillars,
check_oprim_keyword_only) — recorded at `docs/stickdir/lint_before.txt`.
