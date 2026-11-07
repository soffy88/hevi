"""BGM 节拍对齐(HEVI 路线图 Phase2 #37)。

转场卡在音乐节拍点上是常见的观感提升手法,零边际成本(装配阶段的纯计算,不
额外生成任何素材)。只调每处转场的 xfade 重叠时长(在基准值 ± max_shift 内浮动
去贴最近的节拍点),不碰每个镜头的目标时长——那是音频驱动锁定的(旁白时长),
不能因为好看就打乱音画同步。

librosa 做节拍检测(已是既有依赖,不是新引入)。检测失败(非音频文件/librosa
异常)→ 空节拍列表,调用方应该据此回退到原有的统一 xfade 时长,不阻断装配。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_beat_times(audio_path: Path) -> list[float]:
    """librosa 检测音频的节拍时间点(秒)。失败(非音频/解码错误/librosa 缺失)→ []。"""
    try:
        import librosa

        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
        _tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        return [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
    except Exception as e:
        logger.warning("beat detection failed for %s: %s", audio_path, e)
        return []


def beat_snapped_xfade_durations(
    durations: list[float],
    *,
    base_xfade_d: float,
    beats: list[float],
    max_shift: float = 0.3,
) -> list[float]:
    """给每处转场算一个贴近最近节拍点的 xfade 重叠时长。

    第 i 处转场(第 i-1 镜头与第 i 镜头之间)"自然"发生在 `merged`(前面镜头
    累计时长,还没减 xfade)那个时间点;这个点跟最近节拍点的偏移量 `shift` 直接
    转成 xfade_d 的调整量(转场提前发生 = xfade_d 增大,推后发生 = xfade_d 减小),
    夹在 `base_xfade_d ± max_shift` 内,同时不超过相邻两镜头时长的一半(与
    `assemble_longvideo` 现有的 xfade_d 上限规则一致)。

    没有节拍数据(`beats` 为空)→ 原样返回 `[base_xfade_d] * (N-1)`,退化为
    未对齐前的统一重叠时长,不报错。
    """
    n = len(durations)
    if n < 2:
        return []
    if not beats:
        return [base_xfade_d] * (n - 1)

    xfade_ds: list[float] = []
    merged = durations[0]
    for i in range(1, n):
        natural_cut = merged
        nearest = min(beats, key=lambda b: abs(b - natural_cut))
        shift = nearest - natural_cut
        d = base_xfade_d - shift
        d = max(base_xfade_d - max_shift, min(base_xfade_d + max_shift, d))
        d = max(0.05, min(d, durations[i - 1] / 2, durations[i] / 2))
        xfade_ds.append(d)
        merged = merged + durations[i] - d
    return xfade_ds


# ---------------------------------------------------------------- beat-grid fit
# Video-director residual (2026-10-31 recheck item 8): detection
# plus snapping alone cannot see a grid that drifts. The fit below
# is the missing half -- a least-squares grid over the detected
# beats, a half/double-tempo ambiguity test, a residual bar, and
# a refit after rendering. All pure functions, no new dependency.

# Residual bar, kept at the upstream value and NOT widened: 15 ms
# is the bar the source method calibrates against, and widening
# it would hide exactly the failure it exists to catch (a ~2%
# tempo error, or a grid that slipped by two beats). The bar is
# reported with every fit, so a caller that needs a looser bar
# for a named reason can pass its own tolerance explicitly.
RESIDUAL_TOLERANCE_SEC = 0.015
# Cut error bar: a cut must land within 3 frames of a beat, at the
# fps the caller is actually measuring at. This is a different
# instrument from the defect scan's 0.5 s cut tolerance (which
# compares cuts sampled at up to 8 fps in final_qc): both are
# reported in their own units, and neither is silently converted
# into the other.
CUT_TOLERANCE_FRAMES = 3


def _least_squares_grid(beats: list[float]) -> dict[str, Any]:
    """Least-squares fit t = t0 + period * index over sorted beats."""
    ordered = sorted(float(b) for b in beats)
    n = len(ordered)
    if n < 2:
        return {
            "beat_count": n, "t0_sec": ordered[0] if ordered else None,
            "period_sec": None, "bpm": None, "residuals_sec": [],
            "rms_residual_sec": None, "max_abs_residual_sec": None,
        }
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_t = sum(ordered) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    period = sum((x - mean_x) * (t - mean_t) for x, t in zip(xs, ordered)) / denom
    t0 = mean_t - period * mean_x
    residuals = [t - (t0 + period * x) for x, t in zip(xs, ordered)]
    rms = (sum(r * r for r in residuals) / n) ** 0.5
    return {
        "beat_count": n,
        "t0_sec": round(t0, 4),
        "period_sec": round(period, 4) if period > 0 else None,
        "bpm": round(60.0 / period, 2) if period > 0 else None,
        "residuals_sec": [round(r, 4) for r in residuals],
        "rms_residual_sec": round(rms, 4),
        "max_abs_residual_sec": round(max(abs(r) for r in residuals), 4),
    }


def _grid_rms(beats: list[float], t0: float, period: float) -> float:
    """RMS distance of beats to the nearest grid point of (t0, period)."""
    if period <= 0:
        return float("inf")
    sq = 0.0
    for t in beats:
        k = round((t - t0) / period)
        sq += (t - (t0 + k * period)) ** 2
    return (sq / len(beats)) ** 0.5


def fit_beat_grid(
    beats: list[float],
    *,
    residual_tolerance_sec: float = RESIDUAL_TOLERANCE_SEC,
) -> dict[str, Any]:
    """Fit a beat grid and test it for tempo ambiguity and drift.

    Returns the least-squares fit (``t0_sec``, ``period_sec``,
    ``bpm``, residuals), ``within_tolerance`` against the
    +/-15 ms residual bar (kept, not widened -- see the note
    above the constant), and a half/double-tempo check: if the
    beats fit a half-period or double-period grid at least
    twice as well *and* inside the same bar, the tempo is
    ambiguous and the fit says which alternative won. Gaps
    wider than 1.5 periods are reported as possible missed
    beats. Fewer than 2 beats is ``undetermined``, never a fit.
    """
    if not isinstance(beats, list) or any(
            not isinstance(b, (int, float)) or isinstance(b, bool) for b in beats):
        raise ValueError("fit_beat_grid: beats must be a list of numbers")
    ordered = sorted(float(b) for b in beats)
    fit = _least_squares_grid(ordered)
    base: dict[str, Any] = {
        "capability": "assembly.beat_align",
        "check": "beat_grid_fit",
        "beats": ordered,
        "residual_tolerance_sec": float(residual_tolerance_sec),
        "tempo_ambiguity": None,
        "missed_beat_gaps": [],
    }
    if fit["period_sec"] is None:
        return {**base, **fit, "status": "undetermined",
                "within_tolerance": None,
                "reason": "fewer than 2 beats: no grid can be fitted"}
    period = fit["period_sec"]
    t0 = fit["t0_sec"]
    rms = fit["rms_residual_sec"]
    within = fit["max_abs_residual_sec"] <= float(residual_tolerance_sec)
    # Half/double-tempo: would the same beats fit a grid at half
    # or double the period at least twice as well, inside the bar?
    ambiguity = None
    for label, alt_period in (("half_tempo", period / 2.0), ("double_tempo", period * 2.0)):
        alt_rms = _grid_rms(ordered, t0, alt_period)
        if alt_rms <= float(residual_tolerance_sec) and alt_rms * 2.0 < rms:
            ambiguity = {"alternative": label, "period_sec": round(alt_period, 4),
                         "rms_residual_sec": round(alt_rms, 4),
                         "base_rms_residual_sec": rms}
            break
    gaps = []
    for i in range(len(ordered) - 1):
        gap = ordered[i + 1] - ordered[i]
        if gap > 1.5 * period:
            gaps.append({"after_beat": i, "gap_sec": round(gap, 4),
                         "periods": round(gap / period, 2)})
    return {
        **base, **fit,
        "status": "pass" if (within and ambiguity is None) else "fail",
        "within_tolerance": bool(within),
        "tempo_ambiguity": ambiguity,
        "missed_beat_gaps": gaps,
        "reason": (
            "grid fits within +/-15ms and no tempo ambiguity"
            if within and ambiguity is None else
            f"max residual {fit['max_abs_residual_sec']}s exceeds "
            f"+/-{float(residual_tolerance_sec)}s"
            if not within else
            f"tempo ambiguity: {ambiguity['alternative']} fits better"
        ),
    }


def refit_after_render(
    planned_beats: list[float],
    rendered_beats: list[float],
    *,
    residual_tolerance_sec: float = RESIDUAL_TOLERANCE_SEC,
) -> dict[str, Any]:
    """Re-fit the grid on rendered beats and compare with the plan.

    Both sides are fitted independently; the verdict is about
    *drift*: the rendered period must stay within +/-15 ms of
    the planned period (the same bar as the fit itself, applied
    to the period, not to single beats). A rendered side with
    fewer than 2 beats is undetermined, never a silent match.
    """
    plan_fit = fit_beat_grid(planned_beats, residual_tolerance_sec=residual_tolerance_sec)
    rendered_fit = fit_beat_grid(rendered_beats, residual_tolerance_sec=residual_tolerance_sec)
    if plan_fit["period_sec"] is None or rendered_fit["period_sec"] is None:
        return {
            "capability": "assembly.beat_align",
            "check": "beat_grid_refit",
            "status": "undetermined",
            "within_tolerance": None,
            "plan_fit": plan_fit,
            "rendered_fit": rendered_fit,
            "period_drift_sec": None,
            "bpm_drift_pct": None,
            "reason": "one side has fewer than 2 beats: no refit comparison is possible",
        }
    drift = abs(rendered_fit["period_sec"] - plan_fit["period_sec"])
    bpm_drift = abs(rendered_fit["bpm"] - plan_fit["bpm"]) / plan_fit["bpm"] * 100.0 \
        if plan_fit["bpm"] else None
    within = drift <= float(residual_tolerance_sec)
    return {
        "capability": "assembly.beat_align",
        "check": "beat_grid_refit",
        "status": "pass" if within else "fail",
        "within_tolerance": bool(within),
        "plan_fit": plan_fit,
        "rendered_fit": rendered_fit,
        "period_drift_sec": round(drift, 4),
        "bpm_drift_pct": round(bpm_drift, 2) if bpm_drift is not None else None,
        "reason": (
            f"rendered period drift {drift:.4f}s within +/-{float(residual_tolerance_sec)}s"
            if within else
            f"rendered period drift {drift:.4f}s exceeds +/-{float(residual_tolerance_sec)}s"
        ),
    }


def cut_errors(
    cut_times: list[float],
    beat_times: list[float],
    fps: float,
    *,
    tolerance_frames: int = CUT_TOLERANCE_FRAMES,
) -> dict[str, Any]:
    """Cut-to-beat error for each planned cut, in seconds and frames.

    A cut is within tolerance when its nearest beat is at most
    3 frames away *at the fps the caller measures at* -- the
    frame count, not the seconds, is the bar, because the same
    0.1 s is 3 frames at 30 fps and under 1 frame at 8 fps
    sampling. No beats at all is undetermined, never a pass.
    """
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or float(fps) <= 0:
        raise ValueError("cut_errors: fps must be a positive number")
    if not beat_times:
        return {
            "capability": "assembly.beat_align",
            "check": "cut_errors",
            "status": "undetermined",
            "within_tolerance": None,
            "tolerance_frames": int(tolerance_frames),
            "fps": float(fps),
            "cuts": [],
            "reason": "no beats supplied: cut error cannot be measured",
        }
    cuts = []
    for cut in cut_times:
        nearest = min(beat_times, key=lambda b: abs(float(b) - float(cut)))
        offset_sec = float(cut) - float(nearest)
        offset_frames = offset_sec * float(fps)
        cuts.append({
            "cut_sec": float(cut),
            "nearest_beat_sec": float(nearest),
            "offset_sec": round(offset_sec, 4),
            "offset_frames": round(offset_frames, 2),
            "within_tolerance": abs(offset_frames) <= int(tolerance_frames),
        })
    within = all(c["within_tolerance"] for c in cuts)
    return {
        "capability": "assembly.beat_align",
        "check": "cut_errors",
        "status": "pass" if within else "fail",
        "within_tolerance": bool(within),
        "tolerance_frames": int(tolerance_frames),
        "fps": float(fps),
        "cuts": cuts,
        "reason": (
            f"all {len(cuts)} cut(s) within {int(tolerance_frames)} frames of a beat"
            if within else
            f"{sum(1 for c in cuts if not c['within_tolerance'])} cut(s) beyond "
            f"{int(tolerance_frames)} frames of the nearest beat"
        ),
    }
