# ADR: Canonical Film Production Domain

Status: accepted for P0  
Date: 2026-09-10  
Baseline: RC6 `0fcb65333ac5f6cd0860012fa569b6b050e22c6b`

## Decision

HEVI will use one versioned Production Graph as the semantic authority for
film production.  The graph is owned by `hevi.production_graph`; existing
Tongjian, Script2Video, Cinematic, Director, Vault, Studio, Canvas, Slate,
ArtifactStore, MPT and task-runtime components are retained as adapters,
projections, or execution providers according to the ownership rules below.

The graph is represented by stable canonical IDs and immutable
`ProductionRevision` snapshots.  A revision contains the source, narrative,
production ontology, scene/beat/shot graph, references, constraints, plans,
decisions and provenance required to replay or inspect a production.  Binary
assets remain in the existing Vault/ArtifactStore; graph records store their
IDs and immutable version references.

## Explicit ownership invariants

### 1. Canonical Production Graph ownership

- `ProductionProject` is the durable project aggregate.
- `ProductionRevision` is append-only.  The active revision pointer may move
  forward but an existing revision snapshot is never updated in place.
- Every production object has a stable canonical ID and a revision ID.
- Every `CanonicalShot` belongs to exactly one canonical `Scene`; an adapter
  may retain a legacy local identifier, but it cannot become a second
  authority.
- Referential integrity is validated before a revision is committed.
- Existing `productions`/`production_revisions` tables and
  `ProductionGraphRepository` are extended and reused.  No parallel
  production aggregate or ArtifactStore is permitted.

### 2. Legacy schema migration strategy

- Legacy Tongjian, Script2Video and Cinematic schemas remain readable during
  P0.
- Each legacy input is converted once into canonical IDs by a named adapter;
  adapters preserve source spans, legacy IDs and provenance.
- During migration, writes may dual-write a compatibility projection, but
  canonical state is always written first and is the semantic authority.
- Reads are migrated in this order: compatibility read, canonical read with
  compatibility fallback, canonical read.  No destructive legacy migration is
  allowed until both readers and the production-line regression pass.
- Adapters are reversible: canonical records can project back to the legacy
  DTO shape without inventing fields or silently dropping a required field.

### 3. Director/Slate boundary

- Director, Screenwriter, Producer and Editor decide *what*, *why* and
  *which* production state should exist.
- Director code may emit `RevisionPatch`, `ProductionPlan` and
  `DirectorDecision`, but may not mutate canonical production rows directly
  and may not call provider HTTP APIs.
- `run_slate()` remains deterministic work-order execution.  Slate accepts a
  validated production-plan bridge and delegates to existing pipeline,
  checkpoint, queue, MPT and provider runtime components.
- Slate may choose reliable execution details, but may not invent narrative
  structure or creative intent.

### 4. Canvas projection rule

- Canvas persists layout, viewport, grouping and UI-only edge metadata.
- Production meaning resolves through canonical object IDs and revision IDs.
- A Canvas edit that changes production meaning must be represented as a
  validated `RevisionPatch` and committed as a new `ProductionRevision`.
- `CanvasGraph.nodes_json` and `edges_json` are never consulted as the source
  of truth for narrative, assets, shots, readiness or execution.

### 5. Provider Adapter/Compiler separation

- A provider adapter owns transport only: send, poll, cancel, download and
  provider-error parsing.
- A Production Compiler owns model usage semantics: capability matching,
  reference packing, prompt/negative-prompt compilation, duration,
  resolution, audio and model limits.
- `CanonicalShot` contains no provider request body, transport flag, image
  index, model-specific field or provider-specific payload.
- Compiler output is an immutable `ExecutionPlan` pinned to project, shot,
  reference, prompt/skill and resource revisions.  Dispatch cannot mutate it.

### 6. Revision semantics

- A creative edit creates a child `ProductionRevision`; it never overwrites
  the parent object.
- A `RevisionPatch` is the only accepted mutation description for Director
  or Canvas semantic edits.
- Patch validation checks allowed paths, IDs, locks, types and cross-object
  references before commit.
- Locked creative assets and locked keyframes cannot be silently replaced.
- Existing execution-plan insert-only semantics remain in force; replan and
  repair create a new plan version linked to its parent.

### 7. Readiness semantics

- Shot readiness is a state machine, not a prompt-presence flag.
- The only state permitted to enter generation dispatch is `READY`.
- The readiness gate evaluates narrative, assets, references, continuity,
  provider capability, budget and resource availability.
- Results contain machine-readable blockers and warnings.
- Illegal transitions are rejected, including `DRAFT → GENERATING` and any
  transition out of `LOCKED`.

### 8. Provenance requirements

- Source-derived narrative records persist source document/chunk references
  at creation time; provenance is not reconstructed after generation.
- Final artifacts must be traceable through:
  `Source → NarrativeEvent → AdaptationDecision → Scene → Shot →
  DirectorDecision → Skill/Prompt version → ReferenceBundle → ExecutionPlan →
  ExecutionAttempt → Artifact`.
- Existing ArtifactStore integrity, parent relations and provenance are
  extended, not replaced.
- Every external provider attempt records its idempotency identity and
  provider job ID before polling can resume.

### 9. Resource-aware runtime invariant

- `ExecutionProfile` is the only source for effective runtime quotas.
- It records CPU quota, memory limit, GPU availability/count/VRAM, render,
  provider and I/O concurrency.
- Requested runtime concurrency must be less than or equal to the actual
  allocated resource limit after cgroup/container discovery.
- GPU unavailability is a capability/readiness result, not an application
  crash and not evidence of GPU verification.

### 10. Backward compatibility

- RC6 production lines continue to execute through their existing adapters.
- `run_slate()`, ProviderRegistry, MPT, ArtifactStore and existing task APIs
  retain their public behavior unless a tested adapter explicitly inserts the
  canonical graph boundary.
- Legacy `result_video_path`, task rows and Canvas APIs remain compatibility
  projections while canonical IDs and provenance are available.
- New tests may increase coverage and test count; existing tests are not
  weakened or skipped.

## Consequences

The graph introduces explicit domain objects and revisions before provider
dispatch.  This adds validation and persistence work, but makes identity,
continuity, readiness, compilation and provenance inspectable.  Existing
production lines retain their execution paths through adapters, so P0 does
not require a big-bang rewrite or GPU availability.

## Rejected alternatives

- Replacing MPT with Temporal: rejected; HEVI already has durable task,
  checkpoint, queue and idempotency primitives.
- Making Canvas JSONB authoritative: rejected; it cannot safely own revision,
  provenance, locks or execution semantics.
- Adding a second CharacterBible, Director, Novel2Video or ArtifactStore:
  rejected; existing authorities are adapted and converged.
- Placing Seedance/Veo/H3/Wan request fields in `CanonicalShot`: rejected;
  those belong in provider capability contracts and compilers.
