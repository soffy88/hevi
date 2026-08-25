"""voicepro_asr 3O 包的 schema 契约。

对应 Voice-Pro 的音频识别能力模型。
对齐 Voice-Pro 的 ASR pipeline: 语音预处理 → 模型推理 → 词级时间戳 → 断句对齐。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ─── ASR 提供商 ─────────────────────────────────────


class ASRProvider(str, Enum):
    """语音识别提供商。"""
    OPEN_AI_WHISPER = "openai_whisper"
    FASTER_WHISPER = "faster_whisper"
    WHISPER_KIT = "whisper_kit"
    WHISPER_CPP = "whisper_cpp"
    ALIYUN_ASR = "aliyun_asr"


# ─── 词级时间戳模型 ───────────────────────────────


class WordTimestamp(BaseModel):
    """词级时间戳。

    openai-whisper / faster-whisper 输出的核心结构。
    """
    word: str = ""
    start_s: float = 0.0
    end_s: float = 0.0
    start_ms: int = 0
    end_ms: int = 0


class SentenceSegment(BaseModel):
    """句子分段模型。

    包含：开始时间、结束时间、文本、是否完整。
    """
    start_s: float = 0.0
    end_s: float = 0.0
    text: str = ""
    is_complete: bool = False
    c_error_rate: float = 0.0  # CER 字符错误率


# ─── ASR 配置模型 ─────────────────────────────────


class ASRConfig(BaseModel):
    """ASR 识别配置。"""
    provider: ASRProvider = ASRProvider.FASTER_WHISPER
    model: str = "large-v2"  # tiny/medium/large-v2
    language: str = "zh"
    task: str = "transcribe"  # transcribe / translate
    beam_size: int = 5
    best_of: int = 5
    fp16: bool = True
    without_speech_threshold: float = 0.6
    vad_filter: bool = True


# ─── ASR 结果模型 ─────────────────────────────────


class ASRResult(BaseModel):
    """ASR 识别结果。"""
    text: str = ""
    words: list[WordTimestamp] = Field(default_factory=list)
    segments: list[SentenceSegment] = Field(default_factory=list)
    language: str = ""
    duration_s: float = 0.0
    cer: float = 0.0  # 字符错误率
    model_used: str = ""
    latency_s: float = 0.0


# ─── FunASR 输出规范化模型 ───────────────────────


class FunASRWord(BaseModel):
    """FunASR 原始输出词条。"""
    text: str = ""
    start: float = 0.0
    end: float = 0.0


class FunASRResult(BaseModel):
    """FunASR 结果。"""
    text: str = ""
    result: list[FunASRWord] = Field(default_factory=list)
    status: str = ""


# ─── ASR 能力信封 ─────────────────────────────────


class ASRCapability(BaseModel):
    """ASR 能力信封：当前环境可用的 ASR 工具。"""
    capabilities: dict[str, list[str]] = Field(default_factory=dict)
    # capability -> [tool_names], e.g., "transcribe": ["faster_whisper", "whisper_cpp"]
    providers: dict[str, list[str]] = Field(default_factory=dict)
    # provider -> [model_names], e.g., "faster_whisper": ["large-v2", "medium"]
    total_tools: int = 0
    default_provider: str = "faster_whisper"


# ─── 工厂函数 ─────────────────────────────────────


def make_asr_config(
    provider: ASRProvider | str = ASRProvider.FASTER_WHISPER,
    model: str = "large-v2",
    language: str = "zh",
) -> ASRConfig:
    """创建 ASR 配置。"""
    if isinstance(provider, str):
        provider = ASRProvider(provider)
    return ASRConfig(
        provider=provider,
        model=model,
        language=language,
    )