# open-3d-skills attribution

Method source: Moh4696/open-3d-skills (author exploraX),
MIT licence, single LICENSE file (Copyright (c) 2026 exploraX).
Reviewed read-only from the report `hevi-vs-open-3d-skills.md`
(2026-11-01); the graft in this commit is a clean-room rewrite
of the *methods* described there. No script, starter, demo, or
other source text from that repository is copied into hevi:
every line of the new capabilities was newly written in this
repository, reusing only hevi's own harness (Playwright
Chromium + SwiftShader, vendored Three.js r169, `__hf` settle
protocol, `qa.chroma_key_gate`, `pipeline.spend_brake`).

What was grafted (this commit):

- A1 `qa.virtual_clock_contract` — virtual-clock recording
  contract (plan/discipline only).
- A2 `qa.browser_check_matrix` — Chromium + WebKit x
  1440/768/390 check matrix (plan and report schema only).
- A3 `qa.seam_loop_vocabulary` — seam/loop scoring vocabulary
  (scores only; thresholds caller-supplied, no defaults).
- A4 `qa.spend_preflight_checklist` — spend preflight
  checklist; the budget rule is reused from
  `pipeline.spend_brake`, no second budget mechanism.
- A5 `qa.transparent_delivery_contract` — stacked-alpha /
  VP9 alpha / WebP delivery contract (plan only; the asset
  must separately pass `qa.chroma_key_gate`).
- B1 `video.virtual_clock_recorder` — minimal virtual-clock
  recorder (new code; Range-serving harness; `__hf` settle;
  two-run hash identity; not BeginFrame capture).
- B5 `world.threejs_imaging_upgrade` — Three.js imaging
  upgrade (three linked lighting presets, post stack,
  caller-supplied budget, three quality tiers that never
  downgrade while recording, vantages and arc flights).

What was grafted later (2026-11-02, separate commit, same
clean-room terms; no script text copied):

- B3 `video.scroll_film_engine` — keys-driven scroll film
  (linear key interpolation with holds, 4-frame GOP, zero
  B-frames, Range-server requirement for scrub-video
  delivery); seam and loop scores measured on output frames
  and judged by `qa.seam_loop_vocabulary` with
  caller-supplied thresholds; the loop jump is judged only
  when the plan declares a loop. Synthetic fixtures only.
- B4 `video.alpha_cutout_keyer` — per-frame border-ring plate
  measurement, chroma-only keying distance, edge despill
  `F = (C - (1-a)K) / a`, stacked-alpha / VP9 alpha / WebP
  delivery; output separately passes `qa.chroma_key_gate`
  (judge and maker separate). Keying defaults similarity
  0.10 / blend 0.30 are hevi-chosen values calibrated on the
  bundled synthetic fixture, not author numbers. VP9 alpha
  availability is verified per run with ffprobe: this
  environment's ffmpeg/libvpx drops the alpha plane, so the
  VP9 delivery is recorded unavailable there and no file is
  claimed. Shadow/lighting values for the synthetic fixture
  are the fixture rig's declared values, flagged per frame.

What was not done (residuals, stated plainly):

- B2 browser-check executor, B6 exploded view, B7 cursor
  rig: not built in either commit.
- GTAO is declared in the B5 plan vocabulary but not
  applied: no GTAO pass is vendored in this repository and
  nothing was downloaded. The applied post stack is
  RenderPass -> UnrealBloomPass -> OutputPass, recorded as
  such in every B5 report.
- Pure frame time is not measured: B5 records
  seek-plus-screenshot time and marks the frame-time budget
  item `not_checked`; draw calls and triangles are real
  renderer measurements compared with the caller budget.
- No model call chain, key, or budget was touched; no
  install chain was run; no plugin was installed.
- Real-device, Windows/GPU, and slow-network checks were not
  run and are not claimed.

Author-reported numbers not verified, not used as defaults:
the source repository's self-reported figures (output frame
rate, per-frame time / draw-call / triangle budgets, seam
and loop scores, delivery volume ratio, exposure and bloom
values) were not independently verified and appear nowhere
in this graft as default thresholds. Every threshold, budget,
exposure, and bloom value in the new capabilities must be
supplied by the caller; a missing value fails the gate or is
recorded `not_checked`, never passed by default.

Dependency check (ubuntu26, hevi `.venv`, 2026-11-01,
foreground reads; versions are what was actually installed):

- playwright 1.62.0 (pip metadata; `playwright` module has
  no `__version__` attribute)
- Pillow 12.3.0
- numpy 2.4.6
- opencv-python-headless 5.0.0.93 (opencv-python 5.0.0.93
  also installed; not used by this graft)
- ffmpeg 8.0.1 / ffprobe 8.0.1 (system `/usr/bin`)
- Playwright browsers present: chromium-1243, chromium-1248,
  chromium_headless_shell-1234/1248, ffmpeg-1013,
  webkit-2370
- Vendored Three.js: `REVISION = '169'` at
  `hevi/layer4_legacy/scene3d/vendor/three/three.module.js`
  (first candidate of `athenaion_browser.resolve_three_module`);
  vendored post-processing passes present: EffectComposer,
  RenderPass, UnrealBloomPass, OutputPass, Pass, ShaderPass,
  MaskPass. No GTAO/SSAO pass is vendored anywhere in the
  repository.

Evidence (outside this repository, not committed):
`/data/soffy/open3d-sample/` — B1 two-run hash identity,
8fps and 60fps mp4s with ffprobe checks, and a video-seek
run; B5 three-preset screenshots, measured draw calls /
triangles, and two-run hash identity. See the evidence
summary JSON in that directory for the measured values.
B3/B4 evidence is in `b3/` and `b4/` under the same
directory (each with its own `evidence.json`): B3 continuous
film verdict pass with two-run frame-hash identity, cut
variant fails the seam gate, loop variant pass; B4 24-frame
drifting-plate keying verdict pass from `qa.chroma_key_gate`,
worst edge transition 7.0px, stacked-alpha mp4 and WebP
frames delivered, VP9 alpha recorded unavailable (see above),
three-background check frames in place.
