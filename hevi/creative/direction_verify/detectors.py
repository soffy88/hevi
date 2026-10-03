"""P10d detector registry + calibration (QA's QA). Uncalibrated = ADVISORY_ONLY."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.creative.direction_verify.errors import VerifyError

# 构造即真值的强制 fixture 键(R-P10-03:内容必须非周期)
REQUIRED_FIXTURES = ("parallax_zoom_vs_dolly", "shortest_silence", "known_av_offset",
                     "no_change_control")


@dataclass(frozen=True)
class Calibration:
    fixture_set: tuple[str, ...] = ()
    precision: float = 0.0
    recall: float = 0.0
    threshold_theta: float = 0.0
    calibrated_at: str = ""


@dataclass
class Detector:
    id: str
    version: str
    check_class: str
    supported_checks: tuple[str, ...] = ()
    calibration: Calibration | None = None
    status: str = "ADVISORY_ONLY"


class DetectorRegistry:
    def __init__(self) -> None:
        self._detectors: dict[str, Detector] = {}

    def register(self, detector: Detector) -> Detector:
        if detector.status == "ENABLED_FOR_PASS" and detector.calibration is None:
            raise VerifyError(f"detector {detector.id}: ENABLED_FOR_PASS requires calibration",
                              code="DETECTOR_UNCALIBRATED")
        self._detectors[detector.id] = detector
        return detector

    def calibrate(self, detector_id: str, calibration: Calibration) -> Detector:
        missing = [f for f in REQUIRED_FIXTURES if f not in calibration.fixture_set]
        if missing:
            raise VerifyError(f"calibration missing fixtures: {missing}",
                              code="CALIBRATION_INCOMPLETE")
        current = self._detectors[detector_id]
        enabled = Detector(current.id, current.version, current.check_class,
                           current.supported_checks, calibration, "ENABLED_FOR_PASS")
        self._detectors[detector_id] = enabled
        return enabled

    def issue(self, detector_id: str, result: str, confidence: float) -> str:
        """Gate for PASS/FAIL issuance. Uncalibrated/low-confidence -> INCONCLUSIVE."""
        detector = self._detectors[detector_id]
        if result in ("PASS", "FAIL"):
            if detector.status != "ENABLED_FOR_PASS":
                return "INCONCLUSIVE"
            theta = detector.calibration.threshold_theta if detector.calibration else 1.0
            if confidence < theta:
                return "INCONCLUSIVE"
        return result
