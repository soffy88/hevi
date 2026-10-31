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
    return {
        "ok": not problems,
        "problems": problems,
        "sheet_id": sheet_id if isinstance(sheet_id, str) else None,
        "schema_version": schema_version,
        "version": version,
        "colours": sorted(set(colours)),
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
    else:
        raise CapabilityError(
            "pipeline.project_style_sheet: unknown action "
            f"{action!r}; known: validate, readiness, stale"
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
                "Judges JSON plans only; no reference image is read."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.project_style_sheet"]


register_project_style_sheet_capabilities_once()
