# ADR-006 Constraint Graph, Compiler, and Coverage

- Status: Accepted
- Date: 2026-08-25

## Decision

Locked director IR is derived into a provider-neutral Constraint Graph, then
compiled. Every required constraint is `compiled`, `unsupported`, or
`degraded`. Silent drop is a delivery failure. Coverage is stored on
`constraint_coverage` and emitted as metrics.

## Consequences

- Provider-specific prompt encoding happens after compile.
- Cinema may not degrade identity / continuity / delivery constraints.
