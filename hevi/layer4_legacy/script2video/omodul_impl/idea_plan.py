"""Idea2Video 规划:编剧产物 + 每场内核 KernelPlan。"""

from __future__ import annotations

from hevi.layer4_legacy.script2video.omodul_impl.kernel_plan import plan_kernel_artifacts
from hevi.layer4_legacy.script2video.oskill_impl.idea_screenwrite import plan_idea_screenplay
from hevi.script2video.adapter_schemas import IdeaPlan


def plan_idea2video(idea: str, requirement: str = "", style: str = "") -> IdeaPlan:
    del style
    story, characters, scenes, _budget = plan_idea_screenplay(idea, requirement)
    char_payload = [
        {
            "name": char.name,
            "identifier": char.identifier,
            "description": char.description,
            "reference_photo": char.reference_photo,
            "is_visible": char.is_visible,
        }
        for char in characters
    ]
    kernels = [
        plan_kernel_artifacts(
            [
                {
                    "idx": 0,
                    "visual_desc": scene.script,
                    "cam_key": "master",
                    "environment": scene.environment,
                    "visible_chars": scene.characters,
                }
            ],
            char_payload,
        )
        for scene in scenes
    ]
    return IdeaPlan(
        story=story,
        characters=characters,
        scenes=scenes,
        scene_kernels=kernels,
    )
