# MERGE-1015B：补合 reviewsheet
背景：MERGE_1015_REPORT.md 叙述称 reviewsheet(c9afc054, feat/review-sheet) 已合并，但表里写"跳过"，且 `git merge-base --is-ancestor c9afc054 HEAD` 为否——实际没合入 closure。用户已批准合并+推送 patrol PASS 集合，reviewsheet 在内（独立 run_all.sh 退出码 0）。
步骤：
1. cd /data/soffy/projects/hevi-pubfix，确认分支 closure/3o-v3-architecture-creative-baseline，git status 干净（不干净则只 stash 自己的无关改动，不删文件）。
2. 先 `bash audit/reviewsheet/verify_r1/run_all.sh`（在 hevi-reviewsheet worktree 里）确认 exit 0；否则停止并写 MERGE_1015B_REPORT.md 说明。
3. git merge --no-ff c9afc054（冲突：registry.py 保留所有 capability 注册，NOTICE 保留双署名）。
4. 跑 reviewsheet 相关 pytest、tests/test_zerolines.py、scripts/ci/run_3o_v3_lint.py（失败集合必须等于基线4项：check_no_sibling_call、check_omodul_signature、check_enabled_pillars、check_oprim_keyword_only），pytest 设 JWT_SECRET=test-only。无新增失败才 push（git push --no-verify，非 force）。
5. 写 MERGE_1015B_REPORT.md（合并提交号、测试数字、lint），最后一行写 DONE MERGE-1015B 并 commit。
不部署、不重启服务、不调付费 API、不删 worktree 外文件、不清理磁盘（/data<5G 写 DISK_FULL_NOTE.md 停止）。
