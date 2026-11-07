# Attribution — video-shotcraft shot recipe cards

The Markdown files under `cards/` and the data in `shotcraft_index.json`
are imported from:

- **Project:** video-shotcraft by Vincentwei1021
- **Source:** https://github.com/Vincentwei1021/video-shotcraft
- **Upstream commit:** 43bd349a136651865ecfa6ea1cf012f6e957d304 (main, 2026-10-17)
- **License:** Apache License 2.0 (full text in `LICENSE` in this directory)

What was imported: only the shot recipe card data
(`references/shots/<category>/*.md`, 124 cards in 10 categories) and the
upstream `references/shots/ATTRIBUTION.md` (kept here as
`UPSTREAM_ATTRIBUTION.md`, documenting that 38 of the cards are
clean-room re-implementations studied from public product videos).

What was NOT imported: the upstream Remotion demo implementations
(`demos/`), template, workbench, audio assets and gallery. Each card's
index entry retains its upstream `demos/...` reference path as a pointer
into the full checkout at `~/projects/_refs/video-shotcraft`.

Per Apache-2.0 §4: this notice and the license text are retained with
the imported files. The cards were copied verbatim; the index JSON is a
mechanical parse of their frontmatter produced by
`build_shotcraft_index.py` in this directory.
