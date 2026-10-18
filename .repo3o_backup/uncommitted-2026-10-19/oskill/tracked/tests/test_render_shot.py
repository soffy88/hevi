"""Tests for render_shot."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from oprim._shot_types import ShotResult

from oskill._render_shot import render_shot


def _clean_html():
    return "<html><body><div>animation</div></body></html>"


class TestRenderShot:
    @patch("oskill._render_shot.render_html_to_mp4", new_callable=AsyncMock)
    async def test_code_render_returns_shot_result(self, mock_r, tmp_path):
        out = tmp_path / "shot.mp4"
        mock_r.return_value = out
        result = await render_shot(
            shot_type="code_render",
            shot_spec={"html": _clean_html(), "duration_s": 3.0},
            output_path=out,
        )
        assert isinstance(result, ShotResult)
        assert result.shot_type == "code_render"

    @patch("oskill._render_shot.render_html_to_mp4", new_callable=AsyncMock)
    async def test_code_render_shot_type_set(self, mock_r, tmp_path):
        out = tmp_path / "s.mp4"
        mock_r.return_value = out
        result = await render_shot(
            shot_type="code_render",
            shot_spec={"html": _clean_html(), "duration_s": 5.0},
            output_path=out,
        )
        assert result.shot_type == "code_render"
        assert result.duration_s == 5.0

    @patch("oskill._render_shot.render_html_to_mp4", new_callable=AsyncMock)
    async def test_code_render_html_error_is_captured(self, mock_r, tmp_path):
        from oprim._render_html_to_mp4 import RenderHtmlError

        mock_r.side_effect = RenderHtmlError("Unsafe HTML: violations")
        out = tmp_path / "s.mp4"
        result = await render_shot(
            shot_type="code_render",
            shot_spec={"html": "<bad/>", "duration_s": 2.0},
            output_path=out,
        )
        assert result.is_valid is False
        assert len(result.validation_violations) > 0

    @patch("oskill._render_shot.video_generate", new_callable=AsyncMock)
    async def test_generative_returns_shot_result(self, mock_gen, tmp_path):
        out = tmp_path / "gen.mp4"
        out.write_bytes(b"\x00")
        mock_gen.return_value = out
        result = await render_shot(
            shot_type="generative",
            shot_spec={"provider": "wan_local", "prompt": "Cat on moon", "duration_s": 5.0},
            output_path=out,
        )
        assert isinstance(result, ShotResult)
        assert result.shot_type == "generative"

    @patch("oskill._render_shot.video_generate", new_callable=AsyncMock)
    async def test_generative_provider_in_metadata(self, mock_gen, tmp_path):
        out = tmp_path / "gen.mp4"
        out.write_bytes(b"\x00")
        mock_gen.return_value = out
        result = await render_shot(
            shot_type="generative",
            shot_spec={"provider": "wan_cloud", "prompt": "X", "duration_s": 3.0},
            output_path=out,
        )
        assert result.metadata.get("provider") == "wan_cloud"

    @patch("oskill._render_shot.video_generate", new_callable=AsyncMock)
    async def test_generative_error_captured_not_raised(self, mock_gen, tmp_path):
        from oprim._video_generate import VideoGenError

        mock_gen.side_effect = VideoGenError("provider offline")
        out = tmp_path / "gen.mp4"
        result = await render_shot(
            shot_type="generative",
            shot_spec={"provider": "wan_local", "prompt": "X", "duration_s": 5.0},
            output_path=out,
        )
        assert result.is_valid is False

    async def test_invalid_shot_type_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown shot_type"):
            await render_shot(
                shot_type="unknown_type",
                shot_spec={},
                output_path=tmp_path / "x.mp4",
            )

    @patch("oskill._render_shot.render_html_to_mp4", new_callable=AsyncMock)
    async def test_output_path_returned_in_result(self, mock_r, tmp_path):
        out = tmp_path / "my_shot.mp4"
        mock_r.return_value = out
        result = await render_shot(
            shot_type="code_render",
            shot_spec={"html": _clean_html(), "duration_s": 2.0},
            output_path=out,
        )
        assert result.output_path == out

    @patch("oskill._render_shot.render_html_to_mp4", new_callable=AsyncMock)
    async def test_default_duration_is_5(self, mock_r, tmp_path):
        out = tmp_path / "s.mp4"
        mock_r.return_value = out
        result = await render_shot(
            shot_type="code_render",
            shot_spec={"html": _clean_html()},  # no duration_s
            output_path=out,
        )
        assert result.duration_s == 5.0
