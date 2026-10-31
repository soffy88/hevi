# Attribution: editorial project model (method ideas)

Source: `BeatAPI/BeatDesign` (Apache-2.0), as reviewed in
`~/workspace/hevi-vs-beatdesign.md` (read-only review of the
repository at v0.2.5, 2026-10-30). Method ideas and contract
discipline only, clean-room rewritten; no code, text,
configuration, UI, workflow template or media from that
repository is copied into hevi, and the station itself is not
installed. Naming the upstream repository here is provenance
for this attribution, not use of its name as a hevi product
name: no hevi capability, page or product is called by that
name, and the provider brand is likewise not used.

What was borrowed (data-model discipline only, review
section 2 / section 8 items A1-A4):

- Asset-first: one generation produces one Asset; views only
  reference Assets, and removing a view reference never
  deletes the Asset.
- Clip pinned to one concrete Asset: changing a pinned output
  never silently moves an already-cut clip; replacement needs
  explicit confirmation.
- Takes: alternatives for one clip slot, activation never
  moves the clip, the Original is always restorable, and a
  Take shorter than the slot cannot be activated.
- Revision/CAS plus idempotent receipts on a single
  incremental write path, with whole-document replacement
  refused; lineage stored separately from canvas edges.

What was deliberately NOT taken, and remains unimplemented
(residuals, in the review's B/C terms):

- B1 MCP project-operation layer (no command kernel, no
  browser handoff, no polling visibility).
- B2 Browser canvas + timeline UI (no React Flow canvas, no
  interactive timeline editor).
- B3 Browser MP4 export discipline (no WebCodecs export, no
  stale-revision export refusal, no export-write-back).
- B4 Workflow templates / Elements (no fixed-version
  elements, no reusable local templates).
- C1 The whole station: not installed, not deployed; hevi
  keeps its own backend shape.
- C2 Any provider adapter or key/account/billing system: no
  remote generation is wired through this model, and no
  credential is stored or handled here.
- C3 Trademarks and brand names: not used as hevi product
  names (see above).
- C4 The upstream Skill directory and showcase: the upstream
  Skill directory was intentionally empty at review time;
  nothing was taken from it.
- C5 Desktop shell / packaging: not a finished upstream
  feature at review time; not touched.

Upstream evidence limits (from the read-only review): the
review read the repository's docs, architecture notes and
tool inventory; it did not run the station end to end, did
not pay for a generation, and did not verify the provider
catalogue beyond the review's own directory check. Nothing
in this graft relies on the upstream demo or screenshots.
The hevi-side prompt/frame gates (compile-time anchors,
prompt evaluation, frame-count truth) are hevi's own and
are untouched by this graft.
