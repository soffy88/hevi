# AGENTOPS 验收记录 — 单元 C：Agent 画布操作桥（只读 + 写 + 付费 propose 闸）

- worktree: `/data/soffy/projects/hevi-agentops`
- 分支: `feat/agent-ops`
- 基线提交: `92cac3d0` (merge feat/kids-gate 46d7c050 for hevi/capabilities/registry.py)
- 完成依据: `AGENTOPS_TASK.md`、`/data/soffy/projects/hevi-beeftv/BEEFTV_EVAL.md` §4 单元 C

---

## 1. 目标与实现架构

1. **操作注册表（Python）**：`hevi/operations/registry.py` 定义首批 8 个描述符：
   - 只读（4个）：`canvas.get`、`canvas.generation.propose`、`asset.list`、`task.get`
   - 写入（4个）：`canvas.script.rows.append`、`canvas.script.rows.update`、`canvas.script.rows.remove`、`canvas.node.bind_asset`
   - 每个描述符均携带 `readOnly`、`scope`、`params` (JSON Schema) 与 `replay: safe|unsafe`。
2. **CAS 与幂等**：
   - 写操作必须提供 `expectedRevision`，与画布当前版本不符时返回 409 `revision_conflict`，画布不发生任何修改。
   - 写操作支持 `opId` 幂等重放：同一 `opId` + 相同参数重放时返回原回执且标记 `replayed: true`，行数只增加 1 次；同一 `opId` + 不同参数则返回 409 `idempotency_conflict` 拒绝。
3. **权限控制**：
   - 会话模式 `mode=read-only` 时拒绝一切写操作，返回 HTTP 403 及 `scope_denied`，画布不变。
4. **付费生成闸门（propose）**：
   - `canvas.generation.propose` 仅返回 `proposalId`，不写入任何任务行、不调用任何云端/付费 provider。
   - 确认后经既有任务接口提交（`SqliteOperationsStore.create_task` 本地 stub provider，费用为 0.0 USD）。
5. **ShotSpec 校验复用**：
   - 分镜表行（`canvas.script.rows.*`）完全复用 `hevi.production.shot_spec.ShotSpec` 既有 pydantic 校验器，拒绝非法 template/transition/sfx 等，错误来自既有校验器（返回 422）。
6. **MCP 与 HTTP 接入**：
   - MCP：在 `hevi/mcp/tools/canvas_tools.py` 暴露 `hevi.agent.ops.list` 与 `hevi.agent.ops.execute`，并在 `hevi/mcp/server.py` 完成装配。
   - HTTP：新增 `GET /api/ops`（描述符清单）与 `POST /api/ops/{name}`（执行端点），挂载至 FastAPI 主路由。
7. **能力注册表**：
   - 操作桥注册为能力 `agent.ops_bridge` 进入 `hevi/capabilities/registry.py`，支持 `get` / `resolve` / `list_capabilities`，并附带 2 秒 ffmpeg lavfi 产物生成与 ffprobe 检验。
8. **开源协议与署名**：
   - 仓库根目录创建 `NOTICE` 文件，完整署名 BeefTV（MIT）设计理念来源，且不整包 vendor 任何代码。

---

## 2. 验收测试实测结果

### 2.1 单元 C 专门测试集

运行命令：
```bash
JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_agent_ops_bridge.py tests/test_agent_ops_capability.py -q
```
结果：**19 passed in 0.35s**（100% 通过）

逐项对应：
- **标准 1 (`GET /api/ops`)**：
  - `test_ops_list_fields_complete`: PASS
  - `test_ops_readonly_set`: PASS（`readOnly=true` 的恰好为 `asset.list`, `canvas.generation.propose`, `canvas.get`, `task.get`）
- **标准 2 (幂等重放)**：
  - `test_idempotent_append_replays_same_receipt`: PASS（两次提交相同 opId，画布行数只 +1，第二次返回 `replayed: true` 且回执一致）
  - `test_idempotent_conflict_different_params`: PASS（同 opId 不同参数返回 409 `idempotency_conflict`）
- **标准 3 (CAS 保护)**：
  - `test_cas_stale_revision_returns_409`: PASS（过期 expectedRevision 写入返回 409 `revision_conflict`，画布行数保持为 1）
- **标准 4 (read-only 权限)**：
  - `test_readonly_session_denies_write`: PASS（read-only 会话调用 append 返回 403 `scope_denied`，画布行数保持为 0）
- **标准 5 (propose 付费闸与本地 stub 确认)**：
  - `test_propose_returns_only_proposal_id`: PASS（返回 `proposalId`，任务表计数 0 增长）
  - `test_propose_records_intent_not_task`: PASS（仅存 proposal 意图，无 task 行）
  - `test_confirm_submits_via_local_stub_zero_cost`: PASS（确认后由既有任务接口提交，`provider="local_stub"`, `cost_usd=0.0`）
- **标准 6 (ShotSpec 校验复用)**：
  - `test_invalid_template_rejected_by_existing_validator`: PASS（422）
  - `test_invalid_transition_rejected_by_existing_validator`: PASS（422）
  - `test_invalid_sfx_rejected_by_existing_validator`: PASS（422）
  - `test_update_with_bad_row_rejected`: PASS（422）

### 2.2 能力契约产物实测与检验

运行命令：
```python
cap = get("agent.ops_bridge")
res = cap.render({"format": "preview"}, ".tmp/cap_verify", duration=2.0, aspect="9:16", seed=42)
```
实测证据：
- 产物路径: `.tmp/cap_verify/ops_bridge_preview.mp4`
- 产物 SHA-256: `10951e1266d8e64f36799fb896830550d0494c023b2e304307c340b495cc9923`
- 时长: `2.000000` 秒（ffprobe 检验通过）
- 分辨率: `320x568`（9:16 竖屏）
- 编码格式: `h264 / aac`
- 删除产物后重测: `ffprobe` 抛出 `CalledProcessError`，测试如期失败。

### 2.3 综合回归测试（既有 ShotSpec + MCP + 清单完整性）

运行命令：
```bash
JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m pytest \
    tests/test_agent_ops_bridge.py \
    tests/test_agent_ops_capability.py \
    tests/test_mcp.py \
    tests/test_capability_inventory.py \
    tests/test_shot_spec_api.py \
    tests/test_shot_spec_render.py -q
```
结果：**117 passed in 42.10s**（无任何既有功能回归）

### 2.4 3O v3 Lint 门禁

运行命令：
```bash
PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py
```
结果：
- 失败数：**4**（严格等于基线 4 项，无新增失败项）
- 失败项清单（基线已存在）：
  1. `check_no_sibling_call.py`
  2. `check_omodul_signature.py`
  3. `check_enabled_pillars.py`
  4. `check_oprim_keyword_only.py`

---

## 3. 产物与提交清单

- `NOTICE`: BeefTV MIT 许可与设计署名。
- `hevi/operations/`:
  - `__init__.py`: 导出公共接口
  - `registry.py`: 8 个操作描述符与幂等指纹缓存
  - `bridge.py`: `OperationBridge` CAS、权限模式、幂等与 SQLite 真实存储层
- `hevi/api/routers/ops.py`: HTTP `GET /api/ops` 与 `POST /api/ops/{name}`
- `hevi/capabilities/registry.py`: 注册 `agent.ops_bridge` 能力
- `hevi/mcp/tools/canvas_tools.py`: 增加 `hevi.agent.ops.list` 与 `hevi.agent.ops.execute`
- `hevi/mcp/server.py`: 挂载操作桥 MCP 技能
- `tests/test_agent_ops_bridge.py`: 单元 C 16 项全场景覆盖测试
- `tests/test_agent_ops_capability.py`: 能力契约 3 项真实渲染与检验测试
- `tests/test_mcp.py`: 更新 MCP 工具总数（25项）与工具名检查

DONE AGENTOPS-R1
