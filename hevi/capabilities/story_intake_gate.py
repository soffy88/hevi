"""Five-item story intake gate (``qa.story_intake_gate``).

Clean-room rewrite of the method in ``hevi-vs-rain-before-stops.md``
item A1 (from the ``<雨停之前>`` field notes): before any paid
generation, a one-page story proposal must state five things --
who is watching (``audience``), what the protagonist wants
(``protagonist_goal``), what stops them (``obstacle``), the mood of
the episode (``mood``), and the question the ending leaves the
audience asking (``closing_question``). It must also say which
information is carried by the picture and which must be spoken
(``expression_split``: ``visual`` / ``dialogue`` lists), so a
story is never "all told, nothing shown".

Adjective stripping: a proposal whose one-sentence story and
opening anomaly survive only on adjectives ("悬疑", "电影感",
"高级" and the like) -- with no concrete event naming a person,
place or object doing something -- fails with
``adjective_only_story``. The check is a heuristic, not a literary
judgement: callers may supply ``concrete_elements`` (names that
count as concrete) and the concrete-verb list is fixed and
documented below. An adjective-heavy proposal that still names a
concrete event passes; the gate only refuses stories with nothing
concrete left once the adjectives are peeled off.

This module judges proposals only. It never generates, never calls
a model, never touches a budget.
"""

from __future__ import annotations

import json
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

REQUIRED_FIELDS = (
    "audience",
    "protagonist_goal",
    "obstacle",
    "mood",
    "closing_question",
)

# Vague adjectives that must not be the whole story. Peeling these
# off must still leave a concrete event behind.
_VAGUE_ADJECTIVES = (
    "悬疑", "电影感", "高级", "高级感", "震撼", "史诗感", "大片感",
    "氛围感", "质感", "高级的", "悬疑的", "神秘", "烧脑",
)

# Concrete verbs: something happens. A story that names one of
# these, applied to a named person/place/object, is concrete.
_CONCRETE_VERBS = (
    "发现", "捡到", "推开", "遇见", "收到", "走进", "打开", "听到",
    "看见", "写", "落款", "变回", "停", "追问", "离开", "回来",
    "敲", "响", "亮", "熄", "落", "走", "跑", "藏", "找",
)


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.story_intake_gate: {detail}"}
    issue.update(extra)
    return issue


def _strip_adjectives(text: str) -> str:
    stripped = text
    for adjective in _VAGUE_ADJECTIVES:
        stripped = stripped.replace(adjective, "")
    return stripped.strip("，。、；：！？ \t")


# Built-in concrete nouns, used when the caller supplies no
# ``concrete_elements`` list; a caller list augments (never replaces)
# this list, so a plain concrete sentence passes without extra input.
_CONCRETE_NOUNS = (
    "女孩", "男孩", "书店", "信", "街道", "门", "窗", "人", "灯",
    "雨", "柜台", "挂钟", "伞", "铜铃", "店主", "小城", "房间",
    "车", "桥", "河", "老人", "孩子", "医生", "老师", "学生",
)


def _has_concrete_event(text: str, concrete_elements: Any) -> bool:
    """True when the text names a concrete event after adjectives are peeled."""
    stripped = _strip_adjectives(text)
    if len(stripped) < 4:
        return False
    has_verb = any(verb in stripped for verb in _CONCRETE_VERBS)
    elements = list(_CONCRETE_NOUNS)
    if isinstance(concrete_elements, list):
        elements.extend(
            element for element in concrete_elements
            if isinstance(element, str) and element
        )
    has_element = any(element in stripped for element in elements)
    return has_verb and has_element


def check_story_intake(proposal: Any) -> dict[str, Any]:
    """Judge one story proposal. Returns a report; never raises for a bad proposal."""
    issues: list[dict[str, Any]] = []
    if not isinstance(proposal, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("proposal_not_object", "story proposal must be an object")],
        }
    for field in REQUIRED_FIELDS:
        value = proposal.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(_issue(
                "missing_field",
                f"field {field!r} is required and must be a non-empty string",
                field=field,
            ))
    split = proposal.get("expression_split")
    if not isinstance(split, dict):
        issues.append(_issue(
            "missing_expression_split",
            "expression_split must be an object with visual and dialogue lists",
        ))
    else:
        for side in ("visual", "dialogue"):
            entries = split.get(side)
            if not isinstance(entries, list) or not entries or not all(
                isinstance(entry, str) and entry.strip() for entry in entries
            ):
                issues.append(_issue(
                    "missing_expression_split",
                    f"expression_split.{side} must be a non-empty list of strings",
                    side=side,
                ))
    one_sentence = proposal.get("one_sentence")
    anomaly = proposal.get("opening_anomaly")
    core_texts = [
        text for text in (one_sentence, anomaly)
        if isinstance(text, str) and text.strip()
    ]
    if isinstance(one_sentence, str) and not one_sentence.strip():
        issues.append(_issue(
            "missing_field", "field 'one_sentence' must be a non-empty string",
            field="one_sentence",
        ))
    if isinstance(anomaly, str) and not anomaly.strip():
        issues.append(_issue(
            "missing_field", "field 'opening_anomaly' must be a non-empty string",
            field="opening_anomaly",
        ))
    if one_sentence is not None and not isinstance(one_sentence, str):
        issues.append(_issue(
            "missing_field", "field 'one_sentence' must be a string",
            field="one_sentence",
        ))
    if anomaly is not None and not isinstance(anomaly, str):
        issues.append(_issue(
            "missing_field", "field 'opening_anomaly' must be a string",
            field="opening_anomaly",
        ))
    if core_texts and not issues:
        elements = proposal.get("concrete_elements", [])
        if not any(_has_concrete_event(text, elements) for text in core_texts):
            issues.append(_issue(
                "adjective_only_story",
                "after peeling vague adjectives, no concrete event remains: "
                "name a person/place/object doing something concrete",
            ))
    return {
        "ok": not issues,
        "verdict": "pass" if not issues else "fail",
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = check_story_intake(params.get("proposal"))
    if not isinstance(params.get("proposal"), dict):
        raise CapabilityError("qa.story_intake_gate: params.proposal must be an object")
    report_path = Path(out_dir) / "story_intake_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_story_intake_gate_capabilities_once() -> list[str]:
    """Register ``qa.story_intake_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.story_intake_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "proposal": {"type": "object"},
                },
                "required": ["proposal"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Story intake gate: a one-page proposal must state "
                "audience, protagonist goal, obstacle, mood and "
                "closing question, plus a visual-vs-dialogue split; "
                "a story carried only by vague adjectives fails. "
                "Judges proposals only; no generation, no keys."
            ),
            line="qa",
        )
    )
    return ["qa.story_intake_gate"]


register_story_intake_gate_capabilities_once()
