"""Word-anchor gate (``qa.word_anchor_gate``).

Discipline gate only. In a word-anchored timeline, pictures,
effects, captions, and sounds attach to named anchors that
bind word boundaries in the spoken lines -- never to hand-written
second counts. A plan passes only when every anchor has a name,
binds one or more words that actually occur in its line, carries
at least one attachment, and the plan declares that changing a
line re-projects the timeline instead of re-cutting it by hand.
Any numeric time field on an anchor or attachment (a second
anchor mixed into a word-anchored plan) fails. This gate judges
the plan only, aligns nothing, and renders nothing. See
HYPIT_ATTRIBUTION.md. Method restated in our own words; no
upstream DSL text or example script is copied here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_ATTACHMENT_KINDS = frozenset({"broll", "effect", "caption", "sound"})

# Numeric time fields: a word-anchored plan must not carry them.
_TIME_FIELDS = frozenset(
    {"start_s", "end_s", "time_s", "start_time", "end_time", "timecode", "timestamp"}
)

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _line_words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _words_occur(words: list[str], text: str) -> bool:
    """True when the word sequence occurs consecutively in the line."""
    tokens = _line_words(text)
    wanted = [w.lower() for w in words]
    if not wanted:
        return False
    width = len(wanted)
    return any(tokens[i : i + width] == wanted for i in range(len(tokens) - width + 1))


def check_word_anchor(plan: Any) -> dict[str, Any]:
    """Check a word-anchored timeline plan.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. Unnamed anchors, anchors bound to words
    that do not occur in their line, anchors without
    attachments, hand-written time fields, and a missing
    re-projection declaration all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
        }
    script = plan.get("script")
    if not isinstance(script, list) or not script:
        issues.append(_issue("script_missing", "plan must declare a non-empty script list"))
        script = script if isinstance(script, list) else []
    for line_index, line in enumerate(script):
        where = f"script[{line_index}]"
        if not isinstance(line, dict):
            issues.append(_issue(f"{where}:not_object", "each script line must be an object"))
            continue
        text = line.get("text")
        if not isinstance(text, str) or not text.strip():
            issues.append(_issue(f"{where}:text_missing", "each script line needs non-empty text"))
            text = text if isinstance(text, str) else ""
        anchors = line.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            issues.append(
                _issue(f"{where}:anchors_missing", "each script line needs at least one anchor")
            )
            continue
        for anchor_index, anchor in enumerate(anchors):
            awhere = f"{where}.anchors[{anchor_index}]"
            if not isinstance(anchor, dict):
                issues.append(_issue(f"{awhere}:not_object", "each anchor must be an object"))
                continue
            name = anchor.get("name")
            if not isinstance(name, str) or not name.strip():
                issues.append(
                    _issue(f"{awhere}:name_missing", "each anchor needs a non-empty name")
                )
            words = anchor.get("words")
            if (
                not isinstance(words, list)
                or not words
                or any(not isinstance(w, str) or not w.strip() for w in words)
            ):
                issues.append(
                    _issue(
                        f"{awhere}:words_missing",
                        "each anchor must bind a non-empty list of words",
                    )
                )
            elif text and not _words_occur(words, text):
                issues.append(
                    _issue(
                        f"{awhere}:words_not_in_line",
                        "anchor words must occur in the line text",
                    )
                )
            attachments = anchor.get("attachments")
            if not isinstance(attachments, list) or not attachments:
                issues.append(
                    _issue(
                        f"{awhere}:attachments_missing",
                        "each anchor needs at least one attachment",
                    )
                )
            else:
                for att_index, attachment in enumerate(attachments):
                    atwhere = f"{awhere}.attachments[{att_index}]"
                    if not isinstance(attachment, dict):
                        issues.append(
                            _issue(f"{atwhere}:not_object", "each attachment must be an object")
                        )
                        continue
                    kind = attachment.get("kind")
                    if kind not in _ATTACHMENT_KINDS:
                        issues.append(
                            _issue(
                                f"{atwhere}:kind_unknown",
                                "attachment kind must be one of broll, effect, caption, sound",
                            )
                        )
                    issues.extend(
                        _issue(
                            f"{atwhere}:time_field:{field}",
                            "word-anchored attachments must not carry hand-written time fields",
                        )
                        for field in sorted(_TIME_FIELDS & set(attachment))
                    )
            issues.extend(
                _issue(
                    f"{awhere}:time_field:{field}",
                    "word-anchored anchors must not carry hand-written time fields",
                )
                for field in sorted(_TIME_FIELDS & set(anchor))
            )
    if plan.get("reprojection_declared") is not True:
        issues.append(
            _issue(
                "reprojection_undeclared",
                "plan must declare that changing a line re-projects the timeline",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_word_anchor(params.get("plan"))
    report_path = out_dir / "word_anchor.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_word_anchor_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.word_anchor_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Word-anchor gate (discipline only): attachments bind "
                "named word boundaries, never hand-written seconds; "
                "line changes must re-project the timeline."
            ),
        )
    )
    return ["qa.word_anchor_gate"]


__all__ = [
    "check_word_anchor",
    "register_word_anchor_gate_capabilities_once",
]
