"""Word-locked talkcraft primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TalkCue:
    cue_id: str
    text: str
    start_s: float
    end_s: float
    speaker: str = ""
    words: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class TalkcraftRequest:
    cues: tuple[TalkCue, ...] = ()
    style: str = "explainer"
    card_limit: int = 78
    broll_ratio: float = 0.45
    anti_slideshow: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.cues:
            errors.append("at least one voice cue is required")
        if self.card_limit < 1:
            errors.append("card_limit must be positive")
        if not 0 <= self.broll_ratio <= 1:
            errors.append("broll_ratio must be between 0 and 1")
        errors.extend(
            f"cue has invalid range: {cue.cue_id}"
            for cue in self.cues
            if cue.end_s <= cue.start_s
        )
        return errors

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["cues"] = [asdict(cue) for cue in self.cues]
        return body


__all__ = ["TalkCue", "TalkcraftRequest"]
