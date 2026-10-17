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

## 复核问题（Hark 2026-10-17 17:30）
复核未通过，MERGEALL DONE 无效，请继续：
1. 34 个 SKIPPED 的理由只是贴了 git 的 "CONFLICT" 输出，并没有尝试解决。brief 第 3 条要求冲突要真正解决（registry / __init__ / pyproject / .gitignore / NOTICE / provenance-ledger / docs 等合成并集，理解双方意图保留两边功能）。只有在解决后仍有修不好的测试失败时才可 SKIPPED，且原因要写具体失败的测试/技术原因。请逐个重试这 34 个分支（先小后大），每个解决冲突后 commit，状态写 MERGED-WITH-FIXES。
   - modify/delete（hevi/distribution/service.py 等）：查清主线为何删除（chore/remove-publishing 之类），若主线有意删除则保持删除并在 MERGE_PLAN 写明，属于"已解决"而不是 SKIPPED。
   - feat/continuity-1017 等内容已在主线的分支：解决冲突时以主线为准但保留分支独有改动。
2. 另有 37 个 `wip/*-20261017` 分支（各 worktree 未提交改动和 stash 的快照，如 wip/opuscar-20261017、wip/stash-0-20261017 …）未列入 MERGE_PLAN.md，也属于"没合并的更改"，必须加入计划并合并（同样解决冲突）。
3. 最终回归比基线多 1 个失败（ShotPlan 重复权威架构测试）。不得新增失败：找出是哪个合并引入的并修复。
4. 完成标准：`git branch --no-merged integration/mergeall-1017` 只剩确有具体技术原因的 SKIPPED 分支；核心回归失败名单 ⊆ 基线 3 个。
