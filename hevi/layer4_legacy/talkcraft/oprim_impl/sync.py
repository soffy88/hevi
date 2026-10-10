"""Typed contracts for the talkcraft capability (oprim layer: data only, no I/O).

Internalized from video-talkcraft (PolyForm Noncommercial 1.0.0, see
``hevi-remotion-talkcraft/LICENSE.talkcraft``).  Only the method is carried
over: word-level voice sync -> semantic beats -> parametrised motion cards ->
measured gates.  Rendering stays in HEVI's own Remotion sub-project.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

FPS = 30
# Talkcraft motion cards are authored on a 960x540 stage; HEVI renders them
# with ``--scale=2`` to deliver 1920x1080 without re-layout.
STAGE_W = 960
STAGE_H = 540

_PUNCT = set(" \t\r\n，。！？；：、,.!?;:\"'“”‘’（）()《》<>【】[]—-…·~*")


def norm_chars(text: str) -> str:
    """Script/ASR comparison form: no whitespace or punctuation, lower-case."""
    return "".join(ch.lower() for ch in text if ch not in _PUNCT)


SceneRole = Literal["hook", "definition", "cards", "reason", "method", "outro", "plain"]


@dataclass(frozen=True)
class AlignedChar:
    char: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class SentenceTiming:
    """One narrated sentence placed on the master timeline (seconds)."""

    index: int
    text: str
    start_s: float
    end_s: float
    chars: tuple[AlignedChar, ...] = ()
    # share of script characters matched to ASR characters (1.0 = all matched)
    match_ratio: float = 0.0
    aligner: str = "none"

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    def char_time(self, *, substring: str) -> float | None:
        """Absolute start time of ``substring`` inside this sentence, if aligned."""
        if not substring or not self.chars:
            return None
        joined = "".join(c.char for c in self.chars)
        pos = joined.find(norm_chars(substring))
        if pos < 0:
            return None
        return self.chars[pos].start_s


@dataclass(frozen=True)
class NarrationSegment:
    """Producer-agnostic input: one storyboard segment split into sentences."""

    id: str
    role: SceneRole
    sentences: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Beat:
    segment_id: str
    sentence_index: int
    role: SceneRole
    card_id: str
    start_frame: int
    duration_frames: int
    anchor_word: str | None
    anchor_offset_s: float | None
    props: dict[str, Any]


@dataclass
class TalkcraftPlan:
    project: dict[str, Any]
    beats: list[Beat]

    def card_ids(self) -> list[str]:
        return [b.card_id for b in self.beats]

    def to_json(self) -> dict[str, Any]:
        return {"project": self.project, "beats": [asdict(b) for b in self.beats]}


AvatarMode = Literal["lipsync", "still"]
AvatarPosition = Literal["right", "left"]


@dataclass(frozen=True)
class AvatarSpec:
    """Optional digital-human picture-in-picture.  ``None`` anywhere = no avatar.

    image: local path to a frontal portrait; omitted -> bundled AI-generated presenter.
    mode: ``lipsync`` (Wav2Lip, non-commercial weights) or ``still`` (no model).
    """

    mode: AvatarMode = "lipsync"
    image: str | None = None
    position: AvatarPosition = "right"

    @staticmethod
    def from_config(value: object) -> AvatarSpec | None:
        if value in (None, False, "", "none", "off"):
            return None
        if value is True or value in ("lipsync", "still"):
            return AvatarSpec(mode="lipsync" if value is True else value)  # type: ignore[arg-type]
        if isinstance(value, dict):
            if value.get("enabled") is False:
                return None
            mode = value.get("mode", "lipsync")
            pos = value.get("position", "right")
            if mode not in ("lipsync", "still") or pos not in ("right", "left"):
                raise ValueError(f"bad avatar spec: {value}")
            return AvatarSpec(mode=mode, image=value.get("image") or None, position=pos)
        raise ValueError(f"bad avatar spec: {value!r}")


@dataclass
class GateMeasure:
    name: str
    value: float
    threshold: str
    passed: bool
    note: str = ""


@dataclass
class TalkcraftRecord:
    line: str
    video_path: str
    sha256: str
    width: int
    height: int
    duration_s: float
    fps: float
    render_seconds: float
    cards_used: list[str]
    alignment: dict[str, Any]
    gates: list[GateMeasure]
    provenance: dict[str, Any]
    passed: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
