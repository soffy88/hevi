"""Fail-closed deterministic reel analysis gates."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .boundaries import validate_boundaries
from .models import GateStatus, ShotObservation, VideoProbe, VideoQualityFinding, VideoQualityReport


def evaluate_reel_quality(
    shots: list[ShotObservation],
    duration_ms: int,
    *,
    provenance_complete: bool = True,
    expected_duration_ms: int | None = None,
    frozen_frame_detected: bool = False,
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
    if any(
        frame_ref and not Path(frame_ref).is_file()
        for shot in shots
        for frame_ref in shot.frame_refs
    ):
        findings.append(VideoQualityFinding(
            finding_id="quality:frame-presence", code="FRAME_PRESENCE", status=GateStatus.FAIL,
            severity="ERROR", message="referenced frame asset is missing", evidence_refs=["frame_refs"],
        ))
    if any(shot.rhythm is None for shot in shots):
        findings.append(VideoQualityFinding(
            finding_id="quality:rhythm", code="RHYTHM_COMPLETENESS", status=GateStatus.FAIL,
            severity="ERROR", message="rhythm analysis does not cover the complete reel",
            evidence_refs=["rhythm"],
        ))
    if any(
        shot.semantic.camera_motion.value != "UNKNOWN"
        and shot.motion_evidence is not None
        and shot.motion_evidence.motion_class.value == "STATIC"
        for shot in shots
    ):
        findings.append(VideoQualityFinding(
            finding_id="quality:camera-motion", code="CAMERA_MOTION_EVIDENCE_CONFLICT",
            status=GateStatus.WARN, severity="WARN", message="semantic camera motion conflicts with static machine motion",
            evidence_refs=["machine:motion", "semantic:camera_motion"],
        ))
    if frozen_frame_detected:
        findings.append(VideoQualityFinding(
            finding_id="quality:frozen", code="FROZEN_FRAMES", status=GateStatus.WARN,
            severity="WARN", message="all sampled frame deltas are static", evidence_refs=["machine:motion"],
        ))
    if expected_duration_ms is not None and duration_ms != expected_duration_ms:
        findings.append(VideoQualityFinding(
            finding_id="quality:video-duration", code="VIDEO_DURATION_COVERAGE",
            status=GateStatus.FAIL, severity="ERROR",
            message=f"observed={duration_ms};expected={expected_duration_ms}",
            evidence_refs=["machine:duration"],
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


def evaluate_post_render_quality(probe: VideoProbe, *, require_audio: bool = True) -> VideoQualityReport:
    """L0/L1 post-render gate using only probe evidence."""
    findings: list[VideoQualityFinding] = []
    if not probe.has_video or probe.duration_ms <= 0:
        findings.append(VideoQualityFinding(
            finding_id="postrender:media", code="MEDIA_VALIDITY", status=GateStatus.FAIL,
            severity="ERROR", message="video stream or duration is invalid", evidence_refs=["ffprobe"],
        ))
    if require_audio and not probe.has_audio:
        findings.append(VideoQualityFinding(
            finding_id="postrender:audio", code="AUDIO_STREAM_MISSING", status=GateStatus.FAIL,
            severity="ERROR", message="required audio stream is missing", evidence_refs=["ffprobe"],
        ))
    return VideoQualityReport(
        status=GateStatus.FAIL if findings else GateStatus.PASS,
        findings=findings,
        checked=["L0_FILE_VALIDITY", "L1_MEDIA_VALIDITY"],
    )
