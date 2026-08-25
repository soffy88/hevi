# HEVI 生产级闭环状态

本文对照 `Hevi_10分完整架构升级方案_v1.0`，区分“代码与部署闭环”和“已在真实基础设施上验收”。兼容字段或兼容路由仍存在，不代表它们仍是生产事实来源。

## 当前实现

### P0

- Canonical State：生产 API、worker、scheduler 使用 PostgreSQL；`ProductionGraphRepository`、`AutomationRunRepository`、`video_tasks` 分别承载生产、编排运行和任务投影。`_WORKS`、`_RUNS`、`TaskRun` 仅限 local/debug 兼容路径。
- Director：生产图、不可变 revision、stage lock、outbox、关系型 constraints 在同一生产边界内持久化；旧 JSON 只作为快照/兼容投影。产集 `video_provider=auto` 走 Policy Engine，不再硬编码账户级 terminal provider。
- Task truth：生产任务通过 `video_tasks` 排队，完成前必须提交 `ArtifactManifest`；`result_video_path` 仅保留为响应和旧客户端投影。任务状态迁移由统一状态机校验，状态变更、领取和租约恢复与 `domain_events` 同事务写入。
- Attempt/Checkpoint：`task_attempts`、`attempt_checkpoints`、task lease/heartbeat 已接通；过期 attempt 原子地置为 `interrupted` 并重新入队，下一 worker 可从持久化边界接管。复活 worker 不能用过期 `lease_token` 写终态。Tongjian 的 L0-L2 审核态也使用 `paused → queued → worker`，不会由 API 直接执行生产渲染。
- Scheduler：独立 `hevi.scheduler.entrypoint`、leader lease、调度决策审计已接入；生产 worker 只消费 scheduler 标记的任务。
- Runtime separation：API 只提交任务；独立 worker、scheduler、event-publisher 由 compose/systemd entrypoint 运行。

### P1

- Event Bus：事务 outbox、常驻 publisher、每 API 实例独立 consumer cursor、跨实例 WebSocket gateway、重试与 `event_dead_letters` 已接通。发布确认晚于 broker append，故 broker 故障时可重放。
- Constraint Graph：`production_constraints`、`constraint_dependencies`、`constraint_coverage` 已迁移；Director/HyperFrames 统一走 compiler，unsupported 和 silent drop 显式记录，交付前 constraint verdict 阻断 silent drop。
- Artifact Store：PostgreSQL 生产任务完成前必须有 `file://`/`s3://` durable URI、sha256、byte_size；MinIO 是生产实现，local content-addressed store 仅为 local mode。
- Provider Policy：生产任务执行前动态评估 capability、质量下限、候选 provider 和成本上限，并持久化 policy/decision；不满足条件时 fail closed。Fallback 只消费该 snapshot。
- Quality/Repair：GatePolicy、taxonomy、`apply_repair_decision` 执行器已接入标准任务和导演任务边界。

### P2 / 工程门禁

- ADR-001～012 与 RFC-013～015 见 `docs/adr/`。
- CI：`check_runtime_boundaries` + `check_architecture_invariants`。
- DR：`hevi/deploy/backup/{backup,restore,drill}.sh` 支持宿主机客户端或 `POSTGRES_DOCKER` / `MINIO_NETWORK`。
- 负载：`scripts/live_closure_load.py`。
- 一次性签字堆：`hevi/deploy/docker-compose-live.yml` + `scripts/live_env.sh`。

## 2026-08-25 live 签字（hevi-live）

独立 Compose 项目 `hevi-live`（Postgres `127.0.0.1:55432`、MinIO `127.0.0.1:19100`、Redis `127.0.0.1:16379`），Alembic `c0d1e2f3a4b5`，两个 uvicorn 实例 `127.0.0.1:18080` / `18081`。

| 项 | 结果 |
|---|---|
| `HEVI_LIVE_TESTS=1` 全量 live closure | **14 passed**（含过期 lease 接管、双 worker claim、过期 token 无法写终态、checkpoint 可见、production graph 重读、MinIO 篡改拒绝、双 consumer p95、预算 reserve 竞态、质量证据落库、outbox 发布） |
| 崩溃接管 + signed download + raw 过期 | **passed**。4 镜渲染在第 2 镜注入崩溃，第二 worker 从 checkpoint 续跑到 completed；MinIO presign GET 跨进程 200；raw attempt 过期删除后 final 仍可下载。 |
| 4 consumer / 4 读一致性 | **passed**。同一 production revision 四路并发读取一致；8 条事件四路全部收到。 |
| Cinema 约束验证覆盖率 | **passed**。`silent_drops=0`，`verification_rate >= 0.98`。 |
| Scheduler leader 故障切换 | **passed**。A 调度 2 条后租约过期，B 接管并排空剩余积压（5/5 scheduled）。 |
| 成本 P90 估价误差 | **passed**。12 个 settled (estimate, actual) 样本 P90 相对误差 &lt; 20%。 |
| 双 API 实例 WS fan-out | **passed**，20 样本，p95 约束 &lt; 2s（测试 13.26s 内完成） |
| 1k queued / 100 WS | **queue claim passed tasks=1000 unique=1000**；**WS p95=0.574s** |
| DR backup + restore drill | **passed**。PG dump 92K，sentinel 对象恢复到独立 bucket。`RTO_SECONDS=23`（墙钟 34s），远低于 2h。恢复库 `hevi_restore_20260825_133650` 含 `drill-user` production 行；`productions` / `video_tasks` / `artifacts` 三表存在。 |

复跑命令：

```bash
docker compose -f hevi/deploy/docker-compose-live.yml up -d
set -a && source scripts/live_env.sh && set +a
uv run alembic upgrade head
# 两个 API
uv run uvicorn hevi.api.main:app --host 127.0.0.1 --port 18080
uv run uvicorn hevi.api.main:app --host 127.0.0.1 --port 18081
uv run pytest tests/test_live_production_closure.py
uv run python scripts/live_closure_load.py --tasks 1000 --ws 100 --ws-samples 5
POSTGRES_DOCKER=hevi-live-postgres-1 MINIO_NETWORK=hevi-live_default \
  ./hevi/deploy/backup/backup.sh /tmp/hevi-live/backups
POSTGRES_DOCKER=hevi-live-postgres-1 MINIO_NETWORK=hevi-live_default \
  ./hevi/deploy/backup/drill.sh /tmp/hevi-live/backups
```

## 尚未用付费云账号签字的项

崩溃接管走的是与 production 相同的 attempt/checkpoint/artifact 契约，渲染器是本地可恢复 adapter（`checkpoint_render`），不是 Veo/HappyHorse 账单。对象生命周期默认 raw=60 天（30–90 窗口中点）；live 测试把 raw 的 `expires_at` 拨到过去以验证清扫，没有等 60 个自然日。

因此：方案 1–7 与后续三块（接管、signed URL/过期、leader 切换/P90）在 hevi-live 上已经签字。若要把“付费云 provider 被 kill -9 后另一 worker 接着出片”写成运营验收，需要一次真实账单跑数。
