# G0.3 文件级成本评估（正式稿）

- **日期**: 2026-10-02 · **方法**: 只读测绘（子代理核实 + file:line），未改生产代码
- **量级定义**: S ≤3 文件 + 单测；M = 跨模块 + 契约变更 + 回归面；L = 新子系统/存储语义
- **判断声明**: Owner 与量级属工程判断，实施时可推翻

## A3 ScriptUnit 生产化 — M

| 文件 | 动作 |
|------|------|
| `hevi/director/screenplay.py:53` `_SCREENPLAY_PROMPT` | 约束 LLM 输出 `unit_id`（或声明由后处理分配） |
| `hevi/director/screenplay.py:148-177` `_call_llm_json` + `generate_screenplay_draft` | 解析 `unit_id` 并校验 |
| `hevi/director/screenplay.py:213-254` fallback + 构造循环 | fallback 分配 + `inherit_unit_ids` 接线（revision/reorder 路径） |
| `hevi/api/routers/director_pipeline.py:333-401,702-1003` | `_init_work`/`regenerate`/`lock` 透传；`_rollback_downstream` 语义不变 |
| `hevi/director/scene_stage.py:106-292` | `_derive_beats`/`_derive_dialogue_sightlines` 改按 `unit_id`（现有按行锚定测试 `test_beats_anchored_to_dialogue_lines` 需同步） |
| tests | screenplay 生成/解析/回退 9 现有用例 + 新增 ID 继承/迁移用例 |

Owner：Director pipeline。`spike script_identity.py` 直接复用；生成侧输出 ID 是主要工作。

## A4 TTS 对齐生产化 — M

| 文件 | 动作 |
|------|------|
| `hevi/audio/edge_tts_custom.py:130-238` | 逐行保留 `word_boundary` 结果并落盘 `.alignment.json`（`synthesize_with_voice_control` 返回契约变更是最大风险点，8 个调用方） |
| `hevi/tongjian/voiceover.py:59-305` | `_synthesize_line` 透传 `unit_id→audio_id`；`AudioSegment` 携带对齐引用 |
| `hevi/tongjian/assemble.py:192` / `audio/task_adapter.py` / `longvideo_orchestrator.py:491-532` | 调用方适配（可先保持 wav-only，逐步切） |
| tests | 现有 6 音频用例回归 + 多音色/中文/分段 phrase 新增 |

Owner：Audio（TTS）。`spike tts_alignment.py` 的 `AudioAlignment` 即契约；调用方多是成本主因。建议分两步：先落盘不改返回契约（S），再改契约（M）。

## A5 Resolver 供给侧 — M（resolver 本体已在 Spike C 完成）

| 文件 | 动作 |
|------|------|
| `hevi/studio/timeline.py:334` `export_timeline` | 唯一 resolve/export 入口；resolver 只读其状态，不写 model |
| `hevi/studio/timeline.py:41-95,155-327` | clip 构造点（`timeline_from_edit_plan/from_film/split_at`）供给 `dialogue_end_ms` 的源头 |
| 调用方 `api/routers/studio.py:380`、`conversational_edit.py:231`、`ops.py:805` | 回归面 |
| tests | `test_timeline_from_plan_and_patch/split_and_ripple/import_film_split_export` + resolver 供给用例 |

Owner：Studio/Timeline。`anchor_resolver.py` 已就绪；工作量在 `dialogue_end_ms` 供给接线。

## A8 Stem 导出 — M

| 文件 | 动作 |
|------|------|
| `hevi/tongjian/assemble.py:192-292` | `concat_narration_track`/`mix_bgm_master`/`mix_sfx_master` 保留中间 stem（现三函数直混 master） |
| `hevi/tongjian/assemble.py:435-454` | `AssembleInput` + `build_final_video` 产出 `AudioArtifact{master + stems}` |
| `hevi/assembly/assembler.py:342-397` | audio-mix builder 同步 |
| `hevi/verdict/delivery_gate.py:136-186` + `silence_probe.py` | 检测切换到 stem 级 + 版本 pin（探测已就绪） |
| tests | 现有 5 assemble 用例回归 + stem 存在性/时长对齐新增 |

Owner：Tongjian/Assembly。替代方案（零成本）：声明 Sound 相关检查 `NOT_EVALUABLE`，P10-S 先跑画面链。

## A9 Per-shot 内容哈希缓存 — M（新建）

现状：P6 有 `RuntimeRequest.content_hash()`（`production_runtime.py:372`）、`intent_hash` 存档（`:631-671`）、`_run_id` 派生（`:666-671`）、`RuntimeLedger` 按 `run_id` 索引（`:455-475`）；**ShotIntent/ShotPlan 无 `content_hash()`，无 shot 级复用表**（`cinematic` 内零缓存）。
动作：`ShotIntent/ShotPlan.content_hash()` + `request_hash→artifact` 复用表 + early-cutoff 失效语义 + 50×/100× 稳定性测试（仿 `test_p6_6_runtime.py:487-781`）。
Owner：Production/P6 runtime。P10a 前可接受全量重跑（降级），P10c 必需。

## A13 Authority pin — M（三分 Authority）

现状：Style 完整（`id@version` 范本）；`NarrativeCanon`（`creative.py:271-292`）仅 `*_ids` 元组，无 version/hash（但基类 `CreativeObject:38-78` 有 `revision` + `calculated_hash()`，可直接用作 pin 源）；Asset（`asset_intelligence.py:74-81` 无状态；`AssetDecision:92-102` 无 version）需 `requirement_id+policy_id+decision_hash` 组合 pin；Provider 已有 `(provider_id,model_id,model_version)`（VI repo），缺统一查询口。
动作：三 Authority 各补 `resolve(id) -> {version_or_hash}` 只读查询（仿 Style registry）。
Owner：各 Authority owner。入向失效（STALE）的前置。

## A10 Receipt 扩展 — S

`ProductionReceipt`（`execution/models.py:133-199`）加 `pinned_hashes/auto_audit/degrade_events` 字段 + `__post_init__` + `to_dict`；`CompilationReceipt`（`constraints/compiler.py:66-78`）同步。注意 `test_p8_3_execution_receipt.py:100-105` 有**精确字段集守卫**，加字段必须同步更新该测试（预期内）。
Owner：Execution。

## A11 Review 挂接 — S–M

`REVIEW_INPUTS` + `FINAL_REVIEW_CHECKS` 加 `C/Creative` 组（`final_review.py:25-93`），`ReviewInputPackage` 加 `creative_*` 字段（`p5_1_review.py:58-139`）。注意 `test_embrace_shotcraft2.py:110-157` 断言 `groups=={P,F,V,S,B,D}`，加组同步更新。H 类 attest surface 待 Q4 拍板（+M）。
Owner：Verdict。

## A12 Render 能力细化 — S（先粗粒度零成本）

`renderer_capability_matrix` + `shot_readiness` 门已存在；camera-movement 级（orbit/push_in/follow）需 ProviderRegistry 补字段（上游）。P10-S 先按 renderer 名粗粒度 negotiation。
Owner：Providers/Renderers。

## A14 存储 — S（选型确认）

复用 `artifact_store`（内容寻址已存在）+ 原子写 + jsonl 追加模式；无新后端。P10 对象库表选型在 P10a 设计时确认。
Owner：Artifact store。

## 顺序与总览

```text
A2+DONE probe+DONE A/B/C+DONE
A3(M) → A4(M, 可分步S+M) → A5供给(M)   # 阻塞链，不可乱序
A8(M) 与 A13(M) 可并行                 # Sound / 入向失效
A9(M) 可降级为全量重跑                 # P10a 后补
A10(S) A11(S) A12(S粗) A14(S)          # 随 P10a 设计消化
```

G0.3 = DONE。G0 剩余动作全部进入"实施"，审计阶段结束。
