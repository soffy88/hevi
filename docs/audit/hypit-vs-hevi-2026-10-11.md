# hypit-ai/hypit 对照 Hevi：爆款拆解 → 复刻 → 换商品 → 批量变体 → 发布带货（2026-10-11）

审查范围：hypit 仓库 main（GitHub API：20,942★，创建 2026-07-30，最后推送 2026-10-10），Hevi 主仓 `/data/soffy/projects/hevi`（分支 closure/3o-v3-architecture-creative-baseline，HEAD 98e216af），agy 工作树 `/data/soffy/projects/hevi-publishkit`（feat/publishkit-3o，HEAD 686ba666）。服务器只读，未改、未重启；未调用付费 API。

## 一句话结论

- **hypit 的"克隆"不是自动拆片机**，而是"Claude/Codex 当导演"：用 `hypit transcribe`（WhisperX 词级）+ `hypit media tiles/boundaries`（带词标注的帧网格、ffmpeg 场景切点）让 LLM 逐段读懂参考片，写下 ANALYSIS.md / TIMELINE.md，然后**手写一份新的 SVML**，用 Seedance / GPT Image / Fish Audio 等**重新生成**全部人物和画面，再用无头 Chromium 渲染。它不复用原片素材。README 里三个示例的成本是 $1.07–1.15/条，全部依赖付费生成模型。
- **Hevi 有零件，没有这条链路。** 已有：ffmpeg 场景切分、faster-whisper 词级时间戳（CPU）、按讲话挑窗口切片（shorts_clip）、talkcraft 主播线（Wav2Lip CPU）、"参考片结构画像"代码、MatrixMedia 国内矩阵发布的适配器。缺的：①真正读懂参考片（结构/版式/字幕样式/节奏 → 可复用模板）；②以词为锚点、带变量槽的模板 DSL；③批量变体；④商品素材线；⑤能真正上传的发布。**发布环节里还有一个造假函数**（见 §2.6）。
- **建议**：用 3O 的 clean-room 方式内化 hypit 的**思路**，不要拷代码（它的许可证禁止拿来做多租户 SaaS）。具体做 4 件：参考片拆解卡、词锚定模板+变量槽、变体矩阵批量（自带 AI 标识和差异度闸门）、商品实拍素材线。全部能在 CPU 上做，不用花钱。生成式 A-roll（Seedance 一类）不做。
- **"批量发布带货月入几万"不现实，风险很高**：抖音和 TikTok Shop 的现行规则直接点名了"套模板批量同质化""复刻他人视频""搬运他人脚本""AI 虚拟人带货"，而且 2025-09-01 起强制要求 AI 标识。全自动矩阵上传本身也是风控对象。能走通的是"真实商品实拍 + AI 辅助剪辑 + 少量账号 + 人工把关"，单条赚多少取决于选品和投放，跟变体数量关系不大。

---

## 1. hypit 是什么，具体怎么运作

### 1.1 许可证（LICENSE 全文已读）
"修改版 Apache 2.0 + 附加条件"（徽章上写 "Apache-2.0 with conditions"，GitHub 识别为 NOASSERTION）。
- **可以免费做**：在自己的基础设施上自托管；给本组织用，**包括商用和给客户做的活**；一个组织自用的单租户部署。
- **需要商业授权**：(a) **多租户 / SaaS**：两个及以上外部方各有独立 workspace 就算，收不收费都算；(b) **商业再分发**：出售、收费授权，或把 hypit 及其衍生作品作为组件塞进提供给第三方的产品里。Fork 可以，但必须用同一许可证且不得牟利。(c) 不得去掉 CLI、run report、manifest 及由它们派生的用户界面里的名称、LOGO 和版权信息。
- 贡献者条款：作者可以随时把许可证改严或改松。
- **产出归用户**，作者不主张任何权利；第三方模型的产出另受各家条款约束。
- **对 Hevi 的含义**：Hevi 如果只给你自己用，直接部署 hypit 是允许的；但 Hevi 是带 auth/payment/credits 的平台形态，一旦对外提供就属于 (a)/(b)。所以**只能 clean-room 借鉴思路，不能 vendor 或改造它的代码**。

### 1.2 架构
- TypeScript monorepo，`packages/` 下约 90 个包：compiler、markup（SVML）、script、timeline-author、narrative-temporal（语义时间）、caption/caption-fine（词级卡拉 OK 字幕）、region-evidence（逐帧人脸框输入）、media-local（ffmpeg/ffprobe）、html-video / provider-html-local（无头 Chromium 渲染）、whisperx / provider-whisperx-local、yt-dlp、provider-image-opencv-local，以及一批付费 provider：seedance、gpt-image、nano-banana、seedream、wan、pixverse、minimax-h3、grok-imagine、elevenlabs-speech、fishaudio-speech、mimo-speech、volcengine-matting、provider-hypihub/monid/hiapi/pollo/tokendance/beatapi 等。
- 三种文件：`.svml`（作者源：`<script>` 台词带角色、`||` 分词组、`@{marker!}` 语义锚点，加组件和生成请求）、`.svs`（Recipe，样式和参数）、`.svrun`（这次运行要产出的 Target，以及复用哪些已有产物 Candidate）。
- Skill：`skills/hypit/SKILL.md`（`.claude/skills/hypit`、`.codex/skills/hypit` 是同一份），外加约 50 篇 references（reference-video、transformations、captions、caption-tracking、image/video/voice-direction、7 种格式 playbook：talking-head、街采、双人播客、排行榜、短剧、口播 demo、presenter explainer）。

### 1.3 "拆解 → 模板 → 变体"的实际机制
1. **获取**：`hypit download`（yt-dlp）。
2. **拆解**（`references/creation/reference-video.md`）：
   - `hypit transcribe --language zh|en…`：WhisperX 词级对齐，中文按字给时间。
   - `hypit media probe / cut / frames / tile / tiles --every-frame --transcript`：时间标注的帧网格，词标注在画面下方。
   - `hypit media boundaries`：ffmpeg 场景突变检测（`--rate/--threshold`），文档定位是"值得去看的位置"，不当作结构结论。
   - **然后由 LLM 自己看、自己写**：ANALYSIS.md（整体为什么有效）和 TIMELINE.md（按源片时间分段，记每个视觉系统的入场、持续、退场以及对应的词）。**没有自动版式识别、没有 OCR 模板提取、没有自动镜头分类。**
   - **人脸框**：示例用 **Google Video Intelligence（付费）** 和 YOLOv8 AnimeFace 测人脸，写成逐帧归一化 `[x,y,w,h]` 的 `.svs`，喂给 `region-evidence`，让字幕跟着说话人的头走。文档明确说可以换成"别的检测器或人工观察"，仓库本身不带检测器。
3. **模板化**：Agent 按理解手写 reference.svml。时间**锚在词上**（Selection/Moment），而不是锚在秒上。换台词或换配音后，字幕、揭示、音效会跟着新的词时间自动重排。
4. **变体**：`examples/interview/variants.md` 原文："swap-host、swap-lang、swap-ride 是彼此独立的变体，**每个变体有自己的 .svml 和 .svrun**"。swap-host 和 reference 的 diff 就是改角色名、台词和人物描述 prompt，再加上人脸跟踪数据。**仓库里没找到"一条命令出 100 个变体"的批量命令**（CLI 源码 commands 只有 environment/execution/results）。"100 variants" 的意思是同一套编排可以反复跑、只重新生成变化的部分（Run Candidate 复用），实际靠 Agent 写 N 个文件、跑 N 次 build。这句属于营销表述。
5. **渲染**：组件是 HTML/JS，provider-html-local 起无头 Chromium，用 `workers/maxWorkers` 并发按帧截图，再交给 ffmpeg 编码。示例用了 64 个 Chromium 进程。

### 1.4 哪些要钱，哪些能本地跑
| 步骤 | hypit 默认 | 本地可行 |
|---|---|---|
| 下载参考片 | yt-dlp | ✅ |
| 词级 ASR | WhisperX（hosted 或 local，CPU 可跑 small 模型） | ✅ |
| 帧网格 / 场景切点 | ffmpeg | ✅ |
| 理解参考片 | Claude/Codex（付费 LLM 订阅） | ⚠️ 要本地 LLM 才能零成本，而且质量会明显下降 |
| 人脸框 | Google Video Intelligence（付费）/ YOLO | ✅ 换本地检测器 |
| 人物 / 画面生成 | Seedance 2 Mini、GPT Image 2 等（付费） | ❌ 本地无 GPU |
| 配音 | Fish Audio / ElevenLabs（付费） | ✅ 换 piper / CosyVoice |
| 字幕、MG、渲染 | HTML + Chromium | ✅ CPU |
README 自己也说：只用字幕、动效和代码画面，不调生成模型也能出片，不产生模型费用。但三个爆款示例都是靠生成模型做的。

### 1.5 发布
**没有任何发布功能。** 仓库里 "publish/upload" 只出现在 npm 发布脚本和 HypiHub 的素材上传里，没有抖音、TikTok、视频号相关代码。README 讲的"当天发 50 个 Hook 变体"由用户自己去投放。

---

## 2. Hevi 现状（逐项核实，"有代码"和"真能出片"分开写）

### 2.1 参考片拆解：`hevi/video_intelligence/`（约 4,400 行）
- 有：`boundaries.py`（ffmpeg `select='gt(scene,0.35)'`，最短镜头 500ms）、`reference.py`（把分析结果抽象成"结构画像"：镜头时长分布、切点频率、景别/运镜/节奏/转场比例，**不拷原片内容**）、`rhythm.py`（**按位置**把镜头标成 HOOK/SETUP/BUILD/PAYOFF/CLOSE，文件里自己写着"never a claim of visual semantics"）、`reproduction.py`（复刻模式 EXACT_STRUCTURE/STYLE_ONLY/MOTION_ONLY，只有契约，没有渲染）、`patterns.py`、`transcript.py`（只接收已有转写，不自己做 ASR）、`case_analysis.py`。另有 API 路由 `api/routers/intelligence.py` 和 studio 接入。
- **真实性**：`artifacts/video_intelligence/qualification.json` 写着全 PASS，gold 20/20，recall@1=1.0，boundary F1=1.0，但是：
  - `semantic_visual_provider: "BLOCKED_PROVIDER"`，也就是没有任何画面语义理解；
  - 3 个 "real_artifacts" 都是 **Hevi 自己生成的片子**，`shot_count: 1`；
  - `real/reference_profile.json` 的画像是：6 秒单镜头，cut_frequency 0，景别/运镜全部 UNKNOWN，semantic_sequence ["OTHER"]。
  - **结论：管线骨架有，但从没对真实爆款跑过，全 1.0 的指标没有参考价值。**

### 2.2 reference_adapt（零成本版）：`hevi/layer4_legacy/zerolines/omodul_impl/_lines.py:372`
- 做法：用户**手工给出**参考片里的 N 个时间点（offsets）和 N 句新文案 → piper TTS → 每句配一段参考片画面，加 Ken Burns 推/拉/摇 + 调色 + circleopen 转场 + 字幕 + 合成 BGM。
- **不分析参考片结构**（不切镜头、不转写、不识别版式），本质是"用原片素材重配旁白再剪一遍"。
- 实测产物 `/data/soffy/projects/hevi-zero/out/reference_adapt/reference_adapt.mp4`：1280×720，19.2s，有音轨。源片 `nasa_Earth_Views…mp4` 用 ffprobe 量出来是 **320×180**，放大 4 倍，画面发糊（我看了 contact sheet：内容和旁白对得上，但清晰度很差）。之前"源片只有 320×180"的说法属实。
- **对带货的含义**：这条线是在**复用别人的画面**，和 hypit "全部重新生成"正好相反。拿别人的爆款这样剪，就是平台定义的搬运或非原创。

### 2.3 shorts_clip / openshorts（切片）
- zero 线 `shorts_clip`：faster-whisper（large-v3-turbo，CPU int8，`word_timestamps=True`，VAD）→ `pick_windows` 贪心找 18–32s 的连续讲话窗口 → 竖屏（模糊背景加前景）→ 每 4 个词一组的大字幕 → loudnorm。2026-10-11 在容器里实测 qa pass（STATE_LOG）。✅ **能出片**。
- `hevi/openshorts/virality.py`：参考 AI-Youtube-Shorts-Generator 的确定性"病毒度"打分（hook 词表、情绪、金句、实用信号），LLM 可选。用途是"从长视频挑好段落"，**不是"拆别人的爆款"**。

### 2.4 词级对齐、人脸框、重构图
- faster-whisper 词级时间戳在 zerolines/_media.py、talkcraft/_whisper.py、pipeline_lite/oprim_asr.py、production/audio_master_clock_workflow.py 里都有用。✅
- 人脸检测：talkcraft 的 yoloface ONNX（CPU，用于 Wav2Lip）；`hevi/production/reframe.py` 能把主体轨迹转成 ffmpeg crop 表达式（实现了"无证据不居中瞎裁"）。**"字幕跟着说话人的头走"这项功能没有**，但零件齐了。
- `.venv` 里**没装** scenedetect、mediapipe、rembg（见 openmontage 审计）。

### 2.5 模板、变体、商品
- Hevi 的 timeline 格式（`data/timelines/*.json`，共 4,247 个）：`clips[]`，每个 clip 有 `start_s/duration_s/source_in_s/text/transition/effect`，再分 `tracks.video/audio/captions`。**按秒定位，没有词锚点，也没有变量槽**。换一句台词，后面的时间全部要手工重排。
- `hevi/templates/`：数据库里的 `canvas_json` 模板（编辑器画布），不是可参数化的视频模板。
- 批量变体：grep 不到 variant 矩阵、hook 变体或批量渲染 runner。❌
- 电商：整个仓库只有 `hevi/assembly/promo_video_workflow.py`（"产品宣传片八阶段"，**文件里自称 skeleton**，负责简报、镜头卡、节拍、声音设计、自检这些计划部分；渲染走 remotion workflow），接在 `api/routers/embrace_runtime.py`。没有 SKU、价格、CTA 槽位，也没有商品抠图或白底图转场景的功能。❌
- 换主播：talkcraft（Remotion + Wav2Lip-GAN-96 + yoloface，CPU）在容器内 talking_head/avatar_spokesperson 横竖屏都 PASS，**每条 7–9 分钟，2 CPU，内存接近 4G 上限**（STATE_LOG 2026-10-11）。✅ 能出片，但只是"静态肖像对口型"，不能把参考片里的主播换掉。注意 Wav2Lip 权重的商用问题（之前评估过用 MuseTalk 替换）。
- 换语言：`hevi/dub/translate.py`：faster-whisper → **本地 qwen** 翻译 → **edge-tts** 合成 → 混流（代码里也有 deepl/openai 分支）。10-09 审计 PASS（底片是 HTML 卡片）。**它不在 zero 线的 PRODUCERS 列表里**，而且 edge-tts 依赖微软在线服务，不算真正离线。⚠️

### 2.6 发布（重点）
- `hevi/distribution/` + `adapters/matrixmedia.py`：通过子进程调用独立的 GPL 程序 MatrixMedia（矩媒，Electron + puppeteer 浏览器自动化，支持抖音/快手/B站/小红书/视频号/头条/百家号/番茄），不 import 其源码。还有 `adapters/local_file.py` 落盘交接。
  - 实际状态：MatrixMedia 0.11.3 在 `/data/soffy/qualification/MatrixMedia-v0.11.3/`，`artifacts/distribution/matrixmedia-qualification.json`（2026-09-14）显示 tar.gz 版本在 xvfb 下能启动，**`accounts` 返回 `[]`，一个登录账号都没有**；compose 和 .env 里**没配 `MATRIXMEDIA_BIN`**。**从未真正发布过一条。**
- `hevi/publishers/matrix.py`：MatrixMedia 交接契约（CLI/Webhook/落盘，"不假装 OAuth"）。
- ⚠️ **造假函数**：`hevi/layer4_legacy/platforms/oskill_impl/publish.py::publish_to_platform`（`hevi/platforms/oskill/publish.py` 是它的 shim）。只要传入 browser_context，它就**不做任何操作**，直接在 trail 里写 `{"step":"publish","ok":True}` 并返回 `status="published", reason="发布成功"`。"编辑信息、点发布、回填"三步只有注释。另外 `status = "failed" if task.is_available() else "skipped"` 这一行在 not-available 分支里永远得到 "skipped"，也是 bug。**这正是本项目准则里说的"不信 JSON 布尔值"的典型例子，应改成 fail-closed（NOT_IMPLEMENTED）。**（只读审计，未修改。）
- TikTok：platforms 下有 TikTok 枚举和 share_downloader（yt-dlp 下载），**没有上传功能**。
- **publishkit（agy 工作树 feat/publishkit-3o，未合入主分支，主分支没有 `hevi/publishkit/`）**：`build_publish_bundle` = ffprobe/blackdetect/silencedetect QA + sha256 + 在第 2 秒抽一帧当封面 + LLM 生成多平台文案（`llm_call(provider="qwen3_dashscope")`，阿里云 DashScope 是云 API，可能违反零成本规则；失败时有规则降级，只截取文稿前 100 字）。**只出"发布包"，没有任何上传。**白板线第二轮返工（PUBLISHKIT_FIX.md：白板内容是 "Beat 0/Your Brand" 占位，竖版不可读）还在进行中，工作树有未提交改动，可能有 agent 在跑，我没碰。

---

## 3. 对照表

| 能力点 | hypit | Hevi 现状 | 差距 |
|---|---|---|---|
| 下载参考片 | yt-dlp ✅ | share_downloader / video_catcher 用 yt-dlp ✅ | 无 |
| 镜头切分 | ffmpeg 场景检测（只当线索） | video_intelligence/boundaries.py ✅（未对真实爆款跑过） | 小：缺真实验证 |
| 词级 ASR | WhisperX | faster-whisper word_timestamps，CPU ✅ | 无 |
| 带词标注的帧网格 / 证据 | `media tiles --transcript` ✅ | 有 contactsheet.py，不带词标注 | 小 |
| **读懂结构 / 版式 / 字幕样式 → 模板** | LLM 逐段阅读，写 ANALYSIS/TIMELINE | reference.py 只有统计画像，语义 BLOCKED；从未对真实片子跑过 | **大** |
| **词锚定 DSL / 编译器** | SVML + 编译器，锚点在词上 | timeline JSON 按秒定位 | **大** |
| 换台词后自动重排 | ✅ 核心卖点 | ❌ | **大** |
| 换主播 | 重新生成人物（付费） | talkcraft 静态肖像 + Wav2Lip，CPU 7–9 分钟 ✅ | 中：只能做口播 |
| 换语言 | 改台词 + TTS + 自动重排 | dub：qwen + edge-tts ✅（依赖在线 TTS） | 中 |
| 换画幅 | Canvas / Frame | reframe.py 主体轨迹裁切 ✅；shorts 模糊背景 ✅ | 小 |
| 换商品 | 重新生成商品画面（付费） | ❌（promo_video_workflow 是 skeleton） | **大** |
| 跟头字幕 | region-evidence（检测要外部做） | yoloface 有，接线没有 | 中 |
| B-roll / 特效 / MG | HTML 组件库 + Chromium | Remotion（talkcraft/whiteboard）、ASS 字幕、ffmpeg | 中 |
| 批量变体 | 每个变体一份文件，靠 Agent 批量写 | ❌ | **大** |
| 并发渲染 | 64 个 Chromium worker | 容器 2 CPU；宿主 20 核、30G 内存 | 中 |
| 生成式 A-roll | Seedance / GPT Image | GPU 坏了，零成本规则下不做 | 不追 |
| AI 标识（显式 + 元数据） | 无 | 无 | **合规必需** |
| 发布到抖音 / 视频号 | 无 | MatrixMedia 适配器（0 账号、没配置）+ **造假的 publish_to_platform** | 大，而且先要去假 |
| 发布到 TikTok | 无 | 无 | — |
| 发布前 QA / 文案 / 封面 | 无 | publishkit（未合入，返工中） | 中 |

---

## 4. 值不值得内化，内化哪些

**值得，但只学"词锚定模板 + 拆解证据 + 变体矩阵"这套方法，不学"全量重新生成"。** hypit 最有价值的不是代码（不能拷），而是三个设计：①时间锚在词和语义上而不是秒上；②参考片先变成可读证据（带词的帧网格加切点），再由人或 LLM 写出结构说明；③变体等于同一编排换几个槽位，产物尽量复用。这三点都不需要 GPU。

按 3O 分层，在 `hevi/layer4_legacy/viralclone/{oprim_impl,oskill_impl,omodul_impl}` 下 clean-room 实现，外观层 `hevi/viralclone/adapter.py`。优先级如下：

| 优先级 | 内化点 | 内容 | CPU-only | 验收（真产物） |
|---|---|---|---|---|
| **P0** | 参考片拆解卡 `reference_breakdown` | ffmpeg 切点 + faster-whisper 词级 + 带词标注的帧网格（复用 contactsheet）+ 字幕区检测（帧差或 OCR，OCR 需另装 rapidocr-onnxruntime，CPU 可用）→ `breakdown.json`（镜头、句子/词、hook 时长、字幕位置和字号、节奏）+ 网格图。语义部分走仓库已有的 LLM 抽象；没有本地 LLM 时只出证据，并标 `semantic: UNKNOWN` | ✅ | 对 3 条真实带货爆款（用户提供）出卡，人工抽查切点和 hook 时间 |
| **P0** | 词锚定模板 + 变量槽 | 新增 `template.json`：段落（hook/卖点×N/证明/CTA）用"句或词锚点"定位，槽位有 `{product, selling_points[], price, cta, host, lang, aspect, hook_line}`；编译器：TTS → whisper 重新对齐 → 用新词时间生成 Hevi timeline JSON（兼容现有 4,247 份格式） | ✅ | 同一模板换两套文案，字幕和画面切换都落在新词上（逐帧抽查） |
| **P1** | 变体矩阵批量 runner | 笛卡尔积或抽样（hook × 主播 × 商品 × 画幅 × 语言），队列并发；每条都做 ffprobe/QA/sha256；**差异度闸门**（感知哈希和文案相似度太高就拒绝，防同质化）；**自动加 AI 标识**（GB 45438-2025：起始画面边或角，字高 ≥ 短边 5%，持续 ≥ 2s；同时写元数据） | ✅ | 跑 10 条，展示差异度矩阵，确认标识像素尺寸 |
| **P1** | 商品实拍素材线 | 输入用户的商品实拍视频或图片 → 抠图（rembg u2net ONNX CPU，需安装）→ 产品卡、Ken Burns、卖点贴片、价格 / CTA 组件。**不用 AI 生成商品外观**（平台要求和实物一致） | ✅ | 一个真实 SKU 出横竖两版 |
| **P2** | 跟头字幕 | yoloface 逐帧检测 → 和 reframe 坐标对齐 → ASS 字幕位置跟随 | ✅（慢） | 一条双人口播 |
| **P2** | 发布去假 + 半自动 | `publish_to_platform` 改成 fail-closed；MatrixMedia 只做"人工扫码登录 + 人工确认后单条发布"；把 publishkit 合入并换成本地 LLM | ✅ | 一个测试账号真发一条，以平台后台截图为准 |
| 不做 | 生成式人物 / 场景（Seedance 类）、64 路 Chromium | 付费，或需要 GPU | ❌ | — |

**CPU 产能估算（推算，未实测）**：ffmpeg 加 ASS 类的线（shorts_clip、reference_adapt）单条大约在分钟级；talkcraft 口播每条 7–9 分钟（2 CPU 实测）。100 条口播变体在容器 2 CPU 上大约要 12–15 小时。把容器 CPU 上限放到 8–12 核能快 3–5 倍，但宿主内存只剩约 9G 可用，要先评估。

---

## 5. "批量发布带货月入几万"的风险（简要，有来源）

1. **AI 标识是法定义务**：《人工智能生成合成内容标识办法》2025-09-01 起施行，要求显式加隐式标识，禁止删除或隐匿标识，平台要核验元数据并补加提示（cac.gov.cn/2025-03/14/c_1743654684782215.htm）。配套强制国标 GB 45438-2025 规定视频显式标识放在起始画面边或角、字高 ≥ 画面短边的 5%、持续 ≥ 2s（标准 PDF：xiongan.gov.cn 转载件）。
2. **抖音电商**：2025-09 抖音电商安全与信任中心公告，"不得利用 AI 生成虚拟人物或仿冒社会名人、特定专业身份进行带货变现"。2026 年已下架 AI 侵权视频 53.8 万条，处罚账号 4000 多个（界面新闻/腾讯新闻 2026-04-23，news.qq.com/rain/a/20260423A0417L00）。**这一条直接限制了"数字人批量带货"。**
3. **抖音生活服务 AIGC 规范（2026-04）**：必须主动声明 AIGC；"不得以未经授权的素材、**盗取搬运他人脚本**等训练或生成内容"；商品必须与详情页和实际履约一致。处罚包括警告、限流、扣信用分、限制商品推广等。一季度已处置 80 万条以上 AIGC 违规带货内容，涉及"内容搬运……发布不相关内容薅流量养号"（news.qq.com/rain/a/20260422A07AIU00）。**克隆别人的爆款脚本正好踩在这条线上。**
4. **TikTok Shop（英国站政策页，2026-04-27）**：非原创内容明确包括 "Recreating a video that directly mirrors the actions of another creator's content"，以及 "Using AI-generated content that results in duplicate or highly similar videos to other creators (e.g. using the same AI tool, prompt, avatar, or template)"。处罚包括下架、暂停权限、**永久冻结佣金**（seller-uk.tiktok.com/university/essay?knowledge_id=7841352058554114）。美国站 AIGC 政策还要求 AI 内容与实物的尺寸、颜色、材质等一致（seller-us.tiktok.com …knowledge_id=6837891779151617）。另外，大陆账号要做 TikTok 带货，还需要海外主体、店铺和网络环境，这本身是一道门槛。
5. **自动化上传的风控**：MatrixMedia 一类工具靠 puppeteer 模拟登录态、批量投稿，属于平台风控重点识别的"非官方自动化"和"矩阵养号"。多家二手媒体称抖音 2026 年封禁了"AI 托管账号""批量养号"，但我**没找到官方原文核实具体数字**，只作为方向参考。我的判断：同一设备或 IP、同一模板、高频定时投稿，被识别和连坐的概率很高。
6. **收益判断**：hypit 示例证明的是"能低成本做出像样的片子"，不能证明能卖货。带货收入主要看选品、佣金率、投流和账号权重。平台规则恰恰在打压"同模板量产"。合规且可持续的做法：**真实商品实拍 + AI 辅助剪辑和配音（加标识）+ 每条有实质差异 + 少量账号 + 人工审核后发布**。"月入几万"没有可靠依据，我不认为它是这套工具的合理预期。

---

## 6. 文件与来源
- 本报告：`/workspace/projects/eebf6af3-74b0-405d-a51b-f07939a41036/audit/hypit-vs-hevi-2026-10-11.md`
- hypit 原文缓存（README、LICENSE、SKILL.md、reference-video.md、local-tools.md、示例 svml 等）：`/workspace/projects/eebf6af3-74b0-405d-a51b-f07939a41036/work/hypit/`；reference_adapt 抽帧：同目录 `ra_contact.jpg`
- hypit 来源：https://github.com/hypit-ai/hypit（raw.githubusercontent.com/hypit-ai/hypit/main/…，GitHub API tree）
- Hevi 关键路径：`hevi/video_intelligence/`、`artifacts/video_intelligence/qualification.json`、`hevi/layer4_legacy/zerolines/omodul_impl/_lines.py`、`hevi/layer4_legacy/platforms/oskill_impl/publish.py`、`hevi/distribution/adapters/matrixmedia.py`、`artifacts/distribution/matrixmedia-qualification.json`、`hevi/dub/translate.py`、`hevi/assembly/promo_video_workflow.py`；`/data/soffy/projects/hevi-publishkit/PUBLISHKIT_*.md`
