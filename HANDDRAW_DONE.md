# HANDDRAW 单元完成报告

## 1. 调研与评估
- 已完成 `HANDDRAW_EVAL.md`，梳理上游 `sweety-handdraw-video` (v1.2.3, MIT) 流水线各阶段，明确 5 项内置依赖的许可证，核对 provenance ledger。

## 2. 渲染器 Vendor
- 已将上游渲染脚本与依赖 vendor 至 `hevi/layer4_legacy/handdraw/`，通过所有上游 smoke_test 与 unittest。

## 3. 产线接入 (`line=handdraw`)
- 接入主渲染架构 (`hevi/layer4_legacy/handdraw/line.py`, `pipeline.py`, `illustrator.py`)：
  - 支持横屏 `1920x1080` 与竖屏 `1080x1920` 双画布，竖屏适配独立构图和字号。
  - 支持 4 种风格：`1` (极简黑白线条)、`8` (水墨写意)、`10` (情绪叙事淡彩速写)、`17` (墨线绘本)。
  - 手部预设支持 `navy` (马克笔手臂) 与 `pen-only` (仅画笔)。
  - 配音对接 CosyVoice (127.0.0.1:17600) + piper CPU 兜底，整篇旁白母带锁定 + 时间戳对齐。

## 4. E2E 样片交付
- **横屏 (1920x1080)**：`「为什么越生气越容易做错决定」`
  - 路径：`artifacts/handdraw/landscape_anger/`
  - 片长：`45.637` 秒
  - 视频 SHA-256：`8749bbf6b0138a074ab170b487126f6ec4af9bcdae68772fd8853fb491753772`
  - 响度 LUFS (Input I)：`-17.06`
  - 交付物：MP4、封面 PNG、SRT、口播稿、检查记录。
- **竖屏 (1080x1920)**：`「复利效应」`
  - 路径：`artifacts/handdraw/portrait_compound/`
  - 片长：`50.954` 秒
  - 视频 SHA-256：`e196b673a3781fc1070105f5032d500a0abc7ad1c3613177d74786b8eb46ba2f`
  - 响度 LUFS (Input I)：`-16.90`
  - 交付物：MP4、封面 PNG、SRT、口播稿、检查记录。

## 5. 测试与契约注册
- 新增 `tests/test_handdraw_capabilities.py` 与 `tests/test_handdraw_deliverables.py`，全量通过：
  - 描线进度单调递增验证（ reveal map 单调递增）。
  - 产件完整性与唯一字幕轨验证。
  - 旁白时间戳与画面对齐验证。
- 能力契约注册（`hevi/capabilities/registry.py` & `hevi/capabilities/handdraw.py`），本线注册的全部能力名：
  - `handdraw.full`
  - `handdraw.storyboard`
  - `handdraw.narration`
  - `handdraw.illustration`

DONE HANDDRAW-R1
