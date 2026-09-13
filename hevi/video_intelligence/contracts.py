"""Canonical contract snapshot for Video Intelligence v1."""

from __future__ import annotations

from .models import VIDEO_INTELLIGENCE_CONTRACT_VERSION


def contract_snapshot() -> dict[str, object]:
    return {
        "contract_version": VIDEO_INTELLIGENCE_CONTRACT_VERSION,
        "domain_schemas": [
            "VideoAsset", "VideoProbe", "ShotObservation", "ShotBoundaryEvidence", "MotionEvidence",
            "ReelAnalysis", "ReferenceProfile", "IntentProfile", "ArtifactComparison",
            "VideoQualityFinding", "VideoQualityReport", "RevisionFeedback", "VideoTask",
            "VideoAnalysisProvenance",
        ],
        "machine_evidence": ["ffprobe", "ffmpeg_scene_detect", "ffmpeg_gray_frame_delta"],
        "optional_semantic_provider": True,
        "authority": {
            "artifact": "rendered reality",
            "reel_analysis": "observed artifact evidence",
            "quality_report": "evaluation projection",
            "revision_feedback": "proposal only",
        },
    }
