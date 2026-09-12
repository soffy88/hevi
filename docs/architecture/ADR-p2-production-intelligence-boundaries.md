# ADR: P2 Production Intelligence Boundaries

Status: accepted for implementation on `platform/production-intelligence-vnext`.

## Decisions

1. The P0 Production Graph remains the sole semantic authority. P1 remains the
   human command surface.
2. P2 agents, crews and plugins emit typed proposals. They cannot call a
   provider, mutate a graph snapshot, or create a task directly.
3. P2 records use the existing `production_graph_entities` revision-scoped
   store. This avoids a second database authority while preserving restart and
   audit behavior.
4. Adaptive crew conflict resolution follows explicit user instruction,
   locked canonical state, project policy/memory, then learned preference.
5. Learning writes outcome evidence and a preference candidate; it never
   silently rewrites a locked production decision.
6. Scheduler/recovery uses the existing Task/MPT lease and checkpoint path.
   The P2 dispatch lease is evidence/control metadata only.
7. NLE operations become canonical revision operations where semantic and
   remain view state where non-semantic. Regeneration uses minimum dependency
   subtrees.
8. Plugins are allow-listed, signed, and permission-scoped to read data or
   propose typed patches. Arbitrary code execution is out of scope.

## Rejected alternatives

- A second P2 task queue or scheduler: rejected because it would split durable
  execution and idempotency authority.
- Agent-owned production JSON: rejected because it bypasses revision,
  provenance, readiness, and lock protection.
- Automatic preference application: rejected because learned behavior cannot
  override user intent or locked canonical state.

## Evidence contract

Gold D–J tests must exercise the service/API against a persisted project and
must retain IDs linking proposal, revision, execution, artifact, evaluation,
and rights evidence. A record without a project/revision binding is invalid.

