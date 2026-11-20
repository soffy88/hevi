"""Three-in-one character recipe gate (``qa.pose_character_recipe_gate``).

A character recipe fixes three reference slots — portrait,
costume, pose — plus a pure-Chinese structured prompt, and
the separation rule that only the pose is referenced, never
the clothing, hairstyle, or art style. The gate judges the
recipe shape only; it never composes, renders, or calls a
model.

De-duplication against ``image.multi_ref_compose`` (golive3):
generic multi-reference composition already exists there,
with provider reference limits (vidu 7, alibaba_maas 9,
happyhorse 9, runway 3, h3_local 4). This gate does not
re-implement composition. Its increment is the fixed
three-slot recipe, the separation rule, the structured
Chinese prompt, and the binding of each slot to the pose,
costume, and portrait indexes. ``recipe_to_multi_ref``
compiles a passing recipe into the exact input shape
``image.multi_ref_compose`` consumes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities import pose_library
from hevi.capabilities.pose_costume_library_gate import SOURCES as COSTUME_SOURCES
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Restated from golive3.PROVIDER_REF_LIMITS (same numbers, same
# keys) so this module does not import the heavy golive3 stack.
PROVIDER_REF_LIMITS: dict[str, int] = {
    "vidu": 7,
    "alibaba_maas": 9,
    "happyhorse_1_1": 9,
    "happyhorse_1_1_maas_ref": 9,
    "runway": 3,
    "h3_local": 4,
}
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_pose_character_recipe(recipe: Any) -> dict[str, Any]:
    """Validate one three-in-one character recipe.

    Verdicts are ``pass`` / ``fail`` only. A recipe fails when
    any of the three slots is missing or unresolvable, the
    prompt is not a Chinese structured prompt, the separation
    rule does not state that only the pose is referenced (and
    clothing is not referenced), the provider is unknown, or
    the total reference count exceeds the provider limit.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(recipe, dict):
        return fail("recipe_not_object", "character recipe must be a JSON object")
    portrait_ref = recipe.get("portrait_ref")
    if (
        not isinstance(portrait_ref, dict)
        or not isinstance(portrait_ref.get("portrait_id"), str)
        or not portrait_ref["portrait_id"].strip()
    ):
        return fail(
            "portrait_ref_missing",
            "recipe must carry a portrait_ref with a non-empty portrait_id",
        )
    costume_ref = recipe.get("costume_ref")
    if not isinstance(costume_ref, dict):
        return fail("costume_ref_missing", "recipe must carry a costume_ref object")
    if costume_ref.get("source") not in COSTUME_SOURCES:
        return fail(
            "costume_source_unknown",
            f"costume source must be one of {sorted(COSTUME_SOURCES)}, "
            f"got {costume_ref.get('source')!r}",
        )
    if not isinstance(costume_ref.get("set_id"), str) or not costume_ref["set_id"].strip():
        return fail(
            "costume_set_id_missing",
            "recipe costume_ref must carry a non-empty set_id",
        )
    pose_ref = recipe.get("pose_ref")
    if not isinstance(pose_ref, dict):
        return fail("pose_ref_missing", "recipe must carry a pose_ref object")
    pose_key = pose_ref.get("pose_key")
    view = pose_ref.get("view")
    try:
        group = pose_library.get_pose_by_key(pose_key)
    except Exception as exc:  # unknown key or wrong type
        return fail("pose_ref_unknown", f"recipe pose_ref is unresolvable: {exc}")
    if view not in pose_library.VIEWS or group["views"].get(view) is None:
        return fail(
            "pose_view_missing",
            f"pose {pose_key!r} has no {view!r} view (missing views: {group['missing_views']})",
        )
    prompt_zh = recipe.get("prompt_zh")
    if not isinstance(prompt_zh, str) or not prompt_zh.strip():
        return fail(
            "prompt_zh_missing",
            "recipe must carry a non-empty Chinese structured prompt",
        )
    if not _CJK.search(prompt_zh):
        return fail(
            "prompt_not_chinese",
            "the recipe prompt must be a Chinese structured prompt",
        )
    separation = recipe.get("separation_rule")
    if not isinstance(separation, str) or "仅参考姿势" not in separation:
        return fail(
            "separation_rule_missing",
            "recipe must carry a separation rule stating 仅参考姿势",
        )
    if "不参考服装" not in separation:
        return fail(
            "separation_rule_incomplete",
            "the separation rule must also state 不参考服装 "
            "(never the clothing, hairstyle, or art style)",
        )
    provider = recipe.get("provider")
    if provider not in PROVIDER_REF_LIMITS:
        return fail(
            "unknown_provider",
            f"provider must be one of {sorted(PROVIDER_REF_LIMITS)}, got {provider!r}",
        )
    extra_refs = recipe.get("extra_refs", [])
    if not isinstance(extra_refs, list):
        return fail("extra_refs_invalid", "extra_refs must be a list when given")
    total_refs = 3 + len(extra_refs)
    if total_refs > PROVIDER_REF_LIMITS[provider]:
        return fail(
            "provider_ref_limit_exceeded",
            f"recipe needs {total_refs} references but provider "
            f"{provider!r} allows {PROVIDER_REF_LIMITS[provider]}",
        )
    max_refs = recipe.get("max_refs")
    if max_refs is not None and (
        not isinstance(max_refs, int)
        or isinstance(max_refs, bool)
        or max_refs < total_refs
        or max_refs > PROVIDER_REF_LIMITS[provider]
    ):
        return fail(
            "max_refs_invalid",
            f"max_refs must be between {total_refs} and "
            f"{PROVIDER_REF_LIMITS[provider]} for provider {provider!r}",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "portrait_id": portrait_ref["portrait_id"],
        "costume_set_id": costume_ref["set_id"],
        "pose_key": pose_key,
        "view": view,
        "provider": provider,
        "total_refs": total_refs,
        "executed_here": False,
    }


def recipe_to_multi_ref(recipe: dict[str, Any]) -> dict[str, Any]:
    """Compile a passing recipe into multi_ref_compose input shape.

    Raises CapabilityError when the recipe fails the gate.
    Composition itself stays with ``image.multi_ref_compose``.
    """
    from hevi.capabilities.errors import CapabilityError

    verdict = check_pose_character_recipe(recipe)
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"pose_character_recipe: {first['code']}: {first['detail']}")
    return {
        "shot_prompt": recipe["prompt_zh"],
        "references": {
            "portrait": recipe["portrait_ref"]["portrait_id"],
            "costume": recipe["costume_ref"]["set_id"],
            "pose": recipe["pose_ref"]["pose_key"],
        },
        "provider": recipe["provider"],
        "max_refs": recipe.get("max_refs", PROVIDER_REF_LIMITS[recipe["provider"]]),
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_pose_character_recipe(params.get("recipe"))
    report_path = out_dir / "pose_character_recipe_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_character_recipe_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_character_recipe_gate",
            kind="line",
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
            layer="oskill",
            description=(
                "Pose-gallery character recipe gate: fixed portrait "
                "plus costume plus pose slots, Chinese structured "
                "prompt, pose-only separation rule, provider "
                "reference limits; compiles into "
                "image.multi_ref_compose input shape."
            ),
        )
    )
    return ["qa.pose_character_recipe_gate"]


__all__ = [
    "PROVIDER_REF_LIMITS",
    "check_pose_character_recipe",
    "recipe_to_multi_ref",
    "register_pose_character_recipe_gate_capabilities_once",
]
