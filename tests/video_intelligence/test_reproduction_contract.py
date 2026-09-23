from __future__ import annotations

import pytest

from hevi.video_intelligence.case_analysis import CaseAnalysis, TemporalComplexity
from hevi.video_intelligence.case_models import VideoCase
from hevi.video_intelligence.reproduction import (
    ReproductionMode,
    build_reproduction_plan,
    reproduce_case,
)


def _case() -> VideoCase:
    return VideoCase(id="case-1", user_id="user-1", title="case")


def _analysis() -> CaseAnalysis:
    return CaseAnalysis(
        analysis_id="analysis-1",
        case_id="case-1",
        temporal_structure=TemporalComplexity(
            duration_s=5, distinct_actions=1, camera_events=0,
            subject_state_changes=0, scene_state_changes=0, complexity_score=1,
        ),
    )


def test_plan_is_structural_and_provider_agnostic() -> None:
    plan = build_reproduction_plan(
        _case(), _analysis(), provider="qualified-provider", model="model-1"
    )
    assert plan.mode == ReproductionMode.EXACT_STRUCTURE
    assert "Structural constraints" in plan.compiled_prompt


@pytest.mark.asyncio
async def test_reproduction_uses_canonical_injected_generation_and_verdict() -> None:
    calls: list[str] = []

    async def generate(request: dict[str, object]) -> dict[str, object]:
        calls.append("generate")
        assert request["provider"] == "qualified-provider"
        return {"asset_id": "asset-1", "cost": 0.1, "latency_ms": 12}

    async def verdict(artifact: dict[str, object], *, case: VideoCase) -> dict[str, object]:
        calls.append("verdict")
        assert artifact["asset_id"] == "asset-1"
        assert case.id == "case-1"
        return {"status": "PASSED", "verdict_id": "verdict-1"}

    plan = build_reproduction_plan(_case(), _analysis(), provider="qualified-provider", model="m")
    result = await reproduce_case(plan, generate=generate, verdict=verdict, case=_case())
    assert result.status.value == "completed"
    assert result.verdict_id == "verdict-1"
    assert calls == ["generate", "verdict"]
