# REALRENDER3 task (real TTS samples)
Laptop TTS now responds: POST http://100.119.113.90:8795/tts JSON {"text":..., "voice":"auto"} -> audio/wav (may be slow on first call; use timeout >=300s, synthesize sentence by sentence, retry 3x). Client: hevi/audio/remote_tts.py. faster-whisper venv: /data/soffy/tmp/venv-whisper.
1. Render 2 real samples into output_real_render3/ (~45-60s each, Chinese script):
   a) talking-head cut sample (talkedit pipeline, 9:16)
   b) voiceover motion explainer (huashu motion + shotlang, 16:9)
   Audio MUST be the laptop TTS voice, not a test tone.
2. Transcribe each final mp4 audio back with faster-whisper (zh, word timestamps); compute character error rate vs script; save transcripts.
3. Run SHOTLANG QA on both.
4. Verify with ffprobe (duration, audio stream) and report.
5. Write REALRENDER3_DONE.md: exact paths, durations, CER, QA result, honest limits. End with "REALRENDER3 DONE" or "REALRENDER3 BLOCKED". Never claim anything not actually run.
