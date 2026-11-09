"""Opening-hook self-check for copy / script nodes.

The check answers one question: in the first 2-3 seconds of copy, is there a
conflict, a question, or the strongest image?  It is deliberately structural:
it does not rewrite facts, and :func:`rewrite_opening` only replaces the first
sentence, keeping every later line byte-for-byte.

Applied at the shared script stage (``hevi.studio.stages.stage_script``), the
legacy ``generate_script_lines`` fallback, and the ai_drama script/beat stages.
A caller can turn the rewrite off with ``HEVI_HOOK_GATE=0``; the finding remains
in the report either way.
"""

from __future__ import annotations

import os
import re
from typing import Any

__all__ = ["check_hook", "enabled", "ensure_opening_hook", "rewrite_opening"]

# Generic openers spend the hook position on nothing.
_GENERIC = (
    "大家好", "今天我们来", "本期视频", "欢迎来到", "我是", "咱们今天",
    "今天聊聊", "今天，我们聊聊", "hello everyone", "welcome back", "today we",
)
# Conflict / reversal / suspense markers.
_CONFLICT = (
    "却", "但", "可", "反而", "没想到", "没想到", "竟", "竟然", "偏偏", "直到",
    "原来", "最后", "结果", "换来的", "等来", "翻车", "崩", "炸", "输给", "赢过",
    "她叫", "他叫", "这就是", "不对劲", "不是你想的那样", "没想到吧",
    "but", "however", "until", "instead", "surprised", "turned out",
)
_STRONG = ("最", "第一", "唯一", "罕见", "第一次", "最后一个", "最强的", "最强画面")
_TIME = re.compile(r"(?:18|19|20)\d{2}\s*年|\d{1,3}\s*岁|\d+\s*(?:天|年|个月|秒|分钟)")
_NUM = re.compile(r"\d+(?:\.\d+)?\s*(?:万|亿|千|百|人|个|次|年|岁|天|小时|分钟|秒|公里|km|元|%|％)?")
_SENTENCE = re.compile(r"(?<=[。！？!?；;])")

MAX_CHARS = 80


def enabled() -> bool:
    return os.environ.get("HEVI_HOOK_GATE", "1") not in {"0", "false", "False", "no"}


def _cn_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def check_hook(text: str, *, max_chars: int = MAX_CHARS) -> dict[str, Any]:
    """Return a deterministic verdict for the opening of ``text``.

    ``pass`` requires at least two independent signals and no generic preamble.
    ``needs_rewrite`` is True whenever the verdict fails; callers rewrite only
    the first sentence.
    """
    raw = (text or "").strip()
    opening = raw[:max_chars]
    issues: list[dict[str, str]] = []
    signals: list[str] = []
    score = 100
    if not raw:
        return {"pass": False, "needs_rewrite": True, "score": 0,
                "issues": [{"code": "empty", "detail": "空文案"}],
                "signals": [], "opening": ""}

    lowered = opening.lower()
    if any(token.lower() in lowered for token in _GENERIC):
        issues.append({"code": "generic_preamble",
                       "detail": "开头是通用寒暄/自我介绍，占用了前 2-3 秒"})
        score -= 30
    if _cn_len(opening) < 12:
        issues.append({"code": "too_short", "detail": "开头信息量不足（<12 字）"})
        score -= 15
    elif _cn_len(opening) > max_chars:
        issues.append({"code": "too_long", "detail": f"开头超过 {max_chars} 字，钩子被稀释"})
        score -= 10

    if _TIME.search(opening) or len(_NUM.findall(opening)) >= 2:
        signals.append("concrete_anchor")
    if any(token in opening for token in _CONFLICT):
        signals.append("conflict_or_reversal")
    if re.search(r"[？?]", opening):
        signals.append("question")
    if any(token in opening for token in _STRONG):
        signals.append("strongest_image")
    if "岁" in opening and len(_NUM.findall(opening)) >= 2:
        signals.append("age_progression")

    if "concrete_anchor" not in signals:
        issues.append({"code": "no_concrete_anchor",
                       "detail": "前 2-3 秒没有具体数字/时间锚点"})
        score -= 15
    if "conflict_or_reversal" not in signals and "question" not in signals:
        issues.append({"code": "no_conflict_or_question",
                       "detail": "前 2-3 秒没有冲突/悬念/提问"})
        score -= 20
    if "strongest_image" not in signals and "concrete_anchor" not in signals \
            and "conflict_or_reversal" not in signals:
        issues.append({"code": "no_strong_image",
                       "detail": "前 2-3 秒没有最强画面/最意外的一句"})
        score -= 15

    blocking = {"generic_preamble", "no_conflict_or_question"}
    passed = (
        len(signals) >= 2
        and not any(issue["code"] in blocking for issue in issues)
    )
    return {
        "pass": passed,
        "needs_rewrite": not passed,
        "score": max(0, score),
        "issues": issues,
        "signals": signals,
        "opening": opening,
    }


def _best_anchor(text: str) -> str:
    match = _TIME.search(text) or _NUM.search(text)
    return match.group(0).strip() if match else ""


def _first_sentence(text: str) -> tuple[str, str]:
    match = _SENTENCE.search(text)
    if not match:
        return text.strip(), ""
    end = match.end()
    return text[:end].strip(), text[end:].strip()


def rewrite_opening(text: str, *, topic: str = "", max_chars: int = MAX_CHARS) -> dict[str, Any]:
    """Replace only the first sentence; keep the rest untouched.

    No facts are invented.  The replacement is assembled from an anchor that
    already appears in the copy, or from the topic plus a suspense frame.  The
    returned ``opening`` is the new first sentence and ``text`` the full
    rewritten copy.
    """
    raw = (text or "").strip()
    if not raw:
        return {"changed": False, "opening": "", "text": raw}
    first, rest = _first_sentence(raw)
    topic = (topic or "").strip()
    anchor = _best_anchor(raw)
    # Keep an already-strong first sentence.
    current = check_hook(first, max_chars=max_chars)
    if current["pass"] and not any(i["code"] == "generic_preamble" for i in current["issues"]):
        return {"changed": False, "opening": first, "text": raw, "check": current}

    subject = topic or "这件事"
    if anchor:
        opening = f"{anchor}，{subject}最容易被忽略的转折就在这里。"
    else:
        later_conflict = next(
            (s for s in _SENTENCE.split(rest) if any(t in s for t in _CONFLICT)), ""
        ).strip()
        if later_conflict and _cn_len(later_conflict) <= max_chars:
            # Move an existing conflict sentence to the front without changing
            # its wording; remove it from its old position.
            rest = rest.replace(later_conflict, "", 1).strip()
            opening = later_conflict
        else:
            opening = f"{subject}最关键的一秒，为什么总被忽略？"
    new_text = f"{opening}{rest}" if rest else opening
    return {
        "changed": opening != first,
        "opening": opening,
        "text": new_text,
        "check": check_hook(opening, max_chars=max_chars),
    }


def ensure_opening_hook(
    text: str,
    *,
    topic: str = "",
    max_chars: int = MAX_CHARS,
    rewrite: bool | None = None,
) -> dict[str, Any]:
    """Check, then rewrite the opening only when the check fails."""
    check = check_hook(text, max_chars=max_chars)
    do_rewrite = enabled() if rewrite is None else rewrite
    report: dict[str, Any] = {"check": check, "rewritten": False}
    if check["pass"] or not do_rewrite:
        report["text"] = text
        return report
    rewritten = rewrite_opening(text, topic=topic, max_chars=max_chars)
    report.update({
        "text": rewritten["text"],
        "rewritten": rewritten["changed"],
        "new_opening": rewritten["opening"],
        "recheck": rewritten.get("check"),
    })
    return report
