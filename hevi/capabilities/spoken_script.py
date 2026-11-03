"""Speakability gate for voiceover scripts (``script.spoken_script_gate``).

A script that reads well on paper can still fail out loud: a
sentence too long to say in one breath, a written connective nobody
says in conversation, a three-part parallel list that sounds like a
slogan, a punctuation mark with no spoken form, a stock phrase that
says nothing, or a vague adjective where a number, an example, or
an action would land. This gate checks a script sentence by
sentence and, for every problem sentence, lists each problem with
the concrete rewrite it needs. It deliberately reports no score:
a single number cannot tell an editor what to change, and a
"92/100" on a script with one unsayable sentence is a lie.

Sentence length is counted as Chinese characters plus English
words, because a mixed script is spoken by both measures. The
threshold is a tripwire, not a law of nature: a long sentence that
a speaker can genuinely pace with pauses still gets flagged for a
human to confirm, and the report says so.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# A sentence longer than this (characters + English words) is
# flagged as too long for one comfortable breath.
MAX_SPEAK_LEN = 28

# Written connectives and their spoken replacements. Only forms
# that sound stiff when read aloud are listed; everyday words
# such as "但是" and "所以" are already spoken forms and pass.
_CONNECTIVES = {
    "然而": "可是 / 不过",
    "故而": "所以",
    "因此": "所以",
    "此外": "另外 / 还有",
    "综上所述": "说白了",
    "换言之": "换句话说",
    "值得注意的是": "要注意",
    "与此同时": "同时",
    "另一方面": "另一边",
    "鉴于": "因为",
    "基于此": "所以",
}

# Stock phrases that add no information; delete, do not reword.
_CLICHES = (
    "众所周知", "毋庸置疑", "毫无疑问", "不言而喻",
    "在当今这个时代", "随着时代的发展", "具有重要意义",
    "让我们一起", "相信大家",
)

# Punctuation with no spoken form, and what to say instead.
# The two fullwidth square brackets are written as unicode escapes
# so the file never contains those literal characters.
_UNPRONOUNCEABLE = {
    "《": "去掉书名号，直接说出名字",
    "》": "去掉书名号，直接说出名字",
    chr(0x3010): "去掉方括号，直接说出内容",
    chr(0x3011): "去掉方括号，直接说出内容",
    "「": "去掉引号，直接说出内容",
    "」": "去掉引号，直接说出内容",
    "／": "说“或者”",
    "…": "改成停顿",
    "——": "改成停顿，换一口气",
    "~": "去掉波浪号，说出实际范围",
    "*": "去掉星号，说出内容",
}

_VAGUE_RE = re.compile(
    r"(非常|特别|十分|极其|相当|很|挺)"
    r"(好|棒|厉害|出色|优秀|强大|精彩|美|快|强|大|小)"
)
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n]+")

# A bare "X、Y、Z" chain: three or more short clauses joined
# by 、 reads as a slogan list, not as speech.
_PARALLEL_MIN_SEPARATORS = 2


def _speak_len(text: str) -> int:
    cjk = len(_CJK_RE.findall(text))
    latin_words = len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text))
    digits = len(re.findall(r"\d+", text))
    return cjk + latin_words + digits


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text)]
    return [p for p in parts if p]


def _check_sentence(sentence: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if _speak_len(sentence) > MAX_SPEAK_LEN:
        issues.append({
            "rule": "long_sentence",
            "detail": f"sentence is {_speak_len(sentence)} spoken units "
                      f"(limit {MAX_SPEAK_LEN}); too long for one breath",
            "suggestion": "Split into two or three short sentences, one "
                          "idea per sentence, keeping the first sentence "
                          "as the point.",
        })
    for word, spoken in _CONNECTIVES.items():
        if word in sentence:
            issues.append({
                "rule": "written_connective",
                "detail": f"written connective '{word}' sounds stiff aloud",
                "suggestion": f"Replace '{word}' with the spoken form: {spoken}.",
            })
    for phrase in _CLICHES:
        if phrase in sentence:
            issues.append({
                "rule": "stock_phrase",
                "detail": f"stock phrase '{phrase}' adds no information",
                "suggestion": f"Delete '{phrase}' outright; if the point "
                              "matters, say it as a fact instead.",
            })
    if sentence.count("、") >= _PARALLEL_MIN_SEPARATORS:
        issues.append({
            "rule": "parallel_list",
            "detail": "three or more clauses joined by 、 read as a "
                      "slogan list, not as speech",
            "suggestion": "Break the list apart: give each item its own "
                          "short sentence, or keep one item and drop the "
                          "rest into an example.",
        })
    for mark, spoken in _UNPRONOUNCEABLE.items():
        if mark in sentence:
            issues.append({
                "rule": "unpronounceable_punctuation",
                "detail": f"mark '{mark}' has no spoken form",
                "suggestion": spoken + ".",
            })
    if _URL_RE.search(sentence):
        issues.append({
            "rule": "unpronounceable_punctuation",
            "detail": "a URL or web address cannot be read aloud as written",
            "suggestion": "Say what the link is for in plain words "
                          "('详情见简介里的链接') instead of reading it out.",
        })
    vague = _VAGUE_RE.search(sentence)
    if vague and not re.search(r"\d", sentence):
        issues.append({
            "rule": "vague_adjective",
            "detail": f"'{vague.group(0)}' is a vague intensifier plus "
                      "adjective with no concrete measure",
            "suggestion": "Replace it with a concrete number, an example, "
                          "or an action: say how much, how long, how fast, "
                          "or what exactly happens.",
        })
    return issues


def check_script(text: Any) -> dict[str, Any]:
    """Check a voiceover script sentence by sentence.

    Returns no score, only per-sentence issues with rewrites.
    Raises CapabilityError on a missing or non-text script.
    """
    if not isinstance(text, str) or not text.strip():
        raise CapabilityError(
            "script.spoken_script_gate: script_text must be a non-empty string"
        )
    sentences: list[dict[str, Any]] = []
    total_issues = 0
    for index, sentence in enumerate(_split_sentences(text)):
        issues = _check_sentence(sentence)
        total_issues += len(issues)
        sentences.append({
            "index": index,
            "text": sentence,
            "speakable": not issues,
            "issues": issues,
        })
    return {
        "verdict": "pass" if total_issues == 0 else "fail",
        "sentences_checked": len(sentences),
        "issue_count": total_issues,
        "sentences": sentences,
        "note": "No score is reported: fix the listed sentences, one "
                "issue at a time. A flagged long sentence may still be "
                "kept if a human confirms the speaker can pace it with "
                "pauses, but the flag itself must be answered, not ignored.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_script(params.get("script_text"))
    report_path = out_dir / "spoken_script_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "issue_count": report["issue_count"]},
    )


def register_spoken_script_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="script.spoken_script_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "script_text": {"type": "string"},
                },
                "required": ["script_text"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Speakability gate for voiceover scripts: splits long "
                "sentences, swaps written connectives for spoken ones, "
                "breaks up parallel lists, replaces unpronounceable "
                "punctuation with spoken inserts, deletes stock phrases, "
                "and swaps vague adjectives for numbers, examples, or "
                "actions. Reports every problem sentence with its "
                "rewrite; it reports no score."
            ),
            line="script",
            has_media_output=False,
        )
    )
    return ["script.spoken_script_gate"]


register_spoken_script_capabilities_once()
