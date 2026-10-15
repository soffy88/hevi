# 任务 OMFOOTAGE：补齐 OpenMontage 级「免费真实素材」能力（clean-room）
背景：OpenMontage（/data/soffy/projects/vendor/calesthio__OpenMontage，AGPL-3.0）。**只能读它理解设计，严禁复制其代码、提示词或文档文本进 Hevi**；自己重写。Hevi 现状审计：hevi/sourcing/corpus.py 有 CLIP 语料库，但 open_clip 没装，嵌入静默降为零向量，语义检索实际失效；scenedetect 未装；hevi/research 只是 158 行骨架。
要做：
1. 在 hevi .venv 安装 CPU 版 open_clip_torch（torch 已有 2.12），模型权重下载走 modelscope 或 ghfast.top 镜像（hf 被墙），放 /home/soffy/models/。CLIP 不可用时必须报错或在 record 里显式标 degraded，**禁止静默零向量**。
2. 语料库源：Archive.org、NASA Images API、Wikimedia Commons（免 key）+ Pexels（若 .env 已有 key 就用）。按镜头槽文本检索真实运动片段（不是静图 Ken Burns），带出处/许可元数据写入 provenance。
3. 装 PySceneDetect，接进素材切分与源片审查（hevi/verdict/source_media_review.py）。
4. 研究阶段 hevi/research：用仓库已有的免费 LLM 通道（找 .env / 配置里可用的本地或免费 provider；没有就用规则模板）跑真实 web 搜索 + 引用，输出 research_report.json 注入 screenplay。
5. 把 documentary_montage 产线改成默认走这条真实素材链。
6. Piper 作为快速免费 TTS 档接进 Hevi 的 TTS 选择器（piper 可执行与 zh huayan / en ryan 音色在 hevi-zero 已在用，见 /data/soffy/projects/hevi-zero/zl.py），CosyVoice 仍为高质量档。
E2E：scripts/om_footage_e2e.py → output/om_footage_e2e/：两条 60–90 秒纪录片蒙太奇（一条中文旁白 piper，一条无旁白纯音乐），镜头必须是真实运动片段（每个镜头帧间差异>阈值），附 provenance 与 contact sheet。
任务名：OMFOOTAGE
## 通用规则（必须遵守）
- 仓库：本 worktree 是 hevi（v6）的独立分支，基于 closure/3o-v3-architecture-creative-baseline @09558199。只在本 worktree 内改动，只做本地 commit，**不要 push、不要重启/修改任何 docker 容器或系统服务、不要动 /data/soffy/projects/hevi 主目录**。
- 3O 分层：参照已完成的 talkcraft 内化方式（hevi/layer4_legacy/talkcraft/{oprim_impl,oskill_impl,omodul_impl}，外观层 hevi/talkcraft/explainer_adapter.py），读 docs/3O-MIGRATION-REPORT.md；改完跑 `scripts/ci/run_3o_v3_lint.py`，新失败数不得多于基线（先记录基线）。
- Python：用仓库 `.venv/bin/python`。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **零成本**：不调用任何付费 API（火山/豆包/OpenAI/Atlas 等一律不用）。服务器无 GPU。TTS 用本地：piper（hevi-zero 用法见 /data/soffy/projects/hevi-zero/zl.py，中文 zh huayan 音色）或 CosyVoice 引擎 http://127.0.0.1:17600（每次约 75 秒冷启动，必须带 voice_ref，可用 builtin:zh_default）。ASR 用 faster-whisper，模型 /home/soffy/models/faster-whisper-large-v3-turbo（CPU，int8）。github/huggingface 在这台机器上被墙，下载 github 资源用 https://ghfast.top/<原 github url>；pip/npm 可用。
- **禁止造假**：上一次外部 agent 用 5 秒假 mp4 和 mock ASR 冒充完成，被整体作废。所有验收必须是真实产物：用 ffprobe 量时长/分辨率/音轨，抽帧做 contact sheet，记录 sha256；测试里 mock 只能用于单元测试，E2E 必须真跑。
- 上游代码是 MIT 协议：保留原作者版权与 LICENSE（放到 vendor 目录或 third_party/ 下并在 NOTICE 中注明）。
- 结束时写 `<任务名>_DONE.md`：做了什么、文件清单、如何调用、E2E 产物路径与 ffprobe/sha256、lint 前后对比、已知问题。然后 git commit（message 用英文 conventional commits）。
- 遇到同一问题循环超过两次仍失败，停下来把现状和卡点写进 DONE 报告，不要硬凑。
