"""Single-segment frame alignment gate (``qa.h3_frame_align_gate``).

Clean-room restatement of the frame-count arithmetic behind the
pixelaigc single-segment H3 workflow (see
``PIXELAIGC_H3_WORKFLOW_ATTRIBUTION.md``): a requested duration
in seconds is converted to frames at 24 fps, floored at 5 frames,
and snapped **up** to the 5 + 17k grid. The grid rule itself is
owned by ``qa.continuation_grid_gate`` -- this module reuses its
``is_on_grid`` and ``snap_up`` and adds no second grid. Snapping
down, or declaring a frame count that is not the snapped-up
value, fails. Because snapping up lengthens the output, a plan
whose snapped length differs from the requested duration must
declare the actual output duration; an undeclared stretch fails.

This module judges plans only. It never generates, never calls a
model, and never re-implements latent or mask machinery.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hevi.capabilities.pure_helpers import (
    is_on_grid,
    snap_up,
)
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.pure_helpers import (
    FPS,
    GRID_FLOOR_FRAMES,
    _frame_align_issue as _issue,
    requested_frames,
    aligned_frames,
    check_frame_alignment,
)

_Registered = False











def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_frame_alignment(params.get("plan"))
    report_path = out_dir / "h3_frame_align_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_h3_frame_align_gate_capabilities_once() -> list[str]:
    """Register ``qa.h3_frame_align_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.h3_frame_align_gate",
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
                "Single-segment frame alignment gate: requested "
                "seconds convert to frames at 24 fps and snap UP to "
                "the 5+17k grid (grid owned by "
                "qa.continuation_grid_gate); any output stretch must "
                "be declared. Judges plans only; no generation."
            ),
            line="qa",
        )
    )
    return ["qa.h3_frame_align_gate"]


register_h3_frame_align_gate_capabilities_once()
