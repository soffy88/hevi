# Attribution: H3 exemplar gapfill (gaps 1, 2, 4)

Method source: the 14-segment H3 exemplar prompt text supplied by
the user (a purple xianxia solo-dance MV), as analysed read-only in
`~/workspace/hevi-vs-h3-exemplar-prompts.md` (segment 01 run in
full; the remaining 13 segments were not run). No repository was
read, no upstream code was copied, and no exemplar prompt text was
copied verbatim into any default prompt: only the method was
rebuilt -- the numbering-convention discipline, the segment
hand-off fields, and the millisecond / per-beat-camera discipline.

What was grafted (clean-room, method only):

- Gap 1 `qa.reference_numbering_gate` -- declared numbering
  convention (identity-first vs scene-first) checked against the
  mounted picture order; `camera_composition` as its own role
  (composition geometry only, `composition_only` declared); audio
  references registered with file + sha256 + local-clock start;
  the H3 scene-assembly route is judged here and never returns
  `not_checked`. `H3_SECTIONS` is not redefined anywhere in this
  graft; the six-section definition stays solely in
  `pipeline.scene_reference`.
- Gap 2 `qa.segment_match_gate` -- outgoing/incoming match schema
  (gesture, direction, speed, end/start state, rotation phase,
  occlusion direction) with cross-segment boundary checks. The
  `story.prompt_compiler` entry/exit continuity dictionaries are
  untouched.
- Gap 4 `qa.three_layer_clip` -- `_fmt_time` now renders
  millisecond timecodes (three decimals), per-beat physical
  cameras (height / distance / optical axis / path) with a
  repeated-camera failure unless a static camera is explicitly
  declared, and `THREE_LAYER_FIXTURE_VERSION` bumped 1 -> 2 for
  the new frozen fixtures. `story.prompt_compiler` carries and
  renders the same per-beat camera field; the frame-count fork
  (fasth3 318 vs H3 328 frames for 13.268s) is kept as-is, each
  route on its own count, never silently unified.

Deliberately NOT carried over:

- The dance motion chain (gap 3 in the report): the
  `dance-motion-chain-h3.md` Rev.1.4 document was never supplied,
  and no C-chain vocabulary (C13/C16/C17/C36/C44/C45), chain
  timing, or classical-dance sequence was invented. The dance
  action library still requires that document.
- The casting / environment-lock machine checks (gap 5 in the
  report): `cast_count == 1` and the prop whitelist against a
  visible-objects list were not built; they need human or visual
  annotation that was not supplied.
- No generation was run, no model key or budget was touched, and
  no production container or file was changed. This graft is
  plan-level gates and rendering only.
