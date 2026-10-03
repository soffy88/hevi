# P10d Acceptance Note

```yaml
status: PASS (D1-D7)
date: 2026-10-03
spec: docs/p10/p10d_spec.md
```

## Implementation

`hevi/creative/direction_verify/`: `models.py` (ObservationSet/Evidence/Verdict) +
`verdict.py` (deterministic 5-rule aggregation, no LLM) + `detectors.py` (registry;
uncalibrated/low-confidence issuance degrades to INCONCLUSIVE; calibration requires
4 fixture keys incl. non-periodic content per R-P10-03) + `impact.py` (field-level
graph, conservative-edge warnings, early cutoff, rerun_plan, inbound STALE) +
`memory.py` (evidence promotion ≥2, user-scope explicit, refusal suppression,
retirement retained, suggestions never gate).

## Gate results

| Gate | Result |
|------|--------|
| D1 aggregation | PASS (FAIL→REVISE/FAIL; must INCONCLUSIVE→INCONCLUSIVE; should/may→WARNINGS) |
| D2 calibration gate | PASS (unregistered PASS issuance → INCONCLUSIVE; below-theta → INCONCLUSIVE) |
| D3 observation binding | PASS (hash-bound; verdict references plan + artifact) |
| D4 impact + cutoff | PASS (cascade unions downstream writes; preserved proven; cutoff ⊆ upper) |
| D5 inbound | PASS (authority change → STALE ids) |
| D6 memory | PASS (no-evidence rejected; threshold promotion; refusal suppression; retired retained) |
| D7 frozen replay | PASS (frozen P10-S verdict re-aggregated through new engine → PASS) |
| authority boundary | PASS (AST scan clean) |

## Implementation findings (fixed during build)

1. Cascade must union invalidated nodes' writes, else downstream never reached.
2. Changed nodes belong in the upper bound (earliest_stage=Thesis, not BeatPlan).
3. Memory support must derive from initial evidence; twice-refused entries suppressed from suggest.

## Verification

- `.venv/bin/python -m pytest tests/p10/ -q`: **69 passed**
- ruff: clean; mypy: clean (7 source files, NEW errors 0)

## Non-goals respected

Similarity guard off; multilingual IDs; per-shot cache production (A9); Q4 dual-attestation org process.
