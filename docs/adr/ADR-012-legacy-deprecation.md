# ADR-012 Legacy Route Deprecation Policy

- Status: Accepted
- Date: 2026-08-25

## Decision

Compatibility routes may exist, but each must name its canonical replacement
and must not introduce a second lifecycle. Local projections (`TaskRun`,
`_LOCAL_WORK_PROJECTIONS`) are allowed only behind `local_mode` or explicit
non-PostgreSQL repositories. Compatibility layers have a deletion condition;
they are not permanent architecture.

## Consequences

- New workflows attach as adapters to Production / TaskService.
- A router that creates an independent run state machine is a regression.
