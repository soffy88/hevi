"""Pure validation and budget primitives for a causal video stream."""

from __future__ import annotations

from typing import Any

CONTROL_TYPES = ("start", "frame", "end", "heartbeat")
MAX_WIDTH = 2048
MAX_HEIGHT = 2048


def validate_control(message: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    kind = str(message.get("type") or "")
    if kind not in CONTROL_TYPES:
        errors.append(f"unknown stream message type: {kind or '<empty>'}")
    if kind == "start":
        prompt = str(message.get("prompt") or "").strip()
        if not prompt:
            errors.append("start.prompt is required")
        for field, minimum, maximum in (
            ("width", 160, MAX_WIDTH),
            ("height", 160, MAX_HEIGHT),
            ("fps", 1, 60),
        ):
            try:
                value = int(message.get(field) or (840 if field == "width" else 480 if field == "height" else 24))
            except (TypeError, ValueError):
                errors.append(f"{field} must be an integer")
                continue
            if not minimum <= value <= maximum:
                errors.append(f"{field} must be {minimum}..{maximum}")
    if kind == "frame" and not (message.get("index") is not None or message.get("timestamp_ms") is not None):
        errors.append("frame.index or frame.timestamp_ms is required")
    return errors


def frame_budget(*, width: int, height: int, fps: int, seconds: float = 1.0) -> dict[str, Any]:
    """Estimate raw RGBA ingress/egress pressure for admission control."""

    frames = max(1, round(max(0.0, seconds) * fps))
    bytes_per_frame = max(1, width) * max(1, height) * 4
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "seconds": seconds,
        "frames": frames,
        "bytes_per_frame": bytes_per_frame,
        "raw_bytes": frames * bytes_per_frame,
        "raw_mib": round(frames * bytes_per_frame / 1024 / 1024, 3),
        "policy": "bounded session buffer; downstream provider owns encoded frame format",
    }


__all__ = ["CONTROL_TYPES", "MAX_HEIGHT", "MAX_WIDTH", "frame_budget", "validate_control"]
