# Hevi: switch TTS to the LuxTTS HTTP service (task luxapi-r1)

User order (2026-10-15 12:34): "Hevi的接口改成它" — make Hevi's voice/TTS use the LuxTTS service on the laptop.

## Service (already running, do not modify it)
- Base URL: http://100.119.113.90:8795 (laptop WSL, tailnet node desktop-72avcfh-1)
- GET /health -> {"ok":true,"voices":["soffy","en_male"]}
- POST /tts JSON {text, voice: "auto"|"soffy"|"en_male", speed: 1.0, steps: 4} -> audio/wav 48 kHz mono; headers X-Voice, X-Gen-Seconds, X-Audio-Seconds
- POST /v1/audio/speech JSON {input, voice} (OpenAI style) -> audio/wav
- voice "auto": Chinese text -> soffy (user's own cloned voice), otherwise en_male. This is the user's decision: Chinese = her voice, English = en_male.
- One request at a time on a 4 GB GPU (server serialises). First call after a restart can take ~25 s (warm-up); then ~0.5-2 s per sentence. Use timeout >= 90 s and 2 retries.

## Work
1. Worktree already created: /data/soffy/projects/hevi-luxapi on branch feat/luxtts-http. Work only inside it. Never delete anything outside it. If disk is full, stop and report.
2. Hevi already has LuxTTS code (look at hevi/audio/lux_tts_service.py, audio_router.py, speech_platform.py, task_adapter.py, voice_platform router; some of it may only exist in .veya/worktrees/... — find what is on the main branch). Make the LuxTTS backend call the HTTP service above (config: HEVI_LUXTTS_URL default http://100.119.113.90:8795, voice default auto) instead of loading a model locally.
3. Make LuxTTS the default TTS for narration/dialogue in the story-film pipeline (toddler anime story films). Keep CosyVoice/Piper as fallback when /health fails, with a clear log line.
4. Long text: split into sentences (Chinese punctuation aware), synthesize each, concatenate with ~150 ms gaps, resample if the pipeline expects another rate.
5. Tests: unit tests with the HTTP mocked + one live integration test (skip if /health unreachable). Run the existing test suite for the audio module.
6. Live proof: synthesize a short Chinese story paragraph (3-4 sentences) and one English line through Hevi's own code path; save to audit/luxapi/ (wav + ffprobe output + a JSON listing voice per sentence, durations, gen time). If a quick story-film render path exists, render a ≤20 s sample with the new narration into audit/luxapi/ too.
7. Commit on feat/luxtts-http. Do NOT push, do NOT restart/redeploy live Hevi services or containers.
8. Write audit/luxapi/DONE.md: files changed, how to enable/disable, test results (exact pytest summary), sample paths. Final line exactly `DONE LUXAPI-R1`.
