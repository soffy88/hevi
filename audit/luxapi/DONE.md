# LUXAPI-R1 — completion evidence

## Implementation

- `hevi/audio/lux_tts_service.py`: LuxTTS HTTP client; configurable base URL; `/health` readiness; `/tts` JSON contract; bounded retries and long request timeout; Chinese/English sentence splitting; WAV validation/join at 48 kHz mono PCM with 150 ms gaps; per-sentence voice, duration and generation-time metadata. Temporary sentence WAVs are stored under this worktree's `.tmp/`.
- `hevi/audio/audio_router.py`: formal TTS defaults to `lux_tts`; calls the HTTP backend; if it is unavailable or fails, logs the failure and attempts CosyVoice, then Piper. Fallback identity and reason are returned to callers. Audio concat lists are stored in `.tmp/` and ffmpeg failures are surfaced.
- `hevi/audio/speech_platform.py`: registers/reports the LuxTTS engine via the HTTP service availability probe.
- `tests/test_lux_tts_service.py`: mocked HTTP contract, retry, sentence split/join, voice validation, and optional live integration coverage.
- `tests/test_audio_router_provider_identity.py`: routing/provider identity regression coverage.

## Configuration

- Default service URL: `http://100.119.113.90:8795`.
- Override URL with `HEVI_LUXTTS_URL`.
- Voice selection defaults to `HEVI_LUXTTS_VOICE=auto`: Chinese uses `soffy`; non-Chinese uses `en_male`. Explicit supported values are `auto`, `soffy`, and `en_male`.
- LuxTTS is the default formal/narration provider. Set `HEVI_TTS_FORMAL_PROVIDER=cosyvoice` to disable LuxTTS as the selected primary backend. Other existing formal provider selections remain available. When LuxTTS fails, CosyVoice and then Piper are attempted automatically; warnings identify fallback decisions.
- The LuxTTS host service was not modified, restarted, or redeployed. No paid API was called.

## Live synthesis artifacts

- `chinese_story.wav`: 4 Chinese toddler-story sentences through Hevi's LuxTTS HTTP client; actual voice `soffy`; 48 kHz mono PCM; 7.938 seconds.
- `chinese_story.metadata.json`: sentence text, selected voice, durations, generation times, retry counts, and timeline offsets.
- `chinese_story.ffprobe.json`: ffprobe media inspection output.
- `english_line.wav`: 2 English toddler-dialogue sentences through Hevi's LuxTTS HTTP client; actual voice `en_male`; 48 kHz mono PCM; 2.3367 seconds.
- `english_line.metadata.json`: sentence-level synthesis metadata.
- `english_line.ffprobe.json`: ffprobe media inspection output.
- `live_synthesis.json`: combined summary of both live examples.

The audio samples are actual live-service outputs saved during this task. The optional integration test is allowed to skip when the endpoint cannot be reached from the test process; the live WAV and metadata files above are retained as separate integration evidence.

## Verification

Command: `JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -k lux tests`

Exact summary: `6 passed, 1 skipped, 7341 deselected, 2 warnings in 31.22s`.

Audio module suite command: `JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-luxapi/.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q tests/test_audio.py tests/test_audio_router_provider_identity.py tests/test_lux_tts_service.py`

Exact summary: `25 passed in 9.85s`.

## Scope and deployment

All edits and generated evidence are inside `/data/soffy/projects/hevi-luxapi` on branch `feat/luxtts-http`. The main `/data/soffy/projects/hevi` checkout was not edited by this task; no push or live Hevi restart/redeploy was performed.

DONE LUXAPI-R1
