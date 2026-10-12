# DRAMAPLAN 进度（R3/R4/R5 修复轮）

## R3 修复摘要
完成以下修复并提交：
1. `shot_budget.split_single_shot_plan` — 内容不再被丢弃或造空 tts
2. `review.py::deterministic_checks` — char_id speaker 被识别并映射为人名
3. `review.py::script_to_storyboard` — 不再重复相同台词，分镜不出现 char_id
4. `chapters.merge_chapter_graphs` — 新增 `StoryEvent.edge_sources` 记录缝合边
5. E2E `review_has_revision_round` 不再作为必过项，真实出现返修才报告

## R1 审稿回路无预设（已修复）
- 初审与复审均使用中立提示词，允许 error 与 warning，不强制必过
- 复审若仍判定 error 则如实返回 passed=False，不阻断下一轮
- E2E 如实报告 `review_all_passed`，不阻断 qa.passed

## 真实 E2E（run6，免费 NIM）
- 通过：`qa.passed=true`
- 通道：`nvidia/nemotron-3-super-120b-a12b`
- 产物：10 个文件全部 sha256 记录在 qa.json
- 真实发生返修集数：`[1, 2]`（EP3 首轮即通过）

## Git 提交
1. `fix(dramaplan): split_single_shot_plan preserves content (R3)`
2. `fix(dramaplan): R1 neutral supervisor prompts; R2 full text diffs; R4 char_id speaker mapping; R5 edge-level stitched annotation`
3. `fix(dramaplan): R1 reviewer can reject revision rounds; E2E reports revision episodes without gate`
4. `fix(dramaplan): R4 no duplicate dialogue in storyboard; char_id mapping in script_to_storyboard`
5. `feat(e2e): run6 real NIM, non-gating review metrics; R4 no duplicate storyboard lines`
6. `fix(dramaplan): no-duplicate-narration storyboards; differentiate filler shots per index`
7. `feat(e2e): run6 real NIM with no-duplicate storyboards; R5 edge-level stitched evidence`

## 测试结果
- 新增单测 12 passed（含 R3 拆分、R1 复审拒稿、R4 无重复台词、无 char_id）
- 全量回归 102 passed
- 3O v3 lint 仍为基线 4 项（全部位于 site-packages 上游）

## 后续（已在本轮完成）
- DONE 报告更新为 R6 状态与真实数据
