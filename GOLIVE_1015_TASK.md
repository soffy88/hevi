# GOLIVE-1015：收尾合并 + 上线（用户 2026-10-15 22:24「加快进度收尾上线」，已授权部署/重启 hevi-api）
工作目录：合并 worktree /data/soffy/projects/hevi-pubfix（主 checkout /data/soffy/projects/hevi 绝不修改）。

## 1. 合并已独立核验 PASS 的分支到 closure（--no-ff，逐个，冲突保留双方能力注册）
- feat/handdraw-line @42412590（patrol2 verify_r5 PASS）
- feat/motion-director @928c0e73（patrol2 verify PASS；若分支 HEAD 已更新到 700fbdd7 等仅文档提交，可用最新 HEAD，但须确认差异只有文档）
- 确认 feat/review-sheet @c9afc054 已在 closure（git merge-base --is-ancestor）；不在则合入。
- 不合：storyplan、vibe3d、partsci（还在做/未核验）。
每合一个跑该分支测试；全部合完跑全量 pytest（JWT_SECRET=test-only TMPDIR=.tmp，Python /data/soffy/projects/hevi/.venv/bin/python，以 soffy 运行），与基线比无新增失败；3O lint 失败数 ≤4。不满足就停，写 GOLIVE_1015_REPORT.md 说明，不 push 不部署。
满足则 `sudo -u soffy git push --no-verify origin HEAD:closure/3o-v3-architecture-creative-baseline`，记录远端 HEAD。

## 2. 部署 hevi-api（按 DEPLOY.md，构建上下文用 hevi-pubfix 这份干净代码，不用主 checkout）
- 先给当前运行镜像打回滚标签 hevi-cftunnel-hevi-api:rollback-20261015。
- `docker compose --env-file /root/hevi-cftunnel.env --env-file .env -f deploy/docker-compose-cftunnel.yml build hevi-api` 然后 `up -d --no-deps --force-recreate hevi-api`（.env 若 hevi-pubfix 没有，从主 checkout 只读复制，不改主 checkout）。只动 hevi-api，不碰 vault/web/gen_engine/mpt/live 相关服务。
- 验收：https://hevi.kanpan.co/api/health 200；GET /api/capabilities 能列出 scene3d、kids_manifest、agentops、review_sheet、anatomy、handdraw、director_brief/director_check/motion_director 等新能力；用 API 真实跑一条幼儿短片（零成本线，CPU）成功出片，ffprobe 时长/分辨率正常、抽帧非黑屏；容器日志无 traceback。
- 任一失败：立即回滚到 rollback-20261015 镜像并复核 health，报告里写原因。

## 3. 报告
GOLIVE_1015_REPORT.md：合并 commit 列表、测试数字、push 后远端 HEAD、镜像 tag、health/capabilities/样片验收结果（贴命令与输出摘要）、是否回滚。最后一行 `DONE GOLIVE-1015`（失败则 `BLOCKED GOLIVE-1015: 原因`，也算结束）。

## 安全
CPU-only；不调付费 API；不删 worktree 外文件、不清理磁盘、不 docker prune（/data <5G 写 DISK_FULL_NOTE.md 停止）；不改主 checkout；禁止 mock；不伪造验收。
