"""Tests for oskill.llm.batch_classify (B7)."""

from unittest.mock import MagicMock

from oskill.llm.batch_classify import llm_batch_classify


def _mock_llm(response: str) -> MagicMock:
    m = MagicMock()
    m.call.return_value = response
    return m


class TestLLMBatchClassify:
    def test_mock_llm_json(self) -> None:
        llm = _mock_llm('[{"item_idx": 1, "labels": ["tech"]}]')
        result = llm_batch_classify(
            items=[{"text": "AI startup"}], labels=["tech", "finance"], llm=llm
        )
        assert len(result["results"]) >= 1
        assert result["errors"] == []

    def test_multi_label(self) -> None:
        llm = _mock_llm('[{"item_idx": 1, "labels": ["tech", "finance"]}]')
        result = llm_batch_classify(
            items=[{"text": "fintech"}], labels=["tech", "finance"], llm=llm, multi_label=True
        )
        assert len(result["results"]) >= 1

    def test_parse_output_fallback(self) -> None:
        llm = _mock_llm("invalid json response")
        result = llm_batch_classify(items=[{"text": "test"}], labels=["a", "b"], llm=llm)
        # Should fallback gracefully
        assert len(result["results"]) >= 1
        assert result["errors"] == []

    def test_batch_size_gt_items(self) -> None:
        llm = _mock_llm('[{"item_idx": 1, "labels": ["a"]}]')
        result = llm_batch_classify(items=[{"text": "x"}], labels=["a"], llm=llm, batch_size=100)
        assert len(result["results"]) >= 1

    def test_single_batch_failure_isolated(self) -> None:
        llm = MagicMock()
        llm.call.side_effect = RuntimeError("LLM down")
        result = llm_batch_classify(items=[{"text": "x"}, {"text": "y"}], labels=["a"], llm=llm)
        assert len(result["errors"]) == 2
        assert result["results"] == []

    def test_cost_accumulates(self) -> None:
        llm = _mock_llm('[{"item_idx": 1, "labels": ["a"]}]')
        result = llm_batch_classify(
            items=[{"text": f"item{i}"} for i in range(5)], labels=["a"], llm=llm, batch_size=2
        )
        assert result["cost_usd"] > 0

    def test_empty_items(self) -> None:
        llm = _mock_llm("")
        result = llm_batch_classify(items=[], labels=["a"], llm=llm)
        assert result["results"] == []
        assert result["cost_usd"] == 0.0
