# ADR-009 QualityProfile Compiles to GatePolicy

- Status: Accepted
- Date: 2026-08-25

## Decision

Economy / Standard / Cinema compile to `GatePolicy`. Artifact existence is
fail-closed in every profile. Cinema required gates, including checker
failure, are fail-closed. Economy may warn and record. Failures use the
shared taxonomy in `hevi.quality.taxonomy`.

## Consequences

- Standard/Cinema must not mark deliverable after a blocking evaluation.
- Evidence URIs belong on evaluations, not in free-text logs only.
