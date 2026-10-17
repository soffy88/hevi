# Hevi Live Host (赛博小雅) — Design

> 在 Hevi 内部复刻一个**全本地、实时**的 AI 直播主持（抖音式），遵循 Hevi 3O 架构
> （`oprim` / `oskill` / `omodul`）。零网络 API、零 API key、零付费调用。

## 1. 目标与范围

- 输入：直播弹幕（文本）+ 麦克风 / wav 音频
- 处理：VAD 切音 → STT 转写 → 本地 LLM 主持（人设「小雅」）→ TTS 合成
- 输出：逐句流式 `wav` 音频；可选 OBS 虚拟输出 / RTMP 推送
- 非目标（本期不做，见 §6）：虚拟人像（Wav2Lip / MuseTalk）、真实 RTMP 出流、
  真实直播间弹幕爬取（仅文档化方案）。

## 2. 模块地图（3O）

```
hevi/live_host/
├── __init__.py            # 导出 omodul 编排入口
├── schemas.py             # 数据契约：TurnInput / TurnOutput / EngineConfig / StageTiming
├── oprim/                 # 原子能力（无编排，纯计算/IO）
│   ├── silero_vad.py      # Silero VAD onnx 语音活动检测（256/512 窗口，带状态）
│   ├── stt_whisper.py     # faster-whisper 转写原子
│   ├── llm_ollama.py      # ollama HTTP 聊天原子（人设注入）
│   ├── tts_piper.py       # Piper 本地 TTS 原子（subprocess）
│   ├── tts_cosyvoice.py   # CosyVoice 引擎 TTS 原子（HTTP 委托，可选）
│   └── registry.py        # 引擎注册表（可插拔 + 热切换）
├── oskill/                # 技能组合（单阶段能力编排）
│   ├── skill_listen.py    # VAD+STT → 文本
│   ├── skill_think.py     # LLM 生成回复（句子切分）
│   └── skill_speak.py     # TTS 合成 wav
├── omodul/                # 编排（整条对话循环）
│   └── live_loop.py       # 单轮 + 流式子循环（danmaku/mic → audio）
└── ingest/
    ├── stdin_source.py    # 文本弹幕：stdin 行读取
    ├── ws_source.py       # 文本弹幕：本地 websocket 监听
    └── audio_source.py    # 音频源：wav 文件 / 麦克风（可选 sounddevice）
```

归属说明（3O）：
- **oprim**：最小不可再分能力，无状态编排，输入/输出皆为纯数据。每个推理引擎一个原子。
- **oskill**：把若干 oprim 组合成一个业务概念（听、想、说）。
- **omodul**：把 oskill 串成一轮完整直播交互，并决定流式/热切换策略。

## 3. 引擎注册表与热切换

`EngineRegistry` 持有三类引擎：`stt`、`llm`、`tts`。每个引擎是一个实现了统一
协议（`Engine` / `StreamingEngine`）的对象，由 `config` 里的 key 选择：

```yaml
engines:
  stt: whisper            # whisper | <future>
  llm: ollama             # ollama
  tts: piper              # piper | cosyvoice
tts:
  piper:
    binary: /data/soffy/projects/hevi-zero/.venv/bin/piper
    model:  /data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx
  cosyvoice:
    base_url: http://localhost:17600/api/ai/cosyvoice
llm:
  ollama:
    base_url: http://localhost:11434
    model:    llama3.2:3b
```

热切换：运行期改 `config` 并调用 `registry.select("tts", "cosyvoice")` 即可在
Piper（CPU 秒级）与 CosyVoice（GPU 引擎，音质更高）之间切换，无需重启。

## 4. VRAM 预算（目标 GPU：RTX 3080 10GB）

> 本机当前 **GPU 不可用**（nvidia-smi: No devices found），下列为 10GB 目标预算；
> MVP 默认全部 CPU 降级运行（实测见 `audit/live_host/REPORT.md`）。

| 阶段 | 模型 | 精度 | 显存 | 备注 |
|------|------|------|------|------|
| VAD | Silero v6 (onnx) | int8 CPU | ~0 | 常驻，几乎零成本 |
| STT | faster-whisper large-v3-turbo | int8 | ~1.2 GB | 可降级 base (~0.4GB) |
| LLM | llama3.2:3b (Q4_K_M) | q4 | ~2.2 GB | 或 1b (~1.0GB) 提速 |
| TTS | Piper zh (onnx) | — | ~0.1 GB | 常驻，CPU 推理 |
| TTS(可选) | CosyVoice2 | fp16 | ~3–4 GB | GPU 引擎容器，热切换 |
| 头像(可选) | MuseTalk / Wav2Lip | fp16 | ~4–5 GB | 本期不做 |
| **合计** | | | **~7–9 GB** | 留余量给 OBS/系统 |

CPU 降级路径：VAD/STT/TTS 全部 CPU；LLM 走 ollama CPU（首字延迟高，见报告）。

## 5. 延迟目标

- **首音频延迟（First Audio）**：用户输入结束 → 第一句音频可播放，目标 **< 2.5s**。
  - 注：CPU 全降级下 llama3.2:3b 首 token ~数秒，首音频会超出目标（实测见报告）。
    目标对应 GPU 配置（STT int8 + LLM q4 显存常驻）。
- 流式：LLM 逐句切分（句号/问号/感叹号/换行），每句一旦成型立即送 TTS，不等整段生成。
- 各阶段埋点计时（`StageTiming`），E2E 报告输出真值。

## 6. 抖音弹幕接入（本地化，无凭证）

> 严格本地、无 API key、无付费。仅文档化可行方案，本期不实现真实爬取。

1. **浏览器监听方案（推荐，零凭证）**：在主播自己浏览器里用油猴脚本 / 页面内
   `WebSocket` 监听抖音直播间的弹幕 WebSocket（页面私有协议，会随版本变），转发到本
   地 `ws_source` 监听端口。优点：不触碰任何平台 API，不需 cookie 导出。
   - 风险：协议变动需维护脚本；规模仅限单主播自看。
2. **桌面音频/视频采集**：OBS 捕获直播间窗口 → 音频走 VAD → STT，间接「听」弹幕念稿。
3. **明确不做**：第三方付费弹幕爬虫 API、cookie 批量导出、违反平台 ToS 的登录态注入。

`ws_source` 只监听**本地**端口（`127.0.0.1`），不对外暴露，不主动联网。

## 7. OBS 集成

- **音频**：每句 TTS 产出 `wav`，由 OBS 的「音频输入捕获 / 虚拟声卡」或外部合成器
  播放进 OBS 音轨；本期产物为 wav 文件流，OBS 侧用 `ffmpeg`/虚拟设备接入。
- **视频（可选，本期不做）**：Wav2Lip/MuseTalk 把音频驱动头像，输出到 OBS 视频源。
- **RTMP 出流（可选）**：OBS 负责 RTMP 推流；本模块只负责产出可播放的媒体流。

## 8. AIGC 内容标识要求（中国法规）

依据《互联网信息服务深度合成管理规定》及生成式 AI 服务管理办法，**AI 生成内容必须
显著标识**：

- 直播画面/音频须带可见标记 **「AI生成」**（或「人工智能生成」），不可隐藏、不可纯
  靠元数据。
- 本模块在 `omodul` 层提供 `aigc_mark` 钩子：
  - 文本弹幕回复前缀可配置（如 `【AI生成】`）；
  - 音频流侧由 OBS 叠加文字贴片实现画面级标识（OBS 文本源）。
- 设计约束：任何对外输出默认带「AI生成」标识，去掉标识需显式配置且记录在案
  （`config.aigc_label_enabled = True` 为默认）。
