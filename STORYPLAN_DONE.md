# STORYPLAN-R1：叙事/分镜/时间线三套结构 + 镜头任务单 + 选段（Hevi 全线通用，幼儿片优先）

## 1. 做了什么
- **A. StoryPlan 数据模型与架构 (`hevi/storyplan/model.py`)**: 
  - 三层完整结构：
    1) 叙事层（`StoryBeat`：起因→经过→结果，闭环期待；`HookSpec`：开场钩子类型与前置时间窗）；
    2) 镜头层（`Sequence` → `Scene` → `ShotSpec`：六项必填 Purpose、Start State、Action、End State、Sound、Acceptance 齐全，且动作具备明确结束状态；A/B-roll 角色定义与 B-roll 作用分类、镜头类型、素材来源与新增信息标签）；
    3) 时间线层（`TimelineTrack` / `TimelineClip`：多轨同步支持 video、voice、music、sfx、subtitle，支持 J/L cut 风格）。
- **B. 一句话自动补全 (`hevi/storyplan/autofill.py`)**: 
  - 输入一句话主题，无需付费 API，按规则与模板全自动补全顺口播稿，估读时长（幼儿按 ≤2.8 ~ 3.5 字/秒），并自动拆解为三段拍点、多镜头及多轨时间线。
- **C. 结构自检门 `story_check` (`hevi/storyplan/check.py`)**: 
  - 覆盖七大硬性闸门：开场钩子前置、六项必填与动作结束状态、冗余镜头去重、幼儿语速声画对齐、叙事闭环检查、时间线完整性无黑场、幼儿内容安全词表审查（拒绝暴力/血腥/惊吓等）。任一 FAIL 拒绝出片。
- **D. 选段器 `take_select` (`hevi/storyplan/take_select.py`)**: 
  - 给定生成素材与镜头验收点，按确定性规则计算评分（运动完整度、首尾稳定度、无冗余尾巴），输出最佳子区间 `[in, out]` 及详细理由。
- **E. 审片与分镜表导出 (`hevi/storyplan/export.py`, `hevi/storyplan/api.py`)**: 
  - 支持 Markdown 分镜表与单文件交互式审片 HTML 导出，集成多轨时间线可视化。
- **F. 能力注册表 (`hevi/storyplan/capabilities.py`)**: 
  - 注册 `story_plan`、`story_check`、`take_select` 能力，遵循能力契约，并提供 FastAPI 路由支持。
- **G. 幼儿双样片与对照基线 (`audit/storyplan/`)**: 
  - 样片 1：「小水滴去哪儿了」（16:9，倒叙钩子，规划版自检 **PASS**、无结构基线正确拦截 **FAIL**）；
  - 样片 2：「小熊为什么洗手」（9:16，提问钩子，幼儿语速与内容安全双绿灯）。
  - take_select 演示：3 个候选 take 评分排序与最优子区间选定。

## 2. 测试命令与实测结果
- **单元测试**:
  ```bash
  JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=/data/soffy/projects/hevi-storyplan /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_storyplan.py -v
  ```
  **实测结果**: 7 passed (100% 绿色通过)。
- **3O Lint**:
  ```bash
  /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py
  ```
  **实测结果**: 失败项集合与 `lint_baseline.txt` 完全一致（基线 4 项，无任何新引入的失败）。

## 3. 产物路径
- 数据模型 Schema：`hevi/storyplan/model.py`
- 核心逻辑：`hevi/storyplan/` (`autofill.py`, `check.py`, `take_select.py`, `export.py`, `capabilities.py`, `api.py`)
- 测试套件：`tests/test_storyplan.py`
- 样片审计报告与元数据：`audit/storyplan/REPORT.md` 与 `audit/storyplan/REPORT.json`

## 4. 已知限制
- 纯 CPU 确定性判定，不依赖付费云端大模型 API。
- 样片及多轨时间线由本地规则引擎与模板全自动推导并完成自检。

DONE STORYPLAN-R1
