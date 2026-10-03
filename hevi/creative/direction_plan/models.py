"""P10c time-directed objects (Decision/Beat/Cue/Camera/Sound/Signature).

Frozen dataclasses + validate(). Anchors carry coordinate system (R-P10-01):
`coordinate: line-local | film-global`; CompliancePlan accepts film-global only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from hevi.creative.direction_plan.errors import PlanValidationError

OPS = ("set", "add", "remove")
STATUSES = ("PROPOSED", "APPROVED", "REJECTED", "SUPERSEDED", "STALE")
SEVERITY = ("must", "should", "may")
CHECK_CLASSES = ("D", "M", "H")
GEOMETRY = ("extrinsic", "intrinsic", "mixed", "subject_relative")
MOVEMENT_TYPES = ("static", "pan", "tilt", "push_in", "pull_back", "pull_out", "dolly", "truck",
                  "crane", "orbit", "handheld", "whip", "zoom_in", "zoom_out", "follow")


def plan_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                   default=_default).encode()).hexdigest()


def _default(value: object) -> object:
    import dataclasses

    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)  # type: ignore[arg-type]
    if isinstance(value, tuple):
        return list(value)
    return str(value)


# ── Anchor / TimeBinding ──


@dataclass(frozen=True)
class Anchor:
    type: str
    target: str
    edge: str = "end"
    offset_ms: int = 0
    coordinate: str = "line-local"  # line-local | film-global (R-P10-01)

    def key(self) -> str:
        return f"{self.type}:{self.target}:{self.edge}:{self.offset_ms}"


@dataclass(frozen=True)
class TimeBinding:
    anchor: Anchor
    tolerance_class: str = "EVENT_LOOSE"


# ── Decision ──


@dataclass(frozen=True)
class FieldChange:
    node_ref: str
    field_path: str
    op: str
    value_hash: str = ""


@dataclass(frozen=True)
class DirectionDecision:
    id: str
    revision: int
    category: str
    proposition: str = ""
    change_set: tuple[FieldChange, ...] = ()
    rationale: str = ""
    evidence: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    impact_class: str = "normal"
    status: str = "PROPOSED"

    def validate(self) -> None:
        if self.status not in STATUSES:
            raise PlanValidationError(f"decision {self.id}: bad status", code="DECISION_BAD_STATUS")
        for change in self.change_set:
            if change.op not in OPS:
                raise PlanValidationError(f"decision {self.id}: bad op", code="DECISION_BAD_OP")
            if not change.node_ref or not change.field_path:
                raise PlanValidationError(f"decision {self.id}: change unlocatable",
                                          code="DECISION_UNLOCATABLE")
        if self.status == "APPROVED" and not self.change_set:
            raise PlanValidationError(f"decision {self.id}: APPROVED requires change_set",
                                      code="DECISION_NO_CHANGESET")


# ── Beat ──


@dataclass(frozen=True)
class Beat:
    id: str
    start: Anchor
    end: Anchor
    narrative_function: str = ""
    emotional_function: str = ""
    intensity: float = 0.5
    pacing: str = ""
    visual_energy: float = 0.5
    audio_energy: float = 0.5
    transition_in: str = ""
    transition_out: str = ""


@dataclass(frozen=True)
class CurveSample:
    beat_id: str
    value_0_1: float


@dataclass(frozen=True)
class Curve:
    name: str
    samples: tuple[CurveSample, ...] = ()
    proxy: str = ""


@dataclass(frozen=True)
class BeatPlan:
    beats: tuple[Beat, ...] = ()
    curves: tuple[Curve, ...] = ()

    def validate(self) -> None:
        if not self.beats:
            raise PlanValidationError("beat plan empty", code="BEAT_EMPTY")
        ids = [b.id for b in self.beats]
        if len(set(ids)) != len(ids):
            raise PlanValidationError("duplicate beat id", code="BEAT_DUP_ID")
        for prev, nxt in zip(self.beats, self.beats[1:], strict=False):
            if prev.end.key() != nxt.start.key():
                raise PlanValidationError(f"beat coverage gap: {prev.id} -> {nxt.id}",
                                          code="BEAT_COVERAGE_GAP")
        known = set(ids)
        for curve in self.curves:
            for sample in curve.samples:
                if sample.beat_id not in known:
                    raise PlanValidationError(f"curve {curve.name}: unknown beat",
                                              code="BEAT_CURVE_DANGLING")

    def h_class_curves(self) -> list[str]:
        return [c.name for c in self.curves if not c.proxy]


# ── Cue ──


@dataclass(frozen=True)
class CueAction:
    id: str
    modality: str
    intent: dict[str, object] = field(default_factory=dict)
    required: str = "should"
    compose: str = ""  # override | additive (required on overlap)
    verification_class: str = "H"
    detector: str = ""
    tolerance_class: str = "EVENT_LOOSE"

    def validate(self) -> None:
        if self.required not in SEVERITY:
            raise PlanValidationError(f"action {self.id}: bad severity", code="CUE_BAD_SEVERITY")
        if self.verification_class not in CHECK_CLASSES:
            raise PlanValidationError(f"action {self.id}: bad class", code="CUE_BAD_CLASS")


@dataclass(frozen=True)
class Cue:
    id: str
    at: TimeBinding
    trigger: str = ""
    priority: int = 3
    beat_ref: str = ""
    decision_refs: tuple[str, ...] = ()
    rationale: str = ""
    until: TimeBinding | None = None
    actions: tuple[CueAction, ...] = ()

    def validate(self) -> None:
        if not self.actions:
            raise PlanValidationError(f"cue {self.id}: no actions", code="CUE_EMPTY")
        for action in self.actions:
            action.validate()
        seen: dict[tuple[str, str], str] = {}
        for action in self.actions:
            key = (action.modality, self.at.anchor.key())
            if key in seen and (not action.compose or not seen[key]):
                raise PlanValidationError(f"cue {self.id}: CUE_CONFLICT on {action.modality}",
                                          code="CUE_CONFLICT")
            seen[key] = action.compose

    def expand_to_plan(self) -> list[dict[str, object]]:
        return [{"check_id": f"{self.id}:{a.id}", "modality": a.modality,
                 "class": a.verification_class, "detector": a.detector,
                 "tolerance_class": a.tolerance_class, "severity": a.required}
                for a in self.actions]


@dataclass(frozen=True)
class CueMap:
    cues: tuple[Cue, ...] = ()

    def validate(self) -> None:
        for cue in self.cues:
            cue.validate()


# ── Camera ──


@dataclass(frozen=True)
class Movement:
    type: str = "static"
    geometry_class: str = "extrinsic"
    motivation_type: str = ""
    motivation_reason: str = ""
    intensity: str = "subtle"
    magnitude_metric: str = ""
    mag_min: float = 0.0
    mag_max: float = 0.0


@dataclass(frozen=True)
class CameraSpec:
    shot_size: str = "wide"
    framing: str = ""
    angle: str = "eye"
    lens: str = "normal"
    depth: str = ""
    composition: str = ""
    lighting: str = ""
    blocking: str = ""
    movement: Movement = field(default_factory=Movement)

    def validate(self) -> None:
        if self.movement.type not in MOVEMENT_TYPES:
            raise PlanValidationError(f"unknown movement: {self.movement.type}",
                                      code="CAMERA_BAD_MOVEMENT")
        if self.movement.geometry_class not in GEOMETRY:
            raise PlanValidationError("bad geometry_class", code="CAMERA_BAD_GEOMETRY")

    def h_class_items(self) -> list[str]:
        m = self.movement
        if m.type != "static" and not m.magnitude_metric:
            return [f"movement {m.type}: intensity without expected_magnitude"]
        return []

    def signature_hash(self) -> str:
        return plan_hash([self.shot_size, self.framing, self.angle, self.lens,
                          self.composition, self.movement.type, self.movement.geometry_class])


@dataclass(frozen=True)
class SignatureShot:
    id: str
    narrative_role: str = ""
    visual_role: str = ""
    emotional_role: str = ""
    camera: CameraSpec = field(default_factory=CameraSpec)
    lighting: str = ""
    sound: str = ""
    constraints: str = ""
    uniqueness_reason: str = ""

    def validate(self) -> None:
        self.camera.validate()
        if not self.uniqueness_reason:
            raise PlanValidationError(f"signature {self.id}: uniqueness_reason required",
                                      code="SIGNATURE_NO_REASON")


def check_signature_unique(shots: list[SignatureShot]) -> None:
    seen: dict[str, str] = {}
    for shot in shots:
        digest = shot.camera.signature_hash()
        if digest in seen:
            raise PlanValidationError(f"signature duplicate: {shot.id} vs {seen[digest]}",
                                      code="SIGNATURE_DUPLICATE")
        seen[digest] = shot.id


# ── Sound ──


@dataclass(frozen=True)
class Silence:
    id: str
    at: TimeBinding
    duration_ms: int = 0
    scope: tuple[str, ...] = ()
    allow: tuple[str, ...] = ()
    kind: str = ""
    floor_relative_to: str = ""
    floor_drop_db: float = 0.0
    reason: str = ""

    def validate(self) -> None:
        if not self.scope:
            raise PlanValidationError(f"silence {self.id}: scope required",
                                      code="SILENCE_NO_SCOPE")
        if self.duration_ms <= 0:
            raise PlanValidationError(f"silence {self.id}: bad duration",
                                      code="SILENCE_BAD_DURATION")


@dataclass(frozen=True)
class SoundDirection:
    voice_intent: dict[str, object] = field(default_factory=dict)
    music_intent: dict[str, object] = field(default_factory=dict)
    silences: tuple[Silence, ...] = ()
    foley: dict[str, object] = field(default_factory=dict)
    ambience: dict[str, object] = field(default_factory=dict)
    transitions: dict[str, object] = field(default_factory=dict)

    def validate(self) -> None:
        for silence in self.silences:
            silence.validate()
