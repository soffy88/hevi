# ADR-008 Provider Capability and Policy Engine

- Status: Accepted
- Date: 2026-08-25

## Decision

Routing uses `ProviderPolicy`: capability, health, cost, quality history, and
optional exploration. The decision (selected, eligible, rejected, scores) is
persisted on the task. Fallback walks that snapshot. Source code must not
encode live account balance or a machine-local "only working provider".

## Consequences

- Taking a provider offline does not require an application deploy if health
  state is updated.
- Director produce with `video_provider=auto` must call the policy engine.
