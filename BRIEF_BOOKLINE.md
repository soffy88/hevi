# BRIEF BOOKLINE-1017：hevi 讲书 / 图片联播生产线（以 storybook 流程为底座）

## 背景
用户 2026-10-17 指示：现在就做完整的讲书线（类似抖音「原点档案」「枕上听书」「老张说史」「尘封档案」：音频播客式讲书/历史故事 + 配图 + 字幕，8–15 分钟，日更），以 storybook 流程为底座，hevi 已有能力复用，欠缺能力补上；并用实证研究"怎样讲书最吸引人听下去"，把结论落成可执行规则。
参考流程（MIT 许可，可借鉴结构与思路，引用代码需保留版权声明）：/data/soffy/ref/image-story-video-wizard（SKILL.md、references/、scripts/）。16 阶段：START→BRIEF→BENCHMARKS→WRITING_PACK→SCRIPT→VOICE→STORYBOARD→VISUAL_STYLE→CHARACTER_ANCHORS→IMAGE_PROMPTS→IMAGE_GENERATION→ASSET_QC→MUSIC→PREVIEW→FINAL_RENDER→FEEDBACK，关键节点需人确认。
本 worktree：/data/soffy/wt/hevi-bookline，分支 feat/bookline，从 integration/mergeall-1017@a82e6b9d 建出（已含 feat/storybook-flow、anatomy-upstream 等）。另一个代理正在 /data/soffy/wt/hevi-mergeall 做全量合并——不要碰那个目录和主检出 /data/soffy/projects/hevi。

## 先读再复用（别重造）
hevi/storyplan/storybook_pipeline.py、storyplan.critique、storyboard.preview_sheet、hevi/audio/storybook_voice.py（TTS 重排时长、双语字幕、BGM ducking）、transitions.storybook、hevi/capabilities/registry.py、音色库（voices）、字幕、v3 资产库/风格快照/镜头组、explainer/音频相关模块。先写 docs/bookline/REUSE_MAP.md：每个阶段 → 复用哪个现有模块 / 需新建什么。

## 要做
1. 项目状态机：hevi/bookline/ 下实现 16 阶段 PROJECT_STATE.json（阶段、已确认决定、产物路径、下一个待人确认问题），关卡：对标未确认不做写作包；文案未定稿不出完整配音；画风+样图未确认不批量生图；人物母版未确认不批量生图；预览未通过不终渲染；失败只回退到最早受影响阶段。能力注册 bookline.*，API 端点（api/main.py 风格一致）可创建/推进/确认/查看项目。
2. 对标与写作包：输入若干对标文案（txt），本地规则/本地模型分析选题、钩子、结构、节奏、转场、语言特点、收尾，生成写作包（zip：任务、资料、对标、写作要求、硬规则），供外部大模型（如 Kimi）写稿；支持导入成稿。
3. 文案质检：长稿（8–15 分钟，约 2400–4500 字）检查重复啰嗦、字数达标、钩子位置、每段信息密度；不足时指出是写作包哪层的问题（而不是让模型硬扩写）。
4. 配音：TTS 提供方适配层——默认 edge-tts（已安装，免费）+ 现有本地音色；预留豆包 Seed-TTS 2.0 适配器（读环境变量 key，无 key 时清晰报错，不在测试中调用）。同一段 ~20 秒文本批量试听 5–10 个音色；完整配音输出句级时间戳（JSON/SRT）。
5. 分镜：按配音时间戳切镜，每镜 6–8 秒可配置，输出分镜表（编号、旁白片段、起止时间、画面描述、景别、人物、文字卡），编号贯穿提示词/文件名/剪辑。
6. 画风锁定 + 人物母版：画风提示词固定块；人物母版（脸部+全身，年龄/体型/服装）登记，含人物的分镜引用母版做图生图。生图提供方适配层：本地离线后端（复用 handdraw/资产库/PIL 生成可用占位插图，真实渲染非 mock）+ 预留 GPT Image / 第三方 API 适配器（环境变量 key，串行队列、可断点续跑、单张失败不阻塞）。先样图 3–5 张关卡再批量。
7. 资产质检：缺图、尺寸比例、编号对齐、人物母版引用检查。
8. BGM 可选：复用 ducking；无 BGM 也能出片。
9. 剪辑渲染：图片跟配音走 + 轻推拉/横移（Ken Burns）、全程字幕、关键分镜文字卡（案名/人名/时间地点）；先出低清预览，再终渲染（ffmpeg，CPU）。
10. 端到端：用一个公有领域题材（例如《史记》或《资治通鉴》中一段）跑通 ≥3 分钟样片：写作包→（用提供的示例成稿）→edge-tts 配音+时间戳→分镜→本地生图→预览→成片 mp4，ffprobe 验时长，字幕与音轨对齐误差 <150ms 测试。
11. 实证研究（重要）：写 docs/bookline/ENGAGEMENT_RESEARCH.md——用可查证来源（能联网就 curl/搜索；论文、平台创作者指南、播客/有声书留存研究、注意力与叙事心理学研究、头部讲书/历史账号的公开结构拆解），回答"什么让人听下去、完播、订阅"：前 3/15/60 秒钩子、悬念与信息缺口、段落节奏与"爽点"间隔、语速/停顿/音色、画面切换频率、字幕、标题与封面、系列化与订阅转化。每条结论标来源和证据强度（强/中/弱/经验），不得编造来源。然后把可量化的结论落成规则：hevi/bookline/engagement_rules.py（文案打分器：钩子、信息缺口、爽点间隔、重复率、句长、口语化等）并接入第 3 步质检和写作包硬规则；写测试。
12. 文档：docs/bookline/README.md（使用流程、每个确认点、成本估算、外部 API 怎么配置）。

## 验收
- 每项有真实测试（禁止 mock 渲染/音频结果）；全量回归相对基线无新增失败（先记录基线）。
- 端到端样片存在且 ffprobe 通过；ENGAGEMENT_RESEARCH.md 每条结论有来源/证据强度。
- 不新增 >20MB 文件进 git（样片放 audit/bookline/ 时若大于 20MB 不入库，只入库元数据和截图）。

## 规则
CPU-only，不调付费 API（豆包/GPT Image 只写适配器不调用）；edge-tts 免费可用；不 push、不合并、不部署；不要动 hevi-mergeall 和主检出；不删 worktree 外文件；/data<20G 停下写 DISK_FULL_NOTE.md。每步 commit。
最后写 audit/bookline/REPORT.md：做了什么、复用了什么、新建了什么、测试基线 vs 最终、样片路径、研究要点摘要；末行 `BOOKLINE DONE <commit>` 或 `BOOKLINE BLOCKED <原因>` 并 commit。
