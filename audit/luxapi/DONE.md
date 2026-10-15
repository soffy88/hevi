# LUXAPI-R1 — implementation and acceptance evidence

## Result

LuxTTS HTTP is now the default for formal narration, conversational dialogue, story-film voiceover, and digital-human one-line dialogue. The story-film and dialogue entrypoints were explicitly connected to the shared audio router; previously their independent defaults bypassed the new LuxTTS router. Live audio was produced through those high-level default code paths and a short toddler-animation video was rendered locally with that narration.

## Implementation files

- `hevi/audio/lux_tts_service.py`: HTTP client for the dedicated LuxTTS service; configurable URL; `/health` readiness; `/tts` JSON payload; long request timeout and bounded retries; Chinese/English sentence splitting; mono 48 kHz WAV validation and joining with 150 ms sentence gaps; per-sentence metadata including resolved voice, duration, generation time and attempt count. Temporary chunks stay in `.tmp/`.
- `hevi/audio/audio_router.py`: formal and conversational provider defaults; shared LuxTTS call path; explicit warning logs and provider identity when LuxTTS fails; CosyVoice then Piper fallback; ffmpeg concat diagnostics and temporary concat list in `.tmp/`.
- `hevi/audio/speech_platform.py`: LuxTTS engine registration and readiness reporting; batch plans remain executable via fallback when LuxTTS health is down, while catalog metadata distinguishes provider availability from fallback-enabled executability.
- `hevi/api/routers/voice_platform.py`: OpenAI-compatible speech requests default to lux_tts; batch execution accepts fallback-enabled LuxTTS jobs even when its health probe is down.
- `hevi/layer4_legacy/voicepro/omodul_impl/openai_audio.py`: OpenAI-compatible speech now routes LuxTTS requests through shared CosyVoice/Piper fallback when health or synthesis fails, and returns actual-provider/substitution metadata.
- `hevi/studio/kit.py`: Studio auto TTS uses the shared LuxTTS → CosyVoice → Piper route; it no longer bypasses configured fallback with Edge TTS.
- `hevi/api/routers/voice_studio.py`: queued voice tasks and compare requests are not rejected solely because LuxTTS health is down; catalog routing metadata declares the automatic fallback chain.
- `hevi/audio/task_adapter.py`: direct LuxTTS task dispatch now uses the shared LuxTTS → CosyVoice → Piper fallback route and persists actual provider/substitution identity into task configuration.
- `hevi/explainer/voiceover.py`: story-film narration defaults to LuxTTS and routes through the shared fallback-capable router; retains explicit legacy provider overrides; creates a WAV manifest and duration-based captions; logs the actual provider/fallback identity.
- `hevi/digital_human/line_tts.py`: dialogue defaults to the shared LuxTTS router rather than bypassing it; retains explicit provider overrides and emits substitution identity when fallback is used.
- `tests/test_lux_tts_service.py`: mocked HTTP contract, retries, sentence splitting/joining, voice validation and optional live integration test.
- `tests/test_audio_router_provider_identity.py`: provider identity and health-failure→CosyVoice/Piper fallback coverage, including explicit warning assertions.
- `tests/test_explainer_voiceover.py`: story-film default-provider, router dispatch, WAV manifest/caption, and digital-human default-provider regressions.
- `tests/test_luxapi_entrypoint_defaults.py`: checks OpenAI speech defaults/fallback, remote-service catalog metadata, Studio fallback routing, batch fallback availability, task-adapter dispatch, Voice Studio validation, and catalog fallback metadata.
- `tests/test_runtime_edge_coverage.py`: updates the Studio auto-route regression to assert the fallback provider identity.
- `tests/test_voice_studio_task.py`: checks that the persisted task result reports the actual fallback provider and reason.

## Configuration

- Default endpoint: `http://100.119.113.90:8795`; override with `HEVI_LUXTTS_URL`.
- `HEVI_LUXTTS_VOICE=auto` is the default. The service selects `soffy` for Chinese and `en_male` for non-Chinese. Supported explicit values are `auto`, `soffy`, and `en_male`.
- Default formal and conversational router provider: `lux_tts`. Story-film voiceover uses `HEVI_EXPLAINER_TTS_PROVIDER` as an explicit override if set; otherwise it follows `HEVI_TTS_FORMAL_PROVIDER`, then defaults to `lux_tts`. Digital-human dialogue follows those explicit settings, then defaults to `lux_tts`.
- To select CosyVoice directly for formal/narration audio, set `HEVI_TTS_FORMAL_PROVIDER=cosyvoice`. To select a different conversational engine, set `HEVI_TTS_CONVERSATIONAL_PROVIDER` to that supported engine. Existing explicit explainer provider overrides remain available.
- If the LuxTTS health check or synthesis fails, the shared LuxTTS route logs the failure and attempts CosyVoice, then Piper. The returned identity envelope names the actual provider and fallback reason.
- The LuxTTS host service was only queried; it was not modified, restarted or redeployed. No paid API was called.

## Live audio proof

Original low-level HTTP-client integration outputs:

- `chinese_story.wav` — four Chinese story sentences; 7.938 seconds, PCM 16-bit, 48 kHz mono.
- `chinese_story.metadata.json` — per-sentence actual voice (`soffy`), durations, generation time, retry counts and timeline offsets.
- `chinese_story.ffprobe.json` — ffprobe media evidence.
- `english_line.wav` — English dialogue sample; 2.3367 seconds, PCM 16-bit, 48 kHz mono.
- `english_line.metadata.json` — per-sentence actual voice (`en_male`), durations and generation times.
- `english_line.ffprobe.json` — ffprobe media evidence.
- `live_synthesis.json` — combined low-level integration summary.

High-level default-router outputs (these were synthesized after removing explicit provider environment overrides so they exercise the actual defaults):

- `router_story_film_cn.wav` — `synthesize_storyboard()` with one four-sentence Chinese story; 7.938 seconds, 48 kHz mono PCM. The returned manifest, caption time ranges and path are recorded in `router_live_path_proof.json`.
- `router_story_film_cn.ffprobe.json` — media probe.
- `router_english_dialogue.wav` — `digital_human.line_tts.synthesize_line()` using its default provider path; “Hello, little bunny!”, 0.864 seconds, 48 kHz mono PCM. The LuxTTS auto voice policy selects `en_male` for this English input.
- `router_english_dialogue.ffprobe.json` — media probe.
- `router_live_path_proof.json` — high-level voiceover manifest and dialogue route evidence.

## Short toddler-animation render

- `kids_story_sample.mp4` — 7.938-second H.264/AAC video, 540×960 portrait, 24 fps, with the live Chinese narration. The visual is a pastel garden with a smiling bunny gently hopping/blinking, a swaying smiling flower, sun-ray movement and watering droplets, aimed at ages 2–6.
- `kids_story_sample.ffprobe.json` — verifies H.264 video, AAC audio, 48 kHz mono and 7.938-second duration.
- `kids_story_sample.render.json` — render provenance and media metadata.

The existing Remotion CLI is absent at `hevi-remotion/node_modules/.bin/remotion` in this worktree. No dependency was installed. To provide an actual video artifact anyway, the sample was rendered with the existing local FFmpeg binary from procedurally generated sprite frames under `.tmp/` and the live narration WAV. There was only one FFmpeg render process.

The files `KIDS_ANIME_DIRECTION.md` and `CAPABILITY_CONTRACT.md` are not present inside this isolated worktree, so they could not be consulted without leaving the authorized workspace. The sample follows the task's explicit 2–6-year-old toddler-animation direction and changes no capability-contract interface.

## Verification

Exact required selection command:

`JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -k lux tests`

Exact summary: `20 passed, 7341 deselected, 1 warning in 3.81s`. The exact required pipe was executed after these final routing/adapter changes and exited 0.

Audio/story/dialogue regression suite:

`JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q tests/test_audio.py tests/test_audio_router_provider_identity.py tests/test_lux_tts_service.py tests/test_explainer_voiceover.py tests/test_director_echo_dialogue.py`

Exact summary: `35 passed in 4.96s`.

## Final additional revalidation

After fixing the final task-adapter, batch-plan, and Voice Studio health-gate bypasses, the expanded focused audio/interface/task regression suite passed:

`JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q tests/test_audio.py tests/test_audio_router_provider_identity.py tests/test_lux_tts_service.py tests/test_explainer_voiceover.py tests/test_cosyvoice_contract.py tests/test_luxapi_entrypoint_defaults.py tests/test_studio_kit.py tests/test_runtime_edge_coverage.py::test_studio_kit_delegates_and_preserves_cross_line_contracts tests/test_voice_studio_task.py`

Earlier checkpoints were 64 and 65 passing tests. Final expanded suite summary after the task-adapter/batch/Voice Studio fallback fixes: `74 passed in 19.26s`.

## Scope and deployment

All implementation changes and audit artifacts are within `/data/soffy/projects/hevi-luxapi`, branch `feat/luxtts-http`. The main `/data/soffy/projects/hevi` checkout was not changed by this task. Nothing was pushed and no Hevi service/container was restarted or redeployed.


## Continuation — canonical Studio render path and renderer fallback

The wider Studio integration run exposed two failures after the voice provider was corrected: the canonical explainer render path still selected Edge TTS unless its task had a provider override, and its rendering step failed outright when the Remotion CLI was absent. Both are now addressed:

- `hevi/studio/fulfill.py`: the canonical explainer line selects the task's explicit `tts_engine` first, then `HEVI_EXPLAINER_TTS_PROVIDER`, then `HEVI_TTS_FORMAL_PROVIDER`, and defaults to `lux_tts`. The actual renderer identity is returned instead of always claiming Remotion.
- `hevi/explainer/render.py`: retains Remotion whenever its project and CLI exist. If the CLI is absent, it uses the local Pillow/FFmpeg CPU fallback and reports the supported `ffmpeg` runtime identifier.
- `hevi/explainer/cpu_fallback.py`: creates gentle pastel bunny-garden cue cards in both 540×960 portrait and 960×540 landscape layouts; muxes the same synthesized cue-level audio at the appropriate timeline offsets after the three-second title card; validates missing/unsafe audio paths; and writes per-render metadata. Frames and intermediates stay under `.tmp/`. It adds no dependency and calls no paid service.
- `tests/test_explainer_render.py`: exercises the real CPU fallback render orchestration and checks both MP4s have the correct dimensions and both audio/video streams.
- `tests/test_luxapi_entrypoint_defaults.py`: verifies that the canonical explainer route defaults to LuxTTS but honors an explicit task provider override.

Verification after this continuation:

- Targeted render/provider/Studio regressions: `25 passed in 21.52s`.
- Expanded audio/explainer/voice-studio integration suite (35 test files/paths): `306 passed, 1 warning in 50.55s`. The one warning is a Starlette deprecation warning about `httpx` with `starlette.testclient`; tests passed.
- Required acceptance pipe: `23 passed, 7341 deselected, 1 warning in 4.97s`; the exact `tail -3 | grep -q passed` gate exited `0`.
- `python -m py_compile` passed for the CPU fallback, explainer renderer and Studio fulfiller. `git diff --check` passed.

The tracked shared Remotion manifest was restored to its committed baseline after tests; test-generated changes to that manifest are not included. Existing untracked `.veya-project/` and `LUXAPI_TASK.md` were left untouched and unstaged.


## Continuation — alignment provider identity and production-path regression fixes

This pass closed the remaining integration gaps found while exercising the broader audio/story pipeline:

- `hevi/audio/tts_alignment.py`: the alignment entrypoint now synthesizes through Hevi's shared LuxTTS-first router by default, so the alignment API and narration use the same service/fallback route. As LuxTTS does not provide native word-boundary times, generated word intervals are explicitly marked as duration-weighted estimates. The recorded `alignment_source` now follows the actual engine (`lux_tts`, `cosyvoice`, or `piper`) rather than incorrectly always claiming LuxTTS. `HEVI_TTS_ALIGNMENT_PROVIDER=edge_tts` remains an explicit opt-in for native Edge boundary data.
- `tests/test_lux_tts_alignment.py` and `tests/p10/spike/test_tts_alignment.py`: coverage for Lux-default alignment, fallback engine identity, explicit Edge boundary identity, estimated-timestamp metadata, ordered word times, and duration bounds.
- `tests/test_runtime_edge_coverage.py`: fixed a mocked subprocess return code and replaced an obsolete strict-Lux failure expectation with assertions proving the documented LuxTTS → CosyVoice → Piper recovery path, including `requested_provider`, `actual_provider`, and `fallback_reason`.
- `hevi/explainer/cpu_fallback.py` and `tests/test_explainer_render.py`: the CPU fallback clones the final card to cover the narration tail, probes the produced video stream, and rejects video/audio duration drift beyond two frames. The output frame rate is explicitly pinned at 24 fps and checked by the render regression test.

Verification:

- Focused routing/alignment regressions: `10 passed in 18.82s`.
- CPU fallback render check after the final frame-rate change: `1 passed in 1.84s`.
- Expanded audio/explainer/voice/Studio suite, excluding the unrelated `tests/test_history_arc_adapter.py`: `353 passed, 1 skipped, 10 warnings in 106.29s`. Warnings are existing `httpx`/Starlette and `datetime.utcnow()` deprecations.
- The wider run including `tests/test_history_arc_adapter.py` reported `357 passed, 2 failed, 1 skipped, 10 warnings in 102.84s`. The two failures are `test_conflict_corner_note` and `test_g1a_report` in that unrelated history-arc module; no history-arc source or test was modified as part of LuxTTS.
- The final required Lux selection gate, rerun after the alignment and frame-rate changes, passed with `27 passed, 7341 deselected, 1 warning in 8.35s`; the exact required pipe exited `0`.
- Python compilation and `git diff --check` passed after the alignment and renderer changes.

The previously committed `audit/luxapi/kids_story_sample.mp4` remains the original live-narration sample; this continuation does not change the external LuxTTS service, install packages, or deploy/restart Hevi.


## Continuation — LuxTTS alignment entrypoint and AV-duration acceptance

A further integration pass surfaced two items worth tightening beyond the initial `-k lux` gate:

- `hevi/audio/tts_alignment.py` now defaults to the same LuxTTS-first HTTP/fallback implementation used by story-film narration, regardless of a separate formal-style provider override. Actual provider identity is kept in the returned `AudioAlignment` and JSON serialization. Since the LuxTTS HTTP contract returns synthesized audio but no native word-boundary timestamps, its duration-weighted token timeline is explicitly marked with `alignment_source=lux_tts_duration_weighted_estimate` and `is_estimated=true`; this is not represented as forced alignment. Native Edge word-boundary timestamps remain available only through the explicit `HEVI_TTS_ALIGNMENT_PROVIDER=edge_tts` setting.
- `tests/test_lux_tts_alignment.py` adds offline tests for the LuxTTS default, recording the actual fallback provider, opt-in native Edge alignment, and ensuring a `HEVI_TTS_FORMAL_PROVIDER` override cannot bypass the LuxTTS-specific router. The TTS-alignment spike assertions now verify the estimate/provenance flag and no longer duplicate the same assertion block.
- `hevi/explainer/cpu_fallback.py` now pads the last visual card rather than allowing image-concat timestamps to end the visual stream before narration. It probes the actual video-stream duration and fails if the visual stream drifts by more than two 24-fps frames from the target. `tests/test_explainer_render.py` checks this on the rendered file with BGM attached, not only on the un-mixed intermediate.

A refreshed toddler story sample using the saved synthesized cue WAVs from the Hevi story-film path is at `audit/luxapi/live_story_pipeline_render_r4/`. Its FFprobe evidence is in `live_story_pipeline_r4_portrait.ffprobe.json`, `live_story_pipeline_r4_landscape.ffprobe.json`, and `live_story_pipeline_r4_proof.json`.

- Portrait MP4: H.264 540×960, AAC 48 kHz, 11.560 s format duration; audio stream 11.541 s.
- Landscape MP4: H.264 960×540, AAC 48 kHz, 11.560 s format duration; audio stream 11.541 s.
- Both tracks are within 19 ms of each other, well under two 24-fps frames, and each sample is under 20 seconds. Rendering and BGM mixing were run serially; no parallel renderer was started.

Verification after these changes:

- Alignment, LuxTTS HTTP, task-entrypoint, and CPU-render targeted suite: `29 passed, 1 skipped in 34.06s`.
- Expanded audio/explainer/voice-studio/storyboard/render regression suite (including `tests/test_runtime_edge_coverage.py`): `353 passed, 1 skipped, 10 warnings in 98.80s`. One skip is the optional live TTS/network test. The warnings are existing Starlette/httpx and `datetime.utcnow()` deprecations; no test failed.
- The live LuxTTS `/health` endpoint timed out on the latest short probe. No service was restarted or redeployed. The previously saved direct HTTP synthesis evidence remains in `chinese_story.wav` / `chinese_story.metadata.json` and `english_line.wav` / `english_line.metadata.json`, both recording `provider=luxtts_http`; the skipped live test correctly does not count a fresh endpoint check as a pass.
- Python compilation and `git diff --check` passed.



Final acceptance rerun after implementation commit:

- Exact required pipe (`python -m pytest -q -k lux tests 2>&1 | tail -3 | grep -q passed` with the mandated venv and environment): exit code `0`.
- Exact pytest summary: `27 passed, 7341 deselected, 1 warning in 7.72s`.
- `audit/luxapi/DONE.md` final line was checked again and remains `DONE LUXAPI-R1`.


DONE LUXAPI-R1
