from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from oskill._schemas import Script, SubjectRef
from oskill.character_consistency_workflow import (
    CharacterConsistencyResult,
    character_consistency_workflow,
)
from oskill.comic_to_animation_workflow import comic_to_animation_workflow
from oskill.multi_shot_storyboard_workflow import (
    MultiShotStoryboard,
    multi_shot_storyboard_workflow,
)

_VALID_GRID_SIZES: frozenset[int] = frozenset({9, 25})


class WorkflowService:
    """Business layer — 3 oskill creative workflow operations."""

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    async def run_character_consistency(
        self,
        *,
        portrait_image: Path,
        scene_descriptions: list[str],
        image_provider: str,
        output_dir: Path,
    ) -> CharacterConsistencyResult:
        if not scene_descriptions:
            raise ValueError("scene_descriptions must not be empty")
        return await character_consistency_workflow(
            portrait_image=portrait_image,
            scene_descriptions=scene_descriptions,
            llm=self._llm,
            image_provider=image_provider,
            output_dir=output_dir,
        )

    async def run_storyboard_workflow(
        self,
        *,
        script: Script,
        subjects: list[SubjectRef],
        image_provider: str,
        output_dir: Path,
        grid_size: Literal[9, 25] | None = 9,
        style: str | None = None,
        lighting: str | None = None,
    ) -> MultiShotStoryboard:
        return await multi_shot_storyboard_workflow(
            script=script,
            subjects=subjects,
            llm=self._llm,
            image_provider=image_provider,
            output_dir=output_dir,
            grid_size=grid_size,
            style=style,  # type: ignore[arg-type]
            lighting=lighting,  # type: ignore[arg-type]
        )

    async def run_comic_to_animation(
        self,
        *,
        comic_image: Path,
        image_provider: str,
        video_provider: str,
        output_path: Path,
    ) -> Path:
        return await comic_to_animation_workflow(
            comic_image=comic_image,
            llm=self._llm,
            image_provider=image_provider,
            video_provider=video_provider,
            output_path=output_path,
        )
