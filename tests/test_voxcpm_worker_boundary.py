from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_voxcpm_isolated_worker_synthesis_and_stream(tmp_path: Path, monkeypatch) -> None:
    fake_module = tmp_path / "voxcpm.py"
    fake_module.write_text(
        """
import numpy as np


class _TTS:
    sample_rate = 16000


class VoxCPM:
    tts_model = _TTS()

    @classmethod
    def from_pretrained(cls, _model_id, load_denoiser=False):
        return cls()

    def generate(self, **_kwargs):
        return np.zeros(160, dtype=np.float32)

    def generate_streaming(self, **_kwargs):
        yield np.zeros(80, dtype=np.float32)
        yield np.zeros(80, dtype=np.float32)
""",
        encoding="utf-8",
    )
    from hevi.audio import voxcpm_service as vox

    monkeypatch.setattr(vox, "_import_voxcpm", lambda: None)
    monkeypatch.setenv("HEVI_VOXCPM_PYTHON", sys.executable)
    monkeypatch.setenv("HEVI_VOXCPM_MODEL", "fake-model")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(tmp_path), os.getenv("PYTHONPATH", ""))))

    output = await vox.synth_with_voxcpm("worker test", tmp_path / "worker.wav")
    assert output.is_file() and output.stat().st_size > 0

    chunks = [chunk async for chunk in vox.stream_voxcpm("worker stream")]
    assert len(chunks) == 2
    assert all(chunk.sample_rate == 16000 and chunk.pcm_s16le for chunk in chunks)
