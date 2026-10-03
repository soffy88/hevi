"""P10-E canonical ShotSpec contract.

A ShotSpec is the *reference* layer between one direction revision and the
existing ShotIntent/ShotPlan authority: it pins, per shot, the timing anchors,
the camera directive, the upstream refs, the content pins it depends on, and the
verification contract that a later verdict consumes.

What it deliberately does not own (reuse-first, no duplicate authority):
  - camera / movement / check-class / severity vocabulary -> P10c direction_plan
  - anchors and time bindings, and the film-global rule (R-P10-01) -> P10c Anchor
  - the 4 content pins of a revision -> P10b direction_content
  - lifecycle and revision authority -> P10a direction_state
  - shot selection and planning -> existing ShotSelector / ShotPlanner (H1)

References are only ever recorded as ids + digests; this layer never writes to
Canon / Style / Asset / Provider and imports none of them (locked by test).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from hevi.creative.direction_plan.models import (
    CHECK_CLASSES,
    SEVERITY,
    CameraSpec,
    TimeBinding,
)
from hevi.creative.direction_shot.errors import ShotSpecError
from hevi.creative.direction_shot.hashing import is_hash, shot_spec_hash

SHOT_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED", "STALE")
# Same four keys P10b pins per revision; a ShotSpec carries them, never renames them.
CONTENT_PIN_KEYS = ("brief", "thesis", "benchmarks", "treatment")
FILM_GLOBAL = "film-global"


@dataclass(frozen=True)
class ShotTiming:
    """Both edges of one shot, in the film-global coordinate (R-P10-01).

    start and end must share an anchor target so that offsets are directly
    comparable; a spec that spans two targets cannot be ordered deterministically
    here and is rejected rather than guessed at.
    """

    start: TimeBinding
    end: TimeBinding

    def validate(self) -> None:
        for label, binding in (("start", self.start), ("end", self.end)):
            if binding.anchor.coordinate != FILM_GLOBAL:
                raise ShotSpecError(
                    f"shot timing {label} must be {FILM_GLOBAL} (R-P10-01), "
                    f"got {binding.anchor.coordinate or 'unset'}",
                    code="SHOT_COORDINATE_NOT_FILM_GLOBAL")
        if self.start.anchor.target != self.end.anchor.target:
            raise ShotSpecError(
                "shot timing start/end must share one anchor target",
                code="SHOT_TIMING_TARGET_MISMATCH")
        if self.end.anchor.offset_ms < self.start.anchor.offset_ms:
            raise ShotSpecError("shot timing end precedes start", code="SHOT_TIMING_INVERTED")

    def order_key(self) -> tuple[str, str, str, int, int]:
        """Comparable key for overlap detection: (target, type, edge, start, end)."""
        return (self.start.anchor.target, self.start.anchor.type,
                self.start.anchor.edge, self.start.anchor.offset_ms,
                self.end.anchor.offset_ms)


@dataclass(frozen=True)
class ShotVerification:
    """One check a later compliance verdict must evaluate for this shot.

    `detector` is bound here, not resolved: P10d owns calibration and refuses
    PASS/FAIL from an uncalibrated detector, so binding a name is all this layer
    can honestly claim. Class H entries carry no detector by design — the Q4
    attestation surface does not exist yet, so they surface as findings instead
    of being signed off.
    """

    check_id: str
    severity: str = "should"
    check_class: str = "D"
    detector: str = ""
    tolerance_class: str = "EVENT_LOOSE"

    def validate(self) -> None:
        if not self.check_id:
            raise ShotSpecError("verification check_id required", code="SHOT_CHECK_NO_ID")
        if self.severity not in SEVERITY:
            raise ShotSpecError(f"{self.check_id}: bad severity {self.severity!r}",
                                code="SHOT_BAD_SEVERITY")
        if self.check_class not in CHECK_CLASSES:
            raise ShotSpecError(f"{self.check_id}: bad check_class {self.check_class!r}",
                                code="SHOT_BAD_CLASS")
        if self.check_class != "H" and not self.detector:
            raise ShotSpecError(f"{self.check_id}: class {self.check_class} needs a bound detector",
                                code="SHOT_DETECTOR_UNBOUND")


@dataclass(frozen=True)
class ShotSpec:
    shot_id: str
    revision: int
    timing: ShotTiming
    camera: CameraSpec = field(default_factory=CameraSpec)
    beat_ref: str = ""
    cue_refs: tuple[str, ...] = ()
    decision_refs: tuple[str, ...] = ()
    verification: tuple[ShotVerification, ...] = ()
    content_pins: dict[str, str] = field(default_factory=dict)
    authority_pins: tuple[str, ...] = ()
    status: str = "DRAFT"
    spec_hash: str = ""

    def validate(self) -> None:
        if not self.shot_id:
            raise ShotSpecError("shot_id required", code="SHOT_NO_ID")
        if self.revision < 1:
            raise ShotSpecError(f"shot {self.shot_id}: revision must be >= 1",
                                code="SHOT_BAD_REVISION")
        if self.status not in SHOT_STATUSES:
            raise ShotSpecError(f"shot {self.shot_id}: bad status {self.status!r}",
                                code="SHOT_BAD_STATUS")
        self.timing.validate()
        self.camera.validate()  # P10c vocabulary: movement/geometry types, reused not copied
        for check in self.verification:
            check.validate()
        for key in CONTENT_PIN_KEYS:
            if not is_hash(self.content_pins.get(key, "")):
                raise ShotSpecError(
                    f"shot {self.shot_id}: content pin {key!r} missing or not sha256 hex",
                    code="SHOT_PINS_INCOMPLETE")
        if self.status != "DRAFT" and not self.verification:
            raise ShotSpecError(
                f"shot {self.shot_id}: status {self.status} requires verification entries",
                code="SHOT_NO_VERIFICATION")
        if self.spec_hash and self.spec_hash != self.compute_hash():
            raise ShotSpecError(f"shot {self.shot_id}: spec_hash does not match payload",
                                code="SHOT_HASH_MISMATCH")

    def compute_hash(self) -> str:
        return shot_spec_hash(self)

    def sealed(self) -> ShotSpec:
        """Return the same spec with its own digest bound (hash excludes the field)."""
        return replace(self, spec_hash=self.compute_hash())

    def h_class_musts(self) -> list[str]:
        """`must` class-H checks with no detector: not attestable, yet not evaluable."""
        return [c.check_id for c in self.verification
                if c.check_class == "H" and c.severity == "must" and not c.detector]
