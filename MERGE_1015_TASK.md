# MERGE-1015：把已核验通过的 Hevi 分支合并进主线并 push（用户 2026-10-15 15:42 批准："合并并push"）
工作目录：/data/soffy/projects/hevi-pubfix（已有的合并用 worktree；若不在 closure 分支上，先 `git status` 确认干净后切到 closure/3o-v3-architecture-creative-baseline 并 `git pull --ff-only origin closure/3o-v3-architecture-creative-baseline`）。主 checkout /data/soffy/projects/hevi 绝不修改。以 soffy 身份跑 git。

## 第 0 步：先查巡检结论的可疑点（必须做，不许跳过）
巡检 STATUS.md 报的 PASS commit 有几处不对劲：
- reviewsheet 报 R2 PASS 但 commit 88d4518f 是 R1 核验 FAIL 的证据提交；
- handdraw 报 R4 PASS 但 96dd5bb0 是 R3 提交；
- motiondir 报 R1 PASS 但 f6dfd194 只是"merge dirstyle"，看不到 MOTIONDIR_DONE.md 里的 DONE MOTIONDIR-R1。
对这 3 个单元：查分支 HEAD、*_DONE.md 末行、audit/<名>/verify_rN/REPORT.md 是否存在且结论为 PASS。凡是没有真实核验报告或 HEAD 不含声称的修复的，**不合并**，并亲自做独立核验（reviewsheet：`bash audit/reviewsheet/verify_r1/run_all.sh` 必须退出 0；handdraw：按 HANDDRAW_FIX_R4.md 逐条实测；motiondir：DONE 行存在且 MOTIONDIR_TASK.md 的交付项实测）。核验仍失败的写返工单、不合并，在报告里写明。
其余 4 个（scene3d 7849adb2、kidsmanifest ca6408a3、agentops e22d04d1、anatomy d97d3284）快速确认 verify 报告存在且为 PASS 即可。

## 合并
按顺序逐个 `git merge --no-ff <分支>`：scene3d → kidsmanifest → agentops → reviewsheet → handdraw → anatomy → motiondir（只合通过的）。
每合一个：解决冲突（保留双方功能，不删别人代码）；跑 pytest（JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=<worktree>，/data/soffy/projects/hevi/.venv/bin/python，跑该分支相关测试 + capabilities/registry 测试）；3O lint 失败数 ≤ 基线 4。失败就 `git merge --abort`，跳过该分支并记录原因，继续下一个。
全部合完后跑一次全量 pytest，与合并前基线对比，不得新增失败。
然后 `git push --no-verify origin closure/3o-v3-architecture-creative-baseline`。不 force push。

## 报告
写 /data/soffy/projects/hevi-pubfix/MERGE_1015_REPORT.md：每个分支的合并结果（merge commit 或跳过原因）、测试数字、lint 数字、最终 push 后的 HEAD；最后一行 `DONE MERGE-1015`。不部署、不重启任何服务。

## 安全
只在 hevi-pubfix 和各 feature worktree 内工作；不删 worktree 外文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；CPU-only，同时只渲染一个；不调付费 API；不动生产容器；不询问。
