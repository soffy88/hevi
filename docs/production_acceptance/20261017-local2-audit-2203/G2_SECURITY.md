# G2 — Security and runtime configuration

- `hevi/deploy/docker-compose-prod.yml` explicitly labels itself DEPRECATED (2026-10-11) and says not to use it to start containers. It nevertheless contains host port mappings for PostgreSQL `5432:5432`, MinIO `9100:9000`, and Redis `6379:6379`.
- The same deprecated file uses mutable image tags `minio/minio:latest` and `minio/mc:latest`; Redis is `redis:7-alpine`. These are risks if this deprecated file is used inadvertently. No edits were made because its current operational use was not established and the file itself says not to use it.
- The production release workflow checked in at `.github/workflows/production-release.yml` runs locked dependency installation, line qualification, policy/catalog checks, and uploads qualification artifacts. It does not itself demonstrate production image publication, deployment, post-deploy smoke, or rollback.
- Secrets, TLS, authentication/tenant isolation, backup restoration, and firewall behavior were not validated against a live production environment. No credentials were read or changed.

Decision: PARTIAL / NOT ACCEPTED. First identify the authoritative deployment entrypoint and verify it—not the deprecated compose file—against a deployment checklist.
