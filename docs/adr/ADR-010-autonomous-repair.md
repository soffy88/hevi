# ADR-010 Autonomous Repair Budget and Convergence

- Status: Accepted
- Date: 2026-08-25

## Decision

`RepairController` decides; `apply_repair_decision` executes. Actions are
scoped (replace reference, new seed, recompile, switch provider). Stop when
gates pass, budget/attempts exhaust, divergence is detected, or marginal gain
stalls. Every stop has `stop_reason`. Retakes reserve the retake envelope,
never the base rendering allocation.

## Consequences

- Identity mismatch, missing dialogue, and scene drift must produce a
  machine-readable plan and a consumed patch.
- Infinite retries are a bug even if the user asked for Cinema.
