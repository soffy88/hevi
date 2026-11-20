"""Xiaoya persona finetune schema (``video.xiaoya_persona_finetune_schema``).

Fake-level contract for one persona finetune: whether its
weights are present and where, where its training data lives,
whether the cleaning step is applied, and — when the weights
are missing — which honest substitute stands in. The weights
are not on the server today, so a contract that claims them
present without a location, or a substitute claimed to equal
the finetune, is refused outright. The contract certifies the
shape of the plan only. It loads no weight file and runs no
model: every compiled contract declares ``executed_here:
false`` and ``output_file: None``.

Clean-room restatement of the finetune record found in the
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

SFT_DATA_LOCATIONS: frozenset[str] = frozenset({"drive", "local"})


def compile_xiaoya_persona_finetune(plan: Any) -> dict[str, Any]:
    """Compile one persona finetune contract.

    ``plan`` carries ``weights_present`` (a boolean),
    ``weights_location`` (required when the weights are
    present), ``sft_data_location`` (drive or local),
    ``clean_text`` (true), and, when the weights are missing,
    ``substitute`` (a ``model`` name plus ``claimed_equal``
    false). Raises :class:`CapabilityError` on any shape
    violation, on weights claimed present without a location,
    on a missing substitute when the weights are missing, or
    on a substitute ever claimed to equal the finetune. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("xiaoya persona finetune plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("finetune claims are refused here; this contract runs nothing")
    if plan.get("sft_data_location") not in SFT_DATA_LOCATIONS:
        raise CapabilityError("sft_data_location must be drive or local")
    if plan.get("clean_text") is not True:
        raise CapabilityError("clean_text must be applied before any reply is spoken")
    weights_present = plan.get("weights_present")
    if not isinstance(weights_present, bool):
        raise CapabilityError("weights_present must be declared true or false")
    if weights_present:
        location = plan.get("weights_location")
        if not isinstance(location, str) or not location.strip():
            raise CapabilityError("weights claimed present need a location on the server")
        mode = "finetune"
        finetune_active = True
        substitute_model = None
    else:
        substitute = plan.get("substitute")
        if not isinstance(substitute, dict):
            raise CapabilityError("the weights are missing and no substitute is declared")
        substitute_model = substitute.get("model")
        if not isinstance(substitute_model, str) or not substitute_model.strip():
            raise CapabilityError("the substitute must name its model")
        if substitute.get("claimed_equal") is not False:
            raise CapabilityError("a substitute is never claimed to equal the finetune")
        mode = "substitute"
        finetune_active = False
    return {
        "contract": "xiaoya-persona-finetune",
        "mode": mode,
        "finetune_active": finetune_active,
        "weights_present": weights_present,
        "sft_data_location": plan.get("sft_data_location"),
        "substitute_model": substitute_model,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_xiaoya_persona_finetune(params.get("plan"))
    contract_path = out_dir / "xiaoya_persona_finetune_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "mode": contract["mode"],
            "executed_here": False,
        },
    )


def register_xiaoya_persona_finetune_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.xiaoya_persona_finetune_schema",
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
                "xiaoya persona finetune contract (fake): weights "
                "presence and location, training data location, "
                "cleaning applied, honest substitute when weights "
                "are missing; shape only, never executed here."
            ),
        )
    )
    return ["video.xiaoya_persona_finetune_schema"]


__all__ = [
    "SFT_DATA_LOCATIONS",
    "compile_xiaoya_persona_finetune",
    "register_xiaoya_persona_finetune_schema_capabilities_once",
]
