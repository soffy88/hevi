"""voicepro_clone 3O 包的 schema 契约。

对应 Voice-Pro 的声纹克隆能力模型。
对齐 Voice-Pro 的克隆 pipeline: 声纹提取 → 声音建模 → 语音合成 → 声音融合
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ─── 克隆模式 ─────────────────────────────────────


class CloneMode(str, Enum):
    """声纹克隆模式。"""
    ZERO_SHOT = "zero_shot"          # 短音频零样本克隆
    CROSS_LINGUAL = "cross_lingual"  # 跨语言克隆
    INSTRUCT = "instruct"            # 指令式克隆


class CloneProvider(str, Enum):
    """声纹克隆提供商。"""
    COSYVOICE = "cosyvoice"      # CosyVoice (Fun-CosyVoice3 支持韩语等 9 语言)
    F5_TTS = "f5_tts"            # F5-TTS (E2-TTS 变体)
    E2_TTS = "e2_tts"            # E2-TTS
    OPEN_AI = "openai"           # OpenAI 语音克隆 (TTS HD)


# ─── 声纹模型 ─────────────────────────────────────


class VoiceProfile(BaseModel):
    """声纹档案。

    存储克隆声音的特征和元数据。
    """
    profile_id: str = ""
    name: str = ""
    provider: CloneProvider = CloneProvider.COSYVOICE
    reference_audio: str = ""  # 参考音频路径
    language: str = "zh"  # 原始语言
    supported_languages: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── 克隆配置 ────────────────────────────────────


class CloneConfig(BaseModel):
    """克隆配置。"""
    provider: CloneProvider = CloneProvider.COSYVOICE
    mode: CloneMode = CloneMode.ZERO_SHOT
    reference_audio: str = ""  # 参考音频路径或 URL
    target_text: str = ""
    speed: float = 1.0
    pitch: float = 1.0
    # CosyVoice 特有
    prompt_text: str = ""
    instruct_text: str = ""
    # OpenAI 特有
    model: str = "tts-1-hd"


# ─── 克隆结果 ──────────────────────────────────


class CloneResult(BaseModel):
    """声纹克隆结果。"""
    audio_path: str = ""
    text: str = ""
    duration_s: float = 0.0
    provider: CloneProvider = CloneProvider.COSYVOICE
    mode: CloneMode = CloneMode.ZERO_SHOT
    reference_audio: str = ""
    similarity_score: float = 0.0  # 语音相似度评分 (0-1)


# ─── 工厂函数 ───────────────────────────────────


def make_clone_config(
    provider: CloneProvider | str = CloneProvider.COSYVOICE,
    mode: CloneMode | str = CloneMode.ZERO_SHOT,
    reference_audio: str = "",
) -> CloneConfig:
    """创建克隆配置。"""
    if isinstance(provider, str):
        provider = CloneProvider(provider)
    if isinstance(mode, str):
        mode = CloneMode(mode)
    return CloneConfig(
        provider=provider,
        mode=mode,
        reference_audio=reference_audio,
    )