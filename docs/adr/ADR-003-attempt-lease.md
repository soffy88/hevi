# ADR-003 Attempt Lease, Heartbeat, and Recovery

- Status: Accepted
- Date: 2026-08-25

## Decision

Ownership is a lease, not a status string. A worker claims a queued task,
creates an attempt with `lease_token` / `lease_until`, and heartbeats.
Recovery scans only expired leases with stale heartbeats, marks the attempt
`interrupted`, and requeues the task. A revived worker cannot finish with a
stale token.

## Consequences

- Rolling deploys must not treat `running` as zombie.
- Checkpoints bind to `attempt_id` so the next worker resumes a boundary.
