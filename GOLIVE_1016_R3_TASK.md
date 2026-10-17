# GOLIVE-1016-R3 修复轮（上一轮 r2 被标题里的 "GOLIVE-1016" 误判完成而退出，实际未完成）
工作目录 /data/soffy/projects/hevi-pubfix（主 checkout /data/soffy/projects/hevi 不动）。先读 GOLIVE_1016_TASK.md 和 audit/patrol4/GOLIVE_1016_REPORT.md。已完成且线上已核实：partsci、kidsmanifest R5 合入，远端 closure HEAD ec3061a0，hevi-api latest 健康、/api/capabilities 28 项。

## 本轮必须补完（Hark 核查发现的缺口）
1. svfactory（/data/soffy/projects/hevi-svfactory，feat/svfactory @136b86ef）独立核验：按 SVFACTORY_TASK.md 全部重跑——批量 3 片、kill 后续跑、混剪同 seed SHA 一致、kids_gate、未复制 AGPL 源码。写 audit/patrol4/svfactory.md（数字证据）。
2. toonflow（/data/soffy/projects/hevi-toonflow，feat/toonflow-assets @c18daff5，上轮仅 72s 可疑）独立核验：两支样片、角色一致性数字、故意改坏配色必须被报出、真实 MCP 客户端列 tools/提交/取片。写 audit/patrol4/toonflow.md。
3. 全量 pytest 上次因 "No space left on device" 崩溃（audit/patrol4/full_pytest.txt），无有效结果。重跑全量 pytest（cache 指向 worktree 内 .tmp），与基线比无新增失败；lint ≤4。
4. 回滚镜像不存在：docker images 里没有 hevi-cftunnel-hevi-api:rollback-20261016（也没有 rollback-20261015）。在下一次部署前，先把当前运行镜像打 tag hevi-cftunnel-hevi-api:rollback-20261016，并同时打 git tag rollback-20261016 指向部署前的 closure HEAD 并 push 该 tag（sudo -u soffy git push --no-verify origin rollback-20261016）。
5. 验收幼儿片：上次用的是 partsci 科普片。另用幼儿故事线（kids.render_local 或 story_plan 链路）经 API 真实出一支 ≥20s 幼儿片，ffprobe 时长+有声+抽帧，路径写进报告。
6. svfactory / toonflow 独立核验 PASS 的才 --no-ff 合入 closure，全量 pytest/lint 再过一次后 push，再按 GOLIVE_1016_TASK.md 部署方式只重建 hevi-api 并验收；失败立即回滚到 rollback-20261016 镜像。FAIL 的写 <UNIT>_FIX_R2.md 到其 worktree、用 /data/soffy/pi_loop_fix.sh 起下一轮（systemd-run --user，MemoryMax=4G），不合并。

## 报告
写 audit/patrol4/GOLIVE_1016_R3_REPORT.md：每项 PASS/FAIL+证据数字、合并 commits、远端 HEAD、git tag 与镜像 tag、验收结果。文中不要出现完成标记字样，仅最后一行写 `DONE GOLIVE-1016-R3-FINAL`；无法完成写 `BLOCKED GOLIVE-1016-R3-FINAL: 原因`（BLOCKED 时也必须带这个完整标记）。

## 安全
CPU-only，单进程渲染；不调付费 API；禁止 mock；不删 worktree 外文件、不清理磁盘、不 docker prune（/data <5G 写 DISK_FULL_NOTE.md 停止）；只动 hevi-api 容器。
