"""Zero-cost line primitives: line specs, QA thresholds, request contract.

Pure data only (oprim layer): no IO, no subprocess, no imports from the
oskill/omodul siblings.  Every number here is a *gate*, not a claim: the
omodul transaction measures the rendered MP4 and compares it with these.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: the 12 canonical Studio lines that have a zero-cost (CPU, no paid API) engine
ZERO_LINES: tuple[str, ...] = (
    "kinetic_promo",
    "explainer",
    "cinematic",
    "director_pipeline",
    "history_scene",
    "character_animation",
    "talking_head",
    "avatar_spokesperson",
    "shorts_clip",
    "podcast_repurpose",
    "reference_adapt",
    "comic_narration",
)

#: canonical lines that intentionally keep their original implementation only
LEGACY_ONLY_LINES: tuple[str, ...] = ("documentary_montage", "localization_dub")

ENGINES: tuple[str, ...] = ("zero", "legacy")


@dataclass(frozen=True)
class QAThresholds:
    """Measured-gate thresholds.  ``None`` = check not applicable to this format
    (the record lists it under ``checks_not_applicable`` with the reason)."""

    min_motion: float = 1.0
    max_static_ratio: float = 0.5
    max_black_ratio: float | None = 0.1
    max_dark_ratio: float | None = 0.5
    min_volume_db: float = -45.0
    expect_audio: bool = True
    min_duration_s: float = 6.0
    not_applicable_reason: str = ""


@dataclass(frozen=True)
class ZeroLineSpec:
    line_id: str
    width: int
    height: int
    inputs: tuple[str, ...]  # required request fields
    qa: QAThresholds = field(default_factory=QAThresholds)
    max_texts: int | None = None
    description: str = ""


_DEF = QAThresholds()

LINE_SPECS: dict[str, ZeroLineSpec] = {
    "kinetic_promo": ZeroLineSpec(
        "kinetic_promo", 1280, 720, ("texts", "queries"),
        description="stock b-roll + per-clause kinetic typography (ASS transforms) + bright BGM",
    ),
    "explainer": ZeroLineSpec(
        "explainer", 1280, 720, ("texts", "queries"),
        description="one stock shot per narration line, numbered headings, captions",
    ),
    "cinematic": ZeroLineSpec(
        "cinematic", 1280, 720, ("texts", "queries"),
        # letterbox bars (2 x 12% of height) + night grade: black frames are by design,
        # so the black-frame ceiling is raised to 0.25 (still gated), dark-card stays 0.5
        qa=QAThresholds(max_black_ratio=0.25),
        description="graded letterboxed b-roll film, slower read, title card",
    ),
    "director_pipeline": ZeroLineSpec(
        "director_pipeline", 1280, 720, ("texts", "queries"),
        description="rule-based director: beat -> shot spec (size/camera/query) -> assembly; writes shot_list.json",
    ),
    "history_scene": ZeroLineSpec(
        "history_scene", 1280, 720, ("texts", "queries"),
        description="archival-graded b-roll, year/label lower-thirds",
    ),
    "character_animation": ZeroLineSpec(
        "character_animation", 1280, 720, ("texts",),
        qa=QAThresholds(min_motion=0.4, min_duration_s=8.0),
        max_texts=4,
        description="procedural 2D caveman (PIL): walk, crouch+pick stone, light torch, turn; lines timed to actions",
    ),
    "talking_head": ZeroLineSpec(
        "talking_head", 1280, 720, ("texts",),
        qa=QAThresholds(min_motion=0.3),
        description="2D illustrated presenter, mouth driven by VO RMS (5 visemes); not a photoreal avatar",
    ),
    "avatar_spokesperson": ZeroLineSpec(
        "avatar_spokesperson", 1280, 720, ("texts", "queries"),
        description="stock b-roll + circular 2D presenter PiP (RMS lip-sync) + lower third + CTA card",
    ),
    "shorts_clip": ZeroLineSpec(
        "shorts_clip", 720, 1280, ("media_path",),
        description="whisper word timestamps -> 18-32 s windows -> 9:16 blurred-fill reframe + word captions",
    ),
    "podcast_repurpose": ZeroLineSpec(
        "podcast_repurpose", 1080, 1080, ("media_path",),
        qa=QAThresholds(
            min_motion=0.5, max_dark_ratio=None,
            not_applicable_reason="audiogram uses a deliberate dark backdrop; gated by motion/static instead",
        ),
        description="audiogram: cover + live waveform + captions + progress bar",
    ),
    "reference_adapt": ZeroLineSpec(
        "reference_adapt", 1280, 720, ("media_path", "texts", "offsets"),
        # orbital night passes in the reference are legitimately black
        qa=QAThresholds(max_black_ratio=0.35),
        description="re-structured reference segments + new narration, grade, moves, transitions",
    ),
    "comic_narration": ZeroLineSpec(
        "comic_narration", 1080, 1920, ("topic",),
        qa=QAThresholds(min_motion=0.5, min_duration_s=10.0),
        description="Pixelle-style comic narration: prompt/story -> script -> per-sentence AI keyframes + TTS + BGM + Ken Burns + subtitles",
    ),
}


@dataclass(frozen=True)
class ZeroLineRequest:
    line_id: str
    texts: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    topic: str = ""
    title: str = ""
    lang: str = "zh"
    media_path: str = ""
    offsets: tuple[float, ...] = ()
    labels: tuple[str, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        spec = LINE_SPECS.get(self.line_id)
        if spec is None:
            return [f"line {self.line_id!r} has no zero-cost engine"]
        errors: list[str] = []
        for name in spec.inputs:
            if not getattr(self, name):
                if self.line_id == "comic_narration" and name == "topic" and self.texts:
                    continue
                errors.append(f"{self.line_id}: missing required input {name!r}")
        if "queries" in spec.inputs and self.texts and self.queries and self.line_id not in {
            "kinetic_promo", "avatar_spokesperson"
        } and len(self.queries) < len(self.texts):
            errors.append(f"{self.line_id}: need one b-roll query per narration line "
                          f"({len(self.queries)} queries for {len(self.texts)} lines)")
        if self.line_id == "reference_adapt" and self.offsets and len(self.offsets) != len(self.texts):
            errors.append("reference_adapt: offsets must align 1:1 with texts")
        if spec.max_texts is not None and len(self.texts) > spec.max_texts:
            errors.append(f"{self.line_id}: at most {spec.max_texts} narration lines")
        if self.lang not in ("zh", "en"):
            errors.append(f"unsupported language {self.lang!r} (zh|en)")
        if any(not t.strip() for t in self.texts):
            errors.append("empty narration line")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_engine(*, line_id: str, slot_engine: Any = None, env_engine: Any = None) -> str:
    """Engine policy: explicit order slot > deployment env (HEVI_LINE_ENGINE) > legacy.

    Lines without a zero implementation always resolve to ``legacy``.  An
    unknown engine name is an error (never silently mapped).
    """
    raw = slot_engine if slot_engine not in (None, "") else env_engine
    chosen = str(raw).strip().lower() if raw not in (None, "") else "legacy"
    if chosen not in ENGINES:
        raise ValueError(f"unknown line engine {chosen!r}; expected one of {ENGINES}")
    if line_id not in ZERO_LINES:
        return "legacy"
    return chosen


def spec_for(line_id: str) -> ZeroLineSpec:
    try:
        return LINE_SPECS[line_id]
    except KeyError as exc:
        raise KeyError(f"no zero-cost spec for {line_id!r}") from exc


__all__ = [
    "ENGINES",
    "LEGACY_ONLY_LINES",
    "LINE_SPECS",
    "QAThresholds",
    "ZERO_LINES",
    "ZeroLineRequest",
    "ZeroLineSpec",
    "resolve_engine",
    "spec_for",
]
