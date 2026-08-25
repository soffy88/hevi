# ADR-005 Immutable Production Revision and Stage Lock

- Status: Accepted
- Date: 2026-08-25

## Decision

Director documents live on `production_revisions`. A lock points at a
revision id; it never mutates `snapshot_json` in place. Upstream invalidation
creates a new revision and updates the lock pointer. CI forbids
`UPDATE production_revisions ... snapshot_json =`.

## Consequences

- Produce always names `revision_id`.
- Replay is revision + provider snapshot + seed.
