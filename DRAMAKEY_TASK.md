# 任务 DRAMAKEY：CPU 关键帧引擎 + 小说/剧本 → 真关键帧 → 配音字幕成片（ViMax 思路，clean-room）
任务名：DRAMAKEY　　worktree：/data/soffy/projects/hevi-dramakey　　分支：feat/dramakey-3o　　优先级 P0/P1

## 背景（2026-10-11 审计）
Hevi 的短剧/小说链条规划层基本齐了（storygraph 抽取 → season_planner 季规划 → preparation 镜头准备 → Subject），**缺“规划 → 像素”这一段**：
- `hevi/production/novel2video_workflow.py`（注释写明“不直接渲像素”，只写 novel2video_report.json）、`hevi/director/novel2video.py`（薄转发）、`hevi/layer4_legacy/script2video/`（oprim+omodul 约 1300 行：novel_split、character_fuse、camera_graph、image_score、variation、reference_select、portrait_triptych…）全部只出 JSON。
- `hevi/layer4_legacy/script2video/oprim_impl/image_score.py` 只看文件体积/魔数，不看像素——“双候选择优”是假的。
- 本地 SDXL+IP-Adapter（`hevi/image/sdxl_local_service.py`）要 GPU，且 base SDXL 中文老者/道士题材画错（STATUS.md 第 216 行：白须道士 → 银发少女）。GPU 现在坏了。

## 审核方 P0 基准结论（ubuntu26 CPU，8 线程，2026-10-11 实测，contact sheet 在审核方处）
| 引擎 | 512px 单张 | 768px | 峰值内存 | 中文提示直接输入 |
|---|---|---|---|---|
| **SD-Turbo + TAESD 解码（默认）** | 1 步 ≈3.5 s，2 步 ≈6.3 s，4 步 ≈13.2 s | 2 步 ≈17.5 s | 7.6（含加载时 fp16→fp32 转换峰值；常驻约 5 GB） GB | 语义错（CLIP 只懂英文） |
| SD-Turbo + 原 VAE | 1 步 10.5 s，4 步 19.2 s | 4 步 47.8 s | 8.4 GB | 同上 |
| SDXL-Turbo（+TAESDXL） | 1 步 13 s，4 步 31 s（TAESDXL：1 步 ≈8.7 s，2 步 ≈14.2 s） | 4 步 76 s | **16.4 GB（超出 unit 内存上限，禁用）** | 同上 |
| Taiyi-SD-1B-Chinese（中文 CLIP，SD1.x） | 20 步 ≈128（CFG 双倍计算，约 6 s/步） s | — | 未测（中途终止） GB | 能理解中文（灰袍老人），但没画出白须/道观，SD1.x 画质，太慢 → 不采用 |

**结论：默认 CPU 关键帧引擎 = SD-Turbo（`/data/soffy/models/ms/models/AI-ModelScope--sd-turbo/snapshots/master`，fp16 权重以 float32 加载）+ TAESD 解码（`/data/soffy/models/ms/models/madebyollin--taesd/snapshots/master`），512×512、2 步（预览/候选 1 步），guidance_scale=0。** 英文提示下白须道士、汉服书生、雨夜都市、漫画风都画对（见审核方 contact sheet），中文直接输入会画错 → **必须有“中文镜头描述 → 英文 SD 提示词”的翻译/改写步骤**（免费 LLM 通道；兜底用规则词典：人物/年龄/服饰/场景/光线/风格关键词表，保证离线可跑）。竖屏 9:16 用 512×896 或 448×768 再 Ken Burns 放大裁切，实测耗时写进 record。
可选高质量档（不默认）：SDXL-Turbo 画面更自然、东亚面孔更准，但峰值 16.4 GB 内存，只作为 `sdxlturbo_cpu` 引擎插槽实现（`available()` 检查 MemAvailable ≥18 GB 才可用），本任务 E2E 不用它。
许可证：SD-Turbo 是 Stability AI 社区许可（非商用研究免费，年收入 <100 万美元可商用，需在 DONE 报告和 NOTICE 中注明），所以引擎接口必须可插拔，方便以后换 Apache/MIT 权重。

## 要做
### A. 关键帧引擎 oprim（`hevi/layer4_legacy/keyframe/`，shim `hevi/keyframe/`）
1. 抽象接口 `KeyframeEngine`：`generate(prompt_en, *, negative=None, width, height, steps, seed, ref_image=None) -> KeyframeResult(path, seed, engine, model, sec, rss_mb)`；`name`、`available()`、`max_resident_mb`。
2. 实现：`sdturbo_cpu`（默认，常驻单例、懒加载、线程数可配、TAESD 开关）；`cloud_stub`（插槽：名字+配置项+`available()` 永远 False 除非显式 `HEVI_KEYFRAME_CLOUD=1` 且有 provider；**默认不调用，测试不许真调**）；`fake`（仅单元测试用，生成带文字的确定性测试图，**E2E 路径禁止选中**——E2E 脚本里断言 engine != fake）。
3. 注册表 + 选择逻辑：`resolve_keyframe_engine(config)`，环境变量 `HEVI_KEYFRAME_ENGINE`，默认 `sdturbo_cpu`。comicnarr 任务会复用这个接口，**接口签名定下来后写进 `docs/KEYFRAME-ENGINE.md` 并尽早 commit**。
4. 中文→英文提示词 oskill：`zh_shot_to_sd_prompt(shot, character_cards, style)`：LLM 改写（免费通道）+ 规则兜底；角色卡里的固定外观描述（英文 appearance tokens）每镜原样拼入，保证一致性。

### B. 真实择优 + 一致性 gate（替换假 image_score）
5. `image_score` 升级为像素级（保留旧函数做向后兼容）：CLIP 图文相似度（open_clip，CPU；本机已有 /home/soffy/models/open_clip，可用就复用，否则 modelscope 下载 ViT-B-32）+ 简单美学/清晰度（拉普拉斯方差、曝光直方图）+ 坏图检测（全黑/全白/大面积纯色）。每镜生成 **2 个候选（不同 seed）**，按综合分二选一，分数写 record（ViMax 的“双候选 + 择优”思路；VLM 择优留插槽，默认用 CLIP）。
6. 人脸相似度 gate：用 OpenCV 自带 DNN（YuNet 人脸检测 + SFace 识别，opencv_zoo 的 ONNX 模型，Apache-2.0，经 ghfast.top 下载；cv2 已装 5.0）。每个角色先生成**角色定妆图**（角色卡 → 3 个 seed 选最佳作为参考），之后含该角色的镜头与参考脸算余弦相似度，低于阈值（先实测分布再定，写进 DONE）就换 seed 重生该镜（最多 2 次），仍不过则标记 `identity_weak` 但保留（不阻塞成片）。无脸镜头（远景/背影）跳过 gate 并记录。
7. 角色一致性策略：IP-Adapter 在 CPU 上若能在 SD-Turbo 上跑通且单张 <20 s、内存在预算内就作为可选增强（`HEVI_KEYFRAME_IPADAPTER=1`）；否则默认用 **固定角色 seed 基数 + 固定外观 tokens + 参考脸 gate 重试**。先做默认方案，IP-Adapter 只在时间允许时尝试，结论写 DONE。

### C. ViMax 思路的小说规划补强（改 script2video，不新起炉灶）
8. 小说章节切块：现有 novel_split 按 ViMax 参数切块，补上**按章节标题（第X章/回）优先切分**、长章再按长度切。
9. 角色合并 + 角色卡：现有 character_fuse 补别名合并（同一人不同称呼：王生/王七/书生），产出 `CharacterCard{id,name,aliases,gender,age_band,appearance_zh,appearance_en_tokens,voice,ref_image,ref_face_embedding}`，落盘 characters.json。
10. 时长 → 镜头数：每镜默认 3–5 s，按目标总时长算镜头上限（这一点 dramaplan 任务也会在短剧通道修，你这里只管 novel2video/script2video 的路径，函数命名 `shot_budget_for_duration`，放 oskill，便于以后统一）。

### D. 从“只出 JSON”接到真成片（omodul）
11. `novel2video_workflow` / script2video 新增 `render=True` 路径（默认保持旧行为不变，旧测试必须仍过）：规划 JSON → 每镜关键帧（2 候选择优 + 人脸 gate）→ 镜头运动（推/拉/横移 Ken Burns，按 camera_graph 的镜头类型映射，ffmpeg zoompan 或 PIL 逐帧，25fps）→ 配音（piper 默认，旁白 + 角色对白可用不同 piper 音色/语速；CosyVoice 可选）→ 字幕（按 TTS 实际时长或 faster-whisper 对齐，烧录 + 输出 srt）→ 片段拼接 + 淡入淡出 → 成片 MP4（1080×1920 竖屏默认，横屏可选）。
12. 断点续跑：每镜关键帧/音频按内容哈希缓存，重跑只补缺失的镜头。

## 验收（真实出片）
- E2E 脚本 `scripts/e2e/dramakey_e2e.py`：输入用仓库里已有的中文小说片段（崂山道士手稿若找不到就用 `docs/` 或 tests/fixtures 里的中文文本，或自己写 1500 字以内原创短篇，**不要用受版权保护的现代小说**），目标 60–90 秒、10–18 镜，至少 2 个反复出场的角色。产物 `output/dramakey_e2e/<run_id>/`：final.mp4、keyframes/（含落选候选）、characters.json、record.json、qa.json、contact_sheet.jpg、subtitles.srt。
- qa.json 由脚本实测计算：ffprobe 时长/分辨率/fps/音轨；volumedetect；6 帧 contact sheet；相邻抽帧差 > 阈值；关键帧逐张 sha256；每镜 CLIP 分、人脸相似度、是否重生；总耗时、出图总耗时、峰值内存。
- 再做一个 30 秒的“剧本 → 成片”（script2video 路径）小样，证明两条入口都接通。
- 单元测试（fake 引擎，<30 s 跑完）覆盖：引擎注册/选择、提示词翻译兜底、双候选择优、人脸 gate 分支（有脸/无脸/重试耗尽）、镜头预算、缓存命中。

## 参考思路（clean-room，只看思路不抄代码）
- ViMax（MIT）：长篇按章节/长度切块 + 检索增强；角色在多段中出现时做“融合”得到统一角色档案；每个关键帧生成 2 个候选，再用视觉模型挑一个；镜头之间维护“镜头树/镜头图”决定景别和运动。
- waoowaoo（ELv2，只看思路）：先生成一致的角色图/场景图，再以它们为参考出分镜；多角色分别配音。
- 火宝（CC BY-NC-SA，只看思路）：一句话 → 剧本 → 角色设计 → 分镜 → 合成 的一条龙流程。

## 通用规则（必须遵守，审核方 2026-10-11）
- **仓库**：本 worktree 是 hevi（v6）的独立分支 `feat/dramakey-3o`，基于 `closure/3o-v3-architecture-creative-baseline @98e216af`。只在本 worktree 内改动，只做本地 commit（英文 conventional commits）。**不要 push、不要 merge、不要 rebase 到别的分支；不要重启/修改任何 docker 容器或系统服务；不要动 /data/soffy/projects/hevi 主目录和其他 hevi-* worktree。**
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
- **测试**：新增功能要有 pytest 单元测试（tests/test_<模块>_*.py，快速、不加载大模型，用小 fake 引擎），外加一个标 `@pytest.mark.slow` 或独立脚本 `scripts/e2e/dramakey_e2e.py` 的真跑 E2E。跑相关旧测试确认没回归（至少 test_script2video_kernel.py、test_storygraph.py、test_zerolines.py、test_shortdrama_*.py）。
- **完成**：写 `DRAMAKEY_DONE.md`：做了什么、文件清单、如何调用（Python API + CLI 示例）、E2E 产物路径与 ffprobe/sha256/qa.json 摘要、contact sheet 路径、lint 前后对比、测试结果、clean-room 声明、新增依赖、已知问题。然后 git commit。
- **续做友好**：可能因 Gemini 额度被中断后用同一提示词重启。每完成一个阶段就 commit 一次（`wip:` 前缀也行），并在 `DRAMAKEY_PROGRESS.md` 记录已完成到哪一步；重启后先读它。
- 同一问题循环超过两次仍失败，停下来写进 DONE 报告，不要硬凑。

