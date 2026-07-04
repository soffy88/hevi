# RFC-003 — omodul 多镜头并发生成(上游需求 / 知会主库)

状态: Proposed · 作者: 2026-07-02 SaaS-4 出片链修复 · 范围: L1 编排(`omodul.agentic_longvideo_pipeline`)
上游: `git+ssh://git@github.com/helios-plat/omodul.git`(当前钉死 v1.33.1)
性质: **上游改造需求**。hevi 侧无法在注入边界解决(理由见下),故按 RFC-001 先例正式知会主库 omodul owner。

---

## 1. 问题

`agentic_longvideo_pipeline` 的镜头生成是**严格顺序**的(v1.33.1,`agentic_longvideo_pipeline.py:140-172`):

```python
for idx, shot_plan in enumerate(all_shot_plans):
    ref_set   = await select_ref_fn(..., timeline_history=timeline_history, ...)
    best_frame = await _generate_shot_with_retry(...)   # 昂贵:云 fal / 本地 GPU,单镜头 ~60-90s
    timeline_history.append(ShotFrame(..., frame_path=best_frame, ...))
```

后果:成片墙钟时间 = **各镜头延迟之和**。N 镜头 × ~70s/镜头 → 线性膨胀(1-5min 档常 5-8 分钟,长档更甚)。这是当前出片慢的主因之一(hevi 侧已用 RFC/SaaS-4 的 short 单镜头 + 免逐镜头 LLM 缓解了 short 档,但**非 short 档无解**)。

## 2. 为什么 hevi 侧解决不了(注入边界的天花板)

hevi 通过 `_providers` 注入 `video_fn / select_ref_fn / consistency_fn / shot_gen_fn / assembler_fn`,但**驱动循环本身在 omodul 内**。注入的 `video_fn` 是被 omodul 逐镜头 `await` 调用的,hevi 无法从外部让这个 for 循环并发。

可行的外部 hack(在 `video_fn` 里后台预取下一镜头)需要 hevi 维护跨调用的有状态任务表、并与 omodul 的 retry/fallback/checkpoint 逻辑纠缠 —— 正是 [RFC-001] 与 2026-07-02 审计标记为 **#1 风险(对上游 9 处脆弱猴补丁)** 的那类代码。**长期主义下不采用**;正确做法是上游支持。

## 3. 核心张力:连续性 vs 并发

不能无脑 `asyncio.gather` 所有镜头,因为存在**真实数据依赖**:
`select_ref_fn(镜头 N)` 读 `timeline_history`,其中含前序镜头**已生成的帧** `frame_path=best_frame`(i2v 逐镜头衔接的参考)。即镜头 N 的参考选择依赖镜头 N-1 的生成结果。这条 frame-chained 连续性正是顺序的根因。

因此并发方案必须显式处理它,而非忽略。

## 4. 提案(择一,推荐 A;B 为更可扩展的长期形态)

### 方案 A —— 加 `max_concurrent_shots` + 窗口并发(推荐,改动最小、默认零行为变化)

1. `LongVideoConfig` 增字段:`max_concurrent_shots: int = 1`(**默认 1 = 现行严格顺序,100% 向后兼容**)。
2. 当 `> 1` 时,按窗口大小 `max_concurrent_shots` 分批:窗口内各镜头的 `ref_set` 基于**窗口起始时的 `timeline_history` 快照**计算,窗口内 `_generate_shot_with_retry` 并发(`asyncio.gather` + `Semaphore`);窗口结束后统一回填 `timeline_history`,再进入下一窗口。
   - 语义:**跨窗口保持完整连续性,窗口内放宽为"共享窗口起点参考"**。对"分镜为不同场景/镜头参考以角色·环境为主而非前一帧"的常见工况,画质影响可忽略,却得到窗口大小的近线性加速。
3. 并发上限由调用方经该字段控制(云 provider 可给大窗口;本地单 GPU 应保持 1,避免显存争抢——见 hevi 的 `gpu.scheduler`)。

**可直接落地的最小 diff(示意,omodul 内)**:

```python
# LongVideoConfig
max_concurrent_shots: int = 1   # 1 = 严格顺序(默认);>1 = 窗口并发

# 生成循环替换为窗口化
import asyncio
sem = asyncio.Semaphore(config.max_concurrent_shots)

async def _one_shot(idx, shot_plan, hist_snapshot):
    ref_set = await select_ref_fn(llm=mllm, current_shot=shot_plan,
                                  timeline_history=hist_snapshot, characters=..., environments=...)
    async with sem:
        best = await _generate_shot_with_retry(shot_plan=shot_plan, ref_set=ref_set, ..., idx=idx, ...)
    return idx, shot_plan, best

W = max(1, config.max_concurrent_shots)
for base in range(0, len(all_shot_plans), W):
    window = list(enumerate(all_shot_plans))[base:base+W]
    snapshot = list(timeline_history)                    # 窗口起点快照
    results = await asyncio.gather(*[_one_shot(i, p, snapshot) for i, p in window])
    for idx, shot_plan, best in sorted(results):         # 有序回填,保证拼接顺序
        timeline_history.append(ShotFrame(..., frame_path=best, timeline_index=idx, ...))
        shots_generated += 1
```

`W=1` 时行为与现状逐字节等价(单元素窗口、快照即当前 history)。

### 方案 B —— 暴露 `shot_scheduler_fn` provider 钩子(更可扩展,长期)

在 `_providers` 增可选 `shot_scheduler_fn`,签名 `async (shot_plans, *, per_shot_coro_factory, timeline_history) -> list[best_frame]`;omodul 提供默认顺序实现,调用方(hevi)可注入自定义调度(窗口/优先级/GPU 感知/成本感知)。把"调度策略"外置到注入边界,omodul 不再硬编码策略。改动略大,但与现有 `_providers` 注入范式一致,一劳永逸。

## 5. 向后兼容 / 风险

- 方案 A 默认 `max_concurrent_shots=1` → 现有所有调用零行为变化;仅显式调大才并发。
- 需保证**回填顺序**(按 idx 排序)以维持 `_order_and_dedup_shots`/拼接顺序 —— 上面 diff 已 `sorted(results)`。
- retry/fallback/checkpoint 逻辑在 `_generate_shot_with_retry` 内,不受窗口化影响。
- 强 frame-chained 连续性工况:调用方设 `max_concurrent_shots=1` 即可退回严格顺序。

## 6. hevi 侧衔接(上游落地后)

- 升 omodul 版本 → `build_longvideo_config` 按档位/preset 注入 `max_concurrent_shots`:
  - `wan_local`(单 GPU):恒 `1`(经 `hevi.gpu.scheduler` 串行,避免显存争抢)。
  - `ltx2_cloud / wan_cloud`(云并发):按档位给 3–5(1-5min)/ 更大(长档),受成本预算约束。
- hevi 当前状态(**未 fork omodul**):非 short 档保持顺序;short 档已在注入边界做 单镜头 + 免逐镜头 LLM 提速(SaaS-4,~2.5min 出片)。本 RFC 落地前,非 short 档并发不可得。

## 7. 请主库(omodul owner)决策

1. 采纳 方案 A 还是 B?(建议 A 先行解锁收益,B 作后续演进)
2. 目标版本 tag(便于 hevi `pyproject` 钉版接线)。
3. 若采纳,hevi 侧接线(§6)可在上游发版后 1 个 PR 内完成。

---

参见: [RFC-001](RFC-001-longvideo-quality.md)(同类"注入边界 vs 上游改造"的先例;P0-1 参考帧条件化即由主库直接修复并发 v1.33.1)。
