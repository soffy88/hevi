"""Preview-to-video pipeline schema (``video.preview_to_video_pipeline_schema``).

Fake-level contract for the two-stage creation loop: a topic
becomes an interactive HTML preview, the preview is reviewed
and revised, and only then a video HTML is produced and
rendered to MP4. The contract carries the cost estimate for
the paid generation step and the pinned HyperFrames version,
so the pipeline cannot be declared without a budget or an
unpinned renderer. It calls no model, renders nothing, and
starts no browser: every compiled contract declares
``executed_here: false`` and ``output_file: None``.

Clean-room restatement of the pipeline method (see
``AETHERVIZ_G4_G5_ATTRIBUTION.md``). The paid step is
blocked by ``qa.paid_generation_cost_gate`` until a key and
a budget are approved; this contract alone authorizes no
call.
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

STAGES: tuple[str, ...] = (
    "topic",
    "interactive_html",
    "video_html",
    "mp4",
)

# Single-film cost ceiling in USD; matches qa.paid_generation_cost_gate.
COST_CAP_USD = 0.50


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def compile_preview_to_video_pipeline(plan: Any) -> dict[str, Any]:
    """Compile one preview-to-video pipeline contract.

    ``plan`` carries ``topic`` (non-empty string),
    ``interactive_html``, ``video_html`` and ``mp4`` (each
    ``{present: true}``), ``cost_estimate_usd`` (a number at
    or below the $0.50 single-film cap), and
    ``hyperframes_version`` (pinned version string). Raises
    :class:`CapabilityError` on any shape violation. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("preview-to-video pipeline plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("pipeline claims are refused here; this contract executes nothing")
    topic = plan.get("topic")
    if not _is_nonempty_str(topic):
        raise CapabilityError("topic must be a non-empty string")
    for stage in ("interactive_html", "video_html", "mp4"):
        step = plan.get(stage)
        if not isinstance(step, dict) or step.get("present") is not True:
            raise CapabilityError(f"stage {stage!r} must be declared present")
    cost = plan.get("cost_estimate_usd")
    if not _is_number(cost):
        raise CapabilityError("cost_estimate_usd must be declared before any paid step")
    if cost > COST_CAP_USD:
        raise CapabilityError(
            f"cost_estimate_usd ${cost} exceeds the single-film cap ${COST_CAP_USD}"
        )
    version = plan.get("hyperframes_version")
    if not _is_nonempty_str(version):
        raise CapabilityError("hyperframes_version must be pinned")
    return {
        "contract": "preview-to-video-pipeline",
        "topic": topic,
        "stages": list(STAGES),
        "cost_estimate_usd": cost,
        "hyperframes_version": version,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_preview_to_video_pipeline(params.get("plan"))
    contract_path = out_dir / "preview_to_video_pipeline_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "stages": contract["stages"],
            "executed_here": False,
        },
    )


def register_preview_to_video_pipeline_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.preview_to_video_pipeline_schema",
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
            layer="obase",
            line="video",
            description=(
                "preview-to-video pipeline contract (fake): topic to "
                "interactive HTML to video HTML to MP4, with cost "
                "estimate and pinned HyperFrames version; shape only, "
                "never executed here."
            ),
        )
    )
    return ["video.preview_to_video_pipeline_schema"]


__all__ = [
    "COST_CAP_USD",
    "STAGES",
    "compile_preview_to_video_pipeline",
    "register_preview_to_video_pipeline_schema_capabilities_once",
]
