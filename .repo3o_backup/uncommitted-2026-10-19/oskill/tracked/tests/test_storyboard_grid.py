"""Tests for oskill.storyboard_grid."""

from __future__ import annotations

import json
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


def _make_png(path: Path, size: tuple[int, int] = (10, 10)) -> None:
    img = Image.new("RGB", size, color=(100, 150, 200))
    img.save(path, "PNG")


def _register_image_gen(name: str = "mock_flux", fail_on: int | None = None) -> None:
    call_count = [0]

    async def _gen(**kw: Any) -> None:
        call_count[0] += 1
        if fail_on is not None and call_count[0] == fail_on:
            raise RuntimeError("image_gen intentional failure")
        _make_png(Path(str(kw["output_path"])))

    ProviderRegistry.register(category="image_gen", name=name, fn=_gen)


def _make_llm(n: int, fail: bool = False) -> Any:
    def _llm(*, messages: Any, **kw: Any) -> dict[str, Any]:
        if fail:
            raise RuntimeError("LLM down")
        return {"content": json.dumps([f"shot {i} description" for i in range(n)])}

    return _llm


class TestStoryboardGrid:
    async def test_grid9_success(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import storyboard_grid

        _register_image_gen()
        out = tmp_path / "sb9.png"
        result = await storyboard_grid(
            scene_description="A dragon attacks a castle.",
            image_provider="mock_flux",
            llm=_make_llm(9),
            grid_size=9,
            output_path=out,
        )
        assert result == out
        assert out.exists()

    async def test_grid25_success(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import storyboard_grid

        _register_image_gen()
        out = tmp_path / "sb25.png"
        result = await storyboard_grid(
            scene_description="Epic battle scene.",
            image_provider="mock_flux",
            llm=_make_llm(25),
            grid_size=25,
            output_path=out,
        )
        assert result.exists()

    async def test_empty_scene_description(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import storyboard_grid

        _register_image_gen()
        with pytest.raises(ValueError, match="empty"):
            await storyboard_grid(
                scene_description="   ",
                image_provider="mock_flux",
                llm=_make_llm(9),
                grid_size=9,
                output_path=tmp_path / "sb.png",
            )

    async def test_llm_returns_wrong_count(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import StoryboardGridError, storyboard_grid

        _register_image_gen()
        # LLM returns 8, but grid_size=9 → error
        with pytest.raises(StoryboardGridError, match="8"):
            await storyboard_grid(
                scene_description="Castle scene.",
                image_provider="mock_flux",
                llm=_make_llm(8),
                grid_size=9,
                output_path=tmp_path / "sb.png",
            )

    async def test_image_gen_failure(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import StoryboardGridError, storyboard_grid

        _register_image_gen("mock_flux", fail_on=4)
        with pytest.raises(StoryboardGridError):
            await storyboard_grid(
                scene_description="A battle scene.",
                image_provider="mock_flux",
                llm=_make_llm(9),
                grid_size=9,
                output_path=tmp_path / "sb.png",
            )

    async def test_grid9_output_dimensions(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import storyboard_grid

        _register_image_gen()
        out = tmp_path / "sb.png"
        await storyboard_grid(
            scene_description="Sci-fi corridor.",
            image_provider="mock_flux",
            llm=_make_llm(9),
            grid_size=9,
            output_path=out,
        )
        img = Image.open(out)
        w, h = img.size
        # 3 cols × 10px, 3 rows × 10px
        assert w == 30
        assert h == 30

    async def test_grid25_output_dimensions(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import storyboard_grid

        _register_image_gen()
        out = tmp_path / "sb25.png"
        await storyboard_grid(
            scene_description="Fantasy forest.",
            image_provider="mock_flux",
            llm=_make_llm(25),
            grid_size=25,
            output_path=out,
        )
        img = Image.open(out)
        w, h = img.size
        # 5 cols × 10px, 5 rows × 10px
        assert w == 50
        assert h == 50

    async def test_different_image_provider(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import storyboard_grid

        _register_image_gen("alt_provider")
        out = tmp_path / "alt.png"
        result = await storyboard_grid(
            scene_description="Night market.",
            image_provider="alt_provider",
            llm=_make_llm(9),
            grid_size=9,
            output_path=out,
        )
        assert result.exists()

    async def test_chinese_scene_description(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import storyboard_grid

        _register_image_gen()
        out = tmp_path / "zh.png"
        result = await storyboard_grid(
            scene_description="巨龙攻击城堡的史诗战斗场面，充满烟雾与火焰。",
            image_provider="mock_flux",
            llm=_make_llm(9),
            grid_size=9,
            output_path=out,
        )
        assert result.exists()

    async def test_long_scene_description(self, tmp_path: Path) -> None:
        from oskill.storyboard_grid import storyboard_grid

        _register_image_gen()
        long_desc = "A very detailed scene. " * 30  # >500 chars
        assert len(long_desc) > 500
        out = tmp_path / "long.png"
        result = await storyboard_grid(
            scene_description=long_desc,
            image_provider="mock_flux",
            llm=_make_llm(9),
            grid_size=9,
            output_path=out,
        )
        assert result.exists()

    async def test_llm_raises_exception(self, tmp_path: Path) -> None:
        """Lines 90-91: LLM raises Exception → StoryboardGridError."""
        from oskill.storyboard_grid import StoryboardGridError, storyboard_grid

        def _bad_llm(*, messages: object, **kw: object) -> object:
            raise RuntimeError("LLM crashed")

        with pytest.raises(StoryboardGridError, match="LLM sub-shot"):
            await storyboard_grid(
                scene_description="test",
                image_provider="mock_flux",
                llm=_bad_llm,
                grid_size=9,
                output_path=tmp_path / "out.png",
            )

    async def test_image_gen_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 111-112: image_generate raises non-ImageGenError Exception."""
        from oskill.storyboard_grid import StoryboardGridError, storyboard_grid

        with patch(
            "oprim.image_generate.image_generate",
            new=AsyncMock(side_effect=RuntimeError("unexpected IO")),
        ):
            with pytest.raises(StoryboardGridError, match="Unexpected error"):
                await storyboard_grid(
                    scene_description="test",
                    image_provider="mock_flux",
                    llm=_make_llm(9),
                    grid_size=9,
                    output_path=tmp_path / "out.png",
                )

    async def test_pil_stitch_failure(self, tmp_path: Path) -> None:
        """Lines 118-119: PIL stitching raises Exception → StoryboardGridError."""
        from oskill.storyboard_grid import StoryboardGridError, storyboard_grid

        _register_image_gen()
        with patch(
            "oskill.storyboard_grid._stitch_grid",
            side_effect=RuntimeError("PIL fail"),
        ):
            with pytest.raises(StoryboardGridError, match="PIL grid stitching"):
                await storyboard_grid(
                    scene_description="test",
                    image_provider="mock_flux",
                    llm=_make_llm(9),
                    grid_size=9,
                    output_path=tmp_path / "out.png",
                )
