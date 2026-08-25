"""voicepro_clone 3O 包：声纹克隆。

Voice-Pro 的声纹克隆能力内部化：
声纹提取 → 声音建模 → 语音合成 → 声音融合
"""

from __future__ import annotations

# ── Oprim ──
from hevi.voicepro_clone.oprim import (
    cosyvoice_cross_lingual,
    cosyvoice_instruct,
    cosyvoice_zero_shot,
    extract_voiceprint,
    f5_tts_zero_shot,
    merge_voice_clones,
    preprocess_text_for_cosyvoice,
    verify_clone_quality,
)

# ── Schemas ──
from hevi.voicepro_clone.schemas import (
    CloneConfig,
    CloneMode,
    CloneProvider,
    CloneResult,
    VoiceProfile,
    make_clone_config,
)

__all__ = [
    "CloneConfig",
    "CloneMode",
    "CloneProvider",
    "CloneResult",
    "VoiceProfile",
    "cosyvoice_cross_lingual",
    "cosyvoice_instruct",
    "cosyvoice_zero_shot",
    "extract_voiceprint",
    "f5_tts_zero_shot",
    "make_clone_config",
    "merge_voice_clones",
    "preprocess_text_for_cosyvoice",
    "verify_clone_quality",
]