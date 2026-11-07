"""Tests for oskill.character_consistency_workflow."""

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
    img = Image.new("RGB", size, color=(200, 100, 50))
    img.save(path, "PNG")


def _register_image_gen(name: str = "mock_flux", fail_on: int | None = None) -> None:
    call_count = [0]

    async def _gen(**kw: Any) -> None:
        call_count[0] += 1
        if fail_on is not None and call_count[0] == fail_on:
            raise RuntimeError("image_gen failure")
        _make_png(Path(str(kw["output_path"])))

    ProviderRegistry.register(category="image_gen", name=name, fn=_gen)


_GOOD_VIEW_JSON = json.dumps({"front": "front view", "side": "side view", "back": "back view"})


def _make_llm(view_json: str = _GOOD_VIEW_JSON) -> Any:
    def _llm(*, messages: Any, **kw: Any) -> dict[str, Any]:
        return {"content": view_json}

    return _llm


class TestCharacterConsistencyWorkflow:
    async def test_single_scene(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import (
            CharacterConsistencyResult,
            character_consistency_workflow,
        )

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen()

        result = await character_consistency_workflow(
            portrait_image=portrait,
            scene_descriptions=["hero in forest"],
            llm=_make_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
        )
        assert isinstance(result, CharacterConsistencyResult)
        assert len(result.scene_variants) == 1

    async def test_multiple_scenes(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import character_consistency_workflow

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen()

        result = await character_consistency_workflow(
            portrait_image=portrait,
            scene_descriptions=["scene A", "scene B", "scene C"],
            llm=_make_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
        )
        assert len(result.scene_variants) == 3

    async def test_portrait_not_found(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import character_consistency_workflow

        _register_image_gen()
        with pytest.raises(FileNotFoundError):
            await character_consistency_workflow(
                portrait_image=tmp_path / "missing.png",
                scene_descriptions=["scene"],
                llm=_make_llm(),
                image_provider="mock_flux",
                output_dir=tmp_path / "out",
            )

    async def test_scene_descriptions_empty(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import character_consistency_workflow

        portrait = tmp_path / "face.png"
        _make_png(portrait)

        with pytest.raises(ValueError, match="empty"):
            await character_consistency_workflow(
                portrait_image=portrait,
                scene_descriptions=[],
                llm=_make_llm(),
                image_provider="mock_flux",
                output_dir=tmp_path / "out",
            )

    async def test_three_view_fails(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import (
            CharacterConsistencyError,
            character_consistency_workflow,
        )
        from oskill.character_three_view import CharacterThreeViewError

        portrait = tmp_path / "face.png"
        _make_png(portrait)

        async def _fail_three_view(**kw: Any) -> None:
            raise CharacterThreeViewError("forced three_view failure")

        with patch(
            "oskill.character_consistency_workflow.character_three_view",
            new=AsyncMock(side_effect=_fail_three_view),
        ):
            with pytest.raises(CharacterConsistencyError, match="Three-view"):
                await character_consistency_workflow(
                    portrait_image=portrait,
                    scene_descriptions=["scene"],
                    llm=_make_llm(),
                    image_provider="mock_flux",
                    output_dir=tmp_path / "out",
                )

    async def test_scene_variant_fails(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import (
            CharacterConsistencyError,
            character_consistency_workflow,
        )

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        # First 3 calls = three_view (front/side/back), 4th = variant_00 fails
        _register_image_gen("mock_flux", fail_on=4)

        with pytest.raises(CharacterConsistencyError, match="variant"):
            await character_consistency_workflow(
                portrait_image=portrait,
                scene_descriptions=["scene A"],
                llm=_make_llm(),
                image_provider="mock_flux",
                output_dir=tmp_path / "out",
            )

    async def test_consistency_score_correct(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import character_consistency_workflow

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen()

        result = await character_consistency_workflow(
            portrait_image=portrait,
            scene_descriptions=["scene"],
            llm=_make_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
        )
        # all succeed → three_view.consistency_score=1.0, variant_success=1.0 → avg=1.0
        assert result.consistency_score == pytest.approx(1.0)

    async def test_output_files_all_exist(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import character_consistency_workflow

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen()

        result = await character_consistency_workflow(
            portrait_image=portrait,
            scene_descriptions=["scene A", "scene B"],
            llm=_make_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
        )
        assert result.three_view.front.exists()
        assert result.three_view.side.exists()
        assert result.three_view.back.exists()
        for p in result.scene_variants:
            assert p.exists()

    async def test_output_dir_autocreated(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import character_consistency_workflow

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen()
        nested = tmp_path / "a" / "b" / "c"
        assert not nested.exists()

        await character_consistency_workflow(
            portrait_image=portrait,
            scene_descriptions=["scene"],
            llm=_make_llm(),
            image_provider="mock_flux",
            output_dir=nested,
        )
        assert nested.exists()

    async def test_5_scenes(self, tmp_path: Path) -> None:
        from oskill.character_consistency_workflow import character_consistency_workflow

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen()

        result = await character_consistency_workflow(
            portrait_image=portrait,
            scene_descriptions=[f"scene {i}" for i in range(5)],
            llm=_make_llm(),
            image_provider="mock_flux",
            output_dir=tmp_path / "out",
        )
        assert len(result.scene_variants) == 5
        assert 0.0 <= result.consistency_score <= 1.0

    async def test_three_view_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 111-112: character_three_view raises generic Exception."""
        from oskill.character_consistency_workflow import (
            CharacterConsistencyError,
            character_consistency_workflow,
        )

        portrait = tmp_path / "face.png"
        _make_png(portrait)

        with patch(
            "oskill.character_consistency_workflow.character_three_view",
            new=AsyncMock(side_effect=RuntimeError("unexpected three_view error")),
        ):
            with pytest.raises(CharacterConsistencyError, match="Unexpected error"):
                await character_consistency_workflow(
                    portrait_image=portrait,
                    scene_descriptions=["forest scene"],
                    llm=_make_llm(),
                    image_provider="mock_flux",
                    output_dir=tmp_path / "out",
                )

    async def test_scene_variant_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 126-127: image_generate raises generic Exception for scene variant.

        Mock character_three_view to succeed, then mock image_generate to
        raise RuntimeError so the scene-variant loop hits the except Exception path.
        """
        from oskill.character_consistency_workflow import (
            CharacterConsistencyError,
            character_consistency_workflow,
        )
        from oskill.character_three_view import ThreeViewResult

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        out_dir = tmp_path / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        # pre-create dummy view files for the mocked ThreeViewResult
        (out_dir / "three_view" / "front.png").parent.mkdir(parents=True, exist_ok=True)
        for f in ("front.png", "side.png", "back.png"):
            _make_png(out_dir / "three_view" / f)

        fake_three_view = ThreeViewResult(
            front=out_dir / "three_view" / "front.png",
            side=out_dir / "three_view" / "side.png",
            back=out_dir / "three_view" / "back.png",
            consistency_score=1.0,
        )

        with patch(
            "oskill.character_consistency_workflow.character_three_view",
            new=AsyncMock(return_value=fake_three_view),
        ):
            with patch(
                "oprim.image_generate.image_generate",
                new=AsyncMock(side_effect=RuntimeError("unexpected io")),
            ):
                with pytest.raises(CharacterConsistencyError, match="Unexpected error for scene"):
                    await character_consistency_workflow(
                        portrait_image=portrait,
                        scene_descriptions=["forest scene"],
                        llm=_make_llm(),
                        image_provider="mock_flux",
                        output_dir=out_dir,
                    )
