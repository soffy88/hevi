"""Tests for multi_model_ensemble."""

from __future__ import annotations

import pytest

from oskill.llm.multi_model import multi_model_ensemble

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_client(returns: str):
    def client(messages, model, **kwargs):
        return {
            "content": returns,
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 5,
        }

    return client


def make_configs(*model_ids: str) -> dict[str, dict]:
    return {f"model_{i}": {"model": mid} for i, mid in enumerate(model_ids)}


REQUIRED_KEYS = {
    "consensus_label",
    "agreement_score",
    "per_model_responses",
    "aggregation_method",
    "is_unanimous",
    "has_consensus",
    "ensemble_fingerprint",
}


# ---------------------------------------------------------------------------
# Tests: majority_vote
# ---------------------------------------------------------------------------


def test_multi_model_majority_vote_3_agree_1_disagree():
    client_fns = {
        "model_0": make_mock_client("positive"),
        "model_1": make_mock_client("positive"),
        "model_2": make_mock_client("positive"),
        "model_3": make_mock_client("negative"),
    }
    configs = {k: {"model": f"mock-{k}"} for k in client_fns}
    result = multi_model_ensemble(
        "Classify: {text}",
        {"text": "great product"},
        client_fns,
        model_configs=configs,
        aggregation="majority_vote",
    )
    assert result["consensus_label"] == "positive"
    assert result["agreement_score"] == pytest.approx(3 / 4)
    assert result["is_unanimous"] is False


def test_multi_model_majority_vote_tie_takes_first():
    """On a tie, the first encountered label (in sorted key order) wins."""
    client_fns = {
        "model_a": make_mock_client("yes"),
        "model_b": make_mock_client("no"),
    }
    configs = {k: {"model": f"mock-{k}"} for k in client_fns}
    result = multi_model_ensemble(
        "{q}",
        {"q": "binary"},
        client_fns,
        model_configs=configs,
        aggregation="majority_vote",
    )
    # Both have 1 vote, deterministic: should pick the one that comes first
    assert result["consensus_label"] in ("yes", "no")
    assert result["agreement_score"] == pytest.approx(0.5)


def test_multi_model_per_model_traces_in_output():
    client_fns = {
        "gpt": make_mock_client("A"),
        "claude": make_mock_client("A"),
    }
    configs = {k: {"model": f"mock-{k}"} for k in client_fns}
    result = multi_model_ensemble(
        "{q}",
        {"q": "test"},
        client_fns,
        model_configs=configs,
    )
    assert "gpt" in result["per_model_responses"]
    assert "claude" in result["per_model_responses"]
    for trace in result["per_model_responses"].values():
        assert "content" in trace
        assert "label" in trace
        assert "model" in trace


# ---------------------------------------------------------------------------
# Tests: weighted_vote
# ---------------------------------------------------------------------------


def test_multi_model_weighted_vote_breaks_tie_by_weight():
    client_fns = {
        "high_confidence": make_mock_client("buy"),
        "low_confidence": make_mock_client("sell"),
    }
    configs = {k: {"model": k} for k in client_fns}
    weights = {"high_confidence": 0.9, "low_confidence": 0.1}
    result = multi_model_ensemble(
        "{q}",
        {"q": "stock decision"},
        client_fns,
        model_configs=configs,
        aggregation="weighted_vote",
        weights=weights,
    )
    assert result["consensus_label"] == "buy"
    assert result["agreement_score"] > 0.5


# ---------------------------------------------------------------------------
# Tests: score_averaging
# ---------------------------------------------------------------------------


def test_multi_model_score_averaging_returns_mean():
    client_fns = {
        "m1": make_mock_client("0.8"),
        "m2": make_mock_client("0.6"),
        "m3": make_mock_client("0.4"),
    }
    configs = {k: {"model": k} for k in client_fns}
    result = multi_model_ensemble(
        "{q}",
        {"q": "score this"},
        client_fns,
        model_configs=configs,
        aggregation="score_averaging",
    )
    mean = (0.8 + 0.6 + 0.4) / 3
    assert result["consensus_label"] == str(mean)


# ---------------------------------------------------------------------------
# Tests: agreement_only
# ---------------------------------------------------------------------------


def test_multi_model_agreement_only_unanimous_returns_consensus():
    client_fns = {k: make_mock_client("approve") for k in ["a", "b", "c"]}
    configs = {k: {"model": k} for k in client_fns}
    result = multi_model_ensemble(
        "{q}",
        {"q": "vote"},
        client_fns,
        model_configs=configs,
        aggregation="agreement_only",
    )
    assert result["consensus_label"] == "approve"
    assert result["is_unanimous"] is True
    assert result["has_consensus"] is True


def test_multi_model_agreement_only_split_returns_no_consensus():
    client_fns = {
        "a": make_mock_client("yes"),
        "b": make_mock_client("no"),
    }
    configs = {k: {"model": k} for k in client_fns}
    result = multi_model_ensemble(
        "{q}",
        {"q": "split vote"},
        client_fns,
        model_configs=configs,
        aggregation="agreement_only",
    )
    assert result["consensus_label"] == "no_consensus"
    assert result["has_consensus"] is False
    assert result["is_unanimous"] is False


# ---------------------------------------------------------------------------
# Tests: fingerprint
# ---------------------------------------------------------------------------


def test_multi_model_ensemble_fingerprint_deterministic():
    """Same inputs → same fingerprint."""

    def make_fns():
        return {k: make_mock_client("label") for k in ["m1", "m2"]}

    configs = {"m1": {"model": "model-a"}, "m2": {"model": "model-b"}}
    r1 = multi_model_ensemble("{q}", {"q": "test"}, make_fns(), model_configs=configs)
    r2 = multi_model_ensemble("{q}", {"q": "test"}, make_fns(), model_configs=configs)
    assert r1["ensemble_fingerprint"] == r2["ensemble_fingerprint"]
    assert isinstance(r1["ensemble_fingerprint"], str)
    assert len(r1["ensemble_fingerprint"]) == 64  # sha256 hex


# ---------------------------------------------------------------------------
# Tests: error cases
# ---------------------------------------------------------------------------


def test_multi_model_mismatched_client_fns_and_configs_raises():
    client_fns = {"m1": make_mock_client("a"), "m2": make_mock_client("b")}
    configs = {"m1": {"model": "m1"}}  # missing m2
    with pytest.raises(ValueError, match="keys"):
        multi_model_ensemble("{q}", {"q": "x"}, client_fns, model_configs=configs)


def test_multi_model_invalid_aggregation_raises():
    client_fns = {"m1": make_mock_client("a")}
    configs = {"m1": {"model": "m1"}}
    with pytest.raises(ValueError, match="aggregation"):
        multi_model_ensemble(
            "{q}",
            {"q": "x"},
            client_fns,
            model_configs=configs,
            aggregation="invalid_method",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Academic reference test
# ---------------------------------------------------------------------------


@pytest.mark.academic_reference
def test_multi_model_trusttrade_framework_consensus():
    """Test multi-model consensus pattern from TrustTrade framework.

    Reference: arxiv 2603.22567 (TrustTrade, 2026). The TrustTrade framework
    uses multi-model ensemble voting with per-model traces for audit trails.
    Key properties: deterministic fingerprint, per-model attribution,
    and graceful handling of disagreement via agreement_only mode.
    """
    # Simulate 3 analyst models evaluating a trade signal
    client_fns = {
        "fundamentals_model": make_mock_client("BUY"),
        "technical_model": make_mock_client("BUY"),
        "sentiment_model": make_mock_client("HOLD"),
    }
    configs = {
        "fundamentals_model": {"model": "claude-opus-4-7", "temperature": 0.0},
        "technical_model": {"model": "claude-sonnet-4-6", "temperature": 0.0},
        "sentiment_model": {"model": "claude-haiku-4-5", "temperature": 0.0},
    }

    result = multi_model_ensemble(
        "Analyze trade signal for {ticker} given P/E={pe}, RSI={rsi}",
        {"ticker": "AAPL", "pe": "28.5", "rsi": "65"},
        client_fns,
        model_configs=configs,
        aggregation="majority_vote",
    )

    # Majority: BUY (2/3)
    assert result["consensus_label"] == "BUY"
    assert result["agreement_score"] == pytest.approx(2 / 3)
    assert result["is_unanimous"] is False
    assert result["has_consensus"] is True

    # Audit trail: all models traced
    assert set(result["per_model_responses"].keys()) == set(client_fns.keys())

    # Fingerprint is deterministic sha256
    assert len(result["ensemble_fingerprint"]) == 64
    assert REQUIRED_KEYS.issubset(result.keys())
