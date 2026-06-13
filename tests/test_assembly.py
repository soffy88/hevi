from unittest.mock import AsyncMock, patch

import pytest

from hevi.assembly.aspect_ratio import AspectRatio, get_aspect_ratio_filter
from hevi.assembly.cover_extractor import extract_cover
from hevi.assembly.postprocess_service import postprocess_video
from hevi.assembly.subtitle_burner import get_subtitle_filter
from hevi.assembly.transition import get_fade_in_out_filter, get_xfade_filter


@pytest.fixture
def mock_video(tmp_path):
    v = tmp_path / "input.mp4"
    v.write_text("dummy")
    return v


@pytest.fixture
def mock_subtitle(tmp_path):
    s = tmp_path / "sub.srt"
    s.write_text("1\n00:00:01,000 --> 00:00:04,000\nHello")
    return s


@pytest.mark.asyncio
async def test_extract_cover(mock_video, tmp_path):
    out = tmp_path / "cover.jpg"
    with patch("hevi.assembly.cover_extractor.run", new_callable=AsyncMock) as mock_run:

        # Simulate file creation by run
        def side_effect(*args, **kwargs):
            out.write_text("dummy cover")
            return "done"

        mock_run.side_effect = side_effect

        res = await extract_cover(mock_video, out)
        assert res == out
        assert out.exists()
        mock_run.assert_called_once()


def test_aspect_ratio_filters():
    assert "crop=ih*9/16:ih" in get_aspect_ratio_filter(AspectRatio.RATIO_9_16)
    assert "scale=1920:1080" in get_aspect_ratio_filter(AspectRatio.RATIO_16_9)
    assert "crop=ih:ih" in get_aspect_ratio_filter(AspectRatio.RATIO_1_1)

    with pytest.raises(ValueError):
        get_aspect_ratio_filter("invalid")


def test_subtitle_filters(tmp_path):
    sub = tmp_path / "test.srt"
    f = get_subtitle_filter(sub)
    assert "subtitles=" in f
    assert str(sub).replace("\\", "/").replace(":", "\\:") in f

    f_style = get_subtitle_filter(sub, style="bold_yellow")
    assert "PrimaryColour=&H00FFFF" in f_style


def test_transition_filters():
    assert "xfade" in get_xfade_filter(offset=5.0)
    assert "fade=t=in" in get_fade_in_out_filter(duration=10.0)
    assert "fade=t=out" in get_fade_in_out_filter(duration=10.0, end_fade_out=10.0)


@pytest.mark.asyncio
async def test_postprocess_video_basic(mock_video, tmp_path, mock_subtitle):
    out_dir = tmp_path / "output"
    with patch(
        "hevi.assembly.postprocess_service.run", new_callable=AsyncMock
    ) as mock_run, patch(
        "hevi.assembly.postprocess_service.extract_cover", new_callable=AsyncMock
    ) as mock_extract:

        mock_extract.return_value = out_dir / "cover.jpg"

        results = await postprocess_video(
            input_video=mock_video,
            aspect_ratios=[AspectRatio.RATIO_9_16, "16:9"],
            subtitle_path=mock_subtitle,
            watermark="Hevi AI",
            output_dir=out_dir,
        )

        assert "cover" in results
        assert "9:16" in results
        assert "16:9" in results

        # Should have called mock_run for each aspect ratio
        assert mock_run.call_count == 2

        # Verify filter components in one call
        last_call_args = mock_run.call_args.kwargs["args"]
        vf_idx = last_call_args.index("-vf")
        filter_str = last_call_args[vf_idx + 1]

        assert "Hevi AI" in filter_str
        assert "subtitles" in filter_str
        assert "fade" in filter_str


@pytest.mark.asyncio
async def test_postprocess_video_no_sub_no_watermark(mock_video, tmp_path):
    out_dir = tmp_path / "output"
    with patch("hevi.assembly.postprocess_service.run", new_callable=AsyncMock), patch(
        "hevi.assembly.postprocess_service.extract_cover", new_callable=AsyncMock
    ):

        results = await postprocess_video(
            input_video=mock_video, aspect_ratios=[AspectRatio.RATIO_9_16], output_dir=out_dir
        )
        assert "9:16" in results


@pytest.mark.asyncio
async def test_postprocess_invalid_ratio(mock_video, tmp_path):
    with patch("hevi.assembly.postprocess_service.extract_cover", new_callable=AsyncMock):
        with pytest.raises(ValueError):
            await postprocess_video(
                input_video=mock_video, aspect_ratios=["invalid"], output_dir=tmp_path / "out"
            )
