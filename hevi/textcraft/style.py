"""Deterministic Chinese text-style feature extraction (clean-room).

Extracts a statistical *style profile* from a sample text: sentence-length
distribution, paragraph lengths, punctuation distribution, common function-word
frequencies and tone/modal-particle markers.  Everything here is a pure,
deterministic function of the input text — no model, no network — so profiles
are stable, diffable and unit-testable.

The profile can then drive a style transfer: :func:`style_transfer` formats
the profile into instructions and hands the actual rewriting to an *injected*
rewrite function (an LLM in production, a fake in tests).
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable

PROFILE_VERSION = 1

# Sentence-final / clause punctuation that ends a "sentence" for our stats.
_TERMINATORS = "。！？!?；;…"

_PUNCTUATION = "，。、；：？！…—·,.!?;:\"\"''「」『』（）()《》〈〉【】"

# Common Chinese function words / pronouns tracked as style markers.
FUNCTION_WORDS = (
    "的", "了", "是", "在", "就", "也", "都", "而", "但", "又", "把", "被",
    "让", "给", "从", "到", "对", "和", "与", "或", "还", "很", "更", "最",
    "没有", "没", "有", "着", "过", "不",
    "其实", "不过", "只是", "于是", "因此", "所以", "因为", "如果", "虽然",
    "然而", "非常",
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "这", "那",
    "这里", "那里", "什么", "怎么",
)

# Sentence-final modal particles: a strong colloquial-tone marker.
MODAL_PARTICLES = ("啊", "呀", "吧", "呢", "嘛", "哦", "啦", "哇")


def split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty paragraphs on blank lines."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, keeping terminal punctuation attached.

    A newline also ends a sentence.  Deterministic and language-light: it only
    looks at the terminator set in ``_TERMINATORS``.
    """
    sentences: list[str] = []
    buf = ""
    for ch in text:
        if ch == "\n":
            stripped = buf.strip()
            if stripped:
                sentences.append(stripped)
            buf = ""
            continue
        buf += ch
        if ch in _TERMINATORS:
            stripped = buf.strip()
            if stripped:
                sentences.append(stripped)
            buf = ""
    stripped = buf.strip()
    if stripped:
        sentences.append(stripped)
    return sentences


def sentence_lengths(text: str) -> list[int]:
    """Character length (whitespace excluded) of each sentence."""
    return [len(re.sub(r"\s+", "", s)) for s in split_sentences(text)]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pstdev(values: list[float], mean: float) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _round4(x: float) -> float:
    return round(float(x), 4)


def extract_style_profile(text: str) -> dict[str, Any]:
    """Extract a deterministic style profile (JSON-serialisable dict).

    Raises ``ValueError`` for empty / whitespace-only input.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("extract_style_profile: text must be a non-empty string")

    compact = re.sub(r"\s+", "", text)
    char_count = len(compact)
    per_1000 = 1000.0 / char_count if char_count else 0.0

    paragraphs = split_paragraphs(text)
    para_lens = [float(len(re.sub(r"\s+", "", p))) for p in paragraphs]
    para_mean = _mean(para_lens)

    sentences = split_sentences(text)
    sent_lens = [float(len(re.sub(r"\s+", "", s))) for s in sentences]
    sent_mean = _mean(sent_lens)

    punct_counts = {ch: compact.count(ch) for ch in _PUNCTUATION}
    total_punct = sum(punct_counts.values())
    punctuation_per_1000 = {
        ch: _round4(n * per_1000) for ch, n in punct_counts.items() if n
    }
    punctuation_ratio = (
        {ch: _round4(n / total_punct) for ch, n in punct_counts.items() if n}
        if total_punct
        else {}
    )

    function_words = {}
    for word in FUNCTION_WORDS:
        n = compact.count(word)
        if n:
            function_words[word] = _round4(n * per_1000)

    modal_total = sum(compact.count(p) for p in MODAL_PARTICLES)

    n_sent = len(sentences)
    exclamation = sum(1 for s in sentences if s.endswith(("！", "!")))
    question = sum(1 for s in sentences if s.endswith(("？", "?")))

    unique_chars = len(set(compact))

    return {
        "version": PROFILE_VERSION,
        "char_count": char_count,
        "sentence_count": n_sent,
        "paragraph_count": len(paragraphs),
        "sentence_len": {
            "mean": _round4(sent_mean),
            "std": _round4(_pstdev(sent_lens, sent_mean)),
            "min": int(min(sent_lens)) if sent_lens else 0,
            "max": int(max(sent_lens)) if sent_lens else 0,
        },
        "paragraph_len": {
            "mean": _round4(para_mean),
            "std": _round4(_pstdev(para_lens, para_mean)),
        },
        "punctuation_per_1000": punctuation_per_1000,
        "punctuation_ratio": punctuation_ratio,
        "function_words_per_1000": function_words,
        "modal_particles_per_1000": _round4(modal_total * per_1000),
        "exclamation_ratio": _round4(exclamation / n_sent) if n_sent else 0.0,
        "question_ratio": _round4(question / n_sent) if n_sent else 0.0,
        "char_ttr": _round4(unique_chars / char_count) if char_count else 0.0,
    }


def _flatten(profile: dict[str, Any]) -> dict[str, float]:
    """Flatten the numeric parts of a profile into one comparable vector."""
    flat: dict[str, float] = {
        "sentence_len.mean": float(profile["sentence_len"]["mean"]),
        "sentence_len.std": float(profile["sentence_len"]["std"]),
        "paragraph_len.mean": float(profile["paragraph_len"]["mean"]),
        "modal_particles_per_1000": float(profile["modal_particles_per_1000"]),
        "exclamation_ratio": float(profile["exclamation_ratio"]),
        "question_ratio": float(profile["question_ratio"]),
        "char_ttr": float(profile["char_ttr"]),
    }
    for key, value in profile.get("punctuation_ratio", {}).items():
        flat[f"punct:{key}"] = float(value)
    for key, value in profile.get("function_words_per_1000", {}).items():
        flat[f"fw:{key}"] = float(value)
    return flat


def profile_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Mean absolute difference between two profiles' numeric features.

    0.0 for identical profiles; grows as the styles diverge.  Useful to check
    that two samples are stylistically distinguishable.
    """
    fa, fb = _flatten(a), _flatten(b)
    keys = set(fa) | set(fb)
    if not keys:
        return 0.0
    total = sum(abs(fa.get(k, 0.0) - fb.get(k, 0.0)) for k in keys)
    return _round4(total / len(keys))


def build_style_instructions(profile: dict[str, Any]) -> str:
    """Render a profile as plain-language rewriting instructions."""
    sl = profile["sentence_len"]
    lines = [
        "按下面的文风特征改写文本，只改文风不改事实与信息：",
        f"- 句子平均长度约 {sl['mean']:.0f} 字，长短起伏（标准差）约 {sl['std']:.0f}。",
        f"- 段落平均约 {profile['paragraph_len']['mean']:.0f} 字，共 {profile['paragraph_count']} 段的密度感。",
        f"- 感叹句占比约 {profile['exclamation_ratio']:.0%}，疑问句占比约 {profile['question_ratio']:.0%}。",
        f"- 语气词密度约每千字 {profile['modal_particles_per_1000']:.1f} 个（啊/呀/吧/呢/嘛等）。",
    ]
    top_fw = sorted(
        profile.get("function_words_per_1000", {}).items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:6]
    if top_fw:
        lines.append("- 高频虚词/代词：" + "、".join(w for w, _ in top_fw) + "。")
    top_punct = sorted(
        profile.get("punctuation_ratio", {}).items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:5]
    if top_punct:
        lines.append("- 主要标点：" + "、".join(p for p, _ in top_punct) + "。")
    return "\n".join(lines)


def style_transfer(
    text: str,
    profile: dict[str, Any],
    rewrite_fn: Callable[[str, dict[str, Any]], str] | None,
) -> str:
    """Rewrite ``text`` toward ``profile`` using an injected rewrite function.

    ``rewrite_fn`` receives ``(text, profile)`` and returns the rewritten
    text.  In production this wraps an LLM; in tests it is a fake.  With no
    rewrite function this raises ``ValueError`` — there is deliberately no
    silent fallback, because a fake "transfer" would be a fake success.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("style_transfer: text must be a non-empty string")
    if not isinstance(profile, dict) or "sentence_len" not in profile:
        raise ValueError("style_transfer: profile must be a style profile dict")
    if rewrite_fn is None:
        raise ValueError(
            "style_transfer: no rewrite_fn injected (LLM backend not configured)"
        )
    result = rewrite_fn(text, profile)
    if not isinstance(result, str) or not result.strip():
        raise ValueError("style_transfer: rewrite_fn returned an empty result")
    return result


__all__ = [
    "PROFILE_VERSION",
    "FUNCTION_WORDS",
    "MODAL_PARTICLES",
    "split_paragraphs",
    "split_sentences",
    "sentence_lengths",
    "extract_style_profile",
    "profile_distance",
    "build_style_instructions",
    "style_transfer",
]
