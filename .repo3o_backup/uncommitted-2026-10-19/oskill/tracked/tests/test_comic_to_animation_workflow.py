"""Tests for oskill.comic_to_animation_workflow."""

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


def _make_png(path: Path) -> None:
    img = Image.new("RGB", (10, 10), color=(255, 128, 0))
    img.save(path, "PNG")


def _make_llm(
    n_frames: int = 3,
    fail: bool = False,
) -> Any:
    def _llm(*, messages: Any, **kw: Any) -> dict[str, Any]:
        if fail:
            raise RuntimeError("LLM down")
        frames = [
            {"description": f"frame {i} scene", "motion": f"motion {i}"} for i in range(n_frames)
        ]
        return {"content": json.dumps(frames)}

    return _llm


def _register_image_gen(name: str = "flux", fail_on: int | None = None) -> None:
    call_count = [0]

    async def _gen(**kw: Any) -> None:
        call_count[0] += 1
        if fail_on is not None and call_count[0] == fail_on:
            raise RuntimeError("image gen failure")
        _make_png(Path(str(kw["output_path"])))

    ProviderRegistry.register(category="image_gen", name=name, fn=_gen)


def _register_i2v(name: str = "wan22_local", fail_on: int | None = None) -> None:
    call_count = [0]

    async def _i2v(**kw: Any) -> None:
        call_count[0] += 1
        if fail_on is not None and call_count[0] == fail_on:
            raise RuntimeError("i2v failure")
        Path(str(kw["output_path"])).write_bytes(b"mp4data")

    ProviderRegistry.register(category="image_to_video", name=name, fn=_i2v)


async def _mock_video_concat(*args: Any, **kwargs: Any) -> Path:
    out = kwargs.get("output_path") or args[0]
    Path(str(out)).write_bytes(b"final_video")
    return Path(str(out))


class TestComicToAnimationWorkflow:
    async def test_normal_success(self, tmp_path: Path) -> None:
        from oskill.comic_to_animation_workflow import comic_to_animation_workflow

        comic = tmp_path / "panel.png"
        _make_png(comic)
        _register_image_gen()
        _register_i2v()

        with patch(
            "oprim.video_concat.video_concat", new=AsyncMock(side_effect=_mock_video_concat)
        ):
            out = await comic_to_animation_workflow(
                comic_image=comic,
                llm=_make_llm(3),
                image_provider="flux",
                video_provider="wan22_local",
                output_path=tmp_path / "anim.mp4",
            )
        assert out.exists()

    async def test_comic_not_found(self, tmp_path: Path) -> None:
        from oskill.comic_to_animation_workflow import comic_to_animation_workflow

        with pytest.raises(FileNotFoundError):
            await comic_to_animation_workflow(
                comic_image=tmp_path / "missing.png",
                llm=_make_llm(),
                image_provider="flux",
                video_provider="wan22_local",
                output_path=tmp_path / "anim.mp4",
            )

    async def test_llm_failure(self, tmp_path: Path) -> None:
        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)

        with pytest.raises(ComicToAnimationError, match="LLM"):
            await comic_to_animation_workflow(
                comic_image=comic,
                llm=_make_llm(fail=True),
                image_provider="flux",
                video_provider="wan22_local",
                output_path=tmp_path / "anim.mp4",
            )

    async def test_image_gen_failure(self, tmp_path: Path) -> None:
        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)
        _register_image_gen("flux", fail_on=1)
        _register_i2v()

        with pytest.raises(ComicToAnimationError):
            await comic_to_animation_workflow(
                comic_image=comic,
                llm=_make_llm(3),
                image_provider="flux",
                video_provider="wan22_local",
                output_path=tmp_path / "anim.mp4",
            )

    async def test_image_to_video_failure(self, tmp_path: Path) -> None:
        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)
        _register_image_gen()
        _register_i2v("wan22_local", fail_on=1)

        with pytest.raises(ComicToAnimationError):
            await comic_to_animation_workflow(
                comic_image=comic,
                llm=_make_llm(3),
                image_provider="flux",
                video_provider="wan22_local",
                output_path=tmp_path / "anim.mp4",
            )

    async def test_video_concat_failure(self, tmp_path: Path) -> None:
        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)
        _register_image_gen()
        _register_i2v()

        async def _fail_concat(**kw: Any) -> Path:
            raise RuntimeError("concat broken")

        with patch("oprim.video_concat.video_concat", new=AsyncMock(side_effect=_fail_concat)):
            with pytest.raises(ComicToAnimationError, match="concat"):
                await comic_to_animation_workflow(
                    comic_image=comic,
                    llm=_make_llm(3),
                    image_provider="flux",
                    video_provider="wan22_local",
                    output_path=tmp_path / "anim.mp4",
                )

    async def test_output_file_validation(self, tmp_path: Path) -> None:
        from oskill.comic_to_animation_workflow import comic_to_animation_workflow

        comic = tmp_path / "panel.png"
        _make_png(comic)
        _register_image_gen()
        _register_i2v()

        with patch(
            "oprim.video_concat.video_concat", new=AsyncMock(side_effect=_mock_video_concat)
        ):
            out = await comic_to_animation_workflow(
                comic_image=comic,
                llm=_make_llm(3),
                image_provider="flux",
                video_provider="wan22_local",
                output_path=tmp_path / "animation.mp4",
            )
        assert out == tmp_path / "animation.mp4"
        assert out.exists()

    async def test_multi_character_comic(self, tmp_path: Path) -> None:
        """LLM returns 5 frames (multi-character comic) → handled correctly."""
        from oskill.comic_to_animation_workflow import comic_to_animation_workflow

        comic = tmp_path / "multi.png"
        _make_png(comic)
        _register_image_gen()
        _register_i2v()

        with patch(
            "oprim.video_concat.video_concat", new=AsyncMock(side_effect=_mock_video_concat)
        ):
            out = await comic_to_animation_workflow(
                comic_image=comic,
                llm=_make_llm(5),
                image_provider="flux",
                video_provider="wan22_local",
                output_path=tmp_path / "multi_anim.mp4",
            )
        assert out.exists()

    async def test_llm_returns_empty_list(self, tmp_path: Path) -> None:
        """Line 95: LLM returns [] → 'LLM returned no frames'."""
        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)

        def _empty_llm(*, messages: object, **kw: object) -> dict[str, object]:
            return {"content": "[]"}

        with pytest.raises(ComicToAnimationError, match="no frames"):
            with patch(
                "oprim.video_concat.video_concat", new=AsyncMock(side_effect=_mock_video_concat)
            ):
                await comic_to_animation_workflow(
                    comic_image=comic,
                    llm=_empty_llm,
                    image_provider="flux",
                    video_provider="wan22_local",
                    output_path=tmp_path / "out.mp4",
                )

    async def test_keyframe_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 108-109: image_generate raises generic Exception for keyframe."""
        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)

        with patch(
            "oprim.image_generate.image_generate",
            new=AsyncMock(side_effect=RuntimeError("unexpected io")),
        ):
            with patch(
                "oprim.video_concat.video_concat", new=AsyncMock(side_effect=_mock_video_concat)
            ):
                with pytest.raises(ComicToAnimationError, match="Unexpected error for keyframe"):
                    await comic_to_animation_workflow(
                        comic_image=comic,
                        llm=_make_llm(2),
                        image_provider="flux",
                        video_provider="wan22_local",
                        output_path=tmp_path / "out.mp4",
                    )

    async def test_clip_unexpected_exception(self, tmp_path: Path) -> None:
        """Lines 129-130: image_to_video raises generic Exception for clip."""
        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)
        _register_image_gen()

        with patch(
            "oprim.image_to_video",
            new=AsyncMock(side_effect=RuntimeError("unexpected clip error")),
        ):
            with patch(
                "oprim.video_concat.video_concat", new=AsyncMock(side_effect=_mock_video_concat)
            ):
                with pytest.raises(ComicToAnimationError, match="Unexpected error for clip"):
                    await comic_to_animation_workflow(
                        comic_image=comic,
                        llm=_make_llm(2),
                        image_provider="flux",
                        video_provider="wan22_local",
                        output_path=tmp_path / "out.mp4",
                    )

    async def test_video_concat_raises_video_concat_error(self, tmp_path: Path) -> None:
        """Line 139: video_concat raises VideoConcatError → ComicToAnimationError."""
        from oprim.video_concat import VideoConcatError

        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)
        _register_image_gen()
        _register_i2v()

        with patch(
            "oprim.video_concat.video_concat",
            new=AsyncMock(side_effect=VideoConcatError("concat failed")),
        ):
            with pytest.raises(ComicToAnimationError, match="video_concat failed"):
                await comic_to_animation_workflow(
                    comic_image=comic,
                    llm=_make_llm(2),
                    image_provider="flux",
                    video_provider="wan22_local",
                    output_path=tmp_path / "out.mp4",
                )

    async def test_output_not_produced(self, tmp_path: Path) -> None:
        """Line 144: video_concat succeeds but doesn't write output_path."""
        from oskill.comic_to_animation_workflow import (
            ComicToAnimationError,
            comic_to_animation_workflow,
        )

        comic = tmp_path / "panel.png"
        _make_png(comic)
        _register_image_gen()
        _register_i2v()

        async def _noop_concat(**kw: object) -> None:
            pass  # does not create output_path

        with patch("oprim.video_concat.video_concat", new=AsyncMock(side_effect=_noop_concat)):
            with pytest.raises(ComicToAnimationError, match="Output not produced"):
                await comic_to_animation_workflow(
                    comic_image=comic,
                    llm=_make_llm(2),
                    image_provider="flux",
                    video_provider="wan22_local",
                    output_path=tmp_path / "out.mp4",
                )
