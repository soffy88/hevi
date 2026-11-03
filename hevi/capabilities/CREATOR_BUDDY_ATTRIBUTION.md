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

P1/P2 intake (2026-10-28, clean-room, method ideas only):

- pipeline.spend_brake (spend_brake.py): storyboard table plus
  machine-readable confirmed=true plus a single-frame/single-segment
  smoke run before any paid batch; unconfirmed, storyboard-less, or
  unsmoked batches are refused with the missing step named.
- script.spoken_script_gate (spoken_script.py): per-sentence
  speakability checks (long sentences, written connectives, parallel
  lists, unpronounceable punctuation, stock phrases, vague adjectives)
  with a rewrite for each problem sentence; no score is reported.
- edit.speech_blemish_trim (speech_blemish_trim.py): live recordings
  only, from word-level transcript through candidates, the
  keep-before/keep-after guard, risk tiers, a review checklist, keep
  intervals, and provisional post-trim captions that must be replaced
  by fresh transcription of the trimmed audio. TTS tracks are refused.
- design.cover_family (cover_family.py): pinned primary/secondary
  colours, headline font, title zone and brand-mark zone, plus a
  200px readability gate (scaled title size and contrast thresholds).
  Without a rendered image the gate is an arithmetic projection, not
  a viewed thumbnail, and is reported as such.
- research.reference_teardown (reference_teardown.py): hook, pain
  point, information gain, and closing hook answered only from quoted
  source evidence (gaps reported as gaps), per-candidate title risk
  reviews, and structured transcripts. Teardown only: no reference
  material or wording is reused, and a failed fetch lists its missing
  backend instead of fabricating content.

License status is unchanged: UNVERIFIED (root LICENSE 404 at intake
time). Nothing from the source repository is vendored, quoted, or
redistributed in this intake either. No P0 module was changed.
