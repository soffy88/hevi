"""Jianying draft adapter, fake layer (``video.jianying_draft_adapter``).

Contract-only adapter. Given a shot plan it compiles the export
contract for a real Jianying draft: baked plates carry baked motion,
subtitles and audio ride native editable tracks, segment boundaries
follow the round-each-endpoint rule, and the platform notes record
the Mac/Windows boundary honestly (the Mac path is upstream
self-reported as verified against one editor version; the Windows
path is recorded as not verified on real hardware). This module
executes nothing: ``executed_here`` is always false,
``draft_file`` is always null, and no editor is installed, probed,
or invoked. Real export is a separate case. No text, code, or asset
from any outside repository is copied here. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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

BOUNDARY_RULE = "round_each_endpoint_then_subtract"

# Platform boundary, recorded honestly: the Mac export path is
# upstream self-reported as verified against one editor version
# (not re-verified here); the Windows path is upstream-declared as
# not verified on real hardware.
MAC_STATUS = "upstream_self_reported_verified"
WINDOWS_STATUS = "not_verified_on_real_hardware"


def _fail(message: str) -> None:
    raise CapabilityError(message)


def compile_jianying_draft_contract(plan: Any) -> dict[str, Any]:
    """Compile an export contract from a shot plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false`` and
    ``draft_file: null``: nothing is exported here.
    """
    if not isinstance(plan, dict):
        _fail("draft plan must be a JSON object")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        _fail("draft plan must declare a non-empty shots list")
    clips: list[dict[str, Any]] = []
    cursor = 0
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            _fail(f"shots[{index}] must be an object")
        start = shot.get("start_frame")
        end = shot.get("end_frame")
        if not isinstance(start, int) or not isinstance(end, int):
            _fail(f"shots[{index}] must declare integer frame bounds")
        if start != cursor:
            _fail(
                f"shots[{index}] must start at frame {cursor}, got {start}"
            )
        if end <= start:
            _fail(f"shots[{index}] must cover at least one frame")
        clips.append(
            {
                "index": index,
                "shot_id": shot.get("shot_id"),
                "start_frame": start,
                "end_frame": end,
                "layer": "baked_plate",
                "baked_plate_clean": True,
            }
        )
        cursor = end
    subtitle_track = [
        {"index": i, "shot_id": c["shot_id"], "layer": "subtitle_native"}
        for i, c in enumerate(clips)
    ]
    audio_track = [
        {"index": i, "shot_id": c["shot_id"], "layer": "audio_native"}
        for i, c in enumerate(clips)
    ]
    return {
        "contract": "jianying_draft_export",
        "boundary_rule": BOUNDARY_RULE,
        "clips": clips,
        "subtitle_track": subtitle_track,
        "audio_track": audio_track,
        "total_frames": cursor,
        "platform": {
            "mac": {
                "status": MAC_STATUS,
                "notes": (
                    "draft descriptor entry, machine fingerprint, "
                    "and media packaged under Resources/"
                ),
            },
            "windows": {
                "status": WINDOWS_STATUS,
                "notes": "smoke-test before first real use",
            },
        },
        "one_way_conversion": True,
        "device_fingerprint_not_shared": True,
        "executed_here": False,
        "draft_file": None,
        "native_writer": "hevi.studio.jianying_native.write_native_draft",
        "native_writer_note": (
            "Real drafts are written by the native writer (pyJianYingDraft, "
            "Apache-2.0). This capability remains the contract/fake layer."
        ),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_jianying_draft_contract(params.get("plan"))
    contract_path = out_dir / "jianying_draft_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"report_json": str(contract_path), "executed_here": False},
    )


def register_jianying_draft_adapter_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.jianying_draft_adapter",
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
            layer="obase",
            description=(
                "Jianying draft adapter, fake layer: compiles the "
                "export contract (baked plates, native subtitle and "
                "audio tracks, boundary rule, honest Mac/Windows "
                "boundary); executed_here is always false and no "
                "draft file is produced."
            ),
        )
    )
    return ["video.jianying_draft_adapter"]


__all__ = [
    "BOUNDARY_RULE",
    "MAC_STATUS",
    "WINDOWS_STATUS",
    "compile_jianying_draft_contract",
    "register_jianying_draft_adapter_capabilities_once",
]
