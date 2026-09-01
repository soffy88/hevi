"""Executable 3O transactions for localization, shorts and Pocket TTS."""

from __future__ import annotations

import asyncio
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from hevi.production.media_workflows import (
    shorts_generation_workflow,
    video_localization_workflow,
)


def test_video_localization_workflow_executes_and_returns_3o_result(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    async def fake_burn(_video, _subtitles, output, **_kwargs):
        output.write_bytes(b"localized")
        return output

    monkeypatch.setattr("hevi.production.media_workflows._burn_subtitles", fake_burn)
    result = asyncio.run(
        video_localization_workflow(
            {
                "target_language": "zh-CN",
                "bilingual": True,
            },
            {
                "source_video_path": str(source),
                "source_segments": [
                    {"start": 0, "end": 2, "text": "The secret is MCP."},
                ],
                "translated_segments": [
                    {"start": 0, "end": 2, "text": "秘密就是 MCP"},
                ],
            },
            tmp_path / "localize",
        )
    )
    assert result["status"] == "succeeded"
    assert result["fingerprint"]
    assert result["cost_usd"] == 0.0
    assert len(result["decision_trail"]) >= 4
    assert Path(result["findings"]["output_video_path"]).read_bytes() == b"localized"
    assert Path(result["report_path"]).is_file()
    assert {item["kind"] for item in result["artifacts"]} == {"video", "subtitle"}


def test_video_localization_fails_closed_and_writes_report(tmp_path: Path) -> None:
    result = asyncio.run(
        video_localization_workflow(
            {},
            {"source_video_path": str(tmp_path / "missing.mp4")},
            tmp_path / "localize",
        )
    )
    assert result["status"] == "failed"
    assert result["artifacts"] == []
    assert Path(result["report_path"]).is_file()


def test_shorts_generation_workflow_is_standard_transaction(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"clip")
    subtitle = tmp_path / "clip.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHook\n", encoding="utf-8")
    manifest = {
        "artifacts": [
            {
                "kind": "video",
                "path": str(clip),
                "media_type": "video/mp4",
                "primary": True,
            },
            {
                "kind": "subtitle",
                "path": str(subtitle),
                "media_type": "application/x-subrip",
            },
        ]
    }

    monkeypatch.setattr(
        "hevi.production.media_workflows.render_clip_batch",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "result_video_path": str(clip),
            "clips": [{"index": 1, "path": str(clip)}],
            "quality": {"passed": True},
            "config_json": {"artifact_manifest": manifest},
        },
    )
    result = asyncio.run(
        shorts_generation_workflow(
            {"target_clips": 1},
            {"source_video_path": str(source)},
            tmp_path / "shorts",
        )
    )
    assert result["status"] == "succeeded"
    assert result["findings"]["total_shots"] == 1
    assert Path(result["report_path"]).is_file()


def test_pocket_tts_adapter_uses_public_model_api(tmp_path: Path, monkeypatch) -> None:
    from hevi.audio import pocket_tts_service as pocket

    calls: dict[str, str] = {}

    class FakeModel:
        sample_rate = 24_000

        def get_state_for_audio_prompt(self, voice: str):
            calls["voice"] = voice
            return "state"

        def generate_audio(self, state: str, text: str):
            calls["state"] = state
            calls["text"] = text
            return SimpleNamespace()

    monkeypatch.setattr(pocket, "_import_pocket_tts", lambda: SimpleNamespace(TTSModel=FakeModel))
    monkeypatch.setattr(pocket, "_load_model", lambda _config: FakeModel())
    monkeypatch.setattr(pocket, "_write_wav", lambda path, _rate, _audio: path.write_bytes(b"RIFF"))
    output = asyncio.run(
        pocket.synth_with_pocket_tts("hello", output_path=tmp_path / "pocket.wav", voice="alba")
    )
    assert output.is_file()
    assert calls == {"voice": "alba", "state": "state", "text": "hello"}


@pytest.mark.skipif(
    not (shutil.which("espeak-ng") or shutil.which("espeak")),
    reason="HEVI native voice runtime is not installed on this host",
)
def test_pocket_and_voxcpm_capabilities_run_without_upstream_packages(
    tmp_path: Path, monkeypatch
) -> None:
    from hevi.audio import pocket_tts_service as pocket
    from hevi.audio import voxcpm_service as vox

    monkeypatch.setattr(pocket, "_import_pocket_tts", lambda: None)
    monkeypatch.setattr(vox, "_import_voxcpm", lambda: None)
    # Keep this contract test on HEVI's native fallback even when the local
    # developer .env enables the optional isolated VoxCPM worker.
    monkeypatch.setenv("HEVI_VOXCPM_PYTHON", "")
    reference = tmp_path / "reference.wav"
    with wave.open(str(reference), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(22_050)
        stream.writeframes(b"\x00\x00" * 2_205)

    async def run() -> None:
        pocket_path = tmp_path / "native-pocket.wav"
        vox_path = tmp_path / "native-voxcpm.wav"
        await pocket.synth_with_pocket_tts(
            "HEVI native low resource voice.",
            output_path=pocket_path,
            voice="alba",
            language="en",
            reference_audio=reference,
        )
        await vox.synth_with_voxcpm(
            "HEVI native voice design.",
            vox_path,
            language="en",
            voice_design="deep and slow",
        )
        for path in (pocket_path, vox_path):
            with wave.open(str(path), "rb") as stream:
                assert stream.getnframes() > 0

        chunks = [
            chunk
            async for chunk in pocket.stream_pocket_tts("One. Two.", language="en")
        ]
        assert len(chunks) == 2
        assert chunks[-1].final is True

    asyncio.run(run())


@pytest.mark.skipif(
    not (shutil.which("espeak-ng") or shutil.which("espeak")),
    reason="HEVI native voice runtime is not installed on this host",
)
def test_native_voice_is_a_standard_omodul_transaction(tmp_path: Path) -> None:
    from hevi.voicepro.omodul import native_voice_workflow

    result = asyncio.run(
        native_voice_workflow(
            {"engine": "pocket_tts", "language": "en", "voice": "alba"},
            {"text": "HEVI native transaction."},
            tmp_path / "native-omodul",
        )
    )
    assert result["status"] == "succeeded"
    assert result["pillars"] == ["cost", "decision_trail", "fingerprint", "report"]
    assert result["artifacts"]
    assert Path(result["report_path"]).is_file()
