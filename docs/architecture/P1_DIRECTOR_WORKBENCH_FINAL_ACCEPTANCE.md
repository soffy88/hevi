# P1 Director Workbench Acceptance

Status: implementation checkpoint; final P1 acceptance remains open until
browser-level product E2E and the remaining authoring controls are verified.

## Baseline

- `P0_BASELINE_SHA`: `7c623da9854a14c121dd342211bd1faf8c8ee155`
- `P1_STARTING_SHA`: `7c623da9854a14c121dd342211bd1faf8c8ee155`
- Branch: `product/director-workbench-vnext`
- Route: `/studio/projects/{project_id}`
- One-prompt entrypoint: `POST /api/studio/one-prompt`

The P0 production graph remains the authority. The Workbench stores only
selection, view, and loading state in React. Semantic edits use Studio API v2,
revision-producing operations, and stale-revision protection.

## Implemented and verified

The following phase commits are on this branch:

- `eb7fcf5` — shell, canonical project route, DTO/client boundary, inventory
- `53b0aec` — project hub and one-prompt entrypoint
- `28f280b` — keyframe lock controls and persisted task center
- `2118413` — production mode and revision history
- `e4b8b11` — continuity/readiness and execution evidence
- `130e548` — canonical character/world state and creative registry projection
- `f3dc742` — DirectorSession/DirectorDecision applied revision patch flow
- `5d7c15f` — API inventory/OpenAPI revision endpoint
- `509dbd3` — Canvas projection/semantic patch boundary and references view
- `0b25c0d` — Director patch concurrency regression test

Evidence currently available:

- Backend Studio API integration: `tests/test_studio_v2_api.py` — 4 passed.
- Frontend Workbench tests: `hevi-web/src/components/workbench/DirectorWorkbench.test.tsx`.
- Frontend typecheck and suite: 31 files, 158 tests passed.
- `docs/architecture/P1_WORKBENCH_INVENTORY.md` records the pre-existing UI
  surfaces and reuse decisions.
- Canvas semantic changes reject unsupported/non-canonical targets and layout
  changes do not create production revisions.
- Director patch application is revision-based and stale updates return
  `409 STALE_REVISION`.

## Acceptance status

The following are implemented as projections or real commands: Workbench shell,
project navigator, story/storyboard/canvas/timeline/assets/QA views, keyframe
lock controls, ReferenceBundle inspection, production modes, Director
proposal/apply flow, revision history, task/execution context, reopen from the
canonical snapshot, and lost-update protection.

P1 is not promoted to complete by this document. Remaining mandatory evidence
includes a real browser run against a running backend, visual QA at 1440x900
and 1280x720, real historical/long-form/one-prompt Workbench product seeds,
candidate lifecycle commands, dependency-aware targeted rework, persisted
creative memory/registry version operations, timeline editing commands, and a
final full release gate at the final source SHA.

Generated media, runtime databases, screenshots, browser traces, and logs are
not committed.
