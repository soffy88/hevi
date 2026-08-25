"""voicepro_tts 3O 包的 schema 契约。

对应 Voice-Pro 的文本转语音能力模型。
对齐 Voice-Pro 的 TTS pipeline: 输入文本 → 声纹克隆/选择 → 语音生成 → 音频后处理
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

# ─── TTS 提供商 ─────────────────────────────────────


class TTSProvider(str, Enum):
    """TTS 声音生成提供商。"""
    EDGE_TTS = "edge_tts"
    OPEN_AI_TTS = "openai_tts"
    MINIMAX_TTS = "minimax_tts"
    COSYVOICE_TTS = "cosyvoice_tts"
    F5_TTS = "f5_tts"
    KOKORO_TTS = "kokoro_tts"
    AZURE_TTS = "azure_tts"


class VoiceCloneMode(str, Enum):
    """声纹克隆模式。"""
    ZERO_SHOT = "zero_shot"      # 从短音频克隆
    CROSS_LINGUAL = "cross_lingual"  # 跨语言克隆
    INSTRUCT = "instruct"        # 指令式克隆


class VoiceConfig(BaseModel):
    """TTS 声音配置。"""
    provider: TTSProvider = TTSProvider.EDGE_TTS
    voice: str = "zh-CN-Xiaoyan"  # 声音名称
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    # 声纹克隆相关
    clone_source_audio: str = ""  # 声纹克隆源音频路径
    clone_mode: VoiceCloneMode = VoiceCloneMode.ZERO_SHOT
    # OpenAI/TTS 特有
    model: str = "tts-1"  # 或 "tts-1-hd"
    # Azure TTS 特有
    azure_region: str = ""
    # Edge-TTS 特有
    voice_name: str = ""  # 完整的声音名称


# ─── 音频输出模型 ─────────────────────────────────


class AudioOutput(BaseModel):
    """TTS 音频输出模型。"""
    path: str = ""
    duration_s: float = 0.0
    format: str = "wav"  # wav / mp3
    size_bytes: int = 0


# ─── TTS 结果模型 ─────────────────────────────────


class TTSSResult(BaseModel):
    """TTS 合成结果。"""
    audio_path: str = ""
    text: str = ""
    duration_s: float = 0.0
    voice_used: str = ""
    provider: TTSProvider = TTSProvider.EDGE_TTS
    model_used: str = ""
    cost_estimate_usd: float = 0.0


# ─── 音频配置模型 ─────────────────────────────────


class TTSConfig(BaseModel):
    """TTS 合成配置。"""
    provider: TTSProvider = TTSProvider.EDGE_TTS
    voice: str = "zh-CN-Xiaoyan"
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    # 声纹克隆相关
    clone_source_audio: str = ""
    clone_mode: VoiceCloneMode = VoiceCloneMode.ZERO_SHOT
    # 输出格式
    output_format: str = "wav"


# ─── 工厂函数 ─────────────────────────────────────


def make_tts_config(
    provider: TTSProvider | str = TTSProvider.EDGE_TTS,
    voice: str = "zh-CN-Xiaoyan",
    speed: float = 1.0,
) -> TTSConfig:
    """创建 TTS 配置。"""
    if isinstance(provider, str):
        provider = TTSProvider(provider)
    return TTSConfig(
        provider=provider,
        voice=voice,
        speed=speed,
    )


# ─── 工厂函数：创建 TTS 结果 ─────────────────────

def make_tts_result(
    audio_path: str,
    text: str,
    duration_s: float = 0.0,
    voice: str = "",
    provider: TTSProvider | str = TTSProvider.EDGE_TTS,
) -> TTSSResult:
    """创建 TTS 结果实例。"""
    if isinstance(provider, str):
        provider = TTSProvider(provider)
    return TTSSResult(
        audio_path=audio_path,
        text=text,
        duration_s=duration_s,
        voice_used=voice or "",
        provider=provider,
        model_used="",
        cost_estimate_usd=0.0,
    )