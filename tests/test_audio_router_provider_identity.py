from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_chattts_import_error_substitutes_voicebox_explicitly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import audio_router

    async def vb(_text: str, path: Path, **_kwargs: object) -> None:
        path.write_bytes(b"v" * 120)

    monkeypatch.setattr("hevi.explainer.voicebox_client.synthesize", vb)
    monkeypatch.setenv("HEVI_TTS_CONVERSATIONAL_PROVIDER", "chattts")

    def _raise_import(**_kwargs: object) -> str:
        raise ImportError("no chattts")

    monkeypatch.setattr("oprim.chattts_call", _raise_import, raising=False)
    envelope = await audio_router._synthesize_conversational(
        text="x", output_path=tmp_path / "a.wav", instruct=None
    )
    assert envelope["requested_provider"] == "chattts"
    assert envelope["actual_provider"] == "voicebox"
    assert envelope["substituted"] is True
    assert envelope["fallback_reason"] == "chattts_unavailable"


@pytest.mark.asyncio
async def test_unmatched_formal_provider_marks_edge_tts_substitution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import audio_router

    class FakeComm:
        def __init__(self, text: str, voice: str) -> None:
            self._text = text
            self._voice = voice

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"e" * 120)

    monkeypatch.setenv("HEVI_TTS_FORMAL_PROVIDER", "unknown_backend")
    monkeypatch.setattr("edge_tts.Communicate", FakeComm, raising=False)
    envelope = await audio_router._synthesize_formal(
        text="x", output_path=tmp_path / "a.wav", voice="v", instruct=None
    )
    assert envelope["requested_provider"] == "unknown_backend"
    assert envelope["actual_provider"] == "edge_tts"
    assert envelope["substituted"] is True
    assert envelope["fallback_reason"] == "unmatched_formal_provider:unknown_backend"


@pytest.mark.asyncio
async def test_route_single_cue_exposes_full_identity_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import audio_router

    async def conversational(**kwargs: object) -> dict[str, object]:
        path = kwargs["output_path"]
        assert isinstance(path, Path)
        path.write_bytes(b"y" * 120)
        return {
            "path": path,
            "requested_provider": "chattts",
            "actual_provider": "voicebox",
            "substituted": True,
            "fallback_reason": "chattts_unavailable",
        }

    monkeypatch.setattr(audio_router, "_synthesize_conversational", conversational)
    envelope = await audio_router.route_single_cue(
        cue_text="其实呢", cue_style="conversational", output_path=tmp_path / "c.wav", voice="v"
    )
    assert Path(envelope["path"]) == tmp_path / "c.wav"
    assert envelope["requested_style"] == "conversational"
    assert envelope["actual_style"] == "conversational"
    assert envelope["requested_provider"] == "chattts"
    assert envelope["actual_provider"] == "voicebox"
    assert envelope["substituted"] is True
    assert envelope["fallback_reason"] == "chattts_unavailable"


@pytest.mark.asyncio
async def test_route_single_cue_style_fallback_is_not_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import audio_router

    async def broken(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("conversational down")

    async def formal(**kwargs: object) -> dict[str, object]:
        path = kwargs["output_path"]
        assert isinstance(path, Path)
        path.write_bytes(b"x" * 120)
        return {
            "path": path,
            "requested_provider": "cosyvoice",
            "actual_provider": "cosyvoice",
            "substituted": False,
        }

    monkeypatch.delenv("HEVI_TTS_CONVERSATIONAL_PROVIDER", raising=False)
    monkeypatch.setattr(audio_router, "_synthesize_conversational", broken)
    monkeypatch.setattr(audio_router, "_synthesize_formal", formal)
    envelope = await audio_router.route_single_cue(
        cue_text="x", cue_style="conversational", output_path=tmp_path / "f.wav", voice="v"
    )
    assert envelope["requested_style"] == "conversational"
    assert envelope["actual_style"] == "formal"
    assert envelope["requested_provider"] == "lux_tts"
    assert envelope["actual_provider"] == "cosyvoice"
    assert envelope["substituted"] is True
    assert str(envelope["fallback_reason"]).startswith("style_fallback:")



def test_luxtts_is_the_default_for_both_audio_styles(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.audio import audio_router

    monkeypatch.delenv("HEVI_TTS_FORMAL_PROVIDER", raising=False)
    monkeypatch.delenv("HEVI_TTS_CONVERSATIONAL_PROVIDER", raising=False)
    assert audio_router._formal_requested_provider() == "lux_tts"
    assert audio_router._conversational_requested_provider() == "lux_tts"


@pytest.mark.asyncio
async def test_luxtts_http_health_failure_falls_back_to_cosyvoice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import audio_router

    monkeypatch.setenv("HEVI_TTS_FORMAL_PROVIDER", "lux_tts")
    monkeypatch.setattr("hevi.audio.lux_tts_service.lux_tts_available", lambda: False)
    calls: list[str] = []

    async def fake_cosyvoice(*, config: dict, script: list, output_path: Path) -> None:
        calls.append(script[0].text)
        output_path.write_bytes(b"c" * 256)

    monkeypatch.setattr("hevi.audio.cosyvoice_service.cosyvoice_synthesize", fake_cosyvoice)
    result = await audio_router._synthesize_formal(
        text="一只小兔子", output_path=tmp_path / "fallback.wav", voice="soffy", instruct=None
    )
    assert calls == ["一只小兔子"]
    assert result["requested_provider"] == "lux_tts"
    assert result["actual_provider"] == "cosyvoice"
    assert result["substituted"] is True
    assert "luxtts_http_unavailable" in result["fallback_reason"]
    assert (tmp_path / "fallback.wav").stat().st_size == 256
