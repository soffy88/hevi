# AGENTOPS_FIX — R1 核验失败，R2 修复单（完成标志：AGENTOPS_DONE.md 最后一行 `DONE AGENTOPS-R2`）

依据：AGENTOPS_TASK.md + 核验报告 audit/agentops/verify_r1/REPORT.md（requests.json / results.json）。
核验命令（每项修复后自测必须全部通过）：
```
cd /data/soffy/projects/hevi-agentops
JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python audit/agentops/verify_r1/verify.py
JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_agent_ops_bridge.py tests/test_agent_ops_capability.py tests/test_mcp.py tests/test_shot_spec_api.py tests/test_shot_spec_render.py tests/test_openshorts_integration_gates.py tests/test_capability_inventory.py tests/test_capability_truthfulness.py -q
PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py   # 失败数 ≤ 4，日志不提交
```

## F1（阻断回归）openshorts 路由被卸载
- 复现：`python -c "from hevi.api.main import app; print('/api/ai-short/run' in {r.path for r in app.routes})"` → 实际 False，期望 True。
- 原因：hevi/api/main.py 用 `app.include_router(ops_router)` 替换了 `app.include_router(openshorts_router, prefix="/api")`。
- 修：恢复 openshorts_router 挂载，另起一行挂 ops_router。
- 必须新增测试：`test_main_mounts_openshorts_and_ops`（断言 `/api/ai-short/run` 与 `/api/ops` 均在 app.routes）。

## F2（阻断）影子存储冒充真实路径
- 实际：canvas.* 读写新建 SQLite 表 `agent_graphs`；task.get 读 / confirm 写新表 `agent_tasks`；asset.list 读 `_seed_assets` 演示数据。这些不是 Hevi 既有画布/任务/资产。
- 期望：
  - canvas.get / rows.* / bind_asset 操作 **既有画布**（hevi/canvas/graph_repository.GraphRepository / GraphService 的 graph 及其 script 节点），revision 存在既有 graph 记录上（如需新增列，按既有 alembic 迁移惯例加，并提供 SQLite/内存实现走同一 Repository 协议供离线测试——同一套业务代码，不得另起业务表）。
  - task.get 读 **既有任务**（hevi/tasks/repository.TaskRepository.get_task）。
  - propose 后"任务表无新行"断言针对 **既有 tasks 表**；confirm 必须经 **既有任务创建接口**（TaskRepository.create_task / 既有 POST /api/tasks 路径，使用其 idempotency_key 机制），provider 指定为本地 stub/离线 provider（如 hevi/providers/local_qwen_adapter.py 或既有离线 stub），零费用。
  - asset.list 读既有资产/subject 库（hevi/subjects 或既有 asset 仓储），不得用硬编码演示数据。
  - 离线测试可用 PG 不可用时的既有 fallback/内存仓储，但必须是 Repository 的正式实现，不得只为测试造平行表。
- 必须新增测试：`test_ops_canvas_get_reads_existing_graph_repository`、`test_propose_no_row_in_existing_tasks_table`、`test_confirm_creates_task_via_existing_task_repository_local_stub`（断言 TaskRepository 中可读回、provider=本地 stub、无付费 provider 调用计数）、`test_asset_list_reads_existing_asset_store`。

## F3 写操作未强制 opId
- 复现：POST /api/ops/canvas.script.rows.append body 只有 params+expectedRevision（无 opId）→ 实际 200 且行数 +1；期望 400 `opid_required`，画布不变。
- 必须新增测试：`test_write_without_opid_rejected`（四个写操作各一例）。

## F4 registry 能力是占位产物
- 实际：`agent.ops_bridge` 的 render 只生成靛蓝纯色视频，不执行任何 op。
- 期望：能力可经 registry 真正调用操作桥（例如 params 含 `operation`/`params`/`opId`/`expectedRevision`/`mode`，render/execute 走 OperationBridge 并把回执写入 out_dir 的 JSON；如契约要求视频产物，产物必须由该操作结果驱动，例如把画布 ShotSpec 行经既有渲染器渲染），并保留 schema 校验。
- 必须新增测试：`test_registry_resolve_executes_rows_append`（经 registry.resolve 调用后画布行数 +1、回执与 HTTP 一致）、`test_registry_readonly_mode_scope_denied`。

## F5 幂等回执仅进程内存
- 期望：回执与写入同一事务持久化到存储层（opId、参数指纹、回执、op 名），重启后重放仍返回 replayed:true。
- 必须新增测试：`test_idempotency_survives_new_bridge_instance`（新建 store/bridge 实例、清进程缓存后重放仍 replayed:true，行数不再增加）。

## F6 params JSON Schema 未执行校验
- 期望：execute 前按描述符 params 校验（jsonschema 或既有校验工具），不合法 422 `invalid_params`；ShotSpec 字段规则仍只由 hevi.production.shot_spec 负责。
- 必须新增测试：`test_params_schema_enforced`（缺 graph_id、row 带未声明字段）。

## F7 ffmpeg 裸名
- 实际：规定 pytest 命令（sudo -u soffy env …）下 PATH 无 ~/.local/bin，test_capability_render_2s_product_and_ffprobe_check 失败。
- 期望：复用 hevi/renderers/ffmpeg.py 的 FFMPEG_BIN 解析（ffprobe 同理），规定命令下全绿。

## F8 MCP 既有 schema 漂移
- 期望：hevi.execute_canvas 继续使用 hevi.mcp.schemas.EXECUTE_CANVAS_INPUT/OUTPUT，不改既有契约。test_mcp 全过。

## 其它
- AGENTOPS_DONE.md 如实重写 R2 实测（命令、通过/失败数、证据路径），不得照抄 R1 结论。
- 只 git add 自己改的文件；不提交 .tmp/、pi_*.jsonl、*.err、lint 日志；不 push。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-agentops；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 AGENTOPS_DONE.md 最后一行写 DONE AGENTOPS-R2。
