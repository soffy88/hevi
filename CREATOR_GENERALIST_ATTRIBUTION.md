# Creator-Generalist Attribution

Method restatement only. No SKILL text, template code, engine code, sample
project, asset or prompt from the repository was copied into hevi. The six
capabilities below restate methods in hevi's own words and judge or compile
plans; rendering still goes through hevi's existing scene3d / explainer /
shorts_clip / reference_adapt lines.

## Source reviewed

- Public repository `codepawl/creator-generalist` (MIT).
- Local clone: `/data/soffy/projects/creator-generalist`.
- Newest commit seen during review: `85bb905` (2d-generalist 0.9.0).
- License: MIT, copyright CodePawl, 2026. Full text kept at
  `third_party/creator-generalist/LICENSE`.
- The skills were already installed for the local worker under
  `~/.config/opencode/skills` (2d-generalist, 3d-generalist, watch-video,
  design-sound, edit-video, and their craft/tool skills). They were read as
  reference only; hevi does not shell out to them at runtime.

## What was absorbed (method only)

| # | Method | Where it lives in hevi |
|---|---|---|
| 1 | 3D cutaway / build process: 5–7 rounds of failure → improvement, real CC0 / CC BY assets first, CREDITS required, 720p preview → confirm → 1080p | `hevi/studio/generalist_s23.py` `plan_cutaway` / `check_asset_manifest` / `credits_markdown`; formats `history_scene` → `cutaway_3d`; reuses `hevi/scene3d/blender/pipeline.py` queue and approval gate |
| 2 | 3D era scene / world: period research, geography, scale, lived-in detail, a path into the world, sound bed first | `plan_world`; formats `history_scene` → `world_3d` |
| 3 | 2D editorial: map route drawing, true-scale timeline, archival collage with paper / halftone / torn edge, Remotion/SVG, free tools | `plan_editorial_2d` / `check_timeline_scale`; formats `history_scene` and `explainer` → `editorial_2d` |
| 4 | Character motion rules: head leads body by 4–6 frames, staggered joint stops, anticipation and reaction beats; contact/slip/float self-check | `check_character_motion` / `check_contact_and_slip`; `character_animation` line gets the rules via `plan_for` |
| 5 | Sound for phone speakers: usable band, low-end dominance, mid burial, masking margins, sync tolerance | `check_phone_speaker` / `check_masking` / `check_sync` |
| 6 | Watch-video remake recipe: frame sheet, cuts, spectrogram peaks, transcript → a recipe for `reference_adapt`; Shorts editing spec (hook, pacing, beat sync, caption safe zone, platform export) | `plan_remake_recipe` / `audit_shorts_edit`; formats `material_cut` → `reference` / `shorts` |

## What was NOT taken

- No SKILL.md prose, question flow, template, plan JSON, prompt or code was
  copied. The functions above are new hevi code written from the method.
- No paid service is called: no ElevenLabs, no HunyuanVideo-Foley, no Google
  Flow, no paid model. The sound methods are checks against numbers hevi
  already measures locally.
- No new runtime dependency, model download or asset download was added.
- No 67js, three.js template, GLB or texture from the repository is bundled.
- Character likeness, voices and brand assets are not included.

## Third-party components referenced by the method

Named only so the lineage is auditable; none is bundled or invoked by this
graft:

- Blender (GPL) — already a local render dependency of hevi scene3d.
- Remotion and SVG — already used by hevi explainer / motion templates.
- FFmpeg, Pillow — already local dependencies.
- CC0 / CC BY asset sources (Poly Haven, ambientCG, Sketchfab CC filter,
  BlenderKit free plan, Wikimedia Commons) — only a policy list; no asset is
  downloaded by this stage.

## Asset credits for S23 blackbox

The S23 blackbox renders 12 clips with hevi's own procedural geometry and
type; it downloads no external asset. A CREDITS block is still produced by
`credits_markdown()` and is empty by design for this run. See
`docs/S23_3D_ASSET_CREDITS.md` for the policy that any future real asset must
follow.
