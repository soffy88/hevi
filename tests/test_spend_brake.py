"""Tests for pipeline.spend_brake: storyboard, confirmation, smoke."""

from __future__ import annotations

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.spend_brake import (
    authorize_spend,
    gate_spend,
    validate_storyboard,
)


def _board() -> list[dict]:
    return [
        {"shot_id": "S01", "visual": "主持人开场", "duration_sec": 5},
        {"shot_id": "S02", "visual": "产品特写", "duration_sec": 8},
    ]


def test_smoke_run_of_one_needs_storyboard_and_confirmation_only() -> None:
    approval = authorize_spend(
        _board(), confirmed=True, smoke_passed=False, batch_size=1)
    assert approval["approved"] is True
    assert approval["mode"] == "smoke"
    assert approval["rows_checked"] == 2


def test_batch_passes_with_confirmation_smoke_and_cost_total() -> None:
    approval = authorize_spend(
        _board(), confirmed=True, smoke_passed=True, batch_size=10,
        estimated_unit_cost=2.5)
    assert approval["mode"] == "batch"
    assert approval["estimated_total_cost"] == pytest.approx(25.0)


def test_batch_without_smoke_is_refused_and_names_smoke() -> None:
    with pytest.raises(CapabilityError, match="smoke"):
        authorize_spend(
            _board(), confirmed=True, smoke_passed=False, batch_size=10)
    decision = gate_spend(
        _board(), confirmed=True, smoke_passed=False, batch_size=10)
    assert decision["allowed"] is False
    assert any("smoke" in b for b in decision["blockers"])


def test_string_true_is_not_confirmation() -> None:
    with pytest.raises(CapabilityError, match="confirmed"):
        authorize_spend(
            _board(), confirmed="true", smoke_passed=True, batch_size=5)


def test_missing_confirmation_is_refused() -> None:
    with pytest.raises(CapabilityError, match="confirmed"):
        authorize_spend(
            _board(), confirmed=None, smoke_passed=True, batch_size=5)


def test_empty_storyboard_is_refused_and_names_storyboard() -> None:
    with pytest.raises(CapabilityError, match="storyboard"):
        authorize_spend(
            [], confirmed=True, smoke_passed=True, batch_size=5)


def test_broken_storyboard_row_names_the_row() -> None:
    board = [{"shot_id": "S01", "duration_sec": 5}]
    report = validate_storyboard(board)
    assert report["ok"] is False
    assert report["problems"][0]["missing_fields"] == ["visual"]
    with pytest.raises(CapabilityError, match="storyboard"):
        authorize_spend(
            board, confirmed=True, smoke_passed=True, batch_size=5)


def test_all_blockers_listed_at_once() -> None:
    decision = gate_spend(
        [], confirmed=False, smoke_passed=False, batch_size=10)
    joined = " ".join(decision["blockers"])
    assert "storyboard" in joined
    assert "confirmed" in joined
    assert "smoke" in joined
