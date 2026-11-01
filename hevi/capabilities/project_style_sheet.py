"""Project style-sheet contract (``pipeline.project_style_sheet``).

Clean-room rewrite of the *style-sheet discipline* of the
3D cartoon tutorial (see CARTOON_TUTORIAL_ATTRIBUTION.md):
once a look has been tuned, its rules are written down once
as a versioned, project-local contract, and every later
render must read that contract first. A style sheet is not a
mood board and not an upstream style essence: it is the
project's own tuned numbers, pinned to a version.

This differs from ``image.lemo_styles`` on purpose. A lemo
style is an upstream, fixed, read-only essence (a first
paragraph of a STYLE.md, read live); a project style sheet
is tuned inside one project, versioned, and must be re-read
before rendering. The two must never be conflated: the
upstream essence is not a substitute for the project sheet,
and the project sheet must not copy upstream style text or
any reference image.

Rules, all judged on JSON plans only -- no image is
generated, no reference image is read or copied:

* A sheet must carry ``schema_version`` and ``sheet_id``,
  and numeric values for proportions, outline, palette,
  lighting, material and motion. A missing numeric field
  fails, naming the field; prose alone ("soft light",
  "big head") never passes as a number.
* Before rendering, the sheet must be present and the
  render must have read it: ``check_render_readiness``
  requires a sample confirmation that names the exact
  sheet ``version`` it approved, is strictly ``True``
  (the string "true" and 1 are not confirmation), and
  whose sample ran no longer than ``sample_max_sec``
  (default 4.0 seconds, parameterised). A confirmation
  for an older version means the sheet is stale and the
  render is refused until a fresh sample is confirmed.

* Stage block (code-stage extension, see
  CODE_STAGE_MV_ATTRIBUTION.md): a sheet may carry a ``stage``
  object with a lighting rig (position / colour temperature /
  intensity per light, plus a beat curve), a camera path (start
  and end shot sizes, movement, beat binding), particles
  (kind / density / trigger event) and materials (style plus a
  floor with reflectivity, roughness and colour). The stage
  block is optional for a plain sheet -- existing sheets stay
  valid -- but a stage plan with a missing or invalid stage
  block is ``pending`` in :func:`check_stage_readiness` and
  never passes to render. Stage changes are versioned and
  staled exactly like the rest of the sheet: a stage plan
  needs a fresh sample confirmation for the exact sheet
  ``version`` it will render from.
"""

from __future__ import annotations

import json
import re
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

DEFAULT_SAMPLE_MAX_SEC = 4.0

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_values(mapping: Any) -> list[float]:
    if not isinstance(mapping, dict):
        return []
    return [float(v) for v in mapping.values() if _is_num(v)]


def validate_style_sheet(sheet: Any) -> dict[str, Any]:
    """Validate one project style sheet. Structural errors raise; missing numbers fail."""
    if not isinstance(sheet, dict):
        raise CapabilityError(
            "pipeline.project_style_sheet: style sheet must be a JSON object"
        )
    problems: list[str] = []
    schema_version = sheet.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        problems.append("schema_version: must be an integer")
    elif schema_version < 1:
        problems.append("schema_version: must be >= 1")
    sheet_id = sheet.get("sheet_id")
    if not isinstance(sheet_id, str) or not sheet_id.strip():
        problems.append("sheet_id: must be a non-empty string")
    version = sheet.get("version")
    if version is not None and (
        not isinstance(version, int) or isinstance(version, bool) or version < 1
    ):
        problems.append("version: must be a positive integer when present")

    # Proportions: at least one numeric ratio in (0, 1], e.g. head share of height.
    proportions = sheet.get("proportions")
    ratios = _numeric_values(proportions)
    if not isinstance(proportions, dict) or not ratios:
        problems.append(
            "proportions: must be an object with at least one numeric ratio"
        )
    elif not any(0.0 < r <= 1.0 for r in ratios):
        problems.append(
            "proportions: at least one ratio must be in (0, 1] "
            "(a head share of height, not prose)"
        )

    # Outline: a numeric stroke width.
    outline = sheet.get("outline")
    stroke = None
    if isinstance(outline, dict):
        for key in ("stroke_width_px", "stroke_px", "line_width_px"):
            if _is_num(outline.get(key)):
                stroke = float(outline[key])
                break
    if stroke is None:
        problems.append(
            "outline: must carry a numeric stroke width "
            "(stroke_width_px / stroke_px / line_width_px)"
        )
    elif stroke < 0:
        problems.append("outline: stroke width must be >= 0")

    # Palette: at least two concrete hex colours.
    palette = sheet.get("palette")
    colours: list[str] = []
    if isinstance(palette, dict):
        raw = palette.get("colors") or palette.get("colours") or palette.get("hex")
    elif isinstance(palette, list):
        raw = palette
    else:
        raw = None
    if isinstance(raw, list):
        colours = [c.strip().lower() for c in raw if isinstance(c, str) and _HEX_RE.match(c.strip())]
    if len(colours) < 2:
        problems.append(
            "palette: at least 2 concrete #RRGGBB colours are required, "
            f"found {len(colours)}"
        )

    # Lighting / material / motion: each needs at least one numeric value.
    for field in ("lighting", "material", "motion"):
        values = _numeric_values(sheet.get(field))
        if not isinstance(sheet.get(field), dict) or not values:
            problems.append(
                f"{field}: must be an object with at least one numeric value"
            )

    # Stage block: optional for a plain sheet, but when present it
    # must be complete -- a half-declared stage is a failure, not a
    # partial pass, and its problems join the sheet problems.
    stage = sheet.get("stage")
    stage_present = stage is not None
    stage_report = validate_stage_block(stage) if stage_present else {"ok": True, "problems": [], "present": False}
    stage_problems = list(stage_report["problems"])
    if stage_present and not stage_report["ok"]:
        problems.extend(stage_problems)
    return {
        "ok": not problems,
        "problems": problems,
        "sheet_id": sheet_id if isinstance(sheet_id, str) else None,
        "schema_version": schema_version,
        "version": version,
        "colours": sorted(set(colours)),
        "stage_present": stage_present,
        "stage_ok": bool(stage_report["ok"]),
        "stage_problems": stage_problems,
    }


STAGE_SHOT_SIZES = {
    "full_body", "full_shot", "full_length", "wide", "medium",
    "medium_close_up", "close_up", "extreme_close_up", "establishing",
}
STAGE_CAMERA_MOVEMENTS = {
    "static", "pan", "tilt", "dolly", "crane", "zoom",
    "tracking", "orbit", "push_in", "pull_out", "arc",
}
STAGE_PARTICLE_KINDS = {
    "sparkle", "dust", "confetti", "glow", "petal",
    "snow", "ember", "bubble", "star",
}


def _stage_num(value: Any) -> float | None:
    return float(value) if _is_num(value) else None


def _check_beat_curve(curve: Any, where: str, problems: list[str]) -> None:
    """A beat curve is a non-empty list of increasing beat/t_sec points with numeric intensity."""
    if not isinstance(curve, list) or not curve:
        problems.append(f"{where}: beat_curve must be a non-empty list of points")
        return
    previous: float | None = None
    for index, point in enumerate(curve):
        label = f"{where}[{index}]"
        if not isinstance(point, dict):
            problems.append(f"{label}: beat-curve point must be an object")
            continue
        when = _stage_num(point.get("t_sec")) if point.get("t_sec") is not None else _stage_num(point.get("beat"))
        if when is None:
            problems.append(f"{label}: beat-curve point needs a numeric t_sec or beat")
            continue
        if previous is not None and when <= previous:
            problems.append(f"{label}: beat-curve time/beat must strictly increase (got {when:g} after {previous:g})")
        previous = when
        if _stage_num(point.get("intensity")) is None:
            problems.append(f"{label}: beat-curve point needs a numeric intensity")


def validate_stage_block(stage: Any) -> dict[str, Any]:
    """Validate one ``stage`` block (lighting rig / camera path / particles / materials).

    A missing stage block is not an error here -- callers that
    need a stage (see :func:`check_stage_readiness`) report its
    absence as ``pending``. A present but malformed block fails
    with named problems; a non-object stage raises.
    """
    if stage is None:
        return {"ok": False, "problems": ["stage: missing; a stage plan needs a stage block"], "present": False}
    if not isinstance(stage, dict):
        raise CapabilityError(
            "pipeline.project_style_sheet: stage must be a JSON object"
        )
    problems: list[str] = []

    # Lighting rig: lights with position, colour temperature and
    # intensity, plus one rig-level beat curve.
    rig = stage.get("lighting_rig")
    if not isinstance(rig, dict):
        problems.append("stage.lighting_rig: must be an object with 'lights' and 'beat_curve'")
    else:
        lights = rig.get("lights")
        if not isinstance(lights, list) or not lights:
            problems.append("stage.lighting_rig.lights: must be a non-empty list")
        else:
            for index, light in enumerate(lights):
                label = f"stage.lighting_rig.lights[{index}]"
                if not isinstance(light, dict):
                    problems.append(f"{label}: light must be an object")
                    continue
                if not isinstance(light.get("type"), str) or not light["type"].strip():
                    problems.append(f"{label}.type: must be a non-empty string")
                if _stage_num(light.get("angle_deg")) is None:
                    problems.append(f"{label}.angle_deg: must be a number (light position in degrees)")
                if _stage_num(light.get("color_temperature_k")) is None:
                    problems.append(f"{label}.color_temperature_k: must be a number (kelvin)")
                elif not 1000.0 <= float(light["color_temperature_k"]) <= 20000.0:
                    problems.append(f"{label}.color_temperature_k: must be in [1000, 20000] K")
                if _stage_num(light.get("intensity")) is None:
                    problems.append(f"{label}.intensity: must be a number")
                elif float(light["intensity"]) < 0:
                    problems.append(f"{label}.intensity: must be >= 0")
                color_hex = light.get("color_hex")
                if color_hex is not None and (not isinstance(color_hex, str) or not _HEX_RE.match(color_hex.strip())):
                    problems.append(f"{label}.color_hex: must be #RRGGBB when present")
        _check_beat_curve(rig.get("beat_curve"), "stage.lighting_rig.beat_curve", problems)

    # Camera path: start/end shot sizes, movement, beat binding.
    path = stage.get("camera_path")
    if not isinstance(path, dict):
        problems.append("stage.camera_path: must be an object with start/end shot sizes, movement and beat binding")
    else:
        for field in ("start_shot", "end_shot"):
            value = path.get(field)
            if not isinstance(value, str) or value.strip().lower().replace("-", "_") not in STAGE_SHOT_SIZES:
                problems.append(
                    f"stage.camera_path.{field}: must be one of {sorted(STAGE_SHOT_SIZES)}, got {value!r}"
                )
        movement = path.get("movement")
        if not isinstance(movement, str) or movement.strip().lower().replace("-", "_") not in STAGE_CAMERA_MOVEMENTS:
            problems.append(
                f"stage.camera_path.movement: must be one of {sorted(STAGE_CAMERA_MOVEMENTS)}, got {movement!r}"
            )
        binding = path.get("beat_binding")
        if not isinstance(binding, dict):
            problems.append("stage.camera_path.beat_binding: must be an object naming the beats the move binds to")
        else:
            beats = binding.get("beats")
            if not isinstance(beats, list) or not beats or any(not _is_num(b) for b in beats):
                problems.append("stage.camera_path.beat_binding.beats: must be a non-empty list of numbers")
            elif any(b2 <= b1 for b1, b2 in zip(beats, beats[1:])):
                problems.append("stage.camera_path.beat_binding.beats: must strictly increase")
        duration = _stage_num(path.get("duration_s"))
        if duration is not None and duration <= 0:
            problems.append("stage.camera_path.duration_s: must be > 0 when present")

    # Particles: kind, density, trigger event.
    particles = stage.get("particles")
    if not isinstance(particles, dict):
        problems.append("stage.particles: must be an object with kind, density and trigger_event")
    else:
        kind = particles.get("kind")
        if not isinstance(kind, str) or kind.strip().lower() not in STAGE_PARTICLE_KINDS:
            problems.append(
                f"stage.particles.kind: must be one of {sorted(STAGE_PARTICLE_KINDS)}, got {kind!r}"
            )
        density = _stage_num(particles.get("density"))
        if density is None or not 0.0 <= density <= 1.0:
            problems.append("stage.particles.density: must be a number in [0, 1]")
        if not isinstance(particles.get("trigger_event"), str) or not particles["trigger_event"].strip():
            problems.append("stage.particles.trigger_event: must be a non-empty string naming the triggering event")
        speed = _stage_num(particles.get("speed"))
        if speed is not None and speed < 0:
            problems.append("stage.particles.speed: must be >= 0 when present")

    # Materials: style plus a floor with reflectivity, roughness, colour.
    materials = stage.get("materials")
    if not isinstance(materials, dict):
        problems.append("stage.materials: must be an object with style and floor")
    else:
        if not isinstance(materials.get("style"), str) or not materials["style"].strip():
            problems.append("stage.materials.style: must be a non-empty string")
        floor = materials.get("floor")
        if not isinstance(floor, dict):
            problems.append("stage.materials.floor: must be an object with reflective, roughness and color_hex")
        else:
            if floor.get("reflective") is not True and floor.get("reflective") is not False:
                problems.append("stage.materials.floor.reflective: must be strictly True or False")
            roughness = _stage_num(floor.get("roughness"))
            if roughness is None or not 0.0 <= roughness <= 1.0:
                problems.append("stage.materials.floor.roughness: must be a number in [0, 1]")
            color_hex = floor.get("color_hex")
            if not isinstance(color_hex, str) or not _HEX_RE.match(color_hex.strip()):
                problems.append("stage.materials.floor.color_hex: must be #RRGGBB")

    return {"ok": not problems, "problems": problems, "present": True}


def check_stage_readiness(
    sheet: Any, *, sample_confirmation: Any = None, sample_max_sec: float = DEFAULT_SAMPLE_MAX_SEC
) -> dict[str, Any]:
    """Stage readiness: the sheet's version/stale discipline plus a complete stage block.

    Returns ``status: "ready"`` only when the stage block is
    present and valid *and* a fresh, strictly confirmed sample
    names this exact sheet version. Anything else is
    ``status: "pending"`` with ``ok: False`` -- a stage plan
    missing its lighting rig or camera path is pending, never
    passed to render, and a stale sample keeps it pending too.
    """
    readiness = check_render_readiness(
        sheet, sample_confirmation=sample_confirmation, sample_max_sec=sample_max_sec
    )
    problems = list(readiness["problems"])
    stage_present = bool(readiness.get("stage_present")) if "stage_present" in readiness else False
    # check_render_readiness reports via validate_style_sheet; recover
    # the stage report from the sheet directly so the pending reason
    # names the missing fields even when the sheet itself is invalid.
    if isinstance(sheet, dict):
        stage_report = validate_style_sheet(sheet)
        stage_present = bool(stage_report.get("stage_present"))
        stage_ok = bool(stage_report.get("stage_ok"))
        stage_problems = list(stage_report.get("stage_problems", []))
    else:
        stage_ok = False
        stage_problems = ["stage: sheet must be a JSON object"]
    if not stage_present:
        problems.append("stage: missing; a stage plan needs lighting_rig, camera_path, particles and materials")
    elif not stage_ok:
        problems.extend(stage_problems)
    ok = readiness["ok"] and stage_present and stage_ok
    return {
        "ok": ok,
        "status": "ready" if ok else "pending",
        "problems": problems,
        "sheet_ok": readiness["sheet_ok"],
        "stage_present": stage_present,
        "stage_ok": stage_ok,
        "stage_problems": stage_problems,
        "stale": readiness["stale"],
        "sheet_version": readiness.get("sheet_version"),
        "sample_version": readiness.get("sample_version"),
        "sample_duration_sec": readiness.get("sample_duration_sec"),
        "sample_max_sec": readiness.get("sample_max_sec"),
    }


def check_sheet_stale(sheet: Any, baseline_version: Any) -> dict[str, Any]:
    """Report whether a sheet has moved past the version a sample approved."""
    report = validate_style_sheet(sheet)
    if not isinstance(baseline_version, int) or isinstance(baseline_version, bool):
        raise CapabilityError(
            "pipeline.project_style_sheet: baseline_version must be an integer"
        )
    version = sheet.get("version") if isinstance(sheet, dict) else None
    stale = version != baseline_version
    return {
        "stale": stale,
        "sheet_version": version,
        "baseline_version": baseline_version,
        "sheet_ok": report["ok"],
        "problems": report["problems"]
        + (
            [f"stale: sheet version {version} != approved version {baseline_version}"]
            if stale
            else []
        ),
    }


def check_render_readiness(
    sheet: Any, *, sample_confirmation: Any = None, sample_max_sec: float = DEFAULT_SAMPLE_MAX_SEC
) -> dict[str, Any]:
    """Require a fresh, strictly confirmed sample before rendering.

    ``sample_confirmation`` must be an object naming the exact
    sheet ``version`` it approved, with ``confirmed`` strictly
    ``True`` and ``sample_duration_sec`` no longer than
    ``sample_max_sec``. Anything else refuses the render.
    """
    report = validate_style_sheet(sheet)
    problems = list(report["problems"])
    sheet_version = sheet.get("version") if isinstance(sheet, dict) else None
    if sample_confirmation is None:
        problems.append(
            "sample_confirmation: missing; render refused until a sample "
            "for this sheet version is confirmed"
        )
        return {
            "ok": False,
            "problems": problems,
            "sheet_ok": report["ok"],
            "stale": True,
            "sample_duration_sec": None,
        }
    if not isinstance(sample_confirmation, dict):
        raise CapabilityError(
            "pipeline.project_style_sheet: sample_confirmation must be a JSON object"
        )
    confirmed_version = sample_confirmation.get("version")
    if sheet_version is not None and confirmed_version != sheet_version:
        problems.append(
            f"stale: sample approved version {confirmed_version}, "
            f"sheet is version {sheet_version}; re-run the sample"
        )
    if sample_confirmation.get("confirmed") is not True:
        problems.append(
            "sample_confirmation.confirmed: must be strictly True; "
            "the string 'true' or 1 is not confirmation"
        )
    sample_duration = sample_confirmation.get("sample_duration_sec")
    if not _is_num(sample_duration):
        problems.append(
            "sample_confirmation.sample_duration_sec: must be a number"
        )
    elif float(sample_duration) > float(sample_max_sec):
        problems.append(
            f"sample_confirmation.sample_duration_sec: {sample_duration} exceeds "
            f"the sample cap of {sample_max_sec} seconds"
        )
    stale = sheet_version is not None and confirmed_version != sheet_version
    return {
        "ok": not problems,
        "problems": problems,
        "sheet_ok": report["ok"],
        "stale": stale,
        "sheet_version": sheet_version,
        "sample_version": confirmed_version,
        "sample_duration_sec": float(sample_duration) if _is_num(sample_duration) else None,
        "sample_max_sec": float(sample_max_sec),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = str(params.get("action", "validate"))
    if action == "validate":
        report: dict[str, Any] = validate_style_sheet(params.get("sheet"))
    elif action == "readiness":
        report = check_render_readiness(
            params.get("sheet"),
            sample_confirmation=params.get("sample_confirmation"),
            sample_max_sec=float(params.get("sample_max_sec", DEFAULT_SAMPLE_MAX_SEC)),
        )
    elif action == "stale":
        report = check_sheet_stale(params.get("sheet"), params.get("baseline_version"))
    elif action == "stage":
        report = validate_stage_block(params.get("stage"))
    elif action == "stage_readiness":
        report = check_stage_readiness(
            params.get("sheet"),
            sample_confirmation=params.get("sample_confirmation"),
            sample_max_sec=float(params.get("sample_max_sec", DEFAULT_SAMPLE_MAX_SEC)),
        )
    else:
        raise CapabilityError(
            "pipeline.project_style_sheet: unknown action "
            f"{action!r}; known: validate, readiness, stale, stage, stage_readiness"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "project_style_sheet_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "pass": report["ok"] if "ok" in report else not report.get("stale"),
        },
    )


def register_project_style_sheet_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.project_style_sheet",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "sheet": {"type": "object"},
                    "stage": {"type": "object"},
                    "sample_confirmation": {"type": "object"},
                    "sample_max_sec": {"type": "number", "exclusiveMinimum": 0},
                    "baseline_version": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Project style-sheet contract: a versioned, project-local "
                "sheet with numeric proportion/outline/palette/lighting/"
                "material/motion values; rendering requires a fresh, "
                "strictly confirmed sample for the exact sheet version. "
                "An optional stage block adds a lighting rig (position / "
                "colour temperature / intensity / beat curve), a camera "
                "path, particles and materials; a stage plan missing "
                "its lighting or camera fields is pending and never "
                "passes to render. "
                "Judges JSON plans only; no reference image is read."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.project_style_sheet"]


register_project_style_sheet_capabilities_once()
