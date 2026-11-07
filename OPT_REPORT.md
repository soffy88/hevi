# OPT_REPORT.md

## 改了什么
- `hevi/koubo_cut/pipeline.py`：接入 hevi 现有 wav2lip 口型驱动（`build_avatar_clip`，engine=wav2lip），人像从静帧循环改为真实唇动 talking head；音频填充至 30s；证据截图改为全屏叠加（≥2s）+ 圈注；保留逐词字幕与全屏/小窗切换。
- 新增 `PROGRESS_OPT.md`、`samples/opt/contact_sheet.jpg`。

## Commit
- 16a79abb feat(koubo_cut): opt - lipsync avatar, 30s target, fullscreen evidence

## 验收数据
- 3 次运行均 delivered，时长 30.000s，分辨率 1080x1920，音轨 aac。
- volumedetect：mean_volume -18.2 dB，max_volume -1.5 dB（3 次一致）。
- 证据截图：2/2 成功（github.com、wikipedia Artificial intelligence）。
- 口型相关度 lipsync_corr ≈0.70，帧数 900。
- 6 帧 contact sheet：`samples/opt/contact_sheet.jpg`（1/5/10/15/20/25s），帧中可见证据全屏截图与唇动差异。

## 仍存问题
- wav2lip 为 CPU 推理，唇动质量中等（corr ~0.7），非 MuseTalk 高清；未使用 Google Flow。
- HyperFrames 对比度/字号有轻微 warning，不影响成片。
- 产物为本地二进制，未推送。

DONE
