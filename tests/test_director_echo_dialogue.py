"""Director cloud_avatar dialogue prefers Echo, falls back to happyhorse."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.tongjian.scene_render_avatar import _render_dialogue_talk


@pytest.mark.asyncio
async def test_dialogue_uses_echo_when_engine_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALKING_FACE_ENGINE", "echomimic")
    image = tmp_path / "kf.png"
    image.write_bytes(b"png")
    out = tmp_path / "talk.mp4"
    hh = AsyncMock(side_effect=AssertionError("happyhorse should not run"))

    async def fake_tts(text, path):
        Path(path).write_bytes(b"RIFF")
        return Path(path)

    async def fake_echo(*, image_path, audio_path, output_path):
        assert Path(audio_path).read_bytes() == b"RIFF"
        Path(output_path).write_bytes(b"echo")
        return Path(output_path)

    with (
        patch("hevi.digital_human.line_tts.synthesize_line", fake_tts),
        patch(
            "hevi.digital_human.talking_face.generate_talking_face",
            fake_echo,
        ),
        patch("hevi.tongjian.scene_render_avatar.happyhorse_animate", hh),
    ):
        await _render_dialogue_talk(
            image_path=image,
            text="臣敢言",
            output_path=out,
            duration=5,
            resolution="720P",
            style="卡通",
            emotion="沉稳",
            per_char=0.18,
            concat_fn=lambda *_a, **_k: None,
        )
    assert out.read_bytes() == b"echo"
    hh.assert_not_called()


@pytest.mark.asyncio
async def test_dialogue_falls_back_to_happyhorse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALKING_FACE_ENGINE", "echomimic")
    image = tmp_path / "kf.png"
    image.write_bytes(b"png")
    out = tmp_path / "talk.mp4"

    async def boom(*_a, **_k):
        raise RuntimeError("echo down")

    async def fake_hh(*, output_path, **_k):
        Path(output_path).write_bytes(b"hh")

    with (
        patch("hevi.digital_human.line_tts.synthesize_line", boom),
        patch("hevi.tongjian.scene_render_avatar.happyhorse_animate", fake_hh),
    ):
        await _render_dialogue_talk(
            image_path=image,
            text="臣敢言",
            output_path=out,
            duration=5,
            resolution="720P",
            style="卡通",
            emotion="沉稳",
            per_char=0.18,
            concat_fn=lambda *_a, **_k: None,
        )
    assert out.read_bytes() == b"hh"
