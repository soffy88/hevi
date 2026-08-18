"""Duix offline silent lip-sync: start/stop + exclusive with Echo."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.digital_human.duix_offline import generate_silent_duix
from hevi.digital_human.talking_face import TalkingFaceUnavailable, generate_talking_face


def _write_silent(_src: Path, dest: Path) -> Path:
    dest.write_bytes(b"silent")
    return dest


@pytest.mark.asyncio
async def test_generate_silent_duix_stops_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DUIX_STOP_AFTER", "1")
    reference = tmp_path / "face.jpg"
    audio = tmp_path / "master.wav"
    output = tmp_path / "silent.mp4"
    reference.write_bytes(b"jpg")
    audio.write_bytes(b"RIFF")
    stopped: list[int] = []

    async def fake_clip(*, output_path: Path, **_kwargs: object) -> Path:
        output_path.write_bytes(b"raw-mp4")
        return output_path

    monkeypatch.setattr("hevi.digital_human.duix_offline.start_duix_container", lambda: True)
    monkeypatch.setattr("hevi.digital_human.duix_offline.wait_duix_ready", lambda: None)
    monkeypatch.setattr(
        "hevi.digital_human.duix_offline.stop_duix_container",
        lambda: stopped.append(1),
    )
    monkeypatch.setattr(
        "hevi.digital_human.duix_offline.strip_audio",
        _write_silent,
    )
    monkeypatch.setattr(
        "hevi.digital_human.duix_offline.assert_lipsync_duration",
        lambda *_a, **_k: None,
    )

    with patch(
        "hevi.audio.avatar_service.generate_avatar_clip",
        AsyncMock(side_effect=fake_clip),
    ):
        result = await generate_silent_duix(
            reference=reference, audio_path=audio, output_path=output
        )
    assert result.read_bytes() == b"silent"
    assert stopped == [1]


@pytest.mark.asyncio
async def test_already_running_duix_still_stops_when_flag_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DUIX_STOP_AFTER", "1")
    reference = tmp_path / "face.jpg"
    audio = tmp_path / "master.wav"
    output = tmp_path / "silent.mp4"
    reference.write_bytes(b"jpg")
    audio.write_bytes(b"RIFF")
    stopped: list[int] = []

    async def fake_clip(*, output_path: Path, **_kwargs: object) -> Path:
        output_path.write_bytes(b"raw-mp4")
        return output_path

    monkeypatch.setattr("hevi.digital_human.duix_offline.start_duix_container", lambda: False)
    monkeypatch.setattr("hevi.digital_human.duix_offline.wait_duix_ready", lambda: None)
    monkeypatch.setattr(
        "hevi.digital_human.duix_offline.stop_duix_container",
        lambda: stopped.append(1),
    )
    monkeypatch.setattr(
        "hevi.digital_human.duix_offline.strip_audio",
        _write_silent,
    )
    monkeypatch.setattr(
        "hevi.digital_human.duix_offline.assert_lipsync_duration",
        lambda *_a, **_k: None,
    )

    with patch(
        "hevi.audio.avatar_service.generate_avatar_clip",
        AsyncMock(side_effect=fake_clip),
    ):
        await generate_silent_duix(reference=reference, audio_path=audio, output_path=output)
    assert stopped == [1]


@pytest.mark.asyncio
async def test_talking_face_duix_does_not_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALKING_FACE_ENGINE", "duix")
    image = tmp_path / "face.jpg"
    audio = tmp_path / "line.wav"
    image.write_bytes(b"\xff\xd8\xff")
    audio.write_bytes(b"RIFF....")
    out = tmp_path / "talk.mp4"
    with (
        patch(
            "hevi.digital_human.talking_face._engine_capabilities",
            AsyncMock(return_value={"longcat": False}),
        ),
        patch(
            "hevi.digital_human.talking_face._run_duix_offline",
            AsyncMock(side_effect=TalkingFaceUnavailable("duix down")),
        ),
        patch(
            "hevi.digital_human.talking_face._run_echo_mimic",
            AsyncMock(side_effect=AssertionError("duix must not call echo")),
        ),
        patch(
            "hevi.digital_human.talking_face._generate_placeholder_avoiding_null",
            AsyncMock(side_effect=AssertionError("must not placeholder")),
        ),
    ):
        with pytest.raises(TalkingFaceUnavailable, match="duix down"):
            await generate_talking_face(
                image_path=image, audio_path=audio, output_path=out
            )


@pytest.mark.asyncio
async def test_talking_face_echo_does_not_call_duix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALKING_FACE_ENGINE", "echomimic")
    image = tmp_path / "face.jpg"
    audio = tmp_path / "line.wav"
    out = tmp_path / "talk.mp4"
    image.write_bytes(b"\xff\xd8\xff")
    audio.write_bytes(b"RIFF....")

    async def fake_echo(**_kwargs: object) -> Path:
        out.write_bytes(b"echo")
        return out

    with (
        patch(
            "hevi.digital_human.talking_face._engine_capabilities",
            AsyncMock(return_value={"longcat": False}),
        ),
        patch("hevi.digital_human.talking_face._run_echo_mimic", fake_echo),
        patch(
            "hevi.digital_human.talking_face._run_duix_offline",
            AsyncMock(side_effect=AssertionError("echo must not call duix")),
        ),
    ):
        result = await generate_talking_face(
            image_path=image, audio_path=audio, output_path=out
        )
    assert result.read_bytes() == b"echo"
