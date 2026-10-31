# Attribution: open-source-canvas method ideas

Source: `raph651/open-source-canvas` (MIT, Copyright (c) 2026
raph651). Method ideas only, clean-room rewritten; no code, text,
configuration, workflow JSON, screenshot or media from that
repository is copied into hevi, and its frontend is not installed.

What was borrowed (discipline only):

- The ComfyUI gateway contract: a six-endpoint allowlist, a
  request-body cap, visitor isolation for queue-scoped endpoints,
  redacted health responses, and authentication declared by layer
  only, never supplied as a value.
- The pre-submit model-install check: compare a model's required
  files against a caller-supplied loader-visibility snapshot and
  fail naming the file and target folder; never guess.
- Canvas execution scheduling: ready batches with a configurable
  parallel cap, upstream-failure skip, interrupt-based cancel,
  and one task per seed, sharing the single retry ceiling already
  defined by `canvas_workflow`.

What was deliberately NOT taken, and remains unimplemented:

- No real ComfyUI executor: no job is submitted, no ComfyUI
  server is contacted, no workflow JSON is built or run.
- No collaboration room (upstream: in-memory, last-write-wins,
  unauthenticated, demo only).
- No API-model wrappers: upstream's registry is empty and every
  API model reports "wrapper required"; nothing here calls a
  paid API.
- No MiniMax H3 workflow: upstream lists H3 only as an API model
  with no local workflow. H3 execution in hevi still goes through
  the existing `video.fasth3_local` path.
- No 3D viewer chain: upstream has none; the SceneRef P2 3D gap
  is untouched by this graft.
- Model weights are not bundled and are covered by their own
  licences; upstream states the same for its own repository.

Upstream evidence limits (from the read-only review,
`~/workspace/hevi-vs-open-source-canvas.md`): a 12-day-old,
100-star, single-maintainer 0.2.0 repository with no tests and
demo-only online evidence. Nothing in this graft relies on the
upstream demo, screenshots or self-reported local runs.

## Addendum: canvas ComfyUI executor (2026-10-31, D group)

The "no real ComfyUI executor" line above is now partly
superseded: `pipeline.canvas_comfy_executor` exists and
translates canvas_workflow video nodes into ComfyUI API graphs
(template plus runtime injection, 32-grid snapping) and submits
them after the gateway contract and model-install gate, with
800 ms /history polling, a 10-minute timeout and /interrupt
cancel. Evidence limit, unchanged in kind: it has ONLY been
exercised against a local fake ComfyUI server
(tests/test_canvas_comfy_executor.py); no real ComfyUI
generation has been run through it, because the local GPU is
stopped. The collaboration room, API-model wrappers, H3
workflow and 3D viewer chain remain unimplemented, for the
reasons listed above.
