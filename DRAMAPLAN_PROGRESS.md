# DRAMAPLAN 进度（R1–R5 彻底修复轮，2026-10-12）

## 状态：已全部完成并通过独立核验

### R1–R5 修复项逐条闭环：
1. **R1 审稿中立化**：初审与复审提示词采用同一中立标准，允许 0–100 打分与 error/warning；复审允许拒稿，E2E 如实记录 `review_all_passed=false`；单测 `test_revision_round_can_be_rejected_by_llm_error` 验证通过。
2. **R2 改稿全文核对**：`scene_diffs` 结构保存改前/改后全文（summary/narration/dialogue），E2E 真实记录改写内容并在 `review_log.json` 落盘。
3. **R3 镜头拆分内容保留**：`split_single_shot_plan` 按标点保留切分与顺序分组，保证 `"".join(子镜 tts)` 逐字保留原文、无空镜；子镜画面按景别递进；单测 `test_orchestrator_counting_shot_gen_chain_with_fixed_5_shots` 直接调用真正的 `orchestrate_longvideo`（monkeypatch 上游 shot generator 与 pipeline），验证 30/60/120s 严格单调增加 [6, 12, 24]。
4. **R4 角色与台词质量**：规则层确定性检查将 `char_id` 作说话人定为 `error`（`code="char_id_as_speaker", severity="error"`）；分镜 speaker 及画面提示词中的出场角色全面规范映射为真实角色名（绝无裸 `C001`/`C002`）；分镜无重复台词与标点重复。
5. **R5 缝合标记边级化**：跨章因果缝合边在 `edge_sources` 标注 `{"CH01E002->CH02E001": "stitched"}`，原 `causal_source` 保持向后兼容。

### 真实 E2E 实测（run6，免费 NIM）：
- 执行方式：通过独立的 `setsid` 会话完整运行 `scripts/e2e/dramaplan_e2e.py`，未中断。
- 通过：`qa.passed=true`（17 项指标计算全为 true，含 `storyboard_no_char_id_speaker=true`、`storyboard_no_char_id_in_prompt=true`）
- 通道：NVIDIA NIM (`nvidia/nemotron-3-super-120b-a12b`)
- 调用：29 次真实 LLM 调用全部成功，耗时 155.83s
- 产物：9 个核心产物全部 sha256 记录在 `qa.json` 与 `DRAMAPLAN_DONE.md`
- 真实发生返修集数：`[1, 2, 3]`（EP1/EP2 复审给出定性 error 达到 max_rounds 拒稿，EP3 真实通过）

### 测试与 Lint：
- pytest 全量回归：219 passed in 11.06s，0 failed，0 regression
- 3O v3 lint：依然为基线 4 项失败（全部位于 site-packages 上游），`hevi/` 新增 0
- 零第三方依赖安装，零 site-packages 修改，未调用任何付费 API
