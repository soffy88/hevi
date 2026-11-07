"""Tests for oskill.multi_angle_9."""

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
    img = Image.new("RGB", size, color=(80, 120, 160))
    img.save(path, "PNG")


def _register_image_gen(name: str = "mock_flux", fail_on: int | None = None) -> None:
    call_count = [0]

    async def _gen(**kw: Any) -> None:
        call_count[0] += 1
        if fail_on is not None and call_count[0] == fail_on:
            raise RuntimeError("image_gen failure")
        _make_png(Path(str(kw["output_path"])))

    ProviderRegistry.register(category="image_gen", name=name, fn=_gen)


def _make_llm(n: int, capture_messages: list[Any] | None = None) -> Any:
    def _llm(*, messages: Any, **kw: Any) -> dict[str, Any]:
        if capture_messages is not None:
            capture_messages.extend(messages)
        return {"content": json.dumps([f"angle {i} prompt" for i in range(n)])}

    return _llm


class TestMultiAngle9:
    async def test_normal_9_angles(self, tmp_path: Path) -> None:
        from oskill.multi_angle_9 import multi_angle_9

        _register_image_gen()
        out = await multi_angle_9(
            scene_description="Samurai duel at sunset.",
            image_provider="mock_flux",
            llm=_make_llm(9),
            output_path=tmp_path / "angles.png",
        )
        assert out.exists()

    async def test_9_angle_labels_in_prompt(self, tmp_path: Path) -> None:
        from oskill.multi_angle_9 import multi_angle_9

        _register_image_gen()
        captured: list[Any] = []
        await multi_angle_9(
            scene_description="Urban chase scene.",
            image_provider="mock_flux",
            llm=_make_llm(9, capture_messages=captured),
            output_path=tmp_path / "angles.png",
        )
        # LLM must have received a message mentioning all 3 view angles
        all_content = " ".join(str(m) for m in captured)
        for label in ("eye-level", "high-angle", "low-angle"):
            assert label in all_content

    async def test_llm_wrong_count(self, tmp_path: Path) -> None:
        from oskill.multi_angle_9 import MultiAngleError, multi_angle_9

        _register_image_gen()
        with pytest.raises(MultiAngleError, match="7"):
            await multi_angle_9(
                scene_description="Forest clearing.",
                image_provider="mock_flux",
                llm=_make_llm(7),
                output_path=tmp_path / "angles.png",
            )

    async def test_image_gen_failure(self, tmp_path: Path) -> None:
        from oskill.multi_angle_9 import MultiAngleError, multi_angle_9

        _register_image_gen("mock_flux", fail_on=5)
        with pytest.raises(MultiAngleError):
            await multi_angle_9(
                scene_description="Space station corridor.",
                image_provider="mock_flux",
                llm=_make_llm(9),
                output_path=tmp_path / "angles.png",
            )

    async def test_output_dimensions(self, tmp_path: Path) -> None:
        from oskill.multi_angle_9 import multi_angle_9

        _register_image_gen()
        out = tmp_path / "angles.png"
        await multi_angle_9(
            scene_description="Pirate ship deck.",
            image_provider="mock_flux",
            llm=_make_llm(9),
            output_path=out,
        )
        img = Image.open(out)
        w, h = img.size
        assert w == 30  # 3 cols × 10px
        assert h == 30  # 3 rows × 10px

    async def test_empty_scene_description(self, tmp_path: Path) -> None:
        from oskill.multi_angle_9 import multi_angle_9

        _register_image_gen()
        with pytest.raises(ValueError, match="empty"):
            await multi_angle_9(
                scene_description="",
                image_provider="mock_flux",
                llm=_make_llm(9),
                output_path=tmp_path / "angles.png",
            )

    async def test_chinese_scene(self, tmp_path: Path) -> None:
        from oskill.multi_angle_9 import multi_angle_9

        _register_image_gen()
        out = await multi_angle_9(
            scene_description="武士在夕阳下决斗，樱花飘落。",
            image_provider="mock_flux",
            llm=_make_llm(9),
            output_path=tmp_path / "zh_angles.png",
        )
        assert out.exists()

    async def test_output_parent_autocreated(self, tmp_path: Path) -> None:
        from oskill.multi_angle_9 import multi_angle_9

        _register_image_gen()
        nested = tmp_path / "deep" / "nested" / "out.png"
        assert not nested.parent.exists()
        await multi_angle_9(
            scene_description="Volcano erupting.",
            image_provider="mock_flux",
            llm=_make_llm(9),
            output_path=nested,
        )
        assert nested.exists()

    async def test_llm_raises_exception(self, tmp_path: Path) -> None:
        """Lines 105-106: LLM raises Exception → MultiAngleError."""
        from oskill.multi_angle_9 import MultiAngleError, multi_angle_9

        def _bad_llm(*, messages: object, **kw: object) -> object:
            raise RuntimeError("LLM exploded")

        with pytest.raises(MultiAngleError, match="LLM angle-prompt"):
            await multi_angle_9(
                scene_description="test",
                image_provider="mock_flux",
                llm=_bad_llm,
                output_path=tmp_path / "out.png",
            )

    async def test_image_gen_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 125-126: image_generate raises non-ImageGenError Exception."""
        from oskill.multi_angle_9 import MultiAngleError, multi_angle_9

        with patch(
            "oprim.image_generate.image_generate",
            new=AsyncMock(side_effect=RuntimeError("unexpected IO")),
        ):
            with pytest.raises(MultiAngleError, match="Unexpected error"):
                await multi_angle_9(
                    scene_description="test",
                    image_provider="mock_flux",
                    llm=_make_llm(9),
                    output_path=tmp_path / "out.png",
                )

    async def test_pil_stitch_failure(self, tmp_path: Path) -> None:
        """Lines 132-133: PIL stitching raises Exception → MultiAngleError."""
        from oskill.multi_angle_9 import MultiAngleError, multi_angle_9

        _register_image_gen()
        with patch(
            "oskill.multi_angle_9._stitch_3x3",
            side_effect=RuntimeError("PIL fail"),
        ):
            with pytest.raises(MultiAngleError, match="PIL grid stitching"):
                await multi_angle_9(
                    scene_description="test",
                    image_provider="mock_flux",
                    llm=_make_llm(9),
                    output_path=tmp_path / "out.png",
                )
