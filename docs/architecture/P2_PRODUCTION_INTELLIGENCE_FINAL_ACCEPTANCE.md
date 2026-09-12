# HEVI P2 Production Intelligence Acceptance

## Baseline and boundary

`STARTING_SHA=21280f98b5a63f7beb3c49b9082a949348c99da8`  
`BRANCH=platform/production-intelligence-vnext`  
`P0/P1 authority preserved=YES`

P2 records are persisted through the existing `ProductionGraphRepository` in
`production_graph_entities`. They are bound to a canonical project and
revision. Adaptive agents and plugins emit typed proposals only; Director /
RevisionPatch remains the decision boundary and Slate/runtime remains the
execution boundary.

## P2.0 inventory and ADR

- `docs/architecture/P2_PRODUCTION_INTELLIGENCE_INVENTORY.md`
- `docs/architecture/ADR-p2-production-intelligence-boundaries.md`

## Gold D–J runtime evidence

The live PostgreSQL acceptance project was created through
`ProductionGraphRepository.create_project` and reopened from a separate
process after writes.

| Gold | Capability | Evidence |
|---|---|---|
| D | Adaptive Crew / conflict / anti-theater | `AdaptiveCrew`, typed `CrewProposal`, `AntiTheaterEvidence`, `ConflictResolution`; `p2_gold` test |
| E | Outcome learning | `ProductionOutcome` persisted, then `CreativePreference` derived with authority order |
| F | Collaboration | revision-bound `ReviewThread`, base revision retained |
| G | Spatial / NLE / localization | `SpatialConstraint`, `NLEOperation`, `LocalizationTrack` |
| H | Distributed recovery | existing Task/MPT boundary plus persisted `DispatchLease` checkpoint/recovery |
| I | Plugin security | signed, enabled manifest with allow-listed `read_graph`/`propose_patch`; proposal rejected without permission |
| J | Evaluation / rights | `EvaluationCase` → `EvaluationResult` → `RightsLedgerEntry` evidence chain |

Live PostgreSQL project: `cc8c0aad-af9b-4039-a8f7-979fe7f06b6f` (initial
probe project) and the verified persisted run used the project created in the
final live script. The final script reported one record for each of
`adaptive_crew`, `outcome`, `dispatch_lease`, `plugin_manifest`,
`plugin_proposal`, `evaluation_case`, `evaluation_result`, and `rights` after
the writes. The P2 test harness is `tests/test_p2_production_intelligence.py`
and is marked `p2_gold`.

The service/API test also exercises the real `/api/studio/projects/{id}/intelligence`
boundary and reloads records from the repository. No frontend-local state,
mock provider, or second task scheduler is used.

## Final verification record

The P2 source/test closure consists of `hevi/production_graph/intelligence.py`,
`hevi/api/routers/production_intelligence.py`, the router registration in
`hevi/api/main.py`, the P2 inventory/ADR, and the `p2_gold` tests. P0/P1 test
suites remain unchanged and are rerun at the final SHA. Generated databases,
media, and logs remain outside git.

