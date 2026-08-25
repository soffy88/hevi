"""AutoCameo 规划:照片锁身份后并入角色表。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.script2video.adapter_schemas import CameoPlan
from hevi.script2video.oskill.autocameo import process_cameo_photos
from hevi.script2video.schemas import KernelCharacter


async def plan_autocameo(
    photos: list[Path],
    *,
    story_context: str = "",
    existing: list[KernelCharacter] | None = None,
    max_characters: int = 4,
    image_gen: Any = None,
    output_dir: Path | None = None,
    style: str = "cinematic",
) -> CameoPlan:
    plan = await process_cameo_photos(
        photos,
        story_context=story_context,
        max_characters=max_characters,
        image_gen=image_gen,
        output_dir=output_dir,
        style=style,
    )
    plan.merged_characters = [
        *plan.merged_characters,
        *[
            char
            for char in (existing or [])
            if char.identifier not in {item.identifier for item in plan.merged_characters}
        ],
    ]
    return plan
