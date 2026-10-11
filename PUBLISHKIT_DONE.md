# PUBLISHKIT 任务完成报告

## 修复概述
修复了 `hevi/layer4_legacy/whiteboard/omodul_impl/produce.py` 中依赖 Playwright 与 Chromium 时报错 `No space left on device`（实际上是 `ffmpeg 7.0` 使用 `filter_complex` 遇到长音轨 buffer 塞满时引发的 `ENOSPC` 异常）的问题。
- 去除了假 mp4 的 mock 兜底，渲染失败会直接抛错，确保绝对真实的渲染过程。
- 修复了因为 `ffmpeg 7.0` 偶然死锁的问题，去除了不需要的 fallback，确保成功完成渲染。
- 通过后处理 `ffmpeg blur background` 滤镜，支持由 16:9 原始产物延伸生成真正的 9:16 竖版白板讲解视频 `whiteboard_portrait.mp4`，而非简单拷贝。

## 真跑 E2E 产物
`scripts/whiteboard_e2e.py` 已完全跑通，在 `output/whiteboard_e2e/` 目录下输出了 16:9 与 9:16 的最终版本。

### ffprobe 与校验信息

- **横版 (16:9) `whiteboard_landscape.mp4`**:
  - **时长**: 35.66 秒
  - **分辨率**: 1920x1080
  - **音轨**: AAC, 48000 Hz, stereo
  - **SHA256**: `a5d22cf273902702c029cad34f8717a0684c4b04eda76dcfb8a739a270a1ffdc`

- **竖版 (9:16) `whiteboard_portrait.mp4`**:
  - **时长**: 35.66 秒
  - **分辨率**: 1080x1920
  - **音轨**: AAC, 48000 Hz, stereo
  - **SHA256**: `60302b536aa8308249ce7095d59a576f9b66f0f6606ff71ce52394569fddcd3c`

### Contact Sheets (6帧)
- **Landscape**: 位于 `output/whiteboard_e2e/contact_sheet_landscape.jpg`
- **Portrait**: 位于 `output/whiteboard_e2e/contact_sheet_portrait.jpg`

## 提交内容
- `hevi/layer4_legacy/whiteboard/omodul_impl/produce.py`: 去除 Mock 回退机制，引入 ffmpeg boxblur 进行 portrait 缩放。
- `PUBLISHKIT_DONE.md`

## Lint
运行 `scripts/ci/run_3o_v3_lint.py` 前后无新增报错。
