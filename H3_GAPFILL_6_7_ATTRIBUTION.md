# Attribution — H3 exemplar gapfill 6 + 7

Clean-room method rewrite. No code, image, audio, or prompt text was
copied from any external repository.

- **Method source**: the 14-segment H3 exemplar prompts supplied by
  Soffy in chat (purple xianxia solo dance MV), as analysed in
  `~/workspace/hevi-vs-h3-exemplar-prompts.md` (v1) and
  `~/workspace/hevi-vs-h3-exemplar-prompts-v2.md` (v2, 14-segment
  deep/broad empirical run). Gap 6 (1s beat floor vs sub-second
  opening beats) and gap 7 (match direction field stretched by
  element names) are gaps 6 and 7 of the v2 report's §7 list.
- **What was built**: `qa.beat_floor_policy` (default 1.0s floor
  identical to `story.prompt_compiler` gate 1; reviewed lower floors
  need a recorded reason; short-beat merging with an audit trail
  preserving tiling, total duration, and all action/camera text)
  and the `handoff_kind` extension to `qa.segment_match_gate`
  (closed vocabulary; element/fabric hand-offs name their element
  in `element_name`; direction holds direction values only).
- **Not built / not invented**: the dance motion-chain vocabulary
  (`dance-motion-chain-h3.md` Rev.1.4, C13/C16/C17/C36/C44/C45) —
  the document was never supplied and no chain was invented;
  cast-count / environment-lock machine checks (v2 gap 5); rounded
  timecode detection (v2 negative N5). Structure evidence only:
  no real H3 generation was run, no Picture 1–3 or audio bytes
  exist (placeholder bindings only), and "structurally qualified"
  is never claimed to mean "film qualified".
