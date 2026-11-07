# Toonflow recheck graft — attribution

Method ideas restated in our own words from HBAI-Ltd/Toonflow-app
(MIT, verified against the repository LICENSE file, Copyright (c)
2026 HBAI-Ltd; the MIT licence covers that repository's own code
and documentation only, not model services, generated material,
or third-party plugins). No Toonflow code, documentation text,
workflow, skill text, demo material, or generated result is
copied here. The recheck report is
`~/workspace/hevi-vs-toonflow-recheck.md` (2026-11-02, read-only:
20146 stars / 3623 forks, last push 2026-10-31, release v2.0.9).

What was taken, as discipline only:

- A1 `qa.reference_map_contract`: the "missing mapping throws"
  discipline behind the metaso provider's `{{ref N}}` handling by
  referenceOrder, restated as a plan-side gate. Toonflow's
  execution mapping itself was not copied.
- A2 `qa.sandbox_material_reference_gate`: the "references are
  real links, material is not moved" discipline behind sandboxed
  node material references.
- A3 `qa.task_recovery_gate` and B2 `qa.task_recovery_contract`:
  the "recovery needs a checkpoint, finished segments are not
  re-run" discipline behind media-task recovery. The fake
  backend here runs nothing real.
- B1 `video.reference_map_adapter`: a fake execution adapter
  for the same binding contract. No provider call, no key.

What was deliberately not taken:

- Toonflow code or documentation text, desktop/mobile/server
  code, official account chains (register/login/captcha/SMS),
  the tfRouter official route (no independent adapter file in
  the providers code at recheck time; documentation mentions
  only), sponsor pricing as thresholds (the README sponsor
  figures are unverified publicity figures; no price constant
  lives in this graft), demo material, the browser
  SpeechRecognition `asr` package (not server ASR), or the
  generic ffmpeg wrapper as a dedicated composition module.

Open residuals: real execution of B1/B2 waits on a channel, a
key, a GPU, and a budget decision, all Soffy's call. The
product itself is not deployed.
