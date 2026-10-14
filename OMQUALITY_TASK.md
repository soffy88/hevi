# 任务 OMQUALITY：补齐 OpenMontage 级后期增强、审片与知识库（clean-room）
背景：OpenMontage（/data/soffy/projects/vendor/calesthio__OpenMontage，AGPL-3.0），**只读设计，严禁复制代码/文本**。Hevi 缺：rembg、Real-ESRGAN、GFPGAN/CodeFormer 均未安装；Backlot（hevi/backlot、hevi/api/routers/backlot.py）只有事件流，分镜联系表审批门与回放较浅；没有成体系的制片知识库。
要做：
1. 增强工具（全部 CPU、本地权重，镜像 modelscope/ghfast.top）：抠像（rembg u2net 或 isnet）、超分（Real-ESRGAN ncnn-vulkan 不可用就用 PyTorch CPU 版 x2/x4）、人脸修复（GFPGAN 或 CodeFormer，注意权重许可，非商用的标注并默认关闭）、调色 LUT。接进 hevi/studio 工具目录，替换对应的空壳 op。
2. 审片：渲染后自检（ffprobe、4 点抽帧查黑帧/破图、静音/响度、字幕越界）+ 幻灯片风险评分（重复度、静态占比、运动弱、文字依赖）作为 compose 前门；确认 hevi/production/delivery_promise.py 真的在排产前生效。
3. Backlot：分镜联系表审批门（逐场景缩略图、提示词、成本、质量分，approve/reject 写回状态）+ REPLAY 回放；前端在 hevi-web 里补页面，pnpm/npm build 必须通过。
4. 知识库：用中文自写一套制片技能知识文件（按导演阶段：研究、提案、脚本、分镜、素材、剪辑、合成、审片；以及字幕、调色、音乐、配音表演、镜头提示词等手艺），放 hevi/skills/knowledge/，并让 director/planner 能按阶段加载。不得翻译或改写复制 OpenMontage 原文。
E2E：scripts/om_quality_e2e.py → output/om_quality_e2e/：对一条已有成片做抠像、2x 超分、人脸修复前后对比图；对 3 条已有成片出审片报告（至少一条应被幻灯片风险判红）；Backlot API 走一遍审批与回放。
任务名：OMQUALITY
## 通用规则（必须遵守）
- 仓库：本 worktree 是 hevi（v6）的独立分支，基于 closure/3o-v3-architecture-creative-baseline @09558199。只在本 worktree 内改动，只做本地 commit，**不要 push、不要重启/修改任何 docker 容器或系统服务、不要动 /data/soffy/projects/hevi 主目录**。
- 3O 分层：参照已完成的 talkcraft 内化方式（hevi/layer4_legacy/talkcraft/{oprim_impl,oskill_impl,omodul_impl}，外观层 hevi/talkcraft/explainer_adapter.py），读 docs/3O-MIGRATION-REPORT.md；改完跑 `scripts/ci/run_3o_v3_lint.py`，新失败数不得多于基线（先记录基线）。
- Python：用仓库 `.venv/bin/python`。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **零成本**：不调用任何付费 API（火山/豆包/OpenAI/Atlas 等一律不用）。服务器无 GPU。TTS 用本地：piper（hevi-zero 用法见 /data/soffy/projects/hevi-zero/zl.py，中文 zh huayan 音色）或 CosyVoice 引擎 http://127.0.0.1:17600（每次约 75 秒冷启动，必须带 voice_ref，可用 builtin:zh_default）。ASR 用 faster-whisper，模型 /home/soffy/models/faster-whisper-large-v3-turbo（CPU，int8）。github/huggingface 在这台机器上被墙，下载 github 资源用 https://ghfast.top/<原 github url>；pip/npm 可用。
- **禁止造假**：上一次外部 agent 用 5 秒假 mp4 和 mock ASR 冒充完成，被整体作废。所有验收必须是真实产物：用 ffprobe 量时长/分辨率/音轨，抽帧做 contact sheet，记录 sha256；测试里 mock 只能用于单元测试，E2E 必须真跑。
- 上游代码是 MIT 协议：保留原作者版权与 LICENSE（放到 vendor 目录或 third_party/ 下并在 NOTICE 中注明）。
- 结束时写 `<任务名>_DONE.md`：做了什么、文件清单、如何调用、E2E 产物路径与 ffprobe/sha256、lint 前后对比、已知问题。然后 git commit（message 用英文 conventional commits）。
- 遇到同一问题循环超过两次仍失败，停下来把现状和卡点写进 DONE 报告，不要硬凑。

## 网络补充（审核方 2026-10-11）
环境里的 HTTP(S)_PROXY 只用于 Gemini（经新加坡 SSH 隧道，带宽很小）。下载模型/软件包/大文件（modelscope、PyPI 镜像、npm 镜像、ghfast.top 等国内可达源）时，命令前务必加 `env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u ALL_PROXY -u all_proxy` 直连，否则会把隧道堵死、导致你自己的会话断线。github/huggingface 直连不通时用 https://ghfast.top/<github 原始 URL> 或 modelscope。
