from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from hevi.api.routers.voice_studio import SynthesisRequest, synthesize
from hevi.audio.task_adapter import execute_voice_studio_task
from hevi.production.artifacts import ArtifactManifest


@pytest.mark.asyncio
async def test_voice_studio_adapter_persists_nonempty_wav_manifest(tmp_path, monkeypatch) -> None:
    task_id = uuid4()

    async def fake_synthesize(*, script, output_path, emotion=None):
        assert script[0].text == "测试配音"
        assert emotion == "warm"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFF-wav")
        return output_path

    monkeypatch.setattr("hevi.audio.task_adapter.voicebox_synthesize", fake_synthesize)
    monkeypatch.setattr("hevi.audio.task_adapter.Path", lambda *_: tmp_path)
    result = await execute_voice_studio_task(
        {"id": task_id, "config_json": {"text": "测试配音", "effects": "warm"}},
        MagicMock(),
    )

    manifest = ArtifactManifest.model_validate(result["config_json"]["artifact_manifest"])
    assert manifest.path_for("audio") is not None


@pytest.mark.asyncio
async def test_voice_studio_fallback_is_explicitly_recorded(tmp_path, monkeypatch) -> None:
    from hevi.explainer.voicebox_client import VoiceboxError

    task_id = uuid4()

    async def fail_voicebox(**_kwargs):
        raise VoiceboxError("sidecar down")

    async def edge_fallback(*, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFF-edge")
        return output_path

    monkeypatch.setenv("VOICEBOX_ALLOW_EDGE_FALLBACK", "1")
    monkeypatch.setattr("hevi.audio.task_adapter.voicebox_synthesize", fail_voicebox)
    monkeypatch.setattr("hevi.audio.task_adapter.synthesize_with_voice_control", edge_fallback)
    monkeypatch.setattr("hevi.audio.task_adapter.Path", lambda *_: tmp_path)

    result = await execute_voice_studio_task(
        {"id": task_id, "config_json": {"text": "降级测试"}}, MagicMock()
    )

    assert result["config_json"]["audio_provider_used"] == "edge_tts"
    assert result["config_json"]["audio_fallback"] == {
        "from": "voicebox",
        "to": "edge_tts",
        "reason": "sidecar down",
    }


@pytest.mark.asyncio
async def test_task_audio_endpoint_reads_only_audio_manifest(tmp_path) -> None:
    from hevi.api.routers.tasks import get_task_audio

    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFF-wav")
    repo = AsyncMock()
    repo.get_task.return_value = {
        "id": "task-1",
        "user_id": "user-1",
        "config_json": {
            "artifact_manifest": ArtifactManifest(
                artifacts=[{"kind": "audio", "path": str(audio), "primary": True}]
            ).model_dump(mode="json")
        },
    }
    with patch("hevi.api.routers.tasks.decode_access_token", return_value={"sub": "user-1"}):
        response = await get_task_audio(uuid4(), repo, token="jwt")
    assert response.path == str(audio)
    assert response.media_type == "audio/wav"


@pytest.mark.asyncio
async def test_voice_studio_route_creates_a_real_shared_task(monkeypatch) -> None:
    service = MagicMock()
    task_id = uuid4()
    service.create_production = AsyncMock(return_value={"id": task_id, "status": "pending"})
    service.submit_task = AsyncMock(return_value={"id": task_id, "status": "queued"})
    monkeypatch.setattr("hevi.api.routers.voice_studio.require_capability", lambda _: MagicMock())

    result = await synthesize(
        SynthesisRequest(text="给普通人解释复利", engine="voicebox"),
        user={"id": "user-1"},
        svc=service,
    )

    request = service.create_production.await_args.args[0]
    assert request.source == "voice_studio_tts"
    assert result == {
        "task_id": str(task_id),
        "status": "queued",
        "audio_url": f"/api/tasks/{task_id}/audio",
    }
