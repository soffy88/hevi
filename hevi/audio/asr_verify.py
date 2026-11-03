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
            current.append(
                min(
                    current[-1] + 1,
                    previous[target_index] + 1,
                    previous[target_index - 1] + (char != target_char),
                )
            )
        previous = current
    return previous[-1] / len(source)


# --- Critical-word checks (W3) ------------------------------------------------
# Plain CER weights every character equally, so a flipped negation ("没有" ->
# "有") or a dropped digit costs a single character and sails under a 2%
# threshold while reversing the meaning.  These checks look only at the words
# where an error is expensive, and report them structurally.

#: Negation words checked by exact occurrence count.  Single characters on
#: purpose: ASR confusions here ("不"/"没" dropped or inserted) flip polarity.
NEGATION_WORDS: tuple[str, ...] = ("不", "没", "无", "别", "未", "非")

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_BIG_UNITS = {"万": 10_000, "亿": 100_000_000}
_NUMBER_RE = re.compile(
    r"\d+(?:\.\d+)?%?"
    r"|[零一二三四五六七八九十百千万亿两]+(?:点[零一二三四五六七八九]+)?"
)


def _chinese_integer_value(run: str) -> int | None:
    """Parse a Chinese integer run, or return None if it does not parse.

    Handles both styles found in narration: digit-by-digit ("二零二六" ->
    2026) and unit composition ("一千二百" -> 1200, "十万" -> 100000).
    """
    if not run:
        return None
    if all(char in _CN_DIGITS for char in run) and len(run) > 1:
        # No unit characters: read it as a digit string (years, codes...).
        return int("".join(str(_CN_DIGITS[char]) for char in run))
    total = 0
    section = 0
    digit: int | None = None
    for char in run:
        if char in _CN_DIGITS:
            digit = _CN_DIGITS[char]
        elif char in _CN_SMALL_UNITS:
            section += (digit if digit is not None else 1) * _CN_SMALL_UNITS[char]
            digit = None
        elif char in _CN_BIG_UNITS:
            if digit is not None:
                section += digit
                digit = None
            total += (section or 1) * _CN_BIG_UNITS[char]
            section = 0
        else:  # pragma: no cover - regex only feeds known characters
            return None
    if digit is not None:
        section += digit
    return total + section


def _canonical_number(raw: str) -> str | None:
    """Canonical numeric string for comparison; None = not a usable number.

    Arabic and Chinese spellings of the same value canonicalize identically
    ("1200" == "一千二百"), so a faithful ASR format change is not an error.
    A lone unit character ("百" out of "百分之") is a fragment, not a number.
    """
    if raw[0].isdigit():
        percent = raw.endswith("%")
        body = raw[:-1] if percent else raw
        value: int | float = float(body) if "." in body else int(body)
        text = str(int(value)) if float(value).is_integer() else str(value)
        return text + ("%" if percent else "")
    if len(raw) == 1 and raw in {**_CN_SMALL_UNITS, **_CN_BIG_UNITS}:
        return None
    if "点" in raw:
        head, _, frac = raw.partition("点")
        head_value = _chinese_integer_value(head)
        if head_value is None or not frac or any(c not in _CN_DIGITS for c in frac):
            return None
        frac_text = "".join(str(_CN_DIGITS[c]) for c in frac)
        return f"{head_value}.{frac_text}"
    value = _chinese_integer_value(raw)
    return str(value) if value is not None else None


def _extract_numbers(text: str) -> tuple[list[str], list[str]]:
    """(canonical_numbers, raw_spans) in order of appearance."""
    canonical: list[str] = []
    raw_spans: list[str] = []
    for match in _NUMBER_RE.finditer(text):
        value = _canonical_number(match.group(0))
        if value is not None:
            canonical.append(value)
            raw_spans.append(match.group(0))
    return canonical, raw_spans


def critical_word_errors(reference: str, hypothesis: str) -> dict[str, Any]:
    """Compare the words whose mishearing changes meaning, not just chars.

    Checks, in order:

    * Negations: occurrence counts of each word in ``NEGATION_WORDS``
      (不/没/无/别/未/非) in reference vs hypothesis.  Any per-word count
      difference is a mismatch -- a dropped/added negation flips polarity
      while barely moving CER.
    * Numbers: the ordered sequence of numeric expressions (Arabic
      Arabic digits incl. decimals/percent, and Chinese numeral runs).  Chinese
      and Arabic spellings of the same value compare equal (see
      ``_canonical_number``).  Extraction is a heuristic over numeral runs,
      so e.g. idioms containing numeral characters are compared as written
      on both sides.

    Returns a structured dict::

        {
          "passed": bool,
          "negations": {"words": [...], "reference_counts": {...},
                        "hypothesis_counts": {...}, "mismatches": [...]},
          "numbers": {"reference": [...], "hypothesis": [...],
                      "reference_raw": [...], "hypothesis_raw": [...],
                      "match": bool, "first_mismatch_index": int | None},
          "errors": [str, ...],   # human-readable summary of every mismatch
        }
    """
    ref_counts = {word: reference.count(word) for word in NEGATION_WORDS}
    hyp_counts = {word: hypothesis.count(word) for word in NEGATION_WORDS}
    mismatches = [
        {
            "word": word,
            "reference_count": ref_counts[word],
            "hypothesis_count": hyp_counts[word],
            "delta": hyp_counts[word] - ref_counts[word],
        }
        for word in NEGATION_WORDS
        if ref_counts[word] != hyp_counts[word]
    ]
    ref_numbers, ref_raw = _extract_numbers(reference)
    hyp_numbers, hyp_raw = _extract_numbers(hypothesis)
    numbers_match = ref_numbers == hyp_numbers
    first_mismatch: int | None = None
    if not numbers_match:
        for idx, (ref_num, hyp_num) in enumerate(zip(ref_numbers, hyp_numbers, strict=False)):
            if ref_num != hyp_num:
                first_mismatch = idx
                break
        else:
            first_mismatch = min(len(ref_numbers), len(hyp_numbers))
    errors: list[str] = [
        (
            f"否定词「{item['word']}」次数不一致: "
            f"参考 {item['reference_count']} 次, 转写 {item['hypothesis_count']} 次"
        )
        for item in mismatches
    ]
    if not numbers_match:
        errors.append(f"数字序列不一致: 参考 {ref_numbers} != 转写 {hyp_numbers}")
    return {
        "passed": not mismatches and numbers_match,
        "negations": {
            "words": list(NEGATION_WORDS),
            "reference_counts": ref_counts,
            "hypothesis_counts": hyp_counts,
            "mismatches": mismatches,
        },
        "numbers": {
            "reference": ref_numbers,
            "hypothesis": hyp_numbers,
            "reference_raw": ref_raw,
            "hypothesis_raw": hyp_raw,
            "match": numbers_match,
            "first_mismatch_index": first_mismatch,
        },
        "errors": errors,
    }


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
            return {
                "passed": True,
                "attempt": attempt,
                "cer": cer,
                "transcript": transcript,
                "lines": chunk_word_timestamps_for_mobile(words) if words else [],
                # Additive/backward-compatible: critical-word detail for
                # callers that want it.  It deliberately does NOT change the
                # CER pass/fail decision above (existing callers gate on CER).
                "critical_words": critical_word_errors(text, transcript),
            }
        if retry_synthesize is not None and attempt <= retries:
            retried = retry_synthesize()
            audio_path = Path(await retried if inspect.isawaitable(retried) else retried)
    raise AsrVerificationError(f"ASR CER {cer:.3%} 超过门槛 {max_cer:.3%}")
