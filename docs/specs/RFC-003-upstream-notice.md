# [omodul] 需求 + 补丁：`agentic_longvideo_pipeline` 镜头生成窗口并发（RFC-003）

**目标仓库**：`helios-plat/omodul`（基线 tag `v1.33.1`）
**建议版本**：`v1.34.0`（MINOR，新增字段、默认行为不变）
**分支（已备好，待推）**：`feat/v1.34.0-rfc003-shot-concurrency`
**性质**：向后兼容的新增能力；下游 hevi 无法在注入边界解决，需上游支持。

---

## TL;DR

`agentic_longvideo_pipeline` 的镜头生成是严格顺序的，成片墙钟时间 = 各镜头延迟之和（云 provider 单镜头 ~60–90s，N 镜头线性膨胀，1-5min 档常 5–8 分钟）。本提案给 `LongVideoConfig` 增 `max_concurrent_shots: int = 1`（**默认 1 = 现行行为逐字节等价**），`>1` 时按窗口并发生成，**跨窗口保持完整帧链连续性**。已实现并通过 15 项既有测试 + 2 项并发新测（共 17 passed）。

---

## 1. 问题

`omodul/agentic_longvideo_pipeline.py`（v1.33.1，L138-173）逐镜头 `await`：

```python
for idx, shot_plan in enumerate(all_shot_plans):
    ref_set    = await select_ref_fn(..., timeline_history=timeline_history, ...)
    best_frame = await _generate_shot_with_retry(...)   # 昂贵:云 fal / 本地 GPU
    timeline_history.append(ShotFrame(..., frame_path=best_frame, ...))
```

墙钟 = Σ 各镜头延迟。这是长视频出片慢的主因之一。

## 2. 为什么下游解决不了

下游（hevi）通过 `_providers` 注入 `video_fn / select_ref_fn / ...`，但**驱动循环在 omodul 内**。注入的 `video_fn` 是被这个 for 循环逐个 `await` 的，下游无法从外部令其并发。可行的外部 hack（在 `video_fn` 里后台预取下一镜头）需维护跨调用的有状态任务表并与 retry/fallback/checkpoint 纠缠——脆弱且违背“不 fork 上游”的原则。正确做法是上游支持。

## 3. 核心张力:连续性 vs 并发

不能无脑 `gather` 所有镜头,因为存在**真实数据依赖**:`select_ref_fn(镜头 N)` 读 `timeline_history`,其中含前序镜头**已生成的帧** `frame_path`（i2v 逐镜头衔接的参考）。这条 frame-chained 连续性正是顺序的根因,方案必须显式处理。

## 4. 提案（方案 A：窗口并发,推荐）

1. `LongVideoConfig` 增 `max_concurrent_shots: int = 1`。
2. `>1` 时按窗口分批:窗口内各镜头的 `ref_set` 基于**窗口起点的 `timeline_history` 快照**,窗口内 `_generate_shot_with_retry` 并发;窗口结束后**有序回填**（按 idx 排序）再进入下一窗口。
   - 语义:**跨窗口完整帧链连续性,窗口内共享窗口起点参考**。对“分镜为不同场景 / 参考以角色·环境为主而非前一帧”的常见工况,画质影响可忽略,得到窗口大小的近线性加速。
3. 并发上限由调用方经该字段控制（单 GPU 应保持 1 避免显存争抢;云 provider 可调大）。

### 补丁 diff（对 `omodul/agentic_longvideo_pipeline.py`）

```diff
     max_shot_retries: int = 2
     consistency_threshold: float = 0.7
     fallback_video_provider: str | None = None
+    # RFC-003: 镜头生成并发窗口。1 = 严格顺序(默认,行为与历史版本逐字节一致);
+    # >1 = 按窗口并发生成,窗口内共享窗口起点的 timeline_history 快照,跨窗口保持
+    # 完整帧链连续性。单 GPU 工况应保持 1;云 provider 可调大以近线性加速。
+    max_concurrent_shots: int = 1
@@ 生成循环 @@
-    for idx, shot_plan in enumerate(all_shot_plans):
-        ref_set = await select_ref_fn(
-            llm=mllm, current_shot=shot_plan, timeline_history=timeline_history,
-            characters=[f"char_{i}" for i in range(config.num_characters)],
-            environments=[f"env_{idx % 3}"],
-        )
-        best_frame = await _generate_shot_with_retry(
-            shot_plan=shot_plan, ref_set=ref_set, video_fn=video_fn,
-            fallback_video_fn=fallback_video_fn, consistency_fn=consistency_fn,
-            mllm=mllm, shots_dir=shots_dir, idx=idx,
-            max_retries=config.max_shot_retries, threshold=config.consistency_threshold,
-        )
-        from oskill._schemas import ShotFrame
-        timeline_history.append(ShotFrame(
-            shot_id=shot_plan.shot_id if hasattr(shot_plan, "shot_id") else f"shot_{idx}",
-            scene_id=f"scene_{idx}", timeline_index=idx, frame_path=best_frame,
-            characters_present=[f"char_{i}" for i in range(config.num_characters)],
-            environment_id=f"env_{idx % 3}"))
-        shots_generated += 1
+    from oskill._schemas import ShotFrame
+
+    async def _process_shot(idx, shot_plan, hist_snapshot):
+        ref_set = await select_ref_fn(
+            llm=mllm, current_shot=shot_plan, timeline_history=hist_snapshot,
+            characters=[f"char_{i}" for i in range(config.num_characters)],
+            environments=[f"env_{idx % 3}"],
+        )
+        best_frame = await _generate_shot_with_retry(
+            shot_plan=shot_plan, ref_set=ref_set, video_fn=video_fn,
+            fallback_video_fn=fallback_video_fn, consistency_fn=consistency_fn,
+            mllm=mllm, shots_dir=shots_dir, idx=idx,
+            max_retries=config.max_shot_retries, threshold=config.consistency_threshold,
+        )
+        return idx, shot_plan, best_frame
+
+    # 窗口并发:W=1 与历史顺序实现等价;W>1 窗口内并发、跨窗口保持帧链连续性。
+    _window_size = max(1, getattr(config, "max_concurrent_shots", 1))
+    _indexed_plans = list(enumerate(all_shot_plans))
+    for _base in range(0, len(_indexed_plans), _window_size):
+        _window = _indexed_plans[_base : _base + _window_size]
+        _snapshot = list(timeline_history)               # 窗口起点连续性快照
+        if _window_size == 1:
+            _results = [await _process_shot(_window[0][0], _window[0][1], _snapshot)]
+        else:
+            _results = list(await asyncio.gather(
+                *[_process_shot(_i, _p, _snapshot) for _i, _p in _window]))
+        for idx, shot_plan, best_frame in sorted(_results, key=lambda r: r[0]):
+            timeline_history.append(ShotFrame(
+                shot_id=shot_plan.shot_id if hasattr(shot_plan, "shot_id") else f"shot_{idx}",
+                scene_id=f"scene_{idx}", timeline_index=idx, frame_path=best_frame,
+                characters_present=[f"char_{i}" for i in range(config.num_characters)],
+                environment_id=f"env_{idx % 3}"))
+            shots_generated += 1
```

（`asyncio` 该模块已 import;`W=1` 分支保证单镜头工况零协程调度开销、与旧实现逐字节等价。）

## 5. 向后兼容 / 风险

- 默认 `max_concurrent_shots=1` → 所有现有调用零行为变化;仅显式调大才并发。
- **有序回填**（`sorted(_results)`）维持拼接顺序与 timeline 一致性。
- retry / fallback / checkpoint 逻辑在 `_generate_shot_with_retry` 内,不受窗口化影响。
- 强 frame-chained 连续性工况:调用方设 `1` 即退回严格顺序。

## 6. 测试证据

基于 `v1.33.1` + 本补丁,`tests/test_agentic_longvideo_pipeline.py`:

```
17 passed
```

- 15 项**既有**测试全过（默认 `W=1` 向后兼容)。
- 2 项**新增**并发测试:
  - `test_max_concurrent_shots_default_is_sequential`：默认峰值并发 == 1。
  - `test_max_concurrent_shots_runs_in_parallel`：`W=2` 峰值并发 == 2,`shots_generated` 不变。

CHANGELOG 已加 `[1.34.0]` 条目。

## 7. 备选方案 B（更可扩展,长期）

暴露可选 `providers["shot_scheduler_fn"]` 钩子（默认顺序实现),把“调度策略”外置到注入边界,调用方可注入窗口 / 优先级 / GPU 感知 / 成本感知调度,omodul 不再硬编码策略。改动略大但与现有 `_providers` 范式一致。建议 A 先行解锁收益,B 作后续演进。

## 8. 请 omodul owner 决策

1. 采纳 A 还是 B？（建议 A 先行）
2. 目标版本 tag（便于下游 `pyproject` 钉版接线）。
3. 若采纳,下游 hevi 接线（按档位/preset 注入 `max_concurrent_shots`:单 GPU=1、云=3–5）可在上游发版后 1 个 PR 内完成。

---

*下游背景*：hevi 长视频 SaaS。已在注入边界为 short 档做 单镜头 + 免逐镜头 LLM 提速（~2.5min 出片);非 short 档的并发加速依赖本提案落地。下游未 fork omodul（刻意,避免脆弱补丁)。
