# Hevi Architecture Decision Records

These ADRs and RFCs freeze the decisions in `docs/Hevi_10分完整架构升级方案_v1.0`.
A new production feature must name the ADR it follows; if none applies, write one.

| ID | Title |
|---|---|
| [ADR-001](ADR-001-postgresql-truth.md) | PostgreSQL is SaaS production truth; SQLite is Local Mode only |
| [ADR-002](ADR-002-api-worker-separation.md) | API and billable workers are separate processes |
| [ADR-003](ADR-003-attempt-lease.md) | Attempt lease / heartbeat / recovery |
| [ADR-004](ADR-004-transactional-outbox.md) | Transactional outbox and event bus |
| [ADR-005](ADR-005-immutable-revision.md) | Immutable production revision and stage lock |
| [ADR-006](ADR-006-constraint-graph.md) | Constraint graph, compiler, and coverage |
| [ADR-007](ADR-007-artifact-store.md) | Artifact store and provenance |
| [ADR-008](ADR-008-provider-policy.md) | Provider capability and policy engine |
| [ADR-009](ADR-009-gate-policy.md) | QualityProfile compiles to GatePolicy |
| [ADR-010](ADR-010-autonomous-repair.md) | Autonomous repair budget and convergence |
| [ADR-011](ADR-011-billing-idempotency.md) | Billing reservation / consume / refund idempotency |
| [ADR-012](ADR-012-legacy-deprecation.md) | Legacy route deprecation policy |
| [RFC-013](RFC-013-production-ir.md) | Production IR schema v1 and migration |
| [RFC-014](RFC-014-slo-tracing.md) | SLO, tracing, and metric naming |
| [RFC-015](RFC-015-gpu-scheduler.md) | Local GPU resource scheduler |
