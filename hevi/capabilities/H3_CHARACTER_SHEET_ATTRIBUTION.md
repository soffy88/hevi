# Attribution: H3 Character Sheet Designer method ideas

Source: ukr8b3g-cmyk/H3-Character-Sheet-Designer (MIT, as stated in
that repository's LICENSE file). The MIT licence in that repository
covers only the author's own original code and documentation.
Pictures, artwork, screenshots, model weights and user-supplied
reference material are expressly outside that licence (see that
repository's NOTICE.md), and no such material is used here.

What was taken, as method ideas only, rewritten from scratch in
`character_sheet.py` (`qa.character_sheet_gate`):

- A fixed thirteen-view catalogue for a character sheet, with an
  anatomical left/right convention and a rule that a full-body view
  never substitutes for a detail view.
- A body-part scope table: eight parts, each applying only to the
  views where the part is visible from the assigned camera angle,
  with a priority rule for the rear-clothing surface and a rule
  that directive wording is literal appearance text, never a
  layout or timing instruction.
- A reference-role policy: eight roles with part/view scopes,
  later-wins conflict handling, explicit directives beating roles,
  and a guidance-only disclaimer.

No upstream code, prompt text, artwork, guide image or workflow
file was copied. The upstream mannequin atlas image was not copied
or recreated. No ComfyUI node, model weight or generation service
is called by this module; it judges JSON plans only.

Not implemented (stated honestly, not claimed elsewhere):

- ComfyUI adapter: frozen. hevi has no ComfyUI line; no prompt /
  width / height output for a reference-to-video node is produced.
- Guide-image generation: no guide sheet image is produced here.
- Generation measurement: nothing here measures whether a
  generated picture keeps a character consistent. A passing gate
  means the plan is structurally sound; whether a sheet is locked
  still needs a human reviewer's eyes.

P1 grafts (2026-10-31, method ideas only, rewritten from scratch in
`character_sheet_contract.py`, `qa.character_sheet_contract`):

- A deterministic compile contract: versioned sheet state with
  strict key checking, an explicit migration record for older
  schema versions (silent upgrade refused), and a byte-deterministic
  canonical serialisation pinned by a golden fixture.
- Layout-guide ON/OFF discipline: OFF is text-only; ON requires a
  guide image declared self-drawn, and the layout record must state
  it is semantic guidance, not a hard constraint. The upstream
  mannequin atlas is forbidden and was not copied, downloaded or
  referenced.
- A style-only-painting rule: a style change may only change how
  the sheet is painted; adding scenery, people or props, or
  changing identity, proportion or costume through the style
  field, fails. Style assembly itself was not rebuilt here.

P2 feasibility check (2026-10-31, read-only, nothing installed,
nothing run, no generation):

- ComfyUI adapter: a ComfyUI checkout exists on the workstation
  (`/data/soffy/fasth3-comfy/ComfyUI`, custom nodes contain only
  the example node and an image-save helper; no H3 or SceneRef
  node is installed) and no ComfyUI process was running at check
  time. The local GPU reported `nvidia-smi: Unknown Error / No
  devices were found`, so local H3 execution is not feasible from
  this workstation as it stands. No node was installed, no service
  was started, no weight was downloaded.
- Self-drawn guide image: hevi has no dedicated silhouette /
  mannequin guide-image producer. `video.code_render` draws
  deterministic PIL frames and could be a basis for one, but no
  such producer exists today, so this remains a gap. The upstream
  atlas was not used in any form.

Both P2 items remain frozen pending a separate decision and the
workstation steps that decision would name (a working GPU/ComfyUI
route, and a self-drawn guide producer). Nothing here claims a
generated sheet was produced or measured.
