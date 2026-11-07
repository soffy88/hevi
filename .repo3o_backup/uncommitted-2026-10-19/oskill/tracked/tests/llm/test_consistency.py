"""Tests for llm_response_consistency."""

from __future__ import annotations

import pytest

from oskill.llm.consistency import llm_response_consistency

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fixed_client(response_text: str):
    """Always returns the same response."""

    def client_fn(messages, model, **kwargs):
        return {
            "content": response_text,
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 5,
        }

    return client_fn


def make_cycling_client(responses: list[str]):
    """Cycles through provided responses."""
    counter = {"n": 0}

    def client_fn(messages, model, **kwargs):
        text = responses[counter["n"] % len(responses)]
        counter["n"] += 1
        return {
            "content": text,
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 5,
        }

    return client_fn


REQUIRED_KEYS = {
    "responses",
    "unique_responses",
    "n_unique",
    "mean_pairwise_similarity",
    "exact_match_rate",
    "most_common_response",
    "most_common_frequency",
    "is_highly_consistent",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_consistency_all_same_response_high_score():
    client = make_fixed_client("The answer is 42.")
    result = llm_response_consistency(
        "What is {question}?",
        {"question": "the answer"},
        client,
        model="test-model",
        n_samples=5,
    )
    assert result["exact_match_rate"] == 1.0
    assert result["n_unique"] == 1
    assert result["is_highly_consistent"] is True


def test_consistency_all_different_response_low_score():
    responses = [f"Response {i}" for i in range(5)]
    client = make_cycling_client(responses)
    result = llm_response_consistency(
        "Tell me about {topic}",
        {"topic": "something"},
        client,
        model="test-model",
        n_samples=5,
    )
    assert result["exact_match_rate"] == 0.2  # each unique
    assert result["n_unique"] == 5
    assert result["is_highly_consistent"] is False


def test_consistency_returns_all_metrics():
    client = make_fixed_client("consistent answer")
    result = llm_response_consistency(
        "{prompt}",
        {"prompt": "test"},
        client,
        model="m",
        n_samples=3,
    )
    assert REQUIRED_KEYS.issubset(result.keys())
    assert isinstance(result["responses"], list)
    assert len(result["responses"]) == 3


def test_consistency_with_custom_similarity_fn():
    client = make_fixed_client("hello world")

    def jaccard_sim(a: str, b: str) -> float:
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a and not set_b:
            return 1.0
        return len(set_a & set_b) / len(set_a | set_b)

    result = llm_response_consistency(
        "{q}",
        {"q": "test"},
        client,
        model="m",
        n_samples=3,
        similarity_fn=jaccard_sim,
    )
    assert result["mean_pairwise_similarity"] is not None
    assert result["mean_pairwise_similarity"] == pytest.approx(1.0)


def test_consistency_exact_match_rate_calculation():
    # 3 of 5 say "yes"
    responses = ["yes", "yes", "no", "yes", "maybe"]
    client = make_cycling_client(responses)
    result = llm_response_consistency(
        "{q}",
        {"q": "binary question"},
        client,
        model="m",
        n_samples=5,
    )
    assert result["exact_match_rate"] == pytest.approx(3 / 5)
    assert result["most_common_response"] == "yes"
    assert result["most_common_frequency"] == 3


def test_consistency_most_common_response_extraction():
    responses = ["alpha", "beta", "alpha", "alpha", "beta"]
    client = make_cycling_client(responses)
    result = llm_response_consistency("{q}", {"q": "q"}, client, model="m", n_samples=5)
    assert result["most_common_response"] == "alpha"
    assert result["most_common_frequency"] == 3


def test_consistency_invalid_n_samples_raises():
    client = make_fixed_client("response")
    with pytest.raises(ValueError, match="n_samples"):
        llm_response_consistency("{q}", {"q": "q"}, client, model="m", n_samples=0)


def test_consistency_custom_response_extractor():
    """Test that custom response_extractor is called."""

    def client_fn(messages, model, **kwargs):
        return {"content": "ignored", "custom": "extracted_text"}

    def extractor(result: dict) -> str:
        return result["custom"]

    result = llm_response_consistency(
        "{q}",
        {"q": "q"},
        client_fn,
        model="m",
        n_samples=3,
        response_extractor=extractor,
    )
    assert all(r == "extracted_text" for r in result["responses"])


# ---------------------------------------------------------------------------
# Academic reference test
# ---------------------------------------------------------------------------


@pytest.mark.academic_reference
def test_consistency_self_consistency_paper_pattern():
    """Test the self-consistency prompting pattern from Wang et al. (2022).

    Reference: Wang, X. et al. (2022). "Self-Consistency Improves Chain of
    Thought Reasoning in Language Models." ICLR 2023. arXiv:2203.11171.
    The paper shows that sampling multiple reasoning paths and taking the
    majority vote improves accuracy over greedy decoding.

    This test verifies that llm_response_consistency correctly measures
    the majority agreement (exact_match_rate) which is the key metric
    in the self-consistency voting procedure.
    """
    # Simulate 8 samples where 5/8 agree on "positive"
    responses = [
        "positive",
        "positive",
        "negative",
        "positive",
        "neutral",
        "positive",
        "positive",
        "negative",
    ]
    client = make_cycling_client(responses)

    result = llm_response_consistency(
        "Classify the sentiment of: {text}",
        {"text": "The product exceeded all expectations"},
        client,
        model="claude-test",
        n_samples=8,
        temperature=0.7,
    )

    # Self-consistency: most common = majority vote
    assert result["most_common_response"] == "positive"
    assert result["most_common_frequency"] == 5
    assert result["exact_match_rate"] == pytest.approx(5 / 8)
    assert result["n_unique"] == 3
    assert len(result["responses"]) == 8
