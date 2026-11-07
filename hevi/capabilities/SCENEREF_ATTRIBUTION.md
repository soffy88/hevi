# SceneRef method attribution

Method ideas in `scene_reference.py` (the scene-first reference
assembly record, the six-section reference-prompt format, the
picture/voice slot budgets, and the intent/final separation rule)
are a clean-room reimplementation of the method described in
AliC-2001/ComfyUI-SceneRef-Nodes (Apache-2.0), as documented in
`~/workspace/hevi-vs-sceneref.md`. No upstream code, prompt text,
artwork, workflow JSON, model weight, or screenshot is copied or
bundled here. The six-section structure is also the format used by
the H3 character-sheet method; hevi defines it exactly once, in
`scene_reference.py`, and the character sheet gate shares it.

Expressly outside the upstream licence and not used: example
artwork and screenshots, Blender/Daz example files, vendored
third-party material, and all model weights (each under its own
terms). Nothing here adapts a ComfyUI node, runs a model, or
generates a picture.

Not implemented (frozen by design): ComfyUI node adaptation and
graph expansion, the 3D Viewer browser-capture chain and any
Blender/Daz conversion, local H3 execution and memory management,
the vision prompt expander, and any image backend. The "six
sections are the H3 rewriter format" claim is the upstream
repository's own statement and is not independently verified
against MiniMax documentation; it is recorded here as an
attributed method claim, not as an official standard.

## P1 grafts (2026-10-31, clean-room)

Three further method ideas were reimplemented in the same module
and no other: a photo-scene record (one main view, other angles
for the movie branch by default, a place description that must
not describe people or comment on the photographs or their
quality), a blocking record (standing markers bound to cast,
zone, depth and camera relation, with an explicit declaration
that the marker does not appear in the finished film, checked
against the character sheet gate's own view catalogue and
part-scope tables, which are reused rather than restated), and
a frame/size output precheck (the 17k+5 frame lattice at 24 fps
and grid-snapped sizes, with any crop declared in the plan).
No upstream code, prompt text or artwork was copied. The
precheck is plan arithmetic only and does not change the locked
execution values of any other capability.

## P2 feasibility check (2026-10-31, read-only)

Checked read-only on ubuntu26; nothing was installed, started,
restarted, downloaded or run. Full evidence is in
`~/workspace/hevi-vs-sceneref-p2-check.md`. In short: a ComfyUI
0.42.0 instance exists at `/data/soffy/fasth3-comfy/ComfyUI`
with no SceneRef nodes installed; the 3D Viewer browser-capture
chain does not exist in hevi; Blender 5.0.1 is present but no
Daz side and no conversion chain was found; the H3 diffusion,
32B text-encoder and VAE weights are present, but the local
RTX 3080 answers no `nvidia-smi` query, so local execution is
currently blocked at the GPU; and no Qwen3-VL 8B weight, key or
expander/image-backend wiring was found. Each blocked item
lists the step that only Soffy can take.
