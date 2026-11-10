# article2media Attribution

Method restatement only. No SKILL prose, template, engine script, theme CSS,
sample article, demo image or bundled font from the repository was copied into
hevi. The six capabilities below are new hevi code written from the published
method; rendering and export still go through hevi's own studio, ffmpeg and
Pillow paths.

## Source reviewed

- Public repository `threerocks/article2media` (MIT).
- Local clone: `/data/soffy/projects/article2media`.
- License: MIT, copyright LeiLiu, 2026. Full text kept at
  `third_party/article2media/LICENSE`.
- The skills were already installed for the local worker under
  `~/.config/opencode/skills` (article-fetch, video-transcript, article-rewrite,
  article-translate, long-image, image-cards, wechat-layout, explainer-video,
  logic-whiteboard, article-comic and the `article2media` router).
- They were read as reference only; hevi does not shell out to them at runtime.

## What was absorbed (method only)

| # | Method | Where it lives in hevi |
|---|---|---|
| 1 | Delivery review hard limits for talking-head / explainer films: first sentence ≤5s and ≤19 chars, first visual ≤2.5s, static ≤5s, ~4.5 chars/s with >5.2 flagged (regenerate, else pitch-preserving slowdown ≤15%), single-line subtitles with ≤13-char phrase merge, hard cuts, no removal within a 1.4s pause, dwell ≥0.55s, zero <0.6s blink gaps, frame-sampled dropout, safe area, -14 LUFS; `review.json` plus an overview image | `hevi/studio/repurpose_s24.py` `review_delivery` / `render_review_overview`; API `POST /studio/s24/review`; ops `s24_review`; also folded into `POST /studio/craft/review` for `target=film` |
| 2 | Word-level sync shots: whisper word timestamps drive numbers, lists, comparisons and killer lines; no text in generated images, all type overlaid with HTML/CSS | `align_words` / `map_words_to_transcript` / `word_sync_plan`; API `POST /studio/s24/word-sync`; ops `s24_word_sync` |
| 3 | One draft, many outputs: Xiaohongshu 3:4 card group + post caption, WeChat inline-style HTML with base64 images and one-click copy, long image; CSS-variable theme shared with the video subtitle style; offered as an option on the finished-film page, not a new production format | `theme_css` / `export_text_pack`; API `POST /studio/s24/export-pack`, `GET /studio/s24/themes`; create page “同时导出图文” |
| 4 | Article input: web / WeChat / Markdown → `article.md`; original-text path locks each block with SHA-256 and reads the rendered blocks back; video links become transcripts only for the user's own or declared-authorised content, credited to the original author, no bulk scraping, no browser cookies | `ingest_article` / `lock_article_blocks` / `verify_article_render` / `guard_video_transcript`; API `POST /studio/s24/article` |
| 5 | Translation check folded into `localization_dub`: block count, omissions, number loss | `check_localization`; called by `_localization_dub` and written to `localization_check.json`; API `POST /studio/s24/localize-check` |
| 6 | Compliance: voice tiers (bundled design voices usable; cloned voices only with the user's own authorisation and a pre-export confirmation), AIGC label on the first frame and in MP4 metadata, fonts limited to OFL or explicitly commercial licences with a per-font list | `check_voice_tier` / `stamp_aigc` / `font_licenses`; API `POST /studio/s24/compliance`, `GET /studio/s24/fonts` |

## What was NOT taken

- No SKILL.md prose, question flow, reference document, theme file, layout
  script, caption template, prompt or demo article was copied.
- No sample content, screenshots, demo videos, 21 built-in themes or bundled
  fonts from the repository are included. Fonts are resolved from hevi's own
  OFL/commercial sources and listed per licence.
- No new runtime dependency, model download or paid service was added.
  `VoxCPM2` / `mlx` are Apple-Silicon only and are not used; dubbing continues
  on hevi's existing TTS with the S22 licence-audit conclusion.
- No browser cookies are read; no bulk scraping; no external messages.

## Third-party components referenced by the method

Named only so the lineage is auditable; none is bundled or invoked by this
graft:

- faster-whisper — local ASR for measured word timestamps (already a hevi
  dependency; the model is mounted at `/models/faster-whisper-large-v3-turbo`).
- FFmpeg, Pillow, Playwright/Chromium — already local dependencies.
- Noto Sans/Serif CJK, Fusion Pixel, Be Vietnam Pro, Charm, Patrick Hand —
  OFL-1.1 fonts already present in hevi or the local image.
