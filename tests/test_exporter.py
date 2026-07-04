"""hevi.assembly.exporter 测试 —— 成片导出格式转换。mp4/mov 走真 ffmpeg(需环境有);
webm/gif 转码逻辑用 mock 验证参数拼装,不依赖本机 ffmpeg 是否装了 vp9/opus。"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.assembly.exporter import EXPORT_FORMATS, content_type_for, export_video

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_export_formats_list() -> None:
    assert EXPORT_FORMATS == ("mp4", "mov", "webm", "gif")


def test_content_type_for_each_format() -> None:
    assert content_type_for("mp4") == "video/mp4"
    assert content_type_for("mov") == "video/quicktime"
    assert content_type_for("webm") == "video/webm"
    assert content_type_for("gif") == "image/gif"


@pytest.mark.asyncio
async def test_export_video_rejects_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        await export_video(tmp_path / "in.mp4", tmp_path / "out.avi", "avi")


@pytest.mark.asyncio
async def test_export_video_mp4_is_plain_copy(tmp_path: Path) -> None:
    """mp4 → 零成本直传(copy),不调 ffmpeg。"""
    src = tmp_path / "in.mp4"
    src.write_bytes(b"\x00" * 128)
    dst = tmp_path / "out.mp4"
    with patch("hevi.assembly.exporter.ffmpeg_run", new_callable=AsyncMock) as mrun:
        result = await export_video(src, dst, "mp4")
    mrun.assert_not_called()
    assert result == dst
    assert dst.read_bytes() == src.read_bytes()


@pytest.mark.asyncio
async def test_export_video_mov_remux_calls_ffmpeg_copy(tmp_path: Path) -> None:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"\x00" * 128)
    dst = tmp_path / "out.mov"
    with patch("hevi.assembly.exporter.ffmpeg_run", new_callable=AsyncMock) as mrun:
        await export_video(src, dst, "mov")
    args = mrun.await_args.kwargs["args"]
    assert "-c" in args and "copy" in args  # 纯换封装,不重编码


@pytest.mark.asyncio
async def test_export_video_webm_uses_vp9_opus(tmp_path: Path) -> None:
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.webm"
    with patch("hevi.assembly.exporter.ffmpeg_run", new_callable=AsyncMock) as mrun:
        await export_video(src, dst, "webm")
    args = mrun.await_args.kwargs["args"]
    assert "libvpx-vp9" in args and "libopus" in args


@pytest.mark.asyncio
async def test_export_video_gif_uses_fps_scale_filter(tmp_path: Path) -> None:
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.gif"
    with patch("hevi.assembly.exporter.ffmpeg_run", new_callable=AsyncMock) as mrun:
        await export_video(src, dst, "gif")
    args = mrun.await_args.kwargs["args"]
    vf_idx = args.index("-vf")
    assert "fps=10" in args[vf_idx + 1]
