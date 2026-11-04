"""Stale inner-defaults isolation gate (``qa.h3_stale_defaults_gate``).

Clean-room restatement of the staleness discipline behind the
pixelaigc single-segment H3 workflow (see
``PIXELAIGC_H3_WORKFLOW_ATTRIBUTION.md``): a workflow file can
carry two layers of values -- the outer control panel the caller
actually sets, and older example values left inside a nested
sub-process. Only the outer panel is current. Any effective
configuration value that equals a nested inner default while
differing from the outer panel value is stale and fails; the
plan must be cleaned so the effective configuration comes from
the outer panel alone.

This gate compares caller-declared mappings only. It never reads
a workflow file, never copies example text, and never generates.
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
from hevi.capabilities.pure_helpers import (
    _stale_defaults_issue as _issue,
    check_stale_defaults,
)

_Registered = False






def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_stale_defaults(params.get("plan"))
    report_path = out_dir / "h3_stale_defaults_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_h3_stale_defaults_gate_capabilities_once() -> list[str]:
    """Register ``qa.h3_stale_defaults_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.h3_stale_defaults_gate",
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
                "Stale inner-defaults isolation gate: the effective "
                "configuration must come from the outer control "
                "panel; any value equal to a nested sub-process "
                "default that differs from the panel fails. Judges "
                "declared mappings only; never reads workflow files."
            ),
            line="qa",
        )
    )
    return ["qa.h3_stale_defaults_gate"]


register_h3_stale_defaults_gate_capabilities_once()
