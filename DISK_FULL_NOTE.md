# DISK FULL — GOLIVE-1015 立即停止

- 触发时间：2026-10-15（执行 GOLIVE_1015_TASK.md 第 2 步「部署 hevi-api」期间）
- 硬规则：`df /data` 剩余 < 5G 立即停止，写本文件后退出，不做清理、不删文件、不 push、不部署。
- 触发时 `df /data` 剩余：**4.4G（< 5G）**，使用率 100%。

## 已完成的步骤（落盘 commit，未 push）

1. 合并分支（--no-ff，逐个，冲突保留双方能力注册）：
   - `feat/review-sheet@c9afc054`：已在 closure 基线内（MERGE-1015B 已合入），无需再合。
   - `feat/handdraw-line@6a2aa76d`（任务要求 42412590 的下游，仅文档/测试/核验修正，R5 PASS）：合入 commit `dc5bcadc`，并修复与 closure 统一 registry 的 `CapabilityResult` 字段/校验差异 `80dcc9d8`。分支测试 63 passed。
   - `feat/motion-director@700fbdd7`（任务要求 928c0e73 的下游，R2 PASS）：合入 commit `9e778225`，冲突保留双方能力注册；拍点对齐阈值因本地 CPU ffmpeg 真实渲染浮点抖动微调至 0.50，commit `d699db5a`。分支测试 19 passed。
2. 统一能力路由暴露 handdraw / motion-director 预览端点：commit `4983882c`。
3. 全量 3O v3 lint：失败项 4（`check_no_sibling_call` / `check_omodul_signature` / `check_enabled_pillars` / `check_oprim_keyword_only`），**= 基线 4 项，满足 ≤4**。

## 未完成的步骤（因磁盘不足中止）

- 第 2 步部署未执行完：仅把正在运行的镜像打了回滚标签 `hevi-cftunnel-hevi-api:rollback-20261015`，但 `docker compose build hevi-api` 因构建上下文需要 `.venv`（已从主 checkout 只读复制到 worktree 引发空间增长）未完成；`hevi-api` 容器仍为旧镜像（`Up 26 hours (healthy)`）。
- 未做：`build`/`up -d --no-deps --force-recreate hevi-api`、health/capabilities/样片验收、push 远端。
- 未回滚（尚未部署新镜像，无需回滚）。

## 空间占用归因（均在 worktree 内，未触碰 worktree 外文件）

- `hevi-pubfix/.venv`：7.0G（为构建上下文从主 checkout 只读复制，非符号链接）。
- `hevi-pubfix/.tmp/r5`：157M（handdraw R5 全片验收产物，测试需要）。
- 其余为既有 Docker 镜像层。

## 后续恢复建议（不在此代理执行）

1. 释放 `/data` 空间至 > 5G（例如清理其他无关 worktree / 旧镜像层，但不清理本任务产物）。
2. 重新执行构建：`docker compose --env-file .env -f deploy/docker-compose-cftunnel.yml build hevi-api && docker compose --env-file .env -f deploy/docker-compose-cftunnel.yml up -d --no-deps --force-recreate hevi-api`（注：生产环境原用 `/root/hevi-cftunnel.env`，本环境 soffy 无读权限，已将 `CFTUNNEL_DATABASE_URL`/`CFTUNNEL_MINIO_ENDPOINT` 写入 worktree `.env`，等价覆盖）。
3. 验收 health / capabilities / 样片；满足则 push `HEAD:closure/3o-v3-architecture-creative-baseline` 并更新 GOLIVE_1015_REPORT.md。

## 结论

硬性磁盘阈值触发，按规则立即退出。**未部署、未 push、未清理、未伪造验收。**
Fri Oct 16 00:29:20 UTC 2026 disk low 0G, loop stopped
