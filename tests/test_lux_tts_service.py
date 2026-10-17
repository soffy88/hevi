"""HTTP-contract, sentence-assembly and live LuxTTS integration tests."""
from __future__ import annotations

import asyncio
import io
import json
import wave
from pathlib import Path

import httpx
import pytest

from hevi.audio import lux_tts_service as lux


def _wav_bytes(*, sample_rate: int = 48000, duration: float = 0.1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x01\x00" * int(sample_rate * duration))
    return buffer.getvalue()


def _mock_http(monkeypatch: pytest.MonkeyPatch, handler):
    real_client = httpx.AsyncClient

    def client_factory(*, timeout, trust_env=False):
        return real_client(transport=httpx.MockTransport(handler), timeout=timeout, trust_env=trust_env)

    monkeypatch.setattr(lux.httpx, "AsyncClient", client_factory)


def test_health_probe_reports_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lux, "_get_health_payload", lambda: (_ for _ in ()).throw(OSError("offline")))
    assert lux.lux_tts_available() is False


def test_chinese_and_english_sentence_splitting() -> None:
    assert lux.split_sentences("小熊醒来。太阳升起！它去找朋友？") == [
        "小熊醒来。", "太阳升起！", "它去找朋友？"
    ]
    assert lux.split_sentences("The fox waits. The cub waves!") == [
        "The fox waits.", "The cub waves!"
    ]
    assert lux.split_sentences("  \n ") == []


def test_http_payload_retry_and_wav_join(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(lux, "_get_health_payload", lambda: {"ok": True, "voices": ["soffy", "en_male"]})
    requests = []
    wav_data = _wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request, text="temporary busy")
        payload = json.loads(request.content)
        actual_voice = "soffy" if any("\u4e00" <= ch <= "\u9fff" for ch in payload["text"]) else "en_male"
        return httpx.Response(
            200,
            request=request,
            content=wav_data,
            headers={
                "Content-Type": "audio/wav",
                "X-Voice": actual_voice,
                "X-Gen-Seconds": "0.025",
                "X-Audio-Seconds": "0.1",
            },
        )

    _mock_http(monkeypatch, handler)
    out = tmp_path / "story.wav"
    meta_path = tmp_path / "story.json"
    result = asyncio.run(
        lux.synth_with_luxtts(
            "小熊醒来。太阳升起！它去找朋友？",
            out,
            voice="auto",
            gap_ms=150,
            metadata_path=meta_path,
        )
    )
    assert result == out and out.is_file() and out.stat().st_size > 44
    assert len(requests) == 4  # first sentence retried once, then two more sentences
    assert all(request.url.path == "/tts" for request in requests)
    payloads = [json.loads(request.content) for request in requests]
    assert payloads[0] == {"text": "小熊醒来。", "voice": "auto", "speed": 1.0, "steps": 4}
    assert all(item["voice"] == "auto" for item in payloads)
    with wave.open(str(out), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 48000)
        assert wav.getnframes() / wav.getframerate() == pytest.approx(0.6, abs=0.01)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["sentence_count"] == 3
    assert [item["voice"] for item in metadata["sentences"]] == ["soffy"] * 3
    assert all(item["gen_seconds"] == pytest.approx(0.025) for item in metadata["sentences"])
    assert metadata["sentence_gap_ms"] == 150


def test_non_finite_timing_headers_use_safe_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        lux,
        "_get_health_payload",
        lambda: {"ok": True, "voices": ["soffy", "en_male"]},
    )
    wav_data = _wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            content=wav_data,
            headers={
                "Content-Type": "audio/wav",
                "X-Voice": "en_male",
                "X-Gen-Seconds": "inf",
                "X-Audio-Seconds": "Infinity",
            },
        )

    _mock_http(monkeypatch, handler)
    out = tmp_path / "finite-metadata.wav"
    metadata_path = tmp_path / "finite-metadata.json"
    asyncio.run(
        lux.synth_with_luxtts(
            "Hello, little bunny!",
            out,
            voice="auto",
            metadata_path=metadata_path,
        )
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    row = metadata["sentences"][0]
    assert row["voice"] == "en_male"
    assert row["gen_seconds"] >= 0
    assert row["api_audio_seconds"] == pytest.approx(0.1)
    assert all(
        isinstance(value, (int, float)) and value != float("inf") and value == value
        for value in (row["gen_seconds"], row["api_audio_seconds"], metadata["duration_seconds"])
    )


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("speed", float("nan"), "finite positive"),
        ("speed", float("inf"), "finite positive"),
        ("speed", float("-inf"), "finite positive"),
        ("sample_rate", float("nan"), "positive integer"),
        ("sample_rate", True, "positive integer"),
        ("gap_ms", float("inf"), "non-negative integer"),
        ("gap_ms", True, "non-negative integer"),
        ("steps", 1.5, "positive integer"),
        ("steps", True, "positive integer"),
    ],
)
def test_invalid_numeric_options_are_rejected_before_health_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    option: str,
    value: object,
    message: str,
) -> None:
    def forbidden_health_probe() -> dict[str, object]:
        raise AssertionError("invalid numeric options must be rejected before network access")

    monkeypatch.setattr(lux, "_get_health_payload", forbidden_health_probe)
    with pytest.raises(ValueError, match=message):
        asyncio.run(
            lux.synth_with_luxtts(
                "hello, little bunny!",
                tmp_path / "invalid-options.wav",
                **{option: value},
            )
        )


def test_bad_voice_is_rejected_before_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(lux, "_get_health_payload", lambda: {"ok": True, "voices": ["soffy", "en_male"]})
    with pytest.raises(ValueError, match="Unsupported LuxTTS voice"):
        asyncio.run(lux.synth_with_luxtts("hello", tmp_path / "bad.wav", voice="unknown"))


@pytest.mark.parametrize(
    ("voice", "service_voices"),
    [("en_male", ["soffy"]), ("auto", ["soffy"])],
)
def test_missing_service_voice_fails_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    voice: str,
    service_voices: list[str],
) -> None:
    monkeypatch.setattr(
        lux,
        "_get_health_payload",
        lambda: {"ok": True, "voices": service_voices},
    )
    requests: list[httpx.Request] = []
    _mock_http(
        monkeypatch,
        lambda request: requests.append(request) or httpx.Response(500, request=request),
    )
    out = tmp_path / "unavailable-voice.wav"

    with pytest.raises(RuntimeError, match="missing required voice"):
        asyncio.run(lux.synth_with_luxtts("hello, little bunny", out, voice=voice))

    assert requests == []
    assert not out.exists()


@pytest.mark.parametrize(
    ("text", "reported_voice"),
    [("Hello, little bunny!", "soffy"), ("Hello, little bunny!", None)],
)
def test_auto_voice_mismatch_is_retried_then_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    text: str,
    reported_voice: str | None,
) -> None:
    monkeypatch.setattr(
        lux,
        "_get_health_payload",
        lambda: {"ok": True, "voices": ["soffy", "en_male"]},
    )
    requests: list[httpx.Request] = []
    headers = {"Content-Type": "audio/wav"}
    if reported_voice is not None:
        headers["X-Voice"] = reported_voice
    wav_data = _wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request, content=wav_data, headers=headers)

    _mock_http(monkeypatch, handler)
    out = tmp_path / "wrong-voice.wav"
    with pytest.raises(RuntimeError, match="unexpected X-Voice"):
        asyncio.run(lux.synth_with_luxtts(text, out, voice="auto"))

    assert len(requests) == 3
    assert not out.exists()


def test_live_luxtts_http_integration_or_skip(tmp_path: Path) -> None:
    if not lux.lux_tts_available():
        pytest.skip("LuxTTS /health unreachable; live integration is optional in offline CI")
    out = tmp_path / "live.wav"
    metadata = tmp_path / "live.json"
    asyncio.run(
        lux.synth_with_luxtts(
            "你好，小朋友。",
            out,
            voice="auto",
            metadata_path=metadata,
        )
    )
    with wave.open(str(out), "rb") as wav:
        assert wav.getframerate() == 48000
        assert wav.getnchannels() == 1
        assert wav.getnframes() > 0
    info = json.loads(metadata.read_text(encoding="utf-8"))
    assert info["sentences"][0]["voice"] == "soffy"
    assert info["sentences"][0]["gen_seconds"] >= 0


def test_health_probe_invalid_url_returns_false_for_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEVI_LUXTTS_URL", "file:///not-an-http-endpoint")
    assert lux.lux_tts_available() is False
