# 任务 OMRENDER：补齐 OpenMontage 级渲染运行时（clean-room）
背景：OpenMontage（/data/soffy/projects/vendor/calesthio__OpenMontage，AGPL-3.0），**只读设计，严禁复制代码/文本**。Hevi 现状：hevi/providers/hyperframes 已接、hyperframes CLI 已装（~/.nvm/versions/node/v26.4.0/bin/hyperframes），但从未有真实渲染产物；ink-theater 只拷了动作卡清单（hevi/studio/mocap.py），没有角色动画渲染器；hevi/creative/layer4/blender_workflow.py 有代码但机器没装 Blender。
要做：
1. HyperFrames：真实渲染 kinetic typography 与产品宣传两类合成，接进 Hevi runtime.select，作为 Remotion 之外的第二运行时。
2. SVG 角色动画：自己实现骨骼 SVG 角色 + 姿势库 + GSAP/HyperFrames 时间线（可用 Hevi 已有 mocap 卡数据，先确认 mocap-clips 的许可来源并在 NOTICE 注明），产出会表演的卡通角色短片；接进 character_animation 产线。
3. Blender：下载官方 Linux 便携版到 /home/soffy/opt/blender（不要 sudo/apt），CPU 渲染（Eevee 不可用时用 Cycles CPU、低采样），让 blender_workflow 真跑出一个 3D 场景镜头；three.js 场景可选（Playwright 截帧）。
4. 平台输出档：确认 16:9/9:16/1:1/21:9 各平台 profile 都能出。
E2E：scripts/om_render_e2e.py → output/om_render_e2e/：hyperframes 两条（各 15–30 秒）、角色动画一条（20–40 秒，带配音）、Blender 镜头一条（≥5 秒，720p 即可），全部 contact sheet。
任务名：OMRENDER
## 通用规则（必须遵守）
- 仓库：本 worktree 是 hevi（v6）的独立分支，基于 closure/3o-v3-architecture-creative-baseline @09558199。只在本 worktree 内改动，只做本地 commit，**不要 push、不要重启/修改任何 docker 容器或系统服务、不要动 /data/soffy/projects/hevi 主目录**。
- 3O 分层：参照已完成的 talkcraft 内化方式（hevi/layer4_legacy/talkcraft/{oprim_impl,oskill_impl,omodul_impl}，外观层 hevi/talkcraft/explainer_adapter.py），读 docs/3O-MIGRATION-REPORT.md；改完跑 `scripts/ci/run_3o_v3_lint.py`，新失败数不得多于基线（先记录基线）。
- Python：用仓库 `.venv/bin/python`。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **零成本**：不调用任何付费 API（火山/豆包/OpenAI/Atlas 等一律不用）。服务器无 GPU。TTS 用本地：piper（hevi-zero 用法见 /data/soffy/projects/hevi-zero/zl.py，中文 zh huayan 音色）或 CosyVoice 引擎 http://127.0.0.1:17600（每次约 75 秒冷启动，必须带 voice_ref，可用 builtin:zh_default）。ASR 用 faster-whisper，模型 /home/soffy/models/faster-whisper-large-v3-turbo（CPU，int8）。github/huggingface 在这台机器上被墙，下载 github 资源用 https://ghfast.top/<原 github url>；pip/npm 可用。
- **禁止造假**：上一次外部 agent 用 5 秒假 mp4 和 mock ASR 冒充完成，被整体作废。所有验收必须是真实产物：用 ffprobe 量时长/分辨率/音轨，抽帧做 contact sheet，记录 sha256；测试里 mock 只能用于单元测试，E2E 必须真跑。
- 上游代码是 MIT 协议：保留原作者版权与 LICENSE（放到 vendor 目录或 third_party/ 下并在 NOTICE 中注明）。
- 结束时写 `<任务名>_DONE.md`：做了什么、文件清单、如何调用、E2E 产物路径与 ffprobe/sha256、lint 前后对比、已知问题。然后 git commit（message 用英文 conventional commits）。
- 遇到同一问题循环超过两次仍失败，停下来把现状和卡点写进 DONE 报告，不要硬凑。

## 追加（用户 2026-10-11 05:36 批准）：并入 lanshu-create-ai-presenter-video 风格化讲解
上游：/data/soffy/projects/vendor/cclank__lanshu（MIT，可直接移植代码，保留 LICENSE 与 explainer/THIRD_PARTY.md 署名）。读 SKILL.md、explainer/STYLES.md、KITS.md、GOTCHAS.md、references/styled-explainer.md。
1. 把它的 9 种 HyperFrames 风格包（v1-editorial、v2-signal、v3-notebook、v4-paper、v5-comic、v6-cinematic(three.js 3D 一镜到底)、v7-drafting、v8-chalkboard、v9 黏土小城）作为 Hevi HyperFrames 运行时的主力模板，接成 renderer="hyperframes_styled"（或在 runtime.select 中按 style 选择），capability styled_explainer。含逐字字幕、章节条、结尾金句、复习帧、numpy 程序化音效。
2. 配音：MiniMax 一律不用。改为 Hevi 本地 TTS（CosyVoice 高质量档 / piper 快速档）+ faster-whisper 逐字时间戳生成它要的 story.json 词级时间；也支持传入用户自带配音。
3. 渲染时从 jsDelivr/Google Fonts 拉的 GSAP、three.js、字体子集，要在 ubuntu26 本地缓存/vendoring（jsDelivr 若不可达就走 npm 包或 ghfast 镜像），保证离线可渲。
4. 借鉴它的 8 阶段「由产物计算状态」(scripts/check_state.py) 与静止检测、响度验收，接进 Hevi gates。
5. 数字人路线不用移植（Hevi 已有 talkcraft avatar）。
E2E 追加：同一主题（例如 KV cache 或一个中文科普题）至少渲染 4 种风格（含 v6 3D 和 v8 黑板报），每条 30–60 秒中文，16:9，contact sheet + ffprobe。

## 网络补充（审核方 2026-10-11）
环境里的 HTTP(S)_PROXY 只用于 Gemini（经新加坡 SSH 隧道，带宽很小）。下载模型/软件包/大文件（modelscope、PyPI 镜像、npm 镜像、ghfast.top 等国内可达源）时，命令前务必加 `env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u ALL_PROXY -u all_proxy` 直连，否则会把隧道堵死、导致你自己的会话断线。github/huggingface 直连不通时用 https://ghfast.top/<github 原始 URL> 或 modelscope。
