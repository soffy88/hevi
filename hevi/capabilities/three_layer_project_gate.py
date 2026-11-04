"""Three-layer project gate (``qa.three_layer_project_gate``).

Discipline gate only. A re-runnable video project separates
three layers: the source layer describes the work itself
(script, assets, components, composition); the recipe layer
holds reusable style formulas (named parameter sets); the
run-record layer decides what one run produces and which
already-built artifacts it reuses. Mixing layers fails: recipe
parameters inside the source, script content inside a recipe,
or fresh creative content inside a run record. This gate
judges the project description only and renders nothing. See
HYPIT_ATTRIBUTION.md. Method restated in our own words; no
upstream file-format text is copied here.
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

_RECIPE_PARAM_KEYS = frozenset(
    {"palette", "font_size", "appear_frames", "style_params", "parameters"}
)
_RUN_KEYS = frozenset({"targets", "reuse", "build_id", "run_id"})
_CREATIVE_KEYS = frozenset({"script", "script_lines", "lines"})


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def check_three_layer_project(project: Any) -> dict[str, Any]:
    """Check that source, recipe, and run-record layers stay separate.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. A missing layer, recipe parameters in the
    source, script content in a recipe, creative content in a
    run record, or reuse entries without a build id all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(project, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("project_not_object", "project must be a JSON object")],
        }
    source = project.get("source")
    recipe = project.get("recipe")
    run_record = project.get("run_record")
    if not isinstance(source, dict):
        issues.append(_issue("source_missing", "project must declare a source layer object"))
        source = {}
    if not isinstance(recipe, dict):
        issues.append(_issue("recipe_missing", "project must declare a recipe layer object"))
        recipe = {}
    if not isinstance(run_record, dict):
        issues.append(
            _issue("run_record_missing", "project must declare a run-record layer object")
        )
        run_record = {}
    if source:
        if not source.get("script") and not source.get("script_lines"):
            issues.append(_issue("source_script_missing", "source layer must carry the script"))
        issues.extend(
            _issue(
                f"source_has_recipe_param:{key}",
                "recipe parameters must live in the recipe layer, not the source",
            )
            for key in sorted(_RECIPE_PARAM_KEYS & set(source))
        )
        issues.extend(
            _issue(
                f"source_has_run_key:{key}",
                "run-record keys must live in the run-record layer, not the source",
            )
            for key in sorted(_RUN_KEYS & set(source))
        )
    if recipe:
        parameters = recipe.get("parameters")
        if not isinstance(parameters, dict) or not parameters:
            issues.append(
                _issue(
                    "recipe_parameters_missing",
                    "recipe layer must carry a non-empty named parameter set",
                )
            )
        issues.extend(
            _issue(
                f"recipe_has_script:{key}",
                "script content must live in the source layer, not a recipe",
            )
            for key in sorted(_CREATIVE_KEYS & set(recipe))
        )
        issues.extend(
            _issue(
                f"recipe_has_run_key:{key}",
                "run-record keys must live in the run-record layer, not a recipe",
            )
            for key in sorted(_RUN_KEYS & set(recipe))
        )
    if run_record:
        targets = run_record.get("targets")
        if not isinstance(targets, list) or not targets:
            issues.append(
                _issue(
                    "run_targets_missing",
                    "run record must declare a non-empty list of run targets",
                )
            )
        reuse = run_record.get("reuse")
        if not isinstance(reuse, list):
            issues.append(_issue("run_reuse_missing", "run record must declare a reuse list"))
        else:
            for index, entry in enumerate(reuse):
                if (
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("build_id"), str)
                    or not entry["build_id"].strip()
                ):
                    issues.append(
                        _issue(
                            f"run_record.reuse[{index}]:build_id_missing",
                            "every reuse entry needs a non-empty build id",
                        )
                    )
        issues.extend(
            _issue(
                f"run_record_has_creation:{key}",
                "run records decide targets and reuse; they must not hold fresh creative content",
            )
            for key in sorted(_CREATIVE_KEYS & set(run_record))
        )
        issues.extend(
            _issue(
                f"run_record_has_recipe_param:{key}",
                "recipe parameters must live in the recipe layer, not a run record",
            )
            for key in sorted(_RECIPE_PARAM_KEYS & set(run_record))
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_three_layer_project(params.get("project"))
    report_path = out_dir / "three_layer_project.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_three_layer_project_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.three_layer_project_gate",
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
            layer="oskill",
            description=(
                "Three-layer project gate (discipline only): source, "
                "recipe, and run-record layers stay separate; mixing "
                "layers fails."
            ),
        )
    )
    return ["qa.three_layer_project_gate"]


__all__ = [
    "check_three_layer_project",
    "register_three_layer_project_gate_capabilities_once",
]
