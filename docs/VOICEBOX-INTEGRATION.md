# Voicebox 音频服务

HEVI 的解说 E2、通鉴 L3 和短剧通鉴渲染在生产 Compose 中默认使用
`hevi-voicebox` sidecar。源码固定拉在 `services/voicebox`，模型和音色档案由
Compose 会把项目目录下的 `.voicebox-cache` 挂到 Voicebox 的 Hugging Face
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
