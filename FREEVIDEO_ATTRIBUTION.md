# FreeVideo Attribution

Source: FlashML-org/FreeVideo (https://github.com/FlashML-org/FreeVideo),
checked read-only 2026-11-20. Report: `~/workspace/hevi-vs-freevideo.md`.
Local read-only copy: `~/workspace/_freevideo/` (tarball, not installed).

## What was taken

Method only, clean-room restated in hevi's own words. No upstream
code, weights, example material, or demo video appears in hevi.

- A1 adaptive execution planner: per-request budget re-measurement,
  resident-block formula (432.5 MB per block, 8..44 resident, pinned
  host capped at 22 GiB), disk streaming trigger, prefetch slots by
  VRAM (two at 14 GiB or more), OOM retry ladder (lighten placement,
  then shrink chunks, then host-stage attention outputs, at most two
  retries), plan printed dry before weights load.
- A2 low-VRAM honesty: 8 GiB VRAM / 16 GiB host RAM minimums, no
  zero-cost claims, Max on a 10 GiB card needs an honest time
  estimate (community: 15 s Max took about 33 minutes on a 3080
  10 GB), slow disk (under 110 MB/s) must be acknowledged as the
  bottleneck.
- A3 VDN-H3 distinction: the model is an 8-step distilled (DMD)
  derivative of MiniMax H3, revision pinned to `751739ee`; never
  presented as the original H3; FastH3 conclusions do not transfer.
- A4 MiniMax H3 Community License compliance: barred regions (EU,
  GB, KR, US), commercial products over 20M USD annual revenue need
  MiniMax's prior written authorization, commercial UI must display
  "MiniMax H3" and attach the license copy, H3 output must never
  improve another AI model, no non-consensual impersonation, no harm
  to minors, public releases must disclose machine generation.
- A5 prompt + drama execution (increment only over Eian A4
  `qa.seven_section_prompt_gate` and dance A10
  `qa.dance_h3_prompt_gate`): H3 six sections in order, shots
  15–20 s (at most 15 s with a cast card or references, never 3–6 s,
  never above the device limit), in-shot cuts 2–4 s, cast wardrobe
  fixed for the whole film, five pre-generation faults checked,
  speakers numbered by first spoken line, dialogue word for word,
  plan-before-run.
- A6 preview-first + two-pass: half-resolution first pass, second
  pass reuses it, two seeds of the first shot reviewed at full size,
  only liked takes completed.
- A7 LoRA honesty: source and license recorded per LoRA; adult
  LoRAs record a subject age of 24 or above.
- A8 voice reference authorization: CosyVoice3 timbre reference is
  a zero-second-clone equivalent; only the speaker's own voice or an
  authorized voice with proof may speak; upstream carries no consent
  check, hevi supplies it.
- A9 workflow bundle: prompt, seed, and settings travel with the
  video; a ComfyUI-restorable workflow file is present; source
  traceable.
- A10 post-chain license split: RIFE / Real-ESRGAN / ACE-Step run
  commercially; Bandit stems stay non-commercial; Qwen image stays
  research-only; ComfyUI GPL code is learned from, never moved.

## Licenses, split

- FreeVideo code: Apache-2.0. Its `THIRD_PARTY_NOTICES.md` is
  unusually complete and was the cleanest part of the repo.
- H3 weights: MiniMax H3 Community License, NOT open source.
  Territory excludes the EU, UK, South Korea, and the US (China is
  inside the permitted territory). Commercial products over 20M USD
  annual revenue need prior written authorization (api@minimax.io).
  Commercial UI must display "MiniMax H3" prominently. H3 output
  must never improve another AI model. Jurisdiction: Hong Kong.
- H3 acceptable use policy (Exhibit A, 20 rules): no
  non-consensual impersonation (rule 13), public machine-generated
  releases must clearly disclose AI generation (rule 12), no harm
  to minors, no military use, no disinformation.
- Mixed licenses kept apart: ComfyUI parts are GPL-3.0 (method
  only, code never moved into hevi); Qwen-Image-2.1 is a Qwen
  RESEARCH LICENSE (research only); Bandit Plus stems weights are
  CC BY-NC 4.0 (non-commercial); CosyVoice3 dubbing is Apache-2.0;
  RIFE / Real-ESRGAN / ACE-Step / Depth Anything V2 / sherpa-onnx
  each carry their own terms, recorded per step by the A10 gate.

## What was NOT adopted

- "VDN-H3 is MiniMax H3": disproved. VDN-H3 is OpenVDN's 8-step
  distilled derivative; picture quality and character consistency
  differ from the original H3 and must be re-verified.
- "Free" as zero cost: not adopted. Disk, power, and time are real
  costs; the agent runs on the user's own paid Claude Code/Codex
  account.
- The launcher (whole-site installer), ComfyUI GPL code, weights
  (about 99 GB manifest), example material, and demo videos: none moved.
- Author self-reported numbers are not adopted as verified where
  the check report flagged them (capacity grid measured on H200
  with synthetic limits, not on a real 8 GB card).

## Execution layer (separate work item)

Python >=3.12,<3.13 is required; hevi's `.venv` is Python 3.14.4,
so the runtime cannot be installed into the existing environment.
Model download (about 99 GB manifest, VDN-H3 revision `751739ee`),
the ubuntu26 GPU cold boot (FreeVideo does not fix hardware),
and a real-machine smoke run (one Light segment after the 3080
is repaired, then Max) are all separate items requiring Soffy's
separate approval. Nothing here executes anything.
