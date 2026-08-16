"""oprim:oprim_asr —— ASR 听声打轴原子能力(绝对无状态)。

只负责:master_audio.wav → 句级/词级时间戳 JSON + segment 列表。不涉及状态写入。

通道:
  1. faster-whisper(CPU int8)转写, word_timestamps=True 拿到词级时间码;
     段数与 cues 一致时按序一一对应(最常见: 一句 cue 对应一句旁白);
  2. 不一致或 whisper 不可用(无模型/无网络)→ 按 cue 字符权重在音频时长上
     比例分配(proportional fallback), 保证打轴永远有输出、绝不中断装配。

输出 JSON 结构:
    {"duration": float, "segments": [{"index", "start", "end", "text"}],
     "words": [{"start", "end", "text"}]}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from hevi.pipeline_lite.schemas import LiteCue

logger = logging.getLogger(__name__)

# faster-whisper 模型目录: 优先 env, 兜底本地 large-v3-turbo(与 subtitle_align 同源)。
_MODEL_DIR = os.environ.get(
    "FASTER_WHISPER_MODEL_DIR",
    str(Path.home() / "models/faster-whisper-large-v3-turbo"),
)


async def extract_segment_timestamps(
    audio_path: Path | str,
    cues: list[LiteCue],
    output_json_path: Path | str | None = None,
    *,
    model_dir: str | None = None,
    language: str | None = "zh",
    asr_engine: str = "auto",
    hotwords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """提取句级时间戳(秒), 可选落盘 timestamps.json。绝不抛错 —— 兜底比例分配。

    asr_engine: "auto"(VibeVoice-ASR 优先, 失败回退 whisper) / "faster_whisper" /
                "vibevoice"; hotwords 喂给 VibeVoice-ASR 提升专名识别。
    """
    audio = Path(audio_path)
    duration = _probe_duration(audio)

    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    if asr_engine in ("auto", "vibevoice"):
        vibevoice_segs, vibevoice_words = await _vibevoice_transcribe(
            audio, hotwords=hotwords or [], language=language
        )
        if vibevoice_segs:
            segments = _align(vibevoice_segs, cues, duration)
            words = vibevoice_words
            logger.info(
                "lite ASR: vibevoice %d 段 / %d 词 (audio %.2fs)",
                len(vibevoice_segs), len(vibevoice_words), duration,
            )
    if not segments and asr_engine != "vibevoice":
        try:
            whisper_segs, whisper_words = await asyncio.to_thread(
                _whisper_transcribe, audio, model_dir or _MODEL_DIR, language
            )
            segments = _align(whisper_segs, cues, duration)
            words = whisper_words
            logger.info(
                "lite ASR: whisper %d 段 / %d 词 (audio %.2fs)",
                len(whisper_segs), len(whisper_words), duration,
            )
        except Exception as exc:
            logger.warning("lite ASR: whisper 不可用, 按比例打轴: %s", exc)
            segments = _proportional(cues, duration)
    if not segments:
        segments = _proportional(cues, duration)

    if output_json_path is not None:
        out = Path(output_json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"duration": duration, "segments": segments, "words": words},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return segments


def _probe_duration(audio: Path) -> float:
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(audio)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return max(0.5, float(result.stdout.strip()))
    except Exception:
        pass
    return 3.0


def _whisper_transcribe(
    audio: Path, model_dir: str, language: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """同步 whisper 转写(在 to_thread 中执行)。返回 (segments, words)。"""
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    model = WhisperModel(model_dir, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(audio), language=language, word_timestamps=True, vad_filter=True
    )
    out_segs: list[dict[str, Any]] = []
    out_words: list[dict[str, Any]] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        seg_words = [
            {
                "start": float(word.start),
                "end": float(word.end),
                "text": (word.word or "").strip(),
            }
            for word in seg.words or []
        ]
        out_segs.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": text,
                "words": seg_words,
            }
        )
        out_words.extend(seg_words)
    if not out_segs:
        raise RuntimeError("whisper 未识别到语音")
    return out_segs, out_words


def _align(
    whisper_segs: list[dict[str, Any]], cues: list[LiteCue], duration: float
) -> list[dict[str, Any]]:
    """whisper 段 → cue 一一对应(数量一致); 否则按字符权重比例分配。"""
    if len(whisper_segs) == len(cues):
        return [
            {
                "index": cue.index,
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": cue.narration,
                "words": seg.get("words") or [],
            }
            for cue, seg in zip(cues, whisper_segs, strict=True)
        ]
    return _proportional(cues, duration)


def _proportional(cues: list[LiteCue], duration: float) -> list[dict[str, Any]]:
    """按 cue 字符权重在 [0, duration] 上比例切分(词级时间戳同步兜底)。"""
    weights = [max(len(cue.narration), 1) for cue in cues]
    total = sum(weights)
    cursor = 0.0
    result: list[dict[str, Any]] = []
    for index, (cue, weight) in enumerate(zip(cues, weights, strict=True)):
        end = duration if index == len(cues) - 1 else cursor + duration * weight / total
        result.append(
            {
                "index": cue.index,
                "start": round(cursor, 3),
                "end": round(end, 3),
                "text": cue.narration,
                "words": _split_words_proportional(cue.narration, cursor, end),
            }
        )
        cursor = end
    return result


def _split_words_proportional(text: str, start: float, end: float) -> list[dict[str, Any]]:
    """无 whisper 词级时间戳时, 按 空白分词/3 字 chunk 在句内比例切分。"""
    stripped = text.strip()
    if not stripped:
        return []
    tokens = stripped.split()
    if len(tokens) > 1:
        words = tokens
    else:  # 中文连续文本: 按 3 字 chunk 切, 保证卡拉OK 有节奏感。
        words = [stripped[i : i + 3] for i in range(0, len(stripped), 3)] or [stripped]
    weights = [max(len(w), 1) for w in words]
    total_w = sum(weights)
    cursor = start
    span = max(end - start, 0.05)
    out: list[dict[str, Any]] = []
    for i, w in enumerate(words):
        word_end = end if i == len(words) - 1 else cursor + span * weights[i] / total_w
        out.append({"start": round(cursor, 3), "end": round(word_end, 3), "text": w})
        cursor = word_end
    return out


__all__ = ["extract_segment_timestamps"]


async def _vibevoice_transcribe(
    audio: Path,
    *,
    hotwords: list[str] | None = None,
    language: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """VibeVoice-ASR(经 gen-engine /api/ai/asr): 说话人/时间戳/内容。

    引擎不可达/未部署 → 返回 ([], []) 由调用方回退 faster-whisper。
    """
    import httpx

    base = (
        os.environ.get("GEN_ENGINE_BASE_URL")
        or os.environ.get("AI_ENGINE_BASE_URL")
        or "http://hevi-gen-engine:17493"
    ).rstrip("/")
    try:
        with audio.open("rb") as fh:
            files = {"audio": (audio.name, fh, "audio/wav")}
            data = {
                "language": language or "auto",
                "hotwords": ",".join(hotwords or []),
            }
            async with httpx.AsyncClient(
                base_url=base,
                timeout=httpx.Timeout(
                    float(os.environ.get("GEN_ENGINE_TIMEOUT_S", "600")),
                    connect=15.0,
                ),
            ) as client:
                response = await client.post("/api/ai/asr", files=files, data=data)
        if response.status_code != 200:
            logger.warning("vibevoice-asr 端点返回 %s, 回退 whisper", response.status_code)
            return [], []
        payload = response.json()
        utterances = payload.get("utterances") or []
        segments: list[dict[str, Any]] = [
            {
                "start": float(u.get("start", 0.0)),
                "end": float(u.get("end", 0.0)),
                "text": str(u.get("text", "")).strip(),
                "speaker": str(u.get("speaker") or ""),
            }
            for u in utterances
            if str(u.get("text", "")).strip()
        ]
        words = [
            {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"]}
            for s in segments
        ]
        return segments, words
    except Exception as exc:
        logger.warning("vibevoice-asr 调用失败, 回退 whisper: %s", exc)
        return [], []
