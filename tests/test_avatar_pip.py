"""Avatar PiP geometry + compose helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hevi.explainer.avatar_pip import (
    AVATAR_PIP_MARGIN,
    AVATAR_PIP_SIZE,
    AvatarPipLayout,
    assert_lipsync_duration,
    compose_avatar_overlay,
    overlay_filter,
)
from hevi.explainer.echo_avatar import PRESENTER_IMAGE_KEY
from hevi.explainer.render import should_compose_avatar
from hevi.explainer.schemas import Storyboard, StoryboardSegment


def _storyboard_with_photo(path: str) -> Storyboard:
    return Storyboard(
        topic="t",
        segments=[
            StoryboardSegment(
                id="cue-1",
                scene_type="hook",
                narration="hello",
                keywords=["a"],
                props={"title": "t", "subtitle": "s", "items": []},
                visual_config={PRESENTER_IMAGE_KEY: path},
            )
        ],
    )


def test_pip_is_300_circle_bottom_left() -> None:
    pip = AvatarPipLayout()
    assert pip.size == 300
    assert pip.margin == 24
    assert pip.position == "bottom_left"
    assert pip.shape == "circle"
    assert pip.overlay_xy(1080, 1920) == (
        AVATAR_PIP_MARGIN,
        1920 - AVATAR_PIP_SIZE - AVATAR_PIP_MARGIN,
    )
    assert pip.subtitle_padding_bottom() == 364


def test_pip_does_not_overlap_reserved_caption_band() -> None:
    pip = AvatarPipLayout()
    assert pip.overlaps_subtitle_band(1920, 190, 80) is True
    assert pip.overlaps_subtitle_band(1920, pip.subtitle_padding_bottom(), 80) is False


def test_overlay_filter_is_circle_bottom_left() -> None:
    filt = overlay_filter()
    assert "scale=300:300" in filt
    assert "crop=300:300" in filt
    assert "overlay=x=24:" in filt
    assert "geq=" in filt


def test_preview_dir_skips_avatar_compose(tmp_path: Path) -> None:
    board = _storyboard_with_photo("/tmp/face.jpg")
    assert should_compose_avatar(tmp_path / "preview", board) is False
    assert should_compose_avatar(tmp_path / "full", board) is True
    empty = Storyboard(topic="t", segments=[])
    assert should_compose_avatar(tmp_path / "full", empty) is False


def test_compose_avatar_overlay_keeps_base_audio(tmp_path: Path) -> None:
    base = tmp_path / "base.mp4"
    avatar = tmp_path / "avatar.mp4"
    dest = tmp_path / "out.mp4"
    base.write_bytes(b"base")
    avatar.write_bytes(b"face")

    def fake_run(cmd, **_kwargs):
        dest.write_bytes(b"composed")
        assert "-shortest" not in cmd
        assert "0:a?" in cmd
        return SimpleNamespace(returncode=0, stderr="")

    with patch("hevi.explainer.avatar_pip.subprocess.run", side_effect=fake_run):
        compose_avatar_overlay(base, avatar, dest)
    assert dest.read_bytes() == b"composed"


def test_assert_lipsync_duration_rejects_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.wav"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    monkeypatch.setattr(
        "hevi.explainer.avatar_pip.probe_duration",
        lambda path: 10.0 if path.suffix == ".mp4" else 20.0,
    )
    with pytest.raises(RuntimeError, match="不一致"):
        assert_lipsync_duration(video, audio)
