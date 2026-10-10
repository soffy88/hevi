# 任务：把 simon-skills 内化进 Hevi（3O）
上游源码：/data/soffy/projects/vendor/trustfuture__simon-skills（skills/video-common、skills/whiteboard-video、skills/investigation-video）。
目标两块：
A. 发布前套件（来自 video-common + investigation 的 covers-and-publishing/check-publish-copy/qa）：事实核查清单与出处记录、合规检查、封面生成与封面 QA、多平台发布文案（抖音/小红书/B站/视频号/YouTube 等，上游模板）、成片交付 QA（黑帧、静音、响度、字幕越界）。新建 hevi/layer4_legacy/publishkit/...，外观层 hevi/publishkit/adapter.py，输入 = 成片 + 文稿，输出 = publish_bundle/（cover.jpg、各平台文案 md/json、qa_report.json、fact_sources.json）。LLM 部分用仓库已有 LLM 抽象，无 key 时规则降级并在报告里标明。
B. 白板讲解产线（whiteboard-video）：Remotion 模板，复用 Hevi 已有的 hevi-remotion-talkcraft 的 node 运行时方式（node_modules 软链到 vendor 运行时，gitignore）；上游 Remotion/React 版本是钉死的，不要升级。TTS 把火山换成本地（见通用规则），字幕用 faster-whisper 对齐而不是火山字幕。新建 hevi/layer4_legacy/whiteboard/...，接入 render_narrated_storyboard(renderer="whiteboard")，capability whiteboard_explainer。
E2E：scripts/publishkit_e2e.py（对 output/talkcraft_e2e/explainer 的成片出完整 publish_bundle）和 scripts/whiteboard_e2e.py（一条 30–60 秒中文白板讲解，16:9 和 9:16 各一条），产物在 output/publishkit_e2e/、output/whiteboard_e2e/。
任务名：PUBLISHKIT
## 通用规则（必须遵守）
- 仓库：本 worktree 是 hevi（v6）的独立分支，基于 closure/3o-v3-architecture-creative-baseline @09558199。只在本 worktree 内改动，只做本地 commit，**不要 push、不要重启/修改任何 docker 容器或系统服务、不要动 /data/soffy/projects/hevi 主目录**。
- 3O 分层：参照已完成的 talkcraft 内化方式（hevi/layer4_legacy/talkcraft/{oprim_impl,oskill_impl,omodul_impl}，外观层 hevi/talkcraft/explainer_adapter.py），读 docs/3O-MIGRATION-REPORT.md；改完跑 `scripts/ci/run_3o_v3_lint.py`，新失败数不得多于基线（先记录基线）。
- Python：用仓库 `.venv/bin/python`。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **零成本**：不调用任何付费 API（火山/豆包/OpenAI/Atlas 等一律不用）。服务器无 GPU。TTS 用本地：piper（hevi-zero 用法见 /data/soffy/projects/hevi-zero/zl.py，中文 zh huayan 音色）或 CosyVoice 引擎 http://127.0.0.1:17600（每次约 75 秒冷启动，必须带 voice_ref，可用 builtin:zh_default）。ASR 用 faster-whisper，模型 /home/soffy/models/faster-whisper-large-v3-turbo（CPU，int8）。github/huggingface 在这台机器上被墙，下载 github 资源用 https://ghfast.top/<原 github url>；pip/npm 可用。
- **禁止造假**：上一次外部 agent 用 5 秒假 mp4 和 mock ASR 冒充完成，被整体作废。所有验收必须是真实产物：用 ffprobe 量时长/分辨率/音轨，抽帧做 contact sheet，记录 sha256；测试里 mock 只能用于单元测试，E2E 必须真跑。
- 上游代码是 MIT 协议：保留原作者版权与 LICENSE（放到 vendor 目录或 third_party/ 下并在 NOTICE 中注明）。
- 结束时写 `<任务名>_DONE.md`：做了什么、文件清单、如何调用、E2E 产物路径与 ffprobe/sha256、lint 前后对比、已知问题。然后 git commit（message 用英文 conventional commits）。
- 遇到同一问题循环超过两次仍失败，停下来把现状和卡点写进 DONE 报告，不要硬凑。
