# P1 Director Workbench Acceptance

Status: partial product closure; final P1 acceptance remains open until the
full candidate/rework/timeline/memory/version/template gate and authoritative
release check are complete.

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

Closure commits add persisted Workbench control records, canonical
candidate/memory/version/template/rework endpoints, the async One-Prompt
handoff, and the real Playwright harness in
`tests/p1_browser/test_director_workbench_browser.py`.

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
- Real browser run against the FastAPI backend and Next.js frontend passed the
  core/reopen/stale-revision flow and 1440x900/1280x720 screenshots.
- Real product orchestration browser coverage passed for historical and
  long-form persisted projects; the one-prompt semantic route is exercised,
  and the async CPU-render handoff now reaches the Workbench before render
  completion. The latest live run persisted task
  `4d0a4d26-c05b-49f3-9e64-cdcc5a761bd9`, artifact
  `ad1de1377729089b9c2abb0a0527c12726ea7e1828e6fce9c49a541f67537fb6`, and
  output `/tmp/hevi-one-prompt-4d0a4d26-c05b-49f3-9e64-cdcc5a761bd9.mp4`.

## Acceptance status

The following are implemented as projections or real commands: Workbench shell,
project navigator, story/storyboard/canvas/timeline/assets/QA views, keyframe
lock controls, ReferenceBundle inspection, production modes, Director
proposal/apply flow, revision history, task/execution context, reopen from the
canonical snapshot, and lost-update protection.

P1 is not promoted to complete by this document. Remaining mandatory evidence
includes a browser-verified candidate lifecycle with two selected artifacts,
look-variant targeted rework, complete timeline command coverage, memory
authority/reopen proof, prompt/skill version diff and rollback pinning,
template policy browser proof, one-prompt final artifact preview, acceptance
guards, and the final full release gate at the final source SHA.

## Final browser closure checkpoint

At `0150ba56de83db81117eeff2052609ebd049ad66`, the frozen One-Prompt product
flow is accepted: the browser receives project/task identity before CPU render,
the persisted task is visible, and the final artifact survives reload. The
current closure work also keeps candidate rendering on the real
Compiler → Remotion runtime boundary and exposes the machine-readable
dependency projection plus Director project-memory context. These changes are
not themselves promotion evidence: the remaining browser groups above must be
run against persisted projects and recorded before `P1_FINAL_ACCEPTANCE=YES`.

## Audit history

`INITIAL P1 IMPLEMENTATION` → `PARTIAL ACCEPTANCE` → `FINAL PRODUCT CLOSURE`

The final product closure entry is intentionally not marked complete in this
checkpoint: the evidence above records actual browser results without
promoting the remaining unverified gates.

Generated media, runtime databases, screenshots, browser traces, and logs are
not committed.
