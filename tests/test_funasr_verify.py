from __future__ import annotations

from pathlib import Path

import oprim
import pytest

from hevi.audio.funasr_verify import (
    FunASRUnavailableError,
    funasr_timestamp_generator,
)


@pytest.mark.asyncio
async def test_funasr_success_marks_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        oprim,
        "funasr_asr",
        lambda **_kwargs: {"words": [{"text": "你", "start": 0.1, "end": 0.4}]},
        raising=False,
    )
    result = await funasr_timestamp_generator(audio_path=tmp_path / "a.wav")
    assert result["verified"] is True
    assert result["source"] == "funasr"
    assert result["words"][0]["word"] == "你"


@pytest.mark.asyncio
async def test_funasr_missing_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise(**_kwargs: object) -> object:
        raise ImportError("no funasr")

    monkeypatch.setattr(oprim, "funasr_asr", _raise, raising=False)
    with pytest.raises(FunASRUnavailableError, match="unavailable"):
        await funasr_timestamp_generator(audio_path=tmp_path / "a.wav")


@pytest.mark.asyncio
async def test_funasr_empty_fails_closed_without_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(oprim, "funasr_asr", lambda **_kwargs: [], raising=False)
    monkeypatch.setattr(oprim, "probe_duration", lambda _path: 1.0)
    with pytest.raises(FunASRUnavailableError, match="no usable"):
        await funasr_timestamp_generator(audio_path=tmp_path / "a.wav")


@pytest.mark.asyncio
async def test_funasr_heuristic_preview_is_unverified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise(**_kwargs: object) -> object:
        raise RuntimeError("pipeline down")

    monkeypatch.setattr(oprim, "funasr_asr", _raise, raising=False)
    monkeypatch.setattr(oprim, "probe_duration", lambda _path: 1.0)
    result = await funasr_timestamp_generator(
        audio_path=tmp_path / "a.wav", allow_heuristic_preview=True
    )
    assert result["verified"] is False
    assert result["source"] == "heuristic_preview"
    assert "pipeline down" in str(result["reason"])
    assert result["words"] == []
