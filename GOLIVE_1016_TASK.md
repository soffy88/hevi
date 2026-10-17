# PATROL4 + GOLIVE-1016（用户要求加快收尾上线，已授权部署 hevi-api）
工作目录 /data/soffy/projects/hevi-pubfix（主 checkout 不动）。工人自报 PASS 不算，必须自己重跑。

## A. 独立核验（用自己的反例脚本，写 audit/patrol4/<unit>.md）
1. partsci（/data/soffy/projects/hevi-partsci，feat/particle-science，DONE PARTSCI-R1）：重渲两支样片，ffprobe 1080p/有声；抽帧看粒子文字与六层视差位移；亮度变化闪烁 ≤3Hz；事实卡来源与旁白一致；未审批分镜必须拒绝渲染；同 seed 两次 SHA 一致；pytest；lint ≤4。
2. kidsmanifest（hevi-kidsmanifest，DONE KIDSMANIFEST-R4）：暴力词反例「勒脖子、踹飞、针扎、绑树堵嘴、鞭打、狗咬」及同义改写全部拦截，正常幼儿词不误杀；pytest。
FAIL 的写 <UNIT>_FIX_R(n+1).md 到该 worktree 并用 /data/soffy/pi_loop_fix.sh 起下一轮（systemd-run --user，MemoryMax=4G），不合并它。

## B. 合并上线（只合 PASS 的）
合入 closure（--no-ff）：feat/scene3d-vibe @2a223a2b、feat/story-plan @68a7abc3、以及 A 中 PASS 的 partsci / kidsmanifest。全量 pytest 无新增失败、lint ≤4 → `sudo -u soffy git push --no-verify origin HEAD:closure/3o-v3-architecture-creative-baseline`。
部署同 GOLIVE_1015_TASK.md：先打 hevi-cftunnel-hevi-api:rollback-20261016，构建并只重建 hevi-api；验收 health 200、/api/capabilities 含新能力（vibe3d 模板、story_plan/story_check/take_select、partsci）、用 API/能力真实出一支 ≥20s 幼儿片（ffprobe+抽帧+有声）、日志无 traceback；失败立即回滚。

## C. 报告 audit/patrol4/GOLIVE_1016_REPORT.md：每单元 PASS/FAIL+证据数字、合并 commits、远端 HEAD、镜像 tag、验收结果。最后一行 `DONE GOLIVE-1016`（或 `BLOCKED GOLIVE-1016: 原因`）。

## 安全
CPU-only，单进程渲染；不调付费 API；禁止 mock；不删 worktree 外文件、不清理磁盘、不 docker prune（/data <5G 写 DISK_FULL_NOTE.md 停止）；只动 hevi-api 容器。

## A 追加（Hark 06:62）
3. svfactory（hevi-svfactory，feat/svfactory @136b86ef，自报 DONE SVFACTORY-R1）：按 SVFACTORY_TASK.md 验收项全部重跑（批量 3 片、kill 续跑、混剪同 seed SHA、kids_gate、未复制 AGPL 源码）。
4. toonflow（hevi-toonflow，feat/toonflow-assets @c18daff5，自报 DONE TOONFLOW-R1；最后一轮只跑了 72s，高度可疑）：按 TOONFLOW_TASK.md 验收项全部重跑（两支样片、角色一致性数字 + 改坏配色必须报出、真实 MCP 客户端列 tools/提交/取片）。
PASS 的一并在 B 合入上线；FAIL 写 FIX 并起下一轮。
