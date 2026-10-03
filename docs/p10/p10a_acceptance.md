# P10a Acceptance Report

```yaml
status: PASS (14/14 gates)
date: 2026-10-03
spec: docs/p10/p10a_impl_spec.md (FROZEN)
ownership: docs/p10/p10a_ownership.md
```

## Commit / commands

- test command: `.venv/bin/python -m pytest tests/p10/ -q`
- test count: **45 passed** (25 spike + 20 P10a), 20 collected in `test_p10a_state.py`
- ruff: clean (`hevi/creative/direction_state/`, `tests/p10/test_p10a_state.py`)
- type-check: mypy clean, 5 source files, 0 errors (repo baseline NEW_MYPY_ERRORS=0 preserved)

## Implementation

`hevi/creative/direction_state/`: `state.py` (contracts) + `machine.py` (matrix, pure)
+ `repository.py` (file adapter: events.jsonl source of truth + tmp+replace snapshot,
fcntl + threading locks) + `errors.py` + `__init__.py` (SPEC §14 API).
Ownership: new component holds ONLY direction state + policy + adapter; approval
actors / compile receipts / artifact hashes are referenced, never owned.

## Gate results

| Gate | Result | Evidence |
|------|--------|----------|
| A1 transition matrix | PASS | Fixture A full chain DRAFT→VERIFIED, 6 events |
| A2 illegal transition rejection | PASS | 10 forbidden pairs parametrized; `before == after`, event count unchanged |
| A3 reject semantics | PASS | REJECT → stays REVIEW_REQUIRED + review-kind event |
| A4 request-changes semantics | PASS | REQUEST_CHANGES → PROPOSED; distinct op from REJECT |
| A5 atomic transition | PASS | injected `_append_event`/`_write_snapshot` faults → state unchanged; snapshot-stale converges on reload to legal state |
| A6 approval immutability | PASS | A6 test: binding mismatch rejected; A7: VERIFIED snapshot byte-identical after evil transition |
| A7 compile binding | PASS | COMPILE without receipt / wrong revision → MISSING_BINDING |
| A8 verification binding | PASS | VERIFY without/invalid hash or receipt → MISSING_BINDING |
| A9 revision immutability | PASS | only CREATE_REVISION spawns r2; r1 bytes + lifecycle untouched |
| A10 concurrency | PASS | stale expected_state → CONFLICT_STALE_STATE, winner only |
| A11 idempotency | PASS | same command_id ×2 → 1 event, same state; reused id + different payload → DUPLICATE_COMMAND |
| A12 persistence/reload | PASS | new instance on same root → identical state |
| A13 recovery | PASS | fault before/during/after persistence → reload converges, no divergence |
| A14 transition history | PASS | Fixture C: r2 history == [REVISION_PROPOSED, APPROVED]; r1 intact |

## Required negative evidence (all recorded by tests)

```text
REJECT does not mutate lifecycle                      # A3
invalid transition does not mutate state              # A2 (10 pairs)
stale command does not mutate state                   # A8 CONFLICT
duplicate command does not duplicate event            # A9 (1 event)
failed persistence does not leave partial state       # A5 (reload converges)
verified revision cannot be modified                  # A7 (bytes identical)
```

## Exit evaluation

```text
14 acceptance gates PASS + real persistence + real history + atomicity
+ idempotency + concurrency + recovery + revision immutability
=> P10a = PASS => P10b DESIGN ALLOWED
```

Non-goals respected: no BenchmarkSet/Treatment/CueMap/SoundDirection/Program/
Compiler/Impact/Memory; no 15-object freeze.
