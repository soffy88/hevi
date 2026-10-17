# 动态绘本流程补齐（worker brief）
参考思路（无许可证，禁止复制其代码/提示词原文，只借鉴流程）：https://github.com/lhlGitHub/hand-drawn-storybook-animation-skill
Hevi 已有：hevi/capabilities/handdraw.py、scene3d.fox_wheat/star_sea、storyplan、音色库、字幕、v3 的资产库/风格快照/镜头组。先读再复用，别重造。
要补：
1. 剧本自审轮：storyplan 增加"挑剔观众+动画导演"批判→修订流程（本地模型或规则，不调付费 API），输出问题清单与修订版，能力 storyplan.critique。
2. 分镜预览图：按镜头组生成一张漫画格分镜表（每格：景别 远/中/特写、画面描述、台词，铅笔线+淡彩风格，CPU 本地 PIL/SVG 即可），能力 storyboard.preview_sheet。
3. 绘本转场：翻页、湿笔刷晕开、纸页撕裂、铅笔线自绘出现、水彩晕染，接入 handdraw/时间线，能力 transitions.storybook。
4. 配音对齐：按本地 TTS 实际音频时长重排镜头时长，中英双语字幕与语音逐句对齐（误差<150ms），旁白/角色不同音色与语气；留安静段（BGM 自动避让+留白）。豆包仅做可选 provider 接口（无 key 时跳过，不得调用）。
5. 端到端：3 章节原创故事 → 自审 → 分镜表 → 水彩手绘动画+转场 → 本地配音+双语字幕 → mp4 ≥30 秒，ffprobe 验时长，字幕文件与音轨对齐测试。
测试：每项真实测试（禁止 mock 渲染/音频结果），全量回归相对基线无新增失败。
CPU-only，不调付费 API，不 push/合并/部署，不删 worktree 外文件，/data<5G 停。
报告 audit/storybook/REPORT.md，末行 `SBOOK-FINAL DONE <commit>` 或 `SBOOK-FINAL BLOCKED <原因>` 并 commit。
