# STORYPLAN-R1：叙事/分镜/时间线三套结构 + 镜头任务单 + 选段（Hevi 全线通用，幼儿片优先）
来源：用户 2026-10-15 17:52 转来的「视频基础·上册」文章。核心：一条视频同时安排三套结构——叙事结构（信息何时出现，开场钩子）、镜头结构（这一刻看哪里）、时间线结构（同一秒有哪些画面/声音/字幕轨）；画面和声音分开写；每个镜头写「用途/开始/动作/结束/声音/验收」；AI 生成 5 秒只留合格的 2 秒；A-roll 主线 + B-roll（补充说明/交代环境/表达情绪/衔接）；没有新信息的镜头要砍。

## 准备
worktree /data/soffy/projects/hevi-storyplan（分支 feat/story-plan，已基于 origin/closure 创建）。先读：hevi 现有 ShotSpec（feat/shot-spec 已合入）、dirstyle、kids_gate、KIDS_ANIME_DIRECTION.md、CAPABILITY_CONTRACT.md；再读 /data/soffy/projects/hevi-motiondir 里正在做的 DirectorBrief（只读，不改那个 worktree），本单元的数据结构要能被 DirectorBrief 引用/嵌入，字段不冲突。不重造已有模块。

## 交付
A. StoryPlan 数据模型（JSON schema + pydantic）：三层
   1) 叙事层：beats（起因→经过→结果；可选倒叙"先给结果"）、开场钩子（类型：提问/冲突/好奇画面/先给结果）、每个 beat 回应哪个期待；
   2) 镜头层：Sequence → Scene（同一时间地点）→ Shot；每个 Shot 必填 用途、开始状态、动作、结束状态、声音、验收点、A/B-roll 角色（A 主线 / B 补充说明|交代环境|表达情绪|衔接）、镜头类型（建立/人物/插入/切离/空镜）、素材来源（生成/录制/已有/截图）、这一镜新增的信息；
   3) 时间线层：多轨（video、voice、music、sfx、subtitle），各自起止帧；允许画面换镜而旁白连续（J/L cut 风格）。
B. 一句话 → 自动补全 StoryPlan（规则+模板，不调付费 API）：先写顺口播稿，估读时长（中文按 ≤3.5 字/秒，幼儿更慢），再拆 beats → shots → timeline；可导出分镜表（Markdown/CSV/HTML，含编号、秒数、看到什么、听到什么、来源、验收）和镜头清单（按来源/角色分组，准备顺序可不同于播放顺序）。
C. 结构自检门 story_check（任一 FAIL 拒绝出片，给可读原因）：
   - 开场钩子：前 3 秒（幼儿片可配置 3–5 秒）内画面/声音/字幕至少两项交代主题或提出问题；
   - 声画对齐：旁白讲到某物时，画面在该区间内出现该物（用 shot 的信息标签对齐，误差可配置）；台词说完画面还没演到重点 → FAIL；
   - 冗余镜头：连续镜头新增信息为空 → FAIL/警告；
   - 每个 Shot 六项必填齐全；动作必须有明确结束状态；
   - 叙事闭环：开头提出的问题/期待在结尾被回应；
   - 时间线：无空白黑场、字幕不超出对应语音区间、各轨不越界；
   - 串接 kids_gate（幼儿语速、内容安全）。
D. 选段器 take_select：给定一段生成素材和对应 Shot 的验收点，按帧打分（运动完整度：开始→结束状态是否到达；首尾稳定度；突变/闪烁/形变检测用帧差+SSIM；无新信息的尾巴），输出最佳子区间 [in,out] 和理由；多个候选 take 选最优。CPU、确定性。
E. 审片 HTML：分镜表 + 时间线多轨可视化 + 每镜验收结果 + 选段 in/out 标记，单文件。
F. capability 注册：story_plan（生成/补全）、story_check（自检）、take_select（选段）；ShotSpec 与 GET /api/capabilities 可调用；非法参数拒绝。
G. 样片（幼儿 2–6 岁主题，至少 2 支，6–20 秒，1080p，16:9 与 9:16 各一，CPU 渲染，用仓内已有任一 CPU 线如 stickdir/handdraw/anatomy/artmotion 出画面）：例如「小水滴去哪儿了」（倒叙钩子：先看到云）、「小熊为什么洗手」（提问钩子）。每支附「无结构规划基线」对照：story_check 报告应显示基线 FAIL（钩子缺失/声画错位/冗余镜头至少命中一项）、规划版 PASS。附一个 take_select 演示：同一镜头 3 个候选 take，输出选中区间。同 seed sha256 一致。产物和 REPORT.md 放 audit/storyplan/（只提交小体积产物）。
H. pytest 真实运行（禁止 mock 渲染/自检/选段）：JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=<worktree>，Python /data/soffy/projects/hevi/.venv/bin/python；3O lint 失败数 ≤ 基线 4。

## 完成
提交到 feat/story-plan（不 push）。STORYPLAN_DONE.md：做了什么、测试命令与实测结果、样片路径、已知限制，最后一行 `DONE STORYPLAN-R1`。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；CPU-only，同时只渲染一个；不调付费 API；不动生产容器；不 push；禁止 mock。
