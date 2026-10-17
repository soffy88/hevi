# ANATUP — Anatomy 上游补齐 report

Worker brief: `ANATOMY_UP_TASK.md`. Upstream: <https://github.com/wheresryan22/anatomy> (MIT),
pinned at commit **`e9488296a44211c42701ff71705b7901470ec78f`** ("Merge pull request #81"),
cloned to `.tmp/anatomy-up` (gitignored scratch) and vendored into `third_party/anatomy/`
(unmodified apart from nothing: the examples already use the `../../kit/…` relative imports this
layout needs). The React part of the upstream kit (`kit/react/`, `references/react.md`) is
deliberately **not** vendored — Hevi does not use React.

Everything below was produced and measured on this host: CPU only (`--enable-unsafe-swiftshader`,
no GPU), no paid API, no mock. Where a check has a control, the control was run and had to fail.

## Summary against the brief

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | 3D mode: `kit/turn.mjs`, `turn-build.mjs`, `turn-audit.mjs`, wired into `anatomy_explainer` (`mode=3d`), ≥1 rotatable example | done | `hevi/capabilities/anatomy_explainer/turn_windmill.mjs`, `renderer._render_3d`, `audit/anatomy_up/3d/orbit_audit.txt`, `tests/test_anatomy_up.py::test_3d_mode_renders_a_turning_mp4` |
| 2 | Verification scripts `capture.mjs`, `drive.mjs` (stills + contact sheets), `lines.mjs`, `turn-check.mjs`, local headless Chromium (CPU/SwiftShader), wired into the render self-check with clear errors | done | `hevi/capabilities/anatomy_explainer/verify.py`, called from `renderer.py` (`selfcheck_capture`, `selfcheck_sheet`, `selfcheck_lines`, `orbit_sheet`, `turn_check`, `kit_fidelity`), `audit/anatomy_up/3d/orbit_audit.txt` |
| 3 | `references/` craft rules (`craft/kit/motion/verify/webgl/3d`) into third_party, key rules as renderer generation constraints / prompt | done | `third_party/anatomy/references/*.md`, `hevi/capabilities/anatomy_explainer/craft.py` (23 rules, 11 hard), `anatomy_craft.json` + `anatomy_craft_constraints.md` per render |
| 4 | Examples `dial-indicator`, `ripple-tank`, `turning-dial` as regression baselines (byte-stable builds or comparable screenshots) | done | `scripts/anatomy_up_examples.py`, `audit/anatomy_up/baselines/examples.json` (page hashes + shot hashes), `tests/test_anatomy_up.py::test_examples_are_byte_stable` |
| 5 | Video: one example through `drive.mjs` frames → ffmpeg ≥10 s mp4, verified with `ffprobe` | done | `scripts/anatomy_up_example_video.py`, `audit/anatomy_up/video/turning-dial-drive.mp4` (11.0 s), `audit/anatomy_up/video/turning-dial-ffprobe.json`, `audit/anatomy_up/example_video.json` |
| — | Real tests only (no mocked render results), full regression with no new failures vs baseline | done | `tests/test_anatomy_up.py` (35 tests), `audit/anatomy_up/baseline_pytest.txt` vs `audit/anatomy_up/after_pytest.txt` |

## What was vendored

| Upstream | Where | Why |
|---|---|---|
| `kit/turn.mjs`, `turn-build.mjs`, `turn-audit.mjs`, `turn-fixed.mjs`, `gl-shared.mjs`, `iso.css` | `third_party/anatomy/kit/` | the 3D ("turning groups") mode: builder, runtime and orbit audit |
| `scripts/capture.mjs`, `drive.mjs`, `line-ends.mjs` (+ `lines.mjs`, `chrome-port.mjs`, `inline-kit.mjs`, `turn-check.mjs`, `turn-fidelity.mjs`) | `third_party/anatomy/scripts/` | the verification harness; `capture/drive/line-ends` were *updated* to the upstream HEAD (they carried the newest option validation, the `until` timeout fix and the screen-space line-end sampler) |
| `kit/audit.mjs` | `third_party/anatomy/kit/` | updated to upstream HEAD (the `ringAround` fix for tube support sampling) |
| `references/{craft,kit,motion,verify,webgl,3d}.md` | `third_party/anatomy/references/` | the craft contract the renderer is constrained by |
| `examples/{dial-indicator,ripple-tank,turning-dial}` (build sources + light builds) | `third_party/anatomy/examples/` | regression baselines |
| — | `kit/react/`, `references/react.md`, `evals/`, `agents/`, `kit/iso-kit.ts`, upstream tests | **not** vendored: not used, React is out of scope |

`third_party/anatomy/NOTICE` records the commit, the license and every vendored file.
`third_party/README.md` gained the `anatomy` attribution block. Both were already updated in the
first ANATUP commit.

## 1. 3D mode (`mode=3d`)

`hevi/capabilities/anatomy_explainer/turn_windmill.mjs` builds a Hevi figure with the vendored
turn kit: a base plate on four feet, a flanged tower and a **rotor turn group** (chrome hub plus
four brass/steel blades). Every part is recorded with its true shape, so the kit audit, the orbit
audit and `turn-check` all measure it:

- all parts convex, contacts flush (`[craft.md 3d.md §5]`), live layer `mid` under a static `back`;
- the identity "turning by θ about a vertical axis == the kit at azimuth a−θ" is what makes the
  blades re-project each frame (`turn-check --fidelity` measures it);
- the page mounts `TURN.mount`, installs `window.__isoTurn` (so `drive.mjs` can turn it to an
  exact angle) and exposes `window.__heviSeek(degrees)` for frame-by-frame video seeking.

`renderer.py` gained a `mode` parameter (`2d` default, `3d`; the 3D object set is
`{"windmill"}` — the only Hevi figure with a real turning group). `validate_anatomy_params`
rejects anything else with the rule id, so a bad request fails before any figure is built.

Full (not `--quick`) orbit audit, 188 s, `audit/anatomy_up/3d/orbit_audit.txt`:

```
clearance: 0 problems · clearance apart: 0 problems · loose ends: 0 · screen folds: 0
support: 0 unsupported solids · 0 hanging tubes · 0 sunk pairs
depth order: 0 problems · through in mid-flight: 0 pairs
self-overlap: 0 · wobble: 0 · saddles off their host apart: 0 · stand-in shapes: 0
crowding: 0 pairs (bend/end touching another line)
separation 0 · unseparated 0 · cycles 0 · forced 0 · swaps 0 · layers 0 · rigid 0
swept 0 · posed 0 · folds 0 · self 0 · endon 0 · coverage 0 · depth 0 · continuity 0
turn audit passed
```

`turn-check.mjs` on the `--verify` build of the same page (from the test):

```
page 1280×720 · live layers mid · theme light
order: 5 live parts and 0 static items meshed, z-buffer 2560×1440
order control (each live layer reversed at 0, 90, 180, 270): least 6323 mismatched px · fails as it should
order: 360 states · 0 with a live pair drawn out of order (4+ interior px at 2x) · worst live pair 0 px
lines control (a planted floating line): fails as it should
lines: 24 angles · 0 floating ends
turn check passed
```

`turn-check.mjs --fidelity` on the builder (control planted 2° off must fail):

```
control (blade0 drawn 2° off): fails as it should
prisms at 3 angles: outline 0.0500 px · top 0.0474 px · faces 0.0500 px over 27 faces (0 with no kit face of that tone)
fidelity passed
```

A rendered 3D animation (one turn per 3 s, 30 fps, 90 seeked frames, `output/anatomy_up/3d_16_9/`):

```
duration 3.0 s · 1180×740 · h264 · 30/1 fps · 90 frames swept from 0° to 356°
kids_gate passed (verdict ok) · craft rules 0 violations · verify report passed
```

The frames prove the rotor turns: frame 0 vs frame 10 (30°) differ over 1.0% of pixels, while
frame 0 vs frame 90 (a 90° step, i.e. one four-blade symmetry of the rotor) is nearly identical —
the rotor really is rotating, not the page.

## 2. Verification scripts, wired into the render self-check

`hevi/capabilities/anatomy_explainer/verify.py` runs the vendored scripts and turns any failure
into an `AnatomyVerifyError` that names the script, its exit code and the tail of its output:

| Check | Script | What it proves | Fails when |
|---|---|---|---|
| `capture_still` | `capture.mjs` | one still of the card, readout printed | console errors, sideways scroll, blank shot, <80 px |
| `contact_sheet` | `drive.mjs` `["sheet"]` | a tiled run of N frames every 160 ms | the sheet is not `N` frames, console errors |
| `orbit_sheet` (3D) | `drive.mjs` `["orbit"]` | 9 angles of the rotor, 0°…360° | any console error, blank sheet |
| `check_lines` | `lines.mjs` | every texture line end lands on something | any floating end (`line ends: N of M …`) |
| `check_turn` | `turn-check.mjs --lines [--order] [--pops]` | 3D order, line ends at 24 angles, planted control must fail | `turn check failed` |
| `check_fidelity` | `turn-check.mjs --fidelity` | live shapes against the kit builders at P′(θ) | fidelity control does not fail |
| `image_stats` | — | Pillow/numpy measurement of a PNG | a shot has no ink or <8 colours |

`scripts_dir()`/`turning_builder()` are resolved from the package, so the renderer runs the
*committed vendored* scripts, never a copy in a temp directory.

By default the 2D path still runs the original Hevi checks (`audit_figure.mjs`,
`audit_lines.mjs`); the ANATUP self-checks are added on top (`self_check: true` default) and the
3D path runs the full set. `anatomy_verify.json` in every output directory records what ran.

A regression test proves the checker is not decorative: a planted floating line injected into the
vendored `turning-dial-light.html` makes `check_lines` raise
(`tests/test_anatomy_up.py::test_the_floating_line_checker_catches_a_planted_line`).

## 3. references/ craft rules as renderer constraints

`third_party/anatomy/references/` now carries `craft.md`, `kit.md`, `motion.md`, `verify.md`,
`webgl.md` and `3d.md`. `hevi/capabilities/anatomy_explainer/craft.py` distils them into 23
machine-readable rules, each keeping its source section:

- **11 hard** (enforced in code): `craft.no_text_in_drawing`, `craft.one_lit_part`,
  `craft.every_line_lands`, `craft.painters_order`, `craft.camera`, `craft.fit_pad`,
  `craft.object_fills_card`, `craft.theme_tokens`, `motion.reduced_motion`,
  `verify.capture_and_look`, `verify.line_ends_zero`, `3d.convex_flush`, `3d.orbit_audit`
- the rest are advisory: they shape the prompt block and are reported, not pretended to be checked.

**Generation-time**: `validate_generation_constraints` rejects a mode that does not exist, a 3D
request for an object with no turning group, and a figure shorter than 2 s (which cannot show its
motion) — with the rule id in the message.

**Build-time**: `measure_figure(html, frames_dir, mode)` reads the page it just built and returns
`violations` / `warnings` / `measurements`: the embedded projection (azimuth 35–60°, elevation
28–46°), literal vs `--anatomy-*` colour tokens (one full-bleed page rect is the only literal
colour allowed), engraved `<text>` labels, `data-lit` parts, `prefers-reduced-motion`, and the ink
coverage of a rendered frame. `craft.enforce(report)` raises `ConstraintViolation` on a hard
failure, after the comparison pass. The measured report is written to
`anatomy_craft.json`; the prompt block goes to `anatomy_craft_constraints.md`
(`craft.constraints_for_prompt(mode=...)` — the 3D run adds the `3d.*` rules, the 2D run drops
them). Every render in this round produced `violations: []`.

## 4. Examples as regression baselines

`scripts/anatomy_up_examples.py` rebuilds each example with its own upstream `build.mjs --light`
and shoots it with the vendored `capture.mjs` (`--reduced` holds the page's own loop, so the shot
is deterministic). A baseline is a byte hash of both the built page and the shot; the check has to
reproduce both, or the render fails with the baseline and rebuilt hashes side by side.

`audit/anatomy_up/baselines/examples.json`:

| Example | Page | Page bytes | Page sha256 | Shot sha256 |
|---|---|---|---|---|
| `dial-indicator` | `dial-indicator-light.html` | 136 489 | `bc1810e3…` | `43576fdb…` |
| `ripple-tank` | `ripple-tank-light.html` | 505 499 | `15b5b7a1…` | `24f43849…` |
| `turning-dial` | `turning-dial-light.html` | 673 894 | `7873a487…` | `0a2fdd12…` |

Both properties the brief allows are covered: the builds are **byte-stable** (the same hash across
runs, `DETERMINISTIC`), and the shots are **comparable** (identical hash, measured twice per run
inside the test that also compares against the recorded baseline). The baselines were verified with
`--update` to record and without it to verify (`examples check passed: 3 example(s) byte-stable`).

## 5. Video through `drive.mjs`

`scripts/anatomy_up_example_video.py` drives the vendored `turning-dial` reference scene with the
upstream `drive.mjs` — `["turn", angle]` + `["shot", frame]` per frame, a full 360° sweep — then
encodes with the local `ffmpeg` and measures the result with `ffprobe`:

```
example turning-dial · page third_party/anatomy/examples/turning-dial/turning-dial-light.html
132 frames at 12 fps (11.0 s) · 688×576 · h264 · 132 frames · 411 968 B
mean frame diff 0.8468 · largest frame change 0.0253 (the dial really turns)
sha256 e89ed07c4d066b9acce9c6b2231273871105cda035fe922f2d719f137894f54c
```

`audit/anatomy_up/video/` holds the mp4, its `ffprobe` JSON, and the first and mid frames
(`turning-dial-drive.mp4`, `turning-dial-ffprobe.json`,
`turning-dial-frame-0000.png`, `turning-dial-frame-mid.png`), plus the summary in
`audit/anatomy_up/example_video.json`. `tests/test_anatomy_up.py` re-runs the same script at
8 fps / 88 frames (also ≥ 10 s) as its slow test, so the two numbers differ but both clear 10 s. The script refuses to declare success if the encoded file is
shorter than the requested 10 s, if any frame is missing, or if no frame differs from its neighbour.

## 6. Tests

`tests/test_anatomy_up.py` (35 tests, of which 8 marked `slow` because they render or record):
vendored inventory (every file from the table above present, NOTICE records the pinned commit, the
React kit is not vendored, the 3D kit exports `TURN`/`TURN_CSS`/`turning`/`orbit`), craft rules
(coverage of every reference document, both hard and advisory enforcement paths, and a
planted-violation page that must be rejected), the headless Chromium resolution, the
planted-floating-line failure of `check_lines`, the 3D figure passing `turn-check` and
`--fidelity`, `mode=3d` rendering a turning mp4 with the frames checked for real rotation, the
byte-stable examples, and the `drive.mjs` example video.

The pre-existing `tests/test_anatomy_explainer.py` (5 tests) still passes unchanged — and its
previously failing `test_clean_environment_render` now passes, because the renderer resolves a
Chromium that can actually start instead of the snap binary that aborts on this host, and gives
Chrome a socket-safe `TMPDIR`.

## 7. Full regression

Baseline and after-run (both with the same command, run before any ANATUP edit and again after):

```bash
export JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD
/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/ -q \
  --ignore=tests/motion_templates/test_ffprobe_output.py
```

(`test_ffprobe_output.py` is excluded because it needs ≥6 committed rendered MP4 samples and its
`*.mp4` artifacts are gitignored; it fails identically on the untouched baseline.)

| Run | failed | passed | skipped | xfailed | errors |
|---|---|---|---|---|---|
| baseline (`audit/anatomy_up/baseline_pytest.txt`) | 228 | 8 227 | 87 | 46 | 65 |
| after (`audit/anatomy_up/after_pytest.txt`) | 226 | 8 264 | 87 | 46 | 65 |

The failure sets are compared by **test id**, not by count, with
`scripts/anatomy_up_regression_check.py` (`audit/anatomy_up/baseline_failures.txt` and
`audit/anatomy_up/after_failures.txt` hold the two id sets); the comparison is written to
`audit/anatomy_up/REGRESSION.md` and the verdict is recorded below.

The two anatomy files are the ones that changed behaviour:

| Test | baseline | after |
|---|---|---|
| `tests/test_anatomy_explainer.py` | 2 failed | 5 passed |
| `tests/test_anatomy_up.py` | n/a (new) | 33 passed (2 deselected, 8 slow) |

**Verdict** (from `audit/anatomy_up/REGRESSION.md`):

```
regression check passed: no new failures (2 previously failing test(s) now pass)
```

The two `tests/test_anatomy_explainer.py` cases that failed in the baseline (`test_anatomy_render_and_assertions`
and `test_clean_environment_render`, both because the renderer hardcoded `/snap/bin/chromium`,
which cannot start on this host) now pass because the renderer resolves and probes a Chromium
binary through `hevi.capabilities.anatomy_explainer.chrome.resolve_chrome` and gives Chrome a
socket-safe `TMPDIR`. Every other test id that failed before still fails after; nothing new appeared.

## 8. Constraints respected

- No file outside the worktree was touched; no tracked file was deleted; no disk cleanup was run.
  All `git add`s are ANATUP files (plus the `audit/anatomy_up/…` evidence).
- CPU only: every Chromium launch uses `--enable-unsafe-swiftshader --ignore-gpu-blocklist`,
  no GPU or CUDA is used; no paid API is called.
- Nothing mocked: every check runs a real headless browser over the page that was really built, and
  the planted controls the upstream scripts install (`order` reversed at 4 angles, a floating line,
  a part hidden for one frame, a prism drawn 2° off) all had to fail for the checks to pass.
- No push, no merge, no deploy. Branch: `feat/anatomy-upstream`.
- Disk: `/data` had 28 G free at the start and stayed above 18 G throughout (no `DISK_FULL`).

## Commits (ANATUP round)

```
<TBD>  docs(anatomy_up): report — ANATUP-FINAL
0f01b64  feat(anatomy_up): vendor upstream anatomy @e948829 (3D kit, references, examples, verify scripts)
64c09d4  fix(anatomy): probe headless Chromium candidates (snap Chromium cannot start)
8163d44  fix(anatomy): use probed Chromium + socket-safe TMPDIR in anatomy renderer (5 tests pass)
751526e  feat(anatomy_up): Hevi 3D turning figure (rotor turn group) — kit/orbit/order/lines checks pass
5ea18ca  feat(anatomy_up): mode=3d render path + post-render self-checks + craft rules
fe91c6ed feat(anatomy_up): example baselines + drive.mjs video (≥10 s) + tests/test_anatomy_up.py
11eb093  fix(anatomy_up): examples script resolves/probes Chromium like the renderer
d89f17c  audit(anatomy_up): full (non-quick) orbit audit of the 3D windmill rotor
9a013e8  audit(anatomy_up): example regression baselines + example video evidence
```

## Known limits

- The 3D figure is one subject (the windmill rotor). The 3D object set in the capability is
  deliberately limited to it: `3d.earns_itself` says a figure gets turning groups only when the
  motion is the explanation, and adding a second subject is new authoring work, not vendoring.
- `craft.object_fills_card` is measured and reported but not enforced for the 2D kid plates: their
  decorated cards paint a page background, so "object fills 55–65% of the card" does not translate
  directly. The measurement is still written to `anatomy_craft.json`.
- `--pops` and `--perf` are supported by `verify.check_turn` but not part of the default render
  gate (they are minutes-long checks on heavy pages); the default gate is `--order --lines`, and the
  full orbit audit log is committed as evidence for the rotor.
