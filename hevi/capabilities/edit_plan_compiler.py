"""Second-pass edit-plan compiler (``video.edit_plan_compiler``).

Clean-room restatement of the second-pass edit discipline
described in the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): after review, the
surviving takes are assembled by a written plan -- trim
points per shot, seam treatment between neighbours, and one
uniform finish (colour temperature, loudness, grain) for the
whole film. Failed shots never enter the plan; they go to
the redraw list. Shot frame counts follow hevi's 5+17k
continuation grid, never a fixed foreign frame count.

This module compiles plans only. It renders nothing, calls
no encoder, and never touches a budget. Every compiled plan
carries ``executed_here: false``: execution stays a separate
case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.pure_helpers import (
    is_on_grid,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_SEAM_KINDS = ("hard_cut", "xfade")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"video.edit_plan_compiler: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compile_edit_plan(plan: Any) -> dict[str, Any]:
    """Compile one second-pass edit plan and judge its tiling.

    ``plan`` carries ``shots`` (each with ``id``, ``duration_s``,
    ``fps``, ``frames`` and a review ``verdict``), ``seams``
    (between consecutive shots, each with ``kind``), a
    ``finish`` block (colour temperature, loudness, grain),
    and a ``redraw_list``. Verdict ``pass`` means the shots
    tile the declared total duration without gaps or overlap,
    every declared frame count is on the 5+17k grid, seams
    are of a known kind, failed shots are excluded and
    re-drawn, and the finish block is present. The returned
    plan is a schema only: ``executed_here`` is always false.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("edit plan must be an object")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        raise CapabilityError("edit plan requires a non-empty shots list")
    issues: list[dict[str, Any]] = []
    compiled: list[dict[str, Any]] = []
    cursor = 0.0
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict) or not shot.get("id"):
            issues.append(_issue("shot_invalid", f"shot {index} lacks an id"))
            continue
        if shot.get("verdict") == "fail":
            issues.append(
                _issue(
                    "failed_shot_in_plan",
                    f"failed shot {shot['id']} must not enter the edit plan",
                    shot=shot["id"],
                )
            )
        duration = shot.get("duration_s")
        if not _is_number(duration) or duration <= 0:
            issues.append(
                _issue(
                    "duration_invalid",
                    f"shot {shot['id']} requires a positive duration_s",
                    shot=shot["id"],
                )
            )
            continue
        frames = shot.get("frames")
        fps = shot.get("fps")
        if isinstance(frames, int) and not isinstance(frames, bool):
            if not is_on_grid(frames):
                issues.append(
                    _issue(
                        "frames_off_grid",
                        f"shot {shot['id']} declares {frames} frames, off "
                        "the 5+17k grid",
                        shot=shot["id"],
                    )
                )
        elif _is_number(fps):
            computed = round(duration * fps)
            if not is_on_grid(computed):
                issues.append(
                    _issue(
                        "frames_off_grid",
                        f"shot {shot['id']} at {duration}s x {fps}fps is "
                        f"{computed} frames, off the 5+17k grid",
                        shot=shot["id"],
                    )
                )
        else:
            issues.append(
                _issue(
                    "frames_undeclared",
                    f"shot {shot['id']} declares neither frames nor fps",
                    shot=shot["id"],
                )
            )
        start = shot.get("start_s", cursor)
        if _is_number(start) and abs(start - cursor) > 1e-6:
            issues.append(
                _issue(
                    "tiling_gap_or_overlap",
                    f"shot {shot['id']} starts at {start}s, expected {cursor}s",
                    shot=shot["id"],
                )
            )
        compiled.append(
            {"id": shot["id"], "start_s": cursor, "end_s": cursor + duration}
        )
        cursor += duration
    total = plan.get("total_duration_s")
    if _is_number(total) and abs(total - cursor) > 1e-6:
        issues.append(
            _issue(
                "total_duration_mismatch",
                f"declared total {total}s does not match tiled {cursor}s",
            )
        )
    seams = plan.get("seams", [])
    if not isinstance(seams, list):
        raise CapabilityError("seams must be a list when present")
    if len(seams) != max(0, len(compiled) - 1):
        issues.append(
            _issue(
                "seam_count_mismatch",
                f"{len(seams)} seams for {len(compiled)} shots; "
                "one seam is required between each pair",
            )
        )
    for index, seam in enumerate(seams):
        if not isinstance(seam, dict) or seam.get("kind") not in _SEAM_KINDS:
            issues.append(
                _issue("seam_kind_unknown", f"seam {index} kind must be hard_cut or xfade")
            )
    finish = plan.get("finish")
    if not isinstance(finish, dict) or not finish:
        issues.append(
            _issue("finish_missing", "a uniform finish block is required")
        )
    redraw = plan.get("redraw_list", [])
    if not isinstance(redraw, list):
        raise CapabilityError("redraw_list must be a list when present")
    for shot in shots:
        if (
            isinstance(shot, dict)
            and shot.get("verdict") == "fail"
            and shot.get("id") not in redraw
        ):
            issues.append(
                _issue(
                    "failed_shot_not_redrawn",
                    f"failed shot {shot['id']} is missing from the redraw list",
                    shot=shot["id"],
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "compiled_shots": compiled,
        "total_duration_s": cursor,
        "executed_here": False,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_edit_plan(params.get("plan"))
    report_path = out_dir / "edit_plan.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_edit_plan_compiler_capabilities_once() -> list[str]:
    """Register ``video.edit_plan_compiler`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.edit_plan_compiler",
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
            description=(
                "Second-pass edit-plan compiler: trim points, seam "
                "treatments, and a uniform finish, tiling the declared "
                "total on the 5+17k grid; failed shots go to redraw. "
                "Schema only; nothing is rendered here."
            ),
        )
    )
    return ["video.edit_plan_compiler"]


__all__ = [
    "compile_edit_plan",
    "register_edit_plan_compiler_capabilities_once",
]
