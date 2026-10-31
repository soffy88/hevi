"""Tests for the Modal pricing registration (registration only, no
account, no payment, no API key, no network, record unverified;
per-unit GPU/CPU prices stay unverified)."""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.modal_pricing_registration import (
    MODAL_MODEL_ID,
    MODAL_PRICING_URL,
    modal_pricing_config,
    record_in_directory,
    validate_modal_config,
)
from hevi.capabilities.model_directory import call_model, get_record


def test_capability_registered() -> None:
    assert caps.get("model.modal_pricing_registration").name == "model.modal_pricing_registration"


def test_config_records_provider_and_source() -> None:
    config = modal_pricing_config()
    assert config["provider"] == "Modal"
    assert config["kind"] == "compute_provider"
    assert config["pricing_source"]["url"] == MODAL_PRICING_URL
    assert config["pricing_source"]["url"] == "https://modal.com/pricing"
    assert config["pricing_source"]["read_date"] == "2026-11-01"


def test_config_records_all_three_plans() -> None:
    plans = modal_pricing_config()["plans"]
    assert set(plans) == {"Starter", "Team", "Enterprise"}
    starter = plans["Starter"]
    assert starter["monthly_fee_usd"] == 0
    assert starter["free_credit_usd"] == 30
    assert starter["seats"] == 3
    assert starter["concurrency"] == {"containers": 100, "gpus": 10}
    assert starter["free_egress"] == "1 TiB"
    team = plans["Team"]
    assert team["monthly_fee_usd"] == 250
    assert team["free_credit_usd"] == 100
    assert team["seats"] == "unlimited"
    assert team["concurrency"] == {"containers": 5000, "gpus": 50}
    assert team["free_egress"] == "10 TiB"
    assert plans["Enterprise"]["monthly_fee_usd"] == "custom"


def test_config_records_billing_multipliers() -> None:
    billing = modal_pricing_config()["billing"]
    assert billing["per_second_billing"] is True
    assert billing["keep_alive_billed"] is True
    assert billing["keep_alive_seconds"] == 60
    assert billing["sandbox_multiplier"] == 3
    assert billing["non_preemptible_multiplier"] == 3
    assert billing["region_multiplier"] == {"min": 1.15, "max": 1.75}


def test_gpu_and_cpu_prices_stay_unverified() -> None:
    config = modal_pricing_config()
    assert config["gpu_prices"] == "unverified"
    assert config["cpu_prices"] == "unverified"


def test_config_no_account_no_payment_no_api() -> None:
    config = modal_pricing_config()
    assert config["account_registered"] is False
    assert config["payment_method_on_file"] is False
    assert config["api_connected"] is False
    assert config["api_key_stored"] is False
    assert config["status"] == "unverified"
    assert config["verified"] is False


def test_validate_accepts_registered_config() -> None:
    assert validate_modal_config(modal_pricing_config()) == modal_pricing_config()


def test_validate_refuses_invented_gpu_or_cpu_price() -> None:
    config = modal_pricing_config()
    config["gpu_prices"] = {"A100": 2.50}
    with pytest.raises(CapabilityError, match="must stay 'unverified'"):
        validate_modal_config(config)
    config = modal_pricing_config()
    config["cpu_prices"] = {"cpu": 0.10}
    with pytest.raises(CapabilityError, match="must stay 'unverified'"):
        validate_modal_config(config)
    config = modal_pricing_config()
    config["gpu_prices"] = "unverified"
    config["cpu_prices"] = 0.0
    with pytest.raises(CapabilityError, match="must stay 'unverified'"):
        validate_modal_config(config)


def test_validate_refuses_changed_multiplier_or_plan() -> None:
    config = modal_pricing_config()
    config["billing"]["sandbox_multiplier"] = 1
    with pytest.raises(CapabilityError, match="sandbox_multiplier must be 3"):
        validate_modal_config(config)
    config = modal_pricing_config()
    config["billing"]["non_preemptible_multiplier"] = 1
    with pytest.raises(CapabilityError, match="non_preemptible_multiplier"):
        validate_modal_config(config)
    config = modal_pricing_config()
    config["billing"]["region_multiplier"] = {"min": 1.0, "max": 1.0}
    with pytest.raises(CapabilityError, match="region_multiplier"):
        validate_modal_config(config)
    config = modal_pricing_config()
    config["billing"]["keep_alive_billed"] = False
    with pytest.raises(CapabilityError, match="keep-alive"):
        validate_modal_config(config)
    config = modal_pricing_config()
    config["plans"]["Starter"]["monthly_fee_usd"] = 10
    with pytest.raises(CapabilityError, match="Starter monthly_fee_usd"):
        validate_modal_config(config)
    config = modal_pricing_config()
    config["plans"]["Team"]["concurrency"] = {"containers": 100, "gpus": 10}
    with pytest.raises(CapabilityError, match="Team concurrency"):
        validate_modal_config(config)


def test_validate_refuses_account_payment_api_flags() -> None:
    for flag in ("account_registered", "payment_method_on_file",
                 "api_connected", "api_key_stored"):
        config = modal_pricing_config()
        config[flag] = True
        with pytest.raises(CapabilityError, match=flag):
            validate_modal_config(config)


def test_record_in_directory_leaves_unverified_and_call_refused(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "model_directory.json"
    records = record_in_directory(directory)
    assert set(records) == {MODAL_MODEL_ID}
    record = records[MODAL_MODEL_ID]
    assert record["status"] == "unverified"
    assert record["verified_at"] is None
    stored = get_record(directory, MODAL_MODEL_ID)
    assert stored["config_hash"] == record["config_hash"]
    with pytest.raises(CapabilityError, match="not verified"):
        call_model(directory, model_id=MODAL_MODEL_ID, config=record["config"])


def test_modal_record_is_separate_from_floyo_record() -> None:
    from hevi.capabilities.floyo_h3_registration import FLOYO_MODEL_ID

    assert MODAL_MODEL_ID != FLOYO_MODEL_ID
    assert modal_pricing_config()["provider"] == "Modal"
    assert modal_pricing_config()["provider"] != "Floyo"
