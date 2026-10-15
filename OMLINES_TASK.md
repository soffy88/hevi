# 任务 OMLINES：让 Hevi 13 条产线在零成本条件下全部真出片
背景：2026-10-09 审计，Hevi 声称 13/13 VERIFIED，实际只有 documentary_montage、localization_dub、shorts_clip 能交付；其余要么依赖已坏的 GPU/唇形引擎，要么依赖从未出片的付费云。已有一个独立的零成本重建：/data/soffy/projects/hevi-zero（zl.py、puppets.py、lines.py，11 条线全部通过实测 QA，用 hevi .venv 运行 `lines.py <line>`）。另有已合并的 talkcraft 渲染器（renderer="talkcraft"，含可选数字人 avatar）。
要做：
1. 读 hevi 的 13 条产线定义（产线注册表 / acceptance 矩阵 / scripts/qualify_autonomous_production.py），列出每条当前实际走的 provider 链。
2. 为每条线加「零成本档」（free tier）：优先复用 Hevi 内已有能力（talkcraft、CosyVoice、Remotion），缺的从 hevi-zero 以 3O 方式移植（不是 import 外部目录）。GPU/付费 provider 不可用时自动降级到零成本档，并在 record.json 里写明实际用了哪档。
3. 修 qualify_autonomous_production.py：talking_head/avatar 不再映射到已死的 EchoMimic/ComfyUI，改映射到 talkcraft host/avatar 布局；验收以 ffprobe+帧差+音轨实测为准，不再信 JSON 布尔值。
4. 跑全部 13 条线的零成本 E2E，产物 output/om_lines_e2e/<line>/，每条一张 contact sheet + measured QA；汇总表写进 OMLINES_DONE.md（每条：时长、分辨率、音轨、动态镜头占比、用到的档位）。
任务名：OMLINES
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
