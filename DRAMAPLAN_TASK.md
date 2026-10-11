# 任务 DRAMAPLAN：Toonflow 思路的章节事件图 + 三层审稿并入 storygraph；修短剧通道两个老 bug
任务名：DRAMAPLAN　　worktree：/data/soffy/projects/hevi-dramaplan　　分支：feat/dramaplan-3o　　优先级 P2

## 背景
- `hevi/storygraph/`（extract.py、schemas.py、shot_ir.py）已能从手稿抽取人物/事件/因果/关系；`hevi/season_planner/`（planner/preparation/dispatch/production）做季规划与镜头准备；`hevi/api/routers/shortdrama.py`、`hevi/shortdrama/screenwriter.py` 是短剧通道；`hevi/memory/store.py` 是对标 Toonflow 的本地向量记忆。
- 缺：长篇**按章节抽事件图谱再改编**（长篇不丢上下文），以及**决策 / 执行 / 监督三层审稿回路**（目前 LLM 一次出稿，season_planner 的 gate 只是重试最多 5 次）。
- STATUS.md 第 247–260 行记录了短剧通道两个未修的 bug（请先通读那一段）：
  1. **时长不控制镜头数**：`target_duration_s` 怎么设，单集都收敛到约 10 镜。根因在已安装的上游包 `oskill.script_writer._chapters_for_duration()`（<300 s 也至少 2 章）和 `oskill.storyboard_planner` 每章场景/镜头数不受时长约束。**上游包在共享 .venv 的 site-packages 里，禁止修改**——在 hevi 侧修：例如调用前算好镜头预算并以参数/后处理方式约束（合并/裁剪镜头、按预算重分配每章镜头数），入口 `hevi/pipeline/longvideo_orchestrator.py` 及其调用链。
  2. **每次全量重生成**：Editor 的自动返工（`hevi/tasks/task_service.py` 约 394、1746 行，`settings.auto_rework_max_rounds`）一旦触发就整轮重做所有镜头，成本翻倍。改成**只重生成未通过的镜头**（按镜头级 passed/consistency/diagnosis 判定，已通过的镜头原样保留并复用其产物），并保留“整轮重做”作为显式选项。另外 STATUS 提到 100% 镜头被判“参考图角色错配”，请查清这个判定是否有系统性问题（例如阈值、参考图选取、比对对象错位），能修就修，修不了写清根因。
  这两项都**不许为了验证去真调付费视频供应商**：用 fake/录制的 provider 响应写测试，证明镜头数随时长变化、返工只命中失败镜头。

## 要做
1. **章节事件图**（并入 storygraph，不新起模块）：长篇先按章节切分（可复用 script2video 的 novel_split），逐章抽事件（人物、地点、时间、事件摘要、因果/前后依赖、情绪强度、可改编度），再跨章合并为全书事件图（事件 ID 稳定、跨章人物合并），存进 storygraph schema（向后兼容，旧字段不动）；按“目标集数 × 每集时长”从事件图挑选/压缩事件生成改编大纲，接到 season_planner。长文本上下文用 `hevi/memory/store.py` 做章节摘要检索，避免把全文塞进一次 LLM 调用。
2. **三层审稿 agent**（oskill/omodul）：决策层（定改编目标与本集要覆盖的事件、节奏）→ 执行层（写分场/分镜稿）→ 监督层（按清单审稿：人物一致性、事件因果、时长/镜头预算、对白长度、禁忌内容、与事件图的覆盖率；给出结构化问题列表和打分）；不通过就带着问题列表回执行层**只改有问题的场/镜**，最多 N 轮（默认 2），每轮记录 diff 与分数，落盘 review_log.json。监督清单里能用确定性规则检查的（镜头数、时长、字数、人物名是否在角色表）必须用规则，不靠 LLM 打分。
3. **修两个 bug**（见上），并把 dramakey 任务将新增的 `shot_budget_for_duration` 的思路在短剧通道实现为 hevi 内部函数（名字一致，放 `hevi/layer4_legacy/script2video/oskill_impl/` 或 storygraph 合适处；dramakey 在另一 worktree 也会写同名函数，合并时去重，DONE 里注明）。
4. **LLM 通道**：本任务全部是文本 LLM 工作。只用免费/本地通道（见通用规则：HEVI_NIM_*、OPENCODE_*、TEAMOROUTER_*、omniroute free、ollama 兜底）。先写一个小的通道探测脚本，记录哪条通道可用、延迟、JSON 输出是否稳定，选定后写进 DONE。`longvideo_orchestrator` 里现在偏好 `qwen_cloud`（付费 DashScope）——**你的新代码和测试不得触发它**；为短剧规划增加一个显式的 `llm_channel` 配置项，默认走免费通道。

## 验收
- 单元测试（不调网络，用录制的 LLM 响应 fixture）：章节切分、逐章事件抽取解析、跨章合并、事件选择受集数/时长约束；三层审稿：首轮不通过 → 只改问题镜 → 通过；规则检查项；bug1：target_duration_s=30/60/120 s 时镜头数单调增加且落在预算内；bug2：10 镜中 3 镜失败时只重生成这 3 镜（断言 provider 调用次数=3，其余镜头产物路径不变）。
- 真实 LLM 小样（免费通道）：用一段 ≥3 章的公有领域中文文本（聊斋/古典小说片段，或自写原创），产出 `output/dramaplan_e2e/<run_id>/`：event_graph.json、adaptation_outline.json、episode_scripts/、review_log.json（至少一轮真实“监督→返修”）、record.json（通道、调用次数、耗时）。不要求出视频（本任务不碰像素），但若 dramakey 的 render 路径已在本机另一分支可用，**不要**去改它。
- 跑 test_storygraph.py、test_shortdrama_*.py、test_shot_preparation.py、test_script2video_kernel.py 不回归；lint 不新增失败。

## 参考思路（clean-room，只看思路不抄代码）
- Toonflow（MIT）：按章节抽事件图谱，再从图谱改编成剧本；多 Agent 分决策/执行/监督三层互审；本地向量记忆支撑长上下文。
- Jellyfish（Apache-2.0，已以契约方式吸收，见 hevi/production/references.py）：镜头先“准备”再生成，状态可恢复——返工只针对失败镜头与此一致。
- 火宝/waoowaoo：只看思路（剧本分析 → 分场 → 分镜），不看代码与提示词原文。

## 通用规则（必须遵守，审核方 2026-10-11）
- **仓库**：本 worktree 是 hevi（v6）的独立分支 `feat/dramaplan-3o`，基于 `closure/3o-v3-architecture-creative-baseline @98e216af`。只在本 worktree 内改动，只做本地 commit（英文 conventional commits）。**不要 push、不要 merge、不要 rebase 到别的分支；不要重启/修改任何 docker 容器或系统服务；不要动 /data/soffy/projects/hevi 主目录和其他 hevi-* worktree。**
- **共享 .venv**：`.venv` 是指向主仓库的软链，主仓和其它 agent 都在用。**禁止修改 `.venv/lib/python3.14/site-packages/` 下任何已安装包的源码（包括 oskill/oprim/omodul）**；需要改上游行为就在 hevi 内包一层。确需新依赖：只能 `pip install` 新包，且先 `pip install --dry-run` 确认不会升级/降级已有包，否则放弃该依赖；新增依赖写进 DONE 报告。
- **3O 分层**：照 talkcraft / zerolines 的内化方式——实现放 `hevi/layer4_legacy/<模块>/{oprim_impl,oskill_impl,omodul_impl}`，`hevi/<模块>/{oprim,oskill,omodul}/__init__.py` 是兼容 shim（`from hevi.layer4_legacy.<模块>.oprim_impl import *`），对外入口用 lazy delegate（重依赖 torch/diffusers 不得在 import 策略路径上加载）。oprim=纯原子能力（一个模型/一个工具调用），oskill=组合逻辑（无 IO 副作用优先），omodul=工作流/编排/落盘。读 docs/3O-MIGRATION-REPORT.md。开工先跑 `.venv/bin/python scripts/ci/run_3o_v3_lint.py` 记基线，结束再跑，**新失败数不得多于基线**。
- **Clean-room**：六个参考项目（火宝 huobao-drama、Toonflow、Pixelle-Video、Jellyfish、waoowaoo、ViMax）**一行代码都不复制**，也不要 git clone 它们进本仓库。火宝（CC BY-NC-SA 禁商用）、waoowaoo（ELv2）**只看思路**，连提示词原文也不要抄。思路说明见本文件的“参考思路”一节，按那里写，自己实现。DONE 报告里写一段“clean-room 声明”。
- **零成本**：不调用任何付费 API（DASHSCOPE/ALIBABA_MAAS/FAL/VIDU/WAVESPEED/OPENAI/火山/豆包/MiniMax/可灵/Seedance/nano-banana 一律不用，`.env` 里有这些 key 也不许用）。服务器 **无 GPU**（nvidia 驱动处于 Xid 154 故障态，**不要尝试修复或 reset GPU，不要跑 nvidia-smi 以外的 GPU 操作**），一切按 CPU 设计。云端出图/出视频只允许留**接口插槽**（provider 名 + 抽象方法 + 配置开关），默认关闭，测试里不得真调用。
- **CPU 资源**：机器同时跑着别的服务和 agent。torch 推理一律 `torch.set_num_threads(8)`（或环境变量 `HEVI_CPU_THREADS`，默认 8），不要并行开多个出图进程；单进程常驻内存 ≤6G（unit 上限 7G，超了会被 OOM kill）。
- **LLM**：只用免费/本地通道。先查仓库现有配置：`.env` 里的 `HEVI_NIM_*`（NVIDIA NIM 免费）、`OPENCODE_*`（OpenCode 免费模型）、`TEAMOROUTER_*`、本机 omniroute（:20128，只选标为 free 的模型）、本机 ollama（127.0.0.1:11434，llama3.2:3b，质量差，只作离线兜底）。每个 LLM 步骤必须有**确定性规则兜底**（无 LLM 时仍能跑通、只是质量低），E2E 报告写明实际用了哪条通道。
- **TTS/ASR**：piper（用法见 `hevi/layer4_legacy/zerolines/omodul_impl/_media.py` / talkcraft `_media.py` 的 PIPER/VOICES，中文 zh huayan）为默认；CosyVoice 引擎 http://127.0.0.1:17600 可选（冷启动约 75 秒，必须带 voice_ref，可用 builtin:zh_default）。字幕时间轴用 faster-whisper（/home/soffy/models/faster-whisper-large-v3-turbo，CPU int8）或按 TTS 实际时长切分。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **网络**：环境里的 HTTP(S)_PROXY 只给 Gemini 用（新加坡隧道，带宽很小）。下载模型/包时命令前加 `env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u ALL_PROXY -u all_proxy` 直连。huggingface/github 直连被墙：模型用 modelscope（`from modelscope import snapshot_download`，cache_dir=/data/soffy/models/ms）或 https://hf-mirror.com ；github 用 https://ghfast.top/<原始 URL>。已下载可直接用：`/data/soffy/models/ms/models/AI-ModelScope--sd-turbo/snapshots/master`、`AI-ModelScope--sdxl-turbo`、`madebyollin--taesd`、`taesdxl`（同目录下），基准脚本 `/data/soffy/projects/hevi-d3obench/bench.py`。
- **禁止造假（最重要）**：以前外部 agent 多次用 5 秒假 mp4、纯色/静帧视频、mock ASR、手写 gate 布尔值冒充完成，全部作废返工。本任务规定：
  1. E2E 必须真跑真模型，产物是真实 MP4；任何 `mock`/`placeholder`/`dummy`/纯色帧/复制旧产物 的兜底分支在 E2E 路径上一律禁止（单元测试里可以 mock，但必须放在 tests/ 且命名清楚）。
  2. 验收 gate 必须基于实测：ffprobe 量时长/分辨率/fps/音轨（有音轨且非静音：用 ffmpeg volumedetect，mean_volume > -45 dB）；抽 6 帧（均匀分布）拼 contact sheet；相邻抽帧像素差均值 > 阈值证明非静态；记录 MP4 和每张关键帧 PNG 的 sha256。gate 结果由脚本计算写入 `qa.json`，**不许手写或硬编码 passed=True**。
  3. 出图耗时、内存、模型名、seed、实际用了哪个 LLM/TTS 通道写进 `record.json`。
  4. 做不到就如实写进 DONE 报告的“未完成/卡点”，审核方宁可要真实的半成品。审核方会抽帧亲眼看画面、重算 sha256、grep 代码里的 mock 分支。
- **测试**：新增功能要有 pytest 单元测试（tests/test_<模块>_*.py，快速、不加载大模型，用小 fake 引擎），外加一个标 `@pytest.mark.slow` 或独立脚本 `scripts/e2e/dramaplan_e2e.py` 的真跑 E2E。跑相关旧测试确认没回归（至少 test_script2video_kernel.py、test_storygraph.py、test_zerolines.py、test_shortdrama_*.py）。
- **完成**：写 `DRAMAPLAN_DONE.md`：做了什么、文件清单、如何调用（Python API + CLI 示例）、E2E 产物路径与 ffprobe/sha256/qa.json 摘要、contact sheet 路径、lint 前后对比、测试结果、clean-room 声明、新增依赖、已知问题。然后 git commit。
- **续做友好**：可能因 Gemini 额度被中断后用同一提示词重启。每完成一个阶段就 commit 一次（`wip:` 前缀也行），并在 `DRAMAPLAN_PROGRESS.md` 记录已完成到哪一步；重启后先读它。
- 同一问题循环超过两次仍失败，停下来写进 DONE 报告，不要硬凑。

