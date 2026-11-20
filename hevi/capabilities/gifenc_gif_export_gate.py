"""gifenc GIF export gate (``qa.gifenc_gif_export_gate``).

Clean-room restatement of the mattdesl/gifenc method (see
``ANIMATION_STUDIO_18_ATTRIBUTION.md``); no upstream code
appears here. gifenc is the dedicated GIF encoder behind
hevi's animated-GIF export gap: ffmpeg can already encode
GIFs, but there was no dedicated GIF export gate declaring
frame rate, size, palette, looping, and the file-size
budget. Every export must declare all five, name its
encoder (gifenc or ffmpeg, with the division of labour
between the two explicit), and stay inside its declared
size budget when an estimate is given.
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

PALETTES = ("global", "local", "adaptive")
ENCODERS = ("gifenc", "ffmpeg")
MAX_FPS = 50
MAX_DIMENSION = 1280


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_gifenc_gif_export(export: Any) -> dict[str, Any]:
    """Validate a gifenc-style animated GIF export.

    Verdicts are ``pass`` / ``fail`` only. An export fails
    when it is not an object, when fps is outside 1..50, when
    width or height is not a positive integer within 1280,
    when the palette is not global, local, or adaptive, when
    the loop count is not a non-negative integer, when the
    size budget is not a positive integer, when the encoder
    is not gifenc or ffmpeg, or when an estimated size
    exceeds the declared budget.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(export, dict):
        return fail("export_not_object", "GIF export must be a JSON object")
    for field in ("fps", "width", "height", "palette", "loop", "max_file_bytes", "encoder"):
        if field not in export:
            return fail("export_field_missing", f"GIF export must carry {field!r}")
    fps = export["fps"]
    if not isinstance(fps, int) or isinstance(fps, bool) or not 1 <= fps <= MAX_FPS:
        return fail(
            "fps_out_of_range",
            f"fps must be an integer in 1..{MAX_FPS}, got {fps!r}",
        )
    for dim in ("width", "height"):
        value = export[dim]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            or value > MAX_DIMENSION
        ):
            return fail(
                "dimension_out_of_range",
                f"{dim} must be a positive integer within {MAX_DIMENSION}, got {value!r}",
            )
    if export["palette"] not in PALETTES:
        return fail(
            "palette_not_declared",
            f"palette must be one of {PALETTES}, got {export['palette']!r}",
        )
    loop = export["loop"]
    if not isinstance(loop, int) or isinstance(loop, bool) or loop < 0:
        return fail(
            "loop_not_valid",
            f"loop must be a non-negative integer (0 means infinite), got {loop!r}",
        )
    budget = export["max_file_bytes"]
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        return fail(
            "budget_not_positive",
            f"max_file_bytes must be a positive integer, got {budget!r}",
        )
    if export["encoder"] not in ENCODERS:
        return fail(
            "encoder_not_declared",
            f"encoder must be one of {ENCODERS}, got {export['encoder']!r}",
        )
    estimated = export.get("estimated_bytes")
    if estimated is not None:
        if not isinstance(estimated, int) or isinstance(estimated, bool):
            return fail(
                "estimated_bytes_not_int",
                "estimated_bytes must be an integer when given",
            )
        if estimated > budget:
            return fail(
                "estimated_over_budget",
                f"estimated {estimated} bytes exceeds the declared budget of {budget} bytes",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_gifenc_gif_export(params.get("export"))
    report_path = out_dir / "gifenc_gif_export_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_gifenc_gif_export_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.gifenc_gif_export_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "export": {"type": "object"},
                },
                "required": ["export"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "gifenc GIF export gate: fps 1..50, dimensions within "
                "1280, declared palette and loop count, a positive size "
                "budget, a named encoder (gifenc or ffmpeg), and estimates "
                "inside the budget."
            ),
        )
    )
    return ["qa.gifenc_gif_export_gate"]


__all__ = [
    "ENCODERS",
    "MAX_DIMENSION",
    "MAX_FPS",
    "PALETTES",
    "check_gifenc_gif_export",
    "register_gifenc_gif_export_gate_capabilities_once",
]
