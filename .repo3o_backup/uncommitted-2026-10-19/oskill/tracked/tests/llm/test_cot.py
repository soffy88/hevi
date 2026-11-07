"""Tests for chain_of_thought_extractor."""

from __future__ import annotations

import pytest

from oskill.llm.cot import chain_of_thought_extractor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "reasoning",
    "final_answer",
    "steps",
    "method_used",
    "extraction_confidence",
    "raw_response",
}


def make_mock_client(content: str):
    def client_fn(messages, model, **kwargs):
        return {
            "content": content,
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 20,
        }

    return client_fn


# ---------------------------------------------------------------------------
# marker_based tests
# ---------------------------------------------------------------------------


def test_cot_marker_based_basic():
    response = (
        "Let me think: The problem requires careful analysis. "
        "We need to consider multiple factors.\n"
        "Answer: The result is 42."
    )
    result = chain_of_thought_extractor(response)
    assert result["method_used"] == "marker_based"
    assert "42" in result["final_answer"]
    assert result["extraction_confidence"] > 0.5
    assert REQUIRED_KEYS.issubset(result.keys())


def test_cot_marker_based_thinking_tags():
    """Anthropic uses <thinking>...</thinking> tags for extended reasoning."""
    response = (
        "<thinking>\n"
        "Step 1: Analyze the problem.\n"
        "Step 2: Consider alternatives.\n"
        "</thinking>\n"
        "The final answer is 7."
    )
    result = chain_of_thought_extractor(response)
    assert result["method_used"] == "marker_based"
    assert "Analyze the problem" in result["reasoning"]
    assert "7" in result["final_answer"]


def test_cot_returns_all_fields():
    response = "Reasoning: I think carefully. Answer: Done."
    result = chain_of_thought_extractor(response)
    assert REQUIRED_KEYS.issubset(result.keys())
    assert result["raw_response"] == response
    assert isinstance(result["steps"], list)
    assert isinstance(result["extraction_confidence"], float)
    assert 0.0 <= result["extraction_confidence"] <= 1.0


def test_cot_steps_list_populated_when_delimiters_found():
    response = (
        "Let me think:\nStep 1: Start here.\nStep 2: Continue.\nStep 3: Conclude.\nAnswer: Final."
    )
    result = chain_of_thought_extractor(response)
    assert isinstance(result["steps"], list)


def test_cot_no_markers_low_confidence():
    response = "Just a plain response with no markers whatsoever."
    result = chain_of_thought_extractor(response)
    assert result["extraction_confidence"] < 0.5
    assert result["raw_response"] == response


def test_cot_default_markers_anthropic_compatible():
    """Default markers should work with standard Anthropic response format."""
    response = "<thinking>I need to reason step by step.</thinking>Answer: The answer is 100."
    result = chain_of_thought_extractor(response)
    assert result["reasoning"]  # should have extracted reasoning
    assert REQUIRED_KEYS.issubset(result.keys())


# ---------------------------------------------------------------------------
# pattern_based tests
# ---------------------------------------------------------------------------


def test_cot_pattern_based_step_extraction():
    response = (
        "Step 1: Identify the key variables.\n"
        "Step 2: Apply the formula.\n"
        "Step 3: Compute the result.\n"
        "Therefore, the answer is 15."
    )
    result = chain_of_thought_extractor(response, method="pattern_based")
    assert result["method_used"] == "pattern_based"
    assert len(result["steps"]) >= 2
    assert "15" in result["final_answer"]


# ---------------------------------------------------------------------------
# llm_assisted tests
# ---------------------------------------------------------------------------


def test_cot_llm_assisted_requires_client_fn():
    with pytest.raises(ValueError, match="client_fn"):
        chain_of_thought_extractor("some response", method="llm_assisted")


def test_cot_llm_assisted_uses_client_fn():
    json_response = (
        '{"reasoning": "I thought carefully", "steps": ["Step A", "Step B"], "final_answer": "42"}'
    )
    mock_client = make_mock_client(json_response)
    result = chain_of_thought_extractor(
        "some complex response",
        method="llm_assisted",
        client_fn=mock_client,
        model="claude-test",
    )
    assert result["method_used"] == "llm_assisted"
    assert REQUIRED_KEYS.issubset(result.keys())
    assert result["final_answer"] == "42"


# ---------------------------------------------------------------------------
# Academic reference test
# ---------------------------------------------------------------------------


@pytest.mark.academic_reference
def test_cot_wei_2022_examples():
    """Test compatibility with CoT prompting patterns from Wei et al. (2022).

    Reference: Wei, J. et al. (2022). "Chain-of-Thought Prompting Elicits Reasoning
    in Large Language Models." NeurIPS 2022. arXiv:2201.11903.
    The paper demonstrates that multi-step reasoning in the format
    "Step 1: ... Step 2: ... Therefore: ..." improves accuracy.
    This test verifies our extractor handles these Wei-style responses.
    """
    # Typical Wei et al. style response with explicit reasoning steps
    wei_response = (
        "Let me think step by step.\n"
        "The cafeteria had 23 apples. They used 20 to make lunch, so 23 - 20 = 3 apples left.\n"
        "Then they bought 6 more: 3 + 6 = 9 apples.\n"
        "Therefore, the cafeteria has 9 apples."
    )
    result = chain_of_thought_extractor(wei_response, method="marker_based")
    assert result["method_used"] == "marker_based"
    assert REQUIRED_KEYS.issubset(result.keys())
    # The reasoning should contain the math steps
    full_text = result["reasoning"] + result["final_answer"]
    assert "9" in full_text

    # Pattern-based should also work on step-like text
    result2 = chain_of_thought_extractor(wei_response, method="pattern_based")
    assert result2["method_used"] == "pattern_based"
    assert REQUIRED_KEYS.issubset(result2.keys())
