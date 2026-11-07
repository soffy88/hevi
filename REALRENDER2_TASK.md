# REALRENDER2_TASK — 用笔记本上的 TTS 重跑真样片
用户说：笔记本上有 TTS。笔记本在同一 tailnet 上，候选节点 desktop-72avcfh-1（linux/WSL, 100.119.113.90）、desktop-72avcfh（windows, 100.68.226.13）。
1. 从 ubuntu26 通过 tailscale（tailscale ssh / ssh / 探测常见 TTS HTTP 端口如 CosyVoice 50000、GPT-SoVITS 9880、F5-TTS 7860、IndexTTS 等）找到笔记本上的 TTS 服务或程序，弄清调用方式。找不到就在 REALRENDER2_DONE.md 写明需要用户提供什么（服务名/端口/路径）后停止。
2. 在 hevi 中加一个远程 TTS 后端（配置化：host/port/音色），替换 REALRENDER 里的测试音轨。
3. 同时在 ubuntu26 装好 faster-whisper（中文、词级时间戳）真正接入转写。
4. 重跑 REALRENDER_TASK.md 的两条样片（口播剪辑成片、纯配音动效解说），确认音轨是真人声/真 TTS（抽音频转写回来对照稿子），做 SHOTLANG QA。
交付 REALRENDER2_DONE.md：TTS 在哪、怎么调、mp4 绝对路径、时长、转写对照结果、QA；末尾 REALRENDER2 DONE 或 REALRENDER2 BLOCKED。卡住超过两轮写明阻塞点停止。
