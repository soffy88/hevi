"""voicepro_asr oprim：无状态原子，不得引用 oskill/omodul。

对应 Voice-Pro ASR 能力的原子实现：
语音预处理 → 模型推理 → 词级时间戳 → 断句对齐 → 结果验证
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
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

    model = faster_whisper.WhisperModel(
        config.model,
        device=os.getenv("FASTER_WHISPER_DEVICE", "auto"),
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

    started = time.monotonic()
    text_parts: list[str] = []
    for segment in segments:
        text_parts.append(segment.text.strip())
        seg = SentenceSegment(
            start_s=segment.start,
            end_s=segment.end,
            text=segment.text,
            is_complete=True,
        )
        segments_list.append(seg)

        for word in segment.words or []:
            word_info = WordTimestamp(
                word=word.word,
                start_s=word.start,
                end_s=word.end,
                start_ms=int(word.start * 1000),
                end_ms=int(word.end * 1000),
            )
            words.append(word_info)

    return ASRResult(
        text=" ".join(part for part in text_parts if part),
        words=words,
        segments=segments_list,
        language=info.language if hasattr(info, "language") else config.language,
        duration_s=info.duration if hasattr(info, "duration") else 0.0,
        cer=0.0,  # 可选：后续可通过 CER 计算获得
        model_used=f"faster-whisper:{config.model}",
        latency_s=time.monotonic() - started,
    )


# ── Stage 3: Whisper.cpp 识别 ───────────────────────

async def transcribe_whisper_cpp(
    audio_path: str,
    config: ASRConfig,
) -> ASRResult:
    """使用 Whisper.cpp 执行语音识别。

    适用于没有 GPU 的环境，或需要本地推理的场景。
    """
    executable = os.getenv("WHISPER_CPP_BIN", "").strip()
    if not executable:
        executable = shutil.which("whisper-cli") or shutil.which("main") or ""
    model = os.getenv("WHISPER_CPP_MODEL", "").strip()
    if not executable or not model:
        raise RuntimeError(
            "whisper.cpp is not configured; set WHISPER_CPP_BIN and WHISPER_CPP_MODEL"
        )
    source = Path(audio_path)
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f"audio file not found or empty: {source}")
    with tempfile.TemporaryDirectory(prefix="hevi-whisper-cpp-") as temp_dir:
        output_base = Path(temp_dir) / "transcript"
        command = [
            executable,
            "-m",
            model,
            "-f",
            str(source),
            "-oj",
            "-of",
            str(output_base),
        ]
        if config.language and config.language != "auto":
            command.extend(["-l", config.language])
        completed = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=float(os.getenv("WHISPER_CPP_TIMEOUT_S", "900")),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"whisper.cpp failed: {(completed.stderr or completed.stdout)[-1000:]}"
            )
        json_path = output_base.with_suffix(".json")
        if not json_path.is_file():
            raise RuntimeError("whisper.cpp completed without JSON transcript")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    segments_list: list[SentenceSegment] = []
    words: list[WordTimestamp] = []
    text_parts: list[str] = []
    for row in payload.get("transcription", []):
        text = str(row.get("text") or "").strip()
        start_s = _whisper_timestamp(row.get("offsets", {}).get("from"), 1000.0)
        end_s = _whisper_timestamp(row.get("offsets", {}).get("to"), 1000.0)
        if text:
            text_parts.append(text)
            segments_list.append(SentenceSegment(start_s=start_s, end_s=end_s, text=text, is_complete=True))
    return ASRResult(
        text=" ".join(text_parts),
        words=words,
        segments=segments_list,
        language=config.language,
        duration_s=segments_list[-1].end_s if segments_list else 0.0,
        model_used=f"whisper_cpp:{Path(model).name}",
    )


# ── Stage 4: Alibaba Cloud ASR ────────────────────────

async def transcribe_aliyun_asr(
    audio_path: str,
    config: ASRConfig,
) -> ASRResult:
    """使用阿里云语音识别服务。

    适用于需要国内部署或特定合规要求的场景。
    """
    raise RuntimeError(
        "Aliyun ASR adapter is not configured in HEVI; use the configured FunASR/"
        "faster-whisper path or provide a dedicated Aliyun adapter"
    )


# ── Stage 5: OpenAI Whisper API ─────────────────────

async def transcribe_openai_whisper(
    audio_path: str,
    config: ASRConfig,
) -> ASRResult:
    """使用 OpenAI Whisper API 执行语音识别。

    需要有效的 OpenAI API Key。
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OpenAI Whisper requires OPENAI_API_KEY")
    source = Path(audio_path)
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f"audio file not found or empty: {source}")
    import httpx

    base_url = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    data: dict[str, str] = {
        "model": config.model if config.model != "large-v2" else "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
    }
    if config.language and config.language != "auto":
        data["language"] = config.language
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            with source.open("rb") as audio:
                response = await client.post(
                    f"{base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=data,
                    files={"file": (source.name, audio, "audio/wav")},
                )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise RuntimeError(f"OpenAI Whisper request failed: {exc}") from exc
    segments_list: list[SentenceSegment] = []
    words: list[WordTimestamp] = []
    for row in payload.get("segments", []):
        text = str(row.get("text") or "").strip()
        start_s = float(row.get("start") or 0.0)
        end_s = float(row.get("end") or start_s)
        segments_list.append(SentenceSegment(start_s=start_s, end_s=end_s, text=text, is_complete=True))
    for row in payload.get("words", []):
        start_s = float(row.get("start") or 0.0)
        end_s = float(row.get("end") or start_s)
        words.append(
            WordTimestamp(
                word=str(row.get("word") or ""),
                start_s=start_s,
                end_s=end_s,
                start_ms=int(start_s * 1000),
                end_ms=int(end_s * 1000),
            )
        )
    return ASRResult(
        text=str(payload.get("text") or ""),
        words=words,
        segments=segments_list,
        language=str(payload.get("language") or config.language),
        duration_s=float(payload.get("duration") or (segments_list[-1].end_s if segments_list else 0.0)),
        model_used=f"openai_whisper:{data['model']}",
    )


def _whisper_timestamp(value: Any, divisor: float) -> float:
    try:
        return float(value) / divisor
    except (TypeError, ValueError):
        return 0.0


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
