"""Xiaoya topic pool schema (``video.xiaoya_topic_pool_schema``).

Fake-level contract for one cold-field topic pool: its topics,
its size, its repeat rule, and whether it survives a
reconnect. The contract certifies the shape of the plan only.
It speaks no topic and starts no stream: every compiled
contract declares ``executed_here: false`` and
``output_file: None``.

Clean-room restatement of the topic pool found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``).
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

MIN_TOPICS = 100
REPEAT_RULE = "no_repeat_until_exhausted"


def compile_xiaoya_topic_pool(plan: Any) -> dict[str, Any]:
    """Compile one topic pool contract.

    ``plan`` carries ``topics`` (a non-empty list of
    non-empty strings), ``count`` (equal to the list length),
    ``repeat_rule`` (no_repeat_until_exhausted), and
    ``survives_reconnect`` (true). Raises
    :class:`CapabilityError` on any shape violation. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("xiaoya topic pool plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("pool claims are refused here; this contract speaks nothing")
    topics = plan.get("topics")
    if (
        not isinstance(topics, list)
        or not topics
        or any(not isinstance(t, str) or not t.strip() for t in topics)
    ):
        raise CapabilityError("topics must be a non-empty list of non-empty strings")
    if len(topics) < MIN_TOPICS:
        raise CapabilityError(f"the pool needs at least {MIN_TOPICS} topics; got {len(topics)}")
    if plan.get("count") != len(topics):
        raise CapabilityError("count must equal the number of topics")
    if plan.get("repeat_rule") != REPEAT_RULE:
        raise CapabilityError("repeat_rule must be no_repeat_until_exhausted")
    if plan.get("survives_reconnect") is not True:
        raise CapabilityError("the pool must survive a reconnect")
    return {
        "contract": "xiaoya-topic-pool",
        "topic_count": len(topics),
        "repeat_rule": REPEAT_RULE,
        "survives_reconnect": True,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_xiaoya_topic_pool(params.get("plan"))
    contract_path = out_dir / "xiaoya_topic_pool_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "topic_count": contract["topic_count"],
            "executed_here": False,
        },
    )


def register_xiaoya_topic_pool_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.xiaoya_topic_pool_schema",
            kind="video",
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
            layer="obase",
            line="video",
            description=(
                "xiaoya topic pool contract (fake): topics, count, "
                "no-repeat-until-exhausted rule, survives reconnect; "
                "shape only, never executed here."
            ),
        )
    )
    return ["video.xiaoya_topic_pool_schema"]


__all__ = [
    "MIN_TOPICS",
    "REPEAT_RULE",
    "compile_xiaoya_topic_pool",
    "register_xiaoya_topic_pool_schema_capabilities_once",
]
