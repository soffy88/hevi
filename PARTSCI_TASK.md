# PARTSCI-R1：粒子科普动画线（clean-room 内化 YouMind「Cinematic Particle Science」）
来源：用户 2026-10-15 22:07 发来 https://youmind.com/skills/particle-science-animation-krj6Q4F92euyg2 。该 skill 闭源，只有公开描述，所以按描述 clean-room 自研，不抓取/复制其提示词或网页代码。公开描述要点：输入科学概念 → 联网查证 → 分镜脚本先审批 → 收集有授权的真实照片 → 约 2 分钟（时长可调）粒子+矢量 Canvas 科普动画网页；风格=高级科学纪录片+博物馆级科学可视化：六层视差构图、满画幅不杂乱、多层细节矢量主体且光照清晰、全局 bloom 与胶片颗粒、金白星芒粒子文字、语义配色；手机小屏优化（只用少量大号中文关键词+清晰字幕）；经验证的文字粒子引擎、统一坐标规则、单轨背景音乐、逐镜截图审片；可回放或导出带声音视频。亮点：逐镜来源、机制防错、情绪配乐、审批后才生产。

Hevi 产品定位是 2–6 岁幼儿教育动画，所以本线做「幼儿科普」版本：概念如「为什么天是蓝的」「雨从哪里来」「种子怎么长大」；画面亮、暖、可爱，不吓人（黑洞等题材要温和处理），语速慢、关键词 ≤4 字。

worktree /data/soffy/projects/hevi-partsci，分支 feat/particle-science（基于已 push 的 closure）。先读现有 artmotion / webkit / amrules / scene3d / storyplan（若已合入）/ motion-director / kids_gate / layout 门，复用渲染与录制管线（Playwright CPU 逐帧确定性截帧 + ffmpeg），不重造。

## 交付
A. 粒子引擎（Canvas 2D，确定性：seeded RNG + 固定时间步，不依赖实时时钟/requestAnimationFrame 时间）：文字→粒子（中文字形采样成点，聚合/散开/星芒闪烁）、形状→粒子（SVG path 采样）、流体/轨迹类（水滴、光线散射、种子发芽）；粒子数随 CPU 预算自动降级。
B. 六层视差构图系统：远景/中远/主体/前景/粒子/文字字幕层，统一坐标规则（0–1 归一化 + 安全区，16:9 与 9:16 自适应，不硬裁）；相机推拉平移按层速度差。
C. 后期：全局 bloom（多尺度模糊叠加）、胶片颗粒（低强度，幼儿版默认更轻）、语义配色表（如 水=蓝、热=橙、生命=绿、能量=金），配色可配置。
D. 内容流程：概念 → 事实卡（每条事实标来源 URL；离线时用本地小知识库，禁止编造）→ 分镜脚本（复用 storyplan/ShotSpec 结构，审批状态字段：未审批不得渲染）→ 逐镜素材来源字段（CC0/公有领域图片或自绘矢量，记录许可）→ 渲染。机制防错：脚本里的因果机制要与事实卡一致（规则检查，不一致则 FAIL）。
E. 声音：CosyVoice 中文旁白（幼儿语速）+ 单轨背景音乐（仓内已有 CC0 或程序生成）+ ducking + loudnorm；字幕与旁白对齐。
F. 审片：逐镜截图 contact sheet + 自动检查（字幕在安全区、文字不重叠、关键词字号下限、主体占比、亮度/对比度、闪烁频率 ≤3Hz 防光敏、kids_gate）。
G. capability 注册：particle_text、particle_science_scene、parallax_layers；ShotSpec 和 GET /api/capabilities 可调用；非法参数拒绝。
H. 样片：2 支幼儿科普，30–60 秒，1080p（16:9 与 9:16 各一），如「为什么天是蓝的」「雨从哪里来」；同 seed sha256 一致；附「无粒子/无视差」基线对照帧。产物与 REPORT.md 在 audit/partsci/（只提交小体积产物）。
I. pytest 真实运行（禁止 mock 渲染/检查）：JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=<worktree>，Python /data/soffy/projects/hevi/.venv/bin/python；3O lint 失败数 ≤ 基线 4。

## 完成
提交到 feat/particle-science（不 push）。PARTSCI_DONE.md：做了什么、测试命令与实测数字（每帧渲染耗时、粒子数、sha256）、样片路径、已知限制，最后一行 `DONE PARTSCI-R1`。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；CPU-only，同时只渲染一个；不调付费 API；不登录/抓取 YouMind；不动生产容器；不 push；禁止 mock。
