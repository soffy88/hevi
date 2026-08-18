"""韵律时钟 —— 内化 agent-video-pipeline:母带是唯一时间轴。

字幕、语义动效、数字人、成片时长全部绑这份 track。
禁止在 HTML/Remotion 里另抄一套秒数。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_SENTENCE = re.compile(r"(?<=[。！？!?…])")


@dataclass
class ProsodyBeat:
    sentence_id: str
    text: str
    start_s: float
    end_s: float
    emphasis: list[str] = field(default_factory=list)
    tone: str = "baseline"
    cue_index: int = 0


@dataclass
class ProsodyTrack:
    beats: list[ProsodyBeat]
    duration_s: float
    baseline: str = "formal"
    source: str = "cue_estimate"
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "status": "draft",
            "duration_s": self.duration_s,
            "baseline": self.baseline,
            "source": self.source,
            "beats": [asdict(beat) for beat in self.beats],
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload["sha256"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        self.sha256 = payload["sha256"]
        return payload


def _chars_per_second(style: str) -> float:
    return {"formal": 4.2, "conversational": 4.8, "urgent": 5.2}.get(style, 4.2)


def _emphasis(text: str) -> list[str]:
    tokens = [part.strip("，,、；; ") for part in re.split(r"[，,、；;]", text) if part.strip()]
    return [token[:12] for token in tokens if 2 <= len(token) <= 12][:3]


def draft_prosody(
    texts: list[str],
    *,
    estimates: list[float] | None = None,
    baseline: str = "formal",
) -> ProsodyTrack:
    """旁白列表 → 韵律轨。有估时用估时,否则按语速推秒。"""
    rate = _chars_per_second(baseline)
    beats: list[ProsodyBeat] = []
    cursor = 0.0
    for index, raw in enumerate(texts):
        body = (raw or "").strip()
        if not body:
            continue
        parts = [part.strip() for part in _SENTENCE.split(body) if part.strip()] or [body]
        allotted = float(estimates[index]) if estimates and index < len(estimates) else None
        if allotted is None or allotted <= 0:
            allotted = max(len(body) / rate, 1.2)
        unit = allotted / max(len(parts), 1)
        for offset, part in enumerate(parts):
            start = cursor
            end = cursor + unit
            beats.append(
                ProsodyBeat(
                    sentence_id=f"s{index + 1}-{offset + 1}",
                    text=part,
                    start_s=round(start, 3),
                    end_s=round(end, 3),
                    emphasis=_emphasis(part),
                    tone="rise" if offset == 0 else "baseline",
                    cue_index=index,
                )
            )
            cursor = end
    return ProsodyTrack(
        beats=beats,
        duration_s=round(cursor, 3),
        baseline=baseline,
        source="cue_estimate",
    )


def retarget_to_master(track: ProsodyTrack, master_duration_s: float) -> ProsodyTrack:
    """配音母带出来后,按真实时长等比拉伸/压缩,旧字幕作废重绑。"""
    if track.duration_s <= 0 or master_duration_s <= 0:
        return track
    scale = master_duration_s / track.duration_s
    beats = [
        ProsodyBeat(
            sentence_id=beat.sentence_id,
            text=beat.text,
            start_s=round(beat.start_s * scale, 3),
            end_s=round(beat.end_s * scale, 3),
            emphasis=list(beat.emphasis),
            tone=beat.tone,
            cue_index=beat.cue_index,
        )
        for beat in track.beats
    ]
    return ProsodyTrack(
        beats=beats,
        duration_s=round(master_duration_s, 3),
        baseline=track.baseline,
        source="narration_master",
    )
