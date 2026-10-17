# SVFACTORY-R1 验收报告

## 1. 任务概述
吸收 `YILS-LIN/short-video-factory`（AGPL-3.0，Electron 桌面端）可迁移能力，采用 Clean-room 重新实现，专注于 Hevi 2–6 岁幼儿教育动画短片定位，严格过 `kids_gate` 质量安全闸门。

## 2. 核心增量实现
1. **批量预设生产与断点续跑 (`hevi.svfactory.batch`)**：
   - 实现了基于 preset 的持续出片队列。
   - 串行 CPU 渲染，支持断点续跑（跳过已渲染且 manifest 校验通过的片源）。
   - 每片独立生成 `.manifest.json` 与 `kids_gate` 质检结果。
   - 暴露 REST API：`POST /api/batch` 与 `GET /api/batch/{batch_id}`。
2. **素材文件夹自动混剪 (`hevi.svfactory.montage`)**：
   - 给定本地素材目录（视频/图片）与旁白时长。
   - 确定性随机 seed、自动选段、裁 9:16 / 16:9 画幅、防止连续同素材连击。
3. **幼儿字幕样式与本地 CPU 渲染 (`hevi.svfactory.renderer`)**：
   - 封装 `libass` 渲染与 CJK 字体（WenQuanYi Zen Hei），大字描边。
   - 本地 Piper TTS 合成，语速自动对齐控制（≤ 3.5 字/秒），保证 `kids_gate` 全项通过。
4. **能力契约注册 (`hevi.capabilities.svfactory`)**：
   - 注册 `svfactory.montage` 与 `svfactory.render` 到统一能力注册表。

## 3. 验收命令与执行结果
- **单元与集成测试**：
  ```bash
  uv run pytest tests/test_svfactory.py tests/test_svfactory_acceptance.py -v
  ```
  *结果*：全部通过（Passed 4/4）。
- **全量回归测试**：
  ```bash
  uv run pytest tests/test_svfactory.py tests/test_svfactory_acceptance.py tests/test_third_batch_capabilities.py -v
  ```
  *结果*：10 passed in 13.73s。
- **Lint 检查**：
  ```bash
  uv run ruff check hevi/svfactory hevi/capabilities/svfactory.py hevi/api/routers/svfactory.py tests/test_svfactory.py tests/test_svfactory_acceptance.py
  ```
  *结果*：All checks passed! (0 errors, ≤ 4)。

## 4. 样片路径与指标
- 批量样片输出目录：`output/svfactory/`
- 样片规格：1080p / 9:16 竖屏短片、含有声、FFmpeg 抽帧非黑、`kids_gate` 评分 ok（单镜头、光敏闪烁、响度 -16LUFS、语速、字幕大字、台词安全全通过）。

SVFACTORY-R1
