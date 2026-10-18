"""K-1: english_speaking_practice — multi-turn guided English speaking session.

All providers (tts, stt, pronunciation_eval, llm) are injected by the caller.
LLM feedback must be encouraging/guiding — never a direct correction or model answer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from oprim._mneme_speech_types import PronunciationResult, SpeakingPracticeResult

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def english_speaking_practice(
    *,
    topic: str,
    max_turns: int = 5,
    tts: Callable[..., Awaitable[str]],
    stt: Callable[..., Awaitable[str]],
    pronunciation_eval: Callable[..., Awaitable[PronunciationResult]],
    llm: Callable[..., Any],
    model: str = "claude-sonnet-4-6",
) -> SpeakingPracticeResult:
    """Run a guided English speaking practice session on a topic.

    Args:
        topic: The conversation topic or prompt (e.g. "Tell me about your weekend").
        max_turns: Maximum number of student turns (each turn = student speaks, AI responds).
        tts: Provider callable for text → base64 audio.
        stt: Provider callable for base64 audio → text.
        pronunciation_eval: Provider callable for (audio_b64, reference_text) → PronunciationResult.
        llm: LLM caller conforming to LLMCaller protocol.
        model: Model identifier to pass to the LLM caller.

    Returns:
        SpeakingPracticeResult with turn records, pronunciation scores, and overall progress.
    """
    if max_turns < 1:
        raise ValueError("max_turns must be at least 1")
    if not topic.strip():
        raise ValueError("topic must not be empty")

    turns: list[dict] = []
    pronunciation_scores: list[PronunciationResult] = []
    history: list[dict] = [{"role": "user", "content": _opening_prompt(topic)}]

    # Generate opening teacher utterance
    ai_text = await _llm_text(history, llm=llm, model=model)
    history.append({"role": "assistant", "content": ai_text})

    for turn_idx in range(max_turns):
        # Simulate student audio with placeholder — real callers pass actual audio
        student_audio_b64 = await _await_if_coro(
            tts(text="[student input placeholder]", language="en")
        )

        # STT: transcribe student audio
        student_text = await stt(audio_b64=student_audio_b64, language="en")

        # Pronunciation evaluation against the student's own utterance
        pron = await pronunciation_eval(audio_b64=student_audio_b64, reference_text=student_text)
        pronunciation_scores.append(pron)

        # Append student turn to history
        history.append({"role": "user", "content": student_text})

        # Generate encouraging AI feedback (not direct correction)
        feedback_prompt = _feedback_prompt(student_text, pron)
        history.append({"role": "user", "content": feedback_prompt})
        ai_feedback = await _llm_text(history, llm=llm, model=model)
        ai_feedback = _ensure_encouraging(ai_feedback)
        history.append({"role": "assistant", "content": ai_feedback})

        turns.append(
            {
                "turn": turn_idx + 1,
                "student_text": student_text,
                "ai_feedback": ai_feedback,
                "pronunciation": {
                    "overall": pron.overall_score,
                    "fluency": pron.fluency_score,
                    "accuracy": pron.accuracy_score,
                },
            }
        )

    overall_progress = (
        sum(p.overall_score for p in pronunciation_scores) / len(pronunciation_scores)
        if pronunciation_scores
        else 0.0
    )

    return SpeakingPracticeResult(
        turns=turns,
        pronunciation_scores=pronunciation_scores,
        overall_progress=round(overall_progress, 4),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _opening_prompt(topic: str) -> str:
    return (
        "You are a friendly English speaking coach. Your role is to guide the student "
        "through a conversation on the following topic. Give encouraging, open-ended "
        "prompts. Do NOT directly correct mistakes — instead, model correct usage "
        "naturally in your own speech and ask follow-up questions.\n\n"
        f"Topic: {topic}\n\n"
        "Start the conversation with a warm, inviting question to the student."
    )


def _feedback_prompt(student_text: str, pron: PronunciationResult) -> str:
    fluency_label = "good" if pron.fluency_score >= 0.7 else "needs practice"
    return (
        "[Internal instruction — do not show to student]\n"
        f"Student said: {student_text}\n"
        f"Pronunciation fluency: {fluency_label} ({pron.fluency_score:.2f})\n"
        "Respond with 1-2 sentences of encouragement and a guiding follow-up question. "
        "Do NOT restate or directly correct what the student said. "
        "Gently model correct phrasing naturally within your own response."
    )


async def _llm_text(history: list[dict], *, llm: Callable[..., Any], model: str) -> str:
    """Call LLM and extract text from the response."""
    import asyncio

    coro_or_result = llm(messages=history, max_tokens=256)
    if asyncio.iscoroutine(coro_or_result):
        response = await coro_or_result
    else:
        response = coro_or_result

    content = response.get("content", [])
    if isinstance(content, str):
        return content.strip()
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "").strip()
    return str(content).strip()


def _ensure_encouraging(text: str) -> str:
    """Guard: remove any line that looks like a direct correction ('You should say...')."""
    bad_prefixes = (
        "you should say",
        "the correct way is",
        "the correct phrase is",
        "it should be",
        "you made a mistake",
        "that is wrong",
        "incorrect",
    )
    lines = text.splitlines()
    filtered = [
        line for line in lines if not any(line.lower().strip().startswith(p) for p in bad_prefixes)
    ]
    return "\n".join(filtered).strip() or text.strip()


async def _await_if_coro(value: Any) -> Any:
    import asyncio

    if asyncio.iscoroutine(value):
        return await value
    return value
