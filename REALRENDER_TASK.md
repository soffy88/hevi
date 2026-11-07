# REALRENDER_TASK — 口播流水线接真实转写/TTS并出真样片
背景：TALKEDIT_DONE.md 里端到端只产出了 JSON 配置（output_e2e/talkedit_sample/），没有真实 Whisper 转写、TTS、渲染，没有真视频。
要求：
1. 接入真实本地转写（faster-whisper / whisper.cpp，优先本机 GPU/CPU 可跑的；中文要准，带词级时间戳）。
2. 接入真实 TTS（优先本机已有或免费可用的中文 TTS，如 edge-tts/CosyVoice 等；保留用户自录音频选项）。
3. 渲染层真正输出 mp4：剪口癖/静音/多遍择优 → 字幕（避脸）→ B-roll（ghost 匹配）→ 动效卡点（talkcraft/huashu）→ SHOTLANG 分镜+QA → 9:16 与 16:9。
4. 样片：找 ~/projects/hevi 或本机已有口播素材；没有就用 TTS+数字/静态人像生成一段 60 秒左右中文口播当输入。跑两条：a) 真人口播剪辑成片 b) 纯配音动效解说片。
5. 对样片做 SHOTLANG QA 抽帧检查，问题修到通过。
交付 REALRENDER_DONE.md：接了什么、命令、两条 mp4 绝对路径、时长、QA 报告、剩余限制；末尾 REALRENDER DONE 或 REALRENDER BLOCKED。卡住超过两轮写明阻塞点停止。
