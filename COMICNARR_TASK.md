# 任务 COMICNARR：Pixelle 思路的“漫画解说”零成本线（主题 → 脚本 → 一句一图 → TTS → BGM → Ken Burns → 成片）
任务名：COMICNARR　　worktree：/data/soffy/projects/hevi-comicnarr　　分支：feat/comicnarr-3o　　优先级 P1

## 背景
Hevi 的零成本线（`hevi/layer4_legacy/zerolines`，11 条 zero 线 + documentary_montage/localization_dub 保留原实现）能做“主题 → 文案 → 素材 + TTS + BGM → 合成”，但画面是 Pexels 素材/文字卡/PIL 动画，**没有 AI 配图**。Pixelle-Video 的核心卖点“每句一张 AI 图 + 解说”在 Hevi 里没落地（只在 docs/HEVI-ARCHITECTURE.md 当架构参考）。现在 CPU 上 SD-Turbo 每张 512px 图 3.5–6 s，这条线可以零成本做出来。

## 关键帧引擎（与 DRAMAKEY 任务共用接口）
另一个 agent 正在 `/data/soffy/projects/hevi-dramakey`（分支 feat/dramakey-3o）实现 CPU 关键帧引擎 oprim（`hevi/layer4_legacy/keyframe/`，shim `hevi/keyframe/`）。
- 开工先看 `/data/soffy/projects/hevi-dramakey/docs/KEYFRAME-ENGINE.md` 和该分支上 `hevi/layer4_legacy/keyframe/` 是否已存在（只读，不要改那个 worktree）。
- **已存在**：照它的接口签名在你的 worktree 里用（可以 `git cherry-pick` 那个分支上只涉及 keyframe 模块的 commit，DONE 报告写明 cherry-pick 了哪些 commit）。
- **不存在/不完整**：在你的 worktree 内按下面的**同一接口**自己实现最小版，放同一路径 `hevi/layer4_legacy/keyframe/`，以后合并时去重（DONE 报告写明这一点）：
  `KeyframeEngine.generate(prompt_en, *, negative=None, width, height, steps, seed, ref_image=None) -> KeyframeResult(path, seed, engine, model, sec, rss_mb)`；`resolve_keyframe_engine(config)`，环境变量 `HEVI_KEYFRAME_ENGINE`，默认 `sdturbo_cpu`；`cloud_stub` 插槽默认不可用；`fake` 只给单元测试。
- 默认引擎：SD-Turbo（`/data/soffy/models/ms/models/AI-ModelScope--sd-turbo/snapshots/master`，fp16 权重 float32 加载）+ TAESD（`/data/soffy/models/ms/models/madebyollin--taesd/snapshots/master`），512px，1–2 步，guidance 0。审核方基准：1 步≈3.5 s/张，2 步≈6.3 s/张，英文提示画质好、中文直接输入会画错 → 每句中文旁白要先改写成英文画面提示词（免费 LLM + 规则兜底）。漫画风加统一风格 tokens（例如 comic / manga / flat color / clean lineart 之类，自己调，挑最稳定的一组写进配置）。

## 要做
1. 新线 `comic_narration`（作为 zerolines 第 12 条 zero 线：在 `hevi/layer4_legacy/zerolines/oprim_impl/specs.py` 的 LINE_SPECS/ZERO_LINES 注册，`engine` 槽语义与现有 zero 线一致：`engine="zero"` 走本线；同时它的配图步骤内部用 keyframe 引擎槽 `keyframe_engine`）。若审核 docs/acceptance 矩阵、qualify 脚本里有“线清单”硬编码数字 11，要同步更新并保证相关测试仍过。
2. 流水线（omodul）：主题（或一段文章/小说片段）→ 解说脚本（6–14 句，每句 ≤30 字；免费 LLM，规则兜底：模板 + 关键词）→ 每句一个画面描述 → 中→英 SD 提示词 → 每句一张图（同一主角固定外观 tokens + 固定 seed 基数，保证人物大体一致；每句 2 候选用 CLIP 图文分择优，若 dramakey 的 image_score 升级已可用就复用）→ TTS（piper 默认；CosyVoice 可选）→ BGM（复用 hevi 现有 BGM/audio_library 能力，ducking 压低到解说下方）→ 每张图按句子时长做 Ken Burns（推/拉/平移交替，25fps，竖屏 1080×1920，图片先放大再裁避免糊边）→ 字幕烧录（漫画对白框或底部字幕二选一，做成选项）→ 转场 → 成片 MP4 + srt。
3. 风格模板：至少 2 个（`manga_bw` 黑白漫画、`comic_color` 彩色扁平），模板 = 风格 tokens + 负面词 + 字幕样式 + 转场。
4. 断点续跑：每句的图/音频按内容哈希缓存。
5. 接入：Studio/zerolines 现有入口能调用（照现有 zero 线的 `lines.py <line>` / `zero_line_workflow` 方式），给出 CLI 示例。

## 验收（真实出片）
- `scripts/e2e/comicnarr_e2e.py` 跑两条：① 主题输入（例如“为什么猫总爱把东西推下桌”，原创文案）`comic_color` 45–75 秒；② 一段公有领域中文故事（如聊斋/寓言，自写改编）`manga_bw` 45–75 秒。产物 `output/comicnarr_e2e/<run_id>/`：final.mp4、frames/（含落选候选）、script.json、record.json、qa.json、contact_sheet.jpg、subtitles.srt。
- qa.json 实测：ffprobe 时长/分辨率/fps/音轨；volumedetect（解说可闻、BGM 不盖过解说）；6 帧 contact sheet；相邻抽帧差 > 阈值（Ken Burns 必须真的在动）；每张图 sha256 且**互不相同**；每句 CLIP 分；用到的 LLM/TTS 通道。
- 单元测试（fake 引擎，快速）：线注册、脚本切句、提示词兜底、时长分配、Ken Burns 参数、缓存命中；跑 tests/test_zerolines.py 不回归。

## 参考思路（clean-room，只看思路不抄代码）
- Pixelle-Video（Apache-2.0，但本任务仍按 clean-room 自写，不复制其代码/workflow JSON）：输入主题 → 自动写文案 → 每句 AI 配图 → TTS 解说 → BGM → 合成；多模板（含漫画风）。
- 火宝/waoowaoo 与本任务无关，不要参考。

## 通用规则（必须遵守，审核方 2026-10-11）
- **仓库**：本 worktree 是 hevi（v6）的独立分支 `feat/comicnarr-3o`，基于 `closure/3o-v3-architecture-creative-baseline @98e216af`。只在本 worktree 内改动，只做本地 commit（英文 conventional commits）。**不要 push、不要 merge、不要 rebase 到别的分支；不要重启/修改任何 docker 容器或系统服务；不要动 /data/soffy/projects/hevi 主目录和其他 hevi-* worktree。**
- **共享 .venv**：`.venv` 是指向主仓库的软链，主仓和其它 agent 都在用。**禁止修改 `.venv/lib/python3.14/site-packages/` 下任何已安装包的源码（包括 oskill/oprim/omodul）**；需要改上游行为就在 hevi 内包一层。确需新依赖：只能 `pip install` 新包，且先 `pip install --dry-run` 确认不会升级/降级已有包，否则放弃该依赖；新增依赖写进 DONE 报告。
- **3O 分层**：照 talkcraft / zerolines 的内化方式——实现放 `hevi/layer4_legacy/<模块>/{oprim_impl,oskill_impl,omodul_impl}`，`hevi/<模块>/{oprim,oskill,omodul}/__init__.py` 是兼容 shim（`from hevi.layer4_legacy.<模块>.oprim_impl import *`），对外入口用 lazy delegate（重依赖 torch/diffusers 不得在 import 策略路径上加载）。oprim=纯原子能力（一个模型/一个工具调用），oskill=组合逻辑（无 IO 副作用优先），omodul=工作流/编排/落盘。读 docs/3O-MIGRATION-REPORT.md。开工先跑 `.venv/bin/python scripts/ci/run_3o_v3_lint.py` 记基线，结束再跑，**新失败数不得多于基线**。
- **Clean-room**：六个参考项目（火宝 huobao-drama、Toonflow、Pixelle-Video、Jellyfish、waoowaoo、ViMax）**一行代码都不复制**，也不要 git clone 它们进本仓库。火宝（CC BY-NC-SA 禁商用）、waoowaoo（ELv2）**只看思路**，连提示词原文也不要抄。思路说明见本文件的“参考思路”一节，按那里写，自己实现。DONE 报告里写一段“clean-room 声明”。
- **零成本**：不调用任何付费 API（DASHSCOPE/ALIBABA_MAAS/FAL/VIDU/WAVESPEED/OPENAI/火山/豆包/MiniMax/可灵/Seedance/nano-banana 一律不用，`.env` 里有这些 key 也不许用）。服务器 **无 GPU**（nvidia 驱动处于 Xid 154 故障态，**不要尝试修复或 reset GPU，不要跑 nvidia-smi 以外的 GPU 操作**），一切按 CPU 设计。云端出图/出视频只允许留**接口插槽**（provider 名 + 抽象方法 + 配置开关），默认关闭，测试里不得真调用。
- **CPU 资源**：机器同时跑着别的服务和 agent。torch 推理一律 `torch.set_num_threads(8)`（或环境变量 `HEVI_CPU_THREADS`，默认 8），不要并行开多个出图进程；同一时间只允许一个出图进程，峰值内存 ≤8G（本 unit 上限 10G，含 agy 自身，超了会被 OOM kill；SD-Turbo 实测峰值 7.6G，可试 `low_cpu_mem_usage=True` 或直接存一份 fp32 safetensors 降低加载峰值）。
- **CPU 出图互斥**：DRAMAKEY 与 COMICNARR 两个 agent 同时在这台机器上跑，都会加载 SD-Turbo。任何会加载出图模型的进程（E2E、调参脚本）必须先拿全机文件锁：Python 里 `fcntl.flock(open('/tmp/hevi_cpu_render.lock','w'), fcntl.LOCK_EX)`，或命令行 `flock /tmp/hevi_cpu_render.lock <cmd>`，用完即释放；不要常驻后台占着模型。
- **LLM**：只用免费/本地通道。先查仓库现有配置：`.env` 里的 `HEVI_NIM_*`（NVIDIA NIM 免费）、`OPENCODE_*`（OpenCode 免费模型）、`TEAMOROUTER_*`、本机 omniroute（:20128，只选标为 free 的模型）、本机 ollama（127.0.0.1:11434，llama3.2:3b，质量差，只作离线兜底）。每个 LLM 步骤必须有**确定性规则兜底**（无 LLM 时仍能跑通、只是质量低），E2E 报告写明实际用了哪条通道。
- **TTS/ASR**：piper（用法见 `hevi/layer4_legacy/zerolines/omodul_impl/_media.py` / talkcraft `_media.py` 的 PIPER/VOICES，中文 zh huayan）为默认；CosyVoice 引擎 http://127.0.0.1:17600 可选（冷启动约 75 秒，必须带 voice_ref，可用 builtin:zh_default）。字幕时间轴用 faster-whisper（/home/soffy/models/faster-whisper-large-v3-turbo，CPU int8）或按 TTS 实际时长切分。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **网络**：环境里的 HTTP(S)_PROXY 只给 Gemini 用（新加坡隧道，带宽很小）。下载模型/包时命令前加 `env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u ALL_PROXY -u all_proxy` 直连。huggingface/github 直连被墙：模型用 modelscope（`from modelscope import snapshot_download`，cache_dir=/data/soffy/models/ms）或 https://hf-mirror.com ；github 用 https://ghfast.top/<原始 URL>。已下载可直接用：`/data/soffy/models/ms/models/AI-ModelScope--sd-turbo/snapshots/master`、`AI-ModelScope--sdxl-turbo`、`madebyollin--taesd`、`taesdxl`（同目录下），基准脚本 `/data/soffy/projects/hevi-d3obench/bench.py`。
- **禁止造假（最重要）**：以前外部 agent 多次用 5 秒假 mp4、纯色/静帧视频、mock ASR、手写 gate 布尔值冒充完成，全部作废返工。本任务规定：
  1. E2E 必须真跑真模型，产物是真实 MP4；任何 `mock`/`placeholder`/`dummy`/纯色帧/复制旧产物 的兜底分支在 E2E 路径上一律禁止（单元测试里可以 mock，但必须放在 tests/ 且命名清楚）。
  2. 验收 gate 必须基于实测：ffprobe 量时长/分辨率/fps/音轨（有音轨且非静音：用 ffmpeg volumedetect，mean_volume > -45 dB）；抽 6 帧（均匀分布）拼 contact sheet；相邻抽帧像素差均值 > 阈值证明非静态；记录 MP4 和每张关键帧 PNG 的 sha256。gate 结果由脚本计算写入 `qa.json`，**不许手写或硬编码 passed=True**。
  3. 出图耗时、内存、模型名、seed、实际用了哪个 LLM/TTS 通道写进 `record.json`。
  4. 做不到就如实写进 DONE 报告的“未完成/卡点”，审核方宁可要真实的半成品。审核方会抽帧亲眼看画面、重算 sha256、grep 代码里的 mock 分支。
- **测试**：新增功能要有 pytest 单元测试（tests/test_<模块>_*.py，快速、不加载大模型，用小 fake 引擎），外加一个标 `@pytest.mark.slow` 或独立脚本 `scripts/e2e/comicnarr_e2e.py` 的真跑 E2E。跑相关旧测试确认没回归（至少 test_script2video_kernel.py、test_storygraph.py、test_zerolines.py、test_shortdrama_*.py）。
- **完成**：写 `COMICNARR_DONE.md`：做了什么、文件清单、如何调用（Python API + CLI 示例）、E2E 产物路径与 ffprobe/sha256/qa.json 摘要、contact sheet 路径、lint 前后对比、测试结果、clean-room 声明、新增依赖、已知问题。然后 git commit。
- **续做友好**：可能因 Gemini 额度被中断后用同一提示词重启。每完成一个阶段就 commit 一次（`wip:` 前缀也行），并在 `COMICNARR_PROGRESS.md` 记录已完成到哪一步；重启后先读它。
- 同一问题循环超过两次仍失败，停下来写进 DONE 报告，不要硬凑。

