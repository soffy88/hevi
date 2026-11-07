"""Single-issue feedback discipline (``qa.feedback_discipline``).

Clean-room rewrite of the *feedback format* discipline of the
3D cartoon tutorial (see CARTOON_TUTORIAL_ATTRIBUTION.md): a
revision request is only actionable when every item names a
timestamp, a part, and the expected state. Vague feedback such
as "it looks bad, fix it" is not a request this gate can pass.

Rules, all judged on the feedback record only -- this gate
never modifies a film, a frame or a timeline:

* Every item must carry all three elements: a timestamp
  (``at_sec``, a ``timestamp`` string, or a ``frame`` number),
  a ``part`` (what is wrong), and an ``expected`` state (what
  it should look like instead). One missing element fails the
  whole round, naming the item.
* At most two items per round (``MAX_ITEMS_PER_ROUND = 2``).
  A third item fails the round: fix one or two things, then
  re-review, instead of rewriting the whole shot at once.
* Everything not mentioned is frozen. When the caller
  supplies a ``scope`` list, the report names the frozen
  items explicitly; without a scope the report says the
  frozen set is undeclared rather than inventing one.

This gate judges feedback itself. It sits after
``qa.critic_review`` and does not repeat the critic's nine
axes: a review may score well and still produce unactionable
feedback, and that is what fails here.
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

MAX_ITEMS_PER_ROUND = 2

_TIMESTAMP_RE = re.compile(
    r"^\s*(?:(\d+):(\d{2}(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*s?)\s*$",
    re.IGNORECASE,
)


def _parse_timestamp(item: dict[str, Any]) -> float | None:
    """Return the item's time in seconds, or None if it has none."""
    at_sec = item.get("at_sec")
    if isinstance(at_sec, (int, float)) and not isinstance(at_sec, bool):
        return float(at_sec)
    timestamp = item.get("timestamp")
    if isinstance(timestamp, str):
        match = _TIMESTAMP_RE.match(timestamp)
        if match:
            if match.group(1) is not None:
                return float(match.group(1)) * 60.0 + float(match.group(2))
            return float(match.group(3))
    frame = item.get("frame")
    if isinstance(frame, int) and not isinstance(frame, bool):
        # A frame number is timestamp evidence even without an fps:
        # the gate records that a frame was cited, not a second.
        return None
    return None


def _has_timestamp(item: dict[str, Any]) -> bool:
    if isinstance(item.get("at_sec"), (int, float)) and not isinstance(
        item.get("at_sec"), bool
    ):
        return True
    timestamp = item.get("timestamp")
    if isinstance(timestamp, str) and _TIMESTAMP_RE.match(timestamp):
        return True
    frame = item.get("frame")
    return isinstance(frame, int) and not isinstance(frame, bool)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_feedback(feedback: Any) -> dict[str, Any]:
    """Judge one feedback round. Structural errors raise; content failures fail."""
    if not isinstance(feedback, dict):
        raise CapabilityError(
            "qa.feedback_discipline: feedback must be a JSON object"
        )
    items_raw = feedback.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise CapabilityError(
            "qa.feedback_discipline: feedback.items must be a non-empty list"
        )
    problems: list[str] = []
    mentioned_parts: list[str] = []
    checked_items: list[dict[str, Any]] = []
    for index, raw in enumerate(items_raw):
        if not isinstance(raw, dict):
            problems.append(f"item {index}: must be a JSON object")
            continue
        missing: list[str] = []
        if not _has_timestamp(raw):
            missing.append("timestamp (at_sec, timestamp or frame)")
        part = raw.get("part")
        if not _nonempty_str(part):
            missing.append("part")
        expected = raw.get("expected")
        if not _nonempty_str(expected):
            missing.append("expected")
        if missing:
            problems.append(
                f"item {index}: missing feedback element(s): "
                + ", ".join(missing)
            )
        at_sec = _parse_timestamp(raw)
        checked_items.append(
            {
                "index": index,
                "at_sec": at_sec,
                "frame": raw.get("frame") if isinstance(raw.get("frame"), int) else None,
                "part": part.strip() if _nonempty_str(part) else part,
                "expected": expected.strip() if _nonempty_str(expected) else expected,
            }
        )
        if _nonempty_str(part):
            mentioned_parts.append(part.strip())
    if len(items_raw) > MAX_ITEMS_PER_ROUND:
        problems.append(
            f"items: {len(items_raw)} change(s) in one round exceeds the "
            f"limit of {MAX_ITEMS_PER_ROUND}; split the round and re-review"
        )
    scope = feedback.get("scope")
    frozen_items: list[str] = []
    scope_undeclared = False
    if scope is None:
        scope_undeclared = True
    elif isinstance(scope, list):
        for entry in scope:
            if isinstance(entry, str) and entry.strip() not in mentioned_parts:
                frozen_items.append(entry.strip())
    else:
        problems.append("scope: must be a list of part names when present")
    return {
        "ok": not problems,
        "problems": problems,
        "item_count": len(items_raw),
        "max_items_per_round": MAX_ITEMS_PER_ROUND,
        "items": checked_items,
        "mentioned_parts": mentioned_parts,
        "frozen_items": frozen_items,
        "scope_undeclared": scope_undeclared,
        "frozen_rule": (
            "every part not mentioned in this round is frozen; "
            "frozen items are listed in frozen_items"
        ),
    }


def check_feedback_discipline(feedback: Any) -> dict[str, Any]:
    """Alias kept for the capability name; same contract as check_feedback."""
    return check_feedback(feedback)


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    report = check_feedback(params.get("feedback"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "feedback_discipline_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "pass": report["ok"],
            "item_count": report["item_count"],
        },
    )


def register_feedback_discipline_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.feedback_discipline",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"feedback": {"type": "object"}},
                "required": ["feedback"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Single-issue feedback discipline: every feedback item "
                "must name a timestamp, a part and the expected state; "
                "at most two changes per round; unmentioned parts are "
                "listed as frozen. Judges feedback only, never a film."
            ),
            line="qa",
        )
    )
    return ["qa.feedback_discipline"]


register_feedback_discipline_capabilities_once()
