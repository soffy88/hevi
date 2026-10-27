# Method attribution: shuohao-skills (method ideas only)

- Source: shuohao-skills by eternityspring (author name as shown in the
  repository), https://github.com/eternityspring/shuohao-skills
- Licence of the source repository: Apache License 2.0.
- What hevi took: method ideas only, reimplemented from scratch in
  hevi's own code, naming, data shapes and test fixtures:
  1. Fix each scene's opening arrangement before storyboarding, generate
     one deterministic opening sentence from it, and require the
     storyboard's first segment of that scene to copy the sentence
     verbatim (hevi: `story.opening_blocking`,
     `qa.storyboard_opening_gate` in `stage_opening.py`).
  2. Check every production stage with deterministic, script-run gates
     instead of asking a model to judge its own output, scoped to the
     gaps hevi's existing gates do not cover (hevi:
     `qa.production_gates` in `production_gates.py`).
  3. Give a character reference set exactly one root anchor; let every
     other view derive from that anchor alone, never from another view;
     mark views stale (never delete them) when a frozen anchor field
     changes; require human confirmation of the anchor before views are
     added (hevi: `qa.character_anchor_gate` in `character_anchor.py`).
- What hevi did NOT take: no source code, no documentation text, no
  sample stories, characters, scenes, prompts, images, model settings
  or configuration from the source repository was copied into hevi.
  No image or video model from the source's workflow is connected:
  character_anchor.py generates no images, and hevi's picture route
  is unchanged.
- Residual limits, stated plainly: recognising objects in a scene
  image is still a human or model-vision step before data reaches
  stage_opening.py (the module validates structure, it does not read
  pictures); production_gates.py judges supplied JSON, it does not
  watch footage or listen to audio; character_anchor.py judges sheet
  structure and hashes, it does not inspect picture content.
