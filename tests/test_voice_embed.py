"""hevi.audio.voice_embed 测试 — 真实 resemblyzer + lavfi 合成音频(同 test_segment_qc.py
对 CLIP 的态度:验证 API/维度/异常路径,不是"这个向量语义上对不对",那要真实人声样本才能测,
这里只保真管线不炸)。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.audio.voice_embed import VoiceEmbedError, voice_embed
from hevi.subjects.subject_embed import cosine_similarity

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


def _make_tone(path: Path, seconds: float, freq: int = 440) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds}",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@ffmpeg_only
def test_voice_embed_returns_normalized_256d_vector(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _make_tone(wav, 2.0)

    emb = voice_embed(wav)

    assert len(emb) == 256
    norm = sum(x * x for x in emb) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-4)


@ffmpeg_only
def test_voice_embed_same_audio_is_self_similar(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _make_tone(wav, 2.0)

    emb_a = voice_embed(wav)
    emb_b = voice_embed(wav)

    assert cosine_similarity(emb_a, emb_b) == pytest.approx(1.0, abs=1e-4)


def test_voice_embed_missing_file_raises() -> None:
    with pytest.raises(VoiceEmbedError):
        voice_embed(Path("/nonexistent/audio.wav"))
