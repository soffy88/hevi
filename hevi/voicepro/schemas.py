"""obase 契约:Voice-Pro 配音内核的纯数据结构。

3O 归属(待上游): `obase.voicepro_schemas`。不含 provider / 阈值 / Series 字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CosyInferenceMode = Literal["zero_shot", "cross_lingual", "instruct"]
MixStrategyName = Literal["replace", "remix"]


@dataclass
class TimedCue:
    """一条带时钟的字幕/台词。秒;与 assembly.Cue 同形但不依赖装配层。"""

    start: float
    end: float
    text: str
    speaker: str = ""
    emotion: str = "neutral"

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "speaker": self.speaker,
            "emotion": self.emotion,
        }


@dataclass
class TimelineSlot:
    """TTS 片段落到 SRT 时钟上的一格。"""

    cue_index: int
    start_ms: int
    clip_ms: int
    pad_after_ms: int
    clock_start_ms: int
    overflowed: bool = False

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.clip_ms + self.pad_after_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "cue_index": self.cue_index,
            "start_ms": self.start_ms,
            "clip_ms": self.clip_ms,
            "pad_after_ms": self.pad_after_ms,
            "clock_start_ms": self.clock_start_ms,
            "overflowed": self.overflowed,
        }


@dataclass
class MixPlan:
    """人声 + 伴奏床的混音规格。"""

    strategy: MixStrategyName
    vocal_gain_db: float = 0.0
    bed_gain_db: float = -8.0
    filter_complex: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "vocal_gain_db": self.vocal_gain_db,
            "bed_gain_db": self.bed_gain_db,
            "filter_complex": self.filter_complex,
        }


@dataclass
class CosyLinePayload:
    """一行 CosyVoice 引擎 payload(模式 + CV3 前缀已解析)。"""

    text: str
    inference_mode: CosyInferenceMode
    prompt_text: str = ""
    instruct_text: str = ""
    voice_ref: str | None = None
    ref_text: str | None = None
    speed: float = 1.0
    speaker_id: str = "host"

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "text": self.text,
            "inference_mode": self.inference_mode,
            "speaker_id": self.speaker_id,
            "speed": self.speed,
        }
        if self.voice_ref:
            row["voice_ref"] = self.voice_ref
        if self.ref_text is not None:
            row["ref_text"] = self.ref_text
        if self.prompt_text:
            row["prompt_text"] = self.prompt_text
        if self.instruct_text:
            row["instruct_text"] = self.instruct_text
        return row


@dataclass
class F5ModelSpec:
    name: str
    model_path: str
    vocab_path: str
    config: dict[str, Any] = field(default_factory=dict)
    language: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model_path": self.model_path,
            "vocab_path": self.vocab_path,
            "config": dict(self.config),
            "language": self.language,
        }


@dataclass
class SpeakerTurn:
    speaker: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"speaker": self.speaker, "message": self.message}


@dataclass
class TranslateLineResult:
    index: int
    source: str
    translated: str
    kept_original: bool
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "source": self.source,
            "translated": self.translated,
            "kept_original": self.kept_original,
            "attempts": self.attempts,
        }


@dataclass
class DubPlan:
    """配音内核文本规划:整理后的 cue + 时钟 + 混音 + TTS 模式。"""

    cues: list[TimedCue]
    slots: list[TimelineSlot] = field(default_factory=list)
    mix: MixPlan | None = None
    cosy_mode: CosyInferenceMode = "zero_shot"
    f5_model: str | None = None
    speakers: list[SpeakerTurn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cues": [cue.to_dict() for cue in self.cues],
            "slots": [slot.to_dict() for slot in self.slots],
            "mix": self.mix.to_dict() if self.mix else None,
            "cosy_mode": self.cosy_mode,
            "f5_model": self.f5_model,
            "speakers": [turn.to_dict() for turn in self.speakers],
        }
