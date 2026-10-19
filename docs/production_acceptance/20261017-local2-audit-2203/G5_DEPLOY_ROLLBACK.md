# G5 — Deployment and rollback

- `.github/workflows/production-release.yml` is a qualification gate and artifact uploader, not evidence of a complete production deploy/rollback workflow.
- `hevi/deploy/docker-compose-prod.yml` is explicitly deprecated; this audit did not deploy or restart any service.
- No production health endpoint, external URL, container restart count, database migration, immutable image digest, backup restore, rollback drill, or post-deploy business smoke was executed.
- The authoritative current deployment procedure and target environment still need to be verified before production acceptance.

Decision: NOT ACCEPTED. No production rollout is authorized by this audit, and no claim of live deployment is made.
