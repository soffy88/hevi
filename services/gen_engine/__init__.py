"""hevi-gen-engine —— 统一 GPU 生成引擎。

架构:v9.1 基建解耦后, 所有重量级推理(语音合成 / 数字人 Talking Face)全部
收拢到本引擎容器, hevi-api 只保留纯 HTTP 客户端 + Node/Playwright 渲染。

本包为 HEVI 自有代码, 构建时以 git 子模块 services/voicebox(上游 voicebox
项目)为底座: 复用其 Qwen3-TTS 音色克隆能力(profiles/generate/audio 端点),
在此之上挂载 /api/ai/* 统一 AI 端点(CosyVoice / LongCat / capabilities)。
"""

__version__ = "1.0.0"
