# services/gen_engine —— HEVI 统一 GPU 算力引擎

v9.1 基建解耦的核心产物: **把 CPU 控制逻辑与 GPU 算力逻辑做绝对物理隔离**。

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│  hevi-api(纯控制节点)        │ HTTP   │  hevi-gen-engine(GPU 算力池)       │
│  · 调度 / 状态机 / SQLite    │───────▶│  · Voicebox Qwen3-TTS(音色克隆)    │
│  · Remotion 渲染(Node)      │        │  · CosyVoice TTS(解说)            │
│  · Playwright 录屏(Lite)    │        │  · LongCat Talking Face(数字人)    │
│  · 不加载任何推理模型         │        │  · 独立 ai-venv 隔离 vibevoice     │
└─────────────────────────────┘        └──────────────────────────────────┘
        no GPU / no torch                      nvidia runtime / RTX 3080
```

## 演进说明

- 由 `services/voicebox`(上游 git 子模块)演进而来: 该子模块是
  `github.com/jamiepine/voicebox`, **保持不动**; 本目录是 HEVI 自有包装层,
  构建时以子模块为底座, 复用它经过生产验证的 Qwen3-TTS 音色克隆能力
  (profiles / generate / audio / SSE 状态流等端点原样保留)。
- `server.py` 导入子模块构造好的 FastAPI 应用, 挂载 `/api/ai/*` 统一 AI 端点
  (路由表前置, 避免被子模块的 SPA catch-all 遮蔽)。
- `tts_worker.py` 是独立 ai-venv(`/opt/ai-venv`, Python 3.11)的显存隔离
  合成 worker —— vibevoice 要求 `accelerate==1.6.0` / `transformers==4.51.3`
  严格版本钉, 单独 venv 可避免污染 voicebox 运行环境; 子进程退出即回收 VRAM。

## AI 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/api/ai/health`       | 引擎健康 + GPU 状态 + 模型能力 |
| GET  | `/api/ai/capabilities` | `{cosyvoice, longcat, vibevoice}` 可用性 |
| POST | `/api/ai/cosyvoice`    | `{script, config}` → `audio/wav`(合成优先级: oprim CosyVoice → vibevoice 子进程) |
| POST | `/api/ai/fish_speech`  | multipart `text`(+可选 `reference_audio`) → `audio/wav`(fish-speech-1.5 零样本 TTS) |
| POST | `/api/ai/longcat`      | multipart `image`+`audio` → `video/mp4`(与主音频等长的口型视频) |

模型未部署时端点返回 `501`, hevi-api 客户端自动降级(edge_tts / ffmpeg 占位动画),
保证任何环境都有输出。

## 客户端约定(hevi-api 侧)

- `AI_ENGINE_BASE_URL` 环境变量(默认 `http://hevi-gen-engine:17493`)
- `hevi/audio/cosyvoice_service.py` —— CosyVoice HTTP 客户端
- `hevi/digital_human/talking_face.py` —— LongCat HTTP 客户端(保留本地 ffmpeg 降级)

## 模型部署清单

| 模型 | 环境变量 | 默认路径 |
|---|---|---|
| Voicebox Qwen3-TTS | (voicebox 自身 profile) | `.voicebox-cache` 挂载 |
| VibeVoice 1.5B | `VIBEVOICE_MODEL_DIR` | `/models/vibevoice-1.5b` |
| CosyVoice2-0.5B | `COSYVOICE_MODEL_DIR` | `/opt/cosyvoice/model` |
| fish-speech-1.5 | `FISH_SPEECH_MODEL_DIR` | `/models/fish-speech-1.5` |
| LongCat-Video | `LONGCAT_MODEL_PATH` | `/data/models/LongCat-Voice` |

## 构建与部署

```bash
# 生产栈(cftunnel): 自动构建 hevi-gen-engine(带 GPU 挂载)
eval $(ssh-agent -s) && ssh-add ~/.ssh/id_ed25519
docker compose -f deploy/docker-compose-cftunnel.yml up -d --build hevi-gen-engine

# 独立部署
docker compose -f services/gen_engine/docker-compose.yml up --build
```

验证:

```bash
curl -s http://localhost:17600/api/ai/health
curl -s http://localhost:17600/api/ai/capabilities
```
