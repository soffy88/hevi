"""BGM 节拍对齐测试(HEVI 路线图 Phase2 #37)。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.beat_align import beat_snapped_xfade_durations, detect_beat_times

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_beat_snapped_falls_back_to_uniform_when_no_beats():
    result = beat_snapped_xfade_durations([5.0, 5.0, 5.0], base_xfade_d=0.5, beats=[])
    assert result == [0.5, 0.5]


def test_beat_snapped_returns_empty_for_single_shot():
    assert beat_snapped_xfade_durations([5.0], base_xfade_d=0.5, beats=[1.0, 2.0]) == []


def test_beat_snapped_shifts_toward_nearest_beat():
    """2 段各 5s,自然转场点在 t=5.0;节拍点在 4.7 → 转场应该提前发生
    (xfade_d 变大,从 0.5 增到接近 0.8)。"""
    durations = [5.0, 5.0]
    result = beat_snapped_xfade_durations(durations, base_xfade_d=0.5, beats=[4.7], max_shift=0.3)
    assert len(result) == 1
    assert result[0] == pytest.approx(0.8, abs=0.01)


def test_beat_snapped_respects_max_shift_cap():
    """节拍点离自然转场点很远(> max_shift)→ 修正量夹在 base ± max_shift 内,
    不会为了贴节拍就无限拉伸转场。"""
    durations = [5.0, 5.0]
    result = beat_snapped_xfade_durations(durations, base_xfade_d=0.5, beats=[0.0], max_shift=0.3)
    assert result[0] == pytest.approx(0.8, abs=0.01)  # 0.5 + 0.3 封顶


def test_beat_snapped_never_exceeds_half_adjacent_shot_duration():
    """修正后的 xfade_d 也不能超过相邻两镜头时长的一半(与 assemble_longvideo
    现有的 xfade_d 上限规则保持一致,避免转场重叠比镜头本身还长)。"""
    durations = [1.0, 1.0]
    result = beat_snapped_xfade_durations(durations, base_xfade_d=0.5, beats=[0.0], max_shift=0.3)
    assert result[0] <= 0.5  # min(durations)/2


def test_detect_beat_times_missing_file_returns_empty():
    assert detect_beat_times(Path("/nonexistent/audio.wav")) == []


@pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg")
def test_detect_beat_times_on_synthetic_click_track(tmp_path: Path):
    """120 BPM 的合成"咔哒"节拍音轨(每 0.5s 一个短脉冲)—— librosa 应该能测出
    大致贴近 0.5s 间隔的节拍点,不要求逐拍精确对齐真实音乐那么严格。"""
    audio = tmp_path / "click.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.8*lt(mod(t\\,0.5)\\,0.03):d=8:s=22050",
            str(audio),
        ],
        check=True,
        capture_output=True,
    )
    beats = detect_beat_times(audio)
    assert len(beats) >= 4  # 8s / 0.5s 间隔,应该测出好几个节拍点
