# SCENE3D R1C completion report

## Result

All SCENE3D_FIX_R2 blocking items B1–B3 are addressed in this worktree. The full `tests/test_scene3d*.py` acceptance command passes: **45 passed, 1 warning, in 181.66s**. Six R1C MP4s are present, use H.264 at 30 fps, pass the kids visual gate, and each independently re-rendered with the same fixed seed produced an identical SHA-256. Renders ran serially; no paid API was used.

## Root causes and fixes

- **B1 — fox facing away / wooden legs.** The fox's local forward vector is +X, but the old default Y rotation and static orientation did not track the moving camera path. The fox now turns toward the actual camera during `setTime`; the render-side diagnostics expose the head screen bounding box, forward-to-camera dot product, both eye projections and ray-hit occlusion. Legs were shortened and changed to rounded capsules in a warm orange-brown palette. On both aspects, checks at t=1.2/6.0/10.8s measured dot products between 0.9224 and 0.9611; both eyes were in frame and unobscured for all six sampled checks.
- **B2 — beige, desaturated palette / yellow fox.** The preset's sky and fog were too close to the wheat's warm neutral colors and washed out the fox. `fox_in_wheat.json` now uses a clear blue sky, golden wheat and orange fox/paws; bloom and fog are tuned not to collapse their contrast. `kids_gate` now fails below mean saturation 0.35, and color-region diagnostics measure hue and saturation specifically inside the projected fox-head box. At the rendered middle frame, the orange target hue's median is 39.53° and mean saturation is 0.5751; the region gate passes.
- **B3 — “star sea” looked like ground under a distant star wall.** The scene had ground-like assets/composition and too few stars close to the camera's flight volume. The star-sea scene now has no ground or grass assets, a blue-violet nebula palette, and a star field that extends along and around the camera path with visible nearby stars. Camera-path travel measured 37.019 units; at t=0/3.25/6.5/9.75/13s, visible stars within 8 units numbered 184/158/170/171/159 (nearest distance as low as 0.549 units). The rendered portrait frame's green-ground proxy stays under the 0.20 ceiling and the kids gate passes.
- **Pacing guard.** The capability adapter now rejects direct shot renders shorter than 2.0 seconds with `CapabilityError`; the regression test covers a 1.99-second request. The separate kids gate continues to validate final rendered clip pacing/flicker/saturation.

## R1C render artefacts and media evidence

All videos below were checked with `ffprobe` and decoded frame counting; the repeated render SHA matched the deliverable SHA in every row. `output/scene3d_r1c/r1c_render_results.json` is the machine-readable full result, including timings and contact-sheet paths. Each contact sheet contains six evenly spaced frames.

| Shot | Aspect | Duration | Resolution | Codec / FPS | Decoded frames | Mean saturation | SHA-256 | Six-frame contact sheet |
|---|---|---:|---:|---|---:|---:|---|---|
| planet_orbit_16x9 | 16:9 | 12.000s | 960×540 | H.264 / 30 | 360 | 0.3616 | `1d4c86e340f42674439b3104f4bae880778788f20d651f0062e29af868879209` | `output/scene3d_r1c/planet_orbit_16x9/contact_sheet_6f.png` |
| planet_orbit_9x16 | 9:16 | 12.000s | 540×960 | H.264 / 30 | 360 | 0.3673 | `7e07bda3abbd447cadabd6578f89b983ecbed031067d58def41a73a16493084d` | `output/scene3d_r1c/planet_orbit_9x16/contact_sheet_6f.png` |
| fox_wheat_9x16 | 9:16 | 12.000s | 540×960 | H.264 / 30 | 360 | 0.3936 | `1a05f058c3e39e8ef6d5b5a92cb7e65d30fd3b14537ade3a4a1e1529ac043318` | `output/scene3d_r1c/fox_wheat_9x16/contact_sheet_6f.png` |
| fox_wheat_16x9 | 16:9 | 12.000s | 960×540 | H.264 / 30 | 360 | 0.4164 | `e4dd68543f05aa4d01516dae313d3de4a6f0f6aa759adc6b3633c474c9cba4b5` | `output/scene3d_r1c/fox_wheat_16x9/contact_sheet_6f.png` |
| star_sea_9x16 | 9:16 | 13.000s | 540×960 | H.264 / 30 | 390 | 0.5775 | `9462150f053d6ca16420b9f71f8a4c044f76d941e2fd7e785e30081c13ad4e68` | `output/scene3d_r1c/star_sea_9x16/contact_sheet_6f.png` |
| star_sea_16x9 | 16:9 | 13.000s | 960×540 | H.264 / 30 | 390 | 0.5818 | `ef0936cc6c9931d0a026593049660655b153e6ac141f1975b4193eb8736da42f` | `output/scene3d_r1c/star_sea_16x9/contact_sheet_6f.png` |

Verified artifact invariants: `complete=true`, `failures=[]`; each MP4's recorded hash equals its actual hash and the same-seed verification render's hash; all frame counts, durations and dimensions match `ffprobe`.

## Verification

1. Targeted R2 regressions: `JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-scene3d/.tmp PYTHONPATH=/data/soffy/projects/hevi-scene3d /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_scene3d_r2.py` — **6 passed in 11.75s**.
2. Required final command: `JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-scene3d/.tmp PYTHONPATH=/data/soffy/projects/hevi-scene3d /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_scene3d*.py` — **45 passed, 1 warning in 181.66s**. The only warning is the existing Starlette `TestClient` / `httpx` deprecation notice.
3. Python compilation and `git diff --check` are run in the final pre-commit verification.
4. `scripts/ci/run_3o_v3_lint.py` was rerun. It reports the same four accepted pre-existing 3O checks as baseline (`check_no_sibling_call.py`, `check_omodul_signature.py`, `check_enabled_pillars.py`, `check_oprim_keyword_only.py`); other listed 3O checks pass. These failures originate from the shared installed `.venv` package set, not this scene3d worktree; no lint rules were suppressed or modified here.

Only task-owned source, presets, regression tests, the render/verification script and this completion report will be staged. Existing unrelated/untracked audit and Veya metadata files are intentionally untouched.

DONE SCENE3D-R1C
