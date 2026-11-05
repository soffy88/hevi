# VibeVoice attribution (method restatement only)

Method restated from the public repository `microsoft/VibeVoice`
(code MIT, Copyright 2025 Microsoft; repository snapshot
`16fb2cb`, reviewed 2026-11-05). Nothing was copied: no
upstream code, no model weights, no embedded speaker files,
no demo audio, no Skill text.

## What was verified (read-only, no weights downloaded, no inference run)

- The repository is real (MIT code license, 55,305 stars at
  review time). The TTS-1.5B model is specified for about
  90 minutes in a single pass with up to 4 speakers in
  English and Chinese, 24kHz output, on a Qwen2.5-1.5B base.
- **The official TTS-1.5B code path is disabled.** Microsoft
  removed the TTS code on 2025-09-05 after widespread misuse;
  the TTS documentation states installation and usage are
  disabled, and the model table lists the path as Disabled.
  The weights remain on the model hub, but running them is a
  third-party reproduction, not an official path. This graft
  never weakens that statement: any claim that official code
  runs fails at `qa.vibevoice_tts_disabled_gate`.
- VibeVoice-Realtime-0.5B is the only still-available TTS
  path: 0.5B, single speaker, streaming text input, first
  audio in about 200-300ms, 8K context of about 10 minutes,
  English first. Its 25 embedded speaker names were verified
  against the upstream `demo/voices/streaming_model/` file
  listing (names only; no audio or weight files were copied
  or listened to). Non-English embedded languages are
  experimental by the upstream documentation's own statement.
- VibeVoice-ASR-7B is specified for a 60-minute single pass
  in 50+ languages with Who/When/What structured output,
  custom hotwords, a streaming variant, and a vLLM plugin.
  The BitNet variant runs on CPU (about 1.58 GB, 3+ threads,
  real-time factor under 1). It is an ASR engine, never a
  TTS solution, and hevi has not implemented this ASR shape;
  it is recorded here as a method note only.

## License, three ways (never merged)

- Code: MIT (Microsoft, 2025).
- Weights: MIT on the model-hub card data; the card's
  top-level license field is None.
- Repository: states no weight license at all.
- The project warns the models are for research purposes
  only and commercial use is not recommended. Any
  commercial-use mention in hevi must carry that warning.

## Voice-prompt authorization (red line)

- VibeVoice-TTS-1.5B fixes the voice from a voice-prompt
  audio clip, which is functionally equivalent to zero-shot
  voice cloning. The upstream repository carries no consent
  or authorization check (a full-text grep for
  consent/authorization returned nothing); it has only a
  deepfake warning and the research-only notice.
- In hevi, a reference-audio voice prompt is therefore a
  clone equivalent: it passes only with a voice authorization
  declaration (the speaker's own voice or a licensed voice,
  with evidence). Any clone request is hard-intercepted.
  Voice cloning runs only for the speaker's own or already
  authorized voices.
- Realtime takes embedded speaker prompts only and accepts
  no user-uploaded reference audio; a custom voice has to go
  through the official team.

## What this graft is

- 6 oskill discipline gates (`qa.vibevoice_tts_disabled_gate`,
  `qa.vibevoice_voice_prompt_authorization_gate`,
  `qa.vibevoice_realtime_speaker_gate`,
  `qa.vibevoice_longform_honesty_gate`,
  `qa.vibevoice_license_note`, `qa.vibevoice_asr_longform_note`).
- 2 obase fake contracts (`video.vibevoice_realtime_speaker_index`,
  `video.vibevoice_longform_tts_contract`), both with
  `executed_here: false`.
- No weights were downloaded and no inference ran here.
  Realtime and 1.5B behavior is unverified in hevi.

## GPU status (recorded, not solved)

- ubuntu26 `nvidia-smi` still reports `Unknown Error / No
  devices were found` (re-checked 2026-11-05); the cold
  start has not been done. No VibeVoice GPU inference is
  feasible locally until the physical layer is fixed; cloud
  GPU is a separate case requiring a budget and landing
  decision.
