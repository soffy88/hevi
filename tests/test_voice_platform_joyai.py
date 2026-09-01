"""VoiceStudio/JoyAI capability contracts and honest unavailable states."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hevi.joyai.omodul.stream_edit import (
    capabilities,
    create_session,
    reset_sessions,
)
from hevi.joyai.oprim.stream_contract import frame_budget, validate_control
from hevi.voicepro.omodul.platform import (
    create_voice_profile,
    list_model_catalog,
    plan_dictation,
    register_model,
    reset_platform,
    route_model,
)


@pytest.fixture(autouse=True)
def reset_platform_state() -> None:
    reset_platform()
    reset_sessions()
    yield
    reset_platform()
    reset_sessions()


def test_model_registry_reports_local_path_truthfully(tmp_path: Path) -> None:
    missing = register_model(
        model_id="local-tts",
        name="Local TTS",
        kind="tts",
        engine="edge_tts",
        path=str(tmp_path / "missing"),
    )
    assert missing["state"] == "missing"
    assert not missing["ready"]

    model_path = tmp_path / "weights.bin"
    model_path.write_bytes(b"weights")
    ready = register_model(
        model_id="local-tts-ready",
        name="Local TTS Ready",
        kind="tts",
        engine="edge_tts",
        path=str(model_path),
    )
    assert ready["state"] == "ready"
    assert route_model(kind="tts", preferred="local-tts-ready")["selected"]["model_id"] == "local-tts-ready"
    assert any(row["model_id"] == "local-tts" for row in list_model_catalog())

    custom = register_model(
        model_id="custom-unwired",
        name="Unwired",
        kind="tts",
        engine="not-an-adapter",
        path=str(model_path),
    )
    assert custom["state"] == "ready"
    assert not custom["execution_ready"]
    assert route_model(kind="tts", preferred="custom-unwired")["selected"]["model_id"] != "custom-unwired"


def test_voice_gallery_requires_existing_reference_audio(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reference audio not found"):
        create_voice_profile(
            name="missing",
            engine="edge_tts",
            reference_audio=str(tmp_path / "missing.wav"),
        )
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF")
    profile = create_voice_profile(
        name="narrator",
        engine="edge_tts",
        reference_audio=str(reference),
        language="zh",
    )
    assert profile["reference_audio"] == str(reference)
    assert profile["status"] == "ready"


def test_dictation_distinguishes_batch_and_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE_ASR_STREAM_WS_URL", raising=False)
    plan = plan_dictation(engine="faster_whisper")
    assert not plan["streaming"]
    monkeypatch.setenv("VOICE_ASR_STREAM_WS_URL", "ws://asr.local/stream")
    assert plan_dictation(engine="faster_whisper")["streaming"]


def test_stream_contract_budget_and_validation() -> None:
    budget = frame_budget(width=840, height=480, fps=24, seconds=2)
    assert budget["frames"] == 48
    assert budget["raw_bytes"] == 48 * 840 * 480 * 4
    assert validate_control({"type": "start", "prompt": "edit", "width": 840}) == []
    assert validate_control({"type": "frame"}) == ["frame.index or frame.timestamp_ms is required"]
    assert validate_control({"type": "nope"}) == ["unknown stream message type: nope"]


def test_joyai_without_provider_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOYAI_STREAM_WS_URL", raising=False)
    monkeypatch.delenv("JOYAI_BASE_URL", raising=False)
    session = create_session(prompt="change the background")
    assert session.status == "blocked"
    assert not capabilities()["available"]
    assert "provider" in " ".join(session.decision_trail).lower()


def test_joyai_base_url_normalizes_to_websocket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOYAI_BASE_URL", "http://joyai.local")
    monkeypatch.delenv("JOYAI_STREAM_WS_URL", raising=False)
    session = create_session(prompt="style transfer")
    assert session.status == "ready"
    assert capabilities()["provider_url"] == "ws://joyai.local/ws/edit"


def test_openai_audio_normalizes_real_transcript_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.ingest.video_transcript import TranscriptSegment, WordSpan
    from hevi.voicepro.omodul import openai_audio

    monkeypatch.setattr(
        openai_audio,
        "get_engine",
        lambda _engine: SimpleNamespace(kind="asr", available=True, setup=None),
    )
    monkeypatch.setattr(
        openai_audio,
        "fetch_transcript",
        lambda *_args, **_kwargs: [
            TranscriptSegment(
                0.0,
                1.2,
                "hello",
                speaker="spk1",
                words=(WordSpan("hello", 0.0, 0.5),),
            )
        ],
    )
    result = openai_audio.transcribe_audio_file(
        source="input.wav",
        asr_engine="faster_whisper",
        response_format="verbose_json",
    )
    assert result["text"] == "hello"
    assert result["segments"][0]["speaker"] == "spk1"
    assert result["segments"][0]["words"][0]["word"] == "hello"


def test_new_routes_and_tools_are_registered() -> None:
    from hevi.api.main import app
    from hevi.studio.catalog import ALL_CATALOG

    paths = {route.path for route in app.routes}
    assert "/api/stream-edit/capabilities" in paths
    assert "/api/stream-edit/sessions/{session_id}/stream" in paths
    assert "/v1/audio/speech" in paths
    tool_ids = {row[0] for row in ALL_CATALOG}
    assert {"speech.models", "speech.dubbing_plan", "video.stream_session"} <= tool_ids
