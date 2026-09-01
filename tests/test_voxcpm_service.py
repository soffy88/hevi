"""HEVI-native VoxCPM capability with optional upstream fidelity backend."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hevi.audio.voxcpm_service import synth_with_voxcpm, voxcpm_available


def test_available_from_hevi_native_runtime(monkeypatch):
    monkeypatch.setattr("hevi.audio.voxcpm_service._import_voxcpm", lambda: None)
    monkeypatch.setattr(
        "hevi.voicepro.oskill.native_voice.native_voice_available", lambda: True
    )
    assert voxcpm_available() is True


def test_synth_uses_hevi_native_runtime_when_upstream_missing(tmp_path: Path, monkeypatch) -> None:
    def fake_native(_text, output_path, **_kwargs):
        Path(output_path).write_bytes(b"RIFF-native")

    monkeypatch.setattr("hevi.audio.voxcpm_service._import_voxcpm", lambda: None)
    monkeypatch.setattr("hevi.audio.voxcpm_service._isolated_worker_python", lambda: None)
    monkeypatch.setattr(
        "hevi.voicepro.oskill.synthesize_native_voice_sync", fake_native
    )
    result = asyncio.run(synth_with_voxcpm("你好", tmp_path / "out.wav"))
    assert result == tmp_path / "out.wav"


def test_synth_module_generate(tmp_path: Path, monkeypatch):
    out = tmp_path / "out.wav"
    calls: dict = {}

    class FakeModel:
        tts_model = SimpleNamespace(sample_rate=48000)

        @classmethod
        def from_pretrained(cls, *_a, **_k):
            return cls()

        def generate(self, **kw):
            calls.update(kw)
            return [0.0, 0.1]

    fake = SimpleNamespace(VoxCPM=FakeModel)

    def fake_write(path, wav, rate):
        Path(path).write_bytes(b"RIFF")

    monkeypatch.setattr("hevi.audio.voxcpm_service._import_voxcpm", lambda: fake)
    with patch.dict("sys.modules", {"soundfile": SimpleNamespace(write=fake_write)}):
        result = asyncio.run(
            synth_with_voxcpm("hi", out, voice_design="gentle", reference_audio="ref.wav")
        )
    assert result == out
    assert out.exists()
    assert calls["text"].startswith("(gentle)")
    assert calls["reference_wav_path"] == "ref.wav"
