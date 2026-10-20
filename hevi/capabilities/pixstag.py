"""PixStag external render capability (live-action story films).

Registers ``video.pixstag_generate`` so every product line can call the PixStag
v2 video API by name (CAPABILITY_CONTRACT.md; precedent: ``.multimodel``).
PixStag hosts MiniMax-H3 / doubao-seedance behind one endpoint; auth is
``PIXSTAG_API_KEY`` env (``Authorization: Bearer``, verified against
https://pixstag.com/docs/api). Missing key or API errors raise
``CapabilityError`` - never a fake success.

Division of labour for story-to-film (Soffy's call, 2026-10-20):
hevi owns the whole pre-production flow (story -> storyboard -> character
sheets -> shot packages). For live-action story films the *final render* is
delegated to this capability: each shot is handed over as a "shot package"
(first_frame image + motion prompt + duration) and rendered here, shot by
shot, into mp4 clips that hevi then assembles (HyperFrames) into the master.

Shot-package handoff contract for the story-to-film skill:
  prompt: motion/acting prompt in Chinese (describe camera move + performance)
  first_frame_path: local jpg/png <=3MB, the locked shot's key frame
  duration: integer 4..30s
  ratio/resolution: match the film's target (default 9:16, 720P)

Billing: 720P = 1 credit/second; credits expire (~31 days) - the render
sidecar reports the balance snapshot when ``me()`` succeeds.
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

_PIXSTAG_COST_NOTE = (
    "Billed in PixStag credits against the account balance (720P = 1 credit/sec; "
    "credits expire ~31 days). Sidecar reports the estimated credit spend and "
    "the account balance when available."
)


def _render_pixstag_generate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.video import pixstag_client

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clip_path = out_dir / "clip.mp4"
    sidecar = out_dir / "pixstag_sidecar.json"

    first = params.get("first_frame_path")
    last = params.get("last_frame_path")
    try:
        result = pixstag_client.generate_clip(
            prompt=str(params["prompt"]),
            output_path=clip_path,
            model=str(params.get("model", "MiniMax-H3")),
            duration=int(params.get("duration", 5)),
            ratio=str(params.get("ratio", "9:16")),
            resolution=str(params.get("resolution", "720P")),
            first_frame=first,
            last_frame=last,
            reference_images=list(params.get("reference_image_paths") or []),
            use_context_ir=bool(params.get("use_context_ir", False)),
            aigc_watermark=bool(params.get("aigc_watermark", False)),
            return_last_frame=bool(params.get("return_last_frame", False)),
        )
    except pixstag_client.PixStagError as exc:
        raise CapabilityError(f"video.pixstag_generate: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"video.pixstag_generate failed: {exc}") from exc

    balance: dict[str, Any] = {}
    try:
        info = pixstag_client.me()
        balance = {
            "credit": info.get("credit"),
            "credit_frozen": info.get("credit_frozen"),
            "credit_expires_at_utc": pixstag_client.credit_expiry_iso(info),
        }
    except pixstag_client.PixStagError:
        balance = {"error": "user/me unavailable"}

    payload = {
        "task_id": result["task_id"],
        "model": result["model"],
        "duration": result["duration"],
        "ratio": result["ratio"],
        "resolution": result["resolution"],
        "usage": result["usage"],
        "credit_estimate": result["credit_estimate"],
        "usd_estimate": result["usd_estimate"],
        "poster_url": result["poster_url"],
        "last_frame_url": result["last_frame_url"],
        "balance": balance,
        "params": {k: v for k, v in params.items() if "path" not in k},
        "cost_note": _PIXSTAG_COST_NOTE,
    }
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    duration_s = float(result.get("usage", {}).get("total_seconds") or result["duration"])
    return CapabilityResult(
        mp4=str(clip_path),
        duration_s=duration_s,
        sha256=compute_sha256(clip_path),
        qa={
            "task_id": result["task_id"],
            "credit_estimate": result["credit_estimate"],
            "usd_estimate": result["usd_estimate"],
            "balance": balance,
            "sidecar_json": str(sidecar),
            "note": _PIXSTAG_COST_NOTE,
        },
    )


def register_pixstag_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    register(
        Capability(
            name="video.pixstag_generate",
            kind="shot",
            aspects=["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"],
            params_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Motion/acting prompt in Chinese (required by PixStag)",
                    },
                    "model": {
                        "type": "string",
                        "enum": ["MiniMax-H3", "doubao-seedance-2", "doubao-seedance-2-5"],
                        "default": "MiniMax-H3",
                    },
                    "duration": {
                        "type": "integer",
                        "minimum": 4,
                        "maximum": 30,
                        "default": 5,
                    },
                    "ratio": {
                        "type": "string",
                        "enum": ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
                        "default": "9:16",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["720P", "768P", "1080P", "2K"],
                        "default": "720P",
                    },
                    "first_frame_path": {
                        "type": "string",
                        "description": "Local jpg/png (<=3MB) or http(s) URL: opening frame",
                    },
                    "last_frame_path": {
                        "type": "string",
                        "description": "Local jpg/png (<=3MB) or http(s) URL: ending frame (pairs with first_frame)",
                    },
                    "reference_image_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 8,
                        "description": "Reference images (multi-modal reference mode)",
                    },
                    "use_context_ir": {
                        "type": "boolean",
                        "default": False,
                        "description": "Context-IR prompt enhancement (better quality, slower)",
                    },
                    "aigc_watermark": {"type": "boolean", "default": False},
                    "return_last_frame": {"type": "boolean", "default": False},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,  # cloud render; local cost is poll + download only
            render=_render_pixstag_generate,
            description=(
                "PixStag v2 external video render (MiniMax-H3 / doubao-seedance, via "
                "https://pixstag.com). Live-action story films: hevi produces shot "
                "packages (first frame + motion prompt + duration) and this renders "
                "each shot to mp4. Needs PIXSTAG_API_KEY; billed in credits (720P=1/s)."
            ),
            line="livefilm",
        )
    )
    return ["video.pixstag_generate"]
