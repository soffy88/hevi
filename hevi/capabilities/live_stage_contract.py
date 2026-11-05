"""Live stage contract (``video.live_stage_contract``).

Fake-level contract for a live stage console plan of the kind
described in the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): five zones, quick commands,
song queue, reference images, recording and a statistics
panel. Reference images change the picture only and never the
identity of the digital human. The contract certifies the
shape of the plan only. It builds no page and opens no
session: every compiled contract declares ``executed_here:
false`` and ``page_built: false``. Whether a stage actually
runs is a question for a real key/GPU/real-machine case.
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

ZONES: frozenset[str] = frozenset(
    {"quick_commands", "song_queue", "reference_images", "recording", "stats_panel"}
)


def compile_live_stage_contract(plan: Any) -> dict[str, Any]:
    """Compile one live stage console contract.

    ``plan`` carries ``zones`` (exactly the five zones),
    ``quick_commands`` (a non-empty list of ``{label, action}``
    entries), ``song_queue`` (enabled flag),
    ``reference_images`` (enabled flag plus a declaration that
    identity is unchanged), ``recording`` (server-side and
    manual-fetch flags) and ``stats_panel`` (draggable and
    reset-on-double-click flags). Raises
    :class:`CapabilityError` on any shape violation or on any
    claim that a page was built or a session ran here. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("live stage plan must be an object")
    if plan.get("executed_here") is True or plan.get("page_built") is True:
        raise CapabilityError("stage claims are refused here; this contract builds no page")
    zones = plan.get("zones")
    if not isinstance(zones, list):
        raise CapabilityError("live stage plan requires a zones list")
    unknown = [zone for zone in zones if zone not in ZONES]
    if unknown:
        raise CapabilityError(f"unknown stage zone: {unknown[0]}")
    missing = sorted(ZONES - set(zones))
    if missing:
        raise CapabilityError(f"stage zone missing: {missing[0]}")
    commands = plan.get("quick_commands")
    if not isinstance(commands, list) or not commands:
        raise CapabilityError("live stage plan needs a non-empty quick_commands list")
    for position, command in enumerate(commands):
        if not isinstance(command, dict):
            raise CapabilityError(f"quick command {position} must be an object")
        if not isinstance(command.get("label"), str) or not command["label"].strip():
            raise CapabilityError(f"quick command {position} needs a label")
        if not isinstance(command.get("action"), str) or not command["action"].strip():
            raise CapabilityError(f"quick command {position} needs an action")
    song_queue = plan.get("song_queue")
    if not isinstance(song_queue, dict) or not isinstance(song_queue.get("enabled"), bool):
        raise CapabilityError("live stage plan requires a song_queue enabled flag")
    reference_images = plan.get("reference_images")
    if not isinstance(reference_images, dict):
        raise CapabilityError("live stage plan requires a reference_images object")
    if not isinstance(reference_images.get("enabled"), bool):
        raise CapabilityError("reference_images enabled must be a boolean")
    if reference_images.get("declares_identity_unchanged") is not True:
        raise CapabilityError(
            "reference images must declare that the digital human identity "
            "is unchanged; they change the picture only"
        )
    recording = plan.get("recording")
    if not isinstance(recording, dict):
        raise CapabilityError("live stage plan requires a recording object")
    if not isinstance(recording.get("server_side"), bool):
        raise CapabilityError("recording server_side must be a boolean")
    if not isinstance(recording.get("manual_fetch"), bool):
        raise CapabilityError("recording manual_fetch must be a boolean")
    stats_panel = plan.get("stats_panel")
    if not isinstance(stats_panel, dict):
        raise CapabilityError("live stage plan requires a stats_panel object")
    if not isinstance(stats_panel.get("draggable"), bool):
        raise CapabilityError("stats_panel draggable must be a boolean")
    if not isinstance(stats_panel.get("reset_on_double_click"), bool):
        raise CapabilityError("stats_panel reset_on_double_click must be a boolean")
    return {
        "contract": "live-stage",
        "zones": sorted(ZONES),
        "quick_commands": len(commands),
        "song_queue_enabled": song_queue["enabled"],
        "reference_images_enabled": reference_images["enabled"],
        "recording_server_side": recording["server_side"],
        "executed_here": False,
        "page_built": False,
        "stage_case": "separate_key_gpu_case",
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_live_stage_contract(params.get("plan"))
    report_path = out_dir / "live_stage_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "quick_commands": report["quick_commands"],
            "executed_here": False,
        },
    )


def register_live_stage_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.live_stage_contract",
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
            description=(
                "Live stage contract (fake): five zones, quick "
                "commands, song queue, reference images that never "
                "change identity, recording and a statistics panel; "
                "no page is built and no session runs here."
            ),
        )
    )
    return ["video.live_stage_contract"]


__all__ = [
    "ZONES",
    "compile_live_stage_contract",
    "register_live_stage_contract_capabilities_once",
]
