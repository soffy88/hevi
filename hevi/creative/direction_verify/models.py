"""P10d verify models (ObservationSet/Evidence/Verdict). Frozen + validate()."""

from __future__ import annotations

import re
from dataclasses import dataclass

from hevi.creative.direction_verify.errors import VerifyError

RESULTS = ("PASS", "FAIL", "WARN", "INCONCLUSIVE", "NOT_EVALUABLE", "WAIVED")
SEVERITY = ("must", "should", "may")
CLASSES = ("D", "M", "H")
STATUSES = ("PASS", "PASS_WITH_WARNINGS", "REVISE", "FAIL", "INCONCLUSIVE")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ObservationSet:
    artifact_hash: str
    produced_by: str = ""
    produced_at: str = ""
    shot_boundaries: tuple[dict[str, object], ...] = ()
    transcripts: tuple[dict[str, object], ...] = ()
    silence_map: tuple[dict[str, object], ...] = ()

    def validate(self) -> None:
        if not _SHA256.match(self.artifact_hash or ""):
            raise VerifyError("observationset requires artifact_hash", code="OBS_NO_ARTIFACT")


@dataclass(frozen=True)
class DirectionEvidence:
    decision_id: str
    check_id: str
    expected: str = ""
    observed: str = ""
    detector_id: str = ""
    detector_version: str = ""
    calibration_ref: str = ""
    confidence: float = 1.0
    artifact_hash: str = ""
    locator: str = ""

    def validate(self) -> None:
        if not self.artifact_hash or not self.check_id:
            raise VerifyError("evidence requires check_id + artifact_hash", code="EVIDENCE_INCOMPLETE")


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    result: str
    check_class: str
    severity: str
    evidence_refs: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.result not in RESULTS:
            raise VerifyError(f"bad result: {self.result}", code="CHECK_BAD_RESULT")
        if self.check_class not in CLASSES or self.severity not in SEVERITY:
            raise VerifyError(f"bad class/severity: {self.check_id}", code="CHECK_BAD_CLASS")


@dataclass(frozen=True)
class DirectionVerdict:
    artifact_hash: str
    compliance_plan_hash: str
    status: str
    checks: tuple[CheckResult, ...] = ()
    violations: tuple[str, ...] = ()
    suggested_revision: str = ""

    def validate(self) -> None:
        if self.status not in STATUSES:
            raise VerifyError("bad verdict status", code="VERDICT_BAD_STATUS")
        if not _SHA256.match(self.artifact_hash or "") or not self.compliance_plan_hash:
            raise VerifyError("verdict requires artifact_hash + compliance_plan_hash",
                              code="VERDICT_UNBOUND")
        for check in self.checks:
            check.validate()
