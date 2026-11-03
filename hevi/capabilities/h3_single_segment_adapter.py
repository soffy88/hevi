"""Single-segment H3 execution adapter, fake backend (``video.h3_single_segment_adapter``).

Clean-room restatement of the execution shape behind the
pixelaigc single-segment H3 workflow (see
``PIXELAIGC_H3_WORKFLOW_ATTRIBUTION.md``): an outer stage loads
an optional first frame and an optional last frame, hands them
plus a prompt to one nested segment process, and saves the
resulting video. The nested process, described here in hevi's
own words as a stage list rather than copied graph data, runs:
image-to-video conditioning, diffusion-model loading, text
encoder loading, video-VAE loading, audio-VAE loading, turbo
LoRA application, sampling, scheduling, guidance, noise
seeding, resolution selection, frame-count arithmetic, video
assembly, video decoding, and audio decoding. Three modes are
selected only by which frame inputs are supplied: both frames,
first frame only, or neither (text only).

This adapter is a **fake** backend: it builds and checks
execution plans and records, never contacts ComfyUI, never
loads weights, never generates. A real run waits on a GPU, a
ComfyUI install, the registered weights, and the turbo node
package, and is a separate decision. Missing frame inputs for
the declared mode, a mixed LoRA declaration, an off-grid frame
count, or stale inner defaults all fail loudly here; nothing
is silently guessed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hevi.capabilities.continuation_grid_gate import is_on_grid
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.h3_config_registration import (
    CONFIG_ID,
    INCOMPATIBLE_LORA_FAMILIES,
    check_h3_config,
)
from hevi.capabilities.h3_frame_align_gate import check_frame_alignment
from hevi.capabilities.h3_stale_defaults_gate import check_stale_defaults
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Stage list in hevi's own words. Functional roles only; no graph
# data, node identifiers, or wiring from any workflow file.
OUTER_STAGES = (
    "load_first_frame",
    "load_last_frame",
    "segment_subprocess",
    "save_video",
    "annotations",
)

SEGMENT_STAGES = (
    "image_to_video_conditioning",
    "diffusion_model_loading",
    "text_encoder_loading",
    "video_vae_loading",
    "audio_vae_loading",
    "turbo_lora_application",
    "sampling",
    "scheduling",
    "guidance",
    "noise_seeding",
    "resolution_selection",
    "frame_count_arithmetic",
    "video_assembly",
    "video_decoding",
    "audio_decoding",
)

MODES = ("first_last", "first_only", "text_only")


def _plan_sha(plan: dict[str, Any]) -> str:
    blob = json.dumps(plan, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_execution_plan(request: Any) -> dict[str, Any]:
    """Build a checked single-segment execution plan (no execution).

    ``request`` declares ``mode``, ``first_frame`` / ``last_frame``
    (booleans: the frame asset is supplied), ``config_id``,
    ``duration_s``, ``frames``, ``prompt_present``, and
    ``lora_families``. Every gate failure raises
    ``CapabilityError`` with the gate's own wording; nothing is
    silently repaired.
    """
    if not isinstance(request, dict):
        raise CapabilityError("video.h3_single_segment_adapter: request must be an object")
    mode = request.get("mode")
    if mode not in MODES:
        raise CapabilityError(
            f"video.h3_single_segment_adapter: mode must be one of {MODES}, got {mode!r}"
        )
    first = bool(request.get("first_frame"))
    last = bool(request.get("last_frame"))
    if mode == "first_last" and not (first and last):
        raise CapabilityError(
            "video.h3_single_segment_adapter: first_last mode requires "
            "both a first frame and a last frame"
        )
    if mode == "first_only" and (not first or last):
        raise CapabilityError(
            "video.h3_single_segment_adapter: first_only mode requires a "
            "first frame and no last frame"
        )
    if mode == "text_only" and (first or last):
        raise CapabilityError(
            "video.h3_single_segment_adapter: text_only mode requires "
            "neither a first frame nor a last frame"
        )
    if not request.get("prompt_present"):
        raise CapabilityError(
            "video.h3_single_segment_adapter: a prompt must be declared present"
        )
    if request.get("config_id") != CONFIG_ID:
        raise CapabilityError(
            "video.h3_single_segment_adapter: config_id must be "
            f"{CONFIG_ID!r}; no other configuration is adapted here"
        )
    for family in request.get("lora_families") or []:
        if family in INCOMPATIBLE_LORA_FAMILIES:
            raise CapabilityError(
                "video.h3_single_segment_adapter: turbo LoRA family "
                f"{family!r} must never be mixed with the registered LoRA"
            )
    alignment = check_frame_alignment(
        {
            "duration_s": request.get("duration_s"),
            "frames": request.get("frames"),
            "snap_direction": request.get("snap_direction", "up"),
            "declared_output_s": request.get("declared_output_s"),
        }
    )
    if not alignment["ok"]:
        raise CapabilityError(
            "video.h3_single_segment_adapter: frame alignment failed: "
            + "; ".join(i["detail"] for i in alignment["issues"])
        )
    if not is_on_grid(request.get("frames")):
        raise CapabilityError(
            "video.h3_single_segment_adapter: frame count is not on the 5+17k grid"
        )
    stale = request.get("stale_defaults_plan")
    if stale is not None:
        stale_report = check_stale_defaults(stale)
        if not stale_report["ok"]:
            raise CapabilityError(
                "video.h3_single_segment_adapter: stale inner defaults: "
                + "; ".join(i["detail"] for i in stale_report["issues"])
            )
    plan = {
        "backend": "fake",
        "config_id": CONFIG_ID,
        "mode": mode,
        "first_frame": first,
        "last_frame": last,
        "duration_s": request.get("duration_s"),
        "frames": request.get("frames"),
        "output_s": request.get("frames") / 24,
        "outer_stages": list(OUTER_STAGES),
        "segment_stages": list(SEGMENT_STAGES),
        "audio_input": False,
        "relay": False,
        "note": (
            "Audio is model-generated in this shape; no audio input "
            "is accepted and no relay is performed."
        ),
    }
    plan["plan_sha256"] = _plan_sha(plan)
    return plan


def execute_fake(plan: Any) -> dict[str, Any]:
    """Run a fake execution of a built plan and record the outcome.

    No ComfyUI call is made. The record states ``backend: fake``
    and ``artifact: null`` so a fake run can never be mistaken
    for a generated clip.
    """
    if not isinstance(plan, dict) or plan.get("backend") != "fake":
        raise CapabilityError(
            "video.h3_single_segment_adapter: execute_fake requires a plan "
            "built by build_execution_plan"
        )
    return {
        "backend": "fake",
        "plan_sha256": plan.get("plan_sha256"),
        "config_id": plan.get("config_id"),
        "mode": plan.get("mode"),
        "frames": plan.get("frames"),
        "output_s": plan.get("output_s"),
        "stages_checked": len(plan.get("outer_stages", []))
        + len(plan.get("segment_stages", [])),
        "artifact": None,
        "note": "Fake run only: no ComfyUI contact, no weights loaded, no video produced.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        plan = build_execution_plan(params.get("request"))
        record = execute_fake(plan)
    except CapabilityError as exc:
        record = {"ok": False, "error": str(exc), "backend": "fake"}
        plan = None
    payload = {"plan": plan, "fake_run": record}
    record_path = out_dir / "h3_single_segment_adapter.json"
    record_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(record_path),
        qa={"report_json": str(record_path),
            "verdict": "pass" if plan is not None else "fail"},
    )


def register_h3_single_segment_adapter_capabilities_once() -> list[str]:
    """Register ``video.h3_single_segment_adapter`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.h3_single_segment_adapter",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "request": {"type": "object"},
                },
                "required": ["request"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Single-segment H3 execution adapter, FAKE backend: "
                "build and check an execution plan in hevi's own "
                "stage vocabulary (outer frame loading, nested "
                "segment process, video save), with frame-grid, "
                "LoRA-mix, and stale-default checks. No ComfyUI, no "
                "weights, no generation; real runs wait on GPU."
            ),
            line="video",
        )
    )
    return ["video.h3_single_segment_adapter"]


register_h3_single_segment_adapter_capabilities_once()
