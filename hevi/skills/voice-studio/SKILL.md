---
name: voice-studio
version: "0.1.0"
description: Local-first TTS, ASR, voice gallery, dubbing, audiobook, dictation and batch speech workflows.
argument-hint: "catalog | route --kind tts | dubbing --source-video <path> --target-language <lang>"
allowed-tools: Bash, Read
user-invocable: true
---

# /voice-studio

VoiceStudio 风格的 HEVI 语音平台技能。所有可执行音频都必须落成本地文件并带
ArtifactManifest；目录、声线和工作流计划可以先审查，不把计划冒充成音频成品。

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.voice_studio_cli catalog
uv run python -m hevi.skills.voice_studio_cli route --kind tts
uv run python -m hevi.skills.voice_studio_cli dubbing \
  --source-video input.mp4 --target-language en
```

3O 映射：

- `oprim`：模型生命周期、引擎状态、声线元数据、音频格式与本地文件边界。
- `oskill`：TTS/ASR 路由、批量、克隆、译制、有声书、听写和水印意图。
- `omodul`：OpenAI-compatible `/v1/audio/*`、Gallery、批处理和工作流 handoff API。

模型注册只接受本地路径。没有引擎、模型或 streaming sidecar 时，返回明确的
`unavailable/blocked` 状态；不会下载权重、返回远程音频 URL 或伪造水印结果。
