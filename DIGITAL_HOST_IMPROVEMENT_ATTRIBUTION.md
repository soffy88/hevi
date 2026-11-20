# DIGITAL HOST IMPROVEMENT ATTRIBUTION

Digital-host capability improvement graft, 2026-11-20. Clean-room
restatement only: no branch code, no Renoise code or material,
no weight files, no demo videos, and no key, account, or payment
was handled at any point.

## Method sources

1. **Renoise talkback review** (`~/workspace/hevi-vs-renoise-digital-host.md`,
   2026-11-20): the one-click recorded-talkback chain
   (persona → frames → talkback → edit → polish), the
   single-sentence re-record rule, and the model-selection
   guidance (daily / single-take / quality, 480p sample first).
   Renoise itself is a third-party multi-model platform; its
   promotion copy was verified claim by claim and is not
   repeated here as verified fact. No Renoise account was
   opened and no trial was run.
2. **Xiaoya branch checkout** (`/data/soffy/projects/hevi-live/`,
   hevi `live-parity` branch, HEAD `93f3a718`, read-only
  reference): the two avatar keys, the Wav2Lip ONNX CPU lipsync
   run, the five-category danmaku filter, the three queue
   policies, the 105-topic pool, the wardrobe hot-swap, the
   3-second / 6-per-hour reconnect gate, and the persona
   finetune evaluation record. Only method facts (numbers,
   thresholds, category names) were restated as data; no
   branch code was copied into this graft.

## Measured numbers restated here

- Lipsync run (xiaoya_e sample, 23.25 s): talk render 20.68 fps,
  talk realtime factor 1.034, lipsync correlation 0.278, lag
  -1 frame. The correlation bar in the gate is only "positive
  and recorded" because 0.278 is weak and no stronger bar was
  ever measured.
- Moderation table: 5 blocked categories (51 / 23 / 7 / 13 / 9
  terms), max length 40 characters, dedupe 60 seconds.
- Queue: policies fifo / gift_first_fifo / gift_first_random,
  max age 180 seconds, max size 200.
- Topic pool: 105 topics, no repeat until a full round is spoken.
- Wardrobe: base avatar xiaoya_e, crossfade 8 frames.
- Reconnect: 3-second cooldown, at most 6 restarts per
  3600-second window, then silent.
- Finetune evaluation (25 held-out replies): violation rate 0%
  after the cleaning step, against 52% for the base model;
  raw output carried tool-call markers on every reply.
- Not fixed by this graft: first-audio latency averaged 25.4 s
  against a 2.5 s target, and the Piper female voice measured
  a 0.2649 round-trip CER. Both stay open as separate cases.

## Xiaoya assets and rights

- `xiaoya_d`: AI-generated face, no real-person portrait; the
  cleanest face of the two.
- `xiaoya_e` (runtime default): AI-generated face supplied by
  the owner on 2026-10-13; its source is unconfirmed until the
  owner confirms it, and the gate fails an unconfirmed use.
- Motion clips come from Pexels live-action footage under the
  Pexels License (free commercial use, no attribution
  required) and carry no model release: usable for a demo, a
  grey area as the fixed host's motion source, and the gate
  fails that use without a release.
- The same-named `xiaoya_practice` feature in Mneme is a
  different thing and is excluded by the gate.
- The host is called by its plain name. One name that appears
  in the branch's persona prompt and scripts is refused by the
  gate and is not revived here; it appears in the gate code
  only as a refused literal.

## Weights: missing, stated plainly

The persona finetune weights are not on the server: the model
registry holds no finetuned model and the weights directory
does not exist. Only the evaluation record, the Modelfile, and
the logs survive; the training data lives only in a Drive
file. Rebuilding the weights (owner confirms the Drive data,
then a fresh training run) is a separate case. Until then the
honest stand-in is the base model plus a persona prompt, and
the gate and the schema both refuse any claim that the
stand-in equals the finetune.

## What this graft does not do

- No live streaming, no Vidu session, no RTMP push: the Vidu
  live ring is a separate case, and no key or platform account
  is involved here.
- No voice cloning: the clone route stays barred; only the
  owner's authorized voices are ever used.
- No execution: every B schema is a fake contract with
  `executed_here: false`; the Wav2Lip model files are
  referenced by name only and were never copied into hevi.
- No production sync: production is untouched by this graft.
