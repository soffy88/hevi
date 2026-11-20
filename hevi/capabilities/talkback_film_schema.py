"""Recorded talkback film schema (``video.talkback_film_schema``).

Fake-level contract for one recorded talkback film: its five
steps in order, and whether a single fix rebuilds the film.
The contract certifies the shape of the plan only. It
generates no audio, renders no frame, and starts no stream:
every compiled contract declares ``executed_here: false`` and
``output_file: None``.

Clean-room restatement of the film plan described in the
Renoise talkback review (see
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

STEPS: tuple[str, ...] = ("persona", "frames", "talkback", "edit", "polish")


def compile_talkback_film(plan: Any) -> dict[str, Any]:
    """Compile one recorded talkback film contract.

    ``plan`` carries ``steps`` (all five steps true),
    ``step_order`` (persona, frames, talkback, edit, polish),
    and ``single_sentence_fix_rebuilds`` (which must be
    false). Raises :class:`CapabilityError` on any shape
    violation. The returned contract records that nothing was
    executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("talkback film plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("film claims are refused here; this contract renders nothing")
    steps = plan.get("steps")
    if not isinstance(steps, dict):
        raise CapabilityError("a five-step declaration is required")
    for step in STEPS:
        if steps.get(step) is not True:
            raise CapabilityError(f"step {step!r} is missing from the film plan")
    if plan.get("step_order") != list(STEPS):
        raise CapabilityError("the steps must run persona, frames, talkback, edit, polish")
    if plan.get("single_sentence_fix_rebuilds") is True:
        raise CapabilityError("a single fix must never rebuild the whole film")
    return {
        "contract": "talkback-film",
        "steps": list(STEPS),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_talkback_film(params.get("plan"))
    contract_path = out_dir / "talkback_film_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "steps": contract["steps"],
            "executed_here": False,
        },
    )


def register_talkback_film_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.talkback_film_schema",
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
                "recorded talkback film contract (fake): five steps "
                "in order, single fix never rebuilds the film; "
                "shape only, never executed here."
            ),
        )
    )
    return ["video.talkback_film_schema"]


__all__ = [
    "STEPS",
    "compile_talkback_film",
    "register_talkback_film_schema_capabilities_once",
]
