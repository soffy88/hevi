"""Continuation grid gate (``qa.continuation_grid_gate``).

Clean-room restatement of the frame-grid discipline behind the
PrefixStream relay method (see ``PREFIXSTREAM_ATTRIBUTION.md``):
a continuation is built on a fixed frame grid -- 5 + 17k frames
(5, 22, 39, 56, ..., 192, and the same rule extended) -- and the
phase of the tail that is carried over is computed from that grid,
never improvised. A plan whose frame count is not on the grid must
be snapped at compile time, in the plan, with the original count
recorded; cropping or padding at execution time is a failure, not
a fix.

Route calibres are kept separate, because the two H3 routes do
not share a frame count for the same duration:

* the ``fasth3`` route computes ``max(124, round(duration * 24))``
  frames, so a 13.268 s segment is 318 frames -- **not** on the
  grid (its grid neighbours are 311 and 328);
* the ``h3`` route's 328 frames for the same duration **are** on
  the grid (5 + 17 x 19).

This module judges plans only. It never generates, never calls a
model, never touches a budget, and it never re-implements the
latent/mask machinery -- that execution work (B1) waits on a GPU
and a ComfyUI install. No author-reported number lives here as a
default: the grid rule itself (base 5, step 17) is the discipline
being judged, and every count is caller-declared.
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
from hevi.capabilities.pure_helpers import (
    GRID_BASE,
    GRID_STEP,
    is_on_grid,
    snap_down,
    snap_up,
)

_Registered = False



def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.continuation_grid_gate: {detail}"}
    issue.update(extra)
    return issue








def check_continuation_grid(plan: Any) -> dict[str, Any]:
    """Judge one continuation plan against the frame grid.

    ``plan`` is an object with ``route`` (``"fasth3"`` or ``"h3"``)
    and ``segments``: each segment declares ``frames`` (an int) and,
    when its count was snapped, ``snapped_from`` (the pre-snap
    count) plus ``snapped`` true. A segment that declares
    ``execution_crop`` (or ``cropped_in_execution``) true fails:
    cropping belongs to compile time, never to execution.
    Returns ``ok`` / ``issues`` / ``segments`` (each annotated with
    its grid verdict and snap neighbours when off grid).
    """
    issues: list[dict[str, Any]] = []
    segments_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "issues": [
                _issue(
                    "plan_not_object",
                    "continuation plan must be an object",
                )
            ],
            "segments": segments_out,
        }
    route = plan.get("route")
    if route not in ("fasth3", "h3"):
        issues.append(
            _issue(
                "route_undeclared",
                f"route must be 'fasth3' or 'h3', got {route!r}; "
                "the two routes have different frame calibres and "
                "must never be mixed",
            )
        )
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        issues.append(
            _issue(
                "segments_missing",
                "plan must declare a non-empty 'segments' list",
            )
        )
        segments = segments if isinstance(segments, list) else []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            issues.append(
                _issue(
                    "segment_not_object",
                    f"segment {index} must be an object",
                    segment_index=index,
                )
            )
            segments_out.append({"segment_index": index, "on_grid": False})
            continue
        frames = segment.get("frames")
        entry: dict[str, Any] = {"segment_index": index, "frames": frames}
        if segment.get("execution_crop") or segment.get("cropped_in_execution"):
            issues.append(
                _issue(
                    "execution_crop",
                    f"segment {index}: frame count was cropped at "
                    "execution time; snapping belongs to compile time "
                    "and must be declared in the plan",
                    segment_index=index,
                )
            )
            entry["on_grid"] = False
            segments_out.append(entry)
            continue
        if not isinstance(frames, int) or isinstance(frames, bool):
            issues.append(
                _issue(
                    "frames_not_integer",
                    f"segment {index}: 'frames' must be an integer, "
                    f"got {frames!r}",
                    segment_index=index,
                )
            )
            entry["on_grid"] = False
            segments_out.append(entry)
            continue
        if frames < GRID_BASE:
            issues.append(
                _issue(
                    "frames_below_grid",
                    f"segment {index}: {frames} frames is below the "
                    f"grid base of {GRID_BASE}",
                    segment_index=index,
                )
            )
            entry["on_grid"] = False
            segments_out.append(entry)
            continue
        on_grid = is_on_grid(frames)
        entry["on_grid"] = on_grid
        if not on_grid:
            detail = (
                f"segment {index}: {frames} frames is not on the "
                f"5+17k grid (neighbours {snap_down(frames)} / "
                f"{snap_up(frames)}); snap at compile time and "
                "declare 'snapped_from'"
            )
            if route == "fasth3" and frames == 318:
                detail += (
                    "; the fasth3 route's 318 frames for 13.268s "
                    "are off grid by construction (311/328 are the "
                    "grid neighbours) -- do not confuse this with "
                    "the h3 route's 328"
                )
            issues.append(
                _issue(
                    "off_grid",
                    detail,
                    segment_index=index,
                    snap_down=snap_down(frames),
                    snap_up=snap_up(frames),
                )
            )
        elif segment.get("snapped_from") is not None and not segment.get("snapped"):
            issues.append(
                _issue(
                    "snap_undeclared",
                    f"segment {index}: 'snapped_from' is declared but "
                    "'snapped' is not true; a snapped count must be "
                    "declared as snapped",
                    segment_index=index,
                )
            )
        segments_out.append(entry)
    return {
        "ok": not issues,
        "route": route,
        "issues": issues,
        "segments": segments_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_continuation_grid(params.get("plan"))
    report_path = out_dir / "continuation_grid_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_continuation_grid_gate_capabilities_once() -> list[str]:
    """Register ``qa.continuation_grid_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.continuation_grid_gate",
            kind="line",
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
                "Continuation grid gate: judge a relay plan's frame "
                "counts against the 5+17k grid, with fasth3 and h3 "
                "route calibres kept separate. Snapping must be "
                "declared at compile time; execution-time cropping "
                "fails. Judges plans only; no generation, no keys."
            ),
            line="qa",
        )
    )
    return ["qa.continuation_grid_gate"]


register_continuation_grid_gate_capabilities_once()
