"""ASR quality gates inspired by yw-transcribe (Explainer v8 Step 5)."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


class AsrVerificationError(RuntimeError):
    pass


_DIGITS = "零一二三四五六七八九"


def _integer_to_chinese(value: int) -> str:
    if value == 0:
        return "零"
    units = ("", "十", "百", "千")
    digits: list[str] = []
    remaining = value
    while remaining:
        digits.append(_DIGITS[remaining % 10])
        remaining //= 10
    digits.reverse()
    result = ""
    for index, digit in enumerate(digits):
        position = len(digits) - index - 1
        if digit == "零":
            if result and not result.endswith("零") and position > 0:
                result += "零"
            continue
        result += digit + (units[position] if position < len(units) else "")
    return result.rstrip("零")


def normalize_text_for_asr(text: str) -> str:
    """Normalize punctuation, Arabic digits, years and percentages before CER."""
    normalized = text.lower().strip()
    normalized = re.sub(
        r"(\d+(?:\.\d+)?)%",
        lambda match: "百分之" + _integer_to_chinese(int(float(match.group(1)))),
        normalized,
    )

    def replace_digits(match: re.Match[str]) -> str:
        value = match.group(0)
        return "".join(_DIGITS[int(char)] for char in value)

    normalized = re.sub(r"\d+", replace_digits, normalized)
    return re.sub(r"[^\w\u4e00-\u9fff]", "", normalized)


def character_error_rate(expected: str, actual: str) -> float:
    source = normalize_text_for_asr(expected)
    target = normalize_text_for_asr(actual)
    if not source:
        return 0.0 if not target else 1.0
    previous = list(range(len(target) + 1))
    for index, char in enumerate(source, start=1):
        current = [index]
        for target_index, target_char in enumerate(target, start=1):
            current.append(min(
                current[-1] + 1,
                previous[target_index] + 1,
                previous[target_index - 1] + (char != target_char),
            ))
        previous = current
    return previous[-1] / len(source)


def chunk_word_timestamps_for_mobile(
    word_timestamps: list[dict[str, Any]], max_chars_per_line: int = 12
) -> list[dict[str, Any]]:
    """Split word timestamps for 9:16 subtitles without exceeding one-line width."""
    if max_chars_per_line < 1:
        raise ValueError("max_chars_per_line 必须大于 0")
    lines: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    count = 0
    for word_info in word_timestamps:
        word = str(word_info.get("word", word_info.get("text", "")))
        if current and count + len(word) > max_chars_per_line:
            lines.append(_line(current))
            current, count = [], 0
        current.append(word_info)
        count += len(word)
    if current:
        lines.append(_line(current))
    return lines


def _line(words: list[dict[str, Any]]) -> dict[str, Any]:
    def value(item: dict[str, Any], key: str, fallback: str) -> Any:
        return item.get(key, item.get(fallback, 0))

    return {
        "start_ms": value(words[0], "start_ms", "start"),
        "end_ms": value(words[-1], "end_ms", "end"),
        "text": "".join(str(word.get("word", word.get("text", ""))) for word in words),
        "words": words,
    }


async def verify_and_retry(
    text: str,
    audio_path: Path,
    *,
    asr: Callable[[Path], Awaitable[str | dict[str, Any]] | str | dict[str, Any]],
    max_cer: float = 0.02,
    retries: int = 2,
    retry_synthesize: Callable[[], Awaitable[Path] | Path] | None = None,
) -> dict[str, Any]:
    """Verify one sentence; retry only that sentence and return its timestamps."""
    for attempt in range(1, retries + 2):
        result = asr(audio_path)
        if inspect.isawaitable(result):
            result = await result
        transcript = result.get("text", "") if isinstance(result, dict) else str(result)
        words = result.get("words", []) if isinstance(result, dict) else []
        cer = character_error_rate(text, transcript)
        if cer < max_cer:
            return {"passed": True, "attempt": attempt, "cer": cer, "transcript": transcript,
                    "lines": chunk_word_timestamps_for_mobile(words) if words else []}
        if retry_synthesize is not None and attempt <= retries:
            retried = retry_synthesize()
            audio_path = Path(await retried if inspect.isawaitable(retried) else retried)
    raise AsrVerificationError(f"ASR CER {cer:.3%} 超过门槛 {max_cer:.3%}")
