"""Tests for batch_generate_animations."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from oprim._animation_types import AnimationResult

from oskill._batch_generate_animations import batch_generate_animations

_GOOD = AnimationResult(
    html="<html></html>", is_valid=True, validation_violations=[], entity_meta={}
)


def _make_jobs(n: int) -> list[dict]:
    return [
        {"template": f"T{i}", "variables": {"i": str(i)}, "domain_prompt": f"D{i}"}
        for i in range(n)
    ]


class TestBatchGenerateAnimations:
    async def test_empty_jobs_returns_empty(self):
        result = await batch_generate_animations(jobs=[], llm=None)
        assert result == []

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_single_job_returns_one_result(self, mock_gen):
        mock_gen.return_value = _GOOD
        results = await batch_generate_animations(jobs=_make_jobs(1), llm=None)
        assert len(results) == 1
        assert isinstance(results[0], AnimationResult)

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_result_count_matches_job_count(self, mock_gen):
        mock_gen.return_value = _GOOD
        jobs = _make_jobs(7)
        results = await batch_generate_animations(jobs=jobs, llm=None)
        assert len(results) == 7

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_all_results_are_animation_result(self, mock_gen):
        mock_gen.return_value = _GOOD
        results = await batch_generate_animations(jobs=_make_jobs(3), llm=None)
        for r in results:
            assert isinstance(r, AnimationResult)

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_failed_job_returns_failed_result_not_exception(self, mock_gen):
        mock_gen.side_effect = RuntimeError("LLM unavailable")
        results = await batch_generate_animations(jobs=_make_jobs(1), llm=None)
        assert len(results) == 1
        assert results[0].is_valid is False
        assert "generation_error" in results[0].validation_violations

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_one_failure_does_not_block_others(self, mock_gen):
        def side_effect(**kwargs):
            if kwargs.get("template") == "T0":
                raise RuntimeError("fail")
            return _GOOD

        mock_gen.side_effect = side_effect
        jobs = _make_jobs(3)
        results = await batch_generate_animations(jobs=jobs, llm=None)
        assert len(results) == 3
        # T0 failed, T1/T2 succeeded
        assert results[0].is_valid is False
        assert results[1].is_valid is True
        assert results[2].is_valid is True

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_max_concurrent_one_processes_all(self, mock_gen):
        mock_gen.return_value = _GOOD
        results = await batch_generate_animations(jobs=_make_jobs(4), llm=None, max_concurrent=1)
        assert len(results) == 4

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_jobs_missing_optional_keys_handled(self, mock_gen):
        mock_gen.return_value = _GOOD
        # variables and domain_prompt are optional in the job dict
        jobs = [{"template": "T"}]
        results = await batch_generate_animations(jobs=jobs, llm=None)
        assert len(results) == 1
        assert isinstance(results[0], AnimationResult)

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_generate_animation_called_per_job(self, mock_gen):
        mock_gen.return_value = _GOOD
        jobs = _make_jobs(5)
        await batch_generate_animations(jobs=jobs, llm=None)
        assert mock_gen.call_count == 5

    @patch("oskill._batch_generate_animations.generate_animation", new_callable=AsyncMock)
    async def test_failed_job_entity_meta_has_error(self, mock_gen):
        mock_gen.side_effect = ValueError("bad input")
        results = await batch_generate_animations(jobs=_make_jobs(1), llm=None)
        assert "error" in results[0].entity_meta
        assert "bad input" in results[0].entity_meta["error"]
