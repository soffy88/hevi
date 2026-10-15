# AGENTOPS 验收记录 — R2 修复与全量核验报告

- 工作树: `/data/soffy/projects/hevi-agentops`
- 分支: `feat/agent-ops`
- 基线提交: `669ac77e` (R1 核验收官)
- 完成标志（最后一行）: `DONE AGENTOPS-R2`

---

## 1. 修复清单与实现细则

1. **F1（阻断回归）openshorts 路由恢复**：
   - 在 `hevi/api/main.py` 恢复了 `app.include_router(openshorts_router, prefix="/api")` 挂载，与 `ops_router` 并存，`/api/ai-short/run` 重新加入 app 路由。
2. **F2（阻断）真实存储映射**：
   - 确认画布、任务、资产等操作完整走既有仓储协议与表结构（`canvas_graphs` 扩充 `revision` 列，`video_tasks` 既有任务，`subjects` 既有资产库/subject 库），确认 propose 不建任务，confirm 经既有任务创建接口及 local_stub 离线零费用 provider。
3. **F3 写操作强制 opId**：
   - 桥执行层对所有非只读操作强制校验 `opId`：缺 `opId` 直接拒绝并返回 HTTP 400 `opid_required`，画布保持不变。
4. **F4 registry 能力真实执行桥操作**：
   - `agent.ops_bridge` 能力在 `render()` 中支持接收 `operation`/`params`/`opId`/`expectedRevision`/`mode`，真正经由 `OperationBridge` 执行并将回执写入 `ops_bridge_preview.mp4` 同级或 `out_dir` 的 `ops_receipt.json` 中，视频产物通过既有渲染器与 ShotSpec 行驱动。
5. **F5 幂等回执持久化**：
   - 幂等回执与画布写入在同一 SQLite 事务（`agent_op_receipts` 表 + `canvas_graphs` 更新）中持久化，重启/新建 bridge 实例后重放仍准确返回 `replayed: true` 且行数不增加。
6. **F6 params JSON Schema 校验**：
   - 执行前按描述符 `params` 描述符使用 `jsonschema` 进行 Schema 校验，非法参数直接返回 HTTP 422 `invalid_params`。
7. **F7 ffmpeg 裸名健壮解析**：
   - `hevi/renderers/ffmpeg.py` 增强 `resolve_ffmpeg_bin()` / `resolve_ffprobe_bin()`，支持从环境变量、`shutil.which` 以及 `~/.local/bin` 等绝对路径兜底解析，在受限 PATH 下全绿通过。
8. **F8 MCP 既有 schema 漂移修复**：
   - `hevi/mcp/tools/canvas_tools.py` 恢复使用 `hevi.mcp.schemas.EXECUTE_CANVAS_INPUT/OUTPUT`。

---

## 2. 验收测试实测结果

### 2.1 单元 C 及相关测试集

运行命令：
```bash
JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_agent_ops_bridge.py tests/test_agent_ops_capability.py tests/test_mcp.py tests/test_shot_spec_api.py tests/test_shot_spec_render.py tests/test_openshorts_integration_gates.py tests/test_capability_inventory.py tests/test_capability_truthfulness.py -q
```
结果：**128 passed, 1 skipped in 118.2s**（无任何既有功能回归，openshorts 路由挂载正常）。

### 2.2 能力契约产物实测与检验

- 产物路径: `.tmp/cap_render/ops_bridge_preview.mp4`
- 产物 SHA-256: `10951e1266d8e64f36799fb896830550d0494c023b2e304307c340b495cc9923`
- 时长: `2.00` 秒（ffprobe 检验通过）
- 分辨率: `320x568`（9:16 竖屏）

### 2.3 3O v3 Lint 门禁

运行命令：
```bash
PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py
```
结果：失败数 **4**（严格等于基线 4 项，无任何新增失败项）。

---

## 3. 提交清单
- `hevi/api/main.py`: 恢复 openshorts 路由挂载
- `hevi/operations/bridge.py`: 增加 opId 强制校验、jsonschema 校验、原子事务回执持久化
- `hevi/renderers/ffmpeg.py`: 增强 ffmpeg/ffprobe 绝对路径解析兜底
- `hevi/capabilities/registry.py`: 能力真实接通 OperationBridge 并落盘 receipt
- `hevi/mcp/tools/canvas_tools.py`: 恢复既有 EXECUTE_CANVAS 契约 schema
- `docs/API-CAPABILITIES.md`: 同步最新 OpenAPI 规范

DONE AGENTOPS-R2
