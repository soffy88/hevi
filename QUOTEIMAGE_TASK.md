# 任务：把 native-subtitle-quote-image 内化进 Hevi（3O）
上游源码：/data/soffy/projects/vendor/chengyi-ai__native-subtitle-quote-image（主文件 skills/native-subtitle-quote-image/SKILL.md 及其 scripts/references）。
目标：Hevi 成片（或任意本地视频）→ 3:4（或保留原比例）的「字幕金句长图」，两种模式严格分开：保留画面内已烧录字幕 / 用 ASR 文字稿重新绘制字幕。用于封面、小红书、朋友圈配图。
要求：
1. 新建 hevi/layer4_legacy/quoteimage/{oprim_impl,oskill_impl,omodul_impl}，外观层 hevi/quoteimage/adapter.py；输入 = 视频路径 + 模式 + 选句策略（自动选金句 / 指定时间段），输出 = PNG/JPG 若干 + record.json（含每张的源时间码）。
2. ASR 用本地 faster-whisper（复用 hevi/layer4_legacy/talkcraft/omodul_impl/_whisper.py 如可）；选句若需 LLM，用仓库已有的 LLM 抽象且可降级为规则选句（不依赖付费 key）。
3. 中文字体用系统 Noto CJK；逐张质检（上游的裁切/模糊/字幕完整性检查）接入 gates。
4. 接入：capability 注册 quote_image；给 Hevi 的产线产物加一个可选后处理钩子（默认关闭）。
5. E2E：scripts/quoteimage_e2e.py，用 output/talkcraft_e2e/ 下已有的成片和 /data/soffy/projects/hevi-zero/out/ 里两条带烧录字幕的成片各跑一次两种模式，产物放 output/quoteimage_e2e/。
任务名：QUOTEIMAGE
## 通用规则（必须遵守）
- 仓库：本 worktree 是 hevi（v6）的独立分支，基于 closure/3o-v3-architecture-creative-baseline @09558199。只在本 worktree 内改动，只做本地 commit，**不要 push、不要重启/修改任何 docker 容器或系统服务、不要动 /data/soffy/projects/hevi 主目录**。
- 3O 分层：参照已完成的 talkcraft 内化方式（hevi/layer4_legacy/talkcraft/{oprim_impl,oskill_impl,omodul_impl}，外观层 hevi/talkcraft/explainer_adapter.py），读 docs/3O-MIGRATION-REPORT.md；改完跑 `scripts/ci/run_3o_v3_lint.py`，新失败数不得多于基线（先记录基线）。
- Python：用仓库 `.venv/bin/python`。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **零成本**：不调用任何付费 API（火山/豆包/OpenAI/Atlas 等一律不用）。服务器无 GPU。TTS 用本地：piper（hevi-zero 用法见 /data/soffy/projects/hevi-zero/zl.py，中文 zh huayan 音色）或 CosyVoice 引擎 http://127.0.0.1:17600（每次约 75 秒冷启动，必须带 voice_ref，可用 builtin:zh_default）。ASR 用 faster-whisper，模型 /home/soffy/models/faster-whisper-large-v3-turbo（CPU，int8）。github/huggingface 在这台机器上被墙，下载 github 资源用 https://ghfast.top/<原 github url>；pip/npm 可用。
- **禁止造假**：上一次外部 agent 用 5 秒假 mp4 和 mock ASR 冒充完成，被整体作废。所有验收必须是真实产物：用 ffprobe 量时长/分辨率/音轨，抽帧做 contact sheet，记录 sha256；测试里 mock 只能用于单元测试，E2E 必须真跑。
- 上游代码是 MIT 协议：保留原作者版权与 LICENSE（放到 vendor 目录或 third_party/ 下并在 NOTICE 中注明）。
- 结束时写 `<任务名>_DONE.md`：做了什么、文件清单、如何调用、E2E 产物路径与 ffprobe/sha256、lint 前后对比、已知问题。然后 git commit（message 用英文 conventional commits）。
- 遇到同一问题循环超过两次仍失败，停下来把现状和卡点写进 DONE 报告，不要硬凑。
