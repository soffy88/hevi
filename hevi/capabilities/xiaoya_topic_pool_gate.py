"""Xiaoya topic pool gate (``qa.xiaoya_topic_pool_gate``).

When the room goes quiet the host fills the silence from a
cold-field topic pool: the branch under review keeps 105
hand-written topics. The pool is dealt one round at a time
and only repeats after a full round is spoken, and it survives
a disconnect: a reconnect does not reset it to the top.

Clean-room restatement of the method found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``). This gate judges
the shape of a topic pool declaration only; it never speaks a
topic and never starts a stream.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Minimum pool size. The measured pool holds 105 topics; the
# bar is set at 100 so the measured pool passes with room.
MIN_TOPICS = 100
MEASURED_TOPIC_COUNT = 105

# The only repeat rule: one full round before any repeat.
REPEAT_RULE = "no_repeat_until_exhausted"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_xiaoya_topic_pool(pool: Any) -> dict[str, Any]:
    """Validate a cold-field topic pool declaration.

    Verdicts are ``pass`` / ``fail`` only. The pool fails when
    it is not an object, when its topic list is missing or
    holds an empty or non-string entry, when it holds fewer
    than 100 topics, when its repeat rule is not
    no-repeat-until-exhausted, or when it resets on reconnect.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(pool, dict):
        return fail("pool_not_object", "pool must be a JSON object")
    topics = pool.get("topics")
    if (
        not isinstance(topics, list)
        or not topics
        or any(not isinstance(t, str) or not t.strip() for t in topics)
    ):
        return fail(
            "topics_invalid",
            "topics must be a non-empty list of non-empty strings",
        )
    if len(topics) < MIN_TOPICS:
        return fail(
            "topic_pool_too_small",
            f"the pool needs at least {MIN_TOPICS} topics "
            f"(measured {MEASURED_TOPIC_COUNT}); got {len(topics)}",
        )
    if pool.get("repeat_rule") != REPEAT_RULE:
        return fail(
            "repeat_rule_wrong",
            "the repeat rule must be no_repeat_until_exhausted: one full round before any repeat",
        )
    if pool.get("survives_reconnect") is not True:
        return fail(
            "pool_resets_on_reconnect",
            "the pool must survive a reconnect, never reset to the top",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "topic_count": len(topics),
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_xiaoya_topic_pool(params.get("pool"))
    report_path = out_dir / "xiaoya_topic_pool_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_xiaoya_topic_pool_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.xiaoya_topic_pool_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "pool": {"type": "object"},
                },
                "required": ["pool"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "xiaoya topic pool gate: at least 100 topics, "
                "no repeat until a full round is spoken, pool "
                "survives a reconnect."
            ),
        )
    )
    return ["qa.xiaoya_topic_pool_gate"]


__all__ = [
    "MEASURED_TOPIC_COUNT",
    "MIN_TOPICS",
    "REPEAT_RULE",
    "check_xiaoya_topic_pool",
    "register_xiaoya_topic_pool_gate_capabilities_once",
]
