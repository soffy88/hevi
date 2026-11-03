# Athenaion attribution (method source)

Method source: Athenaion by Leon Lin (GitHub: Leonxlnx),
MIT License, Copyright 2026 Leon Lin, as reviewed read-only in
`~/workspace/hevi-vs-athenaion.md` (2026-11-01). The graft in
this directory learns only the *methods and disciplines*
described in that report:

- A1 contract-first discipline: build/test dual exports, shared-file
  ownership, READY markers, footprints/slots/registry coordination,
  seeded-RNG determinism, caller-supplied performance budgets
  (field names `footprints`, `slots`, `registry` borrowed from the
  method description, noted here as the source of those names).
- A2 look/shots separation, including a sun defined relative to
  the camera facing (field names `look` / `shots` / `sun_relative`
  borrowed from the method description).
- A3 reference-restoration acceptance: side-by-side comparison
  image plus luminance percentiles p02/p10/p50/p90/p98 and colour
  statistics (percentile names borrowed from the method description).
- A4 persistent session: build once, snap many variants.
- B1 minimal procedural Three.js world: analytic heightfield,
  procedural sky, seeded scatter, quality scaling, `__hf`
  settle protocol (the `__hf` protocol name follows hevi's own
  `qa.frame_adapter_contract`, which predates this graft).
- B2 SDF statue: SDF modelling, surface-nets meshing, SDF-gradient
  normals.
- B3 parametric classical orders: fluted entasis shafts, capitals,
  entablature with triglyphs.
- B4 waterfall tracing: steepest-descent trace, arrival-time
  `tau` ribbon, flowing-noise shader in (across, t - tau) space
  (the attribute name `tau` borrowed from the method description).
- B5 vegetation scatter: code-drawn atlas, instanced scatter,
  footprint avoidance, distance LOD.

What was NOT copied:

- No Athenaion code text, in whole or in part; every implementation
  file in this graft was written fresh for hevi.
- No image, texture, mesh, bake, or pixel from Athenaion's
  `refs/` or `media/` directories; all visuals here are generated
  from code (analytic formulas, canvas drawing, SDF fields).
- No self-reported number from the Athenaion author (tree counts,
  waterfall counts, restoration percentages, costs, hours, GPU
  claims) appears in any default parameter, acceptance threshold,
  or outward description. All budgets, targets, and counts in
  this graft are caller-supplied or measured from real runs and
  recorded in the run evidence.
- Athenaion itself was not installed and was not run; the vendored
  Three.js module used by B1-B5 is the copy already present in
  this repository (three r169, MIT, Three.js authors).

Residuals (honest limits of this minimal graft): a single world
with low reuse across subjects; no character performance or story
line (Athenaion itself has none either); SDF statue and waterfall
are minimal versions, not the full Athenaion asset depth.
