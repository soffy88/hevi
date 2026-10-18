"""oskill.regime_smoothing — Smooth raw regime states to prevent flapping."""

from __future__ import annotations

from datetime import datetime

from oskill.types import RawRegimeState, SmoothingConfig, SmoothingResult


def regime_smoothing(
    raw_state_history: list[RawRegimeState],
    smoothing_config: SmoothingConfig,
    current_smoothed_state: str | None = None,
) -> SmoothingResult:
    """Smooth raw regime classifications to prevent rapid back-and-forth switches.

    Args:
        raw_state_history: Recent raw regime states, chronological order.
        smoothing_config: Per-regime minimum duration config.
        current_smoothed_state: Current confirmed state, None for first computation.

    Returns:
        SmoothingResult with smoothed_state and transition metadata.
    """
    if not raw_state_history:
        raise ValueError("raw_state_history must be non-empty")

    if current_smoothed_state is None:
        return SmoothingResult(
            smoothed_state=raw_state_history[-1].state,
            state_changed=False,
            change_confirmed_at=raw_state_history[-1].date,
            days_in_current_state=1,
            transitional_state=None,
            transitional_days=0,
        )

    latest_state = raw_state_history[-1].state

    if latest_state == current_smoothed_state:
        return SmoothingResult(
            smoothed_state=current_smoothed_state,
            state_changed=False,
            change_confirmed_at=_find_state_start_date(raw_state_history, current_smoothed_state),
            days_in_current_state=_count_consecutive_from_end(
                raw_state_history, current_smoothed_state
            ),
            transitional_state=None,
            transitional_days=0,
        )

    transitional_days = _count_consecutive_from_end(raw_state_history, latest_state)

    if latest_state in smoothing_config.stress_states:
        required_days = smoothing_config.stress_min_days
    else:
        required_days = smoothing_config.normal_min_days

    if transitional_days >= required_days:
        return SmoothingResult(
            smoothed_state=latest_state,
            state_changed=True,
            change_confirmed_at=raw_state_history[-1].date,
            days_in_current_state=transitional_days,
            transitional_state=None,
            transitional_days=0,
        )

    return SmoothingResult(
        smoothed_state=current_smoothed_state,
        state_changed=False,
        change_confirmed_at=None,
        days_in_current_state=_count_consecutive_from_end(
            raw_state_history, current_smoothed_state
        ),
        transitional_state=latest_state,
        transitional_days=transitional_days,
    )


def _count_consecutive_from_end(history: list[RawRegimeState], state: str) -> int:
    count = 0
    for entry in reversed(history):
        if entry.state == state:
            count += 1
        else:
            break
    return count


def _find_state_start_date(history: list[RawRegimeState], state: str) -> datetime | None:
    for entry in history:
        if entry.state == state:
            return entry.date
    return None
