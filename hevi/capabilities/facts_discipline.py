"""On-screen facts discipline (``qa.facts_discipline``).

Clean-room rewrite of three *wording rules* from the FACTS
discipline of ``win4r/video-director`` (MIT; see
VIDEO_DIRECTOR_ATTRIBUTION.md). No text, code or script from the
source repository is copied here, and nothing here duplicates
``production_gates`` / ``reference_teardown``: those already check
sourcing and evidence in general; this module only adds these
three screen-wording rules:

1. A counter / number shown while it is still moving must not
   carry a value label (the label belongs with the settled
   number, not the moving one).
2. An unfinished month or quarter must be marked "to date" (or
   an equivalent "as of" / cutoff marker).
3. Timing must not be written as cause: a time or event mention
   plus a causal verb ("brought", "drove", ...) with no causal
   evidence marker is a failure, however true the correlation.

Every number must also trace to a source or be marked
illustrative; an unsourced, unmarked number is a warning, not a
failure, because the claim itself may still be checked upstream.

Texts are checked sentence by sentence (split on sentence-ending
punctuation and newlines). Which months/quarters count as
"unfinished" comes from ``as_of`` (``"YYYY-MM"``; defaults to
the current month) or an explicit ``unfinished_periods`` list of
substrings such as ``["10月", "October", "Q4"]``.
"""

from __future__ import annotations

import json
import re
from datetime import date
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

_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n；;]+")
_NUMBER_RE = re.compile(r"\d[\d,]*(\.\d+)?\s*(%|万|亿|千|k|K|M)?")

# Rule 1: counter/number movement phrasing. "停稳/settled" negates
# the rule: a label on a settled counter is exactly what is wanted.
_MOVEMENT_RES = [
    re.compile(p, re.IGNORECASE) for p in (
        r"计数器", r"计数", r"数字\s*(上升|上涨|增长|攀升|跳动|滚动|变化|移动|在跑)",
        r"counter", r"counting\s+up", r"ticking",
        r"number\s+(rising|climbing|growing|ticking|moving|rolling)",
        r"count\s+(rising|climbing|growing|ticking|moving)",
    )
]
_SETTLED_RES = [
    re.compile(p, re.IGNORECASE) for p in (
        r"停稳", r"停止", r"静止", r"定格", r"settled", r"stopped", r"at\s+rest",
    )
]

# Rule 2: to-date / cutoff markers that excuse an unfinished period.
_TO_DATE_RES = [
    re.compile(p, re.IGNORECASE) for p in (
        r"to[\s-]*date", r"截至", r"截止", r"迄今", r"as\s+of", r"year[\s-]*to[\s-]*date",
        r"\bYTD\b", r"本月截至", r"目前为止",
    )
]
_THIS_PERIOD_RES = [
    re.compile(p, re.IGNORECASE) for p in (
        r"本月", r"本季度", r"this\s+month", r"this\s+quarter",
    )
]

# Rule 3: timing/event tokens plus causal verbs, without an
# evidence marker.
_TIMING_RES = [
    re.compile(p, re.IGNORECASE) for p in (
        r"\d{4}\s*年", r"\d{1,2}\s*月", r"[一二三四五六七八九十]{1,3}月",
        r"January|February|March|April|May|June|July|August|September|October|November|December",
        r"\bJan\b|\bFeb\b|\bMar\b|\bApr\b|\bJun\b|\bJul\b|\bAug\b|\bSep\b|\bOct\b|\bNov\b|\bDec\b",
        r"Q[1-4]\b", r"第[一二三四]季度", r"季度", r"spike", r"上线", r"发布",
        r"launch", r"\bpost\b", r"HN\b", r"Hacker\s*News", r"事件", r"活动",
        r"timing", r"时间",
    )
]
_CAUSE_RES = [
    re.compile(p, re.IGNORECASE) for p in (
        r"带来", r"导致", r"推动", r"造成", r"引发", r"致使", r"使得",
        r"led\s+to", r"drove", r"resulted\s+in", r"triggered", r"caused",
        r"brought\s+(in\s+)?", r"powered",
    )
]
_EVIDENCE_RES = [
    re.compile(p, re.IGNORECASE) for p in (
        r"因果证据", r"证据", r"数据证实", r"归因", r"causal\s+evidence",
        r"\bevidence\b", r"attributed", r"数据显示",
    )
]

# Illustrative markers that excuse a number without a source.
_ILLUSTRATIVE_RES = [
    re.compile(p, re.IGNORECASE) for p in (
        r"示意", r"示例", r"举例", r"虚构", r"仅供参考",
        r"illustrative", r"for\s+illustration", r"\bexample\b", r"schematic",
    )
]

_MONTH_NAMES = [
    ("1", ["1月", "一月", "January", "Jan"]),
    ("2", ["2月", "二月", "February", "Feb"]),
    ("3", ["3月", "三月", "March", "Mar"]),
    ("4", ["4月", "四月", "April", "Apr"]),
    ("5", ["5月", "五月", "May"]),
    ("6", ["6月", "六月", "June", "Jun"]),
    ("7", ["7月", "七月", "July", "Jul"]),
    ("8", ["8月", "八月", "August", "Aug"]),
    ("9", ["9月", "九月", "September", "Sep"]),
    ("10", ["10月", "十月", "October", "Oct"]),
    ("11", ["11月", "十一月", "November", "Nov"]),
    ("12", ["12月", "十二月", "December", "Dec"]),
]
_QUARTER_NAMES = [
    ("1", ["Q1", "第一季度", "一季度"]),
    ("2", ["Q2", "第二季度", "二季度"]),
    ("3", ["Q3", "第三季度", "三季度"]),
    ("4", ["Q4", "第四季度", "四季度"]),
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _any_match(patterns: list[re.Pattern[str]], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _unfinished_period_tokens(as_of: str | None, unfinished_periods: list[str] | None) -> list[str]:
    if unfinished_periods:
        return [str(p) for p in unfinished_periods]
    month = None
    quarter = None
    if as_of:
        match = re.match(r"(\d{4})-(\d{1,2})", str(as_of))
        if match:
            month = int(match.group(2))
            quarter = (month - 1) // 3 + 1
    else:
        today = date.today()
        month = today.month
        quarter = (today.month - 1) // 3 + 1
    tokens: list[str] = []
    if month:
        for num, names in _MONTH_NAMES:
            if int(num) == month:
                tokens.extend(names)
    if quarter:
        for num, names in _QUARTER_NAMES:
            if int(num) == quarter:
                tokens.extend(names)
    return tokens


def _contains_period_token(sentence: str, token: str) -> bool:
    if re.search(r"[A-Za-z]", token):
        return re.search(rf"\b{re.escape(token)}\b", sentence, re.IGNORECASE) is not None
    # CJK / numeric tokens: ignore whitespace inside the sentence
    # ("10 月" is the same period as "10月").
    squashed = re.sub(r"\s+", "", sentence)
    return token in squashed


def _claim_texts(claims: Any) -> list[dict[str, Any]]:
    """Normalise claims to [{text, source}]."""
    out: list[dict[str, Any]] = []
    if claims is None:
        return out
    if isinstance(claims, dict):
        claims = [claims]
    if not isinstance(claims, list):
        raise CapabilityError("qa.facts_discipline: claims must be a list of objects or strings")
    for entry in claims:
        if isinstance(entry, str):
            out.append({"text": entry, "source": None})
        elif isinstance(entry, dict):
            text = entry.get("text", entry.get("claim", entry.get("statement", "")))
            if not isinstance(text, str):
                raise CapabilityError(f"qa.facts_discipline: claim needs text, got {entry!r}")
            out.append({"text": text, "source": entry.get("source")})
        else:
            raise CapabilityError(f"qa.facts_discipline: claim must be a string or object, got {entry!r}")
    return out


def check_facts(
    lines: list[str] | None = None,
    claims: list[Any] | dict[str, Any] | None = None,
    *,
    as_of: str | None = None,
    unfinished_periods: list[str] | None = None,
) -> dict[str, Any]:
    """Apply the three screen-wording rules plus the source warning."""
    if lines is None:
        lines = []
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise CapabilityError("qa.facts_discipline: lines must be a list of strings")
    claim_entries = _claim_texts(claims)
    period_tokens = _unfinished_period_tokens(as_of, unfinished_periods)

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    texts = [(line, "line") for line in lines] + [
        (entry["text"], "claim") for entry in claim_entries
    ]
    for text, kind in texts:
        for sentence in _sentences(text):
            if _any_match(_MOVEMENT_RES, sentence) and not _any_match(_SETTLED_RES, sentence) \
                    and _NUMBER_RE.search(sentence):
                failures.append({
                    "rule": "moving_counter_no_value_label",
                    "kind": kind,
                    "sentence": sentence,
                    "detail": "counter/number is described as moving and the same "
                              "sentence carries a concrete value label",
                })
            if _any_match(_THIS_PERIOD_RES, sentence) or any(
                _contains_period_token(sentence, token) for token in period_tokens
            ):
                if not _any_match(_TO_DATE_RES, sentence):
                    failures.append({
                        "rule": "unfinished_period_needs_to_date",
                        "kind": kind,
                        "sentence": sentence,
                        "detail": "unfinished month/quarter without a to-date "
                                 "or as-of marker",
                    })
            if _any_match(_TIMING_RES, sentence) and _any_match(_CAUSE_RES, sentence) \
                    and not _any_match(_EVIDENCE_RES, sentence):
                failures.append({
                    "rule": "timing_not_cause",
                    "kind": kind,
                    "sentence": sentence,
                    "detail": "timing/event wording is written as a cause "
                             "with no causal evidence marker",
                })
    for entry in claim_entries:
        if _NUMBER_RE.search(entry["text"]) \
                and not (isinstance(entry.get("source"), str) and entry["source"].strip()) \
                and not _any_match(_ILLUSTRATIVE_RES, entry["text"]):
            warnings.append({
                "rule": "number_needs_source_or_illustrative",
                "sentence": entry["text"],
                "detail": "number has no source and is not marked illustrative",
            })
    verdict = "fail" if failures else "pass"
    return {
        "capability": "qa.facts_discipline",
        "verdict": verdict,
        "failures": failures,
        "warnings": warnings,
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "checked_lines": len(lines),
        "checked_claims": len(claim_entries),
        "unfinished_period_tokens": period_tokens,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if params.get("as_of") is not None:
        kwargs["as_of"] = str(params["as_of"])
    if params.get("unfinished_periods") is not None:
        kwargs["unfinished_periods"] = [str(p) for p in params["unfinished_periods"]]
    report = check_facts(
        params.get("lines", []), params.get("claims", []), **kwargs
    )
    report_path = out_dir / "facts_discipline_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "failures": report["failures"],
            "warnings": report["warnings"],
        },
    )


def register_facts_discipline_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.facts_discipline",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "lines": {"type": "array", "items": {"type": "string"}},
                    "claims": {"type": "array"},
                    "as_of": {"type": "string"},
                    "unfinished_periods": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "On-screen facts wording: moving counters carry no "
                "value label, unfinished months/quarters need a "
                "to-date marker, timing is not written as cause, and "
                "numbers need a source or an illustrative marker. "
                "Complements production_gates/reference_teardown; it "
                "does not replace their sourcing checks."
            ),
            line="qa",
        )
    )
    return ["qa.facts_discipline"]


register_facts_discipline_capabilities_once()
