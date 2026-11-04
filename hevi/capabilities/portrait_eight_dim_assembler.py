"""Eight-dimension portrait assembler capability.

Registers one ``hevi.capabilities`` entry:

* ``image.portrait_eight_dim_assembler`` -- assemble one portrait
  prompt from one pick per vocabulary dimension (fabric,
  expression, lens, light) plus caller-supplied anchoring,
  environment, restraint, and firewall negatives.  Every assembly
  runs all four gates first and fails closed on any gate failure:

  - ``qa.adult_portrait_gate`` (hard intercept),
  - ``qa.negative_prompt_firewall``,
  - ``qa.physical_language_gate``,
  - ``qa.restraint_ceiling_gate`` (existing conflict detection
    over any ``vocab_picks`` from the 66-entry index).

  The four vocabulary dimensions are orthogonal by construction
  (fabric, light, lens, and expression compete for no shared body
  resource), so the extension entries carry no pair conflicts of
  their own; conflicts can only arrive through ``vocab_picks``.

  Fully local: no keys, no network, zero cost -- this capability
  only assembles text; rendering stays with the image backends.
  Adult portraits only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.adult_portrait_gate import check_adult_portrait
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.negative_prompt_firewall_gate import (
    check_negative_prompt_firewall,
)
from hevi.capabilities.physical_language_gate import check_physical_language
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.restraint_ceiling_gate import check_restraint_ceiling

_DIMENSION_TO_CATEGORY = {
    "fabric": "fabric",
    "expression": "micro_expression",
    "lens": "lens_optics",
    "light": "skin_light",
}


def _resolve_dimension_picks(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from hevi.image.portrait_vocab import eight_dim as ed

    picks: dict[str, dict[str, Any]] = {}
    for dim, category in _DIMENSION_TO_CATEGORY.items():
        raw = plan.get(dim)
        if raw is None or not str(raw).strip():
            continue
        entry = ed.get_entry(raw)
        if entry["category"] != category:
            raise CapabilityError(
                f"dimension {dim!r} pick {raw!r} belongs to category "
                f"{entry['category']!r}, not {category!r}"
            )
        picks[dim] = entry
    return picks


def assemble_eight_dim_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate a plan through all four gates, then assemble it. Composes (3O SPEC 1.2): check_physical_language."""
    from hevi.image.portrait_vocab import eight_dim as ed

    if not isinstance(plan, dict):
        raise CapabilityError("eight-dim plan must be an object")
    dimensions = {
        "anchoring": str(plan.get("anchoring", "")),
        "fabric": str(plan.get("fabric", "")),
        "expression": str(plan.get("expression", "")),
        "lens": str(plan.get("lens", "")),
        "light": str(plan.get("light", "")),
        "environment": str(plan.get("environment", "")),
        "restraint": plan.get("restraint", ""),
        "negatives": plan.get("negatives", []),
    }
    gate_reports = {
        "adult": check_adult_portrait(plan),
        "firewall": check_negative_prompt_firewall(plan),
        "physical_language": check_physical_language({"dimensions": dimensions}),
        "restraint": check_restraint_ceiling(
            {
                "picks": plan.get("vocab_picks", {}),
                "text": str(plan.get("anchoring", ""))
                + str(plan.get("environment", "")),
                "text_en": "",
            }
        ),
    }
    issues: list[str] = []
    for name, report in gate_reports.items():
        issues.extend(f"{name}: {issue}" for issue in report["issues"])
    picks = _resolve_dimension_picks(plan)
    for dim in _DIMENSION_TO_CATEGORY:
        if dim not in picks:
            issues.append(f"dimension_missing: {dim} has no vocabulary pick")
    if issues:
        raise CapabilityError(
            "eight-dim assembly refused: " + "; ".join(issues)
        )
    assembled = ed.assemble_eight_dim(
        picks,
        identity=str(plan.get("identity", "")),
        anchoring=str(plan.get("anchoring", "")),
        environment=str(plan.get("environment", "")),
        scene=str(plan.get("scene", "")),
        framing=str(plan.get("framing", "")),
        negatives=[str(n) for n in plan.get("negatives", [])],
    )
    return {
        **assembled,
        "dimensions": dimensions,
        "gates": {name: r["verdict"] for name, r in gate_reports.items()},
        "declared_age": gate_reports["adult"]["declared_age"],
        "adult_only": True,
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = assemble_eight_dim_plan(params.get("plan"))
    path = out_dir / "portrait_eight_dim_prompt.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        sha256=compute_sha256(path),
        qa={
            "prompt_json": str(path),
            "prompt_zh": payload["prompt_zh"],
            "prompt_en": payload["prompt_en"],
            "negative_prompt": payload["negative_prompt"],
            "entry_ids": payload["entry_ids"],
            "gates": payload["gates"],
            "note": (
                "Assembled locally at zero cost after all four "
                "gates passed; feed prompt_zh / prompt_en to an "
                "image backend and negative_prompt to its negative "
                "field. Adult portraits only."
            ),
        },
    )


_Registered = False


def register_portrait_eight_dim_assembler_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.portrait_eight_dim_assembler",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Eight-dimension portrait assembler: one pick per "
                "vocabulary dimension plus anchoring, environment, "
                "restraint, and firewall negatives, gated by the "
                "adult, firewall, physical-language, and restraint "
                "gates. Fails closed on any gate failure."
            ),
        )
    )
    return ["image.portrait_eight_dim_assembler"]


register_portrait_eight_dim_assembler_capabilities_once()
