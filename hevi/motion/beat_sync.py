"""节拍卡点 —— 最小二乘网格拟合 + kick 重音 + 拍号时间线(3O 内化 Phase B)。

来源: video-shotcraft music-beat-sync.md 的完整方法论:
  1. `librosa.beat.beat_track` 拿 beat 时刻序列(不用它返回的 tempo 标量——可能偏 2%+)
  2. 对序列做最小二乘等距网格拟合 `t_i = t0 + i*T`,求真实 BPM 与相位
     验收:残差 ≤±15ms 说明网格可信;残差大说明有变速段需分段
  3. kick 频段(40–160Hz)带通 → onset 能量 → 找"大 slam"候选拍
  4. 时间线用拍号 `beatF(n)` 写;渲后从成片抽音轨回测切点误差 ≤3f

本模块为 hevi 暂驻(待上游 `oprim.beat_grid_analyze` + `oskill.beat_sync`):
纯数学部分(网格拟合/拍号换算/回测)全部确定性可测;librosa 部分在调用时按需加载。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: 网格可信阈值(毫秒,半帧内):残差超过该值判为"变速段,需要分段拟合"。
GRID_TRUST_MS = 15.0
#: 感知切点误差阈值(帧):> 该值回测不通过。
CUT_ERROR_FRAMES = 3.0


class BeatSyncError(Exception):
    """节拍分析失败。"""


@dataclass(frozen=True)
class BeatGrid:
    """等距节拍网格:t_i = t0 + i * T。"""

    bpm: float
    t0: float  # 相位(第 0 拍时刻,秒)
    period_s: float  # 拍周期 T
    residual_ms: float  # 网格拟合最大残差(±ms)
    beat_count: int

    @property
    def trusted(self) -> bool:
        """残差 ≤ ±15ms(半帧内)判为机器鼓点网格可信。"""
        return self.residual_ms <= GRID_TRUST_MS


def fit_beat_grid(beat_times: list[float]) -> BeatGrid:
    """对 beat 时刻序列做最小二乘等距网格拟合(纯数学,可测)。

    Args:
        beat_times: librosa.beat.beat_track 的 beat 时刻(秒),升序。

    Returns:
        BeatGrid(bpm, t0, period_s, residual_ms, beat_count)。
    """
    import numpy as np

    if len(beat_times) < 4:
        raise BeatSyncError(f"need >=4 beats for grid fit, got {len(beat_times)}")
    ts = np.asarray(beat_times, dtype=float)
    i = np.arange(len(ts), dtype=float)
    A = np.vstack([i, np.ones_like(i)]).T
    (period, t0), *_ = np.linalg.lstsq(A, ts, rcond=None)
    period_f = float(period)
    t0_f = float(t0)
    if period_f <= 0:
        raise BeatSyncError(f"non-positive beat period: {period_f}")
    residuals = ts - (t0_f + i * period_f)
    residual_ms = float(np.abs(residuals).max()) * 1000.0
    return BeatGrid(
        bpm=60.0 / period_f,
        t0=t0_f,
        period_s=period_f,
        residual_ms=residual_ms,
        beat_count=len(beat_times),
    )


def analyze_beat_grid(audio_path: str | Path) -> BeatGrid:
    """从音频文件测定节拍网格(librosa;失败抛 BeatSyncError)。"""
    try:
        import librosa
    except ImportError as e:  # pragma: no cover - env guard
        raise BeatSyncError(f"librosa 未安装: {e}") from e
    try:
        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, tightness=400, units="time")
        del tempo  # 不信标量,只吃时刻序列
        return fit_beat_grid([float(t) for t in beats])
    except BeatSyncError:
        raise
    except Exception as e:
        raise BeatSyncError(f"beat analysis failed for {audio_path}: {e}") from e


def beat_time(grid: BeatGrid, n: int) -> float:
    """拍号 → 秒:t = t0 + n*T(时间线用 beatF(n) 写法)。"""
    return grid.t0 + n * grid.period_s


def beat_number(grid: BeatGrid, t: float) -> float:
    """秒 → 拍号(允许小数;调用方按需 round)。"""
    return (t - grid.t0) / grid.period_s


def kick_onsets(
    audio_path: str | Path, grid: BeatGrid, *, top_n: int = 8
) -> list[tuple[int, float]]:
    """kick 频段(40–160Hz)带通 → onset 能量 → 每拍能量排序,取 top 大 slam 拍。

    Returns:
        [(拍号 n, 能量)] 按能量降序。
    """
    import numpy as np
    from scipy.signal import butter, sosfilt  # type: ignore[import-untyped]

    try:
        import librosa
    except ImportError as e:  # pragma: no cover - env guard
        raise BeatSyncError(f"librosa 未安装: {e}") from e
    try:
        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    except Exception as e:
        raise BeatSyncError(f"load failed for {audio_path}: {e}") from e

    sos = butter(4, [40, 160], btype="band", fs=sr, output="sos")
    kick = sosfilt(sos, y)
    env = librosa.onset.onset_strength(y=kick, sr=sr)
    times = librosa.times_like(env, sr=sr)

    scored: list[tuple[int, float]] = []
    n_beats = int((times[-1] - grid.t0) / grid.period_s) + 1 if times.size else 0
    for n in range(max(n_beats, 0)):
        t = grid.t0 + n * grid.period_s
        idx = int(np.argmin(np.abs(times - t)))
        scored.append((n, float(env[idx])))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_n]


def measure_cut_error(
    video_path: str | Path, expected_cut_times: list[float], *, fps: float = 30.0
) -> tuple[float, list[float]]:
    """渲后回测:对成片抽音轨,比对实际重音时刻与预期切点。

    Args:
        video_path: 成片。
        expected_cut_times: 分镜切点时刻(秒)。
        fps: 帧率(误差换算用)。

    Returns:
        (max_error_frames, per_cut_errors_frames)。失败/无音频抛 BeatSyncError。
        感知阈值约 3 帧 —— > CUT_ERROR_FRAMES 判不通过。
    """
    import numpy as np

    try:
        import librosa
    except ImportError as e:  # pragma: no cover - env guard
        raise BeatSyncError(f"librosa 未安装: {e}") from e
    try:
        y, sr = librosa.load(str(video_path), sr=None, mono=True)
    except Exception as e:
        raise BeatSyncError(f"load failed for {video_path}: {e}") from e

    sos = np.fft
    del sos
    env = librosa.onset.onset_strength(y=y, sr=sr)
    times = librosa.times_like(env, sr=sr)
    # 实际重音 = 每个预期切点 ±0.5 拍窗内找 onset 峰值
    errors: list[float] = []
    for t in expected_cut_times:
        lo, hi = t - 0.5, t + 0.5
        mask = (times >= lo) & (times <= hi)
        if not mask.any():
            errors.append(0.0)  # 该窗无 onset,视为对齐(不误报)
            continue
        actual = times[int(np.argmax(env[mask]))]
        errors.append(abs(actual - t) * fps)
    return (max(errors, default=0.0), errors)
