"""De-AI-flavour polishing for Chinese text (clean-room, pure functions).

A deterministic clean-up pass that removes the tells of machine-generated
Chinese prose:

1. **Template clichés** — stock AI phrases ("值得注意的是", "总而言之",
   "随着科技的不断发展", …) are deleted or swapped for plainer phrasing.
2. **Colloquial swaps** — a small written→spoken word table ("购买"→"买",
   "目前"→"现在", …).
3. **Sentence-length diversification** — over-long sentences are split at
   comma boundaries so the rhythm stops being uniformly long.
4. **Punctuation diversification** — collapsed repeats ("！！"→"！") and a
   mid-sentence "，" upgraded to "；" in comma-heavy sentences.

:func:`humanize_text` returns the polished text plus a change report (how
many edits, of which categories).  Everything is a pure function of the
input: same text in, same text + report out.
"""

from __future__ import annotations

import re
from typing import Any

from .style import sentence_lengths, split_sentences

# Stock phrases typical of generated Chinese prose -> plainer replacement
# ("" = delete the phrase).  Applied longest-first so longer patterns win.
CLICHE_REPLACEMENTS: dict[str, str] = {
    "随着科学技术的不断发展": "科技这些年变化很大",
    "随着科技的不断发展": "科技这些年变化很大",
    "在当今社会": "现在",
    "发挥着至关重要的作用": "特别关键",
    "起到了至关重要的作用": "特别关键",
    "起到了重要的作用": "帮了大忙",
    "具有重要的意义": "挺有意义",
    "具有深远的影响": "影响不小",
    "值得注意的是，": "",
    "值得注意的是": "",
    "需要指出的是，": "",
    "不可否认的是，": "",
    "不难发现，": "",
    "不难发现": "",
    "综上所述，": "",
    "综上所述": "",
    "总而言之，": "说到底，",
    "总的来说，": "说白了，",
    "换句话说，": "也就是说，",
    "更重要的是，": "还有一点，",
    "与此同时，": "同时，",
    "在这个过程中": "这期间",
    "毋庸置疑": "没错",
    "显而易见": "明摆着",
    "这无疑是": "这就是",
    "让我们一起": "我们一起",
}

# Written-register words -> everyday spoken equivalents.
COLLOQUIAL_REPLACEMENTS: dict[str, str] = {
    "购买": "买",
    "食用": "吃",
    "饮用": "喝",
    "目前": "现在",
    "立即": "马上",
    "随后": "接着",
}

_DEFAULT_MAX_SENTENCE_LEN = 42
_TERMINAL_CHARS = "。！？!?；;"


def count_cliches(text: str) -> int:
    """How many stock AI phrases occur in ``text``.

    Counted greedily, longest pattern first, on a shrinking copy — the same
    order :func:`humanize_text` replaces them — so overlapping patterns
    ("综上所述，" vs "综上所述") are never double-counted and the number
    matches the report's ``cliche`` change count.
    """
    total = 0
    rest = text
    for pattern in sorted(CLICHE_REPLACEMENTS, key=len, reverse=True):
        n = rest.count(pattern)
        if n:
            total += n
            rest = rest.replace(pattern, "")
    return total


def _apply_table(
    text: str, table: dict[str, str], category: str, details: list[dict[str, Any]]
) -> tuple[str, int]:
    total = 0
    for pattern in sorted(table, key=len, reverse=True):
        n = text.count(pattern)
        if n:
            text = text.replace(pattern, table[pattern])
            total += n
            details.append(
                {"category": category, "from": pattern, "to": table[pattern], "count": n}
            )
    return text, total


def _split_long_sentence(sentence: str, max_len: int) -> list[str]:
    """Split one over-long sentence at its commas into <= max_len pieces."""
    if len(sentence) <= max_len:
        return [sentence]
    end = sentence[-1] if sentence[-1] in _TERMINAL_CHARS else ""
    body = sentence[:-1] if end else sentence
    clauses = body.split("，")
    if len(clauses) == 1:
        return [sentence]  # no comma to split at; leave it alone
    groups: list[str] = []
    cur = clauses[0]
    for clause in clauses[1:]:
        if len(cur) + 1 + len(clause) <= max_len:
            cur = cur + "，" + clause
        else:
            groups.append(cur)
            cur = clause
    groups.append(cur)
    return [
        g + (end if i == len(groups) - 1 and end else "。")
        for i, g in enumerate(groups)
    ]


def _diversify_sentences(
    text: str, max_len: int, details: list[dict[str, Any]]
) -> tuple[str, int]:
    splits = 0
    out_paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        pieces: list[str] = []
        for sentence in split_sentences(paragraph):
            parts = _split_long_sentence(sentence, max_len)
            if len(parts) > 1:
                splits += len(parts) - 1
                details.append(
                    {"category": "sentence_split", "from": sentence, "to": parts}
                )
            pieces.extend(parts)
        out_paragraphs.append("".join(pieces))
    return "\n\n".join(out_paragraphs), splits


def _diversify_punctuation(
    text: str, details: list[dict[str, Any]]
) -> tuple[str, int]:
    changes = 0
    for pat, repl, label in (
        (r"([！!])\1+", r"\1", "collapse_exclamation"),
        (r"([？?])\1+", r"\1", "collapse_question"),
        (r"。{2,}", "。", "collapse_period"),
        (r"，{2,}", "，", "collapse_comma"),
    ):
        text, n = re.subn(pat, repl, text)
        if n:
            changes += n
            details.append({"category": "punctuation", "from": label, "to": repl, "count": n})

    out_paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        pieces: list[str] = []
        for sentence in split_sentences(paragraph):
            if sentence.count("，") >= 3 and "；" not in sentence:
                commas = [i for i, ch in enumerate(sentence) if ch == "，"]
                mid = commas[len(commas) // 2]
                sentence = sentence[:mid] + "；" + sentence[mid + 1:]
                changes += 1
                details.append(
                    {"category": "punctuation", "from": "，", "to": "；", "count": 1}
                )
            pieces.append(sentence)
        out_paragraphs.append("".join(pieces))
    return "\n\n".join(out_paragraphs), changes


def _std(values: list[int]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return round((sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5, 4)


def humanize_text(
    text: str, *, max_sentence_len: int = _DEFAULT_MAX_SENTENCE_LEN
) -> tuple[str, dict[str, Any]]:
    """Polish ``text`` and return ``(new_text, report)``.

    Pure and deterministic.  Raises ``ValueError`` on empty input or an
    unreasonable ``max_sentence_len``.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("humanize_text: text must be a non-empty string")
    if not isinstance(max_sentence_len, int) or max_sentence_len < 10:
        raise ValueError("humanize_text: max_sentence_len must be an int >= 10")

    details: list[dict[str, Any]] = []
    by_category = {"cliche": 0, "colloquial": 0, "sentence_split": 0, "punctuation": 0}

    cliche_before = count_cliches(text)
    lens_before = sentence_lengths(text)

    out, n = _apply_table(text, CLICHE_REPLACEMENTS, "cliche", details)
    by_category["cliche"] = n
    out, n = _apply_table(out, COLLOQUIAL_REPLACEMENTS, "colloquial", details)
    by_category["colloquial"] = n
    out, n = _diversify_sentences(out, max_sentence_len, details)
    by_category["sentence_split"] = n
    out, n = _diversify_punctuation(out, details)
    by_category["punctuation"] = n

    lens_after = sentence_lengths(out)
    report: dict[str, Any] = {
        "changes_total": sum(by_category.values()),
        "by_category": by_category,
        "details": details,
        "cliche_before": cliche_before,
        "cliche_after": count_cliches(out),
        "sentence_count_before": len(lens_before),
        "sentence_count_after": len(lens_after),
        "sentence_len_std_before": _std(lens_before),
        "sentence_len_std_after": _std(lens_after),
        "max_sentence_len_before": max(lens_before) if lens_before else 0,
        "max_sentence_len_after": max(lens_after) if lens_after else 0,
    }
    return out, report


__all__ = [
    "CLICHE_REPLACEMENTS",
    "COLLOQUIAL_REPLACEMENTS",
    "count_cliches",
    "humanize_text",
]
