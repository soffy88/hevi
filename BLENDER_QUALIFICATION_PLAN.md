# HEVI Blender Production Qualification (Version 1)

## Scope & Constraints

**Purpose**: Close the four final qualification gates:
1. PostgreSQL-backed real E2E (success path)
2. Blender failure E2E (failure path)
3. Replay/Duplicate safety E2E
4. Full final regression (includes MyPy run)

**Constraints** (per conversation):
- Cannot modify canonical 3O repos or `scripts/ci/run_3o_v3_final_global_audit.py`
- No new orchestrator, authority, API endpoint, V2V/subtitle/timeline expansion
- `blender_previz` gated by `BLENDER_PREVIZ_ENABLED`
- Blender binary at `/home/soffy/.local/blender/blender`
- Must commit with clean worktree and `FINAL_GLOBAL_INDEPENDENT_AUDIT=PASS`

**Current state (after our fixes)**:
- Status-contract mismatch fixed (`"status": "completed"` returned by adapter)
- Existing adapter + workflow + capabilities + tests already present
- All non-E2E regression tests pass (Ruff, targeted test suites, final audit)

**Execution order** (tool calls required):

1. **PostgreSQL-backed real E2E**
   - Ensure PostgreSQL is running (check DB health)
   - Create real task via TaskService (use the real repository, NOT a mock)
   - Submit → claim → `_run_adapter_task` (not direct adapter calls)
   - Verify canonical persisted state, real Blender execution, artifact and DB rows
   - Write observational data (TASK_ID, PRODUCTION_RUN_ID, ARTIFACT_ID, counts)

2. **Blender failure E2E**
   - Create a deterministic invalid Blender workload (shot_spec that causes Blender to exit with error)
   - Run the same real task flow
   - Verify failure propagation to task status, `track_task_failure()` call, RepairIncident linking

3. **Replay/Duplicate safety E2E**
   - Pick a successful task
   - Replay via real recovery/resume flow (claim same task, run adapter again via TaskService)
   - Assert no duplicate Blender executions or artifact creations
   - Capture counts before/after for reporting

4. **Full final regression**
   - Run MyPy on hevi/ (capture pre-existing errors)
   - Run Ruff check (should be clean)
   - Re-run the full test suite (targeted test sets)
   - Re-run the final independent audit script (should still pass)

**Key requirements**:
- Use the *real* PostgreSQL pool (via `hevi.db.pg_pool.get_hevi_pg_pool()`)
- Use the real repository instance (`TaskRepository`, `ArtifactRepository`)
- The adapter should run via `TaskService._run_adapter_task`, not direct call to `ProductionAdapterRegistry.execute()`
- Must verify persisted state in PostgreSQL (task, artifact, incident tables)
- All writes to the output summary are via bash writes (or cat).

**Data structures for reporting** (structured for later table):
```
{
  "POSTGRES_BLENDER_E2E": "PASS/FAIL",
  "BLENDER_REAL_PROCESS_EXECUTED": "YES/NO",
  "ARTIFACT_MANIFEST_CREATED": "YES/NO",
  "ARTIFACT_DB_ROW_CREATED": "YES/NO",
  "ARTIFACT_FILE_EXISTS": "YES/NO",
  "ARTIFACT_RETRIEVABLE": "YES/NO",
  "TASK_ID": "uuid",
  "PRODUCTION_RUN_ID": "uuid",
  "ARTIFACT_ID": "uuid",
  "FAILURE_TASK_ID": "uuid",
  "FAILURE_CODE": "string",
  "REPAIR_ACTION": "string",
  "REPAIR_INCIDENT_ID": "uuid",
  "BLENDER_EXECUTION_COUNT_BEFORE": 0,
  "BLENDER_EXECUTION_COUNT_AFTER": 0,
  "ARTIFACT_COUNT_BEFORE": 0,
  "ARTIFACT_COUNT_AFTER": 0
}
```

**Tools** (for Phase 1): `bash`, `write`, `read`, `edit`, `ls`
**Tools** (for Phases 2-3): same, plus `hevi` runtime modules (task_service, adapter, etc.)

**Implementation details to note**:
- We have `hevi.creative.layer4.blender_workflow` which writes PNG files to `output/blender_render.png` by default (adjustable via shot_spec).
- `hevi.production.adapters` contains `execute_blender_previz` which registers the adapter with TaskService.
- The adapter uses `blender_render_workflow` which calls the real Blender binary.
- The task service uses `ProductionAdapterRegistry` injected into it. The default adapter registry includes our new adapter (already added).
- You must create a `shot_spec` in the task's config_json for the valid E2E and an intentionally failing spec for the failure E2E (e.g., missing objects, malformed path).

**Per-section output** (bash writes of results), examples:
```bash
write [path="hevi-blender-results.log"] [content="<formatted summary>" ]
```

**Next steps (to implement)**:
1. Run PostgreSQL health checks; if DB not healthy, set up dummy data but note that real E2E cannot run without DB.
2. Implement real E2E in a Python script (use bash to invoke it) using real TaskService and repository.
3. Export the observational fields (TASK_ID, etc.) as environment variables for later use.
4. Run failure and replay E2Es similarly.
5. Aggregate all results into the final summary and write to a file (qualify_output.json).
6. Then proceed to commit and re-audit (but you must ensure the worktree is clean).

**IMPORTANT**: 
- Do NOT mock the adapter or the TaskService.
- Do NOT directly call `blender_render_workflow` without going through `_run_adapter_task`.
- Do NOT use in-memory `PgPool` (the tests use a real PgPool) unless you have PostgreSQL.
- If PostgreSQL is not reachable, note blocker in output and consider the gate pending.

**Final deliverable**:
- A file qualifying_output.json with all collected fields and PASS/FAIL states for each gate.
- All E2E results (task IDs, artifact IDs, counts) logged.
- All blockers or errors captured.

**IMPORTANT**: After implementing the 4 E2E gates, run the final regression pipeline (MyPy, Ruff, test suites, final audit) to ensure no regressions.

**End of plan**