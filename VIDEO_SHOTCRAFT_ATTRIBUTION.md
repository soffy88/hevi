# VIDEO_SHOTCRAFT_ATTRIBUTION.md

Method-only clean-room graft from Vincentwei1021/video-shotcraft
(Apache-2.0), re-verified 2026-11-04 at HEAD `1266a3ec`.
No card text, demo code, template code, screenshot, audio file, or
palette value table from the upstream repository was copied into
hevi. Card purpose glosses in the index are derived mechanically
from card names only; tuned parameter values, pitfall text, and
demo implementations were intentionally not copied.

## What was restated (own words)

- A1: closed 124-card tuned vocabulary discipline; the hevi-side
  synthesized 152-name catalogue must never be presented as tuned
  cards.
- A2: Jianying export contract discipline (baked plates, native
  editable tracks, endpoint-rounding boundary rule, one-way
  conversion notice, machine-fingerprint do-not-distribute rule).
- A3: nine theme presets as display names only, canonical palette
  precedence order, Ink Press never recoloured, legacy identifiers
  only when explicitly declared.
- A4: preview provenance discipline (release video vs local poster
  vs local render; posters are never motion evidence;
  frame-identical claims stay unverified without verification).
- A5: sound-effect sourcing discipline (public-domain preference,
  attribution entries, key-free selection, unknown provenance
  fails closed).
- A6: Ink Press fixed-grid structure discipline (1920x1080 @ 30fps,
  1085 frames, ten contiguous shots, cue sheet; structure only).
- B1: identity/provenance index of the 124 tuned cards (names,
  categories, style keys, source/demo refs; render verification:
  none).
- B2: Jianying draft export contract, fake layer
  (`executed_here: false`, `draft_file: null`), with the
  Mac/Windows boundary recorded honestly.

## Corrections recorded

- The forwarded "157 cards / 214 styles" numbers are wrong and
  were not used anywhere: verified counts are 124 cards and 150
  style variants. The numbers 157/214 appear nowhere in hevi
  documents or defaults from this graft.
- A prior claim that "124 cards were already imported into hevi"
  was disproved on re-verification: the existing
  `hevi.motion.recipe_card` catalogue is a synthesized 152-name
  catalogue, not the tuned card library. B1 is the true index
  and the two artefacts are kept distinct.

## Third-party layers (not copied, recorded for re-check)

- Freesound material: each item under its recorded licence
  (CC0 / CC BY with an attribution list); no audio bundled.
- Template background music: Mixkit free licence, per-track
  provenance not fully traceable upstream; re-check before
  commercial use.
- Template historical sound effects: several items upstream-marked
  "re-check or replace before publishing"; none bundled here.
- Upstream card ATTRIBUTION states its own method reference was
  fully rewritten with no source material; provenance tables are
  not authorization credentials.

## Boundaries

- No social publishing, no sponsor referral links, no Upload-Post
  key chain: publishing stays a manual step for Soffy himself.
- No Freesound material packaged into the repo.
- No draft carrying a machine fingerprint is distributed.
- Effects unverified: no Remotion render, no per-item Gallery
  preview check, and no Ink Press render was run before this
  graft; those are separate cases (B3/B4 deferred).
- Upstream self-reports (Mac editor verification, frame-identical
  previews) are recorded as self-reported, never as hevi-verified.

## Deferred batch B (2026-11-04)

- B3 `video.remotion_bridge_contract` (contract only,
  `executed_here: false`): a tuned card, theme, composition, and
  grid compiled into a render request. No render happened here.
  A real render was attempted inside the production container
  on 2026-11-04 (MotionGraphics smoke manifest, 540x960 @ 30fps,
  90 frames, output to an ephemeral /tmp probe directory,
  removed afterwards) and failed before any frame with
  `EACCES: permission denied, mkdir
  '/app/hevi-remotion/node_modules/.remotion'` while Remotion
  tried to download Chrome Headless Shell into the root-owned
  project tree as user `hevi`. No MP4 was produced. The block
  is recorded in the contract itself; fixing it needs an
  image/build change (writable browser directory or a
  pre-bundled browser), which is a separate case and was not
  done here. The production container was not modified.
- B4 `video.shotcraft_theme_catalog` (contract only,
  `executed_here: false`): the nine presets as schema plus
  name-derived glosses, recolour locks, and palette field
  names. No palette value table was copied: every entry
  carries `palette_values: null`. Ink Press remains
  non-recolourable; the other presets follow the recorded
  palette precedence order.

## Workbench and capture delta (2026-11-05)

- Motion Workbench and page capture are method restatements
  only, in hevi's own words. No workbench source, capture
  script, demonstration component, card text, music, or sound
  material was copied into hevi, and no referral link or
  publishing key chain was touched.
- Workbench method, as recorded: a finished-film project opens
  in the browser editor only through a single manifest whose
  timeline shares its source with the main composition; three
  editability tiers (time/layer, content/style through
  schema-backed parameters, decomposed imports); rhythm
  constants stay unexposed; edits live in browser local
  storage and are never written back into the film's source
  files; parity comparison of imported and original frames is
  the only frame-identity evidence, and it was not run here,
  so frame-identity stays unverified.
- Capture method, as recorded: screenshots are automatic, but
  the words are not extracted from any page. Copy is written
  from the project brief and from words the user supplies.
  Capture runs locally with invented demonstration data seeded
  first; real customer data never appears in a finished film;
  pages behind a login or a paywall have no capture mechanism
  and fail closed.
- Brand list: the acknowledgements name twelve makers, in the
  order recorded by the gate, and state that the methods were
  restated with no original material, no brand assets, and no
  affiliation or endorsement. One name that appears in
  promotional copy is absent from that list and must not be
  claimed as acknowledged; no per-card provenance to a single
  source film is recorded anywhere.
- Beat sync method, as recorded: beat positions from a beat
  tracker, an equidistant grid fitted by least squares, fit
  residual within fifteen milliseconds, times kept as
  floating-point seconds until the final frame conversion.
  A cut-point error figure from a single finished film is a
  project self-report until re-measured.
- The seven new capabilities are discipline gates and fake
  contracts only (`executed_here: false`). No editor was
  built, no page was captured, no parity run happened, and no
  real-machine browser run happened; those remain separate
  cases.
