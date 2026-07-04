# [omodul] 需求：结构化 per-shot 结果 + 镜头级返工 `regenerate_shots`（3O §C3）

**目标仓库**：`helios-plat/omodul`（基线 tag `v1.35.0`）
**建议版本**：`v1.36.0`（MINOR，新增字段 + 新增函数,默认行为不变、向后兼容）
**性质**：向后兼容的新增能力;**下游 hevi 无法在注入边界解决**(生成循环与结果装配在 omodul 内),需上游支持。
**来源**：hevi SaaS · 见 `3O-new-elements-manifest.md §C3`。同族已就绪范例:`RFC-003-upstream-notice.md`(窗口并发,已并入 v1.35.0)。

---

## TL;DR

`agentic_longvideo_pipeline` 逐镜头生成时**内部已算出每个镜头的关键元数据**(选中哪个变体、一致性分、是否及格),但 `LongVideoResult` **只暴露一个计数** `shots_generated: int`,其余全部丢弃。这堵死了下游三件事:①镜头级选优/评分**落库**;②verdict→**定向返工**闭环;③L4 Editor。本提案:

1. **C3a**:`_generate_shot_with_retry` 返回值从 `best_frame: Path` 升为一个**结构化记录**,并在 `LongVideoResult` 增 `shots: list[ShotRecord]`(默认空列表兼容)。
2. **C3b**:新增编排入口 `regenerate_shots(*, shot_ids, hints, ...)`,复用镜头级 checkpoint **只重生成指定镜头**、把 `hints[idx]` 注入该镜头 prompt,其余复用,再重装配。

均为纯新增;现有调用零行为变化。

---

## 1. 问题:内部算出、对外丢弃

`omodul/agentic_longvideo_pipeline.py`(v1.35.0):

- 生成循环(L193-215)对每个镜头拿到 `best_frame = await _generate_shot_with_retry(...)`,`_generate_shot_with_retry` 内部(L~340)已有:
  ```python
  result = await consistency_fn(mllm=mllm, candidate_frames=candidates, reference=ref_set, criteria=criteria)
  last_best = result.best_frame          # 选中的变体
  if result.passed: return last_best     # 及格与否
  ```
  —— **`result.passed`、选中的是 v0 还是 v1、一致性分**全在手里,但函数只 `return last_best`(一个 Path),元数据即弃。
- `LongVideoResult`(L68)对外字段:`video_path, duration_s, chapters, shots_generated: int, provider_used, failed_shots`。**没有任何 per-shot 明细**。

下游(hevi)本会话已落地 C1(身份向量)+ C2(本地 VLM)+ C4(`shot_scorecard`),注入的 `consistency_fn` 现返回富对象(`best_frame`/`passed`/`scorecard{identity_score, hints, per_candidate}`)。**但这些一进 `_generate_shot_with_retry` 就被压成一个 Path。** 下游拿不到"第 3 镜头选了 v1、身份分 0.94、及格"这类数据。

## 2. 为什么下游解决不了

驱动循环、`_generate_shot_with_retry`、结果装配**全在 omodul 内**。下游经 `_providers` 注入 `video_fn/consistency_fn/...`,但:
- **per-shot 结果**:即使下游的 `consistency_fn` 自己记录,也无法把记录关联回 omodul 的镜头 idx / 最终采纳链(omodul 可能因 retry/fallback 覆盖),且 `LongVideoResult` 无字段承载 → 只能靠**扫输出目录 + 解析文件名**反推,脆弱。
- **定向返工**:`regenerate_shots` 需要驱动内部生成循环**只跑子集**并复用前次 `timeline_history`(帧链连续性),驱动器在 omodul 内,下游无法从外部触发子集重跑。

正确做法是上游把"内部已有的数据"暴露出来 + 提供子集重跑入口。

## 3. 核心张力

- **C3a**:per-shot 记录需 `_generate_shot_with_retry` **透出 consistency `result`**(而非只 best_frame)。`variant_chosen` 可由 `candidates.index(result.best_frame)` 推出;`consistency_score` 取 `getattr(result, "scorecard", None)` 或 result 上的分数字段(下游注入的 consistency_fn 已带);二者缺省时降级为 `None`/`-1`。
- **C3b**:返工必须保持**帧链连续性** —— 重生成镜头 N 时,其 `select_ref_fn` 依赖前序镜头的已生成帧。方案:从前次产物(`shots_dir` 的 `shot_XXXX_vN.mp4` + checkpoint marker)重建 `timeline_history`,只对 `shot_ids` 跑生成,`hints[idx]` 并入 `prompt_override`。

## 4. 提案

### C3a — 结构化 per-shot 结果

```python
class ShotRecord(BaseModel):
    index: int
    path: Path
    provider: str                       # 该镜头实际成片的 video provider(含 fallback 后)
    variant_chosen: int = -1            # candidates 里被选中的下标(缺省 -1)
    consistency_score: float | None = None
    passed: bool = True
    duration_s: float | None = None     # best-effort(可后置)

class LongVideoResult(BaseModel):
    ...                                 # 现有字段不动
    shots: list[ShotRecord] = []        # 新增,默认空 → 老调用零变化
```

diff 要点(对 `agentic_longvideo_pipeline.py`):
```diff
-    async def _process_shot(idx, shot_plan, hist_snapshot):
+    async def _process_shot(idx, shot_plan, hist_snapshot):
         ...
-        best_frame = await _generate_shot_with_retry(...)
-        return idx, shot_plan, best_frame
+        best_frame, meta = await _generate_shot_with_retry(...)   # meta: {variant_chosen, consistency_score, passed, provider}
+        return idx, shot_plan, best_frame, meta
@@ 有序回填 @@
-        for idx, shot_plan, best_frame in sorted(_results, key=lambda r: r[0]):
+        for idx, shot_plan, best_frame, meta in sorted(_results, key=lambda r: r[0]):
             ...
+            shot_records.append(ShotRecord(index=idx, path=Path(best_frame), **meta))
@@ 组装 LongVideoResult @@
-    return LongVideoResult(..., shots_generated=shots_generated, ...)
+    return LongVideoResult(..., shots_generated=shots_generated, shots=shot_records, ...)
```
`_generate_shot_with_retry` 相应把 `return last_best` 改为 `return last_best, {"variant_chosen": ..., "consistency_score": ..., "passed": ..., "provider": ...}`。

### C3b — 镜头级返工入口

```python
async def regenerate_shots(
    *, task_dir: Path, shot_ids: list[int],
    hints: dict[int, str] | None = None,
    config: LongVideoConfig, _providers: dict[str, Any],
) -> LongVideoResult:
    """只重生成 shot_ids:从 task_dir 既有产物重建 timeline_history(帧链连续性),
    对目标镜头 hints[idx] 并入 prompt 重跑,其余复用,重装配。返回带 shots 的结果。"""
```
- 复用现有镜头级 checkpoint(下游已在写 `shot_XXXX.mp4.done.json`);未指定镜头字节不变。
- `hints[idx]` → 并入 `shot_prompt_fn`/`prompt_override` 的富化。
- 与 B9(装配前排序去重)/B11(失败暴露)兼容。

## 5. 向后兼容 / 风险

- `LongVideoResult.shots` 默认 `[]`,`_generate_shot_with_retry` 返回值变为二元组是**内部改动**——只需同步其唯一调用点;对外 `LongVideoResult` 仅**增**字段,现有下游零变化。
- `regenerate_shots` 是**新函数**,不影响 `agentic_longvideo_pipeline` 主入口。
- `consistency_score`/`variant_chosen` 在拿不到时降级 `None`/`-1`,不强依赖下游注入富对象。

## 6. 下游依赖(为什么现在提)

hevi 本会话已落地 Phase 0(C1/C2/C4),双变体在角色锁定时已按身份**真·图对图选优**,`consistency_fn` 产出富评分卡。**卡点就在 omodul 把这些压成一个 Path**:
- hevi `ShotState` 表 + repo 已就绪但**零调用**(无数据可存)——等 C3a 的 `shots`。
- hevi 评分卡的 `hints` 已生成但无处可去——等 C3b 的 `regenerate_shots` 接成 verdict→返工闭环。

## 7. 请 omodul owner 决策

1. C3a `ShotRecord`/`shots` 字段命名与最小集是否 OK?`provider`/`duration_s` 若一期难拿,可先出 `{index, path, variant_chosen, consistency_score, passed}`。
2. C3b `regenerate_shots` 签名 + 是否复用现有 checkpoint 约定(`shot_XXXX.mp4.done.json`)。
3. 目标版本 tag(便于下游 `pyproject` 钉版接线)。
4. 采纳后下游 hevi 接线(`ShotState` 落库 + 评分卡 `hints`→`regenerate_shots`)可在上游发版后 1–2 个 PR 内完成。

---

*下游背景*:hevi 未 fork omodul(刻意,避免脆弱补丁)。C3 是 hevi L1 落库 / L3 verdict 闭环 / L4 Editor 的共同前置。参考实现思路见上;若 owner 愿意,下游可提供 hevi 侧 `consistency_fn` 富对象的字段样例以对齐 `ShotRecord`。
