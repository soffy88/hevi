# P1–P3 实施报告 + P4 阻塞审计

```yaml
status: P1-P3 PASS · P4 BLOCKED (source absent) · P5/P6 seam defined
date: 2026-10-03
verification: tests/p10 115 passed · ruff clean · mypy clean (4 new source files)
spec: HEVI_LONGCAT_VIDEO_INTEGRATION_SPEC v1.0
```

## 已实施（P1–P3，provider-agnostic）

`hevi/generation/`：

| 模块 | 内容 |
|---|---|
| `models.py` | `VideoGenerationRequest`（最小字段集）、`GenerationBudget`、`GenerationStage`、`VideoGenerationCapabilities`、`ConditioningWindow`、`ContinuationState`、`GeneratedClip`、`FallbackRecord` |
| `backend.py` | `VideoGenerationBackend` 协议、能力校验、media/continuation 闸门、`run_generation` 编排、`GenerationJournal` resume |
| `errors.py` | fail-closed 错误码（`CONTINUATION_STATE_MISSING` / `SILENT_FALLBACK` / `CONDITIONING_WINDOW_INVALID` …） |

架构红线已落码并被测试锁死：

- **无 provider flag 泄漏**：`FORBIDDEN_CANONICAL_FIELDS`（`num_cond_frames` / `use_kv_cache` / `enable_bsa` / `refinement_lora` / `use_distill` / `offload_kv_cache` / `enhance_hf` / `context_parallel_size`）在 request 及其全部嵌套结构中缺席。
- **不建第二套 capability/selection authority**：capability 只做**声明与校验**；backend 自述能力，选择权仍归既有 `obase.ProviderRegistry`（`providers/registry.py`）。
- **不建第二套 generation runtime**：本模块只做单次生成编排 + 闸门 + journal；既有 `production/p6/production_runtime.py::RuntimeRequest/RuntimeLedger` 未被复制或替换。
- **continuation 不能退化为 last_frame**：`ConditioningWindow` 强制 `media_ref` + 帧区间 + 时间戳，且 `timestamp span` 必须与 `fps/frame_count` 自洽（±1 帧）。
- **fail-closed**：`continuation_required` + 缺 state → `CONTINUATION_STATE_MISSING`；backend 不回绑 state → `SILENT_FALLBACK`；artifact 缺失/空/fps 不符 → `MEDIA_INTEGRITY_FAILED`；闸门无证据 → `NOT_EVALUABLE`（不默认 PASS）。
- **resume 按 stage 拆分**：REFINEMENT 失败 → 复用已验证 CONTINUATION 产物，不重生成 scene。

实施期修的一个真 bug：`validate_media` 先查 `clip.artifact_path` 再看编排器给的 `source`，导致「backend 自报空路径 + 编排器指定落盘位置」误判失败。已改为 `source` 权威。

## P4 BLOCKED — LongCat 源码不在本仓库（不实现、不伪造）

spec §9 / §13 / §14 / §15 断言「LongCat 当前源码确实使用 KV cache / refinement LoRA + BSA / 13 conditioning frames / generate_vc / generate_refine」。**本仓库无法核实任何一条**：

| 核实项 | 结果 | 证据 |
|---|---|---|
| LongCat 视频模型源码 | **不存在** | `hevi/video/longcat/` 为**空目录**（0 文件） |
| `hevi/longcat/` 是什么 | 3O vendored 管线（oprim/oservi/omodul 协议层），非视频模型 | `hevi/longcat/{oprim,oservi,omodul}` |
| `generate_t2v` / `generate_i2v` / `continue_video` | **零命中** | 全仓 grep |
| `conditioning_window` / `kv_cache` / `enable_bsa` / `num_cond_frames` | **零命中** | 全仓 grep |
| LongCat 在 HEVI 的注册身份 | **`ProviderKind.LLM`**（"OpenAI-compatible agent endpoint"），能力 `("llm",)` | `hevi/providers/facts.py:271-273` |
| 已注册 video provider | veo3 / kling_v2 / hailuo / wan_2_7 / wan_local / ltx2_\* / vidu / happyhorse_1_1 / hyperframes —— **无 LongCat-video** | `hevi/providers/registry.py` |

**结论**：spec 的前提（LongCat 是 HEVI 可接入的视频生成模型）与仓库现状不符 —— 它目前是 LLM endpoint。按 §14 fail-closed 原则，写一个声称 `generate_vc` / `refinement` 可用的 adapter 就是伪造能力，因此 **P4 未实现**。

解除阻塞需要其一：

1. LongCat 视频推理代码的实际位置（路径或可安装包），以及它是否真的暴露 VC / refinement；
2. 或改由**已注册的视频 provider** 承接（wan / veo3 / kling 等），我按同一 canonical 契约实现其 adapter —— 能力按实测声明，不按推测。

## P5/P6 集成缝（已核实，未改代码）

- **HyperFrames**：现为 `ProviderRegistry.register("video","hyperframes", hyperframes_generate)`（`providers/hyperframes/provider.py:216`），capabilities `["t2v","motion_graphics","kinetic_type","zh_prompt"]`。
  接入缝 = 让它消费 `GeneratedClip` 并透传 `clip.provenance()`（generation_id / source_shot_id / continuation_state_id / stage / backend / backend_version），**不新开渲染通道**。
- **Timeline**：`hevi/studio/timeline.py` 当前**不 import 任何 provider**（grep 确认），spec §11「Timeline MUST NOT 直接调用 provider」在现状下**已成立**，无需改动。

## 未做（spec §21 non-goals 一致）

BSA / DiT 改造 / 本地 GPU 优化 / Avatar 接入 / provider benchmark / 替换现有 renderer / 改写 P10·P10a。