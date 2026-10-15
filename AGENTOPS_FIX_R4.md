# AGENTOPS_FIX_R4 — R3 核验失败，R4 修复单（完成标志：AGENTOPS_DONE.md 最后一行 `DONE AGENTOPS-R4`）

R3 独立核验（Hark，`audit/agentops/verify_r3/REPORT.md`）结论：F2/F7/F9 三项返工目标本身**已达成**，但 R3 的 F2 改动引入**回归**，且未跑全量既有测试就报 DONE。判定 FAIL。

## 已达成，不要回退
- F2 影子表已删除：`grep "CREATE TABLE" hevi/operations/` 只剩 `agent_op_receipts`、`agent_schema_version`；画布/任务/资产分别走 `hevi/operations/in_memory.py` 的 `InMemoryGraphRepository` / `InMemoryTaskRepository` / `InMemorySubjectRepository`。
- F7 ffprobe：受限 PATH（`env -i HOME=/home/soffy PATH=/usr/bin:/bin`）下 `test_capability_render_2s_product_and_ffprobe_check` 通过。
- F9 重放回执相等：同 opId 同参数第二次 `replayed=true` 且去掉 `replayed` 后与首次完全相等。
- 以上均由核验员独立探针复现（`probe_f2f9.json`），**修复时不得回退**。

## 阻断项（必须修）

### G1. R3 删除 `seed_assets` 但遗留生产调用点，导致既有测试 16 项 ERROR
- 复现：
  ```
  cd /data/soffy/projects/hevi-agentops
  JWT_SECRET=testsecret TMPDIR=.tmp PYTHONPATH=$PWD \
    /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_agent_ops_bridge.py -q
  ```
- 实际：**16 errors**，`AttributeError: 'SqliteOperationsStore' object has no attribute 'seed_assets'`。
- 根因：R2（`7e41e679`）时 `hevi/operations/bridge.py` 有 `def seed_assets(...)`（第 280 行），`hevi/api/routers/ops.py:48 _seed_assets()` 调用它，`tests/test_agent_ops_bridge.py:37` 通过 `from hevi.api.routers.ops import _get_store, _seed_assets` 使用。R3 为满足 F2「禁止 `_seed_assets` 演示数据」删掉了 `bridge.py` 的 `seed_assets`，**但漏改生产文件 `hevi/api/routers/ops.py`**。
- 期望：`hevi/api/routers/ops.py` 不得再调用不存在的 `store.seed_assets`。修法二选一，且必须保持既有测试与 F2 约束同时成立：
  1. 删除 `_seed_assets` 及其调用，并把 `tests/test_agent_ops_bridge.py` 里对 `_seed_assets` 的依赖改为经既有 `InMemorySubjectRepository`（`hevi/operations/in_memory.py`）写入/读取资产；或
  2. 让 `_seed_assets` 改为经既有 SubjectRepository 写入（不再有「演示数据」语义，改为正式资产写入），并保留测试可用。
- 必须新增测试：`test_asset_list_reads_existing_subject_repository`（往既有 `InMemorySubjectRepository` 写资产，经 `/api/ops/asset.list` 或 `store.list_assets` 读回同一批），确保无 `_seed_assets` 也能 list。
- **必须跑全量既有测试并全绿**（这是 R3 漏做的一步）：
  ```
  JWT_SECRET=testsecret TMPDIR=.tmp PYTHONPATH=$PWD \
    /data/soffy/projects/hevi/.venv/bin/python -m pytest \
    tests/test_agent_ops_bridge.py tests/test_agent_ops_capability.py \
    tests/test_mcp.py tests/test_shot_spec_api.py tests/test_shot_spec_render.py \
    tests/test_openshorts_integration_gates.py tests/test_capability_inventory.py \
    tests/test_capability_truthfulness.py -q
  ```
  期望：**0 error、0 failed**（R3 实测 117 passed / 16 errors）。

## 自测（DONE 前必须全过，写进 DONE 真实输出）
1. 上面全量 pytest：0 error、0 failed。
2. `JWT_SECRET=testsecret PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python audit/agentops/verify_r1/verify.py`：第 2、5 项 `pass_=true`。
3. 受限 PATH：`env -i HOME=/home/soffy PATH=/usr/bin:/bin JWT_SECRET=testsecret PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_agent_ops_capability.py -q` 全绿。
4. `PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py`：失败数 = 基线 4 项。
5. `grep -rn "seed_assets" hevi/` 不得再出现对不存在方法的调用（要么没有，要么方法真实存在）。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-agentops；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 AGENTOPS_DONE.md 最后一行写 `DONE AGENTOPS-R4`。
