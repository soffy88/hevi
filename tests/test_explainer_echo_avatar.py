"""Explainer Echo: stamp presenter after cues, generate avatar after real TTS."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.explainer import assembly as explainer_assembly
from hevi.explainer.contracts import ExplainerCue
from hevi.explainer.echo_avatar import (
    PRESENTER_IMAGE_KEY,
    PRESENTER_VIDEO_KEY,
    attach_echo_avatar,
    concat_audio_files,
)
from hevi.explainer.schemas import ManifestSegment, Storyboard, StoryboardSegment


def test_assembly_does_not_call_talking_face_with_placeholder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    async def fake_render(storyboard, _output_dir, **_kwargs):
        captured["storyboard"] = storyboard
        return "rendered"

    async def forbidden_tf(**_kwargs):
        raise AssertionError("assembly must not generate talking face before TTS")

    monkeypatch.setattr(explainer_assembly, "render_narrated_storyboard", fake_render)
    monkeypatch.setattr(
        "hevi.digital_human.talking_face.generate_continuous_avatar_track",
        forbidden_tf,
    )
    import asyncio

    face = tmp_path / "face.jpg"
    face.write_bytes(b"\xff\xd8\xff")
    result = asyncio.run(
        explainer_assembly.assemble_explainer_cues(
            "主题",
            [ExplainerCue(visual_type="heygen_avatar", text="开场")],
            tmp_path,
            voice="cosyvoice_default",
            presenter_provider="remotion",
            presenter_image_url=str(face),
            packager={"presenter_image_url": str(face), "main_title": "T"},
        )
    )
    assert result == "rendered"
    storyboard = captured["storyboard"]
    cfg = storyboard.segments[0].visual_config
    assert cfg[PRESENTER_IMAGE_KEY] == str(face)
    packaging = cfg.get("packaging") or {}
    assert "presenter_image_url" not in packaging


def test_assembly_stamps_presenter_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    async def fake_render(storyboard, _output_dir, **_kwargs):
        captured["storyboard"] = storyboard
        return "rendered"

    monkeypatch.setattr(explainer_assembly, "render_narrated_storyboard", fake_render)
    import asyncio

    clip = tmp_path / "ref.mp4"
    clip.write_bytes(b"mp4")
    result = asyncio.run(
        explainer_assembly.assemble_explainer_cues(
            "主题",
            [ExplainerCue(visual_type="voiceover", text="开场")],
            tmp_path,
            voice="cosyvoice_default",
            presenter_reference_video=str(clip),
        )
    )
    assert result == "rendered"
    cfg = captured["storyboard"].segments[0].visual_config
    assert cfg[PRESENTER_VIDEO_KEY] == str(clip)


@pytest.mark.asyncio
async def test_attach_echo_after_real_wav(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    wav = audio_dir / "cue-1.wav"
    wav.write_bytes(b"RIFF....wav")
    face = tmp_path / "face.jpg"
    face.write_bytes(b"\xff\xd8\xff")
    public = tmp_path / "public"
    storyboard = Storyboard(
        topic="t",
        segments=[
            StoryboardSegment(
                id="cue-1",
                scene_type="hook",
                narration="hello",
                keywords=["a"],
                props={"title": "t", "subtitle": "s", "items": []},
                visual_config={PRESENTER_IMAGE_KEY: str(face)},
            )
        ],
    )
    manifest = [
        ManifestSegment(
            id="cue-1",
            scene_type="hook",
            text="hello",
            audio_file="audio/cue-1.wav",
            duration_sec=1.0,
            start_sec=0.0,
            keywords=["a"],
            props={"title": "t", "subtitle": "s", "items": []},
            captions=[],
        )
    ]

    async def fake_tf(*, image_path, audio_path, output_path, **_kwargs):
        assert Path(audio_path).exists()
        assert Path(audio_path).name == "master_voiceover.wav"
        assert Path(image_path).exists()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"echo-mp4")
        return Path(output_path)

    with patch(
        "hevi.explainer.echo_avatar.generate_talking_face",
        AsyncMock(side_effect=fake_tf),
    ):
        out = await attach_echo_avatar(
            storyboard=storyboard,
            manifest=manifest,
            output_dir=tmp_path / "run",
            audio_dir=audio_dir,
            remotion_public=public,
        )
    assert out is not None
    assert out.exists()
    assert (public / "continuous_avatar" / "continuous_avatar_l.mp4").exists()
    assert storyboard.segments[0].visual_config["packaging"]["presenter_image_url"] == str(
        face
    )
    assert storyboard.segments[0].visual_config["packaging"]["avatar_src"].endswith(
        "continuous_avatar_p.mp4"
    )
    assert manifest[0].visual_config["packaging"]["presenter_image_url"] == str(face)


@pytest.mark.asyncio
async def test_attach_echo_raises_when_photo_but_no_audio(tmp_path: Path) -> None:
    face = tmp_path / "face.jpg"
    face.write_bytes(b"\xff\xd8\xff")
    storyboard = Storyboard(
        topic="t",
        segments=[
            StoryboardSegment(
                id="cue-1",
                scene_type="hook",
                narration="hello",
                keywords=["a"],
                props={"title": "t", "subtitle": "s", "items": []},
                visual_config={PRESENTER_IMAGE_KEY: str(face)},
            )
        ],
    )
    with pytest.raises(FileNotFoundError, match="配音"):
        await attach_echo_avatar(
            storyboard=storyboard,
            manifest=[],
            output_dir=tmp_path / "run",
            audio_dir=tmp_path / "audio",
            remotion_public=tmp_path / "public",
        )


def test_concat_audio_single_copy(tmp_path: Path) -> None:
    src = tmp_path / "a.wav"
    src.write_bytes(b"RIFF")
    dest = tmp_path / "m.wav"
    concat_audio_files([src], dest)
    assert dest.read_bytes() == b"RIFF"
