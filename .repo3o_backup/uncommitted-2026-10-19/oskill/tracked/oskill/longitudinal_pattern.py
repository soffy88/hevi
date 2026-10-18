"""Analyze longitudinal learning patterns across attempt history.

Pure deterministic algorithm — no LLM.
Computes trend, plateau detection, forgetting curves, and KC trajectory.

Version: oskill v3.21.0
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AttemptRecord:
    """A single attempt record for longitudinal analysis.

    Attributes
    ----------
    question_id : str
    kc_id : str
    correct : bool
    timestamp : float
        Unix timestamp of the attempt.
    response_time_s : float
        Time to answer in seconds.
    mastery_before : float | None
        Mastery at attempt time (if known).
    """

    question_id: str
    kc_id: str
    correct: bool
    timestamp: float
    response_time_s: float = 0.0
    mastery_before: float | None = None


@dataclass(frozen=True)
class KCTrajectory:
    """Longitudinal trajectory for a single KC.

    Attributes
    ----------
    kc_id : str
    accuracy_over_time : list[float]
        Rolling accuracy (newest last).
    trend : float
        Slope of accuracy trend (-1..1). Positive = improving.
    is_plateau : bool
        True if accuracy has been stable (|trend| < 0.02) for >= 5 sessions.
    is_forgetting : bool
        True if accuracy is declining after a prior peak.
    peak_accuracy : float
    current_accuracy : float
    attempt_count : int
    """

    kc_id: str
    accuracy_over_time: list[float]
    trend: float
    is_plateau: bool
    is_forgetting: bool
    peak_accuracy: float
    current_accuracy: float
    attempt_count: int


@dataclass(frozen=True)
class LongitudinalPatternResult:
    """Result of longitudinal pattern analysis.

    Attributes
    ----------
    kc_trajectories : dict[str, KCTrajectory]
        Per-KC trajectory analysis.
    improving_kcs : list[str]
        KCs with positive trend.
    plateau_kcs : list[str]
        KCs that have plateaued.
    forgetting_kcs : list[str]
        KCs showing forgetting decay.
    overall_trend : float
        Mean trend across all KCs.
    sessions_analyzed : int
    """

    kc_trajectories: dict[str, KCTrajectory]
    improving_kcs: list[str]
    plateau_kcs: list[str]
    forgetting_kcs: list[str]
    overall_trend: float
    sessions_analyzed: int


def _rolling_accuracy(records: list[AttemptRecord], window: int = 5) -> list[float]:
    """Compute rolling accuracy over chronological records."""
    if not records:
        return []
    sorted_r = sorted(records, key=lambda r: r.timestamp)
    accuracies: list[float] = []
    for i in range(len(sorted_r)):
        start = max(0, i - window + 1)
        window_recs = sorted_r[start : i + 1]
        acc = sum(1 for r in window_recs if r.correct) / len(window_recs)
        accuracies.append(acc)
    return accuracies


def _linear_trend(values: list[float]) -> float:
    """Compute linear trend slope via least squares (-1..1 normalised)."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    den = sum((x - mean_x) ** 2 for x in xs)
    if abs(den) < 1e-12:
        return 0.0
    return num / den


def _analyze_kc(kc_id: str, records: list[AttemptRecord]) -> KCTrajectory:
    """Analyze a single KC's trajectory."""
    accuracy = _rolling_accuracy(records)
    trend = _linear_trend(accuracy)
    peak = max(accuracy) if accuracy else 0.0
    current = accuracy[-1] if accuracy else 0.0

    is_plateau = len(accuracy) >= 5 and abs(trend) < 0.02
    is_forgetting = (
        len(accuracy) >= 3
        and current < peak - 0.1  # 10% below peak
        and trend < -0.01
    )

    return KCTrajectory(
        kc_id=kc_id,
        accuracy_over_time=accuracy,
        trend=trend,
        is_plateau=is_plateau,
        is_forgetting=is_forgetting,
        peak_accuracy=peak,
        current_accuracy=current,
        attempt_count=len(records),
    )


def longitudinal_pattern(
    records: Sequence[AttemptRecord],
    *,
    min_attempts_per_kc: int = 3,
) -> LongitudinalPatternResult:
    """Analyze longitudinal learning patterns.

    Parameters
    ----------
    records : Sequence[AttemptRecord]
        All attempt records (in any order — sorted internally by timestamp).
    min_attempts_per_kc : int
        Minimum attempts for a KC to be included in analysis.

    Returns
    -------
    LongitudinalPatternResult
    """
    if not records:
        return LongitudinalPatternResult(
            kc_trajectories={},
            improving_kcs=[],
            plateau_kcs=[],
            forgetting_kcs=[],
            overall_trend=0.0,
            sessions_analyzed=0,
        )

    # Group by KC
    by_kc: dict[str, list[AttemptRecord]] = {}
    for r in records:
        by_kc.setdefault(r.kc_id, []).append(r)

    trajectories: dict[str, KCTrajectory] = {}
    for kc_id, kc_records in by_kc.items():
        if len(kc_records) >= min_attempts_per_kc:
            trajectories[kc_id] = _analyze_kc(kc_id, kc_records)

    improving = [kc for kc, t in trajectories.items() if t.trend > 0.01 and not t.is_forgetting]
    plateau = [kc for kc, t in trajectories.items() if t.is_plateau]
    forgetting = [kc for kc, t in trajectories.items() if t.is_forgetting]

    overall_trend = (
        sum(t.trend for t in trajectories.values()) / len(trajectories) if trajectories else 0.0
    )

    # Count unique sessions (timestamps bucketed to same day)
    timestamps = sorted(set(r.timestamp for r in records))
    sessions = len(set(int(ts // 86400) for ts in timestamps)) if timestamps else 0

    return LongitudinalPatternResult(
        kc_trajectories=trajectories,
        improving_kcs=improving,
        plateau_kcs=plateau,
        forgetting_kcs=forgetting,
        overall_trend=overall_trend,
        sessions_analyzed=sessions,
    )
