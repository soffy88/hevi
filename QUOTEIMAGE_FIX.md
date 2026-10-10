# QUOTEIMAGE 核验不合格（审核方 2026-10-11 06:20 CST）——必须修复

1. **native 模式产物错误**：vid_0_native/01_quote_image.jpg 只有第一张（hero）是清晰画面，下面 3 条"字幕条"全是模糊的色块，没有任何可读字幕——字幕带位置/裁切取错了。必须先检测源视频里烧录字幕的真实位置（可用上游的方法，或按帧比较/whisper 时间点抽帧确认），每条字幕条必须含可读的完整字幕文字。
2. **质检门有假判**：`quality_gates.py` 的 subtitle_completeness 写死 `passed: True`（注释 "dummy check"）。必须真实检测（例如字幕带内边缘/文字像素密度、上下边界是否截断文字、相邻条是否重复），能把问题 1 这样的图判为不合格。record.json 里每张图记录所有 gate（目前只记录了 resolution）。
3. **占位数据**：produce.py 非 auto 策略时用写死的 "第一句台词/第二句台词" 兜底。改为真实实现"指定时间段"策略（参数传入时间段，取该段 ASR 句子）；没有输入就报错，不准占位。
4. **E2E 不完整**：任务要求 output/talkcraft_e2e/ 成片也跑两种模式。成片在 /data/soffy/projects/hevi-talkcraft/output/talkcraft_e2e/（explainer/explainer_landscape.mp4、talking_head/talking_head_landscape.mp4 等，这些带烧录字幕），用它们跑，路径可做参数。
5. script 模式各行字号不一致（同一张图里字幕大小跳变），统一字号/行高。
6. 补单元测试 tests/test_quoteimage.py（gate 能判出坏图、时间段策略），用 `.venv/bin/python -m pytest` 跑通。

验收：4 条源视频 × 2 模式，每张图审核方会肉眼看；DONE 里给出每张图尺寸、sha256、源时间码、gate 数值；lint 新失败不多于基线。修完更新 QUOTEIMAGE_DONE.md 并 git commit。不要询问，直接做。
