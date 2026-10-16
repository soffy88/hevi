# HEVI-V3：借鉴 aid-studio 补三块能力（worker brief）

参考：https://github.com/gzxx-2025/aid-studio（MIT，Java）。只借鉴设计思路；若移植任何片段，必须在 NOTICE 注明出处与 MIT 许可。禁止复制任何 AGPL 代码。

工作目录：本 worktree（分支 feat/v3-aid-gaps，基于 closure/3o-v3-architecture-creative-baseline）。不要动主 checkout /data/soffy/projects/hevi 和 hevi-pubfix。
Python：/data/soffy/projects/hevi/.venv/bin/python；测试：JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=. python -m pytest -q -p no:randomly。

先读现有相关代码再动手，复用而不是重造：hevi/subjects（reference_store/subject_service）、hevi/creative/layer4（persistent_identity、continuity_gate、importer）、hevi/style、hevi/director_lens/brief.py、hevi/storyplan、hevi/video/capability_guard.py、hevi/capabilities 注册表、hevi/canvas。

## 要做
1. 资产库（角色/场景/道具）：项目内可复用资产，含参考图、描述、角色绑定音色；从剧本自动抽取角色/场景/道具（复用 importer 逻辑，离线规则或本地模型，不调付费 API）；CRUD API + 能力注册 assets.library / assets.extract。
2. 多参考图融合：一个镜头可挂多张参考图（角色+场景+道具），统一占位符（如 @角色名）解析到对应参考图，按目标模型能力（capability_guard 的参考图上限）裁剪并给出明确报错；能力 image.multi_ref_compose。本地 CPU 实现合成预览（PIL 拼版/遮罩合成即可），真实生成走已有本地 provider。
3. 项目级风格快照 + 镜头组拆分：项目可锁定风格（风格预设+参数）并生成不可变快照 id，后续生成都带快照 id，可回溯；分镜按场景/时长把镜头拆成镜头组，每组生成视频提示词与首尾帧约束；能力 style.project_snapshot、storyboard.shot_groups。

## 验收（全部要有真实测试，禁止 mock 生成结果）
- 每块至少 8 个测试，含边界和失败用例（超参考图上限必须报错；改风格后快照 id 必须变且旧快照不变；同一剧本两次抽取结果确定）。
- 端到端：一段 3 场景剧本 → 抽资产 → 锁风格快照 → 拆镜头组 → 多参考图合成预览 → 用已有本地渲染出 ≥20 秒幼儿片，ffprobe 验时长。
- 全量回归无新增失败；3O lint 失败数不超过 4（基线 4 项）。
- GET /api/capabilities 能看到 5 个新能力。

## 规则
CPU-only，不调付费 API，不 push、不合并、不部署，不删 worktree 以外文件，不清磁盘，/data<5G 立即停止。每完成一步 commit。
最后写 audit/v3/GOLIVE3_REPORT.md：每项做了什么、commit、测试名与原始输出尾行、未完成项。末行写 `V3 DONE <commit>` 或 `V3 BLOCKED <原因>` 并 commit。
