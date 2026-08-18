"""Novel2Video 规划:层次分解后每场走内核。"""

from __future__ import annotations

from hevi.script2video.adapter_schemas import LengthBudget, NovelPlan
from hevi.script2video.omodul.kernel_plan import plan_kernel_artifacts
from hevi.script2video.oskill.novel_adapt import plan_novel_adaptation


def plan_novel2video(novel_text: str, *, budget: LengthBudget | None = None) -> NovelPlan:
    compressed, ratio, events, scenes, book = plan_novel_adaptation(novel_text, budget=budget)
    kernels = [
        plan_kernel_artifacts(
            [
                {
                    "idx": 0,
                    "visual_desc": scene.script,
                    "cam_key": f"e{scene.event_index}_s{scene.idx}",
                    "environment": scene.slugline,
                    "visible_chars": [char.name for char in scene.characters],
                }
            ],
            [
                {
                    "name": char.name,
                    "identifier": char.identifier,
                    "description": char.description,
                }
                for char in scene.characters
            ],
        )
        for scene in scenes
    ]
    return NovelPlan(
        original_chars=len(novel_text),
        compressed=compressed,
        compression_ratio=ratio,
        events=events,
        scenes=scenes,
        book=book,
        scene_kernels=kernels,
    )
