# Animation Studio 18 — Attribution

Graft date: 2026-11-20. Source: the 18-repo "animation studio"
post, checked read-only in `~/workspace/hevi-vs-animation-studio-18.md`.
Only the 6 true gaps were grafted (A1–A6 gates, B1–B6 fake
contract schemas). No upstream code, weights, example material,
or demo content appears anywhere in this graft. No runtime was
installed, no model was downloaded, no key or account was used.

## What was grafted, and from what

| Graft item | Upstream repo | License (verified 2026-11-20) |
|---|---|---|
| A1/B1 Motion Canvas explainer | motion-canvas/motion-canvas | MIT |
| A2/B2 Motion layout/gesture | motiondivision/motion | MIT |
| A3/B3 Ola smooth interpolation | franciscop/ola | MIT |
| A4/B4 Two.js vector scene | jonobr1/two.js | MIT |
| A5/B5 gifenc GIF export | mattdesl/gifenc | MIT |
| A6/B6 Konva interactive stage | konvajs/konva | MIT (LICENSE file read) |

All six grafted sources are MIT. The graft is clean-room method
only: gates and contract schemas restate the method in hevi's
own words; nothing was copied from any upstream file.

## What was NOT grafted, and why

- Remotion Skills (`remotion-dev/skills`): already in hevi
  (`remotion_skills_method_gate` + bridge contract/smoke), and
  the skills repo carries **no LICENSE file** — its text is
  under default all-rights-reserved, so it must never be copied.
- Manim, Anime.js, Lottie Web, Blender, Three.js: already in
  hevi. Blender is **GPL** (`COPYING`: "Apart from the GNU GPL,
  Blender is not available under other licenses") — usable only
  as an external tool call, its code is never moved into hevi.
- Shifty, TweenJS, LUME, Proton: duplicates of capabilities
  hevi already has (GSAP/Anime.js tweening, Three.js scene
  layer, `quarks_particle_contract`); TweenJS is also ~2 years
  unmaintained. Not grafted.
- Godot, Babylon.js: whole game engines, a different layer from
  hevi's video pipeline; not grafted.

## The "all free" claim, corrected

The post's "全都免费" is only half true, and this graft does
not repeat it as verified:

- 16 of the 18 repos are MIT/Apache-2.0 and genuinely free as
  code. The exceptions are Remotion's main repo (custom
  two-tier license: free for individuals and small companies
  including commercial use; larger for-profit organisations
  need a company license), Blender (GPL — free to run as a
  tool, code not freely re-licensable), and `remotion-dev/skills`
  (no license at all — not free to copy).
- Hidden costs the post does not mention: the code is free,
  but rendering, compute, and time are not (Remotion browser
  rendering, Manim, Blender, and Godot all consume local
  compute). Nothing in this graft claims zero cost.
- Update staleness recorded at check time: TweenJS last pushed
  2023-12-18, Lottie Web 2025-09-01, gifenc 2024-09-19,
  Motion Canvas 2026-07-02. The gifenc gate pins no upstream
  version and does not depend on upstream freshness; it only
  gates the export shape.

## Execution layer

All twelve capabilities are method/contract only
(`executed_here: false`). Real execution — a Motion Canvas
runtime, a Motion runtime, a Two.js runtime, a gifenc/ffmpeg
runtime, a Konva runtime — is a separate work item and was
not installed, run, or verified here.
