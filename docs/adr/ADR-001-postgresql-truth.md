# ADR-001 PostgreSQL as SaaS Production Truth

- Status: Accepted
- Date: 2026-08-25

## Decision

PostgreSQL is the only SaaS source of truth for Production, Revision, Task,
Attempt, Constraint, Artifact, Evaluation, and Event state. SQLite `TaskRun`
and filesystem workspaces are Local Mode projections, enabled only when
`HEVI_LOCAL_MODE=1` / `settings.local_mode`. Process-level maps are cache or
test hooks, never production truth.

## Consequences

- Alembic is the only production schema manager.
- API replicas must reconstruct director and task state from PostgreSQL.
- Dual-write to SQLite in SaaS mode is a defect.
