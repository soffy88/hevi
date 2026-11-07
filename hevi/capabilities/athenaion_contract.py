"""Athenaion method graft, A1 + A2 (clean-room, method only).

Method source: Athenaion CONTRACT.md / COMPOSITION.md / looks.js as
described in ``hevi-vs-athenaion.md``; see ATHENAION_ATTRIBUTION.md.
No Athenaion code, image, or self-reported number is copied here:
every threshold in this module must be supplied by the caller, and
a missing item fails instead of silently passing.

A1 ``world.athenaion_discipline`` extends the already-registered
``world.contract_validate`` (``hevi.world_contract``) with the
contract-first discipline: build/test dual exports, shared-file
ownership, READY markers, footprints/slots/registry coordination,
seeded-RNG determinism (banned non-deterministic sources are
scanned in the supplied source texts), and a caller-supplied
performance budget. The existing spatial validator is reused, not
duplicated: when ``contract_path`` is given its result is merged
into the report.

A2 ``qa.look_shot_separation`` judges a plan that carries a
``look`` block and a ``shots`` list: look may only fix light /
material / tone / grade / atmosphere, shots may only fix camera /
movement / fov. A field written on the wrong side fails. The sun
may be defined absolutely or relative to the camera facing; a
relative sun keeps the light direction stable when the camera
moves, which is the property B1 verifies by rendering.
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

BANNED_SOURCES = ("Math.random", "Date.now", "performance.now", "new Date(")

# Look vocabulary: light, material, tone/grade, atmosphere only.
LOOK_KEYS = {
    "sun", "sun_elevation_deg", "sun_azimuth_deg", "sun_relative",
    "sun_disk", "lights", "lighting", "exposure", "white_balance",
    "color_temperature_k", "lift", "gamma", "gain", "contrast",
    "saturation", "grade", "grading", "tone_mapping", "vignette",
    "grain", "bloom", "fog", "fog_density", "fog_color", "atmosphere",
    "aerial_perspective", "material", "materials", "albedo",
    "roughness", "sky", "clouds", "haze",
}
LOOK_SUB_KEYS = {
    "sun": {"elevation_deg", "azimuth_deg", "relative", "disk", "intensity", "color_hex"},
    "grade": {"lift", "gamma", "gain", "contrast", "saturation", "exposure", "curve"},
    "fog": {"density", "color_hex", "near", "far"},
    "sky": {"color_hex", "horizon_hex", "sun_color_hex"},
}
# Shot vocabulary: camera and movement only.
SHOT_KEYS = {
    "name", "position", "pos", "target", "fov", "near", "far",
    "dof", "focus_m", "movement", "duration_s", "time_s",
    "dolly_m", "pan_deg", "tilt_deg", "orbit_deg", "zoom",
}
# Fields that must never appear on the other side.
SHOT_ONLY_IN_LOOK = {"position", "pos", "target", "fov", "movement", "camera"}
LOOK_ONLY_IN_SHOT = {
    "sun", "sun_elevation_deg", "sun_azimuth_deg", "sun_relative",
    "exposure", "lift", "gamma", "gain", "saturation", "contrast",
    "fog", "fog_density", "grade", "grading", "material", "materials",
}


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------- A1


def check_world_discipline(plan: Any) -> dict[str, Any]:
    """Judge a world-module plan against the A1 discipline. Fail-true."""
    if not isinstance(plan, dict):
        raise CapabilityError("world.athenaion_discipline: plan must be a JSON object")
    issues: list[dict[str, Any]] = []

    modules = plan.get("modules")
    if not isinstance(modules, list) or not modules:
        issues.append(_issue("modules_missing", "plan needs a non-empty 'modules' list"))
        modules = []
    for index, module in enumerate(modules):
        where = f"modules[{index}]"
        if not isinstance(module, dict):
            issues.append(_issue("module_not_object", f"{where} must be an object"))
            continue
        name = module.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(_issue("module_name_missing", f"{where}.name must be a non-empty string"))
        exports = module.get("exports")
        if not isinstance(exports, list) or "build" not in exports or "test" not in exports:
            issues.append(_issue(
                "dual_export_missing",
                f"{where} must export both 'build' and 'test'",
                exports=exports,
            ))
        owner = module.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            issues.append(_issue("owner_missing", f"{where}.owner must name the owning module"))
        if module.get("ready") is True and not module.get("ready_marker"):
            issues.append(_issue(
                "ready_marker_missing",
                f"{where} declares ready but names no READY marker file",
            ))

    shared = plan.get("shared_files")
    if not isinstance(shared, list) or not shared:
        issues.append(_issue(
            "shared_files_missing",
            "plan needs a non-empty 'shared_files' list with an owner per file",
        ))
        shared = []
    owners: dict[str, str] = {}
    for entry in shared:
        if not isinstance(entry, dict):
            issues.append(_issue("shared_file_not_object", "shared_files entries must be objects"))
            continue
        path = entry.get("path")
        owner = entry.get("owner")
        if not isinstance(path, str) or not path.strip():
            issues.append(_issue("shared_file_path_missing", "shared file needs a 'path'"))
        elif not isinstance(owner, str) or not owner.strip():
            issues.append(_issue("shared_file_owner_missing", f"shared file {path!r} needs an 'owner'"))
        else:
            owners[path] = owner
    for edit in plan.get("edits") or []:
        if not isinstance(edit, dict):
            issues.append(_issue("edit_not_object", "edits entries must be objects"))
            continue
        path, editor = edit.get("path"), edit.get("editor")
        if path in owners and editor != owners[path] and edit.get("additive_only") is not True:
            issues.append(_issue(
                "shared_file_owner_violation",
                f"non-owner edit of shared file {path!r} by {editor!r} "
                f"must be additive-only; owner is {owners[path]!r}",
                path=path, editor=editor, owner=owners[path],
            ))

    coord = plan.get("coordination")
    if not isinstance(coord, dict):
        issues.append(_issue(
            "coordination_missing",
            "plan needs a 'coordination' object naming footprints, slots and registry",
        ))
    else:
        for key in ("footprints", "slots", "registry"):
            if coord.get(key) is not True:
                issues.append(_issue(
                    "coordination_missing",
                    f"coordination.{key} must be present (true); "
                    "builders register footprints first, consumers read slots/registry",
                    mechanism=key,
                ))

    det = plan.get("determinism")
    if not isinstance(det, dict):
        issues.append(_issue("determinism_missing", "plan needs a 'determinism' object"))
    else:
        if det.get("seeded_rng") is not True:
            issues.append(_issue(
                "seeded_rng_missing",
                "determinism.seeded_rng must be true; world code uses a seeded RNG, never Math.random/Date",
            ))
        if not isinstance(det.get("seed"), (int, str)) or det.get("seed") in (None, ""):
            issues.append(_issue("seed_missing", "determinism.seed must name the seed"))
        sources = det.get("sources")
        if not isinstance(sources, list) or not sources:
            issues.append(_issue(
                "sources_missing",
                "determinism.sources must list the source texts to scan for banned sources; "
                "an unscanned world cannot pass",
            ))
        else:
            for source in sources:
                if not isinstance(source, dict) or not isinstance(source.get("text"), str):
                    issues.append(_issue("source_not_text", "determinism sources need {'path','text'}"))
                    continue
                for banned in BANNED_SOURCES:
                    if banned in source["text"]:
                        issues.append(_issue(
                            "banned_source",
                            f"banned non-deterministic source {banned!r} in {source.get('path')!r}",
                            banned=banned, path=source.get("path"),
                        ))

    budget = plan.get("performance_budget")
    if not isinstance(budget, dict):
        issues.append(_issue(
            "performance_budget_missing",
            "plan needs a 'performance_budget' object; budgets are caller-supplied, never defaults",
        ))
    else:
        for key in ("max_draw_calls", "max_triangles", "max_build_ms_per_module"):
            value = budget.get(key)
            if not _is_num(value) or float(value) <= 0:
                issues.append(_issue(
                    "budget_field_missing",
                    f"performance_budget.{key} must be a positive number supplied by the caller",
                    field=key, value=value,
                ))
        measured = budget.get("measured")
        if isinstance(measured, dict):
            checks = (
                ("draw_calls", "max_draw_calls"),
                ("triangles", "max_triangles"),
            )
            for measured_key, budget_key in checks:
                if measured_key in measured and budget.get(budget_key) is not None:
                    if _is_num(measured[measured_key]) and float(measured[measured_key]) > float(budget[budget_key]):
                        issues.append(_issue(
                            "budget_exceeded",
                            f"measured {measured_key} {measured[measured_key]} exceeds budget {budget[budget_key]}",
                            measured=measured[measured_key], budget=budget[budget_key],
                        ))
            per_module = measured.get("build_ms_per_module")
            if isinstance(per_module, dict) and _is_num(budget.get("max_build_ms_per_module")):
                for name, ms in per_module.items():
                    if _is_num(ms) and float(ms) > float(budget["max_build_ms_per_module"]):
                        issues.append(_issue(
                            "budget_exceeded",
                            f"module {name!r} build {ms}ms exceeds budget "
                            f"{budget['max_build_ms_per_module']}ms",
                            module=name, measured=ms,
                        ))

    return {"verdict": "fail" if issues else "pass", "issues": issues}


def check_athenaion_extension(
    plan: Any, contract: Any = None, manifest: Any = None
) -> dict[str, Any]:
    """A1 discipline plus, when given, the existing spatial validator."""
    discipline = check_world_discipline(plan)
    spatial: dict[str, Any] | None = None
    if contract is not None:
        from hevi.world_contract import validate

        spatial = validate(contract, manifest)
        if not spatial.get("pass"):
            discipline["issues"].append(_issue(
                "spatial_contract_failed",
                "hevi.world_contract validation failed; see 'spatial' report",
                violations=spatial.get("violations"),
            ))
    return {
        "verdict": "fail" if discipline["issues"] else "pass",
        "issues": discipline["issues"],
        "discipline": discipline,
        "spatial": spatial,
    }


# ---------------------------------------------------------------- A2


def check_look_shot_plan(plan: Any) -> dict[str, Any]:
    """Judge look/shots separation. Mixed fields fail; missing parts fail."""
    if not isinstance(plan, dict):
        raise CapabilityError("qa.look_shot_separation: plan must be a JSON object")
    issues: list[dict[str, Any]] = []

    look = plan.get("look")
    if not isinstance(look, dict) or not look:
        issues.append(_issue("look_missing", "plan needs a non-empty 'look' object"))
        look = {}
    for key in look:
        if key in SHOT_ONLY_IN_LOOK:
            issues.append(_issue(
                "camera_field_in_look",
                f"look must not carry camera field {key!r}; camera belongs to shots",
                field=key,
            ))
        elif key not in LOOK_KEYS:
            issues.append(_issue("look_field_unknown", f"look field {key!r} is not a look field", field=key))
    for sub, allowed in LOOK_SUB_KEYS.items():
        block = look.get(sub)
        if isinstance(block, dict):
            for key in block:
                if key not in allowed:
                    issues.append(_issue(
                        "look_subfield_unknown",
                        f"look.{sub}.{key} is not a look field", field=f"{sub}.{key}",
                    ))
    has_sun = any(k in look for k in ("sun", "sun_elevation_deg", "sun_azimuth_deg", "sun_relative"))
    has_grade = any(k in look for k in ("grade", "grading", "exposure", "lift", "gamma", "gain", "saturation", "contrast"))
    if look and not has_sun:
        issues.append(_issue("look_sun_missing", "look must define the sun (absolute or relative)"))
    if look and not has_grade:
        issues.append(_issue("look_grade_missing", "look must define at least one grade/exposure field"))
    sun = look.get("sun")
    if isinstance(sun, dict):
        if sun.get("relative") is not None and sun.get("azimuth_deg") is not None:
            issues.append(_issue(
                "sun_definition_mixed",
                "sun must be absolute (azimuth_deg) or relative to the camera, not both",
            ))
        if sun.get("relative") is not None and sun.get("relative") not in ("left", "right", "front", "behind"):
            issues.append(_issue("sun_relative_invalid", "sun.relative must be left/right/front/behind"))

    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        issues.append(_issue("shots_missing", "plan needs a non-empty 'shots' list"))
        shots = []
    for index, shot in enumerate(shots):
        where = f"shots[{index}]"
        if not isinstance(shot, dict):
            issues.append(_issue("shot_not_object", f"{where} must be an object"))
            continue
        for key in shot:
            if key in LOOK_ONLY_IN_SHOT:
                issues.append(_issue(
                    "look_field_in_shot",
                    f"shot must not carry look field {key!r}; light/grade belong to look",
                    field=key, shot=index,
                ))
            elif key not in SHOT_KEYS:
                issues.append(_issue("shot_field_unknown", f"{where}.{key} is not a shot field", field=key))
        for field in ("position", "target", "fov"):
            if field not in shot:
                issues.append(_issue("shot_field_missing", f"{where} needs {field!r}", field=field))
        fov = shot.get("fov")
        if fov is not None and (not _is_num(fov) or not 1.0 <= float(fov) <= 120.0):
            issues.append(_issue("shot_fov_invalid", f"{where}.fov must be in [1, 120] degrees", fov=fov))

    return {"verdict": "fail" if issues else "pass", "issues": issues}


def look_swap_delta(look_a: Any, look_b: Any) -> dict[str, Any]:
    """Which look aspects change between two looks, light vs grade separately.

    Used by B1 evidence: swapping the look on one fixed shot must
    change the light direction and the grade independently, so the
    two deltas are reported apart instead of as one blob.
    """
    if not isinstance(look_a, dict) or not isinstance(look_b, dict):
        raise CapabilityError("look_swap_delta: both looks must be JSON objects")
    light_keys = {"sun", "sun_elevation_deg", "sun_azimuth_deg", "sun_relative", "lights", "lighting"}
    grade_keys = {"exposure", "lift", "gamma", "gain", "contrast", "saturation", "grade", "grading", "tone_mapping"}
    changed_light = sorted(k for k in light_keys if look_a.get(k) != look_b.get(k))
    changed_grade = sorted(k for k in grade_keys if look_a.get(k) != look_b.get(k))
    return {
        "light_changed": changed_light,
        "grade_changed": changed_grade,
        "light_independent": bool(changed_light),
        "grade_independent": bool(changed_grade),
    }


# ---------------------------------------------------------------- registry


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = str(params.get("mode", "discipline"))
    if mode == "look_shot":
        report = check_look_shot_plan(params.get("plan"))
        ok = report["verdict"] == "pass"
    else:
        contract = manifest = None
        if params.get("contract_path"):
            from hevi.world_contract import load_json

            contract = load_json(params["contract_path"])
            if params.get("manifest_path"):
                manifest = load_json(params["manifest_path"])
        report = check_athenaion_extension(params.get("plan"), contract, manifest)
        ok = report["verdict"] == "pass"
    report_path = out_dir / "athenaion_contract_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"], "ok": ok,
            "issues": report["issues"]},
    )


def register_athenaion_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="world.athenaion_discipline",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "plan": {"type": "object"},
                "contract_path": {"type": "string"},
                "manifest_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=0.01,
        render=_render,
        has_media_output=False,
        description=(
            "A1 contract-first discipline for procedural worlds "
            "(build/test exports, shared-file owners, READY markers, "
            "footprints/slots/registry, seeded RNG, caller-supplied "
            "performance budget), extending world.contract_validate. "
            "Missing items fail. See ATHENAION_ATTRIBUTION.md."
        ),
        line="world",
    ))
    register(Capability(
        name="qa.look_shot_separation",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "plan": {"type": "object"},
            },
            "required": ["mode", "plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.01,
        render=_render,
        has_media_output=False,
        description=(
            "A2 look/shots separation gate: look fixes light/material/"
            "tone/grade only, shots fix camera/movement/fov only; "
            "a field on the wrong side fails. See ATHENAION_ATTRIBUTION.md."
        ),
        line="qa",
    ))
    return ["world.athenaion_discipline", "qa.look_shot_separation"]


register_athenaion_contract_capabilities_once()
