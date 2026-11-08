"""Camera duration/grid advisory (``qa.camera_duration_advisory``).

Advisory only: for one camera movement and one provider from
``model_catalog_data/duration_tiers.json``, suggest a shot
duration inside that provider's verified tier and, where the
provider has a verified frame basis, a frame count snapped to
the H3 frame lattice (17k + 5 frames at 24fps, from
``pure_helpers``). Suggestions are not gates and not render
promises: ``advisory_only`` is always true and
``verified_by_hevi_render`` is always false; real effect on
any model needs GPU verification in a separate case.

No duration is invented. A provider absent from the tier table,
or present with no verified caps, yields no numeric suggestion
at all. The site catalogue itself carries no duration field,
so every number here comes from hevi's own tier table, never
from the site. Frame suggestions are given only for
``fasth3_local``, the one tier whose frame basis is recorded
in the table (124-360 frames); other providers get seconds
only. See CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.cinematic_techniques import get_movement
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.pure_helpers import (
    H3_FPS,
    H3_FRAME_OFFSET,
    H3_FRAME_STEP,
)
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_TIERS_PATH = (
    Path(__file__).resolve().parent / "model_catalog_data" / "duration_tiers.json"
)
_TIERS_CACHE: dict[str, Any] | None = None

# Advisory classes, by movement id. Fast snap movements suit a
# short beat; full-circle and scale-crossing movements suit a
# long segment; time-lapse additionally needs a declared
# compression ratio. Everything else takes the tier midpoint.
_SHORT_BEAT: frozenset[str] = frozenset(
    {
        "whip_pan_right",
        "whip_pan_left",
        "crash_zoom_in",
        "crash_zoom_out",
        "fast_zoom_in",
        "fast_zoom_out",
    }
)
_LONG_SEGMENT: frozenset[str] = frozenset(
    {
        "orbit_clockwise",
        "orbit_counterclockwise",
        "earth_zoom_out",
        "infinite_zoom",
    }
)
_TIME_CLASS: frozenset[str] = frozenset({"time_lapse"})

# Frame basis is recorded in the tier table only for this
# provider (MIN_FRAMES=124, MAX_FRAMES=360 at 24fps).
_FRAME_BASIS_PROVIDER = "fasth3_local"
_FRAME_MIN = 124
_FRAME_MAX = 360


def _load_tiers() -> dict[str, Any]:
    global _TIERS_CACHE
    if _TIERS_CACHE is None:
        _TIERS_CACHE = json.loads(_TIERS_PATH.read_text(encoding="utf-8"))
    return _TIERS_CACHE


def _movement_class(movement_id: str) -> str:
    if movement_id in _SHORT_BEAT:
        return "short_beat"
    if movement_id in _LONG_SEGMENT:
        return "long_segment"
    if movement_id in _TIME_CLASS:
        return "time_class"
    return "mid_tier"


def _snap_to_lattice(frames: int) -> int:
    """Snap a frame count down to the H3 lattice (17k + 5)."""
    if frames <= H3_FRAME_OFFSET:
        return H3_FRAME_OFFSET
    steps = (frames - H3_FRAME_OFFSET) // H3_FRAME_STEP
    return H3_FRAME_OFFSET + H3_FRAME_STEP * steps


def _lattice_frames(seconds: float) -> int:
    frames = _snap_to_lattice(int(round(seconds * H3_FPS)))
    if frames < _FRAME_MIN:
        frames = _FRAME_MIN
    if frames > _FRAME_MAX:
        frames = _snap_to_lattice(_FRAME_MAX)
    return frames


def advise(
    movement_id: Any,
    provider: str = "fasth3_local",
    *,
    compression_ratio: Any = None,
    requested_s: Any = None,
) -> dict[str, Any]:
    """Return a duration/grid advisory for one movement.

    Raises :class:`CapabilityError` for an unknown movement id.
    Unknown providers and tiers without verified caps return an
    advisory with no numeric suggestion instead of raising.
    """
    if not isinstance(movement_id, str):
        raise CapabilityError("movement id must be a string")
    try:
        movement = get_movement(movement_id)
    except CapabilityError:
        raise CapabilityError(
            f"unknown camera movement id {movement_id!r}"
        ) from None
    tiers = _load_tiers()["tiers"]
    tier = tiers.get(provider)
    movement_class = _movement_class(movement_id)
    base: dict[str, Any] = {
        "movement_id": movement_id,
        "name_en": movement.get("name_en"),
        "category": movement.get("category"),
        "movement_class": movement_class,
        "provider": provider,
        "advisory_only": True,
        "verified_by_hevi_render": False,
        "grid_note": (
            f"H3 frame lattice {H3_FRAME_STEP}k + {H3_FRAME_OFFSET} "
            f"frames at {H3_FPS}fps (pure_helpers)"
        ),
    }
    if not isinstance(tier, dict) or tier.get("max_shot_s") is None:
        base.update(
            {
                "tier_status": "unknown",
                "tier_source": None,
                "suggested_duration_s": None,
                "suggested_frames": None,
                "note": (
                    "no verified duration tier for this provider; "
                    "no duration is suggested"
                ),
            }
        )
        return base
    min_s = tier.get("min_shot_s")
    max_s = tier.get("max_shot_s")
    if movement_class == "short_beat":
        suggested = min_s if min_s is not None else None
    elif movement_class == "long_segment":
        suggested = max_s
    elif min_s is not None:
        suggested = (min_s + max_s) / 2.0
    else:
        suggested = max_s
    if requested_s is not None:
        if not isinstance(requested_s, (int, float)) or isinstance(
            requested_s, bool
        ):
            raise CapabilityError("requested_s must be a number")
        suggested = float(requested_s)
        if min_s is not None:
            suggested = max(min_s, suggested)
        suggested = min(max_s, suggested)
    frames: int | None = None
    if suggested is not None and provider == _FRAME_BASIS_PROVIDER:
        frames = _lattice_frames(float(suggested))
    needs_declaration = False
    if movement_class == "time_class":
        if compression_ratio is None:
            needs_declaration = True
        elif not isinstance(compression_ratio, (int, float)) or isinstance(
            compression_ratio, bool
        ) or compression_ratio <= 1:
            raise CapabilityError(
                "compression_ratio must be a number greater than 1"
            )
    base.update(
        {
            "tier_status": "known",
            "tier_source": tier.get("source"),
            "tier_min_s": min_s,
            "tier_max_s": max_s,
            "suggested_duration_s": suggested,
            "suggested_frames": frames,
            "frame_basis": (
                "fasth3_local MIN/MAX_FRAMES (124-360)"
                if provider == _FRAME_BASIS_PROVIDER
                else "no verified frame basis for this provider; "
                "seconds only"
            ),
            "needs_time_compression_declaration": needs_declaration,
            "compression_ratio": compression_ratio,
            "note": (
                "advisory only; real effect on any model is "
                "unverified and needs GPU verification"
                if not needs_declaration
                else "time-lapse needs a declared compression "
                "ratio before this advisory is complete"
            ),
        }
    )
    return base


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    advisory = advise(
        params.get("movement_id"),
        params.get("provider", "fasth3_local"),
        compression_ratio=params.get("compression_ratio"),
        requested_s=params.get("requested_s"),
    )
    advisory_path = out_dir / "camera_duration_advisory.json"
    advisory_path.write_text(
        json.dumps(advisory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(advisory_path),
        qa={"advisory_json": str(advisory_path), "advisory_only": True},
    )


def register_camera_duration_advisory_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.camera_duration_advisory",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "movement_id": {"type": "string"},
                    "provider": {"type": "string"},
                    "compression_ratio": {"type": ["number", "null"]},
                    "requested_s": {"type": ["number", "null"]},
                },
                "required": ["movement_id"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Camera duration/grid advisory (advisory only): "
                "a tier-bound duration suggestion, with lattice-"
                "snapped frames only where a frame basis is "
                "verified; no render promise is made."
            ),
        )
    )
    return ["qa.camera_duration_advisory"]


__all__ = [
    "advise",
    "register_camera_duration_advisory_capabilities_once",
]
