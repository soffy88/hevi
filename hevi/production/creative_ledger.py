"""HEVI P5.2 — creative variety memory.

Three consecutive videos that open with the same push-in, cut on the same
beat, and reuse the same accent colour are not three videos; they are one video
shot three times. The ledger notices that.

The point is *anti-repetition*, not novelty. Variety is never injected
randomly: a transition, colour or camera move only changes when the profile,
the narrative phase and the beat semantics call for it. ``RANDOM_VARIATION == 0``
is an invariant, and repetition that is genuinely intended — a motif, a brand
system, tutorial continuity, emotional restraint — is preserved with a recorded
justification rather than being flagged as a defect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from hevi.production.references import audit_summary  # noqa: F401  (parity re-export)


class PatternFamily(StrEnum):
    """The dimensions a shot's visual language is fingerprinted on."""

    LAYOUT = "LAYOUT"
    TRANSITION = "TRANSITION"
    MOTION = "MOTION"
    ENTRANCE = "ENTRANCE"
    EXIT = "EXIT"
    CAMERA = "CAMERA"
    SPEAKER = "SPEAKER"
    EVIDENCE = "EVIDENCE"
    CAPTION = "CAPTION"
    ACCENT = "ACCENT"
    THEME = "THEME"
    DURATION = "DURATION"


class VarietyFindingKind(StrEnum):
    REPEATED_TRANSITION = "REPEATED_TRANSITION"
    REPEATED_ENTRANCE = "REPEATED_ENTRANCE"
    REPEATED_EXIT = "REPEATED_EXIT"
    REPEATED_CAMERA_MOVE = "REPEATED_CAMERA_MOVE"
    REPEATED_LAYOUT = "REPEATED_LAYOUT"
    UNIFORM_SHOT_LENGTH = "UNIFORM_SHOT_LENGTH"
    REPEATED_ACCENT = "REPEATED_ACCENT"
    REPEATED_THEME = "REPEATED_THEME"
    EXCESSIVE_COMPONENT_REUSE = "EXCESSIVE_COMPONENT_REUSE"


#: How many times the same family may repeat before it is a finding.
DEFAULT_REPEAT_LIMIT = 3

#: A shot-length distribution this tight is uniform rather than paced.
UNIFORM_LENGTH_STDEV = 0.12


def duration_bucket(seconds: float) -> str:
    """Coarse shot-length bucket, so near-identical lengths collide."""
    if seconds <= 1.5:
        return "MICRO"
    if seconds <= 3.0:
        return "SHORT"
    if seconds <= 6.0:
        return "MEDIUM"
    if seconds <= 10.0:
        return "LONG"
    return "EPIC"


@dataclass
class VisualPatternFingerprint:
    """What makes a shot look the way it does, in comparable terms."""

    layout_family: str = ""
    transition_family: str = ""
    motion_family: str = ""
    camera_family: str = ""
    speaker_layout: str = ""
    evidence_layout: str = ""
    caption_layout: str = ""
    accent_family: str = ""
    theme_family: str = ""
    duration_bucket: str = ""
    shot_id: str = ""
    video_id: str = ""
    entrance: str = ""
    exit: str = ""
    component: str = ""
    profile_id: str = ""
    narrative_phase: str = ""

    def family(self, kind: PatternFamily) -> str:
        return {
            PatternFamily.LAYOUT: self.layout_family,
            PatternFamily.TRANSITION: self.transition_family,
            PatternFamily.MOTION: self.motion_family,
            PatternFamily.CAMERA: self.camera_family,
            PatternFamily.SPEAKER: self.speaker_layout,
            PatternFamily.EVIDENCE: self.evidence_layout,
            PatternFamily.CAPTION: self.caption_layout,
            PatternFamily.ACCENT: self.accent_family,
            PatternFamily.THEME: self.theme_family,
            PatternFamily.DURATION: self.duration_bucket,
        }[kind]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepetitionJustification:
    """Why a repeat is intentional rather than a defect."""

    scope: str
    key: str
    reason: str
    approved_by: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VarietyFinding:
    kind: VarietyFindingKind
    key: str
    count: int
    shot_ids: list[str] = field(default_factory=list)
    video_ids: list[str] = field(default_factory=list)
    justified: bool = False
    justification: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class VarietyAudit:
    findings: list[VarietyFinding] = field(default_factory=list)
    ok: bool = True
    shot_count: int = 0
    video_count: int = 0
    justified_repetitions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "shot_count": self.shot_count,
            "video_count": self.video_count,
            "justified_repetitions": self.justified_repetitions,
            "findings": [f.to_dict() for f in self.findings],
        }


class CreativeLedger:
    """Remembers the visual language of this and previous productions.

    Cross-video memory exists only to *discourage* repetition. It is never
    consulted to decide what a video should be — that remains P1/P2's job, so
    the ledger can never become a second creative authority.
    """

    def __init__(self, *, repeat_limit: int = DEFAULT_REPEAT_LIMIT) -> None:
        self.repeat_limit = repeat_limit
        self._within: dict[str, list[VisualPatternFingerprint]] = {}
        self._across: dict[str, list[VisualPatternFingerprint]] = {}
        self._justifications: list[RepetitionJustification] = []

    # ── Recording ──
    def record(self, fingerprint: VisualPatternFingerprint, *, cross_video: bool = True) -> None:
        self._within.setdefault(fingerprint.video_id, []).append(fingerprint)
        if cross_video:
            self._across.setdefault(fingerprint.shot_id or fingerprint.video_id, []).append(
                fingerprint
            )

    def shots(self, video_id: str) -> list[VisualPatternFingerprint]:
        return list(self._within.get(video_id, []))

    def all_shots(self) -> list[VisualPatternFingerprint]:
        out: list[VisualPatternFingerprint] = []
        for shots in self._within.values():
            out.extend(shots)
        return out

    def video_ids(self) -> list[str]:
        return list(self._within)

    def history_size(self) -> int:
        return sum(len(v) for v in self._across.values())

    # ── Justified repetition (§25) ──
    def justify(self, scope: str, key: str, reason: str, *, approved_by: str = "system") -> None:
        """Record that a repeated family is intentional."""
        if not reason.strip():
            raise ValueError("a justification must say why; empty is not a justification")
        self._justifications.append(
            RepetitionJustification(scope=scope, key=key, reason=reason, approved_by=approved_by)
        )

    def justifications(self) -> list[RepetitionJustification]:
        return list(self._justifications)

    def is_justified(self, kind: PatternFamily, key: str) -> bool:
        return any(
            item.scope == "family" and item.key == f"{kind.value}:{key}"
            for item in self._justifications
        )

    # ── Audit (§23) ──
    def audit(
        self,
        *,
        video_id: str = "",
        include_cross_video: bool = True,
        components: dict[str, int] | None = None,
    ) -> VarietyAudit:
        """Audit repetition within a cut and, optionally, against history."""
        shots = self.shots(video_id) if video_id else self.all_shots()
        audit = VarietyAudit(shot_count=len(shots), video_count=len(self._within))
        if len(shots) < 2:
            audit.ok = True
            return audit

        families = {
            PatternFamily.TRANSITION: (VarietyFindingKind.REPEATED_TRANSITION, "transition_family"),
            PatternFamily.LAYOUT: (VarietyFindingKind.REPEATED_LAYOUT, "layout_family"),
            PatternFamily.CAMERA: (VarietyFindingKind.REPEATED_CAMERA_MOVE, "camera_family"),
            PatternFamily.ACCENT: (VarietyFindingKind.REPEATED_ACCENT, "accent_family"),
            PatternFamily.THEME: (VarietyFindingKind.REPEATED_THEME, "theme_family"),
        }
        for kind, (finding_kind, attribute) in families.items():
            by_value: dict[str, list[VisualPatternFingerprint]] = {}
            for shot in shots:
                value = getattr(shot, attribute)
                if value:
                    by_value.setdefault(value, []).append(shot)
            for value, group in by_value.items():
                if len(group) <= self.repeat_limit:
                    continue
                finding = VarietyFinding(
                    kind=finding_kind,
                    key=value,
                    count=len(group),
                    shot_ids=[s.shot_id for s in group],
                    video_ids=sorted({s.video_id for s in group}),
                )
                if self.is_justified(kind, value):
                    finding.justified = True
                    finding.justification = "intentional motif / brand / continuity"
                    audit.justified_repetitions += 1
                audit.findings.append(finding)

        # Entrance and exit get their own justification families. Sharing
        # MOTION with the camera-move family would let one justification for
        # "push_in" silently excuse a repeated entrance effect too.
        for attribute, finding_kind, family in (
            ("entrance", VarietyFindingKind.REPEATED_ENTRANCE, PatternFamily.ENTRANCE),
            ("exit", VarietyFindingKind.REPEATED_EXIT, PatternFamily.EXIT),
        ):
            by_value = {}
            for shot in shots:
                value = getattr(shot, attribute)
                if value:
                    by_value.setdefault(value, []).append(shot)
            for value, group in by_value.items():
                if len(group) <= self.repeat_limit:
                    continue
                finding = VarietyFinding(
                    kind=finding_kind,
                    key=value,
                    count=len(group),
                    shot_ids=[s.shot_id for s in group],
                )
                if self.is_justified(family, value):
                    finding.justified = True
                    finding.justification = "intentional motif / brand / continuity"
                    audit.justified_repetitions += 1
                audit.findings.append(finding)

        lengths = [_length_seconds(shot) for shot in shots]
        if len(lengths) >= 4 and _stdev(lengths) <= UNIFORM_LENGTH_STDEV:
            audit.findings.append(
                VarietyFinding(
                    kind=VarietyFindingKind.UNIFORM_SHOT_LENGTH,
                    key="uniform",
                    count=len(lengths),
                    shot_ids=[s.shot_id for s in shots],
                    justified=self.is_justified(PatternFamily.DURATION, "uniform"),
                )
            )
            if audit.findings[-1].justified:
                audit.justified_repetitions += 1

        for component, count in (components or {}).items():
            if count > self.repeat_limit * 3:
                finding = VarietyFinding(
                    kind=VarietyFindingKind.EXCESSIVE_COMPONENT_REUSE,
                    key=component,
                    count=count,
                )
                if self.is_justified(PatternFamily.MOTION, component):
                    finding.justified = True
                    finding.justification = "intentional motif / brand / continuity"
                    audit.justified_repetitions += 1
                audit.findings.append(finding)

        if include_cross_video and video_id:
            for finding in audit.findings:
                if not finding.video_ids:
                    finding.video_ids = [video_id]
                history = [
                    shot
                    for shot in self.all_shots()
                    if shot.video_id != video_id
                    and getattr(shot, _attribute_for(finding.kind), "") == finding.key
                ]
                if history and not finding.justified:
                    finding.video_ids = sorted({*finding.video_ids, *(h.video_id for h in history)})

        audit.ok = not [f for f in audit.findings if not f.justified]
        return audit

    def to_dict(self) -> dict[str, Any]:
        return {
            "repeat_limit": self.repeat_limit,
            "videos": {vid: len(shots) for vid, shots in self._within.items()},
            "history_size": self.history_size(),
            "justifications": [j.to_dict() for j in self._justifications],
        }


def _attribute_for(kind: VarietyFindingKind) -> str:
    return {
        VarietyFindingKind.REPEATED_TRANSITION: "transition_family",
        VarietyFindingKind.REPEATED_LAYOUT: "layout_family",
        VarietyFindingKind.REPEATED_CAMERA_MOVE: "camera_family",
        VarietyFindingKind.REPEATED_ACCENT: "accent_family",
        VarietyFindingKind.REPEATED_THEME: "theme_family",
        VarietyFindingKind.REPEATED_ENTRANCE: "entrance",
        VarietyFindingKind.REPEATED_EXIT: "exit",
    }.get(kind, "transition_family")


def _length_seconds(shot: VisualPatternFingerprint) -> float:
    table = {"MICRO": 1.2, "SHORT": 2.4, "MEDIUM": 4.5, "LONG": 8.0, "EPIC": 13.0}
    return table.get(shot.duration_bucket, 4.0)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return float(variance**0.5)


def fingerprint_from_shot(
    shot_id: str,
    video_id: str,
    *,
    layout: str,
    transition: str,
    motion: str,
    camera: str,
    speaker_layout: str = "",
    evidence_layout: str = "",
    caption_layout: str = "",
    accent: str = "",
    theme: str = "",
    duration_s: float = 0.0,
    entrance: str = "",
    exit: str = "",
    component: str = "",
    profile_id: str = "",
    narrative_phase: str = "",
) -> VisualPatternFingerprint:
    """Build a fingerprint from a resolved shot."""
    return VisualPatternFingerprint(
        layout_family=layout,
        transition_family=transition,
        motion_family=motion,
        camera_family=camera,
        speaker_layout=speaker_layout,
        evidence_layout=evidence_layout,
        caption_layout=caption_layout,
        accent_family=accent,
        theme_family=theme,
        duration_bucket=duration_bucket(duration_s),
        shot_id=shot_id,
        video_id=video_id,
        entrance=entrance,
        exit=exit,
        component=component,
        profile_id=profile_id,
        narrative_phase=narrative_phase,
    )


__all__ = [
    "DEFAULT_REPEAT_LIMIT",
    "UNIFORM_LENGTH_STDEV",
    "CreativeLedger",
    "PatternFamily",
    "RepetitionJustification",
    "VarietyAudit",
    "VarietyFinding",
    "VarietyFindingKind",
    "VisualPatternFingerprint",
    "duration_bucket",
    "fingerprint_from_shot",
]
