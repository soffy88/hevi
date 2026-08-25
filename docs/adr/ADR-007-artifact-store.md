# ADR-007 Artifact Store and Provenance

- Status: Accepted
- Date: 2026-08-25

## Decision

Completed PostgreSQL tasks must commit an `ArtifactManifest` with durable URI,
sha256, and byte size. MinIO/S3 is SaaS object truth; the worker filesystem
is scratch. `result_video_path` is a response projection. Downloads go
through authorized materialize/presign, never raw host paths.

## Consequences

- Marking `completed` without a committed hash is a defect.
- Artifact relations record DERIVED_FROM / COMPOSED_FROM / EVIDENCE_FOR.
