"""voicepro_asr 3O 包：语音识别 (ASR)。

Voice-Pro 的音频识别能力内部化：
语音预处理 → 模型推理 → 词级时间戳 → 断句对齐 → 结果验证
"""

from __future__ import annotations

# ── Omodul ──
from hevi.voicepro_asr.omodul import (
    plan_clip_generator,
    plan_transcribe_pipeline,
)

# ── Oprim ──
from hevi.voicepro_asr.oprim import (
    make_asr_config,
    normalize_audio,
    transcribe_aliyun_asr,
    transcribe_faster_whisper,
    transcribe_openai_whisper,
    transcribe_whisper_cpp,
    verify_asr_result,
)

# ── Oskill ──
from hevi.voicepro_asr.oskill import (
    skill_batch_transcribe,
    skill_transcribe,
    skill_verify,
)

# ── Schemas ──
from hevi.voicepro_asr.schemas import (
    ASRConfig,
    ASRProvider,
    ASRResult,
    FunASRResult,
    FunASRWord,
    SentenceSegment,
    WordTimestamp,
    make_asr_config,
)

__all__ = [
    "ASRConfig",
    "ASRProvider",
    "ASRResult",
    "FunASRResult",
    "FunASRWord",
    "SentenceSegment",
    "WordTimestamp",
    "make_asr_config",
    "normalize_audio",
    "plan_clip_generator",
    # Omodul
    "plan_transcribe_pipeline",
    "skill_batch_transcribe",
    "skill_transcribe",
    "skill_verify",
    "transcribe_aliyun_asr",
    "transcribe_faster_whisper",
    "transcribe_openai_whisper",
    "transcribe_whisper_cpp",
    "verify_asr_result",
]