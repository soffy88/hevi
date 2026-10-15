# AGENTOPS R3 独立核验报告（Hark，2026-10-15 04:50–05:10 UTC）

- 对象：worktree /data/soffy/projects/hevi-agentops，分支 feat/agent-ops，HEAD 8922ceb9（DONE AGENTOPS-R3）
- 环境：hevi 主 .venv，JWT_SECRET=testsecret，PYTHONPATH=worktree
- 结论：**FAIL**（F2/F7/F9 目标项已达成，但 R3 引入**回归**：`hevi/api/routers/ops.py` 仍调用已删除的 `store.seed_assets()`，`tests/test_agent_ops_bridge.py` 16 项 ERROR）。未 push。返工单 AGENTOPS_FIX_R4.md。

## R3 目标项：达成

| 项 | 实测 | 结论 |
|---|---|---|
| F2 影子存储移除 | `grep "CREATE TABLE" hevi/operations/` 仅剩 `agent_op_receipts`、`agent_schema_version`；画布走 `InMemoryGraphRepository`、任务走 `InMemoryTaskRepository`、资产走 `InMemorySubjectRepository`（均在 `hevi/operations/in_memory.py`，非 tests/）。我的独立探针 `probe_f2f9.py`：往既有 GraphRepository 写图→`/api/ops/canvas.get` 读回同一张图（revision=0, same_id）；propose 后任务仓储 delta=0，confirm 后 delta=1 且经既有 `TaskRepository.get_task` 读回 | **PASS** |
| F7 ffprobe 裸名 | `env -i HOME=/home/soffy PATH=/usr/bin:/bin` 下 `test_capability_render_2s_product_and_ffprobe_check` 1 passed（用 `resolve_ffprobe_bin()`） | **PASS** |
| F9 重放回执相等 | 我独立探针：同 opId 同参数第二次调用 `replayed=true` 且去掉 `replayed` 后与首次**完全相等**；verify.py 第 2 项 `receipt_equal=true` | **PASS** |

- 独立重跑 `audit/agentops/verify_r3/verify.py`（R1 核验员脚本）：第 1/2/3/4/6 项 `pass_=true`；第 5 项 propose_status=200、delta_propose=0、confirm_status=200、delta_confirm=1、note 不再提影子表。network_attempts=[]（零网络）。
- 单元 C：`tests/test_agent_ops_capability.py` **8 passed**（含 F2 四测、F9 一测）。
- 3O lint：失败 4 项 = 基线（check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only）。

## 阻断：R3 引入的回归（ops 路由调用已删除方法）

- 复现：
  ```
  cd /data/soffy/projects/hevi-agentops
  JWT_SECRET=testsecret TMPDIR=.tmp PYTHONPATH=$PWD \
    /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_agent_ops_bridge.py -q
  ```
- 实际：**16 errors**（`AttributeError: 'SqliteOperationsStore' object has no attribute 'seed_assets'`）。
- 根因：R2 提交 `7e41e679` 里 `hevi/operations/bridge.py` 有 `def seed_assets(...)`（第 280 行），`hevi/api/routers/ops.py` 的 `_seed_assets()` 调用它；R3 为满足 F2「不得有 `_seed_assets` 演示数据」删掉了 `bridge.py` 里的 `seed_assets`，**但漏改了生产文件 `hevi/api/routers/ops.py:50` 的调用**。`tests/test_agent_ops_bridge.py:37` 经 `from hevi.api.routers.ops import _seed_assets` 触发。
- 全量回归（单元 C 相关 8 文件）：**117 passed, 1 skipped, 16 errors, rc=1**（`pytest.log`）。
- 证据：`pytest.log`、`pytest_bridge_errors.txt`、`probe_f2f9.json`、`verify.txt`、`lint.txt`。

## 证据（本目录）
- `REPORT.md`、`verify.py`/`verify.txt`（重跑 R1 核验脚本）、`probe_f2f9.py`/`probe_f2f9.json`（我自写 F2/F9 探针）、`pytest.log`（全量回归）、`lint.txt`

## 判定
F2/F7/F9 三项返工目标本身已达成；但 R3 的 F2 改动删除了 `seed_assets` 却遗留生产调用点，导致既有 `tests/test_agent_ops_bridge.py` 16 项 ERROR——属**阻断回归**，违反「不回归」。**FAIL，不 push**，写 AGENTOPS_FIX_R4.md 并起 R4。
