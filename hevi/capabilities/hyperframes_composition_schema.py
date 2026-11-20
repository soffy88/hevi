"""HyperFrames composition schema (``video.hyperframes_composition_schema``).

Fake-level contract for one HyperFrames composition driven
by a GSAP timeline: a ``data-composition-id``, a duration,
a track list, and the single timeline mounted at
``window.__timelines['main']``. This is a different layer
from the two HyperFrames capabilities hevi already has:
``video.hyperframes_styles`` is the style catalogue (18
styles) and ``video.hyperframes_styled_render`` renders
beats JSON plus a style id. Neither of them certifies a
GSAP-timeline composition, and this contract certifies
nothing else: no style is chosen here, no frame is
rendered, and no timeline runs. Every compiled contract
declares ``executed_here: false`` and ``output_file: None``.

Clean-room restatement of the composition method (see
``AETHERVIZ_G4_G5_ATTRIBUTION.md``).
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

TIMELINES_MOUNT = "window.__timelines['main']"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def compile_hyperframes_composition(plan: Any) -> dict[str, Any]:
    """Compile one HyperFrames composition contract.

    ``plan`` carries ``composition_id`` (the
    ``data-composition-id`` value), ``duration_s`` (positive
    number), ``tracks`` (a non-empty list of ``{id, kind}``),
    ``timelines_mount`` (must be
    ``"window.__timelines['main']"``), and optional
    ``segments`` (``{id, duration_s}`` entries whose durations
    must sum to ``duration_s``). Raises
    :class:`CapabilityError` on any shape violation. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("hyperframes composition plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("composition claims are refused here; this contract renders nothing")
    composition_id = plan.get("composition_id")
    if not _is_nonempty_str(composition_id):
        raise CapabilityError("composition_id (data-composition-id) must be a non-empty string")
    duration_s = plan.get("duration_s")
    if not _is_number(duration_s) or duration_s <= 0:
        raise CapabilityError("duration_s must be a positive number")
    tracks = plan.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise CapabilityError("a non-empty tracks list is required")
    track_ids: list[str] = []
    for index, track in enumerate(tracks):
        if not isinstance(track, dict):
            raise CapabilityError(f"tracks[{index}] must be an object")
        if not _is_nonempty_str(track.get("id")):
            raise CapabilityError(f"tracks[{index}] must carry a non-empty id")
        if not _is_nonempty_str(track.get("kind")):
            raise CapabilityError(f"tracks[{index}] must carry a non-empty kind")
        track_ids.append(track["id"])
    if plan.get("timelines_mount") != TIMELINES_MOUNT:
        raise CapabilityError(f"timelines_mount must be {TIMELINES_MOUNT!r}")
    segments = plan.get("segments")
    if segments is not None:
        if not isinstance(segments, list) or not segments:
            raise CapabilityError("segments must be a non-empty list")
        total = 0.0
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                raise CapabilityError(f"segments[{index}] must be an object")
            duration = segment.get("duration_s")
            if not _is_number(duration) or duration <= 0:
                raise CapabilityError(f"segments[{index}] duration_s must be positive")
            total += duration
        if abs(total - duration_s) > 1e-9:
            raise CapabilityError(f"segment durations sum to {total}, not duration_s {duration_s}")
    return {
        "contract": "hyperframes-composition",
        "composition_id": composition_id,
        "duration_s": duration_s,
        "tracks": track_ids,
        "timelines_mount": TIMELINES_MOUNT,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_hyperframes_composition(params.get("plan"))
    contract_path = out_dir / "hyperframes_composition_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "tracks": contract["tracks"],
            "executed_here": False,
        },
    )


def register_hyperframes_composition_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.hyperframes_composition_schema",
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
                "HyperFrames composition contract (fake): "
                "data-composition-id, duration, tracks, and the "
                "single GSAP timeline at "
                "window.__timelines['main']; GSAP-timeline composition "
                "only, not the styles catalogue nor the styled render."
            ),
        )
    )
    return ["video.hyperframes_composition_schema"]


__all__ = [
    "TIMELINES_MOUNT",
    "compile_hyperframes_composition",
    "register_hyperframes_composition_schema_capabilities_once",
]
