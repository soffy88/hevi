"""Intent/artifact comparison emits proposals, never upstream mutations."""

from __future__ import annotations

import uuid
from typing import Any

from .models import ArtifactComparison, GateStatus, IntentProfile, ReelAnalysis


def compare_intent_to_artifact(intent: IntentProfile, analysis: ReelAnalysis) -> ArtifactComparison:
    observed_count = analysis.statistics.shot_count
    count_status = "NOT_EVALUABLE"
    count_score = None
    if intent.expected_shot_count_range:
        low, high = intent.expected_shot_count_range
        count_status = "PASS" if low <= observed_count <= high else "WARN"
        count_score = 1.0 if count_status == "PASS" else 0.0
    dimensions: dict[str, dict[str, Any]] = {
        "SHOT_COUNT": {"expected": intent.expected_shot_count_range, "observed": observed_count,
                       "score": count_score, "status": count_status, "evidence_refs": ["statistics:shot_count"]},
    }
    if intent.expected_pacing:
        average = analysis.statistics.average_shot_duration_ms
        pacing_ranges = {"fast": (0, 3000), "medium": (3000, 7000), "slow": (7000, float("inf"))}
        pace_low, pace_high = pacing_ranges.get(intent.expected_pacing.lower(), (0, -1))
        pacing_status = "PASS" if pace_low <= average <= pace_high else "WARN"
        dimensions["PACING"] = {
            "expected": intent.expected_pacing,
            "observed": average,
            "score": 1.0 if pacing_status == "PASS" else 0.0,
            "status": pacing_status,
            "evidence_refs": ["statistics:average_shot_duration_ms"],
        }
    if intent.visual_intents:
        dimensions["VISUAL_INTENT"] = {
            "expected": intent.visual_intents,
            "observed": None,
            "score": None,
            "status": "NOT_EVALUABLE",
            "evidence_refs": [],
        }
    statuses = {item["status"] for item in dimensions.values()}
    overall = (
        GateStatus.FAIL if "FAIL" in statuses else
        GateStatus.WARN if "WARN" in statuses else
        GateStatus.NOT_EVALUABLE if "NOT_EVALUABLE" in statuses else
        GateStatus.PASS
    )
    return ArtifactComparison(
        comparison_id=f"comparison:{uuid.uuid4().hex}",
        intent_id=intent.intent_id,
        analysis_id=analysis.analysis_id,
        dimensions=dimensions,
        status=overall,
        evidence_refs=[analysis.provenance.source_sha256],
    )
