from __future__ import annotations

from pathlib import Path

import pytest


def test_openai_compatible_speech_defaults_to_lux_tts() -> None:
    from hevi.api.routers.voice_platform import OpenAISpeechRequest

    assert OpenAISpeechRequest(input="Hello, little bunny!").model == "lux_tts"


def test_lux_tts_catalog_reports_remote_network_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.audio import speech_platform

    monkeypatch.setattr(speech_platform, "_tts_available", lambda _spec: False)
    engine = next(
        item for item in speech_platform.list_engines(include_unavailable=True)
        if item.id == "lux_tts"
    )
    assert engine.mode == "network"
    assert "HTTP" in engine.description
    assert "本机不加载模型" in engine.description


@pytest.mark.asyncio
async def test_studio_auto_tts_uses_shared_lux_cosyvoice_piper_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.studio import kit

    calls: dict[str, object] = {}

    async def fake_route(**kwargs: object) -> dict[str, object]:
        calls.update(kwargs)
        output_path = Path(str(kwargs["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"piper-fallback-audio")
        return {
            "path": output_path,
            "requested_provider": "lux_tts",
            "actual_provider": "piper",
            "substituted": True,
            "fallback_reason": "luxtts_http_unavailable:health failed;cosyvoice_unavailable:offline",
        }

    monkeypatch.setattr("hevi.audio.audio_router._synthesize_luxtts_with_fallback", fake_route)
    output_path = tmp_path / "line.wav"
    result = await kit.tts_synth(
        {"text": "小兔子来啦。", "provider": "auto", "output_path": output_path}
    )

    assert result["status"] == "ok"
    assert result["provider"] == "piper"
    assert result["requested_provider"] == "lux_tts"
    assert result["substituted"] is True
    assert "cosyvoice_unavailable" in str(result["fallback_reason"])
    assert Path(result["audio_path"]).read_bytes() == b"piper-fallback-audio"
    assert calls["text"] == "小兔子来啦。"
    assert calls["requested_provider"] == "lux_tts"


@pytest.mark.asyncio
async def test_openai_speech_lux_tts_keeps_fallback_and_provider_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import wave

    from hevi.layer4_legacy.voicepro.omodul_impl import openai_audio

    calls: dict[str, object] = {}

    async def fake_route(**kwargs: object) -> dict[str, object]:
        calls.update(kwargs)
        output_path = Path(str(kwargs["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(48000)
            writer.writeframes(b"\x00\x00" * 480)
        return {
            "path": output_path,
            "requested_provider": "lux_tts",
            "actual_provider": "piper",
            "substituted": True,
            "fallback_reason": "luxtts_http_unavailable;cosyvoice_unavailable",
        }

    monkeypatch.setattr("hevi.audio.audio_router._synthesize_luxtts_with_fallback", fake_route)
    result = await openai_audio.synthesize_audio_file(
        text="Hello, little bunny!",
        engine="lux_tts",
        voice="en_male",
        response_format="wav",
        output_dir=tmp_path,
    )

    assert Path(result["path"]).is_file()
    assert result["engine"] == "lux_tts"
    assert result["actual_provider"] == "piper"
    assert result["substituted"] is True
    assert "cosyvoice_unavailable" in str(result["fallback_reason"])
    assert calls["text"] == "Hello, little bunny!"
    assert calls["requested_provider"] == "lux_tts"
    assert calls["remote_voice"] == "en_male"
    manifest_artifact = result["manifest"]["artifacts"][0]
    assert manifest_artifact["metadata"]["actual_provider"] == "piper"
    assert manifest_artifact["metadata"]["substituted"] is True


def test_lux_tts_batch_remains_executable_when_remote_health_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hevi.audio import speech_platform

    original_available = speech_platform._tts_available

    def fake_available(spec):
        if spec["id"] == "lux_tts":
            return False
        return original_available(spec)

    monkeypatch.setattr(speech_platform, "_tts_available", fake_available)
    plan = speech_platform.build_batch_plan(
        [{"text": "小兔子来啦。", "engine": "lux_tts", "voice": "auto"}]
    )

    assert plan["valid"] is True
    assert plan["errors"] == []
    job = plan["jobs"][0]
    assert job["engine"] == "lux_tts"
    assert job["available"] is True  # executable via fallback, not health claim
    assert job["provider_available"] is False
    assert job["fallback_enabled"] is True


@pytest.mark.asyncio
async def test_voice_studio_accepts_lux_tts_when_health_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from hevi.api.routers.voice_studio import _validate_synthesis_engine

    monkeypatch.setattr(
        "hevi.api.routers.voice_studio.get_engine",
        lambda _engine_id: SimpleNamespace(
            id="lux_tts",
            available=False,
            description="LuxTTS HTTP service unavailable; fallback is enabled.",
            setup="Ensure the endpoint is reachable.",
        ),
    )

    await _validate_synthesis_engine("lux_tts")


@pytest.mark.asyncio
async def test_task_adapter_lux_tts_dispatch_uses_shared_fallback_router(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from hevi.audio.task_adapter import _synthesize_with_engine

    calls: dict[str, object] = {}

    async def fake_route(**kwargs: object) -> dict[str, object]:
        calls.update(kwargs)
        output_path = Path(str(kwargs["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"route-output")
        return {
            "path": output_path,
            "requested_provider": "lux_tts",
            "actual_provider": "piper",
            "substituted": True,
            "fallback_reason": "luxtts_http_unavailable;cosyvoice_unavailable",
        }

    monkeypatch.setattr(
        "hevi.audio.audio_router._synthesize_luxtts_with_fallback", fake_route
    )
    target = tmp_path / "task.wav"
    result = await _synthesize_with_engine(
        "lux_tts",
        line=SimpleNamespace(text="Hello, little bunny!"),
        output_path=target,
        config={"voice": "en_male", "speed": 1.05},
        emotion=None,
    )

    assert result["actual_provider"] == "piper"
    assert result["substituted"] is True
    assert calls["requested_provider"] == "lux_tts"
    assert calls["remote_voice"] == "en_male"
    assert calls["text"] == "Hello, little bunny!"
    assert calls["output_path"] == target


@pytest.mark.asyncio
async def test_voice_studio_catalog_describes_lux_fallback_chain() -> None:
    from hevi.api.routers.voice_studio import speech_catalog

    catalog = await speech_catalog({"id": "test-user"})
    assert catalog["routing"] == {
        "policy": "lux_tts-first",
        "fallback": "lux_tts-health-or-synthesis-failure-to-cosyvoice-then-piper",
    }
