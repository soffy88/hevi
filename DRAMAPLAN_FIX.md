# DRAMAPLAN_FIX（审核方首轮独立核验，2026-10-12）— 不通过，返工

核验对象：feat/dramaplan-3o @8970bd0d（基线 98e216af）。
已确认通过、**不要改坏**的部分：新增+旧测试 114 passed；3O lint 仍是基线 4 项失败、无新增；
E2E 只走 NIM 免费通道；E2E 路径无 mock/placeholder；三层审稿的确定性规则确实能拒稿；
bug2 阈值尺度校准（0.75→0.35）与 `select_rework_shots`/`full_rework` 合理；clean-room 抽查无问题。

下面每一条都必须修，修完在 DRAMAPLAN_DONE.md 里逐条写“如何修的 + 证据（测试名/命令输出）”。

## P1. bug1 没有真修好：时长只能“往下压”，不能“往上加”，60s 与 120s 实际镜头数相同
- `longvideo_orchestrator._counting_shot_gen_fn` 只在 `len(plans) > 每章预算` 时 `fit_shot_plans_to_budget` 合并，
  从不增加镜头。上游 storyboard 每章典型 ~5 镜（STATUS 记录“收敛到约 10 镜”）→ 30s 被压到 6，
  但 60s(预算 12) 和 120s(预算 24) 都还是 ~10 镜，300s 也还是 ~10 镜。“镜头数随时长单调增加”在真实路径上不成立。
- `tests/test_shot_budget.py::test_shot_count_monotonic_across_durations_after_fit` 用人造的 20 镜输入，
  恰好掩盖了这个问题；且没有任何测试走 orchestrator 路径。
- 要求：
  1. 在 hevi 侧实现“不足预算时补足/扩展”：例如把预算传给上游可控参数
     （上游 `oskill.storyboard_planner(shots_per_scene_min, shots_per_scene_max)` 就是现成的杠杆——
     在 hevi 内包一层调用或在 `_counting_shot_gen_fn` 前重分配），或在 hevi 侧把长镜头按时长拆分成多镜。
     **仍然禁止修改 site-packages。**
  2. 加一个走 `_counting_shot_gen_fn`/orchestrator 真实调用链的测试（fake 上游 storyboard，固定每章 5 镜），
     断言 target_duration_s=30/60/120 时最终镜头数严格单调递增且每个都落在 `shot_budget_for_duration` 预算内（允许 ±章数 的取整误差，写明）。
  3. 未显式设 `target_duration_s` 时（按 archetype 推导的时长，如 1-5min→180s）也应套用同一预算，或在 DONE 写明为何不套。

## P2. 改编大纲的镜头预算自相矛盾
- `build_adaptation_outline`：`total_shot_budget = 集数 × shot_budget_for_duration(每集时长)`（60s→36），
  但每集 `shot_budget = shot_budget_per_chapter(每集时长)`（60s→6，这是“上游每章”预算，不是“每集”预算），
  run1–run4 的 adaptation_outline.json 都是 total=36、各集合计 18。
- 要求：每集预算用 `shot_budget_for_duration(episode_duration_s)`，保证 Σ各集 == total（或 ≤ 且写明原因）；
  加单测断言这条不变式；重跑 E2E 产出新 run。

## P3. 事件图没有驱动分镜（只到“分场稿”，且没接进任何生产路径）
- `build_book_event_graph / build_adaptation_outline / outline_to_story / run_three_layer_review`
  在 `hevi/` 内**零调用方**，只在 `scripts/e2e/dramaplan_e2e.py` 和单测里用；`outline_to_story→season_planner` 只在单测里验证。
- episode_scripts 只有场级 `shot_count` 数字，没有镜头级分镜（每镜画面描述/台词/时长/对应事件ID）。
- 要求：
  1. 从审稿通过的 EpisodeScript 生成镜头级分镜（每镜带 `event_id`、画面描述、台词/旁白、时长；
     镜头数=该场 shot_count，Σ = 本集预算内），可直接转成上游 `oskill._schemas.ShotPlan` 列表或 season_planner/dispatch 能消费的结构。
  2. 在短剧通道接一个真实入口（例如 `season_planner`/`hevi/shortdrama` 的“长篇模式”函数或 CLI 选项）：
     长篇文本 → 事件图 → 大纲 → 三层审稿 → 分镜，一条链调用；不要求出视频、不要调付费视频供应商。
  3. E2E 新增 `storyboards/epXX.json`，qa.json 增加脚本计算的检查：每个镜头的 event_id 都在事件图内、
     本集镜头数 == Σscene.shot_count 且 ≤ 本集预算、每集覆盖其大纲事件。

## P4. 三层审稿的“返修”只是确定性打补丁，LLM 监督意见永远不会被处理；日志字段有误导
- `revise_episode_script` 只做截断台词、换说话人、删禁忌句、等比缩时长/镜头数；执行层从不带着问题列表再调 LLM 改稿。
  LLM 监督意见一律 warning、不进硬门、也从不触发返修，所以 run3/run4 里“逻辑连贯/人物弧光”等问题四轮都原样留着。
- `RoundRecord.revised_scenes` 取的是**上一轮所有带 scene_no 的 issue（含 LLM warning）**，不是真正被修改的场：
  run3 EP1 round1 记 revised_scenes=[1,2]，实际触发返修的是整集级 `duration_out_of_range`。
- 要求：
  1. 执行层返修：对被点名的场（规则 error 或 LLM 标 error 的定性问题），带问题列表**调 LLM 只重写这些场**，
     解析失败再回退确定性补丁；未点名场保持对象/哈希不变（保留现有 diff 断言）。
  2. 允许 LLM 监督给出 `severity=error` 的定性问题进入返修回路（硬门仍以规则为准，或设一个可配置开关，写明）。
  3. `revised_scenes` 改为由 scene_diffs 实际变化的场推出；再加一个字段记录“触发返修的 issue codes”。
  4. 单测：fake LLM 第一轮返回带 error 的定性问题 → 执行层只对该场再次调用 LLM（断言调用的 prompt 只含该场）→ 第二轮通过。
  5. E2E 至少一集出现“LLM 定性问题 → LLM 改场 → 再审”的真实记录。

## P5. 长上下文记忆是摆设
- `extract_chapter_graphs` 只 `memory_store.remember(...)` 写入，从不检索；E2E 也没传 memory_store。chapters.py 文档写“按需召回”与事实不符。
- 要求：逐章抽取时检索前文章节摘要/已知角色表（`hevi/memory/store.py`）注入 prompt，用于跨章人物合并与因果；E2E 启用它；
  单测断言第 N 章的 prompt 含第 N-1 章摘要且不含全文。

## P6. 报告失实处要更正
- DONE 把 `CH01E002.effects=["CH02E001"]` 当成“跨章因果边真实存在”的证据，但这是 `merge_chapter_graphs` 机械缝合（上一章末事件→下一章首事件），不是抽取结果。
  要么让 LLM 基于前文摘要真正判断跨章因果（配合 P5），要么在 DONE 和 event_graph.json 里给缝合边打标（如 `causal_source: "stitched"`）。
- bug2 测试名/文档写“provider 调用次数=3”，实际是 6 次底层调用（每镜 2 变体）、断言的是镜头集合。按任务书改成断言“被调用的镜头数=3 且非目标镜头调用次数=0”，并在 DONE 如实写 6 次底层调用的原因。
- 任务书提到 `task_service.py` 约 394 行的返工入口：确认该路径也走镜头级挑选（或说明它不是自动返工入口）。

## 完成标准
- 新增/修改测试全绿；`test_storygraph / test_shortdrama_* / test_shot_preparation / test_script2video_kernel / test_director` 不回归；lint 不新增失败。
- 新 E2E run（免费 NIM 或 ollama），产物含 storyboards/，record.json 写通道与调用次数。
- 不改 site-packages、不调付费 API、不 push/merge。完成后更新 DRAMAPLAN_DONE.md 并 git commit。
