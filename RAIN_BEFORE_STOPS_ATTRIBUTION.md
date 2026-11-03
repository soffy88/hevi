# Attribution — 《雨停之前》 graft (A1–A5 + B1 + B2)

Method source: a first-person field account of producing episode 1
of the AI short drama 《雨停之前》 (Claude Code + Opus 5.5 +
Seedance 2.5, about 3,500 yuan of generation spend, 4m24s at
480p), as checked read-only in `hevi-vs-rain-before-stops.md`
(2026-11-02). The account is a single project's experience, not
a price quote: its total includes trial-and-error tuition (one
1080p round took ~73% of the video spend) and excludes
subscription and labour. Nothing from the account's requirement
template was copied verbatim into default prompts.

Seedance 2.5 specifications (draft mode, 7-day task-id validity,
token billing including reference-video seconds, list prices)
come from Volcano Ark's public documentation and price tables,
as recorded in the same report (F1–F5, checked 2026-11-02).
Per-second figures are third-party conversions, flagged derived
and unverified; the 72% discount figure is a time-limited
promotion, never the list price.

Corrections recorded during checking: the review model named in
the account is GPT-6 Astra (not "GPT Astra"); Midjourney V8.2
does not support character/omni reference. Neither correction
is relied on by any gate in this graft.

What this graft does: discipline gates only (story intake,
text/image consistency, review sign-off, feedback kind labels,
per-version cost view), a fake draft-task ledger, and a
list-price registration. No Seedance/Krea/Midjourney/Gemini/Lyria
account, key, subscription, or paid generation was touched. No
author-reported number is a default threshold.

Residuals (not done): B3 two-picture structural alignment check,
B4 confirmed-text overlay pipeline, B5 scene-block generation
arrangement (execution left as a stub pending a separately
approved Seedance route, key and budget).

What was grafted later (2026-11-03, same clean-room terms;
no template text copied, no price used, no Seedance route):

- B3 `qa.two_image_alignment_gate` — before/after picture
  structure alignment: named structure points supplied by the
  caller, judged within a caller-supplied pixel tolerance, plus
  a repeated-structure count that must agree (the field case is
  a window-pane count). Pixel difference over the declared
  frame region is recorded as evidence only and never passes
  or fails the gate. Synthetic fixture pictures only.
- B4 `video.confirmed_text_overlay` — confirmed-text version
  control plus local overlay: only author-confirmed wording
  that appears verbatim in the supplied script text is
  overlaid, in a caller-supplied placement window, with local
  ffmpeg frame work and a pixel-change verification; video
  only, audio is not preserved. Synthetic solid-colour source
  clip only; no real footage, no model call.

Residuals (still not done): B5 scene-block generation
arrangement (execution left as a stub pending a separately
approved Seedance route, key and budget).
