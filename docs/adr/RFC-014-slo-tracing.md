# RFC-014 SLO, Tracing, and Metric Naming

- Status: Accepted
- Date: 2026-08-25

## Trace context

Every log, event, and provider call should carry the populated subset of:
`trace_id`, `production_id`, `revision_id`, `plan_id`, `task_id`,
`attempt_id`, `node_id`, `provider_call_id`, `artifact_id`, `evaluation_id`.

## SLO targets

See `hevi.observability.slo.SLO_TARGETS`. Event propagation p95 < 2s.
Duplicate billing charges = 0. Completed primary artifacts available at 100%.

## Metric families

Use existing Prometheus names in `hevi.monitoring.metrics`: queue latency,
lease expirations, constraint coverage, artifact commit outcomes, WS lag.
Do not invent a second prefix for the same signal.
