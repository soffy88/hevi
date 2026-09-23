from __future__ import annotations

import pytest

from hevi.video_intelligence.intelligence_runtime import cluster_pattern_signatures, retake_outcome
from hevi.video_intelligence.ssrf import fetch_external_media, validate_external_url


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://localhost/case.mp4",
    "http://127.0.0.1/case.mp4",
    "http://10.0.0.2/case.mp4",
    "http://[::1]/case.mp4",
    "http://169.254.169.254/latest/meta-data",
])
async def test_case_ingest_ssrf_private_network_denied(url: str) -> None:
    with pytest.raises(ValueError):
        await validate_external_url(url)


@pytest.mark.asyncio
async def test_case_ingest_redirect_ssrf_denied() -> None:
    async def request(url: str) -> tuple[int, str | None, bytes, str | None]:
        if url == "https://1.1.1.1/case.mp4":
            return 302, "http://127.0.0.1/admin", b"", None
        raise AssertionError(url)

    with pytest.raises(ValueError, match="SSRF"):
        await fetch_external_media("https://1.1.1.1/case.mp4", request=request)


def test_pattern_clustering_is_suggestion_only_and_does_not_merge() -> None:
    result = cluster_pattern_signatures([
        {"id": "a", "category": "action", "conditions": {"x": 1}, "structure": {"y": 2}},
        {"id": "b", "category": "action", "conditions": {"x": 1}, "structure": {"y": 2}},
    ])
    assert result[0]["pattern_ids"] == ["a", "b"]
    assert result[0]["suggestion_only"] is True


def test_retake_outcome_uses_canonical_dimension_scores() -> None:
    before = {"status": "PASS", "dimensions": {"action_completion": {"score": 0.2}}}
    after = {"status": "PASS", "dimensions": {"action_completion": {"score": 0.9}}}
    assert retake_outcome(before, after) == "improved"
