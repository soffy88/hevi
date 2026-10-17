# BRIEF MERGEALL-1017：把 hevi 所有未合并分支并入主工作分支

## 背景
用户 2026-10-17 明确指示："没合并的更改全部合并，不管是不是你这边的改变"。
主工作分支：`closure/3o-v3-architecture-creative-baseline`（/data/soffy/projects/hevi 当前检出，HEAD a9af1c2e，已包含连续性+首帧+之前未提交的 WIP）。
本 worktree：/data/soffy/wt/hevi-mergeall，分支 `integration/mergeall-1017`，从 a9af1c2e 建出。

## 要做
1. 基线：`git branch --no-merged integration/mergeall-1017` 列出全部未合并本地分支（约 55 个），写进 MERGE_PLAN.md（分支、最近提交时间、与基线分叉提交数、改动文件数）。先跑基线测试：`/data/soffy/projects/hevi/.venv/bin/python -m pytest -q -x --timeout 300 tests` 若全量太慢（>20 分钟）就用 `tests/test_continuity.py tests/test_first_frame.py tests/test_h3_compiler.py tests/test_h3_shot_discipline.py tests/test_prompt_engineering.py tests/test_shot_prompt.py tests/architecture` 加每个分支自己新增的测试；记录基线通过/失败名单。
2. 合并顺序：先近期、小、独立的 feat/* 分支（按分叉小→大），最后才是老分支（feat/spec-001-shortdrama-backend、feat/tongjian-v2-consolidation-color、architecture/*、platform/*、product/*、release/*、closure/3o-v3-architecture、pi-attempt-1 等 3 个月/5 周前的）。
3. 每个分支：`git merge --no-ff <branch>`。冲突要真正解决：理解双方意图后保留两边功能（capability registry、__init__ 导出、pyproject 依赖等合并成并集）；不要用 `-X ours/theirs` 整体丢一边。合并后跑该分支相关测试 + 核心回归，不得引入新失败；如有新失败先修，修不好就 `git merge --abort`/reset 到合并前，把该分支记为 SKIPPED 并写原因。每合一个分支 commit 并更新 MERGE_PLAN.md 状态（MERGED / MERGED-WITH-FIXES / SKIPPED+原因）。
4. 分支里若含大二进制（>20MB 单文件）照常合并即可，但不要新增大文件。
5. 有工人仍在跑的分支（例如 feat/opuscar-integration、feat/stickman-flow 等）也合并其当前提交，报告里注明"合并时点 commit"，之后它们的新提交需要再合一次。
6. 全部完成后：在 integration 分支上跑最终回归，与基线对比。

## 验收
- MERGE_PLAN.md 每个分支都有结论；MERGED 数尽量多；SKIPPED 必须有具体技术原因。
- 最终回归无新增失败（与基线名单对比）。
- 不得修改/删除旧测试来凑通过。

## 规则
CPU-only，不调付费 API；不 push、不部署；不要动 /data/soffy/projects/hevi 主检出目录（Hark 会在核验后快进主分支）；不要删除任何分支或 worktree；不删 worktree 外文件；/data 剩余 <5G 立即停；每步 commit。
最后写 REPORT_MERGEALL.md：合并了哪些、修了哪些冲突、跳过哪些及原因、测试基线 vs 最终；最后一行 `MERGEALL DONE` 或 `MERGEALL BLOCKED`。
