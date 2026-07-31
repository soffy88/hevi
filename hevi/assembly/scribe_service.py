"""ElevenLabs Scribe 转写服务（对标 video-use 词级 + 说话人 + 音频事件）。

提供：
  - 词级时间戳（word-level timestamps）
  - 说话人分离（speaker diarization）
  - 音频事件标注（(laughter), (applause), (sigh), (music) 等）
  - 词间间隙数据（gap analysis），供 snap_to_word_boundary 使用

本模块为纯数据模型 + 可替换的转写适配器，不硬绑 ElevenLabs SDK，
便于测试和离线使用。实际 API 调用由 ScribeClient 协议注入。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# ── 音频事件常量（对标 ElevenLabs Scribe 输出） ────────────────────────

AUDIO_EVENTS = frozenset({
    "(laughter)",
    "(applause)",
    "(sigh)",
    "(music)",
    "(silence)",
    "(noise)",
    "(cough)",
    "(breath)",
    "(footsteps)",
    "(phone)",
})


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScribeWord:
    """词级时间戳，含说话人 + 置信度。"""

    word: str
    start: float
    end: float
    speaker: str = ""  # e.g. "SPEAKER_00"
    confidence: float = 1.0
    type: str = "word"  # "word" | "event"

    @property
    def is_event(self) -> bool:
        return self.type == "event"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class ScribeUtterance:
    """说话人连续语句（一组词）。"""

    speaker: str
    words: list[ScribeWord] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    text: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class ScribeTranscript:
    """完整转写结果（对标 video-use transcript）。"""

    text: str
    words: list[ScribeWord] = field(default_factory=list)
    utterances: list[ScribeUtterance] = field(default_factory=list)
    language: str = ""
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "words": [
                {
                    "word": w.word,
                    "start": w.start,
                    "end": w.end,
                    "speaker": w.speaker,
                    "confidence": w.confidence,
                    "type": w.type,
                }
                for w in self.words
            ],
            "utterances": [
                {
                    "speaker": u.speaker,
                    "text": u.text,
                    "start": u.start,
                    "end": u.end,
                    "word_count": len(u.words),
                }
                for u in self.utterances
            ],
            "language": self.language,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScribeTranscript:
        words = [
            ScribeWord(
                word=str(w["word"]),
                start=float(w["start"]),
                end=float(w["end"]),
                speaker=str(w.get("speaker") or ""),
                confidence=float(w.get("confidence", 1.0)),
                type=str(w.get("type", "word")),
            )
            for w in data.get("words") or []
        ]
        utterances = [
            ScribeUtterance(
                speaker=str(u["speaker"]),
                text=str(u.get("text") or ""),
                start=float(u.get("start", 0.0)),
                end=float(u.get("end", 0.0)),
            )
            for u in data.get("utterances") or []
        ]
        return cls(
            text=str(data.get("text") or ""),
            words=words,
            utterances=utterances,
            language=str(data.get("language") or ""),
            duration_s=float(data.get("duration_s", 0.0)),
        )


# ── 间隙分析（gap analysis）──────────────────────────────────────────


@dataclass(frozen=True)
class WordGap:
    """词间间隙，供 snap_to_word_boundary 使用。"""

    index: int  # 前一个词的索引
    gap_start: float  # 前一个词 end
    gap_end: float  # 下一个词 start
    gap_duration: float

    @property
    def midpoint(self) -> float:
        return self.gap_start + self.gap_duration / 2


def find_word_gaps(words: list[ScribeWord], min_gap_s: float = 0.05) -> list[WordGap]:
    """找词间 ≥ min_gap_s 的间隙，用于安全下刀。

    兼容 ScribeWord 和 edit_craft.Word（后者无 is_event）。
    """
    gaps: list[WordGap] = []
    for i in range(len(words) - 1):
        curr = words[i]
        nxt = words[i + 1]
        if getattr(curr, "is_event", False) or getattr(nxt, "is_event", False):
            continue
        gap_dur = nxt.start - curr.end
        if gap_dur >= min_gap_s:
            gaps.append(WordGap(
                index=i,
                gap_start=curr.end,
                gap_end=nxt.start,
                gap_duration=gap_dur,
            ))
    return gaps


def find_best_gap(
    gaps: list[WordGap],
    target_t: float,
) -> WordGap | None:
    """找到最接近 target_t 的间隙（用于 snap）。"""
    if not gaps:
        return None
    return min(gaps, key=lambda g: abs(g.midpoint - target_t))


# ── 客户端协议 ────────────────────────────────────────────────────────


class ScribeClient(Protocol):
    """转写客户端协议。实际实现可注入 ElevenLabs SDK 或 mock。"""

    async def transcribe(
        self,
        audio_path: str,
        *,
        language: str = "",
        diarize: bool = True,
        tag_audio_events: bool = True,
    ) -> ScribeTranscript: ...


# ── 离线 Mock（测试/开发用）──────────────────────────────────────────


class MockScribeClient:
    """离线转写 mock，从预设 JSON 加载或生成简单结果。"""

    def __init__(self, preset: ScribeTranscript | None = None):
        self._preset = preset

    async def transcribe(
        self,
        audio_path: str,
        *,
        language: str = "",
        diarize: bool = True,
        tag_audio_events: bool = True,
    ) -> ScribeTranscript:
        if self._preset:
            return self._preset
        # 生成简单 mock 结果
        return _build_mock_transcript(audio_path, language)


def _build_mock_transcript(audio_path: str, language: str = "") -> ScribeTranscript:
    """从文件路径构建简单 mock 转写（用于无 API 场景）。"""
    mock_words = [
        ScribeWord("hello", 0.0, 0.5, "SPEAKER_00", 0.95),
        ScribeWord("world", 0.6, 1.0, "SPEAKER_00", 0.93),
        ScribeWord("(silence)", 1.0, 1.5, "", 1.0, type="event"),
        ScribeWord("this", 1.5, 1.7, "SPEAKER_01", 0.90),
        ScribeWord("is", 1.7, 1.8, "SPEAKER_01", 0.88),
        ScribeWord("a", 1.8, 1.85, "SPEAKER_01", 0.92),
        ScribeWord("test", 1.9, 2.3, "SPEAKER_01", 0.96),
    ]
    utterances = [
        ScribeUtterance(
            speaker="SPEAKER_00",
            words=mock_words[:2],
            start=0.0,
            end=1.0,
            text="hello world",
        ),
        ScribeUtterance(
            speaker="SPEAKER_01",
            words=mock_words[3:],
            start=1.5,
            end=2.3,
            text="this is a test",
        ),
    ]
    return ScribeTranscript(
        text="hello world this is a test",
        words=mock_words,
        utterances=utterances,
        language=language or "en",
        duration_s=2.3,
    )


# ── 从 ScribeTranscript 提取给 edit_craft 用的 Word 列表 ─────────────


def to_edit_words(transcript: ScribeTranscript, skip_events: bool = True) -> list:
    """将 ScribeWord 转为 edit_craft.Word（纯词，无事件）。

    返回的是 tuple 列表以兼容 edit_craft.Word frozen dataclass。
    """
    from hevi.assembly.edit_craft import Word

    result: list[Word] = []
    for sw in transcript.words:
        if skip_events and sw.is_event:
            continue
        result.append(Word(word=sw.word, start=sw.start, end=sw.end))
    return result


def extract_audio_events(transcript: ScribeTranscript) -> list[ScribeWord]:
    """提取所有音频事件标注。"""
    return [w for w in transcript.words if w.is_event]


def speaker_segments(transcript: ScribeTranscript) -> list[dict[str, Any]]:
    """按说话人切分时间段，供多说话人剪辑使用。"""
    segments: list[dict[str, Any]] = []
    for u in transcript.utterances:
        segments.append({
            "speaker": u.speaker,
            "start": u.start,
            "end": u.end,
            "text": u.text,
            "word_count": len(u.words),
        })
    return segments
