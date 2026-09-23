from __future__ import annotations

import pytest

from hevi.video_intelligence.case_analysis import CaseAnalysis, TemporalComplexity
from hevi.video_intelligence.case_models import VideoCase
from hevi.video_intelligence.patterns import (
    PatternStatus,
    distill_prompt_template,
    extract_pattern_candidate,
    promote_template,
    qualify_template,
)
from hevi.video_intelligence.reproduction import (
    CaseReproduction,
    ReproductionMode,
    ReproductionStatus,
)


def test_single_success_remains_candidate() -> None:
    case = VideoCase(id="c1", user_id="u1", title="case")
    analysis = CaseAnalysis(
        analysis_id="a1", case_id="c1",
        temporal_structure=TemporalComplexity(duration_s=5, distinct_actions=1, camera_events=0, subject_state_changes=0, scene_state_changes=0, complexity_score=1),
    )
    reproduction = CaseReproduction(
        id="r1", case_id="c1", provider="p", model="m", generation_mode=ReproductionMode.EXACT_STRUCTURE,
        compiled_prompt="x", idempotency_key="k", status=ReproductionStatus.COMPLETED,
        verdict={"status": "PASSED"},
    )
    pattern = extract_pattern_candidate(case=case, analysis=analysis, reproduction=reproduction)
    assert pattern.status == PatternStatus.CANDIDATE
    assert pattern.positive_evidence_count == 1


def test_template_never_promotes_without_explicit_approval() -> None:
    pattern = __import__("hevi.video_intelligence.patterns", fromlist=["VideoPattern"]).VideoPattern(
        id="p1", name="p", category="action", status=PatternStatus.QUALIFIED
    )
    template = distill_prompt_template(pattern, name="candidate")
    with pytest.raises(ValueError):
        promote_template(template, explicit_approval=False)
    qualify_template(template, passed=True)
    assert promote_template(template, explicit_approval=True).qualification_status == PatternStatus.PROMOTED
