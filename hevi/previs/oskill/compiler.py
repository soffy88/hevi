"""Small deterministic camera command vocabulary for natural-language controls."""

from __future__ import annotations

import re

from hevi.previs.oprim.contracts import CameraCue


def camera_from_instruction(instruction: str, *, cue_id: str = "camera-1", time_s: float = 0.0) -> CameraCue:
    text = instruction.lower()
    movement = "static"
    for token, value in (
        ("推近", "dolly_in"),
        ("dolly in", "dolly_in"),
        ("拉远", "dolly_out"),
        ("左移", "tracking_left"),
        ("右移", "tracking_right"),
        ("环绕", "orbital"),
        ("orbit", "orbital"),
        ("摇镜", "pan_right"),
    ):
        if token in instruction or token in text:
            movement = value
            break
    shot_size = "close_up" if any(token in instruction for token in ("特写", "近景")) else "wide" if "远景" in instruction else "medium"
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:度|deg)", instruction, re.I)
    azimuth = float(match.group(1)) if match else 0.0
    return CameraCue(cue_id=cue_id, time_s=time_s, shot_size=shot_size, movement=movement, azimuth_deg=azimuth)


__all__ = ["camera_from_instruction"]
