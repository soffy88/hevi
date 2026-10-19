# HEVI production readiness — final decision

**Decision: NO-GO for general production operation.** A limited internal pilot of the existing non-AI video line may be considered only after human review of each deliverable; this is not a production launch approval.

## Evidence summary

| Gate | Result | Evidence / blocker |
|---|---|---|
| G0 Baseline and WIP preservation | PASS with resource warning | Branch `closure/3o-v3-architecture-creative-baseline`, HEAD `d365dd54`; no cleanup or production changes; disk 99% used and 26 Opencode processes observed |
| G1 Quality gates | FAIL | Global Ruff 3,709 findings; all six touched Python files pass Ruff; 170 targeted tests pass; full suite, typing, coverage, frontend build and security scans not verified |
| G2 Security | PARTIAL | Deprecated Compose exposes DB/cache/object-store ports if used; mutable MinIO tags; authoritative live deployment configuration not yet verified |
| G3 Real non-AI video | PARTIAL | Existing MP4 probes as H.264 1280x720/25fps + AAC, SHA-256 recorded; historical summary duration conflicts with actual probe; human review pending; subtitle visual QC not verified |
| G4 Durable delivery | PARTIAL | 170 targeted contract/receipt/artifact/studio tests pass; no current DB-backed task/retry/restart/idempotency E2E |
| G5 Deploy/rollback | NOT ACCEPTED | No deploy, health check, backup restore, or rollback drill performed; release workflow alone is not deployment evidence |
| G6 Canary operations | NOT RUN | No production canary or current provider/billing/monitoring validation |

## Changes made
1. Fixed the legacy auth service adapter to use the current canonical JWT functions and added regression coverage.
2. Switched the rate-limit adapter from obsolete `aioredis` import to `redis.asyncio` (redis is importable in the current locked environment).
3. Allowed the `zero` and `scene3d` runtimes already declared by production line recipes.
4. Updated the Scene3D recipe contract test for its self-rendering terminal `report` stage.
5. Isolated weak-secret policy tests from environment-injected secret values.
6. Added phase-by-phase acceptance evidence and test logs under this directory.

## P0/P1 blockers before release
1. Establish a reproducible, isolated CI baseline and bring global Ruff to green without suppressing findings; run full tests, typing, coverage, frontend build and security gates.
2. Regenerate the non-AI video with current code; resolve the legacy summary/probe duration mismatch and independently verify subtitle visibility/readability, audio synchronization, and human editorial approval.
3. Prove the current database-backed delivery chain through success, failure/retry, restart recovery, idempotency, and provenance/approval round-trip.
4. Verify the authoritative deployment configuration, secret injection, port exposure, immutable image versions, backups/restores, health checks and rollback drill.
5. Execute a bounded staging canary with explicit quality and operational thresholds before any production release.
6. Add/verify direct dependency provenance for `redis.asyncio` in a clean install. The source was updated, but project dependency metadata was left unchanged in this pass.

## Safety actions taken
- No production deployment or service restart.
- No destructive Git operation, cleanup, or deletion of existing artifacts.
- No global Ruff autofix.
- No production credentials read or external paid provider operation.
- Existing untracked project artifacts were preserved.

This decision is based on evidence collected on 2026-10-17. It does not imply that the historical MP4 is unusable; it means the complete current production service has not met its release gates.
