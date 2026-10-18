"""Chain-of-thought extractor — parses reasoning and final answers from LLM responses."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

_DEFAULT_REASONING_MARKERS = [
    "<thinking>",
    "Let me think:",
    "Reasoning:",
    "Step",
    "First",
]

_DEFAULT_ANSWER_MARKERS = [
    "</thinking>",
    "Answer:",
    "Final answer:",
    "Therefore",
    "Conclusion:",
]


def chain_of_thought_extractor(
    llm_response: str,
    *,
    reasoning_markers: list[str] | None = None,
    answer_markers: list[str] | None = None,
    method: Literal["marker_based", "pattern_based", "llm_assisted"] = "marker_based",
    client_fn: Callable[..., dict] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Extract chain-of-thought reasoning and final answer from an LLM response.

    Methods:
        - marker_based: Split on reasoning_markers to find reasoning, answer_markers for answer.
        - pattern_based: Regex patterns for "Step N:", "First...", "Therefore..." etc.
        - llm_assisted: Use client_fn to re-extract (requires client_fn + model).

    Parameters
    ----------
    llm_response : str
        Raw LLM output text.
    reasoning_markers : list[str] or None
        Markers that begin reasoning blocks. Uses defaults if None.
    answer_markers : list[str] or None
        Markers that begin final answer blocks. Uses defaults if None.
    method : {'marker_based', 'pattern_based', 'llm_assisted'}
        Extraction strategy.
    client_fn : callable or None
        Required for llm_assisted method. (messages, model, **kwargs) -> dict.
    model : str or None
        Model identifier, used only for llm_assisted.

    Returns
    -------
    dict with keys: 'reasoning', 'final_answer', 'steps', 'method_used',
    'extraction_confidence', 'raw_response'
    """
    if reasoning_markers is None:
        reasoning_markers = _DEFAULT_REASONING_MARKERS
    if answer_markers is None:
        answer_markers = _DEFAULT_ANSWER_MARKERS

    if method == "marker_based":
        return _extract_marker_based(llm_response, reasoning_markers, answer_markers)
    elif method == "pattern_based":
        return _extract_pattern_based(llm_response)
    elif method == "llm_assisted":
        if client_fn is None:
            raise ValueError("llm_assisted method requires client_fn to be provided")
        if model is None:
            raise ValueError("llm_assisted method requires model to be provided")
        return _extract_llm_assisted(llm_response, client_fn, model)
    else:
        raise ValueError(f"Unknown method: {method!r}")


def _extract_marker_based(
    response: str,
    reasoning_markers: list[str],
    answer_markers: list[str],
) -> dict[str, Any]:
    """Split on markers to find reasoning and final answer."""
    # Handle <thinking>...</thinking> tags first (Anthropic extended thinking)
    thinking_match = re.search(r"<thinking>(.*?)</thinking>", response, re.DOTALL)
    if thinking_match:
        reasoning_text = thinking_match.group(1).strip()
        # Answer is everything after </thinking>
        after_thinking = response[thinking_match.end() :].strip()
        final_answer = after_thinking if after_thinking else ""
        steps = _extract_steps_from_text(reasoning_text)
        return {
            "reasoning": reasoning_text,
            "final_answer": final_answer,
            "steps": steps,
            "method_used": "marker_based",
            "extraction_confidence": 0.9 if reasoning_text else 0.3,
            "raw_response": response,
        }

    reasoning_text = ""
    final_answer = ""
    steps: list[str] = []

    # Try to find reasoning section
    reasoning_start = -1
    reasoning_marker_found = ""
    for marker in reasoning_markers:
        idx = response.find(marker)
        if idx != -1:
            if reasoning_start == -1 or idx < reasoning_start:
                reasoning_start = idx
                reasoning_marker_found = marker

    # Try to find answer section
    answer_start = -1
    for marker in answer_markers:
        idx = response.find(marker)
        if idx != -1:
            # Answer marker should come after reasoning (if any)
            if answer_start == -1 or idx < answer_start:
                answer_start = idx

    if reasoning_start != -1 and answer_start != -1 and answer_start > reasoning_start:
        # Extract reasoning: from reasoning marker to answer marker
        reason_begin = reasoning_start + len(reasoning_marker_found)
        reasoning_text = response[reason_begin:answer_start].strip()
        final_answer = response[answer_start:].strip()
        # Strip the leading answer marker from final_answer
        for marker in answer_markers:
            if final_answer.startswith(marker):
                final_answer = final_answer[len(marker) :].strip()
                break
    elif reasoning_start != -1:
        # Only reasoning, no answer marker
        reason_begin = reasoning_start + len(reasoning_marker_found)
        reasoning_text = response[reason_begin:].strip()
    elif answer_start != -1:
        # Only answer marker
        final_answer = response[answer_start:].strip()
        for marker in answer_markers:
            if final_answer.startswith(marker):
                final_answer = final_answer[len(marker) :].strip()
                break

    steps = _extract_steps_from_text(reasoning_text if reasoning_text else response)

    # Compute confidence
    found_markers = (reasoning_start != -1) + (answer_start != -1)
    if found_markers == 2:
        confidence = 0.85
    elif found_markers == 1:
        confidence = 0.5
    else:
        confidence = 0.2

    return {
        "reasoning": reasoning_text,
        "final_answer": final_answer,
        "steps": steps,
        "method_used": "marker_based",
        "extraction_confidence": confidence,
        "raw_response": response,
    }


def _extract_pattern_based(response: str) -> dict[str, Any]:
    """Use regex to find step-based reasoning patterns."""
    # Match patterns: "Step N:", "First,", "Therefore", numbered lists
    step_pattern = re.compile(
        r"(?:Step\s+\d+[:.)]|(?:\d+\.\s)|(?:First[,:])|(?:Second[,:])|"
        r"(?:Third[,:])|(?:Next[,:])|(?:Then[,:])|(?:Finally[,:]))",
        re.IGNORECASE,
    )

    answer_pattern = re.compile(
        r"(?:Therefore[,:]?|Thus[,:]?|In conclusion[,:]?|"
        r"(?:The\s+)?(?:final\s+)?[Aa]nswer\s*(?:is)?[,:]?)",
        re.IGNORECASE,
    )

    steps: list[str] = []
    reasoning_text = ""
    final_answer = ""

    # Find all step matches
    step_matches = list(step_pattern.finditer(response))
    answer_match = answer_pattern.search(response)

    if step_matches:
        # Collect step contents
        for i, m in enumerate(step_matches):
            end = (
                step_matches[i + 1].start()
                if i + 1 < len(step_matches)
                else (answer_match.start() if answer_match else len(response))
            )
            step_text = response[m.start() : end].strip()
            if step_text:
                steps.append(step_text)

        reasoning_text = response[: answer_match.start()].strip() if answer_match else response

    if answer_match:
        final_answer = response[answer_match.end() :].strip()

    found = bool(step_matches) + bool(answer_match)
    confidence = 0.8 if found == 2 else (0.5 if found == 1 else 0.2)

    return {
        "reasoning": reasoning_text,
        "final_answer": final_answer,
        "steps": steps,
        "method_used": "pattern_based",
        "extraction_confidence": confidence,
        "raw_response": response,
    }


def _extract_llm_assisted(
    response: str,
    client_fn: Callable[..., dict],
    model: str,
) -> dict[str, Any]:
    """Use client_fn to re-extract chain-of-thought structure."""
    extraction_prompt = (
        "You are a chain-of-thought extractor. Analyze the following response and extract:\n"
        "1. The reasoning steps (as a list)\n"
        "2. The final answer\n"
        'Output JSON: {"reasoning": "...", "steps": [...], "final_answer": "..."}\n\n'
        f"Response to analyze:\n{response}"
    )

    messages = [{"role": "user", "content": extraction_prompt}]
    result = client_fn(messages, model, temperature=0.0, max_tokens=1024)
    raw_content = result.get("content", "")

    # Try to parse JSON from response
    import json

    reasoning_text = ""
    final_answer = ""
    steps: list[str] = []
    confidence = 0.7

    try:
        parsed = json.loads(raw_content)
        reasoning_text = parsed.get("reasoning", "")
        final_answer = parsed.get("final_answer", "")
        steps_raw = parsed.get("steps", [])
        steps = [str(s) for s in steps_raw] if isinstance(steps_raw, list) else []
        confidence = 0.85
    except (json.JSONDecodeError, TypeError, AttributeError):
        # Fallback: use raw content as reasoning
        reasoning_text = raw_content
        confidence = 0.4

    return {
        "reasoning": reasoning_text,
        "final_answer": final_answer,
        "steps": steps,
        "method_used": "llm_assisted",
        "extraction_confidence": confidence,
        "raw_response": response,
    }


def _extract_steps_from_text(text: str) -> list[str]:
    """Extract numbered or bullet steps from text."""
    if not text:
        return []

    step_pattern = re.compile(
        r"(?:Step\s+\d+[:.)]|^\d+\.\s|^[-*]\s)",
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(step_pattern.finditer(text))
    if not matches:
        return []

    steps = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        step_text = text[m.start() : end].strip()
        if step_text:
            steps.append(step_text)
    return steps
