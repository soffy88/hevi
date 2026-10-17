"""LuxTTS Studio entrypoint routing contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hevi.studio.kit import tts_synth


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "voice", "expected_voice"),
    [("lux", "en_male", "en_male"), ("auto", "soffy", "soffy"), ("luxtts", "", "auto")],
)
async def test_studio_tts_routes_lux_aliases_through_fallback_router(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider: str,
    voice: str,
    expected_voice: str,
) -> None:
    from hevi.audio import audio_router

    captured: dict[str, Any] = {}

    async def fake_router(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        output = Path(kwargs["output_path"])
        output.write_bytes(b"wav-fixture")
        return {
            "path": str(output),
            "requested_provider": kwargs["requested_provider"],
            "actual_provider": "cosyvoice",
            "substituted": True,
            "fallback_reason": "luxtts_http_unavailable:fixture",
        }

    monkeypatch.setattr(audio_router, "_synthesize_luxtts_with_fallback", fake_router)
    monkeypatch.setenv("HEVI_LUXTTS_VOICE", "auto")
    output = tmp_path / f"{provider}.wav"
    result = await tts_synth(
        {"text": "Hello, little bunny!", "output_path": str(output), "provider": provider, "voice": voice}
    )

    assert result["status"] == "ok"
    assert result["provider"] == "cosyvoice"
    assert result["substituted"] is True
    assert result["fallback_reason"] == "luxtts_http_unavailable:fixture"
    assert captured["remote_voice"] == expected_voice
    assert captured["requested_provider"] == ("lux_tts" if provider == "auto" else provider)
    assert output.is_file()
