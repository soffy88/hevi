# HEVI-P0-EXECUTION-CONTRACT-001 — evidence

Regenerate everything in this directory with:

```
python scripts/execution_contract_e2e.py --out artifacts/execution_contract/e2e
python scripts/acceptance_matrix.py \
  --e2e-evidence artifacts/execution_contract/e2e_evidence.json \
  --suite-summary <full-suite-summary.json>
```

## Real artifact

`e2e/render/render-1_html.mp4` — produced by the real chain: `VisualSceneIR` →
`ProductionOperation` → `ProductionExecutor` → `HtmlGsapProductionAdapter` →
`compile_scene` → `RenderPlan` → `HtmlGsapRenderer` (real browser capture, real
FFmpeg encode).

```
sha256    7ddbc2add7548477fd3d2bb10fd202eb6a657ffe98f3154daa4bd73db9419990
bytes     8824
ffprobe   format_name=mov,mp4,m4a,3gp,3g2,mj2  duration=2.000000
          stream 0: video 640x360 avg_frame_rate=24/1
```

Two independent runs produce byte-identical output — determinism is measured, not
asserted.

## Gates

20/20 PASS. `acceptance_matrix.py` measures each gate from the repository and from real
artifacts; A17–A20 read the E2E evidence file rather than a hand-written claim.

## BLOCKED

**OpenReel E2E (§54) — BLOCKED.** OpenReel is not present: no package, no sibling
checkout, nothing in `pyproject`. The seam is built and fully tested with an injected
runner (`tests/architecture/test_openreel_seam.py`, 20 tests), and
`tests/architecture/test_execution_contract_architecture.py` asserts the core never
imports it. What cannot be done is executing a real OpenReel action, so that specific
gate is reported BLOCKED rather than skipped.

Note the OpenReel seam is not one of the twenty §61 gates: §61 counts the contract and
the real-media chain, and §54 makes OpenReel explicitly conditional.

**Pre-existing, not fixed here (§46):** `ShotPlan` and `MotionPlan` are each defined in
two long-standing modules. Pinned at their current count so a third definition fails the
architecture audit; fixing them belongs to their owning phase's owner.
