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
