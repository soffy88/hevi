# Attribution: seven-step video workflow graft

Method source: an unsigned, repository-less long article describing a
video-generation workflow ("spec first, write in segments, verify as
you generate, never hand to the model what post can do"), reconstructed
from the article's text in `hevi-vs-video-workflow-7steps.md`. No
repository was read, no code or prompt text was copied, and the
article's generic prompt template was NOT copied verbatim into any
default prompt.

What was grafted (clean-room, method only):

- A1 `qa.generation_spec_gate` -- four-item spec sheet gate.
- A2 `qa.ban_revision_log` -- rule_id + supersede revision chain.
- A3 `qa.verdict_vocabulary` -- single pass/fail/not_checked vocabulary.
- A4 `qa.post_production_checklist` -- seven post items + generation-side refusal.
- B1 `qa.reference_role_gate` -- identity/costume/pose/scene division, max four.
- B2 `qa.hardest_shot_pilot` -- hardest shot first + caller-supplied reserve.
- B3 `qa.three_layer_clip` -- three layers, one action + one camera move
  per segment; `qa.prompt_eval_harness` SAMPLE_VERSION bumped 2 -> 3
  for its two new frozen samples (v2 samples untouched).
- B4 `qa.fix_ticket` -- timecode correction ticket schema.

Deliberately NOT carried over:

- The article's example numbers (six quota units holding back one or
  two; 0-3 / 3-7 / 7-10 second splits for a 10-second shot) were
  never written into defaults or acceptance thresholds. The reserve
  fraction and the freeze-pad threshold are required caller inputs;
  segment windows follow each beat's own declared times.
- The H3 six-section structure (`H3_SECTIONS`) was not redefined,
  renamed, reordered, or merged with the three layers.
- `duration_tiers.json` numbers were not changed; null caps stay null.
- No generation call, key, or budget is touched by any of these
  modules. Rendering the freeze-pad, the Jianying draft, and any
  real generation remain out of scope.
