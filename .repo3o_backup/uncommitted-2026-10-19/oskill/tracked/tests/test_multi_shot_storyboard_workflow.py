"""Tests for oskill.multi_shot_storyboard_workflow."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from obase import ProviderRegistry
from PIL import Image


@pytest.fixture(autouse=True)
def _clean() -> Any:
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


def _make_png(path: Path) -> None:
    img = Image.new("RGB", (10, 10), color=(64, 128, 192))
    img.save(path, "PNG")


def _register_image_gen(name: str = "mock_flux", fail_on: int | None = None) -> None:
    call_count = [0]

    async def _gen(**kw: Any) -> None:
        call_count[0] += 1
        if fail_on is not None and call_count[0] == fail_on:
            raise RuntimeError("image_gen failure")
        _make_png(Path(str(kw["output_path"])))

    ProviderRegistry.register(category="image_gen", name=name, fn=_gen)


def _make_script(n_scenes: int = 2) -> Any:
    from oskill._schemas import Scene, Script

    scenes = [
        Scene(
            index=i,
            narration=f"narration {i}",
            duration_s=5.0,
            visual_description=f"scene {i} visual description",
        )
        for i in range(n_scenes)
    ]
    return Script(
        title="Test",
        description="test script",
        scenes=scenes,
        estimated_duration_s=5.0 * n_scenes,
    )


def _make_adaptive_llm() -> Any:
    """LLM that returns N items when prompt says 'exactly N'."""

    def _llm(*, messages: Any, **kw: Any) -> dict[str, Any]:
        content = str(messages[0].get("content", "")) if messages else ""
        m = re.search(r"exactly (\d+)", content)
        n = int(m.group(1)) if m else 9
        return {"content": json.dumps([f"shot desc {i}" for i in range(n)])}

    return _llm


class TestMultiShotStoryboardWorkflow:
    async def test_normal_full_params(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import (
            MultiShotStoryboard,
            multi_shot_storyboard_workflow,
        )

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(2),
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=9,
            style="科普",
            lighting="暖",
        )
        assert isinstance(result, MultiShotStoryboard)
        assert result.grid_preview is not None
        assert result.grid_preview.exists()

    async def test_grid_size_none(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(2),
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=None,
        )
        assert result.grid_preview is None

    async def test_grid_size_9(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(2),
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=9,
        )
        assert result.grid_preview is not None
        assert result.grid_preview.exists()

    async def test_grid_size_25(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(2),
            subjects=[],
            llm=_make_adaptive_llm(),  # returns 25 items when prompt says "exactly 25"
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=25,
        )
        assert result.grid_preview is not None
        assert result.grid_preview.exists()

    async def test_style_none(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(1),
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=None,
            style=None,
        )
        # no style injection → visual_description unchanged (just "scene 0 visual description")
        assert "科普" not in result.shots[0]["visual_description"]

    async def test_style_injected(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(1),
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=None,
            style="科普",
        )
        assert "科普风格" in result.shots[0]["visual_description"]

    async def test_lighting_none(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(1),
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=None,
            lighting=None,
        )
        assert "lighting:" not in result.shots[0]["visual_description"]

    async def test_lighting_injected(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(1),
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=None,
            lighting="暖",
        )
        assert "lighting:" in result.shots[0]["visual_description"]

    async def test_empty_scenes_raises(self, tmp_path: Path) -> None:
        from oskill._schemas import Script
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        empty_script = Script(title="Empty", description="", scenes=[], estimated_duration_s=0.0)
        with pytest.raises(ValueError, match="empty"):
            await multi_shot_storyboard_workflow(
                script=empty_script,
                subjects=[],
                llm=_make_adaptive_llm(),
                image_provider="mock_flux",
                output_dir=tmp_path / "out",
            )

    async def test_subjects_empty_ok(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        result = await multi_shot_storyboard_workflow(
            script=_make_script(2),
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=None,
        )
        assert len(result.shots) == 2

    async def test_shots_count_matches_scenes(self, tmp_path: Path) -> None:
        from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow

        _register_image_gen()
        script = _make_script(4)
        result = await multi_shot_storyboard_workflow(
            script=script,
            subjects=[],
            llm=_make_adaptive_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
            grid_size=None,
        )
        assert len(result.shots) == len(script.scenes)

    async def test_shot_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 130-131: image_generate raises generic RuntimeError for shot."""
        from oskill.multi_shot_storyboard_workflow import (
            MultiShotStoryboardError,
            multi_shot_storyboard_workflow,
        )

        script = _make_script(1)
        with patch(
            "oprim.image_generate.image_generate",
            new=AsyncMock(side_effect=RuntimeError("unexpected io")),
        ):
            with pytest.raises(MultiShotStoryboardError, match="Unexpected error for shot"):
                await multi_shot_storyboard_workflow(
                    script=script,
                    subjects=[],
                    llm=_make_adaptive_llm(),
                    image_provider="mock_flux",
                    output_dir=tmp_path / "out",
                    grid_size=None,
                )

    async def test_grid_storyboard_grid_error(self, tmp_path: Path) -> None:
        """Lines 155-156: storyboard_grid raises StoryboardGridError."""
        from oskill.multi_shot_storyboard_workflow import (
            MultiShotStoryboardError,
            multi_shot_storyboard_workflow,
        )

        script = _make_script(1)
        _register_image_gen()
        from oskill.storyboard_grid import StoryboardGridError

        with patch(
            "oskill.multi_shot_storyboard_workflow.storyboard_grid",
            new=AsyncMock(side_effect=StoryboardGridError("grid failed")),
        ):
            with pytest.raises(MultiShotStoryboardError, match="Grid preview"):
                await multi_shot_storyboard_workflow(
                    script=script,
                    subjects=[],
                    llm=_make_adaptive_llm(),
                    image_provider="mock_flux",
                    output_dir=tmp_path / "out",
                    grid_size=9,
                )

    async def test_grid_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 157-158: storyboard_grid raises generic RuntimeError."""
        from oskill.multi_shot_storyboard_workflow import (
            MultiShotStoryboardError,
            multi_shot_storyboard_workflow,
        )

        script = _make_script(1)
        _register_image_gen()
        with patch(
            "oskill.multi_shot_storyboard_workflow.storyboard_grid",
            new=AsyncMock(side_effect=RuntimeError("unexpected grid error")),
        ):
            with pytest.raises(MultiShotStoryboardError, match="Unexpected error in grid"):
                await multi_shot_storyboard_workflow(
                    script=script,
                    subjects=[],
                    llm=_make_adaptive_llm(),
                    image_provider="mock_flux",
                    output_dir=tmp_path / "out",
                    grid_size=9,
                )

    async def test_shot_image_gen_fails(self, tmp_path: Path) -> None:
        """Line 129: image_generate raises ImageGenError for shot."""
        from oskill.multi_shot_storyboard_workflow import (
            MultiShotStoryboardError,
            multi_shot_storyboard_workflow,
        )

        _register_image_gen(fail_on=1)  # fail on first shot → ImageGenError via image_generate
        with pytest.raises(MultiShotStoryboardError, match="image_gen failed"):
            await multi_shot_storyboard_workflow(
                script=_make_script(1),
                subjects=[],
                llm=_make_adaptive_llm(),
                image_provider="mock_flux",
                output_dir=tmp_path / "out",
                grid_size=None,
            )
