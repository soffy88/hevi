# HEVI 本地 TTS 安装与接入

当前机器已安装两条本地语音链路：

- Pocket TTS `3.0.2`：安装在 HEVI Python 3.14 环境，CPU 批量与 `generate_audio_stream` 流式输出均由 `hevi/audio/pocket_tts_service.py` 接管。
- VoxCPM `1.0.2`：安装在 `.venv-voxcpm` Python 3.12 隔离环境，使用 `.models/VoxCPM-0.5B` 权重；HEVI 通过 `hevi/audio/voxcpm_worker.py` 的 JSON stdin/stdout 边界调用，避免与 HEVI 的 Python 3.14 依赖冲突。

## 使用

请求 Voice Studio 时显式选择引擎：

```json
{
  "text": "This is a local HEVI voice test.",
  "engine": "pocket_tts",
  "voice": "alba",
  "language": "en"
}
```

VoxCPM 使用 `engine: "voxcpm"`，可追加 `voice_design` 或 `reference_audio`。两条链路最终都必须产出非空本地 WAV；模型加载、下载、超时或参考音频不存在时，任务返回失败原因，不生成占位文件。

## 硬件边界

本机当前没有 NVIDIA 驱动。Pocket TTS 可直接 CPU 运行；VoxCPM worker 已安装 CPU Torch 和 0.5B 权重，但 CPU 推理可能很慢。VoxCPM2 2B 和 GPU/vLLM 服务仍需具备 CUDA 的独立部署机，只需将 `HEVI_VOXCPM_PYTHON` 或 Provider endpoint 指向该运行时即可。

配置项见 `.env.example`：`HEVI_VOXCPM_PYTHON`、`HEVI_VOXCPM_MODEL`、`HEVI_VOXCPM_TIMEOUT_S`、`POCKET_TTS_CONFIG`。
