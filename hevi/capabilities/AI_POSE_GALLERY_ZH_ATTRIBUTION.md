# ai-pose-gallery-zh graft attribution

Clean-room method graft of the costume / portrait / depth /
recipe / workbench layers of anhao/ai-pose-gallery-zh
(2026-11-20 check, report `~/workspace/hevi-vs-ai-pose-gallery-zh.md`).
No upstream code, image, JSON data, or demo material is copied
into hevi. The earlier pose-only index (`image.pose_library`,
commit 3b5c1d76) is covered separately by
`POSE_GALLERY_ATTRIBUTION.md`; this file covers the A1–A9 gates
and B1–B6 fake schemas added in this graft.

## Source

- Repository: anhao/ai-pose-gallery-zh — Chinese edition of an
  AI pose reference gallery; original gallery by ギア
  (@giaaibusi), https://ai-pose-gallery.pages.dev/ .
  Created 2026-10-27, 7418 stars / 1904 forks at check time.
- What it is: three libraries in one (pose 1439 records /
  288 groups, costume 3224 sets, portrait 1499) + a
  three-in-one character synthesis workbench + a ComfyUI
  plugin (4 nodes) + 9 agent skills. Not a generative 3D
  tool, not a renderer, no weights.

## License and rights (as checked 2026-11-20)

- Code is MIT, but the LICENSE states MIT covers source code
  only (index.html, scripts/, _headers). Images under `img/`
  and `thumbs/` and original data under `data/` belong to the
  original author: non-commercial reference use only, remove
  on the author's objection, never repackage or resell.
- Portrait tension, unresolved and never written as resolved:
  the README calls the portrait library CC0 1.0 in one place,
  while the LICENSE scope note says all of `img/` belongs to
  the original author and is not for commercial use. Every
  portrait use in hevi is treated as non-commercial and must
  acknowledge the tension (`cc0_tension_acknowledged`).
- CharaDB anime costume: tags CC0, images reference only,
  no redistribution, never for real people or minors.
- Shisei dynastic costume: carries its own LICENSE-images and
  NOTICE files; their contents were never read in full, so the
  gate requires the record to note them
  (`shisei_license_noted`), not to claim their terms.
- 18+ inventory: pose sexy system 399 records, two-person
  system 275 records; costume sexy/underwear 339 sets. SFW
  mode is on by default; the safety gate is a real gate, not
  the advisory hint `image.pose_library` attaches.
- No voice, TTS, or cloning anywhere in the source; nothing
  here touches the hevi clone red line. Pose pictures are
  plain white mannequin models with no real-person likeness;
  portraits are reference pictures, never face-swap material.

## Verified numbers baked into the gates

- Costume: 3224 sets = giaa realistic 1407 (春 215, 夏 254,
  秋 244, 冬 253, 内衣睡衣 199, 性感 140, 泳装 54,
  礼服 48) + Shisei 57 sets / 227 views + anime 1320
  (hotlinked, not shipped) + CharaDB 440.
- Portrait: 1499 total = 正脸 893 + 造型氛围 606; four hair
  lengths (短发 727, 中发 376, 中长发 260, 长发 136, of the
  whole set); 51 hairstyle subdivisions exist upstream but
  their names were never verified, so no hairstyle name is
  closed here.
- Depth: 1439 webp files under `img/depth/`, one per
  pose-by-view record, named `<record_id>.webp` (verified
  against the upstream tree listing on 2026-11-20; e.g.
  `full_sexy_P001_front.webp`). The bundled
  `pose_index.json` now carries a `depth` field on every
  view entry derived from that convention, and the gate
  always checks the file on disk before a depth switch.
- Style presets: the README claims 12 presets, but the
  preset table and prompt-assembly code were never checked
  item by item, so no preset name is treated as verified
  upstream. Presets must declare `hevi-local` or
  `upstream-unverified` provenance.
- Model protocols: Gemini, GPT Image, Qwen, Doubao, local
  ComfyUI — verified from `aiGenerator.ts`. Drift noted:
  code already lists gpt-image-2.6-sunburst/flare while the
  README stops at 2.5; README-sourced models are refused
  as stale.
- ComfyUI nodes (verified in `nodes.py`): PoseGalleryNode,
  CostumeGalleryNode, PortraitGalleryNode,
  CharacterRecipeNode; the plugin reuses ComfyUI's own
  torch/numpy/Pillow/aiohttp, no extra dependency.

## What hevi already had (not duplicated)

- `image.pose_library`: pose-only index, 288 groups / 1439
  records, report-only, `has_media_output=False`, advisory
  risk hints only. This graft adds the costume and portrait
  indexes, the depth switch (the bundled index previously
  had zero depth fields), the real 18+ safety gate, and the
  recipe/workbench layers.
- `image.multi_ref_compose` (golive3): generic multi-reference
  composition with provider limits. The character recipe gate
  does not re-implement it; it validates the fixed
  three-slot recipe and compiles it into the exact input
  shape multi_ref_compose consumes. Provider limits are
  restated from `golive3.PROVIDER_REF_LIMITS`.
- `qa.parametric_pose_template`: parameterised action
  templates with kinematic constraints and a stick-figure
  render; complementary, different layer.
- Dance MV A5 action-chain gate: action design layer;
  different layer from reference libraries.

## Images stay outside the repo

The full gallery is about 1.2 GB and is never bundled into
hevi. All references resolve at runtime under
`HEVI_POSE_GALLERY_HOME`. The 667 MB pose subset on the Mica
side (`~/workspace/references/ai-pose-gallery-zh/`) is not
on ubuntu26; syncing it (and deciding whether and how much
of the costume/portrait images to sync) is a separate ops
item, not part of this graft. Until a checkout exists, the
gates fail by name and never claim a picture exists.

## Execution

All A gates are discipline only (pass/fail on declarations);
all B schemas are fake contracts with `executed_here: false`.
No install script was run, no key was handled, no image was
generated, no ComfyUI instance was contacted.
