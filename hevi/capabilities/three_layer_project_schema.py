"""Three-layer project schema, fake layer
(``video.three_layer_project_schema``).

Contract-only schema for a re-runnable video project kept
as text: the source layer describes the work itself (script
lines, assets, components, composition), the recipe layer
holds reusable style formulas (a named parameter set), and
the run-record layer decides what one run produces and which
already-built artifacts it reuses under recorded build ids.
Changing the recipe never rewrites the script, and changing
a run target never rebuilds an artifact. Nothing is built,
no model is called, and nothing is rendered:
``executed_here`` is always false, ``rendered_here`` is
always false, and ``output_file`` is always null. See
HYPIT_ATTRIBUTION.md. Method restated in our own words; no
upstream file-format text is copied here.
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


def _fail(message: str) -> None:
    raise CapabilityError(message)


def compile_three_layer_project_contract(project: Any) -> dict[str, Any]:
    """Compile a three-layer project contract (contract only).

    Raises ``CapabilityError`` for a missing layer, an empty
    script, a recipe without parameters, run targets that are
    empty, or reuse entries without a build id. Never builds
    or renders anything.
    """
    if not isinstance(project, dict):
        _fail("project must be a JSON object")
    source = project.get("source")
    recipe = project.get("recipe")
    run_record = project.get("run_record")
    if not isinstance(source, dict):
        _fail("project must declare a source layer object")
    if not isinstance(recipe, dict):
        _fail("project must declare a recipe layer object")
    if not isinstance(run_record, dict):
        _fail("project must declare a run-record layer object")
    script_lines = source.get("script_lines")
    if (
        not isinstance(script_lines, list)
        or not script_lines
        or any(not isinstance(line, str) or not line.strip() for line in script_lines)
    ):
        _fail("source layer must carry a non-empty list of script lines")
    recipe_name = recipe.get("name")
    if not isinstance(recipe_name, str) or not recipe_name.strip():
        _fail("recipe layer must carry a non-empty name")
    parameters = recipe.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        _fail("recipe layer must carry a non-empty parameter set")
    targets = run_record.get("targets")
    if (
        not isinstance(targets, list)
        or not targets
        or any(not isinstance(t, str) or not t.strip() for t in targets)
    ):
        _fail("run record must declare a non-empty list of run targets")
    reuse = run_record.get("reuse")
    if not isinstance(reuse, list):
        _fail("run record must declare a reuse list")
    for entry in reuse:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("build_id"), str)
            or not entry["build_id"].strip()
        ):
            _fail("every reuse entry needs a non-empty build id")
    return {
        "source_lines": len(script_lines),
        "recipe": recipe_name,
        "recipe_parameters": sorted(parameters),
        "targets": list(targets),
        "reuse_count": len(reuse),
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_three_layer_project_contract(params.get("project"))
    contract_path = out_dir / "three_layer_project_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_three_layer_project_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.three_layer_project_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "project": {"type": "object"},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Three-layer project schema (contract only): source, "
                "recipe, and run-record layers for a re-runnable "
                "text-kept project; nothing is built or rendered."
            ),
        )
    )
    return ["video.three_layer_project_schema"]


__all__ = [
    "compile_three_layer_project_contract",
    "register_three_layer_project_schema_capabilities_once",
]
