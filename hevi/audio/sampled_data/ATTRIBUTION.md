# Attribution — sampled-instrument library for `audio.score_render`

The real-instrument samples in `samples/` and the sample-engine design
used by `hevi/audio/sampled.py` come from two open sources:

## mg-styles-15 (code + curation) — MIT License

- Upstream repository: https://github.com/Vincentwei1021/mg-styles-15
- Author: Vincentwei1021
- License: MIT License (full text in `LICENSE` in this directory)
- Vendored from: `lib/audio/` at upstream `main` (fetched 2026-10-21)

What was taken:

- `samples/` — the bundled sample subset under `lib/audio/samples/`
  (102 `.flac` files, 48 kHz stereo, ~56 MB).
- `samples_index.json` here is **generated** by `build_sample_index.py`
  from upstream `lib/audio/samples/index.json`, filtered to the files
  actually vendored, plus a per-instrument normalisation gain computed
  with upstream's rule.
- `upstream/mgaudio_samples.py` — a verbatim copy of upstream
  `lib/audio/mgaudio/samples.py` (the sample engine), kept for
  provenance. hevi does **not** import it at runtime: its round-robin
  sample picking is stateful and its `_dsp` helpers need numba.
  `hevi/audio/sampled.py` is a deterministic adaptation of the same
  design (nearest pitch + nearest velocity layer picking, detected-midi
  pitch correction, spaced-pair channel alignment, velocity-relative
  gain), reimplemented with numpy + soundfile only. See that module's
  docstring for the exact deviations.

## VCSL (audio content) — CC0

- The samples themselves are from **VCSL** (Versilian Studios Community
  Sample Library), released under **CC0** (public domain dedication),
  as curated/bundled by mg-styles-15. Per upstream
  `lib/audio/tools/download_vcsl.sh` / `select_vcsl.py`, VCSL is the
  origin of every file under `samples/`.
- CC0 requires no attribution, but the source is credited here anyway:
  Versilian Studios / VCSL contributors.

Instruments vendored (pitched): piano, marimba, vibraphone, harp,
glock (glockenspiel), kalimba, wineglass.
One-shot percussion: crash, suscymbal, timpani, woodblock, slapstick,
cabasa, guiro, vibraslap.

Rebuild the filtered index from a fresh upstream checkout with:

```
HEVI_MG_AUDIO_HOME=~/projects/_refs/mg-styles-15/lib/audio \
    python3 build_sample_index.py
```
