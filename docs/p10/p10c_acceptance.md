# P10c Acceptance Note

```yaml
status: PASS (C1-C8)
date: 2026-10-03
spec: docs/p10/p10c_spec.md
```

## Implementation

`hevi/creative/direction_plan/`: `models.py` (Anchor/TimeBinding, Decision+change_set,
BeatPlan+proxy curves, CueMap+compose, CameraSpec+geometry_class, SignatureShot,
SoundDirection+silence) + `adapters.py` (CreativeCue→BeatCue link, legacy UNDIRECTED)
+ `compiler.py` (fail-loud compile, reproducible compile_hash, coarse negotiate +
pre-approved degrade only) + `errors.py`.

## Gate results

| Gate | Result |
|------|--------|
| C1 change_set locatable | PASS (APPROVED without change_set rejected; test positional footgun fixed with keywords) |
| C2 beat coverage + proxy | PASS (gap detected; proxyless curve flagged H) |
| C3 CUE_CONFLICT + plan expand | PASS (overlap without compose rejected; actions expand to check entries) |
| C4 vocab + signature unique | PASS (pull_back added to movement vocab; duplicate signature rejected) |
| C5 silence scope | PASS (scope-less silence rejected) |
| C6 adapter回指 | PASS (cue_id + creative_cue_ref; legacy UNDIRECTED) |
| C7 compiler skeleton | PASS (fail-loud ×3; hash reproducible; degrade gated; UNSATISFIABLE/SATISFIED) |
| C8 P10-S rebinding | PASS (P10c Cue/Camera from frozen spike JSONs; measured 0.675 in spec range) |
| authority boundary | PASS (AST scan clean) |

## Verification

- `.venv/bin/python -m pytest tests/p10/ -q`: **61 passed**
- ruff: clean; mypy: clean (5 source files, NEW errors 0)

## Non-goals respected

No verdict engine, detector calibration, dependency/impact graph, Memory (P10d).
