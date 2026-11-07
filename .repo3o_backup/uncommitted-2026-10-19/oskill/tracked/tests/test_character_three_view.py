"""Tests for oskill.character_three_view."""

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
    """Write a tiny valid PNG to path."""
    img = Image.new("RGB", size, color=(128, 64, 32))
    img.save(path, "PNG")


def _register_image_gen(name: str = "mock_flux", fail_on: int | None = None) -> None:
    call_count = [0]

    async def _gen(**kw: Any) -> None:
        call_count[0] += 1
        if fail_on is not None and call_count[0] == fail_on:
            raise RuntimeError("image_gen intentional failure")
        _make_png(Path(str(kw["output_path"])))

    ProviderRegistry.register(category="image_gen", name=name, fn=_gen)


def _make_llm(content: str) -> Any:
    def _llm(*, messages: Any, **kw: Any) -> dict[str, Any]:
        return {"content": content}

    return _llm


_GOOD_VIEW_JSON = json.dumps(
    {"front": "front view prompt", "side": "side view prompt", "back": "back view prompt"}
)


class TestCharacterThreeView:
    async def test_normal_success(self, tmp_path: Path) -> None:
        from oskill.character_three_view import ThreeViewResult, character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen("mock_flux")
        llm = _make_llm(_GOOD_VIEW_JSON)

        result = await character_three_view(
            portrait_image=portrait,
            image_provider="mock_flux",
            llm=llm,
            output_dir=tmp_path / "out",
        )
        assert isinstance(result, ThreeViewResult)

    async def test_portrait_not_found(self, tmp_path: Path) -> None:
        from oskill.character_three_view import character_three_view

        _register_image_gen()
        with pytest.raises(FileNotFoundError):
            await character_three_view(
                portrait_image=tmp_path / "missing.png",
                image_provider="mock_flux",
                llm=_make_llm(_GOOD_VIEW_JSON),
                output_dir=tmp_path / "out",
            )

    async def test_llm_failure(self, tmp_path: Path) -> None:
        from oskill.character_three_view import CharacterThreeViewError, character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen()

        def _bad_llm(*, messages: Any, **kw: Any) -> dict[str, Any]:
            raise RuntimeError("LLM unavailable")

        with pytest.raises(CharacterThreeViewError, match="LLM"):
            await character_three_view(
                portrait_image=portrait,
                image_provider="mock_flux",
                llm=_bad_llm,
                output_dir=tmp_path / "out",
            )

    async def test_llm_bad_json(self, tmp_path: Path) -> None:
        from oskill.character_three_view import CharacterThreeViewError, character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen()

        with pytest.raises(CharacterThreeViewError):
            await character_three_view(
                portrait_image=portrait,
                image_provider="mock_flux",
                llm=_make_llm("NOT JSON AT ALL !!"),
                output_dir=tmp_path / "out",
            )

    async def test_image_gen_failure(self, tmp_path: Path) -> None:
        from oskill.character_three_view import CharacterThreeViewError, character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen("mock_flux", fail_on=2)  # side view fails

        with pytest.raises(CharacterThreeViewError):
            await character_three_view(
                portrait_image=portrait,
                image_provider="mock_flux",
                llm=_make_llm(_GOOD_VIEW_JSON),
                output_dir=tmp_path / "out",
            )

    async def test_output_files_exist(self, tmp_path: Path) -> None:
        from oskill.character_three_view import character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen("mock_flux")
        out_dir = tmp_path / "views"

        result = await character_three_view(
            portrait_image=portrait,
            image_provider="mock_flux",
            llm=_make_llm(_GOOD_VIEW_JSON),
            output_dir=out_dir,
        )
        assert result.front.exists()
        assert result.side.exists()
        assert result.back.exists()

    async def test_consistency_score_range(self, tmp_path: Path) -> None:
        from oskill.character_three_view import character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen("mock_flux")

        result = await character_three_view(
            portrait_image=portrait,
            image_provider="mock_flux",
            llm=_make_llm(_GOOD_VIEW_JSON),
            output_dir=tmp_path / "out",
        )
        assert 0.0 <= result.consistency_score <= 1.0

    async def test_output_dir_autocreated(self, tmp_path: Path) -> None:
        from oskill.character_three_view import character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        _register_image_gen("mock_flux")
        out_dir = tmp_path / "nested" / "deep" / "views"
        assert not out_dir.exists()

        await character_three_view(
            portrait_image=portrait,
            image_provider="mock_flux",
            llm=_make_llm(_GOOD_VIEW_JSON),
            output_dir=out_dir,
        )
        assert out_dir.exists()

    async def test_image_provider_not_registered(self, tmp_path: Path) -> None:
        from oskill.character_three_view import CharacterThreeViewError, character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)
        # No provider registered → ProviderRegistry.get raises

        with pytest.raises(CharacterThreeViewError):
            await character_three_view(
                portrait_image=portrait,
                image_provider="nonexistent_provider",
                llm=_make_llm(_GOOD_VIEW_JSON),
                output_dir=tmp_path / "out",
            )

    async def test_image_gen_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 117-118: except Exception path when image_generate raises RuntimeError."""
        from oskill.character_three_view import CharacterThreeViewError, character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)

        with patch(
            "oprim.image_generate.image_generate",
            new=AsyncMock(side_effect=RuntimeError("unexpected io error")),
        ):
            with pytest.raises(CharacterThreeViewError, match="Unexpected error"):
                await character_three_view(
                    portrait_image=portrait,
                    image_provider="mock_flux",
                    llm=_make_llm(_GOOD_VIEW_JSON),
                    output_dir=tmp_path / "out",
                )

    async def test_output_files_not_created(self, tmp_path: Path) -> None:
        """Line 123: provider succeeds but does not write the output file."""
        from oskill.character_three_view import CharacterThreeViewError, character_three_view

        portrait = tmp_path / "face.png"
        _make_png(portrait)

        async def _noop(**_kw: object) -> None:
            pass  # succeeds but never writes output_path

        with patch("oprim.image_generate.image_generate", new=AsyncMock(side_effect=_noop)):
            with pytest.raises(CharacterThreeViewError, match="did not produce"):
                await character_three_view(
                    portrait_image=portrait,
                    image_provider="mock_flux",
                    llm=_make_llm(_GOOD_VIEW_JSON),
                    output_dir=tmp_path / "out",
                )
