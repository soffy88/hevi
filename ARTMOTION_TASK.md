# 任务：把 huashu-art-motion 内化进 Hevi（3O）
上游源码：/data/soffy/projects/vendor/alchaincyf__huashu-art-motion（先通读 SKILL.md、references/capabilities.md、references/动画语法/*、references/风格配方/*、scripts/）。
目标：给 Hevi 增加「风格化解说动画」能力——35 种代码绘制的艺术风格 + 9 种解说动画语法（3b1b、keynote_ui、finance_chart、kurzgesagt、vox、whiteboard、storytime、kinetic_type、presenter_explainer），全部本地 CPU 渲染（Playwright/manim/ffmpeg 等上游所用方式）。
要求：
1. 新建 hevi/layer4_legacy/artmotion/{oprim_impl,oskill_impl,omodul_impl}，外观层 hevi/artmotion/adapter.py；契约：输入 = 解说稿（或已有音频）+ 风格 id + 语法 id + 画幅(16:9/9:16)，输出 = MP4 + record.json。
2. 配音改走本地 TTS（见通用规则），上游火山/macOS say 路径禁用或保留为可选但默认关闭。
3. 接入 Hevi：render_narrated_storyboard(renderer="artmotion") 或环境变量 HEVI_EXPLAINER_RENDERER=artmotion；在 capability 注册表加 artmotion_explainer；API RunRequest 若已有 renderer 字段则加 "artmotion" 选项。
4. 上游 deliver.py 的「红灯不交付」质检要保留并接进 Hevi 的 gates。
5. E2E：scripts/artmotion_e2e.py，至少渲染 3 条 20–40 秒样片：(a) 16:9 + 3b1b 语法 + 一种风格；(b) 9:16 + kinetic_type + 水墨(17_ink)；(c) 16:9 + finance_chart + 另一风格。产物放 output/artmotion_e2e/，每条有 contact sheet。
6. 单元测试放 tests/，不能让现有测试新增失败。
任务名：ARTMOTION
## 通用规则（必须遵守）
- 仓库：本 worktree 是 hevi（v6）的独立分支，基于 closure/3o-v3-architecture-creative-baseline @09558199。只在本 worktree 内改动，只做本地 commit，**不要 push、不要重启/修改任何 docker 容器或系统服务、不要动 /data/soffy/projects/hevi 主目录**。
- 3O 分层：参照已完成的 talkcraft 内化方式（hevi/layer4_legacy/talkcraft/{oprim_impl,oskill_impl,omodul_impl}，外观层 hevi/talkcraft/explainer_adapter.py），读 docs/3O-MIGRATION-REPORT.md；改完跑 `scripts/ci/run_3o_v3_lint.py`，新失败数不得多于基线（先记录基线）。
- Python：用仓库 `.venv/bin/python`。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **零成本**：不调用任何付费 API（火山/豆包/OpenAI/Atlas 等一律不用）。服务器无 GPU。TTS 用本地：piper（hevi-zero 用法见 /data/soffy/projects/hevi-zero/zl.py，中文 zh huayan 音色）或 CosyVoice 引擎 http://127.0.0.1:17600（每次约 75 秒冷启动，必须带 voice_ref，可用 builtin:zh_default）。ASR 用 faster-whisper，模型 /home/soffy/models/faster-whisper-large-v3-turbo（CPU，int8）。github/huggingface 在这台机器上被墙，下载 github 资源用 https://ghfast.top/<原 github url>；pip/npm 可用。
- **禁止造假**：上一次外部 agent 用 5 秒假 mp4 和 mock ASR 冒充完成，被整体作废。所有验收必须是真实产物：用 ffprobe 量时长/分辨率/音轨，抽帧做 contact sheet，记录 sha256；测试里 mock 只能用于单元测试，E2E 必须真跑。
- 上游代码是 MIT 协议：保留原作者版权与 LICENSE（放到 vendor 目录或 third_party/ 下并在 NOTICE 中注明）。
- 结束时写 `<任务名>_DONE.md`：做了什么、文件清单、如何调用、E2E 产物路径与 ffprobe/sha256、lint 前后对比、已知问题。然后 git commit（message 用英文 conventional commits）。
- 遇到同一问题循环超过两次仍失败，停下来把现状和卡点写进 DONE 报告，不要硬凑。
