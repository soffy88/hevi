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

Latest exact summary after the local history-fixture commit: `27 passed, 7341 deselected, 1 warning in 11.06s`. The user-specified acceptance pipeline, with output captured in `.tmp/luxapi_acceptance_latest.log`, exited `0`.

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

## Continuation — alignment and CPU-render acceptance

This pass closes remaining integration gaps found while exercising the expanded audio/story pipeline:

- `hevi/audio/tts_alignment.py` uses Hevi's shared LuxTTS-first router by default, keeping alignment and narration on the same HTTP/fallback route. Since LuxTTS does not provide native word-boundary timestamps, token timings are explicitly identified as duration-weighted estimates; `alignment_source` records the actual provider (`lux_tts`, `cosyvoice`, or `piper`). Native Edge boundary data remains an explicit opt-in via `HEVI_TTS_ALIGNMENT_PROVIDER=edge_tts`.
- `tests/test_lux_tts_alignment.py` and `tests/p10/spike/test_tts_alignment.py` cover LuxTTS-default selection, actual fallback provider identity, explicit Edge boundary identity, estimate/provenance flags, ordered word timings, and duration bounds.
- `tests/test_runtime_edge_coverage.py` now models a successful subprocess return code and verifies the intended LuxTTS → CosyVoice → Piper fallback behavior, including provider and fallback-reason metadata.
- `hevi/explainer/cpu_fallback.py` holds the final card through the narration tail, probes the real video-stream duration, rejects A/V drift over two frames, and explicitly outputs 24 fps. `tests/test_explainer_render.py` checks the produced file's actual 24 fps, dimensions, A/V tracks, and duration with BGM enabled.
- `tests/test_history_arc_adapter.py` previously read a contract fixture outside this isolated worktree. Added `hevi/history_series/fixtures/sample.sanjiafenjin.json` as the local deterministic fixture and redirected the test to it; this restores the conflict-corner and report-count assertions without reaching into another checkout.

Verification:

- Focused route/alignment regressions: `10 passed in 18.82s`.
- CPU fallback render test after the final frame-rate change: `1 passed in 1.84s`.
- Expanded audio/explainer/voice/Studio suite before adding the history fixture: `353 passed, 1 skipped, 10 warnings in 106.29s`. Warnings are existing Starlette/httpx and `datetime.utcnow()` deprecations.
- Initial attempt including `tests/test_history_arc_adapter.py` exposed two fixture-dependent failures (`test_conflict_corner_note` and `test_g1a_report`): the declared local fixture path was wrong and the fixture loader depended on an external-worktree file. This has been corrected with the checked-in fixture and worktree-local reader; the focused history adapter suite now passes `6 passed in 0.03s`.
- Final combined expanded audio/explainer/voice/Studio/story suite, including the previously failing history adapter: `359 passed, 1 skipped, 10 warnings in 99.96s`. No failures. The warnings are existing Starlette/httpx and `datetime.utcnow()` deprecations.
- The current live `/health` probe returned HTTP 200 and listed `soffy` and `en_male`; `tests/test_lux_tts_service.py::test_live_luxtts_http_integration_or_skip` passed (`1 passed in 2.33s`). The task-specified core audio/service suite passed (`26 passed in 3.89s`). Saved direct HTTP Chinese/English synthesis and high-level story-film/dialogue proof artifacts remain under `audit/luxapi/`.
- Post-fixture acceptance gate: `27 passed, 7341 deselected, 1 warning in 11.06s`, required pipe exit code `0`. `python -m py_compile tests/test_history_arc_adapter.py` and `git diff --check` passed.
- Python compilation and `git diff --check` passed.

The original committed `audit/luxapi/kids_story_sample.mp4` remains the short live-narration toddler-animation sample. This continuation does not alter the external LuxTTS service, install packages, or deploy/restart Hevi.


## Continuation revalidation — 2026-10-15

Re-ran the required selection gate from the isolated `feat/luxtts-http` worktree:

- `JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -k lux tests 2>&1 | tail -3 | grep -q passed` — exit code `0`; exact pytest summary: `27 passed, 7341 deselected, 1 warning in 15.50s`. The warning is the existing Starlette/httpx deprecation warning.
- Audio/service/story/alignment/history regression group — `45 passed in 5.96s`; includes the optional live LuxTTS integration test, which completed without a skip.
- Provider/catalog/Studio/task/renderer integration group — `47 passed in 2.58s`.
- Required WAV/ffprobe/MP4 evidence files are present and non-empty; `git diff --check` passes.

No implementation changes were necessary during this continuation because the acceptance and focused regressions passed. Existing untracked `.trash/`, `.veya-project/`, and `LUXAPI_TASK.md` were not staged or modified.

## Continuation revalidation — 2026-10-15

Re-ran the required selection gate from the isolated `feat/luxtts-http` worktree:

- `JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -k lux tests 2>&1 | tail -3 | grep -q passed` — exit code `0`; exact pytest summary: `27 passed, 7341 deselected, 1 warning in 15.50s`. The warning is the existing Starlette/httpx deprecation warning.
- Audio/service/story/alignment/history regression group — `45 passed in 5.96s`; includes the optional live LuxTTS integration test, which completed without a skip.
- Provider/catalog/Studio/task/renderer integration group — `47 passed in 2.58s`.
- Required WAV/ffprobe/MP4 evidence files are present and non-empty; `git diff --check` passes.

No implementation changes were necessary during this continuation because the acceptance and focused regressions passed. Existing untracked `.trash/`, `.veya-project/`, and `LUXAPI_TASK.md` were not staged or modified.

## Continuation — complete relevant story/audio regression sweep (2026-10-15)

Ran the combined relevant test set covering audio, LuxTTS, LuxTTS alignment, all `test_explainer*.py` tests, LuxAPI entrypoint defaults, dialogue, Studio, Voice Studio task behavior, and the local history-arc fixture:

`JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q tests/test_audio*.py tests/test_lux*.py tests/test_luxapi*.py tests/test_explainer*.py tests/test_director_echo_dialogue.py tests/test_voice_studio_task.py tests/test_studio_kit.py tests/test_history_arc_adapter.py`

Exact result: `203 passed in 6.96s`, with no failures or skips. This sweep includes the optional live LuxTTS integration test, which completed rather than skipping. The existing live proof remains valid: the four-sentence Chinese sample uses `soffy`, the English sample uses `en_male`, and the toddler animation is 7.938 seconds at 540×960/24 fps with H.264 video and 48 kHz mono AAC audio.

The suite created untracked qualification artifacts at `artifacts/qualification/hevi_p6_8_final.json` and `artifacts/qualification/p6_7/`; these were not staged, modified, or removed. They are outside the LuxAPI deliverable. No product-code changes were required because the relevant suite passed.

## Continuation — latest acceptance and live-service check (2026-10-15)

Re-ran the exact user-required gate with the required environment:

`JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -k lux tests 2>&1 | tail -3 | grep -q passed`

Result: pipeline exit code `0`; exact captured pytest summary: `27 passed, 7341 deselected, 1 warning in 11.07s`. The warning remains the existing Starlette/httpx deprecation warning. The live LuxTTS `/health` check returned HTTP 200 and reported `soffy` and `en_male`. Required Chinese/English WAVs, metadata, ffprobe JSON, and the toddler-animation MP4/probe are all present and non-empty. `git diff --check` passed.

The complete relevant regression sweep remains `203 passed in 6.96s`. No LuxAPI code changes were necessary after these checks. The KIDS_ANIME_DIRECTION.md and CAPABILITY_CONTRACT.md references remain absent from this isolated worktree; no files outside this worktree were read or changed.

## Continuation — provider identity fix, live integration and final acceptance (2026-10-15)

The broad diagnostic found one deterministic contract-test regression in `tests/test_coverage_contracts.py::test_audio_router_selects_styles_and_stitches_single_segment`: its CosyVoice/Voicebox stubs were active while the production default requested LuxTTS. The test now explicitly pins the two requested providers via pytest `monkeypatch`, preserving the production LuxTTS defaults and correctly isolating the style-routing behavior.

Verification after the test fix:

- Targeted audio-router regression: `1 passed in 0.70s`.
- Core audio/LuxTTS/alignment/story-voiceover/dialogue/Studio/history suite: `58 passed in 4.44s`.
- Expanded related audio/LuxTTS/explainer/coverage suite: `238 passed, 34 warnings in 13.63s`.
- Optional live HTTP integration test ran against the service and passed (not skipped): `1 passed in 1.17s`.
- Required gate after implementation commit `bf814bf1`: `27 passed, 7341 deselected, 1 warning in 17.33s`; exact required pipeline exited `0`. The warning is the existing Starlette/httpx deprecation warning.
- Live endpoint `/health`: HTTP 200, voice list `soffy`, `en_male`.
- Chinese and English WAVs, sentence metadata, ffprobe JSON, high-level story-film/dialogue WAV evidence, and the 7.938-second toddler animation/probe all exist and are non-empty. The film is H.264/AAC, 540×960, 24 fps, with 48 kHz mono audio.
- `git diff --check` passes and this report ends with the required marker.

A separate non-gating full-repository diagnostic was not clean: `132 failed, 6669 passed, 77 skipped, 46 xfailed, 122 warnings, 444 errors in 603.51s`, with 461 occurrences of `OSError: [Errno 24] Too many open files` and PostgreSQL pool/database setup errors. Multiple full-suite commands remained running after shell-interface errors, so that run was resource-contended and not a reliable clean baseline. The one reproducible LuxAPI-adjacent test failure was fixed above; the focused task-related suites pass. Unrelated database, video, and creative-runtime subsystems were not changed.

`KIDS_ANIME_DIRECTION.md` and `CAPABILITY_CONTRACT.md` are absent from this authorized worktree. No files outside `/data/soffy/projects/hevi-luxapi` were inspected or changed. Existing untracked `.trash/`, `.veya-project/`, `LUXAPI_TASK.md`, and qualification artifacts remain untouched and unstaged.

## Continuation — repeated task-relevant regression sweep (2026-10-15)

Re-ran the complete relevant suite as one pytest process, including audio, LuxTTS, LuxTTS alignment, LuxAPI entrypoint defaults, all explainer tests, dialogue, Studio, Voice Studio tasks, the history fixture, and the audio-router coverage contract:

`JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q tests/test_audio*.py tests/test_lux*.py tests/test_luxapi*.py tests/test_explainer*.py tests/test_director_echo_dialogue.py tests/test_voice_studio_task.py tests/test_studio_kit.py tests/test_history_arc_adapter.py tests/test_coverage_contracts.py`

Exact result on this continuation: `238 passed, 34 warnings in 21.40s`; exit code 0. Warnings are deprecations (`datetime.utcnow`) in Pydantic validation and unrelated covered schema/checkpoint paths. No tests failed.

Both task direction documents (`KIDS_ANIME_DIRECTION.md`, `CAPABILITY_CONTRACT.md`) were searched for within this worktree and are not present. I did not inspect paths outside the authorized worktree to recover them; the toddler sample continues to be bounded by the task's explicit ages 2–6 requirement and existing report artifacts.

## Continuation — final live and acceptance recheck (2026-10-15)

After the repeated related-suite run, re-ran the dedicated live integration test and the exact acceptance pipeline:

- Live HTTP integration: `1 passed in 2.21s` (service reachable; no skip).
- Required command `/data/soffy/projects/hevi/.venv/bin/python -m pytest -q -k lux tests 2>&1 | tail -3 | grep -q passed`: pipeline exit code `0`; captured pytest summary `27 passed, 7341 deselected, 1 warning in 6.72s`.
- Required final line checked as `DONE LUXAPI-R1`; `git diff --check` passed.
- Endpoint health returned HTTP 200 and voices `soffy` and `en_male`.

No further product-code changes were indicated by this verification. Existing unrelated untracked paths remain untouched and unstaged.

## Continuation — endpoint-configuration fallback hardening (2026-10-15)

A fresh edge-case review found that `lux_tts_available()` could raise instead of returning `False` when `HEVI_LUXTTS_URL` was malformed: its exception handler called `_base_url()` again while trying to log the original validation error. This could disrupt callers that rely on the health probe to choose the configured fallback. The logger now reports the health failure without re-validating the URL; an invalid-URL regression test confirms the probe reliably returns `False`. Also removed a redundant `int()` around `round()` identified by Ruff (`RUF046`) in the same client module.

Verification after these changes:

- Health-probe tests: `2 passed, 4 deselected in 0.05s`.
- Complete task-relevant audio/LuxTTS/entrypoint/explainer/dialogue/Studio/history/coverage regression: `239 passed, 34 warnings in 7.91s`, exit code 0. The live LuxTTS integration test ran in this suite without skipping.
- Ruff check for `hevi/audio/lux_tts_service.py` and `tests/test_lux_tts_service.py`: `All checks passed!`.
- `git diff --check`: passed.

The warnings are existing deprecations in Pydantic validation and covered schema/checkpoint paths. No changes were made outside the LuxAPI client and its tests. The required final acceptance command is executed again after committing this continuation.

## Continuation — fresh task acceptance re-run (2026-10-15)

No new reproducible LuxAPI defect was found in this pass; the edge-case health-probe fix and provider-routing behavior remain green. Revalidation was performed from `/data/soffy/projects/hevi-luxapi` on branch `feat/luxtts-http`, using the required environment `JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp`.

- Exact required acceptance pipeline `pytest -q -k lux tests 2>&1 | tail -3 | grep -q passed`: exit code `0`; pytest summary `28 passed, 7341 deselected, 1 warning in 11.21s`.
- Expanded task-relevant regression suite (audio, LuxTTS/LuxAPI, explainer, dialogue, Studio, history adapter and coverage contracts): `239 passed, 34 warnings in 9.59s`, exit code `0`.
- Live LuxTTS `/health`: HTTP 200; `soffy` and `en_male` advertised, with Chinese `soffy` and other-language `en_male` auto-selection.
- Checked 13 required audio/metadata/ffprobe/animation artifacts: no files missing or empty; key metadata and animation ffprobe JSON parsed successfully.
- `git diff --check`: passed.

The warnings in the expanded suite are existing `datetime.utcnow()` deprecations in covered validation/schema/checkpoint paths; there were no failures. This pass required no product-code changes. `KIDS_ANIME_DIRECTION.md` and `CAPABILITY_CONTRACT.md` remain absent from the authorized worktree and were not read from outside it. Existing unrelated untracked paths remain unstaged and untouched. The main checkout, live service configuration, and deployment state were not modified; no paid API was called.
DONE LUXAPI-R1
