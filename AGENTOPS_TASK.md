# AGENTOPS_TASK — 单元 C：Agent 画布操作桥（只读 + 写 + 付费 propose 闸）

- worktree：`/data/soffy/projects/hevi-agentops`，分支 `feat/agent-ops`
- 基线：ShotSpec 已通过提交 `8b2588b2`（feat/shot-spec），已合并 `feat/kids-gate` `46d7c050`（提供 `hevi/capabilities/registry.py`）→ 当前起点 `92cac3d0`
- 依据：`/data/soffy/projects/hevi-beeftv/BEEFTV_EVAL.md` 第 4 节「单元 C」（以及 1.8 节 31 个描述符、第 5 节风险边界）。先完整读。
- 完成文件：`AGENTOPS_DONE.md`；完成标志（最后一行）：`DONE AGENTOPS-R1`

## 目标
1. 新增 `hevi/operations/` 操作注册表（Python），首批 8 个描述符：`canvas.get`、`canvas.script.rows.append`、`canvas.script.rows.update`、`canvas.script.rows.remove`、`canvas.node.bind_asset`、`canvas.generation.propose`、`asset.list`、`task.get`。每个描述符含 `readOnly`、`scope`、`params`（JSON Schema）、`replay: safe|unsafe`。
2. 写操作要求 `expectedRevision`（CAS，不匹配返回 409 且不修改）与 `opId`（幂等：同 opId+同参数重放返回首次回执且 `replayed: true`；同 opId 不同参数应拒绝）。
3. `read-only` 会话/模式拒绝一切写操作，返回 `scope_denied`。
4. `canvas.generation.propose` 只返回 `proposalId`：不建任何生成任务、不调任何 provider；确认后由既有任务接口提交（用本地 stub provider 验证可提交，零费用；stub 仅限这一条"可提交"验证，不得用于让其它验收通过）。
5. `canvas.script.rows.*` 的行内容（ShotSpec）校验**复用现有 pydantic 校验器** `hevi/production/shot_spec.py`，不新造第二套规则。
6. 经 `hevi/mcp/tools/canvas_tools.py` 暴露给 MCP，并新增 HTTP `GET /api/ops`（描述符列表）与执行端点（如 `POST /api/ops/{name}`）。
7. 操作桥注册为能力进 `hevi/capabilities/registry.py`。
8. 借鉴 BeefTV（MIT）设计须在仓库根 `NOTICE` 署名，不 vendor 其代码。

## 可测验收标准
1. `GET /api/ops` 返回 8 个描述符且字段齐全；`readOnly=true` 的恰好是 `canvas.get`/`canvas.generation.propose`/`asset.list`/`task.get`。
2. 幂等：同一 `opId`+同参数重放两次，画布行数只 +1，第二次返回 `replayed: true` 且回执与首次相同。
3. CAS：过期 `expectedRevision` 写入返回 409，画布未被修改。
4. 权限：read-only 会话调用 `canvas.script.rows.append` 返回 `scope_denied`，画布不变。
5. 付费闸：`canvas.generation.propose` 只返回 `proposalId`，断言任务表无新行、无 provider 调用；确认后经既有任务接口可提交（本地 stub provider）。
6. 非法 ShotSpec 行（未知 template/transition/sfx 等）经 rows.append/update 被拒，错误来自既有校验器。
7. 全部测试 CPU-only 跑通、无网络出站（真实 FastAPI TestClient + 真实 DB/存储层，不 mock 业务层）；既有 shot_spec 测试不回归；3O lint 失败数 ≤4。

## 硬规则（必须遵守，违反即视为未完成）

1. **方向与契约**：开工前完整阅读本 worktree 根目录的 `KIDS_ANIME_DIRECTION.md`（Hevi 幼儿动漫方向）和 `CAPABILITY_CONTRACT.md`（能力契约）并遵守。本单元新增的每项能力都必须注册进 `hevi/capabilities/registry.py`，可被所有产线通过 registry 调用（`get/resolve`），并有测试证明可从 registry 调起。
2. **只在本 worktree 内工作**：不得修改主 checkout `/data/soffy/projects/hevi` 或任何其它 worktree；临时文件一律放本 worktree 的 `.tmp/`（并确保 `.tmp/` 不被提交）。
3. **CPU-only**：不调用任何付费 API / 远程 provider，不联网下载大模型；测试无网络出站。
4. **绝不删除 worktree 外的任何东西**；绝不"清理磁盘"，不删 node_modules、缓存、模型、其它项目文件。`df /data` 剩余 <5G 时写 `DISK_FULL_NOTE.md` 并立即停止。
5. **内存紧张**（整机 30G、多任务并行）：渲染与重测试单进程跑（pytest 不开 -n，ffmpeg 单路）；长任务用 `nohup setsid ... &` 启动并轮询到完成，产物完成前不得结束会话。
6. **禁止 mock / 占位 / 硬编码通过**：测试必须真跑真实代码路径和真实 ffmpeg/PIL 产物。pytest 以 soffy 身份运行：
   `JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m pytest <tests> -q`
7. **3O lint**：`PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py`，失败数不得超过基线 4（基线 4 项：check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），不得新增失败项。lint 日志不要提交进仓库。
8. **许可**：Renoise 仓库无 LICENSE —— 只吸收方法论，不复制其原文或代码。BeefTV 为 MIT —— 借鉴的设计/代码须在仓库根 `NOTICE` 中署名，不得整包 vendor。
9. **git**：阶段性 commit，只 `git add` 自己创建/修改的文件（不要 `git add -A`）。不 push、不合并到其它分支、不改写历史。不要询问，直接执行到底。
10. **完成**：写 `AGENTOPS_DONE.md`，如实记录每条验收标准的实测结果（命令、通过/失败数、SHA-256、产物路径），未达成的如实写明；最后一行写完成标志，然后 commit。
