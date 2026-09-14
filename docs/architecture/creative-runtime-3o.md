# HEVI 3O Creative Runtime

This branch adds an additive, HEVI-native creative runtime. The existing
Narrative v1, production, and Distribution contracts remain unchanged.

## Authority and direction

```text
User
  -> HEVI production service
  -> Production Graph
  -> 3O capability composition
  -> Artifact / Evidence / Verdict
```

The internal 3O responsibilities are deliberately separated:

- `obase`: canonical objects, contracts, identity, authority, and provenance.
- `oprim`: deterministic operations such as hashing, version comparison, and
  validated state-delta application.
- `oskill`: professional knowledge and policy. A skill has no state authority
  and cannot bypass permissions or quality gates.
- `omodul`: composed production modules and stage workflows.
- `oservi`: externally callable HEVI services and runtime surfaces.

Users never need to understand 3O names to use HEVI.

## Canonical authority

`NarrativeCanon` and the related `obase` records are the source of truth for
creative state. Documents, Markdown, HTML, UI cards, forecasts, audits, and
shot plans are projections or proposals. A proposal must be validated against
the current revision before an explicit commit can create canonical state.

The direction of authority is:

```text
Narrative canon
  -> story / script intent
  -> storyboard / shot intent
  -> HEVI production graph
  -> artifact and evidence
  -> audit / feedback proposal
```

Downstream evaluation must not silently mutate an upstream canonical object.

## Contract envelope

Every creative object has a stable object ID, project scope, schema version,
revision, authority, timestamps, and provenance references. Canonical JSON is
deterministically serializable. `CreativeStateDelta` is intentionally a
proposal and `apply_state_delta` rejects stale revisions, protected paths, and
unknown fields before returning a newly validated copy.

This document describes HEVI contracts only. No external creative runtime is
used as a dependency, and no external source text, prompt, skill text, test,
fixture, or template is part of the implementation.
