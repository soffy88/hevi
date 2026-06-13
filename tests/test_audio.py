from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.audio import (
    AudioProvider,
    BGMLibrary,
    generate_avatar_clip,
    synthesize_dialogue,
)
from hevi.providers.registry import ProviderRegistry, register_all_providers


@dataclass
class MockSpeakerLine:
    speaker_id: str
    text: str
    voice_ref: Path | str | None = None


@pytest.fixture
def mock_config():
    return {"api_key": "test_key"}


@pytest.fixture
def output_path(tmp_path):
    return tmp_path / "output.wav"


@pytest.fixture
def portrait_image(tmp_path):
    img = tmp_path / "portrait.png"
    img.write_text("dummy")
    return img


@pytest.fixture
def audio_path(tmp_path):
    aud = tmp_path / "input.wav"
    aud.write_text("dummy")
    return aud


@pytest.mark.asyncio
async def test_synthesize_dialogue_single(mock_config, output_path):
    with patch("hevi.audio.tts_service.vibevoice_synthesize", new_callable=AsyncMock) as mock_vv:
        mock_vv.return_value = output_path
        script = [MockSpeakerLine(speaker_id="spk1", text="Hello")]
        res = await synthesize_dialogue(
            config=mock_config, script=script, output_path=output_path  # type: ignore
        )
        assert res == output_path
        mock_vv.assert_called_once_with(
            config=mock_config, script=script, output_path=output_path, watermark=True
        )


@pytest.mark.asyncio
async def test_synthesize_dialogue_multi(mock_config, output_path):
    with patch("hevi.audio.tts_service.vibevoice_synthesize", new_callable=AsyncMock) as mock_vv:
        mock_vv.return_value = output_path
        script = [
            MockSpeakerLine(speaker_id="spk1", text="Hello"),
            MockSpeakerLine(speaker_id="spk2", text="Hi there"),
            MockSpeakerLine(speaker_id="spk1", text="How are you?"),
            MockSpeakerLine(speaker_id="spk3", text="Good morning"),
        ]
        await synthesize_dialogue(
            config=mock_config, script=script, output_path=output_path  # type: ignore
        )
        assert mock_vv.call_args.kwargs["script"] == script


@pytest.mark.asyncio
async def test_synthesize_dialogue_voice_ref(mock_config, output_path):
    with patch("hevi.audio.tts_service.vibevoice_synthesize", new_callable=AsyncMock) as mock_vv:
        mock_vv.return_value = output_path
        script = [MockSpeakerLine(speaker_id="spk1", text="Hello", voice_ref="ref.wav")]
        await synthesize_dialogue(
            config=mock_config, script=script, output_path=output_path  # type: ignore
        )
        assert mock_vv.call_args.kwargs["script"][0].voice_ref == "ref.wav"


@pytest.mark.asyncio
async def test_synthesize_dialogue_watermark_enforced(mock_config, output_path):
    with patch("hevi.audio.tts_service.vibevoice_synthesize", new_callable=AsyncMock) as mock_vv:
        mock_vv.return_value = output_path
        # Test explicit True
        await synthesize_dialogue(
            config=mock_config,
            script=[MockSpeakerLine(speaker_id="1", text="a")],  # type: ignore
            output_path=output_path,
            watermark=True,
        )
        assert mock_vv.call_args.kwargs["watermark"] is True

        # Test explicit False
        await synthesize_dialogue(
            config=mock_config,
            script=[MockSpeakerLine(speaker_id="1", text="a")],  # type: ignore
            output_path=output_path,
            watermark=False,
        )
        assert mock_vv.call_args.kwargs["watermark"] is False


@pytest.mark.asyncio
async def test_synthesize_dialogue_empty_script(mock_config, output_path):
    with pytest.raises(ValueError, match="Script cannot be empty"):
        await synthesize_dialogue(config=mock_config, script=[], output_path=output_path)


@pytest.mark.asyncio
async def test_generate_avatar_clip_duix(mock_config, portrait_image, audio_path, tmp_path):
    out = tmp_path / "avatar.mp4"
    with patch("hevi.audio.avatar_service.avatar_generate", new_callable=AsyncMock) as mock_avatar:
        mock_avatar.return_value = out
        res = await generate_avatar_clip(
            config=mock_config,
            portrait_image=portrait_image,
            audio_path=audio_path,
            output_path=out,
        )
        assert res == out
        mock_avatar.assert_called_once_with(
            config=mock_config,
            provider="duix",
            portrait_image=portrait_image,
            audio_path=audio_path,
            output_path=out,
        )


def test_audio_provider_enum():
    assert AudioProvider.VIBEVOICE == "vibevoice"
    assert AudioProvider.DUIX == "duix"
    assert AudioProvider.LTX2_NATIVE == "ltx2_native"


def test_bgm_library_dirs(tmp_path):
    BGMLibrary(root_dir=tmp_path)
    assert (tmp_path / "bgm").exists()
    assert (tmp_path / "sfx").exists()


def test_bgm_library_list_bgm(tmp_path):
    lib = BGMLibrary(root_dir=tmp_path)
    # Create some files
    mood_dir = tmp_path / "bgm" / "happy"
    mood_dir.mkdir(parents=True)
    (mood_dir / "track1.mp3").write_text("dummy")
    (mood_dir / "track2.mp3").write_text("dummy")

    # List all
    all_bgm = lib.list_bgm()
    assert len(all_bgm) == 2

    # List by mood
    happy_bgm = lib.list_bgm(mood="happy")
    assert len(happy_bgm) == 2

    # List unknown mood
    assert lib.list_bgm(mood="sad") == []


def test_bgm_library_get_sfx(tmp_path):
    lib = BGMLibrary(root_dir=tmp_path)
    sfx_file = tmp_path / "sfx" / "boom.wav"
    sfx_file.write_text("dummy")

    assert lib.get_sfx("boom") == sfx_file
    assert lib.get_sfx("nonexistent") is None


def test_bgm_library_get_bgm_path(tmp_path):
    lib = BGMLibrary(root_dir=tmp_path)
    bgm_file = tmp_path / "bgm" / "happy" / "track1.mp3"
    bgm_file.parent.mkdir(parents=True)
    bgm_file.write_text("dummy")

    assert lib.get_bgm_path("happy/track1.mp3") == bgm_file
    assert lib.get_bgm_path("invalid.mp3") is None


def test_register_all_providers_audio():
    ProviderRegistry._providers = {}
    with patch("hevi.providers.registry.ltx2_cloud_generate"), patch(
        "hevi.providers.registry.video_generate"
    ), patch("hevi.providers.registry.vibevoice_synthesize"), patch(
        "hevi.providers.registry.avatar_generate"
    ):
        register_all_providers()

        assert ("audio", "vibevoice") in ProviderRegistry._providers
        assert ("audio", "duix") in ProviderRegistry._providers
        # Also ensure video still there
        assert ("video", "ltx2_cloud") in ProviderRegistry._providers
