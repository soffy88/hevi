"""voicepro_tts 3O 包：文本转语音 (TTS)。

Voice-Pro 的语音合成能力内部化：
文本预处理 → 声纹克隆/选择 → 语音生成 → 音频后处理
"""

from __future__ import annotations

# ── Omodul ──
from hevi.voicepro_tts.omodul import (
    plan_ai_short,
    plan_clip_generator,
    plan_youtube_studio,
)

# ── Oprim ──
from hevi.voicepro_tts.oprim import (
    make_tts_config,
    make_tts_result,
    synthesize_azure_tts,
    synthesize_cosyvoice,
    synthesize_edge_tts,
    synthesize_f5_tts,
    synthesize_kokoro_tts,
    synthesize_minimax_tts,
    synthesize_openai_tts,
    synthesize_tts,
)
from hevi.voicepro_tts.oskill import (
    make_tts_config as skill_make_tts_config,
)
from hevi.voicepro_tts.oskill import (
    make_tts_result as skill_make_tts_result,
)

# ── Oskill ──
from hevi.voicepro_tts.oskill import (
    skill_batch_synthesize,
    skill_clone_voice,
    skill_synthesize_tts,
)

# ── Schemas ──
from hevi.voicepro_tts.schemas import (
    AudioOutput,
    TTSConfig,
    TTSProvider,
    TTSSResult,
    VoiceCloneMode,
    VoiceConfig,
    make_tts_config,
    make_tts_result,
)

__all__ = [
    "AudioOutput",
    "TTSConfig",
    "TTSProvider",
    "TTSSResult",
    "VoiceCloneMode",
    "VoiceConfig",
    "make_tts_config",
    "make_tts_config",
    "make_tts_result",
    "make_tts_result",
    "plan_ai_short",
    # Omodul
    "plan_clip_generator",
    "plan_youtube_studio",
    "skill_batch_synthesize",
    "skill_clone_voice",
    # Oskill
    "skill_synthesize_tts",
    "synthesize_azure_tts",
    "synthesize_cosyvoice",
    "synthesize_edge_tts",
    "synthesize_f5_tts",
    "synthesize_kokoro_tts",
    "synthesize_minimax_tts",
    "synthesize_openai_tts",
    "synthesize_tts",
]