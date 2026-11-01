# Oyasumi-gamedev graft attribution

Method source: articles on oyasumi-gamedev.com (おやすみゲーム開発部,
operator sharp_maker / MIYADAIKU), as restated in the site's own
words in `~/workspace/hevi-vs-oyasumi-gamedev.md` (2026-11-02,
read-only review). All method descriptions in the grafted modules
are clean-room rewrites in hevi's own wording.

## Red lines observed

- Article and image copyright belongs to the site operator.
  Quoting requires the source URL and forbids alteration
  (summarising counts as alteration). No sentence, illustration,
  or code was copied from the site.
- The tools' terms of use forbid extracting a tool's program,
  parts (including "how shapes are made"), data, or articles for
  use in other software, and forbid redistributing the tools
  themselves. The internals, parameters, and shape-generation
  logic of the site's tools were never inspected and are not
  reproduced here.
- No site number is used as a default threshold anywhere in this
  graft: every threshold, range, and vocabulary entry is
  caller-given or calibrated on hevi's own synthetic fixtures,
  and is labelled as such.
- The site's 3DCG解説 category held zero articles at review
  time; nothing is cited from it.
- Tool claims (sway exports, VRMA output) were not run on the
  site and are not used as evidence. Evidence for this graft is
  hevi-side runs only.

## What landed

- A1 `qa.panel_contrast_gate` -- panel importance tiers, contrast
  basis, break-technique cues, gutter pauses as not_checked.
- A2 `qa.camera_baseline_drop_gate` -- baseline establishment,
  one-axis drops, bridge shots.
- A3 `qa.emotion_orientation_vocabulary` -- action direction plus
  gaze/face/chest/waist/feet orientations, declared compound
  intent, silhouette readability basis.
- A4 `qa.effect_restraint_gate` -- one lead effect per panel,
  layer-off check, caller-given thresholds.
- A5 `qa.stage_freeze_gate` -- prototype/vertical_slice/alpha/
  beta/master order, frozen-input discipline, declared re-review.
- B1 `video.single_image_sway` -- caller-zoned still-picture sway
  over a caller-declared waveform vocabulary; deterministic
  NumPy rendering, ffmpeg assembly. Synthetic fixtures only.
- B2 `qa.parametric_pose_template` -- caller-ranged parameters,
  counter-swing / counter-twist checks, hevi pose JSON plus a 2D
  stick-figure silhouette. No VRMA is read or written; no 3D
  model is touched.

## Left for later (residuals)

- B3 dialogue-bubble/subtitle shape gate, B4 prototype-loop
  ledger: planned only, not built in this graft.
- B1 real-picture sway and B2 real-figure validation: evidence
  here is synthetic fixtures only; real pictures and figures
  need caller-supplied material and a fresh evidence run.
