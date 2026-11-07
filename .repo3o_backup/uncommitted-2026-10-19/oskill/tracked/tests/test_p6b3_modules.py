"""Tests for P6-B3: oskill.image_to_video_workflow + oskill.video_self_assess."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from obase import ProviderRegistry


@pytest.fixture(autouse=True)
def _clean() -> None:  # type: ignore[misc]
    ProviderRegistry.clear()
    yield  # type: ignore[misc]
    ProviderRegistry.clear()


def _register_mock_i2v(name: str = "mock", fail: bool = False) -> None:
    async def _gen(**kw: Any) -> None:
        if fail:
            raise RuntimeError("provider failed")
        Path(str(kw["output_path"])).write_bytes(b"video_data")

    ProviderRegistry.register(category="image_to_video", name=name, fn=_gen)


# ═══════════════════════════════════════════════════════════════════════════════
# image_to_video_workflow
# ═══════════════════════════════════════════════════════════════════════════════


class TestImageToVideoWorkflow:
    async def test_single_image_success(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import image_to_video_workflow

        img = tmp_path / "img.png"
        img.write_bytes(b"PNG")
        _register_mock_i2v("wan22_local")

        result = await image_to_video_workflow(
            reference_images=[img],
            motion_prompts=["pan"],
            durations=[5.0],
            output_dir=tmp_path / "out",
            primary_provider="wan22_local",
            fallback_provider=None,
        )
        assert len(result) == 1
        assert result[0].exists()

    async def test_multi_image_concurrent(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import image_to_video_workflow

        imgs = [tmp_path / f"img{i}.png" for i in range(4)]
        for img in imgs:
            img.write_bytes(b"PNG")
        _register_mock_i2v("wan22_local")

        result = await image_to_video_workflow(
            reference_images=imgs,
            motion_prompts=["pan"] * 4,
            durations=[5.0] * 4,
            output_dir=tmp_path / "out",
            primary_provider="wan22_local",
            fallback_provider=None,
            concurrency=4,
        )
        assert len(result) == 4

    async def test_primary_fails_fallback_succeeds(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import image_to_video_workflow

        img = tmp_path / "img.png"
        img.write_bytes(b"PNG")
        _register_mock_i2v("primary", fail=True)
        _register_mock_i2v("fallback", fail=False)

        result = await image_to_video_workflow(
            reference_images=[img],
            motion_prompts=["zoom"],
            durations=[5.0],
            output_dir=tmp_path / "out",
            primary_provider="primary",
            fallback_provider="fallback",
        )
        assert len(result) == 1
        assert result[0].exists()

    async def test_all_providers_fail_raises(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import (
            ImageToVideoWorkflowError,
            image_to_video_workflow,
        )

        img = tmp_path / "img.png"
        img.write_bytes(b"PNG")
        _register_mock_i2v("primary", fail=True)
        _register_mock_i2v("fallback", fail=True)

        with pytest.raises(ImageToVideoWorkflowError, match="All providers failed"):
            await image_to_video_workflow(
                reference_images=[img],
                motion_prompts=["x"],
                durations=[5.0],
                output_dir=tmp_path / "out",
                primary_provider="primary",
                fallback_provider="fallback",
            )

    async def test_input_length_mismatch_raises(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import (
            ImageToVideoWorkflowError,
            image_to_video_workflow,
        )

        img = tmp_path / "img.png"
        img.write_bytes(b"PNG")
        with pytest.raises(ImageToVideoWorkflowError, match="lengths must match"):
            await image_to_video_workflow(
                reference_images=[img],
                motion_prompts=["a", "b"],
                durations=[5.0],
                output_dir=tmp_path / "out",
            )

    async def test_empty_images_raises(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import (
            ImageToVideoWorkflowError,
            image_to_video_workflow,
        )

        with pytest.raises(ImageToVideoWorkflowError, match="must not be empty"):
            await image_to_video_workflow(
                reference_images=[],
                motion_prompts=[],
                durations=[],
                output_dir=tmp_path / "out",
            )

    async def test_output_dir_created(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import image_to_video_workflow

        img = tmp_path / "img.png"
        img.write_bytes(b"PNG")
        _register_mock_i2v("wan22_local")
        out_dir = tmp_path / "nested" / "dir"

        await image_to_video_workflow(
            reference_images=[img],
            motion_prompts=["x"],
            durations=[5.0],
            output_dir=out_dir,
            primary_provider="wan22_local",
            fallback_provider=None,
        )
        assert out_dir.exists()

    async def test_concurrency_1_serial(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import image_to_video_workflow

        imgs = [tmp_path / f"img{i}.png" for i in range(3)]
        for img in imgs:
            img.write_bytes(b"PNG")
        _register_mock_i2v("wan22_local")

        result = await image_to_video_workflow(
            reference_images=imgs,
            motion_prompts=["x"] * 3,
            durations=[5.0] * 3,
            output_dir=tmp_path / "out",
            primary_provider="wan22_local",
            fallback_provider=None,
            concurrency=1,
        )
        assert len(result) == 3

    async def test_with_llm_translate(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import image_to_video_workflow

        img = tmp_path / "img.png"
        img.write_bytes(b"PNG")
        _register_mock_i2v("wan22_local")

        llm = lambda **kw: {"content": "translated motion prompt"}  # noqa: E731

        result = await image_to_video_workflow(
            reference_images=[img],
            motion_prompts=["pan left"],
            durations=[5.0],
            output_dir=tmp_path / "out",
            primary_provider="wan22_local",
            fallback_provider=None,
            llm=llm,
        )
        assert len(result) == 1

    async def test_no_fallback_primary_fails_raises(self, tmp_path: Path) -> None:
        from oskill.image_to_video_workflow import (
            ImageToVideoWorkflowError,
            image_to_video_workflow,
        )

        img = tmp_path / "img.png"
        img.write_bytes(b"PNG")
        _register_mock_i2v("primary", fail=True)

        with pytest.raises(ImageToVideoWorkflowError):
            await image_to_video_workflow(
                reference_images=[img],
                motion_prompts=["x"],
                durations=[5.0],
                output_dir=tmp_path / "out",
                primary_provider="primary",
                fallback_provider=None,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# video_self_assess
# ═══════════════════════════════════════════════════════════════════════════════


class TestVideoSelfAssess:
    def _mock_vlm(self, scores: dict[str, Any] | None = None) -> Any:
        s = scores or {
            "script_score": 80,
            "visual_score": 70,
            "pacing_score": 60,
            "issues": ["too fast"],
            "suggestions": ["slow down"],
        }
        return lambda **kw: {"content": json.dumps(s)}

    async def test_success(self, tmp_path: Path) -> None:
        from oskill._schemas import Script
        from oskill.video_self_assess import video_self_assess

        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake_video")
        script = Script(
            title="Test",
            description="d",
            scenes=[],
            estimated_duration_s=10.0,
        )

        metrics_mock = AsyncMock(
            return_value=AsyncMock(
                width=1920,
                height=1080,
                duration_s=10.0,
                fps=30.0,
                bitrate_kbps=1500,
                codec_video="h264",
                codec_audio="aac",
                audio_lufs=None,
            )
        )
        with (
            patch("oprim.video_quality_metrics", metrics_mock),
            patch("oskill.video_self_assess._extract_frames", return_value=[tmp_path / "f.png"]),
        ):
            score = await video_self_assess(
                video_path=video,
                script=script,
                vlm=self._mock_vlm(),
            )

        assert score.script_score == 80
        assert score.visual_score == 70
        assert score.overall_score == 80 * 0.4 + 70 * 0.35 + 60 * 0.25

    async def test_video_not_found(self, tmp_path: Path) -> None:
        from oskill._schemas import Script
        from oskill.video_self_assess import VideoSelfAssessError, video_self_assess

        script = Script(title="T", description="d", scenes=[], estimated_duration_s=5.0)
        with pytest.raises(VideoSelfAssessError, match="not found"):
            await video_self_assess(
                video_path=tmp_path / "nope.mp4",
                script=script,
                vlm=self._mock_vlm(),
            )

    async def test_sample_frames_boundary(self, tmp_path: Path) -> None:
        from oskill._schemas import Script
        from oskill.video_self_assess import VideoSelfAssessError, video_self_assess

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        script = Script(title="T", description="d", scenes=[], estimated_duration_s=5.0)
        with pytest.raises(VideoSelfAssessError, match="sample_frames_count"):
            await video_self_assess(
                video_path=video,
                script=script,
                vlm=self._mock_vlm(),
                sample_frames_count=0,
            )

    async def test_vlm_failure_raises(self, tmp_path: Path) -> None:
        from oskill._schemas import Script
        from oskill.video_self_assess import VideoSelfAssessError, video_self_assess

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        script = Script(title="T", description="d", scenes=[], estimated_duration_s=5.0)

        def _fail(**kw: Any) -> None:
            raise RuntimeError("VLM down")

        metrics_mock = AsyncMock(
            return_value=AsyncMock(
                width=1920,
                height=1080,
                duration_s=10.0,
                fps=30,
                bitrate_kbps=1500,
                codec_video="h264",
                codec_audio="aac",
                audio_lufs=None,
            )
        )
        with (
            patch("oprim.video_quality_metrics", metrics_mock),
            patch("oskill.video_self_assess._extract_frames", return_value=[]),
        ):
            with pytest.raises(VideoSelfAssessError, match="VLM call failed"):
                await video_self_assess(
                    video_path=video,
                    script=script,
                    vlm=_fail,
                )

    async def test_vlm_invalid_json_raises(self, tmp_path: Path) -> None:
        from oskill._schemas import Script
        from oskill.video_self_assess import VideoSelfAssessError, video_self_assess

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        script = Script(title="T", description="d", scenes=[], estimated_duration_s=5.0)

        metrics_mock = AsyncMock(
            return_value=AsyncMock(
                width=1920,
                height=1080,
                duration_s=10.0,
                fps=30,
                bitrate_kbps=1500,
                codec_video="h264",
                codec_audio="aac",
                audio_lufs=None,
            )
        )
        with (
            patch("oprim.video_quality_metrics", metrics_mock),
            patch("oskill.video_self_assess._extract_frames", return_value=[]),
        ):
            with pytest.raises(VideoSelfAssessError, match="invalid JSON"):
                await video_self_assess(
                    video_path=video,
                    script=script,
                    vlm=lambda **kw: {"content": "not json"},
                )

    async def test_overall_score_weighted(self, tmp_path: Path) -> None:
        from oskill._schemas import Script
        from oskill.video_self_assess import video_self_assess

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        script = Script(title="T", description="d", scenes=[], estimated_duration_s=5.0)

        scores = {
            "script_score": 100,
            "visual_score": 100,
            "pacing_score": 100,
            "issues": [],
            "suggestions": [],
        }

        metrics_mock = AsyncMock(
            return_value=AsyncMock(
                width=1920,
                height=1080,
                duration_s=10.0,
                fps=30,
                bitrate_kbps=1500,
                codec_video="h264",
                codec_audio="aac",
                audio_lufs=None,
            )
        )
        with (
            patch("oprim.video_quality_metrics", metrics_mock),
            patch("oskill.video_self_assess._extract_frames", return_value=[]),
        ):
            score = await video_self_assess(
                video_path=video,
                script=script,
                vlm=self._mock_vlm(scores),
            )
        assert score.overall_score == 100.0

    async def test_metrics_failure_raises(self, tmp_path: Path) -> None:
        from oskill._schemas import Script
        from oskill.video_self_assess import VideoSelfAssessError, video_self_assess

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        script = Script(title="T", description="d", scenes=[], estimated_duration_s=5.0)

        from oprim import VideoQualityError

        metrics_mock = AsyncMock(side_effect=VideoQualityError("ffprobe fail"))
        with patch("oprim.video_quality_metrics", metrics_mock):
            with pytest.raises(VideoSelfAssessError, match="Metrics extraction"):
                await video_self_assess(
                    video_path=video,
                    script=script,
                    vlm=self._mock_vlm(),
                )

    async def test_pydantic_output(self) -> None:
        from oskill.video_self_assess import VideoQualityScore

        s = VideoQualityScore(
            script_score=80,
            visual_score=70,
            pacing_score=60,
            overall_score=72.5,
            issues=["x"],
            suggestions=["y"],
        )
        assert s.overall_score == 72.5
