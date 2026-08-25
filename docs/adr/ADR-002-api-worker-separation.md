# ADR-002 API and Billable Worker Separation

- Status: Accepted
- Date: 2026-08-25

## Decision

`hevi-api` never starts a production `QueueWorker`. Billable work is claimed
by `hevi.queue.worker_entrypoint`. Scheduling decisions are written by
`hevi.scheduler.entrypoint`. FastAPI `BackgroundTasks` may only run
lossy/local compatibility work after `hevi.tasks.dispatch` rejects a
PostgreSQL pool.

## Consequences

- Scaling API replicas must not multiply executors.
- CI fails if a router calls `run_task_background` or `orchestrate_longvideo`
  through `BackgroundTasks`.
