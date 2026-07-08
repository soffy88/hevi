"""E2 配音 —— edge-tts 逐段生成配音 + 词级时间戳,聚合成整句字幕起止时间。

同 hevi/video/vidu_service.py 等外部调用惯例:真实 REST/SDK 调用,非 mock。用
edge_tts.Communicate(boundary="WordBoundary") 拿词粒度 offset/duration(单位 100ns),
按标点把词级时间戳聚合成"整句字幕"的起止时间——聚合逻辑靠长度对齐(累计消耗字符数),
不做文本内容比对,足够稳健且不依赖 edge-tts 保留标点(它不保留)。

时长以 ffprobe 实测的真实文件时长为准,不用最后一个词的 end 时间——后者会截掉尾部
静音/呼吸,拼进 Remotion Sequence 的 durationInFrames 会真的把配音尾巴切掉。
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

import edge_tts

from hevi.explainer.schemas import CaptionCue, ManifestSegment, Storyboard, validate_props

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "zh-CN-YunyangNeural"  # 专业、可靠(Professional, Reliable)
DEFAULT_RATE = "-25%"  # 默认语速实测偏快(~5.6 字/秒),自媒体解说腔调需要更从容

_CLAUSE_SPLIT_CHARS = list(",,。;;::!!??……~~“”\"'()()·") + [r"\s+"]
_CLAUSE_SPLIT_RE = re.compile(
    "|".join(re.escape(c) if len(c) == 1 else c for c in _CLAUSE_SPLIT_CHARS)
)


class VoiceoverError(Exception):
    """配音合成失败(edge-tts 调用失败,或产物为空)。"""


def _clauses_of(text: str) -> list[str]:
    return [c for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]


async def _synthesize(text: str, out_path: Path, *, voice: str, rate: str) -> list[dict]:
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, boundary="WordBoundary")
    words: list[dict] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append(
                    {
                        "text": chunk["text"],
                        "start": chunk["offset"] / 1e7,
                        "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                    }
                )
    return words


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def _captions_from_words(text: str, words: list[dict]) -> list[CaptionCue]:
    clauses = _clauses_of(text)
    captions: list[CaptionCue] = []
    wi = 0
    for clause in clauses:
        target_len = len(clause)
        consumed = 0
        start_word = wi
        while wi < len(words) and consumed < target_len:
            consumed += len(words[wi]["text"])
            wi += 1
        if wi == start_word:
            continue
        captions.append(
            CaptionCue(text=clause, start=words[start_word]["start"], end=words[wi - 1]["end"])
        )
    return captions


async def synthesize_storyboard(
    storyboard: Storyboard,
    audio_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
) -> list[ManifestSegment]:
    """storyboard(E0 产出)→ 逐段配音,写 mp3 到 audio_dir,返回并入时间戳的 ManifestSegment 列表。

    audio_dir 通常直接传 hevi-remotion/public/audio(P0:单 run 顺序渲染,不做并发隔离,
    同 tongjian P0"尽力而为"的既有惯例)。ManifestSegment.audio_file 是相对 public/ 的路径
    (Remotion staticFile() 约定),不是绝对路径。
    """
    manifest: list[ManifestSegment] = []
    cursor = 0.0
    for seg in storyboard.segments:
        out_path = audio_dir / f"{seg.id}.mp3"
        try:
            words = await _synthesize(seg.narration, out_path, voice=voice, rate=rate)
        except Exception as e:
            raise VoiceoverError(f"段 {seg.id} 配音合成失败: {e}") from e
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise VoiceoverError(f"段 {seg.id} 配音产物为空: {out_path}")

        duration = _probe_duration(out_path)
        captions = _captions_from_words(seg.narration, words)
        props = validate_props(seg.scene_type, seg.props)

        manifest.append(
            ManifestSegment(
                id=seg.id,
                scene_type=seg.scene_type,
                text=seg.narration,
                audio_file=f"audio/{seg.id}.mp3",
                duration_sec=duration,
                start_sec=cursor,
                keywords=seg.keywords,
                props=props,
                captions=captions,
            )
        )
        logger.info("explainer voiceover: 段 %s 时长 %.2fs (累计 %.2fs)", seg.id, duration, cursor)
        cursor += duration

    return manifest
