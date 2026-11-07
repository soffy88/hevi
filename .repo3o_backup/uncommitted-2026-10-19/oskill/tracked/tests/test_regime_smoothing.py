"""Tests for oskill.regime_smoothing."""

from datetime import datetime, timedelta

import pytest

from oskill.regime_smoothing import regime_smoothing
from oskill.types import RawRegimeState, SmoothingConfig

DEFAULT_CONFIG = SmoothingConfig(
    stress_states=["冰点", "恐慌", "狂热"],
    stress_min_days=1,
    normal_min_days=2,
)


def _build_history(states: list[str], start_days_ago: int = 5) -> list[RawRegimeState]:
    return [
        RawRegimeState(
            date=datetime(2026, 5, 20) + timedelta(days=i),
            state=s,
            confidence=0.8,
        )
        for i, s in enumerate(states)
    ]


class TestFirstComputation:
    def test_returns_latest_state(self) -> None:
        history = _build_history(["积极"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state=None)
        assert result.smoothed_state == "积极"
        assert result.state_changed is False
        assert result.days_in_current_state == 1


class TestSameStateContinuation:
    def test_no_switch(self) -> None:
        history = _build_history(["积极", "积极", "积极"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state="积极")
        assert result.smoothed_state == "积极"
        assert result.state_changed is False
        assert result.days_in_current_state == 3
        assert result.transitional_state is None


class TestNormalSwitch:
    def test_requires_2_days(self) -> None:
        history = _build_history(["积极", "积极", "积极", "分歧"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state="积极")
        assert result.smoothed_state == "积极"
        assert result.state_changed is False
        assert result.transitional_state == "分歧"
        assert result.transitional_days == 1

    def test_confirmed_at_2_days(self) -> None:
        history = _build_history(["积极", "积极", "分歧", "分歧"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state="积极")
        assert result.smoothed_state == "分歧"
        assert result.state_changed is True
        assert result.change_confirmed_at == history[-1].date
        assert result.transitional_state is None


class TestStressSwitch:
    def test_immediate_1day(self) -> None:
        history = _build_history(["积极", "积极", "积极", "恐慌"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state="积极")
        assert result.smoothed_state == "恐慌"
        assert result.state_changed is True

    def test_stress_to_stress(self) -> None:
        history = _build_history(["恐慌", "恐慌", "狂热"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state="恐慌")
        assert result.smoothed_state == "狂热"
        assert result.state_changed is True

    def test_normal_to_stress(self) -> None:
        history = _build_history(["谨慎", "谨慎", "狂热"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state="谨慎")
        assert result.smoothed_state == "狂热"
        assert result.state_changed is True


class TestTransitionalOscillation:
    def test_oscillation_resets(self) -> None:
        history = _build_history(["积极", "积极", "分歧", "积极", "分歧"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state="积极")
        assert result.smoothed_state == "积极"
        assert result.transitional_state == "分歧"
        assert result.transitional_days == 1


class TestEdgeCases:
    def test_empty_history_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            regime_smoothing([], DEFAULT_CONFIG, current_smoothed_state="积极")

    def test_single_entry_first_computation(self) -> None:
        history = _build_history(["冰点"])
        result = regime_smoothing(history, DEFAULT_CONFIG, current_smoothed_state=None)
        assert result.smoothed_state == "冰点"
        assert result.days_in_current_state == 1
