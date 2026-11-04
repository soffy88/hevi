# 20 Open Skills Graft — Attribution and Method Notes

Clean-room method intake only. No source code, example project,
SKILL text, asset, or binary from any of the 20 repositories was
copied into hevi, and no package was installed. What was taken in
is method vocabulary and discipline gates, restated in hevi's own
words. Effects that were never verified on real hardware are
recorded as unverified; nothing in this graft claims a render,
a transcription, a simulation, or an installed tool.

## What was built (2026-11-04)

A1–A6 (discipline gates, `oskill`):

- `qa.remotion_skills_method_gate` — composition frame/time
  arithmetic, caption declaration, pinned-commit citation, and
  no verified-render claim without named evidence.
- `qa.animejs_v4_vocabulary` — v4 entry points and easing strings
  only; v3 spellings fail.
- `qa.motion_variant_gate` — `motion/react` vs `motion/dom`
  entry-point split with matching API kinds.
- `qa.postprocessing_variant_gate` — pmndrs package vs three.js
  bundled passes, import paths must agree with the variant.
- `qa.whisperx_subtitle_contract` — word-level timestamps and
  diarization declaration; execution stays contract-only.
- `qa.open_skills_method_notes` — the 20-item license/version
  table with a citation check.

B1–B2 (contract fakes, `obase`, `executed_here: false`):

- `video.lottie_overlay_adapter` — overlay contract by source
  reference; no player bundled, nothing rendered.
- `video.quarks_particle_contract` — emitter contract with a
  pinned library version and a GPU acknowledgement; nothing
  simulated or rendered.

Deferred (not built here): B3 Jolt rigid-body contract, B4
CosyVoice narration contract with a voice-authorization gate,
B5 Tweakpane panel contract. Production sync is a separate
decision; this graft only lands on main.

## Pins and corrections recorded

- Remotion Skills (`remotion-dev/skills`): license undeclared,
  no release. Intake pinned to main-branch commit
  `c7cb2fdcacd134fb2ccb9b7a44f9ffa44e467271` (2026-11-02).
  Method only; no SKILL text copied.
- Anime.js: v4 series only (package `animejs` 4.5.0, MIT).
  Entry points and easing forms were read off the v4 source
  exports. v3 and v4 APIs are not compatible; v3 spellings fail
  the gate.
- Motion is the open successor of Framer Motion; the split is
  `motion/react` (components/hooks) vs `motion/dom`
  (standalone calls).
- MCP for Blender's repository is `ahujasid/mcp-for-blender`
  (community plugin, not a Blender Foundation product). hevi
  already wires it (`video.blender_mcp`); only the name
  correction is recorded here.
- CosyVoice now lives under `QwenAudio/CosyVoice`; maintenance
  has slowed. Its contract is deferred behind a
  voice-authorization decision; the voice-clone route is never
  connected.
- WhisperX is active (commits into 2026-10); the "stalled"
  claim is false. In hevi it exists only as a stub comment;
  live ASR runs on faster-whisper.
- Jolt Physics is rigid-body and collision focused; "soft body"
  is narrowed accordingly. Its contract is deferred.
- Postprocessing: the pmndrs package and the three.js bundled
  passes are two implementations; hevi's scene3d template uses
  the vendored three.js passes.
- Remotion container rendering is unverified (previously
  failed with EACCES in-container). No claim in this graft
  says otherwise.
- three.quarks and Tweakpane maintenance has slowed; versions
  are pinned by declaration and effects are unverified.

## License summary (20 items)

License strings below are taken from each repository's own
LICENSE text; where the hosting API reported NOASSERTION that
is recorded as such and is not treated as a conclusion. Only
method vocabulary was taken in, so no license obligations from
copying arise; GPL items are kept to local-backend or method
reference only, never modified, redistributed, or statically
linked into a hevi distribution.

| # | Item | License |
|---|---|---|
| 01 | Remotion | per in-repo LICENSE text (API: NOASSERTION) |
| 02 | Remotion Skills | undeclared |
| 03 | Anime.js | MIT |
| 04 | Motion | MIT |
| 05 | Manim | MIT |
| 06 | Lottie (lottie-web) | MIT |
| 07 | MCP for Blender | MIT |
| 08 | Three.js | MIT |
| 09 | Three GPU Pathtracer | MIT |
| 10 | Jolt Physics | MIT |
| 11 | postprocessing (pmndrs) | Zlib |
| 12 | three.quarks | MIT |
| 13 | Tweakpane | MIT |
| 14 | ComfyUI | GPL-3.0 |
| 15 | CosyVoice | Apache-2.0 |
| 16 | librosa | ISC |
| 17 | WhisperX | BSD-2-Clause |
| 18 | OBS Studio | GPL-2.0 |
| 19 | LosslessCut | GPL-2.0 |
| 20 | FFmpeg | per in-repo LICENSE text (API: NOASSERTION); LGPL/GPL dual track |

Totals from the table: MIT 10 items (03–10, 12, 13); Zlib 1;
ISC 1; BSD-2-Clause 1; Apache-2.0 1; GPL-2.0 2; GPL-3.0 1;
undeclared 1; per in-repo LICENSE text 2 (01, 20). The
comparison report's count wording is kept in
`hevi-vs-20-open-skills.md`; this file is the graft-time record.

## Already present in hevi (not rebuilt)

Manim, MCP for Blender, Three.js, ComfyUI, librosa, the
LosslessCut cutting method, and FFmpeg were already in hevi and
were not rebuilt. OBS recording is not a finished-film pipeline
step and was not built.
