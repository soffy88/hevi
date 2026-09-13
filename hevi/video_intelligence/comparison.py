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
        "PACING": {"expected": intent.expected_pacing, "observed": analysis.statistics.average_shot_duration_ms,
                   "score": None, "status": "NOT_EVALUABLE", "evidence_refs": ["statistics:duration"]},
        "VISUAL_INTENT": {"expected": intent.visual_intents, "observed": None, "score": None,
                          "status": "NOT_EVALUABLE", "evidence_refs": []},
    }
    overall = GateStatus.PASS if all(item["status"] != "WARN" for item in dimensions.values()) else GateStatus.WARN
    return ArtifactComparison(
        comparison_id=f"comparison:{uuid.uuid4().hex}",
        intent_id=intent.intent_id,
        analysis_id=analysis.analysis_id,
        dimensions=dimensions,
        status=overall,
        evidence_refs=[analysis.provenance.source_sha256],
    )
