# Creator-buddy method attribution (2026-10-28 intake)

Method inspiration only; no upstream text was copied into hevi.

- Source repository: SpaceZephyr/creator-buddy
  https://github.com/SpaceZephyr/creator-buddy
- License status: UNVERIFIED. The repository root LICENSE returned
  404 when checked during the deep-dive review, and a README badge
  alone is not evidence of a license. Nothing from that repository
  is vendored, quoted or redistributed here for that reason.
- What was borrowed: the working methods behind five finished-film
  disciplines -- a fixed project directory with a per-step manifest,
  a final quality gate over a finished film, caption rules for
  breath breaks, a glossary and post-edit retranscription, a fixed
  mix recipe with a loudness gate, and a motion beat chart with a
  still-picture gate. All module text, parameter names, checks and
  tests in this intake were written fresh for hevi.
- What was NOT borrowed: the source repository's skill text, its
  scripts, its trigger-word routing, its external skill
  orchestration, and any route that bypasses a platform's download
  login. hevi's existing renderers (video.code_render, Manim,
  Blender), prompt checks (prompt_compiler) and shot continuity
  checks (shot_continuity) are reused, not duplicated.
- Upstream methods the source repository itself credits (named
  here so a re-arrangement is not mistaken for an original):
  rnskill, chengfeng-videocut-skills, douyin-mcp-server,
  video-spec-builder, hyperframes, Seedance, libtv. Where hevi
  already had an equivalent, hevi's own implementation stands.

New capabilities in this intake:

- pipeline.project_handoff (project_handoff.py)
- qa.final_qc_gate (final_qc.py)
- edit.subtitle_discipline (subtitle_discipline.py)
- audio.mix_recipe (mix_recipe.py)
- video.motion_beat_chart (motion_beat_chart.py)
