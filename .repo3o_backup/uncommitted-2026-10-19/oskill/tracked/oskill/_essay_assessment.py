"""K-2: essay_assessment — LLM-guided rubric assessment with guidance questions.

Composes oprim.rubric_score for objective dimension scoring; uses LLM only for
generating guidance questions. essay_guide is prohibited here (CI check enforced).

LLM prompt rule: "只输出问题，不输出修改建议"
Post-processing: all questions must end with '？'
revision_needed: weighted_score < 60.0
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from oprim._mneme_speech_types import EssayAssessmentInput, EssayAssessmentResult
from oprim._rubric_score import rubric_score

_DEFAULT_RUBRIC = {"结构": 0.25, "立意": 0.35, "语言": 0.25, "格式": 0.15}

_REVISION_THRESHOLD = 60.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def essay_assessment(
    inp: EssayAssessmentInput,
    *,
    llm: Callable[..., Any],
    rubric: dict[str, float] | None = None,
    model: str = "claude-sonnet-4-6",
) -> EssayAssessmentResult:
    """Assess an essay with objective rubric scoring + LLM-generated guidance questions.

    The LLM is prompted to produce ONLY questions (not corrections or model essays).
    All rubric dimension scores come from oprim.rubric_score (pure computation, no LLM).

    Args:
        inp: EssayAssessmentInput with essay_text, grade_level, essay_type, user_id.
        llm: LLM caller conforming to LLMCaller protocol.
        rubric: {dimension: weight} override. Defaults to standard 结构/立意/语言/格式 rubric.
        model: Model to request from the LLM caller.

    Returns:
        EssayAssessmentResult with rubric_scores, guidance_questions, revision_needed.

    Raises:
        ValueError: essay_text is empty.
    """
    if not inp.essay_text.strip():
        raise ValueError("essay_text must not be empty")

    effective_rubric = rubric if rubric is not None else _DEFAULT_RUBRIC

    # --- Pure-computation scoring ---
    scores = rubric_score(
        inp.essay_text,
        rubric=effective_rubric,
        grade_level=inp.grade_level,
        essay_type=inp.essay_type,
    )

    # --- Weighted aggregate for revision_needed ---
    total_weight = sum(effective_rubric.values())
    weighted_score = (
        sum(scores[dim] * w for dim, w in effective_rubric.items() if dim in scores) / total_weight
        if total_weight
        else 0.0
    )
    revision_needed = weighted_score < _REVISION_THRESHOLD

    # --- LLM: generate guidance questions only ---
    questions = await _generate_guidance_questions(inp, scores=scores, llm=llm, model=model)

    return EssayAssessmentResult(
        rubric_scores=scores,
        guidance_questions=questions,
        revision_needed=revision_needed,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _generate_guidance_questions(
    inp: EssayAssessmentInput,
    *,
    scores: dict[str, float],
    llm: Callable[..., Any],
    model: str,
) -> list[str]:
    """Call LLM with strict instruction: questions only, no corrections."""
    import asyncio

    dim_summary = "；".join(f"{d}={v:.1f}分" for d, v in scores.items())
    user = (
        f"作文类型：{inp.essay_type}，年级：{inp.grade_level}\n"
        f"各维度评分：{dim_summary}\n\n"
        "作文正文：\n"
        f"{inp.essay_text}\n\n"
        "请基于以上评分，生成3-5个引导性问题，帮助学生反思和改进。"
        "只输出问题，不输出修改建议。每个问题以'？'结尾。输出JSON数组。"
    )

    messages = [{"role": "user", "content": user}]
    coro_or_result = llm(messages=messages, max_tokens=512)
    if asyncio.iscoroutine(coro_or_result):
        response = await coro_or_result
    else:
        response = coro_or_result

    raw_text = _extract_text(response)
    questions = _parse_questions(raw_text)
    return _enforce_question_mark(questions)


def _extract_text(response: dict | Any) -> str:
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return str(response)
    content = response.get("content", "")
    if isinstance(content, str):
        return content
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return ""


def _parse_questions(raw: str) -> list[str]:
    """Try JSON array parse; fall back to line-by-line extraction."""
    raw = raw.strip()
    # Try to find JSON array in the text
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return [str(q).strip() for q in parsed if str(q).strip()]
        except (json.JSONDecodeError, ValueError):
            pass

    # Fall back: split by newline and filter non-empty lines
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    # Remove leading bullets/numbers
    cleaned = [re.sub(r"^[\d\.、\-\*]+\s*", "", ln) for ln in lines]
    return [c for c in cleaned if c]


def _enforce_question_mark(questions: list[str]) -> list[str]:
    """Ensure every question ends with '？'."""
    result = []
    for q in questions:
        q = q.rstrip("?？").rstrip()
        result.append(q + "？")
    return result
