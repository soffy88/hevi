"""voicepro_asr oprim：无状态原子，不得引用 oskill/omodul。

对应 Voice-Pro ASR 能力的原子实现：
语音预处理 → 模型推理 → 词级时间戳 → 断句对齐 → 结果验证
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

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

# ── Stage 1: 音频预处理 ─────────────────────────────


def normalize_audio(
    audio_path: str,
    output_path: str,
    sample_rate: int = 16000,
    channels: int = 1,
) -> str:
    """使用 ffmpeg 归一化音频。

    KrillinAI/Azure/OpenAI 等 ASR 系统的标准预处理。
    """
    args = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-c:a", "pcm_s16le",
        output_path,
    ]
    subprocess.run(args, check=True, capture_output=True)
    return output_path


# ── Stage 2: Faster-Whisper 识别 ─────────────────────

async def transcribe_faster_whisper(
    audio_path: str,
    config: ASRConfig,
) -> ASRResult:
    """使用 Faster-Whisper 执行语音识别。

    返回：完整的转录结果，包括文字、词级时间戳和句子片段。
    """
    try:
        import faster_whisper
    except ImportError:
        raise RuntimeError("faster-whisper 未安装")

    model = faster_whisper.Model(
        config.model,
        device=config.language if config.language in ("cpu", "cuda", "mps") else "auto",
        compute_type="float16" if config.fp16 else "int8",
    )

    segments, info = model.transcribe(
        audio_path,
        language=config.language if config.language not in ("auto", "") else None,
        beam_size=config.beam_size,
        best_of=config.best_of,
    )

    # 构建结果
    words: list[WordTimestamp] = []
    segments_list: list[SentenceSegment] = []

    for segment in segments:
        seg = SentenceSegment(
            start_s=segment.start,
            end_s=segment.end,
            text=segment.text,
            is_complete=True,
        )
        segments_list.append(seg)

        for word in segment.words:
            word_info = WordTimestamp(
                word=word.word,
                start_s=word.start,
                end_s=word.end,
                start_ms=int(word.start * 1000),
                end_ms=int(word.end * 1000),
            )
            words.append(word_info)

    return ASRResult(
        text=info.text if hasattr(info, "text") else "",
        words=words,
        segments=segments_list,
        language=info.language if hasattr(info, "language") else config.language,
        duration_s=info.duration if hasattr(info, "duration") else 0.0,
        cer=0.0,  # 可选：后续可通过 CER 计算获得
        model_used=f"faster-whisper:{config.model}",
        latency_s=0.0,  # 实际应计时
    )


# ── Stage 3: Whisper.cpp 识别 ───────────────────────

async def transcribe_whisper_cpp(
    audio_path: str,
    config: ASRConfig,
) -> ASRResult:
    """使用 Whisper.cpp 执行语音识别。

    适用于没有 GPU 的环境，或需要本地推理的场景。
    """
    # 占位：实际实现需调用 whisper.cpp CLI 或库
    # raise NotImplementedError("Whisper.cpp bridge not implemented yet")
    
    # 占位返回结构
    return ASRResult(
        text="",
        words=[],
        segments=[],
        language=config.language,
        duration_s=0.0,
        cer=1.0,
        model_used="whisper_cpp:placeholder",
        latency_s=0.0,
    )


# ── Stage 4: Alibaba Cloud ASR ────────────────────────

async def transcribe_aliyun_asr(
    audio_path: str,
    config: ASRConfig,
) -> ASRResult:
    """使用阿里云语音识别服务。

    适用于需要国内部署或特定合规要求的场景。
    """
    # 占位：实际实现需调用阿里云 SDK
    return ASRResult(
        text="",
        words=[],
        segments=[],
        language="zh",
        duration_s=0.0,
        cer=1.0,
        model_used="aliyun_asr:placeholder",
        latency_s=0.0,
    )


# ── Stage 5: OpenAI Whisper API ─────────────────────

async def transcribe_openai_whisper(
    audio_path: str,
    config: ASRConfig,
) -> ASRResult:
    """使用 OpenAI Whisper API 执行语音识别。

    需要有效的 OpenAI API Key。
    """
    # 占位：实际实现需调用 OpenAI API
    return ASRResult(
        text="",
        words=[],
        segments=[],
        language=config.language,
        duration_s=0.0,
        cer=1.0,
        model_used="openai_whisper:placeholder",
        latency_s=0.0,
    )


# ── Stage 6: 结果验证 ───────────────────────────────


def _character_error_rate(expected: str, actual: str) -> float:
    """确定性 Levenshtein CER，避免把验证逻辑委托给可选库。"""
    if not expected:
        return 0.0 if not actual else 1.0
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        current = [i]
        for j, right in enumerate(actual, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right))
            )
        previous = current
    return previous[-1] / len(expected)

def verify_asr_result(
    result: ASRResult,
    expected_text: str | None = None,
    max_cer: float = 0.05,
) -> dict[str, Any]:
    """验证 ASR 识别结果的质量。

    计算 CER (字符错误率) 并检查是否符合阈值。
    """
    if expected_text:
        cer = _character_error_rate(expected_text, result.text)
    else:
        cer = result.cer if result.cer else 1.0

    return {
        "passed": cer <= max_cer,
        "cer": cer,
        "text": result.text,
        "word_count": len(result.words),
        "segment_count": len(result.segments),
    }


# ── 导出 ───────────────────────────────────────────────

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
    "transcribe_aliyun_asr",
    "transcribe_faster_whisper",
    "transcribe_openai_whisper",
    "transcribe_whisper_cpp",
    "verify_asr_result",
    "verify_asr_result",
]
