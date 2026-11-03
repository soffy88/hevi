# HyperFrames attribution

Two different things share the name "HyperFrames" in hevi's
history. This file keeps them apart.

## 1. HeyGen HyperFrames (engine discipline)

- Source: `heygen-com/hyperframes` — "Write HTML. Render video.
  Built for agents." License: **Apache-2.0** (LICENSE is the
  standard Apache-2.0 text; no NOTICE file was present at the
  time of the deep dive, 2026-10-31, v0.8.223).
- What was taken: **method discipline only, clean-room
  rewritten** — the `window.__hf` seek protocol and FrameAdapter
  concept (`getDurationFrames` / `seekFrame` / `destroy`),
  settle confirmation before capture, BeginFrame-style atomic
  capture, frame-time integer math `t = floor(frame) / fps`,
  determinism lint rules (no wall clock, no unseeded randomness,
  no fetch during render, variables locked before frame 0),
  frozen-picture judgement and motion-blur settle judgement.
  No upstream code, text or configuration was copied; the
  upstream Studio, studio-server, SDK, CLI, skills, Parakeet
  model and mediabunny were **not** touched (report §7, class C).
- Excluded from the Apache-2.0 grant (per upstream CREDITS.md):
  mediabunny (MPL-2.0), the Parakeet TDT speech model
  (CC-BY-4.0), vendored three.js files (MIT), GSAP and other
  third-party components listed there. The "HyperFrames" /
  HeyGen brand names are trademarks, not code: hevi must not
  use them as a product name.
- Modules: `qa.frame_adapter_contract`,
  `qa.deterministic_render_gate`, `qa.render_lint`,
  `qa.frozen_picture_gate`, `hevi/video/hf_adapter.py`.
  The gates judge plans and offline frame records; the
  streaming-encoder discipline is contract-layer only (chunk
  order + hash verification), not a real encoder.

## 2. creator-style-kit (style templates, NOT an engine)

- Source: `threeaus/creator-style-kit` (陆三金), License: **MIT**.
  18 sets of 9:16 vertical-screen style templates (chapter /
  list / stat beats), rendered by hevi's own renderers
  (`hevi/video/csk_styled_render.py`).
- Fonts are excluded from the kit distribution: MiSans (free
  for commercial use, no modification/resale) and 优设标题黑
  (free for commercial use) must be fetched per project;
  SFX are Kenney/uisfx, CC0.
- Naming: the registered capability names
  `video.hyperframes_styles` / `video.hyperframes_styled_render`
  are kept stable for call-chain compatibility, but they are
  **CSK style templates + hevi's own renderer — not the HeyGen
  HyperFrames engine**. Documentation and capability
  descriptions must say so. Do not describe the CSK styles as
  the HyperFrames engine.

## 3. Not done (residuals, recorded 2026-10-31)

- B2 sound-pass wiring (delivered mp4s have no audio stream).
- B4 per-style实拍 verification matrix for all 18 styles
  (only warm-notebook was end-to-end verified before this
  graft; dark-keynote blur is addressed by settle capture,
  see the graft commit).
- Wiring the CSK renderer into the `storyfilm` main path
  (the `hyperframes` route in `storyfilm.py` is still an
  orphan: registered, not called from the main path).
