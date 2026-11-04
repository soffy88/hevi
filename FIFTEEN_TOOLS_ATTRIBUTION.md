# Attribution: 15 open tools list (second list)

Method restatement only, from the read-only comparison report
`hevi-vs-15-open-tools.md` (2026-11-04). No source code, sample
project, SKILL text, brush bundle, plugin, or desktop
application from any of the 15 repositories was copied,
installed, or bundled into this repository. Twelve of the 15
items overlap the earlier 20-item list; their earlier
findings stand (see `OPEN_SKILLS_ATTRIBUTION.md`). This file
records the three new items, the CosyVoice attribution
correction, the Audacity license correction, and the honest
standing of the "one prompt, one finished film" shape.

## The three new items

| # | Item | Repository | License (per in-repo LICENSE text) | Standing |
|---|---|---|---|---|
| 02 | Krita | KDE/krita (GitHub mirror; true home invent.kde.org) | GPL-3.0 | Desktop application (Qt/KDE), no SDK. File-contract gate and read-only asset index only; painting and export are a real-machine case. |
| 08 | React Three Fiber | pmndrs/react-three-fiber | MIT | v9 line: React >= 19 below 19.4, Three.js >= 0.156. Variant gate and scene contract only; no React build chain here, rendering is a real-machine case. |
| 13 | Audacity | audacity/audacity | GPLv3 (some files GPLv2), per in-repo LICENSE.txt | 4.x has no official scripting entry point; 3.x keeps macro/script-pipe automation. Version/interface gate only; effect-chain contract built in deferred batch B. |

## Corrections recorded by this graft

- **CosyVoice attribution (correction):** the canonical code
  repository is `QwenAudio/CosyVoice`; `FunAudioLLM/CosyVoice`
  is the old address and redirects to it. Model releases still
  publish under the `FunAudioLLM` namespace. Cite code as
  QwenAudio, models as FunAudioLLM; never mix the two. Code
  license Apache-2.0. Maintenance recorded as slowed (last
  observed push 2026-05-25). The voice-cloning route is never
  connected.
- **Audacity license (correction):** the earlier 20-item round
  recorded GPL-2.0; the repository's own LICENSE.txt names
  GPLv3 first, with some files under GPLv2. GPLv3 governs
  this record.
- **Krita home:** GitHub hosts a mirror only; the project's
  true repository home is invent.kde.org. No GitHub release
  is published from the mirror.

## License summary for the 15 items

MIT 7 items (Anime.js, Manim, Lottie-web, mcp-for-blender,
Three.js, React Three Fiber, Motion); Apache-2.0 1
(CosyVoice); BSD-2-Clause 1 (WhisperX); GPL-3.0 2 (Krita,
ComfyUI); GPLv3 with some files GPLv2 1 (Audacity); GPL-2.0
1 (LosslessCut); LGPL/GPL dual track 1 (FFmpeg); per in-repo
LICENSE text 1 (Remotion, API reports NOASSERTION).

GPL-family items (Krita, ComfyUI, Audacity, LosslessCut,
FFmpeg) are file-format, local-execution-backend, or method
reference only. Nothing GPL-licensed is modified,
redistributed, or statically linked into hevi deliverables
by this graft; Krita and Audacity are desktop applications
and the compliance boundary is invocation, not carriage.

## "One prompt, one finished film": not connected

The honest standing, recorded by
`qa.one_shot_film_honesty_gate`: the front of the pipeline
(design, gates, contracts) is in place; the execution steps
(generation, rendering, narration) still need keys and
graphics hardware. The shape is not connected and must not
be presented as connected. Any ready/connected or
end-to-end-verified claim fails the gate.

## What was built (2026-11-04, this graft)

- A1 `qa.krita_file_contract_gate` (oskill): .kra ZIP
  container, source preservation, three handling modes.
- A2 `qa.r3f_variant_gate` (oskill): React Three Fiber v9
  combination vs plain Three.js declarations.
- A3 `qa.audacity_version_gate` (oskill): 4.x no-scripting
  rule, 3.x interface declaration, project-format check.
- A4 `qa.cosyvoice_attribution_note` (oskill): code/model
  attribution split, clone/installed/maintenance claims fail.
- A5 `qa.one_shot_film_honesty_gate` (oskill): seven-stage
  honest status; connectedness claims fail.
- B1 `video.krita_asset_index` (obase, fake): read-only
  layered-asset index contract; nothing read or written.
- B2 `video.r3f_scene_contract` (obase, fake): canvas /
  camera / primitives contract under a gate-passing renderer
  declaration; nothing built or rendered.

B3 (Audacity effect-chain contract, 3.x-only) was built
in deferred batch B (2026-11-04, see 'Deferred batch B'
below). Production was not touched; effects
were not verified on real machines. Third-party bridges
(Krita 6 MCP bridge, Audacity4-MCP companion fork) are
unproven, are not official, and were not built or compiled.

## Deferred batch B (2026-11-04)

- B3 `audio.audacity_effect_chain_contract` (contract only,
  `executed_here: false`, `audio_rendered: false`): an
  ordered effect chain against the 3.x macro/script-pipe
  interface with the `aup3` project format. Any 4.x
  scripting claim fails closed, because the 4.x line
  currently offers no official scripting entry point.
  Effect names are hevi's contract vocabulary; exact 3.x
  effect names and parameter ranges are a real-machine
  case. No desktop application was installed and no audio
  was processed; real execution needs a 3.x Audacity
  session on a real machine.
