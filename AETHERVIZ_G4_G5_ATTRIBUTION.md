# Aetherviz G4/G5 graft attribution

Graft: aetherviz-master G4/G5, A1–A6 + B1–B4 (10 capabilities),
clean-room method-only restatement. No SKILL.md/README text
copied, no branch `web/` code, no vendored GSAP file, no demo
images, no `three.min.js`. No registration, no login, no
payment, no paid generation call was made for this graft.

Method sources (read-only, 2026-11-20):

- `~/workspace/hevi-vs-aetherviz-g4-g5.md` — the hevi-side
  assessment (G4/G5, sections 1–3). The projection formula,
  the five-segment 30/60/60/60/30 structure, the single
  timeline mounted at `window.__timelines['main']`, the
  fromTo + xPercent/yPercent rule, and the cost figures are
  restated from that report, not from upstream prose.
- `~/workspace/references/aetherviz-master/` — master SKILL.md
  (read-only reference for the projection formula and the
  hybrid-render rules; no text copied).
- `~/workspace/references/aetherviz-master-branch-claude/` —
  unmerged branch (read-only reference for the two-stage
  preview-to-video pipeline shape; no code copied).
- `physics.atlas_figure` (`hevi/capabilities/atlas_figure.py`,
  `atlas_figure.md`) — the Atlas label field in
  `scene.parts[]` and pending item 3 (label overlay anchored
  to 3D points) are the gap B1 fills as a contract; the Atlas
  PALETTE names govern A3 colours.

## Licence notes

- GSAP is GreenSock standard licence (Copyright GreenSock,
  all rights reserved), **not MIT**. No GSAP file is vendored
  here; `qa.gsap_timeline_honesty_gate` accepts only
  `gsap_source` `method_only` or `vendored_standard_license`
  and fails any claim of MIT.
- `three.min.js` (MIT, REVISION 134 in the branch) is not
  copied; the A1 gate takes a caller-supplied camera matrix
  and never imports Three.js.
- The upstream branch `web/` application (Next.js, Anthropic
  key, undeclared hyperframes CLI) is not followed as a
  whole: hevi already has Remotion and HyperFrames render
  lines, so no third application is added.

## HyperFrames CLI: version not pinned upstream

The branch calls `npx hyperframes render` with no version in
`package.json` or `package-lock.json` and no locked source.
This graft does not invent a version: `qa.paid_generation_cost_gate`
and `video.preview_to_video_pipeline_schema` both fail when
`hyperframes_version` is undeclared, so no paid step can be
declared without a pinned version. The pin itself is still
open (see residuals).

## Paid cost basis (public prices, not in-repo prices)

Claude Sonnet 4.6 public pricing: input $3 / million tokens,
output $15 / million tokens. Two calls at most 16,000 output
tokens each: output ceiling 32,000 x $15 / million = $0.48,
plus roughly $0.01–0.02 of input: single-film ceiling about
$0.50. Realistic output (8,000–12,000 tokens per call) is
about $0.25–0.40 per film. Retries and preview revisions
cost extra. The Anthropic key is a new paid dependency that
is not connected here; `qa.paid_generation_cost_gate` fails
every call while `anthropic_key_connected` is false.

## Provenance: zero-source reverse gap, G1 gate first

G5-generated content carries no source mechanism, the same
reverse gap as the master branch. Content entering the
teaching line must first pass the already-registered
per-sentence source ledger gate `qa.source_sentence_ledger`
(`check_source_sentence_ledger`,
`hevi/capabilities/source_sentence_ledger.py`); A4 enforces
this with `teaching_provenance_missing` when `teaching_line`
is true.

Verification correction: the graft brief named a
`citation_check` entry point, but a full-tree grep of the
worktree at 54f2972a finds no `citation_check` module,
capability, or function anywhere in hevi. The real
already-registered provenance gate is
`qa.source_sentence_ledger`; A4 cites that name only, and
the test `test_five_segment_rejects_wrong_provenance_gate_name`
locks the correction in.

## Verification corrections made during this graft

- Atlas colour: the assessment states the Atlas convention
  as force-red / velocity-blue / acceleration-green. The
  Atlas code (`atlas_figure.py` PALETTE) defines red and
  blue but **no green palette**, and the bundled figures use
  velocity-blue and gravity-ink; the green (`#22C55E`) is
  the SKILL.md ArrowHelper hex, not an Atlas palette entry.
  A3 therefore enforces force-red and velocity-blue as Atlas
  palette names and refuses any non-Atlas colour (including
  `green` and hex codes) rather than inventing a palette.
- Layer attribution source: the Mica-side copy
  `~/workspace/3o-conformance/layer_attribution.json` holds
  only 397 entries and is stale; the live source is
  `/data/soffy/3o-conformance/layer_attribution.json` on
  ubuntu26 (573 entries). This graft extended the live JSON
  (573 -> 583) and regenerated
  `hevi/capabilities/layer_attribution.py` with
  `scripts/ci/gen_layer_attribution.py`; the generator HEADER
  constant still reads 461 and was left unchanged, same as
  prior grafts, with the table header hand-synced to 583.
  (Registry 578 -> 588; the 5 unattributed `anidoodle.*`
  entries are the pre-existing gap, unchanged.)
- Test runtime: the worktree has no `.venv` of its own; tests
  run with the main checkout venv
  `/data/soffy/projects/hevi/.venv` (Python 3.14.4), which
  imports hevi from the worktree when run with the worktree
  as the working directory.

## Layer note

A gates (`qa.*`) register kind `line`, layer `oskill`;
B schemas (`video.*`) register kind `video`, layer `obase`,
line `video`, following `talkback_film_gate.py` /
`talkback_film_schema.py`. B4
(`video.hyperframes_composition_schema`) is a different
layer from the existing `video.hyperframes_styles` (18-style
catalogue) and `video.hyperframes_styled_render` (beats JSON
+ style id -> render) in `csk_styles.py`: it certifies only
the GSAP-timeline composition (composition id, duration,
tracks, timeline mount) and chooses no style, renders no
frame, and runs no timeline.

## Residuals (not this graft)

- Paid generation calls need a separate decision: Soffy must
  approve an Anthropic key and a per-film budget first; the
  A6 gate blocks every call until then.
- The HyperFrames CLI version pin is still undecided (source
  and version to be set before any render declaration can
  pass A6/B3 with a real version string).
- The branch `web/` application as a whole is not followed.
- Production sync is a separate step; production untouched.
- Baseline gaps unchanged: 5 `anidoodle.*` capabilities stay
  unattributed, and the omodul pillars test still expects a
  hardcoded 55 against 57 actual (both pre-existing, verified
  in the clean 54f2972a baseline worktree).
