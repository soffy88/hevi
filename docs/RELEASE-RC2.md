# HEVI RC2 Release & Operator Guide (D7)

Release candidate 2 — hardening on top of `hevi-productization-rc1-2026-09-19`.
**Not a 1.0 declaration.**

## 1. Installation

### Backend (pinned, reproducible)

```bash
# from repo root, with uv installed
uv sync --frozen          # installs exactly the locked dependency set
uv run alembic upgrade head
uv run uvicorn hevi.api.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Required environment: `JWT_SECRET` (mandatory; empty → the process exits at
import). See §4.

### Frontend

```bash
cd hevi-web
npm ci                    # lockfile install
NEXT_PUBLIC_DEPLOY_ENV=production \
NEXT_PUBLIC_API_BASE=https://<your-api-host> \
NEXT_PUBLIC_USE_MOCK=false \
npm run build
npm run start
```

The build fails closed if `NEXT_PUBLIC_API_BASE` is missing or unsafe for the
declared environment — this is intentional.

## 2. Quick Start

Open `/workspace` → **制作状态** → fill 项目类型/素材/目标输出 → **开始创建**.
Advanced capabilities (persistent character, continuity, memory, provider,
repair policy) are optional and defaulted. **示例项目** is a labelled demo and
is not production evidence.

## 3. Single-host deployment contract

HEVI's durable differentiation stores are **single-host durable**.

- Exactly **one authoritative HEVI host** and **one API worker authority**
  may operate against one store volume. A second authority host pointed at
  the same stores **fails closed** (`SplitBrainAuthorityError`).
- The public `deploy/docker-compose-cftunnel.yml` stack runs the API only. A
  worker/scheduler must run on the authoritative host (see
  `hevi/deploy/systemd/hevi-worker.service` / `hevi-scheduler.service`).
  Queued PostgreSQL tasks are not executed without a worker.
- Store paths default under `data/` and may be set explicitly:
  `HEVI_IDENTITY_DB`, `HEVI_INCIDENT_DB`, `HEVI_USAGE_DB`, `HEVI_ENDPOINTS_DB`,
  `HEVI_MEMORY_DB`, `HEVI_AUTHORITY_HOST_ID`.

### Host migration

1. Stop the worker/scheduler and API on **Host A**.
2. Back up the authority set (§5).
3. Restore onto **Host B**.
4. Start **Host B**; it takes over the authority claim.
5. Do **not** start Host A again against the same volume while B holds a fresh
   claim — it is refused.

## 4. Environment variables (key ones)

| Var | Purpose |
|-----|---------|
| `JWT_SECRET` | required auth secret |
| `DATABASE_URL` | PostgreSQL (shared DB) |
| `MINIO_*` | artifact object store |
| `HEVI_ADMIN_USER_IDS` | comma-separated operator allowlist for global admin routes; **empty = deny all** |
| `HEVI_IDENTITY_DB` / `HEVI_INCIDENT_DB` | differentiation authority stores |
| `HEVI_AUTHORITY_HOST_ID` | explicit host identity for the authority claim |
| `FFMPEG_*` / provider keys | provider credentials, per provider docs |

Provider credentials are never stored in the authority stores. Logs are
redaction-filtered; global admin endpoints reject all tenants unless the
caller is in `HEVI_ADMIN_USER_IDS`.

## 5. Backup / restore

```bash
# back up the coordinated authority set (identity + incident) under one token
python scripts/ops/authority_backup.py backup --dest /backups/hevi
python scripts/ops/authority_backup.py verify --manifest /backups/hevi/manifest.json
python scripts/ops/authority_backup.py restore --manifest /backups/hevi/manifest.json --target /restore
```

- Restore the **whole set together**; a partially restored set is refused.
- PostgreSQL + MinIO are backed up by the existing `hevi/deploy/backup/backup.sh`.
- **Rollback:** there is no zero-downtime claim. To roll back a failed upgrade,
  stop services, restore the pre-upgrade backup (DB + authority set), and
  redeploy the previous pinned image. SQLite stores only migrate forward; a
  too-new store refuses to open rather than silently rebuilding.

## 6. Upgrade RC1 → RC2

RC2 is backward compatible with RC1 data:

1. Back up (PostgreSQL, MinIO, authority set).
2. Deploy the RC2 image / install RC2 dependencies.
3. `alembic upgrade head` (PostgreSQL); the SQLite authority stores
   forward-migrate on first open (adds `archived`, `owner_id`, event tables).
4. Re-opening is idempotent; run the operator smoke then resume traffic.

Legacy (RC1) incidents have no owner and are **quarantined** from owner-scoped
lists (safe), not back-filled.

## 7. Product features

- **角色库** — cross-project reuse with pinned versions; explicit upgrade; archive.
- **连续性检查** — PASS / WARN (audited override) / BLOCK before paid generation.
- **制作问题** — auto-recovered / confirm-required (cost + preserved shown) / manual, with a verified timeline.
- **制作状态** — server-derived project health and next action.

## 8. Security boundary

- Identity, continuity, incidents and memory are private to the
  server-derived owner. Cross-owner reads/writes are refused.
- Global (non-tenant) registries are admin-only and fail closed.
- This is application-level tenant isolation, not certified infrastructure
  compliance.

## 9. Known limitations

- **Lip-sync presenter: BLOCKED** (no GPU / ComfyUI / EchoMimic). Not claimed.
- **Local GPU runtime: BLOCKED** (no GPU). Control-plane ready only.
- Creative memory: PARTIAL (API + limited UI).
- Access: DOM/ARIA contract tests only for the new surfaces; no repo-wide
  formal accessibility certification.
- Browser-level E2E requires a Playwright-capable environment (not available
  during this qualification); specs are provided under `hevi-web/e2e/`.
- 3O lint drift is a local `.venv` condition; the canonical 3O architecture
  audit is PASS.

## 10. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| API exits at import | `JWT_SECRET` missing |
| `/api/health/ready` 503 | PostgreSQL unavailable, or authority store unopenable; check `authority_stores` in the response |
| 403 on `/api/authorities/endpoints` | caller not in `HEVI_ADMIN_USER_IDS` (by design) |
| tasks never run | no worker/scheduler on the authoritative host |
| `AUTHORITY_HOST_CONFLICT` at startup | a second host holds the store; migrate or release |
| `..._STORE_SCHEMA_TOO_NEW` | store created by a newer build; do not downgrade blindly |
