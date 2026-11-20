"""Character recipe contract schema (``video.pose_character_recipe_schema``).

Contract-only schema for one three-in-one character
recipe: its id, the portrait, costume, and pose slots, the
Chinese structured prompt, the separation rule, and the
provider. Clean-room restatement of the
anhao/ai-pose-gallery-zh workbench recipe method (see
``AI_POSE_GALLERY_ZH_ATTRIBUTION.md``); no upstream code,
image, or data appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed recipe, and raises
``CapabilityError`` on any shape violation. Composition
itself stays with ``image.multi_ref_compose``; the contract
carries the compiled multi-ref input shape alongside the
recipe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.pose_character_recipe_gate import (
    check_pose_character_recipe,
    recipe_to_multi_ref,
)
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recipe_id": {"type": "string", "minLength": 1},
        "portrait_ref": {"type": "object"},
        "costume_ref": {"type": "object"},
        "pose_ref": {"type": "object"},
        "prompt_zh": {"type": "string", "minLength": 1},
        "separation_rule": {"type": "string", "minLength": 1},
        "provider": {"type": "string"},
        "extra_refs": {"type": "array"},
        "max_refs": {"type": "integer"},
    },
    "required": [
        "recipe_id",
        "portrait_ref",
        "costume_ref",
        "pose_ref",
        "prompt_zh",
        "separation_rule",
        "provider",
    ],
    "additionalProperties": False,
}


def compile_pose_character_recipe(recipe: Any) -> dict[str, Any]:
    """Compile one character recipe contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed recipe.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the recipe only;
    it composes nothing and generates nothing.
    """
    if not isinstance(recipe, dict):
        raise CapabilityError("pose_character_recipe: recipe must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in recipe:
            raise CapabilityError(f"pose_character_recipe: missing required field {key!r}")
    extra = sorted(set(recipe) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("pose_character_recipe: unknown fields: " + ", ".join(extra))
    verdict = check_pose_character_recipe(recipe)
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"pose_character_recipe: {first['code']}: {first['detail']}")
    return {
        "contract": "pose-character-recipe",
        "recipe_id": recipe["recipe_id"],
        "portrait_id": verdict["portrait_id"],
        "costume_set_id": verdict["costume_set_id"],
        "pose_key": verdict["pose_key"],
        "view": verdict["view"],
        "provider": verdict["provider"],
        "multi_ref": recipe_to_multi_ref(recipe),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_pose_character_recipe(params.get("recipe"))
    contract_path = out_dir / "pose_character_recipe_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "recipe_id": contract["recipe_id"],
            "executed_here": False,
        },
    )


def register_pose_character_recipe_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.pose_character_recipe_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "recipe": {"type": "object"},
                },
                "required": ["recipe"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="video",
            description=(
                "Pose-gallery character recipe contract (fake): "
                "portrait plus costume plus pose slots, Chinese "
                "structured prompt, pose-only separation rule, "
                "provider; shape only, never executed here."
            ),
        )
    )
    return ["video.pose_character_recipe_schema"]


__all__ = [
    "SCHEMA",
    "compile_pose_character_recipe",
    "register_pose_character_recipe_schema_capabilities_once",
]
