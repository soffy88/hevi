"""Tests for model.model_directory: listed is not verified."""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.model_directory import (
    call_model,
    config_hash,
    fee_notice,
    register_model,
    run_model_test,
)
from hevi.capabilities.registry import get


def _dir(tmp_path: Path) -> Path:
    return tmp_path / "model_directory.json"


def test_capability_registered() -> None:
    assert get("model.model_directory").name == "model.model_directory"


def test_registered_model_is_unverified_and_call_refused(tmp_path: Path) -> None:
    record = register_model(_dir(tmp_path), model_id="m1",
                            config={"size": "1K"})
    assert record["status"] == "unverified"
    assert record["verified_at"] is None
    with pytest.raises(CapabilityError, match="not verified"):
        call_model(_dir(tmp_path), model_id="m1", config={"size": "1K"})


def test_fee_notice_caller_price_and_not_provided(tmp_path: Path) -> None:
    notice = fee_notice(2.5, currency="USD")
    assert "费用由调用方提供" in notice
    assert "2.5" in notice
    missing = fee_notice(None)
    assert "费用未提供" in missing


def test_passing_test_records_time_result_hash_and_allows_call(tmp_path: Path) -> None:
    config = {"size": "1K", "steps": 20}
    record = run_model_test(_dir(tmp_path), model_id="m1", config=config,
                        unit_price_caller=2.5, result="pass")
    assert record["status"] == "verified"
    assert record["verified_at"]
    assert record["result"] == "pass"
    assert record["config_hash"] == config_hash(config)
    assert record["fee_notice_shown_before_test"] is True
    assert "费用由调用方提供" in record["fee_notice"]
    allowed = call_model(_dir(tmp_path), model_id="m1", config=config)
    assert allowed["allowed"] is True
    assert allowed["verified_at"] == record["verified_at"]


def test_failed_test_leaves_model_unverified(tmp_path: Path) -> None:
    run_model_test(_dir(tmp_path), model_id="m1", config={"size": "1K"},
               result="fail")
    with pytest.raises(CapabilityError, match="not verified"):
        call_model(_dir(tmp_path), model_id="m1", config={"size": "1K"})


def test_config_change_without_retest_refused(tmp_path: Path) -> None:
    run_model_test(_dir(tmp_path), model_id="m1", config={"size": "1K"},
               result="pass")
    with pytest.raises(CapabilityError, match="configuration changed"):
        call_model(_dir(tmp_path), model_id="m1", config={"size": "2K"})
    # Retest on the new config restores the call.
    run_model_test(_dir(tmp_path), model_id="m1", config={"size": "2K"},
               result="pass")
    assert call_model(_dir(tmp_path), model_id="m1",
                      config={"size": "2K"})["allowed"] is True


def test_unknown_model_call_refused(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="not in directory"):
        call_model(_dir(tmp_path), model_id="ghost", config={})


def test_no_price_table_in_module() -> None:
    text = Path(__file__).resolve().parent  # tests dir, not module; see below
    import hevi.capabilities.model_directory as mod
    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "prices_usd" not in source
    assert "PRICE_TABLE" not in source
