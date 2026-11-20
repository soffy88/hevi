"""Xiaoya danmaku route schema (``video.xiaoya_danmaku_route_schema``).

Fake-level contract for one danmaku routing table: the five
filter categories, the allowlist, the four routes, and the
queue policy the table feeds. The contract certifies the
shape of the plan only. It reads no live feed, connects to no
platform, and touches no gift or payment: every compiled
contract declares ``executed_here: false`` and
``output_file: None``.

Clean-room restatement of the routing table found in the
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

FILTER_CATEGORIES: frozenset[str] = frozenset(
    {"低俗擦边", "引流广告", "敏感话题", "辱骂", "收益承诺"}
)
ROUTES: frozenset[str] = frozenset({"chat", "wardrobe", "action", "restore"})
POLICIES: frozenset[str] = frozenset({"fifo", "gift_first_fifo", "gift_first_random"})


def compile_xiaoya_danmaku_route(plan: Any) -> dict[str, Any]:
    """Compile one danmaku routing contract.

    ``plan`` carries ``filter_categories`` (all five),
    ``allow_phrases`` (a non-empty list), ``routes`` (all
    four), and ``policy`` (one of the three queue policies).
    Raises :class:`CapabilityError` on any shape violation.
    The returned contract records that nothing was executed
    here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("xiaoya danmaku route plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("route claims are refused here; this contract reads nothing")
    categories = plan.get("filter_categories")
    if not isinstance(categories, list) or not set(categories) >= FILTER_CATEGORIES:
        missing = sorted(FILTER_CATEGORIES - set(categories or []))
        raise CapabilityError(f"all five filter categories are required; missing {missing}")
    allow_phrases = plan.get("allow_phrases")
    if (
        not isinstance(allow_phrases, list)
        or not allow_phrases
        or any(not isinstance(p, str) or not p for p in allow_phrases)
    ):
        raise CapabilityError("a non-empty allowlist is required")
    routes = plan.get("routes")
    if not isinstance(routes, list) or not set(routes) >= ROUTES:
        missing = sorted(ROUTES - set(routes or []))
        raise CapabilityError(f"all four routes are required; missing {missing}")
    policy = plan.get("policy")
    if policy not in POLICIES:
        raise CapabilityError("policy must be fifo, gift_first_fifo, or gift_first_random")
    return {
        "contract": "xiaoya-danmaku-route",
        "filter_categories": sorted(FILTER_CATEGORIES),
        "allow_phrase_count": len(allow_phrases),
        "routes": sorted(ROUTES),
        "policy": policy,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_xiaoya_danmaku_route(params.get("plan"))
    contract_path = out_dir / "xiaoya_danmaku_route_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "policy": contract["policy"],
            "executed_here": False,
        },
    )


def register_xiaoya_danmaku_route_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.xiaoya_danmaku_route_schema",
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
                "xiaoya danmaku route contract (fake): five filter "
                "categories, allowlist, four routes, queue policy; "
                "shape only, never executed here."
            ),
        )
    )
    return ["video.xiaoya_danmaku_route_schema"]


__all__ = [
    "FILTER_CATEGORIES",
    "POLICIES",
    "ROUTES",
    "compile_xiaoya_danmaku_route",
    "register_xiaoya_danmaku_route_schema_capabilities_once",
]
