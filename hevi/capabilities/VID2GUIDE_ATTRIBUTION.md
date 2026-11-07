# Video step segmentation attribution

Capability: `video.step_segmentation`
Skill: `hevi/skills/video-step-segment/`

Method ideas only were learned from jiangsai1979/vid2guide
(MIT, Copyright 2026, repository created 2026-02-24). No code,
prompt, data table, formula, or sentence was copied from that
repository. The capability module, the skill text, the grouping and
confidence arithmetic, and the tests in this graft were written from
scratch for hevi.

What was deliberately not taken:

- The source video acquisition flow (yt-dlp download of online
  videos) and any browser-cookie handling.
- The source model calls (Volcengine ARK / Doubao, including the
  model name) for step identification and frame-based refinement.
- The source transcription invocation (Whisper command line, including
  its hard-coded language setting).
- The source document generation (Markdown and PDF output via
  weasyprint).
- The source setup shape (conda environment, `.env` key file, and
  project-layout preconditions).
- Any example title, example description, example video, or example
  brand from the source.

Boundary: local video files only, with a caller-supplied transcript.
No downloads, no transcription, no model calls, no network calls. A
rights declaration is required for every run; the declaration is the
caller's responsibility and is recorded in the manifest, not verified
by this capability. Frames extracted under the visual-check budget are
human verification requests only: no frame is judged and no step text
is rewritten here.
