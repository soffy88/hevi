# Camera movements — attribution and method note

Method restated from the public camera-movement library at
`aicameramovements.com` (operator not confirmed from on-site text;
no licence statement found on the site, treated as undeclared).
Only the method was learned: the 46-movement catalogue in seven
categories, each movement described in hevi's own wording in the
four-field structure (Movement / Speed / Framing / End), the
one-movement-per-shot rule, and the landing (End) requirement.

No site prompt text was copied: every Movement/Speed/Framing/End
sentence in `hevi/capabilities/cinematic_data/camera_movements.json`
is hevi's own paraphrase of the physical movement. No preview
video or GIF was downloaded or distributed. No third-party
rendering-quality judgement is presented as a conclusion of this
site. No claim is made about the site's About, terms, or licence
pages (none were found in the read-only review).

History: 40 movements were taken in on 2026-10-25
(`shot.camera_movements`); the 2026-11-04 completion added the
remaining 6 (helicopter shot, tilt-shift, infinite zoom, earth zoom
out, time-lapse, pass-through objects), bringing the single-source
catalogue to the full 46. The 124 shotcraft cards are a different
library (Remotion effect cards); shared generic words take their
meaning here from the physical camera definition, never from the
card library.

Standing clarification: `slow_zoom_in` and `slow_zoom_out` are
legal ids in hevi's vocabulary. The slow-zoom ban wording comes
from the H3 benchmark prompt, not from hevi's vocabulary; neither
id may be treated as banned in hevi.

Effects unverified: inclusion in the catalogue records the method
only. Whether a movement renders well on any given video model,
and how movements map to H3 frame grids and duration tiers, was
not established by this review and needs separate GPU verification
(B3/B4, deferred). Site media was not verified shot by shot.

## Deferred batch B (2026-11-04)

- B3 `video.camera_render_mapping` (contract only,
  `executed_here: false`): all 46 movements mapped against
  the minimal code renderer's four fixed tokens. Exactly
  four ids route to a token; the other 42 are explicitly
  `not_supported` with a reason, and compiling one fails
  closed with no silent fallback or direction mirroring.
  The four supported entries record `direction_verified:
  false`: whether the renderer's fixed sweep matches the
  physical direction was not verified. `slow_zoom_in` and
  `slow_zoom_out` remain legal vocabulary ids; they are
  only unrenderable here (zoom family, no focal-length
  control), never banned.
- B4 `qa.camera_duration_advisory` (advisory only): duration
  suggestions drawn solely from hevi's own
  `duration_tiers.json` and frame counts snapped to the H3
  lattice (17k + 5 at 24fps) only where a frame basis is
  verified (`fasth3_local`). Providers without a verified
  tier get no numeric suggestion. The site catalogue
  carries no duration field, so no duration here comes
  from the site. Real rendering effect on any model is
  unverified and needs GPU verification in a separate case.
