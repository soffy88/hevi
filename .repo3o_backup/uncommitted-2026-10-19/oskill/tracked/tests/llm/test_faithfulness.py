"""Tests for faithfulness_score."""

from __future__ import annotations

import pytest

from oskill.llm.faithfulness import faithfulness_score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "faithfulness_score",
    "is_faithful",
    "claims",
    "claim_support",
    "n_supported",
    "n_total",
    "evaluation_fingerprint",
}


def make_claim_extractor_then_nli(claims: list[str], nli_answers: list[str]):
    """Mock client that first returns claim list, then NLI answers in order."""
    call_count = {"n": 0}
    claims_text = "\n".join(claims)

    def client_fn(messages, model, **kwargs):
        n = call_count["n"]
        call_count["n"] += 1
        if n == 0:
            content = claims_text
        else:
            idx = (n - 1) % len(nli_answers)
            content = nli_answers[idx]
        return {
            "content": content,
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 5,
        }

    return client_fn


def make_fixed_client(responses: list[str]):
    """Returns responses in order (cycles)."""
    call_count = {"n": 0}

    def client_fn(messages, model, **kwargs):
        idx = call_count["n"] % len(responses)
        call_count["n"] += 1
        return {
            "content": responses[idx],
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 5,
        }

    return client_fn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_faithfulness_all_claims_supported_score_one():
    claims = ["The sky is blue.", "Water is wet."]
    nli_answers = ["yes", "yes"]
    client = make_claim_extractor_then_nli(claims, nli_answers)
    result = faithfulness_score(
        "The sky is blue. Water is wet.",
        ["The sky appears blue due to Rayleigh scattering. Water is a liquid at room temperature."],
        client,
        model="test",
    )
    assert result["faithfulness_score"] == pytest.approx(1.0)
    assert result["is_faithful"] is True
    assert result["n_supported"] == 2
    assert result["n_total"] == 2


def test_faithfulness_no_claims_supported_score_zero():
    claims = ["The moon is made of cheese.", "Gravity pushes things up."]
    nli_answers = ["no", "no"]
    client = make_claim_extractor_then_nli(claims, nli_answers)
    result = faithfulness_score(
        "The moon is made of cheese. Gravity pushes things up.",
        ["The moon is a rocky celestial body."],
        client,
        model="test",
    )
    assert result["faithfulness_score"] == pytest.approx(0.0)
    assert result["is_faithful"] is False
    assert result["n_supported"] == 0


def test_faithfulness_partial_support():
    """Test partial support with a single evidence piece for deterministic NLI calls."""
    claims = ["Paris is in France.", "Tokyo is in China."]
    # With single evidence, calls are: [0]=extraction, [1]=NLI claim1, [2]=NLI claim2
    nli_answers = ["yes", "no"]
    client = make_claim_extractor_then_nli(claims, nli_answers)
    result = faithfulness_score(
        "Paris is in France. Tokyo is in China.",
        # Single combined evidence → one NLI call per claim
        ["Paris is the capital of France. Tokyo is the capital of Japan."],
        client,
        model="test",
    )
    assert result["faithfulness_score"] == pytest.approx(0.5)
    assert result["n_supported"] == 1
    assert result["n_total"] == 2


def test_faithfulness_threshold_passes():
    claims = ["Claim A", "Claim B", "Claim C"]
    nli_answers = ["yes", "yes", "no"]
    client = make_claim_extractor_then_nli(claims, nli_answers)
    result = faithfulness_score(
        "response",
        ["evidence"],
        client,
        model="test",
        threshold=0.5,
    )
    assert result["faithfulness_score"] == pytest.approx(2 / 3)
    assert result["is_faithful"] is True


def test_faithfulness_threshold_fails():
    claims = ["Claim A", "Claim B", "Claim C"]
    nli_answers = ["no", "no", "yes"]
    client = make_claim_extractor_then_nli(claims, nli_answers)
    result = faithfulness_score(
        "response",
        ["evidence"],
        client,
        model="test",
        threshold=0.8,
    )
    assert result["faithfulness_score"] == pytest.approx(1 / 3)
    assert result["is_faithful"] is False


def test_faithfulness_custom_templates():
    custom_claim_template = "List facts from: {response}"
    custom_nli_template = "Does evidence support claim? Claim:{claim} Ev:{evidence} (yes/no):"

    claims = ["Fact 1"]
    client = make_claim_extractor_then_nli(claims, ["yes"])

    result = faithfulness_score(
        "response text",
        ["evidence text"],
        client,
        model="test",
        claim_extractor_template=custom_claim_template,
        nli_template=custom_nli_template,
    )
    assert result["faithfulness_score"] == pytest.approx(1.0)


def test_faithfulness_returns_all_required_fields():
    claims = ["Claim A"]
    client = make_claim_extractor_then_nli(claims, ["yes"])
    result = faithfulness_score(
        "The response.",
        ["Evidence supports it."],
        client,
        model="test",
    )
    assert REQUIRED_KEYS.issubset(result.keys())
    assert isinstance(result["claims"], list)
    assert isinstance(result["claim_support"], dict)
    assert isinstance(result["evaluation_fingerprint"], str)


def test_faithfulness_evaluation_fingerprint_deterministic():
    """Same inputs → same fingerprint."""
    claims = ["Claim A", "Claim B"]

    def make_client():
        return make_claim_extractor_then_nli(claims, ["yes", "no"])

    r1 = faithfulness_score("response", ["evidence"], make_client(), model="test")
    r2 = faithfulness_score("response", ["evidence"], make_client(), model="test")
    assert r1["evaluation_fingerprint"] == r2["evaluation_fingerprint"]
    assert len(r1["evaluation_fingerprint"]) == 64  # sha256 hex


def test_faithfulness_empty_claims_vacuously_faithful():
    """When no claims are extracted, response is vacuously faithful (score=1.0)."""
    client = make_fixed_client([""])  # returns empty string → no claims
    result = faithfulness_score(
        "response",
        ["evidence"],
        client,
        model="test",
    )
    assert result["faithfulness_score"] == pytest.approx(1.0)
    assert result["is_faithful"] is True
    assert result["n_total"] == 0
    assert result["claims"] == []


# ---------------------------------------------------------------------------
# Academic reference test
# ---------------------------------------------------------------------------


@pytest.mark.academic_reference
def test_faithfulness_ragas_paper_examples():
    """Test faithfulness scoring pattern from RAGAS evaluation framework.

    Reference: Es, S. et al. (2023). "RAGAS: Automated Evaluation of Retrieval
    Augmented Generation." EACL 2024. arXiv:2309.15217.
    RAGAS defines faithfulness as the fraction of claims in the generated
    response that are supported by the retrieved context.

    Key formula: faithfulness = |supported claims| / |total claims|
    """
    # RAGAS-style: response with 3 claims, 2 supported by evidence
    response = (
        "Einstein was born in Germany. He developed the theory of relativity. "
        "He won the Nobel Prize in Chemistry."  # This claim is wrong (it was Physics)
    )
    evidence = [
        "Albert Einstein was a German-born theoretical physicist.",
        "Einstein developed the theory of special and general relativity.",
        "Einstein won the Nobel Prize in Physics in 1921.",
    ]

    claims_from_response = [
        "Einstein was born in Germany.",
        "He developed the theory of relativity.",
        "He won the Nobel Prize in Chemistry.",
    ]
    # Use single combined evidence so there's exactly 1 NLI call per claim.
    # Evidence supports claims 1 and 2 but not 3 (Chemistry != Physics)
    combined_evidence = " ".join(evidence)
    nli_responses = ["yes", "yes", "no"]
    client = make_claim_extractor_then_nli(claims_from_response, nli_responses)

    result = faithfulness_score(response, [combined_evidence], client, model="test")

    assert result["n_total"] == 3
    assert result["n_supported"] == 2
    assert result["faithfulness_score"] == pytest.approx(2 / 3)
    assert result["is_faithful"] is True  # default threshold=0.5, 0.667 > 0.5
    assert REQUIRED_KEYS.issubset(result.keys())

    # Verify claim_support structure
    assert len(result["claim_support"]) == 3
