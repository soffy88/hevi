# Native subtitle stitch attribution

Capability: `image.native_subtitle_stitch`
Skill: `hevi/skills/native-subtitle-quote/`

Method ideas only were learned from chengyi-ai/native-subtitle-quote-image
(MIT, Copyright 2026 Cheng Yi, v2.10.3). No code, prompt, data table,
formula, or sentence was copied from that repository. The capability
module, the skill text, the layout arithmetic, and the tests in this
graft were written from scratch for hevi.

What was deliberately not taken:

- The source rendering script, layout code, and data tables.
- The source online-video acquisition flow (yt-dlp) and any
  browser-cookie handling.
- The source update check against GitHub releases.
- Any example image, example line, or example brand from the source.

Boundary: local video files only. No downloads, no transcription,
no OCR, no network calls. A rights declaration is required for
every render; the declaration is the caller's responsibility and
is recorded in the manifest, not verified by this capability.
