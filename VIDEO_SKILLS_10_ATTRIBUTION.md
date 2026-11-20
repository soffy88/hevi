# Video Skills 10 — Attribution

Graft date: 2026-11-20. Source: the 10-skill "video production
pipeline" post, checked read-only in
`~/workspace/hevi-vs-video-skills-10.md`. Only the 6 true gaps
were grafted (A1–A6 gates, B1–B6 fake contract schemas). No
upstream code, weights, example material, or demo content
appears anywhere in this graft. No runtime was installed, no
model was downloaded, no key or account was used.

## What was grafted, and from what

| Graft item | Upstream repo | License (verified 2026-11-20) |
|---|---|---|
| A1/B1 video-use orchestration increment | browser-use/video-use | MIT |
| A2/B2 multilingual subtitle workflow | alwaysmavs/agent-skills `video-subtitle-translator` | MIT (repo-level) |
| A3/B3 browser demo recording | MengTo/Skills `browser-video-recording` | MIT (repo-level) |
| A4/B4 video asset imagegen | openai/codex `imagegen` sample skill | Apache-2.0 (repo-level) |
| A5/B5 multilingual dubbing pipeline | hevi's own method increment (no upstream) | — |
| A6/B6 App demo film | hevi's own method increment (no upstream) | — |

All grafted sources are MIT or Apache-2.0. The graft is
clean-room method only: gates and contract schemas restate
the method in hevi's own words; nothing was copied from any
upstream file.

## What was NOT grafted, and why

- HyperFrames (`heygen-com/hyperframes`, Apache-2.0): already
  in hevi (`video.hyperframes_styles`, `video.hyperframes_styled_render`,
  G4/G5 `video.hyperframes_composition_schema`). Paid Anthropic
  calls are a separate work item.
- Remotion Skills (`remotion-dev/skills`): already in hevi
  (`qa.remotion_skills_method_gate` + bridge contract/smoke), and
  the skills repo carries **no LICENSE file** — its text is under
  default all-rights-reserved, so it must never be copied.
- ffmpeg-skill: the post's `remotion-dev/s…` link is a
  mislabel/repeat of item 03; `remotion-dev/skills` contains no
  ffmpeg-skill directory. The canonical ffmpeg-skill is
  `kajisho5/ffmpeg-skill` (MIT), already installed outside the
  repo at `~/.claude/skills/ffmpeg-skill` and
  `~/.codex/skills/ffmpeg-skill` (verified in place 2026-11-20).
  Not re-grafted.
- agent-caption (`ahkamboh/agent-caption`): **the GitHub user
  `ahkamboh` does not exist** (API 404); no such repository
  exists. Source, function, and license unverifiable. Not
  grafted. hevi's subtitle capability already covers the
  function (`audio.asr_transcribe`, `audio.forced_align`,
  `qa.whisperx_subtitle_contract`, `edit.word_subtitle_contract`,
  `image.native_subtitle_stitch`).
- video-dubbing / app-demo-agent (`alwaysmavs`): **no such
  repository or directory exists** under alwaysmavs; the
  `agent-skills` tree holds only three skills, neither of them.
  Not grafted as upstream. A5 and A6 are hevi's own method
  increments for the two function gaps, written from hevi's
  pipeline, not from any upstream file.
- The post claim of "directly join the whole video production
  pipeline" is corrected here: 4 of the 10 items carry paid or
  cloud dependencies (Anthropic for HyperFrames, ElevenLabs for
  video-use, OO CLI / Fusion ASR / LLM for the subtitle
  translator, OpenAI gpt-image-2 for imagegen). "Free" covers
  the skill code only, never the call cost. This graft accepts
  none of those routes: ElevenLabs, OO CLI, and the OpenAI paid
  API are all hard-failed by the gates; voiceover and dubbing
  run on authorized voices only (LuxTTS `soffy`, CosyVoice
  authorized voices), and clone / zero-shot modes always fail.

## Execution layer

None of the six runtimes was installed, run, or verified in
this graft. B1–B6 contracts declare `executed_here: false`
and authorize no call. The execution layer (editing runtime,
ASR plus translation runtime, browser automation plus ffmpeg
runtime, free-route image runtime, TTS plus alignment runtime,
screen-recording plus editing runtime) is a separate work
item. Production untouched.
