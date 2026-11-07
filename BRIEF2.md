# 口播精剪 第二轮（必须做实，不许占位）
第一轮 KOUBO_REPORT.md 为占位实现：合成输入、无转写、无证据截图、无 HyperFrames、无 FCPXML，且未 commit。本轮按 BRIEF.md 全部做实：
1. 输入用真实中文口播：用 hevi 现有 talking_head/avatar_spokesperson 线（.env 已复制，可用 Pexels/edge-tts 等免费服务）本地生成 25 秒口播；不行就用 edge-tts 中文语音+一张人像静帧做真实有声输入。
2. faster-whisper 真实转写逐句时间戳；句子功能分类。
3. 用 hevi/core/browser_exec.py 截至少 2 个真实网页（如 github.com、wikipedia 相关页）作证据画面，报告真实成功率。
4. HyperFrames 渲染（/home/soffy/.local/bin/hyperframes，参考 hevi/storyfilm），人像全屏/小窗切换、逐词字幕、卡片。
5. 导出 FCPXML 工程包。commit 到 hark/koubo-cut。
跑 3 次验收并抽帧 contact sheet。写 KOUBO2_REPORT.md，末行 DONE。规则同 BRIEF.md。
