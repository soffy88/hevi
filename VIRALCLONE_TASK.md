# 任务 VIRALCLONE：clean-room 内化"参考片拆解 → 词锚定模板 → 变体批量"（CPU、零成本）

## 背景（先读）
2026-10-11 审查报告（已复制到本 worktree：`docs/audit/hypit-vs-hevi-2026-10-11.md`）对照了 hypit-ai/hypit 与 Hevi。结论：Hevi 有零件（ffmpeg 切点、faster-whisper 词级时间戳、shorts_clip、talkcraft、reference.py 结构画像、zerolines reference_adapt），**没有链路**：不会读懂参考片、timeline 按秒定位没有词锚点和变量槽、没有批量变体、没有商品素材线、没有 AI 标识。

**许可证红线**：hypit 是"修改版 Apache 2.0 + 附加条件"，禁止 SaaS/多租户和商业再分发。**只借鉴思路，严禁复制、改写、翻译 hypit 的任何代码、SVML 语法、文档文本**；不要去下载 hypit 仓库。核验时会做长行比对，发现照搬整体作废。

要借鉴的只有三个设计思想：①时间锚在词/句上而不是秒上，换台词/配音后字幕和画面切换自动跟着新词时间重排；②参考片先变成可读证据（带词标注的帧网格 + 切点 + 统计），再由人/LLM 写结构说明；③变体 = 同一模板换几个槽位。

## 3O 分层与落点
- 实现：`hevi/layer4_legacy/viralclone/{oprim_impl,oskill_impl,omodul_impl}/`；外观层 shim：`hevi/viralclone/`（如 `hevi/viralclone/adapter.py`、`__init__.py`），照 talkcraft 的方式（`hevi/layer4_legacy/talkcraft/` + `hevi/talkcraft/explainer_adapter.py`）。读 `docs/3O-MIGRATION-REPORT.md`。
- 复用并修正现有 `hevi/video_intelligence/`（boundaries.py、reference.py、rhythm.py、contactsheet.py、transcript.py 等）。注意：它的 `artifacts/video_intelligence/qualification.json` 全 1.0 指标只在 Hevi 自己生成的单镜头片上跑过，**从未对真实片跑过**；发现的 bug 就修，修的地方在 DONE 里列出。
- 接入：在 zerolines 的 `reference_adapt` 线（`hevi/layer4_legacy/zerolines/omodul_impl/_lines.py`，PRODUCERS）旁新增一条线（如 `viral_template` / `viral_variants`）或给 reference_adapt 增加"拆解卡驱动"模式；record/结果里的 `engine` 槽和现有线一致（现有是 `engine="zero"`，见 `zerolines/omodul_impl/runtime.py`）。

## 要做

### P0-1 参考片拆解卡 `reference_breakdown`
输入一个本地 mp4 → 输出目录：`breakdown.json` + 网格图 + `breakdown.md`。
- 切点：scenedetect（.venv 已装）或 ffmpeg scene，和 video_intelligence/boundaries.py 打通。
- 词级转写：faster-whisper，模型 `/home/soffy/models/faster-whisper-large-v3-turbo`，CPU int8，`word_timestamps=True`，中文按字给时间。
- 带词标注的帧网格：每格标时间码，格下方标当时说的词（扩展 contactsheet.py）。
- 字幕区检测：帧差/边缘法给出字幕位置、行高（≈字号）；可选 CPU OCR `rapidocr-onnxruntime`（需 pip 安装，用国内镜像直连）。
- 节奏/hook 统计：首个镜头时长、首句结束时间（hook 时长）、平均/中位镜头时长、切点频率、语速（字/秒）、静音段。
- 语义层：只能用本地/免费通道。宿主 `http://127.0.0.1:11434` 有 ollama（llama3.2:3b / llama3.2:1b，纯文本），可以基于转写文本给出段落标签（hook/卖点/证明/CTA）；画面语义没有本地视觉模型就写 `"semantic_visual": "UNKNOWN"`。**不得伪造**任何语义结论，不调用 DashScope/qwen 云/OpenAI/豆包/火山等任何云 API（包括仓库里 `llm_call(provider="qwen3_dashscope")` 这类通道）。

### P0-2 词锚定模板 + 变量槽
- 新增 `template.json` 规格（自己设计，不抄 SVML）：段落（hook / 卖点×N / 证明 / CTA）以"句/词锚点"定位；每个视觉事件（切镜、字幕、贴片、特效、产品卡）挂在锚点上（某句开始/结束、某个词、相对偏移）；变量槽至少 `{product, selling_points[], price, cta, host, lang, aspect, hook_line}`。
- 能从 P0-1 的拆解卡自动起草一份模板（结构/节奏/字幕样式来自拆解，内容槽留空）。
- 编译器：填槽 → TTS（piper，本地 CPU；用法参考 zerolines `_media.py` / `/data/soffy/projects/hevi-zero/zl.py`，中文 zh huayan；CosyVoice http://127.0.0.1:17600 可选）→ faster-whisper 重对齐得到新词时间 → 按新词时间生成**现有 Hevi timeline JSON 格式**（`data/timelines/*.json`：`clips[]` 的 start_s/duration_s/source_in_s/text/transition/effect + `tracks.video/audio/captions`）→ 渲染 mp4（ffmpeg + ASS 字幕即可，可复用 zerolines 的 shots/captions/qa）。字幕、切镜、特效必须落在新词时间上。
- 测试：同一模板两套不同长度文案，验证切换点跟随新词时间（逐帧抽查截图）。

### P1-1 变体矩阵批量
- 一条命令出 N 个变体：笛卡尔积或抽样（hook × 卖点顺序 × 画幅 × 语言/音色 × 配色/字幕样式 × 素材顺序）；并发受控（CPU，默认 ≤4 进程）。
- 每条：ffprobe、blackdetect/silencedetect、sha256、6 帧抽帧非静态检查。
- **差异度闸门**：感知哈希（可 pip 装 imagehash，或自己用 cv2 实现 dHash/pHash）+ 文案相似度；两两差异度低于阈值的变体**拒绝**并记录原因；输出差异度矩阵 json。
- **AI 显式标识**（GB 45438-2025）：起始画面的边或角，文字如"AI生成"/"本视频含AI生成内容"，**字高 ≥ 画面短边的 5%**，持续 **≥ 2s**；用像素实测（截图 + 计算字高）写进 QA。**隐式标识**：写入容器元数据（如 `-metadata comment=...`/`AIGC` 字段：生成方、内容标识、时间），用 ffprobe 读回验证。

### P1-2 商品实拍素材线
- 输入商品实拍图/视频 → rembg（u2net ONNX，CPU，需 pip 安装；模型从 modelscope/ghfast 直连下载）抠图 → 产品卡（白/渐变背景 + 投影）、Ken Burns、卖点贴片、价格/CTA 组件。
- **禁止用 AI 生成商品外观**（平台要求与实物一致）。

## 验收（必须真实，禁止 mock/占位）
- 参考片：一条**可合法使用**的真实公开短视频——Wikimedia Commons 上 CC0/CC-BY/公共领域、或 NASA 等公共领域视频（最好有人声讲话，便于词级转写），或用 Pexels/Pixabay 免费授权素材拼成；**不要用受版权保护的平台爆款**。在 DONE 里写清来源 URL 和许可证。商品图同样用 CC0/公共领域实拍图并注明来源。
- 产出：拆解卡（breakdown.json + 带词网格图 + breakdown.md）+ 模板 template.json + **至少 3 个变体真实 MP4**，放 `output/viralclone_e2e/`。
- 每个变体：ffprobe（时长/分辨率/音轨）、6 帧抽帧 contact sheet 且帧间非静态、sha256、与其它变体的差异度数值、AI 标识可见截图（含像素字高/短边比例、显示时长）、元数据读回。
- 新增单元测试（mock 只允许在单元测试里）+ E2E 脚本真跑。

## 通用规则（必须遵守）
- 仓库：本 worktree 是 hevi 的独立分支 feat/viralclone-3o，基于 closure/3o-v3-architecture-creative-baseline 最新提交。只在本 worktree 内改动，只做本地 commit，**不要 push、不要 merge、不要重启/修改任何 docker 容器或系统服务、不要动 /data/soffy/projects/hevi 主目录和其它 worktree**。不删除任何已有数据。
- 改完跑 `scripts/ci/run_3o_v3_lint.py`，新失败数不得多于基线（**先记录基线**；当前基线有既有失败，是正常的，只比较差异）。跑测试需 `JWT_SECRET=<任意测试串>` 环境变量。
- Python：用仓库 `.venv/bin/python`（pip 安装时用 `.venv/bin/pip`，国内镜像，直连）。ffmpeg/ffprobe 在 /home/soffy/.local/bin/。Node 在 ~/.nvm/versions/node/v26.4.0/bin。
- **零成本 + CPU-only**：服务器 GPU 已坏，不调用任何付费或云 API（DashScope、火山/豆包、OpenAI、Atlas、Seedance 等一律不用）。只用本地模型。
- **禁止造假**：之前外部 agent 用 5 秒假 mp4、mock ASR、"Beat 0/Your Brand" 占位冒充完成，被整体作废。所有验收必须是真实产物：ffprobe 实测、抽帧亲自看图、sha256；状态字段不许写死 PASS/True，必须来自实测。功能做不到就如实标 UNKNOWN/NOT_IMPLEMENTED。
- 第三方代码只能用允许的许可证（MIT/BSD/Apache 原版），保留版权放 third_party/ 并在 NOTICE 注明；hypit 一行都不许用。
- 资源：CPU 渲染并发 ≤4，注意宿主内存（本单元 MemoryMax=7G）。
- 结束时写 `VIRALCLONE_DONE.md`：做了什么、文件清单、如何调用（命令行示例）、E2E 产物路径与 ffprobe/sha256/差异度/标识实测、修了 video_intelligence 哪些 bug、lint 前后对比、已知问题。然后 git commit（英文 conventional commits）。
- 遇到同一问题循环超过两次仍失败，停下来把现状和卡点写进 DONE 报告，不要硬凑。

## 网络
环境里的 HTTP(S)_PROXY 只用于 Gemini（经新加坡 SSH 隧道，带宽很小）。下载模型/软件包/大文件（modelscope、PyPI 镜像、npm 镜像、ghfast.top、Wikimedia 等）时，命令前务必加 `env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u ALL_PROXY -u all_proxy` 直连，否则会把隧道堵死、导致你自己的会话断线。github/huggingface 直连不通时用 https://ghfast.top/<github 原始 URL> 或 modelscope。
