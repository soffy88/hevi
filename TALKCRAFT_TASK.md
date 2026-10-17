# Task: internalize video-talkcraft into Hevi under the 3O architecture (CPU-only, zero cost)

You are working on ubuntu26. Work ONLY in the git worktree `/data/soffy/projects/hevi-talkcraft` (branch `feat/talkcraft-3o`).
NEVER modify anything under `/data/soffy/projects/hevi` (the main checkout has 145 uncommitted user changes) except reading it.
Upstream source (read-only reference): `/data/soffy/projects/vendor/video-talkcraft` (commit 4cd673d). Read its SKILL.md, references/, scripts/, template/ first.

## Hard constraints
- No GPU (driver is dead). No paid API calls. No cloud TTS/ASR. Everything runs on CPU locally.
- Python: `/data/soffy/projects/hevi/.venv/bin/python` (use it; do not pip install into it unless a pure-python dep is truly needed, and note it).
- Node: `export PATH=$HOME/.nvm/versions/node/v26.4.0/bin:$PATH`. Remotion 4.0.486 already installed in `/data/soffy/projects/hevi/hevi-remotion/node_modules` (incl. `.remotion/chrome-headless-shell`). In the worktree, symlink `hevi-remotion/node_modules` -> that directory; do not run npm install in the main repo. Do not commit node_modules.
- TTS: local Piper voices in `/data/soffy/projects/hevi-zero/voices/` (zh_CN-huayan-medium.onnx, en_US-ryan-medium.onnx); see `/data/soffy/projects/hevi-zero/zl.py` for how it is invoked.
- ASR / alignment: local faster-whisper at `/home/soffy/models/faster-whisper-large-v3-turbo` (CPU, int8). Port the alignment logic of upstream `scripts/timestamps_cpu.py` (whisper backend) — do NOT download FireRedASR.
- ffmpeg/ffprobe: `/home/soffy/.local/bin/`.
- Follow Hevi's 3O layering (read `docs/3O-MIGRATION-REPORT.md`, `docs/VIDEOAGENT-INTERNALIZATION.md`, `scripts/ci/run_3o_v3_lint.py`): oprim = typed contracts/atoms, oskill = pure deterministic algorithms, omodul = transactions with side effects, hevi studio/production = registration + delivery gates. Internalize the capability and methodology; do not paste the upstream runtime wholesale.
- Keep output from your tools small (pipe long output to files, read ranges).

## What to build
1. `hevi/talkcraft/` package (3O-layered):
   - contracts: `WordTimestamp`, `Beat`, `ShotSpec`, `Shotbook`, `TalkcraftRenderRequest/Result` (pydantic or dataclasses consistent with the repo).
   - alignment: script + audio -> word/char-level timestamps on CPU via faster-whisper, with per-sentence QA flags (port of timestamps_cpu.py).
   - shotbook planner (pure, deterministic): script sentences + timestamps -> semantic beats -> card selection from a card index (port `cards_index.py` / `card_match.py` logic; domain style profile per references/design-language.md §0), anti-slideshow rules (one slow camera curve per scene, motion-continuity transitions), layout budget.
   - render transaction: writes a timing/shotbook JSON and renders via Remotion CLI on CPU (segment-parallel like `render_shots.mjs` if practical), muxes voice + SFX, loudness-normalizes.
   - QA gates: port freeze/static detection (`freeze_probe.py` / `motion_check.py`), `sfx_check.py`, `contact_sheet.py`. Gate results are measured values written to a record JSON (with SHA-256, duration, resolution, audio stats). Never write boolean-only claims.
2. `hevi-remotion/src/talkcraft/`: vendor the Remotion code needed — `template/motion-systems/`, `template/components/`, and the cards (all 108 if they compile; at minimum 25 covering kinetic title, data/number, list, compare split, quote, chapter card, schematic, video-in-frame, transitions). Register a `TalkcraftExplainer` composition in `Root.tsx` driven by input props (shotbook + timing). Keep upstream provenance comments at file top.
3. Wire into existing lines: add `renderer="talkcraft"` option to the explainer line (`hevi/explainer/`), and make it usable for kinetic_promo and talking_head (talking_head uses a host video/cutout if available, otherwise the 2D presenter fallback — be honest in the record). Register as a capability/tool in whatever registry the repo uses for lines/providers.
4. Licensing: add the upstream LICENSE (PolyForm Noncommercial 1.0.0) text and SFX attribution to `THIRD_PARTY_NOTICES` (create if missing) and a `hevi/talkcraft/README.md` stating commercial use needs the author's authorization.
5. Tests: unit tests for alignment parsing, planner determinism, card selection, QA gate math. Run the repo's pytest for the new tests plus `scripts/ci/run_3o_v3_lint.py`; both must pass. Don't break existing tests you touch.
6. End-to-end proof on CPU: produce one real ~30–60 s Chinese explainer MP4 (1920x1080, 30fps) from a short script about any neutral topic, with Piper voice, word-synced kinetic text and at least 6 different cards. Save to `/data/soffy/projects/hevi-talkcraft/output/talkcraft_e2e/` with `record.json` (measured QA) and `contact_sheet.jpg`. Also one 9:16 kinetic_promo ~15 s.
7. Write `docs/TALKCRAFT-INTERNALIZATION.md` (same style as VIDEOAGENT-INTERNALIZATION.md): capability boundary, 3O mapping, entry points, what was not internalized, licensing.
8. Commit on branch `feat/talkcraft-3o` with clear messages (git user is soffy). Do not push. Do not merge.

## Finish
When done, write `/data/soffy/projects/hevi-talkcraft/TALKCRAFT_DONE.md` summarizing: files added, tests run + counts, lint result, e2e outputs (paths, durations, render times, QA numbers), known gaps. If you get stuck in a loop more than twice on the same problem, write what blocked you into that file and stop.
