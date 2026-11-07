# KOUBO2_REPORT.md — 口播精剪第二轮

## 实现
- `hevi/koubo_cut/pipeline.py`：真实 faster-whisper 转写（large-v3-turbo，逐句时间戳 + 词级时间戳）；句子功能分类（viewpoint/data/example/turn/cta）；Playwright 真实网页证据截图；HyperFrames CLI 渲染（人像全屏/小窗切换、逐词字幕、句子卡片、证据截图）；FCPXML 工程包导出。
- 输入：LuxTTS 生成 26.1s 中文口播 + 人像静帧合成的 1080x1920 有声视频 `work_input/input_portrait.mp4`。
- 归因：`SEECUT_KOUBO_ATTRIBUTION.md`（clean-room，仅方法）。

## Commit
- `8ea3ead7` (hark/koubo-cut)

## 3 次结果
| run | status | duration | resolution | audio | mean_volume | max_volume | evidence |
|---|---|---|---|---|---|---|---|
| run1 | delivered | 26.133s | 1080x1920 | aac | -17.6 dB | -1.5 dB | 2/2 |
| run2 | delivered | 26.133s | 1080x1920 | aac | -17.6 dB | -1.5 dB | 2/2 |
| run3 | delivered | 26.133s | 1080x1920 | aac | -17.6 dB | -1.5 dB | 2/2 |

- 成功数 3/3；平均耗时约 40s/次。
- 产物：`samples/run{1,2,3}/koubo_cut.mp4`（gitignored 二进制，本地保留）、`samples/run{1,2,3}/koubo_cut.fcpxml`、`samples/contact_sheet.jpg`。

## 截证据成功率
- 2/2（github.com、wikipedia Artificial intelligence），成功率 100%。

## 仍存问题
- 人像为静帧循环，非真实唇动；HyperFrames 为 draft 质量；FCPXML 仅主序列引用，未展开多轨素材。
- 单测 `tests/test_koubo_cut_capability.py` 通过。

DONE
