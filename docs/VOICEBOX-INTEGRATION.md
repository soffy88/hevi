# AI 算力引擎音频服务(Voicebox 通道)

HEVI 的解说 E2、通鉴 L3 和短剧通鉴渲染在生产 Compose 中默认使用
`hevi-gen-engine` 统一 GPU 引擎(演进自 `hevi-voicebox` sidecar)。源码底座在
`services/voicebox`(上游 git 子模块), HEVI 包装层在 `services/gen_engine`。
模型和音色档案由
Compose 会把项目目录下的 `.voicebox-cache` 挂到引擎的 Hugging Face
`hub` 缓存，并把 profile/生成记录放在 Docker volume 中。生产容器默认离线运行，
避免模型下载失败时任务一直重试。

首次部署先在宿主机下载 1.7B CustomVoice 权重（约 4.21 GiB）：

```bash
mkdir -p .voicebox-cache
HF_HOME="$PWD/.voicebox-cache" \
  uv run python -c 'from huggingface_hub import snapshot_download; snapshot_download("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", cache_dir=".voicebox-cache")'
```

若宿主机通过代理访问 Hugging Face，在命令前设置 `HTTPS_PROXY`/`HTTP_PROXY`。
随后运行 `docker compose -f deploy/docker-compose-cftunnel.yml up -d --build`。

首次启动会自动创建一个 Voicebox `qwen_custom_voice` 中文 `Dylan` 档案。要使用
自己的参考音频克隆音色：在 Voicebox UI/API 创建 profile 并上传 sample，然后在
`.env` 设置：

```dotenv
VOICEBOX_PROFILE_ID=<profile id>
VOICEBOX_ENGINE=qwen
```

`VOICEBOX_PROFILE_ID` 未设置时使用自动创建的预置档案。表达风格由
`VOICEBOX_INSTRUCT` 控制；解说默认使用自然、沉稳、有呼吸感、避免播音腔的指令。

Voicebox 不返回词级时间戳，HEVI 使用真实 WAV 时长按标点生成分句字幕。旧的
`edge_tts` 只在显式设置 `HEVI_EXPLAINER_TTS_PROVIDER=edge_tts`，或设置
`VOICEBOX_ALLOW_EDGE_FALLBACK=1` 时启用。

## F5-TTS 零样本音色克隆(2026-08-16 新增)

F5-TTS 用参考音频(≤12s 自动截断)+ 其转录文本做零样本音色克隆, 质量优于
Qwen3-CustomVoice 单点; 引擎端点 `/api/ai/f5_tts`(gen-engine 容器内 ai-venv)。

宿主机下载权重(~1.3GiB, 走代理时先设 `HTTPS_PROXY`/`HTTP_PROXY`):

```bash
mkdir -p /home/soffy/models/f5-tts
uv run python -c '
from huggingface_hub import snapshot_download
snapshot_download("SWivid/F5-TTS", allow_patterns="F5TTS_Base/*",
                  local_dir="/home/soffy/models/f5-tts/F5TTS_Base")
snapshot_download("charactr/vocos-mel-24khz",
                  local_dir="/home/soffy/models/f5-tts/vocos")
'
```

`docker-compose-cftunnel.yml` 已挂载 `/home/soffy/models/f5-tts → /models/f5-tts:ro`。
用法: `HEVI_TTS_FORMAL_PROVIDER=f5` + `F5_TTS_REFERENCE_AUDIO/TEXT`(固定解说音色),
或任何持有参考音频+转录的管线直接调 `hevi/audio/f5_tts_service.f5_tts_synthesize`。

## CosyVoice2/3 升级(2026-08-16)

gen-engine 的 cosyvoice 路径优先使用重供货 CosyVoice(含 transformers 5.13 行为
补丁, 修"静默合成错误内容"), 需模型目录为**新布局**(cosyvoice2.yaml)。

宿主机现有旧布局目录补一个 yaml 即可(其余文件共用):

```bash
uv run python -c '
from huggingface_hub import hf_hub_download
hf_hub_download("FunAudioLLM/CosyVoice2-0.5B", "cosyvoice2.yaml",
                local_dir="/home/soffy/models/CosyVoice/CosyVoice2-0.5B")
'
```

多语言 Fun-CosyVoice3-0.5B(韩/日/英等 9 语, ~9GiB, 可选):

```bash
uv run python -c '
from huggingface_hub import snapshot_download
snapshot_download("FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
                  local_dir="/home/soffy/models/CosyVoice3")
'
```

挂载已就绪: `COSYVOICE3_MODEL_DIR=/opt/cosyvoice/fun3`。
选择模型: cosyvoice 端点 `config.model = "Fun-CosyVoice3-0.5B"`(hevi-api 侧
`cosyvoice_synthesize(config={"model": ...})`)。
