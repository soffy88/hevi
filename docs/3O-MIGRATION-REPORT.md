# Hevi 3O 范式迁移实施报告 (Implementation Report)

> 版本: v1.0 | 日期: 2026-08-02 | 目标: 全量符合 3O Paradigm SPEC v3.0
> 基线: Phase 0 全量测试 1274 passed（含 WIP 修复后）/ 终态 **1301 passed, 0 failed**

## 0. 最终状态

| 验证项 | 结果 |
|--------|------|
| 全量 pytest | **1301 passed, 0 failed**（Phase 1→4 每阶段均执行回归） |
| 3O CI 检查（§6.1 三件套） | `check_no_sibling_call` / `check_omodul_signature` / `check_enabled_pillars` **全部通过** |
| 新增/修改文件 ruff + mypy | 全绿（剩余 72 个 ruff 错误均为未触碰的历史 WIP 文件） |
| 能力回退验证集（§6.2） | 主线 / 短剧 / 通鉴 L0-L8 / 音频 / 装配 216 项门禁 **全部通过** |

---

## 1. Phase 1 — 基础设施沉淀与死代码清理 ✅

- **Task 1.1 死代码清理**: 删除 20 个空壳目录（`livestream/` + 19 个仅剩 pycache 的幽灵模块：agent, agent_runtime, ai_models, analysis, blocks, design, enhancement, job_queue, media, memory, n0, preparation, prompts, publisher, qnlr, scripts, services, skills, utils）。65→45 个有效模块目录。
- **API 契约隔离**: `/livestream/*` 4 端点确认由 `DuixLiveService`（digital_human）支撑，503 占位与死模块已解耦，无需改动。
- **Task 1.2 验证**: Provider 注册中心（`providers/registry.py` 注册 20+ provider）与成本下沉（`cost/estimator.py` 已真下沉 `obase.CostTracker.estimate_steps`）**迁移前已满足**，本次确认为"验证型"任务。
- **WIP 同步**: 修复 4 个测试的旧边界 mock（`orchestrate_longvideo` → `execute_standard_operation`，对齐已迁移的 oservi 标准操作路径）。

## 2. Phase 2 — 原子/算法抽取与核心 Patch 消除 ✅

- **Task 2.1 消除侵入式 Patch**（`longvideo_orchestrator.py`）:
  - 确认 **oskill 4.5.0 已上游修复 B7 bug**（`storyboard_planner` 对 `list[dict]` scenes 不再无条件 `model_dump()`）→ **物理删除 `ScriptWrapper` 代理类与 `patched_storyboard_fn`**（共约 90 行）。
  - 新增纯算法 `hevi/pipeline/storyboard_locked_override.py::apply_locked_storyboard_override`（SPEC §2 签名，stateless，目标上游至 `oskill.storyboard_locked_override`），取代运行期 `_providers_script_fn`/`_providers_storyboard_fn` 条件替换。
  - 锁定路径仅剩 omodul 原生 providers 钩子的**薄适配器**（omodul 文档化的注入机制）。
  - 补 4 个纯函数单测 + 既有集成测试全绿。
- **Task 2.2 TTS 原子抽取**:
  - 新增 `scripts/patch_oprim_prims.py`（沿用 patch_vibevoice.py 模式）注入 3 个 oprim 原子：`edge_tts_word_boundary` / `probe_duration` / `vibevoice_tts_call`（后者保留子进程显存隔离，懒加载委托 hevi/audio/tts_service）。
  - **消除 3 处自写 edge-tts**（explainer/voiceover.py、audio/edge_tts_custom.py 逐行合成、其余 ffprobe 探测点）→ 统一走 oprim 原子；`assembler.probe_duration`/`tongjian._get_audio_duration_ms` 收敛至 `oprim.probe_duration`。
  - Dockerfile 接入 `python scripts/patch_oprim_prims.py`。

## 3. Phase 3 — 素材与数字人能力域收拢 ✅

- **Task 3.1 sourcing 重组**: `hevi/stock/` + `hevi/assets/` → **`hevi/sourcing/`**（`stock_search.py` / `loader_bridge.py` / `match_score.py`），对外符号完全兼容（API 与测试已迁移，旧目录物理删除）。实现 `calculate_stock_match_score`（oskill 边界纯算法，文本 n-gram 语义 + StylePack 关键词加权）。
- **Task 3.2 digital_human 收拢**:
  - `hevi/digital_human/` 补全为 4 模块：`models.py`（Presenter 迁入，presenters 保留 shim）、`duix_service.py`、**`avatar_render.py`**（通用 Scale/Crop/FPS 过滤链、concat、抽帧、一致性打分自 `tongjian/scene_render_avatar.py` 抽离，8 个私有函数转为薄转发）、`lipsync_driver.py`（oskill 边界能力感知驱动，诚实标记后处理未实现）。
  - 通鉴通道通过标准配置参数调用该服务，保留水墨/卡通风格切换（1173 行文件瘦身约 130 行）。

## 4. Phase 4 — 业务事务标准化与编排层重构 ✅

- **Task 5.1 装配收敛**:
  - 新增 `hevi/assembly/video_assemble_workflow.py`：标准三件套签名 `(config, input_data, output_dir, *, on_step=None) -> dict`，显式 `_enabled_pillars = {"report", "cost", "decision_trail"}`，失败不 raise，落盘 `assemble_report.json`（含 decision_trail）。目标上游至 `omodul.video_assemble_workflow`。
  - `tongjian/assemble.py::build_final_video` 改为构造 `AssembleConfig/AssembleInput` 调用 workflow；**删除内部 92 行 FFmpeg 拼接**（`_xfade_concat_clips`/`_ffprobe_dur_sync`），avatar 音频保真装配收敛为 `assembler.assemble_talking_clips` 单源。
- **Task 5.2 oservi 编排接入**:
  - 新增 `hevi/pipeline/longvideo_manifest.py`：`longvideo_production_manifest`（`ServiceManifest(name="longvideo_production", skeleton="sequential_composer", trigger={"mode": "on_demand"})`）+ `run_longvideo_composer` 引擎入口。SPEC 三件套步骤分解注明为上游 omodul 目标（当前 omodul 以 `longvideo_produce` 端到端承载）。
  - **Layer 4 PII 脱敏**: 新增 `hevi/core/anon.py`（`anon_user_ref` sha256(salt:user_id)[:24] + `sanitize_input_data` 剔除身份键），manifest 配置仅含伪名；测试验证 user_id/student_id/email 不入 3O 侧。

## 5. §6 CI/CD 与回归验证 ✅

- 3 个 CI 检查脚本落地并接入 `.github/workflows/ci.yml`：
  - `scripts/ci/check_no_sibling_call.py` — 3O 边界目录（assembly/digital_human/production）无 oprim+omodul 裸调同级
  - `scripts/ci/check_omodul_signature.py` — 所有 `*_workflow` 符合三件套签名 + status 返回（失败不 raise）
  - `scripts/ci/check_enabled_pillars.py` — 所有 omodul 显式声明 `_enabled_pillars`
- 新增测试 8 个文件 40+ 用例：`test_storyboard_locked_override` / `test_oprim_prims` / `test_match_score` / `test_digital_human` / `test_video_assemble_workflow` / 更新 `test_edge_tts_custom` / `test_explainer_voiceover` / `test_cost` / `test_credits` / `test_resilience`。

---

## 6. 待上游（需在 3O 主库仓库合入后随 `uv sync` 生效）

| 项 | 位置（Hevi 暂驻） | 目标 |
|----|-------------------|------|
| `apply_locked_storyboard_override` | `hevi/pipeline/storyboard_locked_override.py` | `oskill.storyboard_locked_override` |
| `edge_tts_word_boundary` / `probe_duration` / `vibevoice_tts_call` | `scripts/patch_oprim_prims.py`（site-packages 注入） | `oprim` 上游合入后删除补丁 |
| `video_assemble_workflow` | `hevi/assembly/video_assemble_workflow.py` | `omodul.video_assemble_workflow` |
| `longvideo_production_manifest` 三件套步骤 | `hevi/pipeline/longvideo_manifest.py` | omodul 提供 script_to_storyboard/shot_generation workflow 后替换 |

## 7. 遗留说明

- `tests/test_queue.py::test_claim_is_atomic_no_double_dequeue` 出现一次时序 flake（单测复跑通过，非本迁移引入）。
- 仓库现存 72 个 ruff 错误（`hevi/api/main.py`、`scripts/*` 等）为迁移前历史 WIP 债，本迁移新增/修改文件已全绿，未触碰历史代码。
