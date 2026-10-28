"""Tests for pipeline.spend_ledger: freeze, settle/refund, failed items."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get
from hevi.capabilities.spend_ledger import (
    freeze_batch,
    generation_route,
    ledger_summary,
    record_failed_item,
    retrieve_failed_item,
    settle_batch,
)


def _board() -> list[dict]:
    return [
        {"shot_id": "S01", "visual": "主持人开场", "duration_sec": 5},
        {"shot_id": "S02", "visual": "产品特写", "duration_sec": 8},
    ]


def _ledger(tmp_path: Path) -> Path:
    return tmp_path / "spend_ledger.json"


def test_capability_registered() -> None:
    assert get("pipeline.spend_ledger").name == "pipeline.spend_ledger"


def test_freeze_records_estimate_from_caller_price(tmp_path: Path) -> None:
    batch = freeze_batch(
        _ledger(tmp_path), batch_id="b1", storyboard=_board(),
        confirmed=True, smoke_passed=True, batch_size=10, unit_price=2.5)
    assert batch["status"] == "frozen"
    assert batch["estimated_total"] == pytest.approx(25.0)
    assert batch["unit_price_caller_supplied"] == 2.5
    stored = json.loads(_ledger(tmp_path).read_text(encoding="utf-8"))
    assert stored["batches"][0]["batch_id"] == "b1"


def test_unconfirmed_batch_never_reaches_ledger(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="confirmed"):
        freeze_batch(
            _ledger(tmp_path), batch_id="b-no", storyboard=_board(),
            confirmed="true", smoke_passed=True, batch_size=5,
            unit_price=1.0)
    assert not _ledger(tmp_path).is_file()


def test_freeze_without_caller_price_refused(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="caller"):
        freeze_batch(
            _ledger(tmp_path), batch_id="b-noprice", storyboard=_board(),
            confirmed=True, smoke_passed=True, batch_size=5,
            unit_price=None)


def test_settle_refunds_overcharge_and_records_overrun(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    freeze_batch(ledger, batch_id="b1", storyboard=_board(),
                 confirmed=True, smoke_passed=True, batch_size=10,
                 unit_price=2.5)
    settled = settle_batch(ledger, batch_id="b1", actual_total=18.0)
    assert settled["status"] == "settled"
    assert settled["refund"] == pytest.approx(7.0)
    assert settled["overrun"] == 0.0
    freeze_batch(ledger, batch_id="b2", storyboard=_board(),
                 confirmed=True, smoke_passed=True, batch_size=2,
                 unit_price=2.5)
    settled2 = settle_batch(ledger, batch_id="b2", actual_total=9.0)
    assert settled2["refund"] == 0.0
    assert settled2["overrun"] == pytest.approx(4.0)
    summary = ledger_summary(ledger)
    assert summary["settled"] == 2
    assert summary["total_refund"] == pytest.approx(7.0)


def test_double_settle_refused(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    freeze_batch(ledger, batch_id="b1", storyboard=_board(),
                 confirmed=True, smoke_passed=True, batch_size=2,
                 unit_price=1.0)
    settle_batch(ledger, batch_id="b1", actual_total=2.0)
    with pytest.raises(CapabilityError, match="not 'frozen'"):
        settle_batch(ledger, batch_id="b1", actual_total=2.0)


def test_failed_item_returns_original_never_reroutes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    freeze_batch(ledger, batch_id="b1", storyboard=_board(),
                 confirmed=True, smoke_passed=True, batch_size=2,
                 unit_price=1.0)
    original = {"shot_id": "S01", "prompt": "主持人开场", "image": "s01.png"}
    item = record_failed_item(
        ledger, batch_id="b1", item_id="S01", original_input=original)
    assert item["status"] == "failed"
    retrieved = retrieve_failed_item(ledger, batch_id="b1", item_id="S01")
    assert retrieved["original_input"] == original
    assert retrieved["route"] == "return_original"
    assert retrieved["generate"] is False
    route = generation_route("failed")
    assert route["route"] == "return_original"
    assert route["generate"] is False
    assert generation_route("pending")["generate"] is True
