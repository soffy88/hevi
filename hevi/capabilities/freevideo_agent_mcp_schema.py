"""FreeVideo agent/MCP contract schema (``video.freevideo_agent_mcp_schema``).

Contract-only schema for one FreeVideo agent/MCP wiring:
the agent name, the MCP server, the plan-before-run
declaration, the H3 six sections in order, and the declared
cost. Clean-room restatement of the FlashML-org/FreeVideo
method (see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code
appears in this schema. The agent runs on the user's own
paid account — the cost is declared here, never hidden.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed contract, and raises
``CapabilityError`` on any shape violation. Real execution
needs a separate Python 3.12 + FreeVideo runtime
environment and is a separate work item.
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
from hevi.capabilities.scene_reference import H3_SECTIONS

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent_name": {"type": "string", "minLength": 1},
        "mcp_server": {"type": "string", "minLength": 1},
        "plan_before_run": {"type": "boolean"},
        "six_sections": {"type": "array"},
        "cost": {"type": "object"},
    },
    "required": ["agent_name", "mcp_server", "plan_before_run", "six_sections", "cost"],
    "additionalProperties": False,
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compile_freevideo_agent_mcp(contract: Any) -> dict[str, Any]:
    """Compile one FreeVideo agent/MCP wiring contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed wiring.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the wiring only; it
    renders nothing and executes nothing.
    """
    if not isinstance(contract, dict):
        raise CapabilityError("freevideo_agent_mcp: contract must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in contract:
            raise CapabilityError(f"freevideo_agent_mcp: missing required field {key!r}")
    extra = sorted(set(contract) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("freevideo_agent_mcp: unknown fields: " + ", ".join(extra))
    if contract["plan_before_run"] is not True:
        raise CapabilityError("freevideo_agent_mcp: plan_before_run must be true")
    if contract["six_sections"] != list(H3_SECTIONS):
        raise CapabilityError(
            "freevideo_agent_mcp: six_sections must be exactly the H3 six in order: "
            + ", ".join(H3_SECTIONS)
        )
    cost = contract["cost"]
    if not isinstance(cost, dict):
        raise CapabilityError("freevideo_agent_mcp: cost must be an object")
    for key in ("model", "max_tokens", "estimated_cost_usd"):
        if key not in cost:
            raise CapabilityError(f"freevideo_agent_mcp: cost must carry {key!r}")
    if not isinstance(cost["model"], str) or not cost["model"]:
        raise CapabilityError("freevideo_agent_mcp: cost.model must be a non-empty string")
    if not isinstance(cost["max_tokens"], int) or isinstance(cost["max_tokens"], bool):
        raise CapabilityError("freevideo_agent_mcp: cost.max_tokens must be an integer")
    if cost["max_tokens"] <= 0:
        raise CapabilityError("freevideo_agent_mcp: cost.max_tokens must be positive")
    if not _is_number(cost["estimated_cost_usd"]) or cost["estimated_cost_usd"] < 0:
        raise CapabilityError(
            "freevideo_agent_mcp: cost.estimated_cost_usd must be a non-negative number"
        )
    return {
        "contract": "freevideo-agent-mcp",
        "agent_name": contract["agent_name"],
        "mcp_server": contract["mcp_server"],
        "model": cost["model"],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_freevideo_agent_mcp(params.get("contract"))
    contract_path = out_dir / "freevideo_agent_mcp_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "agent_name": contract["agent_name"],
            "executed_here": False,
        },
    )


def register_freevideo_agent_mcp_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.freevideo_agent_mcp_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "contract": {"type": "object"},
                },
                "required": ["contract"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="video",
            description=(
                "FreeVideo agent/MCP contract (fake): agent name, MCP "
                "server, plan-before-run, H3 six sections in order, "
                "declared cost; shape only, never executed here."
            ),
        )
    )
    return ["video.freevideo_agent_mcp_schema"]


__all__ = [
    "SCHEMA",
    "compile_freevideo_agent_mcp",
    "register_freevideo_agent_mcp_schema_capabilities_once",
]
