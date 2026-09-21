# Frontend/backend production contract inventory

This inventory is based on the FastAPI routes and OpenAPI served by the
qualification stack. The frontend consumes these endpoints through
`src/lib/api-client.ts`; it does not reproduce lifecycle or artifact policy.

| Authority | Endpoint | Request | Response / nullable fields | Error contract |
| --- | --- | --- | --- | --- |
| Production create | `POST /api/pipeline/productions` | `ProductionRequest`: `source`, `topic`; optional duration, providers, quality, aspect ratio, budget, subjects, presenter, style pack, `options` | task projection; `task_id`, `status`, `production_source`, `percent`; task/config fields may be nullable while queued | `401`; `400` validation/value errors; `402` insufficient credits with `error`, `credits_needed`, available; `422` schema validation |
| Production read | `GET /api/tasks/{task_id}`; `GET /api/tasks` | path UUID; list accepts repeatable backend status filter | canonical `video_tasks` projection, owner-scoped; includes status/progress, config, error, lease/attempt fields when present | `401`, `403` owner mismatch, `404`, `422` invalid UUID |
| Revision read | no standalone revision route in current API | n/a | `revision_id` is read from the owner-scoped task/config and artifact manifest; the UI never creates a revision projection | missing revision remains `—`, never inferred from latest |
| Task lifecycle/checkpoint | `GET /api/tasks/{task_id}/checkpoint`; `GET /api/tasks/{task_id}/progress` SSE; `WS /api/ws/tasks` | UUID; SSE JWT query token; WS `subscribe` / `ping` | checkpoint has `attempt_id`, `attempt_no`, `attempt_status`, stage, progress, durable state and manifest; WS `task_update` has task id, backend status and progress | `401`, `404`, `422`; WS reconnects without creating a task |
| Artifact read | `GET /api/authorities/tasks/{task_id}/presentation`; `GET /api/authorities/tasks/{task_id}/currency`; media `GET /api/tasks/{task_id}/video[-url]`, `/audio`, `/cover`, `/export` | owner-scoped task UUID; media token query required | presentation/currency are authority projections; manifest carries artifact id, kind, media type, revision, hash, parents; currency returns evaluations, usable, total | `401`, `404` absent task/manifest, `409` not materializable/not committed, `422` invalid UUID |
| Quality evidence | `task.config_json.quality_evaluation` in canonical task/artifact projection | no frontend threshold input | backend measurements/policy/decision are displayed as evidence; frontend does not compute PASS/WARN/BLOCK | same task/artifact read errors |
| RepairIncident | `GET /api/incidents?production_run_id={id}&product=true`; detail/timeline and explicit action routes | owner-scoped production id; action request schemas are backend-owned | product view has incident id, failure code, diagnosis, status, policy, attempts, verification; timeline has event sequence | `401`, `404` owner/not found, `409` ownership/action conflict, `422` invalid repair action |
| Capability catalog | `GET /api/pipeline/capabilities` | none beyond auth | `capabilities[]`: id, name, routes, available, interface/execution/quality/production readiness, provider readiness, message/setup | `401`; provider-unavailable remains a backend catalog value |
| Health | `GET /api/health/live`; `GET /api/health/ready` | none | live is process liveness; ready is `200` with `status=ready`, or `503` with database/Redis/MinIO/worker heartbeat/scheduler evidence | network failure is offline; readiness `503` is degraded/unavailable, never healthy |

Canonical task statuses recognized by the frontend are exactly:
`pending`, `queued`, `claimed`, `running`, `completed`, `failed`,
`blocked`, `cancelled`, `paused`, and `interrupted`. An unknown status is rendered as
`未知状态（已阻断）`; it is never translated to `succeeded` or `completed`.
