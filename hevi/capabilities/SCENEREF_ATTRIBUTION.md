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
