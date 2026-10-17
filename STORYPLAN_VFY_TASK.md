# STORYPLAN 独立核验任务（你是核验员，不是开发者）
worktree: /data/soffy/projects/hevi-storyplan，分支 feat/story-plan，被核验提交 755888f8（DONE STORYPLAN-R1，STORYPLAN_TASK.md 是原任务书）。
**不要修改任何源码**，只核验；证据与结论写到 audit/storyplan/verify_r1/ 下。不信 STORYPLAN_DONE.md / REPORT.json 里的任何数字。

## 必做
1. 读 STORYPLAN_TASK.md，列出每条验收项，逐条独立复测，给 PASS/FAIL。
2. pytest：`JWT_SECRET=test-only PYTHONPATH=<worktree> .venv/bin/python -m pytest <storyplan 相关测试> -q`，记录数。
3. 3O lint：`scripts/ci/run_3o_v3_lint.py`，基线 4 项既有失败（check_no_sibling_call、check_omodul_signature、check_enabled_pillars、check_oprim_keyword_only），不得新增。
4. 写你自己的反例脚本 audit/storyplan/verify_r1/counter.py，至少：
   a) 开场无钩子 / 钩子超时窗 → story_check 必须拒；
   b) 镜头六项缺任一项、动作无结束状态 → 拒；
   c) 幼儿语速 >3.5 字/秒 → 拒；
   d) 叙事无结果(无闭环) → 拒；
   e) 时间线黑场/缺轨 → 拒；
   f) 至少 15 条有害/惊吓幼儿文本（含：揍、踢、勒脖子、踹飞、鞭打、毒药、炸弹、陌生人、辱骂、鬼怪吓人、血）→ 必须全拒，同时 10 条正常幼儿句（打开门、打招呼、打扫房间、小熊不怕黑……）不得误杀；
   g) take_select：给多条候选 take，必须真选出最优且给理由，不是固定取第一条；
   h) 一句话补全：用 5 个不同主题（含非动物主题），产物必须随主题变化，不得是同一模板换名字；
   i) 能力注册：GET /api/capabilities（或 hevi/capabilities/registry.py）里必须有 story_plan/story_check/take_select，并且能被 DirectorBrief 嵌入（读 hevi 里 motion_director 若不存在就只查接口形状）；
   j) E2E 路径 grep mock/placeholder/dummy/fake/passed=True 硬写。
5. 若有成片/样片：ffprobe 时长/分辨率/音轨，sha256，抽 6 帧 tile=3x2 到 audit/storyplan/verify_r1/sheet.jpg，用看图确认画面真实相关且适合 2–6 岁，不是文字卡。ffmpeg 在 ~/.local/bin。
6. 写 audit/storyplan/verify_r1/REPORT.md：结论首行 `VERDICT: PASS` 或 `VERDICT: FAIL`，逐条证据；FAIL 时另写 STORYPLAN_FIX.md（覆盖，列具体可复现问题与反例输入）。
7. 完成后在 STORYPLAN_VFY_DONE.md 最后一行写 `DONE STORYPLAN-VFY1`，并 git add 仅 audit/storyplan/verify_r1 与 STORYPLAN_VFY_DONE.md 、STORYPLAN_FIX.md 后 commit（不要提交 .venv/日志/lint 输出）。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-storyplan；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 STORYPLAN_VFY_DONE.md 最后一行写 DONE STORYPLAN-VFY1。
