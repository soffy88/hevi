# cyber-xiaoya-live attribution (method restatement only)

Source reviewed read-only on 2026-11-05: `cyber-xiaoya/cyber-xiaoya-live`,
HEAD `c0effaf` (2026-11-02), org account, author 天工开帧, created
2026-10-24, 670 star / 303 fork at review time. Full read-only
review: `~/workspace/hevi-vs-cyber-xiaoya-live.md`.

## What was taken

Methods only, restated in hevi's own words; no upstream code, text,
audio, image, persona, song or action-library content was copied:

- Vidu live component session: cloud vidu-s2 `s_avatar/component`
  session, avatar by `avatar_id` or `image_uri`, actions from an
  action library, RTC channel in managed or customer mode.
- Danmaku routing: priority queue, batching (at most 14 per batch),
  command confirm/dismiss, drop-word list, speaker-side banned-word
  list, reply interval, at most 2 replies per round.
- Gift batching and VIP: 6-second window, 4 people / 50 diamonds
  trigger, at most 12 items per batch, at most 2 batches per minute,
  VIP threshold (default 99 diamonds) with face display and 30-second
  cooldown, once-per-session member welcome that never interrupts a
  song.
- Action priority: VIP above manual above fixed choreography above
  danmaku, same-level FIFO, choreography group and gap intervals.
- OmniVoice live wiring: Gradio service on port 9877 with GPU,
  hot-voice warmup, cache garbage collection, video-memory watchdog,
  24kHz output. Weights (about 10GB) live outside the repository.
- Koubo segmentation: long text split without breaking URLs, email
  addresses, version numbers, times, decimals, percentages or
  English words; sentences stay whole; segments synthesized
  separately and fed sequentially; audio kept separate from the
  song list.
- Stage console: five zones (quick commands, song queue, reference
  images, recording, statistics panel); reference images change the
  picture only, never the digital human identity.

## License and rights

- Upstream code is AGPL-3.0. hevi took method restatements only and
  copied no code, so no copyleft material entered the repository.
  Any future whole-segment port must first pass an AGPL compliance
  review.
- NOTICE: four categories sit outside the AGPL and belong to the
  author — character image material, cloned-voice reference audio
  and voice models, persona prompts / copy / song lists / action
  libraries, and the name 「赛博小雅」 plus Logo. None of them may
  be used commercially or redistributed without written permission,
  and none of them entered this graft.
- "Free and open source" covers the code only. Running is not free:
  Vidu bills per second (1 credit/second and a 45-credit minimum
  balance to open a session are README self-reports, unverified),
  LLM calls bill per use, and every image, voice, persona, song
  library, weight and key must be supplied by the operator.
- The upstream repository carries no consent or authorization check
  for voice cloning (full-text grep for consent/authorization: 0
  hits). hevi's existing clone hard intercept governs: clone
  requests fail unless an own-or-licensed voice authorization
  declaration is present. No clone route was connected here.
- The upstream repository contains no code that pushes a stream to
  Douyin or Bilibili: the rendered picture enters a Vidu RTC
  channel, and reaching a platform needs OBS or equivalent. No
  push-to-platform claim is made here; OBS wiring is a separate
  case. The demo screenshots and 6-second demo in the upstream
  README were not played or watched and are recorded as unverified.
- Vidu and LLM services are third-party paid services; keys are a
  Soffy-side step and never enter the repository. The companion
  danmaku repository (`cyber-xiaoya-danmaku`) was verified to exist
  only; its collection implementation was not reviewed, and no
  third-party collector was connected.

## What is fake here

- A1–A6 are discipline gates only; B1–B4 are fake contract layers
  (`executed_here: false`). No live session was started, no
  collector was connected, no payment was touched, no page was
  built, no weights were downloaded, no GPU inference ran.
- The Vidu live session and the OmniVoice live wiring are
  untested on a real machine; weight download, GPU inference,
  platform accounts and keys are separate cases.
