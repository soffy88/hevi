# RFC-015 Local GPU Resource Scheduler

- Status: Accepted for v1 weights
- Date: 2026-08-25

## Decision

The scheduler is a pure function over persisted queue rows plus a worker
`ResourceSnapshot` (class, VRAM, slots, warm providers, quota tokens, tenant
fairness). PostgreSQL still performs the atomic claim. GPU workers advertise
`worker_resource_class` and `worker_available_vram_mb`. Cloud workers are a
separate pool with concurrency tokens, not a second task type.

## Non-goals for v1

- Kubernetes device plugins
- Per-model warm-up daemons
- Splitting Hevi into microservices per GPU class
