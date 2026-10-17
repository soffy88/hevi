# SVFACTORY-R1 GAP 分析（差距分析）

- 来源参考：`/data/soffy/refs/short-video-factory`（YILS-LIN/short-video-factory，AGPL-3.0，Electron 桌面端，只读思路，clean-room 重写，不复制任何源码/UI/素材到 Hevi）。
- 产品定位：Hevi = 2–6 岁幼儿教育动画短片，必须过 `audit/kids/KIDS_ANIME_DIRECTION.md` + `hevi/quality/kids_gate.py` 的 kids_gate 闸门。
- 参考工具流程（src/electron + src/lib + src/views）：`提示词 → 文案(OpenAI 兼容) → EdgeTTS → 按文案时长从分镜素材文件夹自动混剪 → 字幕特效 → 批量预设持续合成`。

## 参考工具的 6 个能力点 vs Hevi 已有

| # | 参考能力点 | Hevi 现状 | 缺口？ |
|---|-----------|-----------|--------|
| 1 | 提示词→文案（OpenAI 兼容 LLM） | Hevi 无通用「本地一键文案」原子，但有 `script_generator` / `explainer` / `talkcraft` 的文案生成以及 `kids.story_gate` 故事闸门 | 不缺（且有更严的 kids 故事闸门）；本任务不引入付费 LLM |
| 2 | TTS（EdgeTTS 默认） | Hevi 有 `piper_tts_service`（本地 CPU，零依赖）、`cosyvoice`/`voicebox`（远程，禁用）、`edge_tts`（可选默认关闭） | 不缺；用本地 Piper，EdgeTTS 仅作可选且默认关 |
| 3 | 按文案时长从素材文件夹自动混剪 | Hevi 有 `xfade_transitions`（柔和转场）、`montage.video_agent`（agentic，偏重）、`studio.nle` 重剪，但**没有「给定旁白时长 + 本地素材目录 → 自动选段/裁 9:16/16:9/去重/seed 确定」的轻量混剪原子** | **缺** → 新建 `svfactory` 混剪能力 |
| 4 | 字幕特效（幼儿大字/描边/逐字高亮） | Hevi 有 `subtitle_burner.get_subtitle_filter`（libass 烧录，已有 CJK 字体与描边样式预设）与 `kids`/text-overlap 门 | 不缺底层；缺「幼儿字幕样式预设集合 + 溢出/字号合规」的封装 → 轻量新建预设 |
| 5 | 批量预设持续合成（队列 + 断点续跑 + 每片 manifest） | Hevi 无「preset（主题/风格/时长/画幅/音色/字幕）→ 队列持续出片、单进程 CPU 串行、断点续跑、每片独立 manifest + kids_gate」 | **缺** → 新建 `svfactory` 批量生产管线 |
| 6 | API 暴露批量 + 状态查询 | Hevi `capabilities` 注册表与 `routers/capabilities.py` 已有，但无 `POST /api/batch` 与状态查询 | **缺** → 新增 `svfactory` router |

## 真缺口（仅这些进入实现）

1. **批量预设生产（batch preset production）**：一个 preset → 队列持续出片，单进程 CPU 串行、断点续跑、每片独立 manifest + kids_gate 结果；API `POST /api/batch` + 状态查询。
2. **素材文件夹自动混剪（asset-folder auto montage）**：给定本地素材目录（视频/图片）+ 旁白分句时长 → 自动选段、裁 9:16/16:9、`seed` 确定性去重、避免同段重复。
3. **字幕样式预设（幼儿大字/描边/逐字高亮）**：封装现有 libass 烧录 + 现有 kids_gate 字幕门，暴露为 `svfactory.subtitle_style` 能力。

## 明确不做（Hevi 已有或任务禁止）

- 不引入/不依赖付费 API、OpenAI 兼容 LLM、EdgeTTS 默认开启 → TTS 一律走本地 Piper。
- 不复制参考仓库任何源码/UI/素材（clean-room）。
- 不重写 `kids_gate`、不重写 `xfade_transitions`、不重写 `subtitle_burner` 底层；只在其上做薄封装与编排。
- 不接入 GPU 渲染 / 3D / Remotion；本任务全部 CPU-only、ffmpeg 串行。

## 复用清单（实现时直接调用，不新造轮子）

- `hevi.audio.piper_tts_service.synth_with_piper` — 本地 CPU TTS（零依赖）。
- `hevi.assembly.assembler.probe_duration` / `hevi.quality.kids_gate.probe_video_stats` — ffprobe 时长/分辨率。
- `hevi.assembly.subtitle_burner.get_subtitle_filter` — libass CJK 烧录（描边）。
- `hevi.quality.kids_gate.kids_gate_workflow` — 6 项 kids 闸门（已注册 `qa.kids_gate`）。
- `hevi.capabilities.registry` — 统一能力注册表（注册新能力，供各产品线按名调用）。
- CJK 字体：`/home/soffy/.local/share/fonts/wqy-zenhei.ttc`（WenQuanYi Zen Hei），避免烧录豆腐块。
