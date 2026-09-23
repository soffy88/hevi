from __future__ import annotations

import pytest
from pydantic import ValidationError

from hevi.video_intelligence.case_analysis import parse_prompt_structure, temporal_complexity
from hevi.video_intelligence.case_models import (
    CaseIngestInput,
    PromptOrigin,
    RightsStatus,
    VideoCase,
)


def test_case_defaults_are_fail_closed() -> None:
    case = VideoCase(id="case-1", user_id="user-1", title="reference")
    assert case.rights_status == RightsStatus.UNKNOWN
    assert case.prompt_origin == PromptOrigin.UNKNOWN
    assert case.provenance_status.value == "unverified"
    assert case.analysis_status.value == "not_started"


def test_prompt_origin_cannot_claim_without_prompt() -> None:
    with pytest.raises(ValidationError):
        CaseIngestInput(
            title="case",
            source_url="https://example.com/video",
            prompt_origin=PromptOrigin.AUTHOR_PROVIDED,
        )


def test_prompt_origin_is_preserved_and_explicit() -> None:
    body = CaseIngestInput(
        title="case",
        source_url="https://example.com/video",
        original_prompt="a locked camera",
        prompt_origin=PromptOrigin.INFERRED,
    )
    assert body.prompt_origin == PromptOrigin.INFERRED


def test_source_url_rejects_non_http_schemes() -> None:
    with pytest.raises(ValidationError):
        CaseIngestInput(title="case", source_url="file:///tmp/video.mp4")


def test_prompt_structure_and_complexity_are_observational_signals() -> None:
    prompt = parse_prompt_structure("a person picks up a cup, then pans camera")
    complexity = temporal_complexity(duration_ms=5000, prompt=prompt, shot_count=2)
    assert prompt.action_count >= 1
    assert prompt.camera_instruction_count >= 1
    assert complexity.complexity_score >= 3
