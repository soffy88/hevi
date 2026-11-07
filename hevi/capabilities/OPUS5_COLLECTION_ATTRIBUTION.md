# Opus 5.5 collection attribution (2026-10-28 intake)

Method and data sources for `story.opus_prompt_library`,
`image.lemo_styles`, `video.code_render` and `edit.karaoke_render`.
No upstream code was copied into hevi; the two new data files are
indexes built from the sources below, as noted per source.

- yihui-dev/awesome-opus5-5-videos — MIT.
  https://github.com/yihui-dev/awesome-opus5-5-videos
  Bundled: full prompt text + category + tech tags + author +
  original-post link for 703 entries
  (`opus_prompt_data/yihui_index.json`). Partial prompts are flagged,
  never presented as complete recipes.
- zhuyansen/awesome-opus-5.5-video — NO LICENSE on record
  (API license field empty, no LICENSE file in the repo).
  https://github.com/zhuyansen/awesome-opus-5.5-video
  Bundled: metadata ONLY — id, models, category, bilingual title,
  creator handle, original-post URL, duration, views
  (`opus_prompt_data/zhuyansen_meta.json`). No prompt text, prompt
  link or thumbnail is bundled. Read the creator's own post.
- lemomo-ai/lemo-opuscar — MIT.
  https://github.com/lemomo-ai/lemo-opuscar
  Not vendored: the catalogue is read live from the checkout
  (HEVI_LEMO_HOME, default ~/projects/_refs/lemo-opuscar). Only
  slug, bilingual name, category, generic uses and the one-paragraph
  essence blockquote are surfaced. Demo stories, shots, timings and
  demo assets are not surfaced and must not be reused.
- mexicat/pdoom-video — MIT (method reference only).
  https://github.com/mexicat/pdoom-video
  Method taken: deterministic frame(t) rendering, word-level lyric
  timeline, audio analysis feeding the picture, offline frame ->
  ffmpeg assembly, 4K60 as a true-resolution target tier. No code,
  scenes, lyrics or audio from the repo are used.
- JohnHeibel/PDoomVideo — NO LICENSE on record.
  https://github.com/JohnHeibel/PDoomVideo
  Method对照 only (same song, second implementation): its
  ANIMATION_GUIDE / STORYBOARD structure informed the karaoke
  chain's shape. No code or text from the repo is copied, and
  nothing from it is redistributed.

Residual honesty: the PIL frame path in video.code_render /
edit.karaoke_render is deterministic but is not a browser render;
headless-Chromium capture remains the creator-style-kit styled
render's path, and a full-song 4K60 render is costed by frame
count, not shortcut.
