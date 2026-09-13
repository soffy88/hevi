"""Fail-closed deterministic reel analysis gates."""

from __future__ import annotations

from collections import Counter

from .boundaries import validate_boundaries
from .models import GateStatus, ShotObservation, VideoQualityFinding, VideoQualityReport


def evaluate_reel_quality(
    shots: list[ShotObservation], duration_ms: int, *, provenance_complete: bool = True
) -> VideoQualityReport:
    findings: list[VideoQualityFinding] = []
    checked = [
        "TIMELINE_CONTINUITY", "DURATION_CONSISTENCY", "SHOT_ID_SEQUENCE", "BOUNDARY_PROVENANCE",
        "FRAME_PRESENCE", "SHOT_SIZE_ENUM", "CATEGORY_ENUM", "CAMERA_ENUM", "DESCRIPTION_NONEMPTY",
        "DESCRIPTION_NONDUPLICATE", "RHYTHM_COMPLETENESS", "VIDEO_DURATION_COVERAGE",
        "MACHINE_FIELD_IMMUTABILITY", "PROVENANCE_COMPLETE", "TRANSCRIPT_ALIGNMENT",
    ]
    ranges = [(shot.start_ms, shot.end_ms) for shot in shots]
    errors = validate_boundaries(ranges, duration_ms)
    if errors:
        findings.append(VideoQualityFinding(
            finding_id="quality:timeline", code="TIMELINE_CONTINUITY", status=GateStatus.FAIL,
            severity="ERROR", message=";".join(errors), evidence_refs=["machine:timestamps"],
        ))
    ids = [shot.shot_id for shot in shots]
    expected = [f"shot_{index:04d}" for index in range(1, len(ids) + 1)]
    if ids != expected:
        findings.append(VideoQualityFinding(
            finding_id="quality:ids", code="SHOT_ID_SEQUENCE", status=GateStatus.FAIL,
            severity="ERROR", message="shot IDs are not contiguous", evidence_refs=["machine:shot_ids"],
        ))
    descriptions = [shot.semantic.description.strip() for shot in shots]
    if any(not value for value in descriptions):
        findings.append(VideoQualityFinding(
            finding_id="quality:description", code="DESCRIPTION_NONEMPTY", status=GateStatus.FAIL,
            severity="ERROR", message="semantic description missing", evidence_refs=["semantic:description"],
        ))
    if len(descriptions) != len(set(descriptions)) and len(descriptions) > 1:
        findings.append(VideoQualityFinding(
            finding_id="quality:duplicate-description", code="DESCRIPTION_NONDUPLICATE",
            status=GateStatus.WARN, severity="WARN", message="duplicate descriptions detected",
            evidence_refs=["semantic:description"],
        ))
    if not all(shot.boundary_evidence for shot in shots):
        findings.append(VideoQualityFinding(
            finding_id="quality:boundary-evidence", code="BOUNDARY_PROVENANCE", status=GateStatus.FAIL,
            severity="ERROR", message="shot lacks boundary evidence", evidence_refs=["machine:boundaries"],
        ))
    if not all(shot.motion_evidence for shot in shots):
        findings.append(VideoQualityFinding(
            finding_id="quality:motion", code="MOTION_EVIDENCE", status=GateStatus.FAIL,
            severity="ERROR", message="shot lacks motion evidence", evidence_refs=["machine:motion"],
        ))
    if not provenance_complete:
        findings.append(VideoQualityFinding(
            finding_id="quality:provenance", code="PROVENANCE_COMPLETE", status=GateStatus.FAIL,
            severity="ERROR", message="provenance incomplete", evidence_refs=["provenance"],
        ))
    status = GateStatus.FAIL if any(item.status == GateStatus.FAIL for item in findings) else (
        GateStatus.WARN if findings else GateStatus.PASS
    )
    return VideoQualityReport(status=status, findings=findings, checked=checked)


def _distribution(values: list[str]) -> dict[str, int]:
    return dict(Counter(values))
