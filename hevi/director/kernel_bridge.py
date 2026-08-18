"""ShotList → Script2Video 内核的确定性投影。

不改 produce() 行为;给导演流水线一个可调用的规划入口。
"""

from __future__ import annotations

from typing import Any

from hevi.director.pipeline_schemas import ShotList, ShotListItem
from hevi.script2video.omodul.kernel_plan import plan_kernel_artifacts
from hevi.script2video.schemas import KernelPlan


def kernel_shot_payload(shot: ShotListItem, *, index: int) -> dict[str, Any]:
    cam_key = (
        shot.camera_setup_ref
        or shot.camera
        or f"{shot.scene_name}:{shot.camera_angle}:{shot.shot_size}"
    )
    audio = ""
    if shot.audio_track and shot.audio_track.dialogue:
        audio = shot.audio_track.dialogue
    elif shot.dialogue_lines:
        audio = " ".join(
            f"{line.character_name}: {line.text}".strip(": ")
            for line in shot.dialogue_lines
            if line.text
        )
    facing = {item.character_name: item.facing for item in shot.blocking if item.facing}
    return {
        "idx": index,
        "visual_desc": shot.visual_prompt,
        "cam_key": cam_key,
        "environment": shot.scene_name,
        "visible_chars": list(shot.character_names),
        "audio_desc": audio,
        "facing_hints": facing,
        "azimuth_deg": shot.azimuth_deg,
        "action_beats": list(shot.action_beats),
    }


def plan_kernel_from_shot_list(
    shot_list: ShotList,
    *,
    characters: list[dict[str, Any]] | None = None,
) -> KernelPlan:
    payload = [kernel_shot_payload(shot, index=index) for index, shot in enumerate(shot_list.shots)]
    return plan_kernel_artifacts(payload, characters or [])

